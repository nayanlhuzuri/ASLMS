"""The pure parts of the audit search (design `audit-screens`, "Tests", unit): the keyset cursor, the action prefix,
the LIKE escaping of the actor text and the IST day bounds."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from aslms.services.audit_search import (
    AuditInputError,
    action_pattern,
    day_bounds,
    decode_cursor,
    encode_cursor,
    like_escape,
)


def test_cursor_round_trip_and_bad_cursor():
    at = datetime(2026, 10, 8, 4, 30, 1, 123456, tzinfo=UTC)
    row_id = uuid.uuid4()
    cursor = encode_cursor(at, row_id)
    assert "|" not in cursor and "=" not in cursor  # opaque and URL-safe
    assert decode_cursor(cursor) == (at, row_id)
    for bad in ("not-a-cursor", "", "!!!!", encode_cursor(at, row_id)[:-6]):
        with pytest.raises(AuditInputError) as exc:
            decode_cursor(bad)
        assert exc.value.code == "bad_cursor"
    import base64

    naive = base64.urlsafe_b64encode(f"2026-10-08T04:30:01|{row_id}".encode()).decode()
    with pytest.raises(AuditInputError):
        decode_cursor(naive)


def test_action_prefix_vs_exact():
    assert action_pattern("custody.") == ("prefix", "custody.%")
    assert action_pattern("custody.sent") == ("exact", "custody.sent")
    assert action_pattern(" note. ") == ("prefix", "note.%")
    assert action_pattern("a_b.") == ("prefix", "a\\_b.%")
    assert like_escape("50%_off\\x") == "50\\%\\_off\\\\x"
    assert like_escape("plain") == "plain"


def test_ist_day_bounds():
    start, end = day_bounds(date(2026, 10, 8), date(2026, 10, 8))
    assert start == datetime(2026, 10, 7, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 8, 18, 30, tzinfo=UTC)
    start, end = day_bounds(date(2026, 10, 1), None)
    assert start == datetime(2026, 9, 30, 18, 30, tzinfo=UTC) and end is None
    assert day_bounds(None, None) == (None, None)
    with pytest.raises(AuditInputError) as exc:
        day_bounds(date(2026, 10, 9), date(2026, 10, 8))
    assert exc.value.code == "bad_period"
