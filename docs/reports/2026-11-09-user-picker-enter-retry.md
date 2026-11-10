# User Picker Enter retry (row 186)

## What changed
- `frontend/src/components/ui/UserPicker.tsx`: one condition, `retryShown = errorNote !== null && canRetry`, drives both the Try Again button and the Enter key. Enter no longer refetches when the error note is not shown.
- `frontend/src/components/ui/userPicker.test.tsx`: test added (38 lines).
- Docs: decisions log entry, backlog row, CLAUDE.md focus line. No API, table, endpoint or migration change.

## Gates
- ruff check: All checks passed.
- pytest -q: 3206 passed, 3 skipped (56m31s), every run green.
- docker compose build: succeeded (no `up`).
- Screen check (private network, temporary images from the branch): 173 routes and states, 416 screenshots, 0 findings; 551 passed, 7 skipped. Temporary containers, network and images removed.
- git status clean; design note status approved; decisions-log entry and backlog row present.
- CI on main: last run success (run 42584877100).

## Review findings
None supplied.

## Deviations
None.

## Follow-up rows
None.

## Load status (queue-status, tail)
masters done 1; order_pdf done 208,159, pending 184,831; status_batch done 2,916, skipped 8.
