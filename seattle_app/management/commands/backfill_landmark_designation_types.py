"""Backfill HistoricLandmark.designation_type from the SMC Ch. 25.32 tables.

Typical usage:
    python manage.py backfill_landmark_designation_types
    python manage.py backfill_landmark_designation_types --pdf <path> --dry-run

SMC Ch. 25.32 ("Table of Historical Landmarks") groups every designated City
Landmark under Roman-numeral category headers:

    I Residences
    II Buildings
    III Churches
    IV Schools
    V Firehouses
    VI Bridges and Waterways
    VII Boats
    VIII Libraries
    IX Miscellaneous

Each row ends with the designating ordinance number, which we already store
on HistoricLandmark.designating_ord_number. This command parses those tables
and joins back to update designation_type / designation_type_name.

The SDCI GIS source does not expose the category, which is why this is a
separate backfill pass rather than part of ingest_historic_landmarks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


DEFAULT_PDF_PATH = "_data/seattle_municipal_code_20260421.pdf"
DEFAULT_START_PAGE = 4388
DEFAULT_END_PAGE = 4396

ROMANS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX")

# Category headers appear in two forms in the PDF:
#   "I Residences"                          (preamble listing)
#   "I Residences Address Ord. No."         (in-table column header)
#   "VII Boats Ord. No."                    (boats have no Address column)
# Address is therefore optional in the trailing column-header group.
CATEGORY_RE = re.compile(
    r"^(" + "|".join(ROMANS) + r")\s+"
    r"([A-Za-z][A-Za-z \-/&,]+?)"
    r"(?:\s+(?:Address\s+)?Ord\.?\s*No\.?)?"
    r"\s*$"
)

# A landmark row ends with a 5- or 6-digit ordinance number. Running page
# headers ("25.32 ..." / "TABLE OF HISTORICAL LANDMARKS 25.32") end with
# "25.32" (contains a dot), and footers ("(Seattle 12-24) 25-274") end with
# a 3-digit page number, so neither matches this tail anchor.
ORD_TAIL_RE = re.compile(r"\b(\d{5,6})\s*$")


class Command(BaseCommand):
    help = "Backfill HistoricLandmark.designation_type from SMC Ch. 25.32 tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf", default=DEFAULT_PDF_PATH,
            help=f"Path to SMC PDF (default: {DEFAULT_PDF_PATH})",
        )
        parser.add_argument(
            "--start-page", type=int, default=DEFAULT_START_PAGE,
            help=f"First 1-indexed PDF page of Ch. 25.32 tables (default: {DEFAULT_START_PAGE})",
        )
        parser.add_argument(
            "--end-page", type=int, default=DEFAULT_END_PAGE,
            help=f"Last 1-indexed PDF page of Ch. 25.32 tables (default: {DEFAULT_END_PAGE})",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from seattle_app.models import HistoricLandmark

        pdf_path = Path(opts["pdf"])
        if not pdf_path.exists():
            raise CommandError(f"PDF not found: {pdf_path}")

        ord_to_category = _parse_categories(
            pdf_path, opts["start_page"], opts["end_page"]
        )
        seen_romans = {roman for roman, _ in ord_to_category.values()}
        missing = [r for r in ROMANS if r not in seen_romans]
        if missing:
            raise CommandError(
                f"Did not find any rows under these categories: {missing}. "
                "Check --start-page/--end-page or the PDF edition."
            )

        self.stdout.write(
            f"Parsed {len(ord_to_category)} (ord_number, category) pairs from "
            f"pages {opts['start_page']}-{opts['end_page']}."
        )

        updated, unmatched, already_ok = _apply(
            HistoricLandmark, ord_to_category, opts["dry_run"]
        )
        mode = "[DRY RUN] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{mode}updated={updated} already_correct={already_ok} "
            f"no_match_in_pdf={len(unmatched)}"
        ))
        if unmatched:
            sample = sorted(unmatched)[:10]
            self.stdout.write(
                f"Landmarks whose ordinance wasn't found in Ch. 25.32 (sample): "
                f"{sample}"
            )


def _parse_categories(
    pdf_path: Path, start_page: int, end_page: int
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    current: tuple[str, str] | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for one_indexed in range(start_page, end_page + 1):
            page = pdf.pages[one_indexed - 1]
            text = page.extract_text() or ""
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                m_cat = CATEGORY_RE.match(stripped)
                if m_cat:
                    current = (m_cat.group(1), m_cat.group(2).strip())
                    continue
                m_ord = ORD_TAIL_RE.search(stripped)
                if m_ord and current is not None:
                    # setdefault: preserve the first category an ordinance is
                    # seen under, in case of any accidental cross-listing.
                    result.setdefault(m_ord.group(1), current)
    return result


def _apply(Model, ord_to_category, dry_run):
    updated = 0
    already_ok = 0
    unmatched: set[str] = set()

    with transaction.atomic():
        for lm in Model.objects.all():
            ord_no = (lm.designating_ord_number or "").strip()
            if not ord_no:
                continue
            mapping = ord_to_category.get(ord_no)
            if mapping is None:
                unmatched.add(ord_no)
                continue
            roman, name = mapping
            if lm.designation_type == roman and lm.designation_type_name == name:
                already_ok += 1
                continue
            if not dry_run:
                lm.designation_type = roman
                lm.designation_type_name = name
                lm.save(update_fields=["designation_type", "designation_type_name"])
            updated += 1
    return updated, unmatched, already_ok
