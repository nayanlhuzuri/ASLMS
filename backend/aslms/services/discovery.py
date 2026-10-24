"""Department discovery (design `department-discovery`, with the owner's decisions of 14 Oct 2026): the departments'
keywords and name patterns ticked "Search the court" are run through NAPIX Search by Party Name, year by year, in the
`discovery` lane of the fetch queue; the cases found are stored, their dossiers fetched and then scored by the
recommend-and-claim engine unchanged. Nothing here calls NAPIX directly: the runner hands the integration layer's
`NapixHighCourt` to `run_party_search`.

- A *term* is a distinct discoverable rule text (`discovery_terms`), shared by every department using it; its
  departments and its active state are derived live from the active discoverable rules (decision 2).
- One queue row per (term, registration year): kind `party_search`, ref `<est_code>|P|<reg_year>|<term>`
  (decision 3), pending cases only (decision 4).
- Automatic sweeps cover `DISCOVERY_FROM_YEAR` (2025) to the current year: a new term's first sweep at once
  (priority 43) and every active term weekly (42). Older years are searched only when a user asks for them on the
  Court search tab (`request_years`, 42), as often as they like and with no "searched before" warning (owner,
  14 Oct 2026). A manual sweep (`sweep`) needs `admin.data_load`. Both are audited
  `discovery.sweep`; system work is not (decision 11).
- The share of each quota window is enforced by the runner (decision 6); `summary` reports it for the Data collection
  screens only."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, false, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.core.errors import NapixInputError, NapixNotFound
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    DiscoveryHit,
    DiscoveryTerm,
    OfficeKeyword,
    OfficeNamePattern,
    PatternKind,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
)
from aslms.domain.reference import Permission
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access, napix_window, queue
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.load_policy import DISCOVERY_DOSSIER, DISCOVERY_FULL, DISCOVERY_RECENT, QueueOrigin

TERM_RE = re.compile(r"^[A-Z0-9 .,'&()/-]{3,200}$")
PEND_DISP = "P"  # decision 4: pending cases only
MIN_YEAR = 1950
MAX_REQUEST_YEARS = 30
MAX_LIMIT, DEFAULT_LIMIT = 200, 50
LATEST_FAILURES = 20
NEW_DAYS = 7
SWEEP_ACTION = "discovery.sweep"
TERM_STATUSES = ("active", "inactive", "all")
CASE_FILTERS = ("all", "pool", "recommended", "owned")


# ------------------------------------------------------------------------------------------------ errors


class DiscoveryError(ValueError):
    """Bad input (HTTP 400); `code` names it: `not_discoverable`, `not_a_term`, `bad_years`, `bad_input`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DiscoveryNotFound(LookupError):
    """No such term, or one the caller may not see (HTTP 404)."""


class DiscoveryConflict(Exception):
    """The state refuses the action (HTTP 409): `term_inactive` (with `extra`)."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


# ------------------------------------------------------------------------------------------------ terms


def _now() -> datetime:
    return datetime.now(UTC)


def discoverable(value: str | None, kind: PatternKind | str | None = None) -> bool:
    """Decision 1: a stored rule text of 3 to 200 characters of `[A-Z0-9 .,'&()/-]` (so nothing can alter the
    gateway's `k=v|k=v` input), and for a name pattern the kind `exact` or `prefix` (a regex is never sent)."""
    if kind is not None and PatternKind(kind) == PatternKind.REGEX:
        return False
    return bool(value) and bool(TERM_RE.match(value or ""))


def make_ref(est_code: str, reg_year: int, term: str) -> str:
    return f"{est_code}|{PEND_DISP}|{int(reg_year)}|{term}"


def parse_ref(ref: str) -> tuple[str, int, str]:
    """`<est_code>|P|<reg_year>|<term>` → (est_code, reg_year, term); ValueError when malformed."""
    parts = (ref or "").split("|", 3)
    if len(parts) != 4 or parts[1] != PEND_DISP or not parts[2].isdigit() or not TERM_RE.match(parts[3]):
        raise ValueError(f"not a party_search ref: {ref!r}")
    return parts[0], int(parts[2]), parts[3]


def sweep_years(today: date, from_year: int) -> list[int]:
    """The years of an automatic sweep: the current year down to `DISCOVERY_FROM_YEAR`, newest first (owner's
    decision 1 of 14 Oct 2026)."""
    return list(range(today.year, min(from_year, today.year) - 1, -1))


@dataclass(frozen=True)
class RuleRef:
    kind: str  # keyword | exact | prefix
    rule_id: uuid.UUID
    office: Office
    is_active: bool
    discover: bool


def _offices(session: Session) -> dict[uuid.UUID, Office]:
    return {o.id: o for o in session.scalars(select(Office)).all()}


def _department(office: Office | None, by_code: dict[str, Office]) -> Office | None:
    """The active Department-tier ancestor of an active office (the engine's rule, recommend-and-claim decision 1)."""
    if office is None or not office.is_active:
        return None
    parts = office.path.split("/")
    if len(parts) < 2:
        return None
    dept = by_code.get(parts[1])
    if dept is None or not dept.is_active or not access.is_department(dept):
        return None
    return dept


def _rules(
    session: Session, terms: list[str] | None = None, *, active_only: bool
) -> dict[str, list[RuleRef]]:
    """Rules ticked `discover` grouped by their text (only discoverable texts), optionally limited to `terms`."""
    offices = _offices(session)
    out: dict[str, list[RuleRef]] = {}
    kw = select(OfficeKeyword).where(OfficeKeyword.discover.is_(True))
    pt = select(OfficeNamePattern).where(
        OfficeNamePattern.discover.is_(True), OfficeNamePattern.kind != PatternKind.REGEX
    )
    if terms is not None:
        if not terms:
            return out
        kw = kw.where(OfficeKeyword.keyword.in_(terms))
        pt = pt.where(OfficeNamePattern.pattern.in_(terms))
    if active_only:
        kw = kw.where(OfficeKeyword.is_active.is_(True))
        pt = pt.where(OfficeNamePattern.is_active.is_(True))
    for row in session.scalars(kw).all():
        if discoverable(row.keyword) and row.office_id in offices:
            out.setdefault(row.keyword, []).append(
                RuleRef("keyword", row.id, offices[row.office_id], row.is_active, row.discover)
            )
    for row in session.scalars(pt).all():
        if discoverable(row.pattern, row.kind) and row.office_id in offices:
            out.setdefault(row.pattern, []).append(
                RuleRef(
                    PatternKind(row.kind).value, row.id, offices[row.office_id], row.is_active, row.discover
                )
            )
    return out


def _departments_of(rules: list[RuleRef], by_code: dict[str, Office]) -> list[Office]:
    seen: dict[uuid.UUID, Office] = {}
    for r in rules:
        if not r.is_active:
            continue
        dept = _department(r.office, by_code)
        if dept is not None:
            seen.setdefault(dept.id, dept)
    return sorted(seen.values(), key=lambda o: o.code)


def active_departments(session: Session, terms: list[str] | None = None) -> dict[str, list[Office]]:
    """Text → the departments of its active discoverable rules (office and Department-tier ancestor active); texts
    with none are left out (inactive)."""
    by_code = {o.code: o for o in _offices(session).values()}
    out: dict[str, list[Office]] = {}
    for term, rules in _rules(session, terms, active_only=True).items():
        depts = _departments_of(rules, by_code)
        if depts:
            out[term] = depts
    return out


def term_departments(session: Session, term: str) -> list[Office]:
    return active_departments(session, [term]).get(term, [])


def is_active(session: Session, term: str) -> bool:
    return bool(term_departments(session, term))


def ensure_term(session: Session, value: str) -> DiscoveryTerm:
    """Get or insert the term row (`ON CONFLICT (term) DO NOTHING`, then select)."""
    session.execute(
        pg_insert(DiscoveryTerm).values(term=value).on_conflict_do_nothing(index_elements=["term"])
    )
    return session.scalars(
        select(DiscoveryTerm).where(DiscoveryTerm.term == value).execution_options(populate_existing=True)
    ).one()


def _est(settings: Settings | None) -> str:
    from aslms.core.config import get_settings

    return (settings or get_settings()).napix_est_code


def enqueue_term(
    session: Session,
    term: DiscoveryTerm,
    years: list[int],
    priority: int,
    *,
    settings: Settings | None = None,
    requeue: bool = True,
) -> int:
    """One `party_search` row per year, newest first, in the discovery lane; a `done` row runs again with `requeue`,
    a pending one keeps its place. Returns the rows now pending."""
    est = _est(settings)
    n = 0
    for year in sorted(set(years), reverse=True):
        if queue.enqueue(
            session,
            FetchKind.PARTY_SEARCH,
            make_ref(est, year, term.term),
            priority,
            lane=FetchLane.DISCOVERY,
            requeue=requeue,
        ):
            n += 1
    return n


def on_rule_saved(
    session: Session,
    text_value: str,
    *,
    is_active_rule: bool,
    discover: bool,
    settings: Settings | None = None,
    today: date | None = None,
) -> int:
    """Called by `matching_rules` after a create, update, reactivate or `discover` change, in the same transaction:
    an active ticked rule makes its term exist and, when the term's first sweep was never queued and it is active,
    queues it (2025 to the current year, priority 43). Deactivating or unticking queues nothing: pending rows of a
    term left inactive end `skipped` when they run. Returns the rows queued."""
    if not (is_active_rule and discover and discoverable(text_value)):
        return 0
    term = ensure_term(session, text_value)
    if term.full_sweep_queued_at is not None or not is_active(session, term.term):
        return 0
    cfg = settings or _settings()
    n = enqueue_term(
        session,
        term,
        sweep_years(today or today_ist(), cfg.discovery_from_year),
        DISCOVERY_FULL,
        settings=cfg,
    )
    term.full_sweep_queued_at = _now()
    session.flush()
    return n


def _settings() -> Settings:
    from aslms.core.config import get_settings

    return get_settings()


def enqueue_weekly(
    session: Session, today: date | None = None, settings: Settings | None = None
) -> dict[str, int]:
    """The weekly job: every active term (its row created when missing) searched again for 2025 to the current year
    at priority 42, `done` rows revived. Inactive terms get nothing. Returns counts."""
    cfg = settings or _settings()
    years = sweep_years(today or today_ist(), cfg.discovery_from_year)
    now = _now()
    terms = rows = 0
    for value in sorted(active_departments(session)):
        term = ensure_term(session, value)
        rows += enqueue_term(session, term, years, DISCOVERY_RECENT, settings=cfg)
        term.recent_sweep_queued_at = now
        if term.full_sweep_queued_at is None:
            term.full_sweep_queued_at = now
        terms += 1
    session.flush()
    return {"terms": terms, "rows_queued": rows, "years": len(years)}


def _acting(session: Session, user: User | Member | None, permission: Permission) -> Member | None:
    """The caller's membership holding the function (the super admin's first); None for the CLI before a super admin
    exists (the `system` actor)."""
    if user is None:
        return None
    holders = [m for m in access.members(session, user) if m.holds(permission)]
    if not holders:
        raise access.Forbidden(f"{permission.value} is not enabled for you")
    holders.sort(key=lambda m: not m.is_super_admin)
    return holders[0]


def sweep(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    *,
    term_id: uuid.UUID | None = None,
    term_text: str | None = None,
    settings: Settings | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The manual sweep (decision 12, `admin.data_load`): one term or every active term, 2025 to the current year at
    priority 42. Audited `discovery.sweep`."""
    member = _acting(session, user, Permission.ADMIN_DATA_LOAD)
    cfg = settings or _settings()
    years = sweep_years(today or today_ist(), cfg.discovery_from_year)
    if term_id is not None or term_text is not None:
        if term_id is not None:
            term = session.get(DiscoveryTerm, term_id)
        else:
            from aslms.services.matching import normalise_term

            term = session.scalar(
                select(DiscoveryTerm).where(DiscoveryTerm.term == normalise_term(term_text))
            )
        if term is None:
            raise DiscoveryNotFound("no such discovery term")
        if not is_active(session, term.term):
            raise DiscoveryConflict("term_inactive", "no active rule of any department searches this term")
        terms = [term]
    else:
        terms = [ensure_term(session, v) for v in sorted(active_departments(session))]
    now = _now()
    rows = 0
    for term in terms:
        rows += enqueue_term(session, term, years, DISCOVERY_RECENT, settings=cfg)
        term.recent_sweep_queued_at = now
        if term.full_sweep_queued_at is None:
            term.full_sweep_queued_at = now
    session.flush()
    write_audit(
        session,
        access.actor_as(actor, member),
        SWEEP_ACTION,
        "discovery_term" if len(terms) == 1 and (term_id or term_text) else "discovery",
        terms[0].id if len(terms) == 1 and (term_id or term_text) else None,
        after={
            "scope": "term" if (term_id or term_text) else "all",
            "term_ids": [str(t.id) for t in terms],
            "years": [min(years), max(years)] if years else [],
            "rows_queued": rows,
        },
    )
    return {"terms": len(terms), "rows_queued": rows}


# ------------------------------------------------------------------------------------------------ visibility


def _scope_roots(session: Session, user: User | Member) -> list[Office] | None:
    """None for the super admin (everything); else the offices of the memberships holding `admin.keywords`."""
    if access.is_super_admin(user):
        return None
    return [m.office for m in access.holders_in(session, user, Permission.ADMIN_KEYWORDS)]


def _in_roots(office: Office, roots: list[Office] | None) -> bool:
    return roots is None or any(access.subtree_contains(r, office) for r in roots)


def _visible_rules(
    session: Session, user: User | Member, office: Office | None = None
) -> dict[str, list[RuleRef]]:
    """Ticked rules (active or not) in the caller's subtree, by text, narrowed to `office`'s subtree when given."""
    access.require(session, user, Permission.ADMIN_KEYWORDS)
    roots = _scope_roots(session, user)
    out: dict[str, list[RuleRef]] = {}
    for term, rules in _rules(session, active_only=False).items():
        keep = [
            r
            for r in rules
            if _in_roots(r.office, roots) and (office is None or access.subtree_contains(office, r.office))
        ]
        if keep:
            out[term] = keep
    return out


def _visible_term(session: Session, user: User | Member, term_id: uuid.UUID) -> DiscoveryTerm:
    term = session.get(DiscoveryTerm, term_id)
    if term is None or term.term not in _visible_rules(session, user):
        raise DiscoveryNotFound("no such discovery term")
    return term


def _clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    lim = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    return lim, max(0, int(offset or 0))


def _year_counts(session: Session, terms: list[str]) -> dict[str, dict[str, int]]:
    out = {t: {"done": 0, "waiting": 0, "failed": 0} for t in terms}
    if not terms:
        return out
    term_col = func.split_part(FetchQueueItem.ref, "|", 4)
    for term, status, n in session.execute(
        select(term_col, FetchQueueItem.status, func.count())
        .where(FetchQueueItem.kind == FetchKind.PARTY_SEARCH, term_col.in_(terms))
        .group_by(term_col, FetchQueueItem.status)
    ).all():
        st = FetchStatus(status)
        key = {
            FetchStatus.DONE: "done",
            FetchStatus.PENDING: "waiting",
            FetchStatus.RUNNING: "waiting",
            FetchStatus.FAILED: "failed",
        }.get(st)
        if key and term in out:
            out[term][key] += int(n)
    return out


def terms_view(
    session: Session,
    user: User | Member,
    *,
    office: Office | None = None,
    status: str = "active",
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """`GET /admin/discovery/terms`: the terms with at least one ticked rule in the caller's subtree (the super admin
    sees all); rules and departments outside the subtree are not listed."""
    if status not in TERM_STATUSES:
        raise DiscoveryError("bad_input", "status is active, inactive or all")
    visible = _visible_rules(session, user, office)
    roots = _scope_roots(session, user)
    rows = (
        session.scalars(select(DiscoveryTerm).where(DiscoveryTerm.term.in_(list(visible)))).all()
        if visible
        else []
    )
    active = active_departments(session, [r.term for r in rows])
    items = []
    for t in sorted(rows, key=lambda r: r.term):
        is_on = t.term in active
        if (status == "active" and not is_on) or (status == "inactive" and is_on):
            continue
        items.append((t, is_on))
    total = len(items)
    lim, off = _clamp(limit, offset)
    page = items[off : off + lim]
    counts = _year_counts(session, [t.term for t, _ in page])
    since = _now() - timedelta(days=NEW_DAYS)
    new_counts = (
        dict(
            session.execute(
                select(DiscoveryHit.term_id, func.count())
                .where(
                    DiscoveryHit.term_id.in_([t.id for t, _ in page]), DiscoveryHit.first_found_at >= since
                )
                .group_by(DiscoveryHit.term_id)
            ).all()
        )
        if page
        else {}
    )
    out = []
    for t, is_on in page:
        depts = [d.code for d in active.get(t.term, []) if _in_roots(d, roots)]
        out.append(
            {
                "id": t.id,
                "term": t.term,
                "active": is_on,
                "departments": depts,
                "rules": [
                    {
                        "kind": r.kind,
                        "rule_id": r.rule_id,
                        "office_code": r.office.code,
                        "is_active": r.is_active,
                    }
                    for r in visible[t.term]
                ],
                "years": counts.get(t.term, {"done": 0, "waiting": 0, "failed": 0}),
                "last_searched_at": t.last_searched_at,
                "cases_found": t.cases_found,
                "found_last_7_days": int(new_counts.get(t.id, 0)),
                "full_sweep_queued_at": t.full_sweep_queued_at,
                "recent_sweep_queued_at": t.recent_sweep_queued_at,
            }
        )
    return out, total


def term_cases(
    session: Session,
    user: User | Member,
    term_id: uuid.UUID,
    *,
    only: str = "all",
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """`GET /admin/discovery/terms/{id}/cases`: the cases a term found, as summaries (court-public fields), with the
    owner, the caller's departments' active recommendation (every department's with `cases.view_all`) and
    `claimable` by the claim rule. 404 for a term without a ticked rule in the caller's subtree."""
    from aslms.services import inbox
    from aslms.services.ownership import claimable_condition, shown_recommendations_condition

    if only not in CASE_FILTERS:
        raise DiscoveryError("bad_input", "only is all, pool, recommended or owned")
    term = _visible_term(session, user, term_id)
    shown = shown_recommendations_condition(session, user)
    stmt = (
        select(Case, DiscoveryHit, claimable_condition(session, user).label("claimable"))
        .join(DiscoveryHit, DiscoveryHit.case_id == Case.id)
        .where(DiscoveryHit.term_id == term.id, Case.merged_into_case_id.is_(None))
    )
    if only == "pool":
        stmt = stmt.where(inbox.never_owned())
    elif only == "owned":
        stmt = stmt.where(~inbox.never_owned())
    elif only == "recommended":
        stmt = stmt.where(exists().where(Recommendation.case_id == Case.id, shown))
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    lim, off = _clamp(limit, offset)
    rows = session.execute(
        stmt.order_by(DiscoveryHit.last_found_at.desc(), Case.id).limit(lim).offset(off)
    ).all()
    cases = [r[0] for r in rows]
    ids = [c.id for c in cases]
    summ = inbox.summaries(session, cases)
    owners = inbox.primary_codes(session, ids)
    recs: dict[uuid.UUID, dict[str, Any]] = {}
    if ids:
        for rec, code in session.execute(
            select(Recommendation, Office.code)
            .join(Office, Office.id == Recommendation.office_id)
            .where(Recommendation.case_id.in_(ids), shown)
            .order_by(Recommendation.score.desc(), Office.code)
        ).all():
            recs.setdefault(
                rec.case_id,
                {
                    "office_code": code,
                    "band": getattr(rec.band, "value", rec.band),
                    "score": float(rec.score),
                    "status": getattr(rec.status, "value", rec.status),
                },
            )
    items = [
        {
            "case": summ[c.id],
            "reg_year": hit.reg_year,
            "first_found_at": hit.first_found_at,
            "last_found_at": hit.last_found_at,
            "owner_office_code": owners.get(c.id),
            "recommendation": recs.get(c.id),
            "claimable": bool(claimable),
        }
        for c, hit, claimable in rows
    ]
    return items, total


def found_for_condition(session: Session, office: Office) -> Any:
    """The pool filter `found_for` (decision 10) over `Case`: found by a term that equals an active ticked rule in the
    department's subtree."""
    texts = [
        term
        for term, rules in _rules(session, active_only=True).items()
        if any(access.subtree_contains(office, r.office) and r.office.is_active for r in rules)
    ]
    if not texts:
        return false()
    return exists(
        select(DiscoveryHit.id)
        .join(DiscoveryTerm, DiscoveryTerm.id == DiscoveryHit.term_id)
        .where(DiscoveryHit.case_id == Case.id, DiscoveryTerm.term.in_(texts))
    )


# ------------------------------------------------------------------------------------------------ a user's request


def _request_years(values: Any, today: date) -> list[int]:
    try:
        years = sorted({int(v) for v in (values or [])}, reverse=True)
    except (TypeError, ValueError) as exc:
        raise DiscoveryError("bad_years", "years are whole numbers") from exc
    if not years:
        raise DiscoveryError("bad_years", "choose at least one year")
    if len(years) > MAX_REQUEST_YEARS:
        raise DiscoveryError("bad_years", f"at most {MAX_REQUEST_YEARS} years at a time")
    if years[-1] < MIN_YEAR or years[0] > today.year:
        raise DiscoveryError("bad_years", f"years run from {MIN_YEAR} to {today.year}")
    return years


def request_years(
    session: Session,
    actor: Actor,
    user: User | Member,
    *,
    name: str,
    years: Any,
    force: bool = False,
    settings: Settings | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The owner's decision 2 of 14 Oct 2026: a user on the Court search tab asks for a name and the year or years
    to search (older years included). The name must be one of the caller's terms: an active rule ticked "Search the
    court" in their subtree (any active term for the super admin). The owner's decision of 14 Oct 2026: the user
    searches as often as they like, with no "searched before" warning; a year already searched runs again and one
    still waiting keeps its place (`force` is accepted and ignored, for older clients). The rows go into the
    discovery lane at priority 42, within its share; no call counts are returned. Audited `discovery.sweep`
    (scope `request`)."""
    from aslms.services.matching import normalise_term

    access.require(session, user, Permission.ADMIN_KEYWORDS)
    member = _acting(session, user, Permission.ADMIN_KEYWORDS)
    today = today or today_ist()
    value = normalise_term(name)
    if not discoverable(value):
        raise DiscoveryError(
            "not_discoverable", "a name is 3 to 200 letters, digits, spaces and . , ' & ( ) / - only"
        )
    wanted = _request_years(years, today)
    roots = _scope_roots(session, user)
    rules = _rules(session, [value], active_only=True).get(value, [])
    by_code = {o.code: o for o in _offices(session).values()}
    mine = [r for r in rules if _in_roots(r.office, roots)]
    if not mine or not _departments_of(mine, by_code):
        raise DiscoveryError(
            "not_a_term",
            'add the name as a keyword or name pattern with "Search the court" ticked, then search its years',
        )
    term = ensure_term(session, value)
    rows = enqueue_term(session, term, wanted, DISCOVERY_RECENT, settings=settings)
    session.flush()
    write_audit(
        session,
        access.actor_as(actor, member),
        SWEEP_ACTION,
        "discovery_term",
        term.id,
        after={
            "scope": "request",
            "term_ids": [str(term.id)],
            "term": value,
            "years": wanted,
            "rows_queued": rows,
        },
    )
    return {"term_id": term.id, "term": value, "years": wanted, "queued": True}


# ------------------------------------------------------------------------------------------------ the handler


async def run_party_search(
    session: Session, hc: NapixHighCourt, court: Court, ref: str, origin: QueueOrigin | None = None
) -> tuple[dict[str, Any], bool]:
    """Decision 7: (1) a term without an active rule ends `skipped` with no call; (2) Search by Party Name through
    the integration layer (628 is a valid empty answer); (3) the rows are stored with source and origin `discovery`
    and the `ref_no` office of the term (its department when it has one, else `GOA`); rows without a valid CNR are
    counted, never stored; (4) each stored case is recorded in `discovery_hits`; (5) a discovery dossier (41) is
    queued for each stored case without one; (6) the term's counters. Writes no audit row."""
    from aslms.services.cases import ROOT_OFFICE
    from aslms.services.court_search import store_search_rows

    try:
        est, year, value = parse_ref(ref)
    except ValueError as exc:
        raise NapixInputError(str(exc), api="party_name") from exc
    if est != court.est_code:
        raise NapixInputError(f"the ref's court {est} is not {court.est_code}", api="party_name")
    term = session.scalar(select(DiscoveryTerm).where(DiscoveryTerm.term == value))
    depts = term_departments(session, value)
    if term is None or not depts:
        return {"term": value, "reg_year": year, "skipped": "no active rule searches this term"}, True
    try:
        rows = await hc.search_party(value, year, PEND_DISP)
    except NapixNotFound:
        rows = []
    ref_office = depts[0].code if len(depts) == 1 else ROOT_OFFICE
    report = store_search_rows(
        session,
        court,
        rows,
        source=FirstSeenSource.DISCOVERY,
        origin=RecommendationOrigin.DISCOVERY,
        ref_office=ref_office,
    )
    stored: list[Case] = []
    seen: set[uuid.UUID] = set()
    for case in report.cases:
        target = case
        if case.merged_into_case_id is not None:
            target = session.get(Case, case.merged_into_case_id) or case
        if target.id not in seen:
            seen.add(target.id)
            stored.append(target)
    now = _now()
    for case in stored:
        stmt = pg_insert(DiscoveryHit).values(term_id=term.id, case_id=case.id, reg_year=year)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["term_id", "case_id"], set_={"last_found_at": func.now()}
            )
        )
    queued = 0
    for case in stored:
        if case.cnr and case.last_full_refresh_at is None and case.merged_into_case_id is None:
            if queue.enqueue(
                session, FetchKind.DOSSIER, case.cnr, DISCOVERY_DOSSIER, lane=FetchLane.DISCOVERY
            ):
                queued += 1
    term.searches_done = (term.searches_done or 0) + 1
    term.last_searched_at = now
    term.cases_found = int(
        session.scalar(
            select(func.count(func.distinct(DiscoveryHit.case_id))).where(DiscoveryHit.term_id == term.id)
        )
        or 0
    )
    session.flush()
    return {
        "term": value,
        "reg_year": year,
        "rows": len(rows),
        "stored": len(stored),
        "created": report.created,
        "unmatched": len(report.unmatched),
        "dossiers_queued": queued,
    }, False


# ------------------------------------------------------------------------------------------------ the console block


def _share_start(window: napix_window.WindowState, now: datetime) -> datetime:
    return window.started_at or (now - timedelta(seconds=3600))


def discovery_calls(session: Session, window: napix_window.WindowState, now: datetime | None = None) -> int:
    """Discovery-lane calls since the window's start (the last 3,600 s when the window is unknown): decision 6."""
    now = now or _now()
    return int(
        napix_window.calls_since(session, _share_start(window, now), lane_split=True)["by_lane"].get(
            "discovery", 0
        )
    )


def summary(session: Session, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    """`GET /admin/discovery` (the Data collection screens only): the settings, the window's discovery calls and the
    share left, discovery-lane queue rows by kind, terms, cases found and created, the latest failures. System
    figures only, no case data."""
    from aslms.services.napix_window import to_ist

    now = now or _now()
    window = napix_window.current(session, settings, now)
    used = discovery_calls(session, window, now)
    q = FetchQueueItem
    lane = q.lane == FetchLane.DISCOVERY
    by_kind = {
        k: {"pending": 0, "waiting": 0, "running": 0, "failed": 0}
        for k in ("party_search", "dossier", "order_pdf")
    }
    future = and_(q.status == FetchStatus.PENDING, q.not_before.isnot(None), q.not_before > now)
    for kind, pending, waiting, running, failed in session.execute(
        select(
            q.kind,
            func.count().filter(q.status == FetchStatus.PENDING),
            func.count().filter(future),
            func.count().filter(q.status == FetchStatus.RUNNING),
            func.count().filter(q.status == FetchStatus.FAILED),
        )
        .where(lane)
        .group_by(q.kind)
    ).all():
        key = getattr(kind, "value", kind)
        if key in by_kind:
            by_kind[key] = {
                "pending": int(pending),
                "waiting": int(waiting),
                "running": int(running),
                "failed": int(failed),
            }
    term_rows = session.scalars(select(DiscoveryTerm.term)).all()
    active = active_departments(session, list(term_rows))
    latest = [
        {
            "kind": getattr(r.kind, "value", r.kind),
            "ref": r.ref,
            "last_error": r.last_error,
            "finished_at": to_ist(r.finished_at),
        }
        for r in session.scalars(
            select(q)
            .where(lane, q.status == FetchStatus.FAILED)
            .order_by(q.finished_at.desc().nulls_last(), q.id.desc())
            .limit(LATEST_FAILURES)
        ).all()
    ]
    return {
        "settings": {"share": settings.napix_discovery_share, "from_year": settings.discovery_from_year},
        "window": {
            "status": window.status,
            "started_at": to_ist(window.started_at),
            "next_reset_at": to_ist(window.next_reset_at),
            "discovery_calls": used,
            "share_left": max(0, settings.napix_discovery_share - used),
        },
        "queue": {"by_kind": by_kind},
        "terms": {"active": len(active), "inactive": len(term_rows) - len(active)},
        "cases": {
            "found": int(session.scalar(select(func.count(func.distinct(DiscoveryHit.case_id)))) or 0),
            "created_by_discovery": int(
                session.scalar(
                    select(func.count()).where(Case.first_seen_source == FirstSeenSource.DISCOVERY)
                )
                or 0
            ),
            "recommended_from_discovery": int(
                session.scalar(
                    select(func.count()).where(
                        Recommendation.origin == RecommendationOrigin.DISCOVERY,
                        Recommendation.status == RecommendationStatus.RECOMMENDED,
                    )
                )
                or 0
            ),
        },
        "last_searched_at": to_ist(session.scalar(select(func.max(DiscoveryTerm.last_searched_at)))),
        "latest_failures": latest,
    }


def rule_discovery(session: Session, value: str, discover: bool) -> dict[str, Any] | None:
    """The `discovery` block of a rule's API item: its term's id, last search and cases found, when it has one."""
    if not discover:
        return None
    term = session.scalar(select(DiscoveryTerm).where(DiscoveryTerm.term == value))
    if term is None:
        return None
    return {"term_id": term.id, "last_searched_at": term.last_searched_at, "cases_found": term.cases_found}


__all__ = [
    "TERM_RE",
    "DiscoveryConflict",
    "DiscoveryError",
    "DiscoveryNotFound",
    "active_departments",
    "discoverable",
    "enqueue_term",
    "enqueue_weekly",
    "ensure_term",
    "found_for_condition",
    "is_active",
    "make_ref",
    "on_rule_saved",
    "parse_ref",
    "request_years",
    "run_party_search",
    "summary",
    "sweep",
    "sweep_years",
    "term_cases",
    "term_departments",
    "terms_view",
]
