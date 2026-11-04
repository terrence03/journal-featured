from datetime import datetime

import pytest

from journal_featured.schedule import describe, next_run

MON_0700 = datetime(2026, 11, 2, 7, 0)  # a Monday


@pytest.mark.parametrize("expr, expected", [
    ("0 8 * * 1", datetime(2026, 11, 2, 8, 0)),       # later the same day
    ("0 7 * * 1", datetime(2026, 11, 9, 7, 0)),       # exactly now -> next week
    ("30 7 * * 1,4", datetime(2026, 11, 2, 7, 30)),
    ("0 6 * * 4", datetime(2026, 11, 5, 6, 0)),
    ("0 9 * * 0", datetime(2026, 11, 8, 9, 0)),        # Sunday as 0
    ("0 9 * * 7", datetime(2026, 11, 8, 9, 0)),        # Sunday as 7
    ("0 9 * * mon-wed", datetime(2026, 11, 2, 9, 0)),
    ("*/15 * * * *", datetime(2026, 11, 2, 7, 15)),
    ("0 8 1 * *", datetime(2026, 12, 1, 8, 0)),
    ("0 8 15 * 5", datetime(2026, 11, 6, 8, 0)),       # day-of-month OR day-of-week
    ("0 0 29 2 *", datetime(2028, 2, 29, 0, 0)),
])
def test_next_run(expr, expected):
    assert next_run(expr, MON_0700) == expected


def test_describe():
    assert describe("0 8 * * 1") == "每週一 08:00"
    assert describe("30 7 * * 1,4") == "每週一、四 07:30"
    assert describe("5 6 * * *") == "每天 06:05"
    assert describe("0 8 1 * *") == "0 8 1 * *"
