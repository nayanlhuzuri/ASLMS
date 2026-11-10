# Report: data-collection-redesign-tabs-followups (row 204)

Date: 10 Nov 2026. Branch `feature/data-collection-redesign-tabs-followups`, squash-merged into `main` (commit 6b97ae6), tag `feature/data-collection-redesign-tabs-followups-done`.

## What changed
- `backend/aslms/services/data_load.py`: Collect These and fetch-details put a case without details back in the request lane even when its dossier row is `done`, and the count reports only what waits (running rows counted honestly).
- `backend/tests/db/test_api_data_load.py`, `backend/tests/db/test_data_collection_gaps.py`: new tests, including one that drives the real statement timeout (QUERY_CANCELED through `with_timeout` / `_timed`) to a 503 `search_timeout`.
- Design notes (`data-collection-redesign-tabs-followups.md`, `data-collection-redesign-tabs.md`): the owner's live role checks recorded in Verification (Central Operator and Super Administrator).
- Decisions log entry, backlog row 204, CLAUDE.md current focus.
- No tables, no endpoints added, no migration, no frontend change.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3209 passed, 3 skipped (58 min 51 s), every run green.
- `docker compose build`: succeeded. Frontend unchanged, so the screen check was not required.
- `git status` clean on the branch; design note status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: success (run 42788140033).
- `main` moved during the test run (docs-only commits 7ceee0b and ad21832). The squash conflicted in `CLAUDE.md` and `docs/claude_ASLMS_design_decisions.md`; both were resolved by keeping both sides (main's text plus this row's lines). Code was unaffected.

## Review findings
- Advisory (repeat re-fetches of cases the court never returns details for can use the shared hourly quota; accepted by decision 1): not fixed here, parked as backlog row 237 `collect-these-repeat-limit`, which needs an owner decision on the interval.

## Deviations
None beyond the docs-only conflict resolution above.

## Follow-up rows
- 237 `collect-these-repeat-limit`.

## Load status (`aslms queue-status`)
causelist_day done 414 / skipped 266; causelist_recheck done 6 / skipped 11; dossier done 71,554 / pending 12,197 / skipped 51; masters done 1; order_pdf done 208,159 / pending 184,959; status_batch done 2,916 / skipped 8.

## Push
See the final return of the integrator (pushed commit and CI run address).

## Deployed
10 Nov 2026 at 16:16 IST. Images built from clean `main` at 87d28e0; CI run 42798686306 green (changes, policy, backend, frontend, compose, ci-ok). `up -d --wait` with the court-data switch on, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. Switch on in `api` and `worker`; mail still to Mailpit; web build ID matches the image (`voWoRgEwrG4P8IuLgy43X`, frontend unchanged); the new fetch-details code is in the running api; portal smoke passed. No migration. Verification 4 of the design (the live role checks) is the owner's.
