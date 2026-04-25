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

**LLM summaries — wire up the existing infrastructure**
- Models, service module, and prompts already exist (`seattle_app/models.py:47,84` for `MunicipalCodeSection.plain_summary` + `LegislationSummary`; `seattle_app/services/claude_service.py` for `summarize_section`/`summarize_legislation` with full prompts). Nothing runs them and nothing surfaces them to users yet.
- Three pieces to ship the feature end-to-end:
  1. **Management command** to batch-summarize sections and bills (e.g., `summarize_smc_sections`, `summarize_legislation`) — handle prompt caching, rate limits, resumability, and skip already-summarized rows.
  2. **API**: extend `/api/legislation/<slug>/` to include `llm_summary` (summary, impact_analysis, key_changes); add `/api/smc/<section>/` (or similar) for section summaries.
  3. **Frontend**: render summary in `LegislationDetail` (probably above the action history). Decide whether to surface SMC section summaries — depends on whether there's a user-facing SMC browser yet.
- Open design questions: which Claude model? per-section caching strategy? batch via Anthropic Batch API to halve cost?

**Parser quality** (from 2026-04-24 re-parse — 478 `ParseValidationIssue` rows)
- Investigate `25.05.990` and similar pages where pdfplumber returns 5-line malformed extractions.
- Review the 18 synthesized subchapters (chapter has body divider but no TOC scrape) — some may indicate scanner gaps.
- Review the 37 "declared-but-empty" subchapters flushed without body sections.

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
