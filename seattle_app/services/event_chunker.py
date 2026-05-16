"""Chunk a council-meeting transcript by agenda-item chapter markers.

Takes an ``EventTranscript`` and returns a list of
``{label, start_seconds, end_seconds, text}`` dicts — one per
agenda chapter, with the SRT text falling in that chapter's time
window concatenated and HTML-unescaped.

Handles two upstream data-quality issues seen on Seattle Channel:

  1. **Stale chapter markers.** Some pages list markers whose
     ``start_seconds`` extends past the actual meeting end (the
     CMS occasionally copy-pastes markers between meetings — see
     PR #184 WORK_LOG entry on 4/21/2026). Markers whose start
     exceeds the SRT's last entry's end-time are dropped before
     chunking; the prompt context records what was dropped.

  2. **Duplicate chapter timestamps.** Some pages list two markers
     at the same ``data-seek`` value (e.g. 4/14/2026 has CB 121185
     and CB 121187 both at 7103s). Adjacent same-timestamp markers
     are merged: labels are joined with " + ", and the merged chapter
     uses the union of their text windows.

If no chapter markers remain after validation, the chunker returns
a single chunk covering the whole transcript with label
``"Full meeting"`` — the summarizer's per-item pass then collapses
to overview-only for that meeting."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


_SRT_ENTRY_RE = re.compile(
    r"^\d+\r?\n"
    r"(\d{2}):(\d{2}):(\d{2}),\d{3} --> "
    r"(\d{2}):(\d{2}):(\d{2}),\d{3}\r?\n"
    r"((?:.+\r?\n?)+?)"
    r"(?:\r?\n|$)",
    re.MULTILINE,
)


@dataclass
class _SrtEntry:
    start_s: int
    end_s: int
    text: str


def chunk_by_chapters(transcript) -> list[dict]:
    """Return per-chapter chunks for an ``EventTranscript``.

    Each chunk is ``{label, start_seconds, end_seconds, text}``. Text
    is HTML-unescaped, speaker-turn ``>>`` markers preserved as
    paragraph breaks (consistent with ``EventTranscript.transcript_text``).
    """
    entries = _parse_srt(transcript.srt_raw)
    if not entries:
        return [_single_chunk(transcript.transcript_text)]

    srt_end_s = entries[-1].end_s
    raw_markers = transcript.chapter_markers or []
    markers = _validate_and_dedupe_markers(raw_markers, srt_end_s)

    if not markers:
        return [_single_chunk(transcript.transcript_text)]

    chunks: list[dict] = []
    for i, m in enumerate(markers):
        start_s = m["start_seconds"]
        end_s = markers[i + 1]["start_seconds"] if i + 1 < len(markers) else srt_end_s + 1
        window_text = _entries_to_text(
            [e for e in entries if start_s <= e.start_s < end_s]
        )
        chunks.append({
            "label": m["label"],
            "start_seconds": start_s,
            "end_seconds": end_s,
            "text": window_text,
        })
    return chunks


# ---------------------------------------------------------------- internals
def _parse_srt(srt_raw: str) -> list[_SrtEntry]:
    out: list[_SrtEntry] = []
    for m in _SRT_ENTRY_RE.finditer(srt_raw):
        h1, m1, s1, h2, m2, s2, text = m.groups()
        start_s = int(h1) * 3600 + int(m1) * 60 + int(s1)
        end_s = int(h2) * 3600 + int(m2) * 60 + int(s2)
        # Collapse multi-line caption + decode entities.
        flat = " ".join(line.strip() for line in text.splitlines() if line.strip())
        flat = html.unescape(flat)
        out.append(_SrtEntry(start_s=start_s, end_s=end_s, text=flat))
    return out


def _validate_and_dedupe_markers(
    raw_markers: list[dict], srt_end_s: int,
) -> list[dict]:
    """Drop markers past the SRT end; merge adjacent same-start markers."""
    # Sort by start_seconds first (extractor already does this but be safe).
    sorted_markers = sorted(raw_markers, key=lambda c: c["start_seconds"])

    # Drop stale (past end).
    fresh = [m for m in sorted_markers if m["start_seconds"] <= srt_end_s]

    # Merge adjacent same-start.
    merged: list[dict] = []
    for m in fresh:
        if merged and merged[-1]["start_seconds"] == m["start_seconds"]:
            # Same start as previous; merge labels with " + ".
            merged[-1] = {
                **merged[-1],
                "label": f'{merged[-1]["label"]} + {m["label"]}',
            }
        else:
            merged.append(dict(m))
    return merged


def _entries_to_text(entries: list[_SrtEntry]) -> str:
    """Join SRT entries into prose, promoting '>>' speaker-turn markers
    to paragraph breaks (matches the flattening
    ``extract_event_transcripts`` does for ``transcript_text``)."""
    flat = " ".join(e.text for e in entries)
    return re.sub(r"\s*>{2,}\s*", "\n\n>> ", flat).strip()


def _single_chunk(transcript_text: str) -> dict:
    """Fallback when no chapter markers are usable: one chunk for the
    whole meeting."""
    return {
        "label": "Full meeting",
        "start_seconds": 0,
        "end_seconds": None,
        "text": transcript_text,
    }
