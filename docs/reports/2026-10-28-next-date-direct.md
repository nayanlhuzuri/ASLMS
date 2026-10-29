# Report: next hearing shown directly from the latest court order (row 199, `next-date-direct`)

Merged 29 Oct 2026 as commit 1ad4f18 on `main`, tag `feature/next-date-direct-done`. Design: `docs/design/next-date-direct.md` (approved).

## What changed
- 135 files (7,730 insertions, 1,308 deletions): backend services (`next_hearing.py` new, `next_dates.py`, `alerts`, `inbox`, `case_search`, `assistant*`), API routes `POST /next-dates/{id}/report`, `/correct`, `/keep`, portal components (HearingDate, nextdates, case page, dashboard, filters), tests, docs.
- Migration 0034 `next_date_direct`: six derived columns on `cases` (`next_hearing_on`, basis, ids, differs fields, `next_hearing_set_at`), three CHECKs, one index and two partial indexes; reference data (event type, functions `next_dates.report_wrong`, `next_dates.correct`).
- CLI: `aslms next-dates direct` (dry run, `--apply`) and `hearing-refresh`.

## Gates
- ruff: All checks passed.
- pytest: 2944 passed, 3 skipped (44 min 42 s), all green.
- `docker compose build`: succeeded.
- Portal smoke (frontend changed): passed.
- git status clean; design status approved; decisions-log entry and backlog row present.
- CI on main before merge: head run 40730566242 completed success.

## Push and CI
Pushed after the report commit (see the integrator's return value).

## Review findings and closure
- Blocking 1 (court-only next hearing on rows the caller cannot open): closed in f69fcb0.
- Blocking 2 (repeat report after a closed alert raises no alert): closed in f69fcb0.
- Advisories (basis line wording, corrected date superseded at once, step 3 ordering, step 2 older reading, correctors loop, whole-table locks in `direct --apply` and `refresh_all`, `confirmed` in the Case Details source): not closed here; follow-up row 203.

## Deviations
None beyond the design's recorded deviations.

## Deploy steps (owner)
Apply 0034 with the `migrate` step, `docker compose build`, then `aslms next-dates direct` (dry run, then `--apply`) in a quiet window (it locks live cases; see row 203 item 6).

## Load status
`aslms queue-status` did not return within the time given at merge; not recorded.

## Deploying
Screen check on a private network against a `web` built from the merged tree (the shared stack untouched):
458 passed, 7 skipped, 0 findings (144 routes and states). CI on `main` passed (run 40784535259).

Deployed on 29 Oct 2026: images built; api, worker, scheduler, web and pgbouncer stopped at 07:25; `migrate`
0033 -> 0034 (seed 21 rows, audit row `system.migrated`) by 07:46; `up` with the court-data switch (`init` exited 0,
switch checked true in api and worker). With the worker and scheduler stopped (review advisory 4):
`aslms next-dates direct` dry run (941 suggestions shown directly, 1 left to expire, no enter items, no manual date
superseded, no conflicts), then `--apply` at 07:48 (83,203 cases refreshed, so `hearing-refresh --all` was not
needed). `aslms next-dates status`: next hearing by basis none 64,874, court 17,497, around 472, order 359,
confirmed 1; 100 flagged; none left to compute. Worker and scheduler started again; `portal_smoke.py` passed.

The integrator had rebuilt `web` alone at 04:27 for its smoke check, so from then until 07:25 the portal ran the
new screens on the earlier api. The tester's and integrator's instructions now use the private-network screen check
and never recreate a service of the shared stack.
