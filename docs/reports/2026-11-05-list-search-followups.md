# Report: list-search-followups (row 201)

Date: 5 Nov 2026. Branch `feature/list-search-followups`, squash-merged into `main`, tag `feature/list-search-followups-done`.

## What changed
- `backend/aslms/services/matching.py`, `matching_rules.py`: the rescore dirty test compares a fingerprint of the rules; the run's cut-off is taken with `clock_timestamp()` just before the rules load (advisory 1).
- `backend/aslms/api/routers/matching.py`: `GET /admin/counsel-codes` checks `q` with `list_search.parse` (2 to 100 characters, else 400 `bad_q`) (advisory 2). `frontend/openapi.json` and `schema.d.ts` regenerated.
- `frontend/src/components/admin/mapping/CounselCodes.tsx`, `messages.ts`: deactivating a counsel code reloads Recommended From Cause Lists (advisory 3).
- Tests: `test_rescore_on_save.py`, `test_api_matching.py`, `mapping.test.tsx`. Docs: decisions log, design note, backlog, CLAUDE.md focus.
- No migration, no new table.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3183 passed, 3 skipped (44 min).
- `docker compose build`: succeeded (no `up` of any kind).
- Screen check on a private network (temporary `tmpls-*` web and uicheck images, removed afterwards): 173 routes and states, 416 screenshots, 0 findings; 551 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: latest run in progress (Hotfix status timeout), no failure.

## Merge notes
The squash merge conflicted once, in `docs/claude_ASLMS_design_decisions.md` (both sides appended at the end); resolved by keeping both appended sections unchanged.

## Review findings
None supplied for this cycle.

## Deviations
None beyond the log conflict above (the design note records its own fingerprint-timestamp deviation).

## Follow-up rows
None added.

## Load status (`aslms queue-status`, tail)
order_pdf done 201,080, pending 189,821, skipped 3; status_batch done 2,458, pending 6, running 2, skipped 7.

## Deployed
5 Nov 2026 at 14:52 IST. Images built from clean `main` at c8cbc97 (14:27; the later commit ed78ccd is documents only); CI run 41998336593 green (changes, policy, backend, frontend, compose, ci-ok). `up -d --wait` with the court-data switch on, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. Switch on in `api` and `worker`; web build ID matches the image (`MUg9OwY5DhqUxOhqh4Axt`); `rules_fingerprint` present in the running API; portal smoke passed. No migration. Verification 3 and 4 of the design (after deploy) are the owner's.
