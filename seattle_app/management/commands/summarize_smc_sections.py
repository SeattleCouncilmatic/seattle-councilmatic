"""Bulk-summarize SMC sections via the Anthropic Message Batches API.

The command runs in two phases that share a single state file:
    1. Submit. First invocation gathers sections without ``plain_summary``,
       builds a single batch, calls ``messages.batches.create``, and
       persists the batch ID to ``data/summarize_smc_state.json``.
    2. Poll + process. Subsequent invocations retrieve the batch, and
       once it has ``processing_status == "ended"`` they stream the
       results, write each summary to its section row, and mark the
       state as processed. Re-running after that picks up any sections
       still missing a summary and submits a fresh batch.

State lives in JSON rather than a Django table to avoid a migration for
something this small. Cost is contained by caching the system prompt
(SECTION_SYSTEM_PROMPT + few-shot examples) once per cache window and
by the Batch API's flat 50% discount.

Usage:
    python manage.py summarize_smc_sections
    python manage.py summarize_smc_sections --limit 50    # small smoke run
    python manage.py summarize_smc_sections --force       # re-summarize all
    python manage.py summarize_smc_sections --dry-run     # no API calls
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
from django.db.models import Q
from django.utils import timezone

from seattle_app.models import MunicipalCodeSection
from seattle_app.services.claude_service import (
    SECTION_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

DEFAULT_FEW_SHOTS_PATH = "data/few_shot_section_summaries.json"
DEFAULT_STATE_PATH = "data/summarize_smc_state.json"

# Per-request output ceiling. Above the prompt's 400-word target so
# adaptive thinking has headroom and we don't truncate mid-sentence.
MAX_TOKENS_PER_REQUEST = 1500


def _encode_custom_id(section_number: str) -> str:
    """Encode an SMC section number for the Batch API's custom_id field.

    Anthropic requires custom_id to match `^[a-zA-Z0-9_-]{1,64}$`, so
    section numbers like `23.47A.004` (which contain dots) need their
    `.` replaced with `-`. SMC section numbers never contain hyphens
    (SECTION_RE allows only digits + an optional uppercase letter per
    segment), so the swap is bidirectional.
    """
    return section_number.replace(".", "-")


def _decode_custom_id(custom_id: str) -> str:
    """Reverse of `_encode_custom_id`."""
    return custom_id.replace("-", ".")


def _build_system_prompt(few_shots: list[dict]) -> str:
    """Compose SECTION_SYSTEM_PROMPT + the curated few-shot examples.

    The block is sent once per request; cache_control on the system
    prompt makes Anthropic charge cache-write rates only on the first
    request of each ~5-minute window and cache-read rates (~10% of
    normal) on every subsequent request, which is most of the batch.
    """
    parts = [
        SECTION_SYSTEM_PROMPT,
        "",
        "Below are example summaries written in the style and shape "
        "you should match. Each example shows the section identifier, "
        "title, an excerpt of the input you would receive, and the "
        "kind of summary the system expects.",
        "",
    ]
    for i, ex in enumerate(few_shots, start=1):
        parts.extend([
            f"--- Example {i} ({ex.get('archetype', 'section')}) ---",
            f"Section: SMC {ex['section_number']}",
            f"Title: {ex['title']}",
            "Excerpt of full text:",
            ex["input_excerpt"],
            "",
            "Summary:",
            ex["summary"],
            "",
        ])
    return "\n".join(parts)


class Command(BaseCommand):
    help = "Bulk-summarize SMC sections via the Anthropic Message Batches API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of sections to include in this batch (testing).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-summarize sections that already have plain_summary set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be submitted without calling the API.",
        )
        parser.add_argument(
            "--few-shots",
            default=DEFAULT_FEW_SHOTS_PATH,
            help=f"Path to the curated few-shot JSON (default: {DEFAULT_FEW_SHOTS_PATH}).",
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

        # Phase 1: if a batch is in flight or hasn't been processed, handle it.
        if state.get("batch_id") and not state.get("processed"):
            self._poll_and_maybe_process(client, state, state_path)
            return

        # Phase 2: gather sections needing summaries and submit a new batch.
        sections = self._sections_needing_summaries(
            force=opts["force"], limit=opts["limit"]
        )
        if not sections:
            self.stdout.write(self.style.SUCCESS(
                "No sections need summaries. Done."
            ))
            return

        few_shots = self._load_few_shots(opts["few_shots"])
        system_prompt = _build_system_prompt(few_shots)

        if opts["dry_run"]:
            self.stdout.write(
                f"[dry-run] Would submit {len(sections)} sections.\n"
                f"          System prompt: {len(system_prompt):,} chars "
                f"(few-shots: {len(few_shots)} examples).\n"
                f"          First 5: {[s.section_number for s in sections[:5]]}"
            )
            return

        self.stdout.write(
            f"Submitting batch: {len(sections)} sections, model "
            f"{settings.CLAUDE_CODE_SECTION_MODEL}, system prompt "
            f"{len(system_prompt):,} chars."
        )
        batch = self._submit_batch(client, sections, system_prompt)
        state.update({
            "batch_id": batch.id,
            "submitted_at": datetime.now(dt_timezone.utc).isoformat(),
            "section_count": len(sections),
            "model": settings.CLAUDE_CODE_SECTION_MODEL,
            "processed": False,
        })
        # Drop any leftover error/success counts from a prior batch.
        for k in ("processed_at", "success_count", "error_count", "errors"):
            state.pop(k, None)
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Submitted batch {batch.id} with {len(sections)} sections.\n"
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

        # Materialize results once so we can prefetch all matching sections
        # in a single query. ~7.4k results at ~5KB each fits easily in
        # memory; if batches grow past 100k requests we should stream and
        # batch-fetch instead.
        results = list(client.messages.batches.results(batch_id))
        section_numbers = [_decode_custom_id(r.custom_id) for r in results]
        sections_by_number = {
            s.section_number: s
            for s in MunicipalCodeSection.objects.filter(
                section_number__in=section_numbers
            )
        }

        for result in results:
            section_number = _decode_custom_id(result.custom_id)
            kind = result.result.type
            if kind != "succeeded":
                errors.append((section_number, kind))
                continue

            message = result.result.message
            summary_text = self._extract_text(message)
            if not summary_text:
                errors.append((section_number, "empty text in response"))
                continue

            section = sections_by_number.get(section_number)
            if section is None:
                errors.append((section_number, "section not in DB"))
                continue

            section.plain_summary = summary_text
            section.summary_model = message.model
            section.summary_generated_at = timezone.now()
            section.save(update_fields=[
                "plain_summary", "summary_model", "summary_generated_at"
            ])
            success += 1

        state["processed"] = True
        state["processed_at"] = datetime.now(dt_timezone.utc).isoformat()
        state["success_count"] = success
        state["error_count"] = len(errors)
        if errors:
            # Cap the persisted error list so the state file stays readable.
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

    # ------------------------------------------------------------------ #
    #  Phase 2 — submit                                                   #
    # ------------------------------------------------------------------ #

    def _sections_needing_summaries(
        self, force: bool, limit: Optional[int]
    ) -> list[MunicipalCodeSection]:
        qs = MunicipalCodeSection.objects.all().order_by("section_number")
        if not force:
            # `plain_summary` is `TextField(blank=True)` without `null=True`,
            # but some legacy rows still have NULL — `field=""` doesn't match
            # those (NULL = '' is NULL in SQL), so OR isnull to catch both.
            qs = qs.filter(Q(plain_summary="") | Q(plain_summary__isnull=True))
        if limit is not None:
            qs = qs[:limit]
        return list(qs)

    def _submit_batch(
        self,
        client,
        sections: Iterable[MunicipalCodeSection],
        system_prompt: str,
    ):
        model = settings.CLAUDE_CODE_SECTION_MODEL
        requests = []
        for section in sections:
            user_content = (
                f"Section: SMC {section.section_number}\n"
                f"Title: {section.title}\n\n"
                f"Full text:\n{section.full_text}\n\n"
                "Write a plain-English summary of this section for a Seattle resident."
            )
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": user_content}],
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
            requests.append({
                "custom_id": _encode_custom_id(section.section_number),
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
            raise CommandError(
                f"Could not parse state file {path}: {e}"
            ) from e

    @staticmethod
    def _save_state(state: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_few_shots(path: str) -> list[dict]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError as e:
            raise CommandError(
                f"Few-shots file not found: {path}. Run "
                f"`bootstrap_section_summaries` and curate first."
            ) from e
        examples = data.get("examples")
        if not examples:
            raise CommandError(
                f"Few-shots file {path} has no 'examples' array."
            )
        return examples
