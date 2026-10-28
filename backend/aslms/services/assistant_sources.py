"""The Case Assistant's eligibility rule, written once and the same for every mode (design `assistant`, decisions
3 to 6): pure SQL builders over `documents`, no connector import.

Two corpora:
- **court orders** (court-public, decision 3): an order PDF of the court (`order_nature()` of the ingestion rule:
  kind `order`, group `court_record`, scan `skipped`, an `orders` row pointing at it), not archived, of a case that
  is not merged, optionally of the focus cases. No visibility predicate: every assistant user may search, cite and
  open the court orders of every case in ASLMS (the owner's decision of 23 Oct 2026).
- **court filings** (department copies, decision 4): a clean court filing (`filing_nature()`), never
  `private_to_office`, not archived, of a case with a CNR that is not merged, and visible to the asker under the
  ordinary document rule (`visibility.document_visible_condition`: `documents.view`, a visible case and the record
  rule of the same membership), optionally of the focus cases.

Kinds `attachment`, `admin` and `causelist`, and the group `internal`, can never match either corpus: notes, note
attachments, internal and admin documents and cause-list PDFs are never in the assistant's reach.

The outer queries here select from `documents` (and `document_text`) only: the visibility condition correlates on
`cases`, so every case read beside it goes through an alias."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, Literal

from sqlalchemy import ColumnElement, String, and_, exists, func, literal, not_, select
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case, CaseAct, CaseAdvocate, CaseHearing, CaseParty, CaseStatus, PartyRole
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.courts import Court
from aslms.domain.documents import Document, DocumentText, Order, SourcetraceStatus, Visibility
from aslms.domain.org import User
from aslms.services import next_hearing, visibility
from aslms.services.my_cases import my_cases_condition
from aslms.services.sourcetrace_ingest import filing_nature, has_cnr, order_nature

Scope = Literal["case", "my_cases", "research"]
Mode = Literal["preview", "sourcetrace", "ollama"]
OrdersCorpus = Literal["focus", "focus_and_related", "all"]

_ORDER = aliased(Order, name="asst_order")
_ORDER_CASE = aliased(Case, name="asst_order_case")
_FILING_CASE = aliased(Case, name="asst_filing_case")


def _ids(values: Iterable[uuid.UUID] | None) -> list[uuid.UUID] | None:
    return None if values is None else list(dict.fromkeys(values))


def _order_of_case(case_ids: list[uuid.UUID] | None, *, negate: bool = False) -> ColumnElement[bool]:
    conds = [_ORDER.document_id == Document.id, _ORDER_CASE.merged_into_case_id.is_(None)]
    if case_ids is not None:
        conds.append(_ORDER.case_id.not_in(case_ids) if negate else _ORDER.case_id.in_(case_ids))
    return exists(
        select(literal(1))
        .select_from(_ORDER)
        .join(_ORDER_CASE, _ORDER_CASE.id == _ORDER.case_id)
        .where(*conds)
    )


def court_order_condition(
    *,
    focus_case_ids: Iterable[uuid.UUID] | None = None,
    exclude_case_ids: Iterable[uuid.UUID] | None = None,
) -> ColumnElement[bool]:
    """Decision 6, the court-order corpus. `focus_case_ids`: an order of one of these cases (case and my-cases
    scopes); `exclude_case_ids`: an order of another case, and the document backs no order of these cases (the
    "related orders in other cases" of the case scope). Neither: every court order in ASLMS (research)."""
    focus = _ids(focus_case_ids)
    exclude = _ids(exclude_case_ids)
    conds: list[ColumnElement[bool]] = [order_nature(), Document.archived_at.is_(None)]
    if focus is not None:
        conds.append(_order_of_case(focus) if focus else literal(False))
    elif exclude:
        conds.append(_order_of_case(exclude, negate=True))
        conds.append(not_(_order_of_case(exclude)))
    else:
        conds.append(_order_of_case(None))
    return and_(*conds)


def filing_base_condition(*, document_ids: Iterable[uuid.UUID] | None = None) -> ColumnElement[bool]:
    """Decision 6, the court-filing corpus without the asker's visibility: the nature, never private, not archived,
    a case with a CNR that is not merged; optionally one of `document_ids` (the preview's second check of the
    allow-list it received)."""
    conds: list[ColumnElement[bool]] = [
        filing_nature(),
        Document.visibility != Visibility.PRIVATE_TO_OFFICE,
        Document.archived_at.is_(None),
        exists(
            select(literal(1))
            .select_from(_FILING_CASE)
            .where(
                _FILING_CASE.id == Document.case_id,
                has_cnr(_FILING_CASE),
                _FILING_CASE.merged_into_case_id.is_(None),
            )
        ),
    ]
    ids = _ids(document_ids)
    if ids is not None:
        conds.append(Document.id.in_(ids) if ids else literal(False))
    return and_(*conds)


def court_filing_condition(
    session: Session, user: User, *, focus_case_ids: Iterable[uuid.UUID] | None = None
) -> ColumnElement[bool]:
    """Decision 6, the court filings the asker may see (the ordinary document rule), optionally of the focus
    cases."""
    conds = [filing_base_condition(), visibility.document_visible_condition(session, user)]
    focus = _ids(focus_case_ids)
    if focus is not None:
        conds.append(Document.case_id.in_(focus) if focus else literal(False))
    return and_(*conds)


def mode_condition(mode: Mode) -> ColumnElement[bool]:
    """Preview and ollama (design `assistant-ollama`, decision 2: the same search): the document has searchable stored
    text. Sourcetrace: SourceTrace holds it."""
    if mode in ("preview", "ollama"):
        return exists(
            select(literal(1))
            .select_from(DocumentText)
            .where(DocumentText.document_id == Document.id, DocumentText.search_vector.is_not(None))
        )
    return and_(
        Document.sourcetrace_status == SourcetraceStatus.INGESTED, Document.sourcetrace_ref.is_not(None)
    )


# ------------------------------------------------------------------------------------------------ the scope


def focus_cases(
    session: Session, user: User, scope: Scope, case: Case | None, *, limit: int = 1000
) -> tuple[list[uuid.UUID] | None, bool]:
    """Decision 5: `case` the one case (the caller has checked the sight); `my_cases` the caller's own cases
    (`my_cases_condition` AND `visible_case_condition`, not merged), at most `limit`, newest activity first, with
    `truncated`; `research` None (no focus: every court order)."""
    if scope == "case":
        if case is None:
            raise ValueError("a case-scope question needs its case")
        return [case.id], False
    if scope == "research":
        return None, False
    rows = list(
        session.scalars(
            select(Case.id)
            .where(
                Case.merged_into_case_id.is_(None),
                visibility.visible_case_condition(session, user),
                my_cases_condition(session, user),
            )
            .order_by(
                Case.last_hearing_date.desc().nulls_last(),
                Case.next_hearing_on.desc().nulls_last(),
                Case.updated_at.desc(),
                Case.id,
            )
            .limit(limit + 1)
        ).all()
    )
    return rows[:limit], len(rows) > limit


def filing_allow_list(
    session: Session,
    user: User,
    focus_case_ids: list[uuid.UUID] | None,
    mode: Mode,
    *,
    limit: int = 1000,
) -> tuple[list[tuple[uuid.UUID, str]], bool]:
    """Decision 6: the court filings passed to the connector as an allow-list of `(document_id, reference)`,
    at most `limit`, newest `doc_date` first, with `truncated`. The reference is the document id in preview and the
    `sourcetrace_ref` in sourcetrace."""
    rows = session.execute(
        select(Document.id, Document.sourcetrace_ref)
        .where(court_filing_condition(session, user, focus_case_ids=focus_case_ids), mode_condition(mode))
        .order_by(Document.doc_date.desc().nulls_last(), Document.created_at.desc(), Document.id)
        .limit(limit + 1)
    ).all()
    refs = [(doc_id, str(doc_id) if mode == "preview" else str(ref)) for doc_id, ref in rows[:limit]]
    return refs, len(rows) > limit


def _names(rows: Iterable[tuple[uuid.UUID, str]]) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {}
    for cid, name in rows:
        if name and name not in out.setdefault(cid, []):
            out[cid].append(name)
    return out


def case_contexts(session: Session, case_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """The court-public facts of each case (decisions 3 and 12), in the order of `case_ids`: the keyword arguments
    of the connector's `CaseContext` (this module imports no connector). Nothing internal: no owner, custody,
    stage, note, recommendation or `ref_no`."""
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return []
    cases = {
        c.id: (c, court_name)
        for c, court_name in session.execute(
            select(Case, Court.name).join(Court, Court.id == Case.court_id).where(Case.id.in_(ids))
        ).all()
    }
    parties = _names(
        session.execute(
            select(CaseParty.case_id, CaseParty.name)
            .where(CaseParty.case_id.in_(ids), CaseParty.is_current.is_(True))
            .order_by(CaseParty.case_id, (CaseParty.role == PartyRole.PETITIONER).desc(), CaseParty.party_no)
        ).all()
    )
    advocates = _names(
        session.execute(
            select(CaseAdvocate.case_id, CaseAdvocate.name_as_listed)
            .where(CaseAdvocate.case_id.in_(ids), CaseAdvocate.is_current.is_(True))
            .order_by(CaseAdvocate.case_id, CaseAdvocate.side, CaseAdvocate.created_at)
        ).all()
    )
    acts = _names(
        (cid, f"{name} {section}".strip())
        for cid, name, section in session.execute(
            select(CaseAct.case_id, CaseAct.act_name_as_listed, CaseAct.section)
            .where(CaseAct.case_id.in_(ids))
            .order_by(CaseAct.case_id, CaseAct.created_at)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for cid in ids:
        if cid not in cases:
            continue
        c, court_name = cases[cid]
        pets = [c.petitioner_summary] if c.petitioner_summary else []
        ress = [c.respondent_summary] if c.respondent_summary else []
        out.append(
            {
                "case_id": c.id,
                "cnr": c.cnr,
                "case_no_text": c.case_no_text,
                "filing_no_text": c.filing_no_text,
                "court": c.court_est_name or court_name,
                "bench": c.bench_name,
                "case_type": c.case_type_text,
                "year": c.reg_year or c.filing_year,
                "status": CaseStatus(c.status).value,
                "parties": tuple(parties.get(cid) or pets + ress),
                "advocates": tuple(advocates.get(cid) or [a for a in (c.pet_advocate, c.res_advocate) if a]),
                "acts": tuple(acts.get(cid, [])),
                "last_hearing_date": c.last_hearing_date,
                "next_hearing_date": c.next_hearing_date,
            }
        )
    return out


def _v(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def case_details(
    session: Session, case_ids: list[uuid.UUID], *, hearings: int, listings: int
) -> list[dict[str, Any]]:
    """Design `assistant-ollama`, decision 3(a): the "Case Details (Court Record)" of each case, in the order of
    `case_ids`: the court-public facts of `case_contexts`, plus the last `hearings` hearings (business date, next date,
    purpose, bench, short order text as held) and the last `listings` listings (list date, list type, bench, court
    number and printed item; rows of a list replaced by a corrected one marked `superseded`). The same tables as
    `case_detail.hearings` and `case_detail.listings`; nothing internal: no owner, recommendation, stage, custody or
    `ref_no`. Imports no connector. Design `assistant-polish`, decision 6: plus `coram`; design `next-date-direct`,
    decision 11: plus `next_hearing` (the case's one next hearing, never a date entered by hand)."""
    out = case_contexts(session, case_ids)
    ids = [c["case_id"] for c in out]
    if not ids:
        return out
    by_case_h: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
    if hearings > 0:
        ranked = (
            select(
                CaseHearing,
                func.row_number()
                .over(
                    partition_by=CaseHearing.case_id,
                    order_by=(CaseHearing.business_date.desc().nulls_last(), CaseHearing.purpose),
                )
                .label("rn"),
            )
            .where(CaseHearing.case_id.in_(ids))
            .subquery()
        )
        h_alias = aliased(CaseHearing, ranked)
        for h in session.scalars(
            select(h_alias).where(ranked.c.rn <= hearings).order_by(ranked.c.case_id, ranked.c.rn)
        ).all():
            by_case_h[h.case_id].append(
                {
                    "business_date": h.business_date,
                    "next_date": h.hearing_date,
                    "purpose": h.purpose or None,
                    "bench": h.bench_text,
                    "short_order": h.short_order_text,
                }
            )
    by_case_l: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
    if listings > 0:
        ranked_l = (
            select(
                CauselistEntry.case_id.label("case_id"),
                Causelist.list_date.label("list_date"),
                Causelist.list_type.label("list_type"),
                func.coalesce(Causelist.bench_label, CauselistEntry.bench_text).label("bench"),
                CauselistEntry.court_no.label("court_no"),
                func.coalesce(CauselistEntry.printed_sr_no, func.cast(CauselistEntry.sr_no, String)).label(
                    "item"
                ),
                (Causelist.superseded_at.is_not(None)).label("superseded"),
                func.row_number()
                .over(
                    partition_by=CauselistEntry.case_id,
                    order_by=(Causelist.list_date.desc(), Causelist.version.desc(), CauselistEntry.sr_no),
                )
                .label("rn"),
            )
            .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
            .where(CauselistEntry.case_id.in_(ids))
            .subquery()
        )
        for row in session.execute(
            select(ranked_l).where(ranked_l.c.rn <= listings).order_by(ranked_l.c.case_id, ranked_l.c.rn)
        ).all():
            by_case_l[row.case_id].append(
                {
                    "list_date": row.list_date,
                    "list_type": _v(row.list_type),
                    "bench": row.bench,
                    "court_no": row.court_no,
                    "item": row.item,
                    "superseded": bool(row.superseded),
                }
            )
    for c in out:
        c["hearings"] = by_case_h.get(c["case_id"], [])
        c["listings"] = by_case_l.get(c["case_id"], [])
        # design assistant-polish, decision 6: the coram, and the next date read from an order through the
        # assistant's one next-hearing reader; a manual date is an officer's entry and is never put here
        row = session.get(Case, c["case_id"])
        c["coram"] = (row.coram or "").strip() or None
        # design next-date-direct, decision 11: the case's one next hearing; a date entered by hand is an officer's
        # entry and is never given to the model (assistant-polish, decision 6)
        nh = next_hearing.describe_case(session, row)
        c["next_hearing"] = nh if nh is not None and nh.get("basis") != "manual" else None
    return out


# ------------------------------------------------------------------------------------------------ re-checks


class NotCitable(LookupError):
    """A citation outside the scope that was sent, or no longer within the asker's reach."""


def citable_kind(
    session: Session,
    user: User,
    document_id: uuid.UUID,
    *,
    orders: OrdersCorpus | None,
    focus_case_ids: list[uuid.UUID] | None,
    filing_ids: set[uuid.UUID] | None,
) -> str | None:
    """`court_order`, `court_filing` or None for one cited document: a court order in the corpus described by
    `orders` (`focus` only the focus cases; `focus_and_related` and `all` any court order; None no order), or a
    court filing in `filing_ids` (None: any filing the asker may see now) that the asker may still see."""
    order_cond = None
    if orders is not None:
        order_cond = court_order_condition(focus_case_ids=focus_case_ids if orders == "focus" else None)
    filing_cond = court_filing_condition(session, user)
    if filing_ids is not None:
        filing_cond = and_(filing_cond, Document.id.in_(list(filing_ids)) if filing_ids else literal(False))
    cols = [filing_cond.label("filing")]
    if order_cond is not None:
        cols.append(order_cond.label("order"))
    row = session.execute(select(*cols).select_from(Document).where(Document.id == document_id)).one_or_none()
    if row is None:
        return None
    if order_cond is not None and row.order:
        return "court_order"
    if row.filing:
        return "court_filing"
    return None


def assert_citable(
    session: Session,
    user: User,
    document_id: uuid.UUID,
    scope_refs: set[uuid.UUID] | None,
    *,
    orders: OrdersCorpus | None = "all",
    focus_case_ids: list[uuid.UUID] | None = None,
) -> str:
    """Decisions 8 and 12: re-checks one citation; the source kind, or `NotCitable`."""
    kind = citable_kind(
        session, user, document_id, orders=orders, focus_case_ids=focus_case_ids, filing_ids=scope_refs
    )
    if kind is None:
        raise NotCitable("the cited document is outside the scope")
    return kind


def visible_filings(session: Session, user: User, document_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Decision 8, reading again: which of these court filings the asker may still see (one query)."""
    ids = list(dict.fromkeys(document_ids))
    if not ids:
        return set()
    return set(
        session.scalars(
            select(Document.id).where(Document.id.in_(ids), court_filing_condition(session, user))
        ).all()
    )


def court_order_documents(document_ids: Iterable[uuid.UUID]) -> Any:
    """The documents among `document_ids` that are in the court-order corpus (a select of ids)."""
    ids = list(dict.fromkeys(document_ids))
    return select(Document.id).where(Document.id.in_(ids), court_order_condition())


def related_documents(document_ids: Iterable[uuid.UUID], focus_case_ids: list[uuid.UUID]) -> Any:
    """The court-order documents among `document_ids` that back no order of the focus cases (a select of ids)."""
    ids = list(dict.fromkeys(document_ids))
    return select(Document.id).where(Document.id.in_(ids), not_(_order_of_case(focus_case_ids)))
