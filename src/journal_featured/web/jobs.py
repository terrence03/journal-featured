"""Start CLI runs in the background; their output goes to data/logs/ (see runlog)."""

import os
import subprocess
import threading
from pathlib import Path

from journal_featured.config import ROOT
from journal_featured.runlog import exit_code, log_dir, logs, new_log  # noqa: F401  (re-exported)

LABELS = {
    "schedule": "排程執行", "dry": "試跑", "noemail": "執行，不寄信", "run": "正式執行並寄信",
    "curate": "重新精選，不寄信", "curate_mail": "重新精選並寄信", "resend": "重寄最近一次", "rescore": "重新計算分數",
}


def start(args: list[str], label: str) -> Path:
    path = new_log(args, label)
    with path.open("a") as f:
        # The shell appends the exit code so the UI can tell success from failure.
        p = subprocess.Popen(
            ["sh", "-c", 'journal-featured "$@"; echo "[exit $?]"', "sh", *args],
            stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    threading.Thread(target=p.wait, daemon=True).start()  # reap the child, no zombies
    return path


def describe(path: Path) -> str:
    """'11/03 08:00 · 排程執行' from '20261103-080000-schedule.log'."""
    stamp, _, label = path.stem.partition("-")
    time, _, label = label.partition("-")
    try:
        when = f"{stamp[4:6]}/{stamp[6:8]} {time[:2]}:{time[2:4]}"
    except IndexError:
        when = path.stem
    return f"{when} · {LABELS.get(label, label)}"
