# Report: data-collection-redesign (row 172, round 1 of 4)

Merged 27 Oct 2026 as a squash of three commits on `feature/data-collection-redesign`; tag `feature/data-collection-redesign-done`.

## What changed
- Backend: `aslms/services/data_load.py` (overview, pulse, schedule, rates across every lane), `aslms/api/routers/data_load.py` (`GET /admin/data-load/overview`, `/pulse`, `/schedule`), CLI `aslms data-load status` headline and estimate lines. No migration, no new tables.
- Frontend: Data Collection four-tab frame (Overview, Collect Now, Automatic Collection), kit changes (`ProgressBar`, `ScrollBox`, no upper-case labels), uicheck rules `gutter` and `doubled-heading`, `frontend/src/lib/dataCollection.ts`.
- 76 files changed in all, with backend and frontend tests added.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2535 passed, 3 skipped, 0 failed (33m31s).
- `docker compose build`: succeeded.
- Portal smoke after `up -d --wait --no-deps web`: passed.
- Branch clean; design note status `approved`; decisions-log entry and backlog row 172 present.
- CI on main before the merge: success (run 40478748589).

## Review findings (all advisories, none blocking) and closure
All five are carried to follow-up row 191 (not fixed in this cycle):
1. Problems links not read by the Queue tab and shown to readers without queue access.
2. `overview()` queries not wrapped in `_timed` (500 instead of 503).
3. Load Control Status badge can contradict the Overview status line.
4. `useCountUp` restarts from 0 on each poll.
5. `causelist_recheck` calls counted under the `causelist_day` family (not in deviation 4).

## Deviations
As listed in the design note (deviation 1: Problems links; deviation 18: gutter fix by reading, live check is row 187).

## Follow-up rows
- 187 data-collection-gutter-live-check (already in the branch).
- 191 data-collection-redesign-advisories.

## Load status (`aslms queue-status`, abridged)
order_pdf: done 138,989, pending 231,539, skipped 8; status_batch: done 1,286, skipped 6.

## Push
See the integrator's return values (main and tag pushed to origin when accepted).
