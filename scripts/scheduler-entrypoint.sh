#!/bin/sh
set -e

# Snapshot the container env so cron-launched processes inherit it.
# Cron sanitizes the environment; without this, scripts launched from
# cron see neither DATABASE_URL nor any of the other vars from .env,
# so Django falls back to localhost:5432 and the run dies immediately.
# Use Python for proper shell quoting (handles values with spaces, $, ", etc.).
python3 -c "
import os, shlex
with open('/etc/cron-env', 'w') as f:
    for k, v in os.environ.items():
        f.write(f'export {k}={shlex.quote(v)}\n')
"
chmod 600 /etc/cron-env

# Reinstall the crontab from the mounted source file so edits to
# scheduler-crontab take effect on container restart without an image
# rebuild. The Dockerfile installs it at build time too — this just
# refreshes it.
crontab /app/scheduler-crontab

cron
exec tail -f /var/log/cron/sync.log
