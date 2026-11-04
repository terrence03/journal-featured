"""Print the crontab line for supercronic from config.yaml's `schedule`.

docker/entrypoint.sh calls this at start and every 30 s; when the output changes it reloads
supercronic, so a schedule edited in the web UI takes effect without restarting the container.
"""

import re
import sys
from pathlib import Path

import yaml

from .config import ROOT

DEFAULT = "0 8 * * 1"  # Monday 08:00
CRON = re.compile(r"^[\w*,/-]+( [\w*,/-]+){4}$")
COMMAND = "cd /app && journal-featured"


def schedule(config_path: Path | None = None) -> str:
    raw = yaml.safe_load((config_path or ROOT / "config.yaml").read_text()) or {}
    expr = " ".join(str(raw.get("schedule") or DEFAULT).split())
    if not CRON.match(expr):
        raise ValueError(f"schedule 格式錯誤（需為 5 欄 cron，如 \"{DEFAULT}\"）：{expr}")
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
