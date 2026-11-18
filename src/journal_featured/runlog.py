"""Run logs in data/logs/: one file per scheduled run.

`python -m journal_featured.runlog schedule [args...]` is what the crontab calls: it runs
journal-featured, copying the output both to stdout (docker logs) and to a log file.
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .config import ROOT

KEEP = 50
EXIT = re.compile(r"^\[exit (\d+)\]$", re.M)


def log_dir() -> Path:
    raw = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    return (ROOT / raw.get("db_path", "data/journal.db")).parent / "logs"


def new_log(args: list[str], label: str) -> Path:
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now():%Y%m%d-%H%M%S}-{label}.log"
    path.write_text(f"$ journal-featured {' '.join(args)}\n")
    for old in logs()[KEEP:]:
        old.unlink(missing_ok=True)
    return path


def logs() -> list[Path]:
    d = log_dir()
    return sorted(d.glob("*.log"), reverse=True) if d.exists() else []


def exit_code(text: str) -> int | None:
    m = EXIT.search(text)
    return int(m.group(1)) if m else None


def main(argv: list[str]) -> int:
    label, args = (argv[0] if argv else "schedule"), argv[1:]
    path = new_log(args, label)
    with path.open("a") as f:
        p = subprocess.Popen(["journal-featured", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors="replace", cwd=ROOT,
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            f.write(line)
            f.flush()
        code = p.wait()
        f.write(f"[exit {code}]\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
