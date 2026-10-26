"""Masters sync (pipeline stage 1): state, district, bench, case-type and act masters from NAPIX, upserted by
the court's own codes. Rows that disappear upstream are deactivated, never deleted. Runs daily, on the admin
button and before a load. Every response is kept verbatim by the recorder; `master_sync_runs` records counts."""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.courts import (
    Act,
    CaseType,
    Court,
    CourtLevel,
    District,
    DistrictKind,
    HighCourt,
    MasterKind,
    MasterSyncRun,
    State,
)
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services.napix_store import payload_sha256
from aslms.services.napix_values import as_int, as_text

# eCourts spellings in the NAPIX district master → the seeded district name (DB_STANDARD: codes are matched,
# never guessed; a spelling with no seeded counterpart becomes its own row under Assam).
ECOURTS_DISTRICT_ALIASES = {
    "Kamrup(M)": "Kamrup Metropolitan",
    "Sibsagar": "Sivasagar",
    "Karimganj": "Sribhumi",
    "Biswanath Chariali": "Biswanath",
    "South Salmara": "South Salmara-Mankachar",
}
AGENCY_NAMES = {"CBI", "NIA", "C/O 99 APO"}


@dataclass
class MasterReport:
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add(self, master: str, **kw: int) -> None:
        d = self.counts.setdefault(master, {"rows": 0, "inserted": 0, "updated": 0, "deactivated": 0})
        for k, v in kw.items():
            d[k] = d.get(k, 0) + v


def _now() -> datetime:
    return datetime.now(UTC)


def _record(session: Session, master: MasterKind, rows: Any, rep: dict[str, int]) -> None:
    session.add(
        MasterSyncRun(
            master=master,
            row_count=rep["rows"],
            inserted=rep["inserted"],
            deactivated=rep["deactivated"],
            sha256=payload_sha256(rows),
        )
    )


def sync_state_master(session: Session, rows: list[dict[str, Any]], report: MasterReport) -> None:
    existing = {hc.napix_state_code: hc for hc in session.scalars(select(HighCourt)).all()}
    seen: set[int] = set()
    for row in rows:
        code, name = as_int(row.get("state_code")), as_text(row.get("state_name"), 200)
        if code is None or not name:
            continue
        seen.add(code)
        report.add("state", rows=1)
        hc = existing.get(code)
        if hc is None:
            session.add(HighCourt(napix_state_code=code, name=name))
            report.add("state", inserted=1)
        elif hc.name != name or not hc.is_active:
            hc.name, hc.is_active, hc.deactivated_at = name, True, None
            report.add("state", updated=1)
    for code, hc in existing.items():
        if code not in seen and hc.is_active:
            hc.is_active, hc.deactivated_at = False, _now()
            report.add("state", deactivated=1)
    session.flush()
    _record(session, MasterKind.STATE, rows, report.counts["state"])


def sync_district_master(
    session: Session, rows: list[dict[str, Any]], high_court: HighCourt, state: State, report: MasterReport
) -> None:
    all_districts = session.scalars(select(District)).all()
    by_code = {
        d.ecourts_code: d
        for d in all_districts
        if d.ecourts_code is not None and d.high_court_id == high_court.id
    }
    by_name = {d.name.lower(): d for d in all_districts if d.state_id == state.id}
    by_ecourts_name = {d.ecourts_name.lower(): d for d in all_districts if d.ecourts_name}
    seen: set[int] = set()
    for row in rows:
        code, name = as_int(row.get("dist_code")), as_text(row.get("dist_name"), 100)
        if code is None or not name:
            continue
        seen.add(code)
        report.add("district", rows=1)
        d = by_code.get(code)
        if d is None:
            candidate = by_ecourts_name.get(name.lower()) or by_name.get(
                ECOURTS_DISTRICT_ALIASES.get(name, name).lower()
            )
            if candidate is not None and candidate.ecourts_code is None:
                d = candidate
                d.ecourts_code, d.ecourts_name, d.high_court_id = code, name, high_court.id
                report.add("district", updated=1)
            else:
                d = District(
                    state_id=state.id,
                    high_court_id=high_court.id,
                    ecourts_code=code,
                    ecourts_name=name,
                    name=name if name.lower() not in by_name else f"{name} ({code})",
                    kind=DistrictKind.AGENCY if name in AGENCY_NAMES else DistrictKind.DISTRICT,
                )
                session.add(d)
                by_name[d.name.lower()] = d
                report.add("district", inserted=1)
            by_code[code] = d
        else:
            if d.ecourts_name != name or not d.is_active:
                d.ecourts_name, d.is_active, d.deactivated_at = name, True, None
                report.add("district", updated=1)
    for code, d in by_code.items():
        if code not in seen and d.is_active:
            d.is_active, d.deactivated_at = False, _now()
            report.add("district", deactivated=1)
    session.flush()
    _record(session, MasterKind.DISTRICT, rows, report.counts["district"])


def sync_bench_master(
    session: Session, rows: list[dict[str, Any]], high_court: HighCourt, report: MasterReport
) -> None:
    existing = {c.est_code: c for c in session.scalars(select(Court)).all()}
    # the code a new establishment takes in case numbers: its High Court's existing one (design
    # case-ref-court-prefix, "Data"); never from NAPIX, never made up
    hc_codes = sorted(
        {c.ref_code for c in existing.values() if c.high_court_id == high_court.id and c.ref_code}
    )
    seen: set[str] = set()
    for row in rows:
        est, no, name = (
            as_text(row.get("est_code"), 10),
            as_int(row.get("bench_id")),
            as_text(row.get("bench_name"), 200),
        )
        if not est or not name:
            continue
        seen.add(est)
        report.add("bench", rows=1)
        c = existing.get(est)
        full = f"{high_court.name}, {name}"
        if c is None:
            if len(hc_codes) != 1:
                report.errors.append(
                    f"bench {est} ({name}) skipped: {high_court.name} has "
                    f"{'no court code' if not hc_codes else 'more than one court code'} for case numbers"
                )
                continue
            session.add(
                Court(
                    est_code=est,
                    name=full,
                    high_court_id=high_court.id,
                    napix_bench_no=no,
                    bench_location=name,
                    court_level=CourtLevel.HC,
                    ref_code=hc_codes[0],
                )
            )
            report.add("bench", inserted=1)
        elif (c.bench_location, c.napix_bench_no, c.high_court_id, c.is_active) != (
            name,
            no,
            high_court.id,
            True,
        ):
            c.bench_location, c.napix_bench_no, c.high_court_id = name, no, high_court.id
            c.name = c.name or full
            c.is_active, c.deactivated_at = True, None
            report.add("bench", updated=1)
    for est, c in existing.items():
        if est not in seen and c.is_active and c.high_court_id == high_court.id:
            c.is_active, c.deactivated_at = False, _now()
            report.add("bench", deactivated=1)
    session.flush()
    _record(session, MasterKind.BENCH, rows, report.counts["bench"])


def split_type_name(type_name: str) -> tuple[str | None, str | None]:
    """`WA : Writ Appeal` → (`WA`, `Writ Appeal`); `abc : ` → (`abc`, None)."""
    if " : " in type_name:
        short, _, full = type_name.partition(" : ")
        return as_text(short, 60), as_text(full, 300)
    if type_name.endswith(" :"):
        return as_text(type_name[:-2], 60), None
    return as_text(type_name, 60), None


def sync_case_type_master(
    session: Session, rows: list[dict[str, Any]], court: Court, report: MasterReport
) -> None:
    existing = {
        ct.case_type_code: ct
        for ct in session.scalars(select(CaseType).where(CaseType.court_id == court.id)).all()
    }
    seen: set[int] = set()
    for row in rows:
        code, name = as_int(row.get("case_type")), as_text(row.get("type_name"), 300)
        if code is None or not name:
            continue
        seen.add(code)
        report.add("case_type", rows=1)
        short, full = split_type_name(name)
        ct = existing.get(code)
        if ct is None:
            session.add(
                CaseType(
                    court_id=court.id, case_type_code=code, type_name=name, short_name=short, full_name=full
                )
            )
            report.add("case_type", inserted=1)
        elif (ct.type_name, ct.short_name, ct.full_name, ct.is_active) != (name, short, full, True):
            ct.type_name, ct.short_name, ct.full_name, ct.is_active, ct.deactivated_at = (
                name,
                short,
                full,
                True,
                None,
            )
            report.add("case_type", updated=1)
    for code, ct in existing.items():
        if code not in seen and ct.is_active:
            ct.is_active, ct.deactivated_at = False, _now()
            report.add("case_type", deactivated=1)
    session.flush()
    _record(session, MasterKind.CASE_TYPE, rows, report.counts["case_type"])


def sync_act_master(session: Session, rows: list[dict[str, Any]], report: MasterReport) -> None:
    """Keyed by (national_act_code, name): the master repeats codes across acts and names across codes.
    Names carry HTML entities (`&#039;`), unescaped here; the verbatim response keeps the original."""
    existing = {(a.national_act_code, a.name): a for a in session.scalars(select(Act)).all()}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        code = as_text(row.get("national_act_code"), 20)
        name = as_text(html.unescape(str(row.get("actname") or "")), 300)
        if not code:
            continue
        name = name or f"(unnamed act {code})"
        report.add("act", rows=1)
        key = (code, name)
        if key in seen:
            report.add("act", duplicates=1)  # exact repeats in the master
            continue
        seen.add(key)
        a = existing.get(key)
        if a is None:
            session.add(Act(national_act_code=code, name=name))
            report.add("act", inserted=1)
        elif not a.is_active:
            a.is_active, a.deactivated_at = True, None
            report.add("act", updated=1)
    for key, a in existing.items():
        if key not in seen and a.is_active:
            a.is_active, a.deactivated_at = False, _now()
            report.add("act", deactivated=1)
    session.flush()
    _record(session, MasterKind.ACT, rows, report.counts["act"])


async def sync_masters(
    session: Session, hc: NapixHighCourt, *, job_run_id: uuid.UUID | None = None
) -> MasterReport:
    """All five masters in one pass (about five calls). The High Court and the state must be seeded."""
    report = MasterReport()
    sync_state_master(session, await hc.state_master(), report)
    high_court = session.scalar(select(HighCourt).where(HighCourt.napix_state_code == int(hc.state_code)))
    if high_court is None:
        raise RuntimeError(f"state code {hc.state_code} is not in the state master")
    state = session.scalar(select(State).where(State.name == "Assam"))
    if state is None:
        raise RuntimeError("seed first: the state Assam is missing")
    sync_district_master(session, await hc.district_master(), high_court, state, report)
    sync_bench_master(session, await hc.bench_master(), high_court, report)
    court = session.scalar(select(Court).where(Court.est_code == hc.est_code))
    if court is None:
        raise RuntimeError(f"establishment {hc.est_code} is not in the bench master")
    sync_case_type_master(session, await hc.case_type_master(), court, report)
    sync_act_master(session, await hc.act_master(), report)
    return report
