# ASLMS v2 — Assam State Legal Management System

Legal Case Monitoring Portal for the Government of Assam: every department tracks its cases before the
Gauhati High Court in one place, acts on court directions in time, and keeps an accountable record of how
each case is handled. Data comes from the official eCourts / High Court APIs (NAPIX). Case research and
order reading go through SourceTrace, the in-house RAG service.

**Status (25 Sep 2026):** design approved, repository reorganised, Phase 1 build starting. The backend
skeleton and the first migration are the next change. The database starts empty; there is no migration of
earlier data.

## Read first

| Document | Purpose |
|---|---|
| `docs/Legal_Case_Monitoring_Portal_Plan.docx` | The agreed plan. Source of truth. |
| `docs/claude_ASLMS_design_decisions.md` | Decision log and open points. |
| `docs/schema/phase1.md` | Phase 1 database schema. |
| `docs/specs/napix/hc/`, `docs/postman/` | NAPIX High Court API stubs and the Postman test collection. |
| `CLAUDE.md` | Working rules for anyone (or any agent) changing code here. |

## Layout

```
backend/    FastAPI + SQLAlchemy 2 + Alembic + Celery  (Python 3.11+)
frontend/   Next.js portal
infra/      PgBouncer, Prometheus, Grafana, ClamAV, backups, nginx
docs/       plan, decisions, schema, specs, postman
tools/      one-off helper scripts
data/       git-ignored local data: cause-list PDFs (data/causelists/DD-MM-YYYY/), document storage
```

Earlier systems are kept outside this repository, for reference only:
`D:\Dev Workspace\ASLMS-legacy\v1-legacy` and `D:\Dev Workspace\ASLMS-legacy\v2-prototype`.

## Running locally

Prerequisites: Docker Desktop (Postgres 16, Redis, ClamAV run as containers), Python 3.11+, Node 20+.

```bash
cp .env.example .env                       # fill NAPIX_* to use the live gateway
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api aslms seed
docker compose up -d                       # api, workers, beat
```

Backend checks: `cd backend && pytest -q && ruff check aslms`.

## Phases

1. **Core** — live NAPIX test, daily data cycle, department mapping and inbox, case tracking, orders archive,
   case document upload, specific-date alerts, search, case detail page, administration, login and roles,
   in-app and email notifications, dashboard.
2. **Workflow** — custody and requests, case notes trail, SourceTrace ingestion and period-based alerts, SMS, reports.
3. **Extension** — Case Assistant and legal research through SourceTrace; District Courts through the NAPIX DC API.
