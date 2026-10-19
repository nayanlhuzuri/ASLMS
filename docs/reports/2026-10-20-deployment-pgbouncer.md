# deployment-pgbouncer (backlog row 78), 20 Oct 2026

Merge commit on main: 3f811b5. Tag: feature/deployment-pgbouncer-done.

## What changed
- `compose.yml`: new `pgbouncer` service (transaction mode, prepared statements tracked); `api`, `worker`, `scheduler` connect through it; `init`, `migrate`, `backup` and exporters stay direct to Postgres.
- `infra/pgbouncer/Dockerfile`, `infra/pgbouncer/entrypoint.sh`.
- `backend/aslms/cli/ops.py`, `backend/aslms/services/backups.py`: migrate and restore stop and restart pgbouncer.
- `backend/tests/unit/test_pgbouncer.py` (session-feature source scan), compose tests updated.
- Prometheus: pgbouncer exporter target, `PgBouncerClientsWaiting` alert and rules test.
- Docs: operations, design note, decisions log, CLAUDE.md, README, `.env.example` (optional `PGBOUNCER_*`).
- No tables, no endpoints, no migration.

## Gates
- ruff check: All checks passed
- pytest -q: 1478 passed, 109 warnings (19m11s)
- docker compose build: succeeded (all images built)
- frontend unchanged: portal smoke not required
- git status clean; design note status approved; decisions-log entry and backlog row present

## Review findings (all advisory) and closure
1. psycopg/libpq 17 floor not enforced: open, not fixed in this cycle; image has psycopg 3.3.6 / libpq 18 today. Follow-up row 90.
2. Session-feature scan misses indented SET, SET TIME ZONE, RESET, DISCARD, PREPARE: open. Follow-up row 91.
3. Healthcheck only checks the port: open. Follow-up row 92.
4. PgBouncer package not pinned (psycopg docs name 1.22 as minimum): open. Follow-up row 93.
5. Part C dev-stack verification (API smoke through PgBouncer, report and audit screens, worker dedupe) was NOT run by the integrator; it needs a stack restart while the historical load runs. Covered by owner row 89.

## Deviations
- Dev-stack verification not run (see 5); queue-status timed out (database busy with the historical load), so load status is not recorded.

## Follow-up rows
89 (existing), 90 to 93 (new).
