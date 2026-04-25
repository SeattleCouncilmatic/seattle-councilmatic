# Work Log

Long-lived context for Seattle Councilmatic that git and GitHub can't tell you:
locked decisions, known follow-up threads, and a chronological merge log.
**Branch state lives in `gh pr list` — this file does not track it.**

---

## Decisions

- **Frontend ownership.** Django admin at `/admin/` and Wagtail admin at `/cms/` stay server-rendered. The Vite React SPA owns `/` and every unmatched path; Django's `react_app` view returns `frontend/dist/index.html` for those. `STATIC_URL` is `/static/` and Vite's `base` matches.
- **`base.html` retained.** Kept (with webpack-loader stripped) because `404.html` and `500.html` extend it via `handler404`/`handler500`. Don't delete unless you also rewrite the error templates.

## Open threads

Things to fix when you're in the area. Not scoped to any branch.

**Frontend**
- `LegislationDetail`/`MeetingDetail` show `Could not load legislation: HTTP 404` when the slug is invalid. Should route to the SPA `NotFound` component instead.

**Parser quality** (surfaced by 2026-04-24 re-parse — 478 `ParseValidationIssue` rows)
- NEPA/SEPA short-title bypass: `len(bare_title) <= 3` needs to be `<= 4` for 4-char acronyms.
- Review the 18 synthesized subchapters (chapter has body divider but no TOC scrape) — some may indicate scanner gaps.
- Investigate `25.05.990` and similar pages where pdfplumber returns 5-line malformed extractions.
- Review the 37 "declared-but-empty" subchapters flushed without body sections.

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`, `frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching branches:** WIP commit (`wip: <short-state>`) and push so nothing is orphaned in a detached working tree.

**Branch follow-ups from `main`, not from in-flight branches.** Stack only when the new work genuinely depends on the prior branch's code. Stacking on an unmerged branch costs a rebase later — root cause of the WORK_LOG conflict on `frontend/spa-notfound`.

**Include the Done-move in the same PR that ships the work.** Add the workstream's entry under `## Done` in the same commit. Avoids the "stale section after merge" tax we kept hitting.

**Pre-flight at session start:** `git fetch && git log main..origin/main` to catch divergence between local and remote `main` before doing anything else. We lost time to a 16-commit divergence in 2026-04 that this would have caught in one command.

---

## Done

### Frontend — SPA NotFound route — merged 2026-04-24 (PR #15)
Added `frontend/src/components/NotFound.jsx` (+ CSS) and wired `<Route path="*" element={<NotFound />} />` in `App.jsx`. Unknown SPA paths now render a styled 404 page instead of just the Header over an empty body.

### Frontend — retire `django-webpack-loader` — merged 2026-04-24 (PR #14)
Removed `webpack_loader` from `INSTALLED_APPS` + `WEBPACK_LOADER` block; deleted `IndexView`, `home_page.html`, root `package.json`/`package-lock.json`, `webpack.config.js`, `webpack-stats.json`; dropped the `webpack` service + `seattle_node_modules` volume; removed `django-webpack-loader` from `requirements.txt`. `base.html` kept (stripped of webpack bits) for `404.html`/`500.html`.

### Frontend — Vite/React cutover (path A) — merged 2026-04-24 (PR #13)
Vite `base: '/static/'`; new `react_app` view serves `frontend/dist/index.html` for `/` and any unmatched path. `urls.py` restructured: kept `admin/`, APIs, `search/`, `cms/`, `documents/`; dropped wagtail's `""` catch-all so React owns the SPA routes.

### Parser — subchapter TOC + validation — merged 2026-04-24 (PR #12)
Subchapter schema, TOC scanner, body FK stamping, landmark `designation_type` backfill, subchapter divider bug fix. Full re-parse: 9,930 sections, 202 new, 5,562 text-updated, 227 subchapters (209 official, 18 synthesized).
