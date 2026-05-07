"""Extract SMC table bodies via Claude Vision (issue #151).

Background
==========

`parse_smc_pdf` captures table headers (caption + column headers) when
it sees a tabular layout, but the body cells get dispersed as
free-floating text in the surrounding paragraphs. Result: 176 tables
across 86 sections have markdown table syntax but at most 1-2 body
rows; the rest of the data is scattered.

pdfplumber's built-in `extract_tables()` doesn't help — the SMC PDF
doesn't use ruled lines around tables, and the columnar body-text
layout fools whitespace-based heuristics (a 2026-05-06 spike
confirmed: rule-based extraction returns 0 tables on representative
sections like 6.420.100, 22.805.070, 23.41.004).

This command sends the relevant PDF page(s) as images to Claude Haiku
4.5, which extracts structured tables (title, header rows, body rows,
footnotes), then splices proper markdown back into `full_text`.

Cost: ~$0.005-0.01/section at Haiku rates; ~$0.50-2 for the full
corpus of 86 affected sections.

Usage
=====

::

    # Single section (good for validation)
    python manage.py extract_smc_tables --section 6.420.100

    # Full corpus (skips sections that already have ≥3 body rows)
    python manage.py extract_smc_tables --all

    # Smoke run
    python manage.py extract_smc_tables --all --limit 5 --dry-run

    # Try a different model (when Haiku misses something)
    python manage.py extract_smc_tables --section 23.47A.004 --model claude-sonnet-4-6

Idempotent — re-runs skip sections whose tables already have body data.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass

import anthropic
import pdfplumber
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from seattle_app.models import MunicipalCodeSection

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
FALLBACK_MODEL = "claude-sonnet-4-6"

# Pages are rendered at 150 DPI — empirically a good balance of legibility
# (small-font cells in 23.47A.004's permission matrix still readable) and
# token cost (~1700 image tokens per page).
RENDER_RESOLUTION = 150

# Body-row threshold for "needs extraction." Sections whose existing
# tables have at least this many body rows are treated as already-good
# and skipped. Most broken tables today have 0-2 body rows; well-formed
# ones (post-extraction) have many more.
GOOD_TABLE_BODY_ROWS = 3

# Anthropic max_tokens for the response. The 23.47A.004 use-permissions
# matrix is the worst case (multi-page, many rows × many columns); 8K
# tokens covers it with margin.
MAX_TOKENS = 8192


SYSTEM_PROMPT = """You are extracting tables from pages of the Seattle \
Municipal Code PDF.

The PDF uses a 2-column body-text layout. Most pages are prose; a small \
fraction contain real data tables (rate tables, license requirements, \
dimensional standards, use-permission matrices). DO NOT treat the prose \
two-column body-text layout as a table.

When pages are provided in sequence and a table spans multiple pages, \
return it as ONE table with all body rows merged in page order — don't \
emit duplicate "Table A" entries for continuation pages.

Tables with DIFFERENT titles are ALWAYS separate tables, even when they \
appear on the same page or directly adjacent. "Table A" vs "Table B" vs \
"Table B-1" vs "Table B-2" are distinct — emit one entry per distinct \
title with rows scoped to that table only. Do NOT merge rows from \
different tables into one entry.

For each REAL data table, return:
- title: the table's caption (e.g. "Table A for 6.420.100 License \
Requirements for Operation of Power Boilers and Steam Engines")
- header_rows: column header rows (sometimes multi-row)
- body_rows: data rows
- footnotes: any footnote text directly tied to the table

Each row is an array of cell strings. All rows in a single table must \
have the same number of cells; pad with empty strings where the source \
shows merged or blank cells. Section-divider rows (like \
"A. All Boilers" spanning the whole row) should put the label in cell \
zero and use empty strings for the rest, preserving the column count.

JOIN line-break-hyphenated words: "Primaryelec- tion" → "Primary \
election", "max-imum" → "maximum". Keep numbers, dollar amounts, and \
abbreviations as printed. Preserve superscript markers as caret notation \
(e.g. "X^a, b").

If no real data tables are present, return tables: []."""


USER_PROMPT = (
    "Extract the real data tables visible in the attached PDF page(s). "
    "Return ONLY a JSON object with shape "
    '{"tables": [{"title": str, "header_rows": [[str, ...]], '
    '"body_rows": [[str, ...]], "footnotes": [str, ...]}]}. No prose '
    "outside the JSON."
)


# Markdown table row: starts and ends with `|` after stripping whitespace.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
# Separator row cell — `---`, `:---`, `:---:`, etc.
_TABLE_SEP_CELL_RE = re.compile(r"^:?-+:?$")


@dataclass
class TableBlock:
    """Span of consecutive markdown-table-syntax lines in `full_text`."""
    start_line: int  # inclusive
    end_line: int    # inclusive
    body_row_count: int


def _scan_table_blocks(full_text: str) -> list[TableBlock]:
    """Find contiguous runs of `| ... |` lines in full_text. Each run is
    one block; consecutive blocks separated by non-table lines are
    distinct entries.
    """
    lines = full_text.split("\n")
    blocks: list[TableBlock] = []
    cur_start: int | None = None
    cur_rows: list[list[str]] = []
    for i, line in enumerate(lines):
        if _TABLE_ROW_RE.match(line):
            if cur_start is None:
                cur_start = i
                cur_rows = []
            cells = [c.strip() for c in line.strip().lstrip("|").rstrip("|").split("|")]
            cur_rows.append(cells)
        else:
            if cur_start is not None:
                sep_idx = next(
                    (j for j, r in enumerate(cur_rows)
                     if r and all(_TABLE_SEP_CELL_RE.match(c) for c in r)),
                    -1,
                )
                body = max(0, len(cur_rows) - sep_idx - 1) if sep_idx >= 0 else 0
                blocks.append(TableBlock(cur_start, i - 1, body))
                cur_start = None
                cur_rows = []
    if cur_start is not None:
        sep_idx = next(
            (j for j, r in enumerate(cur_rows)
             if r and all(_TABLE_SEP_CELL_RE.match(c) for c in r)),
            -1,
        )
        body = max(0, len(cur_rows) - sep_idx - 1) if sep_idx >= 0 else 0
        blocks.append(TableBlock(cur_start, len(lines) - 1, body))
    return blocks


# Matches one "table code" — the letter (and optional `-N` suffix) Markdown
# tables are conventionally identified by, e.g. "A", "B", "B-1", "A-2".
_TABLE_CODE_RE = re.compile(r"Table\s+([A-Z][\w-]{0,5})")


def _expected_table_codes(section: MunicipalCodeSection) -> set[str]:
    """Find all `Table X for <this section>` references in the section's
    prose. Returns the table codes (e.g. ``{'A'}``, ``{'B-1', 'B-2'}``).

    Cross-references to OTHER sections' tables (``Table A for 23.47A.004``
    appearing in a different section) don't count — we anchor on this
    section's number."""
    pat = re.compile(
        r"Table\s+([A-Z][\w-]{0,5})\s+for\s+" + re.escape(section.section_number)
    )
    return {m.group(1).rstrip("-") for m in pat.finditer(section.full_text or "")}


def _found_table_codes(tables: list[dict]) -> set[str]:
    """Extract the table codes from extracted tables' titles."""
    out: set[str] = set()
    for t in tables:
        m = _TABLE_CODE_RE.search(t.get("title") or "")
        if m:
            out.add(m.group(1).rstrip("-"))
    return out


def _needs_fallback(section: MunicipalCodeSection, tables: list[dict]) -> tuple[bool, str]:
    """Decide whether to retry with the heavier model. Returns
    ``(should_retry, reason)``.

    Two triggers:

    * Haiku returned no tables at all from a section that explicitly
      references its own tables in prose.
    * Haiku returned fewer distinct table codes than the section
      references — typical merged-tables case (B-1 + B-2 collapsed into
      one "B-1" entry; section text mentions B-2 separately).
    """
    expected = _expected_table_codes(section)
    found = _found_table_codes(tables)
    if not tables and expected:
        return True, f"haiku returned 0 tables but section mentions {sorted(expected)}"
    missing = expected - found
    if missing:
        return True, f"missing table codes: {sorted(missing)} (haiku found {sorted(found)})"
    return False, ""


def _needs_extraction(section: MunicipalCodeSection) -> bool:
    """Return True if the section's `full_text` looks like it needs
    Vision-based table extraction.

    Two failure modes the parser produces:

    * Has markdown table syntax (``| --- |``) but the body is too thin
      (1-2 rows or fewer). The body cells got dispersed as orphan
      paragraphs around the markdown block.
    * Has table content captured as text-only (no markdown syntax) by
      PR #59's earlier table-aware extraction. Detect via the
      ``Table A for <this section's number>`` reference pattern in
      prose. Cross-references to *other* sections' tables don't count
      — they're SMC navigation links, not evidence that this section
      has its own broken table.

    Sections that already have a markdown table block with at least
    ``GOOD_TABLE_BODY_ROWS`` body rows are considered fixed.
    """
    text = section.full_text or ""
    blocks = _scan_table_blocks(text)
    if blocks:
        max_body = max(b.body_row_count for b in blocks)
        return max_body < GOOD_TABLE_BODY_ROWS
    own_table_re = re.compile(r"Table [A-Z] for " + re.escape(section.section_number))
    return bool(own_table_re.search(text))


def _section_page_range(section: MunicipalCodeSection, pdf=None) -> tuple[int, int] | None:
    """Return (start_page, end_page) inclusive for `section`, where
    end_page is the page before the next section's start. Returns None
    if `source_pdf_page` isn't set.

    If `pdf` is supplied, probe one page past the natural end: if it
    still references this section by number (table continuation), extend
    the range to include it. Tables routinely span across the boundary
    where the next section begins — see 22.900B.020 (Table B-2 spilled
    onto page 2664, the start of 22.900B.030)."""
    start = section.source_pdf_page
    if not start:
        return None
    next_section = (
        MunicipalCodeSection.objects
        .filter(source_pdf_page__gt=start)
        .order_by("source_pdf_page")
        .only("source_pdf_page")
        .first()
    )
    end = (next_section.source_pdf_page - 1) if next_section else start + 5
    # Cap span at 8 pages — protects against missing-next-section cases
    # where we'd otherwise scan to the end of the PDF.
    end = min(end, start + 7)

    # Continuation probe: if the page just past `end` still mentions
    # this section's number, the section's table likely spilled over.
    if pdf is not None and end < start + 7 and end < len(pdf.pages):
        try:
            probe_text = pdf.pages[end].extract_text() or ""
            if section.section_number in probe_text and "Table" in probe_text:
                end += 1
        except Exception:
            pass

    return start, end


def _render_page_b64(page) -> str:
    img = page.to_image(resolution=RENDER_RESOLUTION)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _strip_json_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _normalize_cell_counts(rows: list[list[str]]) -> list[list[str]]:
    """Pad every row to the max width with empty strings."""
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    return [r + [""] * (width - len(r)) for r in rows]


def _escape_cell(s: str) -> str:
    """Escape pipes and collapse internal newlines so a cell is safe for
    a single-line markdown table row."""
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _render_table_md(table: dict) -> str:
    """Format a structured table as markdown. Caller is responsible for
    normalizing column counts; this just emits the rows."""
    title = table.get("title") or "Table"
    headers = table.get("header_rows") or []
    body = table.get("body_rows") or []
    footnotes = table.get("footnotes") or []

    width = max(
        [len(r) for r in headers] +
        [len(r) for r in body] +
        [1],
    )

    def emit_row(cells):
        padded = (cells + [""] * width)[:width]
        return "| " + " | ".join(_escape_cell(c) for c in padded) + " |"

    out = []
    # Caption row spans full width; title in cell 0, blanks elsewhere.
    out.append(emit_row([title]))
    for h in headers:
        out.append(emit_row(h))
    out.append("| " + " | ".join(["---"] * width) + " |")
    for b in body:
        out.append(emit_row(b))
    for fn in footnotes:
        out.append(f"_{fn.strip()}_")
    return "\n".join(out)


_MIN_CELL_MATCH_LEN = 5


def _orphan_cells_set(tables: list[dict]) -> set[str]:
    """Cell strings (≥ ``_MIN_CELL_MATCH_LEN`` chars) extracted from the
    structured tables, used to recognize the parser's dispersed
    leftovers in prose. Skips trivial cells like ``""`` or ``"P"``."""
    out: set[str] = set()
    for t in tables:
        for row in (t.get("header_rows") or []) + (t.get("body_rows") or []):
            for c in row:
                cell = c.strip()
                if len(cell) >= _MIN_CELL_MATCH_LEN:
                    out.add(cell)
    return out


def _strip_orphan_lines(lines: list[str], from_idx: int, cells: set[str]) -> list[str]:
    """Remove lines starting at ``from_idx`` whose content is dominated by
    table-cell substrings (the parser's broken-table fallout). Stop at
    the first line that doesn't look like cell content — that's where
    real prose resumes.

    Returns a new list with orphan lines elided. Blank lines inside the
    orphan run are also removed; they preserve no useful structure."""
    if not cells:
        return lines
    keep = lines[:from_idx]
    i = from_idx
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            # Empty lines inside the orphan run are dropped silently.
            # Once we exit the run we'll re-add a single separating
            # blank.
            i += 1
            continue
        if any(c in line for c in cells):
            i += 1
            continue
        break
    # Re-attach a single blank line if anything remains to keep
    # paragraph spacing intact.
    if i < len(lines):
        keep.append("")
        keep.extend(lines[i:])
    return keep


def _splice_tables(full_text: str, tables: list[dict], tables_md: list[str]) -> str:
    """Replace the contiguous table-region in `full_text` (from the first
    `|` line to the last) with the joined `tables_md`. If multiple
    table blocks exist with non-table content between them, that
    intervening content is dropped — those are typically the "orphan
    body cells" the parser emitted when it lost the table body.

    If `full_text` has no existing `|...|` lines (the section's tables
    were captured by PR #59's text-extraction path rather than as
    markdown — see 23.47A.004, 23.54.015), append the new markdown at
    a sensible insertion point: just before the trailing ordinance
    citation block (`(Ord. NNNNNN, …)`) if one exists, otherwise at
    the end of the section text.

    After splicing in either path, scan past the new markdown for
    "orphan" lines whose content is dominated by cell strings from
    the extracted tables — those are the parser's leftover dispersed
    body cells (e.g. 22.900B.020's `8½" × 11"  $0.85 per printed page`
    that lived in prose alongside the broken markdown). Strip them
    so the section doesn't double-render the same data."""
    new_block = "\n\n".join(tables_md)
    new_block_lines = new_block.split("\n")
    cells = _orphan_cells_set(tables)
    lines = full_text.split("\n")
    table_line_idxs = [i for i, line in enumerate(lines) if _TABLE_ROW_RE.match(line)]

    if table_line_idxs:
        first = table_line_idxs[0]
        last = table_line_idxs[-1]
        # Splice in the new block, then strip orphans starting just
        # past where the new block ends.
        head = lines[:first]
        tail = lines[last + 1:]
        rebuilt = head + new_block_lines + tail
        cleaned = _strip_orphan_lines(rebuilt, len(head) + len(new_block_lines), cells)
        return "\n".join(cleaned)

    # No existing markdown — append before the trailing ordinance-
    # citation block when one exists, otherwise at the end.
    cite_match = re.search(r"\n\(Ord\.\s+\d", full_text)
    if cite_match:
        head_text = full_text[: cite_match.start()].rstrip()
        tail_text = full_text[cite_match.start():].lstrip("\n")
        # Strip orphans from the head before reattaching the citation
        # tail. Walk backward through head_text for cell-heavy lines.
        head_lines = head_text.split("\n")
        head_lines = _strip_trailing_orphans(head_lines, cells)
        return "\n".join(head_lines) + "\n\n" + new_block + "\n" + tail_text
    head_lines = full_text.rstrip().split("\n")
    head_lines = _strip_trailing_orphans(head_lines, cells)
    return "\n".join(head_lines) + "\n\n" + new_block + "\n"


def _strip_trailing_orphans(lines: list[str], cells: set[str]) -> list[str]:
    """Walk backward through ``lines`` removing trailing orphan-cell
    lines (no `|...|` markdown present, so orphans live at the end of
    the body before the citation footer or EOF)."""
    if not cells:
        return lines
    end = len(lines)
    while end > 0:
        line = lines[end - 1].strip()
        if not line:
            end -= 1
            continue
        if any(c in line for c in cells):
            end -= 1
            continue
        break
    return lines[:end]


def _merge_continuation_tables(tables: list[dict]) -> list[dict]:
    """Tables emitted across multiple pages sometimes come back as
    multiple entries with the same "Table X" prefix. Merge them by
    matching the leading "Table [code]" prefix (where code is a letter
    plus any `-N` / `.N` suffix), concatenating body rows in order.
    Also drops empty-body tables (continuation artifacts where the
    model saw the header but no rows).

    The code-with-suffix match is critical for sections like
    22.900B.020 where Table B-1 and Table B-2 are distinct tables —
    a bare-letter match would collapse them.
    """
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for t in tables:
        title = (t.get("title") or "").strip()
        m = re.match(r"(Table\s+[A-Z][\w-]{0,5})", title)
        key = m.group(1).upper() if m else title.upper()
        if key in by_key:
            existing = by_key[key]
            existing["body_rows"].extend(t.get("body_rows") or [])
            for fn in (t.get("footnotes") or []):
                if fn not in existing["footnotes"]:
                    existing["footnotes"].append(fn)
        else:
            by_key[key] = {
                "title": title,
                "header_rows": list(t.get("header_rows") or []),
                "body_rows": list(t.get("body_rows") or []),
                "footnotes": list(t.get("footnotes") or []),
            }
            order.append(key)
    return [by_key[k] for k in order if by_key[k]["body_rows"]]


class Command(BaseCommand):
    help = "Extract SMC table bodies via Claude Vision and splice into full_text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--section",
            help="Process this single section number (e.g. 6.420.100).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process every section that has broken table syntax.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after processing N sections.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--model",
            default=DEFAULT_MODEL,
            help=f"Anthropic model id (default: {DEFAULT_MODEL}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-process sections that already look fixed (≥3 body rows).",
        )

    def handle(self, *args, **options):
        if not options["section"] and not options["all"]:
            raise CommandError("Pass --section <N> or --all.")
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError("ANTHROPIC_API_KEY is not configured.")

        sections = self._select_sections(options)
        if not sections:
            self.stdout.write(self.style.NOTICE("No sections need extraction."))
            return

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        model = options["model"]
        dry = options["dry_run"]

        self.stdout.write(f"Processing {len(sections)} section(s) with {model}...")

        with pdfplumber.open(settings.SMC_PDF_PATH) as pdf:
            for section in sections:
                self._process_section(client, model, pdf, section, dry)

    def _select_sections(self, options) -> list[MunicipalCodeSection]:
        """Pick sections to process. Either the single one requested, or
        every section with table content that needs Vision extraction.

        Two populations qualify for `--all`:

        * Sections with a markdown table block that has too few body
          rows (the 86 sections produced by the parser's general
          markdown-table path — these have ``| ---`` syntax but bodies
          got dispersed as orphan paragraphs).
        * Sections with table content captured as text-only by PR #59's
          earlier table-aware extraction (23.47A.004 / 23.54.015 and
          similar) — these reference their own table by name (``Table A
          for 23.47A.004 …``) but never produced markdown syntax.
        """
        if options["section"]:
            try:
                s = MunicipalCodeSection.objects.get(section_number=options["section"])
            except MunicipalCodeSection.DoesNotExist:
                raise CommandError(f"No section {options['section']!r}.")
            return [s]

        qs = (
            MunicipalCodeSection.objects
            .filter(
                Q(full_text__contains="| ---")
                | Q(full_text__regex=r"Table [A-Z] for ")
            )
            .order_by("section_number")
        )
        force = options["force"]
        limit = options["limit"]
        out: list[MunicipalCodeSection] = []
        for s in qs:
            if not force and not _needs_extraction(s):
                continue
            out.append(s)
            if limit and len(out) >= limit:
                break
        return out

    def _process_section(self, client, model, pdf, section, dry):
        sn = section.section_number
        page_range = _section_page_range(section, pdf=pdf)
        if not page_range:
            self.stderr.write(self.style.WARNING(
                f"  {sn}: source_pdf_page not set; skipping"
            ))
            return
        start, end = page_range
        page_count = end - start + 1

        self.stdout.write(f"\n=== {sn} (pages {start}-{end}, {page_count} page(s)) ===")

        # Render every page in range. Each page becomes one image content
        # block; the model sees the full section context and can resolve
        # cross-page table continuations natively.
        try:
            images = []
            for page_num in range(start, end + 1):
                page = pdf.pages[page_num - 1]
                images.append(_render_page_b64(page))
        except IndexError:
            self.stderr.write(self.style.WARNING(
                f"  {sn}: page out of range; skipping"
            ))
            return

        try:
            tables = self._extract_tables(client, model, images)
        except Exception as e:
            self.stderr.write(self.style.ERROR(
                f"  {sn}: extraction failed ({type(e).__name__}: {e}); skipping"
            ))
            return

        tables = _merge_continuation_tables(tables)
        used_model = model

        # Sonnet fallback for two failure modes Haiku exhibits on tricky
        # multi-table sections:
        #   * Returns 0 tables when the section's prose explicitly names
        #     its own tables (Vision didn't recognize the layout).
        #   * Returns fewer distinct tables than referenced — typically
        #     "Table B-1" + "Table B-2" merged into one entry, with
        #     "Table B-2" still mentioned in the section's prose.
        # Skip the fallback entirely when the user explicitly chose a
        # model via --model.
        retry, reason = _needs_fallback(section, tables)
        user_chose_model = model != DEFAULT_MODEL
        if retry and not user_chose_model:
            self.stdout.write(self.style.NOTICE(
                f"  {sn}: falling back to {FALLBACK_MODEL} — {reason}"
            ))
            try:
                sonnet_tables = self._extract_tables(client, FALLBACK_MODEL, images)
                sonnet_tables = _merge_continuation_tables(sonnet_tables)
            except Exception as e:
                self.stderr.write(self.style.WARNING(
                    f"  {sn}: fallback failed ({type(e).__name__}: {e}); using Haiku output"
                ))
                sonnet_tables = []
            if sonnet_tables:
                # Take Sonnet's result if it covers strictly more table
                # codes than Haiku — the merged-tables case where Haiku
                # collapsed two tables into one. If Sonnet covers fewer
                # or the same, keep Haiku's output (it's not worse and
                # might have richer body content per table).
                sonnet_codes = _found_table_codes(sonnet_tables)
                haiku_codes = _found_table_codes(tables)
                if len(sonnet_codes) > len(haiku_codes) or (not tables and sonnet_tables):
                    tables = sonnet_tables
                    used_model = FALLBACK_MODEL

        if not tables:
            self.stdout.write(self.style.WARNING(
                f"  {sn}: model returned 0 tables — leaving full_text unchanged"
            ))
            return

        # Normalize cell counts within each table.
        for t in tables:
            t["header_rows"] = _normalize_cell_counts(t["header_rows"])
            t["body_rows"] = _normalize_cell_counts(t["body_rows"])

        tables_md = [_render_table_md(t) for t in tables]
        new_full_text = _splice_tables(section.full_text, tables, tables_md)

        # Report (note which model produced the kept output).
        model_tag = " (sonnet fallback)" if used_model == FALLBACK_MODEL else ""
        self.stdout.write(f"  extracted {len(tables)} table(s){model_tag}:")
        for t in tables:
            self.stdout.write(
                f"    {t['title'][:80]} — "
                f"{len(t['header_rows'])} header / "
                f"{len(t['body_rows'])} body / "
                f"{len(t['footnotes'])} footnotes"
            )

        if dry:
            self.stdout.write(self.style.NOTICE("  (--dry-run; not writing)"))
            return

        section.full_text = new_full_text
        section.save(update_fields=["full_text"])
        self.stdout.write(self.style.SUCCESS(f"  saved."))

    def _extract_tables(self, client, model, page_images_b64: list[str]) -> list[dict]:
        content = []
        for b64 in page_images_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        content.append({"type": "text", "text": USER_PROMPT})

        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        cleaned = _strip_json_fences(text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Some models wrap the JSON in prose despite instructions; try
            # to grab the outer object.
            m = re.search(r"\{.*\}", cleaned, re.S)
            if not m:
                raise
            data = json.loads(m.group(0))

        return data.get("tables") or []
