"""Generate 2-3 paragraph LLM summary cards for current Seattle City
Council members via the Anthropic Message Batches API.

Builds a structured stats snapshot per rep (tenure, committees,
sponsorship portfolio, voting record, bio) using
``reps.stats.build_rep_stats_context``, submits to Claude with the
``REP_SUMMARY_*`` prompt + JSON schema in ``claude_service.py``, and
persists results to ``RepSummary``. Two-phase like
``summarize_legislation`` and ``tag_bill_issue_areas``: first
invocation submits, subsequent invocations poll + process.

Targets reps where ``councilmatic_core_person.is_current = TRUE``
joined to a Seattle City Council membership — the same source-of-
truth filter the rest of the app uses for "currently serving"
(``reps.services._query_current_council_members``). 9 reps as of
2026-05.

State lives in ``data/summarize_reps_state.json`` (gitignored).
Idempotent: reps that already have a ``RepSummary`` are excluded
unless ``--force``. The ``RepSummary.summary_batch_id`` records
which batch each row came from for future filtering.

Usage:
    python manage.py summarize_reps                     # all current reps
    python manage.py summarize_reps --dry-run           # no API calls
    python manage.py summarize_reps --force             # re-summarize all
    python manage.py summarize_reps --person "Joy Hollingsworth"
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Iterable, Optional

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from opencivicdata.core.models import Person

from reps.models import RepSummary
from reps.stats import build_rep_stats_context
from seattle_app.services.claude_service import (
    REP_SUMMARY_OUTPUT_SCHEMA,
    REP_SUMMARY_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/summarize_reps_state.json"

# Per-request budgets. Output is short (250-word cap, ~400 tokens)
# but we want generous thinking room for the synthesis step where
# the model balances structured stats against bio context.
MAX_TOKENS_PER_REQUEST = 4096
THINKING_BUDGET_TOKENS = 2048


def _encode_custom_id(person_id: str) -> str:
    """OCD Person ids are URL-safe ulids/uuids; the dashes Anthropic
    accepts but the leading 'ocd-person/' prefix breaks the regex."""
    return person_id.replace("ocd-person/", "ocdperson_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("ocdperson_", "ocd-person/")


def _current_member_ids() -> list[str]:
    """OCD Person ids for currently serving council members. Mirrors
    the SQL filter in ``reps.services._query_current_council_members``
    so this command targets the same set as the rep-detail page."""
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


class Command(BaseCommand):
    help = "Generate LLM rep summaries via the Anthropic Batch API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be submitted without calling the API.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-summarize reps that already have a RepSummary.",
        )
        parser.add_argument(
            "--person",
            default=None,
            help="Single Person name to process (e.g. 'Joy Hollingsworth').",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override settings.CLAUDE_REP_SUMMARY_MODEL for this run.",
        )
        parser.add_argument(
            "--state-file",
            default=DEFAULT_STATE_PATH,
            help=f"Path to the persisted batch state (default: {DEFAULT_STATE_PATH}).",
        )

    def handle(self, *args, **opts):
        state_path = Path(opts["state_file"])
        state = self._load_state(state_path)

        if not settings.ANTHROPIC_API_KEY:
            raise CommandError(
                "ANTHROPIC_API_KEY is not configured. Set it in your environment "
                "or Django settings before running."
            )
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        if state.get("batch_id") and not state.get("processed"):
            self._poll_and_maybe_process(client, state, state_path)
            return

        people = self._target_people(force=opts["force"], person_name=opts["person"])
        if not people:
            self.stdout.write(self.style.SUCCESS("No reps need summaries. Done."))
            return

        model = opts["model"] or settings.CLAUDE_REP_SUMMARY_MODEL

        # Build stats once up-front so dry-run reflects the same input
        # the real run will submit (and so we can size it).
        contexts = [(p, build_rep_stats_context(p)) for p in people]

        if opts["dry_run"]:
            total_chars = sum(len(self._build_input(ctx)) for _, ctx in contexts)
            self.stdout.write(
                f"[dry-run] Would submit {len(people)} rep(s) with model {model}.\n"
                f"          Total input: {total_chars:,} chars "
                f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
                f"          Reps: {[p.name for p in people]}"
            )
            return

        self.stdout.write(
            f"Submitting batch: {len(people)} rep(s), model {model}."
        )
        batch = self._submit_batch(client, contexts, model)
        state.update({
            "batch_id": batch.id,
            "submitted_at": datetime.now(dt_timezone.utc).isoformat(),
            "rep_count": len(people),
            "model": model,
            "processed": False,
        })
        for k in ("processed_at", "success_count", "error_count", "errors"):
            state.pop(k, None)
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Submitted batch {batch.id} with {len(people)} rep(s).\n"
            f"Re-run this command to poll status and write summaries to the DB."
        ))

    # ------------------------------------------------------------------ #
    #  Phase 1 — poll + process                                           #
    # ------------------------------------------------------------------ #

    def _poll_and_maybe_process(self, client, state: dict, state_path: Path):
        batch_id = state["batch_id"]
        self.stdout.write(f"Polling batch {batch_id}…")
        batch = client.messages.batches.retrieve(batch_id)
        status = getattr(batch, "processing_status", None)
        self.stdout.write(f"  processing_status: {status}")

        counts = getattr(batch, "request_counts", None)
        if counts is not None:
            self.stdout.write(
                f"  counts: processing={getattr(counts, 'processing', '?')} "
                f"succeeded={getattr(counts, 'succeeded', '?')} "
                f"errored={getattr(counts, 'errored', '?')} "
                f"canceled={getattr(counts, 'canceled', '?')} "
                f"expired={getattr(counts, 'expired', '?')}"
            )

        if status != "ended":
            self.stdout.write(self.style.NOTICE(
                "Batch not yet ended. Re-run later to retry polling."
            ))
            return

        self._process_results(client, batch_id, state, state_path)

    def _process_results(
        self, client, batch_id: str, state: dict, state_path: Path
    ):
        success = 0
        errors: list[tuple[str, str]] = []

        results = list(client.messages.batches.results(batch_id))
        person_ids = [_decode_custom_id(r.custom_id) for r in results]
        people_by_id = {p.id: p for p in Person.objects.filter(id__in=person_ids)}

        for result in results:
            person_id = _decode_custom_id(result.custom_id)
            kind = result.result.type
            if kind != "succeeded":
                errors.append((person_id, kind))
                continue

            message = result.result.message
            text = self._extract_text(message)
            if not text:
                block_types = sorted({getattr(b, "type", "?") for b in message.content})
                stop_reason = getattr(message, "stop_reason", "?")
                errors.append((
                    person_id,
                    f"empty text (stop_reason={stop_reason} blocks={block_types})",
                ))
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                errors.append((person_id, f"non-JSON output: {e}"))
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
                    model_version=message.model,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", person_id)
                errors.append((person_id, f"upsert failed: {e}"))

        state["processed"] = True
        state["processed_at"] = datetime.now(dt_timezone.utc).isoformat()
        state["success_count"] = success
        state["error_count"] = len(errors)
        if errors:
            state["errors"] = errors[:50]
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Processed batch {batch_id}: {success} summarized, "
            f"{len(errors)} errored."
        ))
        if errors:
            self.stdout.write(self.style.WARNING(f"First errors: {errors[:5]}"))

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

    # ------------------------------------------------------------------ #
    #  Phase 2 — submit                                                   #
    # ------------------------------------------------------------------ #

    def _target_people(
        self,
        *,
        force: bool,
        person_name: Optional[str],
    ) -> list[Person]:
        person_ids = _current_member_ids()
        qs = Person.objects.filter(id__in=person_ids).order_by("name")
        if person_name:
            qs = qs.filter(name=person_name)
        elif not force:
            qs = qs.filter(rep_summary__isnull=True)
        return list(qs)

    def _submit_batch(
        self, client, contexts: Iterable[tuple[Person, dict]], model: str
    ):
        requests = []
        for person, ctx in contexts:
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
                    }
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": THINKING_BUDGET_TOKENS,
                }
            requests.append({
                "custom_id": _encode_custom_id(person.id),
                "params": params,
            })
        return client.messages.batches.create(requests=requests)

    @staticmethod
    def _build_input(ctx: dict) -> str:
        # Pretty-printed JSON makes the prompt easier for the model to
        # parse than a flattened key/value blob, and keeps the per-rep
        # input under ~4 KB for all 9 current reps.
        return (
            f"Councilmember stats snapshot:\n\n"
            f"{json.dumps(ctx, indent=2, default=str)}\n\n"
            "Write a 2-3 paragraph summary per the system instructions."
        )

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_text(message) -> str:
        for block in message.content:
            if block.type == "text":
                return block.text
        return ""

    @staticmethod
    def _load_state(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"Could not parse state file {path}: {e}") from e

    @staticmethod
    def _save_state(state: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
