"""`aslms napix-probe-rate` — measure the gateway's rate-limit window.

Sends cheap Overview calls at a fixed interval and prints `X-RateLimit-Remaining` after each one. The remaining
count falls by one per call; the moment it jumps back up marks the window boundary. The call log and the notes
(docs/napix_integration_notes.md §6) take the measured value; `NAPIX_RATE_WINDOW_SECONDS` is set from it."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import typer
from rich.console import Console

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.napix.client import NapixClient, NapixResult
from aslms.integration.napix.hc import API

console = Console()


async def run(calls: int, interval: float) -> None:
    results: list[NapixResult] = []
    async with NapixClient.from_settings(on_call=results.append) as client:
        prev: int | None = None
        started = time.monotonic()
        for i in range(calls):
            try:
                res = await client.call(API["overview"])
                limit, remaining = res.rate_limit
            except IntegrationError as e:
                console.print(
                    f"{i + 1:3d}  {datetime.now():%H:%M:%S}  [red]{type(e).__name__}: {e.message[:80]}[/red]"
                )
                limit, remaining = None, None
            elapsed = int(time.monotonic() - started)
            jump = ""
            if prev is not None and remaining is not None and remaining > prev - 1:
                jump = f"  [green]<-- counter reset (+{remaining - prev + 1}) after {elapsed}s[/green]"
            console.print(
                f"{i + 1:3d}  {datetime.now():%H:%M:%S}  +{elapsed:4d}s  limit={limit} remaining={remaining}{jump}"
            )
            prev = remaining
            if i + 1 < calls:
                await asyncio.sleep(interval)


def napix_probe_rate(
    calls: int = typer.Option(30, help="number of Overview calls to make"),
    interval: float = typer.Option(20.0, help="seconds between calls"),
) -> None:
    """Measure the NAPIX rate-limit window by watching X-RateLimit-Remaining over time."""
    if not get_settings().napix_enabled:
        raise typer.Exit("NAPIX_ENABLED is false; set it for this run only")
    console.print(f"{calls} Overview calls, one every {interval:.0f}s ({calls * interval / 60:.0f} min)")
    asyncio.run(run(calls, interval))
