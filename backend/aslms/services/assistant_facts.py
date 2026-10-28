"""Quick facts of a case answered from its court record without any model (design `assistant-polish`, decisions 10 to
13): six facts (next hearing, parties, advocates, status, last order date, bench), recognised only when the whole
question matches one fixed frame or two frames joined by "and" (English only; anything else goes to the model), and
answered in one or two lines per fact, each ending with `[S1]`, the case's Case Details.

- `recognise` is pure: normalise, strip fixed fillers, match whole frames. A question that does not match completely
  goes to the model, never to a guess.
- `next_hearing` is the assistant's **only** reader of the next hearing, used by the quick fact and by the Case
  Details source given to the model (`assistant_sources.case_details`, decision 6). Until row 199 it states the two
  values the case page shows (the court's date of the header, and the next date from orders of the Overview card,
  `next_dates.effective_for_case`) without choosing between them.
- `facts_of` and `answer` read the same court tables the case page shows (`cases`, current `case_parties` and
  `case_advocates`, the case's `orders` in the Orders tab's order, the latest `case_hearings.bench_text`). Nothing
  internal: no owner, stage, custody, notes, recommendation or `ref_no`.

Imports no connector and no write service; reads only."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core import clock
from aslms.domain.alerts import NextDateSource
from aslms.domain.cases import AdvocateSide, Case, CaseAdvocate, CaseHearing, CaseParty, CaseStatus, PartyRole
from aslms.domain.documents import Order

FACTS = ("next_hearing", "parties", "advocates", "status", "last_order", "bench")
FACTS_VERSION = 1
ENGINE = "case_record"
CONNECTOR = "facts"
LABEL = "S1"
ORDER_SOURCES = ("order_specific", "order_period")

# ------------------------------------------------------------------------------------------------ recognising

_CONTRACTIONS = (("who's", "who is"), ("what's", "what is"), ("when's", "when is"), ("where's", "where is"))
_LEAD = (
    "please",
    "kindly",
    "can you tell me",
    "could you tell me",
    "tell me",
    "let me know",
    "i want to know",
    "may i know",
)
_TRAIL = re.compile(r"(?: please| (?:of|in|for) (?:this case|the case|this matter|the matter))$")

_CASE = r"(?:it|the case|this case|the matter)"
_ORDER_TAIL = (
    r"(?: (?:as per|according to|in|from|by) (?:the )?(?:latest|last|most recent|recent) (?:court )?order)?"
)
_PARTY = r"(?:parties|petitioners?|respondents?)"
_ADV = r"(?:advocates?|lawyers?|counsels?)"
_SIDE = r"(?:petitioners?|respondents?|state|government)"

# decision 11's table, fixed in code (a change is a code change with its tests)
_FRAMES: dict[str, tuple[str, ...]] = {
    "next_hearing": tuple(
        f + _ORDER_TAIL
        for f in (
            r"(?:when is|what is) (?:the )?(?:next )?"
            r"(?:hearing|hearing date|date of hearing|next date|listing|listing date)",
            r"(?:when is|when will) (?:the case|this case|the matter|this matter|it) (?:be )?(?:next )?"
            r"(?:listed|heard|taken up|coming up|come up)(?: next)?",
            r"(?:the )?next (?:hearing|date|listing)(?: date)?",
            r"(?:the )?next date of hearing",
        )
    ),
    "parties": (
        rf"(?:who are|who is|who were) (?:the )?{_PARTY}",
        rf"(?:name|names|list)(?: of)? (?:the )?{_PARTY}",
        rf"(?:the )?{_PARTY}(?: names)?",
        r"who (?:filed|has filed|brought) (?:the case|this case|the petition|it)",
        r"(?:who is|who are) (?:the case|this case|it) (?:against|filed against)",
    ),
    "advocates": (
        rf"(?:who are|who is|who were) (?:the )?{_ADV}(?: for (?:the )?{_SIDE})?",
        rf"(?:who appears?|who is appearing) for (?:the )?{_SIDE}",
        rf"(?:name|names|list)(?: of)? (?:the )?{_ADV}",
        r"(?:the )?(?:advocates?|lawyers?|counsel)(?: names)?",
    ),
    "status": (
        r"(?:what is )?(?:the )?(?:current )?(?:case )?status",
        rf"is {_CASE} (?:still )?(?:pending|disposed|closed|decided|over)",
        rf"(?:has|was) {_CASE} (?:been )?(?:disposed|decided|closed)(?: of)?",
        r"(?:is it )?(?:pending or disposed|disposed or pending)",
    ),
    "last_order": (
        r"(?:when was|what is the date of|date of) (?:the )?(?:last|latest|most recent|previous) order"
        r"(?: passed| issued| made)?",
        r"(?:the )?(?:last|latest|most recent) order date",
        r"when did the court (?:last )?pass (?:an |the )?(?:last |latest )?order",
    ),
    "bench": (
        rf"(?:which|what) (?:bench|judge|court)(?: is {_CASE} (?:before|in|listed before))?",
        rf"before (?:which|whom|what) (?:bench|judge)(?: is {_CASE}(?: listed| pending)?)?",
        r"(?:who is|who are) the (?:judge|judges|bench)",
        r"(?:the )?(?:bench|coram|judge)",
    ),
}
_COMPILED = {fact: re.compile("(?:" + "|".join(frames) + ")") for fact, frames in _FRAMES.items()}


def normalise(question: str) -> str:
    """Lower-case; "who's", "what's", "when's" and "where's" expanded; "'s" dropped; every character other than letters,
    digits and spaces turned into a space; spaces collapsed. Pure."""
    q = (question or "").lower().replace("’", "'").replace("‘", "'")
    for short, full in _CONTRACTIONS:
        q = re.sub(rf"\b{re.escape(short)}", full, q)
    q = q.replace("'s", "")
    q = re.sub(r"[^\w\s]|_", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def _strip_fillers(q: str) -> str:
    changed = True
    while changed and q:
        changed = False
        for lead in _LEAD:
            if q == lead or q.startswith(lead + " "):
                q = q[len(lead) :].strip()
                changed = True
        trimmed = _TRAIL.sub("", q).strip()
        if trimmed != q:
            q = trimmed
            changed = True
    return q


def _one(part: str) -> str | None:
    for fact in FACTS:
        if _COMPILED[fact].fullmatch(part):
            return fact
    return None


def recognise(question: str) -> tuple[str, ...] | None:
    """Decision 11: the facts asked, in the order asked, when the whole question (after normalising and the fixed
    fillers) matches one frame or two frames joined by "and"; otherwise None (the question goes to the model)."""
    q = _strip_fillers(normalise(question))
    if not q:
        return None
    one = _one(q)
    if one:
        return (one,)
    words = q.split(" ")
    for i, w in enumerate(words):
        if w != "and" or i == 0 or i == len(words) - 1:
            continue
        left, right = _one(" ".join(words[:i])), _one(" ".join(words[i + 1 :]))
        if left and right:
            return (left,) if left == right else (left, right)
    return None


# ------------------------------------------------------------------------------------------------ wording helpers


def plain_date(d: date | None) -> str:
    """The portal's form: 05 Nov 2026."""
    return d.strftime("%d %b %Y") if d is not None else "-"


def hearing_date(d: date, today: date) -> str:
    """A hearing date with its weekday, and "(today)" or "(tomorrow)" on the IST day (the `HearingDate` badge's)."""
    out = f"{d.strftime('%A')} {plain_date(d)}"
    if d == today:
        out += " (today)"
    elif d == today + timedelta(days=1):
        out += " (tomorrow)"
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ------------------------------------------------------------------------------------------------ next hearing


@dataclass(frozen=True)
class NextHearing:
    """Decision 13: the court's date and purpose (the header), the next date from orders with its source row (the
    Overview card: order-read or manual, never a pending suggestion), the disposal, and the answer in words."""

    court_date: date | None
    purpose: str | None
    source: str | None  # order_specific | order_period | manual | None
    next_date: date | None
    order_date: date | None
    created_at: datetime | None
    disposed: bool
    disposal_date: date | None
    lines: tuple[str, ...] = field(default_factory=tuple)

    @property
    def from_order(self) -> bool:
        return self.source in ORDER_SOURCES and self.next_date is not None


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def next_hearing(session: Session, case: Case, *, today: date | None = None) -> NextHearing:
    """Decision 13, before row 199: the two values the case page shows today, stated without choosing between them.
    Row 199 replaces the reading with its shared next-hearing reader."""
    from aslms.services import next_dates  # the case page's own reader (lazy: next_dates is a large module)

    today = today or clock.today_ist()
    row = next_dates.effective_for_case(session, case)
    source = _value(row.source) if row is not None else None
    order_date = None
    if row is not None and row.order_id is not None:
        order_date = session.scalar(select(Order.order_date).where(Order.id == row.order_id))
    created = row.created_at if row is not None else None
    nh = NextHearing(
        court_date=case.next_hearing_date,
        purpose=(case.next_purpose or "").strip() or None,
        source=source,
        next_date=row.next_date if row is not None else None,
        order_date=order_date,
        created_at=created,
        disposed=_value(case.status) == CaseStatus.DISPOSED.value,
        disposal_date=case.disposal_date,
    )
    return NextHearing(**{**nh.__dict__, "lines": tuple(_next_lines(nh, today))})


def _origin(nh: NextHearing, *, read: bool = False) -> str:
    """Where the next date from orders came from: "from the order of <date>" ("read from" in the comparison), or for
    a manual date "entered in ASLMS on <created date>"."""
    if nh.source == NextDateSource.MANUAL.value:
        made = clock.today_ist(nh.created_at) if nh.created_at is not None else None
        return f"entered in ASLMS on {plain_date(made)}"
    verb = "read from" if read else "from"
    if nh.order_date is not None:
        return f"{verb} the order of {plain_date(nh.order_date)}"
    return f"{verb} an order"


def _next_lines(nh: NextHearing, today: date) -> list[str]:
    if nh.disposed:
        if nh.disposal_date is not None:
            return [
                f"The case was disposed of on {plain_date(nh.disposal_date)}; no further hearing is listed [S1]."
            ]
        return ["The case has been disposed of; no further hearing is listed [S1]."]
    court, other = nh.court_date, nh.next_date
    court_ahead = court is not None and court >= today
    other_ahead = other is not None and other >= today
    if court is not None and other is not None and court == other and court_ahead:
        return [f"Next hearing: {hearing_date(court, today)} [S1]."]
    if court_ahead and (other is None or other == court):
        purpose = f", for {nh.purpose}" if nh.purpose else ""
        return [f"Next hearing: {hearing_date(court, today)}{purpose} (the court's record) [S1]."]
    if other is not None and not court_ahead:
        when = hearing_date(other, today) if other_ahead else f"{plain_date(other)}, which has passed"
        lines = [f"Next date {_origin(nh)}: {when} [S1]."]
        if court is not None and court != other:
            lines.append(f"The court's own record still shows {plain_date(court)}, which has passed [S1].")
        return lines
    if court_ahead and other is not None:
        if other_ahead:
            said = f"is {hearing_date(other, today)}"
        else:
            said = f"was {plain_date(other)}, which has passed"
        return [
            f"The court's record shows {hearing_date(court, today)}. "
            f"The next date {_origin(nh, read=True)} {said} [S1]."
        ]
    if court is not None:
        return [
            f"The last date the court fixed was {plain_date(court)}, which has passed; no later date is held yet [S1]."
        ]
    return ["No next hearing date is held for this case yet [S1]."]


# ------------------------------------------------------------------------------------------------ the other facts


def facts_of(session: Session, case: Case) -> dict[str, Any]:
    """Decision 12's values, read from the court tables the case page shows."""
    parties = session.execute(
        select(CaseParty.role, CaseParty.name)
        .where(CaseParty.case_id == case.id, CaseParty.is_current.is_(True))
        .order_by(CaseParty.role, CaseParty.party_no)
    ).all()
    by_role: dict[str, list[str]] = {PartyRole.PETITIONER.value: [], PartyRole.RESPONDENT.value: []}
    for role, name in parties:
        by_role.setdefault(_value(role), []).append(name)
    advocates = session.execute(
        select(CaseAdvocate.side, CaseAdvocate.name_as_listed)
        .where(CaseAdvocate.case_id == case.id, CaseAdvocate.is_current.is_(True))
        .order_by(CaseAdvocate.side, CaseAdvocate.created_at, CaseAdvocate.name_as_listed)
    ).all()
    by_side: dict[str, list[str]] = {AdvocateSide.PETITIONER.value: [], AdvocateSide.RESPONDENT.value: []}
    for side, name in advocates:
        if name and name not in by_side.setdefault(_value(side), []):
            by_side[_value(side)].append(name)
    last = session.execute(
        select(Order.order_date, Order.order_no)
        .where(Order.case_id == case.id)
        .order_by(Order.order_date.desc(), Order.order_no.desc())
        .limit(1)
    ).first()
    bench_text = session.scalar(
        select(CaseHearing.bench_text)
        .where(
            CaseHearing.case_id == case.id,
            CaseHearing.bench_text.is_not(None),
            func.btrim(CaseHearing.bench_text) != "",
        )
        .order_by(CaseHearing.business_date.desc().nulls_last(), CaseHearing.purpose)
        .limit(1)
    )
    return {
        "petitioner_summary": (case.petitioner_summary or "").strip() or None,
        "respondent_summary": (case.respondent_summary or "").strip() or None,
        "petitioners": by_role[PartyRole.PETITIONER.value],
        "respondents": by_role[PartyRole.RESPONDENT.value],
        "pet_advocate": (case.pet_advocate or "").strip() or None,
        "res_advocate": (case.res_advocate or "").strip() or None,
        "pet_advocates": by_side[AdvocateSide.PETITIONER.value],
        "res_advocates": by_side[AdvocateSide.RESPONDENT.value],
        "status": _value(case.status),
        "disposal_date": case.disposal_date,
        "disposal_nature": (case.disposal_nature or "").strip() or None,
        "last_order": {"order_date": last[0], "order_no": last[1]} if last else None,
        "coram": (case.coram or "").strip() or None,
        "bench_name": (case.bench_name or "").strip() or None,
        "bench_text": (bench_text or "").strip() or None,
    }


def _side(summary: str | None, names: list[str]) -> str | None:
    if summary:
        return summary
    if not names:
        return None
    rest = len(names) - 1
    return names[0] + (f" and {_plural(rest, 'other')}" if rest else "")


def parties_lines(f: dict[str, Any]) -> list[str]:
    pet = _side(f["petitioner_summary"], f["petitioners"])
    res = _side(f["respondent_summary"], f["respondents"])
    if pet is None and res is None:
        return ["No parties are recorded in the court record for this case [S1]."]
    lines = [
        f"{pet or 'The petitioners are not recorded'} versus {res or 'the respondents are not recorded'} [S1]."
    ]
    p, r = len(f["petitioners"]), len(f["respondents"])
    if p or r:
        lines.append(
            f"{_plural(p, 'petitioner')} and {_plural(r, 'respondent')} are listed on the Parties tab [S1]."
        )
    return lines


def advocates_lines(f: dict[str, Any]) -> list[str]:
    pet = f["pet_advocate"] or ("; ".join(f["pet_advocates"]) or "none recorded")
    res = f["res_advocate"] or ("; ".join(f["res_advocates"]) or "none recorded")
    return [f"For the petitioners: {pet}. For the respondents: {res} [S1]."]


def status_lines(f: dict[str, Any]) -> list[str]:
    if f["status"] == CaseStatus.PENDING.value:
        return ["Pending [S1]."]
    if f["status"] == CaseStatus.DISPOSED.value:
        on = f" on {plain_date(f['disposal_date'])}" if f["disposal_date"] else ""
        nature = f", {f['disposal_nature']}" if f["disposal_nature"] else ""
        return [f"Disposed of{on}{nature} [S1]."]
    return ["The court record does not give the status yet [S1]."]


def last_order_lines(f: dict[str, Any]) -> list[str]:
    last = f["last_order"]
    if last is None:
        return ["No court order is held for this case yet [S1]."]
    return [f"The last order is dated {plain_date(last['order_date'])} (No. {last['order_no']}) [S1]."]


def bench_lines(f: dict[str, Any]) -> list[str]:
    if f["coram"]:
        name = f" ({f['bench_name']})" if f["bench_name"] else ""
        return [f"Before {f['coram']}{name} [S1]."]
    if f["bench_text"]:
        return [f"Before {f['bench_text']} [S1]."]
    return ["The court record does not name the bench yet [S1]."]


# ------------------------------------------------------------------------------------------------ the answer


@dataclass(frozen=True)
class FactAnswer:
    """The text (one paragraph per fact, in the order asked), the one Case Details citation as stored, and
    `model_info`."""

    text: str
    citation: dict[str, Any]
    info: dict[str, Any]


def citation(case_id: uuid.UUID) -> dict[str, Any]:
    """Decision 14: the one stored citation of a quick-fact answer."""
    return {
        "source_kind": "case_details",
        "label": LABEL,
        "cited": True,
        "case_id": str(case_id),
        "hearings": 0,
        "listings": 0,
        "compact": False,
    }


def answer(
    session: Session, case_id: uuid.UUID, facts: tuple[str, ...], *, today: date | None = None
) -> FactAnswer:
    """Decision 12: never raises for a missing value (it is said in words)."""
    today = today or clock.today_ist()
    case = session.get(Case, case_id)
    if case is None:
        raise LookupError("no such case")
    values = facts_of(session, case)
    paragraphs: list[str] = []
    for fact in facts:
        if fact == "next_hearing":
            lines = list(next_hearing(session, case, today=today).lines)
        elif fact == "parties":
            lines = parties_lines(values)
        elif fact == "advocates":
            lines = advocates_lines(values)
        elif fact == "status":
            lines = status_lines(values)
        elif fact == "last_order":
            lines = last_order_lines(values)
        elif fact == "bench":
            lines = bench_lines(values)
        else:  # pragma: no cover - recognise names only the six
            raise ValueError(f"unknown fact {fact}")
        paragraphs.append(" ".join(lines))
    return FactAnswer(
        text="\n\n".join(paragraphs),
        citation=citation(case.id),
        info={"engine": ENGINE, "facts": list(facts), "facts_version": FACTS_VERSION},
    )
