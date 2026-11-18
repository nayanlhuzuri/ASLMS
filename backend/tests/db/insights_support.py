"""Shared helpers for the State Insights tests (design `state-insights`): case types of the court mapped to their kinds
of case, cases with parties, printed codes, a category, a main-matter link and orders read by row 250's parser, and
the fact build."""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.cases import (
    AdvocateSide,
    Case,
    CaseAdvocate,
    CaseLink,
    CaseParty,
    CaseStatus,
    LinkKind,
    PartyRole,
)
from aslms.domain.courts import CaseType, Court
from aslms.domain.insights import InsightCaseFact
from aslms.services import insights_facts, insights_groups
from aslms.services import order_sections as order_svc
from aslms.services.seed import SeedReport
from tests.db import next_dates_support as h
from tests.db import order_sections_support as o
from tests.db.world import make_case

TYPES = {
    111: ("WP(C)", "Writ Petition"),
    112: ("WA", "Writ Appeal"),
    142: ("Cont.Cas(C)", "Contempt of Court Cases relating to Civil Contempt"),
    220: ("I.A.(Civil)", "Interlocutory Application (Civil)"),
    171: ("Bail Appln.", "Bail Application"),
}
CATEGORY = "10023 - Selection and appointment with respect to State Govt Employees. ( 850 )"
CONTEMPT_CATEGORY = "10200 - Contempt Petition (Civil). ( 2982 )"
_seq = {"n": 0}


def court(s: Session) -> Court:
    return s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))


def case_types(s: Session) -> dict[int, CaseType]:
    """The test court's case types (inserted once) and their kinds of case through the seed."""
    c = court(s)
    have = {ct.case_type_code: ct for ct in s.scalars(sa.select(CaseType).where(CaseType.court_id == c.id))}
    for code, (short, full) in TYPES.items():
        if code not in have:
            ct = CaseType(
                court_id=c.id,
                case_type_code=code,
                type_name=f"{short} : {full}",
                short_name=short,
                full_name=full,
            )
            s.add(ct)
            have[code] = ct
    s.flush()
    insights_groups.seed(s, SeedReport())
    return have


def case(
    s: Session,
    *,
    type_code: int = 111,
    reg_no: int | None = None,
    reg_year: int = 2025,
    status: CaseStatus = CaseStatus.PENDING,
    category: str | None = CATEGORY,
    petitioners: tuple[str, ...] = ("RAM KUMAR",),
    respondents: tuple[str, ...] = (),
    codes: tuple[str, ...] = (),
    registration_date: date | None = None,
    next_hearing: date | None = None,
    disposal_date: date | None = None,
    disposal_type: str | None = None,
) -> Case:
    types = case_types(s)
    _seq["n"] += 1
    n = reg_no or (9000 + _seq["n"])
    short = types[type_code].short_name
    c = make_case(s, case_no=f"{short}/{n}/{reg_year}", status=status, next_hearing=next_hearing)
    c.case_type_id = types[type_code].id
    c.reg_no, c.reg_year = n, reg_year
    c.category = category
    c.registration_date = registration_date
    c.disposal_date = disposal_date
    c.disposal_type = disposal_type
    for i, name in enumerate(petitioners, start=1):
        s.add(CaseParty(case_id=c.id, role=PartyRole.PETITIONER, party_no=i, name=name, name_normalised=name))
    for i, name in enumerate(respondents, start=1):
        s.add(CaseParty(case_id=c.id, role=PartyRole.RESPONDENT, party_no=i, name=name, name_normalised=name))
    for i, code in enumerate(codes, start=1):
        s.add(
            CaseAdvocate(
                case_id=c.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed=f"ADVOCATE {i} {uuid.uuid4().hex[:6]}",
                counsel_code=code,
            )
        )
    s.flush()
    return c


def main_matter(s: Session, ia: Case, main: Case | None, text: str = "WP(C)/1/2025") -> CaseLink:
    link = CaseLink(
        from_case_id=ia.id,
        to_case_id=main.id if main else None,
        to_case_no_text=main.case_no_text if main else text,
        kind=LinkKind.MAIN_MATTER,
    )
    s.add(link)
    s.flush()
    return link


def order_read(
    s: Session,
    c: Case,
    *,
    respondents: str = "THE STATE OF ASSAM AND 3 ORS",
    linked: list[str] | None = None,
    day: date = date(2026, 1, 28),
    body: str | None = None,
):
    """An order of the case on the court's template with the respondent side of its cause title, read by row 250's
    parser (one `order_sections` row)."""
    kw = {"body": body} if body is not None else {}
    text = o.order_text(cnr=c.cnr, case_no=c.case_no_text, linked=linked, day=day.strftime("%d.%m.%Y"), **kw)
    text = text.replace("THE STATE OF ASSAM AND 3 ORS ", respondents + " ", 1)
    order = h.order_with_text(s, c, text, order_date=day)
    order_svc.read_batch(s, order_id=order.id)
    s.flush()
    return order


def build(s: Session, *cases: Case) -> dict[uuid.UUID, InsightCaseFact]:
    ids = [c.id for c in cases]
    insights_facts.build(s, ids)
    s.flush()
    return facts(s, *cases)


def facts(s: Session, *cases: Case) -> dict[uuid.UUID, InsightCaseFact]:
    rows = s.scalars(
        sa.select(InsightCaseFact)
        .where(InsightCaseFact.case_id.in_([c.id for c in cases]))
        .execution_options(populate_existing=True)
    ).all()
    return {r.case_id: r for r in rows}


def fact(s: Session, c: Case) -> InsightCaseFact:
    return facts(s, c)[c.id]
