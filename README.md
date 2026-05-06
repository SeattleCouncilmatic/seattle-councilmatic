# Seattle Councilmatic

**Live site:** [www.seattlecouncilmatic.org](https://www.seattlecouncilmatic.org)

Seattle Councilmatic is a civic-engagement web app that makes Seattle City
Council activity legible to residents. It tracks legislation, meetings,
councilmembers' voting records, and the Seattle Municipal Code in one place,
with plain-language summaries on every bill and SMC section.

It's a fork/extension of the [Councilmatic](https://www.councilmatic.org/)
platform (DataMade) layered with a custom REST API, a React SPA, and a
Seattle-specific data pipeline (Legistar scrapers + an SMC parser + LLM
summary jobs).

## What's in the site

- **[Legislation](https://www.seattlecouncilmatic.org/legislation)** — every
  bill, resolution, and ordinance from Legistar with full text, sponsors,
  actions, and roll-call votes. Plain-language summaries for current bills.
- **[Meetings](https://www.seattlecouncilmatic.org/meetings)** — committee
  and council agendas, attached documents, locations, video links.
- **[Council members](https://www.seattlecouncilmatic.org/reps)** — each
  rep's district, committees, tenure, and a unified table of every bill
  they sponsored or voted on (sortable, filterable, paginated).
- **[Municipal Code](https://www.seattlecouncilmatic.org/municode)** — the
  full SMC parsed from the official PDF, with subchapter navigation, body
  text, plain-language section summaries, and cross-references between
  sections / RCW citations / linked legislation.
- **Search** across legislation, meetings, and SMC sections.

## Architecture in one paragraph

Daily cron scrapes Legistar (`pupa update seattle`) into Open Civic Data
tables (`opencivicdata_*`); a sync step copies into Councilmatic's
extended tables (`councilmatic_core_*`). The SMC PDF is parsed offline
into structured `MunicipalCodeSection` rows with regex + heuristics. LLM
summaries (Anthropic Claude) run in batched jobs over both legislation
text and SMC sections. Django serves a JSON REST API (`/api/...`) backed
by Postgres + PostGIS; a Vite-built React SPA owns every non-admin route
and consumes that API. Django admin (`/admin/`) and Wagtail CMS (`/cms/`)
remain server-rendered for editorial workflows.

For the deeper version see [ARCHITECTURE.md](ARCHITECTURE.md).
For the production runbook see [DEPLOY.md](DEPLOY.md).
For an accessibility-conventions reference see
[AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

## Local development

Prereqs: Docker + Docker Compose v2, an Anthropic API key (only required
if you want to regenerate summaries locally — the site renders fine
without it).

```bash
git clone https://github.com/SeattleCouncilmatic/seattle-councilmatic.git
cd seattle-councilmatic
cp .env.example .env          # fill in DJANGO_SECRET_KEY at minimum
docker compose up --build     # first build is ~2-3 min
```

Once containers are healthy:

- **Django + REST API:** <http://localhost:8000>
- **Vite SPA (with HMR):** <http://localhost:5173> — preferred for frontend
  iteration; routes proxy `/api/...` and `/admin/` back to Django.
- **Django admin:** <http://localhost:8000/admin/> — create a superuser
  with `docker compose exec app python manage.py createsuperuser`.

To populate the database with real data, run the daily scrape once:

```bash
docker compose exec scheduler sh /app/scripts/update_seattle.sh
```

This pulls the last ~18 months of Legistar data; first run is slow
(10-30 min), subsequent runs are incremental.

## Acknowledgments

Built on:

- [Councilmatic](https://www.councilmatic.org/) by DataMade — the core
  framework for tracking local legislation
- [django-councilmatic](https://github.com/datamade/django-councilmatic) — Django models for legislation, events, members
- [Open Civic Data](https://opencivicdata.org/) — schemas for civic data
- [Pupa](https://github.com/opencivicdata/pupa) — scraping framework
- [pdfplumber](https://github.com/jsvine/pdfplumber) — SMC PDF extraction
- [Anthropic Claude](https://www.anthropic.com/) — plain-language summaries
- [React](https://react.dev/) + [Vite](https://vitejs.dev/) — SPA frontend

Data sources:

- [Seattle City Council](https://www.seattle.gov/council)
- [Seattle Legistar](https://seattle.legistar.com/)
- [Seattle Municipal Code (PDF)](https://www.seattle.gov/cityclerk/codes/seattle-municipal-code) (linked from every SMC page)

## License

Released under the [MIT License](LICENSE).
