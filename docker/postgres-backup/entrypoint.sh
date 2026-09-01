#!/bin/bash
set -uo pipefail

# run once on startup for immediate confirmation the setup works; the weekly
# cron schedule (see crontab) handles ongoing backups after this
echo "[entrypoint] $(date -Iseconds) running one-time startup backup"
/usr/local/bin/backup.sh || echo "[entrypoint] $(date -Iseconds) startup backup failed, weekly schedule will still run"

# -f: foreground, -d 8: log to stderr (docker logs) instead of syslog
exec crond -f -d 8
