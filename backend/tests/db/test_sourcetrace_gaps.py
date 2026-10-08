"""Tester's additions for design `sourcetrace-connector`: the guard under the row lock, idempotence of a second
run, the human retries (API, CLI) and their audit rows, the CLI check, and the 401 paths of the admin API."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.domain.cases import Case
from aslms.domain.documents import Document
from aslms.domain.org import User
from aslms.domain.workflow import SourcetraceIngestion
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import sourcetrace_ingest as st
from aslms.services.audit import Actor
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import st_support as h
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_id(world):
    with world.Session() as s:
        case = w.claimed_case(s, world)
        s.commit()
        return case.id


def _order(world, api, case_id, **kw):
    with world.Session() as s:
        _o, d = ds.stored_order(s, api.store, s.get(Case, case_id), sf.text_pdf([kw.pop("text", "o")]), **kw)
        s.commit()
        return d


def _guard_failures(world):
    with world.Session() as s:
        return list(
            s.execute(
                sa.text("select ref, error_family from source_failures where kind = :k"),
                {"k": st.GUARD_KIND},
            ).all()
        )


def test_guard_under_the_lock_sends_nothing_and_leaves_the_status(world, api, case_id):
    """`assert_sendable` runs again inside `ingest_one`: a document that became unsendable after the claim is
    refused, recorded as a `sourcetrace_guard` failure, never reaches the connector, and keeps its status."""
    with world.Session() as s:
        d = h.upload_row(s, api.store, s.get(Case, case_id), world.office(s, "EDU"), text="late archive")
        d.archived_at = sa.func.now()
        d.archive_reason = "wrong case"
        s.commit()
        doc_id = d.id
    fake = FakeSourceTrace()
    with world.Session() as s:
        doc = s.get(Document, doc_id)
        outcome = asyncio.run(st.ingest_one(s, fake, api.store, doc, h.CONFIG))
        s.commit()
    assert outcome.result == "guarded" and fake.received == []
    assert h.status_of(world, doc_id) == "pending" and h.doc(world, doc_id).sourcetrace_attempts == 0
    assert h.attempts(world, doc_id) == []
    assert _guard_failures(world) == [(str(doc_id), "guard")]


def test_guard_refusal_does_not_stop_or_loop_the_run(world, api, case_id, monkeypatch):
    refused = _order(world, api, case_id, text="refused", order_no="1")
    ok = _order(world, api, case_id, text="fine", order_no="2")
    real = st.assert_sendable

    def picky(doc, case, order):
        if doc.id == refused.id:
            raise st.NotSendable("test refusal")
        return real(doc, case, order)

    monkeypatch.setattr(st, "assert_sendable", picky)
    fake = FakeSourceTrace()
    counters = h.ingest(world, api.store, fake)
    assert counters["guarded"] == 1 and counters["ingested"] == 1 and counters["stopped"] == "empty"
    assert [i.document_id for i in fake.received] == [ok.id]
    assert h.status_of(world, refused.id) == "pending"


def test_a_second_run_sends_nothing_again(world, api, case_id):
    d = _order(world, api, case_id)
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["ingested"] == 1
    again = h.ingest(world, api.store, fake)
    assert again["claimed"] == 0 and again["stopped"] == "empty" and len(fake.received) == 1
    assert len(h.attempts(world, d.id)) == 1


def _failed_pair(world, api, case_id):
    a = _order(world, api, case_id, text="a", order_no="1")
    b = _order(world, api, case_id, text="b", order_no="2")
    h.ingest(world, api.store, FakeSourceTrace().script("rejected", "rejected"))
    assert h.status_of(world, a.id) == h.status_of(world, b.id) == "failed"
    return a, b


def test_retry_all_failed_requeues_and_writes_one_audit_row(world, api, case_id):
    a, b = _failed_pair(world, api, case_id)
    with world.Session() as s:
        n = st.retry_all_failed(s, Actor.system("cli"))
        s.commit()
    assert n == 2
    for d in (a, b):
        row = h.doc(world, d.id)
        assert row.sourcetrace_status == "pending" and row.sourcetrace_attempts == 0
        assert row.sourcetrace_next_at is None
    with world.Session() as s:
        (audit,) = ds.audit_rows(s, "sourcetrace.retry_all_failed")
        assert audit.after == {"count": 2} and audit.actor_name == "cli"
    # nothing failed now: a second call retries nothing but is still audited with count 0
    with world.Session() as s:
        assert st.retry_all_failed(s, Actor.system("cli")) == 0
        s.commit()
    fake = FakeSourceTrace()
    assert h.ingest(world, api.store, fake)["ingested"] == 2


def test_retry_of_a_pending_document_waiting_on_back_off(world, api, case_id):
    d = _order(world, api, case_id)
    h.ingest(world, api.store, FakeSourceTrace().script("unavailable"))
    row = h.doc(world, d.id)
    assert row.sourcetrace_status == "pending" and row.sourcetrace_attempts == 1 and row.sourcetrace_next_at
    with world.Session() as s:
        st.retry(s, Actor.system("cli"), None, s.get(Document, d.id))
        s.commit()
    row = h.doc(world, d.id)
    assert row.sourcetrace_attempts == 0 and row.sourcetrace_next_at is None
    assert h.ingest(world, api.store, FakeSourceTrace())["ingested"] == 1


def _cli(world, monkeypatch, *args):
    from aslms.cli import sourcetrace as cli

    class _Scope:
        def __enter__(self):
            self.s = world.Session()
            return self.s

        def __exit__(self, et, ev, tb):
            if et is None:
                self.s.commit()
            else:
                self.s.rollback()
            self.s.close()
            return False

    monkeypatch.setattr(cli, "session_scope", lambda: _Scope())
    return CliRunner().invoke(cli.sourcetrace_app, list(args))


def test_cli_retry_check_and_status(world, api, case_id, monkeypatch):
    a, b = _failed_pair(world, api, case_id)
    r = _cli(world, monkeypatch, "retry")
    assert r.exit_code != 0  # neither --document nor --all-failed
    r = _cli(world, monkeypatch, "retry", "--document", str(a.id), "--all-failed")
    assert r.exit_code != 0
    r = _cli(world, monkeypatch, "retry", "--document", str(a.id))
    assert r.exit_code == 0, r.output
    assert h.status_of(world, a.id) == "pending" and h.status_of(world, b.id) == "failed"
    r = _cli(world, monkeypatch, "retry", "--document", str(a.id))  # fresh pending: 409 equivalent
    assert r.exit_code == 1
    r = _cli(world, monkeypatch, "retry", "--all-failed")
    assert r.exit_code == 0 and h.status_of(world, b.id) == "pending"
    with world.Session() as s:
        assert len(ds.audit_rows(s, "sourcetrace.retry_requested", entity_id=a.id)) == 1
        assert len(ds.audit_rows(s, "sourcetrace.retry_all_failed")) == 1
    r = _cli(world, monkeypatch, "check")
    assert r.exit_code == 0, r.output
    # a pending document that is archived breaks the rule: check exits 1 and names the count
    with world.Session() as s:
        s.execute(
            sa.update(Document)
            .where(Document.id == a.id)
            .values(archived_at=sa.func.now(), archive_reason="x")
        )
        s.commit()
    r = _cli(world, monkeypatch, "check")
    assert r.exit_code == 1 and "documents_breaking_rule" in r.output
    r = _cli(world, monkeypatch, "status")
    assert r.exit_code == 0 and "state" in r.output


def test_admin_api_refuses_unauthenticated_and_disabled_users(world, api, case_id):
    d = _order(world, api, case_id)
    for method, path in (
        ("get", "/admin/sourcetrace/status"),
        ("get", "/admin/sourcetrace/failed"),
        ("post", f"/admin/sourcetrace/documents/{d.id}/retry"),
    ):
        assert getattr(api, method)(path).status_code == 401
        assert getattr(api, method)(path, headers={"Authorization": "Bearer nope"}).status_code == 401
    headers = ds.login(api, "central_op")
    assert api.get("/admin/sourcetrace/status", headers=headers).status_code == 200
    with world.Session() as s:
        s.execute(sa.update(User).where(User.id == world.users["central_op"].id).values(is_active=False))
        s.commit()
    assert api.get("/admin/sourcetrace/status", headers=headers).status_code == 401


def test_ingestion_rows_never_carry_the_uploader_text(world, api, case_id):
    hd = ds.login(api, "edu_admin")
    d = ds.upload(
        api,
        hd,
        case_id,
        sf.text_pdf(["secret remark filing"]),
        description="INTERNAL REMARK do not share",
        name="privileged-advice.pdf",
    ).json()
    h.ingest(world, api.store, FakeSourceTrace())
    with world.Session() as s:
        rows = s.scalars(
            sa.select(SourcetraceIngestion).where(SourcetraceIngestion.document_id == uuid.UUID(d["id"]))
        ).all()
    assert len(rows) == 1
    blob = repr(rows[0].metadata_sent) + repr(rows[0].response)
    assert "INTERNAL REMARK" not in blob and "privileged-advice" not in blob
