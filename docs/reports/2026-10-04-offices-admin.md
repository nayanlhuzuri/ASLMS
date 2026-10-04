# Report: offices-admin (2026-10-04)

Merge commit: 8b0552d on main; tag `feature/offices-admin-done`. Design note: docs/design/offices-admin.md (approved).

## What changed
- Services: `backend/aslms/services/offices.py` (offices tree, create/edit/deactivate, designations, first admins).
- API: `backend/aslms/api/routers/offices.py` (/admin/offices, designations, tree), schemas, security and access router tweaks.
- CLI: `backend/aslms/cli/offices.py`. Reference: `domain/reference.py`, `services/access_seed.py`.
- Tests: unit rules, db service tests, API tests (including 401, officer 403, admin scope, no audit on failures).
- Docs: decisions log, schema.md as-built lines, backlog, CLAUDE.md current focus. No new migration.

## Gates
- ruff check: All checks passed!
- pytest -q: 150 passed, 7 warnings
- docker compose build: succeeded (api, init, worker, scheduler)
- git status clean; design note status approved; decisions-log entry and backlog row present.

## Review findings (all advisory, none blocking; recorded, not fixed in this cycle)
1. Duplicate-code check is read-then-insert; a concurrent create returns 500 instead of 409 (offices.py ~284, ~464).
2. dependents() guard takes no lock; concurrent user/child creation can leave an active dependent under an inactive office (fix: SELECT FOR UPDATE).
3. access.set_enabled does not check the office is active, so re-enabling can undo the decision-7 invariant.
4. valid_from is not checked against valid_to or today; no DB check constraint.
5. config_changed events are scoped but carry no actor or office id, so scoped timelines cannot filter them.

## Deviations
None beyond those recorded in the design note.

## Follow-up backlog rows
Rows 17 and 18 added for the advisory findings (locking, 409 mapping, re-enable and validity checks; event actor and office id).

## Load status (queue-status)
causelist_day skipped 2; dossier done 2357, failed 11, pending 345, skipped 1; masters done 1; order_pdf pending 16688.
