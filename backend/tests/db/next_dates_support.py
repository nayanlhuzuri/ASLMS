"""Shared helpers for the next-date tests (design `next-date-extraction`): orders with a stored document and its
extracted text written directly (the way the pipeline and the text job leave them), the reader run, claimed cases
through the ownership service, and readers of the rows, events and alerts a run produced."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, NextDate
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DocumentText,
    DownloadStatus,
    Order,
    OrderKind,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.events import Event
from aslms.domain.reference import AlertKind, DocType, EventType
from aslms.services import next_dates
from aslms.services import ownership as own
from aslms.services.workflow_common import today_ist
from tests.db.world import make_case

_n = {"orders": 0}


def days(n: int) -> date:
    return today_ist() + timedelta(days=n)


def dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def order_with_text(
    s: Session,
    case: Case,
    text: str | None,
    *,
    order_date: date | None = None,
    order_no: str | None = None,
    text_status: TextStatus = TextStatus.EXTRACTED,
) -> Order:
    """An order of `case` with a stored order PDF whose text is `text` (`text_status` none: a scan without text;
    `pending`: not extracted yet)."""
    _n["orders"] += 1
    n = _n["orders"]
    sha = hashlib.sha256(f"order-{n}-{uuid.uuid4()}".encode()).hexdigest()
    doc = Document(
        sha256=sha,
        storage_key=f"sha256/{sha[:2]}/{sha}",
        mime="application/pdf",
        size_bytes=1000,
        kind=DocKind.ORDER,
        doc_type=DocType.ORDER,
        doc_group=DocGroup.COURT_RECORD,
        case_id=case.id,
        doc_date=order_date or days(-1),
        visibility=Visibility.CASE_SCOPE,
        virus_scan_status=ScanStatus.SKIPPED,
        text_status=text_status,
        sourcetrace_status=SourcetraceStatus.PENDING,
    )
    s.add(doc)
    s.flush()
    if text_status == TextStatus.EXTRACTED:
        s.add(DocumentText(document_id=doc.id, full_text=text, page_count=1))
    order = Order(
        case_id=case.id,
        order_no=order_no or str(n),
        order_date=order_date or days(-1),
        kind=OrderKind.INTERIM,
        order_details="ORDER",
        document_id=doc.id,
        download_status=DownloadStatus.STORED,
    )
    s.add(order)
    s.flush()
    return order


def claimed(s: Session, world, *, key: str = "edu_admin", next_hearing: date | None = None, **kw) -> Case:
    """A case claimed by `key`'s department; `next_hearing`: the court's own next date (NAPIX `date_next_list`)."""
    case = make_case(s, next_hearing=next_hearing)
    actor, user = world.actor(s, key)
    own.claim(s, actor, user, case, **kw)
    return case


def read(s: Session, **kw) -> dict[str, int]:
    kw.setdefault("batch", 500)
    return next_dates.read_pending(s, **kw)


def rows(s: Session, case: Case) -> list[NextDate]:
    return list(
        s.scalars(
            sa.select(NextDate)
            .where(NextDate.case_id == case.id)
            .order_by(NextDate.created_at, NextDate.id)
            .execution_options(populate_existing=True)
        ).all()
    )


def events(s: Session, case: Case, kind: EventType = EventType.NEXT_DATE_EXTRACTED) -> list[Event]:
    return list(
        s.scalars(
            sa.select(Event).where(Event.case_id == case.id, Event.type == kind).order_by(Event.occurred_at)
        ).all()
    )


def review_alerts(s: Session, case: Case) -> list[Alert]:
    return list(
        s.scalars(
            sa.select(Alert)
            .where(Alert.case_id == case.id, Alert.kind == AlertKind.NEXT_DATE_REVIEW)
            .order_by(Alert.created_at)
            .execution_options(populate_existing=True)
        ).all()
    )


def refreshed(s: Session, obj):
    s.refresh(obj)
    return obj
