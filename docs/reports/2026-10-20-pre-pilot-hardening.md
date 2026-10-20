# Pre-pilot hardening (backlog row 94), 2026-10-20

Design: docs/design/pre-pilot-hardening.md (approved). Branch feature/pre-pilot-hardening, squash-merged to main.

## What changed
No migration, table, endpoint, permission or audit action. Files: backend/aslms/services/{backups,preflight,store_check,ops_metrics}.py,
backend/aslms/cli/{main,ops,db}.py, backend/aslms/core/config.py, compose.yml, infra/pgbouncer/{Dockerfile,entrypoint.sh,healthcheck.sh},
infra/prometheus rules and tests, Grafana dashboards, docs/operations.md, decisions log, tests (unit and db).
- Backup export transaction sets idle_in_transaction_session_timeout = 0 locally.
- APP_ENV accepts only dev, test, prod; the root CLI callback reports an unknown value as one line.
- init runs a document-store writability check and prints the remedy.
- WorkerStalled liveness from the latest claimed row.
- Role passwords sent as SCRAM verifiers.
- libpq 17+ floor; PgBouncer pinned, healthcheck logs in; wider session-feature scan.

## Gates
- ruff check: All checks passed.
- pytest -q: 1512 passed, 2 skipped (27 min).
- docker compose build: succeeded. frontend unchanged, so the portal smoke was not required.
- git status clean; design status approved; decisions-log entry and backlog row 94 present.
- Manual: `APP_ENV=production aslms ops preflight` prints `preflight fatal: APP_ENV: must be dev, test or prod`.

## Review findings and closure
1. Blocking, traceback instead of clean APP_ENV message: closed by commit 3bf574a (root callback reports unknown APP_ENV); verified live.
2. Blocking, test patched only ops.get_settings: closed in the same commit; the check now runs through the main app.
3. Advisory, store-check remedy when /data itself is root-owned (two findings): not closed; follow-up.
4. Advisory, probe file left after a write error (ENOSPC): not closed; follow-up (move os.remove into finally).
5. Advisory, three test_discovery_run tests failed once alongside concurrent runs, passed in two clean full runs and in this gate run: watch for flakiness.

## Deviations
None beyond those in the design note.

## Follow-ups
Added to the backlog: store-check remedy for a root-owned ./data, and probe cleanup on write error.

## Load status (queue-status)
dossier skipped 27; masters done 1; order_pdf done 78307, pending 223530, skipped 3; status_batch done 693, skipped 6 (excerpt).
