# Work Log

Long-lived context for Seattle Councilmatic that git and GitHub can't tell you:
locked decisions, known follow-up threads, and a chronological merge log.
**Branch state lives in `gh pr list` — this file does not track it.**

---

## Decisions

- **Frontend ownership.** Django admin at `/admin/` and Wagtail admin at `/cms/` stay server-rendered. The Vite React SPA owns `/` and every unmatched path; Django's `react_app` view returns `frontend/dist/index.html` for those. `STATIC_URL` is `/static/` and Vite's `base` matches.
- **`base.html` retained.** Kept (with webpack-loader stripped) because `404.html` and `500.html` extend it via `handler404`/`handler500`. Don't delete unless you also rewrite the error templates.

## Up next

Prioritized to-do. Quick wins flagged with *(quick)*.

**Frontend**
- **Meeting agenda items (WIP).** Pick up the work in worktree `claude/zealous-tharp` at `.claude/worktrees/zealous-tharp`, commit `baa719c`. Touches `seattle/events.py` (uncomment + implement `_add_agenda_items`, scrape `hypAgendaPacket` from Legistar HTML), `seattle_app/api_views.py` (return `agenda_items`, `agenda_file_url`, `packet_url`, `minutes_file_url`, `minutes_status`), `frontend/src/components/MeetingDetail.jsx` (~93 LoC of new components: `MatterChip`, `DocIcon`, `AgendaDocButtons`, `AgendaItemRow`). When ready: branch from `main`, cherry-pick `baa719c`, open PR.

**SPA index/search pages** (each likely its own PR; specifics TBD when we pick them up)
- `/legislation/` — search and browse all legislation. `ThisWeek` only shows recent; needs an API search endpoint (or extend `/api/legislation/recent/` with query params) plus a list/filter UI. After shipping, update the `NotFound` `legislation` variant link from `/` to `/legislation/`.
- `/events/` — search and browse all council meetings. Same shape as the legislation index. After shipping, update the `NotFound` `meeting` variant link from `/` to `/events/`.
- `/municode/` — search and browse the Seattle Municipal Code. First user-facing surface for the `MunicipalCodeSection` rows the parser populates. Big open questions: search vs hierarchical browse (Title → Chapter → Section), full-text vs metadata filters, how to render section text. Natural place to surface section-level LLM summaries when those wire up.

**LLM summaries — wire up the existing infrastructure**
- Models, service module, and prompts already exist (`seattle_app/models.py:47,84` for `MunicipalCodeSection.plain_summary` + `LegislationSummary`; `seattle_app/services/claude_service.py` for `summarize_section`/`summarize_legislation` with full prompts). Nothing runs them and nothing surfaces them to users yet.
- Three pieces to ship the feature end-to-end:
  1. **Management command** to batch-summarize sections and bills (e.g., `summarize_smc_sections`, `summarize_legislation`) — handle prompt caching, rate limits, resumability, and skip already-summarized rows.
  2. **API**: extend `/api/legislation/<slug>/` to include `llm_summary` (summary, impact_analysis, key_changes); add `/api/smc/<section>/` (or similar) for section summaries.
  3. **Frontend**: render summary in `LegislationDetail` (probably above the action history). Decide whether to surface SMC section summaries — depends on whether there's a user-facing SMC browser yet.
- Open design questions: which Claude model? per-section caching strategy? batch via Anthropic Batch API to halve cost?

**Parser quality** (post-fix re-parse 2026-04-26: 7,421 sections after PR #22 / 81 `ParseValidationIssue` rows; +1 `TitleAppendix` row after PR #23)
- **Recover the last 6 small missing sections** (`12A.14.160`, `23.48.235`, `23.50A.160`, `23.76.067`, `25.24.030`, `5.48.050`). All ≤ 1k chars, scattered across titles, each with its own layout quirk that PR #22's per-page boundary reset and column-split-strip narrowing didn't catch. Investigate one at a time — likely a mix of column-split title bleed (`8.38.010` style: pdfplumber returns title wraps in wrong order across columns), unfiltered layout artifacts, and individual edge cases. Lowest priority; we're at >99% recovery.
- **Column-split title-fold returns wrong wrap continuation.** Visible on `8.38.010 Short title "Canna-` where the soft-hyphen fold-during-emit (`if title.endswith("-"): title += next_line`) takes the literal next line in reading order, but pdfplumber's column-aware reader puts the wrong column's wrap there. Result: title becomes `Short title "CannaThis Chapter 8.38 shall constitute the` instead of `Short title "Cannabis Employee Job Retention Ordinance"`. Probably needs lookahead through the line list to find the actual wrap (look for the line that, prepended to the hyphen-broken title, reads grammatically) — or skip column-split title folds entirely and accept the truncated title.
- **Table-aware extraction for table-heavy LUC sections.** Sections like `23.47A.004` and `23.54.015` contain large permission tables (Table A "Permitted and prohibited uses by zone"). pdfplumber's column-aware word extraction loses table structure: the cell values arrive as a bag of bare codes (`X X X CCU CCU`, `P P P P P`, etc.) with no row labels (use names) attached, so it's impossible to tell "is a restaurant permitted in NC2?" from the parsed text. Use `pdfplumber.extract_tables()` to detect and serialize tables (probably as markdown rows) and substitute them in place where the column-aware reader currently emits jumbled cells. Applies to `23.47A.004`, `23.54.015`, and likely most LUC sections that reference "Table A for X.Y.Z".
- Investigate `25.05.990` and similar pages where pdfplumber returns 5-line malformed extractions.
- Review the 17 synthesized subchapters (chapter has body divider but no TOC scrape) — some may indicate scanner gaps.
- Review the 11 "declared-but-empty" subchapters flushed without body sections (down from 37 pre-fix).

## Open threads

Lower-priority backlog — fix when you're already in the area, not worth scheduling. (Empty for now; promote items here from Up next when they're deferred.)

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`, `frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching branches:** WIP commit (`wip: <short-state>`) and push so nothing is orphaned in a detached working tree.

**Branch follow-ups from `main`, not from in-flight branches.** Stack only when the new work genuinely depends on the prior branch's code. Stacking on an unmerged branch costs a rebase later — root cause of the WORK_LOG conflict on `frontend/spa-notfound`.

**Include the Done-move in the same PR that ships the work.** Add the workstream's entry under `## Done` in the same commit. Avoids the "stale section after merge" tax we kept hitting.

**Pre-flight at session start:** `git fetch && git log main..origin/main` to catch divergence between local and remote `main` before doing anything else. We lost time to a 16-commit divergence in 2026-04 that this would have caught in one command.

---

## Done

### Parser — capture Title appendix as a new model + fix `15.91.045` bleed — merged 2026-04-26 (PR #23)
Triage of the 10 oversized 30-50k-char sections found 9 legit (substantive long sections like SEPA `25.05.675` Specific environmental policies, alphabetical-definitions `23.84A.036 S`, parking standards `23.54.030`) and 1 buggy: `15.91.045 Additional relief.` was 44778 chars but its real body is ~283 chars — it was accreting Title 15's parks/scenic-routes appendix (pages 2047-2086+, referenced by SEPA) because the parser had no terminator for `APPENDICES I AND II TO TITLE 15`-style headings. Rather than just terminate the section and drop the appendix content, we capture it as a `TitleAppendix(title_number, label, full_text, source_pdf_page)` row keyed by `(title_number, label)`.

New: model `TitleAppendix`, migration 0013, `APPENDIX_HEADING_RE`, `ParsedAppendix` dataclass, appendix-mode in `_walk_sections` (terminates current section, accumulates body until the next chapter heading, deduplicates the running header that repeats `APPENDICES I AND II TO TITLE 15` on every appendix page), `_persist_appendix`, dispatch in `handle()` via `isinstance(record, ParsedAppendix)`. Verified end-to-end on Title 15 → Title 16 transition (pages 2040-2095): `15.91.045` shrinks to 283 chars (real body), one `TitleAppendix(title='15', label='I AND II', chars=43105, page=2047)` row created. Title 16 chapter heading correctly closes the appendix.

Survey: only Title 15 has appendix-style headings in the SMC; the model handles other titles automatically if they ever add appendices.

### Parser — figure-page boundary + tighten column-split header strip — merged 2026-04-26 (PR #22)
Two fixes that together recover 11 of the 17 sections the PR #21 re-parse silently orphan-deleted:

1. **Per-page boundary reset.** `_walk_sections` carried `prev_line` across page boundaries, so a body section heading at `L0` of a page failed `_is_section_boundary` whenever the prior page ended mid-citation or with a layout label (`'... Ord. 125291, § 6,'`, `'Exhibit 23.64.004B'`, `'for 23.48.225'`). Reset `prev_line = None` at the start of each page — body prose that genuinely wraps across pages is unaffected because emission only fires for `SECTION_RE`-matching lines, and those only legitimately appear at line 0 if the new page begins a new section. Recovers `23.48.230` (7.8k chars), `23.64.006` (1.9k).
2. **Tighter column-split header strip.** PR #20's `_strip_layout_artifacts` was unconditionally skipping the bare-section-number line PLUS the next line at the start of the right column. On p2956 the next line is a section-name continuation (`'Specific Areas: Interbay'`) that should be stripped, but on pages like p1122 the next line is body wrap (`'tion and payments for services via the internet'`) — silently eating the body of `8.37.020` and similar. Now only strips the next line if it looks like a header continuation: capital-start, ≤50 chars, no terminal punctuation, not enumerated. Recovers `8.37.020` (20k chars), `8.39.150` (5.5k), `8.39.190` (1k), `8.38.010`, others.

Result: 7409 → 7421 unique sections (11 recovered, no regressions; +101 net since the pre-PR-#21 baseline). All 4 PR #20 recovery cases (`23.47A.002`, `23.47A.010`, `23.47A.040`, `23.54.015`) still emit. Six small losses (≤ 1k chars) remain — filed as Up-next.

### Parser — bound TOC fold to prevent body-into-title runaway — merged 2026-04-26 (PR #21)
PR #20's `_fold_toc_name_wraps` exited TOC mode only on `ENUMERATED_BODY_RE` (`A. ` / `1. `). Chapters whose body sections start with plain prose instead of enumerated subsections — Title 1 ch.1.03 was the canary, where `1.03.010`'s body opens with `'To maintain the records and laws of the City...'` — never tripped the exit signal, so the entire body folded into the last TOC entry's title until the next section heading. Crashed psycopg2 with a `varchar(500)` overflow on the first persist. Plus the heuristic was too tight on capital-starting wraps (rejected real continuations like `'Code reviser to revise laws'`), causing first-section losses in chapters with em-dash compound TOC entries.

Fixes: per-section caps (`_TOC_MAX_FOLD_LINES=3`, `_TOC_MAX_TITLE_CHARS=200`, `_TOC_MAX_WRAP_LINE_CHARS=50`) plus a `_looks_like_toc_continuation` heuristic that accepts any-length lowercase continuations and capital-starting continuations up to 35 chars. Verified Title 1 (28 emits vs 25 in DB, +3 newly-recovered, 0 lost) and Title 23 (1050 emits vs 1035 in DB, 24 recovered including all 4 PR #20 targets, 9 losses of which 6 look phantom and 3 substantive). The 3 substantive Title 23 losses are filed as a separate Up-next item — they're a different bug class (body heading at L0 of a page where the prior page is a sparse figure-only layout page whose tail breaks the boundary check).

### Parser — recover missing sections via TOC-fold + boundary fixes — merged 2026-04-25 (PR #20)
The WORK_LOG had flagged "recover real `23.54.015` and `23.47.004`" as a presumed table-extraction problem; investigation showed the headings were never lost to tables — the parser was emitting them but `_is_section_boundary` rejected them because the prev_line was a layout artifact. Four distinct failure modes uncovered, each fixed:

1. **Soft-hyphen TOC wraps** — last TOC entry's name wrapped via soft hyphen, leaving the wrap continuation as prev for the first body section. New `_fold_soft_hyphens` joins wraps where line N ends with `-` and line N+1 is a lowercase non-heading continuation.
2. **Multi-line non-hyphen TOC wraps** — `23.47A.040`'s TOC entry wraps to 4 lines without soft hyphens. New `_fold_toc_name_wraps` runs in TOC mode (between `Sections:` marker and the first enumerated body subsection like `A. ` / `1. `), folding every name-continuation line into its preceding section-shaped line. Bounded by per-section caps (`_TOC_MAX_FOLD_LINES=3`, `_TOC_MAX_TITLE_CHARS=200`, `_TOC_MAX_WRAP_LINE_CHARS=50`) plus a `_looks_like_toc_continuation` heuristic — needed because chapters like Title 1 ch.1.03 have body sections that don't start with enumerated subsections, so the original ENUMERATED_BODY_RE exit signal alone let the fold runaway and crash psycopg2 with a varchar(500) overflow.
3. **Footers with `.` in chapter-page identifier** — `(Seattle 9-23) 23-180.2` wasn't matched by `FOOTER_RE` (the `.` broke the trailing `[\s\d\-]*$`). Extended to `[\s\d\-\.]*`.
4. **Layout labels and column-split running headers** — lines like `23.47A Map Book A` (between TOC and body) and the `23.47A.009` + `Specific Areas: Interbay` pair (column-split right-half running header) leaked through. New `_strip_layout_artifacts` drops both: `LAYOUT_LABEL_RE` matches "X.Y Map Book/Table/Chart Z", and a bare section-number at the start of the right column triggers a 2-line skip.

Recovered sections (verified via dry-run on pages 2920–3320): `23.47A.002`, `23.47A.010`, `23.47A.040`, `23.54.015`. The fix is general — any chapter that fails for the same reasons will now emit. The `23.47.004` mention in the original WORK_LOG note was a confusion: no section by that number exists; the ghost we deleted in PR #17 had borrowed those digits from a citation list. The real `23.47A.004` was already in the DB.

Side effect: `_persist`'s "text changed" branch will fire on most existing sections during the next full re-parse because the folded lines change `full_text`. LLM summary fields will be cleared (none generated yet anyway). Filed table-aware extraction as a follow-up Up-next item.

### Parser — orphan-section cleanup — merged 2026-04-25 (PR #19)
New `--allow-deletes` flag on `parse_smc_pdf`. The parser now tracks the (title, chapter, section) tuples it emits during a run and, when the flag is set, deletes any `MunicipalCodeSection` rows in the parsed titles that weren't in that set — i.e. orphans left over from earlier buggy parses (the ghost `23.47.004` / `23.54.015` we had to manually `DELETE` after PR #17/#18). Cascade drops `SectionOrdinanceRef` rows; `LegislationSummary` M2M unlinks; `subchapter` FK is `SET_NULL` on the section side so subchapters aren't touched. Gated to full-PDF parses only — refused with `--dry-run`, `--limit`, or any non-default `--start-page`/`--end-page` since partial ranges can't safely tell which titles are fully covered. Each deletion is logged with `style.WARNING` for transparency. Runs before validation so `ParseValidationIssue` reflects the cleaned state.

### Parser — gate `extract_text()` fallback to transition pages — merged 2026-04-24 (PR #18)
PR #17's `_extract_page_lines` fallback called `page.extract_text()` on every page where no `CHAPTER_HEADING_RE` matched — which is most pages. `extract_text()` re-runs the full layout pipeline, so this roughly doubled per-page work and made a full re-parse churn for hours. New `CHAPTER_FRAGMENT_RE` matches a bare `Chapter` line or a bare chapter-number like `25.32`; the fallback only fires when such a fragment is present AND no `CHAPTER_HEADING_RE` line matched. Body pages have neither, so the fast path is restored. Caught when the user noticed the re-parse churning on Title 15 like before the parser improvements.

### Parser — section-boundary leak (catastrophic) — merged 2026-04-24 (PR #17, perf hotfix #18)
Fixed the three catastrophic over-sized sections. Two distinct bugs:
1. **`Chapter 25.32` not detected** because two-column extraction fragments full-width chapter headings ("Chapter" alone in one column, "25.32" in the other). Chapter-flush at `_walk_sections` never fires, so 60+ pages of `25.32 TABLE OF HISTORICAL LANDMARKS` table content kept appending to `25.30.130`. Fix: in `_extract_page_lines`, when a `CHAPTER_FRAGMENT_RE` match exists but no full `CHAPTER_HEADING_RE` line, recover the heading from `extract_text()` (which doesn't column-split) and inject at the top. Hotfix #18 added the fragment gate so the expensive `extract_text()` only runs on transition pages, not every body page.
2. **Ghost heading from citation list** — body text like `23.47.004 ChartA, 23.50.012 ChartA, ...` in the "ORDINANCES CODIFIED" appendix matched `SECTION_RE`, creating a phantom section. Fix: new `EMBEDDED_SECTION_RE` + `LEGITIMATE_SECTION_CITATION_RE` reject titles that contain a section-number-shaped substring without a preceding `Section(s) X.Y.Z` lead-in. Real titles like `Penalty for violation of Section 3.30.050.` keep the lead-in and pass through.

Post-merge re-parse (2026-04-24): `25.30.130` shrank 280k → 177 chars; pages 4445–4495 (the ghost zone) emit zero sections; full PDF parse went from 478 `ParseValidationIssue` rows → 115, declared-but-empty subchapters from 37 → 11. The two ghost rows (`23.47.004`, `23.54.015`) were left in the DB as orphans because the parser is update-or-create only — manually `DELETE`d. Promoted "add orphan-cleanup to parser" as a follow-up Up-next item.

### Frontend — bad-slug 404 → kind-aware NotFound — merged 2026-04-24 (PR #16)
`LegislationDetail` and `MeetingDetail` now check for HTTP 404 from the API and render `<NotFound />` instead of the "Could not load: HTTP 404" error text. `NotFound` gained a `kind` prop with three variants — `legislation` ("Legislation not found" → recent legislation), `meeting` ("Meeting not found" → upcoming meetings), and the default generic ("Page not found" → This Week). The wildcard `<Route path="*">` in `App.jsx` keeps using the generic variant.

### Parser — NEPA/SEPA acronym titles — fixed in PR #12
The "NEPA/SEPA short-title bypass" Open thread was already resolved in `a7c4cc0` via a precise `is_acronym_title` check at `parse_smc_pdf.py:588-592` (`0 < len(bare_title) <= 6 and isalpha() and isupper()`). Cleaner than expanding the generic short-title bypass from `<= 3` to `<= 4`, which would have admitted noise like `"Co2."` or `"12-1"`. Entry was stale on the work log — surfaced 2026-04-24 during quick-wins triage.

### Frontend — SPA NotFound route — merged 2026-04-24 (PR #15)
Added `frontend/src/components/NotFound.jsx` (+ CSS) and wired `<Route path="*" element={<NotFound />} />` in `App.jsx`. Unknown SPA paths now render a styled 404 page instead of just the Header over an empty body.

### Frontend — retire `django-webpack-loader` — merged 2026-04-24 (PR #14)
Removed `webpack_loader` from `INSTALLED_APPS` + `WEBPACK_LOADER` block; deleted `IndexView`, `home_page.html`, root `package.json`/`package-lock.json`, `webpack.config.js`, `webpack-stats.json`; dropped the `webpack` service + `seattle_node_modules` volume; removed `django-webpack-loader` from `requirements.txt`. `base.html` kept (stripped of webpack bits) for `404.html`/`500.html`.

### Frontend — Vite/React cutover (path A) — merged 2026-04-24 (PR #13)
Vite `base: '/static/'`; new `react_app` view serves `frontend/dist/index.html` for `/` and any unmatched path. `urls.py` restructured: kept `admin/`, APIs, `search/`, `cms/`, `documents/`; dropped wagtail's `""` catch-all so React owns the SPA routes.

### Parser — subchapter TOC + validation — merged 2026-04-24 (PR #12)
Subchapter schema, TOC scanner, body FK stamping, landmark `designation_type` backfill, subchapter divider bug fix. Full re-parse: 9,930 sections, 202 new, 5,562 text-updated, 227 subchapters (209 official, 18 synthesized).
