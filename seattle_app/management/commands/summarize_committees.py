"""Generate "what this committee does and is working on" LLM summary cards for
the standing Seattle City Council committees via the Anthropic Message Batches
API.

Builds a structured context per committee (roster, recent meeting overviews,
bills handled) with ``seattle_app.services.committee_stats``, submits to Claude
with the ``COMMITTEE_SUMMARY_*`` prompt + JSON schema, and persists results to
``CommitteeSummary``.

Unlike bills/events, a committee's activity evolves, so this command refreshes
on change rather than once: a committee is targeted when it has no summary or
when its live ``content_hash`` (digest of roster + meetings + bills) differs
from the stored one. Only ~9 committees, so an unchanged cycle is a no-op.

The drain-then-submit state machine lives in ``BatchPipelineCommand``: one run
polls + persists any in-flight batch, then submits a fresh one. State is the
``BatchRun`` row, not a JSON file (issue #208).

Usage:
    python manage.py summarize_committees                 # stale/new committees
    python manage.py summarize_committees --dry-run       # no API calls
    python manage.py summarize_committees --force         # re-summarize all
    python manage.py summarize_committees --committee public-safety
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from django.db import transaction
from django.utils.text import slugify

from seattle_app.models import CommitteeSummary
from seattle_app.services.batch_pipeline import BatchPipelineCommand
from seattle_app.services.claude_service import (
    COMMITTEE_SUMMARY_OUTPUT_SCHEMA,
    COMMITTEE_SUMMARY_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)
from seattle_app.services.committee_stats import (
    build_committee_stats_context,
    committee_content_hash,
)

logger = logging.getLogger(__name__)

# Output is short (180-word cap, ~300 tokens); the headroom covers bounded
# thinking over the roster/meetings/bills context.
MAX_TOKENS_PER_REQUEST = 2048
THINKING_EFFORT = "medium"


def _encode_custom_id(org_id: str) -> str:
    """OCD Organization ids look like 'ocd-organization/<uuid>'; the prefix
    slash breaks Anthropic's custom_id regex, so flatten it."""
    return org_id.replace("ocd-organization/", "ocdorganization_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("ocdorganization_", "ocd-organization/")


class Command(BatchPipelineCommand):
    help = "Generate LLM committee summaries via the Anthropic Batch API."

    command_key = "summarize_committees"
    default_model_setting = "CLAUDE_COMMITTEE_SUMMARY_MODEL"

    def add_batch_arguments(self, parser):
        parser.add_argument(
            "--committee", default=None,
            help="Single committee to process — slug ('public-safety') or "
            "exact name. Implies a forced refresh of just that committee.",
        )

    def no_targets_message(self) -> str:
        return "All committee summaries are up to date. Done."

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #
    def get_targets(self, opts) -> list:
        from seattle_app.api_views import _committee_orgs

        orgs = list(_committee_orgs().order_by("name"))
        only = opts.get("committee")
        if only:
            orgs = [o for o in orgs if slugify(o.name) == only or o.name == only]
            return orgs  # explicit selection is always (re)processed
        if opts["force"]:
            return orgs

        # Otherwise: committees with no summary, or whose inputs changed.
        stored = dict(
            CommitteeSummary.objects.values_list("organization_id", "content_hash")
        )
        targets = []
        for org in orgs:
            live_hash = committee_content_hash(build_committee_stats_context(org))
            if stored.get(org.id) != live_hash:
                targets.append(org)
        return targets

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def build_requests(self, targets, model) -> list[dict]:
        requests = []
        for org in targets:
            ctx = build_committee_stats_context(org)
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": COMMITTEE_SUMMARY_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": self._build_input(ctx)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": COMMITTEE_SUMMARY_OUTPUT_SCHEMA,
                    },
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
                params["output_config"]["effort"] = THINKING_EFFORT
            requests.append({
                "custom_id": _encode_custom_id(org.id),
                "params": params,
            })
        return requests

    def describe_dry_run(self, targets, model) -> str:
        total_chars = sum(
            len(self._build_input(build_committee_stats_context(o))) for o in targets
        )
        return (
            f"[dry-run] Would submit {len(targets)} committee(s) with model {model}.\n"
            f"          Total input: {total_chars:,} chars "
            f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
            f"          Committees: {[o.name for o in targets]}"
        )

    @staticmethod
    def _build_input(ctx: dict) -> str:
        return (
            f"Committee snapshot:\n\n"
            f"{json.dumps(ctx, indent=2, default=str)}\n\n"
            "Write the committee summary per the system instructions."
        )

    # ------------------------------------------------------------------ #
    #  Persist                                                            #
    # ------------------------------------------------------------------ #
    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        from opencivicdata.core.models import Organization

        parsed = list(self.iter_json_results(results))
        org_ids = [_decode_custom_id(cid) for cid, _d, _m, _e in parsed]
        orgs_by_id = {o.id: o for o in Organization.objects.filter(id__in=org_ids)}

        success = 0
        errors: list[tuple[str, str]] = []
        for cid, data, model_version, err in parsed:
            org_id = _decode_custom_id(cid)
            if err:
                errors.append((org_id, err))
                continue
            summary = (data.get("summary") or "").strip()
            if not summary:
                errors.append((org_id, "empty summary in output"))
                continue
            org = orgs_by_id.get(org_id)
            if org is None:
                errors.append((org_id, "organization not in DB"))
                continue
            try:
                ctx = build_committee_stats_context(org)
                self._upsert_summary(
                    org=org,
                    summary_text=summary,
                    stats_snapshot=ctx,
                    content_hash=committee_content_hash(ctx),
                    model_version=model_version,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", org_id)
                errors.append((org_id, f"upsert failed: {e}"))
        return success, errors

    @staticmethod
    @transaction.atomic
    def _upsert_summary(*, org, summary_text: str, stats_snapshot: dict,
                        content_hash: str, model_version: str, batch_id: str) -> None:
        CommitteeSummary.objects.update_or_create(
            organization=org,
            defaults={
                "summary": summary_text,
                "stats_snapshot": stats_snapshot,
                "content_hash": content_hash,
                "model_version": model_version,
                "summary_batch_id": batch_id,
            },
        )
