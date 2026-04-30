"""Download and extract plain text from bill attachments.

Seattle bills carry their substantive content in Legistar document
attachments (PDF or .docx). The :mod:`Bill` row from the OCD/pupa scrape
only stores their URLs, not their content; this module downloads them
on demand and turns them into plain text suitable for LLM
summarization.

Two well-known attachment kinds — see the ``extract_bill_text``
management command for the picker that decides which to use:

* "Summary and Fiscal Note" (.docx) — staff plain-language summary plus
  fiscal analysis. Available from introduction onward.
* "Signed Ordinance NNNNN" / "Signed Resolution NNNNN" (PDF) — canonical
  body text. Only present after enactment.

We skip the "Affidavit of Publication" (PDF, legal notice, no bill
content). Other attachment types fall to ``other`` and are ignored by
default; callers can opt in with ``include_other=True`` if they want a
broader sweep.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import pdfplumber
import requests
from docx import Document

logger = logging.getLogger(__name__)

# Conservative HTTP timeout — Legistar's CDN is fast under normal load,
# but a stuck request shouldn't block a whole batch run.
_HTTP_TIMEOUT_SECONDS = 30

# How long an extracted blob can grow before we treat it as suspicious
# and bail out. Bill texts in the wild run 5k–80k chars; anything past
# this is almost certainly a scan/OCR artifact or wrong document.
_MAX_TEXT_CHARS = 500_000

# Document categories. Matched against BillDocument.note (case-insensitive,
# anchored). Order here mirrors the LLM-input concatenation order.
SUMMARY_NOTE_RE = re.compile(r"^summary\s+and\s+fiscal\s+note\b", re.IGNORECASE)
# Permissive prefix match: "Signed Ordinance 127119", "Signed Resolution
# 32168", "Signed Council Bill 12345" all qualify. Risk of catching a
# stray "Signed [Something Else]" doc is small in practice — Legistar's
# document templates are predictable.
SIGNED_NOTE_RE = re.compile(r"^signed\s+", re.IGNORECASE)
# Pre-enactment canonical text. Legistar attaches the ordinance body as
# "Full Text: CB 121173 v1" (or vN for revised drafts) BEFORE the bill
# is signed; once signed, it gets renamed and re-attached as "Signed
# Ordinance NNNNN". Both are canonical bill body for our summarization
# purposes — categorizing separately just so the audit trail can tell
# them apart and so future code can prefer signed over draft if both
# are present.
FULL_TEXT_NOTE_RE = re.compile(r"^full\s+text\b", re.IGNORECASE)
AFFIDAVIT_NOTE_RE = re.compile(r"\baffidavit\b", re.IGNORECASE)


# Media-type strings, kept verbose for legibility.
_PDF_MEDIA = "application/pdf"
_DOCX_MEDIA = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_DOC_MEDIA = "application/msword"  # legacy binary; we don't extract from these


@dataclass
class ExtractedDocument:
    """Result of extracting one document, including everything we want
    to record on the BillText row's ``source_documents`` JSON."""

    note: str
    url: str
    media_type: str
    category: str          # 'summary' | 'signed' | 'affidavit' | 'other' | 'unsupported'
    text: str              # may be empty for skipped/failed docs
    error: Optional[str] = None


def categorize_note(note: str) -> str:
    """Classify a BillDocument note into our document buckets."""
    if SUMMARY_NOTE_RE.match(note or ""):
        return "summary"
    if SIGNED_NOTE_RE.match(note or ""):
        return "signed"
    if FULL_TEXT_NOTE_RE.match(note or ""):
        return "full_text"
    if AFFIDAVIT_NOTE_RE.search(note or ""):
        return "affidavit"
    return "other"


def extract_text(url: str, media_type: str) -> str:
    """Download `url` and return its plain text.

    Returns "" on download failure, unsupported media type (legacy .doc),
    or extraction failure. Errors are logged at WARNING; callers
    decide whether to skip the document or surface the error.
    """
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("download failed: %s — %s", url, e)
        return ""

    blob = resp.content
    if media_type == _PDF_MEDIA:
        return _extract_pdf(blob, url)
    if media_type == _DOCX_MEDIA:
        return _extract_docx(blob, url)
    if media_type == _DOC_MEDIA:
        # Legacy binary .doc — not commonly used by Seattle but possible
        # for older bills. Skip rather than introduce another dep.
        logger.warning("skipping legacy .doc (not supported): %s", url)
        return ""
    logger.warning("unsupported media type %r for %s", media_type, url)
    return ""


def combine_bill_documents(
    documents: Iterable[dict],
    *,
    include_other: bool = False,
) -> tuple[str, list[ExtractedDocument]]:
    """Pick the right documents for a bill, extract each, and return a
    single concatenated text block plus a per-document audit trail.

    Each document in `documents` is a dict with ``note``, ``url``, and
    ``media_type`` keys (matching the shape we already serialize in the
    bill detail API).

    The returned text is structured for LLM consumption:

        [STAFF SUMMARY AND FISCAL NOTE — note text]
        <body>

        [SIGNED ORDINANCE NNNNN — note text]
        <body>

    Section markers help the LLM tell staff framing apart from the
    canonical text. If a category yields no text, its block is omitted.
    """
    extracted: list[ExtractedDocument] = []
    for doc in documents:
        note = (doc.get("note") or "").strip()
        url = (doc.get("url") or "").strip()
        media_type = (doc.get("media_type") or "").strip()
        category = categorize_note(note)

        if category == "affidavit":
            # Legal notice; never has bill content. Record it for the
            # audit trail but don't download.
            extracted.append(ExtractedDocument(
                note=note, url=url, media_type=media_type,
                category=category, text="",
            ))
            continue
        if category == "other" and not include_other:
            extracted.append(ExtractedDocument(
                note=note, url=url, media_type=media_type,
                category=category, text="",
            ))
            continue
        if not url:
            extracted.append(ExtractedDocument(
                note=note, url=url, media_type=media_type,
                category=category, text="",
                error="missing url",
            ))
            continue

        text = extract_text(url, media_type)
        if len(text) > _MAX_TEXT_CHARS:
            err = f"extracted text too large ({len(text)} chars), suspicious"
            logger.warning("%s: %s", url, err)
            extracted.append(ExtractedDocument(
                note=note, url=url, media_type=media_type,
                category=category, text="", error=err,
            ))
            continue
        extracted.append(ExtractedDocument(
            note=note, url=url, media_type=media_type,
            category=category, text=text,
        ))

    parts: list[str] = []
    # Summary first (staff framing), then canonical text (signed if
    # available, else the pre-enactment "Full Text" draft). Multiple
    # matches in a category get all included; for an enacted bill that
    # also still has a draft attached, the LLM sees both — small cost
    # in tokens, robust to versions diverging.
    sections = (
        ("summary",   "STAFF SUMMARY AND FISCAL NOTE"),
        ("signed",    "SIGNED CANONICAL TEXT"),
        ("full_text", "FULL TEXT (PRE-ENACTMENT DRAFT)"),
    )
    for category, header_word in sections:
        for doc in extracted:
            if doc.category == category and doc.text:
                parts.append(f"[{header_word} — {doc.note}]\n{doc.text}")
    return "\n\n".join(parts), extracted


# ---------------------------------------------------------------------------
# Format-specific extraction
# ---------------------------------------------------------------------------

def _extract_pdf(blob: bytes, url: str) -> str:
    """Plain-text extraction from a PDF blob via pdfplumber.

    pdfplumber's ``extract_text()`` is single-column-friendly and
    suitable for the well-formatted ordinance PDFs Legistar produces.
    Page-by-page join with single newlines so paragraph reflow is
    tractable downstream.
    """
    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            pages: list[str] = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text)
        return "\n".join(pages).strip()
    except Exception as e:
        logger.warning("pdfplumber failed on %s: %s", url, e)
        return ""


def _extract_docx(blob: bytes, url: str) -> str:
    """Plain-text extraction from a .docx blob via python-docx.

    Walks paragraphs in document order and tables row-by-row.
    Headers/footers are ignored — Seattle's "Summary and Fiscal Note"
    template puts the actual content in the body, with template
    cruft in headers/footers we don't want polluting the LLM input.
    """
    try:
        doc = Document(io.BytesIO(blob))
    except Exception as e:
        logger.warning("python-docx failed on %s: %s", url, e)
        return ""

    parts: list[str] = []
    # Walk the document body. Element order matters because a "Summary
    # and Fiscal Note" template intersperses headings, paragraphs, and
    # tables; reading them in document order preserves intent.
    seen_table_ids: set[int] = set()
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for table in doc.tables:
        # Avoid double-counting tables that appear inside body
        # paragraphs; python-docx returns top-level tables here.
        if id(table) in seen_table_ids:
            continue
        seen_table_ids.add(id(table))
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            cells = [c for c in cells if c]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()
