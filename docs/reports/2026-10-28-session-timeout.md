# Cycle report: session timeout (row 169), 28 Oct 2026

Design `docs/design/session-timeout.md` (approved). Built, tested and reviewed on its own branch beside row 188;
squash-merged on 28 Oct 2026.

## Migrations
- `0031_session_timeout` is kept exactly as built (down_revision 0030). Row 188's `0032` was applied to the dev
  database first, and the guard refuses edits to existing migration files, so a new merge migration
  `0033_merge_session_timeout` (down_revision `("0031", "0032")`, no schema change) joins the two into one head.
  `alembic heads`: 0033. `test_migration_0033.py` checks the single head, the parents and a cycle.
- **Deploying:** the `migrate` step applies 0031 then 0033 (the dev database is at 0032). Every user signs in again
  once after the deploy.

## Merge
Conflicts in `CLAUDE.md` (rows 188, 190, 197 kept, row 169 added), the decisions log (both sections kept),
`backend/aslms/cli/main.py` (assistant commands and the `sessions` group), `frontend/e2e/fixtures/index.ts` and
`frontend/e2e/uicheck.spec.ts` (both sides kept). Two integration fixes after the first full run:
`test_migration_0032_mode_check_up_down` asserted that 0032 is the head (now: 0032 is in the chain below the
head), and the new `sessions-sweep` beat job was missing from `NOT_DATA_COLLECTION` (row 172's plain schedule).

## Gates
- `ruff check`: clean. Full `pytest -q` on the merged tree: 2 failed (the two above), 2674 passed, 3 skipped;
  after the fixes the affected files (`test_assistant_ollama.py`, `test_plain_schedule.py`,
  `test_migration_0031.py`, `test_migration_0033.py`) 63 passed. CI runs the full suite on main.
- Frontend: lint, typecheck, e2e `tsc` clean; vitest 84 files, 1755 passed; `gen:api` no diff.
- Screen check on a private network against a `web` built from the merged tree: 428 passed, 7 skipped, 0 failed
  (134 routes and states, 0 findings). The shared stack was not touched.

## Review
Round 1: one blocking finding (an idle or limit sign-out recorded as a logout; fixed: the browser sends
`{reason}` and the web server only clears cookies) and four advisories, fixed on the branch.
