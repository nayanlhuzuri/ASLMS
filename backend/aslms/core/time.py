"""Time helpers. The database stores timestamptz (UTC); the portal presents Indian Standard Time."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def parse_date(value: str | None) -> date | None:
    """Parses the date formats NAPIX and cause lists use; returns None for blanks or junk."""
    if not value:
        return None
    s = str(value).strip()
    if not s or s in {"0000-00-00", "00-00-0000"}:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    return None
