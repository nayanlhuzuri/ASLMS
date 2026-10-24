"""`aslms napix-check` — the live NAPIX test (CLAUDE.md current focus 1).

Walks the High Court APIs in dependency order, prints one line per call with the error family when a call
fails, saves every decrypted response under docs/specs/samples/<api>_<date>.json (PDFs as .pdf) and prints the
rate-limit headers.

Every attempt, retries included, goes through a `NapixRecorder` (no user, no lane) and is written to
`napix_call_log` and `napix_responses` at the end of the run, also when the run fails part-way; the command
refuses to start when it cannot reach the database, so no call is ever unlogged (design
`search-court-advocate-filing`, decision 2). The Search by Advocate Name and Search by Filing Number steps run
only when their inputs are given, and `--max-calls N` starts no new step once N attempts have been made, e.g.
`aslms napix-check --only advocate_name --advocate "MR. A I KATHAR" --reg-year 2025 --pend P --max-calls 2
--tag 2026-10-18-full` or `aslms napix-check --only filing --filing-type 111 --fil-no 7451 --fil-year 2026
--max-calls 2`, each with the master switch set for that run only. No credentials are written anywhere; the only key material shown is an 8-char fingerprint.
Run it with the master switch set for that run only:  NAPIX_ENABLED=true aslms napix-check --date 2026-09-03"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from aslms.core.clock import today_ist
from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.base import CauseListRef
from aslms.integration.napix.client import CallHook, NapixClient, NapixResult, nested_list
from aslms.integration.napix.hc import API, NapixHighCourt
from aslms.services.napix_store import CallLogUnavailable, NapixRecorder, require_call_log

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "specs" / "samples"
MAX_FIL_NO = 9_999_999  # spec §6.6: up to 7 digits
CASE_STEPS = frozenset({"cnr", "current_status", "order", "show_business", "case_search", "party_name"})


@dataclass(frozen=True)
class Probe:
    """The inputs of the two search steps (design `search-court-advocate-filing`, decision 1). With an advocate,
    `reg_year=None` sends an empty year (probe P2)."""

    advocate: str | None = None
    reg_year: int | None = None
    pend: str = "P"
    filing_type: int | None = None
    fil_no: int | None = None
    fil_year: int | None = None


def probe_from_options(
    advocate: str | None,
    reg_year: str | None,
    pend: str | None,
    filing_type: int | None,
    fil_no: int | None,
    fil_year: int | None,
) -> Probe:
    """The command's options checked before any call: an advocate needs `--reg-year YEAR` or `--reg-year blank`
    (an empty year is never sent by accident); the filing step needs all three of its values."""
    year: int | None = None
    if advocate is not None:
        advocate = advocate.strip()
        if not 3 <= len(advocate) <= 99:
            raise typer.BadParameter("--advocate is 3 to 99 characters")
        if reg_year is None:
            raise typer.BadParameter("--advocate needs --reg-year YEAR, or --reg-year blank to send no year")
        y = reg_year.strip().lower()
        if y != "blank":
            if not (y.isdigit() and len(y) == 4):
                raise typer.BadParameter("--reg-year is a 4-digit year or 'blank'")
            year = int(y)
    elif reg_year is not None:
        raise typer.BadParameter("--reg-year goes with --advocate")
    p = (pend or "P").strip().upper()
    if p not in ("P", "D"):
        raise typer.BadParameter("--pend is P or D")
    if filing_type is None and fil_no is None and fil_year is None:
        return Probe(advocate, year, p)
    if filing_type is None or fil_no is None or fil_year is None:
        raise typer.BadParameter("the filing step needs --filing-type, --fil-no and --fil-year together")
    if filing_type < 1:
        raise typer.BadParameter("--filing-type is the case-type master's numeric code")
    if not 1 <= fil_no <= MAX_FIL_NO:
        raise typer.BadParameter(f"--fil-no is 1 to {MAX_FIL_NO}")
    if not 1000 <= fil_year <= 9999:
        raise typer.BadParameter("--fil-year is a 4-digit year")
    return Probe(advocate, year, p, filing_type, fil_no, fil_year)


def database_ready() -> None:
    """Before the first call: the call log must be reachable, or the run would make unlogged calls
    (`napix_store.require_call_log`, shared with `napix-probe-rate`)."""
    require_call_log("napix-check")


def record_calls(recorder: NapixRecorder) -> int:
    """Writes every attempt of the run to `napix_call_log` (and each JSON answer to `napix_responses`)."""
    from aslms.db.session import session_scope

    with session_scope() as session:
        return recorder.flush(session)


def _client_from_settings(hook: CallHook) -> NapixClient:
    return NapixClient.from_settings(on_call=hook)


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
    *,
    probe: Probe | None = None,
    max_calls: int | None = None,
    client_factory: Callable[[CallHook], NapixClient] | None = None,
    check_db: Callable[[], None] | None = None,
    record: Callable[[NapixRecorder], int] | None = None,
) -> int:
    """Returns the number of failed steps. Raises `CallLogUnavailable` before any call when the database cannot
    be reached; every attempt is recorded (`record`, by default into the database) even if the run fails."""
    s = get_settings()
    probe = probe or Probe()
    (check_db or database_ready)()
    calls: list[NapixResult] = []
    recorder = NapixRecorder()  # no user, no lane: an operator's command

    def hook(result: NapixResult) -> None:
        calls.append(result)
        recorder.on_call(result)

    stamp = tag or list_date.isoformat()
    table = Table(title=f"napix-check {list_date}", show_lines=False)
    for col in ("step", "api", "result", "ms", "shape / sample"):
        table.add_column(col)
    failed: list[str] = []
    skipped: list[str] = []
    ctx: dict[str, Any] = {"cnr": cnr}
    recorded = 0
    try:
        async with (client_factory or _client_from_settings)(hook) as client:
            hc = NapixHighCourt(client, s.napix_est_code, s.napix_state_code)
            console.print(
                f"NAPIX {s.napix_base_url}  dept_id={s.napix_dept_id}  est_code={s.napix_est_code}  "
                f"version={s.napix_version}  key fingerprint={client.crypto.fingerprint}  "
                f"hmac self-test={'PASS' if client.crypto.self_test() else 'FAIL'}"
            )

            async def step(
                name: str, api_key: str, fn: Callable[[], Awaitable[Any]], save_as: str | None = None
            ) -> Any:
                if only and name not in only:
                    return None
                if max_calls is not None and len(calls) >= max_calls:
                    skipped.append(name)
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
                    failed.append(name)
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
                await step("causelist_bench", "causelist_bench", lambda: hc.causelist_benches(list_date))
                or []
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
                        lambda: hc.search_party(
                            str(rec["pet_name"])[:40], int(rec["reg_year"]), pend_disp=pend
                        ),
                    )
            elif not only or only & CASE_STEPS:
                console.print(
                    "[yellow]no CNR available (no details rows and --cnr not given): case APIs skipped[/yellow]"
                )

            # design `search-court-advocate-filing`, decision 2: each runs only when its inputs are given
            if probe.advocate:
                adv, year, pend = probe.advocate, probe.reg_year, probe.pend
                await step(
                    "advocate_name", "advocate_name", lambda: hc.search_advocate(adv, year, pend_disp=pend)
                )
            if probe.filing_type is not None and probe.fil_no is not None and probe.fil_year is not None:
                ft, fn, fy = probe.filing_type, probe.fil_no, probe.fil_year
                await step("filing", "filing", lambda: hc.search_filing(ft, fn, fy))
    finally:
        recorded = (record or record_calls)(recorder)

    console.print(table)
    limit, remaining = calls[-1].rate_limit if calls else (None, None)
    console.print(
        f"{len(calls)} calls, {len(failed)} failed"
        + (f", {len(skipped)} steps not started (--max-calls {max_calls})" if skipped else "")
        + f"; {recorded} attempts recorded in napix_call_log; rate limit: limit={limit} remaining={remaining};"
        f" samples in {samples}"
    )
    if skipped:
        console.print("[yellow]not started: " + ", ".join(skipped) + "[/yellow]")
    return len(failed)


def napix_check(
    date_: str = typer.Option(None, "--date", help="cause-list date, YYYY-MM-DD (default: yesterday)"),
    cnr: str = typer.Option(None, help="a CNR to use for the case APIs when the details rows give none"),
    samples: Path = typer.Option(DEFAULT_SAMPLES, help="where decrypted samples are written"),
    only: str = typer.Option(None, help="comma-separated step names to run"),
    max_benches: int = typer.Option(3, help="benches to query Cause List Details for"),
    tag: str = typer.Option(None, help="sample file suffix instead of the date (e.g. pending-case)"),
    advocate: str = typer.Option(None, help="Search by Advocate Name: the name (3 to 99 characters)"),
    reg_year: str = typer.Option(None, "--reg-year", help="advocate search year, or 'blank' to send none"),
    pend: str = typer.Option("P", help="advocate search: P (pending) or D (disposed)"),
    filing_type: int = typer.Option(None, "--filing-type", help="Search by Filing Number: case-type code"),
    fil_no: int = typer.Option(None, "--fil-no", help="Search by Filing Number: the filing number"),
    fil_year: int = typer.Option(None, "--fil-year", help="Search by Filing Number: the filing year"),
    max_calls: int = typer.Option(None, "--max-calls", help="start no new step once N attempts were made"),
) -> None:
    """Live NAPIX test: walks the High Court APIs, saves the decrypted responses as samples, logs every call."""
    from aslms.cli.main import parse_cli_date

    s = get_settings()
    if not s.napix_enabled:
        raise typer.Exit(
            "NAPIX_ENABLED is false; set it for this run only: NAPIX_ENABLED=true aslms napix-check"
        )
    probe = probe_from_options(advocate, reg_year, pend, filing_type, fil_no, fil_year)
    if max_calls is not None and max_calls < 1:
        raise typer.BadParameter("--max-calls is at least 1")
    d = parse_cli_date(date_) or (today_ist() - timedelta(days=1))
    try:
        failures = asyncio.run(
            run(
                d,
                cnr,
                samples,
                set(only.split(",")) if only else None,
                max_benches,
                tag,
                probe=probe,
                max_calls=max_calls,
            )
        )
    except CallLogUnavailable as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from None
    raise typer.Exit(code=1 if failures else 0)
