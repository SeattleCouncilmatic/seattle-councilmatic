"""Tag Seattle City Council bills with issue-area labels via Claude Batch.

Submits each bill's title (plus the first 2k chars of ``BillText.text`` when
available) to Claude with a constrained-vocabulary JSON schema, then writes
the returned 1-3 tags into ``Bill.subject`` (the OCD ``ArrayField`` already
on the model — no new schema). Two-phase like ``summarize_legislation``:
first invocation submits, subsequent invocations poll + process.

The tag vocabulary is fixed in ``claude_service.BILL_TAG_VOCABULARY``;
output is enum-constrained so the model can't invent new tags. Bills
without a title are skipped with a warning (shouldn't happen on real OCD
rows but the OCD scraper occasionally emits placeholder rows).

State lives in ``data/tag_bill_issue_areas_state.json`` (gitignored).
Idempotent: bills with a non-empty ``subject`` are excluded unless
``--force``.

Usage:
    python manage.py tag_bill_issue_areas
    python manage.py tag_bill_issue_areas --limit 5      # smoke run
    python manage.py tag_bill_issue_areas --force        # re-tag all
    python manage.py tag_bill_issue_areas --dry-run      # no API calls
    python manage.py tag_bill_issue_areas --bill "CB 121177"
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

from councilmatic_core.models import Bill

from seattle_app.services.claude_service import (
    BILL_TAG_OUTPUT_SCHEMA,
    BILL_TAG_SYSTEM_PROMPT,
    BILL_TAG_VOCABULARY,
    _supports_adaptive_thinking,
    format_batch_error,
)

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/tag_bill_issue_areas_state.json"

# Per-request token ceiling. Tagging is a tiny structured-JSON task —
# the output is at most ~50 tokens (3 short tag strings). ``low`` effort
# is plenty for the routing decision; non-Haiku models bound thinking
# via ``output_config.effort`` (Haiku doesn't accept the parameter at all).
MAX_TOKENS_PER_REQUEST = 2048
THINKING_EFFORT = "low"

# Hard cap on how much of BillText.text we feed the tagger. The bill
# title is the dominant signal in practice (`City Light Department`,
# `Seattle Public Utilities`, etc. give the topic away); the body text
# is a tiebreaker for procedural bills like appropriations or surplus
# property transfers. 2 kB keeps batch input cheap and uniform.
MAX_BILL_BODY_CHARS = 2_000


def _encode_custom_id(identifier: str) -> str:
    return identifier.replace(" ", "_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("_", " ")


class Command(BaseCommand):
    help = "Tag bills with issue-area labels via the Claude Batch API."

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
            help="Re-tag bills that already have a non-empty subject.",
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
            "--bills",
            default=None,
            help=(
                "Comma-separated bill identifiers to process. Useful for "
                "curated stress-test runs across diverse topics."
            ),
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override settings.CLAUDE_BILL_TAG_MODEL for this run.",
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
            if not state.get("processed"):
                return  # batch still in flight; drained on the next run
            # Ended + persisted: fall through to submit a fresh batch for
            # new work, so one run drains then submits (#204/#206).

        bill_ids = (
            [s.strip() for s in opts["bills"].split(",") if s.strip()]
            if opts.get("bills")
            else None
        )
        bills = self._target_bills(
            force=opts["force"],
            limit=opts["limit"],
            bill_identifier=opts["bill"],
            bill_identifiers=bill_ids,
        )
        if not bills:
            self.stdout.write(self.style.SUCCESS("No bills need tagging. Done."))
            return

        model = opts["model"] or settings.CLAUDE_BILL_TAG_MODEL

        if opts["dry_run"]:
            total_chars = sum(len(self._build_input(b)) for b in bills)
            self.stdout.write(
                f"[dry-run] Would submit {len(bills)} bill(s) with model {model}.\n"
                f"          Total input: {total_chars:,} chars "
                f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
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
            f"Re-run this command to poll status and write tags to the DB."
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
        valid_tags = set(BILL_TAG_VOCABULARY)

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
                errors.append((identifier, format_batch_error(result.result)))
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

            tags_raw = data.get("tags") or []
            # Schema enforces the enum but not array length — Anthropic
            # rejects minItems/maxItems on arrays — so cap and dedupe
            # here. Order is preserved (most-relevant first per prompt).
            tags: list[str] = []
            for t in tags_raw:
                if t in valid_tags and t not in tags:
                    tags.append(t)
                if len(tags) == 3:
                    break
            if not tags:
                errors.append((identifier, f"no valid tags in output: {tags_raw!r}"))
                continue

            bill = bills_by_id.get(identifier)
            if bill is None:
                errors.append((identifier, "bill not in DB"))
                continue

            bill.subject = tags
            bill.save(update_fields=["subject"])
            success += 1

        state["processed"] = True
        state["processed_at"] = datetime.now(dt_timezone.utc).isoformat()
        state["success_count"] = success
        state["error_count"] = len(errors)
        if errors:
            state["errors"] = errors[:50]
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Processed batch {batch_id}: {success} tagged, "
            f"{len(errors)} errored."
        ))
        if errors:
            self.stdout.write(self.style.WARNING(f"First errors: {errors[:5]}"))

    # ------------------------------------------------------------------ #
    #  Phase 2 — submit                                                   #
    # ------------------------------------------------------------------ #

    def _target_bills(
        self,
        *,
        force: bool,
        limit: Optional[int],
        bill_identifier: Optional[str],
        bill_identifiers: Optional[list[str]] = None,
    ) -> list[Bill]:
        qs = (
            Bill.objects
            .exclude(title="")
            .select_related("extracted_text")
            .order_by("-created_at")
        )
        if bill_identifier:
            qs = qs.filter(identifier=bill_identifier)
        elif bill_identifiers:
            qs = qs.filter(identifier__in=bill_identifiers)
        elif not force:
            # `subject=[]` is the default for unset OCD ArrayField; the
            # __exact lookup against an empty list is the idiom for
            # "no tags yet" on Postgres ArrayField.
            qs = qs.filter(subject=[])
        if limit is not None:
            qs = qs[:limit]
        return list(qs)

    def _submit_batch(self, client, bills: Iterable[Bill], model: str):
        requests = []
        for bill in bills:
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": BILL_TAG_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": self._build_input(bill)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": BILL_TAG_OUTPUT_SCHEMA,
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
        return client.messages.batches.create(requests=requests)

    @staticmethod
    def _build_input(bill: Bill) -> str:
        title = (bill.title or "").strip()
        body = ""
        bt = getattr(bill, "extracted_text", None)
        if bt and bt.text:
            body = bt.text[:MAX_BILL_BODY_CHARS].strip()
        parts = [
            f"Bill: {bill.identifier}",
            f"Title: {title}",
        ]
        if body:
            parts.append("")
            parts.append("Excerpt of bill text (truncated for tagging):")
            parts.append(body)
        parts.append("")
        parts.append(
            "Return 1-3 issue-area tags from the controlled vocabulary, "
            "ordered by relevance."
        )
        return "\n".join(parts)

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
