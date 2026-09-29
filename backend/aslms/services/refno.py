"""Reference numbers (DB_STANDARD §3, Appendix C): `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>`.

`OFFICE` is the code of the allocating office, or `GOA` when the system creates the record before any
department owns it. One counter per (office, type, year) in `ref_sequences`; the `INSERT … ON CONFLICT …
RETURNING` locks that one row, so concurrent allocations serialise there and never on the business table.
Gaps are allowed (a rolled-back transaction consumes a number); duplicates are not. A number is allocated
once at insert and never changed on claim, transfer or merge."""

from __future__ import annotations

import enum
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms.core.time import now_ist

SYSTEM_OFFICE = "GOA"
REF_NO_RE = re.compile(
    r"^ASLMS/(?P<office>[A-Z0-9-]{1,20})/(?P<type>[A-Z]{2,10})/(?P<year>\d{4})/(?P<n>\d{6})$"
)


class RecordType(enum.StrEnum):
    """`TYPE` in a reference number; rows of `ref_record_type`."""

    CASE = "CASE"  # cases
    REQ = "REQ"  # requests between offices
    NOTE = "NOTE"  # case notes
    DOC = "DOC"  # uploaded court filings and internal documents
    TRF = "TRF"  # ownership transfers
    NXT = "NXT"  # manually entered next dates
    ALR = "ALR"  # alerts


def allocate_ref_no(
    session: Session, office_code: str, record_type: RecordType | str, when: datetime | None = None
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
        {"o": office_code, "t": str(record_type), "y": year},
    ).scalar_one()
    return f"ASLMS/{office_code}/{record_type}/{year}/{n:06d}"


def is_ref_no(value: str | None) -> bool:
    return bool(value) and REF_NO_RE.match(value.strip().upper()) is not None


def parse_ref_no(value: str) -> dict[str, str | int] | None:
    m = REF_NO_RE.match(value.strip().upper())
    if not m:
        return None
    return {"office": m["office"], "type": m["type"], "year": int(m["year"]), "n": int(m["n"])}
