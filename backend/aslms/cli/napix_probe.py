"""`aslms napix-probe-rate` — measure the gateway's rate-limit window.

Sends cheap Overview calls at a fixed interval and prints `X-RateLimit-Remaining` after each one. The remaining
count falls by one per call; the moment it jumps back up marks the window boundary. Run it across a whole window:
the reset is at a fixed minute of the hour, not on the clock hour, and the 1 Oct run ended before it came (notes
§6, design `napix-window`). The workers do not use this command: they detect the window from the call log.

Every attempt is logged (design `court-data-freshness`, decision 22): the command refuses to start without the call
log (`napix_store.require_call_log`), and each attempt is committed to `napix_call_log` on its own as it happens (lane,
user and job NULL, as an operator's command), so a long probe shows in the call log while it runs and its readings join
the quota-window detection. When a write fails, no further call is made and the command exits with code 1. Times are
shown in IST."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

import typer
from rich.console import Console

from aslms.core.clock import IST
from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import API
from aslms.services.napix_store import CallLogUnavailable, NapixRecorder, require_call_log

console = Console()
COMMAND = "napix-probe-rate"


class RecordFailed(RuntimeError):
    """An attempt could not be written to the call log: the probe stops before the next call."""


def _client_from_settings(hook) -> NapixClient:
    return NapixClient.from_settings(on_call=hook)


async def run(
    calls: int,
    interval: float,
    *,
    client_factory: Callable | None = None,
    recorder: NapixRecorder | None = None,
    check_db: Callable[[str], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """The probe; returns the number of attempts recorded. Raises `CallLogUnavailable` before any call when the call
    log cannot be reached, and `RecordFailed` (after the failed attempt, before the next call) when a write fails."""
    (check_db or require_call_log)(COMMAND)
    if recorder is None:
        from aslms.db.session import get_sessionmaker

        recorder = NapixRecorder(session_factory=get_sessionmaker())
    if recorder.session_factory is None:
        raise ValueError("the probe's recorder commits every attempt apart: give it a session factory")
    recorded = 0
    async with (client_factory or _client_from_settings)(recorder.on_call) as client:
        prev: int | None = None
        started = time.monotonic()
        for i in range(calls):
            try:
                res = await client.call(API["overview"])
                limit, remaining = res.rate_limit
            except IntegrationError as e:
                console.print(
                    f"{i + 1:3d}  {datetime.now(IST):%H:%M:%S}  [red]{type(e).__name__}: {e.message[:80]}[/red]"
                )
                limit, remaining = None, None
            try:
                recorded += recorder.flush_apart(recorder.session_factory)
            except Exception as exc:  # noqa: BLE001 — the recorder's warning names the attempt's non-secret fields
                console.print(
                    f"[red]the call log could not be written ({type(exc).__name__}); stopping[/red]"
                )
                raise RecordFailed(f"call log write failed after {recorded} recorded attempt(s)") from None
            elapsed = int(time.monotonic() - started)
            jump = ""
            if prev is not None and remaining is not None and remaining > prev - 1:
                jump = f"  [green]<-- counter reset (+{remaining - prev + 1}) after {elapsed}s[/green]"
            console.print(
                f"{i + 1:3d}  {datetime.now(IST):%H:%M:%S} IST  +{elapsed:4d}s  limit={limit} "
                f"remaining={remaining}{jump}"
            )
            prev = remaining
            if i + 1 < calls:
                await sleep(interval)
    return recorded


def napix_probe_rate(
    calls: int = typer.Option(30, help="number of Overview calls to make"),
    interval: float = typer.Option(20.0, help="seconds between calls"),
) -> None:
    """Measure the NAPIX rate-limit window by watching X-RateLimit-Remaining over time; every call is logged."""
    if not get_settings().napix_enabled:
        raise typer.Exit("NAPIX_ENABLED is false; set it for this run only")
    console.print(f"{calls} Overview calls, one every {interval:.0f}s ({calls * interval / 60:.0f} min)")
    try:
        recorded = asyncio.run(run(calls, interval))
    except CallLogUnavailable as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    except RecordFailed as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"{recorded} attempt(s) recorded in napix_call_log")
