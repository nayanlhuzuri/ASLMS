""" "Test now" on the System health screen (design `api-health-checker`, decisions 7-9, 11-13): ONE real call to one
court API through the integration layer, with an input ASLMS already holds, run in the request.

- **The guard** (`guard`, decision 8) refuses before any call and writes nothing, in this order: unknown API (404),
  the switch off (409 `napix_off`), no sample (409 `no_sample`), a send with no body whose held sample carries a
  value hidden from the caller (409 `sample_hidden`: a name, a CNR, a case or filing number of a case the caller
  cannot see; design `system-health-inspector`, decision 6), a test of this API less than
  `HEALTH_TEST_API_MIN_SECONDS` ago by anyone (429 `test_too_soon`; the Connection check also counts the data-health
  connectivity check), the caller's `HEALTH_TEST_PER_USER_HOUR` reached (429 `test_limit`), the detected window's
  remaining calls below `NAPIX_SEARCH_FLOOR` (429 `napix_budget`; an unknown remaining allows the test). `run` then
  takes two transaction-scoped advisory locks, always the person's first (409 `user_test_running`: one test at a
  time per person) and then the API's (409 `test_running`), and checks the interval and the person's hourly count
  once more (design `api-health-checker-followups`, decision 6).
- **One call** on a fresh client: `max_attempts = 1` (no back-off retry), `timeout = HEALTH_TEST_TIMEOUT_SECONDS`. The
  only possible second attempt is the client's own token renewal after an HTTP 401: the 401 step is logged first
  and the repeated attempt after it, so the last attempt is the one that decided the outcome.
- **Recorded, never lost** (design `api-health-checker-followups`, decisions 1-2): the `NapixRecorder` (carrying the
  caller's id) is committed in a session of its own in a `finally` as soon as the call ends, and the audit row
  `napix.api_tested` in another after the summary. A test writes one `napix_call_log` row per attempt, at most one
  `napix_responses` row and one audit row; no case data, no master row, no queue row (decision 12). A PDF answer is
  hashed and discarded. The request transaction itself holds only reads and the advisory locks. The audit row is
  written in a `finally` from a minimal record built from the attempts (design `followups-oct`, decision 6): when
  ASLMS's own outcome, structure or summary fails, it carries `unexpected` (the class name only; `summary: null`
  and `summary_error` when the summary failed) and the error propagates (500).
- **Summarised, never shown verbatim** (decision 9): the outcome is built from a whitelist of computed facts. The
  payload, the PDF, the raw text, the parameters, the error text and every name stay on the server."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import Settings
from aslms.core.errors import IntegrationError
from aslms.domain.causelists import CauselistBenchDay
from aslms.domain.courts import Act, CaseType, Court, District, HighCourt
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.integration.napix.hc import NapixHighCourt, rows_of, search_rows
from aslms.integration.napix.preview import preview
from aslms.services import (
    access,
    audit,
    napix_inspect,
    napix_reference,
    napix_samples,
    napix_window,
    system_health,
)
from aslms.services.access import Member
from aslms.services.audit import Actor
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CNR_RE
from aslms.services.napix_admin import acting_member
from aslms.services.napix_samples import NoSample, Sample
from aslms.services.napix_store import NapixRecorder
from aslms.services.napix_values import as_date

MAX_FIELDS = 40
MASTER_KEYS = ("state", "district", "bench_master", "case_type", "act")
LIST_KEYS = ("causelist_bench", "causelist_details")
SEARCH_KEYS = ("case_search", "filing", "party_name", "advocate_name")
ANSWERED_FAMILIES = system_health.ANSWERED_FAMILIES
SAMPLE_HIDDEN = (
    "The held sample belongs to a case you cannot see; type the values in the console's form and send them"
)


class TestRefused(Exception):
    """A test refused before any call (nothing written): `code`, the HTTP status and `retry_after` for a 429."""

    __test__ = False  # not a pytest class

    def __init__(self, code: str, message: str, http_status: int, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code, self.http_status, self.retry_after = code, http_status, retry_after


@dataclass
class TestOutcome:
    __test__ = False

    api: str
    ok: bool
    answered: bool
    status: str
    reason: str
    http_status: int | None
    napix_status: int | None
    error_family: str | None
    duration_ms: int
    attempts: int
    called_at: datetime
    token_verified: bool | None
    remaining: int | None
    input: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)
    # the console (design system-health-inspector, decision 5)
    request: dict[str, Any] = field(default_factory=dict)
    edited: bool = False
    rate_limit: dict[str, int | None] = field(default_factory=lambda: {"limit": None, "remaining": None})
    structure: dict[str, Any] | None = None
    inventory_diff: dict[str, Any] | None = None
    response_id: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api": self.api,
            "ok": self.ok,
            "answered": self.answered,
            "status": self.status,
            "reason": self.reason,
            "http_status": self.http_status,
            "napix_status": self.napix_status,
            "error_family": self.error_family,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "called_at": to_ist(self.called_at),
            "token_verified": self.token_verified,
            "remaining": self.remaining,
            "input": self.input,
            "summary": self.summary,
            "request": self.request,
            "edited": self.edited,
            "rate_limit": self.rate_limit,
            "structure": self.structure,
            "inventory_diff": self.inventory_diff,
            "response_id": self.response_id,
            "response_available": self.response_id is not None,
            "http_meaning": napix_reference.http_meaning(self.http_status, self.error_family),
            "napix_meaning": napix_reference.napix_meaning(self.napix_status),
        }


# ------------------------------------------------------------------------------------------------ summaries (pure)


def _fact(label: str, value: Any) -> dict[str, str]:
    if isinstance(value, bool):
        value = "yes" if value else "no"
    return {"label": label, "value": str(value)}


def _field_names(rows: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for r in rows:
        names.update(str(k) for k in r)
    return sorted(names)[:MAX_FIELDS]


def summarise_rows(rows: list[dict[str, Any]], facts: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"kind": "rows", "row_count": len(rows), "field_names": _field_names(rows), "facts": facts or []}


def summarise_record(data: Any, facts: list[dict[str, str]] | None = None) -> dict[str, Any]:
    record = data if isinstance(data, dict) else {}
    return {
        "kind": "record",
        "row_count": len(record),
        "field_names": sorted(str(k) for k in record)[:MAX_FIELDS],
        "facts": facts or [],
    }


def pdf_pages(pdf: bytes) -> int | None:
    try:
        import pymupdf

        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            return int(doc.page_count)
    except Exception:  # noqa: BLE001 — a file that cannot be opened has no page count
        return None


def summarise_pdf(pdf: bytes, stored_sha256: str | None) -> dict[str, Any]:
    facts = [_fact("Size", f"{math.ceil(len(pdf) / 1024)} KB")]
    pages = pdf_pages(pdf)
    if pages is not None:
        facts.append(_fact("Pages", pages))
    if stored_sha256:
        facts.append(_fact("Same as the stored copy", hashlib.sha256(pdf).hexdigest() == stored_sha256))
    return {"kind": "pdf", "row_count": None, "field_names": [], "facts": facts}


def payload_rows(key: str, data: Any) -> list[dict[str, Any]]:
    if key in MASTER_KEYS:
        return rows_of(data)
    if key in SEARCH_KEYS:
        return search_rows(data)
    return nested_list(data)


def _cnrs(rows: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in rows:
        cino = str(r.get("cino") or "").strip().upper()
        if CNR_RE.match(cino) and cino not in out:
            out.append(cino)
    return out


def _date_present(value: Any) -> bool:
    """A real date: the court's sentinels (`5000-01-01`, `1900-01-01`, `0000-00-00`), a blank and "Next Date Not
    Given" read absent (`napix_values.as_date`; design `api-health-checker-followups`, decision 8)."""
    return as_date(value) is not None


def _text_present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def summarise_payload(
    key: str, data: Any, sample_values: dict[str, Any], source_cnr: str | None = None
) -> dict:
    """The facts that need no database, for a JSON answer (decision 9). Never a value from a name field."""
    if key in MASTER_KEYS or key in LIST_KEYS or key in SEARCH_KEYS:
        rows = payload_rows(key, data)
        facts: list[dict[str, str]] = []
        if key == "causelist_details":
            names = sorted({str(r.get("cause_list_type") or "").strip() for r in rows} - {""})
            facts.append(_fact("List names", ", ".join(names) if names else "none"))
        if key in SEARCH_KEYS:
            cnrs = _cnrs(rows)
            facts.append(_fact("Distinct cases (CNR)", len(cnrs)))
            if key in ("case_search", "filing") and source_cnr:
                facts.append(_fact("The source case is among the rows", source_cnr.upper() in cnrs))
        return summarise_rows(rows, facts)
    record = data if isinstance(data, dict) else {}
    facts = []
    if key == "overview":
        facts.append(_fact("Version", str(record.get("version") or "not given")[:40]))
    elif key == "cnr":
        asked = str(sample_values.get("cnr") or "").upper()
        facts.append(
            _fact("The CNR in the answer is the one asked", str(record.get("cino") or "").upper() == asked)
        )
        pend = str(record.get("pend_disp") or "").strip().upper()
        facts.append(_fact("Case status", {"P": "pending", "D": "disposed"}.get(pend, "not given")))
        facts.append(_fact("A next hearing date is present", _date_present(record.get("date_next_list"))))
        orders = len(nested_list(record.get("interimorder"))) + len(nested_list(record.get("finalorder")))
        facts.append(_fact("Orders in the answer", orders))
        facts.append(_fact("Hearings in the answer", len(nested_list(record.get("historyofcasehearing")))))
    elif key == "current_status":
        blocks = nested_list(record) or ([record] if record.get("cino") else [])
        asked = str(sample_values.get("cnr") or "").upper()
        facts.append(_fact("Blocks returned", len(blocks)))
        facts.append(_fact("The CNR matches", any(str(b.get("cino") or "").upper() == asked for b in blocks)))
        summary = summarise_record(blocks[0] if blocks else {}, facts)
        return summary
    elif key == "show_business":
        asked = sample_values.get("business_date")
        asked_text = asked.isoformat() if hasattr(asked, "isoformat") else str(asked or "")
        facts.append(_fact("The business date matches", str(record.get("business_date") or "") == asked_text))
        facts.append(_fact("Business text is present", _text_present(record.get("business"))))
    return summarise_record(record, facts)


def held_facts(
    session: Session, settings: Settings, key: str, data: Any, sample_values: dict[str, Any]
) -> list:
    """The facts that compare the answer with what ASLMS holds (counts only)."""
    if key in MASTER_KEYS:
        # where masters sync keeps each list (services/masters.py): High Courts in `high_courts`, the court's
        # districts and benches (establishments) under its High Court, case types per court, acts
        hc_id = session.scalar(
            select(HighCourt.id).where(HighCourt.napix_state_code == int(settings.napix_state_code))
        )
        court_id = session.scalar(select(Court.id).where(Court.est_code == settings.napix_est_code))
        if key == "state":
            q = select(func.count()).select_from(HighCourt).where(HighCourt.is_active.is_(True))
        elif key == "district":
            q = (
                select(func.count())
                .select_from(District)
                .where(District.high_court_id == hc_id, District.is_active.is_(True))
            )
        elif key == "bench_master":
            q = (
                select(func.count())
                .select_from(Court)
                .where(Court.high_court_id == hc_id, Court.is_active.is_(True))
            )
        elif key == "case_type":
            q = (
                select(func.count())
                .select_from(CaseType)
                .where(CaseType.court_id == court_id, CaseType.is_active.is_(True))
            )
        else:
            q = select(func.count()).select_from(Act).where(Act.is_active.is_(True))
        return [_fact("ASLMS holds", int(session.scalar(q) or 0))]
    if key == "causelist_bench":
        n = session.scalar(
            select(func.count())
            .select_from(CauselistBenchDay)
            .where(CauselistBenchDay.list_date == sample_values["list_date"])
        )
        return [_fact("Benches ASLMS holds for that date", int(n or 0))]
    if key in SEARCH_KEYS:
        from aslms.services.court_search import held_cnrs

        cnrs = _cnrs(search_rows(data))
        return [_fact("Of them held by ASLMS", len(held_cnrs(session, cnrs)))]
    return []


# ------------------------------------------------------------------------------------------------ the guard


def _wait(at: datetime, now: datetime) -> int:
    return max(1, math.ceil((at - now).total_seconds()))


def _too_soon(session: Session, settings: Settings, key: str, now: datetime) -> None:
    at = system_health.api_allowed_at(session, settings, key, now)
    if at is not None:
        wait = _wait(at, now)
        raise TestRefused(
            "test_too_soon",
            f"this API was tested a moment ago; the next test is possible in {wait} s",
            429,
            wait,
        )


def _over_cap(session: Session, settings: Settings, user: User | Member, now: datetime) -> None:
    """429 `test_limit` once the caller made `HEALTH_TEST_PER_USER_HOUR` tests in the last hour."""
    count, oldest = system_health.user_tests(session, napix_window.user_id_of(user), now)
    cap_at = system_health.user_allowed_at(settings, count, oldest, now)
    if cap_at is not None:
        raise TestRefused(
            "test_limit",
            f"you have made {count} tests in the last hour; the limit is {settings.health_test_per_user_hour}",
            429,
            _wait(cap_at, now),
        )


def guard(
    session: Session,
    settings: Settings,
    user: User | Member,
    key: str,
    now: datetime | None = None,
    values: dict[str, Any] | None = None,
) -> Sample:
    """Decision 8's refusals 1-6, in order, before any call and writing nothing; the sample to send. With `values`
    (the console's form, design `system-health-inspector`, decision 8) they are checked right after the switch and
    replace the held sample (`napix_inspect.InvalidInput`, 422); `no_sample` and `sample_hidden` are only for a send
    without values."""
    now = now or datetime.now(UTC)
    if key not in system_health.BY_KEY:
        raise TestRefused("not_found", "no such court API", 404)
    if not settings.napix_configured:
        raise TestRefused(
            "napix_off", "Court calls are switched off on this server (NAPIX_ENABLED is false)", 409
        )
    chosen = napix_samples.choose(session, settings, key, user)
    if values is not None:
        chosen = napix_inspect.validate(session, settings, key, values, held=chosen)
    if isinstance(chosen, NoSample):
        raise TestRefused("no_sample", chosen.reason, 409)
    if values is None and chosen.hidden_from_caller() & chosen.values.keys():
        # design system-health-inspector, decision 6: every value sent was seen or typed by the sender, so a send
        # with no body never uses a name, CNR, case or filing number of a case the caller cannot see
        raise TestRefused("sample_hidden", SAMPLE_HIDDEN, 409)
    _too_soon(session, settings, key, now)
    _over_cap(session, settings, user, now)
    window = napix_window.current(session, settings, now)
    if window.remaining is not None and window.remaining < settings.napix_search_floor:
        resume = now + timedelta(seconds=window.retry_after(now))
        raise TestRefused(
            "napix_budget",
            "The court's hourly allowance is nearly used up; tests resume after about "
            f"{to_ist(resume).strftime('%H:%M')}",
            429,
            window.retry_after(now),
        )
    return chosen


def lock_user(session: Session, user_id: Any) -> None:
    """409 `user_test_running` while the same person has another test in flight (transaction-scoped: PgBouncer-safe;
    taken before the API's lock, always in that order; design `api-health-checker-followups`, decision 6)."""
    got = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"napix-api-test-user:{user_id}"},
    )
    if not got:
        raise TestRefused(
            "user_test_running", "Your other test is still running; try again when it has finished", 409
        )


def lock(session: Session, key: str) -> None:
    """409 `test_running` while another test of the same API is in flight (transaction-scoped: PgBouncer-safe)."""
    got = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"napix-api-test:{key}"}
    )
    if not got:
        raise TestRefused("test_running", "a test of this API is running; try again in a moment", 409)


# ------------------------------------------------------------------------------------------------ the test


def _status(ok: bool, answered: bool) -> str:
    if ok:
        return "ok"
    return "warn" if answered else "down"


def _audit_sample(sample: Sample) -> dict[str, Any]:
    out = sample.public_values(case_visible=False)
    if sample.source_ref_no:
        out["case_ref_no"] = sample.source_ref_no
    return out


async def run(
    session: Session,
    session_factory: sessionmaker[Session],
    actor: Actor,
    user: User | Member,
    settings: Settings,
    client: NapixClient,
    hc: NapixHighCourt,
    key: str,
    values: dict[str, Any] | None = None,
) -> TestOutcome:
    """One call of one court API (decisions 7-13). A court failure is an outcome (`ok = false`), not an exception.
    The call rows and the audit row are committed through `session_factory`, each in a session of its own; the
    request session only reads and holds the locks (design `api-health-checker-followups`, decisions 1, 2 and 6)."""
    member = acting_member(session, user, Permission.ADMIN_SERVICE_HEALTH)
    sample = guard(session, settings, user, key, values=values)
    user_id = napix_window.user_id_of(user)
    if user_id is not None:
        lock_user(session, user_id)
    lock(session, key)
    # a test committed while this request waited for the locks: refuse rather than call again
    now = datetime.now(UTC)
    _too_soon(session, settings, key, now)
    _over_cap(session, settings, user, now)
    e = system_health.entry(key)
    request = preview(settings, key, e.invoke, sample.values)  # the request as it is sent (no call)
    target = hc.for_codes(est_code=sample.values.get("est_code"), state_code=sample.values.get("state_code"))
    recorder = NapixRecorder(user_id=user_id)
    client.on_call = recorder.on_call
    client.max_attempts = 1
    client.timeout = settings.health_test_timeout_seconds
    called_at = datetime.now(UTC)
    error_family: str | None = None
    value: Any = None
    attempts: list[NapixResult] = []
    unexpected: Exception | None = None
    try:
        try:
            async with client:
                value = await e.invoke(target, sample.values)
        except (IntegrationError, httpx.HTTPError) as exc:
            error_family = type(exc).__name__
        except (
            Exception
        ) as exc:  # ASLMS's own defect in the call: recorded by its class in the audit row, then raised again
            unexpected = exc
    finally:
        attempts = list(recorder.pending)
        recorder.flush_apart(session_factory)
    last = attempts[-1] if attempts else None  # the client logs a renewal's 401 step first (decision 4)
    family = (last.error_family if last is not None and last.error_family else None) or error_family
    ok = unexpected is None and error_family is None and last is not None and last.ok
    http_status = last.http_status if last is not None else None
    napix_status = last.napix_status if last is not None else None
    # the minimal audit record, built from the attempts alone right after their rows were committed; everything
    # below only enriches it, and the row is written in the `finally` whatever happens (design followups-oct, 6)
    after: dict[str, Any] = {
        "api": key,
        "path": e.path,
        "attempts": len(attempts),
        "http_status": http_status,
        "napix_status": napix_status,
        "error_family": None if ok else family,
        "ok": ok,
        "params_sha256": request.plain_sha256,
    }
    failure: Exception | None = unexpected
    if unexpected is not None:
        after["unexpected"] = type(unexpected).__name__  # the class only, never the text (followups-oct, 6)
    summary_failed = False
    try:
        answered = ok or (last is not None and family in ANSWERED_FAMILIES)
        outcome = TestOutcome(
            api=key,
            ok=ok,
            answered=answered,
            status=_status(ok, answered),
            reason=system_health.plain_reason(
                None if ok else family, napix_status, None if ok else http_status
            ),
            http_status=http_status,
            napix_status=napix_status,
            error_family=None if ok else family,
            duration_ms=sum(a.duration_ms for a in attempts),
            attempts=len(attempts),
            called_at=called_at,
            token_verified=last.token_verified if last is not None else None,
            remaining=recorder.last_remaining,
            input={"label": sample.label, "values": sample.public_values()},
            summary={"kind": e.kind, "row_count": None, "field_names": [], "facts": []},
            request={
                "method": request.method,
                "url": request.url,
                "plain": request.plain,
                "envelope": napix_inspect.envelope(settings, request),
            },
            edited=sample.edited,
            rate_limit={
                "limit": last.rate_limit[0] if last is not None else None,
                "remaining": last.rate_limit[1] if last is not None else None,
            },
            response_id=recorder.response_ids.get((e.path, request.plain_sha256)) if ok else None,
        )
        after.update(
            {
                "answered": outcome.answered,
                "duration_ms": outcome.duration_ms,
                "remaining": outcome.remaining,
                "sample": _audit_sample(sample),
                "summary": None,
                # the console's facts (design system-health-inspector, decision 5): the plain parameters sent
                # (names included, as court search audits its query; decision 6 ensures the sender saw or typed
                # them)
                "params": dict(request.params),
                "edited": sample.edited,
                "response_id": str(outcome.response_id) if outcome.response_id is not None else None,
                "token_verified": outcome.token_verified,
                "rate_limit": outcome.rate_limit,
                "structure": None,
            }
        )
        if ok and last is not None and last.pdf is None and last.data is not None:
            outcome.structure = napix_inspect.structure(last.data)
            outcome.inventory_diff = napix_inspect.inventory_diff(
                key, napix_inspect.structure_paths(last.data)
            )
            after["structure"] = outcome.structure
        if ok and last is not None:
            summary_failed = True
            outcome.summary = _summary(session, settings, e, sample, last, value)
            summary_failed = False
        after["summary"] = outcome.summary
    except (
        Exception
    ) as exc:  # ASLMS's own defect: recorded in the audit row by its class only, then raised again
        if failure is None:  # the call's own defect, when there was one, is the one recorded and raised
            failure = exc
            after["unexpected"] = type(exc).__name__
        if summary_failed:
            after["summary_error"] = type(exc).__name__
    finally:
        audit.write_audit_apart(
            session_factory,
            access.actor_as(actor, member),
            system_health.TEST_ACTION,
            "napix",
            None,
            after=after,
        )
    if failure is not None:
        raise failure
    return outcome


def _summary(
    session: Session,
    settings: Settings,
    e: system_health.ApiEntry,
    sample: Sample,
    result: NapixResult,
    value: Any,
) -> dict[str, Any]:
    if result.pdf is not None:
        return summarise_pdf(result.pdf, sample.stored_sha256)
    data = result.data
    summary = summarise_payload(e.key, data, sample.values, sample.source_cnr)
    summary["facts"] = summary["facts"] + held_facts(session, settings, e.key, data, sample.values)
    return summary
