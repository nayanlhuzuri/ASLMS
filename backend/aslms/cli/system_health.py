"""`aslms system-health [--json]` (design `api-health-checker`, decision 18): the System health screen on the command
line. It prints the overall line, the 17 court cards (name, status, last call, 24 h answered rate, median) and the
ten ASLMS services. Read-only: it never calls NAPIX and needs no actor. Exit code 2 when a service is down, else 0,
so the runbook and scripts can use it. There is no test command: the owner's live checks use `aslms napix-check`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import typer

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import service_checks, system_health

SENTENCES = {
    "everything_working": "Everything is working",
    "need_attention": "{n} need attention",
    "not_working": "{n} is not working",
    "not_known": "Not known yet",
}


def _rate(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)} %"


def _ms(value: int | None) -> str:
    return "—" if value is None else f"{value} ms"


def system_health_cmd(
    as_json: bool = typer.Option(False, "--json", help="print the readings as JSON"),
) -> None:
    """The overall line, the court cards from the call log and the ten service checks; exit 2 when a service is
    down."""
    settings = get_settings()
    now = datetime.now(UTC)
    with session_scope() as s:
        cards = system_health.napix_cards(s, settings, None, now)
        services = service_checks.run_all(s, settings, now)
        statuses = [c["status"] for g in cards["groups"] for c in g["cards"]]
        line = system_health.overall(statuses, [x["status"] for x in services])
        s.rollback()
    down = any(x["status"] == "down" for x in services)
    if as_json:
        print(json.dumps({"overall": line, "court": cards, "services": services}, default=str, indent=2))
        raise typer.Exit(2 if down else 0)
    counts = line["counts"]
    n = counts["not_working"] if line["sentence_key"] == "not_working" else counts["attention"]
    print(f"System health: {SENTENCES[line['sentence_key']].format(n=n)} ({line['status']})")
    print(
        f"Court connections: {counts['court_working']} of {counts['court_total']} working; "
        f"ASLMS services: {counts['services_working']} of {counts['services_total']} working"
    )
    print(f"Court calls switched {'on' if cards['napix_enabled'] else 'off'} on this server")
    for group in cards["groups"]:
        print(f"\n{group['label']}")
        for c in group["cards"]:
            last = c["last_call"]
            when = last["called_at"].strftime("%d %b %H:%M") if last else "no call in 7 days"
            print(
                f"  {c['label']:<28} {c['status_word']:<16} last {when:<17} "
                f"24 h {_rate(c['h24']['rate']):>6}  median {_ms(c['h24']['p50_ms'])}"
            )
    print("\nASLMS services")
    for x in services:
        word = system_health.SERVICE_WORDS[x["status"]]
        print(f"  {x['label']:<28} {word:<12} {x['headline']}")
    raise typer.Exit(2 if down else 0)
