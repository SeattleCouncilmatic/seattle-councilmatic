#!/bin/sh
# Daily local pg_dump for Seattle Councilmatic.
#
# Run from the host (NOT inside a container) — uses `docker compose
# exec` to dump from the running postgres container, then writes a
# rotated archive to ./backups/ on the host.
#
# Schedule via host crontab (see DEPLOY.md). Default rotation: 7 days.
# This is a "human-error" insurance policy (recovers from a fat-
# fingered manual SQL change or a bad migration). It's NOT offsite —
# if the Hetzner box dies, these dumps go with it. Pair with a
# remote rsync to a Hetzner Storage Box if you want off-host backup.
#
# Usage:
#   cd /opt/seattle_councilmatic
#   ./scripts/backup-db.sh
#
# Exit codes:
#   0 — backup written, old files rotated
#   1 — dump failed; nothing written
#   2 — compose project not running

set -e

# Resolve to the repo root regardless of how the script is invoked
# (cron typically runs with PWD=/, which would otherwise put backups
# in /backups).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

BACKUP_DIR="$REPO_DIR/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
TIMESTAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT_FILE="$BACKUP_DIR/seattle_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

# Check the compose project is up before trying to dump.
if ! docker compose -f "$COMPOSE_FILE" ps --status running | grep -q seattle_postgres; then
    echo "[backup-db] postgres container is not running; skipping" >&2
    exit 2
fi

# `pg_dump -Fc` = custom format (compressed, restorable with pg_restore).
# `-T` keeps stdout free of TTY allocation so the dump pipes cleanly.
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U postgres -Fc postgres > "$OUT_FILE"

# Sanity check — pg_dump occasionally returns 0 even when the file is
# empty (bad pg_dump version mismatch, etc.). 1KB minimum is generous;
# a real dump of this DB is several MB.
if [ ! -s "$OUT_FILE" ] || [ "$(wc -c < "$OUT_FILE")" -lt 1024 ]; then
    echo "[backup-db] dump file is empty or tiny; aborting" >&2
    rm -f "$OUT_FILE"
    exit 1
fi

# Rotate: drop dumps older than $RETENTION_DAYS.
find "$BACKUP_DIR" -name "seattle_*.dump" -type f -mtime +"$RETENTION_DAYS" -delete

echo "[backup-db] wrote $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
