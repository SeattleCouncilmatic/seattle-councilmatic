"""Resolve in-prose bill citations to councilmatic slugs.

Used by the legislation and SMC detail endpoints to build a small
`{kind:num -> slug}` lookup map alongside the prose they return, so
the frontend can scan for cites at render time and link the ones we
actually carry.

Scope is intentionally narrow:

  * "CB <num>" and "Res(olution)? <num>" cites resolve to the
    matching Bill record (we keep CBs and Resolutions in the
    18-month rolling scrape window).
  * "Ord(inance)? <num>" cites are matched by the regex but do NOT
    resolve — we don't store ordinance-numbered records (the
    underlying CB carries the substance; the Ord. number is just
    its post-passage label, with a separate Legistar matter we
    don't ingest). They fall through to plain text on the
    frontend.

Self-references aren't filtered here — the caller (or the frontend)
is responsible for skipping a cite that points at the page's own
slug, since this service doesn't know which page is rendering.
"""

from __future__ import annotations

import re
from typing import Iterable

from councilmatic_core.models import Bill


# Match prose citations of the form "CB 121185", "Resolution 32195",
# "Res. 32168", "Ordinance 127362", "Ord. 127400". Case-insensitive to
# accommodate LLM output variations. The `\.?` after the prefix lets us
# pick up both "Ord. " and "Ord " forms; `\s+` then requires whitespace
# before the number so we don't match "CB121185" or similar.
PROSE_REF_RE = re.compile(
    r"\b(CB|Res(?:olution)?|Ord(?:inance)?)\.?\s+(\d+)\b",
    re.IGNORECASE,
)


def _kind_token(prefix: str) -> str:
    """Normalize the prefix capture to a 3-char kind token: cb/res/ord."""
    return prefix[:3].lower()


def extract_prose_cites(texts: Iterable[str | None]) -> set[tuple[str, str]]:
    """Return unique (kind, num) cites found across the given texts."""
    cites: set[tuple[str, str]] = set()
    for text in texts:
        if not text:
            continue
        for m in PROSE_REF_RE.finditer(text):
            cites.add((_kind_token(m.group(1)), m.group(2)))
    return cites


def resolve_prose_cites(cites: set[tuple[str, str]]) -> dict[str, str]:
    """Map (kind, num) cites to bill slugs.

    Returns a flat dict keyed by `"<kind>:<num>"` (e.g. `"cb:121185"`).
    Only CB and Res cites are looked up; Ord cites are skipped because
    we don't store ordinance-numbered records. Unresolved cites are
    omitted from the result so the frontend can fall through to plain
    text via a missing key.
    """
    if not cites:
        return {}

    nums_by_kind: dict[str, set[str]] = {"cb": set(), "res": set()}
    for kind, num in cites:
        if kind in nums_by_kind:
            nums_by_kind[kind].add(num)
    if not any(nums_by_kind.values()):
        return {}

    # Build one regex per kind that matches "<prefix> <num>" exactly,
    # accepting CB / Res / Resolution casings on the prefix and any of
    # the cite's number values. Anchored with ^/$ via Postgres regex
    # operator so partial matches like "121185" inside "CB 1211857"
    # don't fire.
    result: dict[str, str] = {}
    qs = Bill.objects.values("identifier", "slug")
    if nums_by_kind["cb"]:
        nums_alt = "|".join(re.escape(n) for n in nums_by_kind["cb"])
        cb_pattern = rf"^\s*CB\s+({nums_alt})\s*$"
        for b in qs.filter(identifier__iregex=cb_pattern):
            num_match = re.search(r"\d+", b["identifier"])
            if num_match:
                result[f"cb:{num_match.group()}"] = b["slug"]
    if nums_by_kind["res"]:
        nums_alt = "|".join(re.escape(n) for n in nums_by_kind["res"])
        res_pattern = rf"^\s*Res(?:olution)?\.?\s+({nums_alt})\s*$"
        for b in qs.filter(identifier__iregex=res_pattern):
            num_match = re.search(r"\d+", b["identifier"])
            if num_match:
                result[f"res:{num_match.group()}"] = b["slug"]
    return result


def build_prose_ref_map(texts: Iterable[str | None]) -> dict[str, str]:
    """Convenience: extract + resolve in one call."""
    return resolve_prose_cites(extract_prose_cites(texts))
