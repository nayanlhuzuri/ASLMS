"""The input of a System health test (design `api-health-checker`, decision 5): only data ASLMS already holds, never
an invented identifier (CLAUDE.md). One chooser per court API card; each is one query with `LIMIT 1`, deterministic
(newest first, ties broken by `id`) and blind to merged cases (`merged_into_case_id IS NULL`). The configured codes
`NAPIX_EST_CODE` and `NAPIX_STATE_CODE` are configuration, not invented identifiers.

- `exists(session, settings, key)` only asks whether a sample is held (the card list disables its button with the
  reason); `choose(session, settings, key, user)` picks the actual sample with a label that names a case only when
  the caller may see it (`visibility.access_basis`). The POST always picks again on the server.
- `Sample.values` is what the call needs. Party and advocate names are never shown (`hidden`); a CNR, a case number
  or a filing number is shown only when the case is visible to the caller (`case_keys`). `public_values` is what the
  API and the audit row get. Read-only."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, aliased

from aslms.core.config import Settings
from aslms.domain.cases import AdvocateSide, Case, CaseAdvocate, CaseHearing, CaseParty, CaseStatus, PartyRole
from aslms.domain.causelists import Causelist, ListSource
from aslms.domain.courts import CaseType
from aslms.domain.documents import Document, Order
from aslms.domain.org import User
from aslms.domain.ownership import DiscoveryTerm
from aslms.services.access import Member
from aslms.services.court_search import PARTY_NAME_RE
from aslms.services.reporting_common import today_ist

HELD_ELSEWHERE = "a case held by ASLMS"
MIN_NAME, MAX_PARTY, MAX_ADVOCATE = 3, 200, 99
# a masked name ("XXXXXXX") carries no letter other than X
UNMASKED_SQL = "[A-WYZa-wyz]"
_UNMASKED = re.compile(UNMASKED_SQL)

REASONS: dict[str, str] = {
    "causelist_details": "No cause list from the court is held yet",
    "show_causelist": "No stored cause-list PDF yet",
    "cnr": "No case has been fetched from the court yet",
    "current_status": "No case has been fetched from the court yet",
    "order": "No stored order PDF yet",
    "show_business": "No hearing with a business date is held yet",
    "case_search": "No fetched case has a registration number yet",
    "filing": "No fetched case has a filing number yet",
    "party_name": "No discovery term or suitable party name is held yet",
    "advocate_name": "No advocate name is held yet",
}
CASE_KEYS = frozenset({"cnr", "reg_no", "fil_no"})
NAME_KEYS = frozenset({"name"})


@dataclass
class Sample:
    values: dict[str, Any]
    label: str
    source_case_id: uuid.UUID | None = None
    source_ref_no: str | None = None
    stored_sha256: str | None = None
    source_cnr: str | None = None
    hidden: frozenset[str] = field(default_factory=lambda: NAME_KEYS)
    case_keys: frozenset[str] = field(default_factory=lambda: CASE_KEYS)
    case_visible: bool = False

    def public_values(self, *, case_visible: bool | None = None) -> dict[str, Any]:
        """The values the screen and the audit row may carry: never a name; a CNR or a case or filing number only
        when the case is visible (`case_visible`, default: as chosen for the caller)."""
        visible = self.case_visible if case_visible is None else case_visible
        out: dict[str, Any] = {}
        for k, v in self.values.items():
            if k in self.hidden or (k in self.case_keys and not visible):
                continue
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out


@dataclass(frozen=True)
class NoSample:
    reason: str


# ------------------------------------------------------------------------------------------------ helpers


def _live_case(c=Case):
    return and_(c.merged_into_case_id.is_(None), c.cnr.is_not(None))


def _fetched(c=Case):
    return and_(_live_case(c), c.last_full_refresh_at.is_not(None))


def _name_ok(column, max_len: int):
    return and_(
        func.length(func.btrim(column)).between(MIN_NAME, max_len),
        column.op("~")(PARTY_NAME_RE.pattern),
        column.op("~")(UNMASKED_SQL),
    )


def name_passes(name: str | None, max_len: int) -> bool:
    """The Python form of `_name_ok` (decision 5's rules for a party or advocate name)."""
    text = (name or "").strip()
    return (
        MIN_NAME <= len(text) <= max_len and bool(PARTY_NAME_RE.match(text)) and bool(_UNMASKED.search(text))
    )


def _pend_disp(status: Any) -> str | None:
    value = status.value if hasattr(status, "value") else status
    return {"pending": "P", "disposed": "D"}.get(value)


def _visible(session: Session, user: User | Member | None, case_id: uuid.UUID | None) -> bool:
    if user is None or case_id is None:
        return False
    from aslms.services.visibility import access_basis

    return bool(access_basis(session, user, case_id))


def _case_label(
    session: Session, user: User | Member | None, case: Case, *, prefix: str = ""
) -> tuple[str, bool]:
    visible = _visible(session, user, case.id)
    if visible:
        what = case.case_no_text or case.cnr or HELD_ELSEWHERE
        if case.cnr and case.case_no_text:
            what = f"{case.case_no_text} (CNR {case.cnr})"
    else:
        what = HELD_ELSEWHERE
    return (f"{prefix}{what}" if prefix else what), visible


def _fmt(d: date) -> str:
    return d.strftime("%d %b %Y")


# ------------------------------------------------------------------------------------------------ the queries


def _q_napix_list() -> Select:
    return (
        select(Causelist)
        .where(Causelist.source == ListSource.NAPIX)
        .order_by(Causelist.list_date.desc(), Causelist.id.desc())
    )


def _q_bench_list() -> Select:
    return _q_napix_list().where(Causelist.bench_id.is_not(None))


def _q_stored_list() -> Select:
    return (
        select(Causelist, Document.sha256)
        .join(Document, Document.id == Causelist.document_id)
        .where(
            Causelist.source == ListSource.NAPIX,
            Causelist.napix_causelist_id.is_not(None),
            Causelist.bench_id.is_not(None),
        )
        .order_by(Causelist.list_date.desc(), Causelist.id.desc())
    )


def _q_reference_case() -> Select:
    return select(Case).where(_fetched()).order_by(Case.last_full_refresh_at.desc(), Case.id.desc())


def _q_order() -> Select:
    return (
        select(Order, Case, Document.sha256)
        .join(Case, Case.id == Order.case_id)
        .join(Document, Document.id == Order.document_id)
        .where(_live_case())
        .order_by(Order.order_date.desc(), Order.id.desc())
    )


def _q_hearing(today: date) -> Select:
    return (
        select(CaseHearing, Case)
        .join(Case, Case.id == CaseHearing.case_id)
        .where(_live_case(), CaseHearing.business_date.is_not(None), CaseHearing.business_date <= today)
        .order_by(CaseHearing.business_date.desc(), CaseHearing.id.desc())
    )


def _q_case_number() -> Select:
    return (
        select(Case, CaseType.case_type_code)
        .join(CaseType, CaseType.id == Case.case_type_id)
        .where(_fetched(), Case.reg_no.is_not(None), Case.reg_year.is_not(None))
        .order_by(Case.last_full_refresh_at.desc(), Case.id.desc())
    )


def _q_filing() -> Select:
    ct = aliased(CaseType)
    return (
        select(Case, ct.case_type_code)
        .join(ct, ct.id == func.coalesce(Case.filing_case_type_id, Case.case_type_id))
        .where(_fetched(), Case.filing_no.is_not(None), Case.filing_year.is_not(None))
        .order_by(Case.last_full_refresh_at.desc(), Case.id.desc())
    )


def _q_respondent() -> Select:
    return (
        select(CaseParty.name, Case)
        .join(Case, Case.id == CaseParty.case_id)
        .where(
            _fetched(),
            Case.status == CaseStatus.PENDING,
            Case.reg_year.is_not(None),
            CaseParty.role == PartyRole.RESPONDENT,
            CaseParty.party_no == 1,
            CaseParty.is_current.is_(True),
            _name_ok(CaseParty.name, MAX_PARTY),
        )
        .order_by(Case.last_full_refresh_at.desc(), Case.id.desc(), CaseParty.id)
    )


def _q_advocate() -> Select:
    return (
        select(CaseAdvocate.name_as_listed, Case)
        .join(Case, Case.id == CaseAdvocate.case_id)
        .where(
            _fetched(),
            Case.reg_year.is_not(None),
            Case.status.in_([CaseStatus.PENDING, CaseStatus.DISPOSED]),
            CaseAdvocate.is_current.is_(True),
            CaseAdvocate.side.in_(list(AdvocateSide)),
            _name_ok(CaseAdvocate.name_as_listed, MAX_ADVOCATE),
        )
        .order_by(Case.last_full_refresh_at.desc(), Case.id.desc(), CaseAdvocate.id)
    )


def _active_term(session: Session) -> DiscoveryTerm | None:
    from aslms.services.discovery import active_departments

    active = sorted(active_departments(session))
    if not active:
        return None
    return session.scalar(
        select(DiscoveryTerm)
        .where(DiscoveryTerm.term.in_(active))
        .order_by(DiscoveryTerm.last_searched_at.desc().nulls_last(), DiscoveryTerm.id.desc())
        .limit(1)
    )


def _first(session: Session, stmt: Select):
    return session.execute(stmt.limit(1)).first()


# ------------------------------------------------------------------------------------------------ choosers


def _no_input(session, settings, user) -> Sample:
    return Sample({}, "No input: the API takes none")


def _state_code(session, settings, user) -> Sample:
    return Sample({"state_code": settings.napix_state_code}, f"State code {settings.napix_state_code}")


def _est_code(session, settings, user) -> Sample:
    return Sample({"est_code": settings.napix_est_code}, f"Court code {settings.napix_est_code}")


def _causelist_bench(session, settings, user) -> Sample:
    row = _first(session, _q_napix_list())
    if row is None:
        day = today_ist()
        return Sample({"list_date": day}, f"Today, {_fmt(day)} (no cause list from the court is held yet)")
    cl = row[0]
    return Sample({"list_date": cl.list_date}, f"The latest cause-list day held, {_fmt(cl.list_date)}")


def _causelist_details(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_bench_list())
    if row is None:
        return NoSample(REASONS["causelist_details"])
    cl = row[0]
    return Sample(
        {"list_date": cl.list_date, "bench_id": str(cl.bench_id)},
        f"Bench {cl.bench_id} on {_fmt(cl.list_date)}, the latest cause list held",
    )


def _show_causelist(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_stored_list())
    if row is None:
        return NoSample(REASONS["show_causelist"])
    cl, sha = row
    return Sample(
        {"bench_id": str(cl.bench_id), "causelist_id": str(cl.napix_causelist_id), "list_date": cl.list_date},
        f"List {cl.napix_causelist_id} of bench {cl.bench_id} on {_fmt(cl.list_date)}, already stored",
        stored_sha256=sha,
    )


def _reference(session, settings, user, key: str) -> Sample | NoSample:
    row = _first(session, _q_reference_case())
    if row is None:
        return NoSample(REASONS[key])
    case = row[0]
    label, visible = _case_label(session, user, case)
    return Sample(
        {"cnr": case.cnr},
        label,
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


def _order(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_order())
    if row is None:
        return NoSample(REASONS["order"])
    order, case, sha = row
    label, visible = _case_label(
        session, user, case, prefix=f"Order {order.order_no} of {_fmt(order.order_date)}, "
    )
    return Sample(
        {"cnr": case.cnr, "order_no": order.order_no, "order_date": order.order_date},
        label,
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        stored_sha256=sha,
        case_visible=visible,
    )


def _show_business(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_hearing(today_ist()))
    if row is None:
        return NoSample(REASONS["show_business"])
    hearing, case = row
    label, visible = _case_label(
        session, user, case, prefix=f"The hearing of {_fmt(hearing.business_date)}, "
    )
    return Sample(
        {"cnr": case.cnr, "business_date": hearing.business_date},
        label,
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


def _case_search(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_case_number())
    if row is None:
        return NoSample(REASONS["case_search"])
    case, code = row
    label, visible = _case_label(session, user, case, prefix=f"Case type {code}, year {case.reg_year}: ")
    return Sample(
        {"case_type": code, "reg_no": case.reg_no, "reg_year": case.reg_year},
        label,
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


def _filing(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_filing())
    if row is None:
        return NoSample(REASONS["filing"])
    case, code = row
    label, visible = _case_label(
        session, user, case, prefix=f"Filing case type {code}, year {case.filing_year}: the filing of "
    )
    return Sample(
        {"case_type": code, "fil_no": case.filing_no, "fil_year": case.filing_year},
        label,
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


def _party_name(session, settings, user) -> Sample | NoSample:
    term = _active_term(session)
    if term is not None:
        year = today_ist().year
        # a discovery term is a rule text, not case data: it may be shown (decision 5)
        return Sample(
            {"name": term.term, "reg_year": year, "pend_disp": "P", "term": term.term},
            f'The discovery term "{term.term}", {year}, pending cases',
        )
    row = _first(session, _q_respondent())
    if row is None:
        return NoSample(REASONS["party_name"])
    name, case = row
    label, visible = _case_label(session, user, case, prefix="A party of ")
    return Sample(
        {"name": name.strip(), "reg_year": case.reg_year, "pend_disp": "P"},
        f"{label}, {case.reg_year}, pending cases",
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


def _advocate_name(session, settings, user) -> Sample | NoSample:
    row = _first(session, _q_advocate())
    if row is None:
        return NoSample(REASONS["advocate_name"])
    name, case = row
    pend = _pend_disp(case.status) or "P"
    label, visible = _case_label(session, user, case, prefix="An advocate of ")
    return Sample(
        {"name": name.strip(), "reg_year": case.reg_year, "pend_disp": pend},
        f"{label}, {case.reg_year}, {'pending' if pend == 'P' else 'disposed'} cases",
        source_case_id=case.id,
        source_ref_no=case.ref_no,
        source_cnr=case.cnr,
        case_visible=visible,
    )


Chooser = Callable[[Session, Settings, "User | Member | None"], "Sample | NoSample"]

CHOOSERS: dict[str, Chooser] = {
    "overview": _no_input,
    "state": _no_input,
    "district": _state_code,
    "bench_master": _state_code,
    "case_type": _est_code,
    "act": _no_input,
    "causelist_bench": _causelist_bench,
    "causelist_details": _causelist_details,
    "show_causelist": _show_causelist,
    "cnr": lambda s, st, u: _reference(s, st, u, "cnr"),
    "current_status": lambda s, st, u: _reference(s, st, u, "current_status"),
    "order": _order,
    "show_business": _show_business,
    "case_search": _case_search,
    "filing": _filing,
    "party_name": _party_name,
    "advocate_name": _advocate_name,
}

# the cheap existence checks of the card list (decision 5): None means "always testable"
_EXISTS: dict[str, Callable[[Session], Select] | None] = {
    "overview": None,
    "state": None,
    "district": None,
    "bench_master": None,
    "case_type": None,
    "act": None,
    "causelist_bench": None,
    "causelist_details": lambda s: _q_bench_list(),
    "show_causelist": lambda s: _q_stored_list(),
    "cnr": lambda s: _q_reference_case(),
    "current_status": lambda s: _q_reference_case(),
    "order": lambda s: _q_order(),
    "show_business": lambda s: _q_hearing(today_ist()),
    "case_search": lambda s: _q_case_number(),
    "filing": lambda s: _q_filing(),
    "party_name": lambda s: _q_respondent(),
    "advocate_name": lambda s: _q_advocate(),
}


def exists(session: Session, settings: Settings, key: str) -> tuple[bool, str | None]:
    """(a sample is held, the reason when not) without picking it."""
    query = _EXISTS[key]
    if query is None:
        return True, None
    if key == "party_name" and _active_term(session) is not None:
        return True, None
    found = session.scalar(select(query(session).limit(1).exists())) is True
    return (True, None) if found else (False, REASONS[key])


def choose(session: Session, settings: Settings, key: str, user: User | Member | None) -> Sample | NoSample:
    return CHOOSERS[key](session, settings, user)


__all__ = ["CHOOSERS", "REASONS", "NoSample", "Sample", "choose", "exists", "name_passes"]
