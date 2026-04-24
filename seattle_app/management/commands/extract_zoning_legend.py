"""Parse the Seattle zoning-district legend (KEY TO DISTRICT DESIGNATIONS)
from the SMC PDF and upsert ZoningCode rows.

Typical usage:
    python manage.py extract_zoning_legend --pdf _data/seattle_municipal_code_20260421.pdf
    python manage.py extract_zoning_legend --pdf <path> --page 3847

If --page is omitted, the command scans the PDF for a page matching
'KEY TO DISTRICT DESIGNATIONS'. Pass --scan-start to hint where to begin
the scan (default 1, i.e. full scan).

The legend page has a 4-column layout:
  col1 (~x0=72)   col2 (~x0=251)   col3 (~x0=323)   col4 (~x0=503)
   left names      left abbrevs     right names      right abbrevs
Wrapping is rare (only MPC-YT wraps in the current edition). A wrap line
has text in col1 or col3 alone with no matching abbreviation on that row;
the continuation is folded into the previous entry's name.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# Column x0 boundaries for the 4-column legend table on p3847. These are
# generous enough to tolerate minor layout shifts between PDF editions.
COL1_MAX = 230
COL2_MAX = 310
COL3_MAX = 490

_LEGEND_ANCHOR = "keytodistrictdesignations"


class Command(BaseCommand):
    help = "Parse the zoning-district legend from the SMC PDF into ZoningCode rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf",
            required=True,
            help="Path to the SMC PDF.",
        )
        parser.add_argument(
            "--page",
            type=int,
            help="1-indexed page number of the legend. Auto-discovered if omitted.",
        )
        parser.add_argument(
            "--scan-start",
            type=int,
            default=1,
            help="1-indexed page to start scanning from when auto-discovering.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print extracted entries without writing to the database.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import ZoningCode
        import pdfplumber

        try:
            pdf = pdfplumber.open(opts["pdf"])
        except FileNotFoundError:
            raise CommandError(f"PDF not found: {opts['pdf']}")

        try:
            page_num = opts["page"] or self._find_legend_page(pdf, opts["scan_start"])
            if page_num is None:
                raise CommandError(
                    "Could not locate the legend page. Pass --page explicitly."
                )
            self.stdout.write(f"Parsing legend from PDF page {page_num}")
            entries = self._extract_legend(pdf.pages[page_num - 1])
        finally:
            pdf.close()

        if not entries:
            raise CommandError("No legend entries extracted — check the page.")

        self.stdout.write(f"Extracted {len(entries)} entries:")
        for abbrev, name in entries:
            self.stdout.write(f"  {abbrev:10s}  {name}")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run; no changes written."))
            return

        counts = {"new": 0, "updated": 0, "unchanged": 0}
        for abbrev, name in entries:
            self._upsert(ZoningCode, abbrev, name, page_num, counts)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. new={counts['new']} updated={counts['updated']} "
                f"unchanged={counts['unchanged']}"
            )
        )

    @staticmethod
    def _find_legend_page(pdf, scan_start: int) -> Optional[int]:
        total = len(pdf.pages)
        for n in range(max(1, scan_start), total + 1):
            page = pdf.pages[n - 1]
            text = page.extract_text() or ""
            page.flush_cache()
            if _LEGEND_ANCHOR in re.sub(r"\s+", "", text).lower():
                return n
        return None

    @staticmethod
    def _extract_legend(page) -> list[tuple[str, str]]:
        """Return (abbreviation, name) tuples in document order."""
        words = page.extract_words(x_tolerance=2, y_tolerance=3)

        by_top: dict[int, list[dict]] = defaultdict(list)
        for w in words:
            by_top[round(w["top"])].append(w)

        rows = []
        for top in sorted(by_top):
            row_words = sorted(by_top[top], key=lambda w: w["x0"])
            c1 = " ".join(w["text"] for w in row_words if w["x0"] < COL1_MAX)
            c2 = " ".join(w["text"] for w in row_words if COL1_MAX <= w["x0"] < COL2_MAX)
            c3 = " ".join(w["text"] for w in row_words if COL2_MAX <= w["x0"] < COL3_MAX)
            c4 = " ".join(w["text"] for w in row_words if w["x0"] >= COL3_MAX)
            rows.append((c1.strip(), c2.strip(), c3.strip(), c4.strip()))

        entries: list[tuple[str, str]] = []
        last_left: Optional[int] = None
        last_right: Optional[int] = None
        for c1, c2, c3, c4 in rows:
            if _looks_like_abbrev(c2):
                entries.append((c2, c1))
                last_left = len(entries) - 1
            elif c1 and not c2 and not c3 and not c4 and last_left is not None:
                ab, nm = entries[last_left]
                entries[last_left] = (ab, f"{nm} {c1}")

            if _looks_like_abbrev(c4):
                entries.append((c4, c3))
                last_right = len(entries) - 1
            elif c3 and not c1 and not c2 and not c4 and last_right is not None:
                ab, nm = entries[last_right]
                entries[last_right] = (ab, f"{nm} {c3}")

        return entries

    @staticmethod
    @transaction.atomic
    def _upsert(Model, abbreviation, name, page_num, counts):
        existing = Model.objects.filter(abbreviation=abbreviation).first()
        if existing is None:
            Model.objects.create(
                abbreviation=abbreviation,
                name=name,
                source_pdf_page=page_num,
            )
            counts["new"] += 1
            return
        if existing.name == name and existing.source_pdf_page == page_num:
            counts["unchanged"] += 1
            return
        existing.name = name
        existing.source_pdf_page = page_num
        existing.save(update_fields=["name", "source_pdf_page", "updated_at"])
        counts["updated"] += 1


def _looks_like_abbrev(s: str) -> bool:
    """True iff s is a plausible zoning abbreviation: short, uppercase
    letters + digits + hyphens only. Filters out column headers like
    'Abbreviated' and stray words."""
    if not s or len(s) > 12:
        return False
    return all(c.isupper() or c.isdigit() or c == "-" for c in s)
