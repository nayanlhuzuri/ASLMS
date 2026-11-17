"""Order sections (design `order-sections`): the reader's job, the replacement of readings, the live checks against
`orders` and `cases`, the data-health block, the check list and the Orders tab's reading.

- The job (decisions 3, 4, 18, 22, 23; design `order-sections-review-advisories`, decisions 6 to 10): every 5-minute
  run takes orders with extracted text and no current reading, and readings whose parser version is older (behind a
  gate carried in `job_runs.counters`); the daily full check from 01:30 IST also takes readings whose document
  changed, whose text changed (by its SHA-256), or whose text is gone, retries the orders with an open failure once a
  day and resolves failures whose text has gone. `read_batch` parses each (document, text) once
  (`services/order_parse.py`, rules only) and, per order in one savepoint, marks the old reading replaced and inserts
  the new one. A row never changes except to be marked replaced once (trigger `order_sections_replace_once`); nothing
  is deleted. No locks on `orders`: the partial unique index on current rows and an `UPDATE … WHERE replaced_at IS
  NULL` that must touch one row settle a race, the loser counting `skipped`. Court orders only (kind `order`, group
  `court_record`). System work: one `job_runs` row (`order_sections`) per run, no audit row, no event; a failure goes
  to `source_failures` (kind `order_parse`, ref the order id) and is resolved when the order is read. No NAPIX call,
  nothing sent to SourceTrace or any model.
- The live checks (decisions 5 and 13): computed in SQL whenever read, never stored, so a corrected case leaves no
  stale flag; `orders` and `cases` are never written from the text. A printed CNR or case number of another case on
  the same PDF, or the order's own case among the printed `Linked Case :` entries, is a `common_order`, not a mismatch.
- Reads (decisions 19 to 21): `status` (the data-health block, each part isolated under its own timeout),
  `checks_pass` and `check_rows` (Problems and Fixes → Data Gaps, no body or title text), `brief` (the Orders list,
  with the reading's state) and `sections_out` (the Orders tab's "What the Order Says"), the last two only for a
  caller who may open the case and the order's PDF. `src_text` gives a `src` span only from the text the reading was
  made from."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    any_,
    case,
    cast,
    exists,
    false,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from uuid6 import uuid7

from aslms.core import clock
from aslms.core.config import Settings, get_settings
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DocumentText,
    Order,
    OrderKind,
    OrderLayout,
    OrderOutcome,
    OrderSection,
    OrderSectionFlag,
    OrderSectionReplaceReason,
    TextStatus,
)
from aslms.domain.ops import JobRun, JobStatus, SourceFailure
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, source_failures, visibility
from aslms.services import order_parse as parse_mod
from aslms.services import order_parse_rules as R
from aslms.services.access import Member
from aslms.services.cases import CaseNotFound
from aslms.services.reporting_common import isolated

log = logging.getLogger(__name__)

JOB = "order_sections"
FAILURE_KIND = "order_parse"
REASONS = tuple(r.value for r in OrderSectionReplaceReason)
COUNTERS = (
    "claimed",
    "parsed",
    "template",
    "whole",
    "replaced_parser_version",
    "replaced_text_reextracted",
    "replaced_document_changed",
    "text_gone",
    "skipped",
    "failed",
    "retried",  # claimed with an open `order_parse` failure (the retry pass, after the five sets)
)
CHECKS = (
    "cnr_differs",
    "case_no_differs",
    "date_differs",
    "reserved_date_differs",
    "pronounced_date_differs",
    "form_differs",
    "common_order",
)
FLAGS = tuple(f.value for f in OrderSectionFlag)
CHECK_NAMES = CHECKS + FLAGS
# the job's gates and the full check's figures, written forward in `job_runs.counters` (design
# `order-sections-review-advisories`, decision 7)
GATE_COUNTERS = ("version_clear", "full_check_on", "full_check", "full_check_found", "failures_resolved")
# decision 6: the daily full check (sets 2, 3 and 5, the retry pass, stale failures) from this IST time on
FULL_CHECK_IST = dtime(1, 30)
# decision 8: set 3 hashes the texts of this many current readings per statement
HASH_PAGE = 20_000
UNIQUE_CURRENT = "ix_order_sections_current"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200


class NoReading(LookupError):
    """The order has no current reading (HTTP 404 `no_reading`, with the document's `text_status` and the
    `reading_state`, design `order-sections-review-advisories`, decision 15)."""

    def __init__(self, text_status: str | None, reading_state: str | None = None) -> None:
        super().__init__("this order has not been read yet")
        self.text_status = text_status
        self.reading_state = reading_state


class CheckInputError(ValueError):
    """An unknown check name (HTTP 400 `bad_input`)."""


class _Lost(Exception):
    """Another reader replaced the current row first (counted `skipped`)."""


@dataclass(frozen=True)
class Candidate:
    order_id: uuid.UUID
    set_no: (
        int  # decision 18: 1 new, 2 document changed, 3 text extracted again, 4 parser version, 5 text gone
    )
    current_id: uuid.UUID | None
    document_id: uuid.UUID | None
    pdf_sha256: str | None
    order_date: date | None
    napix_kind: str | None
    retry: bool = False  # the order had an open `order_parse` failure when it was claimed

    @property
    def reason(self) -> str | None:
        return {
            2: OrderSectionReplaceReason.DOCUMENT_CHANGED.value,
            3: OrderSectionReplaceReason.TEXT_REEXTRACTED.value,
            4: OrderSectionReplaceReason.PARSER_VERSION.value,
            5: OrderSectionReplaceReason.TEXT_GONE.value,
        }.get(self.set_no)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ candidates (18)


def _readable(doc=Document, text_row=DocumentText) -> ColumnElement[bool]:
    """Decision 2: a court order's PDF with extracted text."""
    return and_(
        doc.kind == DocKind.ORDER,
        doc.doc_group == DocGroup.COURT_RECORD,
        doc.text_status == TextStatus.EXTRACTED,
        text_row.full_text.is_not(None),
    )


def _current_exists(order=Order) -> ColumnElement[bool]:
    s = aliased(OrderSection)
    return exists().where(s.order_id == order.id, s.replaced_at.is_(None))


def _open_failure(order_id_col) -> ColumnElement[bool]:
    """The order has an open `order_parse` failure (unique (kind, ref), so one index probe per order)."""
    return exists().where(
        SourceFailure.kind == FAILURE_KIND,
        SourceFailure.ref == cast(order_id_col, String),
        SourceFailure.resolved_at.is_(None),
    )


def _retry_filter(order_id_col, retry: bool) -> ColumnElement[bool]:
    return _open_failure(order_id_col) if retry else ~_open_failure(order_id_col)


def _text_sha_sql(text_col=DocumentText.full_text) -> ColumnElement[str]:
    """Decision 8: the SHA-256 the reader stores (`sha256(full_text.encode("utf-8"))`, hex), computed in SQL; the
    database encoding is UTF-8."""
    return func.encode(func.sha256(func.convert_to(text_col, "UTF8")), "hex")


def any_open_failure(session: Session) -> bool:
    """One indexed probe: is any `order_parse` failure open (decision 6, the retry pass's gate)?"""
    return (
        session.scalar(
            select(literal(1))
            .where(SourceFailure.kind == FAILURE_KIND, SourceFailure.resolved_at.is_(None))
            .limit(1)
        )
        is not None
    )


def _set_new(limit: int, order_id: uuid.UUID | None, retry: bool = False):
    stmt = (
        select(
            Order.id,
            literal(1),
            literal(None).label("current_id"),
            Document.id,
            Document.sha256,
            Order.order_date,
            Order.kind,
        )
        .join(Document, Document.id == Order.document_id)
        .join(DocumentText, DocumentText.document_id == Document.id)
        .where(_readable(), ~_current_exists(), _retry_filter(Order.id, retry))
    )
    if order_id is not None:
        stmt = stmt.where(Order.id == order_id)
    return stmt.order_by(Order.created_at, Order.id).limit(limit)


def _set_current(set_no: int, limit: int, order_id: uuid.UUID | None, retry: bool = False, *, id_range=None):
    """Sets 2 to 5 over the current readings. Set 3 compares the text's hash (decision 8); `id_range` (after, upto)
    bounds it to one keyset page of readings by id."""
    s = OrderSection
    base = (
        select(s.order_id, literal(set_no), s.id, Document.id, Document.sha256, Order.order_date, Order.kind)
        .join(Order, Order.id == s.order_id)
        .where(s.replaced_at.is_(None), _retry_filter(s.order_id, retry))
    )
    if set_no == 5:
        stmt = base.outerjoin(Document, Document.id == Order.document_id).where(
            ~exists().where(
                DocumentText.document_id == Order.document_id,
                Document.id == Order.document_id,
                _readable(),
            )
        )
    else:
        stmt = base.join(Document, Document.id == Order.document_id).join(
            DocumentText, DocumentText.document_id == Document.id
        )
        stmt = stmt.where(_readable())
        changed = or_(s.document_id != Order.document_id, s.pdf_sha256 != Document.sha256)
        if set_no == 2:
            stmt = stmt.where(changed)
        elif set_no == 3:
            stmt = stmt.where(~changed, s.text_sha256 != _text_sha_sql())
        else:
            stmt = stmt.where(s.parser_version < R.PARSER_VERSION)
    if order_id is not None:
        stmt = stmt.where(s.order_id == order_id)
    if id_range is not None:
        after, upto = id_range
        if after is not None:
            stmt = stmt.where(s.id > after)
        if upto is not None:
            stmt = stmt.where(s.id <= upto)
        return stmt.order_by(s.id).limit(limit)
    return stmt.order_by(s.created_at, s.id).limit(limit)


def _hash_pages(session: Session, limit: int, order_id: uuid.UUID | None, retry: bool):
    """Decision 8: set 3 walked in keyset pages of `HASH_PAGE` current readings by id, one hashing statement per page
    (so no statement reads every text at once), until `limit` rows are found or the readings end."""
    if order_id is not None:
        yield from session.execute(_set_current(3, limit, order_id, retry)).all()
        return
    after: uuid.UUID | None = None
    found = 0
    while found < limit:
        page = select(OrderSection.id).where(OrderSection.replaced_at.is_(None))
        if after is not None:
            page = page.where(OrderSection.id > after)
        # the page's last reading (None: fewer than a page are left, so this is the last page)
        upto = session.scalar(page.order_by(OrderSection.id).offset(HASH_PAGE - 1).limit(1))
        for row in session.execute(_set_current(3, limit - found, None, retry, id_range=(after, upto))).all():
            found += 1
            yield row
        if upto is None:
            return
        after = upto


def candidates(
    session: Session,
    *,
    batch: int,
    order_id: uuid.UUID | None = None,
    full: bool = False,
    retry: bool = False,
    version_gate: bool = False,
    info: dict[str, Any] | None = None,
) -> list[Candidate]:
    """Decisions 18 of row 250 and 6 to 9 of `order-sections-review-advisories`, at most `batch` orders, read without
    locks:

    - every run: set 1 (new orders with extracted text and no current reading) and set 4 (readings below
      `PARSER_VERSION`), set 4 skipped when `version_gate` says it is known empty (never with `full`);
    - with `full` (the daily full check): set 2 (document changed), set 3 (text changed, by hash) and set 5 (text
      gone);
    - with `retry`, and only when one probe finds an open `order_parse` failure: the same sets again for the orders
      with an open failure, after every other candidate;
    - with `order_id`: every set and the retry pass for that one order.

    `info` receives `set4_short` (set 4 ran and returned fewer rows than it asked for) and `full_found` (candidates of
    sets 2, 3 and 5)."""
    batch = max(1, int(batch))
    if order_id is not None:
        full = retry = True
        version_gate = False
    if full:
        version_gate = False
    plan: list[int] = [1] + ([] if version_gate else [4]) + ([2, 3, 5] if full else [])
    passes = [False] + ([True] if retry and any_open_failure(session) else [])
    out: dict[uuid.UUID, Candidate] = {}
    meta = {"set4_short": None, "full_found": 0}
    for is_retry in passes:
        for set_no in plan:
            left = batch - len(out)
            if left <= 0:
                break
            if set_no == 1:
                rows = session.execute(_set_new(left, order_id, is_retry)).all()
            elif set_no == 4:  # only set 1 comes before it, and the two never share an order
                rows = session.execute(_set_current(4, left, order_id, is_retry)).all()
            elif set_no == 3:
                rows = list(_hash_pages(session, left + len(out), order_id, is_retry))
            else:
                rows = session.execute(_set_current(set_no, left + len(out), order_id, is_retry)).all()
            if set_no == 4 and not is_retry:
                meta["set4_short"] = len(rows) < left
            for oid, sn, cur, doc_id, sha, odate, kind in rows:
                if oid in out or len(out) >= batch:
                    continue
                out[oid] = Candidate(
                    oid, int(sn), cur, doc_id, sha, odate, _value(kind) if kind else None, is_retry
                )
                if set_no in (2, 3, 5):
                    meta["full_found"] += 1
    if info is not None:
        info.update(meta)
    return list(out.values())


def resolve_stale_failures(session: Session) -> int:
    """Decision 10: every open `order_parse` failure whose order no longer has a readable text is resolved (such an
    order has no reading to replace and is no candidate, so nothing else would close it)."""
    readable_order = (
        select(literal(1))
        .select_from(Order)
        .join(Document, Document.id == Order.document_id)
        .join(DocumentText, DocumentText.document_id == Document.id)
        .where(cast(Order.id, String) == SourceFailure.ref, _readable())
        .exists()
    )
    return int(
        session.execute(
            update(SourceFailure)
            .where(
                SourceFailure.kind == FAILURE_KIND,
                SourceFailure.resolved_at.is_(None),
                ~readable_order,
            )
            .values(resolved_at=func.now())
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )


# ------------------------------------------------------------------------------------------------ writing (4, 23)


def _row_values(parsed: parse_mod.Parsed) -> dict[str, Any]:
    cols = parsed.columns()
    cols["layout"] = OrderLayout(cols["layout"])
    cols["form"] = OrderKind(cols["form"])
    cols["outcome"] = OrderOutcome(cols["outcome"]) if cols["outcome"] else None
    cols["flags"] = [OrderSectionFlag(f) for f in cols["flags"]]
    return cols


def _unique_current(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return (
        getattr(orig, "sqlstate", None) == "23505"
        and getattr(diag, "constraint_name", None) == UNIQUE_CURRENT
    )


def _write_one(
    session: Session, cand: Candidate, parsed: parse_mod.Parsed | None, text_sha: str | None
) -> uuid.UUID | None:
    """One order's replacement in the caller's savepoint: the old current row marked replaced (it must be this
    reader that does it), then the new row inserted. Raises `_Lost` when another reader got there first."""
    new_id = uuid7() if parsed is not None else None
    if cand.current_id is not None:
        n = session.execute(
            update(OrderSection)
            .where(OrderSection.id == cand.current_id, OrderSection.replaced_at.is_(None))
            .values(
                replaced_at=func.clock_timestamp(),
                replaced_by_id=new_id,
                replace_reason=OrderSectionReplaceReason(cand.reason),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if n != 1:
            raise _Lost
    if parsed is not None:
        session.execute(
            insert(OrderSection).values(
                id=new_id,
                order_id=cand.order_id,
                document_id=cand.document_id,
                pdf_sha256=cand.pdf_sha256,
                text_sha256=text_sha,
                created_at=func.clock_timestamp(),
                updated_at=func.clock_timestamp(),
                **_row_values(parsed),
            )
        )
    return new_id


def _record_failure(session: Session, cand: Candidate, exc: BaseException, *, traceback: bool) -> None:
    """Decision 9: the failure goes to `source_failures`; the first failure of an order is logged with its traceback
    (`traceback`), a failure on a retry as one warning line (the order, the attempt count, the exception class)."""
    source_failures.record(session, FAILURE_KIND, str(cand.order_id), f"{exc.__class__.__name__}: {exc}")
    if not cand.retry:
        if traceback:
            log.error("order sections: order %s failed", cand.order_id, exc_info=exc)
        else:  # another order on the same text logged the traceback in this batch
            log.warning(
                "order sections: order %s failed (same text): %s", cand.order_id, exc.__class__.__name__
            )
        return
    attempts = session.scalar(
        select(SourceFailure.attempts).where(
            SourceFailure.kind == FAILURE_KIND, SourceFailure.ref == str(cand.order_id)
        )
    )
    log.warning(
        "order sections: order %s failed again (attempt %s): %s",
        cand.order_id,
        attempts,
        exc.__class__.__name__,
    )


def read_batch(
    session: Session,
    *,
    batch: int | None = None,
    order_id: uuid.UUID | None = None,
    dry_run: bool = False,
    full: bool = False,
    retry: bool = False,
    gates: dict[str, int] | None = None,
) -> dict[str, int]:
    """Decisions 3, 4 and 23 of row 250, 6 to 10 of `order-sections-review-advisories`: the candidates grouped by
    (document, order date, NAPIX kind) and each text parsed once; per order, one savepoint. With `full` the full check's
    sets run and the stale failures are resolved; with `retry` the orders with an open failure are retried; `gates` are
    the previous run's counters (`version_clear`), used for set 4's gate. Returns the counters, `version_clear`,
    `full_check_found` and `failures_resolved` included. With `dry_run` it parses and counts but writes nothing."""
    batch = batch or get_settings().order_sections_batch
    counters = dict.fromkeys(COUNTERS, 0) | dict.fromkeys(
        ("version_clear", "full_check_found", "failures_resolved"), 0
    )
    prev_clear = int((gates or {}).get("version_clear") or 0) == R.PARSER_VERSION
    info: dict[str, Any] = {}
    cands = candidates(
        session,
        batch=batch,
        order_id=order_id,
        full=full,
        retry=retry,
        version_gate=prev_clear and gates is not None,
        info=info,
    )
    counters["claimed"] = len(cands)
    counters["retried"] = sum(1 for c in cands if c.retry)
    counters["full_check_found"] = int(info.get("full_found") or 0)
    short = info.get("set4_short")
    clear = bool(short) if short is not None else prev_clear
    counters["version_clear"] = R.PARSER_VERSION if clear else 0
    if full and not dry_run:
        counters["failures_resolved"] = resolve_stale_failures(session)
    if not cands:
        return counters
    doc_ids = sorted({c.document_id for c in cands if c.set_no != 5 and c.document_id is not None})
    texts: dict[uuid.UUID, str] = {}
    if doc_ids:
        for doc_id, full_text in session.execute(
            select(DocumentText.document_id, DocumentText.full_text).where(
                DocumentText.document_id.in_(doc_ids)
            )
        ).all():
            texts[doc_id] = full_text or ""
    parsed_cache: dict[tuple, tuple[parse_mod.Parsed | None, str | None, BaseException | str | None]] = {}
    traced: set[tuple] = set()  # one traceback per text and batch, however many orders share it
    for cand in cands:
        parsed: parse_mod.Parsed | None = None
        text_sha: str | None = None
        error: BaseException | str | None = None
        if cand.set_no != 5:
            key = (cand.document_id, cand.order_date, cand.napix_kind)
            if key not in parsed_cache:
                text_now = texts.get(cand.document_id)
                if (
                    text_now is None
                ):  # the text went between the two reads: the next full check takes it as set 5
                    parsed_cache[key] = (None, None, "skip")
                else:
                    try:
                        p = parse_mod.parse(text_now, order_date=cand.order_date, napix_kind=cand.napix_kind)
                        parsed_cache[key] = (p, hashlib.sha256(text_now.encode("utf-8")).hexdigest(), None)
                    except Exception as exc:  # noqa: BLE001 — a reader bug on one text never stops the run
                        parsed_cache[key] = (None, None, exc)
            parsed, text_sha, error = parsed_cache[key]
            if error == "skip":
                counters["skipped"] += 1
                continue
            if isinstance(error, BaseException):
                counters["failed"] += 1
                if not dry_run:
                    _record_failure(session, cand, error, traceback=key not in traced)
                    traced.add(key)
                continue
        if dry_run:
            _count(counters, cand, parsed)
            continue
        try:
            with session.begin_nested():
                _write_one(session, cand, parsed, text_sha)
                source_failures.resolve(session, FAILURE_KIND, str(cand.order_id))
        except _Lost:
            counters["skipped"] += 1
            continue
        except IntegrityError as exc:
            if _unique_current(exc):
                counters["skipped"] += 1
                continue
            counters["failed"] += 1
            _record_failure(session, cand, exc, traceback=True)
            continue
        except Exception as exc:  # noqa: BLE001 — one bad order must not stop the run; it is recorded
            counters["failed"] += 1
            _record_failure(session, cand, exc, traceback=True)
            continue
        _count(counters, cand, parsed)
    session.flush()
    return counters


def _count(counters: dict[str, int], cand: Candidate, parsed: parse_mod.Parsed | None) -> None:
    if cand.set_no == 5:
        counters["text_gone"] += 1
        return
    counters["parsed"] += 1
    counters[parsed.layout] += 1
    if cand.reason:
        counters[f"replaced_{cand.reason}"] += 1


def _ist_ymd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def full_check_due(prev: dict[str, Any] | None, now: datetime) -> bool:
    """Decision 6: the full check is due in the first run at or after `FULL_CHECK_IST` each IST day, and again in the
    next run while the last one filled its batch (its date is then not written forward). With no previous counters
    (a first or failed run) it is due."""
    local = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(clock.IST)
    due_day = local.date() if local.time() >= FULL_CHECK_IST else local.date() - timedelta(days=1)
    last_on = int((prev or {}).get("full_check_on") or 0)
    return last_on < _ist_ymd(due_day)


def _previous_counters(session: Session) -> dict[str, Any] | None:
    """Decision 7: the counters of the latest finished run of the job (a run still going has none yet, and must not
    make an overlapping run start a second full check); None after a failed run, so the next starts with no gates."""
    counters = session.scalar(
        select(JobRun.counters)
        .where(JobRun.job == JOB, JobRun.status != JobStatus.RUNNING)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    return dict(counters) if counters else None


def run_job(session: Session, *, cfg: Settings | None = None, now: datetime | None = None) -> dict[str, int]:
    """The 5-minute job (decisions 6 and 7): one `job_runs` row (`partial` when an order failed), as
    `next_dates.run_job`. It reads the previous run's counters (set 4's gate, the date of the last full check), runs a
    light batch or, when due, the full check with the retry pass, and writes the gates forward."""
    cfg = cfg or get_settings()
    now = now or _now()
    prev = _previous_counters(session)
    run = JobRun(job=JOB, run_date=clock.today_ist(now), started_at=now)
    session.add(run)
    session.flush()
    full = full_check_due(prev, now)
    try:
        counters = read_batch(session, batch=cfg.order_sections_batch, full=full, retry=full, gates=prev)
    except Exception as exc:
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = _now()
        session.flush()
        raise
    last_on = int((prev or {}).get("full_check_on") or 0)
    # complete unless the batch was filled by candidates other than retries (a full batch of failing orders alone
    # does not keep the check due: they are retried the next day)
    completed = full and counters["claimed"] - counters["retried"] < cfg.order_sections_batch
    counters["full_check"] = 1 if full else 0
    counters["full_check_on"] = _ist_ymd(clock.today_ist(now)) if completed else last_on
    if not full:
        counters["full_check_found"] = int((prev or {}).get("full_check_found") or 0)
    run.counters = counters
    run.status = JobStatus.PARTIAL if counters.get("failed") else JobStatus.SUCCEEDED
    run.finished_at = _now()
    session.flush()
    return counters


def backfill(
    session_factory: Callable[[], Session],
    *,
    batch: int,
    pause_ms: int = 200,
    limit: int | None = None,
    dry_run: bool = False,
    echo: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """`aslms orders parse --backfill` (decision 23 of row 250, "Services" of `order-sections-review-advisories`):
    light batches (sets 1 and 4) until one claims nothing, then full batches with the retry pass (sets 2, 3, 5 and
    the orders with an open failure) until one claims nothing or reads nothing and holds only retries; one commit per
    batch, a pause between batches, at most `limit` orders. Stopped and started again, it carries on where it was.
    With `dry_run` it parses and counts one pass of `limit` orders (default one batch) and writes nothing."""
    keys = COUNTERS + ("full_check_found", "failures_resolved")
    total = dict.fromkeys(keys, 0)
    done = 0
    seen: set[uuid.UUID] = set()
    full = False
    while True:
        size = batch if limit is None else min(batch, limit - done)
        if size <= 0:
            break
        with session_factory() as s:
            if dry_run:
                counters = _dry_batch(s, size, seen)
                s.rollback()
            else:
                counters = read_batch(s, batch=size, full=full, retry=full)
                s.commit()
        for k in keys:
            total[k] += counters.get(k, 0)
        done += counters["claimed"]
        if echo is not None:
            echo(
                f"{'full ' if full else ''}batch: {counters['claimed']} claimed, {counters['parsed']} read, "
                f"{counters['skipped']} skipped, {counters['failed']} failed (total {done})"
            )
        if dry_run:
            if counters["claimed"] == 0 or limit is None:
                break
        elif not full:
            if counters["claimed"] == 0:
                full = True  # the light sets are empty: the full check's sets and the retries, once
                continue
        else:
            # Orders with an open failure are claimed after every other candidate, so a batch made only of them,
            # none read, means nothing readable is left: stop, or the same failing orders would be claimed again
            # forever. A skip is a race another reader won or a text that went; the next batch moves past it.
            progress = counters["parsed"] + counters["text_gone"] + counters["skipped"]
            only_retries = counters["retried"] == counters["claimed"]
            if counters["claimed"] == 0 or (progress == 0 and only_retries):
                break
        if pause_ms:
            time.sleep(pause_ms / 1000)
    return total


def _dry_batch(session: Session, size: int, seen: set[uuid.UUID]) -> dict[str, int]:
    """A dry-run pass: the next `size` new orders after those already seen, parsed and counted, nothing written."""
    counters = dict.fromkeys(COUNTERS, 0)
    stmt = (
        select(Order.id, Order.order_date, Order.kind, DocumentText.full_text)
        .join(Document, Document.id == Order.document_id)
        .join(DocumentText, DocumentText.document_id == Document.id)
        .where(_readable(), ~_current_exists())
        .order_by(Order.created_at, Order.id)
        .offset(len(seen))
        .limit(size)
    )
    for oid, odate, kind, full in session.execute(stmt).all():
        seen.add(oid)
        counters["claimed"] += 1
        try:
            p = parse_mod.parse(full or "", order_date=odate, napix_kind=_value(kind))
        except Exception:  # noqa: BLE001 — counted, as the job would record it
            counters["failed"] += 1
            continue
        counters["parsed"] += 1
        counters[p.layout] += 1
        DRY_STATS.add(p)
    return counters


class _DryStats:
    """What a dry run prints beside the counters: forms, flags, procedural share and citations by reporter (the
    build report's numbers, design "Verification" 2)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.forms: dict[str, int] = {}
        self.flags: dict[str, int] = {}
        self.reporters: dict[str, int] = {}
        self.procedural = 0
        self.interim = 0
        self.interim_procedural = 0
        self.registrar = 0
        self.outcomes: dict[str, int] = {}
        self.started = time.perf_counter()

    def add(self, p: parse_mod.Parsed) -> None:
        self.forms[p.form] = self.forms.get(p.form, 0) + 1
        for f in p.flags:
            self.flags[f] = self.flags.get(f, 0) + 1
        for j in p.facts["judgments"]:
            self.reporters[j["reporter"]] = self.reporters.get(j["reporter"], 0) + j["count"]
        if p.outcome:
            self.outcomes[p.outcome] = self.outcomes.get(p.outcome, 0) + 1
        self.procedural += int(p.procedural)
        self.registrar += int(p.registrar)
        if p.form == "interim":
            self.interim += 1
            self.interim_procedural += int(p.procedural)

    def as_dict(self) -> dict[str, Any]:
        return {
            "by_form": self.forms,
            "flags": self.flags,
            "citations_by_reporter": self.reporters,
            "outcomes": self.outcomes,
            "procedural": self.procedural,
            "registrar": self.registrar,
            "interim": self.interim,
            "interim_procedural": self.interim_procedural,
            "seconds": round(time.perf_counter() - self.started, 2),
        }


DRY_STATS = _DryStats()


# ------------------------------------------------------------------------------------------------ live checks (5, 13)


def _compact(col):
    """The expression of `ix_cases_case_no_compact`: upper case, no white space."""
    return func.upper(func.regexp_replace(col, r"\s", "", "g"))


def check_columns(s=OrderSection, o=Order, c=Case) -> dict[str, ColumnElement[bool]]:
    """Decision 13, one definition: the live checks of a current reading `s` of order `o` of case `c`."""
    cnr_raw = and_(s.printed_cnr.is_not(None), c.cnr.is_not(None), s.printed_cnr != c.cnr)
    case_no_raw = and_(
        s.printed_case_no.is_not(None),
        c.case_no_text.is_not(None),
        _compact(s.printed_case_no) != _compact(c.case_no_text),
    )
    o2 = aliased(Order)
    c2 = aliased(Case)
    other_on_pdf = (
        select(literal(1))
        .select_from(o2)
        .join(c2, c2.id == o2.case_id)
        .where(
            o2.document_id == o.document_id,
            o2.case_id != o.case_id,
            or_(c2.cnr == s.printed_cnr, _compact(c2.case_no_text) == _compact(s.printed_case_no)),
        )
        .exists()
    )
    lc = func.jsonb_array_elements(s.linked_cases).table_valued("value").alias("lc")
    own_linked = (
        select(literal(1))
        .select_from(lc)
        .where(_compact(lc.c.value.op("->>")("case_no")) == _compact(c.case_no_text))
        .exists()
    )
    common = case((or_(cnr_raw, case_no_raw), or_(other_on_pdf, own_linked)), else_=false())
    judgment = s.form == OrderKind.JUDGMENT
    return {
        "cnr_differs": and_(cnr_raw, ~common),
        "case_no_differs": and_(case_no_raw, ~common),
        "date_differs": and_(
            s.printed_date.is_not(None),
            s.printed_date != o.order_date,
            ~and_(
                judgment,
                o.date_judgement_pronounced.is_not(None),
                s.printed_date == o.date_judgement_pronounced,
            ),
        ),
        "reserved_date_differs": and_(
            s.printed_reserved_on.is_not(None),
            o.date_judgement_reserved.is_not(None),
            s.printed_reserved_on != o.date_judgement_reserved,
        ),
        "pronounced_date_differs": and_(
            s.printed_pronounced_on.is_not(None),
            o.date_judgement_pronounced.is_not(None),
            s.printed_pronounced_on != o.date_judgement_pronounced,
        ),
        "form_differs": s.form != o.kind,
        "common_order": common,
    }


def _check_select(extra=None):
    s, o, c = OrderSection, Order, Case
    cols = check_columns(s, o, c)
    stmt = (
        select(*[expr.label(name) for name, expr in cols.items()], s.id.label("section_id"))
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.replaced_at.is_(None))
    )
    if extra is not None:
        stmt = stmt.where(extra)
    return stmt, cols


def _mismatch(cols: dict[str, ColumnElement[bool]]) -> ColumnElement[bool]:
    return or_(*[cols[n] for n in CHECKS if n != "common_order"])


def _flag_condition(name: str) -> ColumnElement[bool]:
    return literal(OrderSectionFlag(name), OrderSection.flags.type.item_type) == any_(OrderSection.flags)


# ------------------------------------------------------------------------------------------------ reads (19 to 21)


def _row_checks():
    """Decision 13 of `order-sections-review-advisories`: the live checks of every current reading, the raw CNR and
    case-number mismatches and the common-order test computed once per row in a sub-select (`OFFSET 0` keeps the
    planner from inlining it, which would evaluate the common-order sub-queries once per reference, as the
    `check_columns` expressions were). Returns the sub-select (with `section_id` and `flags`) and the check expressions
    over its columns, by name."""
    s, o, c = OrderSection, Order, Case
    cnr_raw = and_(s.printed_cnr.is_not(None), c.cnr.is_not(None), s.printed_cnr != c.cnr)
    case_no_raw = and_(
        s.printed_case_no.is_not(None),
        c.case_no_text.is_not(None),
        _compact(s.printed_case_no) != _compact(c.case_no_text),
    )
    o2 = aliased(Order)
    c2 = aliased(Case)
    other_on_pdf = (
        select(literal(1))
        .select_from(o2)
        .join(c2, c2.id == o2.case_id)
        .where(
            o2.document_id == o.document_id,
            o2.case_id != o.case_id,
            or_(c2.cnr == s.printed_cnr, _compact(c2.case_no_text) == _compact(s.printed_case_no)),
        )
        .exists()
    )
    lc = func.jsonb_array_elements(s.linked_cases).table_valued("value").alias("lc")
    own_linked = (
        select(literal(1))
        .select_from(lc)
        .where(_compact(lc.c.value.op("->>")("case_no")) == _compact(c.case_no_text))
        .exists()
    )
    full = check_columns(s, o, c)
    cheap = ("date_differs", "reserved_date_differs", "pronounced_date_differs", "form_differs")
    sub = (
        select(
            s.id.label("section_id"),
            s.flags.label("flags"),
            cnr_raw.label("cnr_raw"),
            case_no_raw.label("case_no_raw"),
            case((or_(cnr_raw, case_no_raw), or_(other_on_pdf, own_linked)), else_=false()).label("common"),
            *[full[n].label(n) for n in cheap],
        )
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.replaced_at.is_(None))
        .offset(0)
        .subquery("rc")
    )
    cols: dict[str, ColumnElement[bool]] = {
        "cnr_differs": and_(sub.c.cnr_raw, ~sub.c.common),
        "case_no_differs": and_(sub.c.case_no_raw, ~sub.c.common),
        **{n: sub.c[n] for n in cheap},
        "common_order": sub.c.common,
    }
    return sub, cols


def _flag_in(name: str, flags_col) -> ColumnElement[bool]:
    return literal(OrderSectionFlag(name), OrderSection.flags.type.item_type) == any_(flags_col)


def checks_pass(session: Session) -> dict[str, Any]:
    """Decision 12 of `order-sections-review-advisories`: the live checks of decision 13 of row 250 over every current
    reading, in one statement: `counts` by check and by flag, and `any` (a mismatch other than `common_order`, or any
    flag)."""
    sub, cols = _row_checks()
    mismatch = or_(*[cols[n] for n in CHECKS if n != "common_order"])
    row = session.execute(
        select(
            *[func.count().filter(cols[n]) for n in CHECKS],
            *[func.count().filter(_flag_in(f, sub.c.flags)) for f in FLAGS],
            func.count().filter(or_(mismatch, func.cardinality(sub.c.flags) > 0)),
        ).select_from(sub)
    ).one()
    counts = {n: int(v or 0) for n, v in zip(CHECK_NAMES, row[:-1], strict=True)}
    return {"counts": counts, "any": int(row[-1] or 0)}


def _counts_part(session: Session) -> dict[str, Any]:
    """Decision 12 of `order-sections-review-advisories`, `counts`: two statements, one over the readable orders and
    one pass over the current readings with `FILTER` aggregates. `waiting` is set 1 + set 4, failing orders left out."""
    text_row = session.execute(
        select(
            func.count(),
            func.count().filter(~_current_exists(), ~_open_failure(Order.id)),
        )
        .select_from(Order)
        .join(Document, Document.id == Order.document_id)
        .join(DocumentText, DocumentText.document_id == Document.id)
        .where(_readable())
    ).one()
    s = OrderSection
    od = aliased(Order)
    dd = aliased(Document)
    set4 = and_(
        s.parser_version < R.PARSER_VERSION,
        dd.kind == DocKind.ORDER,
        dd.doc_group == DocGroup.COURT_RECORD,
        dd.text_status == TextStatus.EXTRACTED,
        ~_open_failure(s.order_id),
    )
    layouts = [lay.value for lay in OrderLayout]
    forms = [k.value for k in OrderKind]
    agg = session.execute(
        select(
            func.count().filter(s.parser_version == R.PARSER_VERSION),
            func.count().filter(set4),
            func.count().filter(s.procedural),
            func.count().filter(s.registrar),
            func.count().filter(s.outcome.is_not(None)),
            func.count().filter(func.jsonb_array_length(s.facts["directions"]) > 0),
            func.count(func.distinct(s.body_sha256)),
            *[func.count().filter(s.layout == OrderLayout(v)) for v in layouts],
            *[func.count().filter(s.form == OrderKind(v)) for v in forms],
            *[func.count().filter(_flag_condition(f)) for f in FLAGS],
        )
        .select_from(s)
        .outerjoin(od, od.id == s.order_id)
        .outerjoin(dd, dd.id == od.document_id)
        .where(s.replaced_at.is_(None))
    ).one()
    vals = [int(v or 0) for v in agg]
    read, set4_n, proc, reg, outcome, directions, distinct = vals[:7]
    rest = vals[7:]
    by_layout = dict(zip(layouts, rest[: len(layouts)], strict=True))
    rest = rest[len(layouts) :]
    by_form = dict(zip(forms, rest[: len(forms)], strict=True))
    flags = dict(zip(FLAGS, rest[len(forms) :], strict=True))
    return {
        "orders_with_text": int(text_row[0] or 0),
        "read": read,
        "waiting": int(text_row[1] or 0) + set4_n,
        "by_layout": by_layout,
        "by_form": by_form,
        "procedural": proc,
        "registrar": reg,
        "with_outcome": outcome,
        "with_directions": directions,
        "distinct_bodies": distinct,
        "flags": flags,
    }


COUNT_FIELDS = (
    "orders_with_text",
    "read",
    "waiting",
    "by_layout",
    "by_form",
    "procedural",
    "registrar",
    "with_outcome",
    "with_directions",
    "distinct_bodies",
    "flags",
)


def status(
    session: Session,
    *,
    timeout_s: int | None = None,
    restore_s: int | None = None,
    checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decision 21 of row 250, decision 12 of `order-sections-review-advisories`: the data-health block, counts only,
    in three parts. Always, from small indexed reads: `parser_version`, `failed`, `last_run`, `full_check` and
    `timed_out`. Then `counts` and `checks`, each in a savepoint under `timeout_s` (the outer timeout set back to
    `restore_s`); a part that runs out of time leaves its fields null and its name in `timed_out`. `checks` passes a
    result of `checks_pass` already computed (the gaps route), so that part is not run again."""
    cfg = get_settings()
    timeout_s = timeout_s or cfg.order_sections_status_timeout_seconds
    restore_s = restore_s or cfg.report_statement_timeout_seconds
    failed = int(
        session.scalar(
            select(func.count())
            .select_from(SourceFailure)
            .where(SourceFailure.kind == FAILURE_KIND, SourceFailure.resolved_at.is_(None))
        )
        or 0
    )
    last = session.scalar(select(JobRun).where(JobRun.job == JOB).order_by(JobRun.started_at.desc()).limit(1))
    timed_out: list[str] = []
    counts, late = isolated(session, timeout_s, restore_s, lambda: _counts_part(session), part="order counts")
    if late:
        timed_out.append("counts")
    if checks is None:
        checks, late = isolated(
            session, timeout_s, restore_s, lambda: checks_pass(session), part="order checks"
        )
        if late:
            timed_out.append("checks")
    lc = dict(last.counters or {}) if last is not None else {}
    last_on = int(lc.get("full_check_on") or 0)
    return {
        "parser_version": R.PARSER_VERSION,
        **{k: (counts or {}).get(k) for k in COUNT_FIELDS},
        "failed": failed,
        "checks": {n: checks["counts"][n] for n in CHECKS} if checks is not None else None,
        "full_check": {
            "last_on": date(last_on // 10000, last_on // 100 % 100, last_on % 100) if last_on else None,
            "found": int(lc["full_check_found"]) if "full_check_found" in lc and last_on else None,
        },
        "timed_out": timed_out,
        "last_run": (
            {
                "started_at": last.started_at,
                "finished_at": last.finished_at,
                "status": _value(last.status),
                "counters": lc,
            }
            if last is not None
            else None
        ),
    }


def check_rows(
    session: Session,
    *,
    check: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    pass_: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int], list[dict[str, Any]]]:
    """Decision 21 of row 250, decision 13 of `order-sections-review-advisories`: current readings with a live
    mismatch or an intrinsic flag (or the one `check` asked for, which may be `common_order`), newest order first.
    `total` and `counts` come from one `checks_pass` (`pass_` when the caller already has it); the page is one
    statement. Identifiers and printed values only: no body or title text."""
    if check is not None and check not in CHECK_NAMES:
        raise CheckInputError(f"check is one of {', '.join(CHECK_NAMES)}")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    pass_ = pass_ if pass_ is not None else checks_pass(session)
    counts = dict(pass_["counts"])
    total = int(pass_["any"]) if check is None else int(counts[check])
    s, o, c = OrderSection, Order, Case
    sub, cols = _row_checks()
    if check is None:
        cond = or_(*[cols[n] for n in CHECKS if n != "common_order"], func.cardinality(sub.c.flags) > 0)
    elif check in CHECKS:
        cond = cols[check]
    else:
        cond = _flag_in(check, sub.c.flags)
    rows = session.execute(
        select(
            s.order_id,
            s.flags,
            s.printed_cnr,
            s.printed_case_no,
            s.printed_date,
            s.printed_reserved_on,
            s.printed_pronounced_on,
            s.form,
            o.order_no,
            o.order_date,
            o.kind,
            o.date_judgement_reserved,
            o.date_judgement_pronounced,
            c.id,
            c.ref_no,
            c.cnr,
            c.case_no_text,
            *[cols[n].label(n) for n in CHECKS],
        )
        .select_from(sub)
        .join(s, s.id == sub.c.section_id)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(cond)
        .order_by(o.order_date.desc(), o.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = []
    for r in rows:
        m = r._mapping
        items.append(
            {
                "case": {
                    "id": m[c.id],
                    "ref_no": m[c.ref_no],
                    "cnr": m[c.cnr],
                    "case_no_text": m[c.case_no_text],
                },
                "order_id": m[s.order_id],
                "order_no": m[o.order_no],
                "order_date": m[o.order_date],
                "kind": _value(m[o.kind]),
                "form": _value(m[s.form]),
                "checks": [n for n in CHECKS if m[n]],
                "flags": [_value(f) for f in (m[s.flags] or [])],
                "printed": {
                    "cnr": m[s.printed_cnr],
                    "case_no": m[s.printed_case_no],
                    "date": m[s.printed_date],
                    "reserved_on": m[s.printed_reserved_on],
                    "pronounced_on": m[s.printed_pronounced_on],
                },
                "held": {
                    "cnr": m[c.cnr],
                    "case_no": m[c.case_no_text],
                    "date": m[o.order_date],
                    "reserved_on": m[o.date_judgement_reserved],
                    "pronounced_on": m[o.date_judgement_pronounced],
                },
            }
        )
    return total, counts, items


def _parts_names(parts: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for p in parts or []:
        if p.get("part") and p["part"] not in out:
            out.append(p["part"])
    return out


READING_STATES = ("read", "not_read_yet", "scanned", "text_failed", "reading_failed", "withheld")


def _state(
    has_pdf: bool, visible: bool, has_reading: bool, text_status: str | None, failing: bool
) -> str | None:
    """Decision 15 of `order-sections-review-advisories`: the reading's state as the caller may know it. `withheld`
    is decided first (after "no stored PDF"), so a caller who may not open the PDF learns nothing about its text."""
    if not has_pdf:
        return None
    if not visible:
        return "withheld"
    if has_reading:
        return "read"
    if text_status == TextStatus.FAILED.value:
        return "text_failed"
    if text_status == TextStatus.NONE.value:
        return "scanned"
    if text_status == TextStatus.EXTRACTED.value and failing:
        return "reading_failed"
    return "not_read_yet"


def brief(session: Session, user: User | Member, order_ids) -> dict[uuid.UUID, dict[str, Any]]:
    """Decision 20 of row 250 and 15 of `order-sections-review-advisories` for the Orders list, in one query: for every
    order asked, `reading_state` and `reading` (the current reading's tags, only when the state is `read`). One
    document-visibility condition for the page; the open-failure probe by the unique `(kind, ref)` index."""
    ids = [i for i in dict.fromkeys(order_ids) if i is not None]
    out: dict[uuid.UUID, dict[str, Any]] = {i: {"reading": None, "reading_state": None} for i in ids}
    if not ids:
        return out
    can_docs = access.has(session, user, Permission.DOCUMENTS_VIEW)
    # aliases: the document rule correlates its own `orders` and `cases` subqueries on `documents` only
    s, o, c = OrderSection, aliased(Order), aliased(Case)
    cols = check_columns(s, o, c)
    compliance = s.facts["directions"].op("@>")(cast([{"kind": "compliance"}], JSONB))
    visible = visibility.document_visible_condition(session, user) if can_docs else false()
    rows = session.execute(
        select(
            o.id,
            Document.id,
            Document.text_status,
            visible,
            _open_failure(o.id),
            s.id,
            s.layout,
            s.form,
            s.procedural,
            s.registrar,
            s.outcome,
            func.char_length(s.body_text),
            s.parts,
            compliance,
            cols["common_order"],
            s.printed_case_no,
        )
        .select_from(o)
        .join(c, c.id == o.case_id)
        .outerjoin(Document, Document.id == o.document_id)
        .outerjoin(s, and_(s.order_id == o.id, s.replaced_at.is_(None)))
        .where(o.id.in_(ids))
    ).all()
    for (
        oid, doc_id, text_status, vis, failing, sec_id, layout, form, proc, reg, outcome, chars, parts, comp, common,
        printed,
    ) in rows:  # fmt: skip
        state = _state(
            doc_id is not None, bool(can_docs and vis), sec_id is not None, _value(text_status), bool(failing)
        )
        reading = None
        if state == "read":
            parts_list = _parts_names(parts)
            reading = {
                "layout": _value(layout),
                "form": _value(form),
                "procedural": bool(proc),
                "registrar": bool(reg),
                "outcome": _value(outcome) if outcome else None,
                "body_chars": int(chars or 0),
                "parts": [] if parts_list == [R.PART_BODY] else parts_list,
                "has_compliance_directions": bool(comp),
                "common_order": bool(common),
                "printed_case_no": printed if common else None,
            }
        out[oid] = {"reading": reading, "reading_state": state}
    return out


def _txt_item(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out = {k: item.get(k) for k in keys}
    out["page"] = item.get("page")
    out["txt"] = item.get("txt")
    return out


def sections_out(session: Session, user: User | Member, case: Case, order_id: uuid.UUID) -> dict[str, Any]:
    """Decision 19 and 20: the reading of one order of the case for a caller who may open the case, holds
    `documents.view` and passes the document rule for the order's PDF. `src` offsets are not shown; every item keeps
    its page and its `txt` span in `body_text`."""
    visibility.require_visible(session, user, case)
    order = session.scalar(select(Order).where(Order.id == order_id, Order.case_id == case.id))
    if order is None or not access.has(session, user, Permission.DOCUMENTS_VIEW):
        raise CaseNotFound("no such order")
    doc = session.get(Document, order.document_id) if order.document_id is not None else None
    if doc is not None and not visibility.can_view_document(session, user, doc):
        raise CaseNotFound("no such order")
    s, o, c = OrderSection, Order, Case
    cols = check_columns(s, o, c)
    row = session.execute(
        select(s, cols["common_order"])
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.order_id == order.id, s.replaced_at.is_(None))
    ).first()
    if row is None:
        text_status = _value(doc.text_status) if doc is not None else None
        failing = bool(session.scalar(select(_open_failure(literal(order.id)))))
        raise NoReading(text_status, _state(doc is not None, True, False, text_status, failing))
    sec, common = row
    facts = sec.facts or {}
    outcome = facts.get("outcome")
    span = parse_mod.next_date_span(sec.body_text, order.next_date_phrase)
    return {
        "order_id": order.id,
        "layout": _value(sec.layout),
        "form": _value(sec.form),
        "heading": sec.heading,
        "oral": sec.oral,
        "cav": sec.cav,
        "printed_date": sec.printed_date,
        "author": sec.author,
        "neutral_citation": sec.neutral_citation,
        "registrar": sec.registrar,
        "procedural": sec.procedural,
        "flags": [_value(f) for f in sec.flags or []],
        "outcome": (
            {
                "value": outcome["value"],
                "text": outcome["text"],
                "page": outcome["page"],
                "txt": outcome["txt"],
            }
            if outcome
            else None
        ),
        "body_text": sec.body_text,
        "paragraphs": [
            {"label": p.get("label"), "page": p.get("page"), "part": p.get("part"), "txt": p.get("txt")}
            for p in sec.paragraphs or []
        ],
        "parts": [
            {"part": p.get("part"), "page": p.get("page"), "txt": p.get("txt")}
            for p in sec.parts or []
            if p.get("part") != R.PART_BODY
        ],
        "directions": [
            _txt_item(d, ("kind", "text", "addressee", "period", "due_on"))
            for d in facts.get("directions") or []
        ],
        "acts": [_txt_item(a, ("act", "provisions", "kind", "count")) for a in facts.get("acts") or []],
        "judgments": [
            _txt_item(j, ("citation", "reporter", "year", "case_name", "count"))
            for j in facts.get("judgments") or []
        ],
        "next_date": {"txt": list(span) if span else None, "phrase": order.next_date_phrase},
        "common_order": {"printed_case_no": sec.printed_case_no} if common else None,
        "made_from": {
            "document_id": sec.document_id,
            "pdf_sha256": sec.pdf_sha256,
            "parser_version": sec.parser_version,
            "parsed_at": sec.created_at,
        },
    }


# ------------------------------------------------------------------------------------------------ the CLI's view


def resolve_order(session: Session, ref: str) -> Order | None:
    """`aslms orders show`: an order id, or `CNR|order_no|YYYY-MM-DD`."""
    try:
        return session.get(Order, uuid.UUID(ref))
    except ValueError:
        pass
    parts = ref.split("|")
    if len(parts) != 3:
        return None
    cnr, order_no, day = parts
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    return session.scalar(
        select(Order)
        .join(Case, Case.id == Order.case_id)
        .where(Case.cnr == cnr.strip().upper(), Order.order_no == order_no.strip(), Order.order_date == d)
    )


def current_for(session: Session, order_id: uuid.UUID) -> OrderSection | None:
    return session.scalar(
        select(OrderSection).where(OrderSection.order_id == order_id, OrderSection.replaced_at.is_(None))
    )


def text_matches(reading: Any, full_text: str | None) -> bool:
    """Decision 11 of `order-sections-review-advisories`: the text is the one the reading was made from (its SHA-256
    equals the reading's `text_sha256`)."""
    if full_text is None or not getattr(reading, "text_sha256", None):
        return False
    return hashlib.sha256(full_text.encode("utf-8")).hexdigest() == reading.text_sha256


def src_text(reading: Any, full_text: str | None, span) -> str | None:
    """Decision 11 of `order-sections-review-advisories`: `full_text[s:e]` for a `src` span of the reading, only when
    the text is the one the reading was made from; None otherwise (a changed text is treated as no reading)."""
    if span is None or not text_matches(reading, full_text):
        return None
    s, e = int(span[0]), int(span[1])
    return full_text[s:e]


def checks_for(session: Session, order_id: uuid.UUID) -> list[str]:
    stmt, _ = _check_select(OrderSection.order_id == order_id)
    row = session.execute(stmt).first()
    if row is None:
        return []
    return [n for n in CHECKS if row._mapping[n]]


__all__ = [
    "CHECKS",
    "CHECK_NAMES",
    "FAILURE_KIND",
    "JOB",
    "Candidate",
    "CheckInputError",
    "NoReading",
    "backfill",
    "brief",
    "candidates",
    "check_columns",
    "check_rows",
    "checks_for",
    "checks_pass",
    "current_for",
    "read_batch",
    "resolve_order",
    "run_job",
    "resolve_stale_failures",
    "sections_out",
    "src_text",
    "status",
    "text_matches",
]
