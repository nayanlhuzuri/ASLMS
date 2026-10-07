# user-memberships (backlog row 28) - report of 2026-10-07

Merge commit on main: f13002f (squash of feature/user-memberships, 9 commits); tag `feature/user-memberships-done`.

## What changed
- 75 files, +9321 / -695. Migration 0008 (`0008_memberships.py`): membership and admin ticket tables, seed rows
  (`users.propose_head`, `admin.tickets`, `admin_ticket`, `government_order`), back-fill of memberships from users.
- Services: `memberships.py` (add, end, swap, exit items and fingerprint, eligible targets), `tickets.py` (head-change
  tickets, KINDS registry, approve, documents), `visibility.py` (union over memberships, document rule per membership),
  `access.py`, `ownership.py` (reallot on exit), `offices.py`, `users.py`.
- Endpoints: membership administration under `/admin/users/{id}/memberships`, `/admin/users/lookup`, `/admin/tickets/*`
  (head-change, counts, approve, documents), `/me` with memberships; CLI `aslms users` (replace-super-admin, memberships end).
- 28 test files touched; 28 unit/db tests added or changed.

## Gates
- ruff check: All checks passed.
- pytest -q: 482 passed, 30 warnings (361 s).
- docker compose build: succeeded (api, worker, init, scheduler).
- git status clean; design note status approved; decisions-log entry and backlog row present.

## Review findings and closure
Closed on the branch before merge:
- Blocking: document rule ANDed case visibility and record setting across different memberships; fixed in commit
  55b4f5f (rule per membership, case, record setting and function from the same membership).
- Blocking: department admin could add a membership to a disabled login and gain control of it; fixed in commit 23f6102
  (only the super admin adds or reactivates on a disabled login, 409 `login_inactive`).
- Deterministic audit ordering in tests (f3b050a); downgrade guard tests and deviations written back into the design note (07bae22).

Not closed, advisory, carried to backlog row 31 (memberships-hardening):
- State-tier membership exit scope is the State root with no eligible targets (reported three times).
- Exit items computed before case locks; allot-versus-exit race gives 500 instead of 409 stale_exit / ticket_stale;
  stale guard reads an unrefreshed in-memory row.
- update_profile designation change writes no membership.updated audit row.
- approve does not re-check users.propose_head; no path to propose a directorate or unit officer as head.
- Malformed doc_date / files in the multipart request answer 500 instead of 400 bad_field.
- CLI `users create --type dept_head` bypasses the head-change service; CLI end recomputes the fingerprint.
- attach/archive document do not lock the ticket row.
- departments_without_head uses NOT IN over a subquery that can hold NULL.
- 0008 downgrade leaves the seed permission rows.
- Missing tests: facts-only preview for a file held in another department; counsel plus officer document rule.

## Deviations
- Advisory findings above were not fixed in this cycle (the task named them for the report); none is a blocking item.

## Follow-up rows
- 31 memberships-hardening (new); 29 memberships-mirror-drop and 30 admin-ticket-kinds already present.

## Load status (queue-status)
dossier: failed 85, pending 835, skipped 9; masters done 1; order_pdf pending 72213; status_batch done 1, failed 4
(historical load still running in the Compose worker; head of the table not captured).
