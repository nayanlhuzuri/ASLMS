"""Search (plan §5.2, §6.3): the portal database first; if nothing is found and NAPIX is configured, the NAPIX
search APIs are queried live and any case found is fetched by CNR and stored, so the next search is local.
Results carry tracking-card fields only, plus `in_scope` so the UI knows whether the full case can be opened."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from aslms.core.errors import IntegrationError
from aslms.core.text import canonical_case_no, is_cnr, normalise_name, split_case_no
from aslms.domain.cases import Case, CaseAdvocate, CaseParty, CaseStatus, FirstSeenSource
from aslms.domain.org import Office
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.integration.factory import napix_source
from aslms.services import cases as case_svc
from aslms.services import ownership
from aslms.services.scope import Principal, case_scope_clause

CASE_NO_LIKE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9().&\s-]*/\s*\d+\s*(/\s*\d{4})?\s*$")


@dataclass
class SearchFilters:
    status: str | None = None  # pending | disposed
    year: int | None = None
    case_type: str | None = None
    department_id: Any = None
    ownership: str | None = None  # claimed | unclaimed
    advocate: str | None = None
    party: str | None = None


@dataclass
class SearchResult:
    total: int
    items: list[Case]
    live: dict[str, Any] = field(default_factory=dict)


def _query(q: str | None, f: SearchFilters):
    stmt = select(Case).where(Case.merged_into_case_id.is_(None))
    rank = None
    if q:
        text = q.strip()
        if is_cnr(text):
            stmt = stmt.where(Case.cnr == text.upper())
        elif CASE_NO_LIKE.match(text):
            t, n, y = split_case_no(text)
            if t:
                stmt = stmt.where(
                    or_(
                        Case.case_no_text == canonical_case_no(text),
                        Case.filing_no_text == text.upper().replace(" ", ""),
                    )
                )
            else:
                parts = [p.strip() for p in text.split("/")]
                stmt = stmt.where(
                    func.upper(Case.case_type_text) == parts[0].upper(), Case.reg_no == int(parts[1])
                )
        else:
            tsq = func.plainto_tsquery("simple", text)
            like = f"%{normalise_name(text)}%"
            party_hit = exists().where(
                and_(CaseParty.case_id == Case.id, CaseParty.name_normalised.like(like))
            )
            stmt = stmt.where(
                or_(
                    Case.search_vector.op("@@")(tsq),
                    party_hit,
                    func.upper(Case.petitioner_summary).like(like),
                    func.upper(Case.respondent_summary).like(like),
                )
            )
            rank = func.ts_rank(Case.search_vector, tsq)
    if f.status in ("pending", "disposed"):
        stmt = stmt.where(Case.status == CaseStatus(f.status))
    if f.year:
        stmt = stmt.where(Case.reg_year == f.year)
    if f.case_type:
        stmt = stmt.where(func.upper(Case.case_type_text) == f.case_type.upper())
    if f.advocate:
        like = f"%{f.advocate.strip().upper()}%"
        stmt = stmt.where(
            exists().where(and_(CaseAdvocate.case_id == Case.id, func.upper(CaseAdvocate.name_as_listed).like(like)))
        )
    if f.party:
        like = f"%{normalise_name(f.party)}%"
        stmt = stmt.where(
            or_(
                exists().where(and_(CaseParty.case_id == Case.id, CaseParty.name_normalised.like(like))),
                func.upper(Case.petitioner_summary).like(like),
                func.upper(Case.respondent_summary).like(like),
            )
        )
    active = and_(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
    if f.ownership == "unclaimed":
        stmt = stmt.where(~exists().where(active))
    elif f.ownership == "claimed":
        stmt = stmt.where(exists().where(active))
    if f.department_id:
        dept = select(Office.path).where(Office.id == f.department_id).scalar_subquery()
        stmt = stmt.where(
            exists().where(
                and_(
                    active,
                    CaseOwnership.office_id.in_(
                        select(Office.id).where(or_(Office.path == dept, Office.path.like(dept + "/%")))
                    ),
                )
            )
        )
    return stmt, rank


def search(
    session: Session,
    p: Principal,
    q: str | None,
    f: SearchFilters,
    *,
    page: int = 1,
    size: int = 25,
    live: bool = True,
    only_in_scope: bool = False,
) -> SearchResult:
    stmt, rank = _query(q, f)
    if only_in_scope:
        stmt = stmt.where(case_scope_clause(p))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = [rank.desc()] if rank is not None else []
    order += [Case.next_hearing_date.desc().nulls_last(), Case.created_at.desc()]
    items = list(session.scalars(stmt.order_by(*order).offset((page - 1) * size).limit(size)))
    result = SearchResult(total, items)
    if total == 0 and q and live:
        result.live = live_search(session, q)
        if result.live.get("stored"):
            stmt, rank = _query(q, f)
            result.total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            result.items = list(session.scalars(stmt.limit(size)))
    return result


def live_search(session: Session, q: str, limit: int = 10) -> dict[str, Any]:
    """NAPIX fallback. Stores every case it finds (Search by CNR for the full record)."""
    built = napix_source()
    if built is None:
        return {"napix": "not configured"}
    hc, recorder = built
    text = q.strip()
    found: list[str] = []
    try:
        if is_cnr(text):
            found = [text.upper()]
        elif CASE_NO_LIKE.match(text):
            t, n, y = split_case_no(text)
            ct = case_svc.case_type_for(session, case_svc.default_court(session).id, t) if t else None
            if ct and y:
                hits = asyncio.run(hc.search_case_number(ct.case_type_code, n, y))
                found = [str(h.get("cino")).upper() for h in hits if h.get("cino")]
        elif len(text) >= 3:
            hits = asyncio.run(hc.search_party(text)) + asyncio.run(hc.search_advocate(text))
            found = list(dict.fromkeys(str(h.get("cino")).upper() for h in hits if h.get("cino")))
    except IntegrationError as e:
        recorder.flush(session)
        return {"napix": "error", "error": str(e)}
    stored = 0
    court = case_svc.default_court(session)
    for cnr in found[:limit]:
        if not is_cnr(cnr):
            continue
        try:
            rec = asyncio.run(hc.case_by_cnr(cnr))
        except IntegrationError:
            continue
        if rec is None:
            continue
        case, _ = case_svc.resolve_case(
            session, cnr=cnr, case_no_text=None, court=court, source=FirstSeenSource.SEARCH
        )
        case_svc.apply_case_record(session, case, rec)
        ownership.rescore(session, case)
        stored += 1
    recorder.flush(session)
    return {"napix": "ok", "found": len(found), "stored": stored}


def owner_summary(session: Session, case_ids: list) -> dict[Any, dict[str, Any]]:
    """Owning department per case, for tracking cards."""
    out: dict[Any, dict[str, Any]] = {}
    if not case_ids:
        return out
    for own, office in session.execute(
        select(CaseOwnership, Office)
        .join(Office, Office.id == CaseOwnership.office_id)
        .where(CaseOwnership.case_id.in_(case_ids), CaseOwnership.status == OwnershipStatus.ACTIVE)
    ):
        d = out.setdefault(own.case_id, {"primary": None, "watchers": []})
        entry = {"office_id": str(office.id), "code": office.code, "name": office.name}
        if own.role == OwnershipRole.PRIMARY:
            d["primary"] = entry
        else:
            d["watchers"].append(entry)
    return out
