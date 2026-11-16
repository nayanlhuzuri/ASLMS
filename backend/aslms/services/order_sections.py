"""Order sections (design `order-sections`): the reader's job, the replacement of readings, the live checks against
`orders` and `cases`, the data-health block, the check list and the Orders tab's reading.

- The job (decisions 3, 4, 18, 22, 23): `candidates` takes, in order, orders with extracted text and no current
  reading, current readings whose document changed, whose text was extracted again, or whose parser version is
  older, and current readings whose text is gone; `read_batch` parses each (document, text) once
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
- Reads (decisions 19 to 21): `status` (the data-health block), `check_rows` (Problems and Fixes → Data Gaps, no body
  or title text), `brief` (the Orders list) and `sections_out` (the Orders tab's "What the Order Says"), the last two
  only for a caller who may open the case and the order's PDF."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    union,
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
UNIQUE_CURRENT = "ix_order_sections_current"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200


class NoReading(LookupError):
    """The order has no current reading (HTTP 404 `no_reading`, with the document's `text_status`)."""

    def __init__(self, text_status: str | None) -> None:
        super().__init__("this order has not been read yet")
        self.text_status = text_status


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


def _set_current(set_no: int, limit: int, order_id: uuid.UUID | None, retry: bool = False):
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
            stmt = stmt.where(~changed, s.created_at < DocumentText.updated_at)
        else:
            stmt = stmt.where(s.parser_version < R.PARSER_VERSION)
    if order_id is not None:
        stmt = stmt.where(s.order_id == order_id)
    return stmt.order_by(s.created_at, s.id).limit(limit)


def candidates(session: Session, *, batch: int, order_id: uuid.UUID | None = None) -> list[Candidate]:
    """Decision 18: the five sets in their order, oldest first, at most `batch` orders, read without locks. Orders
    with an open `order_parse` failure come last, after all five sets, so an order that keeps failing is retried only
    when there is room and never holds a batch slot that a readable order could use."""
    batch = max(1, int(batch))
    out: dict[uuid.UUID, Candidate] = {}
    for retry, set_no in [(False, n) for n in (1, 2, 3, 4, 5)] + [(True, n) for n in (1, 2, 3, 4, 5)]:
        left = batch - len(out)
        if left <= 0:
            break
        stmt = (
            _set_new(left, order_id, retry)
            if set_no == 1
            else _set_current(set_no, left + len(out), order_id, retry)
        )
        for oid, sn, cur, doc_id, sha, odate, kind in session.execute(stmt).all():
            if oid in out or len(out) >= batch:
                continue
            out[oid] = Candidate(oid, int(sn), cur, doc_id, sha, odate, _value(kind) if kind else None, retry)
    return list(out.values())


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


def read_batch(
    session: Session, *, batch: int | None = None, order_id: uuid.UUID | None = None, dry_run: bool = False
) -> dict[str, int]:
    """Decisions 3, 4 and 23: the candidates grouped by (document, order date, NAPIX kind) and each text parsed once;
    per order, one savepoint. With `dry_run` it parses and counts but writes nothing."""
    batch = batch or get_settings().order_sections_batch
    counters = dict.fromkeys(COUNTERS, 0)
    cands = candidates(session, batch=batch, order_id=order_id)
    counters["claimed"] = len(cands)
    counters["retried"] = sum(1 for c in cands if c.retry)
    if not cands:
        return counters
    doc_ids = sorted({c.document_id for c in cands if c.set_no != 5 and c.document_id is not None})
    texts: dict[uuid.UUID, str] = {}
    if doc_ids:
        for doc_id, full in session.execute(
            select(DocumentText.document_id, DocumentText.full_text).where(
                DocumentText.document_id.in_(doc_ids)
            )
        ).all():
            texts[doc_id] = full or ""
    parsed_cache: dict[tuple, tuple[parse_mod.Parsed | None, str | None, str | None]] = {}
    for cand in cands:
        parsed: parse_mod.Parsed | None = None
        text_sha: str | None = None
        error: str | None = None
        if cand.set_no != 5:
            key = (cand.document_id, cand.order_date, cand.napix_kind)
            if key not in parsed_cache:
                full = texts.get(cand.document_id)
                if full is None:  # the text went between the two reads: the next run takes it as set 5
                    parsed_cache[key] = (None, None, "skip")
                else:
                    try:
                        p = parse_mod.parse(full, order_date=cand.order_date, napix_kind=cand.napix_kind)
                        parsed_cache[key] = (p, hashlib.sha256(full.encode("utf-8")).hexdigest(), None)
                    except Exception as exc:  # noqa: BLE001 — a reader bug on one text never stops the run
                        log.exception("order reader: document %s failed", cand.document_id)
                        parsed_cache[key] = (None, None, f"{exc.__class__.__name__}: {exc}")
            parsed, text_sha, error = parsed_cache[key]
            if error == "skip":
                counters["skipped"] += 1
                continue
            if error is not None:
                counters["failed"] += 1
                if not dry_run:
                    source_failures.record(session, FAILURE_KIND, str(cand.order_id), error)
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
            log.exception("order sections: order %s failed", cand.order_id)
            source_failures.record(
                session, FAILURE_KIND, str(cand.order_id), f"{exc.__class__.__name__}: {exc}"
            )
            continue
        except Exception as exc:  # noqa: BLE001 — one bad order must not stop the run; it is recorded
            counters["failed"] += 1
            log.exception("order sections: order %s failed", cand.order_id)
            source_failures.record(
                session, FAILURE_KIND, str(cand.order_id), f"{exc.__class__.__name__}: {exc}"
            )
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


def run_job(session: Session, *, cfg: Settings | None = None, now: datetime | None = None) -> dict[str, int]:
    """The 5-minute job: one `job_runs` row (`partial` when an order failed), as `next_dates.run_job`."""
    cfg = cfg or get_settings()
    now = now or _now()
    run = JobRun(job=JOB, run_date=clock.today_ist(now), started_at=now)
    session.add(run)
    session.flush()
    try:
        counters = read_batch(session, batch=cfg.order_sections_batch)
    except Exception as exc:
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = _now()
        session.flush()
        raise
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
    """`aslms orders parse --backfill` (decision 23): batches until no candidate is left (or `limit` orders), one
    commit per batch, a pause between batches; stopped and started again, it carries on where it was. With `dry_run`
    it parses and counts one pass of `limit` orders (default one batch) and writes nothing."""
    total = dict.fromkeys(COUNTERS, 0)
    done = 0
    seen: set[uuid.UUID] = set()
    while True:
        size = batch if limit is None else min(batch, limit - done)
        if size <= 0:
            break
        with session_factory() as s:
            if dry_run:
                counters = _dry_batch(s, size, seen)
                s.rollback()
            else:
                counters = read_batch(s, batch=size)
                s.commit()
        for k, v in counters.items():
            total[k] = total.get(k, 0) + v
        done += counters["claimed"]
        if echo is not None:
            echo(
                f"batch: {counters['claimed']} claimed, {counters['parsed']} read, {counters['skipped']} skipped, "
                f"{counters['failed']} failed (total {done})"
            )
        # Orders with an open failure are claimed after every other candidate, so a batch made only of them, none read,
        # means nothing readable is left: stop, or the same failing orders would be claimed again forever. A batch of
        # first failures goes on (the next one passes them by). A skip is a race another reader won or a text that
        # went, and the next batch moves past it.
        progress = counters["parsed"] + counters["text_gone"] + counters["skipped"]
        only_retries = counters["retried"] == counters["claimed"]
        if counters["claimed"] == 0 or (not dry_run and progress == 0 and only_retries):
            break
        if dry_run and limit is None:
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


def status(session: Session) -> dict[str, Any]:
    """Decision 21: the data-health block, counts only (the caller sets the report statement timeout)."""
    s = OrderSection
    current = s.replaced_at.is_(None)
    orders_with_text = int(
        session.scalar(
            select(func.count())
            .select_from(Order)
            .join(Document, Document.id == Order.document_id)
            .join(DocumentText, DocumentText.document_id == Document.id)
            .where(_readable())
        )
        or 0
    )
    agg = session.execute(
        select(
            func.count().filter(s.parser_version == R.PARSER_VERSION),
            func.count().filter(s.procedural),
            func.count().filter(s.registrar),
            func.count().filter(s.outcome.is_not(None)),
            func.count().filter(func.jsonb_array_length(s.facts["directions"]) > 0),
            func.count(func.distinct(s.body_sha256)),
        ).where(current)
    ).one()
    by_layout = {lay.value: 0 for lay in OrderLayout}
    for lay, n in session.execute(select(s.layout, func.count()).where(current).group_by(s.layout)).all():
        by_layout[_value(lay)] = int(n)
    by_form = {k.value: 0 for k in OrderKind}
    for form, n in session.execute(select(s.form, func.count()).where(current).group_by(s.form)).all():
        by_form[_value(form)] = int(n)
    flags = dict.fromkeys(FLAGS, 0)
    flag = func.unnest(s.flags).label("flag")
    sub = select(flag).where(current).subquery()
    for f, n in session.execute(select(sub.c.flag, func.count()).group_by(sub.c.flag)).all():
        flags[_value(f)] = int(n)
    stmt, cols = _check_select()
    sub = stmt.subquery()
    checks_row = session.execute(select(*[func.count().filter(sub.c[n]) for n in CHECKS])).one()
    checks = {n: int(v or 0) for n, v in zip(CHECKS, checks_row, strict=True)}
    # the orders of sets 1 to 4, each once (a reading may be in sets 2 to 4 at the same time)
    sets = [
        (_set_new(1, None) if n == 1 else _set_current(n, 1, None)).order_by(None).limit(None)
        for n in (1, 2, 3, 4)
    ]
    ids = union(*[q.with_only_columns(q.selected_columns[0].label("order_id")) for q in sets]).subquery()
    waiting = int(session.scalar(select(func.count()).select_from(ids)) or 0)
    failed = int(
        session.scalar(
            select(func.count())
            .select_from(SourceFailure)
            .where(SourceFailure.kind == FAILURE_KIND, SourceFailure.resolved_at.is_(None))
        )
        or 0
    )
    last = session.scalar(select(JobRun).where(JobRun.job == JOB).order_by(JobRun.started_at.desc()).limit(1))
    return {
        "parser_version": R.PARSER_VERSION,
        "orders_with_text": orders_with_text,
        "read": int(agg[0] or 0),
        "waiting": waiting,
        "failed": failed,
        "by_layout": by_layout,
        "by_form": by_form,
        "procedural": int(agg[1] or 0),
        "registrar": int(agg[2] or 0),
        "with_outcome": int(agg[3] or 0),
        "with_directions": int(agg[4] or 0),
        "distinct_bodies": int(agg[5] or 0),
        "flags": flags,
        "checks": checks,
        "last_run": (
            {
                "started_at": last.started_at,
                "finished_at": last.finished_at,
                "status": _value(last.status),
                "counters": dict(last.counters or {}),
            }
            if last is not None
            else None
        ),
    }


def check_rows(
    session: Session, *, check: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0
) -> tuple[int, dict[str, int], list[dict[str, Any]]]:
    """Decision 21: current readings with a live mismatch or an intrinsic flag (or the one `check` asked for, which
    may be `common_order`), newest order first. Identifiers and printed values only: no body or title text."""
    if check is not None and check not in CHECK_NAMES:
        raise CheckInputError(f"check is one of {', '.join(CHECK_NAMES)}")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    s, o, c = OrderSection, Order, Case
    cols = check_columns(s, o, c)
    if check is None:
        cond = or_(_mismatch(cols), func.cardinality(s.flags) > 0)
    elif check in CHECKS:
        cond = cols[check]
    else:
        cond = _flag_condition(check)
    base = (
        select(s.id)
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.replaced_at.is_(None), cond)
    )
    total = int(session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    counts_sel = (
        select(
            *[func.count().filter(cols[n]) for n in CHECKS],
            *[func.count().filter(_flag_condition(f)) for f in FLAGS],
        )
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.replaced_at.is_(None))
    )
    counts = {n: int(v or 0) for n, v in zip(CHECK_NAMES, session.execute(counts_sel).one(), strict=True)}
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
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .where(s.replaced_at.is_(None), cond)
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


def brief(session: Session, user: User | Member, order_ids) -> dict[uuid.UUID, dict[str, Any] | None]:
    """Decision 20 for the Orders list, in one query: the current reading's tags of each order the caller may open
    the PDF of (one document-visibility condition for the page); None otherwise."""
    ids = [i for i in dict.fromkeys(order_ids) if i is not None]
    out: dict[uuid.UUID, dict[str, Any] | None] = dict.fromkeys(ids)
    if not ids or not access.has(session, user, Permission.DOCUMENTS_VIEW):
        return out
    # aliases: the document rule correlates its own `orders` and `cases` subqueries on `documents` only
    s, o, c = OrderSection, aliased(Order), aliased(Case)
    cols = check_columns(s, o, c)
    compliance = s.facts["directions"].op("@>")(cast([{"kind": "compliance"}], JSONB))
    rows = session.execute(
        select(
            s.order_id,
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
        .select_from(s)
        .join(o, o.id == s.order_id)
        .join(c, c.id == o.case_id)
        .join(Document, Document.id == o.document_id)
        .where(
            s.replaced_at.is_(None),
            s.order_id.in_(ids),
            visibility.document_visible_condition(session, user),
        )
    ).all()
    for oid, layout, form, proc, reg, outcome, chars, parts, comp, common, printed in rows:
        parts_list = _parts_names(parts)
        out[oid] = {
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
        raise NoReading(_value(doc.text_status) if doc is not None else None)
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
    "current_for",
    "read_batch",
    "resolve_order",
    "run_job",
    "sections_out",
    "status",
]
