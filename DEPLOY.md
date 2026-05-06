# Deploying Seattle Councilmatic

Production runbook for `www.seattlecouncilmatic.org` on a Hetzner CPX21
(3 vCPU, 4 GB RAM, 80 GB disk). One-VPS setup: Caddy + Django (gunicorn)
+ PostGIS + the daily-scrape scheduler all run as containers from a
single `docker-compose.prod.yml`.

## Architecture

```
                 :80/:443 (TLS)
                       │
                  ┌────▼────┐
                  │  Caddy  │  Let's Encrypt; auto-renewing
                  └────┬────┘
                       │ HTTP :8000 (internal)
                  ┌────▼─────┐
                  │ gunicorn │  Django + DRF + Wagtail; 3 workers
                  └────┬─────┘
                       │
                  ┌────▼─────┐    ┌──────────────┐
                  │ postgres │    │  scheduler   │
                  │  PostGIS │    │ daily cron   │
                  └──────────┘    └──────────────┘
```

The Vite SPA is built into the `app` image at build time (multi-stage
Dockerfile, see [Dockerfile](Dockerfile)) and served by Django's
`react_app` view; there's no separate frontend container in prod.

## First-time setup

### 1. DNS

Point both records at the Hetzner box's public IP:

```
A     www.seattlecouncilmatic.org   → <ip>
A     seattlecouncilmatic.org       → <ip>
```

Wait for propagation (usually a few minutes; `dig +short
www.seattlecouncilmatic.org` from a third-party server confirms).

### 2. Server prep

Assumes Ubuntu/Debian with Docker + Compose installed (you said
SSH/firewall/Docker are already set up). Confirm:

```
docker --version          # 24+ recommended
docker compose version    # v2 plugin (NOT docker-compose v1 binary)
```

Open the firewall for HTTPS:

```
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp   # HTTP/3
```

### 3. Clone the repo and configure

```
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/SeattleCouncilmatic/seattle-councilmatic.git seattle_councilmatic
sudo chown -R $USER:$USER seattle_councilmatic
cd seattle_councilmatic
cp .env.example .env
```

Edit `.env` with production values. Required for prod:

```
DEBUG=False
DJANGO_SECRET_KEY=<generate with: python -c 'import secrets; print(secrets.token_urlsafe(64))'>
DJANGO_ALLOWED_HOSTS=www.seattlecouncilmatic.org,seattlecouncilmatic.org
CSRF_TRUSTED_ORIGINS=https://www.seattlecouncilmatic.org,https://seattlecouncilmatic.org

# Database — the postgres container creates the role + database with
# these values on first boot. All three MUST match what's embedded
# in DATABASE_URL. The compose defaults are non-`postgres`
# (`councilmatic_app` / `councilmatic`) so a misconfigured .env
# doesn't silently fall back to the well-known superuser. Override
# here only if you want different names; the password is required.
POSTGRES_USER=councilmatic_app
POSTGRES_DB=councilmatic
POSTGRES_PASSWORD=<strong-random-password>
DATABASE_URL=postgis://councilmatic_app:<same-password>@postgres:5432/councilmatic
POSTGRES_REQUIRE_SSL=False

# Anthropic — required for the LLM summary pipelines (bills + SMC
# sections). The site renders fine without it, but new bills won't
# get plain-language summaries until you set this.
ANTHROPIC_API_KEY=sk-ant-...

ALLOW_CRAWL=True
```

Sanity check:

```
grep -E '^(DEBUG|DJANGO_ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|POSTGRES_PASSWORD)=' .env
```

Should show real values, not the example placeholders. **Never commit
`.env`** — it's gitignored.

### 4. Build and start

```
docker compose -f docker-compose.prod.yml up -d --build
```

First boot does a lot:
* Multi-stage build runs `npm ci && npm run build` (~1-2 min on the CPX21).
* Postgres container creates the database, runs Django migrations
  via `docker-entrypoint.sh` (`DJANGO_MANAGEPY_MIGRATE=on`).
* Caddy fetches Let's Encrypt certs for both names. First fetch can
  take 30-60s; check progress with
  `docker compose -f docker-compose.prod.yml logs -f caddy`.

Verify each service is up:

```
docker compose -f docker-compose.prod.yml ps
```

All four should be `running` (healthy where applicable). Hit the site
in a browser at `https://www.seattlecouncilmatic.org`.

### 5. Initial data load

The scheduler container runs the daily Legistar scrape on cron — but
it doesn't backfill on first boot. Run the scrape manually once to
populate bills, events, reps, and votes:

```
docker compose -f docker-compose.prod.yml exec scheduler \
    sh /app/scripts/update_seattle.sh
```

This is a long-running command (10-30 min on first run depending on
window size). Subsequent runs are incremental and fast.

The Seattle Municipal Code parse + LLM summary pipelines have
separate management commands documented in WORK_LOG.md (search
"summarize_smc_sections" and "extract_bill_text" / "summarize_legislation").

### 6. Daily backup

Add to root's crontab (`sudo crontab -e`):

```
0 4 * * * /opt/seattle_councilmatic/scripts/backup-db.sh >> /var/log/seattle-backup.log 2>&1
```

That dumps to `/opt/seattle_councilmatic/backups/` daily at 4 AM
local with 7-day rotation. Override `BACKUP_RETENTION_DAYS` in the
crontab line to change retention.

**Caveat:** local-only. If the host disk fails, backups go too.
Pair with rsync to a Hetzner Storage Box or S3 if you want offsite
recovery; that's a follow-up not in this runbook.

## Day-2 ops

### Deploy a new release

```
cd /opt/seattle_councilmatic
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Migrations run automatically via the entrypoint
(`DJANGO_MANAGEPY_MIGRATE=on`). Frontend rebuilds because `Dockerfile`
COPYs source into the image. Caddy is untouched unless `Caddyfile`
changed.

Zero-downtime is NOT a goal of this setup — gunicorn restarts mean
~2-5s of 502s during deploys. Acceptable for this site's traffic.

### View logs

```
docker compose -f docker-compose.prod.yml logs -f                   # everything
docker compose -f docker-compose.prod.yml logs -f app               # Django + gunicorn
docker compose -f docker-compose.prod.yml logs -f caddy             # access logs + TLS issues
docker compose -f docker-compose.prod.yml logs -f scheduler         # nightly scrape output
```

### Restart a single service

```
docker compose -f docker-compose.prod.yml restart app
```

### Run a one-off management command

```
docker compose -f docker-compose.prod.yml exec app \
    python manage.py <command>
```

E.g. `python manage.py createsuperuser` for `/admin/` access.

### Manual scrape

```
docker compose -f docker-compose.prod.yml exec scheduler \
    sh /app/scripts/update_seattle.sh
```

Use this when something looks stale and you don't want to wait for
the next cron tick.

### Restore from backup

The DB role and database name are read from `.env`
(`POSTGRES_USER` / `POSTGRES_DB`); the commands below pull them out so
this works whatever names you set. Don't hard-code `postgres` here —
the prod defaults are `councilmatic_app` / `councilmatic`, and a
runbook that targets `postgres`/`postgres` would silently no-op against
those.

```bash
cd /opt/seattle_councilmatic
set -a && . ./.env && set +a   # exports POSTGRES_USER, POSTGRES_DB, etc.
LATEST=$(ls -t backups/seattle_*.dump | head -1)

# Stop the app + scheduler so nothing writes mid-restore.
docker compose -f docker-compose.prod.yml stop app scheduler

# Drop and recreate the DB (wipes current data — only do this if
# you've already lost it). Runs as the postgres superuser, which the
# image creates implicitly even when POSTGRES_USER is non-default.
docker compose -f docker-compose.prod.yml exec postgres \
    dropdb -U postgres "$POSTGRES_DB"
docker compose -f docker-compose.prod.yml exec postgres \
    createdb -U postgres -O "$POSTGRES_USER" "$POSTGRES_DB"

# Pipe the dump in. -j 2 parallelizes the restore (CPX21 has 3 vCPU).
docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" -j 2 < "$LATEST"

# Re-run migrations in case the dump is older than the schema, then
# bring services back up.
docker compose -f docker-compose.prod.yml start app scheduler
docker compose -f docker-compose.prod.yml exec app \
    python manage.py migrate
```

### Rotate `DJANGO_SECRET_KEY`

Editing `.env` and restarting `app` is enough; no migration needed.
Existing sessions invalidate (users log out), which is the expected
side effect of a key rotation.

### Rotate `POSTGRES_PASSWORD`

Coupling: change BOTH `POSTGRES_PASSWORD` AND the password inside
`DATABASE_URL` in `.env` simultaneously, then:

```
docker compose -f docker-compose.prod.yml exec postgres \
    psql -U postgres -c "ALTER USER postgres WITH PASSWORD '<new>';"
docker compose -f docker-compose.prod.yml restart app scheduler
```

### Renew TLS

Automatic. Caddy renews ~30 days before expiry. Only intervene if
you see ACME errors in `caddy` logs.

## Failure modes seen so far

(Empty — populate as we hit them in production.)
