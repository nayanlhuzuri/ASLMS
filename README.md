# ASLMS v2 — Assam State Legal Management System

Legal Case Monitoring Portal for the Government of Assam: every department tracks its cases before the
Gauhati High Court in one place, acts on court directions in time, and keeps an accountable record of how
each case is handled. Data comes from the official eCourts / High Court APIs (NAPIX). Case research and
order reading go through SourceTrace, the in-house RAG service.

**Status (25 Sep 2026):** design approved, repository reorganised, backend skeleton and migration
`0001_phase1_core` (39 tables) in place and round-trip tested, NAPIX integration layer written and tested
offline against a mocked gateway. Next: run `aslms napix-check` with real credentials (the live test), then
the daily data cycle. The database starts empty; there is no migration of earlier data.

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

Backend development without the `api` container (Python 3.11+; the venv lives in `backend/.venv`):

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"      # Windows; use .venv/bin on Linux
.venv/Scripts/alembic upgrade head
.venv/Scripts/aslms seed                     # structural offices, GAHC01, operator account (SEED_ADMIN_*)
.venv/Scripts/python -m pytest -q            # integration tests use <db>_test and skip if Postgres is down
.venv/Scripts/ruff check aslms tests alembic
.venv/Scripts/uvicorn aslms.api.main:app --reload   # http://localhost:8000/api/docs
.venv/Scripts/aslms napix-check --date 2026-09-26 --cnr GAHC010153612024   # live NAPIX test; needs NAPIX_* in .env
```

`napix-check` walks overview → state → bench master → case type master → cause-list benches → cause-list
details → show cause list (PDF) → CNR → current status → show business → order, prints one line per call and
writes every decrypted response to `docs/specs/napix/hc/samples/` (git-ignored) for review.

## Phases

1. **Core** — live NAPIX test, daily data cycle, department mapping and inbox, case tracking, orders archive,
   case document upload, specific-date alerts, search, case detail page, administration, login and roles,
   in-app and email notifications, dashboard.
2. **Workflow** — custody and requests, case notes trail, SourceTrace ingestion and period-based alerts, SMS, reports.
3. **Extension** — Case Assistant and legal research through SourceTrace; District Courts through the NAPIX DC API.
