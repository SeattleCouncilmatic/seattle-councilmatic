# Work Log

Active workstreams for Seattle Councilmatic. One section per project.
Update the **State** and **Next** lines whenever you switch forks or
pause a thread, and commit this file — every branch then shares the
same picture of what's open.

---

## Parser — subchapter TOC + validation
- **Branch:** `llm-summaries` (PR 1: subchapter schema; PR 2: TOC scanner + body FK stamping — both applied, not yet on `main`)
- **State:** Full re-parse ran 2026-04-24. 9,930 sections emitted, 202 new, 5,562 text-updated. 227 Subchapters (209 official, 18 synthesized). 478 `ParseValidationIssue` rows surfaced as persistent parser-quality to-do.
- **Open threads (branched to other forks):**
  - Triage NEPA/SEPA short-title bypass (`len(bare_title) <= 3` → needs 4 for 4-char acronyms)
  - Review the 18 synthesized subchapters — each is a chapter with a body divider but no TOC scrape; some may indicate scanner gaps
  - Investigate `25.05.990` and similar pages where pdfplumber returns 5-line malformed extractions
  - Review the 37 "declared-but-empty" subchapters flushed without body sections
- **Done:** landmark `designation_type` backfill; subchapter divider bug fix; subchapter data model.

## Frontend — Vite/React cutover (path A)
- **Branch:** not yet created. Suggested: `frontend/vite-cutover`
- **State:** Investigation only. Confirmed two separate frontends:
  - `:8000` — legacy Django templates + webpack bundles via `django-webpack-loader` (referenced in `seattle_app/settings.py:180-186` and `seattle_app/templates/base.html`)
  - `:5173` — Vite React SPA in `frontend/` (new, with React Router + Leaflet)
- **Decision locked:** Django admin at `/admin/` stays server-rendered. React owns `/` and everything else. No admin port needed.
- **Next:**
  1. Create `frontend/vite-cutover` branch
  2. `npm run build` in `frontend/` to confirm clean Vite build → `frontend/dist/`
  3. Add Django catch-all view serving `frontend/dist/index.html` AFTER all API + `/admin/` routes
  4. Wire `frontend/dist/assets/` into `STATICFILES_DIRS`
  5. Verify `:8000/` shows React app, `:8000/admin/` still works
  6. Retire `django-webpack-loader`, root `package.json`, `webpack.config.js`, `webpack-stats.json` (separate PR)

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`,
`frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching forks:** WIP commit (`wip: <short-state>`) and push
so nothing is orphaned in a detached working tree.

**When a workstream ships:** move its section to `## Done` at the
bottom of the file with the merge date, so open/closed stays skimmable.
