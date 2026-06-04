"""Generate per-meeting LLM summaries (overview + per-agenda-item) via the
Anthropic Message Batches API.

For each ``Event`` with an ``EventTranscript`` and no ``EventSummary`` (unless
``--force``), assembles a structured prompt input:
  - meeting metadata (date, name)
  - current councilmember roster (for name disambiguation against the
    auto-caption transcript's garbled proper nouns)
  - validated chapter list (after the chunker drops stale markers and merges
    duplicate timestamps)
  - per-chapter transcript chunks with clear boundaries

Submits via Batch with the ``EVENT_SUMMARY_*`` prompt + JSON schema. The
drain-then-submit state machine lives in ``BatchPipelineCommand``: one run
polls + persists any in-flight batch, then submits a fresh one. State is the
``BatchRun`` row, not a JSON file (issue #208).

Persists results to ``EventSummary`` as ``overview`` (string) +
``item_summaries`` (list of ``{label, start_seconds, summary}`` dicts).
``stats_snapshot`` captures the structured context for reproducibility.

Usage:
    python manage.py summarize_events
    python manage.py summarize_events --dry-run
    python manage.py summarize_events --force
    python manage.py summarize_events --event-id ocd-event/<uuid>
"""
from __future__ import annotations

import logging

from django.db import connection, transaction

from councilmatic_core.models import Event

from seattle_app.models import EventSummary
from seattle_app.services.batch_pipeline import BatchPipelineCommand
from seattle_app.services.claude_service import (
    EVENT_SUMMARY_OUTPUT_SCHEMA,
    EVENT_SUMMARY_SYSTEM_PROMPT,
    _supports_adaptive_thinking,
)
from seattle_app.services.event_chunker import chunk_by_chapters

logger = logging.getLogger(__name__)

# Per-request token ceiling. Input per meeting is ~25k tokens (auto-captioned
# transcript ~100KB) plus roster/agenda context. Output is bounded by the
# prompt (overview ≤350 words + N item summaries ≤80 words each); 8k tokens
# gives generous room for a 12-chapter meeting. Thinking is bounded via
# ``output_config.effort``.
MAX_TOKENS_PER_REQUEST = 8192
THINKING_EFFORT = "medium"


def _encode_custom_id(event_id: str) -> str:
    """OCD Event ids start with 'ocd-event/' which the Anthropic custom_id
    regex rejects (slash + max length 64). Strip prefix and replace dashes."""
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
        return [{"name": row[1], "seat": row[2]} for row in cursor.fetchall()]


class Command(BatchPipelineCommand):
    help = "Generate per-meeting LLM summaries via the Anthropic Batch API."

    command_key = "summarize_events"
    default_model_setting = "CLAUDE_EVENT_SUMMARY_MODEL"

    def add_batch_arguments(self, parser):
        parser.add_argument(
            "--event-id", default=None, help="Single Event by OCD id."
        )

    def no_targets_message(self) -> str:
        return "No events need summaries. Done."

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #
    def get_targets(self, opts) -> list:
        qs = Event.objects.filter(transcript__isnull=False).order_by("start_date")
        if opts["event_id"]:
            qs = qs.filter(id=opts["event_id"])
        elif not opts["force"]:
            qs = qs.filter(llm_summary__isnull=True)
        return list(qs)

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def build_requests(self, targets, model) -> list[dict]:
        roster = _current_member_roster()
        requests = []
        for ev in targets:
            chunks = chunk_by_chapters(ev.transcript)
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
        return requests

    def describe_dry_run(self, targets, model) -> str:
        roster = _current_member_roster()
        total_chars = sum(
            len(self._build_input(ev, chunk_by_chapters(ev.transcript), roster))
            for ev in targets
        )
        return (
            f"[dry-run] Would submit {len(targets)} event(s) with model {model}.\n"
            f"          Total input: {total_chars:,} chars "
            f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
            f"          Events: {[(ev.start_date[:10], ev.name) for ev in targets]}"
        )

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
    #  Persist                                                            #
    # ------------------------------------------------------------------ #
    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        parsed = list(self.iter_json_results(results))
        event_ids = [_decode_custom_id(cid) for cid, _d, _m, _e in parsed]
        events_by_id = {e.id: e for e in Event.objects.filter(id__in=event_ids)}

        success = 0
        errors: list[tuple[str, str]] = []
        for cid, data, model_version, err in parsed:
            event_id = _decode_custom_id(cid)
            if err:
                errors.append((event_id, err))
                continue
            event = events_by_id.get(event_id)
            if event is None:
                errors.append((event_id, "event not in DB"))
                continue
            try:
                self._upsert_summary(
                    event=event,
                    data=data,
                    model_version=model_version,
                    batch_id=batch_id,
                )
                success += 1
            except Exception as e:
                logger.exception("upsert failed for %s", event_id)
                errors.append((event_id, f"upsert failed: {e}"))
        return success, errors

    @staticmethod
    @transaction.atomic
    def _upsert_summary(*, event, data, model_version, batch_id):
        # Re-build the stats_snapshot at upsert time (chunker is deterministic
        # for a given EventTranscript, so this matches what we submitted).
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

        # Merge LLM-returned per-item summaries back with their start_seconds.
        # The LLM is prompted to return items in the same order as the input
        # chapter list, so zip by index is the primary matching strategy —
        # robust to subtle label whitespace drift on merged-duplicate chapters
        # where the LLM strips the " + " separator differently. Fall back to
        # label match by exact then substring if cardinality differs.
        llm_items = data.get("item_summaries") or []
        item_summaries = []
        if len(llm_items) == len(chunks):
            for chunk, item in zip(chunks, llm_items):
                item_summaries.append({
                    "label": chunk["label"],  # chunker's label as source of truth
                    "start_seconds": chunk["start_seconds"],
                    "summary": (item.get("summary") or "").strip(),
                })
        else:
            # Cardinality mismatch — fall back to fuzzy label matching. The
            # frontend can degrade if some chunks have no summary.
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


def _fmt_ts(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
