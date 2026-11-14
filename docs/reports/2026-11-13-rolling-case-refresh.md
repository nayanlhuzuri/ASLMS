# Report: rolling-case-refresh (row 238)

Design: docs/design/rolling-case-refresh.md (approved). Squash-merged from `feature/rolling-case-refresh`; tag `feature/rolling-case-refresh-done`.

## What changed
47 files. The Sunday 02:00 sweep of every pending case is replaced by a 22:00 IST nightly refresh (claimed cases first, oldest first, skipping any case fully refreshed in the last 7 days); hearing follow-ups at about 3, 7, 14 and 30 days; revived queue rows keep the caller's priority; a second worker service `worker2` for `causelist_day` items; `aslms daily-cycle nightly`, `ROLLING_REFRESH_DAILY_MAX`; Automatic Collection and the schedule view state the nightly refresh; monitoring rule additions in `infra/prometheus`; Process Workflows, Software Documentation 1.7 and Hosting Guide 1.4 updated. No table, endpoint or migration change.

## Gates
- CI on main (origin/main 9fd7671): success, run 43454150521.
- ruff check: All checks passed.
- pytest -q: 3284 passed, 3 skipped (46 min 55 s), every run green.
- docker compose build: succeeded (no service recreated).
- frontend changed: screen check on a private network against a web image built from the branch: 179 routes and states, 574 screenshots, 0 findings; temporary container, network and images removed.
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings
Six advisories, none blocking, all recorded as backlog row 256: nightly transaction deadlock exposure, `claim_kinds` narrowing manual runs, `orders_queued` under-count, test date fixed at import, loose Sunday assertion, `worker2` missing from the deploy recreate list (the owner's deploy step must use `--no-deps --force-recreate api worker worker2 scheduler web`).

## Deviations
None by the integrator. Row 255 (scribe follow-ups: Word contents page numbers, owner's live checks) was already on the backlog.

## Load status
`aslms queue-status` timed out in the 120 s window on the busy dev database; not recorded.
