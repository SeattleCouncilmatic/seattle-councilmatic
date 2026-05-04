#!/bin/sh
set -e

if [ "$DJANGO_MANAGEPY_MIGRATE" = 'on' ]; then
    python manage.py migrate --noinput
    # `db.DatabaseCache` (prod CACHES backend) requires this table to
    # exist; FetchFromCache / UpdateCache middleware error 500 on every
    # request without it. `createcachetable` reads the cache config and
    # is idempotent (no-op if the table is already there), so it's safe
    # to run on every boot. Cheap insurance against a fresh prod DB or
    # a forgotten one-time setup step.
    python manage.py createcachetable
fi

exec "$@"
