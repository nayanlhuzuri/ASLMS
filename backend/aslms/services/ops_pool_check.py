"""`aslms ops pool-check` (design `followups-oct`, decision 5b): a read-only load check of the connection budget
through PgBouncer, run next to the running stack (`docker compose exec api aslms ops pool-check`).

It builds the engines exactly as `api` does, from the same settings (`db.session.get_engine` and `get_apart_engine`),
in its own process, and simulates a burst of court searches:
- `holders` sessions that open a transaction and sleep inside it (`SELECT pg_sleep(seconds)`), as a request waiting on
  NAPIX does (default `NAPIX_REQUEST_SLOTS + 2`);
- `pages` short transactions per second on the main engine (`SELECT 1`), the other pages of the portal;
- `apart` apart-style transactions on the apart engine (`SELECT 1`, committed), spread over the run.
It writes no row and changes no data, so it writes no audit row. The result: the counts, the p50 and maximum wait for
an apart connection, the maximum wait for a page connection, timeouts and other errors. It fails (exit 1) when any
apart wait exceeds `APART_LIMIT_MS` or any timeout or error occurs."""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import TimeoutError as PoolTimeout

APART_LIMIT_MS = 1000


@dataclass
class _Tally:
    lock: threading.Lock = field(default_factory=threading.Lock)
    apart_ms: list[float] = field(default_factory=list)
    page_ms: list[float] = field(default_factory=list)
    holders_done: int = 0
    timeouts: int = 0
    errors: dict[str, int] = field(default_factory=dict)

    def failed(self, exc: BaseException) -> None:
        with self.lock:
            if isinstance(exc, PoolTimeout) or "timeout" in type(exc).__name__.lower():
                self.timeouts += 1
            else:  # the class only: a driver message may carry the URL
                name = type(exc).__name__
                self.errors[name] = self.errors.get(name, 0) + 1


def _timed(engine: Engine, into: list[float], tally: _Tally) -> None:
    start = time.monotonic()
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — counted, the check goes on
        tally.failed(exc)
        return
    with tally.lock:
        into.append((time.monotonic() - start) * 1000)


def _hold(engine: Engine, seconds: float, started: threading.Barrier, tally: _Tally) -> None:
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SELECT 1"))
            started.wait(timeout=30)
            conn.execute(text("SELECT pg_sleep(:s)"), {"s": seconds})
    except Exception as exc:  # noqa: BLE001
        tally.failed(exc)
        return
    with tally.lock:
        tally.holders_done += 1


def _spaced(n: int, seconds: float, fn, pool: ThreadPoolExecutor, t0: float) -> list:
    futures = []
    for i in range(n):
        at = t0 + seconds * i / max(n, 1)
        delay = at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        futures.append(pool.submit(fn))
    return futures


def run(
    main: Engine,
    apart: Engine,
    *,
    holders: int,
    pages: int,
    apart_n: int,
    seconds: float,
) -> dict[str, Any]:
    """The check itself, on the given engines (the CLI passes the api's)."""
    tally = _Tally()
    started = threading.Barrier(holders + 1) if holders else None
    hold_threads = [
        threading.Thread(target=_hold, args=(main, seconds, started, tally), daemon=True)
        for _ in range(holders)
    ]
    for t in hold_threads:
        t.start()
    if started is not None:
        try:
            started.wait(timeout=30)  # every holder is inside its transaction
        except threading.BrokenBarrierError:
            pass
    t0 = time.monotonic()
    page_total = int(pages * seconds)
    with ThreadPoolExecutor(max_workers=32) as pool:
        feeder = threading.Thread(
            target=lambda: _spaced(page_total, seconds, lambda: _timed(main, tally.page_ms, tally), pool, t0),
            daemon=True,
        )
        feeder.start()
        _spaced(apart_n, seconds, lambda: _timed(apart, tally.apart_ms, tally), pool, t0)
        feeder.join()
    for t in hold_threads:
        t.join(timeout=seconds + 60)
    apart_ms = sorted(tally.apart_ms)
    out = {
        "holders": holders,
        "holders_done": tally.holders_done,
        "pages": len(tally.page_ms),
        "apart": len(apart_ms),
        "apart_wait_p50_ms": round(statistics.median(apart_ms), 1) if apart_ms else None,
        "apart_wait_max_ms": round(apart_ms[-1], 1) if apart_ms else None,
        "page_wait_max_ms": round(max(tally.page_ms), 1) if tally.page_ms else None,
        "timeouts": tally.timeouts,
        "errors": tally.errors,
        "seconds": seconds,
    }
    out["ok"] = (
        tally.timeouts == 0
        and not tally.errors
        and (not apart_ms or apart_ms[-1] <= APART_LIMIT_MS)
        and len(apart_ms) == apart_n
    )
    return out
