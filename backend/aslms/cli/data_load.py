"""`aslms data-load status | coverage | start | pause | resume | order | pdfs-after-details | dedupe | collect |
stop | gaps` (design `data-load-console`, decision 20; `pdfs-after-details`: case details before order PDFs, owner 24
Oct 2026; `collect` and `stop`: Collect Now's all cases listed on a day and Stop Using Everything, design
`data-collection-redesign`, round 3; `gaps`: the cause-list days no collection has asked for, design
`causelist-day-gap-sweep`, decision 7).
Every action acts as the single active super admin through its super-admin membership (the `system`
actor before one exists) and is audited, as the API's actions are. `status` and `coverage` read only."""

from __future__ import annotations

import json
from datetime import date

import typer
from rich import print as rprint
from rich.table import Table

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ops import LoadOrder
from aslms.services import collect, data_load
from aslms.services.access import Forbidden

data_load_app = typer.Typer(
    no_args_is_help=True, help="The backdated NAPIX load: progress, start, pause, order"
)

REFUSED = (
    Forbidden,
    data_load.LoadInputError,
    data_load.LoadConflict,
    data_load.SearchTimeout,
    collect.CollectInputError,
    collect.CollectConflict,
    collect.RequestNotFound,
)


def _cli_actor(session):
    from aslms.cli.pipeline import _cli_actor as actor_of

    return actor_of(session)


def _date(value: str | None) -> date | None:
    from aslms.cli.main import parse_cli_date

    return parse_cli_date(value)


def _refused(exc: Exception) -> typer.BadParameter:
    extra = getattr(exc, "extra", None)
    tail = f" {json.dumps(extra, default=str)}" if extra else ""
    return typer.BadParameter(f"{getattr(exc, 'code', 'refused')}: {exc}{tail}")


ESTIMATE_REASONS = {
    "connection_off": "no date: the court connection is off",
    "paused": "no date: the automatic collection is paused",
    "not_enough_history": "no date: less than a day of collection to measure",
    "no_recent_calls": "no date: no court call in the last hour",
}


def _n(value: int | float | None) -> str:
    return "-" if value is None else f"{value:,.0f}"


def _estimate_line(label: str, line: dict) -> str:
    if line.get("reason"):
        return f"{label}: {ESTIMATE_REASONS.get(line['reason'], line['reason'])}"
    if not line.get("calls_needed"):
        return f"{label}: done"
    at = line["finish_at"]
    return f"{label}: about {at:%a %d %b %Y %H:%M} IST ({_n(line['calls_needed'])} calls)"


def not_asked_line(block: dict | None) -> str:
    """Design causelist-day-gap-sweep, decision 6: "Days not asked for: 4 (2026-10-02 to 2026-10-05)" or "none"."""
    if not block or not block["count"]:
        return "Days not asked for: none"
    parts = [str(r["from"]) if r["days"] == 1 else f"{r['from']} to {r['to']}" for r in block["ranges"]]
    more = f" and {block['more_ranges']} more ranges" if block.get("more_ranges") else ""
    return f"Days not asked for: {_n(block['count'])} ({', '.join(parts)}{more})"


def status_lines(ov: dict) -> list[str]:
    """The headline and the two estimate lines of the Overview (design data-collection-redesign, Services round 1)."""
    lines = [
        f"Automatic collection: {ov['collection'].replace('_', ' ')}"
        + (f", working on {ov['position']['working_on_month']}" if ov["position"]["working_on_month"] else "")
        + f"; court connection {'on' if ov['napix_enabled'] else 'off'}"
    ]
    if ov["days"] is not None:
        d = ov["days"]
        lines.append(
            f"Cause lists: {_n(d['collected'])} of {_n(d['calendar'])} days ({_n(d['failed'])} failed)"
        )
    if ov["days"] is not None or ov.get("not_asked") is not None:
        lines.append(not_asked_line(ov.get("not_asked")))
    c, o, left = ov["cases"], ov["orders"], ov["left"]
    lines.append(
        f"Cases: {_n(c['found'])} found, {_n(c['with_details'])} with details, {_n(c['without_details'])} without"
    )
    lines.append(
        f"Order PDFs: {_n(o['stored'])} of {_n(o['referenced'])} stored, {_n(o['waiting'])} waiting, "
        f"{_n(o['not_available'])} not available at the court, {_n(o['failed'])} failed"
    )
    lines.append(
        f"Still to fetch: {_n(left['total'])} ({_n(left['causelist_days'])} cause-list days, "
        f"{_n(left['case_details'])} case details, {_n(left['order_pdfs'])} order PDFs)"
    )
    est = ov["estimate"]
    lines.append(_estimate_line("Cause lists and case details", est["details"]))
    lines.append(_estimate_line("Every order PDF as well", est["all"]))
    lines.append(
        f"Pace: about {_n(est['basis']['calls_per_hour'])} court calls an hour"
        + (
            f" of the {_n(est['basis']['hourly_limit'])} the court allows"
            if est["basis"]["hourly_limit"]
            else ""
        )
    )
    return lines


@data_load_app.command("status")
def status(
    as_json: bool = typer.Option(False, "--json", help="the progress block as JSON (GET /admin/data-load)"),
) -> None:
    """The Overview's headline and the two estimate lines; `--json` prints the progress block."""
    settings = get_settings()
    with session_scope() as s:
        if as_json:
            print(json.dumps(data_load.progress(s, settings), default=str, indent=2, ensure_ascii=False))
            return
        ov = data_load.overview(s, settings)
    for line in status_lines(ov):
        print(line)


@data_load_app.command("coverage")
def coverage(
    from_: str | None = typer.Option(None, "--from", help="first month, YYYY-MM (default: the load period)"),
    to: str | None = typer.Option(None, "--to", help="last month, YYYY-MM"),
) -> None:
    """Coverage month by month."""
    settings = get_settings()
    with session_scope() as s:
        try:
            months = data_load.coverage(s, settings, from_, to)
        except REFUSED as exc:
            raise _refused(exc) from exc
    table = Table(
        "month", "days", "covered %", "lists", "entries", "cases", "details %", "orders", "left", "failed"
    )
    for m in months:
        table.add_row(
            m["month"],
            str(m["days"]["calendar"]),
            f"{m['days_covered_pct']:.1f}",
            str(m["lists"]),
            str(m["entries"]),
            str(m["cases"]["listed"]),
            "-" if m["details_pct"] is None else f"{m['details_pct']:.1f}",
            f"{m['orders']['stored']}/{m['orders']['referenced']}",
            str(sum(m["work_left"].values())),
            str(sum(m["failed"].values())),
        )
    rprint(table)


@data_load_app.command("start")
def start(
    from_: str = typer.Option(..., "--from", help="first list date (YYYY-MM-DD)"),
    to: str = typer.Option(..., "--to", help="last list date (YYYY-MM-DD, yesterday at the latest)"),
    refetch_held: bool = typer.Option(False, "--refetch-held", help="queue days already held again"),
) -> None:
    """Queue every cause-list day of the range in the load lane (days already held are skipped unless
    `--refetch-held`)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            res = data_load.start(
                s, actor, member, _date(from_), _date(to), "refetch" if refetch_held else "skip"
            )
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(res.as_dict())


@data_load_app.command("pause")
def pause(reason: str = typer.Option(..., "--reason", help="why (3-500 characters)")) -> None:
    """Pause the backdated load (the daily cycle and requests keep running)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = data_load.pause(s, actor, member, reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"paused (version {out.version})")


@data_load_app.command("resume")
def resume(reason: str | None = typer.Option(None, "--reason")) -> None:
    """Resume the backdated load."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = data_load.resume(s, actor, member, reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"running (version {out.version})")


@data_load_app.command("order")
def order(
    preset: str = typer.Option(..., "--preset", help="cases_first | lists_first | cases_with_orders"),
    first_from: str | None = typer.Option(None, "--first-from", help="period to bring forward: first day"),
    first_to: str | None = typer.Option(None, "--first-to", help="period to bring forward: last day"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    """What goes first; every pending load row is re-prioritised."""
    if preset not in {o.value for o in LoadOrder}:
        raise typer.BadParameter("preset is cases_first, lists_first or cases_with_orders")
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out, n = data_load.set_order(s, actor, member, preset, _date(first_from), _date(first_to), reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"{out.load_order} (version {out.version}); {n} pending load rows re-prioritised")


@data_load_app.command("pdfs-after-details")
def pdfs_after_details(
    apply: bool = typer.Option(
        False, "--apply", help="move the rows (without it: a dry run, nothing written)"
    ),
) -> None:
    """Case details before order PDFs (owner, 24 Oct 2026): move every order PDF of the daily, load and discovery
    lanes below 60, in any status but running, to 60 for a pending case and 80 otherwise, in batches and repeated
    passes; request-lane rows keep their priority. A dry run by default; audited `data_load.pdfs_after_details`;
    idempotent; safe while the worker runs."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
    try:
        out = data_load.pdfs_after_details(get_sessionmaker(), actor, member, apply=apply)
    except REFUSED as exc:
        raise _refused(exc) from exc
    found = out["found"]
    rprint(f"order PDFs ahead of case details: {found['rows']} {found['by_lane']} {found['by_status']}")
    rprint(f"  to 60: {found['to_60']}, to 80 (case not pending): {found['to_80']}")
    rprint(f"  running now, not moved: {found['running']}")
    rprint(f"  request-lane order PDFs kept as they are: {out['request_lane_kept']}")
    if not apply:
        rprint("dry run: nothing written (--apply moves them)")
        return
    moved = out["moved"]
    rprint(
        f"moved: {moved['rows']} {moved['by_lane']} {moved['by_status']} "
        f"(to 60: {moved['to_60']}, to 80: {moved['to_80']})"
    )
    if out["job_run_id"] is not None:
        rprint(f"job run {out['job_run_id']}, {moved['batches']} batch(es) in {moved['passes']} pass(es)")
    if moved["left"]:
        rprint(
            f"[yellow]{moved['left']} row(s) still below 60 (running or locked): run it again later[/yellow]"
        )


@data_load_app.command("dedupe")
def dedupe(dry_run: bool = typer.Option(False, "--dry-run", help="print the pairs; write nothing")) -> None:
    """Run the duplicate rules over every case (merge provisional rows, link court duplicates, list for review)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            report = data_load.scan(s, actor, member, dry_run=dry_run)
        except REFUSED as exc:
            raise _refused(exc) from exc
        if dry_run:
            s.rollback()
    table = Table("kind", "case", "cnr", "case no", "other", "other cnr", "other case no")
    for p in report.pairs:
        table.add_row(
            p["kind"],
            p["case"]["ref_no"],
            p["case"]["cnr"] or "",
            p["case"]["case_no_text"] or "",
            p["other"]["ref_no"],
            p["other"]["cnr"] or "",
            p["other"]["case_no_text"] or "",
        )
    rprint(table)
    rprint({**report.counts(), "dry_run": dry_run})


@data_load_app.command("collect")
def collect_day(
    on: str = typer.Option(..., "--date", help="the cause-list date (YYYY-MM-DD, up to tomorrow)"),
    every: bool = typer.Option(
        False,
        "--all",
        help="every case listed (but those refreshed in the last 6 hours); default: never fetched",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="print the check; write nothing"),
) -> None:
    """All Cases Listed on a Day (design data-collection-redesign, decision 27): the cases of the day's current lists
    fetched at once at the bulk "now" priority, using the whole hourly allowance; one bulk request at a time. Audited
    `data_load.collect_requested`."""
    d = _date(on)
    scope = "all" if every else "never"
    settings = get_settings()
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            check = collect.check_day(s, settings, d, scope)
            plan = check["plan"]
            rprint(
                f"{d}: {check['lists']} list(s), {check['cases_listed']} case(s) listed, "
                f"{check['with_details']} with details, {check['never_fetched']} never fetched, "
                f"{check['refreshed_recently']} refreshed in the last 6 hours, {check['no_reference']} without a "
                f"court reference; to fetch ({scope}): {check['to_fetch']}, about {plan['calls']} court calls"
            )
            if dry_run or not check["to_fetch"]:
                if not check["to_fetch"]:
                    rprint("nothing to fetch")
                s.rollback()
                return
            out = collect.collect(s, actor, member, settings, {"kind": "day", "date": d, "scope": scope})
        except REFUSED as exc:
            raise _refused(exc) from exc
    end = f", finishing about {out.expected_end:%d %b %H:%M} IST" if out.expected_end else ""
    rprint(f"request {out.request_id}: {out.to_fetch} case(s) at priority {out.priority}{end}")


@data_load_app.command("stop")
def stop_request(request_id: str = typer.Argument(..., help="the request id (its audit row)")) -> None:
    """Stop Using Everything (decision 31): the rest of a bulk request goes to the normal turn (priority 30); running
    rows finish; nothing is thrown away. Audited `data_load.collect_stopped`."""
    import uuid

    try:
        rid = uuid.UUID(request_id)
    except ValueError as exc:
        raise typer.BadParameter("not a request id") from exc
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = collect.stop(s, actor, member, rid)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"request {out['request_id']} stopped: {out['moved']} row(s) back to the normal turn")


@data_load_app.command("gaps")
def gaps(
    apply: bool = typer.Option(
        False, "--apply", help="queue the days now (without it: a dry run, nothing written)"
    ),
) -> None:
    """The cause-list days of the collection period (the earliest load or daily-cycle day to yesterday) that no
    collection has asked for, folded into ranges with the lane each would take (design causelist-day-gap-sweep,
    decision 7). A dry run by default; `--apply` runs the nightly sweep now, with its `job_runs` row and one audit row
    `data_load.gaps_queued`. No court call."""
    from aslms.services import access, causelist_gaps

    settings = get_settings()
    with session_scope() as s:
        p = causelist_gaps.plan(s, settings)
        if p["from"] is None:
            print("No collection period yet: no load or daily-cycle cause-list day has been asked for")
        else:
            print(f"Collection period: {p['from']} to {p['to']}")
        print("Days not asked for: " + (f"{p['missing']:,}" if p["missing"] else "none"))
        for r in p["ranges"]:
            span = str(r["from"]) if r["days"] == 1 else f"{r['from']} to {r['to']}"
            pr = "/".join(str(x) for x in r["priorities"])
            print(
                f"  {span} ({r['days']} day{'s' if r['days'] != 1 else ''}): {r['lane']} lane, priority {pr}"
            )
        if p["paused"] and p["would_queue_load"]:
            print("The collection is paused: load-lane days wait until it is resumed")
        if not apply:
            print("Dry run: nothing written (--apply queues them)")
            return
        actor, member = _cli_actor(s)
        out = causelist_gaps.run_sweep(s, settings, trigger="cli", actor=access.actor_as(actor, member))
    print(f"Queued: {out['queued_daily']} in the daily lane, {out['queued_load']} in the load lane")
