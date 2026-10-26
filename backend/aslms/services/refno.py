"""Reference numbers: ASLMS/<OFFICE or COURT>/<TYPE>/<YYYY>/<NNNNNN> (DB_STANDARD v1.3 §3, §3a, Appendix C).

A case number is allocated on its court's code (`courts.ref_code`, `GHC` for the Gauhati High Court; design
`case-ref-court-prefix`); every other record type on the acting office, and alerts on `GOA`. One counter row per
(code, record type, year). The INSERT … ON CONFLICT … RETURNING form locks that row
only, so concurrent allocations serialise there and never on the business table. Gaps are allowed (a rolled
back transaction consumes a number); duplicates are not."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from aslms.domain.courts import Court

IST = ZoneInfo("Asia/Kolkata")
REF_NO_RE = re.compile(r"^ASLMS/([A-Z0-9_]{2,20})/([A-Z]{2,10})/(\d{4})/(\d{6})$")
CASE = "CASE"
# DB_STANDARD §3a: every `GOA` case number ever issued was a Gauhati High Court case and names the `GHC` case with
# the same year and number (the owner's one-time renumbering of 25 Oct 2026). A frozen fact, not a setting.
LEGACY_CASE_PREFIX = ("GOA", "GHC")


class CourtCodeMissing(LookupError):
    """The case's court has no `ref_code`: no case number is made up (CLAUDE.md, never fabricate identifiers)."""


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


def allocate_case_ref_no(session: Session, court: Court, when: datetime | None = None) -> str:
    """A case number on the court's code (`ASLMS/GHC/CASE/<YYYY>/<NNNNNN>`). No code -> CourtCodeMissing, and no
    counter is consumed."""
    code = (getattr(court, "ref_code", None) or "").strip()
    if not code:
        raise CourtCodeMissing(
            f"the court {court.est_code} has no reference code; no case number is allocated"
        )
    return allocate_ref_no(session, code, CASE, when)


def current_case_ref_no(ref_no: str) -> str:
    """An old `ASLMS/GOA/CASE/<YYYY>/<NNNNNN>` -> `ASLMS/GHC/CASE/<YYYY>/<NNNNNN>` (§3a); any other value unchanged."""
    parsed = parse_ref_no(ref_no) if isinstance(ref_no, str) else None
    if parsed is None:
        return ref_no
    code, rtype, year, n = parsed
    old, new = LEGACY_CASE_PREFIX
    if code == old and rtype == CASE:
        return format_ref_no(new, CASE, year, n)
    return ref_no
