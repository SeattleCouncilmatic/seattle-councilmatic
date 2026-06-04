"""Bulk-summarize bills via the Anthropic Message Batches API.

For each ``Bill`` with extracted text and no ``LegislationSummary`` (unless
``--force``), submits the staff Summary + Fiscal Note + full text and persists a
structured ``{summary, impact_analysis, key_changes}`` result, resolving each
key change's affected SMC sections into the ``affected_sections`` M2M.

The drain-then-submit state machine lives in ``BatchPipelineCommand``: one run
polls + persists any in-flight batch, then submits a fresh one. State is the
``BatchRun`` row, not a JSON file (issue #208).

Usage:
    python manage.py summarize_legislation
    python manage.py summarize_legislation --dry-run
    python manage.py summarize_legislation --force --limit 5
    python manage.py summarize_legislation --bill 'CB 121177'
    python manage.py summarize_legislation --model claude-opus-4-8 --limit 5
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from django.db import transaction

from councilmatic_core.models import Bill

from seattle_app.models import LegislationSummary, MunicipalCodeSection
from seattle_app.services.batch_pipeline import BatchPipelineCommand
from seattle_app.services.claude_service import (
    LEGISLATION_OUTPUT_SCHEMA,
    LEGISLATION_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

# Per-request token ceiling. Thinking is bounded via ``output_config.effort``
# ("medium" gives ample synthesis room while leaving headroom for the structured
# JSON output: summary + impact_analysis + multi-item key_changes).
MAX_TOKENS_PER_REQUEST = 16384
THINKING_EFFORT = "medium"

# Hard cap on input chars per bill. Opus has a 200k-token context; at ~4
# chars/token that's ~800k chars, but we need room for the system prompt, the
# thinking budget, and the output. Truncate the tail of BillText.text past 600k
# chars — the staff Summary is concatenated first, so any oversized bill keeps
# the most useful part.
MAX_INPUT_CHARS = 600_000

# Pull every 2- or 3-part SMC-shaped section number out of a free-form
# affected_section field, so multi-cite values like "1.04.020, 1.04.070" or
# "23.32.040 and 23.32.060" each resolve to their own MunicipalCodeSection row.
_SMC_CITE_RE = re.compile(r"\d+[A-Z]?\.\d+[A-Z]?(?:\.\d+[A-Z]?)?")


def _encode_custom_id(identifier: str) -> str:
    """Encode a bill identifier for Anthropic's custom_id pattern.

    Bill identifiers are like "CB 121177" / "Res 32168" / "Ord 12345".
    Anthropic requires custom_id to match ``^[a-zA-Z0-9_-]{1,64}$``, so spaces
    aren't allowed. Bill identifiers don't contain underscores in practice, so
    the swap is bidirectional."""
    return identifier.replace(" ", "_")


def _decode_custom_id(custom_id: str) -> str:
    """Reverse of ``_encode_custom_id``."""
    return custom_id.replace("_", " ")


class Command(BatchPipelineCommand):
    help = "Bulk-summarize bills via the Anthropic Message Batches API."

    command_key = "summarize_legislation"
    default_model_setting = "CLAUDE_LEGISLATION_MODEL"

    def add_batch_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Max number of bills to include in this batch (testing).",
        )
        parser.add_argument(
            "--bill", default=None,
            help="Single bill identifier to process (e.g. 'CB 121177').",
        )

    def no_targets_message(self) -> str:
        return "No bills need summaries. Done."

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #
    def get_targets(self, opts) -> list:
        return self._target_bills(
            force=opts["force"],
            limit=opts["limit"],
            bill_identifier=opts["bill"],
        )

    def _target_bills(
        self,
        *,
        force: bool,
        limit: Optional[int],
        bill_identifier: Optional[str],
    ) -> list:
        # Only bills with a non-empty BillText are candidates.
        qs = (
            Bill.objects
            .filter(extracted_text__isnull=False)
            .exclude(extracted_text__text="")
            .select_related("extracted_text")
            .order_by("-created_at")
        )
        if bill_identifier:
            qs = qs.filter(identifier=bill_identifier)
        elif not force:
            qs = qs.filter(llm_summary__isnull=True)
        if limit is not None:
            qs = qs[:limit]
        return list(qs)

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def build_requests(self, targets, model) -> list[dict]:
        requests = []
        for bill in targets:
            text = bill.extracted_text.text
            if len(text) > MAX_INPUT_CHARS:
                # Tail-truncate. BillText concatenates Summary first, so the
                # most-useful content is at the head.
                text = text[:MAX_INPUT_CHARS] + "\n\n[…truncated]"

            user_content = (
                f"Legislation: {bill.identifier}\n"
                f"Title: {getattr(bill, 'title', '') or ''}\n\n"
                f"Full text of the legislation (extracted from attachments):\n{text}"
            )
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": LEGISLATION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": user_content}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": LEGISLATION_OUTPUT_SCHEMA,
                    },
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
                params["output_config"]["effort"] = THINKING_EFFORT
            requests.append({
                "custom_id": _encode_custom_id(bill.identifier),
                "params": params,
            })
        return requests

    def describe_dry_run(self, targets, model) -> str:
        total_chars = sum(len(b.extracted_text.text) for b in targets)
        return (
            f"[dry-run] Would submit {len(targets)} bill(s) with model {model}.\n"
            f"          Total input: {total_chars:,} chars "
            f"(~{total_chars // 4:,} tokens)\n"
            f"          First 5: {[b.identifier for b in targets[:5]]}"
        )

    # ------------------------------------------------------------------ #
    #  Persist                                                            #
    # ------------------------------------------------------------------ #
    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        parsed = list(self.iter_json_results(results))
        identifiers = [_decode_custom_id(cid) for cid, _d, _m, _e in parsed]
        bills_by_id = {
            b.identifier: b
            for b in Bill.objects.filter(identifier__in=identifiers)
        }

        success = 0
        errors: list[tuple[str, str]] = []
        for cid, data, model_version, err in parsed:
            identifier = _decode_custom_id(cid)
            if err:
                errors.append((identifier, err))
                continue
            bill = bills_by_id.get(identifier)
            if bill is None:
                errors.append((identifier, "bill not in DB"))
                continue
            try:
                self._upsert_summary(
                    bill=bill,
                    data=data,
                    model_version=model_version,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", identifier)
                errors.append((identifier, f"upsert failed: {e}"))
        return success, errors

    @staticmethod
    @transaction.atomic
    def _upsert_summary(*, bill, data: dict, model_version: str, batch_id: str) -> None:
        """Create or update the LegislationSummary row and resolve
        affected_sections from the LLM-reported section numbers in each
        key_change."""
        summary, _ = LegislationSummary.objects.update_or_create(
            bill=bill,
            defaults={
                "summary": data.get("summary", "") or "",
                "impact_analysis": data.get("impact_analysis", "") or "",
                "key_changes": data.get("key_changes", []) or [],
                "model_version": model_version,
                "summary_batch_id": batch_id,
            },
        )
        # Resolve `key_changes[].affected_section` to MunicipalCodeSection rows.
        # The LLM sometimes emits a single cite, a comma-separated list, or an
        # "and" connector — pull every 2- or 3-part SMC-shaped cite via regex so
        # each is resolved individually. Section numbers that don't match any
        # row (typos, deprecated, non-SMC) are silently dropped; the JSON still
        # records what the LLM thought.
        section_numbers: set[str] = set()
        for kc in (data.get("key_changes") or []):
            section_numbers.update(_SMC_CITE_RE.findall(kc.get("affected_section") or ""))
        if section_numbers:
            sections = MunicipalCodeSection.objects.filter(
                section_number__in=section_numbers
            )
            summary.affected_sections.set(sections)
        else:
            summary.affected_sections.clear()
