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

## Build decisions (26 Sep 2026, Phase 1 backend)
- **Synchronous services.** Services take a sync SQLAlchemy `Session`; FastAPI runs the sync handlers in its thread pool, and Celery tasks and the CLI call the same code. The async NAPIX client is driven with `asyncio.run` from those paths.
- **NAPIX master switch.** `NAPIX_ENABLED` (default false). Nothing calls the gateway until it is true, even when credentials are present in `.env`. Added after the first backfill run reached the gateway with the prototype's leftover credentials (both calls were rejected: an undecryptable status, then `626 INVALID_TOKEN`).
- **NAPIX error shape seen live:** besides encrypted `{"status": …}` bodies, the gateway can answer with a PHP `print_r` dump (`Array ( [status_code] => 626 [status] => INVALID_TOKEN )`). The client maps both to typed errors.
- **Cause-list parser (new, from scratch):** column bounds from each file's header row; CNR only from the case-number hyperlink; `WITH` → connected matter; `in X` → parent case (IA link); wrapped advocate names and wrapped counsel codes joined. Measured on 60 random 2024–2026 lists: 15,049 entries, 15,044 of 15,045 CNR links captured (the one miss is a placeholder CNR dated 1900 on empty space), ~0.15 s per list.
- **Entry numbering:** `causelist_entries.sr_no` is the entry's position in the list (unique); the printed serial is kept in `raw.printed_sr`, because connected matters often have no printed serial.
- **Recommendations go to departments.** Signals on a directorate roll up to its department; the directorate is kept as `suggested_unit` in the signals. Generic State codes (`PP, ASSAM`, `GA, ASSAM`) add nothing to a score. A department's earlier dismissal or claim is never re-opened by the engine.
- **Allotment.** After claiming, a department allots the case to a unit (directorate/section) and/or an officer: `case_ownership.unit_office_id` (migration 0002). Directorate users see cases allotted to their unit; officers see cases allotted to them or their unit.
- **Standing counsel scope.** A standing-counsel user belongs to a counsel office under a department and sees cases where a counsel code mapped to that department appears, plus documents shared with counsel and court records.
- **Next dates from orders (Phase 1).** A specific date in the latest order is read by rule; a period ("after two weeks") produces a counted hint flagged for manual review and an alert; SourceTrace replaces the hint in Phase 2.
- **Security details found by the tests:** OTP attempt counters and refresh-token revocation are committed before the error is returned (the request transaction rolls back on error, which had silently disabled both); `audit_log.ip` stores only valid addresses.
- **Demo data:** `aslms seed-demo` (refused when `APP_ENV=prod`) loads a few real department names, the most frequent counsel codes and one account per role, for development and demonstration only. The real mapping still comes from the departments (Next item 3).

## Build decisions (26 Sep 2026, Phase 2 and 3 backend)
- **Custody is derived.** Claim → the department office; allotment → the unit and/or officer; request sent → the receiving office (with the request's due date as the custody due date); answered or withdrawn → back to the requester; transfer accepted → the new department; release → the next primary owner; hand-over → explicit move with a mandatory hand-over note written in the same step. Each move appends a `custody_history` leg and a tracking-card event, so every signed-in user sees where a case is and since when.
- **Scope widened by workflow.** An office also sees cases it currently holds and cases with a request addressed to it (directorates; referral departments asked for views). For department officers and referral reviewers this access is personal only (held by, or addressed to, them) so an officer in the department office does not inherit every case the department holds.
- **Stages** are the 17-stage lifecycle from the department workflow note; any stage may be set; stages skipped on the main track are returned and shown as a gap.
- **Notes** are append-only in the database (trigger), numbered per case, carry the custody leg, and are corrected by superseding notes. Attachments are internal documents and are excluded from SourceTrace by rule and by query.
- **SourceTrace** ingestion (court orders and virus-clean court filings only; never notes, note attachments or internal documents), retries, period next-date reading (advisory: stored as `order_period` needing confirmation), and the Case Assistant's conversation storage are built against the `KnowledgeService` interface. Everything stays off until `SOURCETRACE_ENABLED=true` and a real connector replaces the stub.
- **Request alerts:** open requests due within two days (high) or overdue (critical) alert the receiving office or addressee; case alerts also go to the custody holder.

## Build decisions (27 Sep 2026, e-mail and sign-in codes)
- **Mail service: Mailtrap** (owner's choice). Two ways, chosen by `MAIL_BACKEND` (default `auto`): the Mailtrap Email Sending API (`MAILTRAP_API_TOKEN`, `MAILTRAP_API_URL`; the sandbox URL for testing) or SMTP (Mailtrap SMTP or any other). `auto` prefers the API token, then SMTP, then the console. The sender (`SMTP_FROM`) must be on a domain verified in Mailtrap for live sending. A mail failure while sending a sign-in code returns a clear 502, never a crash, and the token is never logged.
- **Resend code** on the sign-in and password-reset pages, with a two-minute countdown. The wait is enforced by the server (`OTP_RESEND_SECONDS=120`, 429 with `retry_after`), plus a cap of `OTP_MAX_PER_HOUR=10` codes per account. Resending invalidates the previous code. The password-reset endpoint needs no password, so a repeat request inside the wait sends nothing and answers exactly as before (no inbox flooding, no account disclosure).

## Next
1. ~~Propose project structure and new database schema from the plan; get approval.~~ Done 25 Sep (plan file approved; structure and Phase 1 schema recorded in `CLAUDE.md` and `docs/schema/phase1.md`, now `docs/schema/schema.md`).
2. ~~Backend skeleton and Alembic `0001_phase1_core`~~ Done 25 Sep: 39 tables, 48 enum types created explicitly in the migration, append-only triggers on `events` and `audit_log`, upgrade → downgrade → upgrade verified by `tests/integration/test_migrations.py`; seed creates STATE / CENTRAL / AG offices, GAHC01 and the operator account. NAPIX integration layer (`backend/aslms/integration/napix/`: crypto with the Subscriber Manual known-answer test, client with token/envelope/rate limit/retry/call hook, HC adapter implementing `CourtSource`) and the `aslms napix-check` CLI are written and tested offline against a mocked gateway (25 tests green). **Pending: run `aslms napix-check` with the real credentials** (overview → state → bench → case type → causelist bench/details → show causelist → CNR → current status → show business → order); it saves each decrypted response under `docs/specs/napix/hc/samples/` (git-ignored) and answers the five open points above.
3. Compile the initial code-to-department mapping, name patterns and office list (from cause lists and department input).
4. Phase 1 build: integration layer, daily data cycle, cause-list parser (cross-check), department mapping + recommend/claim inbox, case tracking, orders archive, case document upload with virus scan, specific-date alerts, search, case detail page, administration, auth (local accounts + OTP) and RBAC with visibility tiers, in-app + email notifications, dashboard, Next.js frontend per the current UI screens.
5. SourceTrace connector behind an interface (endpoints pending) — needed from Phase 2.
3b. Phase 2 backend (custody, requests, stages, notes trail, SourceTrace ingestion tracking) and the Phase 3 assistant storage built and tested (26 Sep); 70 tests. Deployment: production compose with nginx, PgBouncer, ClamAV, Prometheus/Grafana, exporters and nightly backups.
3a. Phase 1 backend built and tested (26 Sep): daily cycle, parser, scoring and inbox, auth with OTP, scope in SQL, documents with virus scan, orders and next dates, alerts and notifications, search with NAPIX fallback, dashboard, reports, administration, audit; 63 tests.
- Open: GHC website URL template unverified; PDF spec not yet in the repo; NAPIX live test pending (`NAPIX_ENABLED=true`, then `aslms napix-check`).

## Milestone DB-1 — pre-migration baseline (29 Sep 2026, DB_STANDARD v1.2 §12.2 step 5)

Recorded before any change of this milestone, from the running stack (`postgres:16`, volume `pgdata_v2`,
alembic head `0003`, 49 application tables + `alembic_version`). The owner confirmed the data is test data.

**How the data was produced.** NAPIX was never reached (`NAPIX_ENABLED=false`; the two calls of 26 Sep were
rejected, see the build decisions above). Everything came from the cause-list PDFs on disk under
`data/causelists/DD-MM-YYYY/` through `LocalDirSource` (files whose names contain notice, roster, sitting,
swearing or circular are skipped), with first-sight fetches and order downloads skipped:

| # | When (UTC) | Command | Folder dates | Result |
|---|---|---|---|---|
| 1 | 26 Sep 15:47 | `aslms cycle --date 2025-09-01`, then `--date 2025-09-02` | 2 | both `partial` (one NAPIX failure each; the master switch was added right after) |
| 2 | 26 Sep 16:17 | `aslms backfill --start 2026-07-27 --end 2026-08-05` | 8 | succeeded |
| 3 | 27 Sep 16:18 | `aslms backfill` (from the earliest folder) | 162 (2024-08-01 … 2025-05-01) | interrupted at 2025-05-02 by the Docker rework (its `job_runs` row is still `running`; nothing of that date was committed) |
| – | 27–29 Sep | beat `daily-cycle-*` for 2026-09-27 … 2026-09-30 | 0 | no folders for those dates; ingested nothing |

Seed: `aslms seed` (STATE, CENTRAL, AG; GAHC01; `admin@aslms.local`) and the demo data
(`aslms seed-demo` on 26 Sep before batch 2, again through `aslms bootstrap --demo` on 27 Sep, which also
ran `rescore_all`): 15 demo offices, 22 counsel codes, 7 name patterns, 4 keywords, 9 demo accounts. One
account was created by hand (`nayan.semt@gmail.com`, dept_admin, SEC-EDU).

Of the 449 folder dates on disk (1,791 PDFs), 172 were ingested (518 lists: 167 daily, 177 supplementary,
165 lawazima, 2 vacation, 7 other); the 277 dates from 2025-05-02 to 2026-07-24 were never processed.

**Manual actions through the portal** (not reproduced by ingestion): 1 claim (`GAHC010185692025` by SEC-EDU
on 26 Sep 16:55 UTC), 4 custody moves, 1 request with 2 messages, 2 stage changes, 7 notes with 2
attachments, 3 uploads (1 court filing, 2 internal), 2 assistant conversations, 15 sign-ins.

**Gate step 5 numbers.**

| Measure | Now | Expected after the rebuild (no manual claim) |
|---|---|---|
| cases | 49,568 (12 provisional; all `first_seen_source = causelist`) | 49,568 |
| causelist_entries | 126,036 (all `pdf_parse`; 126,022 resolved, 14 provisional) | 126,036 |
| recommendations by band | high 10,915 (10,914 recommended + 1 claimed); medium 0 | high 10,915, all recommended |
| unclaimed pool (cases with no active ownership) | 49,567 | 49,568 |
| case_office_scores | 10,932 rows over 9,025 cases | 10,932 |

**Every table, for gate step 7 (idempotency).** Rows that only manual actions or sign-ins produce are marked *m*.

| table | rows | table | rows | table | rows |
|---|---|---|---|---|---|
| alerts | 3 *m* | case_types | 0 | notifications | 6 *m* |
| assistant_conversations | 2 *m* | cases | 49,568 | office_keywords | 4 |
| assistant_messages | 6 *m* | causelist_entries | 126,036 | office_name_patterns | 7 |
| audit_log | 31 *m* | causelist_reconciliations | 0 | office_watchlist | 0 |
| benches | 0 | causelists | 518 | offices | 18 |
| case_acts | 0 | counsel_codes | 22 | orders | 0 |
| case_advocates | 245,087 | courts | 1 | otp_codes | 15 *m* |
| case_hearings | 126,000 | custody | 1 *m* | ownership_transfers | 0 |
| case_links | 22,630 | custody_history | 4 *m* | recommendations | 10,915 |
| case_note_attachments | 2 *m* | digests | 0 | refresh_tokens | 15 *m* |
| case_notes | 7 *m* | document_text | 0 | request_messages | 2 *m* |
| case_office_scores | 10,932 | documents | 521 (518 cause lists + 3 *m*) | requests | 1 *m* |
| case_ownership | 1 *m* | events | 335,173 (≈ 22 *m*) | source_failures | 4 |
| case_parties | 0 | job_runs | 191 | sourcetrace_ingestions | 0 |
| case_snapshots | 0 | master_sync_runs | 0 | user_notification_preferences | 3 *m* |
| case_stages | 2 *m* | napix_call_log | 2 | users | 11 (10 seeded + 1 *m*) |

Events by type: next_date_extracted 125,998; listed 111,964; case_created 49,569; case_linked 22,630;
listed_supplementary 14,069; recommendation_made 10,915; source_failed 4; the rest are manual.

**Reproduction after the rebuild** (`docker compose down -v && docker compose up -d --build`; `init` runs
`alembic upgrade head` and `aslms bootstrap --demo`, so the demo mapping exists before ingestion), in the
original order:

```bash
docker compose exec api aslms backfill --start 2025-09-01 --end 2025-09-02
docker compose exec api aslms backfill --start 2026-07-27 --end 2026-08-05
docker compose exec api aslms backfill --start 2024-08-01 --end 2025-05-01
```

Differences that are expected and are not drift: batch 1 originally ran through `cycle` (alerts raised) and
before the demo codes existed, so its recommendations came from the later `rescore_all`; `job_runs`,
`source_failures` (the two NAPIX rows) and everything marked *m* are not reproduced. Any other difference in
the step-5 numbers is a regression to explain before anything is changed.

## Build decisions (29 Sep 2026, Milestone DB-1 — DB_STANDARD v1.2)

Executed §11 steps 1–7, one commit per step (`DB-1 step N` in the log), after the baseline above.

- **Fresh migration history.** `0001_phase1_core`, `0002_ownership_unit` and `0003_phase2_workflow` are replaced by
  one `0001_core` (67 tables). The baseline data was rebuilt from the same cause-list PDFs (gate step 5).
- **Code sets stay Python enums in the ORM.** The eight `ref_*` columns are `varchar(40)` with a foreign key, mapped
  with `sa.Enum(native_enum=False)`, so services, tests and the API keep the enum members; only the storage changed.
  A ninth set, `ref_record_type`, backs reference numbers. The test database fixture seeds the code sets after
  every truncate, because no row can be written without them.
- **Reference numbers in URLs.** `/` in `ASLMS/GOA/CASE/2026/000001` cannot travel in a path segment, so the API also
  accepts the same number with `-` (`ASLMS-GOA-CASE-2026-000001`); office codes may contain `-`, so the number is
  parsed from the right (type, year, serial are the last three parts). `resolve_case_ref` takes an id, either
  form of the number, or a CNR, and every `/cases/{case_ref}` route uses it.
- **Two master mixins.** `MasterMixin` (`is_active`, `deactivated_at`, `valid_from`, `valid_to`) on the versioned
  organisation masters (`offices`, `designations`); `DeactivateMixin` (the first two) on the other masters, which
  the standard does not version.
- **Designations.** `users.designation_id` points at the master; `users.designation` keeps the text shown at write
  time (author snapshots freeze it), and stays free text for designations not yet in the master.
- **LGD codes are not guessed.** `states` and `districts` are seeded by name (Assam, LGD 18, and its 35 districts;
  Sribhumi for the former Karimganj). The LGD district codes could not be fetched (the LGD and data.gov.in portals
  refuse automated access) and are entered under Administration when supplied; the NAPIX district master fills
  `ecourts_code` through `master_sync`, which now also syncs states and acts (act master added to the API map).
- **Creation cycle.** `offices.created_by` → `users` and `users.office_id` → `offices` (and `users` ↔
  `designations`) form a cycle; the fifteen audit foreign keys are declared `use_alter` and the migration adds them
  after the tables (SQLAlchemy omits `use_alter` keys from a single-table CREATE, so the post-processor emits them).
- **Roles.** `aslms_owner` (NOLOGIN, granted to the migrating user), `aslms_app` and `aslms_readonly` are created by
  `0001_core` only if absent (roles are cluster-wide) with passwords from `ASLMS_APP_PASSWORD` /
  `ASLMS_READONLY_PASSWORD`; downgrade revokes their privileges in the database (`DROP OWNED BY`) and leaves the
  roles. Compose runs the API and workers as `aslms_app`, `init` and PgBouncer's pool credentials follow; the
  nightly backup adds `pg_dumpall --roles-only`.
- **Alerts allocate a number only when new.** The daily generator looks the dedupe key up before inserting, so
  re-runs do not burn serials (gaps are allowed, but not one per existing alert per day).
- **`closed_at`** is set when a case is first seen disposed (CNR or Current Status); "owner closure" has no
  separate action yet.
- **`other` document type** is grouped as `court_filing` in `ref_doc_type`; the uploader still says whether an
  `other` file is internal, as before.
- **Dossier fixture.** `tests/fixtures/cnr_dossier_shape.json` carries the documented field names of every §10
  block but is constructed, not recorded; the live `aslms napix-check` replaces it.
- **Party history.** The dossier apply upserts parties on (case, role, party_no) and marks the missing ones
  `is_current = false`; advocates are matched to the `advocates` master only when a bar registration number is
  known (none in the current dossier fields).
- **Deletion.** No service deletes any more; the four mapping DELETE endpoints deactivate and return the row.
  Documents have no delete endpoint; `archived_at` is the retirement column for when one is needed.
- Open: the real dossier field names (live test), the LGD codes, PostgreSQL schemas per bounded context (§9,
  revisit with Phase 3), retention/archive policy (§6, policy owner to confirm).

## NAPIX live-test basis (29 Sep 2026, product owner)
- **Three foundational documents govern NAPIX testing and integration:** eCourts Open API Specifications NAPIX
  v1.3 (22.04.2025), High Court Open API Specifications v1.0 NAPIX (07.09.2023) and the NAPIX Subscriber Manual
  v1.5 (22.04.2025). Where they differ from the gateway JSON stubs or the earlier Postman collection, these win.
- Points taken from them for the Postman test: token URL is `…/nic/ecourts//oauth2/token` (double slash, Subscriber
  Manual Annexure A); token lasts 1 hour; Basic Auth username/password = the NAPIX app's **Key/Secret**; the
  header `Content-Type: application/x-www-form-urlencoded` is set explicitly; `Authorization` must be exactly
  `Bearer <token>` (no newline); SSL verification is switched off in Postman per the manual (test only — the
  backend keeps verification on); an app must be subscribed to the API product before calls succeed (631 otherwise).
- **First live result (29 Sep, Postman, dept_id `itdepartment-as`).** Token call succeeds. Overview GET returns
  HTTP 200 from the eCourts backend (cookie path `/high_court`, domain `api.ecourts.gov.in`) with an encrypted
  `{"status": …}` body of 48 bytes that does **not** decrypt with the issued Authentication Key (not as text key,
  not in any obvious encoding; even CBC blocks 2–3 stay unreadable, so it is the key, not the IV). Request
  encryption was verified against the Subscriber Manual known-answer test. Open: whether the HC backend holds a
  different key for this dept_id (HC spec §3: key issued "by e-Committee or respective High Court"); next test is
  the SM's own DC District call (`state_code=27`) to tell a DC key from an HC key.
- **Key diagnosis (29 Sep, 13:00–13:05 IST).** (A) DC District `state_code=27` → gateway 401 "Cannot find valid
  subscription" (app not subscribed to the DC product; no key information). (B) HC Bench Master `state_code=6` →
  HC backend `626 INVALID_TOKEN` in plain text, with request_str/request_token verified. (C) Overview with
  `request_str=` blank → the same encrypted status as the first call, byte for byte (deterministic, so it is a fixed
  error message under a key we do not hold). 626 rather than 627 means the dept_id is recognised. Conclusion: the HC
  backend holds a different Authentication Key for `itdepartment-as`; raised with e-Committee / Gauhati HC CPC.
  Transaction IDs: e0b5ce896abbb685935bdd85 (B), e0b5ce896abbb6c4936065a5 (C), e0b5ce896abbb6670976b793 (A).

## NAPIX integration layer — design against the live notes (1 Oct 2026)
- `docs/napix_integration_design.md` fixes the target shape of `backend/aslms/integration/napix/` from
  `docs/napix_integration_notes.md`: variable names follow the notes (`NAPIX_BASE_URL`, `NAPIX_EST_CODE`; the old
  `NAPIX_BASE` / `NAPIX_HC_EST_CODE` stay accepted as aliases for one release; `NAPIX_AUTH_KEY_MODE` is dropped,
  the key is trimmed UTF-8 text cut or zero-padded to 16 bytes); the token URL keeps the manual's `//oauth2/token`;
  no-input APIs encrypt the empty string; the gateway's `httpCode` body and 631 are a `NapixGatewayError`; 626 /
  627 are `NapixAuthError` and are no longer retried; the token is cached per process and mirrored in Redis;
  the limiter reads `X-RateLimit-*`. Only `.env.example` changed with the design; the code follows after approval.
- Verified on 1 Oct: the Authentication Key now in `.env` decrypts both samples in `docs/specs/samples/` and their
  `response_token` verifies; the notes' `HMAC("")` vector reproduces. The 29 Sep key problem is resolved.

## Full system reset (1 Oct 2026, product owner)
- The owner asked for a full system reset with the new database design. Decisions: the September build (Phase 1
  and 2 backend, Next.js portal, infra, the DB-1 migration `0001_core`, 89 tests) moves to
  `D:\Dev Workspace\ASLMS-legacy\v3-sept-build` as reference only, like v1 and v2; the workspace keeps the documents;
  git history is kept (one reset commit); the rebuild starts from `docs/DB_STANDARD.md` v1.2 and
  `docs/schema/schema.md` as the approved design, with no new schema proposal round; the first module is the NAPIX
  integration layer per `docs/napix_integration_design.md`, followed by the live `napix-check`.
- **Every NAPIX field is kept** (owner). The gateway stubs in `docs/specs/napix/hc/` define only the envelope, so
  field names come from the live samples and the e-Committee PDF specifications. Two layers guarantee coverage:
  every response is stored verbatim as JSON, and a field inventory built from the samples (`aslms napix-fields`
  → `docs/specs/napix_field_inventory.md`) is mapped field by field in a coverage table added to `schema.md`
  before migration 0001; a test fails on any inventoried key path without a home.
- The DB-1 acceptance gate stays recorded as it ended: steps 1–4 and 6 passed, step 5 reproduced every count but
  nine recommendations and 71 advocate rows, traced to the baseline's first two dates having been ingested from
  uncommitted code on 26 Sep; steps 7–10 were not run because the build was reset instead.
- Still open from before: the LGD district codes, the SourceTrace API shapes, the NAPIX DC specification, the
  three NAPIX PDF specifications to be added under `docs/specs/pdf/`.

## Deployment target for the pilot (1 Oct 2026, product owner)
- The pilot / PoC runs on the owner's local machine only: one Docker Compose stack (`compose.yml`) with Postgres,
  PgBouncer, Redis, API, workers, beat, frontend and monitoring on one host.
- The later on-premise layout (a data VM with PostgreSQL, PgBouncer and the document store; a stateless app VM
  with Docker Compose) is deferred, not designed now. To keep that move a configuration change, the pilot code
  must: take every connection from `.env` (`DATABASE_URL`, `ASLMS_MIGRATE_URL`, `REDIS_URL`, storage settings),
  never hard-code container hostnames; reach stored files only through the storage interface; keep Postgres and
  the document store as the only stateful services, on named volumes.

## NAPIX live test (1 Oct 2026, `aslms napix-check`, 14 APIs verified)
- The Authentication Key issued for `itdepartment-as` now decrypts every response; 38 live calls, all verified
  against `response_token`. Facts recorded in `docs/napix_integration_notes.md` §1–§9 and the field lists in
  `docs/specs/napix_field_inventory.md` (142 paths across 14 APIs; samples in `docs/specs/samples/`).
- **Cause List Details returns list metadata, not case rows** (`bench, bench_id, causelist_id, cause_list_type`):
  the cause-list PDF (Show Cause List, a Base64 PDF in a JSON string) stays the source of entries and the parser
  stays primary, as the plan allowed for.
- **`NAPIX_STATE_CODE` is 18**, not 6: the state master is a list of High Courts (18 = Gauhati); 6 returned
  Chhattisgarh's bench and Haryana's districts. Bench master: `GAHC01` Principal Seat, `GAHC02` Kohima, `GAHC03`
  Aizawl, `GAHC04` Itanagar.
- **Current Status is a POST with the parameters in the query string**; a form or JSON body is refused by the
  gateway (400). The notes' earlier "form body" line was wrong and is corrected.
- Search by CNR is `/hc-cnr-api/CNR` (`/cnr` is a gateway 404); a transient HTTP 500 "URL Open error" is retried.
  The token response carries `expires_in` 3600.
- The district master's names are eCourts spellings (`Kamrup(M)`, `Sibsagar`, `Karimganj`, `Baska` beside `Baksa`,
  and non-districts `CBI`, `NIA`, `C/O 99 APO`); the LGD-coded `districts` master keeps its own names and maps
  the eCourts code by name.
- Not sampled yet: a pending case's dossier (IAs, objections, hearings in progress). The disposed sample dossier
  already shows 70 field paths, including `lower_court_*`, `trial_lower_court_*`, `pet_legal_heir`,
  `res_legal_heir`, `fir_no`, `police_st_code`, `uniform_code`, `document_details.*`, `category_details.*`.

## NAPIX quota measured (1 Oct 2026, `aslms napix-probe-rate`)
- 36 Overview calls at 20-second intervals: `X-RateLimit-Remaining` fell by one per call and never reset in 12
  minutes; the morning live walk (about 50 calls, 12:20–12:35) was no longer counted at 13:07. The quota is
  **1,000 calls per clock hour**, reset on the hour. Settings `NAPIX_RATE_WINDOW_SECONDS=3600` and
  `NAPIX_RATE_RESERVE=150` (calls kept for the daily cycle; the load queue stops pulling below it).
- Budget: about 23,000 calls a day, so the dossier load of roughly 100,000 cases listed since January 2025 takes
  four to five days of continuous running. A higher plan from e-Committee changes only the two settings.
- Past cause-list dates are served by NAPIX (2025-01-06: 22 benches; 2025-06-02: 24 benches), one PDF per
  (bench, list) per date, so the historical load runs through NAPIX with the website PDFs on disk as fallback.

## Migration 0001 and seed (1 Oct 2026)
- `backend/migrations/versions/0001_core.py` builds the whole approved design: 73 tables (`schema.md` 67 plus the
  addendum's `napix_responses`, `high_courts`, `causelist_bench_days`, `case_transfers`, `case_writ_info`,
  `fetch_queue`), 51 native enum types, `uuid_generate_v7()`, `set_updated_at()` on the 50 mutable tables,
  `aslms_forbid_change()` on `events`, `audit_log`, `case_notes`, `custody_history`, `case_stages`,
  `COMMENT ON TABLE 'class=…'` everywhere, roles `aslms_owner` / `aslms_app` / `aslms_readonly` with the §8 grants
  (`aslms_app` cannot DELETE from `cases`, cannot UPDATE the append-only tables; DELETE only on the eleven cascade
  tables). Upgrade → downgrade → upgrade is a test; so is "no autogenerate diff between the database and the
  models".
- Autogenerated from the model modules (`backend/aslms/domain/`), then post-processed once: enum types are created
  up front (three are shared by two tables), the 33 `use_alter` foreign keys (the `users` ↔ `offices` ↔
  `designations` cycle, `causelists.document_id`, `custody` links) are added after all tables, and the standard's
  functions, triggers, roles and grants appended. The migration holds static literals only and never imports the
  models.
- Role passwords come from `.env` (`ASLMS_APP_PASSWORD`, `ASLMS_READONLY_PASSWORD`); unset leaves the role without
  a login until an administrator sets one. Never logged.
- `aslms seed` (idempotent, keyed by code): the nine `ref_*` sets from the enums (stage phases, document groups,
  default alert severities and tracking-card events are seed data, editable under Administration); 18 Secretariat
  designations (a standard set; the owner's list replaces it when provided); Assam (LGD 18) with its 35 districts
  by current name, `ecourts_name` set where the NAPIX master spells differently (`Kamrup(M)`, `Sibsagar`,
  `Karimganj` for Sribhumi), LGD district codes left empty until entered; the Gauhati High Court (NAPIX state code
  18) with `GAHC01`–`GAHC04` from the verified bench master; the root office `GOA` (Government of Assam, kind
  state), which allocates `ref_no` for cases the system creates before any department claims them. No users, no
  department offices, no counsel codes: those are Administration data.
- Compose (`compose.yml`): `postgres` (16, host port 5433), `redis`, and `init` (builds `backend/Dockerfile`,
  runs `alembic upgrade head && aslms seed`); `docker compose up -d` is the one command. PgBouncer, the API,
  workers and the frontend join as they are built. Tests needing a database use `aslms_test` on the same server
  and skip when it is down.

## Cause-list parser and load pipeline, stage 1–3 (1 Oct 2026)
- **Both PDF kinds carry the CNR.** The NAPIX Show Cause List PDF and the website lists come from the same
  generator; the case-number cell of every entry is a hyperlink `…getcasedetails.php?cino=<CNR>`. The parser
  (`backend/aslms/parsing/causelist_pdf.py`, written new) takes the CNR only from that link, never from text.
  Entries without a link (pages the court published unlinked) are provisional cases keyed by the printed number
  and resolved later through Search by Case Number.
- Layout facts the parser relies on are listed in its module docstring. Three were found only by sweeping all
  1,323 website PDFs on disk (43,094 pages, 318,572 entries, 99.9 % with a CNR): rows printed on a horizontally
  scaled grid under an unscaled header (each entry carries its own scale, read from its case number's
  x-position); a respondent named `THE GAUHATI HIGH COURT AND 9 ORS` (the masthead is recognised only with its
  sub-title on the next line); consolidated lists without a court block. Lok Adalat, production and
  consolidated lists parse as `list_type = other` with the printed type kept.
- `causelist_entries.sr_no` is the entry's position in the list (the stable key); `printed_sr_no` is the serial
  as printed, absent on connected matters listed under `WITH`.
- **Masters:** the state and bench masters wrap their rows in one named key (`state`, `benches`); the act master
  is keyed by `(national_act_code, name)` (migration 0002, see the coverage addendum §E). District rows from
  NAPIX attach to the seeded district by name or eCourts alias (`Kamrup(M)`, `Sibsagar`, `Karimganj`, `Biswanath
  Chariali`, `South Salmara`); spellings with no seeded counterpart (`Baska`, `Mongoldoi`, `N C Hills`, the
  agencies `CBI`, `NIA`, `C/O 99 APO`) become their own rows under Assam, as the court uses them.
- **Pipeline:** `fetch_queue` rows are claimed with `FOR UPDATE SKIP LOCKED`; kinds and `ref` formats are in
  `backend/aslms/services/queue.py`. The runner (`services/runner.py`) stops pulling when the gateway's
  remaining quota is below `NAPIX_RATE_RESERVE`; every attempt is logged in `napix_call_log` and every JSON
  response kept in `napix_responses`; PDFs go to `documents` through the storage service
  (`STORAGE_DIR/<sha256[:2]>/<sha256>.pdf`). A cause-list day is NAPIX first and the website PDFs on disk
  (`CAUSELIST_DIR/<dd-mm-yyyy>/`) when the gateway has no benches for the date. `apply_dossier` writes every
  §C path; child rows are keyed by their natural keys and never deleted (parties and advocates that leave the
  dossier are marked not current).
- CLI: `aslms load --from --to` (enqueue days), `queue-run`, `queue-status`, `sync-masters`, `refetch-date`,
  `refetch-case`. Current Status batches, order PDFs and the Celery schedules are the next stage.

## Pipeline stages 4–5, schedules, Compose workers; first live week (1 Oct 2026)
- **Current Status batches** (`status_batch`, ref `<date>:<n>` = the n-th block of 500 non-disposed CNRs in CNR
  order): a change in next date, last date, status, purpose, disposal date or bench updates the case, writes a
  `next_dates` row (source `current_status`) and an event (`next_date_changed`, `status_changed`,
  `case_disposed`), and queues a dossier re-fetch at the re-fetch priority.
- **Order PDFs** (`order_pdf`, ref `<CNR>|<order_no>|<date>`): queued after every dossier apply for orders without
  a document (pending cases ahead of disposed ones); Show Order → `documents` (kind order, court record,
  SourceTrace pending) → `orders.document_id`; a 628 is `not_available` and retried by the weekly sweep.
- **Schedules** (Celery beat, IST): 06:00 masters; 06:30 and 18:30 yesterday/today/tomorrow's lists; 20:00
  status batches; Sunday 02:00 the dossier sweep of every pending case and the order-PDF retry. Beat only
  enqueues; `aslms queue-worker` (the Compose `worker` service) fetches, sleeping until the next clock hour when
  the quota is below the reserve. `aslms daily-cycle` enqueues the same by hand.
- **Compose:** `worker` and `scheduler` services; `./data` is mounted at `/data` (store and the website PDFs).
  `NAPIX_ENABLED` for the worker comes from the shell that runs `docker compose up`, default off.
- **First live week (2025-01-01 … 01-07):** 4 list days (01-02, 01-03, 01-06, 01-07), 3 days without a list
  (holiday and weekend), 99 list PDFs stored, 2,078 distinct cases queued; 150 dossiers fetched in the same run
  (148 applied, 1,155 party rows, 842 order references), 174 + 152 calls. Every Show Cause List response failed
  the `response_token` check (PDFs are kept; see the notes §4). The 2025-01-01 day is `skipped`: NAPIX has no
  benches for it.
- Admin endpoints (`/admin/napix/health`, the re-fetch buttons) wait for the API; the CLI covers them meanwhile.

## User types, functions and access control (1 Oct 2026, product owner)
- **Super admin** (`super_admin`, a tenth user type): holds every function in the application and manages
  access; cannot be denied a function or disabled by anyone. The first one comes from `ASLMS_SUPERADMIN_EMAIL`
  / `ASLMS_SUPERADMIN_PASSWORD` in `.env` (created by `aslms seed`, never logged) or `aslms users
  create-super-admin`.
- **Functions** are the 42 codes of `ref_permission` (`Permission` enum; module prefix `users`, `access`,
  `admin`, `cases`, `custody`, `requests`, `stages`, `notes`, `documents`, `alerts`, `next_dates`, `reports`,
  `dashboard`, `assistant`, `audit`). The **type matrix** (`role_permissions`, one row per type × function,
  seeded from Table 1 of the plan; `access_seed.DEFAULT_MATRIX`) says what each type has; only the super admin
  switches it (`access.manage_types`). **Per-user overrides** (`user_permissions`, grant or deny, never deleted)
  sit on top. Effective functions = enabled matrix rows + grants − denies; an inactive user has none.
- **Delegation** (owner's choice): `users.create`, `users.edit`, `users.set_type`, `users.enable_disable`,
  `users.grant`, `users.reset_password` are functions like any other, so a departmental admin can hold them.
  A non-super-admin may act only on users in their own office subtree (`offices.path`), only of the types
  `dept_officer`, `directorate_user`, `standing_counsel`, `referral_reviewer`, and may grant only functions
  they hold themselves. Every change is audited (`audit_log`) and raises `user_created` / `user_updated` /
  `access_changed`.
- The `referral_reviewer` type (in the approved list, absent from Table 1) is seeded with the reviewing
  functions of an officer without ownership or custody; the owner can adjust the matrix.
- Migration 0003; schema.md groups 0 and 1 extended first. Passwords are argon2id; the CLI (`aslms users …`,
  `aslms access …`) acts as the super admin named in `.env`. The API slice (login, me, user and access
  endpoints) follows in the same step.

## API slice: sign-in, users and access (3 Oct 2026)
- FastAPI application (`backend/aslms/api/`): `POST /auth/login` (argon2 check, audited), `POST /auth/refresh`
  (rotating refresh tokens stored hashed in `refresh_tokens`), `POST /auth/logout`, `GET /me` (the user and the
  effective functions), `GET/POST /admin/users`, `GET/PATCH /admin/users/{id}`, `…/enable`, `…/disable`,
  `PUT …/type`, `POST …/password`, `GET/PUT …/permissions/{function}`, `GET /admin/permissions`,
  `GET/PUT /admin/access/types/{type}/{function}`, `GET /admin/offices`. Access tokens are 30-minute HS256 JWTs
  signed with `ASLMS_JWT_SECRET` (32+ characters; the API refuses to start without it).
- Every endpoint resolves the caller's functions on the server (`require(Permission)`), lists are filtered to
  the caller's office subtree unless they hold `cases.view_all`, and every write goes through
  `services/access.py`, so the API cannot bypass the delegation rule. Compose gains the `api` service on port
  `API_HOST_PORT` (8000). OTP sign-in and notification preferences remain for a later step.

## The agent team (4 Oct 2026, product owner)
- Development becomes a team process run by specialised agents inside Claude Code, defined and versioned in
  the repository: `architect`, `developer`, `tester`, `reviewer`, `scribe`, `integrator`
  (`.claude/agents/*.md`), the slash commands `/team-cycle`, `/team-design`, `/team-approve`, `/team-status`,
  `/team-review` (`.claude/skills/`), and one orchestrating workflow (`.claude/workflows/team-cycle.js`).
- Owner's choices: one human gate (the design note of each backlog item is approved with `/team-approve`;
  build, test, review, docs and merge then run unattended, pausing only when a rule or an API field is
  missing); the backlog lives in `docs/backlog.md`; each feature is built on `feature/<slug>` and
  squash-merged locally after tests and review (no git remote yet; `github-and-ci` is a backlog item).
- Guardrails enforced by hooks rather than prompts (`.claude/settings.json`, `.claude/hooks/guard.py`): no
  access to `.env` files other than `.env.example`; applied migrations cannot be edited; the NAPIX master
  switch cannot be turned on in a configuration or code file; nothing is written to, copied or imported from
  `ASLMS-legacy`; every edited Python file is linted and formatted. `.claude/` is now versioned (only
  `settings.local.json` and `worktrees/` stay ignored).
- Artefacts: `docs/team/README.md` (how it works), `docs/team/definition-of-done.md`,
  `docs/team/design-template.md`, `docs/design/<slug>.md` per feature, `docs/reports/<date>-<slug>.md` per
  cycle, `backend/tools/docx_text.py` to read the plan. Continuous operation is `/loop 45m /team-cycle` while
  a session is open; a server-side scheduler needs the remote and CI.

## Cases API: visibility, search, case detail, search the court (2026-10-04)

**What was built** (design: docs/design/cases-api.md, approved 2026-10-04)
- Migration 0005 (by hand, `compare_metadata` diff empty): SQL function `aslms_case_search_vector(case_id)`, GIN
  index `ix_cases_search_vector_gin` and expression index `ix_cases_case_no_compact`. No new table, column or
  permission function.
- Services: `services/visibility.py` (one rule as named SQL bases: `state`, `owner`, `recommended`, `pool`,
  `allotted`, `custody`, `request`, `counsel`; used for lists in SQL and for one case in `can_view_case`);
  `services/case_search.py` (`parse_query` auto-detection of CNR, case number, ref number, party, advocate;
  word search through `search_vector`; the visible list); `services/case_detail.py` (overview, parties,
  hearings, orders, listings, links and two-level graph, timeline); `services/court_search.py` (shared dossier
  fetch, searches by CNR, case number and party name, `fetch-court`, quota guard, audit);
  `services/cases.py::refresh_search_vector`, called after every dossier, cause-list and court-search store.
- API (`api/routers/cases.py`): `GET /cases`, `/cases/search`, `/cases/{ref}`, `/{ref}/parties | hearings |
  orders | listings | links | links/graph | timeline`; `POST /cases/search-court` and `POST
  /cases/{ref}/fetch-court` (function `cases.search_court`). Reading needs `cases.view_scope` or
  `cases.view_all` (new dependency `require_any`).
- CLI: `aslms cases reindex-search`, `aslms cases show`.
- Settings (`.env`): `NAPIX_SEARCH_FLOOR=50`, `NAPIX_SEARCH_PER_USER_HOUR=30`,
  `NAPIX_SEARCH_TIMEOUT_SECONDS=60`.
- Tests: `tests/unit/test_case_search_parse.py`, `test_napix_crypto.py` (extended); `tests/db/test_case_visibility.py`,
  `test_case_search.py`, `test_case_detail.py`, `test_court_search.py`.

**Decisions** (reasons in the design note)
- Visibility is one rule written once; a department that transferred a case away stops seeing it unless it
  stayed as a watcher (decision 3). Department-wide holders of `cases.claim` read the full detail of pool
  cases; officers and directorate users do not. The standing-counsel rule from the 26 Sep log is kept.
- Search shows a summary of any non-merged case, marked `visible` or not, with owner office, pool status and
  `claimable`, so a department can find and claim a case; opening a case it cannot see answers 404 (decision 4).
- Court search is synchronous through the NAPIX layer. CNR and case-number searches return the local case or
  fetch its dossier at once; a party-name search stores and scores every hit without fetching dossiers (a
  button, `fetch-court`, fetches one on demand). Every attempt that reached the gateway is audited
  (`case.search_court`); reading cases is not audited.
- Quota guard: refused when the remaining hourly quota is below 50 calls; 30 court searches per user per hour;
  both are `.env` settings (the numbers are the architect's proposals, accepted at approval).
- A CNR search creates the case row only after the court answers with that CNR; `not_found`, failure or
  time-out leave no case, event or queue item (review fix). Party names are limited to letters, digits, spaces
  and `. , ' & ( ) / -`, enforced in the schema, the service and `build_plain` (which refuses `|` and `=`).

**Deviations**
- NAPIX Search by Advocate Name and by Filing Number are deferred (decision 12, scope): no live sample of
  their fields. Both are searched locally meanwhile. Backlog row 21.
- The developer's smaller deviations (hand-written migration 0005, `access_basis` listing every applicable
  basis, `match` naming the field, `dossier_status` on every search item, `fetch-court` 409 `already_fetched`
  on a CNR held by another case, `q` under 3 characters 422 or 400, the runner raising `NapixNotFound` for an
  empty dossier) are items 1-16 of the design note's Deviations section.

**Left for later**
- NAPIX search by advocate and filing number (row 21); merging a provisional case with the case holding its
  resolved CNR; order PDF download and per-document visibility (`documents-uploads`); alerts on new cases found
  by search (`alerts-notifications`); the portal screens (`portal-cases`).
- Verification against the loaded January 2025 days and a live CNR search (design "Verification") is run by the
  integrator with Compose up, the switch set for that run only.

## Design approvals
- 2026-10-04 — offices-admin: approved by the owner as written (docs/design/offices-admin.md)

## Offices administration (2026-10-04)
Built on `feature/offices-admin` from `docs/design/offices-admin.md` (approved 2026-10-04). Tests and review passed.

**What was built**
- No table or column added; no migration. The new function `admin.designations` (43rd in `ref_permission`)
  is seeded by `aslms seed`; the default matrix enables it for no type (the super admin holds it by definition).
- `backend/aslms/services/offices.py`: create, update, deactivate and reactivate offices; placement rules
  (state root only seeded; department, central and advocate_general under state; directorate under department;
  unit under department, directorate, central or advocate_general); immutable upper-case codes; path as the
  chain of codes from the root; deactivation refused (409 with counts) while active children, users,
  ownership or custody depend on the office; the office tree with active-user counts; first department admins;
  designation create, update, deactivate and reactivate.
- API router `backend/aslms/api/routers/offices.py` (prefix `/admin`): `GET /offices`, `/offices/tree`,
  `/offices/{code}`; `POST /offices`; `PATCH /offices/{code}`; `POST /offices/{code}/deactivate` and
  `/reactivate`; `GET` and `POST /offices/{code}/admins`; `GET`, `POST` `/designations`;
  `PATCH /designations/{code}`; `POST /designations/{code}/deactivate` and `/reactivate`. `GET /admin/offices`
  moved from `routers/access.py` unchanged in path.
- CLI `aslms offices create | list | deactivate`, acting as the `.env` super admin.
- Tests: `tests/unit/test_offices_rules.py`, `tests/db/test_offices.py`, `tests/db/test_api_offices.py`
  (including 401, officer 403, admin scope and no audit row on failures).

**Decisions (reasons in the design note)**
- Codes and kinds are immutable because codes are embedded in `ref_no`, `ref_sequences` and audit snapshots, and
  kind fixes the visibility tier. No re-parenting (it would rewrite the paths of a subtree and silently change
  who sees which case); a reorganisation is deactivate-and-create plus ownership transfers.
- Office writes need `offices.manage`; the super admin acts anywhere, a delegated holder only inside their own
  subtree and only on `directorate` and `unit`. Departments, central offices and the Advocate General's office
  are created by the super admin only.
- Designations have their own function so a department cannot edit the State-wide list.
- The first department admin is the same user row `POST /admin/users` would create (no second mechanism); only
  the super admin can create it because `dept_admin` is not delegable.
- Every write writes an audit row (`office.*`, `designation.*`, `office.admin_added`); office writes also emit
  one `config_changed` event.

**Deviations from the design note** (recorded in the note's Deviations section)
- `DuplicateCode(OfficeError)` subclass makes the 409 explicit.
- Designation codes allow underscores (`CS_SEC`, `LEGAL_OFFICER` are seeded); office codes do not.
- "Not the actor's own office" applies to the office being changed, not to the parent of a create, so a
  department admin can create `EDU-DSE` under `EDU` but cannot edit or deactivate `EDU`.
- Inactive offices on `GET /admin/offices/{code}` give 404 unless the caller holds `offices.manage`.
- `*.update` audit rows carry only the fields set; an empty update writes no row and no event.
- Deactivating an inactive office or reactivating an active one is a 400, not a silent no-op; deactivating the
  root is 400, the caller's own office 403.
- The CLI has no tests of its own (wraps the tested service); `aslms offices list` has `--root` and
  `--all/--active-only`; `create` has no `--valid-from`.
- `offices.manage` is in no type's default matrix; tests grant it with a per-user override.

**Left for later**
- Counsel codes, keywords, name patterns, watchlist (`recommend-and-claim`); OTP and self-set passwords
  (`otp-and-profile`); the portal screens (`portal-shell`); true office moves (an audited two-step feature, only
  if the Secretariat needs it); `short_name` / `sort_order` on offices if a screen needs them.
- 2026-10-04 — recommend-and-claim: approved by the owner after review (editable scoring settings, claimed cases never return to the pool, take over within the department; docs/design/recommend-and-claim.md)

## Recommend and claim (2026-10-04)
Built on `feature/recommend-and-claim` from `docs/design/recommend-and-claim.md` (approved by the owner on
2026-10-04 after review). Backlog row 2.

**What was built**
- Migration **0004_ownership_rules**: `scoring_settings` (versioned master: the five kind weights and the two
  band thresholds, one `is_current` row, never updated in place or deleted); rule `weight` columns nullable
  (NULL = the kind's setting); `case_ownership.allotted_at`, `allotted_by_user_id`, `release_reason`;
  `ownership_transfers.decision_note`, `stay_as_watcher`; the partial unique indexes (one active primary per
  case, one active row per (case, office), one active recommendation per (case, office), one open transfer per
  case, one current settings row) and the CHECKs (`weights`, `thresholds`, `current`, `release_watcher`,
  `score_range`, the rule weights). `schema.md` Group 5 rewritten as built.
- `services/scoring_settings.py` (defaults, `current`, `update` with `expected_version`, `history`,
  `seed_default` — version 1 "Plan §4.2 defaults" by `aslms seed`); `services/matching.py` (the engine: noisy-OR
  over the strongest hit per signal kind, `counsel_code` / `keyword` / `name_pattern` / `linked_case` /
  `watchlist`, department roll-up with `suggested_unit`, inline scoring from `apply_entries` and `apply_dossier`
  in a savepoint with failures to `source_failures`, `rescore_all` in batches with a `job_runs` row,
  `rescore_if_dirty`, `unmapped_codes`); `services/matching_rules.py` (counsel codes, keywords, name patterns,
  watchlist: create / update / deactivate / reactivate in the caller's subtree, weights only with
  `admin.scoring`, audit + `config_changed`); `services/ownership.py` (claim, dismiss, suggest, allot, take
  over, stop watching, transfer request / accept / decline / withdraw, each under the case row lock with audit,
  event and custody); `services/custody.py::move_custody` (minimal: `claimed`, `allotted`, `taken_over`,
  `transferred`); `services/visibility.py` (`department_of`, `claimed_conditions`, `owned_case_filter`);
  `services/inbox.py` (Recommended, Claimed Active / Disposed, the pool, Transfers, counts);
  `services/cases.py::resolve_case_ref` (id, `ref_no` in slash or dash form, CNR).
- API: `api/routers/matching.py` (`/admin/scoring-settings` GET / PUT / history, `/admin/counsel-codes` with
  `/unmapped`, `/admin/keywords`, `/admin/name-patterns`, `/admin/watchlist`, `/admin/matching/cases/{ref}/scores`);
  `api/routers/inbox.py` (`/inbox/recommended`, `/claimed`, `/pool`, `/transfers`, `/counts`);
  `api/routers/ownership.py` (`GET /cases/{ref}/ownership`, `POST /cases/{ref}/claim | dismiss | suggest | allot
  | take-over | stop-watching | transfers`, `POST /transfers/{trf}/accept | decline | withdraw`). No release
  endpoint for a primary owner.
- Functions `admin.scoring` (no type by default) and `cases.take_over` (dept head, dept admin, dept officer,
  directorate user); `cases.release` relabelled "Stop watching"; event type `case_taken_over` (tracking card);
  `seed_ref_tables` now refreshes permission labels and descriptions.
- Jobs: Celery task `aslms.rescore_if_dirty`, beat `rescore-dirty` every 15 minutes (the `scheduler` service);
  a settings save dispatches it at once. CLI `aslms rescore [--all | --case REF]`, `aslms codes unmapped`.
- Tests: `tests/unit/test_matching_rules.py`; `tests/db/test_scoring_settings.py`, `test_matching.py`,
  `test_matching_rules_admin.py`, `test_ownership.py`, `test_api_inbox.py` (`tests/db/world.py` holds the shared
  office and user world). `pytest -q`: 215 passed.

**Decisions (reasons in the design note)**
- Scores and recommendations are per Department-tier office; a rule on a directorate or unit counts for its
  department and the most specific office is kept as `suggested_unit`. Generic State codes score nothing.
- Score = 1 − Π(1 − w_kind) over the strongest hit per kind, rounded to 3 decimals; bands `high` ≥
  `threshold_strong`, `medium` ≥ `threshold_possible`. Defaults 0.950 / 0.800 / 0.750 / 0.700 / 0.400 and 0.850 /
  0.500 — **defaults the super admin edits** (`scoring_settings`, function `admin.scoring`); every score row names
  the settings version in `engine_version` (`1.<version>`).
- The engine never re-opens a department's dismissal or claim; a human suggestion may. Engine rows carry the
  `matching` system actor and write no audit rows (events and scores are their record).
- **No return to the pool** (owner review 2026-10-04): once a department has claimed a case it stays with the
  last primary owner — also after disposal — and leaves only by an accepted transfer. The pool is "cases that
  have never had a primary owner". A watcher may stop watching (`cases.release`, relabelled). This
  **supersedes** the 26 Sep sentence "release → the next primary owner" in "Custody is derived"; the custody
  reasons `released` and `returned_to_pool` do not exist.
- **Take over within the same department** (`cases.take_over`): a colleague takes a case allotted to an
  officer, no approval; the unit follows the taker; custody moves with the taker's user when the row is primary;
  event `case_taken_over` names both users for `alerts-notifications`.
- Claimed cases split Active (`pending` / `unknown`) and Disposed by the NAPIX-maintained `cases.status`; no
  second flag.
- Custody follows primary ownership only (minimal, so alerts can find a holder; `custody-workflow` adds
  requests and hand-overs on the same function).
- Rule edits take effect at the next rescore (within 15 minutes); the API says so (`applies_within_minutes`).

**Deviations from the plan, flagged for the owner**
- Plan §4.2 / CLAUDE.md state the thresholds as fixed numbers; they are now defaults the super admin can change
  (the owner edited CLAUDE.md on 2026-10-04 to say so).
- Department discovery through NAPIX Search by Party Name stays deferred (backlog row 19); it never creates a
  department.
- The developer's smaller deviations (default `?office=` for State-wide readers, the `state_party` filter in
  SQL, response fields beyond the design's table, the dispatch reported honestly) are in the design note's
  Deviations section.

**Left for later**
- The case detail and full visibility rule (`cases-api`), alerts on `recommendation_made` / `case_taken_over`
  and the other ownership events (`alerts-notifications`), requests and hand-overs (`custody-workflow`), the
  portal screens including the scoring-settings screen (`portal-cases`), department discovery (row 19).
- Verification against the loaded January 2025 days (design "Verification" steps 4–13) is run by the
  integrator with Compose up; the unmapped-codes top five goes into the cycle report.
- 2026-10-04 — cases-api: approved by the owner as written (docs/design/cases-api.md)
- 2026-10-06 — documents-uploads: approved by the owner as written (docs/design/documents-uploads.md)

## Documents and uploads (2026-10-06)

Design: `docs/design/documents-uploads.md` (approved by the owner 2026-10-06). Branch `feature/documents-uploads`.

**What was built**
- Migration 0006 on `documents` (no new table): `archive_reason`, `page_count`, index on `sha256` (the old unique
  constraint on `sha256` is dropped; one stored file may back several rows), partial unique indexes
  `ix_documents_system_sha` and `ix_documents_upload_dedupe`, and four CHECKs (`ck_documents_internal_not_sent`,
  `ck_documents_user_file`, `ck_documents_upload_case`, `ck_documents_archive_reason`). Seed: doc-group codes and the
  `counter_affidavit` label. No new function.
- Services: `filetypes` (type by content), `scanner` (clamd), `storage` (content-addressed), `documents` (upload,
  listing, detail, file, search, visibility change, archive), `text_extract`, and the document visibility rule in
  `visibility.py`. The case detail Documents tab and `counts.documents` use it.
- Endpoints: `GET /cases/{ref}/documents`, `POST /cases/{ref}/documents`, `GET /cases/{ref}/orders/{order_id}/file`,
  `GET /documents/types`, `GET /documents/search`, `GET /documents/{doc}`, `GET /documents/{doc}/file`,
  `PATCH /documents/{doc}`, `POST /documents/{doc}/archive`.
- Jobs: `aslms.extract_pending_text` (beat every 5 minutes, writes a `job_runs` row) and
  `aslms.extract_document_text` (dispatched after an upload). CLI: `aslms documents extract`, `aslms documents scan-check`.
- Compose: `clamav` service (`clamav/clamav:stable`, signatures in volume `clamdb_v3`); `api` and `worker` get the
  clamd host and the store volume. Settings in `.env.example`: `UPLOAD_MAX_BYTES`, `CLAMAV_HOST`, `CLAMAV_PORT`,
  `CLAMAV_TIMEOUT_SECONDS`, `TEXT_EXTRACT_BATCH`.

**Decisions (reasons in the design note)**
- Allowed types are decided by the file's bytes: PDF, DOCX, DOC (no macro-enabled), JPEG, PNG. Limit 20 MB
  (`UPLOAD_MAX_BYTES`), the architect's number; the plan gives none.
- Every upload is scanned by clamd before it is stored; there is no off switch. With the scanner unreachable the
  upload answers 503. Infected and disallowed files write a `document.upload_rejected` audit row.
- Uploading needs the upload function and a working relation to the case, not merely sight of it. Type, date,
  description and visibility are required (no default visibility). The same file twice to one case by one office
  is refused (409).
- Visibility: court records and `counsel_shared` to everyone on the case; `case_scope` to everyone but standing
  counsel; `private_to_office` to the office, its department head and admin, and the uploader; State-wide readers
  see all.
- SourceTrace: internal documents are never sent (CHECK in the database); a court filing kept `private_to_office`
  is not queued until widened.
- Text is extracted in the background from PDF and Word only; no OCR, so scanned PDFs, images and `.doc` files get
  `text_status = none`. The content search respects visibility.
- No delete. After upload only visibility (audited) and archiving with a reason change; no unarchive. Downloads of
  uploaded documents are audited.

**Deviations (the developer's ten are numbered in the design note's Deviations section)**
- The 413 check is an HTTP middleware (`upload_size_guard`) because FastAPI parses the multipart form before any
  endpoint code runs.
- `{doc}` and `{ref}` in a path use the dash form of a `ref_no`, as in the cases API.
- The content search skips archived documents; the Documents tab lists uploads and order PDFs, not note
  attachments (`custody-workflow` owns those).
- The seed sets the `counter_affidavit` label on insert only.
- Migration 0006 was written as a new file after the autogenerated scaffold was removed (the repository guard
  treats every file in the versions directory as applied).

**Points the owner was asked to check at approval**: the 20 MB limit; standing counsel not seeing `case_scope`
documents; no OCR; ClamAV required to test uploads locally.

**Left for later**
- OCR (backlog row 23); reverse-proxy body limit and an EICAR test through Compose (row 24).
- Note attachments and their per-note visibility (`custody-workflow`); the SourceTrace ingestion of court records
  and filings (`sourcetrace-connector`); alerts on a new document (`alerts-notifications`); the upload screens
  (`portal-workflow`).
- 2026-10-06 — alerts-notifications: approved by the owner as written (docs/design/alerts-notifications.md)

## Alerts and notifications (2026-10-06)
Branch `feature/alerts-notifications`; design `docs/design/alerts-notifications.md` (approved 2026-10-06); migration 0007.

**Built**
- Tables (migration 0007): `alerts` gains `office_id`, `data` jsonb, `closed_at`, `closed_by_user_id`, two CHECKs and indexes; `notifications` gains `severity`, `attempts`, `next_attempt_at` and the outbox index; `digests` gains its sending state. `ref_alert_kind` gains `ownership` and `new_document` (seed only). Details in `docs/schema/schema.md` group 7.
- Services: `alert_rules` (severities, keys, preference rules, rendering), `alerts` (raise with dedupe and ALR allocation, event scan, date sweep, acknowledge / done, readers filtered by visibility in SQL), `recipients`, `notifications` (in-app and e-mail rows, sender with retries, daily digest, preferences), `mailer` (Mailtrap API, SMTP, console, recording; chosen by `MAIL_BACKEND`), `calendar`.
- API: `/alerts` (list, counts, by reference, acknowledge, done, read), `/cases/{ref}/alerts`, `/calendar`, `/me/notification-preferences`. `alert_raised` joins the case timeline.
- Jobs: `aslms.alerts_scan_events` (5 min), `aslms.alerts_sweep_dates` (hourly at :10), `aslms.notifications_send` (2 min), `aslms.digests_build` (08:00 IST). CLI `aslms alerts run / send / digest / status / test-mail`. Settings in `.env.example` (mail, `ALERT_*`, `NOTIFY_*`, `REQUEST_DUE_SOON_DAYS`, `PORTAL_BASE_URL`).

**Decisions (reasons in the design note)**
- Two generators (event scan over a time window, date sweep), idempotent through `dedupe_key`; history is never back-filled (first scan starts at now minus the overlap; only recent orders and dispositions alert).
- Case alerts only for cases with an active owner or watcher; recipients are custody holder, owner and watchers, always filtered by visibility. Recommendation alerts only for strong matches of pending cases.
- Default delivery: in-app always; critical alerts e-mailed at once, the rest in the 08:00 IST digest; SMS refused until a gateway exists.
- Mail content carries title, case number, CNR, court, date and a link; never note text or internal document names.
- `/calendar` added here as plan section 5.5 requires.

**Deviations (thirteen, numbered in the design note's Deviations section)**
- Ownership notices (`case_taken_over`, `transfer_requested`, `transfer_decided`) skip the case-visibility filter, since their recipients cannot see the case (1).
- The in-app list shows one row per alert (2); compliance severity window 7 days, critical band 2 days (4); `get_mailer` requires `SMTP_FROM` (8).
- Migration 0007 written as a new file after the scaffold was removed (9); the 0006 cycle test now compares with the script head (10).
- Review fixes: a `new_document` alert is read only with its document (12); an alert is read and acted on only by the office addressed (13).

**Scope notes for the owner**: next dates read from order text are the separate row 26 (`next-date-extraction`), so the plan's Phase 1 "alerts for orders with specific dates" completes there; compliance alerts come only from scrutiny `compliance_by_date`.

**Left for later**
- Row 26 (next dates from orders); row 27 (SMS, order-text compliance directions, live Mailtrap check); the alert screens and calendar in the portal (`portal-workflow`).
- 2026-10-07 — custody-workflow: approved by the owner as written (docs/design/custody-workflow.md)

## Custody and file movement — owner's rules (7 Oct 2026, product owner)
The custody-workflow cycle stopped on a blocking review finding (custody stranded with a receiving department
after nested requests). Reviewing it, the owner set these rules, which replace the request-based design:
- **Custody is accountability.** When something is pending with an officer, the case shows as held by that
  officer and their office, so pending work is measured against the right person.
- **Sending the file replaces requests.** The holder sends the case (its control) to any registered user in
  any department: pick the department, then the officer. The send carries a remark, a pending action and an
  optional due date. No separate request object.
- **Chain, as in eOffice.** Whoever holds the case can send it on to anyone; every movement is recorded in the
  custody history.
- **Recall.** The owning department can call the case back at any time, with a remark, from wherever it is.
  Ownership never moves with custody; only claim and transfer change ownership.
- **No deletion once claimed.** Nothing in a claimed case is deleted. The only exception is draft notes: a
  note the current holder writes stays a draft, editable and deletable, while that holder still has the case;
  when the case is sent on (or recalled), the drafts become permanent, append-only notes of the case.
- **One person, several departments.** A user can hold designations in more than one department: one login
  with several memberships (department, designation and user type each). They see and act on the cases of all
  their departments with the rights of their type in each. When sending a file, the sender picks the person
  and the membership.
- **Recall is a grantable function** (owner, 7 Oct 2026): `custody.recall`, on for department admins by default;
  a department admin grants it to the officers of their department they choose, and the super admin can grant
  it to anybody. It recalls only cases owned by the department of the membership that holds it.
- **Tracking pending and overdue files is a grantable function** (owner, 7 Oct 2026): `custody.track`, on for the
  department head (seniormost officer) and the department admin by default; the department admin grants it to
  any officer of the department, the super admin to anybody. Holders receive the department's due-soon and
  overdue alerts and see the department's pending and overdue files and counts, wherever the files are held.
- 2026-10-07 — user-memberships: approved by the owner after review (single super admin and department admin, one head with super-admin approval of changes, admin tickets, government order, per-item exit; docs/design/user-memberships.md)
- 2026-10-07 — custody-workflow (revised): approved by the owner after review (send the file to any officer, chain, recall and tracking as granted functions, draft notes; docs/design/custody-workflow.md)

## User memberships: one login, several offices (2026-10-07)
Design: `docs/design/user-memberships.md` (approved by the owner on 2026-10-07; backlog row 28). Migration 0008.

**Built**
- Tables: `user_memberships` (office, derived `department_id`, designation, user type, `is_primary`, validity),
  `admin_tickets` (`TKT` numbers), `admin_ticket_documents` and `membership_documents` (append-only), `ref_ticket_kind`;
  `user_permissions` gains `membership_id` (overrides are per membership); `documents.kind` gains `admin`.
  Partial unique indexes: one active membership per person per department, one super admin, one department admin and
  one head per department. Details are in `docs/schema/schema.md`.
- Services: `services/memberships.py` (add, update, end with the per-item exit, reactivate, primary, department admin
  swap, super admin replacement), `services/tickets.py` (generic admin ticket queue, `head_change` the first kind,
  government-order documents), and authority, scope, visibility, recipients, alerts, ownership, inbox, documents and
  offices reworked to take the acting membership (`access.Member`).
- API: membership endpoints under `/admin/users/{id}/memberships`, `/admin/tickets` (head change, list, counts, detail,
  approve, reject, withdraw, documents), `PUT /admin/offices/{code}/admin`, `/me` with memberships, `/inbox/counts` per
  department. CLI: `aslms users replace-super-admin`, `aslms users memberships list|add|end`.

**Decisions**
- A membership is the unit of authority; functions, scope, visibility bases and the actor snapshot come from it. Visibility
  is the union of the memberships' bases; documents are evaluated per whole membership (review fix, so a counsel
  rule is not lifted by another membership).
- At most one active membership per person per department, so "the membership in department D" is unambiguous.
- `users.office_id`, `role`, `designation`, `designation_id` stay as a mirror of the primary membership, written only by
  the membership service and never read for authorisation (guarded by a test).
- Exactly one super admin, replaced only from the CLI; exactly one department admin per department, changed only by
  the super admin as a swap; the super admin is never subject to approval or delegation limits.
- Head changes: a department admin requests, the super admin approves through a ticket; the super admin changes it
  directly; a department admin can never leave a department headless; a department is created or reactivated with a head.
- Exit step: ending a membership reassigns each allotment and held file to an officer of the department, after a preview.
- Disabled logins are the super admin's: adding or reactivating a membership on one gives 409 `login_inactive` otherwise.

**Deviations** (the design note's Deviations section lists all 13): admin paths sit under the existing `/admin/users`
prefix with one added read endpoint; the exit leg's remark is kept in the `custody_moved` event and audit row because
`custody_history` has no remark column before migration 0009; migration 0008 gives disabled logins an ended membership;
a department admin may preview the head's exit; `/inbox/counts` changes shape (no portal consumes it yet).

**Left for later**
- The dev database is still at 0007 (the historical load runs against it); the integrator upgrades it.
- Portal screens for memberships, the ticket panel and the exit dialog (`portal-shell`).
- Custody-workflow builds on this item (sending a file to a membership). Follow-up rows 29 (drop the mirror columns)
  and 30 (further ticket kinds) added to the backlog.

## Custody workflow: sending the file, recall, stages, notes trail (2026-10-07)
Design `docs/design/custody-workflow.md` (revised and approved 7 Oct 2026 under the owner's rules above); branch
`feature/custody-workflow`; tests and review passed.

**Built**
- Migration 0009 (`0009_workflow.py`): `custody` and `custody_history` gain `holder_membership_id` (and
  `holder_designation` on the history); history reasons `sent`, `recalled` (and `reassigned_on_exit`) with
  `ck_custody_history_reason`; `case_notes` gains `drafted_at`; new `case_note_drafts` and
  `case_note_draft_documents` (the only deletable tables); `case_note_attachments` made append-only; `case_stages`
  index. Dropped after an emptiness check: `requests`, `request_messages`, `ref_request_kind`, the `request_status`
  enum and the `request_id` columns. Seed: note kinds `opinion` and `hand_over`, alert kind `workflow`; `request_due`,
  `request_sent`, `request_answered`, `correction` and record type `REQ` retired (rows kept, inactive).
- Services: `custody.py` (`move_custody`, send, recall, held / sent / summary), `notes.py` (permanent notes, drafts,
  finalisation on send or recall, corrections), `stages.py`, `attachments.py`, `workflow_common.py`,
  `workflow_codes.py`; changes to `visibility.py` (custody basis follows the holder membership, `request` basis
  removed), `recipients.py`, `alerts.py`, `case_detail.py`, `documents.py`, `memberships.py` (exit leg remark,
  drafts count), `ownership.py`.
- API (`api/routers/workflow.py`): `GET /workflow/codes`; `GET /cases/{ref}/custody`; `GET /custody/recipients`,
  `/summary`, `/held`, `/sent`; `POST /cases/{ref}/custody/send` and `/recall`; `GET|POST /cases/{ref}/stages`;
  `GET|POST /cases/{ref}/notes`; `GET /cases/{ref}/notes/drafts`; `PATCH|DELETE /notes/drafts/{draft}`;
  `GET /notes/{note}`. Settings `ATTACHMENTS_MAX_FILES` (5), `NOTE_MAX_CHARS` (20000), `NOTE_DRAFTS_MAX` (20) in
  `.env.example`. No new job; the alert scan and date sweep handle workflow events and due dates.

**Decisions** (the owner's rules of 7 Oct 2026, implemented as written)
- Custody is accountability: the holder is a membership (officer and office); sending replaces requests; the chain
  is open to any holder; `custody.recall` and `custody.track` are grantable functions; ownership never moves with
  custody.
- Draft notes are the one exception to no-deletion; they become permanent, append-only notes (new `ref_no`,
  `drafted_at` kept) when the case is sent on or recalled. DB_STANDARD section 6 / 9 is deviated from for the two
  draft tables only, recorded in `schema.md`.
- Notes and their attachments are internal documents and are never sent to SourceTrace.
- Request tables are dropped, not left unused.

**Deviations** (design note, Deviations section, 9 items)
- 0009 is not applied to the dev database: the Compose worker and scheduler still run `main`'s code (the request
  sweep) during the historical load. It runs on the test database every run, including a down-and-up test.
- 0009 back-fills holder membership and designation on earlier legs; the downgrade stops on drafts, draft-born
  notes and `sent` / `recalled` legs.
- Tracking holders receive both due-soon (`high`) and overdue (`critical`) alerts (decision 24a over 23c).
- Visibility is checked before function checks, so an unseen case gives 404, not 403.
- A correction keeps the original note's office for visibility; `GET /custody/sent` shows the caller's own remark;
  the held list aliases `custody` in its visibility `EXISTS`.

**Left for later**
- Upgrade the dev database to 0009 when the merged images are rebuilt (integrator).
- Portal screens (row 13); request-related reports are replaced by custody and tracking counts.
- No follow-up rows added; the review left none recorded.

## Current Status batch size fixed (7 Oct 2026)
- The daily status refresh failed on 7 Oct: all four batches of 500 CNRs were refused by the gateway with
  HTTP 405 "page not found". Current Status carries the CNRs encrypted in the query string, and a live probe
  (a handful of calls, switch set for that run) showed the limit: 300 CNRs accepted, 350 refused with HTTP 414
  "URI too long", 400–500 refused with 405. The spec's "max 500" does not hold through the gateway.
- `NAPIX_STATUS_BATCH` (default 250, at most 300) now sets the batch size in `services/tracking.py`;
  `NapixHighCourt.current_status` refuses more than 300. Notes §7 updated. Tests: `tests/unit/test_status_batch_size.py`.
- Made directly as a small fix (one setting, one service constant, one guard) rather than a team cycle, because
  the daily refresh was not running.
- 2026-10-07 — otp-and-profile: approved by the owner (code at every sign-in, mobile mandatory; docs/design/otp-and-profile.md)

## OTP sign-in, devices, password reset and first-sign-in confirmation (2026-10-07)
Design `docs/design/otp-and-profile.md` (approved 7 Oct 2026 with the owner's two answers); branch
`feature/otp-and-profile`; tests and review passed (review of 8 Oct 2026 produced deviations 17 and 18).

**Built**
- Migration 0010 (`0010_otp_profile.py`): `users` gains `password_changed_at`, `must_change_password` (back-filled
  from `must_confirm_profile`) and `profile_confirmed_at`; new table `user_devices` (never deleted); `refresh_tokens`
  gains `device_id`; index `ix_otp_codes_user_purpose_created`. No `ref_*` code, enum value or `Permission` added.
  The downgrade refuses while a `user_devices` row exists. `schema.md` updated before the migration.
- Services: `otp.py` (issue, verify, resend wait, `mask_email`, `lock_user`), `auth.py` (start and complete login,
  resend, password reset request and confirm, own password change, refresh with reuse detection, devices, lock check,
  `sign_out_everywhere`), `passwords.py` (policy, hash and verify moved here), `profile.py` (get, confirm, update);
  changes to `users.py` (e-mail change, `set_password` with `by_self`, `end_sessions`, `end_codes`), `notifications.py`
  (`set_preferences` checks before it writes), `mailer.py`, `api/deps.py` (token-age check, first-sign-in gate,
  `current_user_pending`, `get_mailer`), `api/security.py`.
- API: `POST /auth/login` (now step one, answers `step: "otp"`), `/auth/otp/verify`, `/auth/otp/resend`,
  `/auth/password-reset/request` and `/confirm`, `/auth/refresh`, `/auth/logout`; `POST /me/password`, `GET`, `PATCH`
  `/me/profile`, `POST /me/profile/confirm`, `GET /me/devices`, `POST /me/devices/{id}/revoke`; `PATCH
  /admin/users/{id}` accepts `email`; `POST /admin/users/{id}/password` now forces a change.
- CLI: `aslms users set-password` forces a change and applies the password policy; new `aslms users sign-out --email`.
- Settings in `.env.example`: `OTP_TTL_MINUTES` (10), `OTP_MAX_ATTEMPTS` (5), `OTP_RESEND_SECONDS` (120),
  `OTP_MAX_PER_HOUR` (10), `LOGIN_MAX_FAILURES` (10), `LOGIN_LOCK_MINUTES` (15).
- Tests: `tests/unit/test_auth_rules.py`; `tests/db/` `test_auth_otp.py`, `test_auth_resend_and_races.py`,
  `test_profile.py`, `test_api_auth.py`, `test_api_auth_gaps.py`, `test_api_auth_negative.py`,
  `test_migration_0010.py`; the helper `tests/db/auth_support.py::sign_in` replaces the direct logins of every
  existing API test.

**Decisions**
- Sign-in is password, then a 6-digit code e-mailed to the login, at every sign-in. Owner's answer: a known device
  never skips the code, so no device-trust setting or mechanism exists. Devices are still recorded: the first
  verified sign-in from a client issues a device token, a new device triggers a notice e-mail, and the user lists
  and signs out their devices.
- Codes are HMAC-SHA256 keyed with `ASLMS_JWT_SECRET`, valid 10 minutes, 5 tries, one live code per login and
  purpose; a new code at most every 120 seconds and 10 an hour; never logged, audited or returned.
- Lock: 10 failed passwords or codes in 15 minutes refuse sign-in and reset for that login (429 `locked`), counted
  from audit rows, no counter column, and not a permanent lock.
- Failures are returned, not raised, so the attempt count, spent code, audit row and revocations commit with the 401.
- Password reset answers 202 alike for any e-mail and sends mail only for a live account outside the wait; it ends
  every session and does not sign in.
- Password policy for every path: 10+ characters, a letter and a digit, not the current password.
- Credential changes (reset, own change, administrator reset, e-mail change) set `password_changed_at`, revoke
  refresh tokens and spend live codes; an older access token is refused at once. A rotated refresh token presented
  again ends every session of the login.
- First sign-in is enforced on the server: while `must_change_password` or `must_confirm_profile` is set only the
  first-sign-in endpoints answer (403 `password_change_required` / `profile_confirmation_required`); password first.
- Profile confirmation shows memberships read only and saves name, mobile and notification preferences. The mobile
  number is mandatory, Indian 10-digit (`^[6-9][0-9]{9}$`), stored without the country code and not verified.
- Administrators can correct a login's e-mail (a wrong address would lock the person out for good), under the
  existing `users.edit` scope; the old address gets a notice. Administrator and CLI password sets force a change; the
  seeded super admin's `.env` password is a bootstrap secret and also forces one.
- Mail is required to sign in: failure answers 502 `mail_failed`; the console backend with `APP_ENV=prod` answers 503
  `mail_not_configured`; there is no bypass. Development uses the Mailtrap sandbox URL in `.env`.

**Deviations** (design note, Deviations section, 18 items; none changes a business rule)
- No device trust (owner's review): `new_device` stays in the enum but nothing issues it; `/me/devices` has no
  `trusted_until`; `current` follows an optional `X-Device-Token` header.
- Reset confirm answers every failed code alike (401 `otp_invalid`, no `attempts_left`), and a reset request stays a
  neutral 202 when the login is locked or the mail fails, so an account is never disclosed.
- A failed send leaves no `otp_codes` row, so an outage costs no wait and no hourly cap.
- Sign-in resend is narrower (deviation 17): only the newest, unexpired challenge, live or spent by wrong codes, and
  created after the login's `password_changed_at`. Sign-in steps of one login are serialised by `SELECT ... FOR
  UPDATE` on the `users` row, then the `otp_codes` row (deviation 18).
- A logged-out refresh token is not reuse (logout sets `expires_at` to the revocation instant, no schema change); a
  reset revokes tokens but not devices; an out-of-scope e-mail change answers 404 like the rest of `PATCH
  /admin/users/{id}`; `UserError` moved to `passwords.py`; the seeded super admin's `.env` password must pass the policy.
- A refused profile confirmation or update never half-applies; logout revokes only the caller's own token.

**Left for later**
- Portal sign-in screens and httpOnly cookie handling (row 11); SMS channel (row 27); per-IP throttling at the reverse
  proxy (row 16).
- New rows: 33 `auth-retention` (pruning of old `otp_codes` and `refresh_tokens`), 34 `mobile-verification` (SMS
  verification of the mobile number).
- Design Verification steps 2 to 7 (Compose with the Mailtrap sandbox in `.env`) are the live check; upgrade the dev
  database to 0010 when the merged images are rebuilt (integrator).

- 2026-10-08 — sourcetrace-connector: approved by the owner (court orders and court filings only, court-public metadata, filings on provisional cases wait for the CNR, append-only ingestion records, admin.sourcetrace; docs/design/sourcetrace-connector.md)

## SourceTrace connector: interface, fake, ingestion of court records and filings (2026-10-08)
Design `docs/design/sourcetrace-connector.md` (approved by the owner on 8 Oct 2026); branch
`feature/sourcetrace-connector`; tests and review passed. Backlog row 8, status `review`.

**Built**
- Migration 0011 (`0011_sourcetrace.py`): `documents` gains `sourcetrace_attempts`, `sourcetrace_next_at`,
  `sourcetrace_ingested_at`, the CHECKs `ck_documents_sourcetrace_kind`, `ck_documents_private_not_sent` and
  `ck_documents_sourcetrace_ingested`, and the partial index `ix_documents_sourcetrace_due`;
  `sourcetrace_ingestions` gains `connector`, `error_family`, `duration_ms`, `response`, `metadata_sent` NOT NULL,
  the CHECK `ck_sourcetrace_ingestions_outcome`, the index `ix_sourcetrace_ingestions_document_created` and the
  append-only trigger (`aslms_app` loses UPDATE and DELETE). It back-fills archived `pending` / `failed`
  documents to `not_applicable` and stops if any ingestion row exists; its downgrade stops if any ingestion row
  exists or a document has attempts or an ingested time. `schema.md` updated.
- Connector package `backend/aslms/integration/sourcetrace/`: the `SourceTraceConnector` protocol (`name` and one
  async method, `ingest(item) -> IngestResult`), `IngestItem`, `IngestResult`, the errors
  `SourceTraceUnavailable` and `SourceTraceRejected`, `connector_state(settings)` and `get_connector(settings)`,
  and `FakeSourceTrace` for tests.
- Service `services/sourcetrace_ingest.py`: `build_metadata`, `assert_sendable`, `backoff`, `claim_due`,
  `ingest_one`, `ingest_pending`, `run`, `status`, `failed`, `retry`, `retry_all_failed`. Changes to
  `services/documents.py` (`lock_document`, `change_visibility`, `archive`, `document_out`).
- API: `GET /admin/sourcetrace/status`, `GET /admin/sourcetrace/failed`, `POST
  /admin/sourcetrace/documents/{doc}/retry` (all behind the new function `admin.sourcetrace`); `PATCH
  /documents/{doc}` and `POST /documents/{doc}/archive` may answer 409 `document_busy`; `GET /documents/{doc}` adds
  `sourcetrace_ingested_at`.
- CLI `aslms sourcetrace`: `status`, `run [--batch N] [--document ID]`, `retry --document ID | --all-failed`,
  `check`.
- Job: Celery task `aslms.sourcetrace_ingest`, beat entry `sourcetrace-ingest` every 5 minutes in the `scheduler`
  service.
- Permission `admin.sourcetrace` (seed only; 50 rows, 48 active), enabled by default for `central_operator`.
- Settings in `.env.example`: `SOURCETRACE_BATCH` (20), `SOURCETRACE_RUN_SECONDS` (240),
  `SOURCETRACE_TIMEOUT_SECONDS` (60), `SOURCETRACE_MAX_ATTEMPTS` (5), next to the existing `SOURCETRACE_ENABLED`,
  `SOURCETRACE_BASE_URL` and `SOURCETRACE_API_KEY`.
- Tests: `tests/unit/test_sourcetrace.py` (7); `tests/db/test_sourcetrace.py` (23), `test_sourcetrace_gaps.py`
  (8: guard under the lock, idempotence, retry paths, CLI, 401 paths, no uploader text in ingestion rows) and
  `test_api_sourcetrace.py` (5); the helper `tests/db/st_support.py`; existing tests adjusted for 50 functions.

**Decisions**
- There is no real connector. `get_connector` returns `None` and `connector_state` answers `disabled`, or
  `not_implemented` when `SOURCETRACE_ENABLED` is true; it never returns the fake, because a fake reference in the
  real database would be a fabricated identifier. With either state the job sends nothing and writes no `job_runs`
  row; documents keep accumulating as `pending`, to be sent in batches once the connector exists.
- The protocol is ingestion only. The query side (`ask`, next-date reading) is added by the items that use it,
  when their shapes are known.
- Only court orders and court filings are sent, decided by the document's own nature and checked three times: the
  claim query, `assert_sendable` again under the row lock just before the bytes leave (a refusal sends nothing and
  writes a `source_failures` row of kind `sourcetrace_guard`), and the database CHECKs. A court filing that a
  note links to is still sent; the note, its text and its attachments never are.
- The metadata is fixed and court-public (document identity and type, date, CNR, case number, court, and for
  orders the order number, kind and judge, plus synthetic filename, mime, size and hash). The uploader's
  description and original filename, office, visibility and anything from notes, custody or ownership are never
  sent. It is built by one pure function and stored verbatim in `sourcetrace_ingestions.metadata_sent`.
- The `pending` status is the queue: one document per transaction, claimed with `FOR UPDATE ... SKIP LOCKED`,
  uploads before orders and then newest first. No `fetch_queue` kind, so SourceTrace work does not compete with the
  NAPIX quota.
- Retries back off 10, 20, 40 and 80 minutes and the fifth failure marks the document `failed`; a refusal or a
  malformed reference fails at once; a missing file fails at once (family `store`). The run stops after the first
  unavailable or timeout. Every `failed` writes a `source_failures` row and a later success resolves it.
- A visibility change or an archive on a document being sent answers 409 `document_busy` (the row is locked
  `NOWAIT`), so a change cannot overwrite `ingested`. Archiving stops sending of `pending` and `failed` documents;
  an `ingested` one keeps its reference (no known removal endpoint). Widening a private filing re-queues it with no
  attempts.
- Batches: every 5 minutes, at most 20 documents, no new claim after 240 seconds (ceiling 5,760 a day, adjustable).
  The 5-minute beat is the "job placed in the background queue".
- System sends write no `audit_log` row; the append-only ingestion record is the trail. Human actions are audited:
  `sourcetrace.retry_requested` and `sourcetrace.retry_all_failed`.
- A new function `admin.sourcetrace` rather than reusing `admin.napix_refetch`; the failure list applies the document
  visibility rule.

**Deviations from the plan and the design** (the first three were flagged and approved with the design)
- Plan §3.2 names four case details; the metadata adds document identity, type, order number and kind so citations
  can open the document and the assistant can keep related-case retrieval to orders and judgments.
- A court filing on a provisional case waits for the CNR, where the plan sends it "when uploaded" (SourceTrace keys
  material by CNR and a provisional case may be merged).
- Archiving stops sending; this takes over "archive stops SourceTrace queueing" from row 25.
- Built differently from the letter of the design (design note, Deviations section, 10 items): migration 0011 was
  written as a new file because the repository guard treats every file in the versions directory as applied;
  `build_metadata` takes the type label as an argument; `FakeSourceTrace` has an `error` outcome, an `on_ingest`
  hook and `timeout_sleep`; `claim_due` takes `exclude` and an explicit document id skips its back-off; a guard
  refusal counts as `guarded` and makes the run `partial`; `retry` of a `pending` document is accepted only while it
  waits on back-off; widening an archived private filing does not queue it; `aslms sourcetrace check` does not
  count filings waiting for a CNR or archived ingested documents; `connector` is `null` in the status until a real
  connector is ready; the settings have bounds.

**Left for later**
- New rows 36 `sourcetrace-http-connector` (blocked on the SourceTrace API documentation) and 37
  `sourcetrace-next-dates`. Removal of archived ingested documents from SourceTrace, if an endpoint exists.
- Row 14 (`assistant`) must pass only references of documents the asking user may see, never archived ones, and
  keep related-case retrieval to court orders; row 25 loses the archive item.
- Verification step 7 cannot be done until the real connector exists; the fake-backed tests are the proof. Before
  deployment: `alembic upgrade head` on the dev database (0011), `aslms seed`, then `aslms sourcetrace status` and
  `check` (the integrator).

- 2026-10-08 — reports-dashboards: approved by the owner (dashboards by function and membership, live counts, four reports with Excel and PDF export, NJDG age bands, exports audited; docs/design/reports-dashboards.md)


## Dashboards and reports (2026-10-08)

Design: `docs/design/reports-dashboards.md` (approved by the owner on 2026-10-08). Backlog row 9, status `review`.

**What was built**
- `services/reporting_common.py` (today in IST, `ReportConfig`, `SET LOCAL statement_timeout`, Department-tier
  rows, current primary owner, NJDG age bands), `services/dashboard.py`, `services/reports.py`,
  `services/report_export.py` (XlsxWriter workbook, PyMuPDF A4 landscape PDF with repeated headers, page numbers
  and row caps), and `custody.summary_for` factored out of `custody.summary`.
- Endpoints: `GET /dashboard` (which blocks the caller has), `/dashboard/me`, `/dashboard/department`,
  `/dashboard/state`; `GET /reports` and the four reports `pending-cases`, `hearings-disposals`,
  `pending-actions`, `data-health` with `format=json|xlsx|pdf` (files streamed no-store, never stored in
  `documents`, each export audited as `report.exported`).
- CLI `aslms reports run` and `aslms reports dashboard`, acting as the super admin (exports audited).
- Settings `REPORT_MAX_RANGE_DAYS` (366), `REPORT_HEALTH_MAX_DAYS` (92), `REPORT_XLSX_MAX_ROWS` (5000),
  `REPORT_PDF_MAX_ROWS` (1000), `REPORT_STATEMENT_TIMEOUT_SECONDS` (30), `DASHBOARD_LIST_SIZE` (10), in
  `.env.example`; dependency `xlsxwriter`.
- Migration 0012: indexes `ix_cases_disposal_date` (partial) and `ix_case_hearings_business_date`; no table or
  column. The 0011 migration test now reads the head instead of a fixed revision.

**Decisions** (numbers follow the design note)
- 1, 3, 9, 10, 11: dashboards are composed by function and membership, not user type: personal block always,
  a department block per department where a membership holds `cases.claim`, `cases.allot`, `custody.track` or
  `reports.department`, the State block with `dashboard.state`. Blocks load through separate endpoints so one
  slow section does not delay the first screen; department sections are gated (recommendations by
  `cases.claim`, pending actions and custody by `custody.track` or `reports.department`).
- 2, 4: every figure is computed live in SQL from existing tables; no snapshot tables. Stock measures are "as of
  now", period measures come from dated rows; a case counts for its current primary owner.
- 5, 6: four reports cover the plan's §5.10 bullets; NJDG age bands (up to 1, 1-3, 3-5, 5-10, 10-20, 20-30, over
  30 years, plus age not known), a constant the owner may change.
- 7, 8: department scope needs `reports.department` in that department or `reports.state`; `data-health` is
  State only. Aggregates follow the function; every row that names a case is also filtered by the caller's case
  visibility, and the custody remark, notes and documents never appear.

**Deviations from the design** (design note, Deviations section, 16 items; the main ones)
- Claimed counts are primary ownership only, so they differ from `/inbox/counts` by watcher rows (item 1).
- The Excel file is built in memory, because `constant_memory` writes temporary files holding case data; the
  row cap bounds its size (item 5). The PDF exporter paginates tables itself, as PyMuPDF `Story` does not repeat
  headers (item 6).
- `custody.summary_for` is one query and `/custody/summary` gains `with_pending_action`, `pending_no_due_date`
  and `by_holder_office` (additive, item 12). `data-health` takes `from` and `to` together or not at all
  (item 11). `hearings-disposals` leaves merged duplicates out (item 8).

**Left for later**
- New row 39 `portal-reports` (reports screen, Excel and PDF buttons); the dashboard goes into row 11.
- If the owner asks: snapshot tables for past-date figures and trends, scheduled e-mailed reports,
  a `napix_call_log` retention job (bounds the data-health history). Row 10 reads the same tables for the live
  data-health screen; row 26 fills the dashboard's next dates from orders.
- Before deployment (integrator): `alembic upgrade head` on the dev database (0012).

- 2026-10-08 — audit-screens: approved by the owner (audit log read by the super admin and the Auditor type; reading not audited; health screen and re-fetch buttons that only enqueue; docs/design/audit-screens.md)

## Audit screens: audit search, data-health screen, NAPIX buttons (2026-10-08)

**Built** (design `docs/design/audit-screens.md`, approved by the owner on 2026-10-08)
- Migration 0013 `audit_indexes`: `ix_audit_log_created_at` and `ix_audit_log_actor_created`; no table or column.
- `services/audit_search.py` and `api/routers/audit.py`: `GET /audit` (filters by actor, subject login, case with
  merged duplicates, office subtree, action exact or prefix, entity, IST date range; newest first, keyset paging
  with `next_cursor`, `limit` 1-200), `GET /audit/{id}`, `GET /audit/actions`.
- `services/data_health.py` and `services/napix_admin.py`, router `api/routers/napix_admin.py`:
  `GET /admin/data-health` (live snapshot), `GET /admin/napix/health`, `/admin/napix/queue`, `/admin/napix/calls`,
  `GET /admin/failures`; buttons `POST /admin/napix/sync-masters`, `refetch/day`, `refetch/case`, `refetch/order`,
  `queue/{id}/retry`, `queue/retry-failed`; `POST /admin/napix/health/check` (one Overview call).
- `api/deps.napix_client` replaces the cases router's private factory; shared daily-cycle helpers in
  `reporting_common` (the period report is unchanged); `queue.get_state`; function labels refreshed by seed.
- CLI: `aslms audit search`, `aslms data-health`; `refetch-date` and `refetch-case` now go through the service and
  are audited. Setting `NAPIX_HEALTH_CHECK_MIN_SECONDS` (60) in `.env.example`.

**Decisions** (numbers follow the design note)
- 1, 4: one audit search with keyset paging (no total, no offsets); indexes serve the actor, time and case searches;
  searches run under the report statement timeout (503 `search_timeout`).
- 2: the log is read only by `audit.view` in a State-wide membership (super admin, or `cases.view_all`; the default
  Auditor has both), else 403 `audit_scope`. Owner's answer: the super admin and the Auditor type read the log; the
  super admin can switch access off for the type or a single user.
- 3: reading the log and the health screens writes nothing.
- 5, 6: the data-health snapshot is counts and operational references only; visible to `reports.state`,
  `admin.napix_refetch` or `admin.masters_sync`. Failure rows tied to documents follow the document rule (7).
- 8, 9: buttons only enqueue `fetch_queue` rows through `queue.enqueue` (priority 10 masters, 20 day, 30 case, order
  and retry); the API never fetches. Enqueuing is allowed while the switch is off.
- 10: the connectivity check is the only call, guarded (`napix_off` 409, `check_too_soon` and `napix_budget` 429),
  logged like every call; GET endpoints never call NAPIX.
- 11: every button writes an audit row (`napix.*`). 12: re-running Current Status batches early is not a button.

**Deviations** (design note, Deviations section, 9 items; the main ones)
- The check's call-log key is the API path `overview/overview`, not `overview` (item 1).
- Services take the caller and pick the acting membership holding the function; the CLI passes the super admin's
  membership (item 2). `aslms refetch-case` takes a case reference and refuses a case not in the database (item 3).
- Extra 400 codes `bad_actor`, `bad_period`, `bad_cursor`; stale document-kind failure refs are shown to the super
  admin only (items 4, 6). Migration 0013 keeps Alembic's generated docstring (item 7).
- `aslms data-health` needs no super admin; checked on the dev database (item 9).

**Left for later**
- Department-scoped audit view (a vigilance officer reading only the department's offices), and `audit.searched`
  rows recording who searched the log, if the owner or vigilance asks.
- Export of an audit search; a button re-running today's Current Status batches.
- Portal screens for audit and data health (rows 11 and 39); the `napix_call_log` retention job (row 39).
- Before deployment (integrator): `alembic upgrade head` on the dev database (0013); the live Overview check is run
  by the owner with `NAPIX_ENABLED` set for that run.


- 2026-10-10 — portal-shell: approved by the owner (Next.js portal with a backend-for-frontend, tokens in httpOnly cookies, sign-in screens, shell, dashboard and administration screens; npm commands added to the team allowlist; docs/design/portal-shell.md)

## Portal shell: sign-in, shell, dashboard and administration screens (2026-10-10)

Design note: `docs/design/portal-shell.md` (approved by the owner on 2026-10-10; backlog row 11, status `review`).
Branch `feature/portal-shell`. No table, column or migration; `docs/schema/schema.md` unchanged.

**What was built**
- `frontend/`: the Next.js 16 portal (App Router, TypeScript strict, React 19, TanStack Query, CSS Modules, fonts
  self-hosted from npm). A backend-for-frontend: session route handlers under `/api/session/*` (`login`, `verify`,
  `resend`, `reset/request`, `reset/confirm`, `password`, `logout`), a relay `/api/backend/[...path]`, and
  `/api/health`. `src/proxy.ts` gates pages and sets the security headers.
- Screens: sign-in, code, forgot-password and reset; the forced password change and profile confirmation; the
  shell (sidebar, header with the alert count, user menu); the dashboard (personal, department and State blocks, each
  loading and failing alone); administration (users, user detail with the exit dialog, access matrix, offices,
  designations, tickets) and My profile.
- Backend: `GET /reference/labels` (`services/reference.py`, `routers/reference.py`); `GET /admin/users` gains `q`,
  `role`, `include_ended`, `limit`, `offset` and `X-Total-Count`, answering as before without `limit`;
  `backend/tools/export_openapi.py` writes `frontend/openapi.json`, from which `npm run gen:api` generates
  `schema.d.ts` (both committed).
- Compose: `web` service (no `env_file`, so no secret enters it), a health check on `api`, a `portal` network with a
  fixed subnet. `.env.example` adds `WEB_HOST_PORT`, `COOKIE_SECURE`, `RELAY_TIMEOUT_SECONDS`, `ASLMS_SUBNET`, `WEB_IP`.
- Tests: Vitest suites for the client, relay, refresh, session, CSRF, proxy gate, UI kit, auth, shell, dashboard
  and admin screens; backend tests `test_api_reference`, `test_api_users_list`, `test_compose_web`,
  `test_openapi_snapshot`, `test_token_routes`.

**Decisions** (numbers are the design note's)
- 2, 3: tokens live in httpOnly cookies (`aslms_at`, `aslms_rt`, `aslms_device`, `aslms_challenge`); the browser never
  holds a token and the API is unchanged. 4: refresh is single-flight in the web server with a 30-second remembered
  result, so parallel dashboard calls never present a rotated refresh token twice (correct for one `web` process).
- 5, 6: writes need `X-ASLMS-Request: 1` and the `PORTAL_BASE_URL` origin; the relay forwards only allowlisted
  headers, refuses `/auth/*`, `/me/password` and the docs paths, and a backend test checks the token-returning routes
  against the OpenAPI. 7: `X-Forwarded-For` is trusted by the API only from `WEB_IP`, so audit rows carry the
  browser's address.
- 8, 9, 10: the sign-in screens follow the API's steps exactly and the first-sign-in gate stays the server's; page
  gating is convenience, the API enforces functions, scope and visibility.
- 11-15: data loads in the browser through the relay; no acting-membership switch; navigation declared once with
  a `built` flag; the dashboard and administration screens show an action only with its function.
- 16, 19: the two small API additions and OpenAPI-generated types, with a test failing on a stale `openapi.json`.
- 17, 18: plain CSS, WCAG 2.1 AA target, English only with all strings in `messages.ts`; CSP with nonce and the
  other headers. 20, 21: the `web` service as above; frontend checks join the definition of done.

**Deviations** (design note, Deviations section, 13 items; the main ones)
- A dedicated `portal` network carries the trusted address, so the project's default network and its running
  containers (the historical load) are not recreated (item 1).
- Dev tools are the newest releases that run on the local Node 20.18 (ESLint 9, Vitest 4 with Vite 6, jsdom 26,
  TypeScript 5.9); `npm audit` is clean for runtime dependencies, one advisory remains in the dev-only lint chain
  (item 2).
- The relay answers 401 without calling the API when there is no session cookie; stricter CSP and headers than
  listed; one UI-kit module; tabs and bell shown by function (items 3, 5, 7, 8).
- Head-change proposals retype the outgoing head; the `exit` variant and a per-item dialog for the admin swap are not
  offered in the ticket form (items 9, 10).
- Verification steps 3 and 5-8 (the running Compose stack) were not run: starting `api` would apply migrations 0009
  and 0013 to the dev database. `docker compose build web` and a local run of the built server were checked (item 13).

**Left for later**
- Other screens: case inbox, search and case detail (row 12), custody, notes, uploads, alerts and calendar (row 13),
  reports (row 39), audit and data health (row 41), Case Assistant (row 14).
- The Compose verification run once the dev database is migrated; the `exit` variant on the ticket form; one `web`
  process and the `X-Forwarded-For` limit for row 16 (reverse proxy, TLS).


## Dashboard ticket panel (2026-10-11)
- Gap found by the owner on first use: the user-memberships design gave `GET /admin/tickets/counts` "for the
  dashboard panel" and the owner asked for tickets on the super admin's dashboard, but neither reports-dashboards nor
  portal-shell built the panel. Added in the portal only (no API change): a "Tickets awaiting action" block first on
  the dashboard for holders of `admin.tickets` or `users.propose_head` (the API scopes the counts), with open
  tickets, the oldest open date, departments without a head (super admin), counts by kind and by department, and a
  link to `/admin/tickets`. Also shown on the short page of a login without case functions.
- Same day: `/admin/tickets` crashed in the running portal (a server page imported a plain value from a client
  module); fixed in 5aab8c5. Portal pages must be checked in the Compose `web` service, not only by unit tests
  (backlog row 43).

- 2026-10-11 — data-load-console: approved by the owner (progress and estimate, start a backdated load, pause/resume and order, single-case fetch, already-held warnings before any NAPIX call, one row per case with provisional adoption and court-duplicate links, admin.data_load; defaults kept: cases_first, NAPIX_LIVE_RESERVE 100, stored order PDFs not re-fetched; docs/design/data-load-console.md)


## Data-load console (2026-10-11)
Backlog row 45, branch `feature/data-load-console`, design `docs/design/data-load-console.md` (approved by the owner
on 2026-10-11). Built before row 12 at the owner's request.

**What was built**
- Migration 0014: `data_load_settings` (versioned master: paused, `load_order` enum `cases_first` / `lists_first` /
  `cases_with_orders`, optional period to go first), `fetch_queue.lane` (`fetch_lane` enum `request` / `daily` /
  `load`) and `fetch_queue.list_date`, `napix_call_log.lane`, a `court_duplicate` link kind and `dedupe` link source
  on `case_links`, the `case_merged` event type; two queue indexes.
- Services: `services/load_policy.py` (settings, lane and priority policy), `services/data_load.py` (progress,
  estimate, coverage by month, preview, start, pause, resume, order, single-case fetch, fetch details),
  `services/case_dedupe.py` (case-number key, serialised lookup, adoption, `merge_provisional`, court-duplicate
  links, sweep); changes to `queue`, `runner`, `court_search`, `orders`, `causelists`, `napix_admin`, `data_health`.
- API: `/admin/data-load` (progress), `/coverage`, `/preview`, `/start`, `/fetch`, `/fetch-details`, pause, resume,
  order, duplicates scan; the re-fetch buttons and `retry-failed` (lane filter) in `/admin/napix/*` carry the
  already-held warning. CLI: `aslms data-load status | coverage | start | pause | resume | order | dedupe`; `aslms
  load` goes through the same start service. A 03:00 dedupe sweep job.
- New grantable function `admin.data_load` ("Manage the data load"; super admin by default; seed only, 51 rows, 49
  active). Portal: one "Data collection" entry with four tabs (`/data/load`, `/data/health`, `/data/queue`,
  `/data/duplicates`), taking the data-health screen and NAPIX buttons over from row 41.

**Decisions** (numbers are those of the design note)
- Lanes `request` > `daily` > `load` on every queue row, inherited by spawned work; the lane is stored, not
  inferred from a priority number (1). Pause stops only the `load` lane, read by the claim query itself, so it needs
  no cache or restart (2).
- "What goes first" is a preset order plus an optional period brought forward; load priorities 41-48 sit behind the
  daily cycle and requests and ahead of the weekly sweep; default `cases_first` (3). Live-case order PDFs move from
  75 to 40 (5).
- Allowance protection: load runs at 150 or more calls left (`NAPIX_RATE_RESERVE`), daily and request work down to
  100 (`NAPIX_LIVE_RESERVE`, new, default 100), live searches down to 50 (`NAPIX_SEARCH_FLOOR`); the runner seeds
  its count from the call log at the start of each pass (4).
- Progress and period are derived, not stored; the estimate uses only rates measured over the last 7 days and says
  why it gives none (paused, under 24 h of history, no recent calls) (6-8).
- Start is preview then explicit choice about held days; the API answers 409 `already_held` before any NAPIX call
  and `force` / `held=refetch` is the choice to fetch anyway; the same for single-case fetch and the re-fetch
  buttons. Stored order PDFs cannot be re-fetched (409 `already_stored`) (9-12).
- One row per case: every creation goes through one serialised lookup; a provisional row is adopted or merged into
  the row holding its CNR only when it has no portal records, otherwise the pair is listed for review; court-side
  duplicates (same case or filing number, different CNRs) are linked, never merged, and the link counts toward
  department recommendations, never an assignment (13-15). Checks run inline, in the nightly sweep and on demand (16).
- Review findings fixed: a zero or negative case or filing number makes the key unusable (17); the merge locks the
  provisional row before it checks for portal records (18).

**Deviations from the design note** (full list in the note's "Deviations", 18 items)
- Policy code lives in `load_policy.py` to avoid an import cycle; skipped days count as held; the merge check also
  covers `custody_history` and `case_stages`; a provisional row matching several CNR rows merges into the oldest;
  person-asked court searches queue order PDFs in the `request` lane; the advisory lock is taken only on the
  creation path; the `already_held` 409 body is not in the OpenAPI document, so the portal types it by hand.

**Left for later**: see backlog row 46 (reviewed merge of provisional cases with portal records, discovery lane,
early Current Status re-run, coverage summary table, Compose verification). Migration 0014 is not yet applied to the
dev database: the worker is stopped briefly, the migration applied, and the worker restarted; the running backdated
load moves to the `load` lane and continues. NAPIX search by advocate and filing number remains row 21.


- 2026-10-12 — napix-window: approved by the owner (resets detected from the remaining count, worker waits for the expected reset plus 60 s with at most one probe per pass every 180 s, every budget band and figure on the detected window, the user who caused each call in napix_call_log visible to NAPIX operators only; daily and load calls carry no user; docs/design/napix-window.md)


## NAPIX quota window detected, and the user behind each call (2026-10-12)
Design `docs/design/napix-window.md` (backlog row 47), branch `feature/napix-window`, migration 0015.

**What was built**
- `services/napix_window.py`: the quota window is derived from the call log, nothing new is stored. A reset is a rise
  of at least `NAPIX_WINDOW_RESET_JUMP` (default 50) between two readings of `rate_limit_remaining`; it is precise
  when the previous reading is at most 300 s older. The expected next reset E comes from the latest precise reset in
  the last 6 hours plus whole windows. One pure function, `assess`, gives the state: `current`, `reset_due`,
  `overdue` or `unknown`.
- The runner (`services/runner.py`, `cli/pipeline.py`) no longer waits for the clock hour. The worker sleeps until E
  plus `NAPIX_WINDOW_MARGIN_SECONDS` (60); when the remaining count is unknown and work is waiting, it makes at most
  one probe (a single Overview call) per pass and at most one every `NAPIX_WINDOW_PROBE_SECONDS` (180).
- Every guard and figure uses the detected window: the court-search guard, the connectivity-check guard, the runner's
  seed, the health NAPIX block, the console's allowance card.
- Migration 0015: `napix_call_log.user_id` and `fetch_queue.requested_by` (both nullable, to users RESTRICT), partial
  index `ix_napix_call_log_user_called`, CHECK `ck_fetch_queue_requested_by`. `called_at` is now the attempt's own time.
  Court searches, case fetches, re-fetch buttons, the connectivity check and `request`-lane queue rows carry the person.
- New settings: `NAPIX_WINDOW_MARGIN_SECONDS`, `NAPIX_WINDOW_PROBE_SECONDS`, `NAPIX_WINDOW_RESET_JUMP` (in
  `.env.example`).
- Portal: the console shows the current window start and the next expected reset with recent resets; the health tab
  has a calls-by-user table; the call log has lane and user columns. `aslms data-health` prints the window line first.
- `docs/napix_integration_notes.md` section 6 and `docs/napix_integration_design.md` corrected: the reset falls about
  HH:33-HH:35 IST each hour (call log 1-11 Oct, 48,830 rows), not on the hour; the 1 Oct probe ended before it.

**Decisions and reasons**
- Resets are read from the remaining count, not kept in memory or Redis: each runner pass opens a new client, the API
  and worker are separate processes, and Redis holds only the token (row 16).
- The phase comes only from precise resets, so that imprecise sightings (the worker waking late) do not drift the
  expected time by the margin each window.
- At most one probe per pass, and the probe interval is capped at 300 s so consecutive probes always time a reset
  precisely. Margin and probe values hardly matter: the load spends its share in about 15 minutes.
- Daily-cycle and load calls record no user; only calls a person caused do. Names are shown only to holders of the
  NAPIX re-fetch or master-sync permissions; State-reports holders see totals.
- The measured cost being fixed: about 548 calls an hour over the last 24 h against about 850 possible.

**Deviations from the design note** (full list of 9 in the note's "Deviations")
- Decision 1's clustering rule, taken literally, merged two real resets in the 11 Oct log; built instead: a jump
  within a quarter window of the previous reset is the same reset only if a reading fell back by at least the jump in
  between.
- With no observed reset, "calls since the window start" is 0 and `by_user.window` is empty.
- A reading older than one window is never used; the runner re-reads the window when bands block after items ran;
  `last_check` and `check_guard` ignore probes; `retry_item` leaves `requested_by` NULL; the CHECK constraint was
  added by hand to the migration; the console's overdue line uses the default 3-minute figure.

**Left for later**: backlog row 48 (`napix-window-tail`), spending the reserve in the last minutes before the expected
reset, which needs the owner's decision. Migration 0015 is not yet applied to the dev database.

- 2026-10-12 — portal-cases: approved by the owner with the department mapping screens split out into row 50 portal-mapping (inbox, search, case page, ownership actions, CaseLink, five read-only API additions, the relay header fix of row 44 item 1; docs/design/portal-cases.md)


## Portal case screens: inbox, search, case page (2026-10-12)
Design `docs/design/portal-cases.md` (backlog row 12), branch `feature/portal-cases`. No migration; `schema.md` unchanged.

**What was built**
- Portal (`frontend/`): the case inbox at `/inbox/{recommended|claimed|pool|transfers}` with a department selector, tabs
  shown by the API's counts, the score badge and signal chips from the API's `band` and signals, and the claim, dismiss,
  suggest, allot, transfer request / decide / withdraw dialogs; `/search` (local list and search, NAPIX court search by
  CNR, case number or party with each error in words, order and document text); `/cases/[ref]` with eight tabs
  (Overview, Hearings, Orders with inline View and Download, Parties, Documents, Linked cases with an SVG graph, Notes
  read-only, Timeline, Details), banners for provisional, merged and not-fetched cases, and the Ownership card driven by
  the API's `actions`. Every case reference is a link through one `CaseLink`; hidden cases render as text. The header
  search box opens `/search?q=`.
- API (read-only additions): `last_listing` on `CaseSummaryOut`, `listed_from` / `listed_to` on `GET /inbox/recommended`,
  `actions` and `claim_departments` on `GET /cases/{ref}/ownership`, `user_id` and `units` on `GET /custody/recipients`,
  `GET /reference/case-types`. The relay now passes the API's `x-content-type-options` and `content-security-policy`
  headers on files viewed inline (item 1 of row 44).

**Decisions and reasons**
- The score colour and label come from the API's `band`, never from the portal comparing numbers: the bands are the
  super admin's settings.
- Server decides every permission; the portal shows buttons from `actions` and answers a hidden case with one neutral 404.
- Ownership checks were factored into `_check_*` functions so `available_actions` and the actions share one rule.
- Department mapping screens were split out at approval (owner, 12 Oct 2026) into row 50 `portal-mapping`.

**Deviations from the design note** (ten are listed in the note's "Deviations")
- Case API paths use the dash form of `ref_no` because the relay refuses an encoded `/`.
- Each ownership action now checks under the case row lock; outcomes and audit rows unchanged.
- Review fix: `POST /cases/{ref}/dismiss` and `/allot` took no department, so a login in two departments could act on
  the primary membership's recommendation. Both gain an optional `office_code` that must name one of the caller's own
  departments (400 otherwise, 403 without the function, 404 without the row); the inbox sends the selected department.
  The case page's Dismiss still sends none.
- The web smoke run used the branch's standalone server, not the Compose image (no registry access): all 41 pages
  answered 200.

**Left for later**: backlog row 51 (Compose `web` rebuild and smoke run, verification steps 3-9, whether the sandboxed
inline PDF renders, a department choice for the case page's Dismiss, Documents tab paging); row 50 mapping screens;
row 13 custody screens.

- 2026-10-12 — portal-mapping: approved by the owner (Department mapping tab: counsel codes with the unmapped-codes panel, keywords and name patterns, watchlist, scoring settings with history; weights editable only with admin.scoring; frontend only; docs/design/portal-mapping.md)

## Portal mapping screens (2026-10-12)

**Built** (frontend only; no migration, no table, no endpoint, no function; `docs/design/portal-mapping.md`, row 50)
- Routes `/admin/mapping` (opens the first tab the login may read), `/admin/mapping/codes`, `/keywords`, `/watchlist`,
  `/scoring`, under a new "Department mapping" Administration tab. `MAPPING_FUNCTIONS`, `MAPPING_TABS`,
  `mappingTabsFor(me)` and `PEOPLE_ADMIN_FUNCTIONS` in `src/lib/routes.ts`; `ADMIN_FUNCTIONS` now includes the mapping
  functions while Designations keeps its six.
- Counsel codes with the unmapped-codes panel (read only when first opened; "Map" fills the form and sends nothing),
  keywords and name patterns on one page, the watchlist, and the scoring settings with version history.
- Components in `src/components/admin/mapping/`; helpers in `src/lib/mapping.ts` (`isCnr`, `weightBody`,
  `isRootOffice`, `scoringErrors`, `changedFields`, `given`); strings in `T.mapping`; hooks `useScopedOffices`,
  `useScoringSettings`.

**Decisions and reasons**
- Weight inputs and Clear override exist only with `admin.scoring`; `weight` is sent only when changed (a number, or
  `null` to clear), never without the function, because the API refuses any `weight` key without it.
- A code mapped to the root office is sent with `is_generic_state: true`, so the form has one input, not two that must
  agree.
- Case references in the watchlist and the unmapped panel link to `/search?q=<ref>`, not the case page, so a link never
  leads to a 404 for a case the department cannot open yet.
- The scoring tab shows settings only; the portal never computes a band of a stored score.
- The mock-up's "code shared by more than one department" box is not built (a code maps to one office).

**Deviations from the design note** (eight in the note's "Deviations")
- "Reactivated" is said only when the answer's `id` was already in the list the screen held.
- A typed office code (login without `users.view`) never makes a code generic; the API refuses the root office itself.
- The mapping screens show the server's own message for 400, 403, 404, 409, 500, 503 and 504 through `given()`.
- After a watchlist edit or status change the line is "scored again now" or "Saved." (the answers carry no
  `dossier_queued`); an edit dialog with nothing changed closes without a call.
- Verification: `docker compose build web` and smoke run done (46 pages 200, no error line); backend `pytest -q`
  888 passed; frontend `npm test` 282 passed (25 files); lint, typecheck, build clean. The unmapped query measured
  0.11 s and 0.06 s cold on the dev database (49,128 cause-list entries), so nothing recorded for row 20.

**Left for later**: browser verification steps 4, 5 and 7 (they need the e-mailed sign-in code) are for the owner or
the integrator; the shared-codes box and paging of the rule lists (row 20); row 51 follow-ups; row 13 custody screens.


- 2026-10-12 — portal-cases-followups: approved by the owner (server-computed department lists per ownership action, a department choice in every dialog, sensible target lists, documents paged per group, inline view for PDFs and images only); merge not held for the owner's browser checklist, which follows as a post-merge task (INLINE_PDF true by default); docs/design/portal-cases-followups.md


## Portal case screens: department on every action, document paging, inline viewing (2026-10-12)

Backlog row 51, design `docs/design/portal-cases-followups.md` (approved by the owner 12 Oct 2026). No table,
column, code or migration; `docs/schema/schema.md` is unchanged.

**What was built**
- Backend, `services/ownership.py` and `api/routers/ownership.py`: `GET /cases/{ref}/ownership` `actions` now carries
  `dismiss_departments`, `suggest_departments`, `allot_departments`, `take_over_departments`,
  `stop_watching_departments` and `transfer_from`, computed by running each action's own check per department of the
  caller (read only, no lock, no audit). Optional `from_office_code` on `POST /cases/{ref}/suggest` and `office_code`
  on `/take-over` and `/stop-watching` (400 not the caller's department, 403 function not held there, 404 no row or
  recommendation there). Request transfer acts for the primary owner's department when the caller has a membership
  there. The super admin's `claim_departments` is `null` only for a pool case; otherwise the recommended, active
  departments that do not hold the case. `frontend/openapi.json` and `schema.d.ts` regenerated.
- Portal: a shared department choice in every case-page dialog (one department shown as text and sent; several a
  required select with no pre-selection; an `office_required` answer opens the same select); Allot and Take over show
  the chosen department's own unit and officer; Suggest and Request transfer exclude the own department and the
  departments already holding the case; the inbox's Recommended tab sends `from_office_code`, the Pool tab none;
  search-result Claim reads `claim_departments` from the server; the Documents tab pages each group (orders, filings,
  internal) by 50 with its own total and hides empty groups; `src/lib/documents.ts` (`canViewInline`, `INLINE_PDF`):
  View only for PDFs and images, Word downloads (Orders, Documents, Notes attachments).
- Tests: backend `test_ownership_actions.py` and `test_ownership_office_code.py` (flags and lists match outcomes,
  named-department suggest, take over and stop watching, transfer from primary); frontend `case.test.tsx`,
  `inlinePdf.test.tsx`, `documents.test.ts`, `inbox.test.tsx`, `search.test.tsx`.

**Decisions and reasons**
- The server names the departments per action, so the rule is written once; a flag is true exactly when the list is
  not empty, never only because `office_required` had no answer.
- Every action that resolves a department accepts it, so the screen and the API cannot act for different departments.
- The merge does not wait for the owner's browser checklist (owner's decision at approval, replacing design decisions
  10 and 11): the integrator merges after the automated gates. `INLINE_PDF` defaults to `true`. The API's
  `Content-Security-Policy: sandbox` is never relaxed. The checklist is row 53.

**Deviations from the design note** (six in the note's "Deviations")
- `request_transfer` is true exactly when `transfer_from` is set.
- The super admin's claim list holds active departments only.
- `useOfficeRequired`, `officeRequiredCandidates`, `DepartmentChoice` and `pdfDownloadOnly` as helpers;
  `canViewInline` takes an optional `inlinePdf` argument for tests.
- Suggest with one "from" department shows it as text; the inbox leaves the current owner out of the targets.
- Claim from search is disabled while the ownership read loads or fails; an empty list shows a message.
- Each document group shows its total and keeps its page while the next loads.

**Left for later**: the owner's signed-in browser checklist and the Chrome / Firefox PDF result (row 53; if either
fails, `INLINE_PDF` becomes `false`); the live court search only with `NAPIX_ENABLED` set by the owner for that run.


- 2026-10-13 — portal-workflow: approved by the owner with the Files and Alerts & calendar screens split out into row 55 portal-files-alerts (send file, recall, custody and stage tab, notes with drafts and corrections and visibility always chosen, uploads and document management, case alerts tab; seven read-only API additions and the relay content-length header; docs/design/portal-workflow.md)

## Portal case-page workflow: custody, stages, notes, uploads, case alerts (2026-10-13)

Backlog row 13, design `docs/design/portal-workflow.md` (approved by the owner 13 Oct 2026, "approve, split"). No
table, column, code or migration; `docs/schema/schema.md` is unchanged.

**What was built**
- Backend (read-only additions, decision 20): `GET /cases/{ref}` carries `workflow` (`note_mode` draft / permanent /
  null, `upload`, `set_stage`), computed by the same checks the writes run, without locking or writing; `NoteOut.can_correct`;
  `DraftDocumentOut` gains `id`, `doc_type`, `mime`; `AlertItemOut.can_act`; `GET /workflow/codes` carries `limits`
  and `GET /documents/types` carries `upload` (`max_bytes`, extensions) so the portal's pre-checks follow the server's
  settings; `GET /reference/labels` carries `alert_kinds`; `SentItemOut.visible`. `frontend/openapi.json` and
  `schema.d.ts` regenerated.
- Relay: forwards `content-length` (and the multipart content type) so the API's 413 guard refuses an oversized
  upload early.
- Portal, case page: Send file and Recall on the custody card; the Custody and stage tab
  (`/cases/[ref]/custody`: holder, movement history with remarks only where visible, stage history); Set stage; the
  note composer (says draft or permanent before writing, visibility chosen every time with nothing pre-selected),
  corrections as linked new notes, the drafts panel; the upload panel (type and size checked before sending, says
  which uploads reach the Case Assistant, every refusal explained) and document actions (change visibility, archive
  with a reason; no delete, no unarchive); the case Alerts tab (`/cases/[ref]/alerts`) with Acknowledge and Done;
  timeline lines for the new events; messages for each API error code.
- Tests: backend `test_workflow_actions.py` (new), additions to `test_notes.py`, `test_api_alerts.py`,
  `test_api_workflow.py`, `test_api_reference.py`, `test_custody_send.py`, new `test_api_documents.py`; frontend
  `workflow.test.tsx`, `workflow.test.ts`, `timeline.test.ts`, `routes.test.ts`, `relay.test.ts`, `case.test.tsx`.

**Decisions and reasons**
- Owner's split at approval: the Files screens, the Alerts & calendar screens (alerts list and hearing calendar), their
  navigation entries, the bell link and the dashboard links are row 55. This keeps the review on the case page, where
  notes, custody and visibility rules matter most.
- What a page offers comes from the server (flags, `can_correct`, `can_act`, `workflow`), so each rule is written
  once and the screen cannot offer what the API refuses.
- Nothing is sent to SourceTrace from these screens: notes, drafts and attachments are labelled internal.

**Deviations from the design note** (six in the note's "Deviations")
- Split as above; `useAlertCounts()` and `monthGrid()` are left for row 55. When a move hides the case from the
  sender, the portal stores a one-time notice (`src/lib/flash.ts`), goes to the dashboard and shows it once, instead
  of `/files/sent`.
- UI kit additions (`RadioGroup`, grouped `SelectField`, message contexts `CUSTODY_ERRORS`, `UPLOAD_ERRORS`,
  `ALERT_ERRORS`); the shared `Dialog` traps Tab and keeps the latest `onClose` in a ref (it stole focus on each
  keystroke); required fields use `aria-required` and the portal's own messages.
- A first stage pre-fills response mode `department`; the draft composer has no file field; the relay check was also
  run against a real Node 20 server, so no fallback for `content-length` was needed.

**Left for later**: row 55 (Files and Alerts & calendar screens); row 56 (Compose and browser verification of the
design's steps).

- 2026-10-13 — portal-files-alerts: approved by the owner (Files tabs With me, My offices, Department files with the tracking summary, Sent; Alerts list with explicit read marks; hearing calendar with 7-day agenda and month grid; case_visible on alerts so no link leads to a 404; a move that hides the case goes to /files/sent; docs/design/portal-files-alerts.md)

## Portal Files and Alerts & calendar screens (2026-10-13)

**Built** (row 55, design `docs/design/portal-files-alerts.md`, approved 13 Oct 2026; no migration, no table or column)
- Files frame `/files` with tabs `/files/mine` (With me), `/files/offices` (My offices), `/files/department`
  (Department files, with the tracking summary per tracked department) and `/files/sent`; filters and paging in the
  query string; no action buttons on the lists (sending and recalling stay on the case page).
- Alerts frame: `/alerts` (counts, filters by status, kind, severity and unread, Mark read, Mark all read,
  Acknowledge / Done) and `/alerts/calendar` (next 7 days agenda, month grid with the agenda below, department choice
  for State-wide readers).
- Navigation: "Alerts & calendar" built, new "Files" entry after Search, full-path breadcrumbs (`CRUMB_PATHS`), the
  header bell links to `/alerts` through a shared `useAlertCounts()`, the dashboard "My alerts" heading and "Files I
  hold" tile are links (`Tile` gains an optional `href`). A send or recall that hides the case now goes to
  `/files/sent` with the one-time notice (portal-workflow decision 6, as the approval said).
- One read-only API addition: `case_visible` on alert items and on the dashboard's alert list, computed by one
  `visible_case_condition` query per page (`services/alerts.py`, `services/dashboard.py`, `api/schemas.py`).
- Tests: backend `test_api_alerts.py` and `test_api_dashboard.py` additions; frontend `files.test.tsx`,
  `alerts.test.tsx`, `calendar.test.tsx`, additions to `shell.test.tsx`, `dashboard.test.tsx`, `routes.test.ts`,
  `workflow.test.ts`, `workflow.test.tsx`.

**Decisions and reasons**
- `case_visible` comes from the server so no alert row links to a 404 and the visibility rule is written once;
  the browser never guesses from kind and event.
- Opening `/alerts` marks nothing read; reading is by Mark read, Mark all read (no confirmation) or following the
  row's link (a failed mark never blocks navigation), so the bell count never drops unseen.
- The calendar is a plain table (Monday to Sunday, no calendar library); badges "Within 48 h" and "This week" are the
  API's flags, never computed in the browser; a month request never exceeds the API's 62-day range.
- The Department files tab shows only for a membership with a department and `custody.track`, the API's own rule.

**Deviations from the design note**: none recorded in the design; the note itself closes the split left by
portal-workflow (`useAlertCounts()`, `monthGrid()` and the `/files/sent` destination were deferred there).

**Left for later**: row 56 (Compose verification of the workflow and these screens in a browser); the reports screen
(row 39); row 53 browser checklist still with the owner.

## Owner decisions of 13 Oct 2026: filters, cause list screen, counsel code variants
- Filters on every list (portal-filters) and a Cause list screen for a chosen date and bench with Claim (portal-causelist) are added to the backlog right after portal-files-alerts, before the reports and audit screens and the Case Assistant.
- Counsel codes stay exact: normalisation remains upper case, collapsed whitespace and comma spacing only; a dot makes a different code, so variants such as `SC, ELEM. EDU` and `SC, ELEM. EDU.` are each mapped on the mapping screen (several codes may map to one department).

## Department input: Case_Handling.docx (13 Oct 2026)
- A department's description of how a case moves through its office (writ petition, action after the final order, contempt), with the counsel codes and officer names it searches on, kept as `docs/Case_Handling.docx`. Reviewed against the build: stages, sending the file (Option A to directorates and districts, referral departments), allotment and tracking (Option B), compliance alerts, appeals and contempt are covered.
- Owner decisions: add the missing stages (review petition filed, appeal dismissed/allowed, further appeal, complied after dismissal, Vakalatnama submitted, contempt disposed) as a reference-data migration (case-stages-extension); move department discovery (row 19) up after the Cause list screen, since departments find contempt cases by their officers' names; alerts to the officer named in a contempt case are parked until the owner gives the rule (named-officer-alerts).
- Note for setup: map counsel codes in the form the cause list prints them (`SC, SEC. EDU.`, `SC, ELEM. EDU`), not as the department wrote them (`SC, SEC. EDU`, `SC, ELEM, EDU`), since codes are matched exactly. The officer names can be entered as name patterns (both spellings for Pritam / Preetom Saikia); a name pattern alone scores 0.80, a possible match.

- 2026-10-13 — portal-filters: approved by the owner (one shared set of case filters in every list API and portal URL: words, cause-list date presets or any range, court and bench, next hearing date, case type, year, status, department where relevant; server-side; one FilterBar; GET /reference/benches; word search as the Search box everywhere; docs/design/portal-filters.md)

## Portal: one filter bar on every list (portal-filters) (2026-10-13)

Backlog row 59, design `docs/design/portal-filters.md` (approved by the owner 13 Oct 2026). No migration; no table, column, index or setting added, so `docs/schema/schema.md` is unchanged (every filter reads existing columns).

**What was built**
- Backend: `services/case_filters.py` (`CaseFilters`, `parse`, `conditions`, and the SQL pieces moved out of `case_search.py`), `api/filters.py` (shared query-parameter dependency); every list API now takes the same filters: `q`, `listed_from`/`listed_to`, `court_no`, `bench`, `next_from`/`next_to`, `case_type`, `year`, `case_status`, `owner`. This covers `/inbox/recommended|claimed|pool|transfers`, `/custody/held|sent`, `/alerts`, `/cases` and `/cases/search`.
- Own filters: `scored_for` on the pool ("Matched to department"), `other_office` on Transfers. Old names (`status`, `office`) stay accepted where they meant the same thing.
- `GET /reference/benches?days=` (court numbers and bench texts from recent cause lists).
- Portal: `FilterBar`, `DateRangeField`, `FilterChips`, `lib/filters.ts` (`LIST_FILTERS`), `useBenches()`; used on Recommended, Claimed, Pool, Transfers, Files (all tabs), Alerts and Search.
- Tests: backend `test_case_filters.py` (db and unit), `test_filters_write_nothing.py`, `test_custody_held.py`, additions to `test_api_inbox.py`, `test_api_cases.py`, `test_api_alerts.py`, `test_api_reference.py`; frontend `filterbar.test.tsx`, `filters.test.ts`, and updated inbox, files, alerts and search tests.

**Decisions and reasons**
- One set of filter names and one behaviour everywhere, because the owner asked for "a filter everywhere" and each tab behaved differently.
- Words are parsed as the Search box does (CNR, case number, `ref_no`, word prefixes over `search_vector`), replacing the inbox substring match. Advocates and counsel codes become searchable and the GIN index is used; a fragment in the middle of a word no longer matches.
- Cause-list date, court and bench are matched on the same cause-list entry; bench is "contains" on normalised text, since NAPIX has no judge master.
- Every filter only narrows what the list already returns; filtering is never audited and writes nothing (tested).
- Department filter per list: `owner` where cases are owned, `scored_for` on the pool, `other_office` on Transfers.

**Deviations from the design note** (recorded in the note's Deviations section): the department-code check runs where the session is, not in `parse`; length errors answer 400, not 422; the inbox refuses `owner`; next-hearing presets are today to today+6 and today+29; Search's total stays in its heading; `case_state=` in an old Search URL no longer filters; `/reference/benches` normalises spacing. Timings on the dev database were all under 0.6 s, so no index was proposed.

**Left for later**: a court-establishment filter once outlying benches' cases arrive; Compose browser check of the bars (with row 56). The Cause list screen (row 60) follows and may reuse `/reference/benches`.


- 2026-10-13 — portal-causelist: approved by the owner (Cause list screen for any date and bench in court order; published rows to every case reader with portal facts scoped on the server; other departments' recommendations only for State-wide readers; claimable includes the watcher claim; words on the printed row; the day fetch only for admin.napix_refetch; original PDF; docs/design/portal-causelist.md)

## Portal: the Cause list screen (portal-causelist) (2026-10-13)

Backlog row 60, design `docs/design/portal-causelist.md` (approved by the owner 13 Oct 2026). No migration; no table, column, index, reference code, function or setting added, so `docs/schema/schema.md` is unchanged (every read uses existing columns of `causelists`, `causelist_entries`, `causelist_bench_days`, `documents`, `fetch_queue`, `recommendations`, `case_ownership`, `cases`).

**What was built**
- Backend: `services/causelist_view.py` (dates, a day with its benches and lists, entries in court order with recommendation, owner and `claimable`, the list PDF), `api/routers/causelists.py`, schemas in `api/schemas.py`. Endpoints: `GET /causelists/dates`, `GET /causelists/{list_date}`, `GET /causelists/{list_date}/entries` (filters `bench_id` or `list_id`, `list_type`, `court_no`, `q`, `only`), `GET /causelists/lists/{id}/file` (inline needs `documents.view`, attachment needs `documents.download`). All need `cases.view_scope` or `cases.view_all`. Small changes in `services/documents.py` (`serve_stored`) and `services/ownership.py`.
- Portal: `/causelist` (day bar, bench select, list strip, entry table, ownership cell, Claim with the usual department choice), toggles with counts, the Hearings tab link from each listing to that day's list for its bench, the "Cause list" menu item after Search, `lib/causelist.ts`, messages and hooks; `frontend/openapi.json` and `schema.d.ts` regenerated.
- Tests: backend `test_api_causelists.py`, `test_causelist_view.py`, `causelist_support.py`, unit `test_causelist_view.py`; frontend `causelist.test.tsx`, `causelist.test.ts`, additions to `case.test.tsx`, `shell.test.tsx`, `routes.test.ts`.

**Decisions and reasons** (the five points the owner confirmed)
- Every case reader sees every stored entry, since the published cause list is court-public; recommendations, owner and claim are scoped per person on the server.
- Other departments' recommendations only to State-wide readers; department users see their own departments' recommendations.
- Claimable includes the watcher claim (recommended to my department but owned by another).
- Words match the printed entry text (parties, advocates, codes), not the case record.
- The missing-day fetch reuses the existing re-fetch button and its "already held" step, only for `admin.napix_refetch`.
- The list PDF is a court record and is not audited; Claim is audited as usual.

**Deviations from the design note** (full list in the note's Deviations section): `serve_stored` takes the store and a served name; a `causelist_day` row `done` with no list counts as `no_list`; a lone `from` or `to` takes the default span from the other end; court numbers sort via `numeric`; a case number in words also matches the printed case number of a row without a case; a merged case's row points to the survivor; the world's second department stands for FIN in tests; the state label shows for a held day only, the list type and court selects appear only with more than one value, and "Visible to me" carries no count.

**Left for later**: Compose browser check of the screen (with row 56); an index only if day-entries timing on the full load exceeds one second (row 64).

- 2026-10-13 — case-stages-extension: approved by the owner (seven stages: review petition filed, appeal or review dismissed, appeal or review allowed, further appeal filed (higher court), complied after dismissal of appeal or review; Vakalatnama submitted, contempt disposed; migration 0016 inserts the reference rows; docs/design/case-stages-extension.md)

## Case stages: appeal, review and contempt outcomes (case-stages-extension) (2026-10-13)

Backlog row 61, design `docs/design/case-stages-extension.md` (approved by the owner 13 Oct 2026). Source: the department's `Case_Handling.docx`.

**What was built**
- Migration 0016 (`0016_case_stages.py`, reference data only, no table or column change) inserts seven rows into `ref_case_stage` with `ON CONFLICT (code) DO NOTHING`: `review_petition_filed`, `appeal_dismissed`, `appeal_allowed`, `further_appeal_filed`, `complied_after_dismissal` (phase `appeal`, sort 180-220) and `vakalatnama_submitted`, `contempt_disposed` (phase `contempt`, sort 230-240). The catalogue is now 24 stages.
- The `Stage` enum gains the seven members after `CLOSED`; `aslms seed` carries the same phases and labels (`STAGE_PHASE`, `STAGE_LABELS`), so a migrated or a freshly seeded database gives identical rows.
- No API, permission, screen or frontend change: `GET /workflow/codes`, `POST /cases/{ref}/stages` and the Send file stage choice read the catalogue. The `stages.py` docstring was updated; no logic change.
- Tests: unit `test_case_stages_extension.py`; database `test_migration_0016.py`; additions to `test_api_workflow.py` (24 codes, a contempt stage set, an appeal stage set through custody send).

**Decisions and reasons**
- Labels "Appeal or review dismissed" and "Appeal or review allowed" (codes stay `appeal_dismissed` / `appeal_allowed`): one outcome stage covers both kinds of challenge, following Option C of the department's document. Labels are data and can change without a release.
- Ordered after the existing codes (no renumbering); each appears at the end of its phase group in the dialogs. No new phase. Gaps still count only `main` stages, so the new stages never create gaps.
- A reference-data migration, at the owner's request, is a change of convention (earlier `ref_*` additions were seed only), not a deviation from the plan. The migration hard-codes its rows and imports no application code.
- No audit row for the migration; recording a stage on a case is audited as before (`stage.set`).
- The downgrade refuses while any `case_stages` row uses a new code, otherwise deletes the seven rows (so a re-upgrade restores them active).

**Deviations from the design note** (in the note's Deviations section): migration written by hand with one insert per row; the no-op test also checks that a seeded label edit survives; a unit test compares the migration rows with the seed.

**Left for later**: alerts to a named officer in a contempt case (row 62, parked); any behaviour tied to a stage (for example stopping compliance alerts after "Contempt disposed") needs an owner rule.

- 2026-10-14 — Cause list screen, owner's decision on the review finding: recommendation labels stay as built. While a recommendation is open (status recommended), every member of the department sees its band and score on the Cause list entry, including directorate users on cases outside their directorate; once the department claims, dismisses or suggests the case elsewhere the label is gone. The published entries themselves are shown to every case reader.

- 2026-10-14 — department-discovery: approved by the owner with changes: automatic party-name discovery covers registration years 2025 onwards only (older cases arrive through case links); older years searched only when a user enters them on the Court search tab, with no call counts shown to users and a plain-words warning when the same search was made recently; live verification limited to 10 NAPIX calls, testing a blank reg_year first; docs/design/department-discovery.md

## Department discovery (department-discovery) (2026-10-14)

Backlog row 19, design `docs/design/department-discovery.md` (approved by the owner 14 Oct 2026 with changes). Plan §3.1 Table 4 and §5.4.

**What was built**
- Migration 0017 (`0017_department_discovery.py`): `discover` boolean on `office_keywords` and `office_name_patterns` (CHECK `ck_office_name_patterns_discover`: never on a regex); new tables `discovery_terms` and `discovery_hits`; enum values `fetch_kind.party_search`, `fetch_lane.discovery` (between `daily` and `load`) and recommendation origin `discovery`; the data step ticks existing discoverable rules.
- `services/discovery.py`: terms derived live from ticked active rules; a new term's first sweep (priority 43); a weekly sweep (priority 42, Saturday 02:00 IST); a manual sweep (`admin.data_load`); a user's request for older years. The `party_search` handler stores rows through `store_search_rows`, records hits, queues dossiers of found cases (41) and their order PDFs (49). Found cases are scored by the unchanged engine; nothing is assigned automatically.
- Runner: discovery rows are claimed only at or above `NAPIX_RATE_RESERVE` and while the window's discovery calls are below `NAPIX_DISCOVERY_SHARE` (default 100); when only discovery work waits and the share is spent the pass ends as a load-only block.
- API: `/admin/discovery` (summary, terms, term cases, search, sweep), `discover` on keyword and name-pattern endpoints, `GET /inbox/pool?found_for=`. CLI `aslms discovery status|terms|sweep`. Settings `NAPIX_DISCOVERY_SHARE`, `DISCOVERY_FROM_YEAR` in `.env.example`.
- Portal: "Search the court" tick and per-row toggle on the Keywords and name patterns forms; the Department mapping "Court search" tab; the Data collection "Discovery" tab; the discovery lane on the Load, Health and Queue screens; the pool filter "Found by our court search".
- Tests: unit `test_discovery_terms.py`; database `test_discovery_rules.py`, `test_discovery_run.py`, `test_discovery_weekly.py`, `test_migration_0017.py`, `test_api_discovery.py`, `test_api_discovery_negative.py`, `test_cli_discovery.py`; portal `discovery.test.tsx`, `discovery.test.ts`, additions to `mapping.test.tsx` and `inbox.test.tsx`.

**Decisions and reasons (owner's, 14 Oct 2026)**
- Automatic discovery covers registration years 2025 onwards only (`DISCOVERY_FROM_YEAR`); older cases come in through case links. The design's 90-day full sweep back to 2000 and the two-recent-years split were dropped; the first and weekly sweeps cover the same range.
- Older years only when a user enters a name and years on the Court search tab (`POST /admin/discovery/search`, audited `discovery.sweep`). Users see no call counts or allowance; the screen says the court is being searched and results appear as found. A repeat of a name and year already searched is answered with "already searched on <date>; search again?" (409 `searched_before`, `force` to repeat), following the already-held rule of the data-load console. Counts and the allowance appear only on the Data collection screens.
- The name must be one of the caller's terms (400 `not_a_term`), so each found case has a department that sees it and a rule that scores it.
- Discovery has its own lane and share, so it cannot starve the daily cycle and the historical load is not paused by it.

**Deviations from the design note** (full list in its Deviations section): single year range for every automatic sweep (no `scope` or `--full`); the search endpoint and its 409 rule; re-adding a deactivated rule keeps its `discover` value; the weekly job creates missing term rows; tests grouped differently from the plan.

**Left for later**
- Live verification (owner's go-ahead, limited to 10 NAPIX calls with `NAPIX_DISCOVERY_SHARE=10` for that run): try the party-name search with a blank year first and record in `napix_integration_notes.md` §7 whether the gateway accepts it; then one name for 2025 and 2026. Not run in this cycle; the share returns to 100 afterwards.
- Compose verification of migration 0017 and the portal tabs (design Verification steps 2-9).

- 2026-10-14 — department-discovery live check (owner-approved, at most 10 NAPIX calls; 4 used): Search by Party Name refuses a blank `reg_year` (606 INVALID_REG_YEAR), so discovery stays one call per registration year; the court matches `litigant_name` as the whole phrase. "NARAYAN KONWAR" (pending): 52 cases registered in 2025 and 103 in 2026, all contempt cases or applications in them; 16 of the 2025 cases were already held, 36 were new. Recorded in napix_integration_notes.md §7.

## Owner decision of 14 Oct 2026: no re-fetch questions
The user experience stays friendly: no "already held / already searched — fetch again?" question anywhere. A court search for a case already held opens the case and updates its details from the court; the Court search tab searches every time; data-collection re-fetches and loads over held days simply update. Limits (per-user hourly limit, budget bands, stored order PDFs not downloaded again) stay silent and automatic, with one plain line when reached. This replaces the owner's rule of 11 Oct 2026 (data-load-console: "it should alert me") and department-discovery decision 2's warning. Backlog row no-refetch-prompts, before the reports screen.

- 2026-10-14 — Correction to the owner decision "no re-fetch questions" above, on reflection the same day: everything stays as built except the Court search tab, where a name and year may be searched as often as the user likes with no "searched before" warning (department-discovery decision 2's warning removed). The Search page's court search and the Data collection screens keep their "already held, fetch anyway?" questions; the owner's rule of 11 Oct 2026 stands for them. Row 69 done.

- 2026-10-14 — portal-reports: approved by the owner (Reports tabs per report the caller may run; scope Whole State or a department; periods with presets; parameters in the URL; Excel and PDF downloads after the on-screen report, audited by the server; two read-only API additions: department names in GET /reports and 503 report_timeout; snapshots, scheduled e-mail reports and call-log retention parked as reports-followups; docs/design/portal-reports.md)

## Portal: the Reports screen (portal-reports) (2026-10-14)

Backlog row 39, design `docs/design/portal-reports.md` (approved by the owner 14 Oct 2026). Plan §5.10. No migration, no new table or column.

**What was built**
- Portal: `/reports` with one tab per report the caller may run (`/reports/pending-cases`, `/hearings-disposals`, `/pending-actions`, `/data-health`), taken from `GET /reports`; the form (scope, period presets and own dates, holding department, "List the files"), the on-screen report, the Excel and PDF buttons shown once the report has loaded, and a note that downloads are audited. Parameters live in the page address so a report can be bookmarked and Back restores the choices. A report runs when its tab opens with defaults. Components in `frontend/src/components/reports/`, helpers in `src/lib/reports.ts`; the Reports navigation entry is now built.
- Links: dashboard State section to Reports and each department section to that department's reports; data-health report and Data collection Health link to each other; pending actions links to Files and each file to its case page.
- Two read-only API additions: `GET /reports` now also returns `departments` (code, name, `is_active`) for every code its items list, so an inactive department that still owns cases is named; a report past the statement timeout answers 503 `report_timeout`, which the screen explains ("took too long, try a shorter period"). Other operational errors are not mapped.
- Tests: `backend/tests/db/test_api_reports.py` (`test_catalogue_names_its_departments`, `test_report_timeout_is_503`, `test_other_operational_errors_are_not_mapped`), `test_reports.py` adjusted; portal `reports.test.tsx`, `lib/reports.test.ts`, additions to `dashboard.test.tsx`, `data.test.tsx`, `shell.test.tsx`, `routes.test.ts`.

**Decisions and reasons**
- The API stays the authority on which reports, scopes and departments a caller may use; the screen builds tabs and choices from the catalogue and renders nothing private (no remarks, notes, documents or party names). Viewing writes nothing; only downloads are audited, by the server.
- State users default to Whole State; department users have their department filled in. Hearings and disposals opens on this month, data-health on the last 7 days.
- A timeout is a 503 the user can act on, not an error page.

**Deviations from the design note** (its Deviations section): page files pass the URL parameters from the server; only sections whose rows carry `ref_no` are paged (50); the truncated line is shown beside the API note; totals row drawn with `td` in `tfoot`; `QUERY_CANCELED` imported from `services/audit_search.py`; the catalogue is not retried on 403; the Health "Period report" link sits above the snapshot.

**Left for later**: month-end snapshots and trends, scheduled e-mailed reports and a retention job for `napix_call_log` (row 70, each needing an owner rule); drill-down from an aggregate row to a case or file list. The owner's browser check follows the design's Verification section.

- 2026-10-14 — portal-audit-health: approved by the owner (Audit log screen for the super admin and Auditor type: newest entries first, filters in the URL, actions grouped by plain names, entry page with before/after, audit-trail links from case, user and office pages for audit readers only; frontend only; department-scoped view, audit.searched rows and export parked as audit-followups; docs/design/portal-audit-health.md)

## Portal: the Audit log screen (portal-audit-health) (2026-10-14)

Backlog row 41, design `docs/design/portal-audit-health.md` (approved by the owner 14 Oct 2026). Plan §5.13. Frontend only: no migration, no table or column, no new function or setting, no backend change; `docs/schema/schema.md` is unchanged.

**What was built**
- Portal: `/audit` (search) and `/audit/[id]` (one entry) over the existing `GET /audit`, `GET /audit/actions` and `GET /audit/{id}`. The "Audit log" menu entry shows only when `readsAudit(me)` holds (super admin, or a membership with `audit.view` and `cases.view_all`).
- The search opens on the newest 50 entries and loads older ones with More (keyset cursor). Filters use the API's own parameter names and live in the page address: person (e-mail or login id, name contains), case (`ref_no` or CNR, merged cases included), office (department then unit), action (grouped under plain headings with "All ... actions" per group, codes as stored), period (any time, today, last 7 days, last 30 days, own dates), and a "More filters" section (about the user, record type, record id). Refusals show under the field concerned.
- The list shows time to the second in IST, action, who (name, designation, office or "System"), the case link and the record; name, office and action narrow the search. The entry page shows every detail including IP address and browser, a before/after table with changed marks, and `{length, sha256}` values as "Text not kept in the log" (note text and custody remarks are never in the log). Links: all entries for this case, by this person, for this record.
- "Audit trail" links for audit readers only: case page header, user admin page (entries by and about the user), office page (entries by the office).
- New code: `lib/audit.ts`, `readsAudit` in `lib/can.ts`, `formatDateTimeSeconds` in `lib/format.ts`, `components/audit/*`, `useAuditActions()`, route and crumb rules, an `audit` group in `lib/messages.ts`.
- Tests: `lib/audit.test.ts`, `components/audit/audit.test.tsx`, additions to `case.test.tsx`, `admin.test.tsx`, `routes.test.ts`, `format.test.ts`.

**Decisions and reasons**
- The API stays the authority on who may read; the menu and links are display only. Viewing and searching write nothing (audit-screens decision 3 stands).
- Actions are shown as stored codes grouped under plain names, not a label per code: the code is what an auditor quotes, and the list grows with every item.
- Filters in the URL so a search can be bookmarked or sent to another permitted reader.

**Deviations from the design note** (its Deviations section, nine items): a super admin without `audit.view` sees no entry or links; a URL whose filters fail the browser checks is not sent; the action list is requested after the search answers; the 503 text is the screen's own; with "Choose dates" the period refusal shows under "To"; the entry's Back link uses `sessionStorage`, not the referrer; a 422 on the entry id reads as 404; an `office` code that is not an active department is kept and shown as its code; "More filters" is a native `<details>`.

**Left for later**: row 71 `audit-followups` (parked, each needs an owner rule): a department-scoped audit view, `audit.searched` rows, export of an audit search. A person picker for the Person field; row 42 API hardening. The owner's browser check follows the design's Verification section.

- 2026-10-17 — next-date-extraction: approved by the owner (next dates read from stored order text by versioned rules: a written listing date used at once, a returnable date or a period always confirmed, unclear and no-text orders to an enter queue for claimed cases; pending rows never drive alerts; manual next dates; review alert; migration 0018; portal screens split into portal-next-dates; periods by rule until SourceTrace (row 37), calendar months, no weekend or holiday adjustment; docs/design/next-date-extraction.md)

- 2026-10-17 — next-date-extraction: owner's decision after the review stopped the cycle: periods counted from the order date and always confirmed by a user (as designed); dates after after / on or after / from / onwards / not before / commencing need confirmation; another matter's date or two dates in a direction read unclear; only plain directions are firm; written into the design note.

- 2026-10-17 — next-date-extraction, owner's second decision (option B) after the review stopped the cycle again: an order's date is firm only when it equals the court's own date for the case (NAPIX next hearing date or a cause-list listing); everything else is a suggestion confirmed by a person, and a suggestion becomes firm automatically when a matching court date arrives later; more period wordings counted from the order date.

## Next dates from orders (2026-10-17)
Backlog row 26, design `docs/design/next-date-extraction.md` (approved by the owner 17 Oct 2026; deviations 1-16), branch `feature/next-date-extraction`, migration 0018, in review. The portal screens are split into row 73 `portal-next-dates`.

**Built**
- Migration 0018: `orders` gains `next_date_status` (`pending` / `specific` / `period` / `unclear` / `none` / `no_text`), `next_date_found`, `next_date_rule`, `next_date_phrase`, `next_date_rules_version`, `next_date_read_at`, with two CHECKs and a partial index on pending orders; `next_dates` gains its CHECKs, a unique key and a partial index on pending rows; reference rows `next_date_review` (alert kind), `next_date_reviewed` and `next_date_entered` (events); `next_dates.review` described in the seed.
- `services/next_date_rules.py` (pure, `RULES_VERSION = 1`): reads the court's text of an order and gives a status, a date, a rule name and the court's sentence. `services/next_dates.py`: the reader, the review queue (confirm items and enter items), confirm / reject (with an optional replacement date) / enter, supersede and expire, the effective next date, and the match against the court's own date. `services/visibility.py` gains `working_condition_for`.
- API: `GET /next-dates/review`, `POST /next-dates/{id}/confirm`, `POST /next-dates/{id}/reject`, `POST /cases/{ref}/next-dates`, `GET /cases/{ref}/next-dates`; the case overview, Orders tab and dashboard gain next-date fields. `aslms next-dates read | status | sample`. Celery beat `next-dates-read` every 5 minutes (`job_runs` row `next_dates_read`; no NAPIX or SourceTrace call). Settings `NEXT_DATE_BATCH`, `NEXT_DATE_UNCLEAR_DAYS`, `NEXT_DATE_MAX_AHEAD_DAYS` in `.env.example`.

**Decisions and reasons**
- Option B (owner, 17 Oct 2026): an order's date is firm only when it equals the court's own date for the case (`cases.next_hearing_date` or a cause-list listing); every other reading is a suggestion that a person confirms. Reason: fixed rules over free court English always leave edge cases (the review found "the connected appeal is slated to be listed on ..." read as this case's date), so a wrong reading must never raise an alert unchecked. Option A (confirm everything) was rejected as too many clicks; option C (more tuning) as endless.
- A pending suggestion becomes firm by itself when the court's date later matches (system closure to `not_needed`, `needs_review` left true, no reviewer); the match runs at reading time, at the start of each reader run and after the dossier, status and cause-list updates.
- Periods are counted from the order date by rule (calendar months, no weekend or holiday adjustment) and always go to a person unless the court's date agrees; SourceTrace reading stays row 37.
- Pending rows never drive alerts or the calendar; a newer order without a usable date closes the dates of older orders; unclear and no-text orders of claimed cases go to an enter queue; manual dates get an `NXT` ref and are never deleted.
- Rules version stays 1 because no order has been read yet in the dev database.

**Deviations from the design note**: sixteen are recorded in its Deviations section (the text cap keeps the end of the order; listing verbs, nouns and deadlines are not listing dates; reported dates of other matters are no candidate; the words between verb and date must be a closed list to be plain; the `qualified_date` rule; a confirm for a passed date answers 409 `date_passed`; the option B match and its extra period wordings). Review stopped the cycle three times; each round's blocking findings are built and tested.

**Measured** (read-only dry run on the dev database, 17 Oct 2026, 32,091 pending order rows with text): 58.5% `list_on_date`, 19.7% `period`, 3,260 `unclear`, 2,091 `none`. Of the 2,778 rows a first run would write, 2,089 (75%) equal the court's date and are firm at once, 689 go to a person to confirm, and 504 orders would ask for a date. The hand check of the sample of 20 is not yet done (row 74).

**Left for later**: row 73 portal screens (queue page, case next-date block, Orders reading column); row 74 follow-ups and the first live read; row 37 SourceTrace reading of directions; row 27 compliance directions as alert sources.

- 2026-10-17 — portal-next-dates: approved by the owner (review list as a tab of Alerts & calendar, confirm asks once, separate Next date from orders card, department count vs own items explained, plain-words labels, workflow.next_dates flag; designed ahead in a separate worktree; docs/design/portal-next-dates.md)
- 2026-10-17 — search-court-advocate-filing: approved by the owner with the go-ahead for a live probe of at most 10 NAPIX calls before the build; outcome rules (a key with no column pauses for a migration amendment, an unsubscribed API is dropped); advocate hits stored without details; names up to 99 characters; court-call counts removed from the Search page; Data collection fetch stays at three kinds (docs/design/search-court-advocate-filing.md)

## Portal next dates (2026-10-17)
Backlog row 73, design `docs/design/portal-next-dates.md` (approved by the owner 17 Oct 2026; deviations 1-6), branch `feature/portal-next-dates`, no migration, in review. No schema change, so `docs/schema/schema.md` is unchanged.

**Built**
- Backend (one small addition): `workflow.next_dates` on the case workflow block (`CaseWorkflowActionsOut`, `services/workflow_actions.available`): true when the case is owned and an acting membership holds `next_dates.review`, the same rule `next_dates._check_write` runs. Tests in `tests/db/test_workflow_actions.py`; `frontend/openapi.json` and `schema.d.ts` regenerated.
- Portal: the review list at `/alerts/next-dates` (a tab of Alerts & calendar; confirm, reject with an optional replacement date, enter a date), the case page's next-date block with Enter next date and a "Next date from orders" section on Hearings, the reading column on the Orders tab, the dashboard "Recent next dates from orders" table and link to the queue; `AlertLink` for alerts of kind `next_date_review`. Code in `components/nextdates/`, `lib/nextDates.ts`; tests `nextdates.test.tsx`, `nextDates.test.ts` and additions to the case, alerts, dashboard, timeline and routes tests.

**Decisions and reasons**
- Who may act comes from the server flag, not the menu, so the screen never offers a button the API would refuse (decision 3). The dashboard has no such flag, so it shows a pending date as "Waiting for confirmation" (deviation 4).
- Confirm asks once; plain-words labels for rules and statuses (`T.nd.rules`).

**Deviations from the design note**: six, in its Deviations section: branch cut from `main` after row 26 was squash-merged; the `qualified_date` rule name; `date_passed` (409) given its own text; dashboard status words; `AlertLink` moved to its own file and the dialogs kept in one file; "n items match" wording.

**Left for later**: row 74 `next-dates-followups` (first live read, hand check of the sample, backend follow-ups). The owner's browser check follows the design's Verification section.

## Court search by advocate name and filing number (2026-10-18)
Backlog row 21, design `docs/design/search-court-advocate-filing.md` (approved by the owner 17 Oct 2026), branch `feature/search-court-advocate-filing`, no migration, in review. No new table or column, so `docs/schema/schema.md` is unchanged; the new NAPIX paths are in `docs/schema/napix_coverage.md` section D and `docs/specs/napix_field_inventory.md`.

**Built**
- Live probe (owner's go-ahead, 5 of the 10 allowed NAPIX calls, switch set for that run only, every attempt in `napix_call_log`); samples `docs/specs/samples/advocate_name_2026-10-18-p1/p3/p4.json` and `filing_2026-10-18-p5.json`; `docs/napix_integration_notes.md` section 7 updated.
- `aslms napix-check` gains the `advocate_name` and `filing` steps and `--max-calls`; every attempt is now recorded through a recorder and flushed in a `finally`, and the command refuses to start if the database cannot be reached.
- `POST /cases/search-court` gains the kinds `advocate` and `filing` (`services/court_search.py`, `api/schemas.py`); `NapixHighCourt.search_advocate` accepts `reg_year=None` for the probe only; `case_search.items_for` builds court-search results in one query.
- Portal: "Advocate name" and "Filing number" on the Search page's court search, with `field=advocate` read from the URL; the Search page no longer shows court-call counts.

**Decisions and reasons**
- A probe gated the build because the spec PDF had been wrong before for the party search. Results: advocate name works (rows carry `cino, pet_name, reg_no, reg_year, res_name, type_name`); `reg_year` is required (blank gives 606 `INVALID_REG_YEAR`); the honorific does not matter; the court matches part of a name (surname alone returned 325 rows including the 36 of the full name), so the hint asks for the full name. Filing number works (rows carry `cino, type_name, fil_no, fil_year, pet_name, res_name`; the held case was returned). Every key already had a home, so no migration.
- Advocate hits are stored without dossier details and `case_advocates` is not written from them; filing works like case number (local first, then one call).
- Users see no call counts (owner, 14 Oct 2026); the Data collection fetch keeps its three kinds.
- napix-check logs every call it makes, applying the "every call is logged" rule to the one command that broke it.

**Deviations from the design note**: listed in its Deviations section. In short: the build was split at the probe gate; filing rows carry no registration number, so a new case from one has no case number until its dossier arrives; `type_name` of a filing row fills only `case_type_text`; gateway error names 606, 607, 608 and 614 added (609 left unnamed); the napix-check options are validated before any call.

**Left for later**: P6 (an unregistered held case) was not run because the dev database holds none; search by Act, Bar registration number, neutral citation and caveat are not covered; advocate search in department discovery is not planned. The owner's browser check follows the design's Verification section.

- 2026-10-18 — safety-fixes: approved by the owner (api, worker and scheduler as aslms_app with the password from .env set by aslms db-roles; empty NAPIX 200 answers retried on a 10 min / 1 h / 6 h / 24 h / 72 h ladder with a fault pause; the weekly sweep covers every case never fully fetched; permanent failures in source_failures; failed rows revived; advocate searches store 25 at once, up to 300 in the background, more asks for a longer name; migration 0019; docs/design/safety-fixes.md)
- 2026-10-18 — deployment-checklist (rows 16, 77, 78): approved by the owner with the recommended defaults: pilot on the owner's machine on the office LAN (an SDC VM uses the same files), the machine's LAN name with an internal CA, the State government mail relay (Mailtrap sending until then, never the sandbox), backups every 6 hours with up to 6 hours of acceptable loss and the stated retention, a weekly copy to an encrypted external drive, monitoring alerts to the super admin, PgBouncer now, APP_ENV=prod on the pilot, upgrades as an explicit migrate step. Deviations accepted: monitoring and PgBouncer as rows 77 and 78 after row 16 (both before the pilot); aslms_readonly gains pg_monitor; monitoring screens on loopback only; docker compose up no longer migrates an existing database; the sample-of-20 definition and pass rule of decision 19 (docs/design/deployment-checklist.md)

## Safety fixes: application role, NAPIX recovery, capped advocate searches (2026-10-18)
Backlog row 76 (audit items Top 1 and Top 4 of `docs/audits/2026-10-18-independent-audit.md`, and item 1 of row 75), design `docs/design/safety-fixes.md` (approved by the owner 18 Oct 2026), branch `feature/safety-fixes`, migration 0019, in review. No new table or column.

**Built**
- Database role: Compose `api`, `worker` and `scheduler` connect as `aslms_app` (password `ASLMS_APP_PASSWORD`, required by Compose `:?`); `init` alone keeps `POSTGRES_USER` and now runs `alembic upgrade head && aslms seed && aslms db-roles`. `aslms db-roles` (in `cli/db.py`) sets the `aslms_app` password (and `aslms_readonly` when set) on every run with a quoted literal, never printed; it exits 1 on an empty, short (< 16), badly-charactered or default password, so `init` fails and the services do not start. `.env.example` corrected.
- NAPIX recovery: an empty or non-JSON HTTP 200 is `NapixEmptyResponse` (a `NapixUnavailable`), not retried inside the call; the queue retries on the ladder 10 min / 1 h / 6 h / 24 h / 72 h and marks `failed` after the sixth attempt (`MAX_ATTEMPTS = 6`); a request-lane enqueue brings a pending row's `not_before` forward; the runner pauses after `NAPIX_FAULT_STREAK` consecutive gateway failures for `NAPIX_FAULT_PAUSE_SECONDS`; the weekly sweep adds every non-merged case never fully fetched (by CNR, else `<est>|<number>`); rows that fail for good are mirrored into `source_failures` as `fetch_<kind>` (`services/source_failures.py`) and resolved when the row later ends done or skipped; `aslms queue-retry-failed --kind --lane` (audited `napix.queue_retry_failed`).
- Advocate searches: the first `NAPIX_ADVOCATE_STORE_NOW` new cases are stored in the request; up to `NAPIX_ADVOCATE_STORE_MAX` distinct CNRs the rest are queued as `search_rows` rows (one `napix_responses.id` each, no NAPIX call) and stored by the Celery task `aslms.store_search_rows` (kicked after commit, beat every 2 minutes); beyond the maximum nothing more is stored and the answer asks for more of the name. `CourtSearchOut` and the `case.search_court` audit row carry `court_cases`, `queued`, `not_stored`; the portal shows both notices.
- Tests: grants test for every table, an API flow under `aslms_app`, ladder, mirror, sweep, fault pause, advocate cap and background storing, `aslms db-roles` refusals and success and failure paths.

**Decisions and reasons**
- Evidence from the call log drove the fix: 9,668 empty 200 answers from `hc-cnr-api/CNR` in 30 days, the next call failing 89 % of the time, so waiting at the queue works and in-call retries only spend the allowance; 733 of the 736 failed dossier rows were this fault.
- `queue.LOCAL_KINDS` keeps `search_rows` out of the NAPIX runner so quota bands and window waits never hold it up.
- A password change is applied on every `init` run, which a one-time migration could not do.
- The empty-body fault is recorded in `docs/napix_integration_notes.md`.

**Deviations from the design note**: eight, in its Deviations section: audit numbers only on an `ok` advocate search; the API-flow test sets the role per connection (session level) because the app commits per request; `queue.claim` re-reads the claimed row; `search_rows` enqueued with `requeue=True` and skipped when the response is gone; `db-roles` also refuses a bad readonly password; `hc.advocate_rows` is the existing extractor; the grants test excludes DELETE on append-only `sourcetrace_ingestions`; the queue kind label in the portal.

**Left for later**: migrations still run as the cluster superuser, not `aslms_owner` (rows 16 and 80); the token endpoint's intermittent 401s (row 79); `job_runs` stuck in `running` (row 80); row 75 items 2 and 3 remain. Integrator, after merge and with `ASLMS_APP_PASSWORD` set in `.env`: `aslms queue-retry-failed --kind dossier` and `--kind status_batch` once.

## Deployment checklist, Part A: a closed-network pilot that is safe to run and recover (2026-10-19)
Backlog row 16 (rows 77 and 78 are Parts B and C, built later), design `docs/design/deployment-checklist.md` (approved by the owner 18 Oct 2026), branch `feature/deployment-checklist`, in review. No table, column or migration. Runbook: `docs/operations.md`.

**Built**
- Compose: only `proxy` publishes ports (443, and 80 redirecting); `postgres`, `redis`, `api`, `web` and `clamav` publish none. `compose.dev.yml` publishes loopback ports for development and puts `proxy` in profile `proxy`; `compose.clamav-mirror.yml` and `compose.clamav-offline.yml` cover ClamAV without internet. nginx proxy config under `infra/proxy/` (limits, health check), pinned images, hardened services, a Redis password and health check, a `backup` service, an explicit `migrate` service.
- `aslms ops` commands (`cli/ops.py`): `preflight` (names failing settings, never prints values; refuses weak or default secrets, and in `APP_ENV=prod` the unsafe settings), `db-guard`, `role-passwords`, `migrate`, `backup`, `backup-scheduler`, `backup-status`, `restore-check`, `restore`, `repair-jobs`, `load-report`, `sample-cnrs`, `make-cert` (internal CA, EC P-256). Services: `preflight`, `db_guard`, `backups`, `job_repair`, `load_report`, `certs`.
- Backups every `BACKUP_INTERVAL_HOURS` (default 6) at minute 30 IST, with retention settings `BACKUP_KEEP_*` (pruning dump sets only, never the store mirror); a weekly restore check Sunday 04:30 IST into a scratch database.
- Portal: client address taken from the trusted proxy hop only, a throttled-sign-in message, pinned base image (rows 43 and 44 items). Tests: `test_deployment_ops`, `test_backups_unit`, `test_ops_unit`, `test_preflight`, `test_deployment_compose`, `test_proxy_config`, and frontend `api.test.ts`.

**Decisions and reasons**
- One Compose stack on one host serves the owner's machine and a State Data Centre VM unchanged.
- `docker compose up` no longer applies migrations to an existing database; upgrades are an explicit, backed-up `migrate` step. This changes the old note in `compose.yml` and the 1 Oct Compose decision.
- `init` runs `aslms ops preflight && aslms ops db-guard && aslms db-roles && aslms seed`, so a bad secret stops every service. A live check found the dev `.env` still carrying the default `ASLMS_READONLY_PASSWORD`; preflight refused it as designed and the owner was asked to replace it.
- The owner's credentials never reach `api`, `worker` and `scheduler` (row 82): Compose blanks `POSTGRES_PASSWORD` and `ASLMS_MIGRATE_URL` for them.

**Deviations from the design note**: listed in its "Deviations made while building Part A". In short: `db-roles` extended rather than a second step; preflight reads four more settings and also checks `ASLMS_READONLY_PASSWORD` and URL-safe passwords; image tags pinned (nginx at the minor version); `COMPOSE_PATH_SEPARATOR=:` in `.env.example`; ClamAV mirror set in `freshclam.conf`; beat's schedule file in `/tmp` because the image runs as an unprivileged user (review fix).

**Left for later**: monitoring (row 77) and PgBouncer (row 78); migrations still run as the cluster superuser (row 80); the owner-run checks, the load counts and the sample-of-20 result are row 85; EICAR live test is row 24.

- 2026-10-19 — deployment-checklist dev cut-over on the owner's machine: new .env values (COMPOSE_PATH_SEPARATOR, COMPOSE_FILE with the dev override, REDIS_PASSWORD, PORTAL_BASE_URL); stack up with only 127.0.0.1 ports for postgres, api and web, Redis internal with a password; init found the database at head (0019) and set both role passwords; services connect as aslms_app; portal smoke passed; first backup 18:48 (352 MB dump and manifest; store copy running). Found: the root-owned document store refused writes from uid 10001 (fixed with chmod; runbook and row 86 item 9).

## Deployment monitoring, Part B (2026-10-19)
Backlog row 77 (split from row 16), design `docs/design/deployment-checklist.md` Part B, decisions 22-28 (approved by the owner 18 Oct 2026; `docs/design/deployment-monitoring.md` is a pointer to it), branch `feature/deployment-monitoring`, in review. One migration: 0020. Runbook: `docs/operations.md`.

**Built**
- Compose profile `monitoring`: Prometheus, Alertmanager, Grafana, Flower, the postgres and redis exporters and the ASLMS operations exporter; interfaces on 127.0.0.1 only. Profile `monitoring-host` adds node-exporter and cadvisor for a Linux VM.
- `aslms ops metrics` (`services/ops_metrics.py`, read-only, as `aslms_readonly`, each reading in a READ ONLY transaction): queue, jobs, worker liveness, NAPIX window, mail, backups, disk, ClamAV signatures, portal probe and certificate expiry. `--once` prints one reading.
- API request metrics (`api/metrics.py`) on internal port 9100: `aslms_api_requests_total{method,route,status}` and `aslms_api_request_duration_seconds`, by route template.
- Alert rules (17, `infra/prometheus/rules.yml`) tested with `promtool test rules infra/prometheus/rules.test.yml`; Alertmanager mails them through the SMTP settings; three provisioned dashboards (overview, PostgreSQL, Redis and Celery).
- Migration 0020: `GRANT pg_monitor TO aslms_readonly` (downgrade `REVOKE`). Preflight now requires `ASLMS_READONLY_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` and `FLOWER_BASIC_AUTH`. Tests: `test_ops_metrics_unit`, `test_ops_metrics`, `test_api_metrics`, `test_compose_monitoring`, `test_migration_0020`, `test_preflight`.

**Decisions and reasons**
- Grafana has no SQL data source; only the exporters read the database, and as the read-only role.
- Database URL defaults use `127.0.0.1`, not `localhost`: on Windows `localhost` tried `::1` first and each connection waited 5 to 20 seconds, which made the tester's database tests crawl.
- Alertmanager renders its configuration in an entrypoint script, with the SMTP password in a mode-600 file, because no image renders environment variables.
- Flower is not scraped (its metrics sit behind basic auth); the Celery queue length comes from the redis exporter.

**Deviations from the design note**: listed in its "Deviations made while building Part B". In short: two more gauges (disk total, oldest queued mail); an unmatched route is counted as `unmatched`; JobLate is three rules with a `late_after` label; ServiceDown also fires on `pg_up == 0`; the ops exporter sits on `default` and `edge`, not `portal`; the three new secrets are required even without the profile.

**Verified**: full suite `1471 passed` in 27 minutes on a quiet Postgres; `promtool check` and `promtool test rules` pass; in a scratch Compose project all seven Prometheus targets were up, Grafana and Flower refused anonymous access.

**Left for later**: migration 0020 is not applied to the dev database and the dev `.env` lacks the three new values (row 87, with the test-alert e-mail check); PgBouncer (row 78); the owner-run deployment checks (row 85); row 86 items.

## Deployment PgBouncer, Part C (2026-10-20)
Backlog row 78 (split from row 16), design `docs/design/deployment-checklist.md` Part C, decision 29 (approved by the owner 18 Oct 2026; `docs/design/deployment-pgbouncer.md` is a pointer to it), branch `feature/deployment-pgbouncer`, in review. No migration. Runbook: `docs/operations.md` section 18.

**Built**
- `infra/pgbouncer` (Dockerfile and entrypoint): Alpine with PgBouncer 1.25.1 (`>= 1.21`), uid 10001. The entrypoint writes `pgbouncer.ini`, an HBA file and a mode-600 `userlist.txt` into a tmpfs. `pool_mode = transaction`, `max_client_conn 200`, `default_pool_size 20`, `max_prepared_statements 200`, empty `server_reset_query`. The three values are `PGBOUNCER_MAX_CLIENT_CONN`, `PGBOUNCER_DEFAULT_POOL_SIZE` and `PGBOUNCER_MAX_PREPARED_STATEMENTS` in `.env.example`.
- Compose: service `pgbouncer` on 6432, internal only, started after `init`. `DATABASE_URL_SYNC` of `api`, `worker` and `scheduler` points at `pgbouncer:6432`; `init`, `migrate`, `backup` and the exporters stay direct to Postgres. `aslms ops migrate` and `restore` stop `pgbouncer`, and their refusal hints name it.
- Monitoring: `pgbouncer-exporter` (v0.12.1) with its Prometheus scrape job, alert `PgBouncerClientsWaiting`, and `pgbouncer_up == 0` added to `ServiceDown`, with promtool tests.
- Tests: `test_pgbouncer` (including the source scan `test_no_session_level_postgres_features` refusing session-level Postgres features in `backend/aslms`, and `test_compose_pgbouncer_urls`), plus changes to `test_compose_monitoring` and `test_deployment_compose`.

**Decisions and reasons**
- Transaction mode with prepared statements tracked, so the pool stays small; session-level features (advisory session locks, `LISTEN`, `SET` outside a transaction and the like) are therefore refused by a source test rather than found in production.
- Migrations, backups and restores bypass the pool because they need session state and the owner's role.

**Deviations from the design note**: listed in its "Deviations made while building Part C". In short: the build task named a note that did not exist, so the pointer file was created; `auth_type = hba` with SCRAM on every line, so `aslms_app` reaches only the application database and `aslms_readonly` only the console; the exporter signs in as `aslms_readonly` (a `stats_users` entry, no new secret, `admin_users` empty); the "clients wait 5 minutes" alert is queued clients for `for: 5m` because `query_wait_timeout` would refuse a client first; `ignore_startup_parameters = extra_float_digits` and no Unix socket.

**Left for later**: the owner-run checks on the real stack (row 89); migration 0020 and the dev `.env` additions of row 87 still apply; the owner-run deployment checks (row 85); row 86 and 88 items before the pilot.


- 2026-10-20 — pre-pilot-hardening: approved by the owner (backup dump exempt from the idle timeout, APP_ENV limited to dev/test/prod, store-check in init, worker liveness from the latest claimed row, role passwords as SCRAM verifiers, libpq 17+ floor, PgBouncer pinned with a login healthcheck, statement-based session-feature scan; docs/design/pre-pilot-hardening.md)

## Pre-pilot hardening (2026-10-20)
Backlog row 94 (rows 81, 90, 91, 92 and 93 in full; row 86 items 1, 5 and 9; row 88 item 1), design `docs/design/pre-pilot-hardening.md` (approved by the owner 20 Oct 2026), branch `feature/pre-pilot-hardening`, in review. No migration, table, endpoint, permission or audit action. Runbook: `docs/operations.md` sections 3, 4, 6, 17 and 18.

**Built**
- Backups: `backups.dump()` runs `SET LOCAL idle_in_transaction_session_timeout = 0` first in its REPEATABLE READ transaction, so a `pg_dump` longer than the server's 15-minute idle limit no longer has its snapshot session killed; every other session keeps the limit.
- `APP_ENV` is `Literal["dev", "test", "prod"]`: `production`, `Prod` or empty stop every process when the settings load. `aslms ops preflight` prints `preflight fatal: APP_ENV: must be dev, test or prod` and exits 1. Preflight has a third level, `fatal`, that stops the start at every `APP_ENV`.
- `aslms ops store-check` (`services/store_check.py`), run by `init` right after preflight with `./data:/data` mounted: creates a missing `/data/store`, makes a real write probe in the store and each first-level folder, and on failure exits 1 with the Linux `chown` and the Docker Desktop `chmod` remedies and a pointer to `docs/operations.md` section 6.
- Worker liveness: gauge `aslms_worker_alive_timestamp` = the later of the latest `queue-run` pass start and the latest `fetch_queue` claim (not `search_rows`, which the scheduler claims). `WorkerStalled` and the two dashboard panels ("worker last activity") use it; `aslms_worker_last_pass_timestamp` stays.
- `aslms db-roles` sends a client-side SCRAM-SHA-256 verifier (`pgconn.encrypt_password(..., b"scram-sha-256")`, built by `role_password_statement`), still under `SET LOCAL log_statement = 'none'`; the plain text never leaves the process.
- Preflight finding `libpq_floor()`: libpq older than 17 is fatal (PgBouncer transaction pooling with protocol-level prepared statements); a unit test asserts the floor in the test environment.
- PgBouncer pinned to `pgbouncer=1.25.1-r0` with `postgresql16-client=16.15-r0`; the healthcheck `infra/pgbouncer/healthcheck.sh` logs in through the pool as `aslms_app` and runs `SELECT 1` (password only as `PGPASSWORD` from the container's environment), with `start_period: 10s`.
- The session-feature scan in `test_pgbouncer.py` reads SQL statements: every string constant except docstrings (f-strings joined with `{}`), split on `;`, comments and `(` stripped, flagged on a session `SET` (including `SET TIME ZONE` and indented `SET` in triple-quoted SQL), `RESET`, `DISCARD`, SQL `PREPARE` / `DEALLOCATE`, `LISTEN` / `UNLISTEN`; any case in a direct `text()` / `.execute()` / `.exec_driver_sql()` / `sql.SQL()` argument, upper case elsewhere. Advisory session locks, temporary tables, `set_config(..., false)` and `WITH HOLD` stay line-based. The package passes.

**Decisions and reasons**
- Refusing an unknown `APP_ENV` at load, not only in preflight: a process started by hand would otherwise read `production` as "not prod" and skip `refuse_superuser`.
- The idle timeout is lifted for the exporting transaction only (`SET LOCAL`), not by role or server setting, so the guard stays for the application, `init` and `migrate`.
- Liveness from the claim time that `queue.claim` already writes: no heartbeat column, no migration, no change to the worker.
- SCRAM computed by libpq (the reference implementation) with the algorithm named, so a server `password_encryption = md5` cannot weaken it.

**Deviations from the design note**: listed in its "Deviations". In short: `init` also gets `STORAGE_DIR: /data/store`; the unknown-`APP_ENV` line says `preflight fatal:` as in the Services section; store-check re-raises an `OSError` that is not a permission error; a comment in the generated `pgbouncer.ini` says 1.22+.

**Verified**: full suite `1509 passed, 2 skipped` (20 minutes); `promtool check rules` and `promtool test rules` pass; the dump test fails without the `SET LOCAL` (the server ends the idle session) and passes with it; `apk policy` on `alpine:3.23.3` lists `pgbouncer 1.25.1-r0` and `postgresql16-client 16.15-r0`.

**Left for later**: the integrator's Compose verification (image build with the pins, the healthy login healthcheck, store-check on the dev store, the SCRAM verifiers in `pg_authid`, the alive gauge during the load); the other items of rows 86 and 88; row 80 (migrations as `aslms_owner`); the owner-run checks (rows 85, 87, 89).

- 2026-10-20 — github-and-ci: approved by the owner with the defaults, and the repository always stays on the owner's personal account nayanlhuzuri (no transfer); private; GitHub Free to start; the integrator pushes main and the feature/*-done tags after each local merge (fast-forward only, never forced), replacing the 4 Oct "never push" rule; the owner signs in gh and makes the first push after two full-history scans (docs/design/github-and-ci.md).
- 2026-10-20 — document-ocr: owner chose option C, no OCR in Phase 1; build Part 0 only (plain-words text labels such as "Scanned, not read", the content-search note, the documents_text block on data-health) and pin PyMuPDF below 2 so that no onnxruntime models are loaded under the "no local model" rule. Option B (SourceTrace returns the text it holds) parked as a follow-up row until row 36 (docs/design/document-ocr.md).

## Document OCR, Part 0 only (2026-10-20)
Backlog row 23, design `docs/design/document-ocr.md` (approved by the owner 20 Oct 2026, option C: no OCR in Phase 1), branch `feature/document-ocr`. No migration, no schema change.

**Built**
- Plain-words text labels on the Documents tab (`textLabel` in `frontend/src/lib/documents.ts`, words in `T.case.textLabels`): `pending` "Being read", `extracted` "Searchable", `none` on a PDF or image "Scanned, not read", on an old Word file "Old Word format, not read", on anything else "No text in the file", `failed` "Text could not be read". The raw `text_status` is no longer shown; a value added later shows as sent until it has words.
- The content-search note under the box on the Search text tab: scanned documents, images and old Word files are not searched by their content.
- `documents_text` block on `GET /admin/data-health` (`data_health.documents_text`, schemas `DocumentsTextOut`, `DocumentsTextKindOut`, `DocumentsTextNoneOut`): one grouped count over kinds `order`, `upload`, `attachment` (never `causelist` or `admin`) by status, with `none` split into `scanned_pdf`, `image`, `doc`, `other`. Totals only. Shown as a "Document text" block on the data-health screen. `frontend/openapi.json` and `schema.d.ts` regenerated.
- PyMuPDF pinned `pymupdf>=1.24,<2` in `backend/pyproject.toml`, with `test_pymupdf_loads_no_neural_runtime` (importing it loads no onnxruntime) and `test_pyproject_pins_pymupdf_below_2`.

**Decisions and reasons**
- Option C, no OCR in Phase 1: the dev database holds only born-digital court orders (0 `none` among 60,612 order PDFs at design time), uploads are still unmeasured, and a local OCR engine would sit against "no local model". The pilot gives the real count of scanned filings, which the data-health block now shows.
- PyMuPDF below 2: version 2 pulls onnxruntime layout models, which the "all AI through SourceTrace, no local model" rule forbids. Measured on 200 stored order PDFs (803 pages): text from 1.28.2 and 2.0 identical in 200 of 200 files and 803 of 803 pages. Image 596 MB against 914 MB with 2.0.
- Say "scanned, not read" plainly rather than leave the reading column empty.

**Deviations from the design note**: a fourth `none` bucket `other`, because `text_extract` also gives `none` to an empty DOCX, which "Scanned, not read" would misdescribe (labelled "No text in the file"); the second dependency test; `textLabel` in `lib/documents.ts`; the image check on a separately tagged image so the shared images are left for the integrator. Listed in the note's "Deviations".

**Verified**: `import pymupdf` on the built image gives 1.28.2 with no onnxruntime loaded; `documents_text` on the dev database equals the SQL group count (order 59,542 extracted, 4,189 pending, 0 failed, 0 none; upload and attachment 0). Backend and frontend tests for the counts, labels, note and block were added.

**Left for later**: Part A (local OCR engine, migration 0021) and the OCR interface are not built; Part B (SourceTrace returns the text of court orders and filings it holds, never internal documents) is parked as row 96, waiting for row 36 and decided again after the pilot. The tester's step 3 (uploads through the portal) needs the rebuilt `api` and `web` images; the integrator rebuilds them.

## GitHub remote and CI (2026-10-20)
Backlog row 15, design `docs/design/github-and-ci.md` (approved by the owner 20 Oct 2026), branch `feature/github-and-ci`. No migration, no schema change; `docs/schema/schema.md` is unchanged.

**Built**
- `.github/workflows/ci.yml`: jobs `changes` (docs-only detection), `policy`, `backend` (Postgres 16.15 service, `ASLMS_TEST_REQUIRE_DB=1`, installs with `backend/constraints-ci.txt`), `frontend`, `compose` (bake with per-target tags, `web` smoke through `portal_smoke.py`, `promtool test rules`) and `ci-ok`. Read-only token, no secrets, `NAPIX_ENABLED=false` with empty credentials, actions pinned by commit SHA. `.github/workflows/secret-scan.yml` (weekly, whole history) and `.github/dependabot.yml` (github-actions, monthly).
- A test database per run (`backend/tests/db/conftest.py`, helpers in `backend/tests/db/rundb.py`): name `<base>_<UTC stamp>_<6 hex>`, stale run databases swept after 24 hours (never `FORCE`, exact-pattern names only), dropped at session end; test-only variables `ASLMS_TEST_DB_PER_RUN`, `ASLMS_TEST_KEEP_DB`, `ASLMS_TEST_REQUIRE_DB`. A cluster advisory lock on the `postgres` database serialises role creation, the `migrated` upgrade and every test marked `migration_cycle` (new marker; all `test_migration_*.py` modules and the cycling tests elsewhere are marked).
- `backend/tools/repo_policy.py` (`tree`, `range`, `history`; prints path, line and rule, never the value), `.gitleaks.toml` (default rules plus NAPIX credential, Mailtrap token and private-key rules, commented allowlist), `.gitignore` additions, an optional `.githooks/pre-push` (owner enables with `git config core.hooksPath .githooks`).
- `.claude/hooks/guard.py`: refuses forced, mirrored, all-branch, pruning and deleting pushes, a push with no remote or a remote other than `origin`, `git remote` changes, and `gh secret` / `gh repo` / `gh api` forms; it reads every line of a multi-line command.
- Team definitions: the integrator checks CI on `main` before merging and pushes `main` and the `feature/<slug>-done` tag (fast-forward only) when a remote exists; `team-cycle` returns `pushed` and `ciRun`; `team-status` shows `origin/main` and the last CI runs; definition of done, team README, `README.md` and `docs/operations.md` (sections 16 and 19) follow.
- Tests: `test_ci_workflow`, `test_db_test_isolation`, `test_run_database`, `test_repo_policy`, `test_guard_push`.

**Decisions and reasons**
- Private repository on the owner's personal account `nayanlhuzuri`, always (no transfer): the repo holds court-record personal data (samples, fixtures) and specification PDFs of unknown redistribution licence.
- This replaces the 4 Oct "never push" rule: the integrator pushes `main` and the tag after each local merge, fast-forward only, never forced; a refused push is `merged: yes, pushed: no`. A red CI run on `main` stops the next merge; without `gh` the report says "CI status unknown".
- CI holds no secrets and starts only `web` in the `compose` job, so nothing can reach NAPIX.
- A per-run database fixes the audit finding that two runs wiped each other's data; the cluster lock covers roles, which are shared by every database (0020 grants and revokes `pg_monitor`).
- gitleaks CLI by image digest, not `gitleaks-action` (licence key). A true finding is never fixed by an agent; history rewriting and key rotation are the owner's.

**Deviations from the design note** (listed in its "Deviations", 1 to 14): `.claude/settings.json` left unchanged for the owner to apply; images built with `docker/bake-action` and tagged per target (unproven until the first GitHub run; fallback is a plain `docker compose build`); the history holds three old development defaults, not one (`POSTGRES_PASSWORD=aslms`, `ASLMS_APP_PASSWORD=aslms_app`, `ASLMS_READONLY_PASSWORD=aslms_readonly`), kept in a commented `HISTORY_ALLOWLIST` used only by `range` and `history`; extra guard and policy rules; `backend/constraints-ci.txt` added because an unconstrained install resolved newer FastAPI, Starlette and ruff and would have made CI red; two tests made independent of the CI environment; the OpenAPI export keeps RFC 9110 phrases on Python 3.12 and 3.13; the guard multi-line fix from review.

**Verified**: full-history gitleaks 8.30.1 scan clean (275 commits, per the design note); the backend job reproduced in Linux containers; the guard, policy, workflow and isolation tests added. Two discovery-runner tests failed once in the first Linux run and passed on rerun (row 100).

**Left for later**: nothing is pushed yet. Row 97 (owner: first push, first green run, repository settings, `settings.json` entries), row 98 (dependency locks), row 99 (optional test Postgres service), row 100 (possible flaky tests).

- 2026-10-20 — portal-ui-redesign: approved by the owner after four interactive mockups (v4 kept as docs/design/ui/aslms-ui-direction-v4.html): modern clean theme with smooth animations, one design system and the alignment rule, Government of Assam branding with the official emblem to be supplied, responsive on every device, English with seams for later translation (Bhashini/Sarvam would need an owner exception to the SourceTrace-only AI rule), Case inbox (own work, with Department cases and full filters for admins) and Case claim (suggestions with a full-details modal and inline orders with print and download), My calendar, simpler dashboard and case page; five build rounds; open questions as recommended, including the sight-only transfer_in basis for the receiving department while a transfer is requested (docs/design/portal-ui-redesign.md).
- 2026-10-20 — api-health-checker: approved by the owner with the defaults (System health at /system, function admin.service_health granted by the super admin, 17 NAPIX API cards with a live Test now from held data only, ten ASLMS service checks, one test per API per 60 s and 30 per person per hour, no typed input, no migration). Owner also chose sign-in template A (split panel) for round 5 (docs/design/api-health-checker.md).
- 2026-10-21 — api-health-checker-followups: approved by the owner with the recommendations: decision 7 kept (the connectivity check shares the Connection test's lock); decision 11 added, so `POST /cases/search-court`, `/cases/{ref}/fetch-court`, `/admin/data-load/fetch` and `/fetch-details` also commit their call rows apart (the "every call is logged, never lost" rule everywhere); the team-approve step reworded to replace the `approved_by:` line (docs/design/api-health-checker-followups.md).
- 2026-10-21 — portal-ui-polish: approved by the owner with the defaults (uicheck run whenever frontend/src changes; not in CI yet) (docs/design/portal-ui-polish.md).
- 2026-10-21 — ownership-refinements: approved by the owner with the architect's recommended answers (a)-(h); migration number by build order (0021) (docs/design/ownership-refinements.md).
- 2026-10-21 — alerts-visibility-roles: approved by the owner with the recommended answers: private documents follow the notes rule; listed-for-tomorrow critical with an immediate e-mail; the listing pass in the hourly sweep from 19:10; migration number by build order (0022) (docs/design/alerts-visibility-roles.md).
- 2026-10-21 — court-data-freshness: approved by the owner with the recommended answers: (a) the morning recheck of today's lists is ON (CAUSELIST_RECHECK_MORNING defaults to true); (b) no orphaned responses purged; (c) a file-only change is not a new version; (d) 1,000 disposed refreshes a night; migration number by build order (0023) (docs/design/court-data-freshness.md).

## Portal UI redesign, round 1: design system and shell (2026-10-20)
Backlog row 101 `portal-ui-foundation`, branch `feature/portal-ui-foundation`; design `docs/design/portal-ui-redesign.md` (approved by the owner; visual reference `docs/design/ui/aslms-ui-direction-v4.html`). Frontend only: no migration, no API change, `docs/schema/schema.md` unchanged.

**Built**
- Design tokens and the split UI kit in `frontend/src/components/ui/` (`controls`, `data`, `feedback`, `layout`, `overlays`, each with its own CSS module; `index.tsx` now re-exports; the old `ui.module.css` is gone): Card, PageHeader, Kpi, Chip, Skeleton, Collapsible, Menu, SidePanel, Modal, Stepper, DataTable (cards on phones), Lead and DateChip alignment columns. `motion.ts` holds the motion hooks, which honour `prefers-reduced-motion`.
- Shell: `PortalShell.tsx`, `Brand.tsx`, `icons.tsx`, header with the Government of Assam emblem slot (placeholder; `src/lib/brand.ts` is where the official emblem goes), grouped sidebar, phone drawer and bottom bar, breadcrumbs inside each page's `PageHeader`. Navigation declared in `src/lib/routes.ts`.
- i18n seams: `lang` attribute, locale-aware formatting in `format.ts`, labels moved into `src/lib/messages.ts`, `i18n.ts`.
- Tests: `tokens.test.ts` (contrast of every token pair), `motion.test.tsx`, `ui.test.tsx`, `i18n.test.ts` (JSX literal check), extended `shell.test.tsx`, `routes.test.ts`.

**Decisions and reasons** (full list in the design note's "Deviations", round 1, items 1 to 10)
- Red text uses `--red-text #B42318`, because `--red #D92D20` is 4.45:1 and 4.49:1, under the 4.5:1 the design requires; `--red` stays for fills.
- Only the Alerts entry has a count pill in round 1; Case inbox and Files counts wait for `/inbox/mine/counts` (round 2). Case claim and My calendar are declared with `built: false` until rounds 2 and 3.
- `Dialog` keeps its 760 px width until round 3 moves workflow dialogs to the Action dialog template.
- Where `matchMedia` is unavailable the motion hooks act as under reduced motion.
- Case numbers carry the global `cno` class; bare `ref_no` stays monospace.
- No separate design note for the row; round 1 was built from the redesign note.

**Left for later**: rounds 2 to 5 (rows 102 to 105: inbox and claim, case page and calendar, dashboard and work lists, oversight and settings, sign-in pages, removal of deprecated token aliases, the responsive sweep). The official emblem is still to be supplied by the owner.

## Portal UI redesign, round 2: Case inbox, Case claim and the case details modal (2026-10-20)
Backlog row 102 `portal-ui-inbox-claim`, branch `feature/portal-ui-inbox-claim`; design `docs/design/portal-ui-redesign.md` (approved; no separate note for the row). No migration; `docs/schema/schema.md` gets one as-built note (no table or column change).

**Built**
- Backend, read-only: `services/my_cases.py` (new) behind `GET /inbox/mine` and `GET /inbox/mine/counts` (Working on, Files with me, Claimed by me, Disposed); `GET /inbox/claimed` gained the filters unallotted, stage, holder and action, with stage and custody on its items; `whole_department` on `/inbox/counts`; `services/inbox.py`, `ownership.py` and `api/schemas.py` adjusted to match.
- Sight basis `transfer_in` in `services/visibility.py` (`member_bases`): while a transfer to a department is `requested`, the receiving department's admin, and an officer holding claim or allot, can read the case. Sight only, never a write (owner approved question 1 of the design).
- Portal: Case inbox (`MyCases`, `DepartmentCases` with the full filter bar, More filters and removable chips) and Case claim (Recommended, Unclaimed pool, Transfers to us) with the large case details modal (tabs, "Why this is suggested", ownership actions in the fixed footer, collapsible orders with the PDF inline, Print, Download). Old inbox URLs redirect (`Redirects.tsx`). Navigation counts come from `/inbox/mine/counts`, re-read every two minutes and on window focus. The old `Claimed`, `Pool`, `Recommended` and `Transfers` tab components are replaced.
- From the round-1 review: a closing Dialog, Modal or SidePanel is inert (`inert`, pointer-events none) and ignores clicks, `ConfirmDialog` drops a submit while closed or busy, so an append-only write such as a note cannot be sent twice; the drawer closes when the viewport grows past 820 px.
- Tests: `test_my_cases.py`, `test_visibility_transfer_in.py` (receiving admin reads while requested; an officer without claim or allot does not; sight lost on decline or withdraw; no write through the basis), additions to `test_api_inbox.py`; frontend `inbox.test.tsx` rewritten, `shell.test.tsx`, `motion.test.tsx`, `claimFixtures.ts`.

**Decisions and reasons** (full list in the design note's "Deviations", round 2, items 1 to 16)
- Claimed by me also counts a transfer the person accepted when a watcher row was promoted to primary, so accepted transfers are not lost from the person's list.
- `overdue` and `due_week` match only a custody row with a due date and a pending action other than none, so a file on an ownership leg with no action is never shown as overdue.
- Department cases opens on the caller's first whole-read department; a State-wide reader without one chooses first.
- Transfers to us defaults to status `requested`; From us shows any status.
- The transfer modal shows "Why this is suggested" only if the receiving department also holds a recommendation (a transfer is not a suggestion).
- Department cases rows carry no Allot button; Allot stays on the case page (round 3 moves it to "More actions").
- The success notice stays on Case claim, with "Open case page".

**Left for later**: rounds 3 to 5 (rows 103 to 105: case page and calendar, dashboard and work lists, oversight and settings, responsive sweep); round-1 and round-2 review advisories in row 106 and the rows beyond it.

## 2026-10-20 — Government of Assam emblem installed; push permissions applied (on `main`, outside a cycle)

**What changed**
- The owner supplied the official Government of Assam emblem (350 × 365 PNG, 20 Oct 2026). It is kept unaltered as `frontend/public/brand/assam-emblem-lockup.png`. The lion capital is cut from the same file with no other change, as `assam-emblem-mark.png`, for the 40 px header slot. `frontend/src/lib/brand.ts` names both. The header and drawer show the mark. The sign-in and first-sign-in pages show the full emblem above the portal name (`BrandLockup`), ahead of their round-5 redesign. Nothing is drawn or traced (design portal-ui-redesign, decision 21).
- Two fixes were needed for the files to be served at all: the page gate in `frontend/src/proxy.ts` leaves `/brand/` out of the matcher, because the sign-in page must show the emblem before anyone signs in, and the `web` image now copies `public/` (`frontend/Dockerfile`). Until now the image had no `public/` folder, because nothing was in it.
- `.claude/settings.json` gets the entries of design github-and-ci, decision 10 (deviation 1), which the owner approved on 20 Oct 2026:
  - `allow`: `git push origin main`, `git push origin refs/tags/feature/*`, `gh run list*`, `gh run view*`;
  - `deny`: `--force`, `-f`, `--force-with-lease` and `--mirror` pushes.
- **Deviation:** Claude Code checks `ask` before `allow`, so the broad `ask` entry `git push*` would have overridden the two push allows. It is replaced by narrower `ask` entries: `--delete`, `--all`, `--tags`, `origin :…`, `origin +…` and `origin feature/*`. Any other push is unlisted and is still prompted in the default permission mode. The guard hook still refuses the force forms.
- Tests: `shell.test.tsx`: the header shows the official mark by default, both files are present under `public/brand/`, and the placeholder is still shown when no emblem is set. `proxy.test.ts`: `/brand/` files are outside the gate. Vitest has 710 tests, lint and typecheck are clean, and portal_smoke passed against the rebuilt `web`.

**Left for later**: an SVG or a larger PNG (at least 800 px high) would sharpen the header mark on high-density screens; the owner may supply one, and only the files and the sizes in `brand.ts` change.

## 2026-10-20 — The application's name; show-password button (on `main`, outside a cycle)

**Owner decision (20 Oct 2026).** The application is the **Assam State Litigation Management System**, abbreviated ASLMS. "Legal Case Monitoring Portal" was a working title and is no longer used. The sign-in pages no longer name the Gauhati High Court.

**What changed**
- The portal uses the new name (`T.portalLong`) in the header, the page title and the sign-in and first-sign-in pages. On phones the header shows "ASLMS", and the full name stays available to screen readers.
- The e-mail footers in `services/alert_rules.py`, the test e-mail in `cli/alerts.py`, the API title (`api/main.py`, `frontend/openapi.json`), `pyproject.toml`, `README.md`, the `CLAUDE.md` heading and the architect's definition all use the new name.
- Existing file names, such as `Legal_Case_Monitoring_Portal_Plan.docx`, and earlier entries of this log are not changed.
- Every password field now has a show / hide button. `TextField` with `type="password"` adds an eye button that toggles, with `aria-pressed` and the label "Show password" / "Hide password". This covers the sign-in, reset, first-sign-in and administrator forms. Tests are in `ui.test.tsx`.
- A new sign-in page template is being chosen with the owner from mockups. It will be built separately.

## Portal UI redesign, round 3: the case page, action dialogs and My calendar (2026-10-20)
Backlog row 103 `portal-ui-case-calendar`, branch `feature/portal-ui-case-calendar`; design `docs/design/portal-ui-redesign.md` (approved; no separate note for the row, the developer's choices are in its "Round 3, row 103" section). No migration; `docs/schema/schema.md` gets one as-built note (no table or column change).

**Built**
- Backend, read-only: `GET /me/calendar` (`services/calendar.py` `my_calendar`, route in `api/routers/alerts.py`, `MyCalendarOut` in `api/schemas.py`): hearings of my cases, my action due dates and next dates to confirm, each with a `critical` flag, in date, kind, case order. `frontend/openapi.json` regenerated.
- Portal case page: summary header (next hearing, file holder, stage, owner, one primary action), tabs Overview, Hearings, Orders, Documents, Notes, Timeline, More; Overview with latest order and recent activity, secondary facts folded; Orders rows show the judge and "Next date read"; Timeline rows lead with the date chip.
- Workflow dialogs on the Action dialog template (the kit's `Dialog`, 560 px or 720 px `wide`, Cancel or Back left and one primary right in a fixed footer, case number as subtitle); Send file as a 3-step dialog with people as radio cards; Add note in a 720 px dialog.
- My calendar (month grid, legend filter, day agenda, dots on phones) and Alerts as its own menu entry; the old hearings calendar kept as the Department hearings view; `/alerts/calendar` redirects keeping its query string.
- Tests: `backend/tests/db/test_my_calendar.py` (three kinds for an officer, colleague's and unseen cases absent, overdue or near-due is critical, no confirm items without next-dates review, range limits, default range covers the month grid, ordering, reading writes nothing, 403 without a view function, merged-away case not listed); frontend `calendar.test.tsx`, `departmentHearings.test.tsx`, and updates to `case.test.tsx`, `workflow.test.tsx`, `alerts.test.tsx`, `shell.test.tsx`, `routes.test.ts`, `tokens.test.ts`.

**Decisions and reasons** (full list in the design note, "Round 3, row 103", items 1 to 15)
- With only one of `from` / `to` given, the other is the grid edge of that month; more than 62 days or `to` before `from` answers 422 `bad_range`.
- Action due dates are limited to custody rows the caller holds and the visibility rule; confirm items are the review queue's, so they need an active primary owner and a proposed date from today on.
- The header names the court and item of the next hearing only when the latest listing is on the next hearing day, so it never shows an earlier day as the next one.
- Claim and Accept transfer move to More actions when another action is primary; Decline and Withdraw stay on the Ownership card, so the page keeps one primary action.
- Every `Dialog` is now 560 px, administration dialogs included until round 5 restyles them.
- The calendar's legend is screen state, not in the URL; switching views drops `month`, `day` and `department`.

**Left for later**: rounds 4 and 5 (rows 104 and 105: dashboard and work lists, oversight and settings, sign-in pages, removal of deprecated token aliases, responsive sweep).


## System health: court API and ASLMS service checker (2026-10-21)
Backlog row 109 `api-health-checker`, branch `feature/api-health-checker`; design `docs/design/api-health-checker.md` (approved by the owner on 20 Oct 2026, 19 numbered decisions). No migration; `docs/schema/schema.md` has an as-built note (no table or column change). This screen is an addition the owner asked for, not in the plan; it complements Prometheus and Grafana (row 77) and the data-health screen, and replaces neither.

**Built**
- Function `admin.service_health` ("System health"), seeded by `aslms seed` (`access_seed.py`, `domain/reference.py`), given to no user type by default; the super admin holds it. Every endpoint needs it, reading included.
- API (`api/routers/system_health.py`, schemas in `api/schemas.py`): `GET /system-health` (cards and overall line), `GET /system-health/napix/{api}` (card detail), `POST /system-health/napix/{api}/test` ("Test now"), `GET /system-health/services` (the ten ASLMS checks). `frontend/openapi.json` and `schema.d.ts` regenerated.
- Services: `services/system_health.py` (the 17 court cards from `napix_call_log` over 7 days with no call made, `card_status`, the overall line), `services/napix_samples.py` (one held-data input chooser per card), `services/napix_api_check.py` (guard, one live call through the integration layer, whitelisted summary, audit row), `services/service_checks.py` (API, database through the pool and direct, Redis, queue worker, scheduler, ClamAV, backups, document store, web portal).
- `NapixHighCourt.case_by_cnr(cnr, *, fallback=True)`: the test passes `fallback=False` so a gateway 404 on `/CNR` is reported as it is and the alternate path is never tried.
- `ops_metrics.worker_alive_at(session)`: the worker liveness rule is now one function shared by the exporter and this screen.
- Settings (also in `.env.example`): `HEALTH_TEST_API_MIN_SECONDS` (60), `HEALTH_TEST_PER_USER_HOUR` (30), `HEALTH_TEST_TIMEOUT_SECONDS` (30), `HEALTH_POOL_ADDRESS`, `HEALTH_POSTGRES_DIRECT_HOST`, `HEALTH_POSTGRES_DIRECT_PORT`.
- CLI: `aslms system-health [--json]`, read-only.
- Portal: `/system` ("System health" in the Settings group): status ring, 17 court cards in four groups with 24 hourly bars and answered rates, a detail and test panel, the ten service checks; new inline SVG chart components in `components/ui/charts.tsx` with a reduced-motion fallback.
- Tests: `tests/db/test_api_system_health.py` (every endpoint needs the function, reading never calls the gateway, one call per API from held inputs, no held data means no call, names never leave the server, a test writes no case data, a gateway 500 is one attempt, empty 200 reported as the known fault, 628 reads answered, the CNR 404 never tries the alternate path, per-API interval, per-user hourly cap, quota floor, unknown window allows a test, concurrent test refused), `test_service_checks.py`, `test_system_health_seed_cli.py`, unit tests `test_system_health.py` and `test_service_checks.py`, frontend `system.test.tsx`, `charts.test.tsx`, `systemHealth.test.ts`, `routes.test.ts`.

**Decisions and reasons** (full list in the design note)
- A grantable function rather than super-admin-only or reusing `admin.napix_refetch`, so live court tests do not reach every Central operator.
- A card's "answered" counts a valid not-found or input refusal as up; only transport, gateway, auth and empty-answer failures count as failed. Status (Working, Unsteady, Failing, No recent calls) comes from one pure function.
- "Test now" makes exactly one call, with no retry or batch, using an input only from data already held; no typed input in this item (the owner may reopen). The answer is summarised from a whitelist and never shown verbatim; party and advocate names never leave the server.
- Refusals before any call and writing nothing, in order: unknown API, switch off, no held sample, one test per API per interval, per-person hourly cap, quota floor, one at a time (a transaction-scoped advisory lock, safe under PgBouncer transaction mode). Every test that made a call writes one `napix.api_tested` audit row; the interval and cap count those rows.
- The test runs synchronously in the API request, not through the `request` lane. `NAPIX_ENABLED` is never set in code or tests; tests patch `Settings.napix_configured`.
- The screen alerts nobody and keeps no history of its own; alerting stays in Prometheus and Alertmanager. Mail and SourceTrace are out of scope.

**Deviations**: none from the plan or the approved note. The note's header carries a stray second `approved_by: (pending)` line; the owner's approval is recorded in the first.

**Left for later**: typed test inputs, a "test all court APIs" button (rejected for now by decisions 6 and 7), and service cards for mail and SourceTrace once the real connector exists. The owner's browser check with `NAPIX_ENABLED` on for one run is not done by the team.

## 2026-10-21 — System health: the pool card as the app role (on `main`, outside a cycle)

- After api-health-checker merged, `aslms system-health` in the running stack showed "Database through the pool — Unsteady, its details could not be read". The services connect as `aslms_app`, and migration 0001 revokes every right on `alembic_version` from that role, so the card's revision query was refused. The tests had run as the owner role and never saw it.
- The card now reads the revision in its own savepoint. When the revision is refused, the fact reads "checked when the services start" (`init`'s db-guard already refuses to start the services on a database behind the code), and the card stays ok. The grant is not widened. Test: `test_pool_card_as_the_app_role_without_the_revision_table` (`SET LOCAL ROLE aslms_app`).
- The first restore check of the backups was run by hand (`docker compose exec backup aslms ops restore-check`). The Backups card had read "no restore check in the last 8 days", because the weekly Sunday run had not yet come round since the backup service started.


## Portal UI redesign, round 4: the dashboard and work screens (2026-10-21)
Backlog row 104 `portal-ui-dashboard-work`, branch `feature/portal-ui-dashboard-work`; design `docs/design/portal-ui-redesign.md` (approved; no separate note for the row, the developer's choices are in its "Round 4, row 104" section, items 1 to 14). No migration; `docs/schema/schema.md` has an as-built note (no table or column change).

**Built**
- Backend, read-only: `GET /dashboard/me` gains `headline`, `upcoming` and `attention` (A7) in `services/dashboard.py`, with schemas `DashboardHeadlineOut`, `DashboardClaimCountsOut`, `DashboardWeekHearingsOut`, `DashboardFilesWithMeOut`, `DashboardOverdueOut`, `DashboardUpcomingOut` and `DashboardMeAttentionOut` in `api/schemas.py`. `frontend/openapi.json` and `schema.d.ts` regenerated. Existing personal fields are unchanged.
- Portal dashboard: greeting, five headline numbers, Upcoming hearings, Needs your attention; the views My work, Department and State in the query string (`/?view=`), the rest of the old personal block folded under "More about my work" (`components/dashboard/Headline.tsx`, `Blocks.tsx`).
- Files, Search, Cause list and My profile moved to the Work list and Settings templates: cards on phones, details in a side panel, the due date leading each Files row in a `DateChip`, Cause list entries with `Lead` and show-only `Chip`s, and the new kit component `SettingsLayout` (Details, Notifications, Change password, Devices; `?group=`).
- Kit: `DataTable` ignores a row click that lands on a link or control inside the row; `format.ts` and `messages.ts` additions.
- Tests: `backend/tests/db/test_dashboard_headline.py` (headline figures, upcoming hearings of the week in order, attention order and limits, merged and unseen cases hidden, existing personal fields unchanged, the headline writes nothing, the API answers the headline); frontend tests in `dashboard.test.tsx`, `files.test.tsx`, `search.test.tsx`, `causelist.test.tsx`, `profile.test.tsx`; the spacing check in `tokens.test.ts` now covers `dashboard`, `files` and `causelist`.

**Decisions and reasons** (full list in the design note)
- `headline.next_dates_to_confirm` is the next-date queue count for the caller, so the number equals the total of the review list it opens; `files_with_me` equals `/inbox/mine/counts.files`.
- `file_received` items are files with me from the last 7 days, excluding legs the caller wrote themselves and files already listed as overdue or due soon.
- Upcoming is My calendar's hearings from today to today + 7 in date order, showing "Court n . item m" because the alert item carries no parties.
- A login with State and personal work opens on My work; without personal work it opens on State. The ticket panel heads the last view the login has.
- `DashboardMeAttentionOut` is named so because `DashboardAttentionOut` already names the department block's section.
- Search keeps one primary button on the page (the filter bar's Apply); "Search the court", Claim and Open case page are secondary.

**Deviations**: none from the plan or the approved note; the choices where the note was silent are in its "Round 4" section.

**Left for later**: round 5 (row 105: Reports, Audit log, Data collection and Administration on the Report, Work list, Dashboard and Settings templates; sign-in pages with the brand; removal of deprecated token aliases; responsive sweep). `SettingsLayout` is reused there for Administration.


## Portal UI redesign, round 5: oversight, settings and the final sweep (2026-10-21)
Backlog row 105 `portal-ui-oversight-settings`, branch `feature/portal-ui-oversight-settings`; design
`docs/design/portal-ui-redesign.md` (approved; no separate note for the row, the developer's choices are in its "Round 5,
row 105" section, items 1 to 10). Frontend only: no API change, no migration, `docs/schema/schema.md` unchanged.

**Built**
- Reports on the Report template: the choices in a card on top, the results below, Download Excel and Download PDF always
  in the page header's secondary actions (disabled until the report on screen has loaded, then carrying exactly its
  parameters).
- Audit log on the Work list template: filters in a card, rows as a `DataTable` (cards on phones), a row opening its entry
  page, a count of the entries shown.
- Data collection on the Dashboard template: panels on a two-column board, the lanes, call counts and discovery figures as
  headline numbers, the duplicate kinds as chips.
- Administration on the Settings template: the groups (users, user types, offices, designations, Department mapping,
  tickets) as a sub-menu on laptops and a select on phones; Users and Tickets lists as `DataTable`s.
- The sign-in, code, reset and first-sign-in pages on `AuthFrame`, the owner's template A (split panel with the full name,
  three benefit tiles and the official emblem lockup; the two-step indicator on sign-in and code); the error and not-found
  pages with the brand over the empty-state pattern.
- The deprecated token aliases removed; new `--panel-*` tokens for the sign-in panel, contrast-tested.
- Tests: `components/auth/frame.test.tsx` (the brand and panel on every public page, steps, show password, error pages);
  Report, Work list, Dashboard and Settings template tests in `reports.test.tsx`, `audit.test.tsx`, `data.test.tsx` and
  `admin.test.tsx`; `tokens.test.ts` fails on any alias left and checks spacing in every CSS module;
  `src/app/pages.test.tsx` renders every page and allows at most one primary action, and refuses a server file calling a
  function of the client UI kit.

**Decisions and reasons** (full list in the design note)
- One primary per page is now checked across the portal; where a page had two, the secondary one became secondary (the
  users filter's Search, Enable login, Reactivate, Add admin, New office under an office, a ticket's Archive and Attach,
  Add pattern, the discovery tab's Claim, the load console's Resume, Save and Fetch now).
- Audit rows open the entry page, not a side panel, because the before / after values, IP address and browser stay on the
  entry page only (portal-audit-health decision 5).
- Administration keeps its group routes, so no address changes.
- `not-found.tsx` became a client component after the Compose portal smoke showed every page logging a server call to
  `buttonClass()`; the new check in `pages.test.tsx` keeps that from returning.

**Deviations**: none from the plan or the approved note; the choices where the note was silent are in its "Round 5"
section.

**Left for later**: the owner's browser check of round 5 (Verification, "After round 5": the same layout on Reports,
Audit log, Data collection and Administration; the sign-in page with the emblem; 375, 768 and 1280 px without sideways
scrolling except wide report tables). Administration tables other than Users and Tickets still scroll sideways inside
their card on phones.


## System health follow-ups: call records that survive a failed request (2026-10-21)
Backlog row 110 `api-health-checker-followups`, branch `feature/api-health-checker-followups`; design `docs/design/api-health-checker-followups.md` (approved by the owner on 21 Oct 2026 with the recommendations, 11 decisions). No migration (head stays 0020); `docs/schema/schema.md` has as-built notes (no table or column change) and the `ref_permission` count corrected to 52 rows, 50 active. Closes the six advisory findings of row 109 and two defects of the same kind found while designing.

**Built**
- `NapixRecorder.flush_apart(session_factory)` commits the `napix_call_log` and `napix_responses` rows in a session of their own, opens no session when nothing is pending, and clears the pending attempts only after the commit. `audit.write_audit_apart(...)` does the same for an audit row.
- System health Test now (`services/napix_api_check.run`): call rows committed apart in a `finally`, then the summary, then `napix.api_tested` written apart; an unexpected error in the summary still writes the audit row with `summary: null` and `summary_error` (the exception class name) and the request answers 500. The request transaction itself writes nothing.
- The data-health connectivity check (`napix_admin.health_check`) gets a `try/finally`, the same separate commits, and takes the lock `napix-api-test:overview` shared with the Connection test (409 `check_running`).
- Per-person lock `napix-api-test-user:<user>` taken before the per-API lock (409 `user_test_running`); the per-API interval and the hourly cap are checked again once both locks are held.
- Client (`NapixClient._attempt`): a token renewal is logged in the order it happened, as the HTTP 401 step (`ok` false, `error_family` NULL) and then the repeated attempt as its own row; a failed repeat is no longer copied onto the 401 row; durations no longer nest. `napix_api_check.final_attempt` removed.
- `services/system_health.py`: the answered rates, bars, median and p95, last-result rule and last 10 calls leave out the renewal step (`http_status = 401 AND error_family IS NULL`). The quota window and calls-by-person still count it.
- Summary dates read with `napix_values.as_date` (the sentinels `5000-01-01`, `1900-01-01`, `0000-00-00`, a blank and "Next Date Not Given" read as absent); business text stays a plain non-blank check.
- Owner's addition (decision 11): `POST /cases/search-court`, `POST /cases/{ref}/fetch-court` and `POST /admin/data-load/fetch` commit their call rows apart too. Their audit rows and case data stay in the request transaction.
- Portal: two messages in `frontend/src/lib/messages.ts`; `frontend/openapi.json` and `schema.d.ts` regenerated for the two new refusal codes.
- Tests: `tests/unit/test_napix_client.py` (renewal logs the 401 step first, a failure after renewal is logged once, a failed renewal on the 401 row, durations do not nest, a second 401 is an auth error); `tests/unit/test_system_health.py` (sentinel dates, business text); `tests/db/test_api_system_health.py` (rows survive a failure after the call and a failed audit, one test at a time per person, cap checked again after the locks, request transaction writes nothing, renewal counted once, past renewal rows not counted); `tests/db/test_api_napix_admin.py` (renewed success is ok, rows survive a failed audit and an unexpected error, the check and the Connection test exclude each other); `tests/db/test_court_search.py` and `tests/db/test_api_data_load.py` (call rows survive an unexpected error; `fetch-details` makes no court call); `frontend/src/server/api.test.ts` (the two messages).

**Decisions and reasons** (full list in the design note)
- A separate session, not a savepoint or a mid-request commit: a savepoint rolls back with the request, and a mid-request commit would release the advisory locks and commit half-done work. It keeps the CLAUDE.md rule that every call is logged and failures are never lost.
- The audit row is written apart too, so the per-API interval and the per-person cap, which count those rows, see every test that made a call. ASLMS's own defects after a call give a 500, not a hidden empty summary.
- The client emits the 401 step before the repeat, rather than pairing rows in SQL, since the rows carry no link. One predicate also covers old successful-renewal rows, so no data migration.
- A try-lock, not a blocking lock, so no pooled connection is held for another person's call; transaction-scoped, so safe under PgBouncer transaction mode (row 78).
- The connectivity check shares the Connection test's lock (decision 7, kept by the owner) to close the race of two Overview calls.

**Deviations from the design note**
- `POST /admin/data-load/fetch-details` makes no NAPIX call (it only queues `dossier` rows in the `request` lane), so it is already safe and not converted; a test proves no call and no call row. The other three routes are converted.
- Inventory of request-time callers: Test now, the connectivity check and the two `_with_napix` helpers (`api/routers/cases.py`, `api/routers/data_load.py`) are converted; the queue runner and the CLI already commit apart.
- The court routes interleave the call and case writes inside the service, so `NapixRecorder` takes an optional `session_factory`; when set (only by the two `_with_napix` helpers) every `flush(session)` commits apart. `_with_napix` also calls `flush_apart` in a `finally`.
- `CHECK_LOCK` and `napix_admin.lock_check` live in `napix_admin` because `napix_api_check` imports it (import cycle otherwise).
- The seam of `test_request_transaction_writes_nothing`: `get_session` replaced through `dependency_overrides` with a copy that reads `pg_current_xact_id_if_assigned()` before the commit (NULL proves no write).
- The stray second `approved_by: (pending)` line of `docs/design/api-health-checker.md` removed; the team-approve skill wording was already changed by the owner on `main`.

**Left for later**: data health's "failed today" count and failures list still include a renewal's 401 row (outside this row); past renewal rows whose repeat failed count twice until they leave the 7-day window (no rewrite of `napix_call_log`); typed test inputs and mail and SourceTrace cards (from row 109). No live NAPIX check was made (scripted gateway only).

## 2026-10-21 — No agency names in the portal (owner decision, on `main`)

- The owner's decision: the portal, its e-mails and documents written for others name only ASLMS and the Government of Assam, never SeMT or AMTRON. The owner said this earlier too. That first instruction was not recorded and was lost when the conversation was summarised.
- Removed from:
  - the sign-in frame's footer line (`T.auth.frame.maker`, now "ASLMS · Government of Assam");
  - `README.md` and the `CLAUDE.md` heading paragraph ("Owner: Government of Assam");
  - `docs/ASLMS_Process_Workflows.md`;
  - the sign-in mockup `docs/design/ui/aslms-sign-in-templates.html`;
  - a unit test's sample e-mail address.
- Earlier entries of this log, reports and design notes are history and stay unchanged.
- Guard tests: `frontend/src/lib/branding.test.ts` (no file under `src/` or `public/` names them; the application's name) and `backend/tests/unit/test_branding.py` (no file in the `aslms` package names them).

## 2026-10-21 — The NAPIX switch also reaches the API (owner decision, on `main`)

- Until now Compose passed `NAPIX_ENABLED` only to the `worker`. The `api` therefore always ran with the switch off, and the portal's own court calls answered `napix_off`: court search, fetch from court, the data-load fetch and System health's Test now. The owner approved passing it to the `api` the same way (`NAPIX_ENABLED: ${NAPIX_ENABLED:-false}`). It is still never written as on in any file, and the default stays off.
- The rule in `docs/operations.md` section 11 is updated to say so.

## 2026-10-21 — NAPIX signature check for PDF answers; warnings throttled (on `main`, outside a cycle)

- The owner saw the worker log flooded with "napix response_token mismatch". The call log showed the cause: all 20,287 Show Order answers in 24 hours failed the signature check, while every JSON answer verified. This is the gateway quirk for PDF answers recorded on 1 Oct. The PDFs are decrypted, checked (`%PDF`) and stored as before.
- `NapixClient.signature_matches` also accepts the unquoted Base64 and the encrypted `response_str` as signed forms.
- `_warn_mismatch` warns at most once per API every 10 minutes and counts the suppressed mismatches. Every call still records `token_verified` in `napix_call_log`, so nothing is lost.
- Tests in `tests/unit/test_napix_client.py`.
- Whether the gateway's real form is one of these will show in the call log after deployment. If it is neither, the warnings stay throttled. The System health inspector (row 123) will show the check per API.
