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

## Deploy (14 Nov 2026 at 08:03 IST)
- CI green on `715f5bf` (run 43544404431) and on the docs commit after it. Images built from a clean `main`.
- `docker compose up -d --no-deps --force-recreate api worker worker2 scheduler web` with the court-data switch on; no migration.
- Checked: the switch on in `api`, `worker` and `worker2` (the scheduler carries none, by design); `worker2` logs "queue worker started (slot second, NAPIX on)" and "slot main" on `worker`; `worker` repaired 1 interrupted `queue-run` row at start; web build ID `C9tfsGBll97FcEQpD1kkg`; portal 307 to sign-in, API health 200.
- First pass of `worker2`: 59 order PDFs, 0 failed, then a wait for the hourly window (reserve 100). Throughput stays bound by the NAPIX hourly allowance; the second slot keeps order PDFs and short calls moving while a Current Status call is slow.
- Still to see: the first 22:00 `nightly-refresh` (Verification 5), the 20:00 status check alongside `worker2` (Verification 4), Sunday 02:00 (Verification 8).
