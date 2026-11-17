# Order sections review advisories (row 264), integrator report

Merged 17 Nov 2026 as one squash commit on `main`, tag `feature/order-sections-review-advisories-done`. Design: `docs/design/order-sections-review-advisories.md` (approved 16 Nov 2026). No migration (row 250 carries 0038).

## What changed
- `backend/aslms/services/order_parse.py`: parser version 2; `Linked Case :` blocks of a `whole` reading end where they end; `PageMap.page` before the first printed marker counts the form feeds.
- `backend/aslms/services/order_sections.py`: light runs of the 5-minute job and a daily 01:30 IST full check; isolated status parts; re-extraction found by `created_at` against `document_text.updated_at`; reading states; open `order_parse` failures resolved when the text goes and no traceback every 5 minutes.
- Frontend: Orders tab by the server's reading state ("Text Could Not Be Read", "Not Read Into Parts"), partial order checks on Data Collection, labels, generated API types.
- Docs: design note and row 250 measurements, decisions log, backlog, runbook, process workflows, Word guides. New test fixtures under `backend/tests/fixtures/orders/`.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3638 passed, 3 skipped (44 min 34 s); no failure in the run.
- `docker compose build`: succeeded (build only, no `up`).
- Screen check (private network, `web` and `uicheck` images built from the branch, runbook section 16): 184 routes and states, 594 screenshots, 0 findings; 866 passed, 14 skipped; temporary containers, network and images removed.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (run 43828899715). `origin/main` equalled local `main` before the merge.

## Review findings
All three reviewer findings were advisories, left open and recorded as row 266: (1) the last linked block with no coram and no `Advocate for` line takes in body text, and `assert_invariants` does not check the invariant; (2) the full check's retry pass hashes every reading twice while a failure is open; (3) Deviation 4's wording is wrong, an overlapping run also runs the full check (data correct, scan cost doubled). Finding 1 needs a further PARSER_VERSION bump if fixed after the backfill.

## Deviations
None beyond those in the design note (Deviation 4 is corrected by row 266 point 3).

## Follow-up rows
266 `order-sections-review-advisories-review` (new). Row 265 (measurements after the backfill, rendered page numbers, owner checks) was already added by the scribe.

## Load status
`aslms queue-status` was started but had not answered within 2 minutes (the worker is busy with the historical load); not recorded here.

## Push
See the final return of the cycle: `main` and the tag are pushed with the two fixed forms when the remote accepts them.

## Deploy
Deployed 17 Nov 2026 together with row 264 (owner's confirmation (d) of row 264), from `main` at 716b001 after CI was
green (the compose job's first try lost its network during `npm ci` and passed on a rerun).
- 23:00 IST: `api`, `worker`, `worker2`, `scheduler`, `web` and `pgbouncer` stopped; `napix_call_log` held 579,170 rows.
- `docker compose --profile ops run --rm migrate`: preflight passed (dev, 7 warnings), backup
  `20261117-2300-pre-migrate` written and listed by `pg_restore`, 0037 -> 0038, seed nothing to insert, audit row
  `system.migrated`. Done at 23:28.
- `up -d` with the court-data switch, then `--no-deps --force-recreate api worker worker2 scheduler web`: the switch on
  in `api`, `worker` and `worker2`, both workers "NAPIX on", `/signin` 307, `/api/health` 200, the running web
  `BUILD_ID` equals the image's. Portal down 23:00 to 23:29.
- `aslms orders parse --dry-run --limit 3000`: 2,967 template, 33 whole, no failure, 1.98 s per 1,000.
- `aslms orders parse --backfill` 23:30 to 23:53: 269,999 read at version 2, 0 failed. `aslms orders status`:
  `parser_version` 2, `read` = `orders_with_text` = 269,999, `waiting` 0, `failed` 0, `timed_out` empty. No version 1
  row. No court call from the backfill (the 904 calls in the window were the queue's CNR fetches).
- Measurements (table 672 MB, the times of decision 14, all inside budget) are in `docs/design/order-sections.md`,
  "Measurements".
