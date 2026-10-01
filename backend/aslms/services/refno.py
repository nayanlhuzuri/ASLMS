"""Reference numbers: ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN> (DB_STANDARD §3, Appendix C).

One counter row per (office, record type, year). The INSERT … ON CONFLICT … RETURNING form locks that row
only, so concurrent allocations serialise there and never on the business table. Gaps are allowed (a rolled
back transaction consumes a number); duplicates are not."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

IST = ZoneInfo("Asia/Kolkata")
REF_NO_RE = re.compile(r"^ASLMS/([A-Z0-9_]{2,20})/([A-Z]{2,10})/(\d{4})/(\d{6})$")


def now_ist() -> datetime:
    return datetime.now(IST)


def allocate_ref_no(
    session: Session, office_code: str, record_type: str, when: datetime | None = None
) -> str:
    year = (when or now_ist()).year
    n = session.execute(
        text(
            """
            INSERT INTO ref_sequences (office_code, record_type, year, last_value) VALUES (:o, :t, :y, 1)
            ON CONFLICT (office_code, record_type, year)
            DO UPDATE SET last_value = ref_sequences.last_value + 1
            RETURNING last_value
            """
        ),
        {"o": office_code, "t": record_type, "y": year},
    ).scalar_one()
    return format_ref_no(office_code, record_type, year, n)


def format_ref_no(office_code: str, record_type: str, year: int, n: int) -> str:
    return f"ASLMS/{office_code}/{record_type}/{year}/{n:06d}"


def parse_ref_no(ref_no: str) -> tuple[str, str, int, int] | None:
    m = REF_NO_RE.match(ref_no.strip().upper())
    if not m:
        return None
    office, rtype, year, n = m.groups()
    return office, rtype, int(year), int(n)
