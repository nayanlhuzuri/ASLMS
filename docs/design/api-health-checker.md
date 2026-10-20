# Design: System health — court API and ASLMS service checker for the super admin

```
slug: api-health-checker
status: approved
approved_by: owner on 2026-10-20
author: architect
date: 2026-10-20
approved_by: (pending)
```

## Context
Backlog row 109. The owner asked on 20 Oct 2026 for a screen in the super admin's login of the Assam State Litigation
Management System (ASLMS). On it, clicking a particular API gives a response that shows whether it is healthy. It
covers every NAPIX High Court API and ASLMS's own services, with graphics for a good experience.

Five owner decisions are fixed and not reopened here:
1. **Scope.** Every NAPIX High Court API the integration layer uses, plus ASLMS's own services: the API, PostgreSQL
   (through PgBouncer and direct), Redis, the queue worker and the scheduler (liveness), ClamAV, the backup job (last
   success), the document store (writable) and the web portal. Mail and SourceTrace are out of scope.
2. **Live call on click.** Each NAPIX card shows its last result from the call log at once, without a call. "Test
   now" makes ONE real call through the integration layer and shows the status, the response time and a readable
   summary. The ASLMS service checks are cheap and may run when the screen opens and on click.
3. **A grantable function** for the super admin, following `admin.data_load`, `admin.sourcetrace` and
   `admin.scoring`.
4. **Graphics.** An overall status, per-API cards in status colours, response time, a small latency and success
   history from the call log, success rates over 24 h and 7 days, and grouped sections. All of it follows the
   approved redesign: `docs/design/portal-ui-redesign.md` and the mock-up `docs/design/ui/aslms-ui-direction-v4.html`.
5. **The friendly-UI rule applies.** Ordinary users never see call counts or quotas. This screen is an
   administrator's tool, and the cost of a test may be shown on it (decision 14).

**Plan.** Plan §3 (Table 3) names "Prometheus and Grafana for system health; Flower for background jobs". Plan §5.10
lists "Data collection health" among the reports. This screen is an **addition the owner asked for, not in the plan**.
It complements Prometheus and Grafana (row 77) and the data-health screen (row 10) and replaces neither. Alerting
stays in Prometheus and Alertmanager. The screen alerts nobody and keeps no history of its own. Flagged for the owner;
it is not a deviation from anything the plan says.

**Already in place and reused (decision 16 lists exactly what is reused):**
- The connectivity check `POST /admin/napix/health/check` (`services/napix_admin.py`: one Overview call, the
  `check_guard` refusals `napix_off`, `check_too_soon` and `napix_budget`, the `NapixRecorder` carrying the caller's
  id, the audit row `napix.health_checked`).
- `GET /admin/napix/health` and `/admin/data-health`. `data_health.window_block` serves the detected quota window.
- `services/napix_window.py`: `current`, `retry_after`, `user_id_of`.
- `services/ops_metrics.py` (`aslms ops metrics`): the worker liveness rule of pre-pilot-hardening decision 4,
  `parse_clamav_version`, `probe_http`, and the backup reading from `job_runs`.
- `services/store_check.write_probe`, `services/scanner.ClamdScanner.version`, `services/job_repair.SCHEDULER_JOBS`,
  `services/db_guard.script_facts`.
- The scripted gateway (`tests/unit/conftest.Gateway`, `tests/db/conftest.router`) and the
  `app.state.napix_factory` seam.
- The Prometheus alert thresholds in `infra/prometheus/rules.yml`. The service checks use the same numbers
  (decision 10), so the screen and the alerts agree.

**Not covered:**
- Mail (Mailtrap or SMTP) and SourceTrace (owner decision 1).
- The three NAPIX APIs in `hc.API` that the layer does not use and that notes §7 marks "not needed yet":
  `advocate_bar_reg`, `act_details` and `neutral_citation`.
- The alternate CNR path `cnr_alt` (`/hc-cnr-api/cnr`, a known gateway 404 per notes §7).
- A history store for ASLMS services: Prometheus keeps that.
- Typed test inputs (decision 6).
- A "test all court APIs" button (decision 7).
- The proxy probe: the `api` container cannot reach the proxy (it is on the `edge` network only). The screen loading
  in the browser is itself proof that the proxy works, and the ops exporter probes it for Prometheus.

## Decisions

1. **One function, `admin.service_health`** ("System health": "See whether the court APIs and ASLMS's services are
   working, and test a court API with one live call"). It is a `ref_permission` row seeded by `aslms seed`, with no
   migration: `admin.sourcetrace` and `admin.data_load` came the same way (migration 0011's docstring says so).
   - `DEFAULT_MATRIX` gives it to no user type.
   - The super admin always holds every function, so the screen is the super admin's from the first seed. The super
     admin can grant it to a person (a `user_permissions` override) or to a type (the type matrix) under the existing
     delegation rule.
   - Every endpoint of this item needs it, reading included. The data-health readers (`reports.state`,
     `admin.napix_refetch`, `admin.masters_sync`) do not get this screen automatically.

   Alternatives: reuse `admin.napix_refetch` (it would hand live court tests to every Central operator, against owner
   decision 3); super-admin-only with no function (owner decision 3 asks for a grantable function).

2. **Where it lives in the portal: a new sidebar entry "System health" (`/system`) in the Settings group**, after
   Data collection and before Administration. It shows with `admin.service_health`. The screen is built directly on
   the round-1 kit and the Dashboard template (redesign decisions 11-20 and 26), so round 5 (row 105) does not need
   to touch it.

   Alternatives:
   - A sixth tab of Data collection: "Data health" and "System health" side by side are easily confused, and the
     Data collection entry is gated by the data readers.
   - A tab of Administration: Administration is people, offices and mapping.

3. **The 17 court API cards, in four groups.** Each card is identified by its `hc.API` key, and the call log stores
   the path, e.g. `hc-cnr-api/CNR`:

   | Group | Card (plain name) | `hc.API` key → method |
   |---|---|---|
   | Connection and masters | Connection check | `overview` → `overview()` |
   | | High Courts list | `state` → `state_master()` |
   | | Districts list | `district` → `district_master()` |
   | | Benches list | `bench_master` → `bench_master()` |
   | | Case types list | `case_type` → `case_type_master()` |
   | | Acts list | `act` → `act_master()` |
   | Cause lists | Benches sitting on a day | `causelist_bench` → `causelist_benches(date)` |
   | | Lists of a bench | `causelist_details` → `causelist_details(date, bench_id)` |
   | | Cause list PDF | `show_causelist` → `show_causelist(ref)` |
   | Case details | Case details by CNR | `cnr` → `case_by_cnr(cnr, fallback=False)` |
   | | Case status | `current_status` → `current_status([cnr])` |
   | | Order PDF | `order` → `show_order(cnr, order_no, order_date)` |
   | | Hearing business | `show_business` → `show_business(cnr, business_date)` |
   | Searches | Search by case number | `case_search` → `search_case_number(type, no, year)` |
   | | Search by filing number | `filing` → `search_filing(type, fil_no, fil_year)` |
   | | Search by party name | `party_name` → `search_party(name, year, pend_disp)` |
   | | Search by advocate name | `advocate_name` → `search_advocate(name, year, pend_disp)` |

   The catalogue is one constant, `CATALOGUE`, in `services/system_health.py`. Each entry holds:
   - the key and the plain label key;
   - the group and the HTTP method (GET; POST for Current Status);
   - the sample chooser (decision 5) and the summariser (decision 9).

   The technical name and path appear only under "Technical details" in the card's panel. The plain name is what the
   screen shows (owner decision 4: no jargon where a plain word works).

   **One change in the integration layer:** `NapixHighCourt.case_by_cnr` gains `fallback: bool = True`. The test
   passes `False`, so a gateway 404 on `/CNR` is reported as it is and the known-404 `/cnr` path is never called.
   One click then means one call. The default keeps today's behaviour for every other caller.

4. **A card's "last result" comes from `napix_call_log`, with no call made.** The window is the last 7 days (IST).
   - **Answered** is a row with `ok = true`, or with `error_family` `NapixNotFound` (600 / 628) or `NapixInputError`
     (another 6xx): the court replied, so the API is up. **Failed** is every other row: `NapixUnavailable`,
     `NapixEmptyResponse`, `NapixGatewayError`, `NapixAuthError`, `NapixProtocolError`, or a transport error.
     Alternative: use `ok` alone (a valid "record not found" would then read as an outage).
   - **The status of a card** comes from one pure function, `card_status(last, h24)`:
     - `unknown`, "No recent calls": no call in 7 days.
     - `down`, "Failing": the last call failed, and either the 24 h answered rate is below 50 % over at least 3 calls,
       or the last 3 calls all failed.
     - `warn`, "Unsteady": the last call failed, or the 24 h answered rate is below 90 % over at least 5 calls, or the
       24 h p95 is above 20 s (half the 40 s timeout).
     - `ok`, "Working": otherwise.

     A failed test is a call-log row like any other, so the card changes at once.
   - **Figures per card:**
     - the last call: time, answered or failed, ms, HTTP and NAPIX status, plain reason, and who made it (background
       work or a person, never a name);
     - 24 h and 7 d: calls, answered, failed, answered rate;
     - 24 h median and p95 response time;
     - 24 hourly IST buckets (answered, failed, average ms) for the bar chart;
     - in the detail panel only: 7 daily buckets and the last 10 calls.

     The figures come from two grouped queries over `called_at >= now() - 7 days`, which the existing
     `ix_napix_call_log_called_at` serves: one grouped by (api, IST hour) and one with `percentile_cont` over 24 h.
     They run under `SET LOCAL statement_timeout` = `REPORT_STATEMENT_TIMEOUT_SECONDS`.
   - **No migration.** A week is at most about 170 k rows at the gateway's 1,000 calls an hour. Verification step 4
     times the queries on the dev database, which holds the running historical load. If the summary takes over 2 s
     there, the developer stops and asks; an `(api, called_at)` index migration is not added silently.
     Alternative: an `(api, called_at)` index now (a migration for a cost not yet measured).
   - The `lane` and `job_run_id` columns are not shown. Calls without a user (runner, scheduler) read "background
     work". Calls with a user read "a person", and a test made by the caller reads "your test".

5. **The test input comes only from data ASLMS already holds. Nothing is invented** (CLAUDE.md: never fabricate
   identifiers). Each chooser is one query with `LIMIT 1`, deterministic (newest first, ties broken by `id`), and
   ignores merged cases (`merged_into_case_id IS NULL`). The configured codes `NAPIX_EST_CODE` (GAHC01) and
   `NAPIX_STATE_CODE` (18) are configuration, not invented identifiers. "The reference case" below means the non-merged
   case with a CNR and the latest `last_full_refresh_at`.

   | Card | Input and where it comes from | When nothing is held |
   |---|---|---|
   | Connection check, High Courts list, Acts list | none | always testable |
   | Districts list, Benches list | `state_code` = `NAPIX_STATE_CODE` | always testable |
   | Case types list | `est_code` = `NAPIX_EST_CODE` | always testable |
   | Benches sitting on a day | `list_date` of the latest `causelists` row with `source = napix` | today (IST): a date is not an identifier, and "no benches that day" is still an answer |
   | Lists of a bench | (`list_date`, `bench_id`) of the latest `causelists` row with `source = napix` | not testable: "No cause list from the court is held yet" |
   | Cause list PDF | (`bench_id`, `napix_causelist_id`, `list_date`) of the latest napix `causelists` row with a `napix_causelist_id` and a stored `document_id` | not testable: "No stored cause-list PDF yet" |
   | Case details by CNR, Case status | the reference case's CNR (Case status sends a batch of one) | not testable: "No case has been fetched from the court yet" |
   | Order PDF | (`cnr`, `order_no`, `order_date`) of the latest `orders` row with a stored `document_id` whose case has a CNR | not testable: "No stored order PDF yet" |
   | Hearing business | (`cnr`, `business_date`) of the latest `case_hearings` row with `business_date` on or before today (IST) whose case has a CNR | not testable: "No hearing with a business date is held yet" |
   | Search by case number | `case_types.case_type_code`, `reg_no` and `reg_year` of the newest fetched case that has all three | not testable: "No fetched case has a registration number yet" |
   | Search by filing number | `filing_no`, `filing_year` and the filing case type's code (`filing_case_type_id`, else `case_type_id`) of the newest fetched case that has them | not testable: "No fetched case has a filing number yet" |
   | Search by party name | (a) the active `discovery_terms.term` with the latest `last_searched_at`, with the current IST year and `pend_disp = P`, the weekly discovery sweep's own call; else (b) the first current respondent (`case_parties`, `role` respondent, `party_no` 1, `is_current`) of the newest fetched pending case whose respondent name passes these rules: matching `court_search.PARTY_NAME_RE`, not masked (`X` only), 3 to 200 characters, with that case's `reg_year` and `pend_disp` from its status | not testable: "No discovery term or suitable party name is held yet" |
   | Search by advocate name | `case_advocates.name_as_listed` (current, 3 to 99 characters, `PARTY_NAME_RE`, not masked) of the newest fetched case with a `reg_year`, with that year and `pend_disp` P or D from the case's status | not testable: "No advocate name is held yet" |

   - **Two points on the GET.** The card list only asks whether a sample exists (cheap `EXISTS` queries), so it can
     disable the button with the reason. The detail endpoint and the POST pick the actual sample. The POST always
     picks again on the server; the browser never sends an input.
   - **What the screen shows of the input.** The non-personal values: dates, bench id, list id, codes, years, order
     number, `pend_disp`, and a discovery term (a rule text, not case data).
     - A CNR or case number is shown only when the caller may see that case (`visibility.case_visible`). Otherwise
       it reads "a case held by ASLMS". The server enforces visibility for every query, including this label.
     - Party and advocate names are never shown. They read "a party of WP(C) 6780/2025" or "an advocate of …",
       subject to the same visibility rule, else "of a case held by ASLMS".

6. **No typed input in this item.** The owner may only test with the held sample. A free CNR, number or name would
   make this screen an unguarded court search: none of court search's storing, its per-user limit or its rule that
   found cases are kept. It would also invite typed identifiers here. The Search page (`cases.search_court`) already
   does this properly. If the owner wants it later, it is a follow-up row with its own guard.
   Alternative: allow typed input under the same rate limits (rejected for the reasons above).

7. **One court call per click, with no batch and no retry.**
   - Each "Test now" makes one HTTP call to one API, on a **fresh client** from `deps.napix_client(request)`. The
     service sets `client.max_attempts = 1` and `client.timeout = HEALTH_TEST_TIMEOUT_SECONDS` (30 s) before
     `async with client`.
     - There is no back-off retry: a test reports what happened, and a retry would spend more calls on the same
       fault.
     - A fresh client means a fresh local `RateLimiter`, so it never sleeps on another process's headers.
     - The only possible second attempt is the client's own one-time token renewal after an HTTP 401. Both attempts
       are logged and counted, and `attempts` in the result says so.
   - There is no "Test all court APIs": that would be 17 calls in one click. The ASLMS services have one "Check
     again" for all of them, because they cost nothing outside ASLMS.

8. **The guard, before any call and writing nothing.** The refusals are checked in this order:
   1. 404 `not_found`: an unknown API key.
   2. 409 `napix_off`: the switch, `settings.napix_configured` as this API process sees it. The button is disabled
      with the reason "Court calls are switched off on this server (NAPIX_ENABLED is false)". The switch is never set
      in code or tests; tests patch `Settings.napix_configured` as `test_api_napix_admin.py` does.
   3. 409 `no_sample`: decision 5, with the reason text.
   4. 429 `test_too_soon`, with `retry_after`: a test of this API ran less than `HEALTH_TEST_API_MIN_SECONDS` (60)
      ago, by anyone. This is counted from `audit_log` rows `napix.api_tested` with `after->>'api'` equal to the key,
      served by `ix_audit_log_created_at`. For the Connection check, the interval is the larger of this and
      `NAPIX_HEALTH_CHECK_MIN_SECONDS`, measured from `napix_admin.last_check_at`. A test of the Connection check and
      the data-health connectivity check are the same Overview call, so each counts against the other.
   5. 429 `test_limit`, with `retry_after`: the caller has made `HEALTH_TEST_PER_USER_HOUR` (30) tests in the last
      hour (`ix_audit_log_actor_created`).
   6. 429 `napix_budget`, with `retry_after` to the expected reset: the detected window's remaining calls are below
      `NAPIX_SEARCH_FLOOR` (50), the floor court search and the connectivity check already use. While the remaining
      count is unknown (`reset_due`, `unknown`), the test is allowed: the next call will tell, as the other guards
      treat it. The screen then says "The court's hourly allowance is nearly used up; tests resume after about
      14:34".
   7. 409 `test_running`: `pg_try_advisory_xact_lock(hashtextextended('napix-api-test:<key>', 0))` fails because
      another test of the same API is in flight. The lock is transaction-scoped, so it is safe under PgBouncer's
      transaction mode. The session-feature scan of row 78 allows it; `case_dedupe.lock_number` uses the same form.

   Together these mean a click storm cannot drain the quota:
   - at most one test per API per minute (17 a minute in all);
   - at most 30 tests per person per hour;
   - never below the floor kept for people's searches.

   All three numbers are settings (decision 17).

9. **The answer is summarised, never shown verbatim.** The response model is built from a whitelist of computed
   facts. `NapixResult.data`, `pdf`, `raw_text`, `params`, the error text and any name are never put in it.
   - **Lists** (masters, benches, lists of a bench, searches): the row count and the field names of the rows (sorted,
     at most 40).
     - Masters add "ASLMS holds n": the count in `states`, `districts` (that state), `benches`, `case_types` (that
       court) or `acts`.
     - Benches sitting on a day adds the number ASLMS holds for that date. Lists of a bench adds the distinct
       `cause_list_type` values (trimmed, court-public list names such as LAWAZIMA).
     - Searches add the distinct valid CNRs and how many of them ASLMS holds. Search by case number and Search by
       filing number add "the source case is among the rows: yes or no".
   - **Records** (Connection check, Case details by CNR, Case status, Hearing business): the number of top-level
     fields and their names.
     - Connection check adds the `version` value.
     - Case details by CNR adds: the CNR in the answer equals the one asked (yes or no), the case status (pending or
       disposed), whether a next hearing date is present, and the counts of orders and hearings in the answer.
     - Case status adds the blocks returned and whether `cino` matches.
     - Hearing business adds whether `business_date` matches and whether business text is present (not the text).
   - **PDFs** (Cause list PDF, Order PDF): size in KB, page count (PyMuPDF, already pinned for text extraction; left
     out if the file cannot be opened), and "same as the stored copy: yes or no". "Same" compares the SHA-256 with
     the stored `documents.sha256`. The bytes are discarded.
   - **Every outcome** carries: `ok`, `answered`, the plain reason, HTTP status, NAPIX status, error family,
     `duration_ms` (summed over attempts), `attempts`, `called_at` (IST), `token_verified`, and `remaining` (calls
     left in the window after the call, from `recorder.last_remaining`).

   The decrypted payload never contains the bearer token, the client secret, the auth key or `dept_id`. Those travel
   in headers, Basic auth and the query envelope, never in `data`. Because the model is a whitelist, a payload field
   cannot leak by accident. A test asserts that neither the scripted client secret, nor the access token, nor any
   party or advocate name from the scripted answer appears in the response or in the audit row.
   Alternative: show a redacted raw payload (redaction by field name is fragile, and a party search answer is a list
   of personal names).

10. **The ten ASLMS service checks.** They run in parallel threads, each with its own timeout of
    `OPS_PROBE_TIMEOUT_SECONDS` (5 s), so the whole check answers within about 6 s. Thresholds are the Prometheus
    rules' numbers. Each check returns a status (`ok` / `warn` / `down` / `unknown`), a one-line headline, a few
    labelled facts and `duration_ms`.

    | Card | How it is checked | Down (red) | Unsteady (amber) |
    |---|---|---|---|
    | ASLMS API | the request is being served; facts: version (`aslms.__version__`), process start and uptime | — (it answered) | — |
    | Database through the pool | `SELECT 1` timed on the request's session; then server version, `pg_database_size`, connections (`count(*) FROM pg_stat_activity` against `max_connections`), and the stored Alembic revision against the code head (`db_guard.script_facts`). If the session's host:port (from `DATABASE_URL_SYNC`) is not `HEALTH_POOL_ADDRESS` (`pgbouncer:6432`), the card reads "The API connects to the database directly on this server" | the query fails | connections above 80 % (`PostgresConnectionsHigh`); revision not at head ("The database needs an upgrade") |
    | Database server (direct) | a credential-free protocol probe of `HEALTH_POSTGRES_DIRECT_HOST:PORT` (`postgres:5432`): the 8-byte SSLRequest and the server's one-byte `S` / `N` answer, which is what `pg_isready` establishes. No second login path for the API and no extra secret. When the pool card is down and this one is up, the screen says "The database answers; the pool (PgBouncer) does not" | no answer | pool card up but this probe fails (a configuration mismatch, shown as such) |
    | Redis | `PING` timed, `INFO server` (version), `INFO memory` (used against `maxmemory`) through `REDIS_URL`, which is never printed | no answer | memory above 90 % of `maxmemory` |
    | Queue worker | liveness = the later of the latest `queue-run` start and the latest claimed `fetch_queue` row (`search_rows` excepted): the rule of pre-pilot-hardening decision 4, moved into `ops_metrics.worker_alive_at(session)` and used by both the exporter and this check. Facts: the latest pass (rows, end, and its `counters.stopped` up to 120 characters when the pass did not fail; a failed pass reads "The latest pass failed", with no traceback), runnable rows waiting | older than 2 h (`WorkerStalled`) | older than 70 min (a worker sleeping until the window's reset wakes within about 62 min) |
    | Scheduler | the latest `job_runs` start among `job_repair.SCHEDULER_JOBS` (`notifications_send` runs every 2 min); facts: failed scheduler jobs in the last 24 h | older than 30 min (`JobLate`) | older than 10 min |
    | Virus scanner | `ClamdScanner.version()` and `ops_metrics.parse_clamav_version` | no answer (uploads then answer 503) | signatures older than 3 days (`ClamAVSignaturesOld`) |
    | Backups | `job_runs` `backup` and `restore_check`, the latest succeeded or partial run of each. The API has no `BACKUP_DIR` mount; the backup service writes a `job_runs` row per run. Facts: last backup, expected next (interval `BACKUP_INTERVAL_HOURS`), last restore check | never, or older than 13 h (`BackupMissing`); restore check older than 8 days (`RestoreCheckMissing`) | older than the interval plus 1 h |
    | Document store | `store_check.write_probe(STORAGE_DIR)` on the root only (create and remove one probe file); `shutil.disk_usage`: free space | the probe fails ("ASLMS cannot save documents") | under 15 % or 10 GB free (`DiskLow`) |
    | Web portal | `ops_metrics.probe_http(OPS_PROBE_WEB_URL)` (`http://web:3000/api/health`; the `api` container shares the `portal` network with `web`), timed | no 2xx | slower than 2 s |

    - **The overall status is computed on the server.** Each section has a count ("Court connections: 15 of 17
      working"; "ASLMS services: 10 of 10 working"). The overall line is the worst status across both sections, with
      these rules:
      - `unknown` and switched-off cards never count as down.
      - A court card counts at most as `warn` in the overall line, because the court's service is outside ASLMS.
        Its own card still shows red.
    - **No cache.** Each check is cheap. The button is busy while the checks run, and the proxy's per-address
      throttle bounds reloads.
    - **The service checks are not audited.** They read, plus one temporary probe file, like reading the data-health
      screen. Alternative: audit each "Check again" (noise in the log for a read).

11. **The test runs synchronously in the API request, not through the `request` lane.**
    - The owner asked to click and get a response. A queued item waits for the worker's next pass, behind a running
      load item. It may sleep through a window wait of up to an hour, and its timing would include the queue.
    - The existing connectivity check is synchronous for the same reason.
    - The cost is one API thread held for at most `HEALTH_TEST_TIMEOUT_SECONDS` plus the token request, with the
      transaction open, as `napix_admin.health_check` already does. The per-API lock bounds concurrent tests to 17,
      and in practice to one administrator. The relay timeout (120 s) is well above.

    Alternative: enqueue in the `request` lane and poll (latency of minutes, more moving parts, and a response time
    that is not the API's).

12. **A test writes no case data.** It writes exactly:
    - one `napix_call_log` row per attempt (CLAUDE.md: every call logged), with `user_id` = the caller (napix-window
      decision 9), `lane` NULL and `job_run_id` NULL;
    - one `napix_responses` row (or a `last_seen_at` bump) for a JSON answer, through `NapixRecorder.flush`.
      CLAUDE.md requires every response to be kept verbatim. This is the raw store, not case data;
    - one `audit_log` row.

    Nothing is applied: no `cases`, `case_parties`, `case_advocates`, `case_hearings`, `orders`, `documents`,
    `causelists`, master rows, `fetch_queue` rows, events or alerts. Masters change only through masters sync, and
    cases only through the queue or court search. A PDF answer is hashed and discarded; the documents of both PDF
    samples are already stored (decision 5). A test proves the row counts of those tables are unchanged.

13. **Audit: one row per test that made a call**, whether it answered or failed. The action is `napix.api_tested`,
    with `entity_type` `napix` and `entity_id` NULL. The actor is the caller's membership holding
    `admin.service_health` (the super admin's first; `napix_admin.acting_member`).
    - `after` holds: `api` (the key), `path`, `ok`, `answered`, `http_status`, `napix_status`, `error_family`,
      `duration_ms`, `attempts`, `remaining`, `sample` (non-personal values plus the source case's `ref_no` when
      there is one), and `summary` (the decision 9 facts).
    - `case_id` is not set: a health test is not case work, and the case's trail stays about the case. The `ref_no`
      in `after` keeps the link for an auditor.
    - A refused test writes nothing, as `check_guard`. These audit rows are what the per-API and per-user limits
      count.

14. **The friendly-UI rule: what this screen may show.** It shows only to holders of `admin.service_health`, an
    administrator's function, so it may show:
    - the cost on the button ("Test now · 1 court call");
    - the window's remaining calls ("Calls left this hour: 812, resets about 14:34");
    - call counts per API.

    No other screen changes, and no ordinary user sees any of these numbers. People's names never appear: calls are
    "background work", "a person" or "your test".

15. **The screen: graphics on the Dashboard template, plain words, motion with a reduced-motion fallback.** The
    layout follows the v4 mock-up's tokens, kit and alignment rule.

    **Page header.** Title "System health", subtitle "Court connections and ASLMS services · updated 14:32". It has
    one primary action, "Check services again", which re-runs the ten service checks; there is one primary per screen
    (redesign decision 16).

    **Overview band** (a Card):
    - A large status ring: an SVG donut of the court cards' 24 h answered rate, with the words inside ("98 %
      answered").
    - The overall sentence: "Everything is working" / "2 need attention" / "1 is not working".
    - Four `Kpi`s, count-up: "Court calls answered (24 h)", "Typical court response (median, 24 h)", "Calls left this
      hour", "ASLMS services working (n of 10)".
    - When the switch is off, a `Notice`: "Court calls are switched off on this server. The cards show the last
      results; tests are not possible."

    **Court connections (NAPIX)**, in four sub-headed groups (decision 3). The cards sit in a grid: three per row
    from 1100 px, two on tablets, one on phones. Each card has:
    - a header row: the status badge in a `Lead` (96 px, so every name starts at the same place: the alignment rule)
      and the plain name;
    - a muted line: "Last call 14:31 · 840 ms" or "No call in the last 7 days";
    - `SparkBars`: 24 hourly bars, answered in green and failed stacked in red. Its accessible name reads "Last 24
      hours: 118 answered, 2 failed";
    - two small figures: "24 h 98 %" and "7 days 97 %";
    - "Test now · 1 court call", a secondary button of size `sm`. It is disabled, with the reason as its description,
      when the switch is off, no sample is held, or the next test is not yet allowed ("Next test possible in 40 s").

    **The card's panel.** Clicking the card body, or Enter on it, opens a `SidePanel` (full screen on phones). Its
    address is in the query string (`?api=cnr`), so Back closes it. "Test now" opens the same panel with the test
    running. The panel holds:
    - the status and the last call;
    - "The test will use": the sample label of decision 5;
    - the test area:
      - "Testing… (up to 30 s)" with a pulsing status dot while the call runs;
      - then the result: a large status word, the response time against a bar marking the 24 h median, the summary as
        a `KvList`, the attempts and the calls left;
    - a 7-day `DataTable`, one row per day (calls, answered, failed, average ms), which is also the screen-reader
      alternative to the bars;
    - the last 10 calls (time, outcome, ms, statuses, plain reason, who);
    - a `Collapsible` "Technical details": API name, path, method, the input field names.

    **ASLMS services.** A list of `ListRow`s: the status badge in a `Lead`, the plain name, the headline ("Answered in
    3 ms", "Last backup 2 h ago · next by 18:30", "Signatures from 19 Oct"), and the ms at the right. A row expands
    (`Collapsible`) to its facts.

    **Refresh.** The NAPIX summary is read again every 60 s while the page is visible, and after each test. The
    service checks run when the page opens, on "Check services again" and on window focus.

    **Motion** (redesign decision 13):
    - bars grow from the baseline (`--slow`, a 10 ms stagger);
    - the ring sweeps in 700 ms, like `Meter`;
    - the testing dot pulses;
    - the panel slides;
    - Kpis count up.

    Under `prefers-reduced-motion: reduce`, everything shows in its final state at once.

    **Colour** is never the only signal: every status has its word. Labels come from `messages.ts` (`T.system`).
    **New kit pieces**, inline SVG with no chart library (CSP `style-src 'self' 'unsafe-inline'` permits the inline
    widths `Meter` already uses): `SparkBars`, `RateRing` and `StatusDot`, in `components/ui/charts.tsx`.

16. **Reuse, not duplication.**
    - The existing endpoints stay as they are. `/admin/napix/health`, `/admin/napix/health/check`,
      `/admin/data-health` and `/admin/napix/calls` are unchanged.
    - The new service reuses: `data_health.window_block`, `napix_window.current` / `user_id_of`, `NapixRecorder`,
      `napix_admin.acting_member` and `last_check_at`, `ops_metrics.parse_clamav_version` / `probe_http`, the new
      shared `ops_metrics.worker_alive_at`, `store_check.write_probe`, `ClamdScanner.version`,
      `job_repair.SCHEDULER_JOBS`, `db_guard.script_facts`, `court_search.PARTY_NAME_RE` and `visibility.case_visible`.
    - The ops exporter's database block calls `worker_alive_at` instead of its inline query: same result, one rule.
    - Nothing else is changed.

17. **Settings**, with defaults, in `core/config.py` and `.env.example`, all optional:
    - `HEALTH_TEST_API_MIN_SECONDS` = 60 (10-3600);
    - `HEALTH_TEST_PER_USER_HOUR` = 30 (1-200);
    - `HEALTH_TEST_TIMEOUT_SECONDS` = 30 (greater than 0, at most 40, the NAPIX timeout);
    - `HEALTH_POOL_ADDRESS` = `pgbouncer:6432`;
    - `HEALTH_POSTGRES_DIRECT_HOST` = `postgres`;
    - `HEALTH_POSTGRES_DIRECT_PORT` = 5432.

    No Compose change: the `api` service reads `.env` and the defaults fit the Compose network.

18. **A read-only CLI, `aslms system-health [--json]`.** It prints the overall line, the 17 court cards (name,
    status, last call, 24 h rate, median) and the ten services. It never calls NAPIX and needs no actor. It exits 2
    when a service is down and 0 otherwise, so the runbook and scripts can use it. There is no CLI test command: the
    owner's live checks keep using `aslms napix-check`.

19. **The owner may change these defaults at approval without reopening the design:** the 60 s, 30 an hour and 30 s
    settings (decision 17), the "Unsteady" and "Failing" thresholds (decision 4), the navigation label "System
    health" (decision 2), and the choice of no typed input (decision 6).

## Data
**No table, no column and no migration** (head stays 0020). The paragraph for `docs/schema/schema.md`, after the
data-health and napix-window paragraphs:

> System health (design `api-health-checker`, no migration, no table or column): the function `admin.service_health`
> joins `ref_permission` through `aslms seed`. No user type has it by default; the super admin holds every function.
> The screen reads `napix_call_log` over the last 7 days for its court cards, served by `ix_napix_call_log_called_at`.
> It reads `job_runs`, `fetch_queue`, `causelists`, `orders`, `documents`, `cases`, `case_parties`, `case_advocates`,
> `case_hearings`, `case_types`, `discovery_terms` and the master tables for samples and service checks; it never
> writes to them. A "Test now" writes one `napix_call_log` row per attempt (`user_id` the caller, `lane` and
> `job_run_id` NULL), at most one `napix_responses` row through the recorder, and one `audit_log` row
> `napix.api_tested` (`entity_type` `napix`, `entity_id` NULL, no `case_id`; `after` holds the API key, the outcome,
> the non-personal sample values and the summary, never the payload). The per-API interval and the per-user hourly
> cap of the test count those audit rows (`ix_audit_log_created_at`, `ix_audit_log_actor_created`).

- Reference codes: `ref_permission` gains `admin.service_health` (label "System health", description as in
  decision 1). The seed adds it to `PERMISSION_LABELS`, and `seed_matrix` writes a disabled `role_permissions` row for
  every type.
- `Permission.ADMIN_SERVICE_HEALTH = "admin.service_health"` joins `domain/reference.py`. `ref_permission` is a
  `ref_code` set, not a `pg_enum`, so there is no migration.
- No FK, class or audit-column change.

## Services
- **`services/system_health.py`** (new): `CATALOGUE`; the call-log readings; the status rules; the overall line.
  - `CATALOGUE: tuple[ApiEntry, ...]`, with `ApiEntry(key, label_key, group, method, chooser, invoke, summarise)`.
  - `card_status(last, h24) -> str`: pure (decision 4).
  - `napix_cards(session, settings, user, now=None) -> dict`:
    - the switch, `window_block`, and the groups with their cards;
    - per card: `test` = {`available`, `reason`, `cost`: 1, `next_allowed_at`}, from the sample `EXISTS` queries, the
      per-API interval and the caller's hourly count; and `last_test` = {`at`, `ok`, `by_you`} from audit rows of the
      last 7 days;
    - runs under `with_timeout(session, REPORT_STATEMENT_TIMEOUT_SECONDS)`.
  - `api_detail(session, settings, user, key, now=None) -> dict`: the card, the 7 daily buckets, the last 10 calls and
    the chosen sample with its visibility-aware label. Raises `UnknownApi`.
  - `overall(cards, services) -> dict`: decision 10.
- **`services/napix_samples.py`** (new): one chooser per card (decision 5).
  - `exists(session, key) -> bool`, and `choose(session, settings, key, user) -> Sample | NoSample(reason)`.
  - `Sample(values: dict[str, Any], label: str, source_case_id: uuid | None, source_ref_no: str | None, stored_sha256:
    str | None)`.
  - Personal values (names) go into `values` for the call but are excluded from `public_values()`, which is what the
    API and the audit row get.
- **`services/napix_api_check.py`** (new): the test. Not named `*_test.py`, which pytest would collect.
  - `guard(session, settings, user, key, now=None) -> Sample`: the refusals of decision 8, in order, raised as
    `TestRefused(code, message, http_status, retry_after)`. Writes nothing.
  - `async run(session, actor, user, settings, client, hc, key) -> TestOutcome`:
    1. `acting_member(session, user, Permission.ADMIN_SERVICE_HEALTH)`;
    2. `guard`;
    3. the advisory lock;
    4. `NapixRecorder(user_id=napix_window.user_id_of(user))` set as `client.on_call`;
    5. `client.max_attempts = 1` and `client.timeout = HEALTH_TEST_TIMEOUT_SECONDS`;
    6. `async with client`: the entry's `invoke(hc, sample)`.

    An `IntegrationError` or `httpx.HTTPError` is an outcome, not an exception. Then the recorder is flushed (also in
    a `finally`, before any error leaves, so failures are recorded and never lost), the summary is built (decision 9),
    and the audit row is written (decision 13).
  - `summarise_rows`, `summarise_record`, `summarise_pdf` and `plain_reason(error_family, napix_status)`: pure, unit
    tested against `docs/specs/samples/`.
- **`services/service_checks.py`** (new): `run_all(session, settings, now=None) -> dict`.
  - The ten checks of decision 10. The network probes (Redis, the direct Postgres probe, ClamAV, the web probe, the
    store probe) run in a `ThreadPoolExecutor(max_workers=6)`, each with the probe timeout. The database readings run
    on the request's session.
  - Each check is a function taking injectable probes, for tests. A check that raises becomes `unknown` with the
    exception class name only.
  - Never calls NAPIX. Never returns a URL, a password or a host credential.
- **`services/ops_metrics.py`**: extract `worker_alive_at(session) -> datetime | None` (decision 16). `collect_database`
  calls it. Behaviour unchanged.
- **`integration/napix/hc.py`**: `case_by_cnr(cnr, *, fallback: bool = True)` (decision 3).
- **`services/access_seed.py`**: the label of `admin.service_health`; it is not added to any `DEFAULT_MATRIX` set.
- **CLI** `cli/…`: `aslms system-health [--json]` (decision 18).
- **Audit and events:** the audit row `napix.api_tested` only. No event, no alert, no notification.

## API
A new router, `api/routers/system_health.py`, with prefix `/admin/system-health` and tag `system-health`. Every
endpoint needs **`Permission.ADMIN_SERVICE_HEALTH`** (`require(...)`). Errors carry `{code, message}`, plus
`retry_after` with a `Retry-After` header on 429. Times are in IST. The schemas go in `api/schemas.py`, and the
frontend's `schema.d.ts` is regenerated.

| Method and path | Answer |
|---|---|
| `GET /admin/system-health` | `SystemHealthOut`: `as_of`, `napix_enabled`, `window` (the `NapixWindowOut` of `data_health.window_block`), `groups: [{key, label, cards: [ApiCardOut]}]`, `summary: {working, unsteady, failing, no_recent, total}`. **Never calls NAPIX**, never probes services. |
| `GET /admin/system-health/napix/{api}` | `ApiDetailOut`: the `ApiCardOut`, `days: [{date, calls, answered, failed, avg_ms}]` (7), `recent: [{called_at, answered, ok, duration_ms, http_status, napix_status, error_family, reason, by: "background" \| "person" \| "you"}]` (10), `sample: {available, label, values, reason}`, `technical: {name, path, method, input_fields}`. 404 `not_found` for an unknown key. Never calls NAPIX. |
| `POST /admin/system-health/napix/{api}/test` | No body. 200 `ApiTestOut` for a test that made a call, answered or failed: `{api, ok, answered, status, reason, http_status, napix_status, error_family, duration_ms, attempts, called_at, token_verified, remaining, input: {label, values}, summary: {kind: "rows" \| "record" \| "pdf", row_count, field_names, facts: [{label, value}]}}`. Refusals, with no call and nothing written: 404 `not_found`; 409 `napix_off`, `no_sample`, `test_running`; 429 `test_too_soon`, `test_limit`, `napix_budget`; 403 `forbidden`. The court's own failure is a 200 with `ok: false`, not an HTTP error, because the test worked and the API did not. |
| `GET /admin/system-health/services` | `ServicesOut`: `checked_at`, `overall: {status, sentence_key, counts}`, `services: [{key, label, status, headline, facts: [{label, value}], duration_ms}]` (10, in decision 10's order). Never calls NAPIX. |

- `ApiCardOut` = `{key, label, group, status, last_call, h24: {calls, answered, failed, rate, p50_ms, p95_ms}, d7:
  {calls, answered, failed, rate}, hours: [{hour, answered, failed, avg_ms}] (24), test: {available, reason, cost,
  next_allowed_at}, last_test}`.
- **Visibility.** The screen carries no case data beyond decision 5's labels, which name a case only when
  `case_visible` allows it. Everything else is system-wide counts with no names.
- `/me` lists the new function automatically. The `web` relay needs no change.

## Jobs
None. Nothing is scheduled, queued or retried. Tests run in the request (decision 11). The service checks run on
request. The background work stays as it is.

## Tests
No live NAPIX anywhere. The switch is never set; `Settings.napix_configured` is patched as in
`test_api_napix_admin.py`.

**Backend, database** (`tests/db/test_api_system_health.py`, scripted gateway behind `app.state.napix_factory`):
- `test_every_endpoint_needs_admin_service_health`: 403 for an officer, a Central operator, State oversight and an
  auditor by default; 200 for the super admin; 200 for an officer after `access.set_override(..., GRANT)`.
- `test_reading_never_calls_the_gateway`: the GET list, the detail and the services; `gw.seen` stays empty.
- `test_cards_count_not_found_and_input_refusals_as_answered`: seeded call-log rows give the expected 24 h and 7 d
  rates, buckets, p50 and p95.
- `test_card_status_rules`: Working, Unsteady, Failing and No recent calls from seeded rows.
- `test_cnr_alt_rows_are_not_counted`.
- `test_switch_off_refuses_without_a_call_or_audit` (409 `napix_off`).
- `test_each_api_makes_exactly_one_call_with_held_inputs`, parametrised over the 17 keys. It asserts:
  - one `gw.seen` entry, the expected path and decrypted parameters;
  - the inputs taken from the seeded held data;
  - `est_code` and `state_code` from settings;
  - one `napix_call_log` row with `user_id` = the caller;
  - one audit row `napix.api_tested`.
- `test_no_held_data_means_no_sample_and_no_call`, on an empty database:
  - 409 `no_sample` with the reason for Lists of a bench, Cause list PDF, Case details by CNR, Case status, Order
    PDF, Hearing business, the four searches;
  - the masters and the Connection check stay testable;
  - Benches sitting on a day uses today (IST).
- `test_party_search_prefers_a_discovery_term`, and `test_party_and_advocate_names_never_leave_the_server`: the
  scripted answer's `pet_name` / `res_name` and the chosen name do not appear in the response JSON, the audit `after`,
  or the GET detail.
- `test_sample_label_names_the_case_only_when_visible`.
- `test_response_has_no_secret_or_token`: the client secret, the scripted access token and the auth key string are
  absent from the response and the audit row.
- `test_test_writes_no_case_data`: row counts of cases, parties, advocates, hearings, orders, documents, causelists,
  masters, `fetch_queue`, events and alerts are unchanged; `napix_responses` gains one row.
- `test_a_gateway_500_is_one_attempt_and_a_failed_outcome`: 200 with `ok: false` and `NapixUnavailable`; one logged
  row; audited.
- `test_empty_200_is_reported_as_the_known_fault`.
- `test_628_reads_answered`.
- `test_cnr_404_never_tries_the_alternate_path`.
- `test_token_renewal_counts_two_attempts`.
- `test_per_api_interval` (429 `test_too_soon` with `Retry-After`, for any user) and
  `test_connection_check_shares_the_check_interval` (a data-health check, then a test of the Connection check: 429).
- `test_per_user_hourly_cap` (429 `test_limit`).
- `test_quota_floor` (429 `napix_budget` with `retry_after` to the expected reset); `test_unknown_window_allows_a_test`.
- `test_concurrent_test_of_one_api_is_refused`: the advisory lock held from a second session gives 409 `test_running`.
- `test_pdf_summary_compares_with_the_stored_copy`: same and different.
- `test_unknown_api_is_404`.

**Backend, service checks** (`tests/db/test_service_checks.py` and `tests/unit/test_service_checks.py`):
- each check with injected probes for ok, warn and down at the thresholds of decision 10:
  - the worker from `job_runs` and `fetch_queue` rows (70 min, 2 h);
  - the scheduler (10 min, 30 min);
  - backups (interval plus 1 h, 13 h, never, restore check 8 days);
  - ClamAV (down, signatures 3 days old);
  - store (an unwritable tmp dir, low free space);
  - web (non-2xx, slow);
  - Redis (no answer, memory);
  - the direct probe (`S`, `N`, refused);
  - the pool card's "connects directly" wording;
- a raising check becomes `unknown` with the class name only;
- the whole run finishes within the probe timeout plus a margin when one probe hangs;
- no URL or password appears in the output;
- `test_overall_counts_court_cards_at_most_as_warn`.
- `test_ops_metrics_worker_alive_unchanged`: the exporter's gauge equals `worker_alive_at`.

**Backend, unit:**
- `test_summarisers_on_samples`: every JSON sample in `docs/specs/samples/` and the two PDFs give the expected kind,
  counts and field names, and no value from a name field.
- `test_plain_reason_covers_every_error_family`.
- `test_catalogue_matches_hc_methods`: every entry's key is in `hc.API`, and the three unused keys and `cnr_alt` are
  absent.

**Seed:**
- `test_seed_adds_admin_service_health_disabled_for_every_type`;
- `test_super_admin_holds_admin_service_health`.

**CLI:** `test_system_health_cli_prints_and_never_calls_napix`, which also checks exit code 2 with a service down.

**Frontend** (vitest, `components/system/system.test.tsx`, `components/ui/charts.test.tsx`, `lib/routes.test.ts`):
- the nav entry shows only with `admin.service_health`;
- the 17 cards render in four groups with their badge inside a `Lead`;
- "Test now" is disabled with the reason when `napix_enabled` is false, `test.available` is false or
  `next_allowed_at` is in the future;
- a click POSTs once (a double click is guarded by `inFlight`) and the panel shows the summary;
- a 429 shows "Next test possible in n s";
- a 409 `no_sample` shows the reason;
- the services list renders statuses with words;
- "Check services again" is the page's only primary button;
- `SparkBars` and `RateRing` carry their accessible names;
- under reduced motion, bars and ring render at their final values with no transition;
- the panel's address is `?api=` and Back closes it.

## Verification
1. `ruff check` clean; `pytest -q` green, including every test above; `npm run lint`, `npm test` and `npm run build`
   green in `frontend/`.
2. `aslms seed` on the dev database:
   - `SELECT code FROM ref_permission WHERE code = 'admin.service_health'` gives 1 row;
   - `SELECT count(*) FROM role_permissions WHERE permission = 'admin.service_health' AND is_enabled` gives 0.
3. With Compose up and `NAPIX_ENABLED` false, sign in as the super admin and open `/system`:
   - 17 court cards in four groups show the last results from the call log, with no call made: `napix_call_log`
     count unchanged;
   - every "Test now" is disabled with the switched-off reason;
   - ten service rows show; `api`, both database rows, Redis, worker, scheduler, store and web read Working; ClamAV
     reads Working once its signatures have loaded; Backups reads from `job_runs`;
   - `docker compose stop clamav` and "Check services again" give Virus scanner "Not working"; start it again;
   - `aslms system-health` prints the same in the `api` container.
4. On the dev database (the running historical load), `EXPLAIN ANALYZE` of the two call-log queries behind `GET
   /admin/system-health` stays under 2 s in total; the time goes in the build report. Over 2 s means the developer
   stops and asks (decision 4).
5. A login without the function gets 403 on all four endpoints, and the nav entry is hidden.
6. **Owner-run live check** (needs the owner's go-ahead and `NAPIX_ENABLED=true` for that run only, as for every
   live call). Budget: at most 6 calls. Test the Connection check, Districts list and Case details by CNR once each.
   Expect:
   - three `napix_call_log` rows (four to six only if the token had to be renewed) with the owner's `user_id`;
   - three `audit_log` rows `napix.api_tested`;
   - the cards updated;
   - a second click on the same card within 60 s gives "Next test possible in n s" without a call.
   Record the counts in the decisions log.
7. The scribe updates:
   - `docs/schema/schema.md`: the paragraph of "Data";
   - `docs/claude_ASLMS_design_decisions.md`;
   - `docs/operations.md`: a "System health screen" section with the CLI, the thresholds and the owner's live check;
   - `.env.example`: decision 17.

## Open questions
None. Every decision is made. Decision 19 lists the defaults the owner may change at approval without reopening the
design.
