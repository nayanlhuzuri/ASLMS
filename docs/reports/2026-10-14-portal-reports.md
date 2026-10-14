# Report: portal-reports (backlog row 39)

Merged to `main` as commit 67948c4, tag `feature/portal-reports-done`.

## What changed
- 35 files, no migration, no new tables.
- Portal: Reports screen with a tab per report the caller may run (pending cases, hearings and disposals, pending actions, data-collection health); scope (Whole State or a department), period presets, parameters in the URL, Excel and PDF downloads after the on-screen report, files list 50 per page. Files: `frontend/src/lib/reports.ts` (+ test), `frontend/src/components/reports/ReportPage.tsx`, `ReportView.tsx`, `routes.ts`, dashboard and data-health links.
- API (read-only additions): department names in `GET /reports`; 503 `report_timeout` (`backend/aslms/api/routers/reports.py`, `schemas.py`, `services/reports.py`). Tests extended in `tests/db/test_api_reports.py`, `test_reports.py`.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1063 passed, 89 warnings (20m07s).
- `docker compose build`: succeeded.
- `portal_smoke.py`: portal smoke: passed (all four /reports/* pages 200).
- `git status` clean; design status `approved`; decisions-log entry and backlog row present.

## Review findings
Both advisory, not fixed in this cycle (carried to row 70 follow-ups, see below):
1. `ReportView.tsx` page offset (SectionTable state keyed only by section key) is not reset when different rows are shown in the same mounted view; Back to a cached report can show an empty table at offset beyond the rows. Fix: key ReportView by the query string or reset offset on rows change.
2. `reports.ts` `reportParams` (hearings-disposals) sends a lone `from` or `to`; the API answers a FastAPI 422 instead of `bad_period`. Fix: fall back to the this-month default.

## Deviations
None recorded by the integrator beyond those in the design note.

## Follow-up rows
- Row 70 `reports-followups` (snapshots, scheduled e-mail reports, call-history retention) already exists. The two advisory findings above are recorded here and in row 70's scope for the next pass.

## Load status
queue-status (14 Oct 2026): causelist_day done 130 / pending 431; dossier done 39592 / failed 557 / pending 137; order_pdf done 25018 / pending 222317 / failed 3; status_batch done 253.
