# Architecture Documentation

## System Overview

Seattle Councilmatic is a Django-based civic engagement platform that scrapes, transforms, and presents Seattle City Council legislative data.

## Data Pipeline

### Stage 1: Extraction (Pupa Scrapers)

**Location:** `seattle/` directory

Scrapers pull data from source websites and transform it into Open Civic Data format.

#### People Scraper (`people.py`)

**Source:** <https://www.seattle.gov/council/members>

**Process:**

1. Fetches council member list from official website
2. Extracts: name, district, contact info
3. Creates `Person` objects with `Membership` to Seattle City Council organization
4. Yields to Pupa for validation and storage

**Key Classes:**

- `SeattlePersonScraper(Scraper)`

**Output:** `opencivicdata_person`, `opencivicdata_membership` tables

#### Events Scraper (`events.py`) - TODO

**Source:** <https://seattle.legistar.com>

**Will extract:** Meeting dates, agendas, participants, locations

#### Bills Scraper (`bills.py`) - TODO

**Source:** <https://seattle.legistar.com>

**Will extract:** Legislation, sponsors, actions, votes

### Stage 2: Transform & Load (Pupa)

**Command:** `pupa update seattle`

**Process:**

1. Scraper yields objects (Person, Event, Bill, etc.)
2. Pupa validates against OCD schemas
3. Writes to PostgreSQL in OCD format
4. Tracks imports in `pupa_*` tables

**Tables Created:**

- `opencivicdata_person`
- `opencivicdata_organization`
- `opencivicdata_membership`
- `opencivicdata_post`
- `pupa_import`, `pupa_runplan` (tracking)

### Stage 3: Sync (Custom Management Command)

**Command:** `python manage.py sync_councilmatic`

**Why Needed:**

Django-councilmatic 5.x uses multi-table inheritance. Councilmatic models extend OCD models but live in separate tables with additional fields.

**Process:**

```sql
-- Simplified version of what happens
INSERT INTO councilmatic_core_person (person_id, slug, headshot, councilmatic_biography)
SELECT 
    id as person_id,
    generate_slug(name) as slug,
    '' as headshot,
    NULL as councilmatic_biography
FROM opencivicdata_person
WHERE id NOT IN (SELECT person_id FROM councilmatic_core_person)
```

**Tables Created:**

- `councilmatic_core_person` (links to `opencivicdata_person`)
- Eventually: `councilmatic_core_bill`, `councilmatic_core_event`, etc.

### Stage 4: Presentation (Django Views)

**Location:** `seattle_app/` and `councilmatic_core/`

Django views query Councilmatic models and render templates.

**Key Views:**

- Homepage: Recent bills, upcoming meetings
- Person detail: Council member profile, sponsored bills
- Bill detail: Full text, actions, votes

---

## Database Schema

### Open Civic Data Models

**Core:**

- `opencivicdata_jurisdiction` - Represents Seattle
- `opencivicdata_division` - Geographic divisions
- `opencivicdata_organization` - Seattle City Council, committees
- `opencivicdata_post` - Council positions (Position 1-9, Districts 1-7)
- `opencivicdata_person` - Council members
- `opencivicdata_membership` - Person → Organization relationships

**Legislative:**

- `opencivicdata_bill` - Legislation
- `opencivicdata_billaction` - Legislative actions (introduced, passed, etc.)
- `opencivicdata_billsponsorship` - Who sponsored bills
- `opencivicdata_vote` - Voting records
- `opencivicdata_personvote` - Individual votes

**Events:**

- `opencivicdata_event` - Meetings
- `opencivicdata_eventagendaitem` - Agenda items
- `opencivicdata_eventparticipant` - Who attended

### Councilmatic Models

**Extended Models:**

- `councilmatic_core_person` - Adds: slug, headshot, biography
- `councilmatic_core_bill` - Adds: custom classifications, web-specific metadata
- `councilmatic_core_event` - Adds: event-specific display logic

**Relationship:**

```plaintext
councilmatic_core_person.person_id → opencivicdata_person.id (FK)
```

### Pupa Tracking Tables

- `pupa_import` - Import run metadata
- `pupa_runplan` - Scraper execution plans

---

## Configuration

### Key Settings (`seattle_app/settings.py`)

```python
# Jurisdiction name - MUST match seattle/__init__.py
OCD_CITY_COUNCIL_NAME = 'Seattle City Council'

# Committee titles for display
COMMITTEE_CHAIR_TITLE = 'Chair'
COMMITTEE_MEMBER_TITLE = 'Member'

# Site metadata
SITE_META = {
    'site_name': 'Seattle Councilmatic',
    'site_desc': 'City Council legislation tracker',
    'site_author': 'Your Name',
}

# Legislative sessions (if using)
LEGISLATIVE_SESSIONS = [
    {'identifier': '2024', 'name': '2024'},
]
```

### Environment Variables (`.env`)

```bash
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=True

# Database
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres

# Optional
DJANGO_MANAGEPY_MIGRATE=on
```

---

## Development Patterns

### Adding a New City (Future)

When adapting this for another city:

1. **Copy scraper template:**

```bash
   cp -r seattle/ portland/
```

2. **Update jurisdiction:**

```python
   # portland/__init__.py
   class Portland(Jurisdiction):
       division_id = "ocd-division/country:us/state:or/place:portland"
       name = "Portland City Council"
       url = "https://www.portland.gov/council"
```

3. **Modify scrapers** for Portland's data sources

4. **Add to INSTALLED_APPS:**

```python
   INSTALLED_APPS = [
       # ...
       'portland',  # New scraper app
   ]
```

5. **Update settings:**

```python
   OCD_CITY_COUNCIL_NAME = 'Portland City Council'
```

6. **Run pipeline:**

```bash
   pupa update portland
   python manage.py sync_councilmatic
```

### Testing Scrapers

**Unit test pattern:**

```python
# tests/test_people_scraper.py
from seattle.people import SeattlePersonScraper

def test_people_scraper():
    scraper = SeattlePersonScraper()
    results = list(scraper.scrape())
    
    assert len(results) == 9  # Seattle has 9 council members
    assert all(hasattr(p, 'name') for p in results)
    assert all(p.memberships for p in results)
```

**Integration test:**

```bash
# Scrape without import
pupa update seattle people --scrape

# Check output
ls -la _data/person_*.json

# Validate JSON
cat _data/person_*.json | jq .
```

---

## Deployment Considerations

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Use strong `SECRET_KEY`
- [ ] Configure real database (not SQLite)
- [ ] Configure static file serving (WhiteNoise or CDN)
- [ ] Set up SSL/TLS
- [ ] Configure logging
- [ ] Set up monitoring
- [ ] Schedule scraper runs (cron or Celery)
- [ ] Set up backups

### Scraper Scheduling

**Recommended schedule:**

```cron
# Run people scraper daily at 2 AM
0 2 * * * /path/to/update_seattle.sh people

# Run events/bills scrapers every 6 hours
0 */6 * * * /path/to/update_seattle.sh events
0 */6 * * * /path/to/update_seattle.sh bills
```

### Performance Optimization

**Database:**

- Add indexes on frequently queried fields
- Use `select_related()` and `prefetch_related()` in queries
- Consider database connection pooling

**Caching:**

- Redis for session/cache backend
- Cache expensive queries
- Use template fragment caching

---

## Troubleshooting Guide

### Common Issues

**Issue:** Data in admin but not on website

**Cause:** Councilmatic models not synced

**Fix:**

```bash
python manage.py sync_councilmatic
```

---

**Issue:** Scraper fails with "no such table: pupa_runplan"

**Cause:** Pupa database not initialized

**Fix:**

```bash
pupa dbinit us
```

---

## Future Enhancements

### Short Term

- [ ] Complete events scraper
- [ ] Complete bills scraper
- [ ] Add committee data
- [ ] Improve error handling in scrapers

### Medium Term

- [ ] Historical data import
- [ ] Email alerts for new legislation
- [ ] RSS feeds
- [ ] API endpoints

### Long Term

- [ ] Multi-city support
- [ ] Automated scraper generation (AI-assisted)
- [ ] Mobile app
- [ ] Integration with other civic data sources
