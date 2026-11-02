# Report: Close Case (row 207, `close-case`)

Merged 2 Nov 2026 as squash commit ed5814c on `main`, tag `feature/close-case-done`.

## What changed
- Backend: the grantable function Close Case (default for department heads and officers); close and reopen services and API (`POST /cases/{ref}/close`, reopen on the court's status change); the remark is an append-only note with an audit row and a timeline event; closing ends the file's movement and clears the pending action; the retired `closed` stage can no longer be set.
- Table: `case_closures`, with guard triggers (migration 0035, `0035_close_case.py`).
- Portal: Close Case and Reopen dialogs, rail and header states, Open / Closed switch on My Cases and Department, Ready to Close on With Me and the dashboard.
- Docs: design note, decisions log, process workflows, backlog, `CLAUDE.md` focus line. 83 files, +5160/-146.

## Gates
- CI on `main`: green, run 41346948748 (head of `origin/main` = 7f52af4).
- `ruff check .`: All checks passed.
- `pytest -q`: 3068 passed, 3 skipped, 255 warnings in 2076.49s (0:34:36). Every run green.
- `docker compose build`: succeeded.
- Screen check (private network, temporary images, runbook section 16): 170 routes and states, 407 screenshots, 0 findings; 542 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.

## Review findings and how each was closed
All three are advisories, none closed in the branch; recorded as row 213 `close-case-followups`.
1. Reopen-once trigger and `ck_case_closures_reopen_manual` leave `reopen_note_id` and `reopened_by_*` changeable on a still-open closure. The service never does this; a gap in the defence-in-depth guard only. Needs a new migration.
2. `ready_to_close`, `to_close` and the Ready to Close chip ignore the open-transfer condition that `close` enforces (409 `transfer_open`). Matches the wording of decisions 15, 21 and 22.
3. `max_length=2000` on the close remark and reopen reason answers 422 in place of 400 `bad_field` for API callers; custody send and recall behave the same.

## Deviations
None beyond those recorded in the design note.

## Follow-up rows
213 `close-case-followups`.

## Deploying
Deployed 2 Nov 2026 at 10:05 IST, after CI on `main` passed (run 41378146718: policy, backend, frontend, compose).
- Images built from a clean detached worktree of `main` at b82c10a (the main checkout was on the next cycle's branch),
  `aslms-web` and the backend images including `aslms-migrate`; `./backend` on disk checked equal to `main`.
- `docker compose stop api worker scheduler web pgbouncer` at 09:01 IST, then `docker compose --profile ops run --rm
  migrate`: preflight passed (dev, 7 warnings), the image matched `./backend` (migrations up to 0035), the pre-migrate
  backup written and listed, `0034 -> 0035`, seed 20 rows (`ref_permission` +2, `role_permissions` +18), audit row
  `system.migrated`. The backup took most of the hour, so the portal was down from 09:01 to 10:05 IST.
- `NAPIX_ENABLED=true docker compose --profile monitoring up -d --wait`; `init` reported the database at head (0035)
  and nothing left to seed; court data on in `api` and `worker`; `portal_smoke.py` passed; the worker resumed court
  calls (220 in the first 10 minutes); `case_closures` empty.

## Load status (`aslms queue-status`)
causelist_day done 410, skipped 262; dossier done 58,187, pending 25,012, skipped 27 (full table from the command; the load continues in the worker).

## Push
`main` and the tag are pushed fast-forward only; the result is in the integrator's return.
