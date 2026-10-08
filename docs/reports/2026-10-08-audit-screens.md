# audit-screens (2026-10-08)

Design: docs/design/audit-screens.md (approved by the owner on 2026-10-08).

## What changed
- Migration 0013 (audit indexes; no new table; schema.md extended).
- API: audit log search (`/audit`, super admin and Auditor type, reading not audited), `/admin/data-health`,
  `/admin/napix/*` (health check, re-fetch order and sync buttons that only enqueue).
- Services: `audit_search`, `data_health`, `napix_admin`; shared daily-cycle helpers in `reporting_common`;
  `queue.get_state`; setting `NAPIX_HEALTH_CHECK_MIN_SECONDS`; function labels in `access_seed`.
- CLI: `aslms audit`, `aslms data-health`; `aslms refetch-case` now needs a case already in the database (deviation 3).
- Tests: test_api_audit, test_api_napix_admin, test_audit_search, test_data_health, test_migration_0013,
  test_audit_search_unit.

## Gates
- ruff check: All checks passed!
- pytest -q: 771 passed, 67 warnings in 564.87s
- docker compose build: succeeded (api, worker, init, scheduler)
- git status clean; design note status approved; decisions-log entry and backlog row present.

## Review findings (all advisory; none blocking, none fixed in this cycle)
1. `refetch_order` does not lock the order row; a concurrent order_pdf run can leave status pending with a stored PDF.
2. `check_guard` has no lock; the one-check-per-minute limit does not hold under concurrency.
3. `health_check` catches only IntegrationError and httpx.HTTPError; other exceptions skip the log flush and audit row.
4. `data_health.snapshot` does not turn QueryCanceled (statement timeout) into a coded 503.
5. Hour block uses a UTC hour cut in Python while `latest_remaining` uses the database timezone hour.
6. `aslms refetch-case` no longer fetches a CNR absent from the database (deviation 3, not yet in the decisions log).
All six are carried to backlog row 42 (audit-screens-hardening).

## Deviations
Deviation 3 above, recorded in the design note; the decisions-log entry is part of row 42.

## Follow-up rows
42 audit-screens-hardening (findings 1-6). Row 41 portal-audit-health already exists.

## Load status (`aslms queue-status`)
dossier: done 18713, failed 133, pending 536, running 1, skipped 23; causelist_day: done 41, pending 573, skipped 29;
order_pdf: pending 141192; status_batch: done 57, skipped 3; masters: done 1.
