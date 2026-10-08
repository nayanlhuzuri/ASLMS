# ASLMS — Legal Case Monitoring Portal

A portal for Assam government departments to track their cases before the Gauhati High Court: daily cause lists, case details and orders from the NAPIX APIs, department ownership, hearing alerts, custody and notes, and an AI Case Assistant through SourceTrace. Owner: SeMT Assam / AMTRON.

## Read these first
- `docs/Legal_Case_Monitoring_Portal_Plan.docx` — the agreed plan. **Source of truth**: if code, this file or the log disagree with the plan, follow the plan and flag the conflict.
- `docs/claude_ASLMS_design_decisions.md` — decision log, what is built, what is next. Append; never rewrite history.
- `docs/DB_STANDARD.md` and `docs/schema/schema.md` — the approved database standard and design (UUID v7 keys, `ref_no`, `ref_*` code sets, no deletion of legal records, table classes, roles). Build the database from them; extend `schema.md` before any migration adds a table.
- `docs/napix_integration_notes.md` — how the NAPIX APIs actually behave, verified by live tests (auth, encryption, errors, endpoints). Follow it exactly; it overrides the spec PDF where they differ. `docs/napix_integration_design.md` is the layer's design.
- NAPIX specs: gateway stubs in `docs/specs/napix/hc/` (envelope only, no response fields); decrypted live samples in `docs/specs/samples/`; the Postman collection in `docs/postman/`. Check field names against the samples and the e-Committee PDF specifications; never guess NAPIX fields.
- `docs/Legal_Case_Monitoring_Progress_Report.docx` — how the earlier scraper-based system worked. Background only.

## Building from scratch
The whole system, including the database, is designed and built new from the plan. Nothing existing is the foundation.
- **No starting data.** The database begins empty and is filled only through the NAPIX daily cycle, user searches and department discovery. There is no migration from the scraper-based system.
- **No inherited code.** Earlier builds live outside the workspace, for reading only: `D:\Dev Workspace\ASLMS-legacy\v1-legacy` (first system), `v2-prototype` (September 2026 prototype) and `v3-sept-build` (the 25–29 Sep 2026 build: Phase 1 and 2 backend, portal, infra, DB-1 migration). Read them for lessons; never copy modules from them, import them, or point tooling at them.
- **Every NAPIX field is kept.** Each API response is stored verbatim as JSON, and every documented or observed field has a typed home in the schema (the coverage table in `docs/schema/schema.md`). A field without a home is a defect.

## Stack
Python 3.11+ backend (FastAPI), Celery + Redis, PostgreSQL 16 + PgBouncer, Alembic migrations, Next.js frontend, Docker Compose, Prometheus/Grafana. `ruff check` clean, `pytest -q` green.

## Rules that must not be broken
- - **Ownership is recommend-and-claim.** Never assign a case to a department automatically. Default bands: score ≥ 0.85 = strong recommendation, 0.50–0.85 = possible match, < 0.50 = no recommendation; the super admin can change the weights and bands from the application. A case belongs to a department only after it claims it, and once claimed it never returns to the unclaimed pool.
- **All AI goes through SourceTrace**, via the SourceTrace connector interface. No cloud LLM, no local model. SourceTrace endpoints are not known yet: code against the interface and use a fake implementation in tests.
- **Never send to SourceTrace:** case notes or internal documents. Only court orders and uploaded court filings are ingested.
- **Case notes are append-only.** No edits or deletes; corrections are new notes linked with `supersedes`.
- **NAPIX calls go only through `backend/aslms/integration/napix/`** (encryption, tokens, retry, rate limits). No other module calls NAPIX directly. Every call is logged; failures are recorded, never lost.
- **`NAPIX_ENABLED` is the master switch** (default `false`). Never flip it on in code or tests; the live test is run with it set for that run.
- **Secrets:** NAPIX credentials and other secrets come from `.env` only. Never commit `.env`, print secrets, or write them to logs.
- **Visibility is enforced on the server** for every query (State → Department → Directorate tiers, per-document and per-note visibility). Never rely on the frontend to hide data.
- **Audit:** every significant action (ownership decisions, custody moves, notes, uploads, configuration changes) writes an audit log row.
- **Uploads:** permitted types only (PDF, Word, images), size limit, virus scan before storage.
- **Never fabricate identifiers.** No made-up CNRs or codes; a case without a CNR is provisional.

## Database
- Built from `docs/DB_STANDARD.md` v1.2 and `docs/schema/schema.md` (approved 29 Sep 2026); the NAPIX coverage addendum is approved before migration 0001 is written.
- Fresh Alembic history. After the first migration is applied, schema changes only through new migrations; never edit an applied migration.

## How to work in this repo
- Use plan mode for any change touching more than one module; wait for approval before editing.
- Work in small steps. Add or update tests for every new service or endpoint, and run the test suite before finishing.
- When a decision changes, update `docs/claude_ASLMS_design_decisions.md` in the same change.
- If something needed is missing (an API field, a SourceTrace endpoint, a business rule), stop and ask rather than inventing it.

## How the team works
The build runs as an agent team defined in this repository (`.claude/agents`, `.claude/skills`,
`.claude/workflows`, hooks in `.claude/settings.json`), described in `docs/team/README.md`: architect →
owner approval → developer → tester → reviewer → scribe → integrator, one backlog item
(`docs/backlog.md`) per cycle on `feature/<slug>`, merged locally after tests and review. Commands:
`/team-cycle`, `/team-design`, `/team-approve`, `/team-status`, `/team-review`. Definition of done:
`docs/team/definition-of-done.md`. Hooks block `.env` access, edits to applied migrations, turning the
NAPIX master switch on in any file, and any write from `ASLMS-legacy`.

## Current focus (after the reset of 1 Oct 2026)
Done: NAPIX integration layer and live check; approved coverage addendum; migrations 0001–0004, seed, Compose
(`postgres`, `redis`, `init`, `api`, `worker`, `scheduler`); the cause-list PDF parser; the load-and-refresh
pipeline; user types, functions, the type matrix and per-user overrides with the delegation rule; the API
slice (sign-in, `/me`, user and access administration); offices administration (offices, tree, designations,
first department admins, `aslms offices`; no migration, 43 functions); recommend-and-claim (scoring settings, matching engine, recommendations, claim / dismiss / suggest / allot / take over / transfer, the case inbox API, `aslms rescore`; migration 0004); the cases API (server-side visibility, local search, case detail and tabs, NAPIX court search by CNR, case number and party name behind `cases.search_court`, quota guard; migration 0005); documents and uploads (type check by content, ClamAV scan before storage and a `clamav` Compose service, 20 MB limit, per-document visibility, download, order PDFs from the store, background text extraction and content search, no delete; migration 0006); alerts and notifications (event scan and date sweep, in-app and e-mail notifications with Mailtrap, daily digest, preferences, hearing calendar, `aslms alerts`; migration 0007, in review); user memberships (one login, several offices each with its own designation and type; one super admin and one department admin per department; head changes through admin tickets; the exit step; migration 0008, in review).; custody workflow (sending the file to any officer's membership with remark, pending action and due date; recall and tracking as grantable functions; case stages; the append-only notes trail with the holder's drafts, attachments and per-note visibility; request tables dropped; migration 0009, in review, not yet applied to the dev database); OTP sign-in and profile (a 6-digit code e-mailed at every sign-in, so a working mail service is required, with Mailtrap in development; devices with a new-device notice; password reset by e-mail; the server-enforced first-sign-in password change and profile confirmation with a mandatory mobile number; administrators can correct a login's e-mail; `aslms users sign-out`; migration 0010, in review); the SourceTrace connector (the connector interface, a fake for tests only and no real connector yet; ingestion of court orders and court filings only, never notes or internal documents, with append-only ingestion records, retries, the `admin.sourcetrace` function, `aslms sourcetrace`, a 5-minute job that sends nothing until a real connector exists; migration 0011, in review); dashboards and reports (personal, department and State dashboard blocks by function and membership; the four reports pending-cases, hearings-disposals, pending-actions and data-health with Excel and PDF export, audited; `aslms reports`; migration 0012 adds two indexes, in review). The historical load from 2025-01-01 is running in the
Compose worker. Next, in order:
1. The portal (sign-in screens in row 11, custody screens in row 13, dashboard in row 11, reports screen in row 39), the Case Assistant (row 14)
   and the real SourceTrace connector (row 36, blocked on the SourceTrace API documentation) — the backlog order. Next dates from order text is row 26. NAPIX search by advocate and filing number is row 21.
2. Before deployment: load counts and the sample-of-20 check in the decisions log; `pg_dump` of the dev database.
