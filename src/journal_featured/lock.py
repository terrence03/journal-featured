"""Cross-process run lock, so the cron job and runs started by hand never overlap.

flock works across containers too, as long as they share the same bind-mounted data directory.
"""

import fcntl
from contextlib import contextmanager
from pathlib import Path

NAME = "run.lock"


class Busy(Exception):
    pass


@contextmanager
def hold(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"已有另一個執行中的工作（{path}）") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def is_held(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with hold(path):
            return False
    except Busy:
        return True
