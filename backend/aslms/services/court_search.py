"""Search the court and fetch a found case (design `cases-api`, decisions 9–14), through the integration
layer only (`aslms.integration.napix`). Shared with the queue runner: `fetch_dossier` and `resolve_cnr` apply
a dossier the same way whether the queue or a user asked.

- `guard`: the switch (`NAPIX_ENABLED` and credentials), the quota floor (`NAPIX_SEARCH_FLOOR` against the
  remaining count of the detected quota window, `services/napix_window.py`; design `napix-window`, decision 6) and
  the per-user limit (`NAPIX_SEARCH_PER_USER_HOUR` audit rows `case.search_court` / `case.fetch_court` in the last
  hour).
- `search_court`: by CNR (held with a dossier → local, no call; else Search by CNR and the dossier), by case
  number (Search by Case Number, every row stored, the exact row's dossier fetched), by party name (every row
  stored, no dossier — the user fetches the one they need). Rows whose `cino` is not a CNR are returned as
  `unmatched` and never stored: no fabricated identifier.
- `fetch_court`: the dossier of a found case; a provisional case without a CNR is resolved through Search by
  Case Number first (the CNR comes from the court, never invented).
Every call is audited with its outcome and the recorder's `napix_call_log` rows are flushed before the router
commits — also before an HTTP error is raised, so failures are recorded, never lost. The router's recorder carries
the caller's id, and the order PDFs a person's search queues carry them as `requested_by` (design `napix-window`,
decision 9)."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.core.errors import IntegrationError, NapixInputError, NapixNotFound, NapixProtocolError
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import CaseType, Court
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchLane
from aslms.domain.org import User
from aslms.domain.ownership import RecommendationOrigin
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import case_dedupe, matching, napix_window
from aslms.services.audit import Actor, write_audit
from aslms.services.cases import ApplyReport, apply_dossier, get_or_create_case, refresh_search_vector
from aslms.services.load_policy import QueueOrigin
from aslms.services.napix_store import NapixRecorder
from aslms.services.napix_values import as_int, as_text, case_no_text
from aslms.services.orders import enqueue_order_pdfs

CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")
# letters, digits, spaces and the punctuation seen in party names (DR., M/S, S.K. & CO., ORS.); never `|` or `=`,
# which would add or change a pair in the gateway's `k=v|k=v` request
PARTY_NAME_RE = re.compile(r"^[A-Za-z0-9 .,'&()/-]+$")
SEARCH_ACTIONS = ("case.search_court", "case.fetch_court")
# a person's search: the order PDFs it finds are queued in the request lane (design data-load-console, decision 1)
REQUEST_ORIGIN = QueueOrigin(FetchLane.REQUEST)


def request_origin(user: User | None) -> QueueOrigin:
    """The request origin of a person's search, carrying them as `requested_by` (design napix-window, decision 9)."""
    return QueueOrigin(FetchLane.REQUEST, requested_by=napix_window.user_id_of(user))


MIN_PARTY_NAME = 3
MIN_YEAR = 1950


# ------------------------------------------------------------------------------------------------ errors


class CourtSearchError(ValueError):
    """Bad input (HTTP 400)."""


class CourtSearchFailure(Exception):
    """The court could not be searched now; `code` names why and `http_status` how to answer."""

    http_status = 503

    def __init__(self, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


class CourtSearchUnavailable(CourtSearchFailure):
    """`napix_off` / `napix_budget` (503), `napix_unavailable` (502), `napix_timeout` (504)."""

    STATUS = {"napix_off": 503, "napix_budget": 503, "napix_unavailable": 502, "napix_timeout": 504}

    def __init__(self, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(code, message, retry_after=retry_after)
        self.http_status = self.STATUS.get(code, 503)


class SearchLimit(CourtSearchFailure):
    """The caller used their hourly court searches (429 `search_limit`)."""

    http_status = 429

    def __init__(self, retry_after: int):
        super().__init__("search_limit", "hourly court-search limit reached", retry_after=retry_after)


class AlreadyFetched(Exception):
    """The case already has a dossier (409 `already_fetched`; re-fetching is `admin.napix_refetch`)."""


class NotFoundAtCourt(Exception):
    """The provisional case's number is unknown to the court (404 `not_found_at_court`)."""


# ------------------------------------------------------------------------------------------------ results


@dataclass
class DossierFetch:
    case: Case
    report: ApplyReport
    order_pdfs_queued: int


@dataclass
class StoreReport:
    cases: list[Case] = field(default_factory=list)
    created: int = 0
    unmatched: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CourtSearchResult:
    source: str  # local | court
    calls: int
    created: int
    cases: list[Case]
    unmatched: list[dict[str, Any]]
    outcome: str


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ guard


def user_searches_last_hour(session: Session, user: User) -> tuple[int, datetime | None]:
    since = _now() - timedelta(hours=1)
    n, oldest = session.execute(
        select(func.count(), func.min(AuditLog.created_at)).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action.in_(SEARCH_ACTIONS),
            AuditLog.created_at >= since,
        )
    ).one()
    return int(n or 0), oldest


def guard(session: Session, user: User, settings: Settings, now: datetime | None = None) -> None:
    """Decision 13: refuses before any call; a refused search writes nothing. The quota floor reads the detected
    window (design napix-window, decision 6): refused when its remaining count is known and below
    `NAPIX_SEARCH_FLOOR`, with `retry_after` to the expected reset plus the margin (or one probe interval)."""
    if not settings.napix_configured:
        raise CourtSearchUnavailable("napix_off", "court search is switched off on this server")
    now = now or _now()
    window = napix_window.current(session, settings, now)
    remaining = window.remaining
    if remaining is not None and remaining < settings.napix_search_floor:
        raise CourtSearchUnavailable(
            "napix_budget",
            f"the court gateway's hourly quota is nearly spent ({remaining} calls left)",
            retry_after=window.retry_after(now),
        )
    n, oldest = user_searches_last_hour(session, user)
    if n >= settings.napix_search_per_user_hour:
        wait = 3600
        if oldest is not None:
            wait = max(1, int((oldest + timedelta(hours=1) - _now()).total_seconds()))
        raise SearchLimit(wait)


# ------------------------------------------------------------------------------------------------ shared fetch


def court_for(session: Session, est_code: str) -> Court:
    court = session.scalar(select(Court).where(Court.est_code == est_code))
    if court is None:
        raise RuntimeError(f"court {est_code} is not seeded")
    return court


async def fetch_dossier(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    cnr: str,
    *,
    source: FirstSeenSource,
    origin: QueueOrigin | None = None,
) -> DossierFetch:
    """Search by CNR → the court's dossier → get or create the case → `apply_dossier` → order PDFs queued.
    The case row is created only after the court has answered with a dossier for that very CNR, so a CNR the
    court does not know (or a gateway failure) never leaves a case behind. An empty dossier raises
    `NapixNotFound` (the queue records it as skipped, the API as `not_found`); a dossier labelled with another
    CNR raises `NapixProtocolError`. A CNR not held yet first looks for a provisional row with the dossier's number
    and adopts it (design `data-load-console`, decision 13); the order PDFs take the lane of `origin`, and the
    duplicate rules run for the case afterwards (decision 16)."""
    cnr = cnr.strip().upper()
    data = await hc.case_by_cnr(cnr)
    cino = as_text(data.get("cino"), 16) if data else None
    if not cino:
        raise NapixNotFound(f"empty dossier for {cnr}", api="cnr")
    if cino.upper() != cnr:
        raise NapixProtocolError(f"dossier asked for {cnr} is labelled {cino}", api="cnr")
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    if case is None:
        case = _adopt_provisional(session, court, cnr, data)
    if case is None:
        case, _ = get_or_create_case(session, court, cnr=cnr, case_no=None, source=source)
    report = apply_dossier(session, case, data)
    queued = enqueue_order_pdfs(session, case, origin)
    case_dedupe.check_cases(session, [case.id])
    case = session.get(Case, report.case_id)
    return DossierFetch(case, report, queued)


def _adopt_provisional(session: Session, court: Court, cnr: str, data: dict[str, Any]) -> Case | None:
    """The provisional row (no CNR, not merged) with the dossier's case number takes the CNR, under the number
    lock; None when there is none."""
    type_text = as_text(data.get("type_name_reg") or data.get("type_name"), 60)
    reg_no, reg_year = as_int(data.get("reg_no")), as_int(data.get("reg_year"))
    ctid = as_int(data.get("case_type_id"))
    type_id = None
    if ctid is not None:
        type_id = session.scalar(
            select(CaseType.id).where(CaseType.court_id == court.id, CaseType.case_type_code == ctid)
        )
    key = case_dedupe.number_key(
        court_id=court.id, case_type_text=type_text, case_type_id=type_id, reg_no=reg_no, reg_year=reg_year
    )
    if not key.usable:
        return None
    case_dedupe.lock_number(session, court.id, key)
    provisional = case_dedupe.find_provisional(session, court.id, key)
    if provisional is None:
        return None
    return case_dedupe.adopt(session, provisional, cnr)


def _case_type_by_short(session: Session, court: Court, short: str) -> CaseType | None:
    compact = re.sub(r"\s+", "", short.upper())
    for ct in session.scalars(select(CaseType).where(CaseType.court_id == court.id)).all():
        names = [ct.short_name or ""] + list(ct.aliases or [])
        if any(re.sub(r"\s+", "", n.upper()) == compact for n in names if n):
            return ct
    return None


async def resolve_cnr(session: Session, hc: NapixHighCourt, court: Court, case_no: str) -> str | None:
    """`WP(C)/4326/2025` → Search by Case Number with the type code from the case-type master → the CNR of
    the row whose number and year match, or None. The CNR always comes from the court."""
    parts = (case_no or "").rsplit("/", 2)
    if len(parts) != 3:
        return None
    short, no, year = parts[0].strip(), as_int(parts[1]), as_int(parts[2])
    ct = _case_type_by_short(session, court, short)
    if ct is None or no is None or year is None:
        return None
    rows = await hc.search_case_number(ct.case_type_code, no, year)
    for row in rows:
        cino = as_text(row.get("cino"), 16)
        if cino and as_int(row.get("reg_no")) == no and as_int(row.get("reg_year")) == year:
            return cino.upper()
    return None


# ------------------------------------------------------------------------------------------------ storing rows


def _fill_empty(case: Case, name: str, value: Any) -> bool:
    if value is None or value == "" or getattr(case, name) not in (None, ""):
        return False
    setattr(case, name, value)
    return True


def store_search_rows(session: Session, court: Court, rows: list[dict[str, Any]]) -> StoreReport:
    """Decision 9: rows with a valid `cino` become cases (`source = search`), the search fields fill only empty
    columns (a dossier is authoritative); then the vector is refreshed and the cases scored."""
    report = StoreReport()
    changed: list[uuid.UUID] = []
    seen: set[str] = set()
    for row in rows:
        cino = (as_text(row.get("cino"), 16) or "").upper()
        if not CNR_RE.match(cino):
            report.unmatched.append(
                {
                    k: as_text(row.get(k))
                    for k in ("type_name", "reg_no", "reg_year", "pet_name", "res_name")
                    if row.get(k) not in (None, "")
                }
            )
            continue
        if cino in seen:
            continue
        seen.add(cino)
        type_name = as_text(row.get("type_name"), 60)
        reg_no, reg_year = as_int(row.get("reg_no")), as_int(row.get("reg_year"))
        case_no = case_no_text(type_name, reg_no, reg_year)
        case, created = get_or_create_case(
            session, court, cnr=cino, case_no=case_no, source=FirstSeenSource.SEARCH
        )
        touched = created
        touched |= _fill_empty(case, "petitioner_summary", as_text(row.get("pet_name")))
        touched |= _fill_empty(case, "respondent_summary", as_text(row.get("res_name")))
        touched |= _fill_empty(case, "reg_no", reg_no)
        touched |= _fill_empty(case, "reg_year", reg_year)
        touched |= _fill_empty(case, "case_type_text", type_name)
        touched |= _fill_empty(case, "police_st_code", as_text(row.get("police_st_code"), 20))
        touched |= _fill_empty(case, "uniform_code", as_text(row.get("uniform_code"), 20))
        ctid = as_int(row.get("case_type_id"))
        if ctid is not None and case.case_type_id is None:
            ct = session.scalar(
                select(CaseType).where(CaseType.court_id == court.id, CaseType.case_type_code == ctid)
            )
            if ct is not None:
                case.case_type_id = ct.id
                touched = True
        report.cases.append(case)
        report.created += int(created)
        if touched:
            changed.append(case.id)
    session.flush()
    if changed:
        refresh_search_vector(session, changed)
        matching.score_cases(session, changed, origin=RecommendationOrigin.SEARCH)
    if report.cases:
        ids = [c.id for c in report.cases]
        case_dedupe.check_cases(session, ids)
        report.cases = [session.get(Case, i) for i in ids]
    return report


# ------------------------------------------------------------------------------------------------ the searches


def _resolve_case_type(session: Session, court: Court, value: str) -> CaseType:
    v = (value or "").strip()
    if not v:
        raise CourtSearchError("case_type is required")
    ct = None
    if v.isdigit():
        ct = session.scalar(
            select(CaseType).where(CaseType.court_id == court.id, CaseType.case_type_code == int(v))
        )
    if ct is None:
        ct = _case_type_by_short(session, court, v)
    if ct is None:
        raise CourtSearchError(f"unknown case type {value!r}")
    return ct


def _local_by_number(session: Session, court: Court, ct: CaseType, reg_no: int, reg_year: int) -> Case | None:
    compact = re.sub(r"\s+", "", (ct.short_name or "").upper())
    stmt = (
        select(Case)
        .where(
            Case.court_id == court.id,
            Case.reg_no == reg_no,
            Case.reg_year == reg_year,
            Case.last_full_refresh_at.isnot(None),
        )
        .order_by(Case.created_at)
    )
    for case in session.scalars(stmt).all():
        if case.case_type_id == ct.id or re.sub(r"\s+", "", (case.case_type_text or "").upper()) == compact:
            return case
    return None


def _failure_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "napix_timeout"
    if isinstance(exc, NapixInputError):
        return "napix_input"
    return "napix_unavailable"


def _finish(
    session: Session,
    actor: Actor,
    recorder: NapixRecorder,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    case_id: uuid.UUID | None,
    after: dict[str, Any],
) -> None:
    """Flush the call log and write the audit row (decision 14); the router commits, also before an error."""
    recorder.flush(session)
    write_audit(session, actor, action, entity_type, entity_id, after=after, case_id=case_id)
    session.flush()


async def search_court(
    session: Session,
    actor: Actor,
    user: User,
    request: dict[str, Any],
    *,
    hc: NapixHighCourt,
    recorder: NapixRecorder,
    settings: Settings,
    force: bool = False,
    audit_extra: dict[str, Any] | None = None,
) -> CourtSearchResult:
    """`force` (the data-load console, design `data-load-console` decision 10): by CNR the local short cut is
    skipped and the dossier fetched again; by case number the local match is skipped. `audit_extra` joins the
    audit row (`via`, `force`, `warned`)."""
    kind = request.get("kind")
    court = court_for(session, hc.est_code)
    origin = request_origin(user)
    calls_before = recorder.calls
    fields = {k: v for k, v in request.items() if k not in ("kind", "force")}
    audit: dict[str, Any] = {"kind": kind, "request": fields, **(audit_extra or {})}

    def done(result: CourtSearchResult) -> CourtSearchResult:
        audit.update(
            calls=result.calls, results=len(result.cases), created=result.created, outcome=result.outcome
        )
        _finish(
            session,
            actor,
            recorder,
            action="case.search_court",
            entity_type="napix_search",
            entity_id=None,
            case_id=result.cases[0].id if len(result.cases) == 1 else None,
            after=audit,
        )
        return result

    try:
        if kind == "cnr":
            result = await asyncio.wait_for(
                _search_cnr(session, hc, court, request["cnr"], force=force, origin=origin),
                settings.napix_search_timeout_seconds,
            )
        elif kind == "case_number":
            result = await asyncio.wait_for(
                _search_case_number(session, hc, court, request, force=force, origin=origin),
                settings.napix_search_timeout_seconds,
            )
        elif kind == "party":
            result = await asyncio.wait_for(
                _search_party(session, hc, court, request), settings.napix_search_timeout_seconds
            )
        else:
            raise CourtSearchError("kind is one of cnr, case_number, party")
    except NapixNotFound:
        return done(CourtSearchResult("court", recorder.calls - calls_before, 0, [], [], "not_found"))
    except (IntegrationError, TimeoutError) as exc:
        code = _failure_code(exc)
        audit.update(calls=recorder.calls - calls_before, results=0, created=0, outcome=f"failed:{code}")
        audit["error"] = str(exc)[:300]
        _finish(
            session,
            actor,
            recorder,
            action="case.search_court",
            entity_type="napix_search",
            entity_id=None,
            case_id=None,
            after=audit,
        )
        if code == "napix_input":
            raise CourtSearchError(str(exc)) from exc
        raise CourtSearchUnavailable(code, str(exc)) from exc
    result.calls = recorder.calls - calls_before
    return done(result)


async def _search_cnr(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    cnr: str,
    *,
    force: bool = False,
    origin: QueueOrigin = REQUEST_ORIGIN,
) -> CourtSearchResult:
    cnr = (cnr or "").strip().upper()
    if not CNR_RE.match(cnr):
        raise CourtSearchError("not a CNR: four letters and twelve digits")
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    if case is not None and case.last_full_refresh_at is not None and not force:
        return CourtSearchResult("local", 0, 0, [case], [], "ok")
    existed = case is not None
    fetched = await fetch_dossier(session, hc, court, cnr, source=FirstSeenSource.SEARCH, origin=origin)
    return CourtSearchResult("court", 0, int(not existed), [fetched.case], [], "ok")


async def _search_case_number(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    request: dict[str, Any],
    *,
    force: bool = False,
    origin: QueueOrigin = REQUEST_ORIGIN,
) -> CourtSearchResult:
    ct = _resolve_case_type(session, court, str(request.get("case_type", "")))
    reg_no, reg_year = as_int(request.get("reg_no")), as_int(request.get("reg_year"))
    if reg_no is None or reg_year is None or reg_year < MIN_YEAR or reg_year > _now().year + 1:
        raise CourtSearchError("reg_no and reg_year are required")
    local = _local_by_number(session, court, ct, reg_no, reg_year)
    if local is not None and not force:
        return CourtSearchResult("local", 0, 0, [local], [], "ok")
    rows = await hc.search_case_number(ct.case_type_code, reg_no, reg_year)
    report = store_search_rows(session, court, rows)
    exact = next(
        (
            c
            for c in report.cases
            if c.reg_no == reg_no and c.reg_year == reg_year and (force or c.last_full_refresh_at is None)
        ),
        None,
    )
    if exact is not None and exact.cnr:
        await fetch_dossier(session, hc, court, exact.cnr, source=FirstSeenSource.SEARCH, origin=origin)
    return CourtSearchResult("court", 0, report.created, report.cases, report.unmatched, "ok")


async def _search_party(
    session: Session, hc: NapixHighCourt, court: Court, request: dict[str, Any]
) -> CourtSearchResult:
    name = (request.get("name") or "").strip()
    reg_year = as_int(request.get("reg_year"))
    pend = str(request.get("pend_disp") or "P").strip()
    if len(name) < MIN_PARTY_NAME:
        raise CourtSearchError(f"name is at least {MIN_PARTY_NAME} characters")
    if not PARTY_NAME_RE.match(name):
        raise CourtSearchError("name: letters, digits, spaces and . , ' & ( ) / - only")
    if reg_year is None or reg_year < MIN_YEAR or reg_year > _now().year + 1:
        raise CourtSearchError("reg_year is required (1950 to the current year)")
    if pend not in ("P", "D", "both"):
        raise CourtSearchError("pend_disp is P, D or both")
    rows: list[dict[str, Any]] = []
    found_any = False
    for flag in ("P", "D") if pend == "both" else (pend,):
        try:
            rows.extend(await hc.search_party(name, reg_year, flag))
            found_any = True
        except NapixNotFound:
            continue
    if not found_any:
        raise NapixNotFound("no case for that party name", api="party_name")
    report = store_search_rows(session, court, rows)
    return CourtSearchResult("court", 0, report.created, report.cases, report.unmatched, "ok")


# ------------------------------------------------------------------------------------------------ fetch a found case


async def fetch_court(
    session: Session,
    actor: Actor,
    user: User,
    case: Case,
    *,
    hc: NapixHighCourt,
    recorder: NapixRecorder,
    settings: Settings,
) -> Case:
    """Decision 10: the dossier of a case without one; a provisional case is resolved by number first."""
    if case.last_full_refresh_at is not None:
        raise AlreadyFetched("the case already has a dossier")
    court = session.get(Court, case.court_id) or court_for(session, hc.est_code)
    calls_before = recorder.calls
    audit: dict[str, Any] = {"cnr": case.cnr, "case_no": case.case_no_text}

    def finish(outcome: str) -> None:
        audit.update(calls=recorder.calls - calls_before, outcome=outcome)
        _finish(
            session,
            actor,
            recorder,
            action="case.fetch_court",
            entity_type="case",
            entity_id=case.id,
            case_id=case.id,
            after=audit,
        )

    try:
        cnr = case.cnr
        if not cnr:
            cnr = await asyncio.wait_for(
                resolve_cnr(session, hc, court, case.case_no_text or ""),
                settings.napix_search_timeout_seconds,
            )
            if cnr is None:
                finish("not_found")
                raise NotFoundAtCourt("the court has no record of that case number")
            held = session.scalar(select(Case).where(Case.cnr == cnr))
            if held is not None and held.id != case.id:
                # the number resolves to a case already held: the provisional row is merged into it when it holds
                # no portal record (design data-load-console, decision 13), otherwise listed for review
                audit["resolved_to"] = held.ref_no
                try:
                    merged = case_dedupe.merge_provisional(session, case, held, actor)
                except case_dedupe.MergeStale as exc:
                    finish("changed")
                    raise AlreadyFetched(f"{exc}; open it again") from exc
                if isinstance(merged, case_dedupe.NeedsReview):
                    finish("resolved_elsewhere")
                    raise AlreadyFetched(f"that number is case {held.ref_no}, already held")
                audit["merged_into"] = held.ref_no
                if held.last_full_refresh_at is not None:
                    finish("merged")
                    return held
                case = held
            else:
                case_dedupe.adopt(session, case, cnr)
            audit["cnr"] = cnr
        fetched = await asyncio.wait_for(
            fetch_dossier(
                session, hc, court, cnr, source=FirstSeenSource.SEARCH, origin=request_origin(user)
            ),
            settings.napix_search_timeout_seconds,
        )
    except NapixNotFound:
        finish("not_found")
        raise NotFoundAtCourt("the court returned no dossier for that CNR") from None
    except (IntegrationError, TimeoutError) as exc:
        code = _failure_code(exc)
        audit["error"] = str(exc)[:300]
        finish(f"failed:{code}")
        if code == "napix_input":
            raise CourtSearchError(str(exc)) from exc
        raise CourtSearchUnavailable(code, str(exc)) from exc
    audit["order_pdfs_queued"] = fetched.order_pdfs_queued
    finish("ok")
    return fetched.case
