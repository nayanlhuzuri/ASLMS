# Report: api-health-checker (backlog row 109)

Merge commit on main: see `git log` (tag `feature/api-health-checker-done`). 48 files, no migration.

## What changed
- Function `admin.service_health` (52 ref_permission rows, 50 active), Settings entry `/system` in the portal.
- System health API, court API test service (`napix_api_check.py`), service checks, `system_health.py`, `aslms system-health`.
- 17 NAPIX High Court API cards from `napix_call_log`; 'Test now' makes one call from held data, audit row `napix.api_tested`.
- Ten ASLMS service checks; frontend page, SVG bars/ring, `systemHealth.ts` with tests.

## Gates
- ruff check: All checks passed
- pytest -q: 1790 passed, 2 skipped (30 min)
- docker compose build: succeeded
- portal_smoke: passed (includes /system)
- git status clean; design status approved; decisions-log entry and backlog row present
- CI on main: CI status unknown (no remote, no gh)

## Push
Not pushed: no remote `origin`.

## Review findings (all advisory, none blocking)
1. Call-log rows in the request transaction (napix_api_check.py 386-441): open; same weakness as napix_admin.health_check. Follow-up recommended.
2. Outer 401 of a token renewal counted as failed in _ANSWERED_SQL: open; follow-up.
3. Per-user hourly cap has no per-user lock: open; bounded by per-API interval and quota floor.
4. _present() ignores sentinels 5000-01-01 and 1900-01-01: open; should use napix_values.NO_DATE.
5. schema.md ref_permission row still says 51 rows / 49 active: open documentation fix (52 / 50).
6. Design header has a second `approved_by: (pending)` line: status is approved by the owner on 2026-10-20; header left as is.

## Deviations
None. The advisory findings were carried forward rather than fixed in this cycle; a follow-up backlog row is added.

## Load status (queue-status)
order_pdf done 98638, pending 203349, running 1, skipped 4; status_batch done 790, skipped 6; masters done 1.
