""" "Test now" on the System health screen (design `api-health-checker`, decisions 7-9, 11-13): ONE real call to one
court API through the integration layer, with an input ASLMS already holds, run in the request.

- **The guard** (`guard`, decision 8) refuses before any call and writes nothing, in this order: unknown API (404),
  the switch off (409 `napix_off`), no sample (409 `no_sample`), a test of this API less than
  `HEALTH_TEST_API_MIN_SECONDS` ago by anyone (429 `test_too_soon`; the Connection check also counts the data-health
  connectivity check), the caller's `HEALTH_TEST_PER_USER_HOUR` reached (429 `test_limit`), the detected window's
  remaining calls below `NAPIX_SEARCH_FLOOR` (429 `napix_budget`; an unknown remaining allows the test). `run` then
  takes a transaction-scoped advisory lock per API (409 `test_running`) and looks at the interval once more.
- **One call** on a fresh client: `max_attempts = 1` (no back-off retry), `timeout = HEALTH_TEST_TIMEOUT_SECONDS`. The
  only possible second attempt is the client's own token renewal after an HTTP 401; both attempts are logged.
- **Recorded, never lost**: the `NapixRecorder` (carrying the caller's id) is flushed in a `finally`. A test writes
  one `napix_call_log` row per attempt, at most one `napix_responses` row and one audit row `napix.api_tested`; no
  case data, no master row, no queue row (decision 12). A PDF answer is hashed and discarded.
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
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.core.errors import IntegrationError
from aslms.domain.causelists import CauselistBenchDay
from aslms.domain.courts import Act, CaseType, Court, District, HighCourt
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.integration.napix.hc import NapixHighCourt, rows_of, search_rows
from aslms.services import access, napix_samples, napix_window, system_health
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CNR_RE
from aslms.services.napix_admin import acting_member
from aslms.services.napix_samples import NoSample, Sample
from aslms.services.napix_store import NapixRecorder

MAX_FIELDS = 40
MASTER_KEYS = ("state", "district", "bench_master", "case_type", "act")
LIST_KEYS = ("causelist_bench", "causelist_details")
SEARCH_KEYS = ("case_search", "filing", "party_name", "advocate_name")
ANSWERED_FAMILIES = system_health.ANSWERED_FAMILIES


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


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() not in ("", "0000-00-00")


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
        facts.append(_fact("A next hearing date is present", _present(record.get("date_next_list"))))
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
        facts.append(_fact("Business text is present", _present(record.get("business"))))
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


def guard(
    session: Session, settings: Settings, user: User | Member, key: str, now: datetime | None = None
) -> Sample:
    """Decision 8's refusals 1-6, in order, before any call and writing nothing; the chosen sample."""
    now = now or datetime.now(UTC)
    if key not in system_health.BY_KEY:
        raise TestRefused("not_found", "no such court API", 404)
    if not settings.napix_configured:
        raise TestRefused(
            "napix_off", "Court calls are switched off on this server (NAPIX_ENABLED is false)", 409
        )
    chosen = napix_samples.choose(session, settings, key, user)
    if isinstance(chosen, NoSample):
        raise TestRefused("no_sample", chosen.reason, 409)
    _too_soon(session, settings, key, now)
    count, oldest = system_health.user_tests(session, napix_window.user_id_of(user), now)
    cap_at = system_health.user_allowed_at(settings, count, oldest, now)
    if cap_at is not None:
        raise TestRefused(
            "test_limit",
            f"you have made {count} tests in the last hour; the limit is {settings.health_test_per_user_hour}",
            429,
            _wait(cap_at, now),
        )
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


def lock(session: Session, key: str) -> None:
    """409 `test_running` while another test of the same API is in flight (transaction-scoped: PgBouncer-safe)."""
    got = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"napix-api-test:{key}"}
    )
    if not got:
        raise TestRefused("test_running", "a test of this API is running; try again in a moment", 409)


# ------------------------------------------------------------------------------------------------ the test


def final_attempt(attempts: list[NapixResult], *, raised: bool) -> NapixResult | None:
    """The attempt that decided the outcome. After an HTTP 401 the client renews its token and asks again inside the
    first attempt, so the renewed attempt is reported before the 401 one: on success it is the last answered
    attempt, on failure the last one carrying an error family."""
    if not attempts:
        return None
    if raised:
        return next((a for a in reversed(attempts) if a.error_family), attempts[-1])
    return next((a for a in reversed(attempts) if a.ok), attempts[-1])


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
    actor: Actor,
    user: User | Member,
    settings: Settings,
    client: NapixClient,
    hc: NapixHighCourt,
    key: str,
) -> TestOutcome:
    """One call of one court API (decisions 7-13). A court failure is an outcome (`ok = false`), not an exception."""
    member = acting_member(session, user, Permission.ADMIN_SERVICE_HEALTH)
    sample = guard(session, settings, user, key)
    lock(session, key)
    # a test of this API committed while this request waited for the lock: refuse rather than call again
    _too_soon(session, settings, key, datetime.now(UTC))
    e = system_health.entry(key)
    recorder = NapixRecorder(user_id=napix_window.user_id_of(user))
    client.on_call = recorder.on_call
    client.max_attempts = 1
    client.timeout = settings.health_test_timeout_seconds
    called_at = datetime.now(UTC)
    error_family: str | None = None
    value: Any = None
    attempts: list[NapixResult] = []
    try:
        try:
            async with client:
                value = await e.invoke(hc, sample.values)
        except (IntegrationError, httpx.HTTPError) as exc:
            error_family = type(exc).__name__
    finally:
        attempts = list(recorder.pending)
        recorder.flush(session)
    last = final_attempt(attempts, raised=error_family is not None)
    family = (last.error_family if last is not None and last.error_family else None) or error_family
    ok = error_family is None and last is not None and last.ok
    answered = ok or (last is not None and family in ANSWERED_FAMILIES)
    napix_status = last.napix_status if last is not None else None
    http_status = last.http_status if last is not None else None
    summary: dict[str, Any] = {"kind": e.kind, "row_count": None, "field_names": [], "facts": []}
    if ok and last is not None:
        summary = _summary(session, settings, e, sample, last, value)
    outcome = TestOutcome(
        api=key,
        ok=ok,
        answered=answered,
        status=_status(ok, answered),
        reason=system_health.plain_reason(None if ok else family, napix_status, None if ok else http_status),
        http_status=http_status,
        napix_status=napix_status,
        error_family=None if ok else family,
        duration_ms=sum(a.duration_ms for a in attempts),
        attempts=len(attempts),
        called_at=called_at,
        token_verified=last.token_verified if last is not None else None,
        remaining=recorder.last_remaining,
        input={"label": sample.label, "values": sample.public_values()},
        summary=summary,
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        system_health.TEST_ACTION,
        "napix",
        None,
        after={
            "api": key,
            "path": e.path,
            "ok": outcome.ok,
            "answered": outcome.answered,
            "http_status": outcome.http_status,
            "napix_status": outcome.napix_status,
            "error_family": outcome.error_family,
            "duration_ms": outcome.duration_ms,
            "attempts": outcome.attempts,
            "remaining": outcome.remaining,
            "sample": _audit_sample(sample),
            "summary": summary,
        },
    )
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
