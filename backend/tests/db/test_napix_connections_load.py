"""The connection budget of the NAPIX request paths (design `followups-oct`, decisions 1 to 5), against the scripted
gateway (never live NAPIX).

The app is built with a deliberately tiny main pool (3 connections, no overflow, a 3 s pool timeout), an apart pool of
1, 2 request slots and a 2 s slot wait, and 12 court searches are fired at once from threads, four times the pool.
Every gateway call is held on a `threading.Barrier`, so the calls really overlap. With the fix every request ends in
200 or 503 `napix_busy`, every call has its row and no "napix call rows could not be written" warning is logged. The
control runs the old wiring (the apart writes on the main pool, 99 slots) and must starve: the pool timeout and the
warning document why the fix exists and fail this file if the cycle ever comes back."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from aslms.api import deps
from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.ops import NapixCallLog
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import court_search, napix_store
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS
from tests.unit.conftest import KEY, Gateway

JWT = "test-secret-of-at-least-thirty-two-characters"
SEARCH = {"kind": "party", "name": "JANIFA", "reg_year": 2024}
REQUESTS = 12
WARNING = "napix call rows could not be written"


class HeldGateway:
    """The scripted gateway; every API call waits on a barrier of `parties` (so that many calls overlap) and answers
    status 628 (not found), which the party search turns into a 200 with no rows and nothing to store."""

    def __init__(self, parties: int, barrier_timeout: float) -> None:
        self.gw = Gateway(NapixCrypto(KEY))
        self.barrier = threading.Barrier(parties)
        self.barrier_timeout = barrier_timeout
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.gw.responses = [self._answer] * 1000

    def _answer(self, path, q, request):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self.barrier.wait(timeout=self.barrier_timeout)
        except threading.BrokenBarrierError:  # a call with no partner left: carry on, mend the barrier
            with self._lock:
                if self.barrier.broken:
                    self.barrier.reset()
        finally:
            with self._lock:
                self.in_flight -= 1
        return self.gw.encrypted_status(628)

    def factory(self):
        client = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(self.gw.handle),
            backoff_base=0.0,
        )
        return client, NapixHighCourt(client, "GAHC01", "18")


@pytest.fixture()
def switch_on(monkeypatch):
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))


@pytest.fixture()
def warnings(monkeypatch):
    seen: list[str] = []
    real = napix_store.log.warning

    def record(event, *args, **kwargs):
        seen.append(event)
        return real(event, *args, **kwargs)

    monkeypatch.setattr(napix_store.log, "warning", record)
    return seen


@pytest.fixture()
def tiny(world, migrated):
    """The tiny main pool and the apart pool of one, both over the test database; disposed after the test."""
    main = sa.create_engine(migrated, pool_size=3, max_overflow=0, pool_timeout=3, pool_pre_ping=True)
    apart = sa.create_engine(migrated, pool_size=1, max_overflow=0, pool_timeout=3, pool_pre_ping=True)
    yield main, apart
    main.dispose()
    apart.dispose()


def _app(main, apart, *, slots: int, wait: int, gateway: HeldGateway, **settings_kw) -> TestClient:
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret=JWT,
        aslms_access_token_minutes=5,
        redis_url=None,
        napix_request_slots=slots,
        napix_request_wait_seconds=wait,
        **settings_kw,
    )
    main_factory = sessionmaker(bind=main, expire_on_commit=False, autoflush=False)
    apart_factory = sessionmaker(bind=apart, expire_on_commit=False, autoflush=False) if apart else None
    app = create_app(settings, main_factory, apart_factory)
    app.state.napix_factory = gateway.factory
    return TestClient(app, raise_server_exceptions=False)


def _fire(client: TestClient, headers: dict, n: int = REQUESTS) -> list[tuple[int, dict, float]]:
    barrier = threading.Barrier(n)

    def one(_):
        barrier.wait(timeout=30)
        start = time.monotonic()
        r = client.post("/cases/search-court", json=SEARCH, headers=headers)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return r.status_code, body, time.monotonic() - start

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(one, range(n)))


def _count(world, model) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.select(sa.func.count()).select_from(model)) or 0)


def test_twelve_searches_on_a_pool_of_three_lose_no_call_row(world, tiny, switch_on, warnings):
    main, apart = tiny
    gateway = HeldGateway(parties=2, barrier_timeout=1.0)
    with _app(main, apart, slots=2, wait=2, gateway=gateway) as client:
        headers = bearer(client, USERS["edu_admin"][0], PW)
        results = _fire(client, headers)
    codes = sorted(code for code, _, _ in results)
    assert all(
        code == 200 or (code == 503 and body["detail"]["code"] == "napix_busy") for code, body, _ in results
    ), codes
    assert codes.count(200) >= 2, codes
    assert max(elapsed for _, _, elapsed in results) < 30
    assert len(gateway.gw.seen) >= 2 and gateway.max_in_flight == 2, "the calls overlapped, two at a time"
    assert _count(world, NapixCallLog) == len(gateway.gw.seen), "every call has its row"
    assert WARNING not in warnings
    # No assertion on the main pool's checked-out count: the pool has 3 connections and no overflow, so that count
    # can never pass 3. The proof that no request holds a connection while it waits for a slot or calls is above:
    # every request ended in 200 or 503 within the 3 s pool timeout, where a starved pool answers 500 (the control
    # below), and `test_slot_refuses_a_session_that_has_written` checks the connection is given back.
    # one audit row per answered search, none for a busy refusal
    with world.Session() as s:
        audits = s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == "case.search_court")
        )
    assert audits == codes.count(200)


def test_old_wiring_starves_and_warns(world, tiny, switch_on, warnings):
    """The control: the apart writes on the main pool and no bound on the requests waiting on NAPIX. Three calls
    meet at the barrier, each holding one of the three connections, and each flush waits for a fourth."""
    main, _apart = tiny
    gateway = HeldGateway(parties=3, barrier_timeout=10.0)
    with _app(main, None, slots=30, wait=2, gateway=gateway) as client:
        client.app.state.napix_slots = threading.BoundedSemaphore(99)  # beyond the setting's range: no bound
        headers = bearer(client, USERS["edu_admin"][0], PW)
        results = _fire(client, headers)
    assert WARNING in warnings, "the old wiring loses call rows"
    assert any(code == 500 for code, _, _ in results)
    assert _count(world, NapixCallLog) < len(gateway.gw.seen)


def test_busy_answers_503_after_the_wait_and_writes_nothing(world, tiny, switch_on):
    main, apart = tiny
    gateway = HeldGateway(parties=1, barrier_timeout=1.0)
    with _app(main, apart, slots=1, wait=1, gateway=gateway) as client:
        headers = bearer(client, USERS["edu_admin"][0], PW)
        client.app.state.napix_slots.acquire()  # every slot in use
        start = time.monotonic()
        r = client.post("/cases/search-court", json=SEARCH, headers=headers)
        elapsed = time.monotonic() - start
        client.app.state.napix_slots.release()
    assert r.status_code == 503 and r.headers["retry-after"] == "15"
    assert r.json()["detail"] == {
        "code": "napix_busy",
        "message": "Court searches are busy; try again in a few seconds.",
        "retry_after": 15,
    }
    assert elapsed >= 1.0, "it waited for a slot first"
    assert gateway.gw.seen == [] and _count(world, NapixCallLog) == 0
    with world.Session() as s:
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("case.%")))
            == 0
        )
        user = world.user(s, "edu_admin")
        assert court_search.user_searches_last_hour(s, user)[0] == 0, (
            "not counted against the hourly searches"
        )


class SignallingSlots:
    """A slot semaphore that says when a request has started waiting on it."""

    def __init__(self) -> None:
        self.sem = threading.BoundedSemaphore(1)
        self.waiting = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        self.waiting.set()
        return self.sem.acquire(blocking, timeout) if blocking else self.sem.acquire(False)

    def release(self) -> None:
        self.sem.release()


def test_guard_runs_again_after_the_slot(world, tiny, switch_on):
    """The person's hourly count reaches the limit while the request waits for its slot: the guard taken again inside
    the slot refuses (429 `search_limit`) with no call."""
    main, apart = tiny
    gateway = HeldGateway(parties=1, barrier_timeout=1.0)
    with _app(main, apart, slots=1, wait=10, gateway=gateway, napix_search_per_user_hour=1) as client:
        headers = bearer(client, USERS["edu_admin"][0], PW)
        slots = SignallingSlots()
        slots.sem.acquire()  # in use by "another request"
        client.app.state.napix_slots = slots
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/cases/search-court", json=SEARCH, headers=headers)
            assert slots.waiting.wait(timeout=20), "the request reached the slot"
            with world.Session() as s:  # a search of this person committed meanwhile
                s.add(
                    AuditLog(
                        actor_user_id=world.user(s, "edu_admin").id,
                        action="case.search_court",
                        entity_type="napix_search",
                        after={"calls": 1},
                    )
                )
                s.commit()
            slots.release()
            r = future.result(timeout=30)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "search_limit"
    assert gateway.gw.seen == [] and _count(world, NapixCallLog) == 0


def test_slot_refuses_a_session_that_has_written(world):
    """Giving the connection back commits the request transaction, so a write at that point is a defect, never a
    silent commit: unflushed objects and a flushed row both raise `RuntimeError`, and no slot is taken."""
    slots = threading.BoundedSemaphore(1)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                napix_slots=slots,
                settings=Settings(_env_file=None, napix_request_wait_seconds=0),
                napix_factory=lambda: pytest.fail("no client is built"),
            )
        )
    )
    with world.Session() as s:
        s.add(AuditLog(action="test.pending", entity_type="test", after={}))
        with pytest.raises(RuntimeError, match="unflushed"):
            with deps.napix_request(request, s):
                pass
        s.flush()  # now written in the transaction
        with pytest.raises(RuntimeError, match="has written"):
            with deps.napix_request(request, s):
                pass
        s.rollback()
    assert slots.acquire(blocking=False), "the slot was never taken"
    slots.release()
    request.app.state.napix_factory = lambda: ("client", "hc")
    with world.Session() as s:  # a read-only session gives its connection back, then takes the slot
        s.execute(sa.text("SELECT 1"))
        with deps.napix_request(request, s) as pair:
            assert pair == ("client", "hc")
            assert not s.in_transaction(), "no connection held while waiting or calling"
            assert not slots.acquire(blocking=False), "the slot is held inside the block"
    assert slots.acquire(blocking=False), "and released after it"
