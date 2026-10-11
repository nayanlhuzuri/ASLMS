"""Open every portal page in the running Compose `web` service and fail on any server-side render error.

Unit tests render components outside Next.js and miss errors that only happen in the real server (for example a
server page importing a plain value from a "use client" module, which crashed /admin/tickets on 11 Oct 2026). This
check requests each page under `frontend/src/app` with a dummy session cookie (enough to pass the page gate; the
pages load their data in the browser, so no real session is needed), expects HTTP 200, and then scans the `web`
container's log for render errors written during the run.

Usage, from the repository root, with `web` built from the branch and running:
    backend/.venv/Scripts/python backend/tools/portal_smoke.py [--base http://localhost:3000]
Exit status 0 when every page answers 200 and the log shows no error; 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "src" / "app"
COOKIE = "aslms_at=smoke; aslms_rt=smoke"
ERROR_LINE = re.compile(r"⨯|TypeError|ReferenceError|Unhandled|Error:")


def page_routes() -> list[str]:
    routes = set()
    for page in APP.rglob("page.tsx"):
        parts = []
        for part in page.parent.relative_to(APP).parts:
            if part.startswith("(") and part.endswith(")"):
                continue  # route group, not in the URL
            if part.startswith("[") and part.endswith("]"):
                part = "smoke-x"  # a dynamic segment; the page loads its data in the browser
            parts.append(part)
        routes.add("/" + "/".join(parts))
    return sorted(routes)


def fetch(base: str, route: str) -> int:
    req = urllib.request.Request(base + route, headers={"Cookie": COOKIE})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report a redirect as its status instead of following it
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    args = ap.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 1))
    failures = []
    for route in page_routes():
        status = fetch(args.base, route)
        ok = status == 200
        print(f"{'ok ' if ok else 'BAD'} {status} {route}")
        if not ok:
            failures.append(f"{route}: HTTP {status}")
    log = subprocess.run(
        ["docker", "compose", "logs", "web", "--since", started, "--no-log-prefix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    errors = [line for line in log.splitlines() if ERROR_LINE.search(line)]
    for line in errors:
        print(f"LOG {line}")
    if errors:
        failures.append(f"{len(errors)} error line(s) in the web log")
    print("portal smoke: " + ("passed" if not failures else "FAILED — " + "; ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
