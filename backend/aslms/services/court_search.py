"""Search the court and fetch a found case (design `cases-api`, decisions 9–14), through the integration
layer only (`aslms.integration.napix`). Shared with the queue runner: `fetch_dossier` and `resolve_cnr` apply
a dossier the same way whether the queue or a user asked.

- `guard`: the switch (`NAPIX_ENABLED` and credentials), the quota floor (`NAPIX_SEARCH_FLOOR` against the
  remaining count of the detected quota window, `services/napix_window.py`; design `napix-window`, decision 6) and
  the per-user limit (`NAPIX_SEARCH_PER_USER_HOUR` audit rows `case.search_court` / `case.fetch_court` in the last
  hour).
- `answer_locally` (design `ownership-refinements`, decisions 4 to 6): runs before the guard for the kinds `cnr`,
  `case_number` and `filing`; validates as `search_court` does and answers a case held with its dossier with no
  call (`source: "local"`, `calls: 0`), so the answer works with the switch off, below the quota floor and over the
  per-user limit. Audited (`case.search_court`, `calls: 0`). A row with `after.calls` = 0 does not count towards the
  per-user limit: zero calls are free.
- `search_court`: by CNR (held with a dossier → local, no call; else Search by CNR and the dossier), by case
  number (Search by Case Number, every row stored, the exact row's dossier fetched), by filing number (held with
  a dossier → local; else Search by Filing Number and the asked row's dossier), by party name or advocate name
  (every row stored, no dossier — the user fetches the one they need; design `search-court-advocate-filing`).
  Rows whose `cino` is not a CNR are returned as `unmatched` and never stored: no fabricated identifier.
- `fetch_court`: the dossier of a found case; a provisional case without a CNR is resolved through Search by
  Case Number first (the CNR comes from the court, never invented).
Every call is audited with its outcome and the recorder's `napix_call_log` rows are flushed before the router
commits — also before an HTTP error is raised, so failures are recorded, never lost. The API's recorder carries a
session factory, so those flushes are committed in a session of their own and survive an unexpected error later
in the request (design `api-health-checker-followups`, decision 11). The router's recorder carries
the caller's id, and the order PDFs a person's search queues carry them as `requested_by` (design `napix-window`,
decision 9)."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import Settings, get_settings
from aslms.core.errors import IntegrationError, NapixInputError, NapixNotFound, NapixProtocolError
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import CaseType, Court
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, NapixResponse
from aslms.domain.org import User
from aslms.domain.ownership import RecommendationOrigin
from aslms.integration.napix.hc import NapixHighCourt, advocate_rows
from aslms.services import case_dedupe, matching, napix_window, queue
from aslms.services.audit import Actor, write_audit
from aslms.services.cases import (
    ROOT_OFFICE,
    ApplyReport,
    apply_dossier,
    get_or_create_case,
    refresh_search_vector,
)
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
MAX_ADVOCATE_NAME = 99  # HC spec §6.8 (design search-court-advocate-filing, decision 6)
MAX_FIL_NO = 9_999_999  # HC spec §6.6: up to 7 digits
MIN_YEAR = 1950
KINDS = ("cnr", "case_number", "filing", "party", "advocate")


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
    # an advocate search (design safety-fixes, decision 14): distinct CNRs the court returned, new cases being added
    # in the background, new cases beyond the cap that were not stored; 0 for the other kinds
    court_cases: int = 0
    queued: int = 0
    not_stored: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ guard


def user_searches_last_hour(session: Session, user: User) -> tuple[int, datetime | None]:
    """The caller's court searches and fetches of the last hour and the oldest one's time. A row whose `after.calls`
    is the number 0 is left out: zero calls are free (design `ownership-refinements`, decision 6); a row without
    `calls` still counts."""
    since = _now() - timedelta(hours=1)
    n, oldest = session.execute(
        select(func.count(), func.min(AuditLog.created_at)).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action.in_(SEARCH_ACTIONS),
            AuditLog.created_at >= since,
            func.coalesce(AuditLog.after["calls"].astext, "") != "0",
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


def store_search_rows(
    session: Session,
    court: Court,
    rows: list[dict[str, Any]],
    *,
    source: FirstSeenSource = FirstSeenSource.SEARCH,
    origin: RecommendationOrigin = RecommendationOrigin.SEARCH,
    ref_office: str = ROOT_OFFICE,
) -> StoreReport:
    """Decision 9: rows with a valid `cino` become cases (`source = search`), the search fields fill only empty
    columns (a dossier is authoritative); then the vector is refreshed and the cases scored. Department discovery
    passes its own `source`, `origin` and the office the new cases' `ref_no` is allocated on (design
    `department-discovery`, decisions 7-9); a person's search keeps the defaults."""
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
            session, court, cnr=cino, case_no=case_no, source=source, ref_office=ref_office
        )
        touched = created
        touched |= _fill_empty(case, "petitioner_summary", as_text(row.get("pet_name")))
        touched |= _fill_empty(case, "respondent_summary", as_text(row.get("res_name")))
        touched |= _fill_empty(case, "reg_no", reg_no)
        touched |= _fill_empty(case, "reg_year", reg_year)
        touched |= _fill_empty(case, "case_type_text", type_name)
        touched |= _fill_empty(case, "police_st_code", as_text(row.get("police_st_code"), 20))
        touched |= _fill_empty(case, "uniform_code", as_text(row.get("uniform_code"), 20))
        # Search by Filing Number rows carry `fil_no` / `fil_year` (probe P5, design search-court-advocate-filing)
        touched |= _fill_empty(case, "filing_no", as_int(row.get("fil_no")))
        touched |= _fill_empty(case, "filing_year", as_int(row.get("fil_year")))
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
        matching.score_cases(session, changed, origin=origin)
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
            calls=result.calls,
            results=len(result.cases),
            created=result.created,
            outcome=result.outcome,
            source=result.source,
        )
        if kind == "advocate" and result.outcome == "ok":  # design safety-fixes, decision 14
            audit.update(court_cases=result.court_cases, queued=result.queued, not_stored=result.not_stored)
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
        elif kind == "filing":
            result = await asyncio.wait_for(
                _search_filing(session, hc, court, request, force=force, origin=origin),
                settings.napix_search_timeout_seconds,
            )
        elif kind == "party":
            result = await asyncio.wait_for(
                _search_party(session, hc, court, request), settings.napix_search_timeout_seconds
            )
        elif kind == "advocate":
            result = await asyncio.wait_for(
                _search_advocate(
                    session, hc, court, request, recorder=recorder, settings=settings, user=user
                ),
                settings.napix_search_timeout_seconds,
            )
        else:
            raise CourtSearchError(f"kind is one of {', '.join(KINDS)}")
    except NapixNotFound:
        return done(CourtSearchResult("court", recorder.calls - calls_before, 0, [], [], "not_found"))
    except (IntegrationError, TimeoutError) as exc:
        code = _failure_code(exc)
        audit.update(
            calls=recorder.calls - calls_before,
            results=0,
            created=0,
            outcome=f"failed:{code}",
            source="court",
        )
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


def _check_cnr(cnr: str | None) -> str:
    value = (cnr or "").strip().upper()
    if not CNR_RE.match(value):
        raise CourtSearchError("not a CNR: four letters and twelve digits")
    return value


def _local_cnr(session: Session, cnr: str) -> Case | None:
    """The case held under the CNR with its dossier, or None (the CNR is validated by the caller)."""
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    return case if case is not None and case.last_full_refresh_at is not None else None


def _check_number(session: Session, court: Court, request: dict[str, Any]) -> tuple[CaseType, int, int]:
    ct = _resolve_case_type(session, court, str(request.get("case_type", "")))
    reg_no, reg_year = as_int(request.get("reg_no")), as_int(request.get("reg_year"))
    if reg_no is None or reg_year is None or reg_year < MIN_YEAR or reg_year > _now().year + 1:
        raise CourtSearchError("reg_no and reg_year are required")
    return ct, reg_no, reg_year


def _check_filing(session: Session, court: Court, request: dict[str, Any]) -> tuple[CaseType, int, int]:
    ct = _resolve_case_type(session, court, str(request.get("case_type", "")))
    fil_no = as_int(request.get("fil_no"))
    if fil_no is None or not 1 <= fil_no <= MAX_FIL_NO:
        raise CourtSearchError(f"fil_no is 1 to {MAX_FIL_NO}")
    fil_year = _check_year(request.get("fil_year"), "fil_year")
    return ct, fil_no, fil_year


def _local_number(session: Session, court: Court, request: dict[str, Any]) -> Case | None:
    """Validates a case-number request and returns the case held with its dossier, or None."""
    ct, reg_no, reg_year = _check_number(session, court, request)
    return _local_by_number(session, court, ct, reg_no, reg_year)


def _local_filing(session: Session, court: Court, request: dict[str, Any]) -> Case | None:
    """Validates a filing-number request and returns the case held with its dossier, or None."""
    ct, fil_no, fil_year = _check_filing(session, court, request)
    return _local_by_filing(session, court, ct, fil_no, fil_year)


LOCAL_KINDS = ("cnr", "case_number", "filing")


def answer_locally(
    session: Session,
    actor: Actor,
    user: User,
    request: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> CourtSearchResult | None:
    """Design `ownership-refinements`, decisions 4 and 5: before any guard and without an integration client. For
    `cnr`, `case_number` and `filing`: the input is validated as `search_court` does (`CourtSearchError`, 400) and a
    case held with its dossier is answered with `source: "local"`, `calls: 0` and one `case.search_court` audit row
    (`calls: 0`, `source: "local"`, the case's id). None when nothing is held, and always for `party` and
    `advocate`, which need the court. An unknown kind raises `CourtSearchError`."""
    kind = request.get("kind")
    if kind not in KINDS:
        raise CourtSearchError("kind is one of " + ", ".join(KINDS))
    if kind not in LOCAL_KINDS:
        return None
    court = court_for(session, (settings or get_settings()).napix_est_code)
    if kind == "cnr":
        case = _local_cnr(session, _check_cnr(request.get("cnr")))
    elif kind == "case_number":
        case = _local_number(session, court, request)
    else:
        case = _local_filing(session, court, request)
    if case is None:
        return None
    fields = {k: v for k, v in request.items() if k not in ("kind", "force")}
    write_audit(
        session,
        actor,
        "case.search_court",
        "napix_search",
        None,
        after={
            "kind": kind,
            "request": fields,
            "calls": 0,
            "results": 1,
            "created": 0,
            "outcome": "ok",
            "source": "local",
        },
        case_id=case.id,
    )
    session.flush()
    return CourtSearchResult("local", 0, 0, [case], [], "ok")


async def _search_cnr(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    cnr: str,
    *,
    force: bool = False,
    origin: QueueOrigin = REQUEST_ORIGIN,
) -> CourtSearchResult:
    cnr = _check_cnr(cnr)
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    if not force and _local_cnr(session, cnr) is not None:
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
    ct, reg_no, reg_year = _check_number(session, court, request)
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


def _check_year(value: Any, label: str = "reg_year") -> int:
    year = as_int(value)
    if year is None or year < MIN_YEAR or year > _now().year + 1:
        raise CourtSearchError(f"{label} is required (1950 to the current year)")
    return year


async def _name_calls(
    request: dict[str, Any],
    *,
    method: Callable[[str, int, str], Awaitable[list[dict[str, Any]]]],
    api: str,
    max_len: int | None = None,
    hc: NapixHighCourt | None = None,
) -> list[tuple[dict[str, Any], tuple[str, str] | None]]:
    """Party and advocate name (design search-court-advocate-filing, decision 6): the same input checks and the
    `P` / `D` / `both` loop (628 on one flag is not an error). Each row comes with the (api, params_sha256) of the
    response that carried it (from `hc.last`, when `hc` is given). `NapixNotFound` when no call found anything."""
    name = (request.get("name") or "").strip()
    pend = str(request.get("pend_disp") or "P").strip()
    if len(name) < MIN_PARTY_NAME:
        raise CourtSearchError(f"name is at least {MIN_PARTY_NAME} characters")
    if max_len is not None and len(name) > max_len:
        raise CourtSearchError(f"name is at most {max_len} characters")
    if not PARTY_NAME_RE.match(name):
        raise CourtSearchError("name: letters, digits, spaces and . , ' & ( ) / - only")
    reg_year = _check_year(request.get("reg_year"))
    if pend not in ("P", "D", "both"):
        raise CourtSearchError("pend_disp is P, D or both")
    rows: list[tuple[dict[str, Any], tuple[str, str] | None]] = []
    found_any = False
    for flag in ("P", "D") if pend == "both" else (pend,):
        try:
            got = await method(name, reg_year, flag)
        except NapixNotFound:
            continue
        found_any = True
        last = hc.last if hc is not None else None
        key = (last.api, last.params_sha256) if last is not None else None
        rows.extend((row, key) for row in got)
    if not found_any:
        raise NapixNotFound("no case for that name", api=api)
    return rows


async def _search_party(
    session: Session, hc: NapixHighCourt, court: Court, request: dict[str, Any]
) -> CourtSearchResult:
    """Every row with a valid `cino` stored and scored, no dossier fetched: the court matches party names exactly
    (probe P4), so the rows stay few (design safety-fixes, decision 12)."""
    rows = await _name_calls(request, method=hc.search_party, api="party_name")
    report = store_search_rows(session, court, [row for row, _ in rows])
    return CourtSearchResult("court", 0, report.created, report.cases, report.unmatched, "ok")


def held_cnrs(session: Session, cnrs: list[str]) -> set[str]:
    """The CNRs among `cnrs` that a case row holds already, in one query."""
    if not cnrs:
        return set()
    return set(session.scalars(select(Case.cnr).where(Case.cnr.in_(cnrs))).all())


async def _search_advocate(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    request: dict[str, Any],
    *,
    recorder: NapixRecorder | None = None,
    settings: Settings | None = None,
    user: User | None = None,
) -> CourtSearchResult:
    """Decision 6 of search-court-advocate-filing: like the party name, with the spec's 99-character maximum.
    Nothing is written to `case_advocates` from a hit (the row does not say on which side the advocate appears);
    the case's advocates arrive with its dossier.

    The court matches part of a name, so the rows stored are capped (design safety-fixes, decisions 12-14): the
    distinct valid CNRs in court order (P before D); the held ones found in one query; the first
    `NAPIX_ADVOCATE_STORE_NOW` new ones stored now. When all the distinct CNRs number at most
    `NAPIX_ADVOCATE_STORE_MAX`, the remaining new ones are stored in the background (one `search_rows` queue row per
    response that carries them, lane `request`, priority 30, `requested_by` the person); otherwise nothing more is
    stored (`not_stored`) and every response stays verbatim in `napix_responses`. The answer lists the held cases
    among the first STORE_MAX CNRs plus the ones stored now."""
    cfg = settings or get_settings()
    store_now, store_max = cfg.napix_advocate_store_now, cfg.napix_advocate_store_max
    rows = await _name_calls(
        request, method=hc.search_advocate, api="advocate_name", max_len=MAX_ADVOCATE_NAME, hc=hc
    )
    order: list[str] = []  # distinct valid CNRs, court order
    keys_of: dict[str, set[tuple[str, str]]] = {}
    for row, key in rows:
        cino = _cino(row)
        if cino is None:
            continue
        if cino not in keys_of:
            order.append(cino)
            keys_of[cino] = set()
        if key is not None:
            keys_of[cino].add(key)
    held = held_cnrs(session, order)
    new = [c for c in order if c not in held]
    now_new = set(new[:store_now])
    rest = new[store_now:]
    court_cases = len(order)
    listed = {c for c in order[:store_max] if c in held} | now_new
    to_store = [row for row, _ in rows if (cino := _cino(row)) is None or cino in listed]
    report = store_search_rows(session, court, to_store)
    queued = not_stored = 0
    if rest and court_cases <= store_max and recorder is not None:
        recorder.flush(session)  # writes the call log and the responses, and names the responses' ids
        keys = sorted({k for c in rest for k in keys_of[c]})
        ids = list(dict.fromkeys(recorder.response_ids[k] for k in keys if k in recorder.response_ids))
        for rid in ids:
            queue.enqueue(
                session,
                FetchKind.SEARCH_ROWS,
                str(rid),
                queue.PRIORITY["request"],
                requeue=True,
                lane=FetchLane.REQUEST,
                requested_by=napix_window.user_id_of(user),
            )
        queued = len(rest) if ids else 0
        not_stored = 0 if ids else len(rest)
    elif rest:
        not_stored = len(rest)
    return CourtSearchResult(
        "court",
        0,
        report.created,
        report.cases,
        report.unmatched,
        "ok",
        court_cases=court_cases,
        queued=queued,
        not_stored=not_stored,
    )


# ------------------------------------------------------------------------------------------------ background storing


def store_response_rows(session: Session, response_id: uuid.UUID | str) -> dict[str, int] | None:
    """The handler of a `search_rows` queue row (design safety-fixes, decision 13): reads the stored advocate-search
    payload with the same extractor as `NapixHighCourt.search_advocate` and stores every valid row whose CNR is not
    held yet (source `search`, origin `search`). Idempotent; makes no NAPIX call. None when the response is unknown."""
    resp = session.get(NapixResponse, uuid.UUID(str(response_id)))
    if resp is None:
        return None
    est = (resp.params or {}).get("est_code") or get_settings().napix_est_code
    court = court_for(session, est)
    rows = advocate_rows(resp.payload)
    valid = [(cino, row) for row in rows if (cino := _cino(row))]
    held = held_cnrs(session, list(dict.fromkeys(c for c, _ in valid)))
    fresh = [row for cino, row in valid if cino not in held]
    report = store_search_rows(session, court, fresh) if fresh else StoreReport()
    return {"stored": report.created, "held": len(held), "unmatched": len(rows) - len(valid)}


def run_store_search_rows(session_factory: sessionmaker[Session], *, limit: int = 50) -> dict[str, int]:
    """The `aslms.store_search_rows` task: claims `search_rows` rows until none are left (at most `limit`), one
    transaction per row; a failure goes on the queue's ladder and, when final, into `source_failures`."""
    counts = {"done": 0, "skipped": 0, "failed": 0}
    for _ in range(limit):
        with session_factory() as s:
            item = queue.claim(s, [FetchKind.SEARCH_ROWS])
            if item is None:
                s.commit()
                break
            item_id, ref = item.id, item.ref
            s.commit()
            try:
                out = store_response_rows(s, ref)
                item = s.get(FetchQueueItem, item_id)
                queue.complete(s, item, out or {"error": "response not found"}, skipped=out is None)
                counts["skipped" if out is None else "done"] += 1
            except Exception as exc:  # noqa: BLE001 — recorded on the row and retried on the ladder
                s.rollback()
                item = s.get(FetchQueueItem, item_id)
                queue.fail(s, item, f"{exc.__class__.__name__}: {exc}", family=type(exc).__name__)
                counts["failed"] += 1
            s.commit()
    return counts


def _compact(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").upper())


def _local_by_filing(session: Session, court: Court, ct: CaseType, fil_no: int, fil_year: int) -> Case | None:
    """Decision 5: a non-merged case with a dossier whose filing number and year are the request's and whose
    filing type is the requested type (`filing_case_type_id`, or the text compacting to the short name or an
    alias; when the case has no filing type, its registration type id); the oldest first."""
    names = {_compact(n) for n in [ct.short_name or "", *(ct.aliases or [])]} - {""}
    stmt = (
        select(Case)
        .where(
            Case.court_id == court.id,
            Case.filing_no == fil_no,
            Case.filing_year == fil_year,
            Case.last_full_refresh_at.isnot(None),
            Case.merged_into_case_id.is_(None),
        )
        .order_by(Case.created_at)
    )
    for case in session.scalars(stmt).all():
        if case.filing_case_type_id == ct.id or _compact(case.filing_case_type_text) in names:
            return case
        if case.filing_case_type_id is None and not case.filing_case_type_text and case.case_type_id == ct.id:
            return case
    return None


def _cino(row: dict[str, Any]) -> str | None:
    cino = (as_text(row.get("cino"), 16) or "").upper()
    return cino if CNR_RE.match(cino) else None


async def _search_filing(
    session: Session,
    hc: NapixHighCourt,
    court: Court,
    request: dict[str, Any],
    *,
    force: bool = False,
    origin: QueueOrigin = REQUEST_ORIGIN,
) -> CourtSearchResult:
    """Decision 5: local first, then Search by Filing Number (every row stored), then the dossier of the case asked
    for when it has none: the row whose `fil_no` / `fil_year` are the request's, else the single valid row. `force`
    skips the local match and re-fetches the asked case's dossier (nothing passes it today)."""
    ct, fil_no, fil_year = _check_filing(session, court, request)
    local = _local_by_filing(session, court, ct, fil_no, fil_year)
    if local is not None and not force:
        return CourtSearchResult("local", 0, 0, [local], [], "ok")
    rows = await hc.search_filing(ct.case_type_code, fil_no, fil_year)
    report = store_search_rows(session, court, rows)
    valid = [(cino, row) for row in rows if (cino := _cino(row))]
    asked_cnr = next(
        (
            cino
            for cino, row in valid
            if as_int(row.get("fil_no")) == fil_no and as_int(row.get("fil_year")) == fil_year
        ),
        None,
    )
    if asked_cnr is None and len({cino for cino, _ in valid}) == 1:
        asked_cnr = valid[0][0]
    asked = next((c for c in report.cases if asked_cnr and c.cnr == asked_cnr), None)
    if asked is not None and asked_cnr and (force or asked.last_full_refresh_at is None):
        await fetch_dossier(session, hc, court, asked_cnr, source=FirstSeenSource.SEARCH, origin=origin)
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
