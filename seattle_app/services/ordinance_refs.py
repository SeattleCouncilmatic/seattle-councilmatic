"""Parse ordinance revision references out of SMC section text.

The regex matches the revision-history parenthetical that appears at the
end of each SMC section's full_text, e.g.:

    (Ord. 126234, § 1, 2023; Ord. 118396 § 11(part), 1996)

Each match yields an ExtractedRef(ordinance_number, section_reference,
ordinance_year) tuple. A 4-digit year is required, which filters out
body references like "repeals Ord. 16003" that don't carry year context.

This module is imported by both the `parse_smc_pdf` and
`extract_ordinance_refs` management commands so the extraction logic
lives in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Sample shapes this matches:
#   Ord. 126234, § 1, 2023
#   Ord. 118396 § 11(part), 1996
#   Ord. 108934, § 1.076, 1980
#   Ord. No. 100475 § 1, 1971
#
# The comma before § is inconsistent in the source; pdfplumber preserves
# the § glyph on body pages; refs may contain parens or periods; the year
# is the last token. `ref` stops at comma/semicolon/colon so neighboring
# entries inside a multi-ord parenthetical don't bleed together.
ORD_REF_RE = re.compile(
    r"Ord\.\s*"
    r"(?:No\.\s*)?"
    r"(?P<num>\d+)"
    r"(?:\s*,?\s*§{1,2}\s*(?P<ref>[^,;:\n]*?))?"
    r"(?:\s*,\s*(?P<year>\d{4}))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedRef:
    ordinance_number: str
    section_reference: str
    ordinance_year: int


def extract_ordinance_refs(text: str) -> list[ExtractedRef]:
    """Return structured refs parsed from section text. Empty list if none.

    Duplicates (same ordinance + section_reference) are collapsed so they
    don't trip the DB unique constraint on SectionOrdinanceRef.
    """
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    refs: list[ExtractedRef] = []
    for m in ORD_REF_RE.finditer(text):
        num = m.group("num")
        ref = (m.group("ref") or "").strip()
        year = int(m.group("year"))
        key = (num, ref)
        if key in seen:
            continue
        seen.add(key)
        refs.append(ExtractedRef(
            ordinance_number=num,
            section_reference=ref,
            ordinance_year=year,
        ))
    return refs
