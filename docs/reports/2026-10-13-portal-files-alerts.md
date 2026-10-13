# Report: portal-files-alerts (backlog row 55)

Date: 2026-10-13. Merged to `main` as `ab55d75`, tag `feature/portal-files-alerts-done`. Design: `docs/design/portal-files-alerts.md` (approved by the owner 13 Oct 2026, now `built`).

## What changed
- Frontend (`frontend/src/components/files/`, `alerts/`, routes under `/files/*` and `/alerts*`):
  - Files frame with tabs With me, My offices, Department files (tracking summary) and Sent.
  - Alerts list with filters, Mark read, Mark all read, Acknowledge and Done.
  - Hearing calendar with a 7-day agenda and a month grid.
  - Navigation entries, header bell link, dashboard links.
  - A move that hides the case goes to `/files/sent`.
- Backend: one read-only addition, `case_visible` on alert items and the dashboard alert list (`services/alerts.py`, `services/dashboard.py`, `api/schemas.py`).
- Tables: none. Migration: none. New endpoints: none.

## Gate outputs
- `ruff check .`: All checks passed.
- `pytest -q`: 925 passed, 71 warnings (941 s).
- `docker compose build`: succeeded (web, api, worker, init, scheduler).
- `portal_smoke.py` against the running `web` service: portal smoke: passed.
- `git status`: clean on the branch. Design status was `approved` at the gate and is set to `built` on `main`. The decisions-log entry and the backlog row exist.

## Review findings (both advisory, left open)
1. Held.tsx:193 uses the department-tracking 403 text for every held scope, where design decision 16 meant it for the Department files tab only. Only visible when a login loses `cases.view_scope` while its cached `/me` still shows the tabs. Not fixed in this cycle.
2. Calendar.tsx:170-178 uses `keepPreviousData`, so after a State-wide reader switches department or month, the previous data stays on screen until the new request returns. Not fixed in this cycle.

Both are carried as follow-up rows (see below).

## Deviations
None from the design note.

## Follow-up rows
Backlog row 58 portal-files-alerts-followups holds both advisory fixes.

## Load status (`aslms queue-status`)
- dossier: done 28952, failed 410, pending 234, running 1, skipped 29.
- order_pdf: done 22269, failed 5, pending 175751, skipped 47.
- status_batch: done 194, failed 1, skipped 3. masters: done 1. causelist_day skipped 59 (earlier rows not shown in the tail).
