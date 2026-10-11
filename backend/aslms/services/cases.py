"""Cases: creation from a cause-list entry (provisional until the dossier arrives), and `apply_dossier` /
`apply_status`, which write every path of the Search by CNR and Current Status responses to its column
(docs/schema/napix_coverage.md §C) after storing the whole block in `case_snapshots`. Both are idempotent:
the same payload applied twice changes nothing; child rows are keyed by their natural keys, and parties or
advocates that leave the dossier are marked not current, never deleted."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.domain.cases import (
    AdvocateSide,
    Case,
    CaseAct,
    CaseAdvocate,
    CaseApplication,
    CaseHearing,
    CaseLink,
    CaseLowerCourt,
    CaseObjection,
    CaseParty,
    CaseSnapshot,
    CaseStatus,
    CaseTransfer,
    CaseWritInfo,
    FirstSeenSource,
    HearingSource,
    LinkKind,
    LinkSource,
    LowerCourtLevel,
    PartyRole,
    SnapshotSource,
)
from aslms.domain.courts import Bench, CaseType, Court, District, State
from aslms.domain.documents import Order, OrderKind
from aslms.domain.events import Event, EventVisibility
from aslms.domain.reference import EventType
from aslms.parsing.causelist_pdf import split_advocates
from aslms.services.napix_store import payload_sha256
from aslms.services.napix_values import (
    as_bool_yn,
    as_date,
    as_int,
    as_text,
    block_items,
    case_no_text,
    leading_code,
    numbered_values,
)
from aslms.services.refno import allocate_ref_no

ROOT_OFFICE = "GOA"


def _now() -> datetime:
    return datetime.now(UTC)


def normalise_name(name: str) -> str:
    return " ".join(name.upper().replace(".", " ").split())


# ------------------------------------------------------------------------------------------------ lookup / create


def _type_id_for(session: Session, court: Court, case_no: str | None) -> uuid.UUID | None:
    parts = (case_no or "").rsplit("/", 2)
    if len(parts) != 3 or not parts[0].strip():
        return None
    return session.scalar(
        select(CaseType.id).where(CaseType.court_id == court.id, CaseType.short_name == parts[0].strip())
    )


def find_case(session: Session, court: Court, *, cnr: str | None, case_no: str | None) -> Case | None:
    """A case by CNR, else a provisional case (no CNR, not merged) by the case number key: the same compact printed
    number, or the same type, number and year (design `data-load-console`, decision 13)."""
    from aslms.services import case_dedupe

    if cnr:
        found = session.scalar(select(Case).where(Case.cnr == cnr))
        if found is not None:
            return found
    if case_no:
        key = case_dedupe.number_key(
            court_id=court.id, case_no_text=case_no, case_type_id=_type_id_for(session, court, case_no)
        )
        return case_dedupe.find_provisional(session, court.id, key)
    return None


def get_or_create_case(
    session: Session,
    court: Court,
    *,
    cnr: str | None,
    case_no: str | None,
    source: FirstSeenSource,
) -> tuple[Case, bool]:
    """A case by CNR, or a provisional case by its printed number when the list gave no CNR. Never fabricates a
    CNR. Creation takes the advisory lock on (court, compact number) and looks again, so two transactions cannot
    create two rows for one printed number (decision 13). Returns (case, created)."""
    from aslms.services import case_dedupe

    case = find_case(session, court, cnr=cnr, case_no=case_no)
    if case is None and case_no:
        case_dedupe.lock_number(
            session, court.id, case_dedupe.number_key(court_id=court.id, case_no_text=case_no)
        )
        case = find_case(session, court, cnr=cnr, case_no=case_no)
    if case is not None:
        if cnr and case.cnr is None:
            case.cnr, case.is_provisional = cnr, True
        if case_no and not case.case_no_text:
            case.case_no_text = case_no
        return case, False
    case = Case(
        cnr=cnr,
        court_id=court.id,
        case_no_text=case_no,
        ref_no=allocate_ref_no(session, ROOT_OFFICE, "CASE"),
        first_seen_source=source,
        is_provisional=True,
    )
    _fill_from_case_no(case, case_no, session, court)
    session.add(case)
    session.flush()
    emit_event(
        session, EventType.CASE_CREATED, case, {"cnr": cnr, "case_no": case_no, "source": source.value}
    )
    return case, True


def _fill_from_case_no(case: Case, case_no: str | None, session: Session, court: Court) -> None:
    """`WP(C)/4189/2016` → type text, number, year and the case-type row when the short name is known."""
    if not case_no:
        return
    parts = case_no.rsplit("/", 2)
    if len(parts) != 3:
        return
    t, n, y = parts
    case.case_type_text = case.case_type_text or t.strip()
    case.reg_no = case.reg_no or as_int(n)
    case.reg_year = case.reg_year or as_int(y)
    if case.case_type_id is None:
        ct = session.scalar(
            select(CaseType).where(CaseType.court_id == court.id, CaseType.short_name == t.strip())
        )
        if ct is not None:
            case.case_type_id = ct.id


def emit_event(
    session: Session,
    kind: EventType,
    case: Case | None,
    payload: dict[str, Any],
    dedupe: str | None = None,
    *,
    scoped: bool = False,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """One event row, deduplicated by `dedupe_key`. Tracking-card visibility unless `scoped`."""
    key = dedupe or f"{kind.value}:{case.id if case else 'system'}:{payload_sha256(payload)[:16]}"
    exists = session.scalar(select(Event.id).where(Event.dedupe_key == key))
    if exists:
        return
    session.add(
        Event(
            case_id=case.id if case else None,
            type=kind,
            payload=json.loads(json.dumps(payload, default=str)),
            dedupe_key=key[:300],
            actor_user_id=actor_user_id,
            visibility=EventVisibility.SCOPED if scoped else EventVisibility.TRACKING_CARD,
        )
    )


# ------------------------------------------------------------------------------------------------ dossier


@dataclass
class ApplyReport:
    case_id: uuid.UUID
    cnr: str | None
    changed: bool
    snapshot_new: bool
    counts: dict[str, int] = field(default_factory=dict)
    status_changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


def _bench_for(session: Session, court: Court, data: dict[str, Any]) -> Bench | None:
    bid = as_int(data.get("bench_id"))
    if bid is None:
        return None
    bench = session.scalar(select(Bench).where(Bench.court_id == court.id, Bench.bench_id == bid))
    if bench is None:
        bench = Bench(court_id=court.id, bench_id=bid)
        session.add(bench)
    name, btype = as_text(data.get("bench_name"), 100), as_int(data.get("bench_type"))
    if name:
        bench.bench_name = name
    if btype is not None:
        bench.bench_type_code = btype
    coram = as_text(data.get("coram"))
    if coram:
        bench.judge_names = coram
    bench.last_seen = _now()
    session.flush()
    return bench


def _court_for(session: Session, case: Case, data: dict[str, Any]) -> Court:
    est = as_text(data.get("est_code"), 10)
    if est:
        court = session.scalar(select(Court).where(Court.est_code == est))
        if court is not None:
            case.court_id = court.id
            return court
    return session.get(Court, case.court_id)


def apply_core_fields(session: Session, case: Case, data: dict[str, Any], court: Court) -> None:
    """The scalar paths shared by the dossier and Current Status (§C)."""
    case.court_est_name = as_text(data.get("court_est_name"), 200) or case.court_est_name
    type_reg = as_text(data.get("type_name_reg") or data.get("type_name"), 60)
    if type_reg:
        case.case_type_text = type_reg
    ctid = as_int(data.get("case_type_id"))
    if ctid is not None:
        ct = session.scalar(
            select(CaseType).where(CaseType.court_id == court.id, CaseType.case_type_code == ctid)
        )
        if ct is not None:
            case.case_type_id = ct.id
    elif case.case_type_id is None and type_reg:
        ct = session.scalar(
            select(CaseType).where(CaseType.court_id == court.id, CaseType.short_name == type_reg)
        )
        if ct is not None:
            case.case_type_id = ct.id
    reg_no, reg_year = as_int(data.get("reg_no")), as_int(data.get("reg_year"))
    if reg_no is not None:
        case.reg_no = reg_no
    if reg_year is not None:
        case.reg_year = reg_year
    cn = case_no_text(case.case_type_text, case.reg_no, case.reg_year)
    if cn:
        case.case_no_text = cn
    type_fil = as_text(data.get("type_name_fil"), 60)
    if type_fil:
        case.filing_case_type_text = type_fil
        ct = session.scalar(
            select(CaseType).where(CaseType.court_id == court.id, CaseType.short_name == type_fil)
        )
        if ct is not None:
            case.filing_case_type_id = ct.id
    fil_no, fil_year = as_int(data.get("fil_no")), as_int(data.get("fil_year"))
    if fil_no is not None:
        case.filing_no = fil_no
    if fil_year is not None:
        case.filing_year = fil_year
    fn = case_no_text(case.filing_case_type_text or case.case_type_text, case.filing_no, case.filing_year)
    if fn:
        case.filing_no_text = fn
    for src, dst in (
        ("date_of_filing", "filing_date"),
        ("dt_regis", "registration_date"),
        ("date_first_list", "date_first_list"),
        ("date_last_list", "last_hearing_date"),
        ("date_of_decision", "disposal_date"),
        ("date_filing_disp", "date_filing_disp"),
        ("date_judgement_pronounced", "date_judgement_pronounced"),
        ("date_judgement_reserved", "date_judgement_reserved"),
    ):
        if src in data:
            setattr(case, dst, as_date(data.get(src)))
    if "date_next_list" in data:
        case.next_hearing_date = as_date(data.get("date_next_list"))
    if "purpose_name" in data:
        case.next_purpose = as_text(data.get("purpose_name"), 200)
    pend = as_text(data.get("pend_disp"))
    if pend:
        case.status = {"P": CaseStatus.PENDING, "D": CaseStatus.DISPOSED}.get(
            pend.upper()[:1], CaseStatus.UNKNOWN
        )
        if case.status == CaseStatus.DISPOSED and case.closed_at is None:
            case.closed_at = _now()
    for src, dst, lim in (
        ("disposal_type", "disposal_type", 200),
        ("disp_nature", "disposal_nature", 200),
        ("short_order", "short_order", None),
        ("reason_for_rej", "reason_for_rej", None),
        ("goshwara_no", "goshwara_no", 10),
        ("bench_name", "bench_name", 100),
        ("coram", "coram", None),
        ("desgname", "coram_designation", 100),
        ("judicial_branch", "judicial_branch", 200),
        ("fir_no", "fir_no", 40),
        ("police_station", "police_station", 200),
        ("police_st_code", "police_st_code", 20),
        ("uniform_code", "uniform_code", 20),
        ("main_matter", "main_matter_text", 200),
        ("pet_name", "petitioner_summary", None),
        ("res_name", "respondent_summary", None),
        ("pet_adv", "pet_advocate", None),
        ("res_adv", "res_advocate", None),
        ("state_name", "state_name_as_listed", 100),
        ("dist_name", "district_name_as_listed", 100),
    ):
        if src in data:
            setattr(case, dst, as_text(data.get(src), lim))
    if "fir_year" in data:
        case.fir_year = as_int(data.get("fir_year"))
    if "bench_type" in data:
        case.bench_type_code = as_int(data.get("bench_type"))
    bench = _bench_for(session, court, data)
    if bench is not None:
        case.bench_id, case.napix_bench_id = bench.id, bench.bench_id
    cat = data.get("category_details") or {}
    if isinstance(cat, dict):
        if "category" in cat:
            case.category = as_text(cat.get("category"))
            case.category_code = leading_code(cat.get("category"))
        if "sub_category" in cat:
            case.sub_category = as_text(cat.get("sub_category"))
    doc = data.get("document_details") or {}
    if isinstance(doc, dict):
        case.filing_state_code = as_int(doc.get("case_state_code"))
        case.filing_district_code = as_int(doc.get("case_dist_code"))
    state_name = as_text(data.get("state_name"), 100)
    if state_name:
        st = session.scalar(select(State).where(State.name.ilike(state_name)))
        if st is not None:
            case.state_id = st.id
    dist_name = as_text(data.get("dist_name"), 100)
    if dist_name:
        d = session.scalar(
            select(District)
            .where((District.ecourts_name.ilike(dist_name)) | (District.name.ilike(dist_name)))
            .limit(1)
        )
        if d is not None:
            case.district_id = d.id


def _sync_parties(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (p.role, p.party_no): p
        for p in session.scalars(select(CaseParty).where(CaseParty.case_id == case.id)).all()
    }
    seen: set[tuple[PartyRole, int]] = set()
    for role, name_key, extra_key, heir_key in (
        (PartyRole.PETITIONER, "pet_name", "pet_extra_party", "pet_legal_heir"),
        (PartyRole.RESPONDENT, "res_name", "res_extra_party", "res_legal_heir"),
    ):
        names: list[tuple[int, str]] = []
        first = as_text(data.get(name_key))
        if first:
            names.append((1, first))
        extras = numbered_values(data.get(extra_key), "party_no")
        # extra parties are numbered from 1 in their own block; the printed main party is the summary line
        offset = 1 if first and extras and extras[0][0] == 1 else 0
        names.extend((n + offset, t) for n, t in extras)
        heir = as_bool_yn(data.get(heir_key)) if heir_key in data else None
        for party_no, name in names:
            key = (role, party_no)
            seen.add(key)
            row = existing.get(key)
            if row is None:
                session.add(
                    CaseParty(
                        case_id=case.id,
                        role=role,
                        party_no=party_no,
                        name=name,
                        name_normalised=normalise_name(name),
                        has_legal_heir=heir,
                    )
                )
                counts["case_parties"] = counts.get("case_parties", 0) + 1
            else:
                if row.name != name:
                    row.name, row.name_normalised = name, normalise_name(name)
                row.has_legal_heir = heir if heir is not None else row.has_legal_heir
                row.is_current = True
    for key, row in existing.items():
        if key not in seen and row.is_current:
            row.is_current = False


def _sync_advocates(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (a.side, a.name_as_listed): a
        for a in session.scalars(select(CaseAdvocate).where(CaseAdvocate.case_id == case.id)).all()
    }
    seen: set[tuple[AdvocateSide, str]] = set()
    for side, key in ((AdvocateSide.PETITIONER, "pet_adv"), (AdvocateSide.RESPONDENT, "res_adv")):
        text = as_text(data.get(key))
        if not text:
            continue
        pieces = (
            [p.strip() for p in text.split(",") if p.strip()]
            if "," in text and not text.upper().startswith(("SC,", "GA,", "PP,"))
            else [text]
        )
        names, codes = split_advocates(pieces if len(pieces) > 1 else [text])
        for name in names:
            k = (side, name[:300])
            seen.add(k)
            if k not in existing:
                session.add(CaseAdvocate(case_id=case.id, side=side, name_as_listed=name[:300]))
                counts["case_advocates"] = counts.get("case_advocates", 0) + 1
            else:
                existing[k].is_current = True
        for code in codes:
            k = (side, code[:300])
            seen.add(k)
            if k not in existing:
                session.add(
                    CaseAdvocate(
                        case_id=case.id, side=side, name_as_listed=code[:300], counsel_code=code[:60]
                    )
                )
                counts["case_advocates"] = counts.get("case_advocates", 0) + 1
            else:
                existing[k].is_current = True
                existing[k].counsel_code = existing[k].counsel_code or code[:60]
    for k, row in existing.items():
        if k not in seen and row.is_current:
            row.is_current = False


def _sync_acts(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (a.act_name_as_listed, a.section)
        for a in session.scalars(select(CaseAct).where(CaseAct.case_id == case.id)).all()
    }
    for _n, row in block_items(data.get("acts")):
        name, section = as_text(row.get("actname"), 300), as_text(row.get("section"), 200) or ""
        if not name or (name, section) in existing:
            continue
        session.add(CaseAct(case_id=case.id, act_name_as_listed=name, section=section))
        existing.add((name, section))
        counts["case_acts"] = counts.get("case_acts", 0) + 1


def _sync_orders(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (o.order_no, o.order_date): o
        for o in session.scalars(select(Order).where(Order.case_id == case.id)).all()
    }
    for block, kind in (("interimorder", OrderKind.INTERIM), ("finalorder", OrderKind.FINAL)):
        for _n, row in block_items(data.get(block)):
            no, d = as_text(row.get("order_no"), 20), as_date(row.get("order_date"))
            if not no or d is None:
                continue
            o = existing.get((no, d))
            details = as_text(row.get("order_details"), 200)
            k = (
                OrderKind.JUDGMENT
                if details and "JUDG" in details.upper() and kind == OrderKind.FINAL
                else kind
            )
            if o is None:
                o = Order(case_id=case.id, order_no=no, order_date=d, kind=k)
                session.add(o)
                existing[(no, d)] = o
                counts["orders"] = counts.get("orders", 0) + 1
            o.kind = k
            o.order_details = details
            o.order_judge_name = as_text(row.get("order_judge_name"))
            o.date_judgement_pronounced = as_date(row.get("date_judgement_pronounced"))
            o.date_judgement_reserved = as_date(row.get("date_judgement_reserved"))
            o.raw = row


def _sync_hearings(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (h.business_date, h.purpose): h
        for h in session.scalars(select(CaseHearing).where(CaseHearing.case_id == case.id)).all()
    }
    for _n, row in block_items(data.get("historyofcasehearing")):
        bd = as_date(row.get("business_date"))
        purpose = as_text(row.get("purpose_of_listing"), 200) or ""
        h = existing.get((bd, purpose))
        if h is None:
            h = CaseHearing(case_id=case.id, business_date=bd, purpose=purpose, source=HearingSource.DOSSIER)
            session.add(h)
            existing[(bd, purpose)] = h
            counts["case_hearings"] = counts.get("case_hearings", 0) + 1
        h.hearing_date = as_date(row.get("hearing_date"))
        h.bench_text = as_text(row.get("judge_name"))
        h.causelist_type = as_text(row.get("causelist_type"), 60)
        if "desgname" in row:
            h.judge_designation = as_text(row.get("desgname"), 100)


def _sync_applications(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        a.ia_number: a
        for a in session.scalars(select(CaseApplication).where(CaseApplication.case_id == case.id)).all()
    }
    for _n, row in block_items(data.get("iafiling")):
        ia = as_text(row.get("ia_number"), 80)
        if not ia:
            continue
        a = existing.get(ia)
        if a is None:
            a = CaseApplication(case_id=case.id, ia_number=ia)
            session.add(a)
            existing[ia] = a
            counts["case_applications"] = counts.get("case_applications", 0) + 1
        a.party_name = as_text(row.get("ia_pet_name"))
        a.status = (as_text(row.get("ia_pend_disp")) or "")[:1] or None
        a.filing_date = as_date(row.get("date_of_filing"))
        a.raw = row


def _sync_objections(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    """`objections` is one flat block: objection1…n with one scrutiny/compliance/receipt date set."""
    block = data.get("objections")
    items: list[tuple[int, dict[str, Any]]]
    if isinstance(block, dict) and any(k.startswith("objection") for k in block):
        common = {k: v for k, v in block.items() if not k.startswith("objection")}
        items = [(n, {**common, "objection": t}) for n, t in numbered_values(block, "objection")]
    else:
        items = [(n, row) for n, row in block_items(block)]
    existing = {
        (o.scrutiny_date, o.seq): o
        for o in session.scalars(select(CaseObjection).where(CaseObjection.case_id == case.id)).all()
    }
    for n, row in items:
        sd = as_date(row.get("scrutiny_date"))
        if sd is None:
            continue
        o = existing.get((sd, n))
        if o is None:
            o = CaseObjection(case_id=case.id, seq=n, scrutiny_date=sd)
            session.add(o)
            existing[(sd, n)] = o
            counts["case_objections"] = counts.get("case_objections", 0) + 1
        o.objection = as_text(row.get("objection"))
        o.compliance_by_date = as_date(row.get("objections_compliance_by_date"))
        o.receipt_date = as_date(row.get("obj_reciept_date") or row.get("obj_receipt_date"))
        o.raw = row


def _sync_transfers(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (t.transfer_date, t.to_court_text)
        for t in session.scalars(select(CaseTransfer).where(CaseTransfer.case_id == case.id)).all()
    }
    for _n, row in block_items(data.get("transfer")):
        td = as_date(row.get("transfer_date"))
        to = as_text(row.get("to_court_no_desgname"), 300) or ""
        if (td, to) in existing:
            continue
        session.add(
            CaseTransfer(
                case_id=case.id,
                transfer_date=td,
                from_court_text=as_text(row.get("from_court_no_desgname"), 300),
                to_court_text=to,
                raw=row,
            )
        )
        existing.add((td, to))
        counts["case_transfers"] = counts.get("case_transfers", 0) + 1


def _sync_writ_info(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        w.appellate_case_number
        for w in session.scalars(select(CaseWritInfo).where(CaseWritInfo.case_id == case.id)).all()
    }
    for _n, row in block_items(data.get("writinfo")):
        no = as_text(row.get("appellate_case_number"), 200)
        if not no or no in existing:
            continue
        session.add(
            CaseWritInfo(
                case_id=case.id,
                appellate_case_number=no,
                appellate_authority=as_text(row.get("appellate_authority"), 200),
                raw=row,
            )
        )
        existing.add(no)
        counts["case_writ_info"] = counts.get("case_writ_info", 0) + 1


def _sync_links(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        (k.to_case_no_text, k.kind)
        for k in session.scalars(select(CaseLink).where(CaseLink.from_case_id == case.id)).all()
    }

    def add(kind: LinkKind, to_no: str, to_cnr: str | None = None, filing: str | None = None) -> None:
        if (to_no, kind) in existing:
            return
        to_case = session.scalar(select(Case).where(Case.cnr == to_cnr)) if to_cnr else None
        session.add(
            CaseLink(
                from_case_id=case.id,
                to_case_id=to_case.id if to_case else None,
                to_case_no_text=to_no,
                to_cnr=to_cnr,
                filing_number_text=filing,
                kind=kind,
                source=LinkSource.DOSSIER,
            )
        )
        existing.add((to_no, kind))
        counts["case_links"] = counts.get("case_links", 0) + 1

    mm_cino = as_text(data.get("main_matter_cino"), 16)
    mm = as_text(data.get("main_matter"), 200)
    if mm_cino or mm:
        add(LinkKind.MAIN_MATTER, mm or mm_cino or "", mm_cino)
    for _n, row in block_items(data.get("link_cases")):
        no = as_text(row.get("case_number"), 200)
        fil = as_text(row.get("filing_number"), 200)
        if no or fil:
            add(LinkKind.LINKED, no or fil or "", None, fil)


def _sync_lower_courts(session: Session, case: Case, data: dict[str, Any], counts: dict[str, int]) -> None:
    existing = {
        lc.level: lc
        for lc in session.scalars(select(CaseLowerCourt).where(CaseLowerCourt.case_id == case.id)).all()
    }
    for level, prefix in (
        (LowerCourtLevel.APPELLATE, "lower_court_"),
        (LowerCourtLevel.TRIAL, "trial_lower_court_"),
    ):
        name = as_text(data.get(prefix + "name"), 300)
        caseno = as_text(data.get(prefix + "caseno"), 200)
        dec = as_date(data.get(prefix + "dec_dt"))
        if caseno in {"0", "", None}:
            caseno = None
        if not (name or caseno or dec):
            continue
        lc = existing.get(level)
        if lc is None:
            lc = CaseLowerCourt(case_id=case.id, level=level)
            session.add(lc)
            existing[level] = lc
            counts["case_lower_courts"] = counts.get("case_lower_courts", 0) + 1
        lc.court_name, lc.case_no_text, lc.decision_date = name, caseno, dec
        lc.raw = {k: v for k, v in data.items() if k.startswith(prefix)}


def _snapshot(session: Session, case: Case, source: SnapshotSource, data: Any) -> bool:
    sha = payload_sha256(data)
    snap = session.scalar(
        select(CaseSnapshot).where(CaseSnapshot.case_id == case.id, CaseSnapshot.payload_sha256 == sha)
    )
    if snap is not None:
        snap.last_seen_at = _now()
        return False
    session.add(
        CaseSnapshot(
            case_id=case.id,
            source=source,
            payload_sha256=sha,
            payload=json.loads(json.dumps(data, default=str)),
        )
    )
    return True


def apply_dossier(session: Session, case: Case, data: dict[str, Any]) -> ApplyReport:
    """Search by CNR → every table of §C. Returns what changed."""
    cino = as_text(data.get("cino"), 16)
    if cino and case.cnr and cino.upper() != case.cnr.upper():
        raise ValueError(f"dossier is for {cino}, not {case.cnr}")
    if cino and not case.cnr:
        case.cnr = cino.upper()
    new = _snapshot(session, case, SnapshotSource.CNR, data)
    was_disposed = case.status == CaseStatus.DISPOSED
    court = _court_for(session, case, data)
    counts: dict[str, int] = {}
    apply_core_fields(session, case, data, court)
    _sync_parties(session, case, data, counts)
    _sync_advocates(session, case, data, counts)
    _sync_acts(session, case, data, counts)
    _sync_orders(session, case, data, counts)
    _sync_hearings(session, case, data, counts)
    _sync_applications(session, case, data, counts)
    _sync_objections(session, case, data, counts)
    _sync_transfers(session, case, data, counts)
    _sync_writ_info(session, case, data, counts)
    _sync_links(session, case, data, counts)
    _sync_lower_courts(session, case, data, counts)
    case.raw = json.loads(json.dumps(data, default=str))
    case.is_provisional = False
    case.dossier_stale = False
    case.last_full_refresh_at = _now()
    if case.status == CaseStatus.DISPOSED and not was_disposed:
        emit_event(
            session,
            EventType.CASE_DISPOSED,
            case,
            {"cnr": case.cnr, "disposal_date": case.disposal_date},
            dedupe=f"case_disposed:{case.cnr}:{case.disposal_date}",
        )
    session.flush()
    refresh_search_vector(session, [case.id])
    _attach_watchlist_and_score(session, case)
    return ApplyReport(case.id, case.cnr, changed=new or bool(counts), snapshot_new=new, counts=counts)


def refresh_search_vector(session: Session, case_ids) -> int:
    """Recomputes `cases.search_vector` with the SQL function of migration 0005 for the given cases (design
    `cases-api`, decision 6). Called after a dossier apply, a cause-list apply and a court-search store; the
    vector is never written by hand."""
    ids = list(dict.fromkeys(i for i in case_ids if i is not None))
    if not ids:
        return 0
    result = session.execute(
        text("UPDATE cases SET search_vector = aslms_case_search_vector(id) WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    return int(result.rowcount or 0)


def _attach_watchlist_and_score(session: Session, case: Case) -> None:
    """Fills `office_watchlist.case_id` for the case's CNR and scores the case (recommend-and-claim,
    decisions 4 and 14). Scoring failures are recorded by the engine, never raised."""
    from aslms.domain.ownership import OfficeWatchlist
    from aslms.services import matching

    if case.cnr:
        for w in session.scalars(
            select(OfficeWatchlist).where(OfficeWatchlist.cnr == case.cnr, OfficeWatchlist.case_id.is_(None))
        ).all():
            w.case_id = case.id
        session.flush()
    matching.score_cases(session, [case.id], origin=matching.origin_for_dossier(case))


STATUS_WATCH = (
    "next_hearing_date",
    "last_hearing_date",
    "status",
    "next_purpose",
    "disposal_date",
    "napix_bench_id",
)


def apply_status(session: Session, case: Case, block: dict[str, Any]) -> ApplyReport:
    """One `cases{n}` block of Current Status → the shared scalar columns; reports which tracked fields
    changed so the caller can refresh the dossier and raise events."""
    cino = as_text(block.get("cino"), 16)
    if cino and case.cnr and cino.upper() != case.cnr.upper():
        raise ValueError(f"status block is for {cino}, not {case.cnr}")
    before = {k: getattr(case, k) for k in STATUS_WATCH}
    new = _snapshot(session, case, SnapshotSource.CURRENT_STATUS, block)
    court = _court_for(session, case, block)
    apply_core_fields(session, case, block, court)
    case.last_status_refresh_at = _now()
    changes = {k: (before[k], getattr(case, k)) for k in STATUS_WATCH if before[k] != getattr(case, k)}
    if changes:
        case.dossier_stale = True
    session.flush()
    return ApplyReport(case.id, case.cnr, changed=bool(changes), snapshot_new=new, status_changes=changes)


# ------------------------------------------------------------------------------------------------ references


class CaseNotFound(LookupError):
    """No case for the given reference (HTTP 404)."""


_CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")


def ref_no_from_url(ref: str) -> str | None:
    """`ASLMS-GOA-CASE-2026-001842` (the URL form) or `ASLMS/GOA/CASE/2026/001842` → the slash form. Office
    codes may contain hyphens, so the last three segments are taken from the right."""
    s = (ref or "").strip().upper()
    if s.startswith("ASLMS/"):
        return s
    if not s.startswith("ASLMS-"):
        return None
    parts = s.split("-")
    if len(parts) < 5:
        return None
    return "/".join(["ASLMS", "-".join(parts[1:-3]), *parts[-3:]])


def resolve_case_ref(session: Session, ref: str) -> Case:
    """A case by id, `ref_no` (slash or dash form) or CNR (DB_STANDARD §3). Unknown → CaseNotFound."""
    s = (ref or "").strip()
    case = None
    try:
        case = session.get(Case, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            case = session.scalar(select(Case).where(Case.ref_no == ref_no))
        elif _CNR_RE.match(s.upper()):
            case = session.scalar(select(Case).where(Case.cnr == s.upper()))
    if case is None:
        raise CaseNotFound("no such case")
    return case
