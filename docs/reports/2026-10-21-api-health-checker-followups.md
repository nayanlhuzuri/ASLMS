# api-health-checker-followups (row 110)

Merged to main as b4ca6fb, tag `feature/api-health-checker-followups-done`. No migration (head 0020).

## What changed
27 files: NAPIX call rows are committed apart (`flush_apart` in `napix_store.py`) so a failing request keeps them; the court-search, fetch-court and data-load fetch routes follow the same rule (decision 11); the connectivity check shares the Connection test's lock and counts a renewal's outer 401 correctly; per-user hourly cap lock; NO_DATE sentinels in `_present()`; `schema.md` ref_permission count 52/50; portal messages. No table or endpoint added.

## Gates
- ruff check: all checks passed
- pytest: 1824 passed, 2 skipped (26 min)
- docker compose build: succeeded
- portal smoke (frontend changed): passed
- git status clean; design status approved; decisions-log entry and backlog row present
- CI on main: unknown (no remote, no gh)

## Push
Not pushed: no remote.

## Review findings (4 advisory, all open, none blocking)
1. Pool hold-and-wait in flush_apart callers: parked as row 114.
2. napix_api_check audit row skipped on an exception before the audit write: row 114.
3. health_check writes no audit row on an unexpected exception: row 114.
4. flush() through flush_apart leaves response_ids unreset (latent): row 114.

## Deviations
None.

## Load status
`aslms queue-status` printed nothing within 40 s; not recorded.
