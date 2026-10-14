# Report: portal-audit-health (backlog row 41)

Merged 14 Oct 2026 as a54b8fb on main; tag `feature/portal-audit-health-done`. Design: docs/design/portal-audit-health.md (approved).

## What changed
Frontend only; no migration, table, endpoint or backend change. 28 files.
- Pages: `/audit` (newest 50 first, More, filters in the URL) and `/audit/[id]` (entry page, before/after table, related-entry links).
- Components in `frontend/src/components/audit/` (AuditSearch, AuditFilters, AuditTable, AuditEntry, BeforeAfter); helpers in `lib/audit.ts`; `readsAudit` in `lib/can.ts`; messages, routes, hooks and types extended; IST time to the second in `lib/format.ts`.
- "Audit trail" links on the case page (CaseFrame), user page (UserDetail) and office page (Offices), shown to audit readers only.
- Tests: audit.test.tsx, audit.test.ts, plus additions to admin, case, format and routes tests.

## Gates
- ruff check: All checks passed
- pytest -q: 1063 passed, 89 warnings (20m10s)
- docker compose build: succeeded
- portal smoke (web service): portal smoke: passed
- git status clean on branch; design status approved; decisions-log entry (14 Oct 2026) and backlog row present.

## Review findings
1. Advisory, `can.ts` readsAudit: the super_admin branch accepts `audit.view` from the union of functions, while the API requires it in the State-wide membership. Nothing leaks (the API returns 403); links could show with no access. Not fixed in this cycle; follow-up row 72.
2. Advisory, `audit.test.tsx`: refusals `case not_found`, `bad_office`, `bad_period` are tested only through pure `fieldOfError`, not at component level. Follow-up row 72.

## Deviations
None beyond those recorded in the design note's deviations section.

## Follow-ups
Row 71 (audit-followups, from approval) and row 72 (the two advisories above).

## Load status (queue-status, excerpt)
order_pdf: done 25482, failed 3, pending 224515, skipped 134. status_batch: done 253, failed 1, skipped 5.
