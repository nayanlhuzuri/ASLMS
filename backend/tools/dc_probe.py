"""District Court (`dc-*`) live probe, backlog row 222 `district-court-live-check` (owner-approved, 3 Nov 2026).

A one-off operator tool, modelled on `aslms napix-check`, not part of the application. Every call goes through the
integration layer (`NapixClient.call`); every attempt is recorded by a `NapixRecorder` into `napix_call_log` (and each
decrypted JSON answer into `napix_responses`) at the end of the run, also when a step fails; the run refuses to start
when the call log cannot be reached.

**Owner-approved, one-off deviation (row 222, option 2):** the District Court rows are written with
`rate_limit_remaining` NULL. The quota-window code (`services/napix_window.py`, `readings`) does not yet separate the
District Court allowance from the High Court's, so a District Court count in that column would be read as a High Court
reading. The real rate headers of every response are kept in this tool's own output instead (`dc_probe_run_*.json`).

No Overview call is made (its path is shared with the High Court window probe). No retries: one attempt per step, so
the call budget is exact. No credentials, tokens, query strings or request bodies are printed or written.

Steps are positional arguments `label:api_key:k1=v1;k2=v2` (parameters in the specification's order), e.g.

    python dc_probe.py --out /out --tag 2026-11-03 --max-calls 2 state:state: district:district:state_code=6

Run inside a one-off container of the api image with the court-data switch set on the command line for that run only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.services.napix_store import CallLogUnavailable, NapixRecorder, require_call_log

# paths exactly as the gateway stubs in docs/specs/napix/dc/ give them (basePath + path)
DC_API: dict[str, tuple[str, str]] = {
    "state": ("dc-state-api/state", "GET"),
    "district": ("dc-district-api/district", "GET"),
    "court_complex": ("dc-court-complex-api/courtComplex", "GET"),
    "court_list": ("dc-court-list-api/courtList", "GET"),
    "casetype": ("dc-casetype-master-api/casetypeMaster", "GET"),
    "police_station": ("dc-police-station-master-api/policeStationMaster", "GET"),
    "causelist": ("dc-causelist-api/causelist", "GET"),
    "advocate_causelist": ("dc-advocate-causelist-api/advocateCauselist", "GET"),
    "case_number": ("dc-case-number-api/caseSearch", "GET"),
    "cnr": ("dc-cnr-api/cnr", "GET"),
    "current_status": ("dc-current-status-api/currentStatus", "POST"),
    "show_business": ("dc-show-business-api/showBusiness", "GET"),
    "order": ("dc-oreder-api/order", "GET"),
    "caveat_name": ("dc-caveat-name-api/caveatName", "GET"),
}
RATE_WORDS = ("ratelimit", "rate-limit", "retry-after", "quota")


class HeaderTap(httpx.AsyncBaseTransport):
    """Wraps the real transport and keeps, per response, the URL path (never the query), the status, the rate headers
    with their values and the names (only) of all other headers."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.seen: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        rate = {k: v for k, v in response.headers.items() if any(w in k.lower() for w in RATE_WORDS)}
        self.seen.append(
            {
                "path": request.url.path,
                "status": response.status_code,
                "rate_headers": rate,
                "other_header_names": sorted(k for k in response.headers if k not in rate),
            }
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def parse_step(raw: str) -> tuple[str, str, dict[str, str]]:
    label, key, rest = (raw.split(":", 2) + ["", ""])[:3]
    if key not in DC_API:
        raise SystemExit(f"unknown api key {key!r}; one of {', '.join(DC_API)}")
    params: dict[str, str] = {}
    for pair in filter(None, rest.split(";")):
        k, _, v = pair.partition("=")
        params[k.strip()] = v.strip()
    return label or key, key, params


def shape(res: NapixResult | None) -> str:
    if res is None:
        return "-"
    if res.pdf:
        return f"pdf {len(res.pdf)} bytes"
    d = res.data
    if isinstance(d, dict):
        rows = nested_list(d)
        inner = d if rows else next((v for v in d.values() if isinstance(v, dict) and nested_list(v)), None)
        if not rows and inner is not None:
            rows = nested_list(inner)
        top = ", ".join(list(d)[:10])
        return f"keys [{top}]" + (f"; {len(rows)} rows, row keys [{', '.join(rows[0])}]" if rows else "")
    if isinstance(d, list):
        return f"list[{len(d)}]"
    return type(d).__name__


def hc_latest() -> list[dict[str, Any]]:
    """Read-only: the latest High Court readings in the call log (rows that are not `dc-*`), for the allowance
    comparison. No call is made."""
    from aslms.db.session import session_scope

    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT api, called_at, rate_limit_remaining FROM napix_call_log "
                "WHERE api NOT LIKE 'dc-%' AND rate_limit_remaining IS NOT NULL "
                "ORDER BY called_at DESC LIMIT 3"
            )
        ).all()
    return [{"api": a, "called_at": c.isoformat(), "remaining": r} for a, c, r in rows]


def dc_rows_logged(since: datetime) -> dict[str, Any]:
    from aslms.db.session import session_scope

    with session_scope() as s:
        n, with_rem, ok = s.execute(
            text(
                "SELECT count(*), count(rate_limit_remaining), count(*) FILTER (WHERE ok) FROM napix_call_log "
                "WHERE api LIKE 'dc-%' AND called_at >= :since"
            ),
            {"since": since},
        ).one()
        total_today = s.scalar(
            text("SELECT count(*) FROM napix_call_log WHERE api LIKE 'dc-%' AND called_at >= :d"),
            {"d": since.replace(hour=0, minute=0, second=0, microsecond=0)},
        )
    return {
        "dc_rows_this_run": n,
        "with_remaining": with_rem,
        "ok": ok,
        "dc_rows_since_utc_midnight": total_today,
    }


async def run(args: argparse.Namespace) -> int:
    steps = [parse_step(s) for s in args.steps]
    require_call_log("dc_probe")
    started = datetime.now(UTC)
    tap = HeaderTap()
    recorder = NapixRecorder()  # no user, no lane: an operator's tool
    facts: list[dict[str, Any]] = []
    compare: dict[str, Any] | None = None

    def hook(result: NapixResult) -> None:
        last = tap.seen[-1] if tap.seen else None
        if last is not None and not last["path"].endswith(result.api):
            last = None  # no response reached the tap for this attempt (a transport error)
        facts.append(
            {
                "api": result.api,
                "params": result.params,
                "called_at": result.called_at.isoformat() if result.called_at else None,
                "ok": result.ok,
                "http_status": result.http_status,
                "napix_status": result.napix_status,
                "error_family": result.error_family,
                "error": (result.error or "")[:300] or None,
                "duration_ms": result.duration_ms,
                "token_verified": result.token_verified,
                "rate_limit_parsed": list(result.rate_limit),
                "headers": last,
            }
        )
        # the owner-approved deviation: the District Court count is not written to the column the window reads
        recorder.on_call(replace(result, rate_limit=(None, None)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    try:
        async with NapixClient.from_settings(on_call=hook, transport=tap, max_attempts=1) as client:
            for label, key, params in steps:
                if len(facts) >= args.max_calls:
                    print(f"[stop] --max-calls {args.max_calls} reached; not started: {label}")
                    break
                path, method = DC_API[key]
                before = len(facts)
                res: NapixResult | None = None
                try:
                    res = await client.call(path, params, method=method)
                    status = "ok"
                except IntegrationError as e:
                    failed += 1
                    status = f"{type(e).__name__}: {str(e.message)[:200]}"
                saved = "-"
                if res is not None and res.pdf:
                    p = out / f"dc_{label}_{args.tag}.pdf"
                    p.write_bytes(res.pdf)
                    saved = p.name
                elif res is not None and res.data is not None:
                    p = out / f"dc_{label}_{args.tag}.json"
                    p.write_text(
                        json.dumps(res.data, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8",
                        newline="\n",
                    )
                    saved = p.name
                rate = (
                    facts[-1]["headers"]["rate_headers"]
                    if len(facts) > before and facts[-1]["headers"]
                    else {}
                )
                print(f"[{label}] {path} {params} -> {status}; {shape(res)}; saved {saved}; rate {rate}")
                if args.compare_after == label and len(facts) > before:
                    compare = {
                        "dc_call": {"api": path, "called_at": facts[-1]["called_at"], "rate_headers": rate},
                        "hc_latest_from_call_log": hc_latest(),
                        "read_at": datetime.now(UTC).isoformat(),
                    }
                    print(f"[compare] {json.dumps(compare, default=str)}")
    finally:
        try:
            from aslms.db.session import session_scope

            with session_scope() as s:
                recorded = recorder.flush(s)
        except Exception as e:  # noqa: BLE001
            print(
                f"[error] call rows not written ({type(e).__name__}); attempts: {len(facts)}", file=sys.stderr
            )
            raise
        logged = dc_rows_logged(started)
        run_file = out / f"dc_probe_run_{started:%Y%m%dT%H%M%SZ}.json"
        run_file.write_text(
            json.dumps(
                {
                    "started_at": started.isoformat(),
                    "attempts": facts,
                    "recorded": recorded,
                    "logged": logged,
                    "compare": compare,
                    "token_requests_seen": [t for t in tap.seen if "oauth2" in t["path"]],
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"[done] {len(facts)} attempts, {failed} failed, {recorded} recorded; call log {logged}; {run_file.name}"
        )
    return failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True, help="sample file suffix, e.g. the date")
    ap.add_argument(
        "--max-calls", type=int, required=True, help="start no new step once N attempts were made"
    )
    ap.add_argument("--compare-after", default=None, help="step label after which to read the HC count")
    ap.add_argument("steps", nargs="+")
    args = ap.parse_args()
    if not get_settings().napix_enabled:
        raise SystemExit("the court-data switch is off; set it on the command line for this run only")
    try:
        failed = asyncio.run(run(args))
    except CallLogUnavailable as e:
        raise SystemExit(str(e)) from None
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
