"""Bulk-summarize bills via the Anthropic Message Batches API.

Reads from ``BillText`` (populated by the ``extract_bill_text`` command),
submits each bill's text to Opus 4.7 with the structured-JSON output
config from ``claude_service.py``, and persists results to
``LegislationSummary``. Two-phase like ``summarize_smc_sections``: first
invocation submits, subsequent invocations poll + process.

Bills without ``BillText`` (extraction failed entirely) are skipped —
the audit trail in ``BillText.source_documents`` already explains why
each one was. Bills with empty ``BillText.text`` are also skipped (every
candidate document was over-cap or malformed).

State lives in ``data/summarize_legislation_state.json`` (gitignored —
batch IDs are per-environment). Idempotent: bills that already have a
``LegislationSummary`` are excluded unless ``--force``. The
``LegislationSummary.summary_batch_id`` field records which batch each
row came from so future ops can filter by batch.

Usage:
    python manage.py summarize_legislation
    python manage.py summarize_legislation --limit 5      # smoke run
    python manage.py summarize_legislation --force        # re-summarize all
    python manage.py summarize_legislation --dry-run      # no API calls
    python manage.py summarize_legislation --bill "CB 121177"
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
from django.db import transaction
from django.utils import timezone

from councilmatic_core.models import Bill

from seattle_app.models import BillText, LegislationSummary, MunicipalCodeSection
from seattle_app.services.claude_service import (
    LEGISLATION_OUTPUT_SCHEMA,
    LEGISLATION_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/summarize_legislation_state.json"

# Per-request token + thinking ceilings. Mirrors the explicit-budget
# pattern that worked for the SMC bulk summarizer (PR #70): max_tokens
# accommodates THINKING_BUDGET tokens of thinking plus generous output
# room. The structured JSON output for legislation is more verbose
# than a section summary because it has summary + impact_analysis +
# multi-item key_changes — give it more output room.
MAX_TOKENS_PER_REQUEST = 16384
THINKING_BUDGET_TOKENS = 8192

# Hard cap on input chars per bill. Opus 4.7 has a 200k-token context;
# at ~4 chars/token that's ~800k chars, but we need room for the system
# prompt (~500 tokens), thinking (8192), and output (~8k). Truncate the
# tail of BillText.text past 600k chars — the staff Summary is
# concatenated first, so any oversized bill keeps the most useful part.
MAX_INPUT_CHARS = 600_000


def _encode_custom_id(identifier: str) -> str:
    """Encode a bill identifier for Anthropic's custom_id pattern.

    Bill identifiers are like "CB 121177" / "Res 32168" / "Ord 12345".
    Anthropic requires custom_id to match `^[a-zA-Z0-9_-]{1,64}$`, so
    spaces aren't allowed. Bill identifiers don't contain underscores
    in practice, so the swap is bidirectional.
    """
    return identifier.replace(" ", "_")


def _decode_custom_id(custom_id: str) -> str:
    """Reverse of `_encode_custom_id`."""
    return custom_id.replace("_", " ")


class Command(BaseCommand):
    help = "Bulk-summarize bills via the Anthropic Message Batches API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of bills to include in this batch (testing).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-summarize bills that already have a LegislationSummary.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be submitted without calling the API.",
        )
        parser.add_argument(
            "--bill",
            default=None,
            help="Single bill identifier to process (e.g. 'CB 121177').",
        )
        parser.add_argument(
            "--model",
            default=None,
            help=(
                "Override settings.CLAUDE_LEGISLATION_MODEL for this run "
                "(useful for A/B-ing Sonnet vs Opus on a small batch)."
            ),
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

        # Phase 1: poll any in-flight batch.
        if state.get("batch_id") and not state.get("processed"):
            self._poll_and_maybe_process(client, state, state_path)
            return

        # Phase 2: gather candidates and submit.
        bills = self._target_bills(
            force=opts["force"],
            limit=opts["limit"],
            bill_identifier=opts["bill"],
        )
        if not bills:
            self.stdout.write(self.style.SUCCESS(
                "No bills need summaries. Done."
            ))
            return

        model = opts["model"] or settings.CLAUDE_LEGISLATION_MODEL

        if opts["dry_run"]:
            total_chars = sum(len(b.extracted_text.text) for b in bills)
            self.stdout.write(
                f"[dry-run] Would submit {len(bills)} bill(s) with model {model}.\n"
                f"          Total input: {total_chars:,} chars "
                f"(~{total_chars // 4:,} tokens)\n"
                f"          First 5: {[b.identifier for b in bills[:5]]}"
            )
            return

        self.stdout.write(
            f"Submitting batch: {len(bills)} bill(s), model {model}."
        )
        batch = self._submit_batch(client, bills, model)
        state.update({
            "batch_id": batch.id,
            "submitted_at": datetime.now(dt_timezone.utc).isoformat(),
            "bill_count": len(bills),
            "model": model,
            "processed": False,
        })
        for k in ("processed_at", "success_count", "error_count", "errors"):
            state.pop(k, None)
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Submitted batch {batch.id} with {len(bills)} bill(s).\n"
            f"Re-run this command to poll status and write results to the DB."
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
        identifiers = [_decode_custom_id(r.custom_id) for r in results]
        bills_by_id = {
            b.identifier: b
            for b in Bill.objects.filter(identifier__in=identifiers)
        }

        for result in results:
            identifier = _decode_custom_id(result.custom_id)
            kind = result.result.type
            if kind != "succeeded":
                errors.append((identifier, kind))
                continue

            message = result.result.message
            text = self._extract_text(message)
            if not text:
                block_types = sorted({getattr(b, "type", "?") for b in message.content})
                stop_reason = getattr(message, "stop_reason", "?")
                errors.append((
                    identifier,
                    f"empty text (stop_reason={stop_reason} blocks={block_types})",
                ))
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                errors.append((identifier, f"non-JSON output: {e}"))
                continue

            bill = bills_by_id.get(identifier)
            if bill is None:
                errors.append((identifier, "bill not in DB"))
                continue

            try:
                self._upsert_summary(
                    bill=bill,
                    data=data,
                    model_version=message.model,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", identifier)
                errors.append((identifier, f"upsert failed: {e}"))

        state["processed"] = True
        state["processed_at"] = datetime.now(dt_timezone.utc).isoformat()
        state["success_count"] = success
        state["error_count"] = len(errors)
        if errors:
            state["errors"] = errors[:50]
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Processed batch {batch_id}: {success} succeeded, "
            f"{len(errors)} errored."
        ))
        if errors:
            self.stdout.write(self.style.WARNING(
                f"First errors: {errors[:5]}"
            ))

    @staticmethod
    @transaction.atomic
    def _upsert_summary(*, bill: Bill, data: dict, model_version: str, batch_id: str) -> None:
        """Create or update the LegislationSummary row and resolve
        affected_sections from the LLM-reported section numbers in
        each key_change.
        """
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
        # Resolve `key_changes[].affected_section` to MunicipalCodeSection
        # rows. The LLM output has section numbers as strings; some may
        # not match any row in our SMC table (typo, deprecated section,
        # or referencing a non-SMC code), in which case we silently drop
        # them — the JSON still records what the LLM thought.
        section_numbers = {
            (kc.get("affected_section") or "").strip()
            for kc in (data.get("key_changes") or [])
        }
        section_numbers.discard("")
        if section_numbers:
            sections = MunicipalCodeSection.objects.filter(
                section_number__in=section_numbers
            )
            summary.affected_sections.set(sections)
        else:
            summary.affected_sections.clear()

    # ------------------------------------------------------------------ #
    #  Phase 2 — submit                                                   #
    # ------------------------------------------------------------------ #

    def _target_bills(
        self,
        *,
        force: bool,
        limit: Optional[int],
        bill_identifier: Optional[str],
    ) -> list[Bill]:
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

    def _submit_batch(self, client, bills: Iterable[Bill], model: str):
        requests = []
        for bill in bills:
            text = bill.extracted_text.text
            if len(text) > MAX_INPUT_CHARS:
                # Tail-truncate. BillText concatenates Summary first,
                # so the most-useful content is at the head.
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
                    }
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": THINKING_BUDGET_TOKENS,
                }
            requests.append({
                "custom_id": _encode_custom_id(bill.identifier),
                "params": params,
            })
        return client.messages.batches.create(requests=requests)

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
