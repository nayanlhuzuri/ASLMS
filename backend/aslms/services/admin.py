"""Administration (plan §5.11): offices in the government hierarchy, users and roles, code-to-department
mapping, name patterns and keywords, watchlists, NAPIX masters, and department discovery (plan §3.1:
department party names run periodically through Search by Party Name). Every change is audited."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import any_, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.errors import ConflictError, IntegrationError, NotFoundError, ValidationError
from aslms.core.security import hash_password
from aslms.core.text import is_cnr
from aslms.core.time import now_utc, today_ist
from aslms.domain.cases import Act, Case, District, FirstSeenSource, State
from aslms.domain.org import Office, OfficeKind, Role, User
from aslms.domain.ownership import (
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    OfficeWatchlist,
    RecommendationOrigin,
)
from aslms.domain.reference import Bench, CaseType, Court, CourtLevel, MasterKind, MasterSyncRun
from aslms.integration.ghc.causelist_pdf import normalise_counsel_code
from aslms.services import audit, ownership
from aslms.services import cases as case_svc
from aslms.services.audit import Actor
from aslms.services.auth import validate_password

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 .&-]{0,31}$")


# ------------------------------------------------------------------------------------------ offices
def create_office(
    session: Session, actor: Actor, *, code: str, name: str, kind: OfficeKind, parent_id: uuid.UUID | None
) -> Office:
    code = code.strip().upper()
    if not CODE_RE.match(code) or "/" in code:
        raise ValidationError("office code: capitals, digits, space . & - only, up to 32 characters")
    if session.scalar(select(Office).where(Office.code == code)):
        raise ConflictError("an office with this code exists", code=code)
    parent = session.get(Office, parent_id) if parent_id else None
    if parent_id and parent is None:
        raise NotFoundError("parent office not found")
    if kind == OfficeKind.DEPARTMENT and parent is not None:
        raise ValidationError("a department is a top-level office")
    if kind in (OfficeKind.DIRECTORATE, OfficeKind.SECTION) and parent is None:
        raise ValidationError("a directorate or section needs a parent office")
    office = Office(
        code=code,
        name=name.strip(),
        kind=kind,
        parent_id=parent.id if parent else None,
        path=f"{parent.path}/{code}" if parent else code,
    )
    session.add(office)
    session.flush()
    audit.record(
        session,
        actor,
        "office.create",
        "office",
        office.id,
        after={"code": code, "name": name, "kind": kind.value},
    )
    return office


def update_office(
    session: Session, actor: Actor, office: Office, *, name: str | None = None, is_active: bool | None = None
) -> Office:
    before = {"name": office.name, "is_active": office.is_active}
    if name:
        office.name = name.strip()
    if is_active is not None:
        office.is_active = is_active
        office.deactivated_at = None if is_active else now_utc()
    audit.record(
        session,
        actor,
        "office.update",
        "office",
        office.id,
        before=before,
        after={"name": office.name, "is_active": office.is_active},
    )
    return office


# ------------------------------------------------------------------------------------------ users
def create_user(
    session: Session,
    actor: Actor,
    *,
    email: str,
    full_name: str,
    office_id: uuid.UUID,
    role: Role,
    password: str,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
    mobile: str | None = None,
) -> User:
    email = email.strip().lower()
    if session.scalar(select(User).where(User.email == email)):
        raise ConflictError("a user with this e-mail exists")
    office = session.get(Office, office_id)
    if office is None:
        raise NotFoundError("office not found")
    _check_role_office(role, office)
    validate_password(password)
    user = User(
        email=email,
        full_name=full_name.strip(),
        office_id=office.id,
        role=role,
        password_hash=hash_password(password),
        designation=designation,
        designation_id=designation_id,
        mobile=mobile,
    )
    session.add(user)
    session.flush()
    audit.record(
        session,
        actor,
        "user.create",
        "user",
        user.id,
        after={"email": email, "role": role.value, "office": office.code},
    )
    return user


def _check_role_office(role: Role, office: Office) -> None:
    if role == Role.STATE_OVERSIGHT and office.kind != OfficeKind.STATE_OFFICE:
        raise ValidationError("state oversight users belong to the State office")
    if role == Role.CENTRAL_OPERATOR and office.kind != OfficeKind.CENTRAL_CELL:
        raise ValidationError("central operators belong to the central monitoring cell")
    if role in (Role.DEPT_ADMIN, Role.DEPT_HEAD) and office.kind != OfficeKind.DEPARTMENT:
        raise ValidationError("department admins and heads belong to a department office")
    if role == Role.DIRECTORATE_USER and office.kind not in (OfficeKind.DIRECTORATE, OfficeKind.SECTION):
        raise ValidationError("directorate users belong to a directorate or section")


def update_user(session: Session, actor: Actor, user: User, **changes: Any) -> User:
    before = {k: getattr(user, k) for k in changes if hasattr(user, k)}
    if "office_id" in changes or "role" in changes:
        office = session.get(Office, changes.get("office_id", user.office_id))
        if office is None:
            raise NotFoundError("office not found")
        _check_role_office(changes.get("role", user.role), office)
    for k, v in changes.items():
        if k == "password":
            validate_password(v)
            user.password_hash = hash_password(v)
        elif v is not None and hasattr(user, k):
            setattr(user, k, v)
    audit.record(
        session,
        actor,
        "user.update",
        "user",
        user.id,
        before={k: str(v) for k, v in before.items()},
        after={k: ("***" if k == "password" else str(v)) for k, v in changes.items()},
    )
    return user


# ------------------------------------------------------------------------------------------ mapping
def upsert_counsel_code(
    session: Session,
    actor: Actor,
    *,
    code: str,
    office_id: uuid.UUID,
    weight: float = 0.95,
    is_generic_state: bool = False,
    notes: str | None = None,
) -> CounselCode:
    norm = normalise_counsel_code(code)
    if not (0 <= weight <= 1):
        raise ValidationError("weight must be between 0 and 1")
    if session.get(Office, office_id) is None:
        raise NotFoundError("office not found")
    row = session.scalar(select(CounselCode).where(CounselCode.code == norm))
    before = None
    if row:
        before = {
            "office_id": str(row.office_id),
            "weight": float(row.weight),
            "generic": row.is_generic_state,
        }
        row.office_id, row.weight, row.is_generic_state, row.notes, row.is_active = (
            office_id,
            weight,
            is_generic_state,
            notes,
            True,
        )
        row.deactivated_at = None
    else:
        row = CounselCode(
            code=norm, office_id=office_id, weight=weight, is_generic_state=is_generic_state, notes=notes
        )
        session.add(row)
    session.flush()
    audit.record(
        session,
        actor,
        "mapping.counsel_code",
        "counsel_code",
        row.id,
        before=before,
        after={"code": norm, "office_id": str(office_id), "weight": weight, "generic": is_generic_state},
    )
    return row


def unmapped_codes(session: Session, limit: int = 100) -> list[dict[str, Any]]:
    """Codes seen in cause lists that are not mapped yet, most frequent first — the admin's to-do list."""
    from aslms.domain.causelists import CauseListEntry

    code = func.unnest(CauseListEntry.counsel_codes).label("code")
    sub = select(code).subquery()
    rows = session.execute(
        select(sub.c.code, func.count())
        .where(sub.c.code.notin_(select(CounselCode.code)))
        .group_by(sub.c.code)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [{"code": c, "seen": n} for c, n in rows]


def rescore_for_code(session: Session, code: str) -> int:
    """Rescores the cases in which this counsel code appears (advocates or cause-list entries)."""
    from aslms.domain.cases import CaseAdvocate
    from aslms.domain.causelists import CauseListEntry

    ids = set(session.scalars(select(CaseAdvocate.case_id).where(CaseAdvocate.counsel_code == code)))
    ids |= set(
        session.scalars(
            select(CauseListEntry.case_id).where(
                CauseListEntry.case_id.isnot(None), literal(code) == any_(CauseListEntry.counsel_codes)
            )
        )
    )
    cfg = ownership.load_config(session)
    for c in session.scalars(select(Case).where(Case.id.in_(ids))):
        ownership.rescore(session, c, cfg)
    return len(ids)


def queue_rescore_all() -> bool:
    """Asks the workers for a full rescore (after a pattern, keyword or watchlist change). Returns False when the
    queue is unreachable; the operator can then run it from Operations."""
    try:
        from aslms.jobs.tasks import ops_rescore_all

        ops_rescore_all.apply_async(retry=False)
        return True
    except Exception:  # noqa: BLE001 — a broker outage must not fail the admin change
        return False


def rescore_all(session: Session, limit: int | None = None) -> int:
    """After the mapping changes, recompute scores for pending cases (idempotent)."""
    cfg = ownership.load_config(session)
    q = (
        select(Case)
        .where(Case.status != "disposed", Case.merged_into_case_id.is_(None))
        .order_by(Case.next_hearing_date.desc().nulls_last())
    )
    if limit:
        q = q.limit(limit)
    n = 0
    for c in session.scalars(q):
        ownership.rescore(session, c, cfg)
        n += 1
    return n


# ------------------------------------------------------------------------------------------ NAPIX masters
def sync_masters(session: Session, hc) -> dict[str, int]:
    counts: dict[str, int] = {}
    court = case_svc.default_court(session)
    try:
        benches = asyncio.run(hc.bench_master())
    except IntegrationError as e:
        raise IntegrationError(f"bench master: {e}") from e
    for b in benches:
        est = str(b.get("est_code") or "").strip()
        if not est:
            continue
        session.execute(
            insert(Court)
            .values(
                est_code=est,
                name=str(b.get("bench_name") or b.get("est_name") or est)[:300],
                state_code=hc.state_code,
                bench_location=str(b.get("bench_name") or "")[:200] or None,
                court_level=CourtLevel.HC,
            )
            .on_conflict_do_nothing(index_elements=["est_code"])
        )
    session.add(
        MasterSyncRun(
            master=MasterKind.BENCH,
            fetched_at=now_utc(),
            row_count=len(benches),
            sha256=hashlib.sha256(json.dumps(benches, sort_keys=True, default=str).encode()).hexdigest(),
        )
    )
    counts["benches"] = len(benches)
    types = asyncio.run(hc.case_type_master())
    for t in types:
        code, name = t.get("case_type"), t.get("type_name")
        if code is None or not name or not str(code).strip().isdigit():
            continue
        name = str(name).strip()
        session.execute(
            insert(CaseType)
            .values(
                court_id=court.id,
                case_type_code=int(code),
                type_name=name[:64],
                full_name=str(t.get("full_form") or t.get("type_full_name") or "")[:300] or None,
                aliases=[name.upper()],
            )
            .on_conflict_do_update(
                index_elements=["court_id", "case_type_code"], set_={"type_name": name[:64]}
            )
        )
    session.add(
        MasterSyncRun(
            master=MasterKind.CASE_TYPE,
            fetched_at=now_utc(),
            row_count=len(types),
            sha256=hashlib.sha256(json.dumps(types, sort_keys=True, default=str).encode()).hexdigest(),
        )
    )
    counts["case_types"] = len(types)
    counts.update(_sync_places_and_acts(session, hc))
    # cases created before the master was loaded get their case type now
    session.execute(
        update(Case)
        .where(Case.case_type_id.is_(None), Case.case_type_text.isnot(None), Case.court_id == court.id)
        .values(
            case_type_id=select(CaseType.id)
            .where(CaseType.court_id == court.id, Case.case_type_text == any_(CaseType.aliases))
            .limit(1)
            .scalar_subquery()
        )
    )
    return counts


def _sync_run(session: Session, kind: MasterKind, rows: list) -> None:
    session.add(
        MasterSyncRun(
            master=kind,
            fetched_at=now_utc(),
            row_count=len(rows),
            sha256=hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest(),
        )
    )


def _sync_places_and_acts(session: Session, hc) -> dict[str, int]:
    """DB_STANDARD §0 rule 2 / §10: states, districts and acts are synced from the NAPIX masters, keyed by
    the court's own codes, never deleted (rows absent upstream are deactivated). LGD codes are not in
    NAPIX and stay as entered by the administrator."""
    counts: dict[str, int] = {}
    states = asyncio.run(hc.state_master())
    for row in states:
        code, name = (
            _s(row.get("state_code") or row.get("state_cd")),
            _s(row.get("state_name") or row.get("name")),
        )
        if not code or not name:
            continue
        st = session.scalar(select(State).where(State.ecourts_code == code)) or session.scalar(
            select(State).where(func.lower(State.name) == name.lower())
        )
        if st is None:
            session.add(State(ecourts_code=code, name=name[:120]))
        else:
            st.ecourts_code, st.is_active, st.deactivated_at = code, True, None
    session.flush()
    _sync_run(session, MasterKind.STATE, states)
    counts["states"] = len(states)
    home = session.scalar(select(State).where(State.ecourts_code == hc.state_code))
    districts = asyncio.run(hc.district_master())
    if home is not None:
        seen: set[str] = set()
        for row in districts:
            code, name = (
                _s(row.get("dist_code") or row.get("district_code")),
                _s(row.get("dist_name") or row.get("district_name") or row.get("name")),
            )
            if not name:
                continue
            d = session.scalar(
                select(District).where(
                    District.state_id == home.id, func.lower(District.name) == name.lower()
                )
            )
            if d is None and code:
                d = session.scalar(
                    select(District).where(District.state_id == home.id, District.ecourts_code == code)
                )
            if d is None:
                d = District(state_id=home.id, name=name[:120], ecourts_code=code)
                session.add(d)
            else:
                d.ecourts_code, d.is_active, d.deactivated_at = code or d.ecourts_code, True, None
            seen.add(name.lower())
        session.flush()
        for d in session.scalars(
            select(District).where(District.state_id == home.id, District.is_active.is_(True))
        ):
            if d.name.lower() not in seen and districts:
                d.is_active, d.deactivated_at = False, now_utc()
    _sync_run(session, MasterKind.DISTRICT, districts)
    counts["districts"] = len(districts)
    acts = asyncio.run(hc.act_master())
    for row in acts:
        code = _s(row.get("act_code") or row.get("national_act_code") or row.get("actcode"))
        name = _s(row.get("act_name") or row.get("actname") or row.get("name"))
        if not name:
            continue
        a = (
            session.scalar(select(Act).where(Act.national_act_code == code)) if code else None
        ) or session.scalar(select(Act).where(func.lower(Act.name) == name.lower()))
        if a is None:
            session.add(Act(national_act_code=code[:32] if code else None, name=name[:300]))
        else:
            a.national_act_code, a.is_active, a.deactivated_at = (
                (code[:32] if code else a.national_act_code),
                True,
                None,
            )
    session.flush()
    _sync_run(session, MasterKind.ACT, acts)
    counts["acts"] = len(acts)
    return counts


def _s(v) -> str | None:
    t = str(v).strip() if v is not None else ""
    return t or None


def record_bench(session: Session, court: Court, bench_id: str, judges: str | None) -> None:
    today = today_ist()
    session.execute(
        insert(Bench)
        .values(court_id=court.id, bench_id=bench_id, judge_names=judges, first_seen=today, last_seen=today)
        .on_conflict_do_update(
            index_elements=["court_id", "bench_id"], set_={"last_seen": today, "judge_names": judges}
        )
    )


# ------------------------------------------------------------------------------------------ discovery
def discover(session: Session, hc, *, per_department: int = 50) -> dict[str, int]:
    """Runs each active name pattern and keyword through NAPIX Search by Party Name (pending cases) and stores
    the cases found. Finds a department's cases before they appear in a cause list."""
    court = case_svc.default_court(session)
    terms: dict[str, uuid.UUID] = {}
    for p in session.scalars(
        select(OfficeNamePattern).where(
            OfficeNamePattern.is_active.is_(True), OfficeNamePattern.kind != "regex"
        )
    ):
        terms.setdefault(p.pattern.strip(), p.office_id)
    for k in session.scalars(select(OfficeKeyword).where(OfficeKeyword.is_active.is_(True))):
        if len(k.keyword.strip()) >= 6:
            terms.setdefault(k.keyword.strip(), k.office_id)
    counts = {"terms": len(terms), "found": 0, "new_cases": 0, "failed": 0}
    cfg = ownership.load_config(session)
    for term in terms:
        try:
            hits = asyncio.run(hc.search_party(term))
        except IntegrationError:
            counts["failed"] += 1
            continue
        for h in hits[:per_department]:
            cnr = str(h.get("cino") or "").upper()
            if not cnr:
                continue
            counts["found"] += 1
            case, created = case_svc.resolve_case(
                session,
                cnr=cnr,
                case_no_text=h.get("case_no") or None,
                court=court,
                source=FirstSeenSource.DISCOVERY,
                petitioner=h.get("pet_name"),
                respondent=h.get("res_name"),
            )
            if created:
                counts["new_cases"] += 1
                ownership.rescore(session, case, cfg, origin=RecommendationOrigin.DISCOVERY)
    return counts


def watch(
    session: Session, actor: Actor, office_id: uuid.UUID, cnr: str, reason: str | None
) -> OfficeWatchlist:
    cnr = cnr.strip().upper()
    if not is_cnr(cnr):
        raise ValidationError("not a CNR", cnr=cnr)
    row = session.scalar(
        select(OfficeWatchlist).where(OfficeWatchlist.office_id == office_id, OfficeWatchlist.cnr == cnr)
    )
    if row:
        row.is_active, row.reason, row.deactivated_at = True, reason or row.reason, None
    else:
        case = case_svc.get_by_cnr(session, cnr)
        row = OfficeWatchlist(
            office_id=office_id, cnr=cnr, case_id=case.id if case else None, reason=reason, **actor.snapshot()
        )
        session.add(row)
    session.flush()
    audit.record(
        session,
        actor,
        "mapping.watch",
        "office_watchlist",
        row.id,
        after={"cnr": cnr, "office_id": str(office_id)},
    )
    case = case_svc.get_by_cnr(session, cnr)
    if case:
        ownership.rescore(session, case)
    return row
