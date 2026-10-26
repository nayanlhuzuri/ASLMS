"""The SourceTrace connector interface, the fake and the pure rules of the ingestion service (design
`sourcetrace-connector`, "Tests", unit): the metadata keys, the sending guard, the back-off, the connector states,
who may import the connector, the fake's script, and the API key kept out of reprs and logs."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    Order,
    OrderKind,
    ScanStatus,
    SourcetraceStatus,
    Visibility,
)
from aslms.domain.reference import DocType
from aslms.integration.sourcetrace import (
    IngestItem,
    SourceTraceRejected,
    SourceTraceUnavailable,
    connector_state,
    get_connector,
)
from aslms.integration.sourcetrace.fake import FakeSourceTrace, fake_reference
from aslms.services import sourcetrace_ingest as st

ASLMS = Path(__file__).resolve().parents[2] / "aslms"
DUMMY_KEY = "st-dummy-key-0123456789abcdef"

BASE_KEYS = {
    "external_id",
    "source_kind",
    "doc_type",
    "doc_type_label",
    "document_date",
    "cnr",
    "case_number",
    "court",
    "filename",
    "mime",
    "size_bytes",
    "sha256",
}
ORDER_KEYS = {"order_no", "order_kind", "order_judge_name"}


def _court() -> Court:
    return Court(id=uuid.uuid4(), est_code="GAHC01", name="Principal Seat at Guwahati")


def _case(cnr: str | None = "ASHC010012342025") -> Case:
    return Case(id=uuid.uuid4(), cnr=cnr, case_no_text="WP(C)/1234/2025", ref_no="ASLMS/GHC/CASE/2026/000001")


def _order_doc(case: Case) -> tuple[Document, Order]:
    doc = Document(
        id=uuid.uuid4(),
        sha256="a" * 64,
        storage_key="aa/" + "a" * 64 + ".pdf",
        mime="application/pdf",
        size_bytes=1234,
        kind=DocKind.ORDER,
        doc_type=DocType.ORDER,
        doc_group=DocGroup.COURT_RECORD,
        case_id=case.id,
        doc_date=date(2025, 1, 10),
        description="Order 3 of 2025-01-10 in WP(C)/1234/2025",
        visibility=Visibility.CASE_SCOPE,
        virus_scan_status=ScanStatus.SKIPPED,
        sourcetrace_status=SourcetraceStatus.PENDING,
    )
    order = Order(
        id=uuid.uuid4(),
        case_id=case.id,
        order_no="3",
        order_date=date(2025, 1, 10),
        kind=OrderKind.FINAL,
        order_judge_name="HON'BLE MR. JUSTICE A",
        document_id=doc.id,
    )
    return doc, order


def _upload(case: Case, **over) -> Document:
    values = {
        "id": uuid.uuid4(),
        "ref_no": "ASLMS/EDU/DOC/2026/000007",
        "sha256": "b" * 64,
        "storage_key": "bb/" + "b" * 64 + ".pdf",
        "mime": "application/pdf",
        "size_bytes": 999,
        "original_filename": "draft-with-internal-remarks.pdf",
        "kind": DocKind.UPLOAD,
        "doc_type": DocType.PETITION,
        "doc_group": DocGroup.COURT_FILING,
        "case_id": case.id,
        "doc_date": date(2025, 1, 3),
        "description": "Department's own remark: weak case, settle",
        "visibility": Visibility.CASE_SCOPE,
        "office_id": uuid.uuid4(),
        "virus_scan_status": ScanStatus.CLEAN,
        "sourcetrace_status": SourcetraceStatus.PENDING,
        "actor_name": "Edu Off1",
        "actor_office_code": "EDU",
    }
    values.update(over)
    return Document(**values)


def test_metadata_has_exactly_the_allowed_keys():
    case, court = _case(), _court()
    doc, order = _order_doc(case)
    meta = st.build_metadata(doc, case, court, order, doc_type_label="Order")
    assert set(meta) == BASE_KEYS | ORDER_KEYS
    assert meta["source_kind"] == "court_order" and meta["external_id"] == str(doc.id)
    assert meta["document_date"] == "2025-01-10" and meta["order_kind"] == "final"
    assert meta["court"] == {"est_code": "GAHC01", "name": "Principal Seat at Guwahati"}
    assert meta["filename"] == "ASHC010012342025_3_2025-01-10.pdf"
    assert meta["case_number"] == "WP(C)/1234/2025" and meta["cnr"] == "ASHC010012342025"

    up = _upload(case)
    meta = st.build_metadata(up, case, court, None, doc_type_label="Petition")
    assert set(meta) == BASE_KEYS
    assert meta["source_kind"] == "court_filing" and meta["doc_type"] == "petition"
    assert meta["filename"] == "ASLMS-EDU-DOC-2026-000007.pdf"
    flat = repr(meta)
    for secret in (
        "draft-with-internal-remarks",
        "weak case",
        "Edu Off1",
        "case_scope",
        str(up.office_id),
    ):
        assert secret not in flat, secret


def test_assert_sendable_refuses_each_forbidden_case():
    case = _case()
    doc, order = _order_doc(case)
    st.assert_sendable(doc, case, order)
    st.assert_sendable(_upload(case), case, None)
    st.assert_sendable(_upload(case, visibility=Visibility.COUNSEL_SHARED), case, None)
    refused = {
        "internal upload": (_upload(case, doc_group=DocGroup.INTERNAL), case, None),
        "attachment": (_upload(case, kind=DocKind.ATTACHMENT, doc_group=DocGroup.INTERNAL), case, None),
        "admin": (
            _upload(
                case,
                kind=DocKind.ADMIN,
                doc_group=DocGroup.INTERNAL,
                case_id=None,
                visibility=Visibility.PRIVATE_TO_OFFICE,
            ),
            None,
            None,
        ),
        "cause list": (
            Document(
                id=uuid.uuid4(),
                kind=DocKind.CAUSELIST,
                doc_group=DocGroup.COURT_RECORD,
                doc_type=DocType.CAUSELIST,
                virus_scan_status=ScanStatus.SKIPPED,
                visibility=Visibility.CASE_SCOPE,
            ),
            None,
            None,
        ),
        "private filing": (_upload(case, visibility=Visibility.PRIVATE_TO_OFFICE), case, None),
        "archived": (_upload(case, archived_at=datetime.now(UTC), archive_reason="wrong case"), case, None),
        "order without an order row": (doc, case, None),
        "unscanned upload": (_upload(case, virus_scan_status=ScanStatus.PENDING), case, None),
    }
    prov = _case(cnr=None)
    refused["provisional case"] = (_upload(prov, case_id=prov.id), prov, None)
    for name, (d, c, o) in refused.items():
        with pytest.raises(st.NotSendable):
            st.assert_sendable(d, c, o)
            pytest.fail(f"sendable: {name}")


def test_backoff_schedule():
    assert [st.backoff(n) for n in (1, 2, 3, 4)] == [timedelta(minutes=m) for m in (10, 20, 40, 80)]


def test_get_connector_states():
    off = Settings(_env_file=None, sourcetrace_enabled=False)
    on = Settings(_env_file=None, sourcetrace_enabled=True, sourcetrace_api_key=DUMMY_KEY)
    assert connector_state(off) == "disabled" and get_connector(off) is None
    assert connector_state(on) == "not_implemented" and get_connector(on) is None
    for s in (off, on):
        assert not isinstance(get_connector(s), FakeSourceTrace)


IMPORT_RE = re.compile(
    r"^\s*(from\s+aslms\.integration\.sourcetrace\b|import\s+aslms\.integration\.sourcetrace\b)", re.M
)
ALLOWED = {
    ("services", "sourcetrace_ingest.py"),
    ("jobs", "celery_app.py"),
    ("cli", "sourcetrace.py"),
    # design assistant: the Case Assistant service, its preview and its CLI
    ("services", "assistant.py"),
    ("services", "assistant_preview.py"),
    ("cli", "assistant.py"),
}


def test_only_listed_modules_import_the_connector():
    offenders = []
    for path in ASLMS.rglob("*.py"):
        rel = path.relative_to(ASLMS)
        if rel.parts[:2] == ("integration", "sourcetrace"):
            continue
        if tuple(rel.parts[-2:]) in ALLOWED:
            continue
        if IMPORT_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(str(rel))
    assert offenders == []


def _item(content: bytes = b"%PDF-1.4 order") -> IngestItem:
    return IngestItem(
        document_id=uuid.uuid4(),
        content=content,
        mime="application/pdf",
        filename="x.pdf",
        metadata={"external_id": "x"},
    )


def test_fake_records_and_follows_its_script():
    fake = FakeSourceTrace(timeout_sleep=0.2).script("unavailable", "rejected", "bad_reference", "timeout")

    async def go():
        out = []
        for _ in range(3):
            try:
                out.append((await fake.ingest(_item())).reference)
            except (SourceTraceUnavailable, SourceTraceRejected) as exc:
                out.append(type(exc).__name__)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(fake.ingest(_item()), timeout=0.01)
        out.append((await fake.ingest(_item(b"abc"))).reference)
        return out

    out = asyncio.run(go())
    assert out == ["SourceTraceUnavailable", "SourceTraceRejected", "", fake_reference(b"abc")]
    assert fake_reference(b"abc").startswith("fake-") and len(fake_reference(b"abc")) == 5 + 24
    assert len(fake.received) == 5
    with pytest.raises(ValueError):
        fake.script("explode")


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def test_connector_repr_and_logs_hide_the_api_key():
    settings = Settings(_env_file=None, sourcetrace_enabled=True, sourcetrace_api_key=DUMMY_KEY)
    # a handler on the package logger itself: the app's logging set-up may stop propagation to the root
    logger = logging.getLogger("aslms.integration.sourcetrace")
    handler = _Collect()
    logger.addHandler(handler)
    old_level, old_disabled = logger.level, logger.disabled
    logger.setLevel(logging.DEBUG)
    logger.disabled = False  # alembic's fileConfig (run by the database tests) disables existing loggers
    try:
        connector_state(settings)
        get_connector(settings)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.disabled = old_disabled
    assert handler.lines  # the not_implemented warning
    assert all(DUMMY_KEY not in line for line in handler.lines)
    assert DUMMY_KEY not in repr(settings) and DUMMY_KEY not in str(settings.sourcetrace_api_key)
    fake = FakeSourceTrace()
    item = _item(DUMMY_KEY.encode())
    assert DUMMY_KEY not in repr(fake) and DUMMY_KEY.encode() not in repr(item).encode()
    meta = st.build_metadata(_upload(_case()), _case(), _court(), None)
    assert DUMMY_KEY not in repr(meta)
