# ASLMS: Assam State Litigation Management System

[![CI](https://github.com/nayanlhuzuri/ASLMS/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nayanlhuzuri/ASLMS/actions/workflows/ci.yml)

The Assam State Litigation Management System (ASLMS) is the Government of Assam's portal for tracking its cases before
the Gauhati High Court. Each department sees its cases in one place, knows what is listed next, who holds the file
and what needs doing, and every decision is recorded.

## What ASLMS does

- **Court data from the official source.** Daily cause lists, case details and orders come only from the official
  eCourts / High Court APIs (NAPIX). Nothing is scraped, and every answer is kept exactly as received.
- **Cases find their department.** The system recommends each case to the department it most likely belongs to,
  using counsel codes, keywords and name patterns. Nothing is assigned automatically: a department **claims** a
  case, and a claimed case never returns to the unclaimed pool.
- **Never miss a hearing.** Personal and department calendars, hearing alerts in the portal and by e-mail, a daily
  digest, and next dates read from order text for a person to confirm.
- **Know who holds the file.** The file moves between officers with a remark, a pending action and a due date.
  Recalls, overdue alerts and the full trail are kept.
- **Notes and documents.** Append-only notes with per-note visibility. Uploads are type-checked and virus-scanned
  before storage. Orders can be read, printed and downloaded.
- **Oversight.** Personal, department and State dashboards; reports with Excel and PDF export; the audit log;
  System health for the court APIs and the ASLMS services.
- **Secure by design.** Every sign-in needs an e-mailed code, the server decides what each person may see, every
  significant action is audited, and no legal record is ever deleted.

How each of these works, step by step, is in **[docs/ASLMS_Process_Workflows.md](docs/ASLMS_Process_Workflows.md)**.

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

## Project layout

| Folder | Contents |
|---|---|
| `backend/aslms/` | The Python application: `api/` (FastAPI routes), `services/` (business rules), `integration/napix/` (the only code that calls NAPIX), `integration/sourcetrace/` (the AI connector interface), `jobs/` (Celery schedules), `cli/` (the `aslms` command), `domain/` (database models) |
| `backend/migrations/` | Alembic migrations (applied migrations are never edited) |
| `backend/tests/` | Unit and database tests |
| `backend/tools/` | Developer tools: OpenAPI export, portal smoke test, repository policy |
| `frontend/` | The Next.js portal and its backend-for-frontend (`src/app/` pages, `src/components/` screens and UI kit, `src/lib/` text, routes and API client) |
| `infra/` | Configuration for the nginx proxy, PgBouncer, ClamAV, Prometheus, Alertmanager and Grafana |
| `docs/` | The plan, the decision log, the database standard and schema, the runbook, designs and reports |
| `.github/` | CI workflows and Dependabot |

## Ownership and use

ASLMS is the property of the **Government of Assam**. This repository is private. Its code, documents and data
are for official use only and may not be copied, distributed or used elsewhere without written permission.
Court data shown by ASLMS remains the record of the Gauhati High Court.

