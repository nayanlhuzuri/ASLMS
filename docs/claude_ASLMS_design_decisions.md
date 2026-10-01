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

