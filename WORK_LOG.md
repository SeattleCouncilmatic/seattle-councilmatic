# Work Log

Active workstreams for Seattle Councilmatic. One section per project.
Update the **State** and **Next** lines whenever you switch forks or
pause a thread, and commit this file — every branch then shares the
same picture of what's open.

---

## Frontend — Vite/React cutover (path A)
- **Branch:** `frontend/vite-cutover` (PR open, not yet merged)
- **State:** Cutover complete on branch. `:8000/` now serves the Vite React build via Django (`react_app` view returns `frontend/dist/index.html`); `/static/assets/...` resolves through `STATICFILES_DIRS`; wagtail's `""` catch-all removed so React owns `/` and unmatched paths. Browser-verified: `/`, `/admin/`, `/cms/`, `/legislation/<slug>`, API routes all working.
- **Decision locked:** Django admin at `/admin/` stays server-rendered. Wagtail admin stays at `/cms/`. React owns `/` and everything else.
- **Next (this branch):** push and open PR.
- **Next (follow-up branch `frontend/retire-webpack-loader`):**
  1. Remove `django-webpack-loader` from `INSTALLED_APPS` and the `WEBPACK_LOADER` settings block
  2. Delete `webpack-stats.json`, root `package.json`, root `package-lock.json`, `webpack.config.js`
  3. Delete `seattle_app/templates/base.html` (and `home_page.html` if unused) + the now-orphaned `IndexView` in `seattle_app/views.py`
  4. Drop the `webpack` service from `docker-compose.yml`
  5. Remove `django-webpack-loader` from `requirements.txt`

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

### Parser — subchapter TOC + validation — merged 2026-04-24 (PR #12)
- Subchapter schema, TOC scanner, body FK stamping, landmark `designation_type` backfill, subchapter divider bug fix.
- Full re-parse 2026-04-24: 9,930 sections, 202 new, 5,562 text-updated, 227 subchapters (209 official, 18 synthesized), 478 `ParseValidationIssue` rows logged as persistent parser-quality backlog.
- Known open quality threads (not blocking, captured for later): NEPA/SEPA short-title bypass needs `len(bare_title) <= 4` for 4-char acronyms; review 18 synthesized subchapters for scanner gaps; investigate `25.05.990` and similar 5-line malformed pdfplumber extractions; review 37 "declared-but-empty" subchapters.
