"""Generate per-meeting LLM summaries (overview + per-agenda-item) via
the Anthropic Message Batches API.

For each ``Event`` with an ``EventTranscript`` and no ``EventSummary``
(unless ``--force``), assembles a structured prompt input:
  - meeting metadata (date, name)
  - current councilmember roster (for name disambiguation against the
    auto-caption transcript's garbled proper nouns)
  - validated chapter list (after the chunker drops stale markers and
    merges duplicate timestamps)
  - per-chapter transcript chunks with clear boundaries

Submits via Batch with the ``EVENT_SUMMARY_*`` prompt + JSON schema.
Two-phase like the rep / legislation summarizers: first invocation
submits, subsequent invocations poll + process.

Persists results to ``EventSummary`` as
``overview`` (string) + ``item_summaries`` (list of
``{label, start_seconds, summary}`` dicts). ``stats_snapshot`` captures
the structured context for reproducibility.

Usage:
    python manage.py summarize_events
    python manage.py summarize_events --dry-run
    python manage.py summarize_events --force
    python manage.py summarize_events --event-id ocd-event/<uuid>
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

from councilmatic_core.models import Event
from opencivicdata.core.models import Person

from seattle_app.models import EventSummary, EventTranscript
from seattle_app.services.claude_service import (
    EVENT_SUMMARY_OUTPUT_SCHEMA,
    EVENT_SUMMARY_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
    format_batch_error,
)
from seattle_app.services.event_chunker import chunk_by_chapters

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/summarize_events_state.json"

# Per-request token ceiling. Input per meeting is ~25k tokens
# (auto-captioned transcript ~100KB) plus roster/agenda context. Output
# is bounded by the prompt (overview ≤350 words + N item summaries ≤80
# words each); 8k tokens gives generous room for a 12-chapter meeting.
# Thinking is bounded via ``output_config.effort``.
MAX_TOKENS_PER_REQUEST = 8192
THINKING_EFFORT = "medium"


def _encode_custom_id(event_id: str) -> str:
    """OCD Event ids start with 'ocd-event/' which the Anthropic
    custom_id regex rejects (slash + max length 64). Strip prefix
    and replace dashes for safety."""
    return event_id.replace("ocd-event/", "ocdevent_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("ocdevent_", "ocd-event/")


def _current_member_roster() -> list[dict]:
    """Roster of currently serving councilmembers for the prompt.
    Mirrors ``reps.services._query_current_council_members``."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT p.id, p.name, m.label
            FROM opencivicdata_person p
            INNER JOIN councilmatic_core_person cp ON cp.person_id = p.id
            INNER JOIN opencivicdata_membership m ON m.person_id = p.id
            INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
            WHERE o.name = 'Seattle City Council' AND cp.is_current = TRUE
            ORDER BY p.name
            """
        )
        return [
            {"name": row[1], "seat": row[2]}
            for row in cursor.fetchall()
        ]


class Command(BaseCommand):
    help = "Generate per-meeting LLM summaries via the Anthropic Batch API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be submitted without calling the API.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-summarize events that already have an EventSummary.",
        )
        parser.add_argument(
            "--event-id",
            default=None,
            help="Single Event by OCD id.",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override settings.CLAUDE_EVENT_SUMMARY_MODEL for this run.",
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
            raise CommandError("ANTHROPIC_API_KEY not configured.")
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        if state.get("batch_id") and not state.get("processed"):
            self._poll_and_maybe_process(client, state, state_path)
            if not state.get("processed"):
                return  # batch still in flight; drained on the next run
            # Ended + persisted: fall through to submit a fresh batch for
            # new work, so one run drains then submits (#204/#206).

        events = self._target_events(
            force=opts["force"], event_id=opts["event_id"]
        )
        if not events:
            self.stdout.write(self.style.SUCCESS("No events need summaries. Done."))
            return

        model = opts["model"] or settings.CLAUDE_EVENT_SUMMARY_MODEL

        roster = _current_member_roster()
        # Build prompt inputs up-front so dry-run sizing matches real.
        contexts = []
        for ev in events:
            chunks = chunk_by_chapters(ev.transcript)
            contexts.append((ev, chunks))

        if opts["dry_run"]:
            total_chars = sum(
                len(self._build_input(ev, chunks, roster))
                for ev, chunks in contexts
            )
            self.stdout.write(
                f"[dry-run] Would submit {len(events)} event(s) with model {model}.\n"
                f"          Total input: {total_chars:,} chars "
                f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
                f"          Events: {[(ev.start_date[:10], ev.name) for ev in events]}"
            )
            return

        self.stdout.write(
            f"Submitting batch: {len(events)} event(s), model {model}."
        )
        batch = self._submit_batch(client, contexts, roster, model)
        state.update({
            "batch_id": batch.id,
            "submitted_at": datetime.now(dt_timezone.utc).isoformat(),
            "event_count": len(events),
            "model": model,
            "processed": False,
        })
        for k in ("processed_at", "success_count", "error_count", "errors"):
            state.pop(k, None)
        self._save_state(state, state_path)

        self.stdout.write(self.style.SUCCESS(
            f"Submitted batch {batch.id} with {len(events)} event(s).\n"
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

    def _process_results(self, client, batch_id, state, state_path):
        success = 0
        errors: list[tuple[str, str]] = []

        results = list(client.messages.batches.results(batch_id))
        event_ids = [_decode_custom_id(r.custom_id) for r in results]
        events_by_id = {e.id: e for e in Event.objects.filter(id__in=event_ids)}

        for result in results:
            event_id = _decode_custom_id(result.custom_id)
            kind = result.result.type
            if kind != "succeeded":
                errors.append((event_id, format_batch_error(result.result)))
                continue

            message = result.result.message
            text = self._extract_text(message)
            if not text:
                blocks = sorted({getattr(b, "type", "?") for b in message.content})
                stop = getattr(message, "stop_reason", "?")
                errors.append((event_id, f"empty text (stop={stop} blocks={blocks})"))
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                errors.append((event_id, f"non-JSON output: {e}"))
                continue

            event = events_by_id.get(event_id)
            if event is None:
                errors.append((event_id, "event not in DB"))
                continue

            try:
                self._upsert_summary(
                    event=event,
                    data=data,
                    model_version=message.model,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", event_id)
                errors.append((event_id, f"upsert failed: {e}"))

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
    def _upsert_summary(*, event, data, model_version, batch_id):
        # Re-build the stats_snapshot at upsert time (chunker is
        # deterministic for a given EventTranscript, so this matches
        # what we submitted).
        chunks = chunk_by_chapters(event.transcript)
        snapshot = {
            "meeting_date": event.start_date,
            "meeting_name": event.name,
            "roster": _current_member_roster(),
            "chapters": [
                {"label": c["label"], "start_seconds": c["start_seconds"]}
                for c in chunks
            ],
        }

        # Merge LLM-returned per-item summaries back with their
        # start_seconds. The LLM is prompted to return items in the
        # same order as the input chapter list, so zip by index is the
        # primary matching strategy — robust to subtle label whitespace
        # drift on merged-duplicate chapters where the LLM strips the
        # " + " separator differently. Fall back to label match by
        # exact then substring if cardinality differs from the input.
        llm_items = data.get("item_summaries") or []
        item_summaries = []
        if len(llm_items) == len(chunks):
            for chunk, item in zip(chunks, llm_items):
                item_summaries.append({
                    "label": chunk["label"],  # use chunker's label as source of truth
                    "start_seconds": chunk["start_seconds"],
                    "summary": (item.get("summary") or "").strip(),
                })
        else:
            # Cardinality mismatch — fall back to fuzzy label matching.
            # The frontend can degrade if some chunks have no summary.
            by_exact = {c["label"]: c for c in chunks}
            for item in llm_items:
                label = item.get("label") or ""
                chunk = by_exact.get(label) or next(
                    (c for c in chunks if label in c["label"] or c["label"] in label),
                    None,
                )
                item_summaries.append({
                    "label": chunk["label"] if chunk else label,
                    "start_seconds": chunk["start_seconds"] if chunk else None,
                    "summary": (item.get("summary") or "").strip(),
                })

        EventSummary.objects.update_or_create(
            event=event,
            defaults={
                "overview": (data.get("overview") or "").strip(),
                "item_summaries": item_summaries,
                "stats_snapshot": snapshot,
                "model_version": model_version,
                "summary_batch_id": batch_id,
            },
        )

    # ------------------------------------------------------------------ #
    #  Phase 2 — submit                                                   #
    # ------------------------------------------------------------------ #

    def _target_events(self, *, force, event_id):
        qs = Event.objects.filter(transcript__isnull=False).order_by("start_date")
        if event_id:
            qs = qs.filter(id=event_id)
        elif not force:
            qs = qs.filter(llm_summary__isnull=True)
        return list(qs)

    def _submit_batch(self, client, contexts, roster, model):
        requests = []
        for ev, chunks in contexts:
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": EVENT_SUMMARY_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": self._build_input(ev, chunks, roster)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": EVENT_SUMMARY_OUTPUT_SCHEMA,
                    },
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
                params["output_config"]["effort"] = THINKING_EFFORT
            requests.append({
                "custom_id": _encode_custom_id(ev.id),
                "params": params,
            })
        return client.messages.batches.create(requests=requests)

    @staticmethod
    def _build_input(event, chunks: list[dict], roster: list[dict]) -> str:
        meeting_date = (event.start_date or "")[:10]
        roster_lines = "\n".join(
            f"  - {r['name']} ({r['seat']})" for r in roster
        )
        chapter_lines = "\n".join(
            f"  {i + 1}. {c['label']} (starts at {_fmt_ts(c['start_seconds'])})"
            for i, c in enumerate(chunks)
        )
        chunked_transcript = "\n\n".join(
            f"=== Chapter {i + 1}: {c['label']} ===\n{c['text']}"
            for i, c in enumerate(chunks)
        )
        return (
            f"Meeting: {event.name}\n"
            f"Date: {meeting_date}\n\n"
            f"Current councilmembers (roster for name disambiguation):\n"
            f"{roster_lines}\n\n"
            f"Validated agenda chapter list:\n"
            f"{chapter_lines}\n\n"
            f"Transcript by chapter:\n\n"
            f"{chunked_transcript}\n\n"
            "Produce the structured overview + per-item summaries per "
            "the system instructions."
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


def _fmt_ts(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
