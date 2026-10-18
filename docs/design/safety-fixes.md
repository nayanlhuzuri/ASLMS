# Design: Safety fixes from the independent audit (application role, NAPIX recovery, capped advocate searches)

```
slug: safety-fixes
status: approved
author: architect
date: 2026-10-18
approved_by: owner (nayanlhuzuri) on 2026-10-18
```

## Context
Backlog row 76. It covers three findings: Top 1 and Top 4 of the independent audit of 18 Oct 2026
(`docs/audits/2026-10-18-independent-audit.md`), and item 1 of row 75 (review finding 1 of
search-court-advocate-filing). The plan (§2 "retry, rate-limit and error handling so that a failed call is retried
and logged, never lost") and DB_STANDARD §8 (`aslms_app` for the API and workers, `aslms_owner` for migrations) are
the source. These fixes bring the build back into line with them. They are not new scope.

What the running system shows (read-only queries on the dev database, 18 Oct 2026):

1. **Database role.** `compose.yml` connects `init`, `api`, `worker` and `scheduler` as `POSTGRES_USER` (`aslms`,
   a cluster superuser). The `aslms_app` role exists and has the right grants: 0001 lines 394-400, and every later
   migration that adds a table (0003, 0004, 0008, 0009, 0010, 0014, 0017) grants on it. But nothing logs in as
   `aslms_app`, so the controls on paper do not hold in practice: no DELETE on legal records, no UPDATE on the logs,
   no DDL. Its password is set only once, by migration 0001 (`_set_role_passwords`), from whatever `.env` held at the
   time. `.env.example` says "the application connects as aslms_app" but sets `aslms:aslms`. A code read finds no
   runtime DDL. The app deletes rows only from `case_office_scores`, `otp_codes` and the two draft tables, all of
   which are on the DELETE lists (`CASCADE_TABLES`, `DRAFT_TABLES`). Its sequences are `ref_sequences` rows, which
   need only INSERT and UPDATE.
2. **NAPIX recovery.** In the last 30 days `hc-cnr-api/CNR` answered **HTTP 200 with an empty body 9,668 times**. It
   was logged as `NapixProtocolError: NAPIX non-JSON response:`. The client does not retry a `NapixProtocolError`
   (`client.call` retries only `NapixUnavailable`). The runner then calls `queue.fail(retry_in=10 min)`, and after
   `MAX_ATTEMPTS = 5` the row is `failed` for good. The faults come in runs. In the worst hours, 337 of 896 calls
   were empty (8 Oct 18:00 UTC) and 317 of 574 (17 Oct 16:00 UTC). **After an empty answer, the next CNR call failed
   too in 8,588 of 9,702 cases, a median 0.57 s later.** So retrying a few seconds later does not help. Only waiting
   does. The queue holds **736 failed dossier rows: 733 of them are the empty body**, 2 are token-endpoint 401s and
   2 are HTTP 500/503. 723 of them belong to disposed cases that were never fetched (`last_full_refresh_at IS NULL`).
   The weekly sweep (`tracking.enqueue_weekly_dossier_sweep`) covers non-disposed CNRs only, so nothing ever brings
   those cases back. `source_failures` holds no row for any of this. For cases with a CNR, "never fully fetched" is
   the same as `is_provisional` (both are set by `cases.apply_dossier`): 759 disposed, 44 pending and 123 unknown.
3. **Advocate searches.** The court matches **part of a name** (probe P4: "SAIKIA" alone gives 325 distinct CNRs
   for one year; notes §7). `court_search._name_search` stores every row in the request, creating, scoring and
   duplicate-checking each one. A three-letter name with "both" can create thousands of case rows inside one HTTP
   request. The party-name search matches exactly (P4 against the party probes), so it is not changed here.

Reused: `services/queue.py` (enqueue, claim, fail, revival), `services/runner.py`, `services/napix_admin.retry_failed`
(audited `napix.queue_retry_failed`), `cli/pipeline._cli_actor`, the `source_failures` table (derived; unique on
(kind, ref); `resolved_at`), `matching.record_failure`, `store_search_rows`, `napix_store.NapixRecorder`, the Celery
pattern "kick after commit, beat as the backstop" (`documents.dispatch_extract`), and the scripted gateway in
`tests/db/conftest.py`.

Not covered here:
- Row 16: published ports, the Redis password, TLS and the proxy, backups, PgBouncer, monitoring, a non-default
  `POSTGRES_PASSWORD`, and running migrations as a non-superuser `aslms_owner` login.
- The token endpoint's intermittent HTTP 401s (376 calls in 30 days, `NapixAuthError`). The ladder below retries them
  like any other failure, but their cause is not examined here.
- Marking `job_runs` rows stuck in `running` at start-up (audit §3).
- Row 75 items 2 (the napix-check recorder flush) and 3 (the flaky discovery test): they stay in row 75.

## Decisions

**A. The application role (audit #1)**

1. **`api`, `worker` and `scheduler` connect as `aslms_app`. `init` alone keeps `POSTGRES_USER`**, for migrations,
   seed and role passwords. Their `DATABASE_URL_SYNC` becomes
   `postgresql+psycopg://aslms_app:${ASLMS_APP_PASSWORD:?set ASLMS_APP_PASSWORD in .env}@postgres:5432/${POSTGRES_DB:-aslms}`.
   Compose's `environment:` overrides the `env_file`, so the host-side `DATABASE_URL_SYNC` in `.env` does not leak
   in. `docker compose up` refuses to start without the password (Compose `:?`).
   - Alternative: transfer table ownership to a login `aslms_owner` now. That means ALTER OWNER on about 90 tables,
     functions and types, which is the deployment hardening of row 16.
   - What remains, recorded for the owner: migrations still run as the cluster superuser, not as `aslms_owner`
     (DB_STANDARD §8). That moves to row 16.
2. **A new idempotent command, `aslms db-roles`, sets the role passwords from `.env` on every `init` run.** The
   `init` command becomes `alembic upgrade head && aslms seed && aslms db-roles`.
   - It uses `Settings.migrate_url` (the owner) and runs `ALTER ROLE aslms_app LOGIN PASSWORD '<value>'`, with the
     literal quoted through psycopg's `sql.Literal`, never formatted by hand. `aslms_readonly` gets the same
     treatment when `ASLMS_READONLY_PASSWORD` is set; when it is blank, that role is left as it is and a note is
     printed.
   - **Refusals** (exit 1, so `init` fails and the services never start, failing closed): the password is empty,
     shorter than 16 characters, uses characters other than `A-Z a-z 0-9 _ -` (it goes into a URL without encoding),
     or is a known default (`aslms`, `aslms_app`, `aslms_readonly`, `changeme`, `password`).
   - The value is never printed or logged. Output is limited to "aslms_app password set" or the refusal reason.
   - It writes no `audit_log` row. It is a deployment step run by the owner's shell, like migrations, and it
     changes no application record.
   - Alternative: a new migration that sets the passwords. Rejected: a migration runs once, so a rotated password
     would never reach the database.
3. **`.env.example` is corrected:**
   - The Postgres comment reads: "POSTGRES_USER is the cluster owner and is used only by the Compose `init` step
     (migrations, seed, `aslms db-roles`); the api, worker and scheduler connect as aslms_app with
     ASLMS_APP_PASSWORD (DB_STANDARD §8)".
   - `ASLMS_APP_PASSWORD=` is blank and marked required ("at least 16 letters, digits, `_` or `-`; e.g.
     `openssl rand -hex 24`").
   - The host `DATABASE_URL_SYNC` example uses `aslms_app:<ASLMS_APP_PASSWORD>`, and `ASLMS_MIGRATE_URL` is given
     as the owner URL.
   - `POSTGRES_PASSWORD` is left as it is. Changing it does not change an existing cluster's password, so it belongs
     to row 16.
4. **Proof by tests (owner rule from the audit: "one test running an API flow under `SET ROLE aslms_app`").**
   - A grants test pins DB_STANDARD §8 on every table: SELECT and INSERT everywhere; UPDATE everywhere except
     `APPEND_ONLY_TABLES` and `napix_call_log`; DELETE only on `CASCADE_TABLES` and `DRAFT_TABLES`; nothing on
     `alembic_version`.
   - One test module runs the main paths inside `SET LOCAL ROLE aslms_app`.
   - The rest of the suite keeps the owner connection, because `wipe` and `session_replication_role` need it.
   - Alternative: run the whole suite as `aslms_app`. Rejected: the fixtures delete and disable triggers by design.

**B. NAPIX recovery (audit #4)**

5. **An empty or non-JSON HTTP 200 body is "unavailable", not a protocol error.**
   - `client._parse_response` raises a new `NapixEmptyResponse(NapixUnavailable)` (in `core/errors.py`) for an
     empty body, or for a body that is neither JSON, nor a PDF, nor a PHP `print_r` status. The `print_r` status is
     still mapped first, so a 626 stays an auth error.
   - The call log keeps the family name (`error_family = NapixEmptyResponse`), so the health screen can tell this
     fault from an HTTP 500.
   - These stay `NapixProtocolError`: a `response_str` that cannot be decrypted (a key problem) and a non-200 HTML
     page.
   - **The client does not retry `NapixEmptyResponse` inside the call.** The evidence above shows the next call
     fails 89 % of the time half a second later, so the 2 s and 4 s in-call retries would only spend the hourly
     allowance. `client.call` re-raises it at once. Other `NapixUnavailable` causes keep their three attempts.
   - A person's court search that meets the fault answers 503 `napix_unavailable`, as for an HTTP 500 today.
6. **A longer retry ladder before `failed`.** `queue.fail` uses `RETRY_LADDER = (10 min, 1 h, 6 h, 24 h, 72 h)`.
   - After the n-th failed attempt (`attempts`, counted at claim), the row goes back to `pending` with
     `not_before = now + RETRY_LADDER[n-1]`. After the sixth failed attempt it is `failed`, so `MAX_ATTEMPTS = 6`
     and the span is about 4.3 days.
   - One ladder serves every failure and every kind. The `retry_in` parameter and the runner's 10-minute special
     case go.
   - Alternative: keep five tries and a longer fixed delay. Rejected: the audit's ladder covers both a short burst
     and a fault that lasts a day.
7. **A person asking again does not wait for the ladder.**
   - When `enqueue` is called with lane `request` on a `pending` row whose `not_before` lies in the future, the row
     takes the caller's `not_before` (NULL, which means now). Attempts and the ladder position are kept.
   - Every other caller keeps the current rule: a pending row keeps its `not_before`.
   - Without this, a person's re-fetch could sit behind a 24 h or 72 h step.
8. **The runner pauses during a gateway fault.**
   - When `NAPIX_FAULT_STREAK` items in a row (default 5, range 3-50) fail with `NapixUnavailable` (any cause), the
     pass stops with `resume_at = now + NAPIX_FAULT_PAUSE_SECONDS` (default 300, range 60-3600),
     `stopped_reason = "gateway fault: N failures in a row; pausing M s"` and `RunReport.fault_pause = True`.
   - A done or skipped item resets the count. `worker_wait` prints the fault line instead of "reset overdue".
   - This is the "back-off" for the gateway as a whole: on 17 Oct the runner spent 317 calls in one hour on empty
     answers.
   - Alternative: no pause, relying on the per-row ladder alone. Rejected: every new row would still spend one call
     inside the burst.
9. **The weekly sweep includes every case never fully fetched, whatever its status.**
   - `enqueue_weekly_dossier_sweep` queues the non-disposed CNRs, as now, and adds every non-merged case with
     `last_full_refresh_at IS NULL`:
     - by CNR when it has one;
     - by `<est_code>|<case_no_text>` when it has no CNR but has a printed number (the runner resolves it through
       Search by Case Number; no identifier is made up);
     - cases with neither are left out.
   - The rows are queued at priority 50 in the daily lane with `requeue=True`, so `failed` and `skipped` rows are
     revived with zero attempts.
   - That costs about 930 extra calls a week at today's counts.
10. **Rows that fail for good are mirrored into `source_failures`.**
    - When `queue.fail` marks a row `failed`, it upserts `source_failures`: kind `fetch_<kind>` (for example
      `fetch_dossier`), ref = the queue ref (300 characters at most), `error` = the last error,
      `error_family` = the exception's class name passed in by the runner. `attempts + 1` and `last_seen` are
      bumped on a repeat, and `resolved_at` is cleared.
    - When a row with that (kind, ref) later ends `done` or `skipped` (`queue.complete`), the open failure gets
      `resolved_at = now()`.
    - The helpers move to a small `services/source_failures.py` (`record`, `resolve`). `matching.record_failure`
      becomes a thin call to it, so all callers share one upsert.
    - The data-health "needs attention" list shows these kinds with no change. They are not document kinds, so the
      list's existing document-visibility filter does not apply to them.
    - There is no backfill, because the existing failed rows are revived (decision 11).
11. **The existing failed rows are revived once, by command.**
    - A new `aslms queue-retry-failed --kind <kind> [--lane <lane>]` calls the existing `napix_admin.retry_failed`
      with the CLI system actor (`_cli_actor`), so it writes the audited `napix.queue_retry_failed` row with the
      count.
    - The integrator runs `aslms queue-retry-failed --kind dossier` and `--kind status_batch` once, after the client
      fix is deployed.
    - Alternatives: a data migration, which would put an unaudited data change into the schema history; or waiting
      for Sunday's sweep, which revives them anyway (decision 9) but a week later. The super admin can also use the
      existing "retry failed" button on the Data collection screen.

**C. Advocate searches (row 75 item 1)**

12. **The rows stored from one advocate search are capped, and most of them are stored in the background.**
    - The request makes the court calls as today and lists the distinct valid CNRs in court order (P rows before D
      rows).
    - The CNRs already held are found in one query.
    - Of the new CNRs, the first `NAPIX_ADVOCATE_STORE_NOW` (default 25, range 1-100) are stored in the request with
      `store_search_rows`, as today.
    - **When all the distinct CNRs number at most `NAPIX_ADVOCATE_STORE_MAX` (default 300, range 25-2000; must be at
      least STORE_NOW),** the remaining new ones are stored in the background (decision 13).
    - **When they number more,** nothing more is stored. The answer says how many the court found and asks for more
      of the name. The rows are not lost: every response stays verbatim in `napix_responses`.
    - The answer lists the held cases among the first STORE_MAX CNRs, plus the ones stored now.
    - The party-name search is unchanged, because the court matches party names exactly.
    - Alternatives: cap only, with no background storing (rejected: the backlog asks for both; a later local search
      should find what the court returned); or store everything in the background (rejected: a three-letter name
      would still create thousands of rows, only later).
13. **The background storing is a durable queue row that makes no NAPIX call.**
    - A new `fetch_kind` value `search_rows` holds the ref of one `napix_responses.id`, so a "both" search queues
      two rows.
    - Each row goes in lane `request`, priority 30, with `requested_by` set to the person.
    - The handler (`court_search.store_response_rows`) reads the stored payload with the same row extractor as
      `NapixHighCourt.search_advocate` (a pure `hc.advocate_rows(payload)`). It stores every valid row whose CNR is
      not yet held with `store_search_rows` (source `search`, origin `search`). It is idempotent.
    - **Claimed only by a Celery task, never by the NAPIX runner.** `queue.LOCAL_KINDS = {search_rows}` is excluded
      from `claim` and `has_runnable` when no kinds are named, so the quota bands and the window waits never hold
      it up. The task `aslms.store_search_rows` claims `kinds=[search_rows]` until none are left. The API kicks it
      with `send_task` after its commit (best effort), and a beat every 2 minutes is the backstop.
    - Failures follow the ladder (decision 6) and are mirrored into `source_failures` as `fetch_search_rows`
      (decision 10).
    - To get the response ids, `napix_store.store_response` returns the row id (`RETURNING id` on the upsert) and the
      recorder exposes the ids of the responses written by its last flush, keyed by (api, params_sha256). The search
      flushes the recorder before it queues.
    - Alternative: a Celery task carrying the rows as arguments. Rejected: a lost broker message would drop the work
      silently. The queue row keeps it visible on the console and retried.
14. **The answer and the audit say what happened.**
    - `CourtSearchOut` gains `court_cases` (distinct CNRs the court returned), `queued` (new cases being added in the
      background) and `not_stored` (new cases beyond the cap). All three default to 0 for the other kinds.
    - The `case.search_court` audit row's `after` gains the same three numbers.
    - The portal's court search shows a notice:
      - when `queued > 0`: "N more cases are being added; search the portal again in a minute";
      - when `not_stored > 0`: "The court found N cases for this name; only the first K new ones were added. Type
        more of the name (initials and surname) to narrow it."
    - The background storing writes no audit row. The search that caused it is audited, and discovery's storing is
      not audited either.

15. **`docs/napix_integration_notes.md` gains the fault.** "HTTP 200 with an empty body (hc-cnr-api, in runs of
    minutes to hours; 9,668 times between 18 Sep and 18 Oct 2026; the next call fails too in 89 % of cases): treat
    as unavailable, do not retry immediately, back off at the queue." The evidence is the call log, which is live
    behaviour.

No plan deviation. Decision 1 leaves a recorded DB_STANDARD §8 gap (migrations as the superuser), handed to row 16.

## Data
No table or column is added. Migration **0019_safety_fixes** (new; applied migrations untouched):
- In an autocommit block, as in 0014 and 0017: `ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'search_rows'`.
- No grant change: `aslms_app` already has SELECT, INSERT and UPDATE on `fetch_queue`, and INSERT and UPDATE on
  `source_failures`.
- The downgrade refuses while a `search_rows` row is `pending` or `running`. PostgreSQL cannot drop an enum value,
  so the value stays (harmless, unused).

Paragraphs for `docs/schema/schema.md` (after the department-discovery block):

> (safety-fixes, migration 0019) `fetch_kind` gains `search_rows` (ref `<napix_responses.id>`): the background
> storing of an advocate search's rows beyond the first `NAPIX_ADVOCATE_STORE_NOW`, lane `request`, priority 30,
> `requested_by` the person. It makes no NAPIX call. Its rows are claimed only by the Celery task
> `aslms.store_search_rows`, never by the queue runner (`queue.LOCAL_KINDS`). Every kind is retried on the ladder
> 10 min, 1 h, 6 h, 24 h, 72 h after its first five failures and becomes `failed` after the sixth
> (`queue.RETRY_LADDER`, `MAX_ATTEMPTS = 6`). A `request`-lane enqueue on a pending row brings its `not_before`
> forward. `fetch_queue` stays class `derived`, with RESTRICT keys and no DELETE.

> `source_failures` (derived; unique (kind, ref); `created_at`, `updated_at` with the `set_updated_at` trigger; no
> FK) gains the kinds `fetch_<fetch_kind>` (`fetch_dossier`, `fetch_order_pdf`, `fetch_causelist_day`,
> `fetch_status_batch`, `fetch_masters`, `fetch_party_search`, `fetch_search_rows`), ref = the queue row's ref. One
> is written when a queue row becomes `failed` (`error`, `error_family`, `attempts + 1`, `last_seen`; `resolved_at`
> cleared) and resolved (`resolved_at = now()`) when that row later ends `done` or `skipped`. Written only through
> `services/source_failures.py`.

> Roles (DB_STANDARD §8, as built from safety-fixes): the Compose `api`, `worker` and `scheduler` connect as
> `aslms_app`. `init` connects as `POSTGRES_USER` and runs `alembic upgrade head`, `aslms seed` and `aslms db-roles`.
> The last sets the `aslms_app` (required) and `aslms_readonly` (optional) passwords from `.env` on every run.
> Migrations still run as the cluster superuser, not `aslms_owner` (row 16).

No `ref_*` codes. `docs/schema/napix_coverage.md`: no new field, and the `fetch_queue` row gains the kind
`search_rows` in its kind list.

## Services
- **`core/errors.py`**: `class NapixEmptyResponse(NapixUnavailable)`.
- **`integration/napix/client.py`**:
  - `_parse_response`: for an empty body, or a non-JSON body without a `print_r` status, it sets
    `result.raw_text = text[:2000]` and raises `NapixEmptyResponse`.
  - `call`: re-raises `NapixEmptyResponse` without the in-call retry. Other `NapixUnavailable` causes are unchanged.
  - `hc.py`: `advocate_rows(payload) -> list[dict]` is pure (`nested_list(payload.get("casenos"))`) and is used by
    `search_advocate` and by the background handler.
- **`services/queue.py`**:
  - `RETRY_LADDER`, `MAX_ATTEMPTS = 6`.
  - `fail(session, item, error, *, family=None)`: the ladder; on `failed` it calls `source_failures.record`.
  - `complete(...)` calls `source_failures.resolve(session, f"fetch_{kind}", ref)`.
  - `enqueue`: the request-lane `not_before` rule (decision 7).
  - `LOCAL_KINDS`, excluded in `_filters` when `kinds` is None.
- **`services/source_failures.py`** (new): `record(session, kind, ref, error, family=None)` (the existing upsert,
  plus `error_family`) and `resolve(session, kind, ref) -> int`. `matching.record_failure` delegates to `record`.
- **`services/runner.py`**:
  - It passes `family=type(exc).__name__` to `queue.fail`.
  - It counts consecutive `NapixUnavailable` item failures and stops with `fault_pause` and `resume_at` (decision 8).
  - `RunReport.fault_pause`.
  - It never dispatches `search_rows`: `dispatch` raises if one is handed to it.
- **`cli/pipeline.worker_wait`**: the fault-pause line.
- **`services/tracking.enqueue_weekly_dossier_sweep`**: non-disposed CNRs plus the never-fully-fetched cases
  (decision 9). It returns the count queued and stays called from `schedules.enqueue_weekly`. The schedules
  docstring is updated.
- **`services/court_search.py`**:
  - `_search_advocate` gets its own storing step (decision 12), with `NAPIX_ADVOCATE_STORE_NOW` and
    `NAPIX_ADVOCATE_STORE_MAX`.
  - After the calls it flushes the recorder, takes the response ids, and queues `search_rows` rows with
    `queue.enqueue(..., lane=REQUEST, requested_by=user.id)`.
  - `CourtSearchResult` gains `court_cases`, `queued` and `not_stored`, and the audit `after` carries them.
  - New `store_response_rows(session, response_id) -> dict` (the handler; `{stored, held, unmatched}`).
  - `search_court` returns, and the router kicks `aslms.store_search_rows` after its commit when `queued > 0`
    (best effort, with a logged warning on failure, as in `dispatch_extract`).
- **`services/napix_store.py`**: `store_response` returns the id. `NapixRecorder.flush` records
  `response_ids[(api, params_sha256)]` for the attempts it wrote.
- **`jobs/celery_app.py`**: task `aslms.store_search_rows` (claim, handle, complete or fail, commit per row, at most
  50 rows per run) and beat `store-search-rows` every 2 minutes.
- **`cli/db.py`**: `db_roles()`, registered as `aslms db-roles` (decision 2). Pure validation in
  `validate_role_password(value) -> str | None` (the refusal reason).
- **`cli/pipeline.py`** (or `cli/main.py` registration): `aslms queue-retry-failed --kind --lane`, which calls
  `napix_admin.retry_failed` with `_cli_actor`, commits and prints the count.
- **`core/config.py`**: `napix_fault_streak` (3-50, default 5), `napix_fault_pause_seconds` (60-3600, default 300),
  `napix_advocate_store_now` (1-100, default 25) and `napix_advocate_store_max` (25-2000, default 300), with a
  validator that STORE_NOW ≤ STORE_MAX. `aslms_app_password` stays as it is. All of them, with comments, go into
  `.env.example`.
- **`compose.yml`**:
  - `api`, `worker` and `scheduler` get the `aslms_app` URL.
  - `init` gets the new command, and `ASLMS_APP_PASSWORD` and `ASLMS_READONLY_PASSWORD` reach it through the
    `env_file`.
  - The header comment states the role split.

Audit: `napix.queue_retry_failed` (existing) for the CLI revival, and `case.search_court` (existing, with three more
numbers). Nothing else in this item is a significant user action. Events: none.

## API
- `POST /cases/search-court` (`Permission.CASES_SEARCH_COURT`, unchanged): the request is unchanged. The response
  `CourtSearchOut` gains `court_cases: int = 0`, `queued: int = 0` and `not_stored: int = 0`. Visibility is
  unchanged: the items go through `case_search.items_for` as today. The guard is unchanged: switch, quota floor and
  per-user limit.
- `POST /admin/napix/queue/retry-failed` (`ADMIN_NAPIX_REFETCH`, or `ADMIN_MASTERS_SYNC` for `masters`, unchanged):
  `RetryFailedIn.kind` accepts `search_rows`.
- `GET /admin/napix/queue`, `GET /admin/failures` and `GET /admin/data-health` (unchanged permissions) show the new
  kind and failure kinds with no shape change.
- Frontend: regenerate `frontend/src/lib/api/schema.d.ts`. `CourtSearch.tsx` shows the two notices (decision 14),
  with the strings in `lib/messages`. No new screen.

## Jobs
- `aslms.store_search_rows`: kicked by the API after a capped advocate search, and beat `store-search-rows` every
  2 minutes in the `scheduler` container. It claims `fetch_queue` kind `search_rows` (ref `<napix_responses.id>`,
  lane `request`, priority 30) and makes no NAPIX call.
- The weekly sweep (Sunday 02:00 IST, existing) widens as in decision 9. The dossier rows stay at priority 50,
  lane `daily`.
- The queue runner: the retry ladder and the fault pause. The `queue-worker` loop honours `resume_at` as today.

## Tests
Unit (`tests/unit`):
- `test_empty_200_is_napix_empty_response_and_not_retried_in_call`: the scripted transport sees one attempt; the
  `NapixResult` carries `error_family = NapixEmptyResponse`.
- `test_non_json_200_is_unavailable_but_print_r_626_is_auth`.
- `test_undecryptable_response_str_stays_protocol_error`.
- `test_http_500_still_retried_three_times`.
- `test_validate_role_password_refusals` (empty, short, bad character, each known default) and the acceptance of a
  32-character hex value.
- `test_worker_wait_prints_fault_pause`.
- `test_advocate_rows_extracts_casenos_in_order` (from `advocate_name_2026-10-18-p4.json`).
- `test_settings_store_now_not_above_store_max`.

Database (`tests/db`):
- `test_app_role_grants_follow_db_standard`: every public table, per decision 4.
- `test_app_role_cannot_delete_cases_or_update_audit_log`: `SET LOCAL ROLE aslms_app`, then `DELETE FROM cases` and
  `UPDATE audit_log` raise `InsufficientPrivilege`.
- `test_api_flow_as_aslms_app`: inside one `SET LOCAL ROLE aslms_app` connection, through the TestClient with the
  session override:
  - sign-in (password and e-mailed code with the console mailer);
  - `GET /me`, the case list, case detail;
  - claim; send the file; a note; an upload (fake scanner);
  - `GET /admin/data-health`; a report; `GET /audit`.
  It ends with an `alerts.scan_events` run, a queue-runner pass with the scripted gateway (a dossier applied and an
  order PDF stored) and one `store_search_rows` run. None of these raises a privilege error.
- `test_queue_retry_ladder_10m_1h_6h_24h_72h_then_failed`: replaces the 5-minute expectation in
  `test_queue_claim_order_and_failure_backoff`.
- `test_failed_row_mirrored_to_source_failures_and_resolved_on_done`.
- `test_request_enqueue_brings_pending_row_forward_daily_does_not`.
- `test_runner_pauses_after_fault_streak`: the scripted gateway answers empty 200s; the pass stops after 5 items
  with `fault_pause` and `resume_at`, and one success in between resets the count.
- `test_empty_200_dossier_retried_by_ladder_then_succeeds`.
- `test_weekly_sweep_includes_never_fetched_disposed_and_cnr_less_cases`: a disposed never-fetched case is queued
  and its `failed` row revived; a fetched disposed case is not queued; a CNR-less provisional row is queued by
  `<est>|<number>`.
- `test_queue_retry_failed_cli_revives_and_audits`.
- `test_advocate_search_stores_first_n_and_queues_rest`: 30 new CNRs, STORE_NOW 25 → 25 created, 2 `search_rows`
  rows for "both", `queued = 5`; the handler then creates the 5; a second handler run creates nothing.
- `test_advocate_search_over_cap_stores_first_n_only`: STORE_MAX exceeded → `not_stored > 0`, no `search_rows` row,
  the audit `after` carries the numbers.
- `test_runner_never_claims_search_rows`.
- `test_migration_0019_adds_kind_and_downgrade_refuses_while_pending`.
- The existing `test_save_queues_the_first_sweep` and the whole suite stay green.

Frontend (`vitest`): `court search shows the queued and not-stored notices`.

## Verification
The integrator, after merge (the owner sets `ASLMS_APP_PASSWORD` in `.env` first, a value like
`openssl rand -hex 24`; no assistant reads `.env`):
1. `ruff check .` is clean, `pytest -q` is green and the frontend `npm test` is green.
2. Run `alembic upgrade head` (to 0019). `docker compose up -d --build`: `init` completes and prints
   "aslms_app password set". With `ASLMS_APP_PASSWORD` blank, `docker compose config` refuses (proves fail-closed;
   restore afterwards).
3. `docker compose exec postgres psql -U aslms -d aslms -c "select usename, count(*) from pg_stat_activity where datname='aslms' group by 1"`
   shows `aslms_app` for the api, worker and scheduler connections, and `aslms` only for the psql session itself.
   `psql -U aslms_app` (with the password) `-c "delete from cases where false"` gives "permission denied".
4. `python backend/tools/portal_smoke.py` passes. The worker log shows passes with calls and no privilege error. In
   the scheduler log, `extract-text`, `alerts-scan-events` and `notifications-send` each run once without error.
5. Run `docker compose exec worker aslms queue-retry-failed --kind dossier`, then `--kind status_batch`. The counts
   should be about 736 and 1. `aslms queue-status` shows dossier `failed` 0 straight after, and one
   `napix.queue_retry_failed` audit row per command.
6. Within 24 h: `select error_family, count(*) from napix_call_log where called_at > now() - interval '24 hours' and not ok group by 1`
   shows `NapixEmptyResponse` instead of `NapixProtocolError` for empty bodies. Rows in `fetch_queue` with
   `attempts > 1` have `not_before` on the ladder. `source_failures` holds a `fetch_*` row only for rows that are
   `failed`. Record the count of the 723 cases that now have `last_full_refresh_at` set.
7. `aslms daily-cycle weekly` (or Sunday's beat): the dossier count includes the never-fetched disposed cases
   (about 930 more than the non-disposed count).
8. One advocate court search with a short surname for one year (one or two NAPIX calls, within the per-user limit).
   The answer shows `created ≤ 25`, and `queued` or `not_stored` as the court's count implies. Within 2 minutes,
   `fetch_queue` `search_rows` rows are `done` and a local search finds the queued cases.
9. Record the results in the cycle report and the decisions log, including the row 16 hand-over (migrations still
   run as the superuser).

## Open questions
None. The four new defaults are proposals the owner may change at approval:
- `NAPIX_FAULT_STREAK` 5 and `NAPIX_FAULT_PAUSE_SECONDS` 300;
- `NAPIX_ADVOCATE_STORE_NOW` 25 and `NAPIX_ADVOCATE_STORE_MAX` 300;
- the ladder 10 min / 1 h / 6 h / 24 h / 72 h, which is the audit's.

## Deviations
Recorded by the developer while building (18 Oct 2026). None changes a business rule or an API field.
1. **Audit numbers.** `court_cases`, `queued` and `not_stored` join the `case.search_court` audit `after` only for an
   advocate search that answered `ok`; the other kinds' audit rows are unchanged (the response fields default to 0
   for every kind, as designed).
2. **The API-flow test** uses an engine whose every connection runs `SET ROLE aslms_app` (session level) rather than
   `SET LOCAL ROLE` inside one connection: the app commits per request, and `SET LOCAL` ends at the first commit. The
   sign-in code is read from the test `RecordingMailer`; the console mailer logs only the masked recipient and the
   subject, so the code cannot be read from it.
3. **`queue.claim` re-reads the claimed row** (`populate_existing`), so a second claim in the same session sees the
   updated `attempts`; the ladder depends on it.
4. **`search_rows` rows are enqueued with `requeue=True`**: a repeated search whose response is identical keeps the
   same `napix_responses` id, and the done row must run again. They are queued only for the responses that carry at
   least one of the remaining new CNRs. A row whose response id no longer exists ends `skipped`.
5. **`aslms db-roles`** applies the same refusals to `ASLMS_READONLY_PASSWORD` when it is set (exit 1).
6. **`hc.advocate_rows`** is the existing `search_rows` extractor (`casenos`, else a flat numbered list), so
   `search_advocate` behaves exactly as before.
7. **The grants test** expects DELETE on `CASCADE_TABLES` and `DRAFT_TABLES` except the append-only
   `sourcetrace_ingestions`, which keeps SELECT / INSERT only (docs/schema/schema.md).
8. **The portal** labels the new queue kind "Advocate search rows" in the Data collection kind names.
