# ASLMS v2 — Design Decision Log (running)

Last updated: 2026-09-25, second revision (owner confirmed: build from blank, code and data; no migration of the scraper data; repository reorganised)

**Source of truth.** `docs/Legal_Case_Monitoring_Portal_Plan.docx` is the agreed plan. Where this log and the plan differ, the plan wins. This log records the decisions and the reasons behind them.

References:
- Portal plan: `docs/Legal_Case_Monitoring_Portal_Plan.docx`
- Progress report on the scraper-based system: `docs/Legal_Case_Monitoring_Progress_Report.docx`
- UI screens (current, 6 boards, match the plan): https://claude.ai/artifact/7VyaD1VhmPARcJasZQXvsC
- Earlier workflow diagrams: https://claude.ai/artifact/2AP4LiH9mQzup9xMR7vYqy and earlier UI canvas: https://claude.ai/artifact/Pd1iPUXAkyiiezMpsk5ehL (both predate the plan; follow the plan where they differ)
- NAPIX specs: gateway JSON stubs in `docs/specs/napix/hc/` (they describe only the request envelope, not the input or response fields); the e-Committee PDF spec (HC Open API v1.0, 07.09.2023, and the Subscriber Manual) is to be added beside them. Postman test collection in `docs/postman/`.
- Codebase: D:\Dev Workspace\ASLMS, a monorepo: `backend/` (FastAPI, Celery, Alembic), `frontend/` (Next.js), `infra/` (PgBouncer, Prometheus, Grafana, ClamAV, backups), `docs/`, `tools/`, and a git-ignored `data/` (cause-list PDFs under `data/causelists/DD-MM-YYYY/`, document storage under `data/storage/`).
- Reference only, kept outside the workspace and never imported: `D:\Dev Workspace\ASLMS-legacy\v1-legacy` (the first system) and `D:\Dev Workspace\ASLMS-legacy\v2-prototype` (the September 2026 prototype, see below).

## Fresh start (2026-09-25)
- The whole system is rebuilt from scratch, including the database. An earlier v2 prototype (21–23 Sep 2026: ~6.8k lines, a 56-table schema, a working cause-list parser and NAPIX client) does exist; it has been moved to `D:\Dev Workspace\ASLMS-legacy\v2-prototype` together with copies of its `CLAUDE.md`, `DESIGN_LOG.md` and `KICKOFF_PROMPT.md`. Owner's decision (25 Sep): **everything is built from blank, code and data**. The prototype is read for lessons only; no module is copied or imported from it.
- **No starting data.** The new database begins empty and is filled only through the NAPIX daily cycle, user searches and department discovery. The migration of the scraper-based system's data described in the plan (section 7) is not done; no staging tables, importer or `migrate` command are built.
- New schema designed from the plan; fresh Alembic history.
- Repository reorganised on 25 Sep: NAPIX JSON specs moved from `High Court Case Status API/` to `docs/specs/napix/hc/`; the 1,792 cause-list PDFs untracked and moved to `data/causelists/`; `archive/legacy/` and the prototype moved out of the workspace; `.venv-legacy`, `case_documents/`, `order_documents/` removed; `.gitignore` expanded; `docs/DESIGN_LOG.md` and `docs/KICKOFF_PROMPT.md` removed as superseded (copies in the prototype folder).

## Superseded decisions (changed by the portal plan)
- Ownership: auto-confirm threshold and central triage are REMOVED. The system only recommends; a department must claim (see Ownership below).
- AI: Ollama / local model and the in-portal knowledge repository are REMOVED. All AI work goes through SourceTrace, the in-house RAG solution (see SourceTrace below).
- Frontend: "React UI per canvas" is replaced by a Next.js frontend, following the current UI screens.
- Dropped from scope: caveat monitoring; mapping accuracy report; any feedback loop that tunes codes/weights from claims and dismissals.

## Audit verdict on legacy repo (now archive/legacy/)
- ~11k lines FastAPI/SQLAlchemy/Celery/React, AI-generated in layers, never reconciled. Core automation loop non-functional (stub ingestion, mismatched Celery queues, broken scraper task, no refresh loop, bad keyword normalisation, fabricated CINOs, 3x duplicated upserts, unauthenticated causelist endpoints, per-process SECRET_KEY).
- Salvaged: GHC portal JSON endpoints, PDF hyperlink CINO extraction idea.

## Existing scraper-based system (development team) — migration source
- Next.js frontend, Python backend, PostgreSQL. Built first for the Education Department.
- Cause lists Jan 2025 – Aug 2026 downloaded; entries parsed with regex (case number, main parties, petitioner/respondent advocates, court number, division bench, case URL); case details collected through the GHC portal's exposed APIs; linked older cases also captured; orders in file storage with links in DB.
- Holds 86,219 cases, 394,153 orders, 55,128 case links.
- Tables: all_case_api_data, all_causelists, case_advocates, case_orders, case_parties, cases, cases_linked, user.
- Alerts only for orders with a specific next date. Verified by random sample (cause lists, then cases) against the court portal.
- Earlier decision (migrate this data into the new database, then keep it current through NAPIX; ingest existing orders into SourceTrace in batches) is **withdrawn** by the owner on 25 Sep: the new system starts with no data. The figures above remain as background only.

## Decisions
- Greenfield build from the plan; fresh Alembic history; new schema.
- Stack: Python backend (FastAPI), Celery + Redis for background jobs, PostgreSQL + PgBouncer, Next.js frontend, Docker Compose. Monitoring: Prometheus/Grafana, Flower.
- State-wide, multi-department. Visibility tiers: STATE (CM/CS, read-only all) → DEPARTMENT (self + directorates) → DIRECTORATE (own + requests). 2-level hierarchy for now (offices self-ref path; 3rd level possible).
- eOffice-style CUSTODY per case (holder office/officer, pending action, since, due) derived from Requests/Stages/Assignments; tracking card visible to every signed-in user; contents scoped.
- CASE NOTES / NOTING TRAIL: append-only `case_notes` belonging to the case, following it across custody moves. Author snapshot frozen on each note (name, designation, office, role); per-case seq_no; custody leg recorded; kinds general/handover/instruction/opinion/hearing_note/compliance/decision/system; immutable — corrections via `supersedes` (both kept); attachments = documents substrate rows via `case_note_attachments` (sha256 dedupe, reusable across notes); visibility case_scope | counsel_shared | private_to_office; State tier sees all. `hand_over()` = handover note + custody move in one step. Events NOTE_ADDED/FILE_ADDED + audit_log row per note.
- Courts & sources: GHC PRIMARY = NAPIX HC API; SUPPLEMENTARY = GHC website (cross-checks and gaps). District courts = NAPIX DC API (Phase 3). NAPIX credentials approved; kept in `.env`, never committed.
  - Cause lists: Cause List Bench → Cause List Details as the main source; Show Cause List document parsed as a cross-check. Earlier note said HC cause lists arrive only as PDF via hc-show-causelist, so the parser is central — settle this in the live NAPIX test. Keep the parser until Cause List Details is confirmed complete.
  - Case data: Search by CNR (full history, on first sight + weekly refresh); Current Status (daily, many CNRs per call); Show Order (new orders); Show Business (proceedings).
  - Search: portal DB first; if not found, NAPIX Case No./Filing No./Party/Advocate search, then Search by CNR, then store.
  - Department discovery: department party names/keywords run periodically through Search by Party Name.
  - All NAPIX calls go through the integration layer (encryption, tokens, retry, rate limits). Schedules to be confirmed after the live test.
- OWNERSHIP (recommend and claim):
  - Signals: standing counsel code in the cause list advocate column (strongest, e.g. SC, EDU), keywords/name patterns in party names, linked-case history (related case already claimed), department watchlist. Combined into a 0–1 score per department.
  - ≥ 0.85: strong recommendation, top of the department inbox. 0.50–0.85: possible match in the inbox. < 0.50: not recommended; stays in the unclaimed pool, searchable and claimable by any department.
  - NO case is assigned automatically. A case becomes a department's only when the department claims it. Department can dismiss a recommendation and suggest another department (which then gets the recommendation).
  - More than one claimant → one primary owner, others watchers. Central operator follows up unclaimed cases.
  - Inbox tabs: Recommended, Claimed, Unclaimed pool, Transfers. Each recommendation shows the signals behind its score.
- ALERTS: generated from the most recent order. Specific date → read directly. Period ("list after two weeks") → SourceTrace reads the order, date counted from the order date. Unclear direction → flagged for manual review. Dashboard: within 48 h = critical; this week highlighted. Alerts go to case owner and custody holder.
- SOURCETRACE (in-house RAG; replaces Ollama and the knowledge repository):
  - Ingestion API: each court order (automatic on download) and each uploaded court filing, with CNR, case number, court, document date. Portal records ingestion status (pending/ingested/failed) and the SourceTrace reference; failures retried automatically; persistent failures listed on an admin screen. Same mechanism for the one-time backfill of existing orders, in batches.
  - Query API: next-date extraction; Case Assistant questions; general research.
  - Acts, rules and policies are uploaded directly into SourceTrace, not through the portal.
  - Actual endpoint names/shapes not yet available — build the connector behind an interface so they can be filled in later.
  - Never sent to SourceTrace: notes, internal documents.
- CASE ASSISTANT: AI chat window on every case page, backed by the SourceTrace query API. Portal passes case context (CNR, details, orders, court filings). Answers draw on the case's orders and filings, related past cases, and Acts/rules/policies; every answer cites sources that open in the portal. An answer can be copied (with references) into a new case note. Conversation history saved per user per case, visible only to that user. General research without a case is also available.
- CASE DOCUMENTS: users upload documents to a case (writ petition, affidavit-in-opposition, reply, rejoinder, IAs, annexures, compliance reports, parawise comments, instructions to counsel). Each upload records type, date, description, uploader and office. PDF, Word, images; size limit; virus scan before storage. Two groups: court filings (ingested into SourceTrace) and internal documents (never sent). Visibility per document: case_scope | counsel_shared | private_to_office.
- Deployment: Docker Compose on a pilot server → State Data Centre / on-prem. No cloud LLM. Backups and monitoring from the pilot stage.
- Auth: local accounts + OTP. Roles: state_oversight, dept_admin, dept_officer, dept_head, directorate_user, referral_reviewer, standing_counsel, central_operator, auditor.
- Channels: in-app + email baseline; SMS for high priority (e.g. hearing within 48 h); daily digest option. Department lifecycle guided, not enforced.
- Portal modules (plan Section 5): Dashboard; Search; Case detail page (Overview, Hearings, Orders, Documents, Linked cases, Notes & files, Case Assistant); Department case inbox; Alerts & hearing calendar; Orders & case documents; Custody & workflow; Case notes trail; Case Assistant & legal research; Reports (no mapping accuracy report; includes data collection health); Administration (departments/offices, code-to-department mapping, keywords/patterns, users/roles, NAPIX masters); Notifications; Audit log.

## Phasing (from the plan)
- Phase 1 (Core): live NAPIX test; ~~migration of existing data~~ (withdrawn, no starting data); daily data cycle through NAPIX; department mapping and inbox; case tracking; orders archive; case document upload; alerts for specific-date orders; search; case detail page; administration; login and roles; in-app and email notifications; dashboard.
- Phase 2 (Workflow): custody and workflow; case notes trail; automatic ingestion of orders and court filings into SourceTrace (incl. existing orders); SourceTrace-based alerts for period-based orders; SMS; reports.
- Phase 3 (Extension): Case Assistant and legal research through SourceTrace; District Court cases through NAPIX DC API.

## Database (new design)
The schema is designed new from the plan. It must cover at least:
- Organisation: departments, directorates, offices (hierarchy), users, roles.
- Cases: cases (CNR business key), parties, advocates, hearings/proceedings, linked cases.
- Cause lists: daily cause lists and their entries.
- Ownership: codes, keywords/patterns, watchlists; per-department scores and signals; recommendations with status recommended/claimed/dismissed and suggested department; primary owner + watchers; unclaimed pool.
- Workflow: custody, requests between offices, stages, due dates.
- Case notes: append-only notes with author snapshot, supersedes, attachments, visibility.
- Documents: court orders and uploads; group (court_filing | internal), type, visibility, virus-scan status, SourceTrace ingestion status + reference.
- Alerts and notifications: next dates (with source: specific date / period via SourceTrace / manual review), alerts, notifications sent.
- Case Assistant: conversations and messages per user per case, with cited references.
- Audit log (append-only).
- Operations: job runs, NAPIX call log and source failures, so the "data collection health" report has something to read.
Previous designs for reference only: the scraper-based system tables listed above and the prototype's 56-table schema. No migration staging tables.

## NAPIX spec findings (25 Sep, from the JSON stubs and the Postman collection)
- The 22 JSON files are IBM API Connect stubs: every API takes `dept_id`, `request_str`, `request_token`, `version` and returns a string. Input field names (`est_code`, `causelist_date`, `bench_id`, `causelist_id`, `cino`, `order_no`, `order_date`, `business_date`, `case_type`, `reg_no`, `reg_year`, `state_code`) and response keys come from the PDF spec, which must be added to `docs/specs/napix/hc/`.
- Every API in the plan's Table 4 has a stub. Current Status is the only POST. Show Order needs `order_no` and `order_date` (both from the CNR response). Search by Case Number needs the numeric `case_type` code, so **Case Type Master is added to the usage map** (setup + monthly). Act Master is needed only if Search by Act is kept; Advocate Bar Reg, Neutral Citation and the two Caveat APIs are not used. `overview` serves as the credential/connectivity health check.
- To settle in the live test: (1) whether Cause List Details returns case rows or only the list of cause lists per bench (the schema stores entries from `napix_details` and `pdf_parse` separately until then); (2) `est_code` for the Principal Seat (assumed GAHC01) and the outlying benches, `state_code` (assumed 6); (3) auth-key encoding (text / hex / base64); (4) whether PDF APIs return raw `application/pdf` or base64 inside `response_str`; (5) the exact nested-object keys (`case1…`, `sr_no1…`) per API.

## Lessons from the earlier v2 prototype (code not available)
- A cause-list parser read the case number (CNR) correctly on all rows of 5 real cause lists (1,518 rows): the approach works, but the parser must be written again.
- Code-and-keyword matching over the backfilled cause lists produced recommendations across about 20 departments, which supports the scoring approach.
- The standing counsel codes, name patterns and office list used there are not available; they must be compiled again, from the cause lists and with the departments.
- The notes trail design (append-only, author snapshot, hand-over as one step) is recorded under Decisions and still applies.

## Next
1. ~~Propose project structure and new database schema from the plan; get approval.~~ Done 25 Sep (plan file approved; structure and Phase 1 schema recorded in `CLAUDE.md` and `docs/schema/phase1.md`).
2. Backend skeleton and Alembic `0001_phase1_core`; `aslms napix-check` CLI that exercises overview → state → bench → case type → CNR → current status → causelist bench/details → show causelist and saves each decrypted response shape under `docs/specs/napix/hc/samples/`. This is the live NAPIX test; it answers the five open points above.
3. Compile the initial code-to-department mapping, name patterns and office list (from cause lists and department input).
4. Phase 1 build: integration layer, daily data cycle, cause-list parser (cross-check), department mapping + recommend/claim inbox, case tracking, orders archive, case document upload with virus scan, specific-date alerts, search, case detail page, administration, auth (local accounts + OTP) and RBAC with visibility tiers, in-app + email notifications, dashboard, Next.js frontend per the current UI screens.
5. SourceTrace connector behind an interface (endpoints pending) — needed from Phase 2.
- Open: GHC website URL template unverified; PDF spec not yet in the repo.
