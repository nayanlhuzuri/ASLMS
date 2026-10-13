# Report: portal-filters (row 59), 13 Oct 2026

Merged to `main` as 61f92e1 (squash), tag `feature/portal-filters-done`. Design: docs/design/portal-filters.md (approved).

## What changed
- Shared case filters (words, cause-list date presets or any range, court and bench, next hearing range, case type, year, status, department) added server-side to every list API; `GET /reference/benches`.
- Portal: one `FilterBar` (frontend/src/components/filters/FilterBar.tsx), `frontend/src/lib/filters.ts` and messages; filters live in the query string on Recommended, Claimed, Unclaimed, Transfers, Files, Alerts and Search.
- No migration, no new tables. 52 files changed.

## Gates
- ruff check: All checks passed
- pytest -q: 965 passed, 71 warnings
- docker compose build: succeeded
- portal_smoke: portal smoke: passed
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings (both advisory, left open)
1. `year`, `listed_*`, `next_*` malformed values return FastAPI 422 (list-shaped detail) rather than the 400 string of decision 7; only hand-edited URLs are affected. Added as follow-up.
2. FilterBar: with a "More filters" field applied the disclosure button is a no-op (`open = userOpen || moreSet`). Added as follow-up.

## Deviations
None beyond those recorded in the design note (deviations 1-2).

## Follow-ups
Row 63 (filters-followups) extended with findings 1 and 2; browser check with row 56.

## Load status (queue-status)
dossier done 30130 / failed 421 / pending 22; order_pdf done 22367 / pending 181740 / failed 5; status_batch done 194; causelist_day running 1, skipped 64.
