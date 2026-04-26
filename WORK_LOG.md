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

**Parser quality** (post-fix re-parse 2026-04-24: 9,919 sections, 115 `ParseValidationIssue` rows — down from 478 pre-fix)
- **Recover real `23.54.015` and `23.47.004` (table-heavy Land Use Code sections).** The two "ghost" rows we deleted had bogus citation-list titles, but the section numbers themselves are real Land Use Code sections (`23.54.015` is a parking standards section per user). The post-PR-#17/#18 parser correctly avoids creating ghost rows but also fails to emit the real sections — their headings live amid tables that the column-aware extractor can't find. Investigate: where do the real `23.54.015` and `23.47.004` headings appear in the source PDF? Why does the column-split lose them? Likely needs table-aware extraction or a heading-recovery pass similar to the chapter-fragment fix in `_extract_page_lines`. Until fixed, the DB has no record of these sections at all.
- Triage the 10 remaining 30–50k-char sections (`25.05.675`, `15.91.045`, `23.47A.009`, `23.84A.036` with single-char `S` title, `25.05.800`, `22.602.045`, `23.58C.050`, `23.49.011`, `21.04.440`, `23.54.030`). None are catastrophic (the three >150k ghosts are now fixed and deleted). Most look legitimately substantive — but `15.91.045 Additional relief.` at 44k seems suspicious for a single "additional relief" section, and `23.84A.036 S` (single-char title) is worth confirming as the alphabetical-definitions edge case.
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
