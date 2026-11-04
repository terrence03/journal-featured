"""Start CLI runs in the background and keep their output in data/logs/."""

import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from journal_featured.config import ROOT
from journal_featured.web.common import data_dir

KEEP = 50
EXIT = re.compile(r"^\[exit (\d+)\]$", re.M)


def log_dir() -> Path:
    return data_dir() / "logs"


def start(args: list[str], label: str) -> Path:
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now():%Y%m%d-%H%M%S}-{label}.log"
    with path.open("w") as f:
        f.write(f"$ journal-featured {' '.join(args)}\n")
        f.flush()
        # The shell appends the exit code so the UI can tell success from failure.
        p = subprocess.Popen(
            ["sh", "-c", 'journal-featured "$@"; echo "[exit $?]"', "sh", *args],
            stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    threading.Thread(target=p.wait, daemon=True).start()  # reap the child, no zombies
    for old in logs()[KEEP:]:
        old.unlink(missing_ok=True)
    return path


def logs() -> list[Path]:
    d = log_dir()
    return sorted(d.glob("*.log"), reverse=True) if d.exists() else []


def exit_code(text: str) -> int | None:
    m = EXIT.search(text)
    return int(m.group(1)) if m else None
