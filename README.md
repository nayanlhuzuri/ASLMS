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
| Phase 3: Case Assistant and research | conversation storage, case chat and Research page built; answers need SourceTrace |
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

## Running it

Prerequisite: Docker Desktop. One command builds and starts everything:

```bash
docker compose up -d --build
```

| Open | What |
|---|---|
| http://localhost:3000 | the portal |
| http://localhost:8025 | Mailpit: every e-mail the portal sends, including the six-digit sign-in codes |
| http://localhost:8000/api/docs | API documentation (dev only) |

On the first start the `init` container migrates the database, seeds it and loads the demo departments and one
account per role. Sign in with, for example, `edu.admin@aslms.local` and the password `Demo@2026pass`, then take the
code from the Mailpit inbox. Other demo accounts: `edu.head`, `edu.officer`, `dse.user`, `edu.counsel`,
`health.admin`, `fin.admin`, `cs.office`, `auditor` (all `@aslms.local`).

Cause-list PDFs placed in `data/causelists/DD-MM-YYYY/` are picked up by the daily cycle, or at once with
`docker compose exec api aslms backfill`. Other commands run the same way (`docker compose exec api aslms report`).

To send real e-mail through Mailtrap instead of Mailpit, put `MAILTRAP_API_TOKEN` (and a `SMTP_FROM` on your
verified Mailtrap domain) in `.env` and run `docker compose up -d` again; see the e-mail section of `.env.example`.

Stop with `docker compose down` (data is kept in Docker volumes and `data/`). `.env` is optional on a laptop;
copy `.env.example` to change settings. Uploads show "scan failed" unless ClamAV runs
(`docker compose --profile scan up -d` with `CLAMAV_HOST=clamav`). Production: `docs/operations.md`.

### Developing without containers

```bash
docker compose up -d postgres redis mailpit
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/uvicorn aslms.api.main:app --reload          # needs DATABASE_URL_SYNC=...@localhost:5433/aslms
cd ../frontend && npm install && npm run dev               # API_BASE_URL=http://localhost:8000
```

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
