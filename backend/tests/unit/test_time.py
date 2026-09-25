from __future__ import annotations

from datetime import date

from aslms.core.time import parse_date


def test_parse_date_accepts_court_formats() -> None:
    assert parse_date("2026-09-25") == date(2026, 9, 25)
    assert parse_date("25-09-2026") == date(2026, 9, 25)
    assert parse_date("25/09/2026") == date(2026, 9, 25)
    assert parse_date("25.09.2026") == date(2026, 9, 25)
    assert parse_date("2026-09-25 10:30:00") == date(2026, 9, 25)


def test_parse_date_rejects_blanks_and_junk() -> None:
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("0000-00-00") is None
    assert parse_date("not a date") is None
