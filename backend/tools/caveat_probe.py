"""Live probe of the High Court caveat APIs (backlog row 223 `caveat-live-check`, owner-approved 3 Nov 2026).

One NAPIX call per run, so each next call is chosen from the last answer and the owner's budget (at most 10 calls)
is never overspent. The call goes only through the integration layer's `NapixClient.call` (encryption, the shared
token, the rate limiter) with automatic retries switched off (`max_attempts=1`: a failure is recorded, not
repeated). Every attempt is written to `napix_call_log` (and a decrypted JSON answer to `napix_responses`) through
`NapixRecorder`, also when the call fails; the probe refuses to start when the call log cannot be reached.

Parameters are exactly those of the High Court Open API Specification v1.0, section 8:
  name     GET hc-caveat-name-api/caveatname       est_code|caveat_party_name|search_type   (8.1.4)
  details  GET hc-caveat-details-api/caveatdetails est_code|caveat_code                     (8.2.4)
`--omit KEY` leaves one parameter out on purpose (the bad-input call). `log` and `held` make no call: `log` prints
the caveat rows of `napix_call_log`, `held` which matched case numbers ASLMS already holds.

The record of each call (inputs, HTTP and eCourts status, rate-limit numbers, the decrypted answer or error text) is
written to `--out` as `<tag>.json`. No credential, token or encrypted request string is printed or saved.

Run in a one-off container of the api image with the court-data switch on for that run only (set on the
`docker compose run` command line, never in a file), mounting this folder read-only at /probe and a scratch folder
at /out, with `--entrypoint python api /probe/caveat_probe.py name --party "STATE OF ASSAM" --tag c1`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.integration.napix.client import NapixClient, NapixResult
from aslms.services.napix_store import CallLogUnavailable, NapixRecorder, require_call_log

APIS = {
    "name": "hc-caveat-name-api/caveatname",
    "details": "hc-caveat-details-api/caveatdetails",
}


def build_params(args: argparse.Namespace) -> dict[str, str]:
    """The spec's input string, in its order; `--omit` drops one key (the deliberate bad input)."""
    if args.step == "name":
        params = {
            "est_code": args.est,
            "caveat_party_name": args.party or "",
            "search_type": args.search_type,
        }
    else:
        params = {"est_code": args.est, "caveat_code": args.caveat_code or ""}
    if args.omit:
        if args.omit not in params:
            raise SystemExit(f"--omit {args.omit}: not a parameter of {args.step}")
        params.pop(args.omit)
    return params


def record(recorder: NapixRecorder) -> int:
    from aslms.db.session import session_scope

    with session_scope() as session:
        return recorder.flush(session)


def summary(
    res: NapixResult | None, tag: str, params: dict[str, str], exc: Exception | None
) -> dict[str, Any]:
    out: dict[str, Any] = {"tag": tag, "params": params}
    if res is None:
        out["error"] = f"no attempt recorded: {type(exc).__name__ if exc else 'unknown'}"
        return out
    limit, remaining = res.rate_limit
    out.update(
        api=res.api,
        called_at=res.called_at.isoformat() if res.called_at else None,
        ok=res.ok,
        http_status=res.http_status,
        napix_status=res.napix_status,
        error_family=res.error_family,
        error=res.error,
        duration_ms=res.duration_ms,
        token_verified=res.token_verified,
        rate_limit={"limit": limit, "remaining": remaining},
        data=res.data,
    )
    if not res.ok and res.raw_text:
        out["raw_text"] = res.raw_text[:2000]
    return out


async def probe(args: argparse.Namespace) -> int:
    params = build_params(args)
    require_call_log("caveat_probe")
    recorder = NapixRecorder()  # no user, no lane: an operator's probe
    calls: list[NapixResult] = []

    def hook(result: NapixResult) -> None:
        calls.append(result)
        recorder.on_call(result)

    exc: Exception | None = None
    recorded = 0
    try:
        async with NapixClient.from_settings(on_call=hook, max_attempts=1) as client:
            try:
                await client.call(APIS[args.step], params)
            except IntegrationError as e:
                exc = e
    finally:
        recorded = record(recorder)
    rec = summary(calls[-1] if calls else None, args.tag, params, exc)
    rec["attempts"] = len(calls)
    rec["recorded_in_call_log"] = recorded
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.tag}.json").write_text(
        json.dumps(rec, indent=2, ensure_ascii=False, default=str), encoding="utf-8", newline="\n"
    )
    brief = {k: v for k, v in rec.items() if k != "data"}
    data = rec.get("data")
    if isinstance(data, dict):
        brief["data_keys"] = list(data)[:20]
    print(json.dumps(brief, indent=2, ensure_ascii=False, default=str))
    return 0 if rec.get("ok") else 1


def show_log() -> int:
    from sqlalchemy import text

    from aslms.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(
            text(
                """
                SELECT called_at, api, http_status, napix_status, ok, error_family, rate_limit_remaining,
                       duration_ms, token_verified
                FROM napix_call_log WHERE api LIKE 'hc-caveat-%' ORDER BY called_at, id
                """
            )
        ).all()
    for r in rows:
        print(" | ".join(str(v) for v in r))
    print(f"{len(rows)} caveat rows in napix_call_log (as of {datetime.now(UTC).isoformat()})")
    return 0


def show_held(case_numbers: list[str]) -> int:
    """No call: which of the `matched_case_no` values (e.g. `WP(C)/4688/2026`) ASLMS already holds, and since when."""
    from sqlalchemy import bindparam, text

    from aslms.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(
            text(
                """
                SELECT case_no_text, cnr, filing_date, registration_date, created_at
                FROM cases WHERE case_no_text IN :nos ORDER BY case_no_text
                """
            ).bindparams(bindparam("nos", expanding=True)),
            {"nos": case_numbers},
        ).all()
    for r in rows:
        print(" | ".join(str(v) for v in r))
    print(f"{len(rows)} of {len(case_numbers)} matched case numbers held")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Live probe of the High Court caveat APIs (row 223)")
    ap.add_argument("step", choices=["name", "details", "log", "held"])
    ap.add_argument("case_numbers", nargs="*", help="held: matched case numbers to look up")
    ap.add_argument("--est", default="GAHC01", help="establishment code (spec 8.1.4 / 8.2.4)")
    ap.add_argument("--party", help="caveat_party_name, 3 to 99 characters")
    ap.add_argument("--search-type", default="A", help="A anywhere, S starting with")
    ap.add_argument("--caveat-code", help="the 15-digit caveat_code from a Caveat Name answer")
    ap.add_argument("--omit", help="leave this parameter out (the deliberate bad input)")
    ap.add_argument("--tag", default="caveat", help="file name of the record in --out")
    ap.add_argument("--out", default="/out")
    args = ap.parse_args(argv)
    if args.step == "log":
        return show_log()
    if args.step == "held":
        return show_held(args.case_numbers)
    if not get_settings().napix_enabled:
        print("the court-data switch is off; set it on the command line of this run only", file=sys.stderr)
        return 2
    try:
        return asyncio.run(probe(args))
    except CallLogUnavailable as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
