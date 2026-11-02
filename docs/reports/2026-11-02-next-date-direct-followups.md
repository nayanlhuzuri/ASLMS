# next-date-direct-followups (row 203) - 2026-11-02

Merge commit 62cae6f on main, tag `feature/next-date-direct-followups-done`. No migration.

## What changed
30 files (backend services `next_hearing`, `next_dates`, `access`, `assistant*`, `cases`, `cli/next_dates`, API schemas; frontend `hearingDate`, test helpers; e2e fixtures; docs).
- Corrections stand at the latest order's step; step 3 takes the later court date; a corrected date is superseded by a later passed court date or a second open reading.
- Holders of `next_dates.correct` read in one SQL query (`memberships_holding`).
- `direct --apply` and `hearing-refresh --all` commit per page.
- Case Assistant shows the confirmed next hearing only for a case the asker may open.
- `basisLine` tells plain entries from corrections; `corrected` added to the screen-check fixtures (fix that stopped the first merge run).

## Gates
- CI on main: last run success (run 41450057534).
- ruff: All checks passed.
- pytest: 3110 passed, 3 skipped (37m39s).
- docker compose build: succeeded, no `up`.
- Screen check (private network, temporary images, removed afterwards): 173 routes and states, 416 screenshots, 0 findings; 551 passed, 7 skipped.
- git status clean; design note status approved.
- Developer: frontend 89 files, 1932 tests; typecheck, lint, build pass.

## Review findings (both advisory, mayMerge true; not closed in the branch)
1. Plain date entered while a correction stands has no effect (needs an owner decision: 409 or newest manual row wins).
2. `test_refresh_all_commits_each_page` touches every committed case in the shared test database.
Both recorded as backlog row 218 (proposed).

## Deviations
None.

## Load status
`aslms queue-status` timed out at 120 s and was not read; see the load status in the console.
