# ASLMS v2 — Assam State Legal Management System

Legal Case Monitoring Portal for the Government of Assam. Every department tracks its cases before the Gauhati
High Court in one place, acts on court directions in time, and keeps an accountable record of how each case is
handled. Data comes from the official eCourts / High Court APIs (NAPIX), with the court's cause-list PDFs as a
cross-check. Case research and order reading go through SourceTrace, the in-house RAG service.

## What is built

| Area | State |
|---|---|
| Daily data cycle: cause lists (NAPIX + PDF parser), cases by CNR, hearings, next dates, events | built; NAPIX side waits for `NAPIX_ENABLED` |
| Recommend-and-claim: scoring from counsel codes, name patterns, keywords, watchlist, linked cases; inbox; claim, dismiss, suggest, transfer, allot, release | built |
| Case tracking: first-sight fetch, daily Current Status, weekly refresh, change detection | built; needs NAPIX |
| Orders archive with text extraction and next dates (specific dates read; periods flagged for review) | built; downloads need NAPIX |
| Case documents: upload with type, visibility, virus scan | built |
| Alerts, calendar, in-app / e-mail notifications, daily digest; SMS gateway hook | built |
| Search (portal first, NAPIX fallback), case detail, dashboard per role, reports (Excel/CSV), administration, audit log | built |
| Sign-in with password + e-mailed OTP; nine roles; visibility enforced in SQL | built |
| Phase 2: custody, requests between offices, guided stages, notes trail | built |
| Phase 2: SourceTrace ingestion and period next dates | built against the interface; off until the SourceTrace API is available |
| Phase 3: Case Assistant and research | conversation storage and UI built; answers need SourceTrace |
| Phase 3: District Courts via NAPIX DC API | not started (no DC specification in the repository) |
| Deployment: Docker Compose with nginx, PgBouncer, ClamAV, Prometheus/Grafana, backups | built |

The database starts empty. There is no migration of earlier data.

## Read first

| Document | Purpose |
|---|---|
| `docs/Legal_Case_Monitoring_Portal_Plan.docx` | The agreed plan. Source of truth. |
| `docs/claude_ASLMS_design_decisions.md` | Decision log and open points. |
| `docs/schema/phase1.md` | Database schema (Phase 1 and the Phase 2/3 tables). |
| `docs/operations.md` | Installation, configuration, daily operation, backups, upgrades. |
| `docs/specs/napix/hc/`, `docs/postman/` | NAPIX High Court API stubs and the Postman test collection. |
| `CLAUDE.md` | Working rules for anyone (or any agent) changing code here. |

## Layout

```
backend/    FastAPI + SQLAlchemy 2 + Alembic + Celery (Python 3.11+); tests in backend/tests
frontend/   Next.js portal (TypeScript); talks to the API through its own server-side proxy
infra/      nginx, Prometheus, Grafana, backup scripts
docs/       plan, decisions, schema, operations, specs
data/       git-ignored local data: cause-list PDFs (data/causelists/DD-MM-YYYY/), document storage
```

## Running on a laptop

Prerequisites: Docker Desktop, Python 3.11+, Node 20+.

```bash
cp .env.example .env
docker compose up -d postgres redis

cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # Linux/macOS: .venv/bin/...
.venv/Scripts/alembic upgrade head
.venv/Scripts/aslms seed                 # structural offices, GAHC01, operator account
.venv/Scripts/aslms seed-demo            # DEV ONLY: demo departments, code mappings, one account per role
.venv/Scripts/aslms backfill --limit 5   # ingest cause-list PDFs from data/causelists
.venv/Scripts/aslms rescore
.venv/Scripts/uvicorn aslms.api.main:app --reload        # API on :8000, docs at /api/docs

cd ../frontend
npm install && npm run dev               # portal on http://localhost:3000 (API_BASE_URL=http://localhost:8000)
```

Sign in with a demo account (the password is printed by `seed-demo`); the one-time code is written to the API's
console while `SMTP_HOST` is empty.

Everything in containers instead: `docker compose up -d --build` (portal on :3000).
Production: see `docs/operations.md`.

## Checks

```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check aslms tests alembic
cd frontend && npm run typecheck && npm run lint && npm run build
```
Integration tests need Postgres (they create `<db>_test`) and are skipped when it is not reachable.

## Useful commands

```bash
aslms napix-check --date YYYY-MM-DD --cnr <CNR>   # live NAPIX test (needs NAPIX_ENABLED=true)
aslms cycle --date YYYY-MM-DD                     # the daily cycle for one date
aslms refresh status|full|first-sight|orders|masters|discovery
aslms alerts                                      # raise alerts and send queued notifications
aslms import-offices offices.csv / import-codes codes.csv / create-user ...
aslms report                                      # data summary and top unmapped counsel codes
```
