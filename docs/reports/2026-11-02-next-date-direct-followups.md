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

## Deployed
Deployed 2 Nov 2026 at 23:17 IST. CI on `main` (run 41484115549) first failed on one timing test,
`tests/unit/test_next_date_rules.py::test_hostile_text_reads_quickly` (1.13 s against its 1.0 s limit on the shared
runner; 3,111 passed). Row 203 does not touch the rules module or that test, and it passes locally in 0.21 s, so only
the failed job was re-run: attempt 2 passed every job. No migration. Images built from the clean `main` checkout at
a6ab5cc; `docker compose --profile monitoring up -d --wait` with the court-data switch on recreated the app services,
then `api`, `worker`, `scheduler` and `web` once more with `--no-deps --force-recreate`; court data on in `api` and
`worker`; the running `web` has the image's build ID; `portal_smoke.py` passed.

Verification 3 (runbook section 21), at 23:18 to 23:21 IST:
- `aslms next-dates status` before: order 530, confirmed 1, none 64,560, court 17,662, around 529; flagged (order
  differs) 243.
- `hearing-refresh --all --dry-run`: 83,282 cases, `would_change` 83 (none 64,589, court 17,662, order 502, around
  528, confirmed 1).
- `docker compose stop worker scheduler`, then `hearing-refresh --all`: refreshed 83,282, changed 83, differs cleared
  54, differs set 0, manual superseded 0, skipped locked 0.
- Status after: order 502, confirmed 1, none 64,589, court 17,662, around 528; flagged 189.
- `worker` and `scheduler` started again with the court-data switch on (both healthy; court data on in `api` and
  `worker`).
