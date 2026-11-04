#!/bin/sh
# No arguments: run on CRON_SCHEDULE. With arguments: run them once
# (e.g. `docker compose run --rm app journal-featured --dry-run`).
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

: "${CRON_SCHEDULE:=0 8 * * 1}"
echo "$CRON_SCHEDULE cd /app && journal-featured" > /tmp/crontab
echo "排程：$CRON_SCHEDULE（TZ=${TZ:-UTC}）"
exec /usr/local/bin/supercronic -passthrough-logs /tmp/crontab
