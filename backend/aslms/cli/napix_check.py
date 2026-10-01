"""`aslms napix-check` — the live NAPIX test (CLAUDE.md current focus 1).

Walks the High Court APIs in dependency order, prints one line per call with the error family when a call
fails, saves every decrypted response under docs/specs/samples/<api>_<date>.json (PDFs as .pdf) and prints the
rate-limit headers. No credentials are written anywhere; the only key material shown is an 8-char fingerprint.
Run it with the master switch set for that run only:  NAPIX_ENABLED=true aslms napix-check --date 2026-09-03"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.base import CauseListRef
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.integration.napix.hc import API, NapixHighCourt

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "specs" / "samples"


def _save(samples: Path, name: str, res: NapixResult | None, stamp: str) -> str:
    if res is None:
        return "-"
    samples.mkdir(parents=True, exist_ok=True)
    if res.pdf:
        p = samples / f"{name}_{stamp}.pdf"
        p.write_bytes(res.pdf)
        return f"{p.name} ({len(res.pdf)} bytes)"
    if res.data is None:
        return "-"
    p = samples / f"{name}_{stamp}.json"
    p.write_text(
        json.dumps(res.data, indent=2, ensure_ascii=False, default=str), encoding="utf-8", newline="\n"
    )
    return p.name


def _shape(res: NapixResult | None) -> str:
    if res is None:
        return "-"
    if res.pdf:
        return f"pdf {len(res.pdf)} bytes"
    d = res.data
    if isinstance(d, dict):
        rows = nested_list(d)
        if rows:
            return f"{len(rows)} rows; keys {', '.join(list(rows[0])[:8])}"
        return "dict " + ", ".join(list(d)[:8]) + (" …" if len(d) > 8 else "")
    if isinstance(d, list):
        return f"list[{len(d)}]"
    return type(d).__name__


async def run(
    list_date: date,
    cnr: str | None,
    samples: Path,
    only: set[str] | None,
    max_benches: int,
    tag: str | None = None,
) -> int:
    s = get_settings()
    calls: list[NapixResult] = []
    stamp = tag or list_date.isoformat()
    table = Table(title=f"napix-check {list_date}", show_lines=False)
    for col in ("step", "api", "result", "ms", "shape / sample"):
        table.add_column(col)
    failures = 0
    ctx: dict[str, Any] = {"cnr": cnr}

    async with NapixClient.from_settings(on_call=calls.append) as client:
        hc = NapixHighCourt(client, s.napix_est_code, s.napix_state_code)
        console.print(
            f"NAPIX {s.napix_base_url}  dept_id={s.napix_dept_id}  est_code={s.napix_est_code}  "
            f"version={s.napix_version}  key fingerprint={client.crypto.fingerprint}  "
            f"hmac self-test={'PASS' if client.crypto.self_test() else 'FAIL'}"
        )

        async def step(
            name: str, api_key: str, fn: Callable[[], Awaitable[Any]], save_as: str | None = None
        ) -> Any:
            nonlocal failures
            if only and name not in only:
                return None
            before = len(calls)
            try:
                value = await fn()
                res = calls[-1] if len(calls) > before else None
                table.add_row(
                    name,
                    API[api_key],
                    "[green]ok[/green]",
                    str(res.duration_ms if res else "-"),
                    f"{_shape(res)} → {_save(samples, save_as or name, res, stamp)}",
                )
                return value
            except IntegrationError as e:
                res = calls[-1] if len(calls) > before else None
                failures += 1
                table.add_row(
                    name,
                    API[api_key],
                    f"[red]{type(e).__name__}[/red]",
                    str(res.duration_ms if res else "-"),
                    str(e.message)[:90],
                )
                return None

        await step("overview", "overview", hc.overview)
        await step("state_master", "state", hc.state_master)
        await step("district_master", "district", hc.district_master)
        await step("bench_master", "bench_master", hc.bench_master)
        ctypes = await step("case_type_master", "case_type", hc.case_type_master)
        await step("act_master", "act", hc.act_master)

        benches = (
            await step("causelist_bench", "causelist_bench", lambda: hc.causelist_benches(list_date)) or []
        )
        refs: list[CauseListRef] = []
        rows_seen: list[dict[str, Any]] = []
        for b in benches[:max_benches]:
            details = await step(
                "causelist_details",
                "causelist_details",
                lambda b=b: hc.causelist_details(list_date, b.bench_id),
                save_as=f"causelist_details_bench{b.bench_id}",
            )
            if details:
                rows_seen.extend(details)
                refs.extend(hc.causelist_refs(list_date, b.bench_id, details))
        if refs:
            ref = refs[0]
            await step(
                "show_causelist",
                "show_causelist",
                lambda: hc.show_causelist(ref),
                save_as=f"show_causelist_bench{ref.bench_id}",
            )
        if not ctx["cnr"]:
            for row in rows_seen:
                c = row.get("cino") or row.get("cnr")
                if c:
                    ctx["cnr"] = str(c).strip().upper()
                    break
        if ctx["cnr"]:
            cnr_ = ctx["cnr"]
            rec = await step("cnr", "cnr", lambda: hc.case_by_cnr(cnr_)) or {}
            await step("current_status", "current_status", lambda: hc.current_status([cnr_]))
            orders = nested_list(rec.get("interimorder")) + nested_list(rec.get("finalorder"))
            if orders and orders[0].get("order_no") and orders[0].get("order_date"):
                o = orders[0]
                od = date.fromisoformat(str(o["order_date"])[:10])
                await step("order", "order", lambda: hc.show_order(cnr_, str(o["order_no"]), od))
            hist = nested_list(rec.get("historyofcasehearing") or rec.get("history"))
            bd = next(
                (
                    h.get("business_date") or h.get("hearing_date")
                    for h in hist
                    if h.get("business_date") or h.get("hearing_date")
                ),
                None,
            )
            if bd:
                await step(
                    "show_business",
                    "show_business",
                    lambda: hc.show_business(cnr_, date.fromisoformat(str(bd)[:10])),
                )
            ct = (
                rec.get("case_type_id")
                or rec.get("case_type")
                or (ctypes[0].get("case_type") if ctypes else None)
            )
            if ct and rec.get("reg_no") and rec.get("reg_year"):
                await step(
                    "case_search",
                    "case_search",
                    lambda: hc.search_case_number(int(ct), int(rec["reg_no"]), int(rec["reg_year"])),
                )
            if rec.get("pet_name") and rec.get("reg_year"):
                pend = str(rec.get("pend_disp") or "P")[:1].upper()
                await step(
                    "party_name",
                    "party_name",
                    lambda: hc.search_party(str(rec["pet_name"])[:40], int(rec["reg_year"]), pend_disp=pend),
                )
        else:
            console.print(
                "[yellow]no CNR available (no details rows and --cnr not given): case APIs skipped[/yellow]"
            )

    console.print(table)
    limit, remaining = calls[-1].rate_limit if calls else (None, None)
    console.print(
        f"{len(calls)} calls, {failures} failed; rate limit: limit={limit} remaining={remaining}; samples in {samples}"
    )
    return failures


def napix_check(
    date_: str = typer.Option(None, "--date", help="cause-list date, YYYY-MM-DD (default: yesterday)"),
    cnr: str = typer.Option(None, help="a CNR to use for the case APIs when the details rows give none"),
    samples: Path = typer.Option(DEFAULT_SAMPLES, help="where decrypted samples are written"),
    only: str = typer.Option(None, help="comma-separated step names to run"),
    max_benches: int = typer.Option(3, help="benches to query Cause List Details for"),
    tag: str = typer.Option(None, help="sample file suffix instead of the date (e.g. pending-case)"),
) -> None:
    """Live NAPIX test: walks the High Court APIs and saves the decrypted responses as samples."""
    from aslms.cli.main import parse_cli_date

    s = get_settings()
    if not s.napix_enabled:
        raise typer.Exit(
            "NAPIX_ENABLED is false; set it for this run only: NAPIX_ENABLED=true aslms napix-check"
        )
    d = parse_cli_date(date_) or (date.today() - timedelta(days=1))
    failures = asyncio.run(run(d, cnr, samples, set(only.split(",")) if only else None, max_benches, tag))
    raise typer.Exit(code=1 if failures else 0)
