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

### Post-deploy data population

**Ongoing automation:** the scheduler container runs the full pipeline
**every 6 hours** (00/06/12/18 Pacific), with an offset drain pass ~1h
after each cycle (01/07/13/19). New bills/events surface within ~6h of
posting and get tagged + summarized within ~1h of the batch completing;
the Batch commands are drain-then-submit, so each cycle polls + persists
the previous batch and submits a fresh one. Rep summaries refresh weekly
(Sunday 2:30 AM). All pipeline jobs share a `flock -n /tmp/seattle_pipeline.lock`
so runs can't overlap or race a batch state file. See
[scripts/update_seattle.sh](scripts/update_seattle.sh),
[scripts/poll_llm_batches.sh](scripts/poll_llm_batches.sh),
[scripts/update_reps.sh](scripts/update_reps.sh), and
[scheduler-crontab](scheduler-crontab) for the wiring.

**Email digests** (#235) compose + send weekly on Sunday 6 AM Pacific via
[scripts/compose_and_send_digests.sh](scripts/compose_and_send_digests.sh)
(own `flock`, not the pipeline lock — digests only read pipeline data).
Inert in prod until Phase 4: with signups closed there are no subscribers
to compose for, and `send_digest_batches` refuses the SMTP transport
outside `DEBUG`. Before the Phase 4 launch flip, set `DIGEST_SITE_BASE_URL`
(email links), `DIGEST_POSTAL_ADDRESS` (CAN-SPAM), and the Postmark
transport config.

**Manual runs** are still needed for first-time backfill on a new
environment, after a prompt or vocabulary change (run with `--force`
to regenerate), or when debugging. The table below documents each
command's intent for those cases:

| Command | When to run manually | Idempotent? |
| --- | --- | --- |
| `python manage.py scrape_rep_bios` | After membership changes (the weekly cron also runs this) | Yes — UPSERTs by `person_id` |
| `python manage.py backfill_council_terms` | When a member is sworn in, resigns, or is replaced. Not in the cron — the hardcoded term-date list is reviewed by hand | Yes — only writes when existing field is empty unless `--force` |
| `python manage.py extract_bill_text` | Initial backfill on a new env, or after a parser change | Yes — UPSERTs by `bill_id` |
| `python manage.py tag_bill_issue_areas` | Initial backfill, or with `--force` after a prompt / vocabulary change | Yes — UPSERTs by `bill_id`. Two-phase: submit, wait ~10-30 min, re-run to poll + persist |
| `python manage.py summarize_legislation` | Initial backfill, or with `--force` after a prompt change | Yes — UPSERTs by `bill_id`. Two-phase: submit, wait ~5-10 min, re-run to poll + persist |
| `python manage.py summarize_reps` | After any of `scrape_rep_bios`, `backfill_council_terms`, or `tag_bill_issue_areas` runs against changed data; or with `--force` after a prompt change | Yes — UPSERTs by `person_id`. Two-phase: submit, wait ~5-10 min, re-run to poll + persist |
| `python manage.py extract_event_transcripts` | Initial backfill, or to pick up SRTs Seattle Channel published since the last cron tick | Yes — UPSERTs by `event_id`. Polite-paced HTTP; no LLM cost |
| `python manage.py summarize_events` | Initial backfill, or with `--force` after a prompt change | Yes — UPSERTs by `event_id`. Two-phase: submit, wait ~5-10 min, re-run to poll + persist. ~$0.10/meeting |
| `python manage.py import_event_summaries` | One-off env-sync — import summaries from a JSON export produced on another env (saves the LLM cost of regenerating) | Yes — UPSERTs by `event_id`, matched via `legistar_event_id` |
| `python manage.py scrape_committee_info` | Initial backfill of committee scope + meeting schedule (the weekly cron also runs this) | Yes — UPSERTs by `organization_id`. Polite-paced HTTP; no LLM cost |
| `python manage.py summarize_committees` | After `scrape_committee_info` on a new env, or with `--force` after a prompt change | Yes — UPSERTs by `organization_id`. Re-summarizes only changed committees (content hash). Two-phase: submit, wait ~5-10 min, re-run to poll + persist |
| `python manage.py compose_digests --cadence weekly` | QA a digest run (`--dry-run` prints match counts; `--since YYYY-MM-DD` widens the news window against stale dev data) | Yes — one pending `DigestSend` per subscriber per cadence per day |
| `python manage.py send_digest_batches` | Deliver pending digests after a manual compose (`--allow-smtp` required outside `DEBUG` — SMTP is test-to-self only) | Yes — only `status=pending` rows send; re-runs are no-ops |

**For new LLM-data PRs:** add a one-line entry to this table AND a
corresponding step to [scripts/update_seattle.sh](scripts/update_seattle.sh)
or [scripts/poll_llm_batches.sh](scripts/poll_llm_batches.sh) so the
new pipeline is in the automation from day one.

> **Rebuild the image before regenerating when a summarizer's _code_ or
> _output format_ changes — not just its data.** Prod bakes both the Django
> code and the built Vite bundle into the image (no bind-mount; see the
> multi-stage `Dockerfile`). So a PR that changes a summarizer's prompt,
> schema, or model fields needs `git pull && docker compose -f
> docker-compose.prod.yml up -d --build` **first**, _then_ the `migrate` +
> `--force` regen. Running the regen against the old image silently
> produces old-format rows (and the old SPA keeps rendering), which looks
> like "the change didn't take" even though the batch ingested fine. This
> bit us on the committee scope-intro change (2026-06-08): the regen ran
> against the pre-change image and emitted bulleted summaries with no intro.

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
