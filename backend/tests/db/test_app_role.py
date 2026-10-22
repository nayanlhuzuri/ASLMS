"""Design `safety-fixes`, decision 4: the grants of `aslms_app` follow DB_STANDARD §8 on every table, the role cannot
delete legal records or update the logs, and the main paths run under it without a privilege error (the owner rule
from the audit: "one test running an API flow under SET ROLE aslms_app").

The API flow uses its own engine whose every connection runs `SET ROLE aslms_app`: sign-in with the e-mailed code,
`/me`, the case list and detail, claim, sending the file, a note, an upload, the data-health screen, a report and the
audit log; then the event scan, a queue-runner pass with the scripted gateway (a dossier applied and an order PDF
stored) and one run of the background storing of advocate-search rows. The rest of the suite keeps the owner
connection (`wipe` and `session_replication_role` need it)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from sqlalchemy.orm import sessionmaker

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.db.base import APPEND_ONLY_TABLES, CASCADE_TABLES, DRAFT_TABLES
from aslms.domain.cases import Case
from aslms.domain.documents import Document, Order
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.integration.napix.client import NapixResult
from aslms.services import alerts, court_search, queue
from aslms.services.napix_store import NapixRecorder, store_response
from aslms.services.runner import QueueRunner
from aslms.services.scanner import FakeScanner
from aslms.services.storage import LocalStore
from tests import samplefiles as sf
from tests.db import alerts_support as h
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.conftest import TEST_URL, router, sample
from tests.db.world import make_case

NO_UPDATE = set(APPEND_ONLY_TABLES) | {"napix_call_log"}
# DELETE only on the cascading and draft tables; an append-only table among them (sourcetrace_ingestions, whose FK
# cascades per DB_STANDARD §6) keeps SELECT / INSERT only (docs/schema/schema.md)
MAY_DELETE = (set(CASCADE_TABLES) | set(DRAFT_TABLES)) - set(APPEND_ONLY_TABLES)


def _privileges(engine, table: str) -> dict[str, bool]:
    with engine.connect() as conn:
        return {
            p: bool(
                conn.execute(
                    sa.text("select has_table_privilege('aslms_app', :t, :p)"),
                    {"t": f"public.{table}", "p": p},
                ).scalar()
            )
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }


def test_app_role_grants_follow_db_standard(engine):
    with engine.connect() as conn:
        tables = (
            conn.execute(sa.text("select tablename from pg_tables where schemaname = 'public'"))
            .scalars()
            .all()
        )
    assert len(tables) > 50
    wrong: dict[str, dict[str, bool]] = {}
    for t in tables:
        got = _privileges(engine, t)
        if t == "alembic_version":
            want = {"SELECT": False, "INSERT": False, "UPDATE": False, "DELETE": False}
        else:
            want = {"SELECT": True, "INSERT": True, "UPDATE": t not in NO_UPDATE, "DELETE": t in MAY_DELETE}
        if got != want:
            wrong[t] = got
    assert wrong == {}


def test_app_role_cannot_delete_cases_or_update_audit_log(engine):
    for stmt in ("DELETE FROM cases WHERE false", "UPDATE audit_log SET action = action WHERE false"):
        with engine.connect() as conn:
            conn.execute(sa.text("SET LOCAL ROLE aslms_app"))
            with pytest.raises(sa.exc.ProgrammingError) as info:
                conn.execute(sa.text(stmt))
            assert isinstance(info.value.orig, pg_errors.InsufficientPrivilege)
            conn.rollback()
    with engine.connect() as conn:  # and no DDL
        conn.execute(sa.text("SET LOCAL ROLE aslms_app"))
        with pytest.raises(sa.exc.ProgrammingError) as info:
            conn.execute(sa.text("CREATE TABLE app_role_probe (id int)"))
        assert isinstance(info.value.orig, pg_errors.InsufficientPrivilege)
        conn.rollback()


# ------------------------------------------------------------------------------------------------ the flow


@pytest.fixture()
def app_engine():
    eng = sa.create_engine(TEST_URL, poolclass=sa.pool.NullPool)

    @sa.event.listens_for(eng, "connect")
    def as_app(dbapi_conn, _record):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET ROLE aslms_app")
        dbapi_conn.commit()

    yield eng
    eng.dispose()


def _order_router(gw):
    base = router(gw)
    pdf = sf.text_pdf(["ORDER", "List the matter after two weeks."])

    def handle(path, q, request):
        if path == "hc-order-api/order":
            return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        return base(path, q, request)

    return handle


def test_api_flow_as_aslms_app(world, app_engine, napix, tmp_path):
    w.widen(world)
    AppSession = sessionmaker(bind=app_engine, expire_on_commit=False)
    with AppSession() as s:
        assert s.execute(sa.text("select current_user")).scalar() == "aslms_app"
    with world.Session() as s:
        case = make_case(s, pet="RAM KUMAR", res="STATE OF ASSAM")
        h.recommend(s, world, case, "EDU")
        s.commit()
        case_id = str(case.id)
        off1 = str(world.users["edu_off1"].id)

    settings = Settings(
        _env_file=None,
        aslms_jwt_secret=ds.JWT,
        aslms_access_token_minutes=5,
        storage_dir=str(tmp_path / "store"),
        redis_url=None,
    )
    app = create_app(settings, AppSession)
    app.state.scanner = FakeScanner()
    with TestClient(app) as api:
        admin = ds.login(api, "edu_admin")  # password and the e-mailed code
        me = api.get("/me", headers=admin)
        assert me.status_code == 200, me.text
        assert api.get("/cases", headers=admin).status_code == 200
        assert api.get(f"/cases/{case_id}", headers=admin).status_code == 200
        r = api.post(f"/cases/{case_id}/claim", json={"officer_user_id": off1}, headers=admin)
        assert r.status_code == 201, r.text
        h1 = w.login(api, "edu_off1")
        with world.Session() as s:
            target = str(world.membership(s, "edu_off2").id)
        r = api.post(
            f"/cases/{case_id}/custody/send",
            headers=h1,
            json={"to_membership": target, "pending_action": "report", "remark": "please report"},
        )
        assert r.status_code == 201, r.text
        h2 = w.login(api, "edu_off2")
        r = api.post(
            f"/cases/{case_id}/notes",
            headers=h2,
            data={"kind": "general", "body": "a note under aslms_app", "visibility": "case_scope"},
        )
        assert r.status_code == 201, r.text
        r = ds.upload(api, h2, case_id, sf.text_pdf())
        assert r.status_code == 201, r.text
        root = ds.login(api, "root")
        assert api.get("/admin/data-health", headers=root).status_code == 200
        assert api.get("/reports/pending-cases", headers=admin).status_code == 200
        audit = api.get("/audit", headers=root)
        assert audit.status_code == 200 and audit.json()["items"]

    # the event scan
    with AppSession() as s:
        alerts.scan_events(s, config=alerts.AlertConfig.from_settings(settings))
        s.commit()

    # a queue-runner pass: a dossier applied, its order PDFs stored
    gw, client, hc = napix
    gw.responses = [_order_router(gw)] * 10_000
    cnr = "GAHC010000000601"
    with AppSession() as s:
        queue.enqueue(s, FetchKind.DOSSIER, cnr, 30, lane=FetchLane.REQUEST)
        s.commit()
    run_settings = Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "store"),
        causelist_dir=str(tmp_path / "lists"),
        napix_rate_reserve=0,
        napix_live_reserve=0,
        napix_search_floor=0,
    )
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            runner = QueueRunner(
                AppSession,
                hc,
                settings=run_settings,
                store=LocalStore(run_settings.storage_dir),
                recorder=recorder,
                reserve=0,
            )
            # until the queue is empty: the court refresh the claim above queued (design ownership-refinements,
            # decision 1) and its order PDFs run too, besides the dossier asked for here and its order PDF
            return await runner.run(max_items=None, kinds=[FetchKind.DOSSIER, FetchKind.ORDER_PDF])

    rep = asyncio.run(go())
    assert rep.failed == 0 and rep.done >= 3, rep.items
    with AppSession() as s:
        fetched = s.scalar(sa.select(Case).where(Case.cnr == cnr))
        assert fetched is not None and fetched.last_full_refresh_at is not None
        stored = s.scalar(
            sa.select(sa.func.count())
            .select_from(Order)
            .join(Document, Document.id == Order.document_id)
            .where(Order.case_id == fetched.id)
        )
        assert stored == 3  # the three orders of the dossier

    # one run of the background storing of an advocate search's rows
    payload = sample("advocate_name_2026-10-18-p1.json")
    with AppSession() as s:
        rid = store_response(
            s,
            NapixResult(
                api="hc-advocate-name-api/advocatename",
                params_sha256="0" * 64,
                ok=True,
                data=payload,
                params={"est_code": "GAHC01", "advocate_name": "P J SAIKIA"},
            ),
        )
        queue.enqueue(s, FetchKind.SEARCH_ROWS, str(rid), 30, lane=FetchLane.REQUEST)
        s.commit()
    out = court_search.run_store_search_rows(AppSession)
    assert out == {"done": 1, "skipped": 0, "failed": 0}
    with AppSession() as s:
        row = queue.get_state(s, FetchKind.SEARCH_ROWS, str(rid))
        assert row.status == FetchStatus.DONE and row.result["stored"] == len(payload["casenos"])
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) >= 2
