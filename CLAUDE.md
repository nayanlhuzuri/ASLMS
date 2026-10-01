# ASLMS — Legal Case Monitoring Portal

A portal for Assam government departments to track their cases before the Gauhati High Court: daily cause lists, case details and orders from the NAPIX APIs, department ownership, hearing alerts, custody and notes, and an AI Case Assistant through SourceTrace.

## Read these first
- `docs/Legal_Case_Monitoring_Portal_Plan.pdf` — the agreed plan. **Source of truth**: if code, this file or the log disagree with the plan, follow the plan and flag the conflict.
- `docs/claude_ASLMS_design_decisions.md` — decision log, schema notes, what is built, what is next.
- `docs/Legal_Case_Monitoring_Progress_Report.pdf` — how the existing scraper-based system works (migration source).
- `docs/napix_integration_notes.md` — how the NAPIX APIs actually behave, verified by live tests (auth, encryption, errors, endpoints). Follow it exactly; it overrides the spec PDF where they differ.
- NAPIX specs: PDFs in `docs/specs/`; request/response JSON in `High Court Case Status API/`. Check field names against these files; never guess NAPIX fields. Decrypted live samples are in `docs/specs/samples/`.

## Building from scratch
The whole system, including the database, is being designed and built new from the plan. Nothing existing is the foundation.
- `archive/legacy/` — first version of the code. Reference only: do not modify it or import from it.
- The existing scraper-based database (described in the progress report) is a data migration source, not a schema to copy.

## Stack
Python backend (FastAPI), Celery + Redis, PostgreSQL + PgBouncer, Alembic migrations, Next.js frontend, Docker Compose, Prometheus/Grafana.

## Rules that must not be broken
- **Ownership is recommend-and-claim.** Never assign a case to a department automatically. Score ≥ 0.85 = strong recommendation, 0.50–0.85 = possible match, < 0.50 = unclaimed pool. A case belongs to a department only after it claims it.
- **All AI goes through SourceTrace**, via the SourceTrace connector interface. No cloud LLM, no Ollama or other local model. SourceTrace endpoints are not known yet: code against the interface and use a fake implementation in tests.
- **Never send to SourceTrace:** case notes or internal documents. Only court orders and uploaded court filings are ingested.
- **Case notes are append-only.** No edits or deletes; corrections are new notes linked with `supersedes`.
- **NAPIX calls go only through the integration layer** (encryption, tokens, retry, rate limits). No other module calls NAPIX directly.
- **Secrets:** NAPIX credentials and other secrets come from `.env` only. Never commit `.env`, print secrets, or write them to logs.
- **Visibility is enforced on the server** for every query (State → Department → Directorate tiers, per-document and per-note visibility). Never rely on the frontend to hide data.
- **Audit:** every significant action (ownership decisions, custody moves, notes, uploads, configuration changes) writes an audit log row.
- **Uploads:** permitted types only (PDF, Word, images), size limit, virus scan before storage.

## Database
- The schema is designed new from the plan (modules in Section 5, data groups in Section 7). Propose the schema in plan mode and get approval before writing the first migration.
- Starting conventions (can be revised during schema design): UUID primary keys; CNR as the unique business key for cases; enums as varchar + CHECK; consistent constraint names.
- Fresh Alembic history. After the first migration is applied, schema changes only through new migrations; never edit an applied migration.

## How to work in this repo
- Use plan mode for any change touching more than one module; wait for approval before editing.
- Work in small steps. Add or update tests for every new service or endpoint, and run the test suite before finishing.
- When a decision changes, update `docs/claude_ASLMS_design_decisions.md` in the same change.
- If something needed is missing (an API field, a SourceTrace endpoint, a business rule), stop and ask rather than inventing it.

## Current focus
Phase 1 (Core), starting from an empty project:
1. Test the NAPIX High Court APIs live and compare the responses with the JSON files and the plan's API usage map, especially whether Cause List Details returns complete case entries.
2. Propose the project structure and the new database schema from the plan, for approval.
3. Then build Phase 1 in small steps. See "Next" in the decision log.
