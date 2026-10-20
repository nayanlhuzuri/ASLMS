# ASLMS v2: Assam State Legal Management System

The Legal Case Monitoring Portal for the Government of Assam. Each department tracks its cases before the Gauhati
High Court in one place: daily cause lists, case details and orders from the official eCourts / High Court APIs
(NAPIX), department ownership by recommend-and-claim, hearing alerts, custody of the file, case notes, documents,
dashboards, reports and the audit trail. Case research and order reading go through SourceTrace (the connector is
waiting for its API documentation). Owner: SeMT Assam / AMTRON.

## Stack

Python 3.12 (FastAPI, SQLAlchemy, Alembic, Celery), PostgreSQL 16 with PgBouncer, Redis, ClamAV, Next.js (`frontend/`), nginx,
Prometheus, Alertmanager, Grafana and Flower (Compose profile `monitoring`), and Docker Compose for the whole stack.

## Development quick start

1. Copy `.env.example` to `.env`. Keep `APP_ENV=dev`, `COMPOSE_PATH_SEPARATOR=:` and `COMPOSE_FILE=compose.yml:compose.dev.yml` (on Windows Docker separates the files with `;` unless `COMPOSE_PATH_SEPARATOR=:` is set). Generate the
   required secrets (`POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`, `ASLMS_READONLY_PASSWORD`, `REDIS_PASSWORD`,
   `ASLMS_JWT_SECRET`, `GRAFANA_ADMIN_PASSWORD`, and `FLOWER_BASIC_AUTH` as `user:password`) with
   `openssl rand -hex 32`, and set `PORTAL_BASE_URL=http://localhost:3000` and a mail service (the Mailtrap sandbox
   is fine in development).
2. `docker compose up -d`. The portal is at http://localhost:3000, the API at http://127.0.0.1:8000 (`/docs`), and
   Postgres at `127.0.0.1:5433`. Every port is bound to loopback only.
3. Backend tests: `cd backend && .venv/Scripts/python -m pytest -q` (the database tests use the Compose Postgres;
   each run creates and drops its own database `aslms_test_<stamp>_<hex>`, operations.md section 16). Lint: `.venv/Scripts/ruff check .`. Frontend: `cd frontend && npm test && npm run lint`.

CI runs the same gates on GitHub for every push of `main` and every pull request (`.github/workflows/ci.yml`,
operations.md section 19); it holds no secrets.

The NAPIX master switch stays off in every file. The owner sets it in the shell for a live run.

## The pilot

Run it with `APP_ENV=prod`, `COMPOSE_FILE=compose.yml` and a certificate in `infra/proxy/certs`. Only the nginx
proxy is reachable (443, and 80 which redirects). Installation, upgrades (the explicit `migrate` step), backups,
the restore check, the disaster restore, secret rotation, ClamAV modes, monitoring (`COMPOSE_PROFILES=monitoring`:
Grafana, Prometheus, Alertmanager and Flower on the host's loopback, the alert rules and what to do for each) and the
go-live checklist are in **[docs/operations.md](docs/operations.md)**.

## Main commands

| Command | What it does |
|---|---|
| `docker compose up -d` | start the stack (`init` runs preflight, the migration guard, role passwords and seed) |
| `docker compose --profile ops run --rm migrate` | the explicit upgrade: backup, migrate, seed, audit row |
| `aslms ops preflight` | check the settings; with `APP_ENV=prod` errors stop the start |
| `aslms ops backup`, `backup-status`, `restore-check` | backups and the restore check |
| `aslms ops load-report`, `sample-cnrs` | the load counts and the sample-of-20 CNR check |
| `aslms ops make-cert --host <name> --ip <address>` | an internal CA and the proxy's certificate |
| `aslms data-load status` | the backdated NAPIX load |
| `aslms data-health` | queue, jobs, mail and NAPIX health |
| `aslms ops metrics --once` | one reading of the operations exporter (the Compose `ops-exporter` serves it on 9108) |

Inside Compose, run them as `docker compose exec api aslms …` (or `exec backup` for the backup commands).

## Documents

| Document | Purpose |
|---|---|
| `docs/Legal_Case_Monitoring_Portal_Plan.docx` | The agreed plan. Source of truth. |
| `docs/claude_ASLMS_design_decisions.md` | Decision log: what is built, what is next. |
| `docs/DB_STANDARD.md`, `docs/schema/schema.md` | The database standard and the approved design. |
| `docs/napix_integration_notes.md`, `docs/napix_integration_design.md` | How NAPIX behaves live, and the integration layer's design. |
| `docs/operations.md` | The operations runbook and the pilot go-live checklist. |
| `docs/backlog.md`, `docs/design/`, `docs/team/` | The backlog, the design notes and how the agent team works. |
| `CLAUDE.md` | Working rules for anyone (or any agent) changing code here. |

The database starts empty and is filled only through the NAPIX daily cycle, user searches and department
discovery. There is no migration of earlier data.
