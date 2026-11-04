#!/bin/sh
# No arguments: run on the schedule in config.yaml. With arguments: run them once
# (e.g. `docker compose run --rm app journal-featured --dry-run`).
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

CRONTAB=/tmp/crontab
python -m journal_featured.schedule > "$CRONTAB"
echo "排程：$(cut -d' ' -f1-5 "$CRONTAB")（TZ=${TZ:-UTC}）"

# Watch config.yaml: when the schedule changes (e.g. edited in the web UI), rewrite the
# crontab and send SIGUSR2 so supercronic (PID 1 after exec) reloads it. An invalid
# schedule is reported and the previous one stays in effect.
(
    while sleep 30; do
        if python -m journal_featured.schedule > "$CRONTAB.new" 2> "$CRONTAB.err"; then
            if ! cmp -s "$CRONTAB.new" "$CRONTAB"; then
                mv "$CRONTAB.new" "$CRONTAB"
                echo "排程已更新：$(cut -d' ' -f1-5 "$CRONTAB")"
                kill -USR2 1
            fi
        elif ! cmp -s "$CRONTAB.err" "$CRONTAB.lasterr"; then
            echo "排程未更新：$(cat "$CRONTAB.err")"
            cp "$CRONTAB.err" "$CRONTAB.lasterr"
        fi
    done
) &

exec /usr/local/bin/supercronic -passthrough-logs "$CRONTAB"
