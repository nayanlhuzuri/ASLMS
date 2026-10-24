"""IST dates from one place (design `court-data-freshness`, decision 23). The containers run on UTC and the
application's datetimes stay UTC-aware; a job between 00:00 and 05:30 IST must still get the IST date, so every
"today" in `backend/aslms` comes from `today_ist()`, never from `date.today` (a unit test enforces it)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_ist(now: datetime | None = None) -> date:
    """The IST calendar date of `now` (default: the current time). A naive `now` is read as UTC."""
    now = now or now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(IST).date()


def ist_midnight(d: date) -> datetime:
    """00:00 IST of `d` as a UTC-aware datetime (18:30 UTC of the day before)."""
    return datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)
