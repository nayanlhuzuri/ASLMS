"""Ingestion into SourceTrace against `FakeSourceTrace` (design `sourcetrace-connector`, "Tests", database): what
is sent and with which metadata, what is never sent, the waits (private, archived, provisional), the retries and
failures, the locks between runs and against document changes, the run limits and order, the disabled job, the
shared order PDF, the CHECKs, the append-only record and migration 0011."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, DocKind, Document, OrderKind, SourcetraceStatus, Visibility
from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.reference import DocType
from aslms.domain.workflow import SourcetraceIngestion
from aslms.integration.sourcetrace.fake import FakeSourceTrace, fake_reference
from aslms.services import sourcetrace_ingest as st
from aslms.services.audit import Actor
from aslms.services.causelists import store_pdf
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import st_support as h
from tests.db import workflow_support as w
from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_id(world):
    """An EDU case claimed by the EDU admin and allotted to off1."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        s.commit()
        return case.id


def _order(world, api, case_id, text="An order", **kw):
    with world.Session() as s:
        case = s.get(Case, case_id)
        order, doc = ds.stored_order(s, api.store, case, sf.text_pdf([text]), **kw)
        s.commit()
        return order, doc


def _filing(world, api, case_id, office="EDU", **kw):
    with world.Session() as s:
        d = h.upload_row(s, api.store, s.get(Case, case_id), world.office(s, office), **kw)
        s.commit()
        return d


def _failures(world, kind=st.FAILURE_KIND):
    with world.Session() as s:
        return list(s.scalars(sa.select(SourceFailure).where(SourceFailure.kind == kind)).all())


# ------------------------------------------------------------------------------------------------ what is sent


def test_order_pdf_ingested_with_reference_attempt_and_metadata(world, api, case_id):
    order, doc = _order(world, api, case_id, kind=OrderKind.FINAL, order_no="4")
    fake = FakeSourceTrace()
    counters = h.ingest(world, api.store, fake)
    assert counters["claimed"] == 1 and counters["ingested"] == 1 and counters["stopped"] == "empty"
    row = h.doc(world, doc.id)
    content = api.store.get(row.storage_key)
    assert row.sourcetrace_status == SourcetraceStatus.INGESTED
    assert row.sourcetrace_ref == fake_reference(content) and row.sourcetrace_ingested_at is not None
    assert row.sourcetrace_attempts == 1 and row.sourcetrace_next_at is None
    rows = h.attempts(world, doc.id)
    assert len(rows) == 1
    a = rows[0]
    assert a.ok and a.attempt == 1 and a.connector == "fake" and a.reference == row.sourcetrace_ref
    assert a.error is None and a.error_family is None and a.response["reference"] == row.sourcetrace_ref
    item = fake.received[0]
    assert a.metadata_sent == item.metadata and item.content == content
    with world.Session() as s:
        case = s.get(Case, case_id)
    assert item.metadata["cnr"] == case.cnr and item.metadata["source_kind"] == "court_order"
    assert item.metadata["order_no"] == "4" and item.metadata["order_kind"] == "final"
    assert item.metadata["doc_type_label"] and item.filename == f"{case.cnr}_4_2025-01-10.pdf"


def test_court_filing_case_scope_and_counsel_shared_ingested(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    a = ds.upload(api, hd, case_id, sf.text_pdf(["filing one"]), visibility="case_scope").json()
    b = ds.upload(api, hd, case_id, sf.text_pdf(["filing two"]), visibility="counsel_shared").json()
    assert a["sourcetrace_status"] == b["sourcetrace_status"] == "pending"
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["ingested"] == 2
    assert {str(i.document_id) for i in fake.received} == {a["id"], b["id"]}
    for item in fake.received:
        assert item.metadata["source_kind"] == "court_filing"
        assert "Writ petition as filed" not in repr(item.metadata) and "petition.pdf" != item.filename
    assert h.status_of(world, uuid.UUID(a["id"])) == "ingested"


def test_internal_uploads_attachments_admin_and_causelists_never_sent(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    internal = ds.upload(api, hd, case_id, sf.text_pdf(["internal memo"]), doc_type="correspondence").json()
    assert internal["doc_group"] == "internal" and internal["sourcetrace_status"] == "not_applicable"
    note = api.post(
        f"/cases/{case_id}/notes",
        headers=hd,
        data={"kind": "general", "body": "internal note text", "visibility": "case_scope"},
        files=[("files", ("a.pdf", sf.text_pdf(["attachment"])))],
    )
    assert note.status_code == 201, note.text
    with world.Session() as s:
        cl, _ = store_pdf(
            s, api.store, sf.text_pdf(["A cause list"]), doc_date=date(2025, 1, 6), description="list"
        )
        h.upload_row(
            s,
            api.store,
            s.get(Case, case_id),
            world.office(s, "EDU"),
            text="admin doc",
            kind=DocKind.ADMIN,
            doc_type=DocType.GOVERNMENT_ORDER,
            group=DocGroup.INTERNAL,
            visibility=Visibility.PRIVATE_TO_OFFICE,
        )
        s.commit()
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(Document)
                .where(Document.sourcetrace_status != "not_applicable")
            )
            == 0
        )
    fake = FakeSourceTrace()
    counters = h.ingest(world, api.store, fake)
    assert counters["claimed"] == 0 and fake.received == []


def test_linked_court_filing_still_sent_and_note_never(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    filing = ds.upload(api, hd, case_id, sf.text_pdf(["the filing"])).json()
    r = api.post(
        f"/cases/{case_id}/notes",
        headers=hd,
        data={
            "kind": "general",
            "body": "CONFIDENTIAL note: settle quietly",
            "visibility": "case_scope",
            "document_refs": [filing["ref_no"]],
        },
        files=[("files", ("own.pdf", sf.text_pdf(["CONFIDENTIAL attachment"])))],
    )
    assert r.status_code == 201, r.text
    assert sorted(a["linked"] for a in r.json()["attachments"]) == [False, True]
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    assert [str(i.document_id) for i in fake.received] == [filing["id"]]
    item = fake.received[0]
    assert b"CONFIDENTIAL" not in item.content and "CONFIDENTIAL" not in repr(item.metadata)


# ------------------------------------------------------------------------------------------------ waits


def test_private_filing_waits_until_widened(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    d = ds.upload(api, hd, case_id, sf.text_pdf(["private filing"]), visibility="private_to_office").json()
    assert d["sourcetrace_status"] == "not_applicable"
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["claimed"] == 0
    with world.Session() as s:  # a stale attempt count from an earlier life must not survive the widening
        s.execute(sa.update(Document).where(Document.id == uuid.UUID(d["id"])).values(sourcetrace_attempts=3))
        s.commit()
    r = api.patch(f"/documents/{d['id']}", headers=hd, json={"visibility": "case_scope"})
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "pending"
    row = h.doc(world, uuid.UUID(d["id"]))
    assert row.sourcetrace_attempts == 0 and row.sourcetrace_next_at is None
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    # case_scope <-> counsel_shared touches nothing
    r = api.patch(f"/documents/{d['id']}", headers=hd, json={"visibility": "counsel_shared"})
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "ingested"


def test_archive_stops_sending(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    d = ds.upload(api, hd, case_id, sf.text_pdf(["to be archived"])).json()
    r = api.post(f"/documents/{d['id']}/archive", headers=hd, json={"reason": "uploaded to the wrong case"})
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "not_applicable"
    with world.Session() as s:
        audit = ds.audit_rows(s, "document.archived", entity_id=uuid.UUID(d["id"]))[-1]
    assert (
        audit.before == {"sourcetrace_status": "pending"}
        and audit.after["sourcetrace_status"] == "not_applicable"
    )
    # widening an archived private filing does not queue it again
    p = ds.upload(api, hd, case_id, sf.text_pdf(["private, archived"]), visibility="private_to_office").json()
    assert (
        api.post(f"/documents/{p['id']}/archive", headers=hd, json={"reason": "not needed"}).status_code
        == 200
    )
    r = api.patch(f"/documents/{p['id']}", headers=hd, json={"visibility": "case_scope"})
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "not_applicable"
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["claimed"] == 0 and fake.received == []


def test_archived_ingested_keeps_reference(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    d = ds.upload(api, hd, case_id, sf.text_pdf(["ingested then archived"])).json()
    h.ingest(world, api.store, FakeSourceTrace())
    ref = h.doc(world, uuid.UUID(d["id"])).sourcetrace_ref
    r = api.post(f"/documents/{d['id']}/archive", headers=hd, json={"reason": "superseded by a fresh copy"})
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "ingested"
    row = h.doc(world, uuid.UUID(d["id"]))
    assert row.sourcetrace_ref == ref and row.sourcetrace_ingested_at is not None
    with world.Session() as s:
        assert st.check(s) == {"documents_breaking_rule": 0, "ingestions_of_unsendable": 0}


def test_provisional_case_filing_waits_for_cnr(world, api):
    with world.Session() as s:
        case = make_case(s)
        case.cnr, case.is_provisional = None, True
        s.flush()
        d = h.upload_row(s, api.store, case, world.office(s, "EDU"))
        s.commit()
        cid = case.id
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["claimed"] == 0
    with world.Session() as s:
        stt = st.status(s, Settings(_env_file=None))
    assert stt["waiting_cnr"] == 1 and stt["due_now"] == 0 and stt["counts"]["pending"] == 1
    with world.Session() as s:
        case = s.get(Case, cid)
        case.cnr, case.is_provisional = "ASHC010099992025", False
        s.commit()
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    assert fake.received[0].metadata["cnr"] == "ASHC010099992025" and fake.received[0].document_id == d.id


# ------------------------------------------------------------------------------------------------ retries


def test_unavailable_backs_off_then_fails_after_max_attempts(world, api, case_id):
    _o1, d1 = _order(world, api, case_id, text="order one", order_no="1", order_date=date(2025, 2, 1))
    _o2, d2 = _order(world, api, case_id, text="order two", order_no="2", order_date=date(2025, 1, 1))
    fake = FakeSourceTrace().script(*["unavailable"] * 5)
    before = datetime.now(UTC)
    counters = h.ingest(world, api.store, fake)
    # newest doc_date first; the run stops after the first unavailable, so d2 is not tried
    assert counters["claimed"] == 1 and counters["retrying"] == 1 and counters["stopped"] == "unavailable"
    assert [i.document_id for i in fake.received] == [d1.id]
    row = h.doc(world, d1.id)
    assert row.sourcetrace_status == SourcetraceStatus.PENDING and row.sourcetrace_attempts == 1
    assert before + timedelta(minutes=9) < row.sourcetrace_next_at < before + timedelta(minutes=11)
    assert h.status_of(world, d2.id) == "pending" and h.attempts(world, d2.id) == []
    with world.Session() as s:  # park d2 so that only d1 is retried below
        s.execute(
            sa.update(Document)
            .where(Document.id == d2.id)
            .values(sourcetrace_next_at=sa.func.now() + sa.text("interval '1 day'"))
        )
        s.commit()
    for n, minutes in ((2, 20), (3, 40), (4, 80)):
        h.make_due(world, d1.id)
        start = datetime.now(UTC)
        h.ingest(world, api.store, fake)
        row = h.doc(world, d1.id)
        assert row.sourcetrace_attempts == n and row.sourcetrace_status == SourcetraceStatus.PENDING
        assert (
            start + timedelta(minutes=minutes - 1)
            < row.sourcetrace_next_at
            < start + timedelta(minutes=minutes + 1)
        )
    h.make_due(world, d1.id)
    counters = h.ingest(world, api.store, fake)
    assert counters["failed"] == 1
    row = h.doc(world, d1.id)
    assert row.sourcetrace_status == SourcetraceStatus.FAILED and row.sourcetrace_attempts == 5
    assert row.sourcetrace_next_at is None
    rows = h.attempts(world, d1.id)
    assert [r.attempt for r in rows] == [1, 2, 3, 4, 5] and {r.error_family for r in rows} == {"unavailable"}
    assert all(r.response == {"status": 503} for r in rows)
    (failure,) = _failures(world)
    assert failure.ref == str(d1.id) and failure.error_family == "unavailable" and failure.resolved_at is None
    assert len(fake.received) == 5 and h.attempts(world, d2.id) == []


def test_timeout_counts_as_unavailable(world, api, case_id):
    _o, d = _order(world, api, case_id)
    _o2, d2 = _order(world, api, case_id, text="second", order_no="2", order_date=date(2025, 1, 2))
    fake = FakeSourceTrace(timeout_sleep=2.0).script("timeout")
    config = st.IngestConfig(batch=10, run_seconds=60, timeout_seconds=0.05, max_attempts=5)
    counters = h.ingest(world, api.store, fake, config)
    assert counters["claimed"] == 1 and counters["retrying"] == 1 and counters["stopped"] == "unavailable"
    first = d if h.attempts(world, d.id) else d2
    (a,) = h.attempts(world, first.id)
    assert not a.ok and a.error_family == "timeout" and "0.05" in a.error
    assert (
        h.status_of(world, first.id) == "pending" and h.doc(world, first.id).sourcetrace_next_at is not None
    )


def test_rejected_and_bad_reference_fail_at_once(world, api, case_id):
    _o, d1 = _order(world, api, case_id, text="rejected one", order_date=date(2025, 3, 1))
    _o2, d2 = _order(world, api, case_id, text="bad ref", order_no="2", order_date=date(2025, 2, 1))
    fake = FakeSourceTrace().script("rejected", "bad_reference")
    counters = h.ingest(world, api.store, fake)
    assert counters["claimed"] == 2 and counters["failed"] == 2 and counters["stopped"] == "empty"
    for d, family in ((d1, "rejected"), (d2, "protocol")):
        row = h.doc(world, d.id)
        assert row.sourcetrace_status == SourcetraceStatus.FAILED and row.sourcetrace_attempts == 1
        assert row.sourcetrace_ref is None
        (a,) = h.attempts(world, d.id)
        assert a.error_family == family
    assert {f.error_family for f in _failures(world)} == {"rejected", "protocol"}


def test_missing_file_fails_with_store_family(world, api, case_id):
    _o, d = _order(world, api, case_id)
    api.store.path(d.storage_key).unlink()
    fake = FakeSourceTrace()
    counters = h.ingest(world, api.store, fake)
    assert counters["failed"] == 1 and fake.received == []
    (a,) = h.attempts(world, d.id)
    assert a.error_family == "store" and "missing" in a.error
    assert h.status_of(world, d.id) == "failed"


def test_success_resolves_the_source_failure(world, api, case_id):
    _o, d = _order(world, api, case_id)
    fake = FakeSourceTrace().script("rejected")
    h.ingest(world, api.store, fake)
    assert _failures(world)[0].resolved_at is None
    with world.Session() as s:
        st.retry(s, Actor.system("test"), None, s.get(Document, d.id))
        s.commit()
    assert h.status_of(world, d.id) == "pending" and h.doc(world, d.id).sourcetrace_attempts == 0
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    (failure,) = _failures(world)
    assert failure.resolved_at is not None
    rows = h.attempts(world, d.id)
    assert [(r.ok, r.attempt) for r in rows] == [(False, 1), (True, 1)]


# ------------------------------------------------------------------------------------------------ locks


def test_two_runs_never_send_the_same_document(world, api, case_id):
    ids = set()
    for n in range(6):
        _o, d = _order(
            world, api, case_id, text=f"order {n}", order_no=str(n + 1), order_date=date(2025, 1, n + 1)
        )
        ids.add(d.id)
    fakes = [FakeSourceTrace(on_ingest=lambda item: time.sleep(0.05)) for _ in range(2)]
    results: list[dict] = []
    errors: list[BaseException] = []

    def go(fake):
        try:
            results.append(h.ingest(world, api.store, fake))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(f,)) for f in fakes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    sent = [i.document_id for f in fakes for i in f.received]
    assert sorted(map(str, sent)) == sorted(map(str, ids))
    assert sum(r["ingested"] for r in results) == 6
    assert all(len(f.received) > 0 for f in fakes)  # both runs worked, on different documents
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(SourcetraceIngestion)) == 6


def test_visibility_change_during_send_answers_document_busy(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    d = ds.upload(api, hd, case_id, sf.text_pdf(["being sent"])).json()
    seen = {}

    def during(item):
        seen["patch"] = api.patch(
            f"/documents/{d['id']}", headers=hd, json={"visibility": "private_to_office"}
        )
        seen["archive"] = api.post(f"/documents/{d['id']}/archive", headers=hd, json={"reason": "wrong case"})

    h.ingest(world, api.store, FakeSourceTrace(on_ingest=during))
    for key in ("patch", "archive"):
        r = seen[key]
        assert r.status_code == 409 and r.json()["detail"]["code"] == "document_busy", (key, r.text)
    row = h.doc(world, uuid.UUID(d["id"]))
    assert row.sourcetrace_status == SourcetraceStatus.INGESTED and row.visibility == Visibility.CASE_SCOPE
    assert row.archived_at is None
    # after the send the narrowing is refused for what it is
    r = api.patch(f"/documents/{d['id']}", headers=hd, json={"visibility": "private_to_office"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_ingested"


# ------------------------------------------------------------------------------------------------ limits, order


def test_batch_and_run_time_limits(world, api, case_id):
    for n in range(5):
        _order(world, api, case_id, text=f"order {n}", order_no=str(n + 1), order_date=date(2025, 1, n + 1))
    fake = FakeSourceTrace()
    config = st.IngestConfig(batch=2, run_seconds=60, timeout_seconds=1, max_attempts=5)
    counters = h.ingest(world, api.store, fake, config)
    assert counters["claimed"] == 2 and counters["stopped"] == "batch"
    slow = FakeSourceTrace(on_ingest=lambda item: time.sleep(0.15))
    config = st.IngestConfig(batch=50, run_seconds=0.1, timeout_seconds=1, max_attempts=5)
    counters = h.ingest(world, api.store, slow, config)
    assert counters["claimed"] == 1 and counters["stopped"] == "time"
    assert h.ingest(world, api.store, fake)["ingested"] == 2


def test_uploads_before_orders_newest_first(world, api, case_id):
    _o, order_doc = _order(world, api, case_id, order_date=date(2025, 3, 1))
    older = _filing(world, api, case_id, text="older filing", doc_date=date(2025, 1, 1))
    newer = _filing(world, api, case_id, text="newer filing", doc_date=date(2025, 2, 1))
    fake = FakeSourceTrace()
    h.ingest(world, api.store, fake)
    assert [i.document_id for i in fake.received] == [newer.id, older.id, order_doc.id]


def test_disabled_job_sends_nothing_and_writes_no_run(world, api, case_id, monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli import sourcetrace as cli
    from aslms.jobs import celery_app

    _order(world, api, case_id)
    for enabled, state in ((False, "disabled"), (True, "not_implemented")):
        settings = Settings(_env_file=None, sourcetrace_enabled=enabled, redis_url=None)
        monkeypatch.setattr(celery_app, "settings", settings)
        assert celery_app.sourcetrace_ingest_task() == {"state": state}
        monkeypatch.setattr(cli, "get_settings", lambda s=settings: s)
        result = CliRunner().invoke(cli.sourcetrace_app, ["run"])
        assert result.exit_code == 1 and "refused" in result.output and state in result.output
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun).where(JobRun.job == st.JOB)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(SourcetraceIngestion)) == 0
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(Document)
                .where(Document.sourcetrace_status == "pending")
            )
            == 1
        )


def test_run_writes_a_job_run(world, api, case_id):
    _order(world, api, case_id)
    _order(world, api, case_id, text="refused", order_no="2", order_date=date(2025, 1, 2))
    counters = st.run(world.Session, FakeSourceTrace().script("ok", "rejected"), api.store, h.CONFIG)
    assert counters["ingested"] == 1 and counters["failed"] == 1
    with world.Session() as s:
        (run,) = s.scalars(sa.select(JobRun).where(JobRun.job == st.JOB)).all()
        assert run.status.value == "partial" and run.counters["claimed"] == 2 and run.finished_at is not None


def test_shared_order_pdf_sent_once(world, api, case_id):
    pdf = sf.text_pdf(["One order for two cases"])
    with world.Session() as s:
        first = s.get(Case, case_id)
        _o1, doc = ds.stored_order(s, api.store, first, pdf)
        other = make_case(s)
        ds.stored_order(s, api.store, other, pdf, document=doc, order_no="7")
        s.commit()
        first_cnr = first.cnr
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    assert len(fake.received) == 1 and fake.received[0].metadata["cnr"] == first_cnr
    assert fake.received[0].metadata["order_no"] == "1"


# ------------------------------------------------------------------------------------------------ the database


def test_checks_refuse_private_pending_causelist_pending_and_ingested_without_ref(world, api, case_id):
    filing = _filing(world, api, case_id)
    with world.Session() as s:
        cl, _ = store_pdf(s, api.store, sf.text_pdf(["list"]), doc_date=date(2025, 1, 6), description="list")
        s.commit()
        cl_id = cl.id
    cases = (
        ("ck_documents_private_not_sent", filing.id, {"visibility": "private_to_office"}),
        ("ck_documents_sourcetrace_kind", cl_id, {"sourcetrace_status": "pending"}),
        ("ck_documents_sourcetrace_ingested", filing.id, {"sourcetrace_status": "ingested"}),
        (
            "ck_documents_sourcetrace_ingested",
            filing.id,
            {"sourcetrace_status": "ingested", "sourcetrace_ref": "st-1"},
        ),
    )
    for name, doc_id, values in cases:
        with world.Session() as s:
            with pytest.raises(sa.exc.IntegrityError, match=name):
                s.execute(sa.update(Document).where(Document.id == doc_id).values(**values))
            s.rollback()
    with world.Session() as s:
        s.execute(
            sa.update(Document)
            .where(Document.id == filing.id)
            .values(
                sourcetrace_status="ingested", sourcetrace_ref="st-1", sourcetrace_ingested_at=sa.func.now()
            )
        )
        s.rollback()


def test_ingestion_rows_are_append_only(world, api, case_id):
    _o, d = _order(world, api, case_id)
    h.ingest(world, api.store, FakeSourceTrace())
    for sql in ("UPDATE sourcetrace_ingestions SET ok = false", "DELETE FROM sourcetrace_ingestions"):
        with world.Session() as s:
            with pytest.raises(sa.exc.DBAPIError, match="append-only"):
                s.execute(sa.text(sql))
            s.rollback()
    with world.Session() as s:
        with pytest.raises(sa.exc.IntegrityError, match="ck_sourcetrace_ingestions_outcome"):
            s.add(
                SourcetraceIngestion(
                    document_id=d.id, attempt=2, ok=False, connector="fake", metadata_sent={}
                )
            )
            s.flush()
        s.rollback()
    assert len(h.attempts(world, d.id)) == 1


def test_migration_0011_back_fills_archived_and_down_up(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0010")
    doc_ids = {name: uuid.uuid4() for name in ("archived_pending", "archived_failed", "live_pending")}
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))  # no case / office rows needed
            for name, doc_id in doc_ids.items():
                archived = name.startswith("archived")
                conn.execute(
                    sa.text(
                        "INSERT INTO documents (id, sha256, storage_key, mime, size_bytes, kind, doc_type, doc_group, "
                        "case_id, visibility, virus_scan_status, sourcetrace_status, archived_at, archive_reason) "
                        "VALUES (:i, :sha, 'k', 'application/pdf', 1, 'order', 'order', 'court_record', :c, "
                        "'case_scope', 'skipped', :st, :at, :why)"
                    ),
                    {
                        "i": doc_id,
                        "sha": doc_id.hex * 2,
                        "c": uuid.uuid4(),
                        "st": "failed" if name == "archived_failed" else "pending",
                        "at": datetime.now(UTC) if archived else None,
                        "why": "wrong" if archived else None,
                    },
                )
            # the guard: an ingestion row at 0010 stops the upgrade
            conn.execute(
                sa.text(
                    "INSERT INTO sourcetrace_ingestions (document_id, attempt, ok) VALUES (:d, 1, false)"
                ),
                {"d": doc_ids["live_pending"]},
            )
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        with pytest.raises(RuntimeError, match="cannot upgrade to 0011"):
            command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM sourcetrace_ingestions"))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            got = dict(conn.execute(sa.text("SELECT id, sourcetrace_status::text FROM documents")).all())
            assert got[doc_ids["archived_pending"]] == "not_applicable"
            assert got[doc_ids["archived_failed"]] == "not_applicable"
            assert got[doc_ids["live_pending"]] == "pending"
            assert (
                conn.execute(
                    sa.text("SELECT has_table_privilege('aslms_app', 'sourcetrace_ingestions', 'DELETE')")
                ).scalar()
                is False
            )
            assert (
                conn.execute(
                    sa.text("SELECT has_table_privilege('aslms_app', 'sourcetrace_ingestions', 'INSERT')")
                ).scalar()
                is True
            )
        # down with no attempts: fine; up again
        command.downgrade(cfg, "0010")
        command.upgrade(cfg, "head")
        # the downgrade refuses while an attempt row exists
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO sourcetrace_ingestions (document_id, attempt, ok, connector, error, error_family, "
                    "metadata_sent) VALUES (:d, 1, false, 'fake', 'x', 'rejected', '{}')"
                ),
                {"d": doc_ids["live_pending"]},
            )
        with pytest.raises(RuntimeError, match="cannot downgrade 0011"):
            command.downgrade(cfg, "0010")
        with engine.connect() as conn:
            # a refused downgrade rolls back whole: the database stays at the head (0012 and later included)
            assert (
                conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
            )
    finally:
        wipe_if_migrated(db_url)
        command.upgrade(cfg, "head")
