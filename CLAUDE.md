# CLAUDE.md — ASLMS v2 (Assam State Legal Management System)

You are working on the Legal Case Monitoring Portal for the Government of Assam (owner: SeMT Assam / AMTRON).
Read this file fully before touching code. Then read, once, in this order:

1. `docs/Legal_Case_Monitoring_Portal_Plan.docx` — **the agreed plan and the source of truth.** Where anything
   else (including this file) differs from it, the plan wins.
2. `docs/claude_ASLMS_design_decisions.md` — running decision log: what was decided, why, and what the plan
   left open. Append to it whenever a decision is taken; never rewrite history in it.
3. `docs/schema/phase1.md` — the approved Phase 1 database schema.
4. `docs/specs/napix/hc/` and `docs/postman/` — the NAPIX High Court API stubs and the test collection.

Design decisions are settled with the product owner and are not re-litigated. When something is genuinely
ambiguous, ask in one line and proceed with the sensible default.

## Built from blank

- **No starting data.** The database begins empty and is filled only through the NAPIX daily cycle, user
  searches and department discovery. There is no migration from the earlier scraper-based system.
- **No inherited code.** Two earlier systems exist outside the workspace, for reading only:
  `D:\Dev Workspace\ASLMS-legacy\v1-legacy` (first system) and `D:\Dev Workspace\ASLMS-legacy\v2-prototype`
  (September 2026 prototype, with a working cause-list PDF parser and NAPIX client). Read them for lessons;
  never copy modules from them, import them, or point tooling at them.

## What the system does

Collects Gauhati High Court data through NAPIX (the e-Committee's official eCourts API gateway; district courts
via the NAPIX DC API in Phase 3), with the GHC website as a supplementary cross-check. Every cause-list row is
resolved to a canonical case by CNR (shown to users as CINO). A scoring engine **recommends** each case to the
department it most likely belongs to; a department **claims** it. The portal then tracks the court record,
stores orders and uploaded case documents, raises alerts from next dates, and (Phase 2) carries an
eOffice-style custody trail and an append-only noting trail. All AI work (reading orders for next dates, the
Case Assistant, research) goes through **SourceTrace**, the in-house RAG service, via a connector.

Users: state_oversight (CM/CS office, read-only across the State), dept_head, dept_admin, dept_officer,
directorate_user, referral_reviewer, standing_counsel, central_operator, auditor.

## Ground rules (non-negotiable)

1. **Never fabricate identifiers.** No made-up CNRs. A case without a CNR is `is_provisional = true`.
2. **Nothing is assigned automatically.** The engine writes scores and recommendations; only an explicit claim
   by a department writes `case_ownership`. Thresholds: ≥ 0.85 strong, 0.50–0.85 possible, < 0.50 unclaimed pool.
3. **Events are append-only** and carry a `dedupe_key`. Every state change emits one event; timelines, alerts
   and dashboards read from events. `audit_log` is append-only too.
4. **Idempotent everywhere.** Re-running the daily cycle for a date creates nothing new: documents dedupe on
   sha256, cause-list entries on their unique constraint, events on `dedupe_key`, snapshots on payload hash.
5. **Author snapshots.** Claims, uploads, notes and audit rows freeze who (name, designation, office) at write time.
6. **Visibility is enforced in SQL**, never in a prompt or on the client. Department scope = `offices.path`
   prefix. State tier roles see everything read-only. Standing counsel sees only cases they appear in plus
   `counsel_shared` items.
7. **All NAPIX calls go through `backend/aslms/integration/napix/`.** No router, service or job calls the
   gateway directly. Every call is logged to `napix_call_log`; failures go to `source_failures`, never lost.
8. **AI only through the SourceTrace connector** (`integration/sourcetrace/`, behind an interface; endpoint
   shapes pending). No cloud LLM, no local LLM. Court orders and court filings may be sent; **notes and
   internal documents never.** AI output is advisory, versioned, and applied only on a user action.
9. **Uploads** accept PDF, Word and images only, within the size limit, and are virus-scanned before storage.
10. **Schema changes go through Alembic** (`alembic revision --autogenerate`, hand-check, rename to
    `NNNN_slug.py`, set `revision = 'NNNN'`). Never edit an applied migration; add a new one.
11. **Celery queue names** in `backend/aslms/jobs/celery_app.py` must match the `-Q` flags in `docker-compose.yml`.
12. **Secrets** live in `.env` (git-ignored) and are never logged or sent to the browser. NAPIX credentials
    especially. `.env.example` documents every variable with a safe default.
13. Python 3.11+, type hints, `ruff check` clean, `pytest -q` green. Frontend: Next.js (App Router) + TypeScript.
14. **The database follows `docs/DB_STANDARD.md` v1.2** (UUID v7 keys, eOffice-style `ref_no` on quotable
    records, no deletion of legal records — FKs RESTRICT, `ref_*` lookup tables for the eight user-facing code
    sets, table classes in `COMMENT ON TABLE`, `public` schema kept). Read it before adding or changing any
    table. Milestone DB-1 (its §11–§12) runs before the Plan's build order resumes.

## Repository map (target layout)

```
backend/
  pyproject.toml  alembic.ini  Dockerfile
  alembic/versions/         0001_phase1_core.py — fresh history
  aslms/
    core/         config (pydantic-settings), logging (structlog), security (argon2, JWT), time (IST), errors
    db/           session (async + sync), base (Base, mixins), seed/ (offices, roles, masters, counsel codes)
    domain/       SQLAlchemy 2 models, one module per data group: org, reference, cases, causelists, ownership,
                  documents, alerts, events, ops  (Phase 2: workflow, notes, sourcetrace; Phase 3: assistant)
    integration/  the only place that talks to the outside world, each behind a Protocol in base.py
      napix/      crypto, client (token, envelope, retry, rate limit, call log), hc (typed calls), masters, dc (Phase 3)
      ghc/        causelist_pdf (parser), website (supplementary PDFs)
      sourcetrace/ interface + stub (real client in Phase 2)
      email.py  sms.py (stub)  antivirus.py (clamd)
    services/     business logic, no HTTP: scope, auth, cases, search, causelists, ownership, tracking, orders,
                  documents, alerts, notifications, admin, audit, events, dashboard, reports
    jobs/         celery_app (queues: ingest, track, documents, notify, default), schedules, tasks/
    api/          main, deps (current_user, scope), schemas/ (pydantic I/O), routers/ (auth, users, cases, search,
                  causelists, inbox, alerts, orders, documents, admin, dashboard, reports, audit, health)
    cli/          `aslms` (typer): seed, napix-check, cycle, backfill, report
  tests/          unit/, integration/ (skip when Postgres is unreachable), fixtures/ (sample PDFs, recorded NAPIX shapes)
frontend/         Next.js portal, talks only to backend/api
infra/            pgbouncer/, prometheus/, grafana/, clamav/, backup/, nginx/
docs/             plan + progress report (docx), decisions log, schema/, specs/napix/hc/, postman/, adr/
tools/            one-off helper scripts
data/             git-ignored: causelists/DD-MM-YYYY/{Daily,Supplementary,Lawazima}_DD-MM-YYYY.pdf, storage/
```

## Domain vocabulary

Case (canonical, CNR) · CauseList / CauseListEntry (one row, immutable, source `napix_details` or `pdf_parse`)
· Score / Recommendation (recommended | claimed | dismissed | suggested_elsewhere | expired) · Ownership
(primary | watcher) · Transfer · Document (court_record | court_filing | internal; visibility case_scope |
counsel_shared | private_to_office) · Order · NextDate (causelist | current_status | order_specific |
order_period | manual) · Alert · Notification · Event · AuditLog · Office (department → directorate; `path`)
· Phase 2: Custody, Request, Stage, CaseNote · Phase 3: Assistant conversation.

## NAPIX essentials

- Base `https://delhigw.napix.gov.in/nic/ecourts`; OAuth2 client-credentials token (`/oauth2/token`, Basic
  client_id:client_secret, `grant_type=client_credentials&scope=napix`), sent as `Authorization: Bearer`.
- Every API takes `dept_id`, `request_str`, `request_token`, `version` (`v1.0`).
  `request_str = base64(AES-128-CBC(plain, key = IV = 16-char auth key, PKCS7))`,
  `request_token = hex(HMAC-SHA256(plain, "15081947"))`, where `plain` is `k1=v1|k2=v2` in the documented order.
  Known-answer test: `HMAC("state_code=27")` = `d10f8382c089c134ae7635fea97b2ca81488b25f3db23c9d578146599b7679c7`.
- Responses are `{response_str, response_token, version}`; decrypt, verify the token, parse JSON. Error bodies
  `{status: 6xx}` are encrypted too (600 invalid CNR, 626 invalid token, 628 not found, 631 access not allowed…).
  Lists come as `{"case1": {...}, "case2": {...}}` or `{"sr_no1": ...}`, not arrays.
- Current Status is the only POST (bulk CNRs, comma-separated). Show Order needs `cino|order_no|order_date`.
  Search by Case Number needs the numeric `case_type` from Case Type Master.
- Open until the live test (`aslms napix-check`): what Cause List Details returns (rows or list metadata),
  `est_code` per bench (GAHC01 assumed), `state_code` (6 assumed), auth-key encoding, and whether PDF APIs
  return raw `application/pdf` or base64 inside `response_str`. Record the answers in the decisions log.

## Milestone DB-1 — database conformance (next; do this before anything else)

Execute `docs/DB_STANDARD.md` §11 steps 1–7 (§12.1 is step 6) one commit per step, then run the §12.2
acceptance gate and report the outputs of gate steps 4, 5, 7 and 8 verbatim. Record the pre-migration
baseline (how the test data was produced and its counts) before step 1. Stop on any baseline drift.

## Current state (26 Sep 2026)

Phase 1 and the Phase 2 workflow are built and tested (70 backend tests); the Phase 3 assistant has its storage and
UI. Waiting on outside input: NAPIX live test (`NAPIX_ENABLED=true`, `aslms napix-check`), the real
code-to-department mapping from the departments, the SourceTrace API shapes, and the NAPIX DC specification.
Migrations: 0001 (Phase 1 core), 0002 (`case_ownership.unit_office_id`), 0003 (Phase 2/3 tables).
Operations: `docs/operations.md`.

## Build order — Phase 1 (Core), one reviewable change at a time

1. Backend skeleton + migration `0001_phase1_core` (schema per `docs/schema/phase1.md`); `alembic upgrade head`,
   `downgrade -1`, `upgrade head` round-trip; seed for offices, roles and one admin.
2. NAPIX integration layer + `aslms napix-check` (the live test; saves decrypted shapes to
   `docs/specs/napix/hc/samples/`). Then settle the open points above.
3. Daily data cycle: cause-list bench → details → show-causelist PDF (parser as cross-check) → entries →
   cases (CNR API on first sight) → snapshots → events. Current Status daily; full refresh weekly.
4. Ownership: counsel codes, patterns, keywords, watchlist; scoring engine (pure functions, signals returned);
   recommendations; inbox (Recommended / Claimed / Unclaimed pool / Transfers); claim, dismiss, suggest, transfer.
5. Auth (local accounts, argon2, OTP by email, JWT + rotating refresh) and RBAC/scope; administration
   (offices, users, codes, keywords, NAPIX masters).
6. Orders archive (Show Order download, text extraction) and case document upload (types, visibility, ClamAV).
7. Next dates and alerts (causelist, current status, specific-date orders); notifications in-app + email;
   daily digest; dashboard per role; search (portal DB first, NAPIX fallback, store on hit); case detail page.
8. Reports and data-collection health; Next.js frontend per the UI boards.

Phase 2 (built): custody & workflow, notes trail, SourceTrace ingestion + period-based next dates (behind the
interface), SMS hook, reports. Phase 3: Case Assistant & research (storage built, answers need SourceTrace),
District Courts (not started).

Additional rules learned while building:
- Services take a sync `Session`; the caller owns the transaction. A service that must persist something even when
  it then raises (OTP attempt counters, refresh-token revocation) commits before raising, with a comment saying why.
- `NAPIX_ENABLED` is the master switch; never flip it on in code or tests.
- Custody is only ever moved through `services.workflow.move`; officers' workflow access is personal (held by /
  addressed to them), not by office.

## Running locally (once the skeleton exists)

```bash
cp .env.example .env                       # fill NAPIX_* to use the live gateway
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api aslms seed
docker compose up -d                       # api, workers, beat
cd backend && pytest -q && ruff check aslms
```

## Definition of done for any change

- `ruff check` clean, `pytest -q` green, new behaviour has a test.
- Migration added if models changed; upgrade → downgrade → upgrade works.
- `README.md` / `.env.example` updated if a command or variable changed; decisions log appended if a decision was taken.
- No secrets committed. Nothing imported from the legacy folders.
