"""The research index in the database (design `research-index`, "Tests", database; decisions 7, 9 to 15, 22, 30, 33
and 34): migration 0042, the halfvec column, the retire-once trigger and the grants, chunk sets shared by identical
bodies and kept across readings, case sheets, the job's budget and watermark, the asking flag, failures, the rebuild,
and no court call. The embedding model is `FakeOllama` (never a real model)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import DBAPIError

from aslms.domain.audit_actions import AUDIT_ACTIONS
from aslms.domain.cases import CaseParty, PartyRole
from aslms.domain.documents import DocumentText, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchQueueItem, JobRun, NapixCallLog, SourceFailure
from aslms.domain.research import ResearchEmbedding
from aslms.services import order_parse_rules as R
from aslms.services import order_sections
from aslms.services import research_embed as re_
from aslms.services import research_index as ri
from aslms.services.audit import Actor
from tests.db import research_support as rs
from tests.db.conftest import alembic_config, wipe_if_migrated
from tests.db.world import make_case
from tests.redis_stub import RedisStub

PROFILE = rs.PROFILE


def order_sections_rows(s, order):
    from tests.db import order_sections_support as o

    return o.readings(s, order)


def _orders(s, n=1, *, body=rs.PENSION_BODY, heading="JUDGMENT", kind=OrderKind.JUDGMENT):
    out = []
    for _ in range(n):
        case = make_case(s)
        out.append(rs.court_order(s, case, body=body, heading=heading, kind=kind))
    rs.read_orders(s)
    return out


# ------------------------------------------------------------------------------------------------ migration and DDL


@pytest.mark.migration_cycle
def test_migration_0042_up_down_up(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    q = {
        "ext": "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
        "tables": "SELECT count(*) FROM pg_tables WHERE tablename IN ('research_chunks', 'research_embeddings')",
        "hnsw": "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_research_embeddings_hnsw_768'",
        "gin": "SELECT count(*) FROM pg_indexes WHERE indexname IN "
        "('ix_order_sections_facts_judgments', 'ix_order_sections_facts_acts')",
        "types": "SELECT count(*) FROM pg_type WHERE typname IN ('research_chunk_kind', 'research_retire_reason')",
    }
    try:
        command.downgrade(cfg, "0041")
        with engine.connect() as conn:
            assert conn.execute(sa.text(q["ext"])).scalar() is None
            assert conn.execute(sa.text(q["tables"])).scalar() == 0
            assert conn.execute(sa.text(q["gin"])).scalar() == 0
            assert conn.execute(sa.text(q["types"])).scalar() == 0
            assert (
                conn.execute(sa.text("SELECT count(*) FROM pg_type WHERE typname = 'order_kind'")).scalar()
                == 1
            )
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(sa.text(q["ext"])).scalar() == "0.8.7"
        assert conn.execute(sa.text(q["tables"])).scalar() == 2
        hnsw = conn.execute(sa.text(q["hnsw"])).scalar()
        assert "hnsw" in hnsw and "halfvec_cosine_ops" in hnsw and "(dims = 768)" in hnsw
        assert conn.execute(sa.text(q["gin"])).scalar() == 2
        assert conn.execute(sa.text(q["types"])).scalar() == 2


def test_grants_and_class_comments(engine):
    with engine.connect() as conn:
        for table in ("research_chunks", "research_embeddings"):

            def priv(role, p, table=table):
                return conn.execute(
                    sa.text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": table, "p": p}
                ).scalar()

            assert priv("aslms_app", "SELECT") and priv("aslms_app", "INSERT") and priv("aslms_app", "UPDATE")
            assert not priv("aslms_app", "DELETE")
            assert priv("aslms_readonly", "SELECT") and not priv("aslms_readonly", "INSERT")
            comment = conn.execute(
                sa.text("SELECT obj_description(CAST(:t AS regclass))"), {"t": table}
            ).scalar()
            assert comment == "class=derived"


def test_halfvec_binding_and_dims_check(world):
    with world.Session() as s:
        _orders(s)
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 1
        chunk = rs.chunks(s)[0]
        good = [0.0] * 767 + [1.0]
        s.add(
            ResearchEmbedding(
                input_sha256=chunk.embed_sha256,
                first_chunk_id=chunk.id,
                model="m:1",
                model_digest="d",
                model_key="m:1@d",
                profile="embeddinggemma",
                dims=768,
                embedding=good,
            )
        )
        s.flush()
        dist = s.scalar(
            sa.text("SELECT embedding <=> CAST(:v AS halfvec) FROM research_embeddings LIMIT 1"),
            {"v": "[" + ",".join(["0"] * 767 + ["1"]) + "]"},
        )
        assert dist == pytest.approx(0.0, abs=1e-3)
        with pytest.raises(DBAPIError, match="ck_research_embeddings_dims"), s.begin_nested():
            s.add(
                ResearchEmbedding(
                    input_sha256="x" * 64,
                    first_chunk_id=chunk.id,
                    model="m:1",
                    model_digest="d",
                    model_key="m:1@d",
                    profile="embeddinggemma",
                    dims=768,
                    embedding=[0.5] * 10,
                )
            )
            s.flush()
        with pytest.raises(ValueError):
            from aslms.db.base import vector_literal

            vector_literal([float("nan")])
        s.rollback()


def test_retire_once_trigger(world):
    with world.Session() as s:
        _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
        cid = rs.chunks(s)[0].id
    with world.Session() as s, pytest.raises(DBAPIError, match="a row never changes"):
        s.execute(sa.text("UPDATE research_chunks SET text = 'x' WHERE id = :i"), {"i": cid})
    with world.Session() as s:
        s.execute(
            sa.text("UPDATE research_chunks SET retired_at = now(), retire_reason = 'rebuilt' WHERE id = :i"),
            {"i": cid},
        )
        s.commit()
    with world.Session() as s, pytest.raises(DBAPIError, match="retired once"):
        s.execute(
            sa.text("UPDATE research_chunks SET retire_reason = 'reading_gone' WHERE id = :i"), {"i": cid}
        )


# ------------------------------------------------------------------------------------------------ chunk sets


def test_sets_shared_by_identical_bodies(world):
    with world.Session() as s:
        orders = _orders(s, 3)
        keys = {rs.reading(s, o).body_sha256 for o in orders}
        assert len(keys) == 1
        got = ri.sync_sets(s, profile=PROFILE)
        assert got["cut"] == 1
        chunks = rs.chunks(s)
        assert {c.body_sha256 for c in chunks} == keys
        for c in chunks:
            first = s.get(type(rs.reading(s, orders[0])), c.first_reading_id)
            assert c.text == first.body_text[c.txt_start : c.txt_end]
            assert c.embed_sha256 == ri.rc.input_sha256(PROFILE, c.context_line, c.text)
            assert c.chunker_version == ri.rc.CHUNKER_VERSION and c.chars == len(c.text)
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 0  # cut once
        s.commit()


def test_empty_body_gets_no_chunk(world):
    with world.Session() as s:
        _orders(s, body="\n", heading="ORDER", kind=OrderKind.INTERIM)
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 0
        assert rs.chunks(s) == []


def test_new_reading_same_body_reuses_set(world):
    with world.Session() as s:
        (order,) = _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
        before = [c.id for c in rs.chunks(s)]
    with world.Session() as s:  # the header changes, the body does not
        t = s.get(DocumentText, order.document_id)
        t.full_text = t.full_text.replace("PETITIONER A ", "PETITIONER AA ")
        s.commit()
    with world.Session() as s:
        order_sections.read_batch(s, batch=10, full=True)
        s.commit()
    with world.Session() as s:
        assert len(order_sections_rows(s, order)) == 2  # a new reading, the body unchanged
        assert ri.retire_orphans(s) == 0
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 0
        assert [c.id for c in rs.chunks(s)] == before


def test_changed_body_retires_old_set_and_vectors(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        (order,) = _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
    key = re_.live_key(fake.client(), cfg.research_embed_model)
    assert key.key == rs.KEY
    with world.Session() as s:
        re_.embed_batch(s, fake.client(), key, re_.pending(s, key.key, limit=50), cfg)
        s.commit()
        old_chunks = {c.id for c in rs.chunks(s)}
        assert len(rs.vectors(s)) == len({c.embed_sha256 for c in rs.chunks(s)})
    with world.Session() as s:
        t = s.get(DocumentText, order.document_id)
        t.full_text = t.full_text.replace("vigilance clearance", "departmental clearance")
        s.commit()
    with world.Session() as s:
        order_sections.read_batch(s, batch=10, full=True)
        s.commit()
    with world.Session() as s:
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 1
        assert ri.retire_orphans(s) == len(old_chunks)
        retired = re_.retire_unused(s)
        s.commit()
        assert retired >= 1  # the changed paragraph's vector; unchanged paragraphs keep theirs by hash
        gone = [c for c in rs.chunks(s, current=False) if c.id in old_chunks]
        assert {c.retire_reason.value for c in gone} == {"reading_gone"}
        live_hashes = {c.embed_sha256 for c in rs.chunks(s)}
        assert all(v.input_sha256 in live_hashes for v in rs.vectors(s))


def test_parser_version_bump_reuses_vectors_by_hash(world, monkeypatch):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
    key = re_.live_key(fake.client(), cfg.research_embed_model)
    with world.Session() as s:
        re_.embed_batch(s, fake.client(), key, re_.pending(s, key.key, limit=50), cfg)
        s.commit()
        n_vectors = len(rs.vectors(s))
    calls = len(fake.embeds)
    monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
    with world.Session() as s:
        order_sections.read_batch(s, batch=10)
        s.commit()
    with world.Session() as s:
        assert ri.sync_sets(s, profile=PROFILE)["cut"] == 1
        ri.retire_orphans(s)
        assert re_.retire_unused(s) == 0
        assert re_.pending(s, key.key, limit=50) == []  # identical inputs: no model call
        s.commit()
        assert len(rs.vectors(s)) == n_vectors and len(fake.embeds) == calls
        assert {c.parser_version for c in rs.chunks(s)} == {R.PARSER_VERSION}


# ------------------------------------------------------------------------------------------------ case sheets


def test_sheet_new_on_change(world):
    with world.Session() as s:
        case = make_case(s, pet="SUMMARY PET", res="SUMMARY RES")
        case.category, case.sub_category, case.case_type_text, case.reg_year = (
            "Service",
            "Pension",
            "WP(C)",
            2025,
        )
        s.add(CaseParty(case_id=case.id, role=PartyRole.RESPONDENT, party_no=1, name="THE STATE OF ASSAM",
                        name_normalised="the state of assam"))  # fmt: skip
        s.flush()
        got = ri.sync_sheets(s, profile=PROFILE, since=None)
        assert got["sheets"] >= 1
        (sheet,) = [c for c in rs.chunks(s, kind="case_sheet") if c.case_id == case.id]
        assert "Category: Service / Pension" in sheet.text and "Respondents: THE STATE OF ASSAM" in sheet.text
        assert case.cnr not in sheet.text and case.ref_no not in sheet.text
        assert ri.write_sheets(s, [case.id], profile=PROFILE)["sheets"] == 0  # same text: nothing new
        case.short_order = "Disposed of."
        s.flush()
        assert ri.write_sheets(s, [case.id], profile=PROFILE)["sheets"] == 1
        old = [c for c in rs.chunks(s, current=False, kind="case_sheet") if c.case_id == case.id]
        assert sorted(str(c.retire_reason) for c in old) == ["None", "sheet_changed"]
        s.commit()


# ------------------------------------------------------------------------------------------------ the job


def test_job_budget_and_watermark(world):
    fake = rs.fake()
    cfg = rs.settings(research_job_seconds=5)
    with world.Session() as s:
        _orders(s, 2)
        _orders(s, 1, body=rs.JUDGMENT_BODY)
        s.commit()
    ticks = iter([0.0] + [1.0] * 3 + [100.0] * 50)  # the second embedding batch is past the budget
    counters = re_.run_job(world.Session, fake.client(), cfg, monotonic=lambda: next(ticks))
    assert counters["cut"] == 2 and counters["model_key"] == rs.KEY
    assert counters["embedded"] > 0 and counters["watermark"]
    with world.Session() as s:
        run = s.scalar(sa.select(JobRun).where(JobRun.job == ri.JOB))
        assert run.status.value == "succeeded" and run.counters["cut"] == 2
    # disabled: nothing is done or called
    calls = len(fake.requests)
    assert re_.run_job(world.Session, fake.client(), rs.settings(research_index_enabled=False)) == {
        "disabled": 1
    }
    assert len(fake.requests) == calls
    # the model not held: the chunk steps run, embedding is skipped
    fake.embed_held = False
    calls = len(fake.embeds)
    counters = re_.run_job(world.Session, fake.client(), cfg)
    assert counters["model_unready"] == 1 and counters["embedded"] == 0 and len(fake.embeds) == calls


def test_job_waits_for_asking_flag():
    r = RedisStub()
    slept = []
    re_.set_asking(r)
    waited = re_.wait_for_people(r, step=2.0, limit=6.0, sleep=slept.append)
    assert waited == 6000 and slept == [2.0, 2.0, 2.0]
    re_.clear_asking(r)
    assert re_.wait_for_people(r, sleep=slept.append) == 0
    r.fail = True
    assert re_.wait_for_people(r, sleep=slept.append) == 0  # Redis down: never wait


def _embed_all(world, fake, cfg):
    key = re_.live_key(fake.client(), cfg.research_embed_model)
    while True:
        with world.Session() as s:
            todo = re_.pending(s, key.key, limit=50)
            if not todo:
                return key
            re_.embed_batch(s, fake.client(), key, todo, cfg)
            s.commit()


def test_job_sheet_cursor_moves_past_full_pages(world, monkeypatch):
    """Review finding 2: with a full page of changed cases the sheet cursor moves past that page (ties on one
    `updated_at` broken by id), so the job reaches every changed case and a page of unchanged sheets is not read
    again; a backfill phase row (no watermark) does not send the job back to its first look-back."""
    monkeypatch.setattr(ri, "SHEET_BATCH", 2)
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:  # one commit: the five share one updated_at
        mine = [make_case(s).id for _ in range(5)]
        s.commit()
    start = datetime.now(UTC) + timedelta(hours=1)
    afters = []
    for i in range(40):
        now = start + timedelta(minutes=5 * i)
        counters = re_.run_job(world.Session, fake.client(), cfg, now=now)
        afters.append(counters["sheet_after"])
        if i == 0:
            assert counters["sheet_after"] is not None  # a full page: the cursor sits on its last case
            with world.Session() as s:
                s.add(JobRun(job=ri.JOB, run_date=now.date(), started_at=now + timedelta(seconds=30),
                             finished_at=now + timedelta(seconds=31), counters={"backfill": 1, "phase": "sheets"}))  # fmt: skip
                s.commit()
                assert re_._previous_counters(s)["sheet_after"] == counters["sheet_after"]
        if counters["sheet_after"] is None:
            break
    else:
        pytest.fail("the sheet cursor never reached the end")
    assert len(set(a for a in afters if a)) == len([a for a in afters if a])  # never the same page twice
    assert datetime.fromisoformat(counters["sheet_watermark"]) == now - ri.WATERMARK_SLACK
    with world.Session() as s:
        have = {c.case_id for c in rs.chunks(s, kind="case_sheet")}
        assert set(mine) <= have


def test_job_parser_bump_keeps_vectors_across_runs(world, monkeypatch):
    """Review finding 3: a parser-version bump re-reads every order; the job cuts one set a run here, and an old set
    is retired only once its order's new set is cut, so no vector is lost and no model call is made, however many
    runs the cutting takes."""
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        orders = [
            rs.court_order(
                s,
                make_case(s),
                body=rs.PENSION_BODY.replace("a teacher", f"a teacher of school {i}"),
                heading="JUDGMENT",
                kind=OrderKind.JUDGMENT,
            )
            for i in range(3)
        ]
        rs.read_orders(s)
        ri.sync_sets(s, profile=PROFILE)
        ri.sync_sheets(s, profile=PROFILE, since=None)
        s.commit()
    key = _embed_all(world, fake, cfg)
    with world.Session() as s:
        n_vectors = len(rs.vectors(s))
        old_sets = {c.body_sha256 + str(c.parser_version) for c in rs.chunks(s, kind="order_body")}
    calls = len(fake.embeds)
    monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
    with world.Session() as s:
        order_sections.read_batch(s, batch=10)
        s.commit()
        assert all(len(order_sections_rows(s, o)) == 2 for o in orders)
    monkeypatch.setattr(re_, "SETS_PER_STEP", 1)
    start = datetime.now(UTC) + timedelta(hours=1)
    for i in range(6):
        counters = re_.run_job(world.Session, fake.client(), cfg, now=start + timedelta(minutes=5 * i))
        with world.Session() as s:
            assert len(rs.vectors(s)) == n_vectors, f"run {i}: a vector was retired"
            if i == 0:
                assert counters["cut"] == 1 and counters.get("vectors_retired", 0) == 0
                live = {c.body_sha256 + str(c.parser_version) for c in rs.chunks(s, kind="order_body")}
                assert len(live & old_sets) == 2  # the two orders still waiting keep their old sets
        if counters["cut"] == 0:
            break
    with world.Session() as s:
        assert {c.parser_version for c in rs.chunks(s, kind="order_body")} == {R.PARSER_VERSION}
        assert re_.pending(s, key.key, limit=50) == []
    assert len(fake.embeds) == calls  # identical inputs: no model call


def test_embed_failure_recorded_and_retried(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
    key = re_.live_key(fake.client(), cfg.research_embed_model)
    fake.too_long_over = 10  # every input is refused as too long
    with world.Session() as s:
        todo = re_.pending(s, key.key, limit=50)
        res = re_.embed_batch(s, fake.client(), key, todo, cfg)
        s.commit()
        assert res.failed == len(todo) and res.embedded == 0
        fails = s.scalars(sa.select(SourceFailure).where(SourceFailure.kind == "research_embed")).all()
        assert {f.ref for f in fails} == {str(c.id) for c in todo} and {f.error_family for f in fails} == {
            "too_long"
        }
        assert re_.pending(s, key.key, limit=50) == []  # the job skips open failures
    # a wrong dimension is a failure too
    fake.too_long_over = None
    fake.embed_dims = 10
    with world.Session() as s:
        todo = re_.pending(s, key.key, limit=50, retry=True)
        assert re_.embed_batch(s, fake.client(), key, todo, cfg).failed == len(todo)
        s.rollback()
    fake.embed_dims = 768
    counters = re_.reconcile_job(world.Session, fake.client(), cfg)
    assert counters["retried"] >= 1 and counters["retry_failed"] == 0
    with world.Session() as s:
        assert ri.failures_open(s) == 0
        run = s.scalar(sa.select(JobRun).where(JobRun.job == ri.RECONCILE_JOB))
        assert run.status.value == "succeeded"


def test_rebuild_embeddings_audited(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s)
        ri.sync_sets(s, profile=PROFILE)
        s.commit()
    key = re_.live_key(fake.client(), cfg.research_embed_model)
    with world.Session() as s:
        re_.embed_batch(s, fake.client(), key, re_.pending(s, key.key, limit=50), cfg)
        s.commit()
    fake.embed_digest = "sha256:" + "f" * 64  # a re-pull: a new live key
    new = re_.live_key(fake.client(), cfg.research_embed_model)
    assert new.key != key.key
    with world.Session() as s:
        assert len(re_.pending(s, new.key, limit=50)) >= 1  # old vectors are not the live key's
        actor = Actor.system("aslms research-index rebuild")
        after = ri.rebuild(s, chunks=False, embeddings=True, live_key=new.key, actor=actor)
        s.commit()
        assert after["vectors_retired_by_key"] == {key.key: len(rs.vectors(s, current=False))}
        assert rs.vectors(s) == []
        row = s.scalar(sa.select(AuditLog).where(AuditLog.action == "research_index.rebuilt"))
        assert row.entity_type == "research_index" and row.after["embeddings"] is True
        assert "research_index.rebuilt" in AUDIT_ACTIONS
        with pytest.raises(ValueError):
            ri.rebuild(s, chunks=False, embeddings=False, live_key=None, actor=Actor.system())


def test_backfill_phases_and_resume(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s, 1, body=rs.JUDGMENT_BODY)
        _orders(s, 1, body=rs.PENSION_BODY, heading="ORDER", kind=OrderKind.INTERIM)
        s.commit()
    lines = []
    got = re_.backfill(world.Session, fake.client(), cfg, chunks_only=True, pause_ms=0, echo=lines.append)
    assert got["cut"] == 2 and got["embedded"] == 0 and fake.embeds == []
    got = re_.backfill(world.Session, fake.client(), cfg, pause_ms=0, limit=1, sleep=lambda _x: None)
    assert got["cut"] == 0 and got["embedded"] == 1
    got = re_.backfill(world.Session, fake.client(), cfg, pause_ms=0, sleep=lambda _x: None)
    with world.Session() as s:
        assert re_.pending(s, rs.KEY, limit=100) == []
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun).where(JobRun.job == ri.JOB)) >= 5


def test_status_block(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s)
        s.commit()
    re_.run_job(world.Session, fake.client(), cfg)
    with world.Session() as s:
        block = ri.status(s, enabled=True, live_key=rs.KEY, readiness="ready", timeout_s=5, restore_s=30)
        assert block["chunks"]["order_body"] >= 1 and block["coverage"] > 0 and block["timed_out"] == []
        assert block["last_run"]["status"] == "succeeded" and block["table_sizes"]["research_chunks"] > 0


def test_no_napix_no_fetch_queue(world):
    fake = rs.fake()
    cfg = rs.settings()
    with world.Session() as s:
        _orders(s, 2)
        s.commit()
    re_.run_job(world.Session, fake.client(), cfg)
    re_.reconcile_job(world.Session, fake.client(), cfg)
    re_.backfill(world.Session, fake.client(), cfg, pause_ms=0, sleep=lambda _x: None)
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == 0
    assert {p for _m, p, _b in fake.requests} <= {"/api/tags", "/api/ps", "/api/version", "/api/embed"}
