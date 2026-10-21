# portal-ui-dashboard-work (row 104, round 4 of 5)

Merge commit: 4c20c96 on main; tag `feature/portal-ui-dashboard-work-done`.

## What changed
- Backend: `GET /dashboard/me` gains `headline`, `upcoming`, `attention` (`backend/aslms/services/dashboard.py`). No migration, no table change (as-built note in `docs/schema/schema.md`).
- Frontend: dashboard (greeting, five headline numbers, Upcoming hearings, Needs your attention); Files, Search, Cause list, My profile on the Work list and Settings templates.
- 39 files changed.

## Gates
- ruff: All checks passed
- pytest: 1798 passed, 2 skipped (22m27s)
- docker compose build: succeeded
- portal smoke: passed
- git status clean; design note status approved; decisions-log entry and backlog row present

## Push and CI
Not pushed: no remote (`git remote get-url origin` fails). `gh` is not installed: CI status unknown.

## Review findings (advisory, both open, not fixed in this cycle)
1. `dashboard.py:506-511`: `file_received` omits only overdue/due-soon cases, not `confirm_next_date` ones, so a case can take two attention rows. Follow-up row 111.
2. `Headline.tsx:108-115`: `dayWords` gives no badge for a hearing 3-7 days ahead in the next calendar week (decision 23 wants a badge on every row). Follow-up row 111.

## Deviations
None beyond the design note's round 4 section.

## Follow-up rows
Row 111 `dashboard-work-followups` added.

## Load status
See `aslms queue-status` (not captured in this run).
