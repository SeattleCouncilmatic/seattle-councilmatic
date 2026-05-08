"""Extract embedded figures from the SMC PDF, save as PNGs, and splice
markdown image links into ``MunicipalCodeSection.full_text``.

Background — issue #170
=======================

Many sections (especially Title 23 zoning) reference figures by caption
("Map A for 23.48.235", "Exhibit B for 23.48.012"). The parser strips
caption lines as section boundaries (``parse_smc_pdf.py:233``) and
never extracts the image itself, so rendered sections only show the
caption text — the picture is missing. Sections like 23.48.235 are
nearly unreadable without the maps.

Discovery scan (2026-05-07): 632 image-bearing PDF pages corpus-wide,
of which 140 are body pages with standard "Prefix Code for X.Y.Z"
captions across 75 distinct sections. ~95% of captioned figures are
in Title 23. Out of scope for this pass: multi-page attachment series
like 5.72.030's neighborhood maps where the "caption" is just the
neighborhood name — those need section-context heuristics, not
caption matching.

Recovery side effect: closes #152. Section 23.48.235 (Upper-Level
Setbacks) was missing because its number lives only in the running
header and its title appears below a figure caption rather than next
to the section number. This command's special-case handler synthesizes
the row by carving content out of 23.48.230's bleed-over full_text.

Usage
=====

::

    python manage.py extract_smc_figures              # full pass
    python manage.py extract_smc_figures --section 23.48.235
    python manage.py extract_smc_figures --dry-run    # report only
    python manage.py extract_smc_figures --force      # re-extract PNGs

Idempotent — sections whose ``full_text`` already has the markdown
image link for a figure are skipped unless ``--force`` is set.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from seattle_app.models import MunicipalCodeSection


# Permissive caption matcher. Tolerates the pdfplumber word-merging
# artifact ("ExhibitAfor 23.60A.188") via optional whitespace, and
# captures any descriptive title that sits on the same line ("Map A
# for 23.50A.190 Designated Industrial Streets").
CAPTION_RE = re.compile(
    r"^(?P<prefix>Map|Exhibit|Figure|Chart|Diagram)\s*"
    r"(?P<code>[A-Z](?:[-.]\d{1,2})?)\s*"
    r"for\s+"
    r"(?P<section>\d+\.\d+[A-Z]?\.\d+[A-Z]?)"
    r"(?:\s+(?P<title>.{1,160}))?\s*$",
    re.IGNORECASE,
)

# 150 DPI matches extract_smc_tables; readable for small features
# (street labels on zone maps, dimensions on setback diagrams).
RENDER_RESOLUTION = 150
# Bbox padding in PDF points (1pt = 1/72in). pdfplumber's image bbox
# is sometimes tight to content; a small pad protects edge labels.
BBOX_PADDING = 6

FIGURES_DIR = Path(settings.BASE_DIR) / "seattle_app" / "static" / "smc-figures"
STATIC_URL_PREFIX = settings.STATIC_URL.rstrip("/") + "/smc-figures"


@dataclass
class Figure:
    """A figure on a single PDF page, located by image bbox and tied to a
    target section by its caption."""
    page_num: int
    image_bbox: tuple[float, float, float, float]  # x0, top, x1, bottom
    caption: str            # e.g., "Map A for 23.48.235"
    prefix: str             # "Map", "Exhibit", ...
    code: str               # "A", "B-1", ...
    target_section: str     # "23.48.235"
    figure_title: str | None  # any descriptive title that followed the caption


@dataclass
class SectionWork:
    """All figures whose caption references this section."""
    section_number: str
    figures: list[Figure] = field(default_factory=list)


def _section_slug(section_number: str) -> str:
    return section_number.replace(".", "-").lower()


def _caption_slug(prefix: str, code: str) -> str:
    return f"{prefix.lower()}-{code.lower().replace('.', '-')}"


def _figure_path(figure: Figure) -> Path:
    return (
        FIGURES_DIR
        / _section_slug(figure.target_section)
        / f"{_caption_slug(figure.prefix, figure.code)}.png"
    )


def _figure_url(figure: Figure) -> str:
    return (
        f"{STATIC_URL_PREFIX}/{_section_slug(figure.target_section)}/"
        f"{_caption_slug(figure.prefix, figure.code)}.png"
    )


def _markdown_image(figure: Figure) -> str:
    """Markdown image link rendered inline in `full_text`. Title (if
    present) goes after the image as a small italic caption."""
    img = f"![{figure.caption}]({_figure_url(figure)})"
    if figure.figure_title:
        return f"{img}\n\n_{figure.figure_title.strip()}_"
    return img


def _crop_padded(page, bbox: tuple[float, float, float, float]):
    x0, top, x1, bottom = bbox
    return page.crop((
        max(0, x0 - BBOX_PADDING),
        max(0, top - BBOX_PADDING),
        min(page.width, x1 + BBOX_PADDING),
        min(page.height, bottom + BBOX_PADDING),
    ))


def _save_figure_png(page, figure: Figure) -> int:
    """Render the cropped region as PNG and write to disk. Returns the
    file size in bytes."""
    out_path = _figure_path(figure)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped = _crop_padded(page, figure.image_bbox)
    img = cropped.to_image(resolution=RENDER_RESOLUTION)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out_path.write_bytes(buf.getvalue())
    return len(buf.getvalue())


def _scan_pdf(
    pdf,
    section_filter: str | None = None,
    page_range: tuple[int, int] | None = None,
) -> list[Figure]:
    """Walk the PDF and collect every captioned figure. Uses
    ``page.flush_cache()`` after each page so we don't accumulate
    parsed-page state across all 4500+ pages.

    ``page_range`` (start, end) inclusive limits the scan to a window —
    used when ``--section`` is set to avoid the 25-minute full-PDF
    walk. Pages 1-indexed."""
    figures: list[Figure] = []
    if page_range is not None:
        page_iter = (
            (pn, pdf.pages[pn - 1])
            for pn in range(page_range[0], min(page_range[1] + 1, len(pdf.pages) + 1))
        )
    else:
        page_iter = enumerate(pdf.pages, start=1)
    for pn, page in page_iter:
        if not page.images:
            page.flush_cache()
            continue
        text = page.extract_text() or ""
        # Match captions line-by-line. A page can host >1 figure
        # (rare in Title 23 but possible), so iterate every line.
        page_caps: list[Figure] = []
        for line in text.split("\n"):
            stripped = line.strip()
            m = CAPTION_RE.match(stripped)
            if not m:
                continue
            target = m.group("section")
            if section_filter and target != section_filter:
                continue
            page_caps.append((stripped, m))
        # Pair captions with images on the page. If counts match,
        # zip them by document order. Otherwise associate every
        # caption with the first image (good enough for single-image
        # pages, which are the dominant case).
        imgs = page.images
        if len(page_caps) == len(imgs):
            pairs = list(zip(page_caps, imgs))
        else:
            pairs = [(cap, imgs[0]) for cap in page_caps]
        for (caption_text, m), img in pairs:
            prefix = m.group("prefix").title()
            code = m.group("code").upper()
            target = m.group("section")
            # Canonical caption: "Prefix Code for Target". The matched
            # line in PDF text often appends a descriptive title (kept
            # separately as `figure_title`); the section's full_text
            # may render the standalone caption WITHOUT that title, so
            # we splice on the canonical form to hit both layouts.
            figures.append(Figure(
                page_num=pn,
                image_bbox=(img["x0"], img["top"], img["x1"], img["bottom"]),
                caption=f"{prefix} {code} for {target}",
                prefix=prefix,
                code=code,
                target_section=target,
                figure_title=(m.group("title") or "").strip() or None,
            ))
        page.flush_cache()
    return figures


def _splice_figure_into_full_text(full_text: str, figure: Figure) -> tuple[str, bool]:
    """Replace the standalone caption line in ``full_text`` with a
    markdown image link. Returns ``(new_text, changed)``.

    The match must be a STANDALONE caption — the entire line is just
    the caption, optionally followed by a short descriptive title.
    Mid-sentence prose references like ``"as shown in Exhibit B for
    23.48.235"`` look the same lexically but should NOT be replaced
    with an image; they're cross-references, not figure positions.

    Recognized caption forms (after whitespace normalization):

    * ``Map A for 23.48.235`` — bare caption.
    * ``Map A for 23.50A.190 Designated Industrial Streets`` — caption
      with descriptive title appended.
    * ``ExhibitAfor 23.60A.188`` — pdfplumber word-merging artifact.

    Idempotent: returns the original text if the image link is already
    present.
    """
    md = _markdown_image(figure)
    if _figure_url(figure) in full_text:
        return full_text, False

    cap_norm = re.sub(r"\s+", "", figure.caption).lower()
    if not cap_norm:
        return full_text, False
    lines = full_text.split("\n")
    for i, line in enumerate(lines):
        norm = re.sub(r"\s+", "", line.strip()).lower()
        if not norm.startswith(cap_norm):
            continue
        # The line begins with the caption. Accept if the rest is
        # either empty or a short descriptive title — reject if the
        # caption is followed by long sentence content (mid-sentence
        # references after a comma/colon look longer than 160 chars
        # or wrap into adjacent prose).
        trailing = norm[len(cap_norm):]
        if len(trailing) > 160:
            continue
        lines[i] = md
        return "\n".join(lines), True

    return full_text, False


def _append_figure_before_citation(full_text: str, figure: Figure) -> tuple[str, bool]:
    """Fallback for figures whose caption couldn't be located cleanly
    in ``full_text`` (the parser broke the caption into fragments —
    see 23.48.235's bleed-over). Insert the markdown image link just
    before the trailing ordinance citation if present, otherwise at
    the end. Idempotent."""
    if _figure_url(figure) in full_text:
        return full_text, False
    md = _markdown_image(figure)
    cite_match = re.search(r"\n\(Ord\.\s+\d", full_text)
    if cite_match:
        head = full_text[: cite_match.start()].rstrip()
        tail = full_text[cite_match.start():].lstrip("\n")
        return head + "\n\n" + md + "\n\n" + tail, True
    return full_text.rstrip() + "\n\n" + md + "\n", True


# 23.48.235 special-case recovery — see issue #152.
RECOVER_23_48_235 = {
    "section_number": "23.48.235",
    "title": "Upper-Level Setbacks",
    "title_number": "23",
    "chapter_number": "23.48",
    "source_pdf_page": 3015,
    # The boundary in 23.48.230's bleed-over text where 23.48.235's
    # content begins. We slice 23.48.230's full_text at this marker
    # and create a new section row from the slice + page-extracted
    # body text from pages 3015-3018.
    "bleed_marker": "for 23.48.235",
    "page_range": (3015, 3018),
}


def _resolve_page_range(section_number: str) -> tuple[int, int] | None:
    """For ``--section X``, narrow the PDF scan to just X's page range so
    we don't pay for a full 4500-page walk. Returns ``(start, end)``
    inclusive, or None if we can't determine the range (caller should
    fall back to a full scan)."""
    if section_number == RECOVER_23_48_235["section_number"]:
        return RECOVER_23_48_235["page_range"]
    s = (
        MunicipalCodeSection.objects
        .filter(section_number=section_number)
        .only("source_pdf_page")
        .first()
    )
    if s is None or s.source_pdf_page is None:
        return None
    nxt = (
        MunicipalCodeSection.objects
        .filter(source_pdf_page__gt=s.source_pdf_page)
        .order_by("source_pdf_page")
        .only("source_pdf_page")
        .first()
    )
    end = (nxt.source_pdf_page - 1) if nxt else (s.source_pdf_page + 10)
    # Captioned figures sometimes spill onto the page where the next
    # section begins (see 23.48.235 Exhibit C on page 3018). Probe one
    # extra page.
    end = end + 1
    return (s.source_pdf_page, end)


class Command(BaseCommand):
    help = "Extract figures from SMC PDF; splice markdown image links into full_text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--section",
            help="Process only figures whose caption targets this section.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen; no PNG writes, no DB writes.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-extract PNGs and re-splice markdown even if already present.",
        )

    def handle(self, *args, **options):
        section_filter = options.get("section")
        dry = options["dry_run"]
        force = options["force"]

        page_range = _resolve_page_range(section_filter) if section_filter else None
        if section_filter and page_range:
            self.stdout.write(
                f"Scanning PDF pages {page_range[0]}-{page_range[1]} for figures..."
            )
        else:
            self.stdout.write("Scanning PDF for figures...")
        with pdfplumber.open(settings.SMC_PDF_PATH) as pdf:
            figures = _scan_pdf(pdf, section_filter=section_filter, page_range=page_range)
            self.stdout.write(
                f"Found {len(figures)} captioned figure(s) "
                f"across {len({f.target_section for f in figures})} section(s)."
            )

            # Group by target section so we can splice once per section.
            by_section: dict[str, list[Figure]] = {}
            for fig in figures:
                by_section.setdefault(fig.target_section, []).append(fig)

            n_png_written = 0
            n_sections_updated = 0
            n_orphan_figures = 0

            for sec_num in sorted(by_section):
                figs = by_section[sec_num]
                section = (
                    MunicipalCodeSection.objects
                    .filter(section_number=sec_num)
                    .first()
                )
                if section is None and sec_num == RECOVER_23_48_235["section_number"]:
                    section = self._recover_23_48_235(pdf, dry=dry)
                    if section is None:
                        # Synthesis failed — report and skip; the figure
                        # PNGs still get written so the data is ready
                        # whenever the synthesis path is fixed.
                        self.stderr.write(self.style.WARNING(
                            f"  {sec_num}: synthesis failed; figures saved as orphans"
                        ))

                if section is None:
                    n_orphan_figures += len(figs)
                    self.stderr.write(self.style.NOTICE(
                        f"  {sec_num}: no DB row; saving {len(figs)} figure(s) as orphan PNGs"
                    ))
                    if not dry:
                        for fig in figs:
                            page = pdf.pages[fig.page_num - 1]
                            try:
                                size = _save_figure_png(page, fig)
                                n_png_written += 1
                                self.stdout.write(f"    saved {_figure_path(fig).name} ({size:,}B)")
                            finally:
                                page.flush_cache()
                    continue

                # Render PNGs and splice into the section's full_text.
                new_text = section.full_text
                splice_count = 0
                for fig in figs:
                    page = pdf.pages[fig.page_num - 1]
                    try:
                        out_path = _figure_path(fig)
                        if force or not out_path.exists():
                            if not dry:
                                size = _save_figure_png(page, fig)
                                n_png_written += 1
                                self.stdout.write(
                                    f"    saved {out_path.relative_to(FIGURES_DIR.parent)} "
                                    f"({size:,}B)"
                                )
                            else:
                                self.stdout.write(
                                    f"    would save {out_path.relative_to(FIGURES_DIR.parent)}"
                                )
                    finally:
                        page.flush_cache()
                    new_text, changed = _splice_figure_into_full_text(new_text, fig)
                    if not changed:
                        # No clean caption line — fall back to
                        # appending before the citation. Used by
                        # 23.48.235 whose bleed-over has the caption
                        # broken into multi-line fragments.
                        new_text, changed = _append_figure_before_citation(new_text, fig)
                    if changed:
                        splice_count += 1

                if splice_count and new_text != section.full_text:
                    n_sections_updated += 1
                    self.stdout.write(
                        f"  {sec_num}: spliced {splice_count}/{len(figs)} figure(s) "
                        f"into full_text"
                    )
                    if not dry:
                        section.full_text = new_text
                        section.save(update_fields=["full_text"])
                else:
                    self.stdout.write(
                        f"  {sec_num}: {len(figs)} figure(s); no full_text change"
                    )

            self.stdout.write(self.style.SUCCESS(
                f"\nDone. PNGs written: {n_png_written}. "
                f"Sections updated: {n_sections_updated}. "
                f"Orphan figures: {n_orphan_figures}."
            ))

    def _recover_23_48_235(self, pdf, dry: bool) -> MunicipalCodeSection | None:
        """Synthesize section 23.48.235 by:
        * Finding the bleed-over content inside 23.48.230's full_text
          (the parser put 23.48.235's prose there because it couldn't
          detect the heading).
        * Slicing that content out of 23.48.230.
        * Building a clean full_text for 23.48.235 from the slice.
        * Creating the new MunicipalCodeSection row.

        Returns the new section or None on failure. Idempotent: if
        23.48.235 already exists, returns it untouched.
        """
        existing = (
            MunicipalCodeSection.objects
            .filter(section_number="23.48.235")
            .first()
        )
        if existing:
            return existing

        donor = (
            MunicipalCodeSection.objects
            .filter(section_number="23.48.230")
            .first()
        )
        if donor is None:
            self.stderr.write(self.style.WARNING(
                "  23.48.235 recovery: donor 23.48.230 not in DB; skipping"
            ))
            return None

        marker = RECOVER_23_48_235["bleed_marker"]
        idx = donor.full_text.find(marker)
        if idx < 0:
            self.stderr.write(self.style.WARNING(
                "  23.48.235 recovery: bleed marker not found in 23.48.230; skipping"
            ))
            return None

        # Walk back to the start of the line containing the marker —
        # that's where 23.48.230's prose ends and 23.48.235's content
        # begins.
        line_start = donor.full_text.rfind("\n", 0, idx)
        if line_start < 0:
            line_start = 0
        donor_clean = donor.full_text[:line_start].rstrip()
        recovered = donor.full_text[line_start:].lstrip("\n")
        recovered = self._clean_23_48_235_recovered(recovered)

        new_section = MunicipalCodeSection(
            title_number=RECOVER_23_48_235["title_number"],
            chapter_number=RECOVER_23_48_235["chapter_number"],
            section_number=RECOVER_23_48_235["section_number"],
            title=RECOVER_23_48_235["title"],
            full_text=recovered,
            source_pdf_page=RECOVER_23_48_235["source_pdf_page"],
            subchapter=donor.subchapter,
        )
        self.stdout.write(self.style.SUCCESS(
            f"  23.48.235 recovery: synthesized "
            f"({len(recovered):,} chars from 23.48.230 bleed-over)"
        ))
        if dry:
            return new_section

        with transaction.atomic():
            new_section.save()
            donor.full_text = donor_clean
            donor.save(update_fields=["full_text"])
        return new_section

    # Patterns that appear in 23.48.235's bleed-over text but aren't
    # part of the actual prose: running headers and the broken caption
    # / figure-title fragments that pdfplumber's column-major capture
    # split apart. Strip them so the recovered body reads as prose.
    _RECOVERY_FRAGMENT_PATTERNS = [
        r"^23\.48\.235\s+LANDUSECODE\s*$",      # running header (right side)
        r"^Upper-Level Setbacks\s*$",            # section title — redundant with `title` field
        r"^Exhibit\s+[A-Z]\s*$",                 # broken caption pieces
        r"^Exhibit\s+[A-Z]\s+for\s*$",           # broken caption tail
        r"^for\s+23\.48\.235\s*$",               # broken caption tail
        r"^Stepped Upper-Level\s*$",             # broken Exhibit-A title piece
        r"^Setbacks\s*$",                        # broken Exhibit-A title piece
        r"^Upper-Level Setback from Specified\s*$",  # broken Exhibit-B title piece
        r"^Streets in SM-SLU 85/65-160\s*$",     # broken Exhibit-B title piece
        r"^Zone\s*$",                            # broken Exhibit-B title piece
        r"^Horizontal Projection into\s*$",      # broken Exhibit-C title piece
    ]

    def _clean_23_48_235_recovered(self, text: str) -> str:
        """Drop known broken-fragment lines from 23.48.235's bleed-over.
        These appear because pdfplumber captured pages 3015-3018 as
        2-column body text and the 1-column figure captions / titles
        got broken across lines."""
        for pat in self._RECOVERY_FRAGMENT_PATTERNS:
            text = re.sub(pat, "", text, flags=re.MULTILINE)
        # Collapse runs of 2+ blank lines.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"
