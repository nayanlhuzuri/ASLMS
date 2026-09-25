"""`aslms napix-check` — the live NAPIX test the plan puts first.

Walks the High Court APIs in dependency order, prints one line per call, and saves every decrypted response
under docs/specs/napix/hc/samples/ so the real field names can be reviewed and the open points in the
decisions log answered (Cause List Details shape, est_code, key mode, PDF transport, nested keys).
No credentials are ever written to the samples; the only key material shown is an 8-char fingerprint."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError, SourceNotFound
from aslms.core.time import parse_date
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.integration.napix.crypto import KNOWN_ANSWER_TOKEN
from aslms.integration.napix.hc import API, NapixHighCourt

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "specs" / "napix" / "hc" / "samples"


def _save(samples: Path, name: str, res: NapixResult) -> str:
    samples.mkdir(parents=True, exist_ok=True)
    if res.pdf:
        p = samples / f"{name}.pdf"
        p.write_bytes(res.pdf)
        return f"{p.name} ({len(res.pdf)} bytes)"
    p = samples / f"{name}.json"
    p.write_text(json.dumps(res.data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return p.name


def _shape(data: Any) -> str:
    if isinstance(data, dict):
        keys = list(data)[:8]
        return "dict " + ", ".join(keys) + (" …" if len(data) > 8 else "")
    if isinstance(data, list):
        return f"list[{len(data)}]"
    return type(data).__name__


async def run(list_date: date, cnr: str | None, samples: Path, only: set[str] | None) -> int:
    settings = get_settings()
    calls: list[NapixResult] = []
    client = NapixClient.from_settings(on_call=calls.append)
    hc = NapixHighCourt(client, settings.napix_hc_est_code, settings.napix_state_code)
    console.print(
        f"NAPIX {settings.napix_base}  dept_id={settings.napix_dept_id}  version={settings.napix_version}  "
        f"key fingerprint={client.crypto.fingerprint} mode={settings.napix_auth_key_mode}  "
        f"hash self-test={'PASS' if client.crypto.self_test() else 'FAIL (expected ' + KNOWN_ANSWER_TOKEN[:8] + '…)'}"
    )
    table = Table(title=f"napix-check {list_date}", show_lines=False)
    for col in ("step", "api", "result", "ms", "shape / file"):
        table.add_column(col)
    failures = 0
    ctx: dict[str, Any] = {"cnr": cnr}

    async def step(name: str, coro_factory, api_key: str, save_as: str | None = None):
        nonlocal failures
        if only and name not in only:
            return None
        before = len(calls)
        try:
            value = await coro_factory()
            res = calls[-1] if len(calls) > before else None
            shape = _shape(res.data) if res and res.data is not None else ("pdf" if res and res.pdf else "-")
            file = _save(samples, save_as or name, res) if res else "-"
            table.add_row(
                name,
                API[api_key],
                "[green]ok[/green]",
                str(res.duration_ms if res else 0),
                f"{shape} → {file}",
            )
            return value
        except SourceNotFound as e:
            res = calls[-1] if len(calls) > before else None
            table.add_row(
                name, API[api_key], "[yellow]not found[/yellow]", str(res.duration_ms if res else 0), str(e)
            )
            return None
        except IntegrationError as e:
            failures += 1
            res = calls[-1] if len(calls) > before else None
            table.add_row(
                name, API[api_key], "[red]error[/red]", str(res.duration_ms if res else 0), str(e)[:120]
            )
            return None

    await step("overview", hc.overview, "overview")
    states = await step("state", hc.state_master, "state")
    if states:
        ctx["states"] = [(s.get("state_code"), s.get("state_name") or s.get("name")) for s in states][:40]
    benches = await step("bench_master", hc.bench_master, "bench")
    if benches:
        ctx["est_codes"] = sorted({str(b.get("est_code")) for b in benches if b.get("est_code")})
    await step("case_type_master", hc.case_type_master, "case_type")

    cl_benches = await step("causelist_bench", lambda: hc.causelist_benches(list_date), "causelist_bench")
    first_bench = cl_benches[0].bench_id if cl_benches else None
    refs = None
    if first_bench:
        refs = await step(
            "causelist_details", lambda: hc.causelists_for_bench(list_date, first_bench), "causelist_details"
        )
    if refs:
        ref = refs[0]
        ctx["details_returns_rows"] = bool(ref.raw.get("rows")) if isinstance(ref.raw, dict) else False
        if ref.causelist_id:
            await step("show_causelist", lambda: hc.causelist_pdf(ref), "show_causelist")

    record = None
    if cnr:
        record = await step("cnr", lambda: hc.case_by_cnr(cnr), "cnr")
        await step("current_status", lambda: hc.current_status([cnr]), "current_status")
    if record:
        if record.hearings:
            bd = None
            for h in record.hearings:
                bd = parse_date(h.get("business_date") or h.get("hearing_date") or h.get("date"))
                if bd:
                    break
            if bd:
                await step("show_business", lambda: hc.business(cnr, bd), "show_business")
        if record.orders:
            o = next((o for o in record.orders if o.order_date), None)
            if o:
                await step("order", lambda: hc.order_pdf(cnr, o), "order")

    console.print(table)
    summary = {
        "list_date": list_date.isoformat(),
        "calls": len(calls),
        "failures": failures,
        "token_verified": [c.token_verified for c in calls if c.token_verified is not None],
        "est_codes_seen": ctx.get("est_codes"),
        "states_seen": ctx.get("states"),
        "details_returns_rows": ctx.get("details_returns_rows"),
    }
    (samples / "_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    console.print(f"samples written to {samples}")
    console.print(json.dumps(summary, indent=2, default=str))
    return 1 if failures else 0


def napix_check(
    list_date: str = typer.Option(None, "--date", help="Cause-list date YYYY-MM-DD (default: tomorrow)"),
    cnr: str = typer.Option(
        None, "--cnr", help="A CNR/CINO to exercise CNR, status, business and order APIs"
    ),
    samples: Path = typer.Option(DEFAULT_SAMPLES, "--samples", help="Where to write decrypted samples"),
    only: str = typer.Option(None, "--only", help="Comma-separated step names to run"),
) -> None:
    """Live NAPIX test: walks the HC APIs and saves each decrypted response shape."""
    d = date.fromisoformat(list_date) if list_date else date.today() + timedelta(days=1)
    steps = {s.strip() for s in only.split(",")} if only else None
    code = asyncio.run(run(d, cnr, samples, steps))
    raise typer.Exit(code)


def nested_preview(data: Any, n: int = 3) -> list[dict[str, Any]]:
    return nested_list(data)[:n]
