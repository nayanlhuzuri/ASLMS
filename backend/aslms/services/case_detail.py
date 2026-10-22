"""The case detail (design `cases-api`, decisions 7, 8, 11, 15): one overview and one call per heavy tab.
Every function starts with `visibility.require_visible` (→ 404 "no such case" when the caller may not see
the case); linked-case summaries carry `visible` from the same rule. Read-only: no audit row, no event. The
raw payloads (`case_snapshots`, `napix_responses`) are not exposed here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert
from aslms.domain.cases import (
    Case,
    CaseAct,
    CaseAdvocate,
    CaseApplication,
    CaseHearing,
    CaseLink,
    CaseLowerCourt,
    CaseObjection,
    CaseParty,
    CaseTransfer,
    CaseWritInfo,
)
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.courts import Bench, Court
from aslms.domain.documents import Document, Order
from aslms.domain.events import Event
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import EventType, Permission, RefEventType
from aslms.domain.workflow import CaseNote
from aslms.services import access, inbox, stages, workflow_actions
from aslms.services.visibility import (
    alert_document_condition,
    claim_departments,
    departments,
    document_visible_condition,
    never_owned,
    require_visible,
    visible_case_condition,
)

MAX_GRAPH_NODES = 200

# the columns of `cases` the overview prints, grouped (decision 7); `raw` and `search_vector` stay out
IDENTITY = (
    "cnr",
    "court_est_name",
    "case_type_id",
    "case_type_text",
    "reg_no",
    "reg_year",
    "case_no_text",
    "filing_case_type_id",
    "filing_case_type_text",
    "filing_no",
    "filing_year",
    "filing_no_text",
    "filing_date",
    "registration_date",
    "date_first_list",
)
STATUS = (
    "status",
    "disposal_date",
    "disposal_nature",
    "disposal_type",
    "short_order",
    "date_filing_disp",
    "reason_for_rej",
    "date_judgement_pronounced",
    "date_judgement_reserved",
    "goshwara_no",
    "next_hearing_date",
    "next_purpose",
    "last_hearing_date",
)
CLASSIFICATION = (
    "bench_id",
    "napix_bench_id",
    "bench_name",
    "bench_type_code",
    "coram",
    "coram_designation",
    "judicial_branch",
    "category",
    "category_code",
    "sub_category",
)
PLACE = (
    "state_id",
    "district_id",
    "state_name_as_listed",
    "district_name_as_listed",
    "filing_state_code",
    "filing_district_code",
    "fir_no",
    "fir_year",
    "police_station",
    "police_st_code",
    "uniform_code",
    "main_matter_text",
)
PARTIES_AS_PRINTED = ("petitioner_summary", "respondent_summary", "pet_advocate", "res_advocate")
PORTAL = (
    "is_provisional",
    "is_tracked",
    "first_seen_source",
    "last_full_refresh_at",
    "last_status_refresh_at",
    "dossier_stale",
    "merged_into_case_id",
    "closed_at",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
)

# decision 15: the event types the timeline shows now; documents, notes and alerts join with their own
# visibility (custody-workflow decision 20: `custody_moved` and `stage_set` for everyone who sees the case,
# `note_added` only when the note is visible to the caller)
COURT_EVENTS = (
    EventType.CASE_CREATED,
    EventType.CASE_UPDATED,
    EventType.CASE_DISPOSED,
    EventType.CASE_LINKED,
    EventType.LISTED,
    EventType.LISTED_SUPPLEMENTARY,
    EventType.NEXT_DATE_EXTRACTED,
    EventType.NEXT_DATE_CHANGED,
    EventType.STATUS_CHANGED,
    EventType.ORDER_FOUND,
    EventType.ORDER_STORED,
)
OWNERSHIP_EVENTS = (
    EventType.CLAIMED,
    EventType.ALLOTTED,
    EventType.CASE_TAKEN_OVER,
    EventType.TRANSFER_REQUESTED,
    EventType.TRANSFER_DECIDED,
    EventType.OWNERSHIP_RELEASED,
    EventType.CUSTODY_MOVED,
    EventType.STAGE_SET,
    EventType.NEXT_DATE_REVIEWED,  # design next-date-extraction, decision 14: shown to every reader of the case
    EventType.NEXT_DATE_ENTERED,
)
# shown to the department named in the payload (`office_code`, `from_office_code`, `to_office_code`) and to
# State-wide readers; `alert_raised` (design alerts-notifications, decision 15) carries the office addressed
# and, for a `new_document` alert, is shown only with the document (`_alert_events_rule`)
DEPARTMENT_EVENTS = (
    EventType.RECOMMENDATION_MADE,
    EventType.DISMISSED,
    EventType.SUGGESTED_ELSEWHERE,
    EventType.ALERT_RAISED,
    EventType.RECOMMENDATION_CLOSED,  # design ownership-refinements: to the closed department and State-wide readers
)


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") and not isinstance(v, bool | int | float | str) else v


def _group(case: Case, names: tuple[str, ...]) -> dict[str, Any]:
    return {n: _value(getattr(case, n)) for n in names}


def _count(session: Session, stmt: Select) -> int:
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


def _page(session: Session, stmt: Select, limit: int | None, offset: int | None) -> tuple[list, int]:
    limit, offset = inbox.clamp(limit, offset)
    total = _count(session, stmt)
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    return list(rows), total


# ------------------------------------------------------------------------------------------------ overview


def party_out(p: CaseParty) -> dict[str, Any]:
    return {
        "role": _value(p.role),
        "party_no": p.party_no,
        "name": p.name,
        "address": p.address,
        "has_legal_heir": p.has_legal_heir,
        "is_current": p.is_current,
    }


def advocate_out(a: CaseAdvocate) -> dict[str, Any]:
    return {
        "side": _value(a.side),
        "name_as_listed": a.name_as_listed,
        "counsel_code": a.counsel_code,
        "bar_reg_no": a.bar_reg_no,
        "is_current": a.is_current,
    }


def _parties(session: Session, case: Case, *, include_former: bool) -> tuple[list[dict], list[dict]]:
    pq = select(CaseParty).where(CaseParty.case_id == case.id).order_by(CaseParty.role, CaseParty.party_no)
    aq = (
        select(CaseAdvocate)
        .where(CaseAdvocate.case_id == case.id)
        .order_by(CaseAdvocate.side, CaseAdvocate.name_as_listed)
    )
    if not include_former:
        pq = pq.where(CaseParty.is_current.is_(True))
        aq = aq.where(CaseAdvocate.is_current.is_(True))
    return (
        [party_out(p) for p in session.scalars(pq).all()],
        [advocate_out(a) for a in session.scalars(aq).all()],
    )


def _ownership(session: Session, case: Case) -> dict[str, Any]:
    rows = session.scalars(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case.id, CaseOwnership.status == OwnershipStatus.ACTIVE
        )
    ).all()
    primary = next((r for r in rows if OwnershipRole(r.role) == OwnershipRole.PRIMARY), None)
    out: dict[str, Any] = {"primary": None, "watchers": []}
    if primary is not None:
        office = session.get(Office, primary.office_id)
        unit = session.get(Office, primary.unit_office_id) if primary.unit_office_id else None
        officer = session.get(User, primary.officer_user_id) if primary.officer_user_id else None
        out["primary"] = {
            "office_code": office.code if office else None,
            "office_name": office.name if office else None,
            "unit": {"code": unit.code, "name": unit.name} if unit else None,
            "officer": {"id": officer.id, "full_name": officer.full_name} if officer else None,
            "claimed_at": primary.claimed_at,
        }
    watcher_ids = [r.office_id for r in rows if OwnershipRole(r.role) == OwnershipRole.WATCHER]
    if watcher_ids:
        out["watchers"] = sorted(session.scalars(select(Office.code).where(Office.id.in_(watcher_ids))).all())
    return out


def _custody(session: Session, user: User, case: Case, basis: list[str]) -> dict[str, Any] | None:
    """Design custody-workflow, decision 25: the custody card (remark per decision 11)."""
    from aslms.services import custody

    return custody.card(session, user, case, bases=basis)


def _claimable(session: Session, user: User, case: Case) -> bool:
    if not claim_departments(session, user):
        return False
    return bool(session.scalar(select(never_owned()).select_from(Case).where(Case.id == case.id)))


def _counts(session: Session, user: User, case: Case) -> dict[str, int]:
    from aslms.services import notes
    from aslms.services.documents import visible_count

    def n(stmt: Select) -> int:
        return int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    return {
        "hearings": n(select(CaseHearing.id).where(CaseHearing.case_id == case.id)),
        "orders": n(select(Order.id).where(Order.case_id == case.id)),
        "listings": n(select(CauselistEntry.id).where(CauselistEntry.case_id == case.id)),
        "links": n(_links_stmt(case)),
        "documents": visible_count(session, user, case),  # visible to the caller, not archived
        "timeline": _count(session, _timeline_stmt(session, None, case, unrestricted=True)),
        "notes": notes.visible_count(session, user, case),  # visible permanent notes (custody-workflow)
        "my_drafts": notes.my_draft_count(session, user, case),
    }


def overview(session: Session, user: User, case: Case) -> dict[str, Any]:
    basis = require_visible(session, user, case)
    court = session.get(Court, case.court_id)
    bench = session.get(Bench, case.bench_id) if case.bench_id else None
    parties, advocates = _parties(session, case, include_former=False)
    merged_into = session.get(Case, case.merged_into_case_id) if case.merged_into_case_id else None
    return {
        "id": case.id,
        "ref_no": case.ref_no,
        "identity": _group(case, IDENTITY),
        "status": _group(case, STATUS),
        "classification": _group(case, CLASSIFICATION),
        "place": _group(case, PLACE),
        "parties_as_printed": _group(case, PARTIES_AS_PRINTED),
        "portal": _group(case, PORTAL),
        "court": {"est_code": court.est_code, "name": court.name} if court else None,
        "bench": (
            {"bench_id": bench.bench_id, "judge_names": bench.judge_names, "bench_name": bench.bench_name}
            if bench
            else None
        ),
        "parties": parties,
        "advocates": advocates,
        "acts": [
            {
                "act_name_as_listed": a.act_name_as_listed,
                "national_act_code": a.national_act_code,
                "section": a.section,
            }
            for a in session.scalars(
                select(CaseAct).where(CaseAct.case_id == case.id).order_by(CaseAct.act_name_as_listed)
            ).all()
        ],
        "lower_courts": [
            {
                "level": _value(lc.level),
                "court_name": lc.court_name,
                "case_no_text": lc.case_no_text,
                "decision_date": lc.decision_date,
            }
            for lc in session.scalars(select(CaseLowerCourt).where(CaseLowerCourt.case_id == case.id)).all()
        ],
        "applications": [
            {
                "ia_number": a.ia_number,
                "party_name": a.party_name,
                "status": a.status,
                "filing_date": a.filing_date,
            }
            for a in session.scalars(
                select(CaseApplication)
                .where(CaseApplication.case_id == case.id)
                .order_by(CaseApplication.ia_number)
            ).all()
        ],
        "objections": [
            {
                "seq": o.seq,
                "objection": o.objection,
                "scrutiny_date": o.scrutiny_date,
                "compliance_by_date": o.compliance_by_date,
                "receipt_date": o.receipt_date,
            }
            for o in session.scalars(
                select(CaseObjection)
                .where(CaseObjection.case_id == case.id)
                .order_by(CaseObjection.scrutiny_date, CaseObjection.seq)
            ).all()
        ],
        "court_transfers": [
            {
                "transfer_date": t.transfer_date,
                "from_court_text": t.from_court_text,
                "to_court_text": t.to_court_text,
            }
            for t in session.scalars(
                select(CaseTransfer)
                .where(CaseTransfer.case_id == case.id)
                .order_by(CaseTransfer.transfer_date)
            ).all()
        ],
        "writ_info": [
            {"appellate_case_number": w.appellate_case_number, "appellate_authority": w.appellate_authority}
            for w in session.scalars(select(CaseWritInfo).where(CaseWritInfo.case_id == case.id)).all()
        ],
        "ownership": _ownership(session, case),
        "custody": _custody(session, user, case, basis),
        "stage": stages.current_block(session, case),
        "access_basis": basis,
        "claimable": _claimable(session, user, case),
        "dossier_status": "fetched" if case.last_full_refresh_at is not None else "not_fetched",
        "merged_into_ref_no": merged_into.ref_no if merged_into else None,
        "counts": _counts(session, user, case),
        "workflow": workflow_actions.available(session, user, case),
        **_next_date_block(session, user, case),
    }


def _next_date_block(session: Session, user: User, case: Case) -> dict[str, Any]:
    """Design next-date-extraction, decision 18: the next date from orders (decision 9's row with its order and
    phrase) and the case's review items the caller may act on."""
    from aslms.services import next_dates

    row = next_dates.effective_for_case(session, case)
    return {
        "next_date_from_orders": next_dates.next_date_out(session, row) if row is not None else None,
        "next_dates_to_review": next_dates.to_review_for_case(session, user, case),
    }


# ------------------------------------------------------------------------------------------------ tabs


def parties(session: Session, user: User, case: Case, *, include_former: bool = False) -> dict[str, Any]:
    require_visible(session, user, case)
    p, a = _parties(session, case, include_former=include_former)
    return {"parties": p, "advocates": a}


def hearings(session: Session, user: User, case: Case, *, limit=None, offset=None) -> Page:
    require_visible(session, user, case)
    stmt = (
        select(CaseHearing)
        .where(CaseHearing.case_id == case.id)
        .order_by(CaseHearing.business_date.desc().nulls_last(), CaseHearing.purpose)
    )
    rows, total = _page(session, stmt, limit, offset)
    return Page(
        [
            {
                "business_date": h.business_date,
                "hearing_date": h.hearing_date,
                "purpose": h.purpose or None,
                "bench_text": h.bench_text,
                "judge_designation": h.judge_designation,
                "causelist_type": h.causelist_type,
                "next_date": h.hearing_date,
                "business_text": h.business_text,
                "short_order_text": h.short_order_text,
                "case_number_text": h.case_number_text,
                "source": _value(h.source),
            }
            for h in rows
        ],
        total,
    )


def orders(session: Session, user: User, case: Case, *, limit=None, offset=None) -> Page:
    require_visible(session, user, case)
    stmt = (
        select(Order, Document)
        .outerjoin(Document, Document.id == Order.document_id)
        .where(Order.case_id == case.id)
        .order_by(Order.order_date.desc(), Order.order_no.desc())
    )
    limit, offset = inbox.clamp(limit, offset)
    total = _count(session, stmt)
    rows = session.execute(stmt.limit(limit).offset(offset)).all()
    return Page(
        [
            {
                "id": o.id,
                "order_no": o.order_no,
                "order_date": o.order_date,
                "kind": _value(o.kind),
                "order_details": o.order_details,
                "order_judge_name": o.order_judge_name,
                "date_judgement_pronounced": o.date_judgement_pronounced,
                "date_judgement_reserved": o.date_judgement_reserved,
                "is_reportable": o.is_reportable,
                "download_status": _value(o.download_status),
                "document_id": o.document_id,
                "text_status": _value(d.text_status) if d else None,
                "page_count": d.page_count if d else None,
                "next_date_status": _value(o.next_date_status),
                "next_date_found": o.next_date_found,
                "next_date_rule": o.next_date_rule,
                "next_date_phrase": o.next_date_phrase,
            }
            for o, d in rows
        ],
        total,
    )


def listings(session: Session, user: User, case: Case, *, limit=None, offset=None) -> Page:
    require_visible(session, user, case)
    stmt = (
        select(CauselistEntry, Causelist)
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(CauselistEntry.case_id == case.id)
        .order_by(Causelist.list_date.desc(), CauselistEntry.sr_no)
    )
    limit, offset = inbox.clamp(limit, offset)
    total = _count(session, stmt)
    rows = session.execute(stmt.limit(limit).offset(offset)).all()
    return Page(
        [
            {
                "list_date": cl.list_date,
                "list_type": _value(cl.list_type),
                "bench_label": cl.bench_label or e.bench_text,
                "bench_id": cl.bench_id,
                "court_no": e.court_no,
                "sr_no": e.sr_no,
                "printed_sr": e.printed_sr_no,
                "section": e.section,
                "is_connected": e.is_connected,
                "counsel_codes": list(e.counsel_codes or []),
                "remarks": e.remarks,
                "source": _value(e.source),
            }
            for e, cl in rows
        ],
        total,
    )


# ------------------------------------------------------------------------------------------------ links


def _links_stmt(case: Case) -> Select:
    incoming = [CaseLink.to_case_id == case.id]
    if case.cnr:
        incoming.append(CaseLink.to_cnr == case.cnr)
    return select(CaseLink).where(or_(CaseLink.from_case_id == case.id, *incoming))


def _other_case_ids(links: list[CaseLink], case: Case) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for k in links:
        if k.from_case_id != case.id:
            ids.add(k.from_case_id)
        elif k.to_case_id is not None:
            ids.add(k.to_case_id)
    return ids


def _resolve_targets(session: Session, links: list[CaseLink]) -> dict[uuid.UUID, uuid.UUID]:
    """Outgoing links without `to_case_id` whose `to_cnr` is a held case: link id → case id."""
    cnrs = {k.to_cnr for k in links if k.to_case_id is None and k.to_cnr}
    if not cnrs:
        return {}
    by_cnr = {c.cnr: c.id for c in session.scalars(select(Case).where(Case.cnr.in_(cnrs))).all()}
    return {k.id: by_cnr[k.to_cnr] for k in links if k.to_case_id is None and k.to_cnr in by_cnr}


def _summaries_with_visibility(
    session: Session, user: User, ids: set[uuid.UUID]
) -> tuple[dict[uuid.UUID, dict], set[uuid.UUID]]:
    if not ids:
        return {}, set()
    rows = session.execute(
        select(Case, visible_case_condition(session, user).label("v")).where(Case.id.in_(ids))
    ).all()
    cases = [c for c, _ in rows]
    visible = {c.id for c, v in rows if v}
    return inbox.summaries(session, cases), visible


def links(session: Session, user: User, case: Case) -> dict[str, Any]:
    require_visible(session, user, case)
    rows = list(session.scalars(_links_stmt(case)).all())
    resolved = _resolve_targets(session, rows)
    other: set[uuid.UUID] = set()
    for k in rows:
        if k.from_case_id != case.id:
            other.add(k.from_case_id)
        else:
            target = k.to_case_id or resolved.get(k.id)
            if target is not None:
                other.add(target)
    summ, visible = _summaries_with_visibility(session, user, other)
    items = []
    for k in rows:
        if k.from_case_id == case.id:
            direction, target = "out", k.to_case_id or resolved.get(k.id)
        else:
            direction, target = "in", k.from_case_id
        items.append(
            {
                "direction": direction,
                "kind": _value(k.kind),
                "case_no_text": k.to_case_no_text or None,
                "cnr": k.to_cnr,
                "filing_number_text": k.filing_number_text,
                "source": _value(k.source),
                "case": summ.get(target) if target else None,
                "visible": target in visible if target else False,
            }
        )
    return {"items": items}


def link_graph(session: Session, user: User, case: Case, *, depth: int = 2) -> dict[str, Any]:
    """Breadth-first over both link directions, `depth` levels (1–3), at most 200 nodes (`truncated`).
    Unresolved links are leaf nodes `no:<printed number>`; held cases are summaries with `visible`."""
    require_visible(session, user, case)
    depth = max(1, min(int(depth or 2), 3))
    root = str(case.id)
    nodes: dict[str, dict[str, Any]] = {root: {"key": root, "case_id": case.id, "label": case.case_no_text}}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    visited: set[uuid.UUID] = {case.id}
    frontier: list[Case] = [case]
    truncated = False
    for _level in range(depth):
        next_frontier: list[Case] = []
        for current in frontier:
            rows = list(session.scalars(_links_stmt(current)).all())
            resolved = _resolve_targets(session, rows)
            for k in rows:
                if k.from_case_id == current.id:
                    other_id = k.to_case_id or resolved.get(k.id)
                    src = str(current.id)
                    dst = str(other_id) if other_id else f"no:{k.to_case_no_text or k.to_cnr or k.id}"
                    other_key, label = dst, (k.to_case_no_text or k.to_cnr or None)
                else:
                    other_id = k.from_case_id
                    src, dst = str(other_id), str(current.id)
                    other_key, label = src, None
                if other_key not in nodes:
                    if len(nodes) >= MAX_GRAPH_NODES:
                        truncated = True
                        continue
                    nodes[other_key] = {"key": other_key, "case_id": other_id, "label": label}
                edge = (src, dst, _value(k.kind))
                if edge not in seen:
                    seen.add(edge)
                    edges.append({"from": src, "to": dst, "kind": edge[2]})
                if other_id is not None and other_id not in visited:
                    visited.add(other_id)
                    nxt = session.get(Case, other_id)
                    if nxt is not None:
                        next_frontier.append(nxt)
        frontier = next_frontier
        if truncated or not frontier:
            break
    ids = {n["case_id"] for n in nodes.values() if n["case_id"] is not None}
    summ, visible = _summaries_with_visibility(session, user, ids)
    out_nodes = [
        {
            "key": n["key"],
            "case": summ.get(n["case_id"]) if n["case_id"] else None,
            "case_no_text": (summ[n["case_id"]]["case_no_text"] if n["case_id"] in summ else n["label"]),
            "visible": n["case_id"] in visible if n["case_id"] else False,
        }
        for n in nodes.values()
    ]
    return {"nodes": out_nodes, "edges": edges, "truncated": truncated}


# ------------------------------------------------------------------------------------------------ timeline


def _document_events(session: Session, user: User | None, *, unrestricted: bool):
    """`document_uploaded` rows, shown only when the document is visible to the caller (design
    documents-uploads, decision 12); every row when counting unrestricted."""
    is_doc = Event.type == EventType.DOCUMENT_UPLOADED
    if unrestricted:
        return is_doc
    if user is None:
        return literal(False)
    visible_doc = exists(
        select(literal(1))
        .select_from(Document)
        .where(
            Document.id == cast(Event.payload["document_id"].astext, PG_UUID(as_uuid=True)),
            document_visible_condition(session, user),
        )
    )
    return is_doc & visible_doc


def _note_events(session: Session, user: User | None, *, unrestricted: bool):
    """`note_added` rows, shown only when the note is visible to the caller (custody-workflow, decision 20)."""
    is_note = Event.type == EventType.NOTE_ADDED
    if unrestricted:
        return is_note
    if user is None:
        return literal(False)
    from aslms.services.visibility import note_visible_condition

    visible_note = exists(
        select(literal(1))
        .select_from(CaseNote)
        .where(
            CaseNote.id == cast(Event.payload["note_id"].astext, PG_UUID(as_uuid=True)),
            note_visible_condition(session, user),
        )
    )
    return is_note & visible_note


def _alert_events_rule(session: Session, user: User | None, *, unrestricted: bool):
    """ANDed onto the department rule: an `alert_raised` row for a `new_document` alert is shown only when the
    document the alert names is visible to the caller (design alerts-notifications, deviation 12); every
    other row passes; every row when counting unrestricted."""
    if unrestricted:
        return literal(True)
    if user is None:
        return literal(False)
    visible_alert = exists(
        select(literal(1))
        .select_from(Alert)
        .where(
            Alert.id == cast(Event.payload["alert_id"].astext, PG_UUID(as_uuid=True)),
            alert_document_condition(session, user),
        )
    )
    return or_(Event.type != EventType.ALERT_RAISED, visible_alert)


def _timeline_stmt(session: Session, user: User | None, case: Case, *, unrestricted: bool = False) -> Select:
    types = list(COURT_EVENTS + OWNERSHIP_EVENTS)
    stmt = select(Event).where(Event.case_id == case.id)
    docs = or_(
        _document_events(session, user, unrestricted=unrestricted),
        _note_events(session, user, unrestricted=unrestricted),
    )
    dept_rows = Event.type.in_(list(DEPARTMENT_EVENTS)) & _alert_events_rule(
        session, user, unrestricted=unrestricted
    )
    if unrestricted or (user is not None and access.has(session, user, Permission.CASES_VIEW_ALL)):
        return stmt.where(or_(Event.type.in_(types), dept_rows, docs))
    codes = [d.code for d in departments(session, user)] if user is not None else []
    if not codes:
        return stmt.where(or_(Event.type.in_(types), docs))
    mine = or_(
        Event.payload["office_code"].astext.in_(codes),
        Event.payload["from_office_code"].astext.in_(codes),
        Event.payload["to_office_code"].astext.in_(codes),
    )
    return stmt.where(or_(Event.type.in_(types), dept_rows & mine, docs))


def timeline(session: Session, user: User, case: Case, *, limit=None, offset=None) -> Page:
    require_visible(session, user, case)
    stmt = _timeline_stmt(session, user, case).order_by(Event.occurred_at.desc(), Event.id.desc())
    rows, total = _page(session, stmt, limit, offset)
    labels = (
        {
            r.code: r
            for r in session.scalars(
                select(RefEventType).where(RefEventType.code.in_({_value(e.type) for e in rows}))
            ).all()
        }
        if rows
        else {}
    )
    actor_ids = {e.actor_user_id for e in rows if e.actor_user_id}
    actors = (
        {u.id: u.full_name for u in session.scalars(select(User).where(User.id.in_(actor_ids))).all()}
        if actor_ids
        else {}
    )
    items = []
    for e in rows:
        code = _value(e.type)
        ref = labels.get(code)
        items.append(
            {
                "type": code,
                "label": (ref.timeline_label or ref.label) if ref else code,
                "icon_key": ref.icon_key if ref else None,
                "occurred_at": e.occurred_at,
                "actor_name": actors.get(e.actor_user_id) if e.actor_user_id else None,
                "payload": e.payload or {},
            }
        )
    return Page(items, total)
