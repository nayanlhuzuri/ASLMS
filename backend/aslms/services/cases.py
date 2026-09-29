"""Canonical cases: resolution by CNR, creation from cause-list rows, and applying court records (NAPIX CNR and
Current Status responses) with change detection → events, orders, next dates.

Identity rules (ground rule 1): a case is found by CNR; a row without a CNR resolves to an existing case with
the same court and case number if one exists, otherwise to a provisional case with `cnr = NULL`. When a CNR
later arrives for a provisional case's number, the provisional case is upgraded in place — never guessed."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import any_, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.text import canonical_case_no, is_cnr, normalise_name, split_case_no
from aslms.core.time import now_utc, parse_date
from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import (
    AdvocateSide,
    Case,
    CaseAct,
    CaseAdvocate,
    CaseHearing,
    CaseLink,
    CaseParty,
    CaseSnapshot,
    CaseStatus,
    FirstSeenSource,
    HearingSource,
    LinkKind,
    LinkSource,
    PartyRole,
    SnapshotSource,
)
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import EventType
from aslms.domain.reference import CaseType, Court, CourtLevel
from aslms.integration.base import CaseRecord, StatusRecord
from aslms.integration.ghc.causelist_pdf import is_counsel_code, normalise_counsel_code
from aslms.services import events
from aslms.services.refno import SYSTEM_OFFICE, RecordType, allocate_ref_no


# ------------------------------------------------------------------------------------------ lookups
def default_court(session: Session) -> Court:
    est = get_settings().napix_hc_est_code
    court = session.scalar(select(Court).where(Court.est_code == est))
    if court is None:
        court = Court(
            est_code=est,
            name="Gauhati High Court",
            state_code=get_settings().napix_state_code,
            court_level=CourtLevel.HC,
        )
        session.add(court)
        session.flush()
    return court


def case_type_for(session: Session, court_id: uuid.UUID, type_text: str | None) -> CaseType | None:
    if not type_text:
        return None
    t = type_text.strip().upper()
    return session.scalar(
        select(CaseType).where(
            CaseType.court_id == court_id,
            (func.upper(CaseType.type_name) == t) | (literal(t) == any_(CaseType.aliases)),
        )
    )


def get_by_cnr(session: Session, cnr: str) -> Case | None:
    return session.scalar(select(Case).where(Case.cnr == cnr.strip().upper()))


def find_by_case_no(session: Session, court_id: uuid.UUID, case_no_text: str) -> Case | None:
    canon = canonical_case_no(case_no_text)
    return session.scalar(
        select(Case)
        .where(Case.court_id == court_id, Case.case_no_text == canon, Case.merged_into_case_id.is_(None))
        .order_by(Case.is_provisional.asc(), Case.created_at.asc())
        .limit(1)
    )


# ------------------------------------------------------------------------------------------ creation
def resolve_case(
    session: Session,
    *,
    cnr: str | None,
    case_no_text: str | None,
    court: Court,
    source: FirstSeenSource,
    is_filing_number: bool = False,
    petitioner: str | None = None,
    respondent: str | None = None,
    ref_office: str = SYSTEM_OFFICE,
) -> tuple[Case, bool]:
    """Finds or creates the canonical case. Returns (case, created). A new case gets its reference number
    from `ref_office` (`GOA` unless a department's discovery created it; DB_STANDARD §3)."""
    cnr = cnr.strip().upper() if cnr else None
    if cnr and not is_cnr(cnr):
        cnr = None
    canon = canonical_case_no(case_no_text) if case_no_text and not is_filing_number else None

    if cnr:
        case = get_by_cnr(session, cnr)
        if case:
            return case, False
        if canon:
            prov = session.scalar(
                select(Case).where(
                    Case.court_id == court.id, Case.case_no_text == canon, Case.is_provisional.is_(True)
                )
            )
            if prov:
                prov.cnr, prov.is_provisional = cnr, False
                events.emit(
                    session,
                    EventType.CASE_REFRESHED,
                    f"cnr_assigned:{prov.id}:{cnr}",
                    case_id=prov.id,
                    payload={"cnr": cnr, "reason": "provisional case upgraded when its CNR appeared"},
                )
                return prov, False
    elif canon:
        existing = find_by_case_no(session, court.id, canon)
        if existing:
            return existing, False
    elif case_no_text and is_filing_number:
        existing = session.scalar(
            select(Case).where(Case.court_id == court.id, Case.filing_no_text == case_no_text.upper())
        )
        if existing:
            return existing, False

    type_text, reg_no, reg_year = split_case_no(canon) if canon else (None, None, None)
    ct = case_type_for(session, court.id, type_text)
    case = Case(
        ref_no=allocate_ref_no(session, ref_office, RecordType.CASE),
        cnr=cnr,
        court_id=court.id,
        case_type_id=ct.id if ct else None,
        case_type_text=type_text,
        reg_no=reg_no,
        reg_year=reg_year,
        case_no_text=canon,
        filing_no_text=case_no_text.upper() if is_filing_number and case_no_text else None,
        status=CaseStatus.PENDING,
        petitioner_summary=petitioner,
        respondent_summary=respondent,
        is_provisional=cnr is None,
        first_seen_source=source,
    )
    session.add(case)
    session.flush()
    events.emit(
        session,
        EventType.CASE_CREATED,
        f"case_created:{cnr or case.id}",
        case_id=case.id,
        payload={
            "cnr": cnr,
            "ref_no": case.ref_no,
            "case_no": canon or case.filing_no_text,
            "source": source.value,
            "provisional": cnr is None,
        },
    )
    return case, True


def add_advocates(session: Session, case: Case, side: AdvocateSide, names: list[str]) -> None:
    """Adds advocates not yet recorded for this side. Counsel codes are stored normalised in `counsel_code`."""
    existing = {
        (a.name_as_listed.upper())
        for a in session.scalars(
            select(CaseAdvocate).where(CaseAdvocate.case_id == case.id, CaseAdvocate.side == side)
        )
    }
    for raw in names:
        name = raw.strip()
        if not name or name.upper() in existing:
            continue
        code = normalise_counsel_code(name) if is_counsel_code(name) else None
        session.add(CaseAdvocate(case_id=case.id, side=side, name_as_listed=name, counsel_code=code))
        existing.add(name.upper())


def add_link(
    session: Session,
    from_case: Case,
    to_case_no_text: str,
    kind: LinkKind,
    source: LinkSource,
    to_cnr: str | None = None,
) -> None:
    canon = canonical_case_no(to_case_no_text) or to_case_no_text
    target = get_by_cnr(session, to_cnr) if to_cnr else find_by_case_no(session, from_case.court_id, canon)
    stmt = (
        insert(CaseLink)
        .values(
            from_case_id=from_case.id,
            to_case_id=target.id if target else None,
            to_case_no_text=canon,
            to_cnr=to_cnr,
            kind=kind,
            source=source,
        )
        .on_conflict_do_nothing(index_elements=["from_case_id", "to_case_no_text", "kind"])
    )
    if session.execute(stmt).rowcount:
        events.emit(
            session,
            EventType.CASE_LINKED,
            f"link:{from_case.id}:{canon}:{kind.value}",
            case_id=from_case.id,
            payload={"to": canon, "kind": kind.value},
        )


def link_pending_targets(session: Session, case: Case) -> None:
    """When a case appears, point earlier links that named it by number (or CNR) at it."""
    conds = []
    if case.case_no_text:
        conds.append(CaseLink.to_case_no_text == case.case_no_text)
    if case.cnr:
        conds.append(CaseLink.to_cnr == case.cnr)
    for cond in conds:
        session.execute(
            update(CaseLink).where(cond, CaseLink.to_case_id.is_(None)).values(to_case_id=case.id)
        )


def refresh_search_vector(session: Session, case_id: uuid.UUID) -> None:
    session.execute(
        text(
            """
            UPDATE cases c SET search_vector =
                setweight(to_tsvector('simple', coalesce(c.cnr, '') || ' ' || coalesce(c.case_no_text, '') || ' ' ||
                          coalesce(c.filing_no_text, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(c.petitioner_summary, '') || ' ' ||
                          coalesce(c.respondent_summary, '')), 'B') ||
                setweight(to_tsvector('simple', coalesce(c.pet_advocate, '') || ' ' || coalesce(c.res_advocate, '') ||
                          ' ' || coalesce((SELECT string_agg(p.name, ' ') FROM case_parties p WHERE p.case_id = c.id), '') ||
                          ' ' || coalesce((SELECT string_agg(a.name, ' ') FROM case_advocates a WHERE a.case_id = c.id), '')),
                          'C')
            WHERE c.id = :id
            """
        ),
        {"id": case_id},
    )


def record_next_date(
    session: Session,
    case: Case,
    next_date: date | None,
    source: NextDateSource,
    *,
    order_id: uuid.UUID | None = None,
    confidence: float | None = None,
    needs_review: bool = False,
    note: str | None = None,
    ref_office: str = SYSTEM_OFFICE,
    created_by: uuid.UUID | None = None,
) -> bool:
    """Upserts a next-date fact. Returns True when it is new. A manual entry gets a reference number (`NXT`)
    from the reviewer's office."""
    if not next_date:
        return False
    ref_no = None
    if source == NextDateSource.MANUAL:
        exists_ = session.scalar(
            select(NextDate.id).where(
                NextDate.case_id == case.id,
                NextDate.next_date == next_date,
                NextDate.source == source,
                NextDate.order_id.is_(None) if order_id is None else NextDate.order_id == order_id,
            )
        )
        if exists_:
            return False
        ref_no = allocate_ref_no(session, ref_office, RecordType.NXT)
    stmt = (
        insert(NextDate)
        .values(
            ref_no=ref_no,
            created_by=created_by,
            case_id=case.id,
            next_date=next_date,
            source=source,
            order_id=order_id,
            confidence=confidence,
            needs_review=needs_review,
            review_status=ReviewStatus.PENDING if needs_review else ReviewStatus.NONE,
            note=note,
        )
        .on_conflict_do_nothing(index_elements=["case_id", "next_date", "source", "order_id"])
    )
    created = bool(session.execute(stmt).rowcount)
    if created:
        events.emit(
            session,
            EventType.NEXT_DATE_EXTRACTED,
            f"next_date:{case.id}:{next_date}:{source.value}:{order_id or ''}",
            case_id=case.id,
            payload={
                "next_date": next_date.isoformat(),
                "source": source.value,
                "needs_review": needs_review,
            },
        )
    return created


# ------------------------------------------------------------------------------------------ court records
def _sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _snapshot(session: Session, case: Case, source: SnapshotSource, payload: dict[str, Any]) -> bool:
    stmt = (
        insert(CaseSnapshot)
        .values(
            case_id=case.id,
            source=source,
            fetched_at=now_utc(),
            payload_sha256=_sha(payload),
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["case_id", "payload_sha256"])
    )
    return bool(session.execute(stmt).rowcount)


def _diff_events(
    session: Session,
    case: Case,
    *,
    status: str,
    next_date: date | None,
    purpose: str | None,
    disposal_date: date | None,
    source: str,
) -> None:
    new_status = CaseStatus(status) if status in ("pending", "disposed") else None
    if new_status and case.status != CaseStatus.UNKNOWN and case.status != new_status:
        events.emit(
            session,
            EventType.STATUS_CHANGED,
            f"status:{case.id}:{new_status.value}:{disposal_date or ''}",
            case_id=case.id,
            payload={
                "from": case.status.value,
                "to": new_status.value,
                "disposal_date": str(disposal_date or ""),
                "source": source,
            },
        )
    if next_date and case.next_hearing_date != next_date:
        events.emit(
            session,
            EventType.HEARING_DATE_CHANGED,
            f"next_hearing:{case.id}:{next_date}",
            case_id=case.id,
            payload={
                "from": str(case.next_hearing_date or ""),
                "to": next_date.isoformat(),
                "purpose": purpose,
                "source": source,
            },
        )


def apply_case_record(session: Session, case: Case, rec: CaseRecord) -> dict[str, int]:
    """Applies a full CNR record. Idempotent: an unchanged payload creates nothing new."""
    counts = {"new_orders": 0, "new_hearings": 0, "changed": 0}
    changed = _snapshot(session, case, SnapshotSource.CNR_API, rec.raw)
    case.last_full_refresh_at = now_utc()
    if not changed and case.cnr:
        return counts
    counts["changed"] = 1
    _diff_events(
        session,
        case,
        status=rec.status,
        next_date=rec.next_hearing_date,
        purpose=rec.next_purpose,
        disposal_date=rec.disposal_date,
        source="cnr_api",
    )

    if rec.cnr and not case.cnr:
        case.cnr, case.is_provisional = rec.cnr, False
    court = session.get(Court, case.court_id)
    if rec.case_type_text and rec.reg_no and rec.reg_year:
        case.case_type_text, case.reg_no, case.reg_year = rec.case_type_text.upper(), rec.reg_no, rec.reg_year
        case.case_no_text = f"{case.case_type_text}/{rec.reg_no}/{rec.reg_year}"
        ct = case_type_for(session, court.id, case.case_type_text) if court else None
        case.case_type_id = ct.id if ct else case.case_type_id
    for attr in (
        "filing_no_text",
        "filing_date",
        "registration_date",
        "disposal_date",
        "disposal_nature",
        "next_purpose",
        "last_hearing_date",
        "coram",
        "category",
        "judicial_branch",
        "petitioner_summary",
        "respondent_summary",
        "pet_advocate",
        "res_advocate",
    ):
        val = getattr(rec, attr)
        if val is not None:
            setattr(case, attr, val)
    if rec.status in ("pending", "disposed"):
        case.status = CaseStatus(rec.status)
    if rec.next_hearing_date:
        case.next_hearing_date = rec.next_hearing_date
    case.raw = rec.raw

    if rec.parties:
        session.query(CaseParty).filter(CaseParty.case_id == case.id).delete()
        seen: set[tuple[str, int]] = set()
        for p in rec.parties:
            key = (p.role, p.party_no)
            if key in seen:
                continue
            seen.add(key)
            session.add(
                CaseParty(
                    case_id=case.id,
                    role=PartyRole(p.role),
                    party_no=p.party_no,
                    name=p.name,
                    name_normalised=normalise_name(p.name),
                    address=p.address,
                )
            )
    for side, text_ in (
        (AdvocateSide.PETITIONER, rec.pet_advocate),
        (AdvocateSide.RESPONDENT, rec.res_advocate),
    ):
        if text_:
            add_advocates(session, case, side, [text_])

    for h in rec.hearings:
        d = parse_date(h.get("business_date") or h.get("hearing_date") or h.get("date"))
        if not d:
            continue
        stmt = (
            insert(CaseHearing)
            .values(
                case_id=case.id,
                business_date=d,
                purpose=str(h.get("purpose") or h.get("purpose_name") or "")[:300],
                bench_text=h.get("judge_name") or h.get("bench") or None,
                next_date=parse_date(h.get("next_date")),
                source=HearingSource.CNR_HISTORY,
                raw=h,
            )
            .on_conflict_do_nothing(index_elements=["case_id", "business_date", "purpose"])
        )
        counts["new_hearings"] += session.execute(stmt).rowcount or 0

    for a in rec.acts:
        if a.get("act"):
            session.execute(
                insert(CaseAct)
                .values(
                    case_id=case.id,
                    act_name_as_listed=str(a["act"])[:300],
                    section=str(a.get("section") or "")[:200],
                )
                .on_conflict_do_nothing(index_elements=["case_id", "act_name_as_listed", "section"])
            )

    for o in rec.orders:
        if not o.order_date or not o.order_no:
            continue
        kind = (
            OrderKind.FINAL
            if o.kind == "final"
            else OrderKind.JUDGMENT
            if o.kind == "judgment"
            else OrderKind.INTERIM
        )
        stmt = (
            insert(Order)
            .values(
                case_id=case.id,
                order_no=o.order_no,
                order_date=o.order_date,
                kind=kind,
                download_status=DownloadStatus.PENDING,
                raw=o.raw,
            )
            .on_conflict_do_nothing(index_elements=["case_id", "order_no", "order_date"])
            .returning(Order.id)
        )
        oid = session.execute(stmt).scalar_one_or_none()
        if oid:
            counts["new_orders"] += 1
            events.emit(
                session,
                EventType.ORDER_RECEIVED,
                f"order:{case.id}:{o.order_no}:{o.order_date}",
                case_id=case.id,
                payload={
                    "order_id": str(oid),
                    "order_no": o.order_no,
                    "order_date": o.order_date.isoformat(),
                    "kind": kind.value,
                },
            )

    for no in rec.linked_case_nos:
        add_link(session, case, no, LinkKind.CONNECTED, LinkSource.CNR_API)
    for main_cnr in rec.linked_cnrs:
        if main_cnr != case.cnr:
            target = get_by_cnr(session, main_cnr)
            add_link(
                session,
                case,
                target.case_no_text if target and target.case_no_text else main_cnr,
                LinkKind.MAIN_MATTER,
                LinkSource.CNR_API,
                to_cnr=main_cnr,
            )

    record_next_date(session, case, rec.next_hearing_date, NextDateSource.CURRENT_STATUS)
    session.flush()
    link_pending_targets(session, case)
    refresh_search_vector(session, case.id)
    return counts


def apply_status_record(session: Session, case: Case, st: StatusRecord) -> bool:
    """Applies a Current Status result. Returns True when anything changed."""
    case.last_status_refresh_at = now_utc()
    if not _snapshot(session, case, SnapshotSource.CURRENT_STATUS, st.raw):
        return False
    _diff_events(
        session,
        case,
        status=st.status,
        next_date=st.next_hearing_date,
        purpose=st.next_purpose,
        disposal_date=st.disposal_date,
        source="current_status",
    )
    if st.status in ("pending", "disposed"):
        case.status = CaseStatus(st.status)
    for attr in (
        "next_hearing_date",
        "next_purpose",
        "last_hearing_date",
        "disposal_date",
        "disposal_nature",
    ):
        val = getattr(st, attr)
        if val is not None:
            setattr(case, attr, val)
    record_next_date(session, case, st.next_hearing_date, NextDateSource.CURRENT_STATUS)
    return True
