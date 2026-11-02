# Report: Case Inbox follow-ups (row 208, `case-inbox-simplify-followups`)

Merged 2 Nov 2026 as squash commit eac2a5f on `main`, tag `feature/case-inbox-simplify-followups-done`.

## What changed
- Frontend only, no migration, no table, no endpoint: `frontend/src/lib/routes.ts`, `lib/filters.ts`, `components/files/Held.tsx`, `components/inbox/Redirects.tsx`, and tests in `routes.test.ts`, `inbox.test.tsx`, `cases-list.test.tsx`, `sort.test.tsx`.
- Clear All on the tracker-only Department list keeps `department` fixed.
- The tracker's Overdue chip (`action=overdue`) counts as an active filter: the no-matches state and Clear All appear.
- Old My-Cases-bound addresses carrying `action=overdue` redirect to With Me with `overdue=true`.
- Docs: design note, decisions log, backlog, `CLAUDE.md` focus line.

## Gates
- CI on `main`: green, run 41378146718 (head of `origin/main` = b82c10a).
- `ruff check .`: All checks passed.
- `pytest -q`: 3068 passed, 3 skipped, 255 warnings in 2834.23s (0:47:14). Every run green.
- `docker compose build`: succeeded (no service recreated).
- Screen check (private network, temporary images, runbook section 16): 170 routes and states, 407 screenshots, 0 findings; 542 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.

## Review findings and how each was closed
One advisory, not closed in the branch; recorded as row 214.
1. `myCasesTarget` carries `department` into the With Me address, but With Me's list has no department field, so it is ignored silently. No data is exposed (the server decides the list; design decision 3 accepts the changed meaning). Dropping `department` in the With Me branch would make the address honest.

## Deviations
None.

## Follow-up rows
214 `case-inbox-simplify-followups-2`.

## Pushed
See the final return of the integrator: `main` and the tag pushed fast-forward only.

## Load status
`aslms queue-status` did not answer within the 120 s limit while the dev worker was busy with the historical load; not recorded.
