# Report: causelist-day-gap-sweep (row 200)

Date: 2 Nov 2026. Design: `docs/design/causelist-day-gap-sweep.md` (approved 30 Oct 2026). Branch `feature/causelist-day-gap-sweep`, squash-merged to `main`, tag `feature/causelist-day-gap-sweep-done`.

## What changed
- New `backend/aslms/services/causelist_gaps.py`: the 04:15 sweep queues, in the load lane, every day of the collection period with no `causelist_day` row; idempotent; recorded in `job_runs`; scheduler start-up catch-up for days missed while the machine was off.
- Edits to `services/data_load.py`, `job_repair.py`, `queue.py`, `schedules.py`; CLI `aslms data-load gaps` (dry run) and `aslms data-load status` naming "Days Not Asked For".
- Data Collection Overview block and the Automatic Collection 04:15 entry (frontend: `Overview.tsx`, `AutomaticCollection.tsx`, `dataCollection.ts`, messages, CSS, OpenAPI and generated types, e2e fixtures).
- Documents: `docs/schema/schema.md`, `docs/operations.md` section 22, `ASLMS_Process_Workflows.md`, the two Word guides and their build scripts, decisions log, design note.
- No migration, no new table.
- Tests: `tests/db/test_causelist_gaps.py` (new), updates to the overview, freshness, status-line and ops unit tests; frontend `collection.test.tsx`.

## Gates
- Branch contained only row 200 commits (4 commits); `git status` clean; design status `approved`.
- CI on main: `gh run list --branch main --limit 1` is `completed success` (run 41395902944); `origin/main` equals local `main` before the merge.
- `ruff check .`: All checks passed.
- `pytest -q`: 3099 passed, 3 skipped (45 min 23 s), every run green.
- `docker compose build`: succeeded (no `up` of any kind was run).
- Screen check (private network `tmpgap-net`, images `tmpgap-web` and `tmpgap-uicheck` from the branch): 170 routes and states, 407 screenshots, 0 findings, 542 passed, 7 skipped. Container, network and images removed.
- Definition of done: decisions-log entry and backlog row present.

## Review findings
Both advisories, neither blocking, are not fixed in this branch and go to row 215:
1. The failed `job_runs` row is rolled back with the caller's session when the sweep re-raises (`causelist_gaps.py:232-236`); disposed-refresh has the same pattern.
2. The start-up catch-up lower bound `max(today - window, collection_start)` skips yesterday when the only rows are today's or tomorrow's (cosmetic; the 06:30 run covers it).

## Deviations
None beyond those recorded in the design note.

## Follow-up rows
- 215 `causelist-day-gap-sweep-followups` (the two advisories above).

## Push
See the final return of the integrator: `main` and the tag are pushed fast-forward only when the remote accepts.

## Load status (`aslms queue-status`)
dossier: 63,918 done, 19,265 pending, 43 skipped; order_pdf: 200,734 done, 188,929 pending; status_batch: 2,017 done, 6 skipped; masters 1 done; causelist_recheck 7 skipped.

## Deployed
Deployed 2 Nov 2026 at 14:42 IST, after CI on `main` passed (run 41414656425: policy, backend, frontend, compose). No
migration and no `.env` change (`CAUSELIST_CATCHUP_DAYS` defaults to 7). Images built from the clean `main` checkout at
5d6fc77; `docker compose --profile monitoring up -d --wait` with the court-data switch on recreated the app services,
then `api`, `worker`, `scheduler` and `web` once more with `--no-deps --force-recreate`; court data on in `api` and
`worker`; the running `web` has the image's build ID; `portal_smoke.py` passed. The scheduler started the catch-up
(`trigger start`, 26 Oct to 3 Nov 2026, nothing to queue) and lists `aslms.causelist_gap_sweep`; `aslms data-load gaps`
(dry run): collection period 2025-01-01 to 2026-11-01, days not asked for: none.
