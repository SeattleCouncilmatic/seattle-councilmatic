# Work Log

Active workstreams for Seattle Councilmatic. One section per project.
Update the **State** and **Next** lines whenever you switch forks or
pause a thread, and commit this file — every branch then shares the
same picture of what's open.

---

## Frontend — retire `django-webpack-loader` (path A, follow-up)
- **Branch:** `frontend/retire-webpack-loader` (PR open, not yet merged)
- **State:** Cleanup complete on branch. Removed `webpack_loader` from `INSTALLED_APPS` and the `WEBPACK_LOADER` settings block; deleted `IndexView`, `home_page.html`, root `package.json`, root `package-lock.json`, `webpack.config.js`, `webpack-stats.json`; dropped the `webpack` service + `seattle_node_modules` volume from `docker-compose.yml`; removed `django-webpack-loader` from `requirements.txt`. **Kept `base.html` (stripped of webpack-loader bits)** because `404.html` and `500.html` still extend it via the `handler404`/`handler500` registrations — option-1 deviation from original work-log step that said "delete base.html". Container restarted clean; all routes still 200/302; `404.html` still renders via `base.html`.
- **Next:** awaiting PR review/merge.

## Frontend — SPA NotFound route
- **Branch:** `frontend/spa-notfound` (branched from `frontend/retire-webpack-loader`; rebase onto `main` once cleanup PR merges; PR open after push)
- **State:** Done on branch. Added `frontend/src/components/NotFound.jsx` + `.css` (matches site palette: `#2E3D5B` brand, `#1A1A1A` text) with big "404", message, and "← Back to This Week" button. Wired `<Route path="*" element={<NotFound />} />` into `App.jsx` after the existing `/`, `/legislation/:slug`, `/events/:slug` routes. Build clean (1724 modules, 402.66 kB JS, 34.09 kB CSS). Browser-verified.
- **Known follow-up (not in this PR):** `LegislationDetail` and `MeetingDetail` show `Could not load legislation: HTTP 404` when the slug doesn't exist in the API. Would be cleaner to route bad slugs to the same `NotFound` component. Defer to a future small PR.
- **Next:** push and open PR.

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`,
`frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching forks:** WIP commit (`wip: <short-state>`) and push
so nothing is orphaned in a detached working tree.

**When a workstream ships:** move its section to `## Done` at the
bottom of the file with the merge date, so open/closed stays skimmable.

---

## Done

### Frontend — Vite/React cutover (path A) — merged 2026-04-24 (PR #13)
- Vite `base: '/static/'`; built assets resolve through Django's static pipeline.
- New `react_app` view serves `frontend/dist/index.html` for `/` and any unmatched path.
- `urls.py` restructured: kept `admin/`, APIs, `search/`, `cms/`, `documents/`; dropped wagtail's `""` catch-all so React owns the SPA routes.
- Browser-verified: `/`, `/admin/`, `/cms/`, `/legislation/<slug>`, API routes all working.
- Legacy `IndexView`, `home_page.html`, `base.html`, `django-webpack-loader`, root `package.json`, `webpack.config.js`, `webpack-stats.json`, and the `webpack` docker service are still present but unrouted — retiring them is the next workstream above.

### Parser — subchapter TOC + validation — merged 2026-04-24 (PR #12)
- Subchapter schema, TOC scanner, body FK stamping, landmark `designation_type` backfill, subchapter divider bug fix.
- Full re-parse 2026-04-24: 9,930 sections, 202 new, 5,562 text-updated, 227 subchapters (209 official, 18 synthesized), 478 `ParseValidationIssue` rows logged as persistent parser-quality backlog.
- Known open quality threads (not blocking, captured for later): NEPA/SEPA short-title bypass needs `len(bare_title) <= 4` for 4-char acronyms; review 18 synthesized subchapters for scanner gaps; investigate `25.05.990` and similar 5-line malformed pdfplumber extractions; review 37 "declared-but-empty" subchapters.
