"""`aslms napix-check` logs every call (design `search-court-advocate-filing`, decision 2): a run against the
scripted gateway leaves one `napix_call_log` row per attempt, with no user and no lane, and each JSON answer in
`napix_responses`; the rows are written also when the run breaks part-way."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import httpx
import pytest
from sqlalchemy import text

import aslms.db.session as db_session
from aslms.cli.napix_check import Probe, run
from aslms.integration.napix.client import CallHook, NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from tests.db.conftest import router, wipe
from tests.unit.conftest import KEY, Gateway


@pytest.fixture()
def db(clean_db, engine, monkeypatch):
    """`session_scope` on the test database (the command's default check and flush use it); wiped afterwards."""

    @contextmanager
    def scope(url=None):
        s = clean_db()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(db_session, "session_scope", scope)
    yield clean_db
    with engine.begin() as conn:
        wipe(conn)


def _factory(gw: Gateway):
    def make(hook: CallHook) -> NapixClient:
        return NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gw.handle),
            on_call=hook,
            backoff_base=0.0,
        )

    return make


def _log(Session) -> list[tuple]:
    with Session() as s:
        return s.execute(
            text(
                "SELECT api, ok, napix_status, http_status, user_id, lane FROM napix_call_log ORDER BY called_at"
            )
        ).all()


async def test_every_attempt_is_logged_without_user_or_lane(db, tmp_path) -> None:
    gw = Gateway(NapixCrypto(KEY))
    handle = router(gw)
    # the master answers after one gateway 503 (a retried attempt); the advocate search answers 628
    gw.responses = [lambda p, q, r: httpx.Response(503), handle, lambda p, q, r: gw.encrypted_status(628)]
    failures = await run(
        date(2026, 10, 17),
        None,
        tmp_path,
        {"case_type_master", "advocate_name"},
        1,
        "t",
        probe=Probe(advocate="A I KATHAR", reg_year=2025),
        client_factory=_factory(gw),
    )
    assert failures == 1  # the advocate search answered 628
    rows = _log(db)
    assert [(r.api, r.ok, r.http_status) for r in rows] == [
        ("hc-case-type-master-api/casetypemaster", False, 503),
        ("hc-case-type-master-api/casetypemaster", True, 200),
        ("hc-advocate-name-api/advocatename", False, 200),
    ]
    assert rows[2].napix_status == 628
    assert all(r.user_id is None and r.lane is None for r in rows)
    assert len(rows) == len(gw.seen)
    with db() as s:
        stored = s.execute(text("SELECT api FROM napix_responses")).scalars().all()
    assert stored == ["hc-case-type-master-api/casetypemaster"]


async def test_calls_are_logged_when_the_run_breaks(db, tmp_path) -> None:
    gw = Gateway(NapixCrypto(KEY))

    def boom(p, q, r):
        raise RuntimeError("transport broke")

    gw.responses = [router(gw), boom]
    with pytest.raises(RuntimeError):
        await run(
            date(2026, 10, 17),
            None,
            tmp_path,
            {"case_type_master", "filing"},
            1,
            "t",
            probe=Probe(filing_type=111, fil_no=7451, fil_year=2026),
            client_factory=_factory(gw),
        )
    rows = _log(db)
    assert [(r.api, r.ok) for r in rows] == [
        ("hc-case-type-master-api/casetypemaster", True),
        ("hc-filing-api/Filing", False),
    ]
