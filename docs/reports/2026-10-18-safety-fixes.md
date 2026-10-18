# Report: safety-fixes (backlog row 76), 18 Oct 2026

Merged to `main` as a squash commit (tag `feature/safety-fixes-done`). Design: `docs/design/safety-fixes.md` (approved).

## What changed
- 41 files, 1761 insertions, 102 deletions. No migration, no new tables.
- Database roles: api, worker and scheduler connect as `aslms_app`; password set from `.env` by `aslms db-roles` (`backend/aslms/cli/db.py`); `compose.yml` and `.env.example` updated.
- NAPIX recovery of empty-200 responses; shared failure recording in `services/source_failures.py`.
- Advocate searches capped, case rows stored in the background; frontend search screen and `schema.d.ts`/`messages.ts` updated.
- Tests: `tests/db/test_app_role.py`, `test_safety_fixes.py`, `test_safety_fixes_search.py`, `tests/unit/test_db_roles_command.py`, `test_safety_fixes.py`, frontend `search.test.tsx`.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1353 passed, 102 warnings (22m07s).
- `docker compose build`: succeeded.
- Portal smoke (frontend changed): passed.
- Branch clean; design status approved; decisions-log entry and backlog row present.

## Review findings (all advisory) and closure
1. `_set_password` sends `ALTER ROLE ... PASSWORD '<literal>'`; the server may log it on failure or under `log_statement`. Not fixed in this cycle. Follow-up: hash client-side (SCRAM verifier via `encrypt_password`). Added as backlog row 81.
2. api, worker and scheduler still load all of `.env` (including `POSTGRES_PASSWORD`). Handed to row 16 (per-service env files or blanked variables). Row 82.
3. `sourcetrace_ingest.py` keeps its own `source_failures` upsert, contradicting decision 10 and the schema.md text. Row 83.
4. The aslms_app flow test does not run the beat jobs that delete or upsert (rescore-dirty, dedupe sweep, extract-text, notifications, discovery, OTP expiry). Row 84: add a pass under `app_engine`.

## Deviations
None beyond those recorded in the design note; the review findings above are open advisories, not blockers.

## Follow-up rows added
81 to 84 (see above). Rows 79 and 80 were added earlier by the cycle.

## Load status (`aslms queue-status`)
order_pdf done 46161, pending 255507; status_batch done 498, failed 1, skipped 6; dossier skipped 19; masters done 1.
