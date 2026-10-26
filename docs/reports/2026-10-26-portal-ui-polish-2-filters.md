# Report: portal-ui-polish-2-filters (row 163)

Round 3 of 3 of the approved navigation mockup (design `docs/design/portal-ui-polish-2-filters.md`, decisions 21-25).

## What changed
Frontend only (37 files): `FilterCard` and `FilterBar layout="card"` (Filter Layout B) on six pages, the cause-list date navigator with the day's list badge, the View Cause List modal (`frontend/src/components/causelist/ViewCauseList.tsx`), cause-list helpers in `frontend/src/lib/causelist.ts`, uicheck day fixtures and five Layout B states. No migration, no table, no endpoint change.

## Gates
- ruff check: all checks passed
- pytest -q: 2368 passed, 3 skipped (30 min)
- docker compose build: succeeded
- portal smoke: passed
- git status clean; design note approved; decisions-log entry and backlog row present
- CI on main (gh run list): last run success (run 40246003677)

## Merge
Squash commit 044246e on main, tag `feature/portal-ui-polish-2-filters-done`. See the integrator's return values for the push and CI run.

## Review findings
Four advisories, all closed as follow-up row 168 (frontend only):
1. "No Lists" badge shown while the day loads or fails.
2. A court-wide bench with several lists shows only the first list's entries.
3. `probeFile` fetches the PDF twice and drops the caller's signal.
4. Missing tests: `no_pdf` answer, FilterCard stacking on phones.

## Deviations
None beyond those in the design note.

## Follow-up rows
168 (new).

## Load status
`aslms queue-status`: order_pdf done 137701, pending 169317, skipped 8; status_batch done 1178, skipped 6; dossier skipped 51; masters done 1 (excerpt).
