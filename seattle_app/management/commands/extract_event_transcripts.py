"""Extract Seattle Channel SRT transcripts for council meetings.

For each in-scope ``Event`` (default: Full Council meetings from
2026-01-01 forward), walks the chain:

    OCD Event  ->  Legistar MeetingDetail page  ->  Seattle Channel
    video page  ->  SRT closed-caption file  ->  EventTranscript row

The Legistar page exposes a Seattle Channel `videoid=x\\d+` link; the
Seattle Channel video page exposes both the SRT download URL and the
underlying MP4 URL. Chapter markers (per-agenda-item timestamps) are
parsed from `<a class="seekItem" data-seek="<seconds>">{label} - <ts></a>`
elements on the same page.

Persisted shape (see ``EventTranscript``):
  - ``srt_raw``      — original SRT verbatim
  - ``transcript_text`` — flattened plain text, entities decoded
  - ``chapter_markers`` — [{label, start_seconds}] ordered by time
  - ``video_url``    — MP4 URL for future Whisper re-transcription

Idempotent — re-running upserts by ``event_id``. ``--force`` to refresh
already-extracted rows.

Usage:
    python manage.py extract_event_transcripts                  # all in-scope
    python manage.py extract_event_transcripts --dry-run        # no DB writes
    python manage.py extract_event_transcripts --force          # re-scrape all
    python manage.py extract_event_transcripts --event-id ocd-event/<uuid>
    python manage.py extract_event_transcripts --since 2026-01-01
    python manage.py extract_event_transcripts --name "City Council"
"""
from __future__ import annotations

import html
import logging
import re
import time

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from councilmatic_core.models import Event

from seattle_app.models import EventTranscript

logger = logging.getLogger(__name__)


_SC_HOST = "https://seattlechannel.org"
_REQUEST_TIMEOUT = 15
_REQUEST_DELAY_SECONDS = 1  # polite between Legistar/SC fetches per event

# Legistar MeetingDetail page exposes the Seattle Channel link as
# `seattlechannel.org/FullCouncil?videoid=x\d+&Mode2=Video` (or a near
# variant). Capture only the videoid for re-composition with the
# canonical page URL.
_LEGISTAR_VIDEOID_RE = re.compile(
    r"seattlechannel\.org/[^\"'\s<>]*?videoid=(x\d+)",
    re.IGNORECASE,
)

# Seattle Channel video page exposes the SRT path as a substring like
# `documents/SeattleChannel/closedcaption/<year>/council_<MMDDYY>_<id>.srt`.
# The leading slash is sometimes present, sometimes not.
_SC_SRT_RE = re.compile(
    r"(documents/SeattleChannel/closedcaption/\d{4}/council_\d{6}_\d+\.srt)",
    re.IGNORECASE,
)

# Seattle Channel video page exposes the MP4 URL as a protocol-relative
# `//video.seattle.gov/media/council/council_<MMDDYY>_<id>.mp4`.
_SC_MP4_RE = re.compile(
    r"//(video\.seattle\.gov/media/council/council_\d{6}_\d+\.mp4)",
    re.IGNORECASE,
)

# Chapter markers: `<a class="seekItem" href="#" data-seek="<sec>">{label}</a>`
# where {label} usually ends with " - <hh:mm:ss>" which we strip for a
# clean label.
_SC_CHAPTER_RE = re.compile(
    r'<a[^>]*class="seekItem"[^>]*data-seek="(\d+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)

# SRT entry skeleton — sequence number, timestamp line, then text lines
# until a blank line. We use this just for flattening; the raw SRT is
# preserved separately.
_SRT_ENTRY_RE = re.compile(
    r"^\d+\r?\n"                                        # sequence
    r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\r?\n"  # timestamp
    r"((?:.+\r?\n?)+?)"                                 # text (non-greedy)
    r"(?:\r?\n|$)",                                     # blank or EOF
    re.MULTILINE,
)

# Label-suffix stripper: matches a trailing " - <hh:mm:ss>" or " - <m:ss>"
# tag that the SC UI appends to each chapter title for display.
_CHAPTER_TS_SUFFIX_RE = re.compile(r"\s*-\s*\d+:\d{2}(?::\d{2})?\s*$")


class Command(BaseCommand):
    help = (
        "Scrape Seattle Channel SRT transcripts + chapter markers for "
        "council meetings, persist as EventTranscript rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-scrape events that already have an EventTranscript.",
        )
        parser.add_argument(
            "--event-id",
            default=None,
            help="Single Event by OCD id (e.g. 'ocd-event/<uuid>').",
        )
        parser.add_argument(
            "--since",
            default="2026-01-01",
            help=(
                "Filter to events with start_date >= this ISO date "
                "(default: 2026-01-01)."
            ),
        )
        parser.add_argument(
            "--name",
            default="City Council",
            help=(
                "Event.name filter (default: 'City Council' — Full Council "
                "meetings). Pass empty string to include all event types."
            ),
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        force = opts["force"]

        qs = self._target_events(
            event_id=opts["event_id"],
            since=opts["since"],
            name=opts["name"],
            force=force,
        )
        events = list(qs)
        if not events:
            self.stdout.write(self.style.SUCCESS("No events need transcripts. Done."))
            return

        self.stdout.write(
            f"Scraping transcripts for {len(events)} event(s) "
            f"(dry-run={dry}, force={force})."
        )

        n_ok = 0
        n_skipped = 0
        n_errors = 0

        for event in events:
            # OCD Event.start_date is an ISO partial-date string, not
            # a datetime, so substring rather than .date().
            label = f"{(event.start_date or '?')[:10]} {event.name}"
            try:
                result = self._scrape_one(event)
            except _ExtractorSkip as e:
                self.stdout.write(self.style.NOTICE(f"  {label}: {e}"))
                n_skipped += 1
                continue
            except Exception as e:
                logger.exception("extractor failed for %s", event.id)
                self.stderr.write(self.style.ERROR(f"  {label}: {type(e).__name__}: {e}"))
                n_errors += 1
                continue

            n_chapters = len(result["chapter_markers"])
            n_chars = len(result["transcript_text"])
            self.stdout.write(
                f"  {label}: {n_chars:,} chars, {n_chapters} chapter marker(s)"
            )
            if not dry:
                with transaction.atomic():
                    EventTranscript.objects.update_or_create(
                        event=event,
                        defaults={
                            "srt_raw": result["srt_raw"],
                            "transcript_text": result["transcript_text"],
                            "chapter_markers": result["chapter_markers"],
                            "source_url": result["source_url"],
                            "video_url": result["video_url"],
                        },
                    )
                n_ok += 1
            time.sleep(_REQUEST_DELAY_SECONDS)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone (dry-run={dry}). OK: {n_ok}. Skipped: {n_skipped}. Errors: {n_errors}."
        ))

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #

    def _target_events(self, *, event_id, since, name, force):
        qs = Event.objects.all()
        if event_id:
            qs = qs.filter(id=event_id)
        else:
            if name:
                qs = qs.filter(name=name)
            if since:
                qs = qs.filter(start_date__gte=since)
            # Only past meetings — future ones have no recording yet.
            qs = qs.filter(start_date__lt=timezone.now().isoformat())
        if not force:
            qs = qs.filter(transcript__isnull=True)
        return qs.order_by("start_date")

    # ------------------------------------------------------------------ #
    #  Per-event scrape                                                   #
    # ------------------------------------------------------------------ #

    def _scrape_one(self, event) -> dict:
        legistar_url = self._legistar_url(event)
        videoid = self._extract_videoid(legistar_url)
        sc_page_url = f"{_SC_HOST}/FullCouncil?videoid={videoid}&Mode2=Video"
        sc_html = self._fetch_text(sc_page_url)

        srt_path = self._extract_first(_SC_SRT_RE, sc_html)
        if not srt_path:
            raise _ExtractorSkip("no SRT URL on Seattle Channel page")
        srt_url = f"{_SC_HOST}/{srt_path.lstrip('/')}"

        mp4_path = self._extract_first(_SC_MP4_RE, sc_html)
        video_url = f"https://{mp4_path}" if mp4_path else ""

        chapter_markers = self._extract_chapter_markers(sc_html)

        srt_raw = self._fetch_text(srt_url)
        transcript_text = self._srt_to_plain_text(srt_raw)

        return {
            "srt_raw": srt_raw,
            "transcript_text": transcript_text,
            "chapter_markers": chapter_markers,
            "source_url": srt_url,
            "video_url": video_url,
        }

    @staticmethod
    def _legistar_url(event) -> str:
        src = event.sources.first()
        if not src:
            raise _ExtractorSkip("no source URL on Event")
        return src.url

    def _extract_videoid(self, legistar_url: str) -> str:
        legistar_html = self._fetch_text(legistar_url)
        videoid = self._extract_first(_LEGISTAR_VIDEOID_RE, legistar_html)
        if not videoid:
            raise _ExtractorSkip("no Seattle Channel videoid on Legistar page")
        return videoid

    @staticmethod
    def _extract_first(pattern, text):
        m = pattern.search(text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_chapter_markers(sc_html: str) -> list[dict]:
        out = []
        for m in _SC_CHAPTER_RE.finditer(sc_html):
            secs = int(m.group(1))
            raw_label = html.unescape(m.group(2)).strip()
            label = _CHAPTER_TS_SUFFIX_RE.sub("", raw_label).strip()
            out.append({"label": label, "start_seconds": secs})
        out.sort(key=lambda c: c["start_seconds"])
        return out

    @staticmethod
    def _srt_to_plain_text(srt_raw: str) -> str:
        """Flatten SRT to plain text. Decodes HTML entities, preserves
        the '>>' speaker-turn markers (so the LLM can identify speaker
        changes), drops sequence numbers and timestamp lines, joins
        wrapped caption lines into space-separated sentences. Inserts
        a paragraph break before each '>>' so the output reads as
        speaker turns rather than one wall of text."""
        out_lines: list[str] = []
        for m in _SRT_ENTRY_RE.finditer(srt_raw):
            text = m.group(1).rstrip("\n\r")
            # SRT text can span multiple caption lines; collapse to one.
            joined = " ".join(line.strip() for line in text.splitlines() if line.strip())
            joined = html.unescape(joined)
            out_lines.append(joined)
        flat = " ".join(out_lines)
        # Promote every '>>' to a paragraph break to expose speaker
        # turns. Normalize the literal marker variants ('>>>', '>>', '>')
        # to a single '\n\n>> ' so downstream chunking can split on the
        # paragraph break regardless of how many chevrons the captioner
        # used at that moment.
        flat = re.sub(r"\s*>{2,}\s*", "\n\n>> ", flat)
        return flat.strip()

    @staticmethod
    def _fetch_text(url: str) -> str:
        # Seattle Channel + Legistar block default Python UA; use a
        # browser-style UA to avoid sporadic 403s.
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SeattleCouncilmaticBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text


class _ExtractorSkip(Exception):
    """Raised when an event can't be scraped for a benign reason
    (no source URL, no videoid, no SRT on the SC page). Caller logs
    and moves on rather than counting as an error."""
