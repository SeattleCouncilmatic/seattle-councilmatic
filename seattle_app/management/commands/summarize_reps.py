"""Generate 2-3 paragraph LLM summary cards for current Seattle City Council
members via the Anthropic Message Batches API.

Builds a structured stats snapshot per rep (tenure, committees, sponsorship
portfolio, voting record, bio) using ``reps.stats.build_rep_stats_context``,
submits to Claude with the ``REP_SUMMARY_*`` prompt + JSON schema, and persists
results to ``RepSummary``.

Targets reps where ``councilmatic_core_person.is_current = TRUE`` joined to a
Seattle City Council membership — the same source-of-truth filter the rest of
the app uses for "currently serving".

The drain-then-submit state machine lives in ``BatchPipelineCommand``: one run
polls + persists any in-flight batch, then submits a fresh one. State is the
``BatchRun`` row, not a JSON file (issue #208). Idempotent: reps that already
have a ``RepSummary`` are excluded unless ``--force``.

Usage:
    python manage.py summarize_reps                     # all current reps
    python manage.py summarize_reps --dry-run           # no API calls
    python manage.py summarize_reps --force             # re-summarize all
    python manage.py summarize_reps --person "Joy Hollingsworth"
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from django.db import connection, transaction

from opencivicdata.core.models import Person

from reps.models import RepSummary
from reps.stats import build_rep_stats_context
from seattle_app.services.batch_pipeline import BatchPipelineCommand
from seattle_app.services.claude_service import (
    REP_SUMMARY_OUTPUT_SCHEMA,
    REP_SUMMARY_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

# Per-request token ceiling. Output is short (250-word cap, ~400 tokens) but the
# synthesis step balances structured stats against bio context — thinking is
# bounded via ``output_config.effort``.
MAX_TOKENS_PER_REQUEST = 4096
THINKING_EFFORT = "medium"


def _encode_custom_id(person_id: str) -> str:
    """OCD Person ids are URL-safe ulids/uuids; the dashes Anthropic accepts but
    the leading 'ocd-person/' prefix breaks the regex."""
    return person_id.replace("ocd-person/", "ocdperson_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("ocdperson_", "ocd-person/")


def _current_member_ids() -> list[str]:
    """OCD Person ids for currently serving council members. Mirrors the SQL
    filter in ``reps.services._query_current_council_members`` so this command
    targets the same set as the rep-detail page."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT p.id
            FROM opencivicdata_person p
            INNER JOIN councilmatic_core_person cp ON cp.person_id = p.id
            INNER JOIN opencivicdata_membership m ON m.person_id = p.id
            INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
            WHERE o.name = 'Seattle City Council' AND cp.is_current = TRUE
            ORDER BY p.id
            """
        )
        return [row[0] for row in cursor.fetchall()]


class Command(BatchPipelineCommand):
    help = "Generate LLM rep summaries via the Anthropic Batch API."

    command_key = "summarize_reps"
    default_model_setting = "CLAUDE_REP_SUMMARY_MODEL"

    def add_batch_arguments(self, parser):
        parser.add_argument(
            "--person", default=None,
            help="Single Person name to process (e.g. 'Joy Hollingsworth').",
        )

    def no_targets_message(self) -> str:
        return "No reps need summaries. Done."

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #
    def get_targets(self, opts) -> list:
        return self._target_people(force=opts["force"], person_name=opts["person"])

    def _target_people(self, *, force: bool, person_name: Optional[str]) -> list:
        person_ids = _current_member_ids()
        qs = Person.objects.filter(id__in=person_ids).order_by("name")
        if person_name:
            qs = qs.filter(name=person_name)
        elif not force:
            qs = qs.filter(rep_summary__isnull=True)
        return list(qs)

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def build_requests(self, targets, model) -> list[dict]:
        requests = []
        for person in targets:
            ctx = build_rep_stats_context(person)
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": REP_SUMMARY_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": self._build_input(ctx)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": REP_SUMMARY_OUTPUT_SCHEMA,
                    },
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
                params["output_config"]["effort"] = THINKING_EFFORT
            requests.append({
                "custom_id": _encode_custom_id(person.id),
                "params": params,
            })
        return requests

    def describe_dry_run(self, targets, model) -> str:
        total_chars = sum(
            len(self._build_input(build_rep_stats_context(p))) for p in targets
        )
        return (
            f"[dry-run] Would submit {len(targets)} rep(s) with model {model}.\n"
            f"          Total input: {total_chars:,} chars "
            f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
            f"          Reps: {[p.name for p in targets]}"
        )

    @staticmethod
    def _build_input(ctx: dict) -> str:
        # Pretty-printed JSON makes the prompt easier for the model to parse than
        # a flattened key/value blob, and keeps the per-rep input under ~4 KB.
        return (
            f"Councilmember stats snapshot:\n\n"
            f"{json.dumps(ctx, indent=2, default=str)}\n\n"
            "Write a 2-3 paragraph summary per the system instructions."
        )

    # ------------------------------------------------------------------ #
    #  Persist                                                            #
    # ------------------------------------------------------------------ #
    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        parsed = list(self.iter_json_results(results))
        person_ids = [_decode_custom_id(cid) for cid, _d, _m, _e in parsed]
        people_by_id = {p.id: p for p in Person.objects.filter(id__in=person_ids)}

        success = 0
        errors: list[tuple[str, str]] = []
        for cid, data, model_version, err in parsed:
            person_id = _decode_custom_id(cid)
            if err:
                errors.append((person_id, err))
                continue
            summary = (data.get("summary") or "").strip()
            if not summary:
                errors.append((person_id, "empty summary in output"))
                continue
            person = people_by_id.get(person_id)
            if person is None:
                errors.append((person_id, "person not in DB"))
                continue
            try:
                self._upsert_summary(
                    person=person,
                    summary_text=summary,
                    stats_snapshot=build_rep_stats_context(person),
                    model_version=model_version,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", person_id)
                errors.append((person_id, f"upsert failed: {e}"))
        return success, errors

    @staticmethod
    @transaction.atomic
    def _upsert_summary(*, person, summary_text: str, stats_snapshot: dict,
                        model_version: str, batch_id: str) -> None:
        RepSummary.objects.update_or_create(
            person=person,
            defaults={
                "summary": summary_text,
                "stats_snapshot": stats_snapshot,
                "model_version": model_version,
                "summary_batch_id": batch_id,
            },
        )
