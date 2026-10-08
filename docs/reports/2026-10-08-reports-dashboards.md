# Report: reports-dashboards (backlog row 9)

Merged to `main` as 772b9f5, tag `feature/reports-dashboards-done`, 2026-10-08.

## What changed
- Services: `dashboard.py` (personal, department, State blocks), `reports.py` (four reports), `report_export.py`
  (Excel in memory, PDF with paginated tables), `reporting_common.py`; `custody.summary_for` extended additively
  (`with_pending_action`, `pending_no_due_date`, `by_holder_office`).
- Endpoints: `/dashboard` (personal, department, State) and `/reports` (pending-cases, hearings-disposals,
  pending-actions, data-health; Excel / PDF export).
- CLI: `aslms reports`. Config: report limits in `core/config.py`.
- Database: migration 0012 (report indexes only; no new tables), `docs/schema/schema.md` updated.
- Tests: test_dashboard, test_reports, test_api_dashboard, test_api_reports, test_migration_0012,
  test_reports_unit; support module `report_support.py`.
- Docs: design note (approved), decisions log entry, backlog.

## Gates
- ruff check: All checks passed!
- pytest -q: 731 passed, 65 warnings in 723s
- docker compose build: succeeded (init, api, worker, scheduler)
- git status clean; design note status approved; decisions-log entry and backlog row present.

## Review findings (both advisory, not fixed in this cycle)
1. Department block `pending_actions.due_soon`/`overdue` use `summary_for` totals, which include held files with a
   due date but no pending action (for example after the exit step), while `held`, the overdue list and the State
   row do not. Follow-up row 40.
2. `department_block` checks section gates against the first eligible membership in the department only, so a
   person with two memberships there may miss a section. Follow-up row 40.

## Deviations
16 deviations are listed in the design note and summarised in the decisions log (primary-ownership counts, in-memory
Excel, own PDF pagination, additive `/custody/summary` fields, `data-health` date pair, merged duplicates left out).

## Follow-up rows
- 40 `reports-hardening` (the two advisories above). Row 39 `portal-reports` already existed.
- Before deployment: `alembic upgrade head` on the dev database (0012).

## Load status (`aslms queue-status`)
causelist_day: done 38, pending 578, skipped 27. dossier: done 17806, failed 191, pending 193, skipped 21.
masters: done 1. order_pdf: pending 134951. status_batch: done 22, skipped 1.
