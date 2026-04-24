"""Extract the Table of Ordinances Codified from the SMC PDF into
OrdinanceCodification rows.

Typical usage:
    python manage.py extract_ordinance_codifications --pdf _data/seattle_municipal_code_20260421.pdf
    python manage.py extract_ordinance_codifications --pdf <path> --pdf-scan-start 4390
    python manage.py extract_ordinance_codifications --pdf <path> --dry-run

Scans the PDF forward for a page containing 'TABLE OF ORDINANCES CODIFIED'
(normalized for whitespace, since the SMC PDF's mixed editions sometimes
drop spaces between words) and continues as long as each page has the
'ORDINANCES CODIFIED' running header. Each row in the two-column layout
becomes one OrdinanceCodification: ordinance_number, description, and
SMC refs extracted from the description.

Ordinance identifiers include initiatives ('I-137') as well as plain
numeric ordinances — the regex allows an optional single-letter prefix.

Glyph fidelity: the SMC PDF fails to decode '§' and en-dashes on these
pages, so descriptions may contain replacement characters. The raw text
is stored as-is; UI code can clean up for display.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterator, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# Discovery anchors — whitespace-normalized match.
_TOC_TITLE = "tableofordinancescodified"
_RUNNING_HEADER = "ordinancescodified"

# Matches an ordinance identifier: either plain digits (e.g. "127091") or
# a one-letter prefix like "I-137" (initiative). Stays conservative about
# length to avoid matching stray numbers inside descriptions.
_ORD_ID_RE = re.compile(r"^[A-Z]?-?\d{1,6}$")

# Extracts SMC chapter/section refs from a description. Matches any dotted
# numeric token that looks like an SMC reference, from 2-part (chapter
# '25.32') through 4-part with letter modifier ('20.37.040.K').
_SMC_REF_RE = re.compile(
    r"(?<![.\d])"                                          # boundary: not a bigger number
    r"(\d{1,2}[A-Z]?\.\d{1,3}[A-Z]?"                       # title.chapter
    r"(?:\.\d{1,3}[A-Z]?(?:\.[A-Z])?)?)"                   # optional .section(.subletter)
    r"(?![.\d])"
)


@dataclass
class TocDiscovery:
    first_page: Optional[int] = None
    last_page: Optional[int] = None

    @property
    def found(self) -> bool:
        return self.first_page is not None and self.last_page is not None

    @property
    def page_count(self) -> int:
        if not self.found:
            return 0
        return self.last_page - self.first_page + 1


class Command(BaseCommand):
    help = "Parse the Table of Ordinances Codified from the SMC PDF."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", required=True)
        parser.add_argument(
            "--pdf-scan-start",
            type=int,
            default=4300,
            help="1-indexed page to start scanning from (default 4300 for speed).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing to the database.",
        )
        parser.add_argument(
            "--purge-missing",
            action="store_true",
            help="Delete OrdinanceCodification rows whose ordinance_number no longer appears.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import OrdinanceCodification
        import pdfplumber

        try:
            pdf = pdfplumber.open(opts["pdf"])
        except FileNotFoundError:
            raise CommandError(f"PDF not found: {opts['pdf']}")

        try:
            discovery = self._discover_range(pdf, opts["pdf_scan_start"])
            if not discovery.found:
                raise CommandError(
                    "Could not find the Table of Ordinances Codified. "
                    "Try --pdf-scan-start 1 for a full scan."
                )
            self.stdout.write(
                f"TOC pages: {discovery.first_page}–{discovery.last_page} "
                f"({discovery.page_count} pages)"
            )

            counts = {"new": 0, "updated": 0, "unchanged": 0, "pages_processed": 0}
            seen_ord_numbers: set[str] = set()

            for page_num in range(discovery.first_page, discovery.last_page + 1):
                page = pdf.pages[page_num - 1]
                entries = self._parse_page(page)
                page.flush_cache()
                counts["pages_processed"] += 1

                for ord_num, desc in entries:
                    seen_ord_numbers.add(ord_num)
                    self._upsert(
                        OrdinanceCodification, ord_num, desc,
                        page_num, opts["dry_run"], counts,
                    )
        finally:
            pdf.close()

        purged = 0
        if opts["purge_missing"] and not opts["dry_run"] and seen_ord_numbers:
            purged = (
                OrdinanceCodification.objects
                .exclude(ordinance_number__in=seen_ord_numbers)
                .delete()[0]
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. pages={counts['pages_processed']} "
            f"new={counts['new']} updated={counts['updated']} "
            f"unchanged={counts['unchanged']} purged={purged}"
        ))

    @staticmethod
    def _discover_range(pdf, scan_start: int) -> TocDiscovery:
        """Find the TOC page range. Tolerates short runs of empty/header-less
        pages (the SMC PDF has occasional blank separator pages inside the
        TOC — p4444 in the 2026-04 edition).
        """
        MAX_GAP = 3
        d = TocDiscovery()
        total = len(pdf.pages)
        gap = 0
        for n in range(max(1, scan_start), total + 1):
            page = pdf.pages[n - 1]
            text = page.extract_text() or ""
            page.flush_cache()
            norm = re.sub(r"\s+", "", text).lower()

            if d.first_page is None:
                if _TOC_TITLE in norm:
                    d.first_page = n
                    d.last_page = n
                    gap = 0
                continue
            if _RUNNING_HEADER in norm:
                d.last_page = n
                gap = 0
            else:
                gap += 1
                if gap > MAX_GAP:
                    break
        return d

    def _parse_page(self, page) -> list[tuple[str, str]]:
        words = page.extract_words(x_tolerance=2, y_tolerance=3)
        # Drop running headers + bottom-of-page footer/page-number zones
        words = [w for w in words if 60 <= w["top"] <= 720]

        mid_x = page.width / 2
        left_words = [w for w in words if w["x0"] < mid_x]
        right_words = [w for w in words if w["x0"] >= mid_x]

        entries: list[tuple[str, str]] = []
        for col_words in (left_words, right_words):
            entries.extend(_parse_column(col_words))
        return entries

    @staticmethod
    @transaction.atomic
    def _upsert(Model, ord_num, description, page_num, dry_run, counts):
        description = description.strip()
        codified = _extract_refs(description)
        defaults = {
            "description": description,
            "codified_sections": codified,
            "source_pdf_page": page_num,
        }

        if dry_run:
            counts["new"] += 1
            return

        existing = Model.objects.filter(ordinance_number=ord_num).first()
        if existing is None:
            Model.objects.create(ordinance_number=ord_num, **defaults)
            counts["new"] += 1
            return

        changed = False
        for field, value in defaults.items():
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            existing.save(update_fields=list(defaults.keys()) + ["scraped_at"])
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1


def _parse_column(col_words: list[dict]) -> list[tuple[str, str]]:
    """Pull (ord_number, description) entries out of one column's worth of words."""
    if not col_words:
        return []

    # Column's ordinance-number x0 is the leftmost x0 we see. Description
    # text starts a consistent offset to the right of that.
    min_x0 = min(w["x0"] for w in col_words)

    by_top: dict[int, list[dict]] = defaultdict(list)
    for w in col_words:
        by_top[round(w["top"] / 3)].append(w)

    entries: list[tuple[str, str]] = []
    current_num: Optional[str] = None
    current_desc: list[str] = []

    for bucket in sorted(by_top):
        line_words = sorted(by_top[bucket], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in line_words).strip()
        if not line_text:
            continue
        # Drop the "TABLE OF ORDINANCES CODIFIED" section title on p1 of the TOC.
        if "TABLE OF ORDINANCES" in line_text.upper():
            continue

        first = line_words[0]
        at_col_start = abs(first["x0"] - min_x0) <= 5
        looks_like_ord = bool(_ORD_ID_RE.match(first["text"]))

        if at_col_start and looks_like_ord:
            if current_num is not None:
                entries.append((current_num, " ".join(current_desc).strip()))
            current_num = first["text"]
            rest = " ".join(w["text"] for w in line_words[1:]).strip()
            current_desc = [rest] if rest else []
        else:
            if current_num is not None:
                current_desc.append(line_text)

    if current_num is not None:
        entries.append((current_num, " ".join(current_desc).strip()))
    return entries


def _extract_refs(description: str) -> list[str]:
    """Pull SMC chapter/section references out of a description. Dedup order-preserving."""
    if not description:
        return []
    seen: set[str] = set()
    refs: list[str] = []
    for m in _SMC_REF_RE.finditer(description):
        ref = m.group(1)
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs
