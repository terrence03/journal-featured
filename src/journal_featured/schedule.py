"""Print the crontab line for supercronic from config.yaml's `schedule`.

docker/entrypoint.sh calls this at start and every 30 s; when the output changes it reloads
supercronic, so a schedule edited in the web UI takes effect without restarting the container.
"""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .config import ROOT

DEFAULT = "0 8 * * 1"  # Monday 08:00
CRON = re.compile(r"^[\w*,/-]+( [\w*,/-]+){4}$")
# runlog tees the output into data/logs/ (shown on the web UI) as well as to docker logs.
COMMAND = "cd /app && python -m journal_featured.runlog schedule"
WEEKDAYS = "日一二三四五六"
_NAMES = {**{d: i for i, d in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))},
          **{m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                         "oct", "nov", "dec"), 1)}}


def schedule(config_path: Path | None = None) -> str:
    raw = yaml.safe_load((config_path or ROOT / "config.yaml").read_text()) or {}
    expr = " ".join(str(raw.get("schedule") or DEFAULT).split())
    if not CRON.match(expr):
        raise ValueError(f"schedule 格式錯誤（需為 5 欄 cron，如 \"{DEFAULT}\"）：{expr}")
    return expr


def _field(spec: str, lo: int, hi: int) -> set[int]:
    """Values matched by one cron field: *, a, a-b, with optional /step, comma-separated."""
    out = set()
    for part in spec.lower().split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        else:
            a_s, _, b_s = rng.partition("-")
            a = _NAMES.get(a_s, None) if not a_s.isdigit() else int(a_s)
            b = (_NAMES.get(b_s) if not b_s.isdigit() else int(b_s)) if b_s else (hi if step else a)
            if a is None or b is None:
                raise ValueError(f"無法解析 cron 欄位：{spec}")
        out.update(range(a, b + 1, int(step) if step else 1))
    return out


def next_run(expr: str, now: datetime) -> datetime | None:
    """First time after `now` matching the 5-field cron expression (standard day-of-month/week OR rule)."""
    minute, hour, dom, month, dow = expr.split()
    minutes, hours = sorted(_field(minute, 0, 59)), sorted(_field(hour, 0, 23))
    doms, months = _field(dom, 1, 31), _field(month, 1, 12)
    dows = {d % 7 for d in _field(dow, 0, 7)}
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for i in range(366 * 5):
        day = start.date() + timedelta(days=i)
        if day.month not in months:
            continue
        in_dom, in_dow = day.day in doms, (day.weekday() + 1) % 7 in dows
        if dom != "*" and dow != "*":
            if not (in_dom or in_dow):
                continue
        elif not (in_dom and in_dow):
            continue
        for h in hours:
            for m in minutes:
                t = datetime.combine(day, datetime.min.time(), now.tzinfo).replace(hour=h, minute=m)
                if t >= start:
                    return t
    return None


def describe(expr: str) -> str:
    """Plain-language reading of the common forms; falls back to the raw expression."""
    parts = str(expr).split()
    if len(parts) != 5 or not (parts[0].isdigit() and parts[1].isdigit()) or parts[2:4] != ["*", "*"]:
        return expr
    time = f"{int(parts[1]):02d}:{int(parts[0]):02d}"
    if parts[4] == "*":
        return f"每天 {time}"
    days = parts[4].split(",")
    if all(d.isdigit() and int(d) <= 7 for d in days):
        return f"每週{'、'.join(WEEKDAYS[int(d) % 7] for d in days)} {time}"
    return expr


def main() -> int:
    try:
        print(f"{schedule()} {COMMAND}")
    except Exception as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
