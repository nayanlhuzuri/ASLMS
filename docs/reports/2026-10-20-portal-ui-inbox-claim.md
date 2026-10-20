# portal-ui-inbox-claim (backlog row 102, round 2 of 5)

Merge commit: b61261e on main; tag `feature/portal-ui-inbox-claim-done`. Design: docs/design/portal-ui-redesign.md (approved).

## What changed
- Frontend: Case inbox (Working on, Files with me, Claimed by me, Disposed, Department cases) and Case claim (Recommended, Unclaimed pool, Transfers to us) with the case details modal (frontend/src/components/claim/, components/inbox/); old inbox URLs redirect.
- Backend, read-only: `GET /inbox/mine`, `/inbox/mine/counts`, `/inbox/claimed` filters (unallotted, stage, holder, action), `whole_department` on `/inbox/counts`, `transfer_in` sight basis (services/ownership.py, visibility).
- No migration, no table or endpoint-write change. Round-1 fix: closing Dialog/Modal/SidePanel is inert during exit.

## Gates
- ruff check: All checks passed
- pytest: 1681 passed, 2 skipped (run with postgres published on 5433 via compose.dev.yml; the plain compose service is not reachable from the host, which made a first run skip 878 database tests; that run was discarded)
- docker compose build: succeeded
- portal smoke: passed
- git status clean; design note status approved; decisions-log entry and backlog row present.
- CI on main: CI status unknown (no remote `origin`, no `gh`).

## Push
Not pushed: no remote.

## Review findings (all advisory) and closure
1. CaseModal.tsx 171-172: open_transfer taking precedence over the clicked row. Not fixed in this cycle; follow-up row 107.
2. OrderRow.tsx: only first 50 orders, no pager. Follow-up row 107.
3. ownership.py 1229-1238: transfer_in check lacks cases.view_scope. Follow-up row 107.
4. ModalActions.tsx inFlight guard has no test. Follow-up row 107.
5. ClaimFrame.tsx push vs replace leaves duplicate history entry. Follow-up row 107.

## Deviations
Postgres container recreated with compose.dev.yml to publish port 5433 for the test run.

## Load status (queue-status)
order_pdf done 87990, pending 213854, skipped 4; status_batch done 789, running 1, skipped 6.
