"""Parse the Detailed Table of Contents from the SMC PDF (pages
149-168 of the 20260421 snapshot) and populate CodeTitle + CodeChapter
rows with human-readable names.

    python manage.py extract_smc_toc
    python manage.py extract_smc_toc --pdf _data/seattle_municipal_code_20260421.pdf
    python manage.py extract_smc_toc --start-page 149 --end-page 168 --dry-run

The TOC has two title formats:
  - Two-line: 'Title 1' on its own line, then 'GENERAL PROVISIONS'
  - One-line: 'Title 12A CRIMINAL CODE' (number and name together)

Chapter rows look like '<num> <name (possibly wrapping)> <vol-roman>
<page>'. Names that wrap append the next line's text up to the
roman-vol-page tail. Subtitle / Division dividers within a title's
chapter list are skipped (chapter-level only, today).
"""

import re
from pathlib import Path

import pdfplumber
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from seattle_app.models import CodeTitle, CodeChapter


DEFAULT_PDF_PATH = "_data/seattle_municipal_code_20260421.pdf"
DEFAULT_START = 149
DEFAULT_END = 168

# 'Title 1' or 'Title 12A' or 'Title 12A CRIMINAL CODE'
TITLE_RE = re.compile(r'^Title\s+(\S+)(?:\s+(.+))?$')

# Chapter row: '<num> <name> <roman-vol> <page>'
# Number: digits, optional letter, dot, digits, optional letter (e.g.
# '1.01', '23.47A', '12A.04').
CHAPTER_RE = re.compile(
    r'^(\d+(?:[A-Z])?\.\d+(?:[A-Z])?)\s+'
    r'(.+?)\s+'
    r'([IVX]+)\s+'
    r'(\S+)$'
)
# Continuation tail: a wrapped chapter row finishes with just '<roman> <page>'
TAIL_RE = re.compile(r'^(.+?)\s+([IVX]+)\s+(\S+)$')

# Junk lines to skip — prefix match (footers like 'TC-1 (Seattle 6-25)'
# combine the page-corner ID and edition stamp on one line).
JUNK_RE = re.compile(
    r'^(?:DETAILED TABLE OF CONTENTS|Page$|Vol\. No\.|TC-|\(Seattle )'
)
# In-title structural dividers we don't capture today. No trailing \b
# because '(Reserved)' / 'Chapters:' end with non-word chars and \b
# fails at non-word/non-word boundaries.
DIVIDER_RE = re.compile(
    r'^(?:Chapters:|Articles:|\(Reserved\)|Subtitle\s|Division\s|Subchapter\s)'
)
# Section endings — stop processing when we see these.
END_MARKERS_RE = re.compile(r'^(Table of Ordinances Codified|Index|Zoning Index)\b')


class Command(BaseCommand):
    help = "Populate CodeTitle and CodeChapter from the SMC PDF's Detailed Table of Contents."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", default=DEFAULT_PDF_PATH, help=f"Path to SMC PDF (default: {DEFAULT_PDF_PATH})")
        parser.add_argument("--start-page", type=int, default=DEFAULT_START)
        parser.add_argument("--end-page", type=int, default=DEFAULT_END)
        parser.add_argument("--dry-run", action="store_true", help="Print what would be persisted, don't write")

    def handle(self, *args, **opts):
        pdf_path = Path(opts["pdf"])
        if not pdf_path.exists():
            raise CommandError(f"PDF not found: {pdf_path}")

        lines = self._collect_lines(pdf_path, opts["start_page"], opts["end_page"])
        titles, chapters = self._parse(lines)

        self.stdout.write(f"Parsed {len(titles)} titles, {len(chapters)} chapters")

        if opts["dry_run"]:
            for tn, name in titles:
                self.stdout.write(f"  Title {tn}: {name}")
            for cn, tn, name in chapters:
                self.stdout.write(f"    {cn} ({tn}): {name}")
            return

        with transaction.atomic():
            for tn, name in titles:
                CodeTitle.objects.update_or_create(title_number=tn, defaults={"name": name})
            for cn, tn, name in chapters:
                CodeChapter.objects.update_or_create(
                    chapter_number=cn,
                    defaults={"title_number": tn, "name": name},
                )

        self.stdout.write(self.style.SUCCESS(
            f"Persisted {len(titles)} titles and {len(chapters)} chapters."
        ))

    def _collect_lines(self, pdf_path: Path, start: int, end: int) -> list[str]:
        out = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num in range(start, end + 1):
                text = pdf.pages[page_num - 1].extract_text() or ''
                for line in text.splitlines():
                    line = line.strip()
                    if not line or JUNK_RE.match(line):
                        continue
                    if END_MARKERS_RE.match(line):
                        return out
                    out.append(line)
        return out

    def _parse(self, lines: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
        """Walk lines with a small state machine. State 'awaiting_title_name'
        is set after seeing a bare 'Title N' line; the next non-junk lines
        accumulate into the title name until 'Chapters:' / '(Reserved)' /
        another 'Title' / a chapter row.
        """
        titles: list[tuple[str, str]] = []
        chapters: list[tuple[str, str, str]] = []

        current_title: str | None = None
        title_name_buf: list[str] = []      # accumulating multi-line title name
        awaiting_title_name = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Title heading
            m = TITLE_RE.match(line)
            if m:
                # Flush any pending title-name buffer (rare — happens when the
                # previous title had no chapters, e.g. Title 24 (Reserved)).
                self._flush_title_name(titles, current_title, title_name_buf)
                current_title = m.group(1)
                title_name_buf = []
                inline_name = (m.group(2) or '').strip()
                if inline_name:
                    title_name_buf.append(inline_name)
                    awaiting_title_name = False
                else:
                    awaiting_title_name = True
                i += 1
                continue

            # Title-name accumulator: lines following a bare 'Title N' until
            # we hit a chapter row or 'Chapters:' divider.
            if awaiting_title_name:
                if DIVIDER_RE.match(line) or CHAPTER_RE.match(line):
                    awaiting_title_name = False
                    self._flush_title_name(titles, current_title, title_name_buf)
                    title_name_buf = []
                    # fall through to handle this line below
                else:
                    # Soft-hyphen fold: 'PRESERVA-' + 'TION' -> 'PRESERVATION'
                    text = line
                    if title_name_buf and title_name_buf[-1].endswith('-'):
                        title_name_buf[-1] = title_name_buf[-1][:-1] + text
                    else:
                        title_name_buf.append(text)
                    i += 1
                    continue

            # Skip dividers without state change.
            if DIVIDER_RE.match(line):
                i += 1
                continue

            # Chapter row.
            cm = CHAPTER_RE.match(line)
            if cm:
                chap_num = cm.group(1)
                chap_name = cm.group(2).strip()
                chapters.append((chap_num, current_title or '', chap_name))
                i += 1
                continue

            # Wrapped chapter name: previous line started a chapter without
            # the trailing roman+page. Look back at the last chapter, see if
            # its name actually ended where it should have, and if not, fold
            # the next-line continuation.
            #
            # Simpler heuristic: if THIS line has the tail shape (text +
            # roman + page) and the previous line was non-chapter prose,
            # then back-track. We avoid this by detecting the wrap forward:
            # when we see a chapter-prefixed line that DOESN'T match
            # CHAPTER_RE (because the tail is on the next line), fold.
            partial_chap = re.match(
                r'^(\d+(?:[A-Z])?\.\d+(?:[A-Z])?)\s+(.+?)$',
                line,
            )
            if partial_chap and i + 1 < len(lines):
                # peek the next line — if it has tail shape, fold
                tail = TAIL_RE.match(lines[i + 1])
                if tail:
                    chap_num = partial_chap.group(1)
                    name_head = partial_chap.group(2).strip()
                    name_tail = tail.group(1).strip()
                    # Soft-hyphen fold across the line break
                    if name_head.endswith('-'):
                        chap_name = name_head[:-1] + name_tail
                    else:
                        chap_name = f"{name_head} {name_tail}"
                    chapters.append((chap_num, current_title or '', chap_name))
                    i += 2
                    continue

            # Anything else (orphan continuation, unknown line) — skip.
            i += 1

        # Flush any trailing title name
        self._flush_title_name(titles, current_title, title_name_buf)
        return titles, chapters

    @staticmethod
    def _flush_title_name(titles, current_title, buf):
        if not current_title or not buf:
            return
        # Join, normalize whitespace
        name = ' '.join(buf).strip()
        # Drop already-flushed dupes (defensive)
        if titles and titles[-1][0] == current_title:
            return
        titles.append((current_title, name))
