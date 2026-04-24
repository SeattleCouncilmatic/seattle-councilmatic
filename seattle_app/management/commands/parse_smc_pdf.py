"""Parse the Seattle Municipal Code PDF into MunicipalCodeSection rows.

Typical usage:
    python manage.py parse_smc_pdf _data/seattle_municipal_code_20260421.pdf
    python manage.py parse_smc_pdf <path> --start-page 500 --end-page 600 --dry-run
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

import pdfplumber
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


SECTION_RE = re.compile(r"^(\d+[A-Z]?)\.(\d+[A-Z]?(?:\.\d+)?)\.(\d+[A-Z]?)\s+(.+)$")
# Matches e.g. "23.48.040 Street-facing facade standards",
# "12A.02.010 Title and scope" (Seattle Criminal Code — letter-suffixed title),
# or "23.58A.002 Heights" (letter-suffixed chapter — supplemental chapters
# inserted after original codification).
# Groups: 1=title_number (23 / 12A), 2=chapter tail (48 / 58A / 48.605),
# 3=section tail (040 / 040A), 4=title text

CHAPTER_RE = re.compile(r"^Chapter\s+\d+[A-Z]?\.\d+[A-Z]?\b")
# Matches a chapter heading like "Chapter 25.32 HISTORIC LANDMARKS",
# "Chapter 12A.14 FIREARMS", or "Chapter 23.58A HEIGHTS". Used as a
# section terminator so content from a chapter with no section-
# numbered entries (e.g. a tabular landmarks chapter) doesn't bleed
# into the preceding chapter's last section.

CHAPTER_HEADING_RE = re.compile(
    r"^Chapter\s+(\d+[A-Z]?\.\d+[A-Z]?)"
    r"(?:\s+([A-Z][A-Z\s,\-\'\.\/&]*))?"
    r"\s*$"
)
# Strict form: only matches clean chapter headings — either "Chapter X.Y"
# alone or "Chapter X.Y ALL-CAPS NAME". Used where CHAPTER_RE's tolerance
# causes false positives (TOC scanner state transitions, body-section
# terminator). Body-text cross-references like "Chapter 25.05," or
# "Chapter 23.41." don't reach a clean end, so they fail.

SUBCHAPTER_RE = re.compile(r"^Subchapter\s+[IVXLCDM]+\b")
# Matches a subchapter heading like "Subchapter IX Categorical Exemptions"
# or a bare "Subchapter III". Also a section terminator: without this,
# "Subchapter IX ..." is not recognized as a paragraph boundary, so the
# section that follows it (e.g. 25.05.800) gets rejected by
# _is_section_boundary and its heading + body are appended to the
# preceding section's body instead.

SUBCHAPTER_LINE_RE = re.compile(r"^Subchapter\s+([IVXLCDM]+)(?:\s+(.+?))?\s*$")
# Captures the roman numeral and an optional trailing name.
#   group(2) is None → bare "Subchapter <Roman>" (TOC-style, split layout)
#   group(2) is set  → inline "Subchapter <Roman> <Name>" (body divider)
# Used to distinguish TOC entries from body dividers, since in the PDF's
# column-aware extraction TOCs put the name on the following line.

SECTIONS_MARKER_RE = re.compile(r"^Sections\s*:\s*$", re.IGNORECASE)
# The "Sections:" header that introduces the TOC list inside a chapter.

# Page-header lines we want to strip. Running header format:
#   "<CHAPTER TITLE IN CAPS> <section-number>"
# We detect them as lines where 50%+ of characters are uppercase and the line
# contains a section-number-ish token at the end.
HEADER_RE = re.compile(r"^[A-Z][A-Z\s,\-\'\.\/]+\s+\d+\.\d+")
HEADER_NUM_FIRST_RE = re.compile(
    r"^\d+[A-Z]?\.\d+[A-Z]?(?:\.\d+[A-Z]?)?"
    r"\s+[A-Z][A-Z,\-\'\.\/]*"                # first all-caps token
    r"\s+[A-Z][A-Z\s,\-\'\.\/]*$"              # second all-caps token (+tail)
)
# Number-first running header like "25.05.985 ENVIRONMENTAL PROTECTION AND
# HISTORIC PRESERVATION" that appears on the even side of facing pages.
# HEADER_RE alone only catches the name-first variant. Requiring two
# whitespace-separated all-caps tokens distinguishes real headers (multi-
# word chapter names) from single-word acronym section titles like NEPA
# or SEPA, which must not be filtered here.
# Footer lines like "153 (Seattle 12-23)", "(Seattle3-20)", or
# "(Seattle12-22) 12-48" (edition tag followed by chapter-page identifier).
FOOTER_RE = re.compile(r"^\s*[\d\s\-]*\(Seattle[\s\d\-]+\)[\s\d\-]*$")


def _looks_like_subchapter_name_continuation(line: str) -> bool:
    """True if `line` looks like a wrapped name from a preceding subchapter
    divider. The first section under a subchapter gets rejected by the
    boundary check if a name-wrap line sits between them:

        Subchapter III Categorical Exemptions
        and Threshold Determination            <- continuation
        25.05.300 Purpose                      <- boundary check fails

    To keep the boundary check simple, callers absorb these lines in the
    outer loop. A continuation is any non-empty line that isn't a
    section / chapter / subchapter heading.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if SECTION_RE.match(stripped):
        return False
    if SUBCHAPTER_LINE_RE.match(stripped) or CHAPTER_HEADING_RE.match(stripped):
        return False
    return True


def _is_section_boundary(prev_line: Optional[str]) -> bool:
    """True if prev_line is a paragraph boundary a real section,
    chapter, or subchapter heading can follow.

    Real headings come after one of:
      - the start of the parse range (no prev_line)
      - a sentence terminal or revision parenthetical (. ? ! ))
      - a chapter / subchapter / title / subtitle heading line
      - another section-shaped line (the last TOC entry before the
        chapter body, or the revision note of the prior section)

    Body-text cross-references that wrap onto a new line starting with
    a chapter/subchapter/section number fail — their preceding line is
    a sentence fragment ending on a preposition or citation lead-in
    like "Section", "RCW", "by", "under".
    """
    if prev_line is None:
        return True
    stripped = prev_line.strip()
    if not stripped:
        return True
    if stripped[-1] in ".?!)":
        return True
    if stripped.startswith(("Chapter ", "Subchapter ", "Title ", "Subtitle ")):
        return True
    if SECTION_RE.match(stripped):
        return True
    # All-uppercase standalone lines (no lowercase) are either structural
    # headings or page running headers that leaked through the header
    # filter — e.g. bare "HISTORIC PRESERVATION" when the facing page's
    # heading "ENVIRONMENTAL PROTECTION AND HISTORIC PRESERVATION" splits
    # across columns with no trailing section number to trigger HEADER_RE.
    # Either way no body prose crosses them, so treat as a boundary.
    if not any(c.islower() for c in stripped):
        return True
    return False


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> int:
    """Convert a roman numeral to an integer (I..MMM). Permissive — doesn't
    reject malformed romans; callers feed it the output of a regex that
    already restricted the character set."""
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN_VALUES.get(c, 0)
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total


@dataclass
class _SubchapterDraft:
    """In-memory record of a subchapter collected by _TocScanner. Flushed
    to Subchapter rows via Command._persist_subchapter_drafts."""
    chapter_number: str
    roman: str
    name: str = ""
    toc_source: str = "official"  # official | synthesized
    toc_source_pdf_page: Optional[int] = None
    body_source_pdf_page: Optional[int] = None
    declared_section_numbers: list[str] = field(default_factory=list)


class _TocScanner:
    """Stateful scanner that watches every parsed line in document order
    and accumulates _SubchapterDraft rows for any chapter TOCs it sees.

    A chapter TOC looks like this in column-aware extraction:

        Chapter 25.05                       <- CHAPTER_RE, no trailing text
        ENVIRONMENTAL POLICIES AND          <- chapter name (wraps)
        PROCEDURES
        Sections:                           <- SECTIONS_MARKER_RE
        Subchapter I                        <- SUBCHAPTER_LINE_RE, no name
        Purpose/Authority                   <- subchapter name (may wrap)
        25.05.010 Authority                 <- SECTION_RE, declared entry
        25.05.020 Purpose
        ...
        Subchapter II                       <- next subchapter
        ...

    The TOC ends when an INLINE "Subchapter <Roman> <Name>" divider
    appears (body-format, which puts the roman and name on one line).
    Chapters with no subchapter TOC — or with no TOC at all — produce
    no drafts from the scanner; the body pass will synthesize Subchapter
    rows on the fly via _resolve_body_subchapter.
    """

    _STATE_IDLE = "idle"
    _STATE_AFTER_CHAPTER = "after_chapter"
    _STATE_IN_TOC = "in_toc"
    _STATE_IN_SUBCHAPTER_NAME = "in_subchapter_name"
    _STATE_IN_SUBCHAPTER_SECTIONS = "in_subchapter_sections"

    def __init__(self):
        self.state: str = self._STATE_IDLE
        self.current_chapter: Optional[str] = None
        self.current_draft: Optional[_SubchapterDraft] = None
        self.drafts_by_key: dict[tuple[str, str], _SubchapterDraft] = {}

    def observe(
        self, line: str, page_num: int, prev_line: Optional[str]
    ) -> Optional[tuple[str, str]]:
        """Process one line in document order. Returns the (chapter, roman)
        key if this line was an inline BODY subchapter divider (so the
        caller can update its current-subchapter tracker for FK stamping);
        None otherwise.

        prev_line gates state transitions against body-text cross-references:
        a line that matches CHAPTER_HEADING_RE or SUBCHAPTER_LINE_RE in the
        middle of a paragraph (prev_line doesn't end in .?!)) is text, not
        a heading, and must not advance scanner state.
        """
        stripped = line.strip()
        if not stripped:
            return None

        m_chapter = CHAPTER_HEADING_RE.match(stripped)
        if m_chapter:
            # Strict CHAPTER_HEADING_RE is restrictive enough on its own
            # (requires "Chapter X.Y" alone or "Chapter X.Y ALL-CAPS-NAME"
            # anchored to end of line). Body-text cross-refs like
            # "Chapter 25.05, to facilitate..." fail it outright, so we
            # don't need the additional prev_line boundary check here —
            # and omitting it avoids losing real chapter headings whose
            # prev_line is a wrapped subtitle/title name continuation
            # (e.g. "Subtitle VII" / "Miscellaneous Provisions" /
            # "Chapter 21.68" — the subtitle wrap fails boundary but the
            # chapter heading is real).
            self._finalize_current_draft()
            num, name = m_chapter.group(1), m_chapter.group(2)
            self.current_chapter = num
            # "Chapter X.Y" alone → a TOC may follow. "Chapter X.Y NAME" in
            # one line is a body-style heading; no TOC to scan.
            self.state = (
                self._STATE_IDLE if name else self._STATE_AFTER_CHAPTER
            )
            return None

        if SECTIONS_MARKER_RE.match(stripped):
            if self.state == self._STATE_AFTER_CHAPTER:
                self.state = self._STATE_IN_TOC
            return None

        m_sub = SUBCHAPTER_LINE_RE.match(stripped)
        if m_sub:
            roman, name = m_sub.group(1), m_sub.group(2)
            if name:
                # Candidate inline body divider — only real if either
                #   (a) we're still inside a TOC for this chapter, so this
                #       is the TOC->body transition (prev_line is often a
                #       wrapped TOC title continuation like "training" and
                #       fails the plain boundary check), OR
                #   (b) the preceding line was a paragraph boundary.
                # This keeps body-text cross-refs like "Subchapter VIII of
                # this Chapter 25.05" out, since by the time we see those
                # we've long since exited TOC state (the first real body
                # divider switches state to IDLE).
                in_toc_state = self.state in (
                    self._STATE_AFTER_CHAPTER,
                    self._STATE_IN_TOC,
                    self._STATE_IN_SUBCHAPTER_NAME,
                    self._STATE_IN_SUBCHAPTER_SECTIONS,
                )
                if not in_toc_state and not _is_section_boundary(prev_line):
                    return None
                self._finalize_current_draft()
                self.state = self._STATE_IDLE
                if not self.current_chapter:
                    return None
                key = (self.current_chapter, roman)
                draft = self.drafts_by_key.get(key)
                if draft is None:
                    # No TOC preceded this divider (chapter without a TOC, or
                    # TOC didn't list this subchapter) — synthesize.
                    draft = _SubchapterDraft(
                        chapter_number=self.current_chapter,
                        roman=roman,
                        name=name.strip(),
                        toc_source="synthesized",
                        body_source_pdf_page=page_num,
                    )
                    self.drafts_by_key[key] = draft
                else:
                    draft.body_source_pdf_page = page_num
                    if not draft.name:
                        draft.name = name.strip()
                return key
            # Bare "Subchapter <Roman>" — only meaningful when we're in a
            # TOC for a known chapter. Outside that, ignore it.
            if self.current_chapter and self.state in (
                self._STATE_AFTER_CHAPTER,
                self._STATE_IN_TOC,
                self._STATE_IN_SUBCHAPTER_NAME,
                self._STATE_IN_SUBCHAPTER_SECTIONS,
            ):
                self._finalize_current_draft()
                self.current_draft = _SubchapterDraft(
                    chapter_number=self.current_chapter,
                    roman=roman,
                    toc_source="official",
                    toc_source_pdf_page=page_num,
                )
                self.state = self._STATE_IN_SUBCHAPTER_NAME
            return None

        m_section = SECTION_RE.match(stripped)
        if m_section and self.current_draft is not None and self.state in (
            self._STATE_IN_SUBCHAPTER_NAME,
            self._STATE_IN_SUBCHAPTER_SECTIONS,
        ):
            title_num, chap_tail, sec_tail, _ = m_section.groups()
            sec_num = f"{title_num}.{chap_tail}.{sec_tail}"
            # setdefault-style: duplicates from TOC wrap quirks become no-ops
            if sec_num not in self.current_draft.declared_section_numbers:
                self.current_draft.declared_section_numbers.append(sec_num)
            self.state = self._STATE_IN_SUBCHAPTER_SECTIONS
            return None

        # Any other line:
        if self.state == self._STATE_IN_SUBCHAPTER_NAME and self.current_draft is not None:
            # Continuation of the subchapter's name.
            self.current_draft.name = (
                (self.current_draft.name + " " + stripped).strip()
            )
        return None

    def _finalize_current_draft(self):
        if self.current_draft is not None:
            key = (self.current_draft.chapter_number, self.current_draft.roman)
            # If a later duplicate appears (e.g. re-entering a TOC on re-parse
            # of overlapping ranges), prefer the most-recent scan.
            self.drafts_by_key[key] = self.current_draft
            self.current_draft = None


@dataclass
class ParsedSection:
    title_number: str
    chapter_number: str
    section_number: str
    title: str
    source_pdf_page: int
    text_lines: list[str] = field(default_factory=list)
    subchapter_key: Optional[tuple[str, str]] = None
    # (chapter_number, roman) — resolved to a Subchapter row during _persist.

    @property
    def full_text(self) -> str:
        return "\n".join(self.text_lines).strip()


class Command(BaseCommand):
    help = "Parse the Seattle Municipal Code PDF into MunicipalCodeSection rows."

    def add_arguments(self, parser):
        parser.add_argument("pdf_path", help="Path to the SMC PDF file.")
        parser.add_argument(
            "--start-page",
            type=int,
            default=1,
            help="First page (1-indexed) to parse. Useful for testing on a range.",
        )
        parser.add_argument(
            "--end-page",
            type=int,
            default=None,
            help="Last page (1-indexed, inclusive) to parse. Defaults to end of PDF.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after N sections have been emitted.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report counts without writing to the database.",
        )
        parser.add_argument(
            "--verbose-sections",
            action="store_true",
            help="Print each section header as it is emitted.",
        )
        parser.add_argument(
            "--skip-ordinance-refs",
            action="store_true",
            help="Don't extract SectionOrdinanceRef rows during the parse. "
                 "Refs can be populated separately via extract_ordinance_refs.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import MunicipalCodeSection

        pdf_path = opts["pdf_path"]
        start_page = max(1, opts["start_page"])
        end_page = opts["end_page"]
        limit = opts["limit"]
        dry_run = opts["dry_run"]
        verbose_sections = opts["verbose_sections"]
        extract_refs = not opts["skip_ordinance_refs"]

        try:
            pdf = pdfplumber.open(pdf_path)
        except FileNotFoundError:
            raise CommandError(f"PDF not found: {pdf_path}")

        total_pages = len(pdf.pages)
        if end_page is None or end_page > total_pages:
            end_page = total_pages
        if start_page > end_page:
            raise CommandError(
                f"start_page {start_page} > end_page {end_page}"
            )

        self.stdout.write(
            f"Parsing pages {start_page}–{end_page} of {total_pages} "
            f"({'DRY RUN' if dry_run else 'writing to DB'})"
        )

        counts = {"emitted": 0, "created": 0, "updated_text": 0, "unchanged": 0}
        current_title: Optional[str] = None
        title_section_count = 0

        # Fresh state per run. _toc_scanner is driven by _walk_sections; the
        # cache backs _resolve_subchapter to keep DB hits to one per key.
        self._toc_scanner = _TocScanner()
        self._subchapter_cache: dict[tuple[str, str], object] = {}

        try:
            for section in self._walk_sections(pdf, start_page, end_page):
                counts["emitted"] += 1

                if section.title_number != current_title:
                    if current_title is not None:
                        self.stdout.write(
                            f"Title {current_title}: finished "
                            f"({title_section_count} sections)"
                        )
                    self.stdout.write(
                        f"Title {section.title_number}: started at page "
                        f"{section.source_pdf_page}"
                    )
                    current_title = section.title_number
                    title_section_count = 0
                title_section_count += 1

                if verbose_sections:
                    # section_number is already the full hierarchy
                    # (e.g. "4.04.160"). title_number and chapter_number are
                    # stored separately but prefix the section_number.
                    self.stdout.write(
                        f"  [p{section.source_pdf_page:>5}] "
                        f"{section.section_number} — {section.title[:70]}"
                    )
                if not dry_run:
                    self._persist(section, MunicipalCodeSection, counts, extract_refs)
                if limit and counts["emitted"] >= limit:
                    self.stdout.write(self.style.WARNING(f"Reached --limit {limit}, stopping."))
                    break

            if current_title is not None:
                self.stdout.write(
                    f"Title {current_title}: finished "
                    f"({title_section_count} sections)"
                )
        finally:
            pdf.close()

        summary = (
            f"Done. Emitted {counts['emitted']} sections "
            f"(new={counts['created']}, text-updated={counts['updated_text']}, "
            f"unchanged={counts['unchanged']})"
        )
        if extract_refs:
            summary += (
                f" | refs_synced={counts.get('refs_synced', 0)} "
                f"across {counts.get('sections_with_refs', 0)} sections"
            )
        self.stdout.write(self.style.SUCCESS(summary))

        if not dry_run:
            unref = self._flush_unreferenced_drafts()
            stale = self._cleanup_stale_duplicates()
            vcounts = self._run_validation()
            sc_total = len(self._subchapter_cache)
            official = sum(
                1 for r in self._subchapter_cache.values()
                if getattr(r, "toc_source", None) == "official"
            )
            synth = sc_total - official
            self.stdout.write(
                f"Subchapters: {sc_total} total ({official} official, "
                f"{synth} synthesized); {unref} declared-but-empty "
                f"subchapters flushed without body sections; "
                f"{stale} stale duplicate(s) cleaned up."
            )
            issue_total = vcounts["missing_from_body"] + vcounts["undeclared_in_toc"]
            if issue_total:
                self.stdout.write(self.style.WARNING(
                    f"Validation: {issue_total} issue(s) — "
                    f"{vcounts['missing_from_body']} missing_from_body, "
                    f"{vcounts['undeclared_in_toc']} undeclared_in_toc. "
                    f"See ParseValidationIssue rows."
                ))
            else:
                self.stdout.write("Validation: no TOC/body mismatches.")

    # ------------------------------------------------------------------
    # Page → line extraction

    def _walk_sections(
        self,
        pdf,
        start_page: int,
        end_page: int,
    ) -> Iterator[ParsedSection]:
        """Yield ParsedSection objects in document order.

        Also drives self._toc_scanner (attached by handle()) so every line
        gets observed for TOC structure, and tracks the currently-active
        body subchapter so emitted sections can be stamped with a FK key.
        """
        current: Optional[ParsedSection] = None
        prev_line: Optional[str] = None
        current_body_subchapter_key: Optional[tuple[str, str]] = None

        for page_num in range(start_page, end_page + 1):
            page = pdf.pages[page_num - 1]
            lines = self._extract_page_lines(page)
            # pdfplumber caches parsed chars/lines/rects/curves per Page and
            # never evicts them. Over thousands of pages that turns into
            # swap thrashing and eventually OOM — flush once we're done
            # with the page since we never revisit.
            page.flush_cache()

            i = 0
            while i < len(lines):
                line = lines[i]
                # The TOC scanner sees every line first. It returns a
                # subchapter key only when the line is an inline body
                # divider (e.g. "Subchapter IX Categorical Exemptions"),
                # which is also the signal to update FK tracking.
                divider_key = self._toc_scanner.observe(line, page_num, prev_line)
                if divider_key is not None:
                    current_body_subchapter_key = divider_key
                # A new chapter resets the active body subchapter: the next
                # chapter starts with no subchapter context until its own
                # first divider fires. Use strict heading regex + boundary
                # check so body-text cross-references ("Chapter 25.05, to
                # facilitate...") don't spuriously clear the tracker.
                if (
                    CHAPTER_HEADING_RE.match(line)
                    and _is_section_boundary(prev_line)
                ):
                    current_body_subchapter_key = None

                m = SECTION_RE.match(line)
                raw_title = m.group(4) if m else ""
                # 23.84A (Definitions) titles sections with quoted single
                # letters like '"A."' to group definitions alphabetically —
                # skip a leading quote when checking the opening letter, and
                # size the short-title bypass against the title with any
                # surrounding quotes stripped so '"A."' (4 chars) counts as
                # a 2-char bare title.
                first_letter = raw_title.lstrip(" \"'")[:1]
                bare_title = raw_title.strip().strip("\"'")
                # Compact all-caps acronym titles like "NEPA", "SEPA", "FEIS".
                # These pass the isupper() check but fail the has-lowercase
                # rule and exceed the 3-char short-title bypass. Allow them
                # explicitly: single word, letters only, <= 6 chars. Multi-
                # word all-caps like "ENVIRONMENTAL PROTECTION" stay rejected
                # because they contain whitespace and fail isalpha().
                is_acronym_title = (
                    0 < len(bare_title) <= 6
                    and bare_title.isalpha()
                    and bare_title.isupper()
                )
                if (
                    m
                    and first_letter.isupper()
                    and (
                        len(bare_title) <= 3
                        or any(c.islower() for c in raw_title)
                        or is_acronym_title
                    )
                    and _is_section_boundary(prev_line)
                    and not self._is_toc_entry(lines, i, prev_line)
                ):
                    # Valid section heading: starts with a capital letter
                    # (possibly after an opening quote) and either is very
                    # short (e.g. '"A."' in an alphabetical definitions
                    # chapter like 23.84A) or has mixed case, and sits at
                    # a paragraph boundary.
                    # Rules out:
                    #   - Running-header "<num> <CHAPTER NAME IN CAPS>" (no
                    #     lowercase, and multi-word so not under the 3-char
                    #     short-title bypass)
                    #   - Body-text cross-references like "3.70.100 and
                    #     3.70.160 to initiate..." that happen to start a line
                    #     after a column break (title starts with lowercase "and")
                    #   - Wrapped citations like "...SMC Section" \n "11.82.340
                    #     A (Suspension...)" — preceding line is a sentence
                    #     fragment, not a paragraph terminal.
                    # Chapter TOCs are skipped separately via _is_toc_entry.
                    if current is not None:
                        yield current
                    title_num, chap_tail, sec_tail, title = m.groups()
                    title = title.strip()
                    # Handle soft-hyphen wraps: long section titles split across
                    # two lines end with "-"; fold the next line in.
                    if title.endswith("-") and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        title = title[:-1] + next_line
                        i += 1
                    full_section = f"{title_num}.{chap_tail}.{sec_tail}"
                    chapter_number = f"{title_num}.{chap_tail}"
                    # Only stamp a subchapter_key if the divider's chapter
                    # agrees with this section's chapter. A body divider
                    # whose chapter doesn't match would indicate either a
                    # cross-chapter reference or a parser misattribution.
                    sc_key: Optional[tuple[str, str]] = None
                    if (
                        current_body_subchapter_key is not None
                        and current_body_subchapter_key[0] == chapter_number
                    ):
                        sc_key = current_body_subchapter_key
                    current = ParsedSection(
                        title_number=title_num,
                        chapter_number=chapter_number,
                        section_number=full_section,
                        title=title,
                        source_pdf_page=page_num,
                        subchapter_key=sc_key,
                    )
                elif (
                    (CHAPTER_HEADING_RE.match(line) or SUBCHAPTER_RE.match(line))
                    and _is_section_boundary(prev_line)
                ):
                    # Chapter / subchapter heading closes the current section
                    # so a non-sectioned chapter (tables, figures) or a
                    # subchapter divider can't bleed its content into the
                    # preceding section's body. Strict CHAPTER_HEADING_RE +
                    # boundary check prevents body-text cross-references like
                    # "Subchapter VIII of this Chapter 25.05" from falsely
                    # terminating the current section.
                    if current is not None:
                        yield current
                        current = None
                    if SUBCHAPTER_RE.match(line):
                        # Body subchapter names often wrap onto a second
                        # line (e.g. "Subchapter III Categorical Exemptions"
                        # / "and Threshold Determination"). Absorb up to 2
                        # continuation lines so the first section under
                        # the subchapter sees the divider as its boundary.
                        consumed = 0
                        while consumed < 2 and i + 1 < len(lines) and (
                            _looks_like_subchapter_name_continuation(lines[i + 1])
                        ):
                            i += 1
                            consumed += 1
                        prev_line = line  # effective prev is the divider
                        i += 1
                        continue
                elif current is not None:
                    current.text_lines.append(line)
                # Lines before the first section-heading in the range are dropped
                prev_line = lines[i]
                i += 1

        if current is not None:
            yield current

    def _extract_page_lines(self, page) -> list[str]:
        """Return the page's body lines in reading order, headers/footers stripped.

        SMC body pages are two-column. We split by the page midpoint, extract
        words in each half, group into lines by Y-position, then concatenate
        left column then right column. Running header and footer lines are
        dropped via regex.
        """
        try:
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
        except Exception:
            return []

        # Sparse pages (chapter-end/transition pages with a handful of
        # words) aren't really two-column — title lines can span the full
        # page width, and splitting at page.width/2 orphans the tail word
        # into the "right" column (e.g. p4164 splits "Notice of assumption
        # of lead agency status" as left:"... agency" / right:"status",
        # which then bleeds across pages and breaks the next section's
        # boundary check). Fall back to single-column reading order below
        # a threshold.
        if len(words) < 30:
            lines = self._words_to_lines(words)
        else:
            mid_x = page.width / 2
            left = [w for w in words if (w["x0"] + w["x1"]) / 2 < mid_x]
            right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= mid_x]
            lines = self._words_to_lines(left) + self._words_to_lines(right)
        return [ln for ln in lines if not self._is_header_or_footer(ln)]

    @staticmethod
    def _words_to_lines(words: list[dict]) -> list[str]:
        if not words:
            return []
        # Bucket words into lines by rounded y-position. /3 tolerates baseline
        # wobble within a line; adjust if extraction looks off.
        words = sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
        lines: list[str] = []
        current_bucket: Optional[int] = None
        current_words: list[str] = []
        for w in words:
            bucket = round(w["top"] / 3)
            if current_bucket is None or bucket == current_bucket:
                current_words.append(w["text"])
                current_bucket = bucket
            else:
                lines.append(" ".join(current_words))
                current_words = [w["text"]]
                current_bucket = bucket
        if current_words:
            lines.append(" ".join(current_words))
        return lines

    @staticmethod
    def _is_toc_entry(
        lines: list[str], i: int, prev_line: Optional[str]
    ) -> bool:
        """True if the section-heading at lines[i] is really a TOC entry.

        Chapter tables of contents list every section back-to-back with
        no body text between entries. A TOC middle entry therefore has
        BOTH a section-shaped line immediately before it and a section-
        shaped line immediately after it. Body sections (even terse ones
        like "22.801.110 Reserved.") sit after body text that ends in a
        sentence terminal or revision paren, so their prev line is not
        section-shaped.

        The first and last entries of a TOC run fall through — they get
        emitted, but the body pass overwrites them via _persist.

        Soft-hyphen title wraps insert one continuation line (the heading
        ends with "-"), so in that case we check lines[i+2] instead.

        A prior implementation looked 3 lines ahead, which over-rejected
        terse-but-real sections whose body was shorter than the lookahead
        — those got absorbed into the preceding section's body.
        """
        if i >= len(lines):
            return False
        offset = 2 if lines[i].rstrip().endswith("-") else 1
        j = i + offset
        if j >= len(lines):
            return False
        next_is_section = SECTION_RE.match(lines[j]) is not None
        prev_is_section = (
            prev_line is not None
            and SECTION_RE.match(prev_line.strip()) is not None
        )
        return next_is_section and prev_is_section

    @staticmethod
    def _is_header_or_footer(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if FOOTER_RE.match(stripped):
            return True
        no_lowercase = not any(c.islower() for c in stripped)
        if HEADER_RE.match(stripped) and no_lowercase:
            # Name-first running header "ENVIRONMENTAL PROTECTION AND
            # HISTORIC PRESERVATION CODE 25.05.800". True section headings
            # also match partly — but the no-lowercase guard protects them
            # since real section titles contain lowercase words.
            return True
        if HEADER_NUM_FIRST_RE.match(stripped) and no_lowercase:
            # Number-first running header "25.05.985 ENVIRONMENTAL
            # PROTECTION AND HISTORIC PRESERVATION" on even-side pages.
            # Same no-lowercase guard — real all-caps section titles (very
            # rare) would slip through, but acronym-only titles like NEPA
            # are rejected here correctly because HEADER_NUM_FIRST_RE's
            # tail requires at least two all-caps tokens with a space.
            return True
        return False

    # ------------------------------------------------------------------
    # Persistence

    @transaction.atomic
    def _persist(self, section: ParsedSection, Model, counts: dict, extract_refs: bool) -> None:
        """Create or update a MunicipalCodeSection, preserving LLM fields
        when the full_text has not changed. When extract_refs is true,
        also sync the section's SectionOrdinanceRef rows for new sections
        and for sections whose text has changed.

        The subchapter FK is resolved and saved on EVERY row whose key is
        present on the ParsedSection, even when the full_text is otherwise
        unchanged — otherwise re-parses couldn't repair rows where the FK
        drifted (e.g. when the parser is updated to detect a subchapter
        that an earlier parse missed).
        """
        from seattle_app.models import SectionOrdinanceRef

        sc_row = (
            self._resolve_subchapter(section.subchapter_key)
            if section.subchapter_key else None
        )

        key = dict(
            title_number=section.title_number,
            chapter_number=section.chapter_number,
            section_number=section.section_number,
        )
        try:
            existing = Model.objects.get(**key)
        except Model.DoesNotExist:
            existing = None

        if existing is None:
            row = Model.objects.create(
                **key,
                title=section.title,
                full_text=section.full_text,
                source_pdf_page=section.source_pdf_page,
                subchapter=sc_row,
            )
            counts["created"] += 1
            if extract_refs:
                Command._sync_refs(row, section.full_text, SectionOrdinanceRef, counts)
            return

        fk_target = sc_row.id if sc_row is not None else None
        fk_changed = existing.subchapter_id != fk_target

        if existing.full_text == section.full_text:
            # Same content. Touch the source page in case it shifted and the
            # subchapter FK if it drifted; preserve plain_summary etc.
            update_fields: list[str] = []
            if existing.source_pdf_page != section.source_pdf_page:
                existing.source_pdf_page = section.source_pdf_page
                update_fields.append("source_pdf_page")
            if fk_changed:
                existing.subchapter = sc_row
                update_fields.append("subchapter")
            if update_fields:
                existing.save(update_fields=update_fields)
            counts["unchanged"] += 1
            return

        # Text changed: update text + title + source page + subchapter,
        # clear stale summary.
        existing.title = section.title
        existing.full_text = section.full_text
        existing.source_pdf_page = section.source_pdf_page
        existing.subchapter = sc_row
        existing.plain_summary = ""
        existing.summary_model = ""
        existing.summary_generated_at = None
        existing.save(
            update_fields=[
                "title",
                "full_text",
                "source_pdf_page",
                "subchapter",
                "plain_summary",
                "summary_model",
                "summary_generated_at",
            ]
        )
        counts["updated_text"] += 1
        if extract_refs:
            Command._sync_refs(existing, section.full_text, SectionOrdinanceRef, counts)

    def _resolve_subchapter(self, key: tuple[str, str]):
        """Return the Subchapter row for (chapter_number, roman), creating
        or updating one from the TOC scanner's draft if needed. Cached
        per parse run to avoid repeated lookups."""
        from seattle_app.models import Subchapter

        cached = self._subchapter_cache.get(key)
        if cached is not None:
            return cached

        chapter_number, roman = key
        draft = self._toc_scanner.drafts_by_key.get(key)

        if draft is not None:
            row, _ = Subchapter.objects.update_or_create(
                chapter_number=chapter_number,
                roman=roman,
                defaults={
                    "ordinal": roman_to_int(roman),
                    "name": draft.name,
                    "toc_source": draft.toc_source,
                    "toc_source_pdf_page": draft.toc_source_pdf_page,
                    "body_source_pdf_page": draft.body_source_pdf_page,
                    "declared_section_numbers": draft.declared_section_numbers,
                },
            )
        else:
            # Defensive: a body divider fired without the scanner recording
            # anything. Shouldn't happen in practice, but don't drop the FK.
            row, _ = Subchapter.objects.get_or_create(
                chapter_number=chapter_number,
                roman=roman,
                defaults={
                    "ordinal": roman_to_int(roman),
                    "toc_source": Subchapter.SOURCE_SYNTHESIZED,
                },
            )

        self._subchapter_cache[key] = row
        return row

    def _cleanup_stale_duplicates(self) -> int:
        """Delete Subchapter rows whose (body_source_pdf_page, roman) pair
        matches a sibling row with more stamped sections.

        Triggered when an earlier parse misattributed a subchapter to the
        wrong chapter (e.g. 23.48's dividers got stored under 23.47A before
        a later fix corrected chapter detection). update_or_create keys on
        (chapter_number, roman), so the fixed run writes a new row rather
        than updating the stale one; this pass resolves the split.
        """
        from seattle_app.models import Subchapter
        from collections import defaultdict

        groups: dict[tuple[int, str], list] = defaultdict(list)
        for sc in Subchapter.objects.exclude(body_source_pdf_page__isnull=True):
            groups[(sc.body_source_pdf_page, sc.roman)].append(sc)

        deleted = 0
        for siblings in groups.values():
            if len(siblings) <= 1:
                continue
            # Keep the row with the most linked sections; if all tie at 0,
            # keep the one most recently created (highest pk).
            ranked = sorted(
                siblings,
                key=lambda s: (s.sections.count(), s.pk),
                reverse=True,
            )
            for loser in ranked[1:]:
                if loser.sections.count() == 0:
                    loser.delete()  # CASCADE drops its ParseValidationIssue rows
                    deleted += 1
        return deleted

    def _flush_unreferenced_drafts(self) -> int:
        """Persist any TOC drafts that were never referenced by a body
        section (subchapter declared in the TOC but no emitted section
        stamped to it). Without this, the validation pass wouldn't see
        them as official subchapters with their declared list."""
        flushed = 0
        for key in list(self._toc_scanner.drafts_by_key):
            if key not in self._subchapter_cache:
                self._resolve_subchapter(key)
                flushed += 1
        return flushed

    def _run_validation(self) -> dict[str, int]:
        """Diff each official Subchapter's declared_section_numbers against
        the sections actually stamped to it. Writes one ParseValidationIssue
        row per mismatch. Returns a summary dict for the caller."""
        from seattle_app.models import ParseValidationIssue, Subchapter

        counts = {"missing_from_body": 0, "undeclared_in_toc": 0}
        with transaction.atomic():
            # Full refresh: old issues don't survive across runs.
            ParseValidationIssue.objects.all().delete()

            new_rows: list[ParseValidationIssue] = []
            official = Subchapter.objects.filter(
                toc_source=Subchapter.SOURCE_OFFICIAL
            ).prefetch_related("sections")
            for sc in official:
                declared = set(sc.declared_section_numbers)
                actual = set(sc.sections.values_list("section_number", flat=True))
                for sn in sorted(declared - actual):
                    new_rows.append(ParseValidationIssue(
                        subchapter=sc,
                        category=ParseValidationIssue.CAT_MISSING_FROM_BODY,
                        section_number=sn,
                        message=f"{sn} declared in TOC but not emitted by body parse",
                    ))
                    counts["missing_from_body"] += 1
                for sn in sorted(actual - declared):
                    new_rows.append(ParseValidationIssue(
                        subchapter=sc,
                        category=ParseValidationIssue.CAT_UNDECLARED_IN_TOC,
                        section_number=sn,
                        message=f"{sn} emitted by body parse but not declared in TOC",
                    ))
                    counts["undeclared_in_toc"] += 1
            if new_rows:
                ParseValidationIssue.objects.bulk_create(new_rows)
        return counts

    @staticmethod
    def _sync_refs(section_row, full_text: str, RefModel, counts: dict) -> None:
        """Replace SectionOrdinanceRef rows for this section with a fresh
        extraction from full_text. Atomic swap within the caller's
        transaction so partial states aren't observable."""
        from seattle_app.services.ordinance_refs import extract_ordinance_refs

        refs = extract_ordinance_refs(full_text)
        RefModel.objects.filter(section=section_row).delete()
        if refs:
            RefModel.objects.bulk_create([
                RefModel(
                    section=section_row,
                    ordinance_number=r.ordinance_number,
                    section_reference=r.section_reference,
                    ordinance_year=r.ordinance_year,
                )
                for r in refs
            ])
            counts["refs_synced"] = counts.get("refs_synced", 0) + len(refs)
            counts["sections_with_refs"] = counts.get("sections_with_refs", 0) + 1
