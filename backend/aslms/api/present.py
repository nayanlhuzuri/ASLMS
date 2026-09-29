"""Builds API response models from ORM rows. Tracking cards are safe for every user; details are built only
after the router has checked scope."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas as S
from aslms.domain.alerts import NextDate
from aslms.domain.cases import Case, CaseAct, CaseAdvocate, CaseParty
from aslms.domain.documents import Order
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import Court
from aslms.services.scope import Principal, case_scope_clause
from aslms.services.search import owner_summary


def cards(db: Session, p: Principal, cases: Iterable[Case]) -> list[S.CaseCard]:
    cases = list(cases)
    ids = [c.id for c in cases]
    owners = owner_summary(db, ids)
    in_scope = (
        set(db.scalars(select(Case.id).where(Case.id.in_(ids), case_scope_clause(p)))) if ids else set()
    )
    courts = {c.id: c.name for c in db.scalars(select(Court))}
    custody = custody_cards(db, ids)
    stages = current_stages(db, ids)
    return [
        S.CaseCard(
            id=c.id,
            ref_no=c.ref_no,
            cnr=c.cnr,
            case_no=c.case_no_text,
            filing_no=c.filing_no_text,
            case_type=c.case_type_text,
            reg_year=c.reg_year,
            status=c.status.value,
            is_provisional=c.is_provisional,
            petitioner=c.petitioner_summary,
            respondent=c.respondent_summary,
            next_hearing_date=c.next_hearing_date,
            next_purpose=c.next_purpose,
            last_hearing_date=c.last_hearing_date,
            disposal_date=c.disposal_date,
            court=courts.get(c.court_id),
            owners=S.Owners(**owners.get(c.id, {})) if c.id in owners else S.Owners(),
            custody=custody.get(c.id),
            stage=stages.get(c.id),
            in_scope=c.id in in_scope,
        )
        for c in cases
    ]


def card(db: Session, p: Principal, case: Case) -> S.CaseCard:
    return cards(db, p, [case])[0]


def office_ref(o: Office | None) -> S.OwnerRef | None:
    return S.OwnerRef(office_id=str(o.id), code=o.code, name=o.name) if o else None


def ownership_rows(db: Session, case_id: uuid.UUID, include_history: bool = False) -> list[S.OwnershipOut]:
    q = select(CaseOwnership).where(CaseOwnership.case_id == case_id)
    if not include_history:
        q = q.where(CaseOwnership.status == OwnershipStatus.ACTIVE)
    out = []
    for own in db.scalars(q.order_by(CaseOwnership.claimed_at)):
        officer = db.get(User, own.officer_user_id) if own.officer_user_id else None
        out.append(
            S.OwnershipOut(
                id=own.id,
                office=office_ref(db.get(Office, own.office_id)),
                role=own.role.value,
                status=own.status.value,
                unit=office_ref(db.get(Office, own.unit_office_id)) if own.unit_office_id else None,
                officer={"id": str(officer.id), "name": officer.full_name, "designation": officer.designation}
                if officer
                else None,
                claimed_at=own.claimed_at,
                claimed_by=own.actor_name,
            )
        )
    return out


def detail(db: Session, p: Principal, case: Case) -> S.CaseDetail:
    base = card(db, p, case).model_dump()
    latest = db.scalar(
        select(Order)
        .where(Order.case_id == case.id)
        .order_by(Order.order_date.desc(), Order.order_no.desc())
        .limit(1)
    )
    return S.CaseDetail(
        **base,
        filing_date=case.filing_date,
        registration_date=case.registration_date,
        disposal_nature=case.disposal_nature,
        coram=case.coram,
        category=case.category,
        judicial_branch=case.judicial_branch,
        pet_advocate=case.pet_advocate,
        res_advocate=case.res_advocate,
        is_tracked=case.is_tracked,
        last_full_refresh_at=case.last_full_refresh_at,
        last_status_refresh_at=case.last_status_refresh_at,
        first_seen_source=case.first_seen_source.value,
        parties=[
            S.PartyOut.model_validate(x)
            for x in db.scalars(
                select(CaseParty)
                .where(CaseParty.case_id == case.id)
                .order_by(CaseParty.role, CaseParty.party_no)
            )
        ],
        advocates=[
            S.AdvocateOut.model_validate(x)
            for x in db.scalars(
                select(CaseAdvocate)
                .where(CaseAdvocate.case_id == case.id)
                .order_by(CaseAdvocate.side, CaseAdvocate.created_at)
            )
        ],
        acts=[
            S.ActOut.model_validate(x) for x in db.scalars(select(CaseAct).where(CaseAct.case_id == case.id))
        ],
        ownership=ownership_rows(db, case.id),
        latest_order=S.OrderOut.model_validate(latest) if latest else None,
        next_dates=[
            S.NextDateOut.model_validate(x)
            for x in db.scalars(
                select(NextDate)
                .where(NextDate.case_id == case.id)
                .order_by(NextDate.next_date.desc())
                .limit(20)
            )
        ],
    )


def custody_cards(db: Session, case_ids: list) -> dict:
    from aslms.core.time import today_ist
    from aslms.domain.workflow import Custody

    out: dict = {}
    if not case_ids:
        return out
    today = today_ist()
    for cur, office in db.execute(
        select(Custody, Office)
        .join(Office, Office.id == Custody.holder_office_id)
        .where(Custody.case_id.in_(case_ids))
    ):
        holder = db.get(User, cur.holder_user_id) if cur.holder_user_id else None
        out[cur.case_id] = S.CustodyOut(
            holder_office=office_ref(office),
            holder_user=holder.full_name if holder else None,
            pending_action=cur.pending_action,
            since=cur.since,
            due_date=cur.due_date,
            days_pending=(today - cur.since.date()).days,
            overdue=bool(cur.due_date and cur.due_date < today),
        )
    return out


def current_stages(db: Session, case_ids: list) -> dict:
    from sqlalchemy import func

    from aslms.domain.workflow import CaseStage

    if not case_ids:
        return {}
    latest = (
        select(CaseStage.case_id, func.max(CaseStage.created_at).label("at"))
        .where(CaseStage.case_id.in_(case_ids))
        .group_by(CaseStage.case_id)
        .subquery()
    )
    return {
        cid: st.value
        for cid, st in db.execute(
            select(CaseStage.case_id, CaseStage.stage).join(
                latest, (latest.c.case_id == CaseStage.case_id) & (latest.c.at == CaseStage.created_at)
            )
        )
    }
