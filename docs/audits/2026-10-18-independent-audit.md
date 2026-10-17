# ASLMS independent audit — merged code on `main` (commit 9f2bf8a, 18 Oct 2026)

Independent, read-only audit by a separate agent (Fable, highest effort) at the owner's request, outside the team
cycle. Scope chosen by the owner: security and privacy; rules and plan conformance; data integrity and operations;
usability and go-live readiness. Nothing is built from this report without the owner's approval. Claims 1 and 4 below
were re-checked against the running system on 18 Oct 2026 (the application connects as the superuser `aslms`; 759
case-detail fetches have failed for good, 723 of them disposed cases never fetched).

Scope and method: read-only review of the plan, standard, schema, decisions log, backlog and the code on `main` in an
isolated worktree; read-only SELECTs on the dev database; the backend unit suite run from the worktree (471 passed,
ruff clean); a focused run of the database tests (121 passed; the run was then disturbed by another session using the
shared `aslms_test` database); the frontend suite not run (no `node_modules` in the audit worktree), so the
integrator's reports are taken for those.

## Executive summary

The build is of unusually good quality for its age: the visibility rule is one piece of SQL evaluated per membership
and tested on every list and detail path; notes, audit, custody history and stages are append-only at the database
level; every NAPIX call is logged and every response is kept verbatim; the sign-in flow (password, e-mailed code,
rotating refresh tokens, device records, lock-out) is careful; the portal keeps tokens in httpOnly cookies behind a
relay with CSRF and CSP protection; uploads are typed by content and scanned before storage; and every design
departure found is written in the decisions log with the owner's name on it. The team process is visibly working.

What is not ready is everything around the application: the running stack connects to PostgreSQL as the superuser
`aslms`, not the `aslms_app` role the standard and the decisions log say it uses, so the "application cannot delete
legal records" control exists on paper only; Postgres (default password), Redis (no password, holding the NAPIX bearer
token) and the API are published on every network interface; there is no TLS, no reverse proxy, no backup, no
monitoring, and migrations run automatically on every start; sign-in depends entirely on an e-mail service that today
is the Mailtrap sandbox. On the data side, a NAPIX gateway fault (HTTP 200 with an empty body, thousands of times in
bursts) leaves cases permanently without details because retries stop after five attempts and the weekly repair skips
disposed cases: 723 such cases exist in the dev database today. The dev database also holds no departments, users or
counsel codes, so recommend-and-claim, custody, notes and alerts have been exercised only by tests, never by a
department on real data; the owner's browser verification rows (53, 56, 63, 64, 67) are still open.

**Go-live verdict: not ready today; ready with conditions for a small closed-network pilot once the conditions below
are met (all are days, not weeks, of work).** Conditions: (1) deployment hardening (backlog row 16: no published
Postgres/Redis/API ports, real passwords, Redis password, TLS and a reverse proxy, backups, monitoring) and the
application connecting as `aslms_app`; (2) a government SMTP service with a verified sender, tested with a real
sign-in; (3) the NAPIX failure-recovery fix (Top 4); (4) the mapping data compiled and entered (departments,
department admins, counsel codes in the printed form, name patterns), then one department's real
claim-send-note-upload cycle checked in a browser (rows 53/56); (5) the owner's decisions on who may read private notes
and on administrator e-mail changes.

## Top 10 recommendations (ranked)

1. **The application runs as the PostgreSQL superuser, not `aslms_app`** — high (defect; standard non-conformance).
   `compose.yml` lines 53, 70, 105, 132 connect every service as `POSTGRES_USER` (the cluster superuser);
   `.env.example` says "the application connects as aslms_app" but sets `aslms:aslms`; `pg_stat_activity` shows the
   app connected as `aslms` (`rolsuper = t`), `aslms_app` unused. Grants exist (`0001_core.py` 394-400) but nothing runs
   as the role; tests rely on superuser rights. Risk: a bug or injected SQL can delete legal records, disable the
   append-only triggers or edit the audit log. Fix: point `api`, `worker`, `scheduler` at `aslms_app` (owner role only
   for `init`), real passwords, one test running an API flow under `SET ROLE aslms_app`; correct the `.env.example`
   comment. Effort small; no owner decision.
2. **Deployment exposure: database, Redis and API ports open to the network with default secrets** — critical for any
   deployment beyond the owner's machine (risk). Postgres on `0.0.0.0:5433`, Redis on `6379` without a password (it
   holds the NAPIX token), API on `8000` with `/docs` open; default passwords in `.env.example`; no TLS, proxy or per-IP
   limits; `COOKIE_SECURE` with an http localhost address. Fix: backlog row 16 before the first department signs in
   (no published ports, Redis password, reverse proxy with TLS, real `PORTAL_BASE_URL`, API docs off, per-IP throttling
   of `/api/session/*`). Effort medium; owner decision: where the pilot runs and its address.
3. **Every holder of "View all cases" reads every department's private notes and internal documents** — high (risk;
   needs an owner rule). `cases.view_all` members (super admin, State oversight, central operator, auditor) pass every
   record rule, including notes "private to the office" and internal documents (`services/visibility.py` 406-409,
   449-450, 512-513, 578-579; default matrix `access_seed.py` 145-165). The plan does not say these roles read
   departments' private noting. Fix after the owner's rule: make the State-wide pass depend on the note functions and a
   new `documents.view_internal`. Effort small-medium; owner decision yes.
4. **NAPIX gateway faults leave cases permanently without details** — high (defect). Empty HTTP-200 bodies are a
   protocol error not retried inside the call; the queue retries five times ten minutes apart then marks `failed`; the
   weekly sweep covers non-disposed cases only; nothing alerts. Dev DB: 9,740 such errors (483 in one hour on 17 Oct),
   759 failed dossier rows, 723 disposed cases never fetched, `source_failures` empty. Fix: treat an empty/non-JSON 200
   as unavailable (retry with back-off); a longer retry ladder (10 min, 1 h, 6 h, 24 h, 72 h); include every case never
   fully fetched in the weekly sweep; mirror permanent failures into `source_failures`; meanwhile "retry failed" on the
   Data collection screen. Effort small; no owner decision. Not in the backlog today.
5. **Sign-in depends entirely on one e-mail service, today a test sandbox** — high (go-live setup). A code is mailed at
   every sign-in with no bypass; Mailtrap is a testing service; SMS does not exist. Risk: a mail outage locks every
   officer out. Fix: a government SMTP relay (NIC/SDC) with a verified sender and a live check; decide on an SMS code
   or a super-admin break-glass procedure. Owner decision yes.
6. **Anyone who knows an e-mail address can lock that person out; no per-IP throttling** — medium. Ten failures in 15
   minutes lock the login per account (`services/auth.py`); nothing limits by source address; `locked` also confirms
   the address exists. Fix: per-IP throttling at the proxy, progressive delay or captcha, a neutral answer for
   unauthenticated callers. Rows 16, 33, 35.
7. **A department admin can take over a subordinate's login (e-mail change + password reset)** — medium (needs an
   owner rule). Accepted deliberately in otp-and-profile decision 13; audited and the old address notified. Options:
   e-mail changes only by the super admin or through an admin ticket; password resets only by the person's own
   e-mailed code. Owner decision yes.
8. **Audit-log IP addresses can be chosen by the browser** — medium. The web server takes the browser's own
   `X-Forwarded-For` (`frontend/src/server/api.ts` 34-39). Fix with the reverse proxy (row 44 item 3, row 16).
9. **The historical load will run for weeks, and SourceTrace material depends on it** — medium (planning). 54,179
   cases, 300,212 order references, 268,762 order PDFs still pending, ~16-22k calls a day; about 5.5 orders per case
   against the plan's 1.4. Tell departments what is complete at go-live; consider the `cases_with_orders` order for the
   live period. Owner decision: what "complete" means at go-live.
10. **The system has never been exercised with real departments, users or codes** — high for go-live (gap). Dev DB: 1
   office, 1 user, 0 counsel codes, 0 recommendations, 0 ownership, 0 alerts; browser rows 53, 56, 63, 64, 67 open;
   README stale; no operations runbook. Fix: a setup session with one department (Education): create it and its admin,
   map the printed codes, enter officer names, `aslms rescore`, walk claim -> allot -> send -> note -> upload -> alert in
   the browser, record the result; write a short runbook. Owner decision: which department pilots.

## Further findings by area

### 1. Security and privacy
- First passwords are typed by the administrator and handed over out of band; an invitation e-mail with a
  set-password link would remove the shared secret. Owner decision on wording.
- The super admin may claim, dismiss, allot and decide transfers for any department (audited); the owner may prefer a
  purely technical super admin. Owner decision.
- Verified good: 30-minute access tokens checked against `password_changed_at` / `is_active`; sound refresh rotation
  and reuse detection; no CORS; CSRF header plus Origin; HttpOnly SameSite=Lax Secure cookies; CSP with nonces; the
  relay refuses `/auth/*`, `/docs` and token routes and never forwards cookies; open-redirect guarded; secrets as
  `SecretStr`; `.env` git-ignored; `web` gets no `env_file`; httpx request logging silenced.
- Verified good, uploads: size middleware plus count, type by bytes with extension agreement and macro refusal, ClamAV
  before any write (fail-closed 503), duplicate refusal, refusals audited.
- Verified good, audit completeness: `write_audit` in 25 service modules covering every significant action; note text
  and remarks stored as digests; reading not audited (owner's decision).

### 2. Rules and plan conformance
- Conform: recommend-and-claim (no automatic assignment, no return to the pool, editable bands by owner decision);
  SourceTrace limits enforced three times including database CHECKs; notes append-only with supersedes; NAPIX only
  through the integration layer with every call and response stored; `NAPIX_ENABLED` default false; no fabricated
  identifiers; every NAPIX field kept (coverage test).
- Dev data: 931 provisional rows (926 with a CNR awaiting a dossier, 5 without); 46 groups of same type/number/year
  with different CNRs against 26 court-duplicate links — worth a look on the Duplicates screen.
- Plan departures recorded as owner decisions: no data migration; PDF parser primary; editable thresholds; sending the
  file instead of requests; code at every sign-in; next dates option B; discovery from 2025; no re-fetch prompts then
  narrowed; filings on provisional cases wait for the CNR.
- Departures not clearly recorded: (a) the application role (Top 1) contradicts a logged decision; (b) PgBouncer,
  monitoring and backups were to be in the pilot Compose (decision of 1 Oct; plan §2.2, §8.2) and none exist;
  (c) the GHC website cross-check is only fallback PDFs and `causelist_reconciliations` is never written;
  (d) compliance alerts for directions in orders exist only for scrutiny dates. Suggest one decisions-log entry
  closing these four.

### 3. Data integrity and operations
- DB_STANDARD conformance is good (UUID v7, `ref_no`, `ref_*`, RESTRICT keys, class comments, triggers, roles and
  grants, migration guards); only the role usage is non-conforming.
- Migrations run on every `docker compose up` with no backup step; take a `pg_dump` first or make migration explicit
  (row 16).
- No backups anywhere; `archive_mode` off; the document store is a bind mount. Go-live blocker (row 16).
- Postgres on container defaults (128 MB `shared_buffers`) for a 1.8 GB database that will double; tune for the host.
- Growth: `case_snapshots` 219 MB, `events` 175 MB, `napix_responses` 168 MB, `napix_call_log` ~2.7M rows a year with
  no pruning; retention (DB_STANDARD §6) still "owner to confirm".
- `job_runs` has 8 `queue-run` rows stuck `running` after worker restarts; mark them failed at start-up.
- Performance at 100k cases: fine (indexes, pool count 28 ms, word search 3.5 ms, statement timeouts on reports).
- All jobs on one Celery worker with concurrency 1: fine for a pilot, but a slow extraction batch delays e-mail.
- ClamAV needs outbound internet for signatures; in the SDC allow egress or provide a mirror (row 24).
- Test suite: all database tests share one `aslms_test` database, so two sessions cannot test at once; for CI use a
  database per run (row 15).
- Coverage gaps that matter: nothing runs as `aslms_app`; no test of the retry ladder under a sustained gateway fault;
  no end-to-end browser test.

### 4. Usability and go-live readiness
- Genuinely good: clear shell; the right cards on the case page; the note composer says draft or permanent before
  writing and makes visibility a choice; uploads pre-checked and every refusal explained; plain-English errors;
  buttons only when the server allows the action.
- Will confuse or block: no Case Assistant (row 14) and no OCR (row 23) — scanned orders show nothing in the reading
  column (say "scanned, not read"); the next-dates confirmation queue needs a named owner in each department (state
  "the custody holder confirms" in the guide); the "I can no longer open the case I just sent" notice should explain
  when the case becomes visible again; no user guide or in-portal help, README stale; mobile numbers unverified and no
  SMS alerts.
- Owner set-up still needed: real `.env` secrets; a mail service; the super admin's first sign-in; departments,
  directorates, designations; one admin per department; counsel codes (printed form), keywords, name patterns; scoring
  if the defaults change; the data-load order; the 20-reading hand check and load counts; the browser checklists.

## Backlog rows to move up
- Row 16 (deployment, Redis hardening, backups, PgBouncer, monitoring) to the top, ahead of rows 14 and 15.
- Rows 33 / 35 (auth retention, per-IP throttling, lock-out) with row 16.
- Row 44 item 3 (trusted hop for `X-Forwarded-For`) with row 16.
- Rows 53 and 56 (owner's browser checklists) before any department sees the portal.
- Row 27's live Mailtrap check becomes a live government SMTP check.
- New high row: the NAPIX retry and repair fix (Top 4).
- Row 24 (ClamAV signatures, proxy body limit) with row 16.
- Row 70 stays parked; add `case_snapshots` retention to it.
- Row 14 (Case Assistant) waits for the SourceTrace documentation and should not precede row 16 and the pilot set-up.

## What is done well (do not change)
- One visibility rule in SQL, per membership, reused everywhere, with tests against `can_view_case` /
  `can_view_document`.
- Append-only legal records enforced in the database; lifecycle by state; `ref_no` everywhere; verbatim NAPIX storage
  with the coverage test.
- The sign-in design (row locks, constant-time checks, neutral answers, rotating refresh tokens with reuse detection).
- The portal's backend-for-frontend (no token in the browser, CSRF plus Origin, CSP, sandboxed PDFs, server-decided
  buttons, plain-English messages, filters in the URL).
- Operations design (resumable queue with lanes, detected quota window, every call logged with the person behind it,
  console and health screens, idempotent alerts, the daily dedupe sweep).
- The team process (owner-approved designs, deviations written back, decisions log, separate tester, cycle reports).

## Owner decisions requested
1. Who may read notes and documents "private to the office" across departments: State oversight, auditor, central
   operator — each yes/no (Top 3).
2. Whether department admins may change a subordinate's e-mail and set passwords directly, or only through a ticket or
   the person's own reset (Top 7).
3. Whether the super admin may act on cases for departments or is purely a system administrator.
4. Where the pilot runs, the portal's real address, the mail service, and whether an SMS code or break-glass sign-in is
   wanted when mail fails (Top 2, Top 5).
5. What "complete" means at go-live given the weeks-long order-PDF backlog (Top 9).
6. Which department pilots first and who confirms next dates in it (Top 10).
7. Retention of `case_snapshots`, `napix_responses`, `napix_call_log` and OTP / refresh rows (DB_STANDARD §6).
8. OCR for scanned orders and filings (row 23): local engine, SourceTrace, or not in Phase 1.
9. A decisions-log entry closing the four unrecorded departures.
