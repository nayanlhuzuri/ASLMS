"""Shared helpers for the document tests: an API client over the world with a temporary store and a
`FakeScanner`, sign-in, an upload call, and stored order PDFs inserted the way the pipeline does."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DownloadStatus,
    Order,
    OrderKind,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.events import AuditLog
from aslms.domain.reference import DocType
from aslms.services.scanner import FakeScanner
from aslms.services.storage import LocalStore
from tests.db.world import PW, USERS

JWT = "test-secret-of-at-least-thirty-two-characters"


def make_api(world, tmp_path: Path, **overrides) -> TestClient:
    """The app over the world's session factory; `client.store` is the temporary `LocalStore`,
    `client.scanner` the `FakeScanner` the upload endpoint uses."""
    store_dir = tmp_path / "store"
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret=JWT,
        aslms_access_token_minutes=5,
        storage_dir=str(store_dir),
        redis_url=None,
        **overrides,
    )
    app = create_app(settings, world.Session)
    app.state.scanner = FakeScanner()
    client = TestClient(app)
    client.__enter__()
    client.store = LocalStore(store_dir)
    client.scanner = app.state.scanner
    client.settings = settings
    return client


def login(api: TestClient, key: str) -> dict:
    r = api.post("/auth/login", json={"email": USERS[key][0], "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(
    api: TestClient,
    headers: dict,
    case_ref,
    data: bytes,
    name: str = "petition.pdf",
    *,
    doc_type: str = "petition",
    doc_date: str = "2025-01-03",
    description: str = "Writ petition as filed",
    visibility: str = "case_scope",
    doc_group: str | None = None,
    **extra,
):
    fields = {
        "doc_type": doc_type,
        "doc_date": doc_date,
        "description": description,
        "visibility": visibility,
    }
    if doc_group is not None:
        fields["doc_group"] = doc_group
    return api.post(
        f"/cases/{case_ref}/documents", headers=headers, files={"file": (name, data)}, data=fields, **extra
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit_rows(s: Session, action: str, **where) -> list[AuditLog]:
    stmt = sa.select(AuditLog).where(AuditLog.action == action)
    for k, v in where.items():
        stmt = stmt.where(getattr(AuditLog, k) == v)
    return list(s.scalars(stmt.order_by(AuditLog.created_at, AuditLog.id)).all())


def stored_order(
    s: Session,
    store: LocalStore,
    case: Case,
    pdf: bytes,
    *,
    order_no: str = "1",
    order_date: date = date(2025, 1, 10),
    kind: OrderKind = OrderKind.INTERIM,
    document: Document | None = None,
) -> tuple[Order, Document]:
    """An `orders` row with its PDF in the store, as `fetch_order_pdf` writes it (one document may be shared
    by passing `document`)."""
    if document is None:
        stored = store.put(pdf, "application/pdf")
        document = s.scalar(
            sa.select(Document).where(Document.sha256 == stored.sha256, Document.kind == DocKind.ORDER)
        )
        if document is None:
            document = Document(
                sha256=stored.sha256,
                storage_key=stored.key,
                mime="application/pdf",
                size_bytes=stored.size,
                kind=DocKind.ORDER,
                doc_type=DocType.ORDER,
                doc_group=DocGroup.COURT_RECORD,
                case_id=case.id,
                doc_date=order_date,
                description=f"Order {order_no} of {order_date} in {case.case_no_text}",
                visibility=Visibility.CASE_SCOPE,
                virus_scan_status=ScanStatus.SKIPPED,
                text_status=TextStatus.PENDING,
                sourcetrace_status=SourcetraceStatus.PENDING,
            )
            s.add(document)
            s.flush()
    order = Order(
        case_id=case.id,
        order_no=order_no,
        order_date=order_date,
        kind=kind,
        order_details="ORDER",
        document_id=document.id,
        download_status=DownloadStatus.STORED,
    )
    s.add(order)
    s.flush()
    return order, document


def pending_order(
    s: Session, case: Case, *, order_no: str = "9", order_date: date = date(2025, 1, 12)
) -> Order:
    order = Order(
        case_id=case.id,
        order_no=order_no,
        order_date=order_date,
        kind=OrderKind.INTERIM,
        download_status=DownloadStatus.NOT_AVAILABLE,
        last_error="not available (628)",
    )
    s.add(order)
    s.flush()
    return order
