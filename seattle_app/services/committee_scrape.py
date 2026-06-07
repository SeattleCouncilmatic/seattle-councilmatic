"""Parse a committee's scope + regular meeting schedule out of its seattle.gov
committee page.

The page renders labeled sections, each label on its own line:

    Committee regular meeting days and time:
    2nd Thursdays at 9:30 a.m.
    Committee Members:
    ...
    Committee Scope:
    To provide policy direction and oversight ... relating to:
    <area 1>
    <area 2>
    City Council
    Address:
    ...

So we walk the page text and collect the lines after each label until the next
label (or the contact block / council name). Kept label-driven rather than
CSS-selector-driven because seattle.gov's markup is class-soup, but the visible
label text is stable.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

_SCOPE_LABEL = "committee scope"
_SCHEDULE_LABEL = "committee regular meeting days and time"

# Lines that end a section: the other section labels + the contact block that
# follows scope + a stray council-name line the template emits before it.
_STOP_LABELS = {
    "committee scope",
    "committee regular meeting days and time",
    "committee members",
    "chair",
    "vice chair",
    "member",
    "address",
    "mailing address",
    "phone",
    "fax",
    "email",
    "city council",
}


def _page_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n")]
    return [ln for ln in lines if ln]


def _is_stop(line: str) -> bool:
    return line.lower().rstrip(":").strip() in _STOP_LABELS


def _find_label(lines: list[str], label: str) -> int:
    for i, ln in enumerate(lines):
        if ln.lower().rstrip(":").strip() == label:
            return i
    return -1


def _block_after(lines: list[str], label: str, *, max_lines: int | None = None) -> list[str]:
    """Lines following ``label`` up to the next section label (or ``max_lines``)."""
    i = _find_label(lines, label)
    if i < 0:
        return []
    out: list[str] = []
    for ln in lines[i + 1:]:
        if _is_stop(ln):
            break
        out.append(ln)
        if max_lines is not None and len(out) >= max_lines:
            break
    return out


def extract_committee_info(html: str) -> tuple[str, str]:
    """Return ``(scope, meeting_schedule)`` parsed from a committee page.

    Either may be ``""`` if its section isn't present. ``scope`` keeps its
    internal line breaks (intro sentence + the areas it lists); ``schedule`` is
    collapsed to a single line."""
    lines = _page_lines(html)
    scope = "\n".join(_block_after(lines, _SCOPE_LABEL)).strip()
    schedule = " ".join(_block_after(lines, _SCHEDULE_LABEL, max_lines=2)).strip()
    return scope, schedule
