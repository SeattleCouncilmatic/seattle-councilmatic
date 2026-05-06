# Architecture

Seattle Councilmatic is a Django + Postgres + React/Vite app that pulls
legislative data from Legistar, parses the Seattle Municipal Code from
the city's PDF, layers on Anthropic-generated plain-language summaries,
and serves the result through a JSON REST API consumed by a single-page
React frontend.

This document is the engineering-level overview. For setup see
[README.md](README.md); for the production runbook see
[DEPLOY.md](DEPLOY.md); for a11y conventions see
[AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

## High-level layout

```text
                        ┌───────────────────────────┐
   Legistar API ───────▶│  pupa scrapers (seattle/) │──┐
   (people/bills/        └───────────────────────────┘  │  (1) extract
   events/votes)                                        ▼
                                            ┌──────────────────────┐
   SMC PDF ────────────▶ parse_smc_pdf ────▶│   PostgreSQL +       │
                          (pdfplumber)      │   PostGIS            │  (2) load
                                            │                      │
   Seattle.gov maps ───▶ ingest_zoning,     │ • opencivicdata_*    │
                         ingest_landmarks,  │ • councilmatic_core_*│
                         ingest_districts   │ • seattle_app_*      │
                                            │ • reps_*             │
                                            └──────────┬───────────┘
                                                       │  (3) summarize
                                                       ▼
                                            ┌──────────────────────┐
   Anthropic Claude ◀─── summarize_*  ◀────▶│  text/summary fields │
   (Batch + Sync)                           │  on bills + sections │
                                            └──────────┬───────────┘
                                                       │  (4) serve
                                                       ▼
                                            ┌──────────────────────┐
   Browser ◀── React SPA ◀── Django REST ───│  /api/legislation,   │
   (frontend/)              (api_views.py)  │  /api/events,        │
                                            │  /api/reps,          │
                                            │  /api/smc            │
                                            └──────────────────────┘
```

## Code layout

| Package | Role |
| --- | --- |
| `seattle/` | Pupa scrapers — `people.py`, `bills.py`, `events.py`, `vote_events.py`. Each emits OCD-shaped objects; pupa imports them. |
| `seattle_app/` | The main Django app: models, admin, REST API (`api_views.py`), services, management commands (parser, summarizers, ingest jobs). |
| `seattle_app/services/` | `claude_service.py` (Anthropic client wrapper), `prose_refs.py` (regex cite scanning), `ordinance_refs.py`, `municode_client.py`, `bill_text_extractor.py` (.docx attachment text). |
| `seattle_app/management/commands/` | All offline jobs — `parse_smc_pdf`, `summarize_legislation`, `summarize_smc_sections`, `ingest_zoning_polygons`, `ingest_historic_landmarks`, `extract_bill_text`, `sync_councilmatic`, etc. |
| `reps/` | Council-member-specific app: `services.py` produces the legislation-involvement table + voting-history block; URL routes under `/api/reps/`. |
| `frontend/` | Vite + React SPA. Component-per-feature in `src/components/`. CSS-modules-by-convention (filename-prefixed classes, no CSS-in-JS). |
| `scripts/` | `update_seattle.sh` (daily scrape entrypoint), `backup-db.sh` (pg_dump + rotation). |

## Data pipeline

### 1. Extract — pupa scrapers (`seattle/`)

Run via `pupa update seattle` inside the `app` container. Four scrapers,
all sharing a Legistar API client (`seattle/_http.py`):

- **`people.py`** — current councilmembers from Legistar. Tenure
  start/end dates are admin-managed (not scraped) per
  [WORK_LOG decision 2026-04](WORK_LOG.md) — pupa's MembershipImporter
  uses dates in its uniqueness key, so passing them creates duplicate
  Membership rows on every re-run.
- **`bills.py`** — every bill, resolution, and ordinance in a rolling
  548-day window. Title, sponsors, actions, attached documents, status.
- **`events.py`** — committee + council meetings in the same window.
  Agenda items, attached documents, location, video URL.
- **`vote_events.py`** — roll-call votes per agenda-item-with-MatterId.
  See [WORK_LOG](WORK_LOG.md#votes--implement-seattlevoteeventscraper-data-only-no-ui-yet--committed-2026-05-03)
  for the three pupa edge cases this scraper had to work around.

Pupa validates each yielded object against OCD schemas, persists to the
`opencivicdata_*` tables, and tracks runs in `pupa_*` tables.

### 2. Sync to Councilmatic models (`sync_councilmatic`)

django-councilmatic uses multi-table inheritance: every OCD entity has a
matching `councilmatic_core_*` row that adds slugs, headshots,
human-readable status, and other display-layer fields. The
`sync_councilmatic` management command bridges the gap (it INSERTs new
rows for any OCD object missing its councilmatic counterpart).

The daily scrape script (`scripts/update_seattle.sh`) runs this step
automatically after `pupa update`.

### 3. Parse the Seattle Municipal Code (`parse_smc_pdf`)

The SMC isn't available as structured data — we parse it from the
official PDF. `parse_smc_pdf` (~1k lines, the most complex command in
the project) walks each page with `pdfplumber`, builds a model of titles
→ chapters → subchapters → sections, captures full text (with markdown
tables for the ~86 sections that include them), and writes one
`MunicipalCodeSection` row per leaf section.

Post-parse, `clean_section_full_text` runs a Haiku-curated word-split
pass over body text — `pdfplumber` merges words on tight-kerning pages
(`TherequirementsofthisSection`), and a hybrid algorithmic + LLM-curated
verdict file (`seattle_app/data/split_decisions.json`) is the safest
way to split them back apart without breaking legal vocabulary
(`thereof`, `easement`, `grantee`).

Other ingest commands populate auxiliary spatial data:

- `ingest_zoning_polygons` — zoning categories from a Municode HTML
  scrape, stored as PostGIS multipolygons.
- `ingest_historic_landmarks` — landmark designations + boundaries.
- `ingest_historic_review_districts` — historic district overlays.

### 4. Summarize — Anthropic Claude (`summarize_*`)

Two summary pipelines, both via `seattle_app.services.claude_service`:

- **`summarize_legislation`** — short plain-language summaries on
  current bills. Uses the Anthropic Batch API (24h SLA, 50% cost
  reduction); state file `data/summarize_legislation_state.json`
  tracks in-flight batch IDs so the command is restartable.
- **`summarize_smc_sections`** — section-level summaries on every
  parsed SMC leaf. Same batch pattern. `bootstrap_section_summaries`
  curates a few-shot prompt that the bulk job consumes.

Sonnet is the default model for both; Haiku is reserved for narrower
tasks like the word-split verdicts (see `seed_split_decisions`).

### 5. Serve — REST API + React SPA

**Django** (`seattle_app/api_views.py` + `reps/services.py`) exposes a
JSON REST API:

| Route | Returns |
| --- | --- |
| `/api/legislation/` | Index + filters (search, status, classification, date range) |
| `/api/legislation/recent/` | Homepage hero — last N bills with summaries |
| `/api/legislation/<slug>/` | Bill detail — sponsors, actions, roll-call votes, attachments, summary |
| `/api/events/` | Index + filters |
| `/api/events/<slug>/` | Event detail — agenda, documents, participants |
| `/api/events/upcoming/` | Homepage "this week" widget |
| `/api/reps/` | Council member index |
| `/api/reps/<slug>/` | Rep detail — committees, tenure, legislation-involvement table |
| `/api/smc/tree/` | Title → chapter → subchapter nav tree |
| `/api/smc/sections/<number>/` | SMC section detail with cross-references |
| `/api/smc/` | SMC search |

The same Django process also serves `/admin/` (Django admin, for
editorial overrides on people/legislation) and `/cms/` (Wagtail, for
the About page and other CMS-managed content). Wagtail's catch-all is
intentionally _not_ included in `urls.py` so the React SPA can own
every other path.

**React SPA** (`frontend/`) is a Vite-built bundle. In dev,
`vite dev` runs on `:5173` with HMR and a middleware that proxies
`/api/...`, `/admin/`, and `/cms/` to Django on `:8000`. In prod, the
multi-stage `Dockerfile` runs `npm run build` and the Django
`react_app` view serves `frontend/dist/index.html` for any non-API,
non-admin route. SPA routing is React Router; data fetching is plain
`fetch()` (no SWR/Query layer).

## Database schema

### Open Civic Data (pupa-managed)

Pupa controls these tables; we never write to them directly outside of
the scrapers.

- `opencivicdata_jurisdiction`, `opencivicdata_division` — Seattle
- `opencivicdata_organization` — City Council + each committee
- `opencivicdata_post`, `opencivicdata_person`, `opencivicdata_membership`
- `opencivicdata_bill`, `opencivicdata_billaction`,
  `opencivicdata_billsponsorship`
- `opencivicdata_voteevent`, `opencivicdata_personvote`,
  `opencivicdata_votecount`
- `opencivicdata_event`, `opencivicdata_eventagendaitem`,
  `opencivicdata_eventdocument`

### Councilmatic extensions (django-councilmatic)

One-to-one extensions of the OCD entities, joined by FK:

- `councilmatic_core_person.person_id → opencivicdata_person.id` —
  adds `slug`, `headshot`, `councilmatic_biography`, `is_current`.
- `councilmatic_core_bill`, `councilmatic_core_event`,
  `councilmatic_core_organization` — per-entity slugs and display
  fields.

### Seattle-specific (`seattle_app/` and `reps/`)

Models added by this project:

- `MunicipalCodeSection` — leaf-section content. The flagship
  Seattle-specific table. Includes `full_text`, `summary`,
  `search_vector` (Postgres tsvector, GENERATED ALWAYS — see
  PR #163 for the manager workaround), zoning + landmark FK columns.
- `CodeTitle`, `CodeChapter`, `Subchapter`, `TitleAppendix` — SMC
  hierarchy.
- `ParseValidationIssue` — the parser self-reports anomalies (gaps
  in section numbering, orphaned subchapters) for triage.
- `ZoningPolygon`, `HistoricLandmark`, `HistoricReviewDistrict` —
  PostGIS-backed overlays.
- Wagtail page models for CMS-managed content.

## Configuration

Two environment files:

- **`.env.example`** — checked into the repo; documents every
  variable. Copy to `.env` for dev.
- **`.env`** — never committed; created from `.env.example` per
  environment.

The most important variables:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Generate with `python -c 'import secrets; print(secrets.token_urlsafe(64))'` |
| `DEBUG` | `True` in dev, `False` in prod |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host list |
| `DATABASE_URL` | `postgis://user:pw@postgres:5432/db` (note: `postgis://` not `postgresql://` — required for PostGIS schema) |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | Match `DATABASE_URL`; the postgres container creates these on first boot. |
| `ANTHROPIC_API_KEY` | Required for `summarize_*` commands; site renders fine without. |
| `CSRF_TRUSTED_ORIGINS` | Required behind HTTPS reverse proxy (Django 4+) |
| `ALLOW_CRAWL` | Robots.txt switch |

For the full prod set see [DEPLOY.md](DEPLOY.md).

## Daily operations

The `scheduler` container runs `scripts/update_seattle.sh` on a cron
schedule. The script chains:

1. `pupa update seattle` — extract + load via OCD
2. `python manage.py sync_councilmatic` — bridge to councilmatic_core
3. `python manage.py summarize_legislation` — kick off / poll batch summaries

In prod, the production runbook ([DEPLOY.md](DEPLOY.md)) covers the
backup cron (`scripts/backup-db.sh`), TLS renewal (Caddy auto), and
deploy flow (`git pull && docker compose up -d --build`).

## Active work and history

- **Current state and short-lived context** — branch state via
  `gh pr list`, active task tracking via `gh issue list`.
- **Conventions and meaty postmortems** — [WORK_LOG.md](WORK_LOG.md).
- **Accessibility conventions** — [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md)
  ("Conventions to keep applying").
