# Design: Audit log API for auditors; the data-health screen, `/admin/napix/health`, re-fetch and sync buttons

```
slug: audit-screens
status: approved
author: architect
date: 2026-10-08
approved_by: owner (nayanlhuzuri) on 2026-10-08
```

## Context
Plan §5.13 (Audit Log): "A permanent record of every significant action in the portal. Logins, ownership
decisions, custody moves, notes, file uploads and configuration changes. Searchable by user, case and date;
read-only for auditors." Data: the portal database (append-only). Table 1: the auditor has "read-only access to
case records and the audit log". Plan §5.10 (Reports) and §3 (integration): "Data collection health: status of the
daily data cycle, and any failed API calls or SourceTrace ingestions"; a failed call "is retried and logged, never
lost". Backlog row 10: the audit log API (searchable by user, case, date) for auditors; the data-health screen
(queue depths, calls used, failures), `/admin/napix/health`, the re-fetch and sync buttons. The decisions log
(1 Oct 2026, pipeline stages 4–5) says "Admin endpoints (`/admin/napix/health`, the re-fetch buttons) wait for the
API; the CLI covers them meanwhile"; `cases-api` (decision 14) and `documents-uploads` (decision 11) point their
re-fetch of a fetched case and of a missing order PDF here.

In place today (reused, not rebuilt):
- `audit_log` (append-only, trigger `aslms_forbid_change`), written by `services/audit.py::write_audit` from every
  service (about 75 action codes: `auth.*`, `user.*`, `membership.*`, `access.*`, `office.*`, `designation.*`,
  `ownership.*`, `recommendation.*`, `transfer.*`, `custody.*`, `stage.set`, `note.*`, `document.*`, `ticket.*`,
  `alert.*`, `scoring_settings.update`, `sourcetrace.*`, `report.exported`, `profile.*`). Note bodies and custody
  remarks appear only as `{length, sha256}` (custody-workflow decision 21); document rows carry the original file
  name. Indexes today: `action`, `case_id`, `entity_id` — none on the actor or the time.
- Functions (seeded since migration 0003): `audit.view` (default: `auditor`; the super admin holds every
  function), `admin.napix_refetch` and `admin.masters_sync` (default: `central_operator`), `reports.state`
  (`state_oversight`, `central_operator`). Nothing checks `audit.view`, `admin.napix_refetch` or
  `admin.masters_sync` yet. Only the super admin can grant them (the delegation rule: a non-super-admin grants
  only functions they hold).
- Operations tables: `fetch_queue` (kinds `masters`, `causelist_day`, `dossier`, `status_batch`, `order_pdf`;
  `services/queue.py` with `enqueue(..., requeue=)`, `status_counts`, `STALE_RUNNING`, `PRIORITY`),
  `napix_call_log` (one row per attempt, `rate_limit_remaining`, `error_family`, `token_verified`),
  `job_runs`, `master_sync_runs`, `causelists`, `source_failures` (kinds `scoring`, `text_extraction`,
  `document_missing`, `sourcetrace_ingestion`, `sourcetrace_guard`), `notifications` / `digests` (the mail
  outbox), `documents.sourcetrace_status`. Helpers: `court_search.latest_remaining_this_hour`,
  `court_search.seconds_to_next_hour`, `sourcetrace_ingest.status`, `reporting_common.with_timeout` /
  `today_ist` / `IST_ZONE`, `runner.open_hc`, `napix_store.NapixRecorder`, the `napix_factory` hook on
  `app.state` used by the cases router, `cases.resolve_case_ref`, `visibility.require_visible`,
  `visibility.state_wide`, `visibility.document_visible_condition`.
- CLI: `aslms refetch-date`, `refetch-case`, `sync-masters` (synchronous), `queue-status`, `daily-cycle`.
- The period report `GET /reports/data-health` (reports-dashboards, `reports.state`, exportable) — counts per day
  over a period. This item is the live view of "now" with the actions; it does not change the report.

Not covered: the portal screens (the audit screen and the data-health screen are built in the portal rows; row 11
`portal-shell` holds administration screens, row 39 `portal-reports` the reports); a department-scoped audit view
(decision 2, left for later); export of the audit log to Excel or PDF (left for later); a `napix_call_log`
retention job (row 39); re-running today's Current Status batches early (decision 12); SourceTrace retries (already
`/admin/sourcetrace/*`); marking a failure resolved by hand.

## Decisions
1. **One audit search endpoint with keyset paging.** `GET /audit` filters by actor (`user` id or e-mail, or
   `actor` name text), subject user (`about_user`), case (`case`: id, `ref_no` or CNR, with the cases merged
   into it), actor office (`office`, its subtree), `action` (exact, or a prefix ending in `.`), `entity_type`,
   `entity_id`, and an IST date range (`from`, `to`, inclusive). Newest first, ordered by `(created_at DESC, id
   DESC)`; the page carries an opaque `next_cursor` (the last row's `created_at` and `id`), `limit` 1–200,
   default 50; no `total`. Alternatives: limit/offset with a total (as the other lists) — rejected: the log only
   grows, deep offsets and exact counts over millions of rows are slow, and new rows arriving while paging shift
   offsets; a free-text search over `before` / `after` — rejected: no index can serve it and the plan asks for
   user, case and date. `GET /audit/{id}` returns one row (deep links); `GET /audit/actions` returns the distinct
   action codes for the filter list.
2. **The audit log is read whole, and only by a State-wide reader.** `audit.view` counts only in a membership that
   is also State-wide (the super admin, or a membership holding `cases.view_all` — the default auditor has both);
   anyone else holding `audit.view` gets 403 `audit_scope`. Reason: the rows name actions on every case, document
   and note, including the original file names of private filings and internal documents, IP addresses and
   e-mail addresses; only someone who may see all of those may read the log unfiltered. Alternatives: filter rows
   by the caller's case, document and note visibility — rejected for now: it needs a rule per entity type and per
   payload field, and the plan's auditor is a State-level role; any `audit.view` holder sees all — rejected: it
   would let a grant to a department membership read other departments' private file names. **Owner's answer
   (8 Oct 2026):** the super admin and the Auditor type read the audit log, as above. **Owner check:** a
   department-scoped audit view (e.g. a department vigilance officer reading only actions of the department's
   offices) is added later if the owner asks (left for later).
3. **Reading the audit log writes nothing.** Searches, row views and the health screens are not audited
   (reports-dashboards decision 13: exports audited, views not). The audit log stays a record of actions that
   change something. **Owner check:** if vigilance requires a trail of who searched the log, a later item adds
   `audit.searched` rows (the filters, not the results).
4. **Indexes for the three searches; no new table or column.** Migration `0013_audit_indexes` adds
   `ix_audit_log_created_at` (created_at) and `ix_audit_log_actor_created` (actor_user_id, created_at). The case
   search uses the existing `ix_audit_log_case_id`. Alternative: a BRIN index on `created_at` — rejected: the
   B-tree also serves the keyset ordering, and the table is not large enough yet to need BRIN. Every search runs
   under `SET LOCAL statement_timeout` (`REPORT_STATEMENT_TIMEOUT_SECONDS`, 30 s); a timeout answers 503
   `search_timeout` ("narrow the search").
5. **`/admin/napix/health` is the NAPIX block; `/admin/data-health` is the whole screen.** The NAPIX block: the
   switch as this API process sees it (`napix_configured`, never a credential), the current clock hour (calls,
   failed calls, the latest `rate_limit_remaining`, `NAPIX_RATE_RESERVE`, `NAPIX_SEARCH_FLOOR`, seconds to the
   next hour), today's calls in IST (total, failed, by error family, responses whose `response_token` failed),
   the last call, the last success, the last failure, and the last connectivity check. The data-health screen
   adds: queue depths per kind (`pending` split into runnable and waiting on `not_before`, `running` with the
   stale ones older than `STALE_RUNNING`, `failed`, `skipped`, `done`, the oldest runnable row), the daily cycle
   (yesterday, today and tomorrow in IST: the `causelist_day` row's status, attempts, finish and error, lists
   stored, entries parsed, parse failures; the latest status-batch date with done / failed / pending / running),
   the last masters sync per master (`master_sync_runs`), the latest run of each job (`job_runs`, jobs seen in the
   last 30 days), the mail outbox (e-mail notifications queued and failed, oldest queued, digests queued and
   failed — alerts-notifications decision 17 points here), the SourceTrace summary
   (`sourcetrace_ingest.status`, counts only, as the data-health report already shows it) and open
   `source_failures` by kind. Counts and operational references only; no party names, note text or document
   content. Alternatives: one endpoint named `/admin/napix/health` holding mail and SourceTrace too — rejected:
   misleading name; separate endpoints per block — rejected: the screen needs one consistent snapshot.
6. **Who sees the health screens:** any of `reports.state`, `admin.napix_refetch`, `admin.masters_sync`. The plan
   puts data-collection health under Reports (§5.10), so State oversight sees it as it sees the period report; the
   two NAPIX administration functions are the people who press its buttons. Alternative: a new function
   `admin.data_health` — rejected: three existing functions already describe exactly these people, and a new
   function needs a matrix decision with no new holder.
7. **Detail lists behind the counts.** `GET /admin/napix/queue` (rows by kind, status, ref prefix, with `total`,
   limit/offset — the queue is bounded by cases × kinds), `GET /admin/napix/calls` (call log rows by period, API
   and outcome, keyset like decision 1; never `params`, only `params_sha256`), `GET /admin/failures` (open or all
   `source_failures` by kind). Queue refs and call rows are court references (dates, CNRs, order numbers), not case
   data, and are shown as stored. Failure rows whose `ref` is a document id (`text_extraction`,
   `document_missing`, `sourcetrace_ingestion`, `sourcetrace_guard`) are shown only when the document is visible to
   the caller by the document rule (rows of documents without a case only to the super admin), as
   `/admin/sourcetrace/failed` does; SourceTrace retries stay on `/admin/sourcetrace/*`.
8. **The buttons enqueue; the API never fetches.** Masters sync, re-fetch a cause-list day, re-fetch a case,
   re-fetch an order PDF, retry a failed queue row and retry all failed rows of a kind each write or revive a
   `fetch_queue` row through `queue.enqueue` and return its state; the worker does the calls within its budget and
   reserve. Alternatives: call NAPIX inside the request (as `aslms sync-masters` does) — rejected: a request
   would hold the API for the duration of several calls, bypass the queue's budget and retry rules, and a lost
   request would lose the work. The answer carries `napix_enabled` of the API process so the screen can warn that
   the work waits; enqueuing while the switch is off is allowed (the row waits, nothing is lost; the worker's
   switch is set in its own environment and may differ).
9. **What each button does.**
   - **Sync masters** (`admin.masters_sync`): `masters/all` at priority 10, `requeue=True`.
   - **Re-fetch a cause-list day** (`admin.napix_refetch`): `causelist_day/<date>` at priority 20 (`list_today`),
     `requeue=True`, as `aslms refetch-date`. The date must not be after tomorrow (IST); a past date with no list
     ends `skipped` as today.
   - **Re-fetch a case** (`admin.napix_refetch`, and the case visible to the caller, else 404): `dossier/<CNR>`, or
     `dossier/<est_code>|<case number as printed>` for a provisional case (the runner's existing ref form), at
     priority 30, `requeue=True`, as `aslms refetch-case`. A merged duplicate answers 409 `merged` with the
     surviving case's `ref_no`; a case with neither a CNR nor a printed number answers 409 `no_reference` (never a
     made-up identifier).
   - **Re-fetch an order PDF** (`admin.napix_refetch`, the case visible): the order must belong to the case; a
     stored PDF answers 409 `already_stored`; otherwise `orders.download_status` is set back to `pending` and
     `order_pdf/<CNR>|<order_no>|<date>` is queued at priority 30 with `requeue=True`; a case without a CNR answers
     409 `no_reference`.
   - **Retry a queue row**: a `failed` or `skipped` row returns to `pending` with no attempts (`queue.enqueue`
     revives it); `pending`, `running` or `done` answers 409 `not_retryable` (re-fetch a done row with the
     re-fetch buttons). `masters` rows need `admin.masters_sync`, the other kinds `admin.napix_refetch`.
   - **Retry all failed rows of a kind**: the same for every `failed` row of one kind, in one statement; returns
     the count.
   Priority 30 puts a person's request ahead of new dossiers (40), sweeps (50) and history (60), behind today's
   lists (20). Every button writes one `audit_log` row (decision 11). A `running` row is left alone and reported
   as `running`; a `pending` row keeps the better priority (existing `enqueue` rule).
10. **One live connectivity check.** `POST /admin/napix/health/check` makes a single Overview call
    (`/overview/overview`, the integration design's "connectivity / credential check in data-health") through the
    integration layer with a `NapixRecorder`, so the attempt is in `napix_call_log` like any other; the payload is
    not returned (only the outcome: ok, HTTP and NAPIX status, error family, duration, `token_verified`, remaining
    quota). Refused without a call: switch off → 409 `napix_off`; an Overview call logged in the last
    `NAPIX_HEALTH_CHECK_MIN_SECONDS` (60) → 429 `check_too_soon` with `Retry-After`; remaining quota this hour
    below `NAPIX_SEARCH_FLOOR` → 429 `napix_budget` (the court-search guard's floor). Needs `admin.napix_refetch` or
    `admin.masters_sync` (it spends quota). `GET` health endpoints never call NAPIX. Alternative: probe on every
    `GET` — rejected: the screen would spend quota on each refresh.
11. **Audit of the actions.** `napix.masters_sync_requested`, `napix.refetch_requested` (entity `fetch_queue`,
    the row id; `case_id` for a case or an order; `after` = kind, ref, priority, the row's status before and after),
    `napix.queue_retry` (one row), `napix.queue_retry_failed` (kind and count, one audit row), and
    `napix.health_checked` (the outcome, never the payload or a credential). The CLI commands `refetch-date` and
    `refetch-case` go through the same service and are audited with the CLI actor (the super admin named in
    `.env`, as the other CLI groups do). No event and no alert: these are operations, not case history.
12. **Not a button: re-running today's Current Status batches early.** The batches of a date run once (refs
    `<date>:<n>` are not re-queued once done), so a midday run would make the 20:00 run find them done and skip the
    evening refresh. The CLI `daily-cycle status` remains for the operator. Alternative: a button that re-queues
    them with `requeue=True` — rejected for now: it doubles the day's status calls; left for later if the owner
    asks.
13. **The NAPIX client for the API comes from one place.** The cases router's `_napix(request)` (the
    `app.state.napix_factory` hook, else `runner.open_hc`) moves to `api/deps.py::napix_client`, used by the
    court search and the health check. NAPIX is still reached only through `backend/aslms/integration/napix/`.

## Data
No table or column. Migration **`0013_audit_indexes`** (new file; applied migrations are not edited), paragraph for
`docs/schema/schema.md` (Group 8, after the `audit_log` row):

> Audit search indexes (audit-screens, migration 0013, no table or column): `ix_audit_log_created_at`
> (created_at) and `ix_audit_log_actor_created` (actor_user_id, created_at). The log is read by
> `services/audit_search.py` only (`GET /audit`, keyset on `(created_at, id)`, IST date bounds), by holders of
> `audit.view` in a State-wide membership; reading writes nothing. `audit_log` stays append-only (`aslms_app`
> SELECT / INSERT), class `derived`, FKs unchanged (`case_id` → cases RESTRICT, `actor_user_id` → users SET NULL).

Model: `AuditLog.__table_args__` gains the two `Index` objects so `tests/unit/test_schema_metadata.py` stays in
step. Downgrade drops the two indexes.

Group 9 note for `schema.md` (`napix_call_log`, `fetch_queue`, `source_failures` rows): "Read live by
`services/data_health.py` (`/admin/data-health`, `/admin/napix/*`, design `audit-screens`); the re-fetch and sync
buttons write `fetch_queue` rows only through `queue.enqueue`."

No `ref_*` code is added: the audit action codes are free text (`varchar(80)`), as today. No new function: the
endpoints use `audit.view`, `reports.state`, `admin.napix_refetch`, `admin.masters_sync`. `seed` refreshes the
labels: `admin.napix_refetch` "Re-fetch court data" — "Re-fetch a cause-list day, a case or an order PDF from NAPIX,
and retry failed fetches"; `admin.masters_sync` "Sync court masters" — "Queue a refresh of the NAPIX masters and run
the connectivity check".

Settings (`core/config.py`, `.env.example`): `NAPIX_HEALTH_CHECK_MIN_SECONDS` (60, 10–3600). Reused:
`REPORT_STATEMENT_TIMEOUT_SECONDS`, `NAPIX_RATE_RESERVE`, `NAPIX_SEARCH_FLOOR`.

## Services
**`services/audit_search.py`** (new)
- `auditor_member(session, user) -> Member` — the first membership holding `audit.view` that is State-wide
  (`is_super_admin` or holds `cases.view_all`); `Forbidden("audit_scope")` otherwise (decision 2).
- `AuditQuery` (dataclass): `user_id`, `user_email`, `actor_text` (2–100 chars, `ILIKE` on `actor_name`, `%` and
  `_` escaped), `about_user_id` / `about_user_email`, `case_ref`, `office_code`, `action`, `entity_type`,
  `entity_id`, `from_`, `to` (dates, `from_ <= to`), `cursor`, `limit`.
- `search(session, user, q) -> AuditPage(items, next_cursor)`:
  - e-mails resolve to a login (case-insensitive); unknown → `AuditInputError("unknown_user")`;
  - `case_ref` through `cases.resolve_case_ref`; unknown → `CaseNotFound`; the filter is `case_id IN (the case,
    cases whose merged_into_case_id is the case)`;
  - `about_user`: `(entity_type = 'user' AND entity_id = :uid) OR (entity_type = 'user_membership' AND entity_id IN
    (that login's membership ids))`;
  - `office`: `actor_office_code IN (codes of the office's subtree)` (offices `path` prefix); unknown code → 400
    `bad_office`;
  - `action` ending in `.` is a prefix (`LIKE 'custody.%'`), else exact;
  - dates are IST days converted to UTC bounds `[from 00:00 IST, to + 1 day 00:00 IST)`;
  - order `(created_at DESC, id DESC)`, fetch `limit + 1` for `next_cursor`; cursor = URL-safe base64 of
    `<created_at ISO>|<id>`, malformed → `AuditInputError("bad_cursor")`;
  - runs under `with_timeout(REPORT_STATEMENT_TIMEOUT_SECONDS)`; `QueryCanceled` → `SearchTimeout`;
  - each item joins the case summary (`id`, `ref_no`, `cnr`, `case_no_text`) by LEFT JOIN.
- `get(session, user, id) -> dict` — one row; unknown → `NotFound`.
- `actions(session, user) -> list[str]` — distinct `action` values by a recursive skip-scan over
  `ix_audit_log_action` (one index probe per distinct code).
- Writes nothing.

**`services/data_health.py`** (new; reads only, under `with_timeout`)
- `napix_health(session, settings, now=None) -> dict` — decision 5's NAPIX block. "This hour" = since
  `date_trunc('hour', now())`; "today" = the IST day; the last check = the latest `napix_call_log` row with `api =
  'overview'`; `latest_remaining` from `court_search.latest_remaining_this_hour`.
- `snapshot(session, user, settings, now=None) -> dict` — `{as_of, napix, queue, daily_cycle, status_batches,
  masters, jobs, mail, sourcetrace, failures}` as decision 5. Queue depths in one `GROUP BY kind, status` plus the
  runnable / waiting / stale split by `FILTER`; daily cycle reuses the `fetch_queue` and `causelists` queries of
  `reports.data_health` (factored into a shared helper, no behaviour change to the report).
- `queue_rows(session, *, kind, status, ref_prefix, limit, offset) -> (items, total)`.
- `call_rows(session, *, from_, to, api, ok, cursor, limit) -> (items, next_cursor)` — never selects `params`.
- `failure_rows(session, user, *, kind, open_only, limit, offset) -> (items, total)` — document-ref kinds ANDed with
  `document_visible_condition(session, user)` over `documents.id = ref::uuid` (rows of documents without a case
  only for the super admin) (decision 7).
- `DOCUMENT_FAILURE_KINDS = {"text_extraction", "document_missing", "sourcetrace_ingestion", "sourcetrace_guard"}`.

**`services/napix_admin.py`** (new; every function takes the `Actor` and writes one audit row)
- `request_masters_sync(session, actor, member) -> QueueState`.
- `refetch_day(session, actor, member, list_date, today=None) -> QueueState` — `list_date > tomorrow (IST)` →
  `AdminInputError("date_in_future")`.
- `refetch_case(session, actor, user, case) -> QueueState` — `require_visible`; merged → `Merged(target_ref)`; no
  CNR and no printed number → `NoReference`.
- `refetch_order(session, actor, user, case, order_id) -> QueueState` — visible case, order of that case (else
  `NotFound`), `document_id` set → `AlreadyStored`, no CNR → `NoReference`; sets `download_status = pending`.
- `retry_item(session, actor, user, item_id) -> QueueState` — row locked `FOR UPDATE`; kind gate (`masters` →
  `admin.masters_sync`, others `admin.napix_refetch`); status not `failed` / `skipped` → `NotRetryable`.
- `retry_failed(session, actor, user, kind) -> int` — one `UPDATE … WHERE kind = :k AND status = 'failed'`
  setting `pending`, `attempts = 0`, `not_before = NULL`, `last_error = NULL`; one audit row with the count.
- `async health_check(session, actor, settings, client, hc) -> CheckOutcome` — decision 10's guards first (no call
  when refused, nothing written), then `hc.overview()` with the recorder attached, `recorder.flush(session)`,
  audit `napix.health_checked`; an integration error is an outcome (`ok = false`, its family), not a 500.
- `QueueState = {kind, ref, queue_id, status, priority, attempts, not_before, napix_enabled}`.
- The CLI `refetch-date` / `refetch-case` call `refetch_day` / `refetch_case` with the CLI actor (no visibility
  check for the super admin; the service takes the CLI's super-admin member).

`services/queue.py` gains `get_state(session, kind, ref)`; nothing else changes.

## API
Errors `{code, message}` as elsewhere; times in IST; `{case}` an id, `ref_no` (slash or dash form) or CNR.

New router `api/routers/audit.py` (prefix `/audit`):

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /audit` | `audit.view` in a State-wide membership (else 403 `audit_scope`) | `user`, `actor`, `about_user`, `case`, `office`, `action`, `entity_type`, `entity_id`, `from`, `to`, `limit` (1–200, 50), `cursor` | `{items: [AuditRowOut], next_cursor}` | 400 `unknown_user`, `bad_office`, `bad_cursor`, `bad_period`; 404 `not_found` for an unknown case; 503 `search_timeout`. |
| `GET /audit/actions` | same | — | `{actions: [str]}` | |
| `GET /audit/{id}` | same | — | `AuditRowOut` | 404 `not_found`. |

`AuditRowOut = {id, at, action, entity_type, entity_id, case: {id, ref_no, cnr, case_no_text} | null, actor:
{user_id, name, designation, office_code}, ip, user_agent, before, after}`.

New router `api/routers/napix_admin.py` (prefix `/admin`). `health_reader = require_any(reports.state,
admin.napix_refetch, admin.masters_sync)`:

| Method and path | Function | Request | Response |
|---|---|---|---|
| `GET /admin/data-health` | `health_reader` | — | `{as_of, napix, queue: {by_kind: [{kind, pending, runnable, waiting, running, stale, failed, skipped, done}], oldest_runnable_at, failed_total}, daily_cycle: [{date, label, causelist_day: {status, attempts, finished_at, last_error} \| null, lists_stored, entries_parsed, lists_parse_failed}], status_batches: {date, done, failed, pending, running} \| null, masters: [{master, fetched_at, row_count}], jobs: [{job, started_at, finished_at, status, counters}], mail: {email_queued, email_failed, email_oldest_queued_at, digests_queued, digests_failed}, sourcetrace: {...as /admin/sourcetrace/status}, failures: [{kind, open, oldest_first_seen}]}` |
| `GET /admin/napix/health` | `health_reader` | — | `{enabled, est_code, hour: {started_at, calls, failed, latest_remaining, reserve, search_floor, seconds_to_next_hour}, today: {calls, failed, by_family: {family: n}, token_unverified}, last_call_at, last_ok_at, last_failure: {called_at, api, http_status, napix_status, error_family} \| null, last_check: {called_at, ok, duration_ms, token_verified, error_family} \| null}` |
| `GET /admin/napix/queue` | `health_reader` | `kind`, `status`, `ref` (prefix), `limit` (1–200, 50), `offset` | `{total, items: [{id, kind, ref, priority, status, attempts, not_before, started_at, finished_at, last_error, result, updated_at}]}` |
| `GET /admin/napix/calls` | `health_reader` | `from`, `to` (IST dates, default today), `api`, `ok`, `limit`, `cursor` | `{items: [{id, called_at, api, http_status, napix_status, ok, error_family, error, duration_ms, token_verified, rate_limit_remaining, job_run_id}], next_cursor}` |
| `GET /admin/failures` | `health_reader` | `kind`, `open` (default true), `limit`, `offset` | `{total, items: [{id, kind, ref, error, error_family, first_seen, last_seen, attempts, resolved_at}]}` (decision 7's document rule) |
| `POST /admin/napix/health/check` | `admin.napix_refetch` or `admin.masters_sync` | — | `{ok, called_at, http_status, napix_status, error_family, duration_ms, token_verified, remaining}`; 409 `napix_off`; 429 `check_too_soon` / `napix_budget` with `Retry-After` |
| `POST /admin/napix/sync-masters` | `admin.masters_sync` | — | `QueueStateOut` (202) |
| `POST /admin/napix/refetch/day` | `admin.napix_refetch` | `{date}` | `QueueStateOut` (202); 400 `date_in_future` |
| `POST /admin/napix/refetch/case` | `admin.napix_refetch` + case visible | `{case}` | `QueueStateOut` (202); 404 `not_found`; 409 `merged` (with `ref_no`), `no_reference` |
| `POST /admin/napix/refetch/order` | `admin.napix_refetch` + case visible | `{case, order_id}` | `QueueStateOut` (202); 404 `not_found`; 409 `already_stored`, `no_reference` |
| `POST /admin/napix/queue/{id}/retry` | `admin.napix_refetch` (`masters` rows: `admin.masters_sync`) | — | `QueueStateOut`; 404; 409 `not_retryable` |
| `POST /admin/napix/queue/retry-failed` | `admin.napix_refetch` (`kind=masters`: `admin.masters_sync`) | `{kind}` | `{kind, retried}` |

`QueueStateOut = {kind, ref, queue_id, status, priority, attempts, not_before, napix_enabled}`. No `GET` endpoint
calls NAPIX; the buttons never call NAPIX (decision 8).

CLI: `aslms audit search [--user EMAIL] [--case REF] [--from D] [--to D] [--action A] [--limit N]` (acts as the
`.env` super admin, prints a table; writes nothing); `aslms data-health` (prints the snapshot as JSON);
`refetch-date` and `refetch-case` now audited (decision 11).

## Jobs
None. The buttons write `fetch_queue` rows of the existing kinds and ref formats (`masters/all`,
`causelist_day/<YYYY-MM-DD>`, `dossier/<CNR>` or `<est_code>|<case number>`, `order_pdf/<CNR>|<order_no>|<date>`)
at the priorities of decision 9; the existing worker runs them.

## Tests
Unit (`tests/unit/test_audit_search_unit.py`):
- `test_cursor_round_trip_and_bad_cursor` — encode / decode; a malformed cursor raises `bad_cursor`.
- `test_action_prefix_vs_exact` — `custody.` is a prefix, `custody.sent` exact; `%` and `_` in `actor` are
  escaped.
- `test_ist_day_bounds` — `from`/`to` map to `[D 00:00 IST, D+1 00:00 IST)` in UTC.

Database (`tests/db/test_audit_search.py`, `tests/db/test_api_audit.py`):
- `test_search_by_user_case_and_date_combined` — rows written through the real services (claim, custody send,
  note, upload) are found by actor, by case and by date; filters AND together.
- `test_ist_day_boundary` — a row at 23:59 IST on D is in `to=D`; one at 00:00 IST on D+1 is not.
- `test_about_user_includes_membership_rows` — `user.*` and `membership.*` rows about a login.
- `test_case_filter_includes_merged_duplicates` and `test_case_by_ref_no_and_cnr`.
- `test_office_filter_covers_subtree`.
- `test_keyset_paging_has_no_gaps_or_repeats` — rows sharing one `created_at` across a page boundary.
- `test_audit_scope` — auditor and super admin 200; department officer 403; a department officer granted
  `audit.view` 403 `audit_scope`; an auditor whose membership is denied `cases.view_all` 403 `audit_scope`.
- `test_reading_writes_nothing` — `audit_log` count unchanged after searches, a row view and `actions`.
- `test_actions_lists_distinct_codes`; `test_unknown_user_400_unknown_case_404`; `test_row_detail`.
- `test_rows_carry_no_note_text` — the `note.added` and `custody.sent` rows found by the search carry only the
  `{length, sha256}` digest.

Database (`tests/db/test_data_health.py`, `tests/db/test_api_napix_admin.py`):
- `test_snapshot_counts_exact` — seeded `fetch_queue` rows of each kind and state (one stale `running`, one waiting
  on `not_before`), `napix_call_log` rows this hour, earlier today and yesterday, `job_runs`, queued and failed
  e-mail notifications and digests, open and resolved `source_failures`; every figure equals the seeded numbers.
- `test_napix_health_hour_and_last_failure` — latest remaining of this hour only; last failure and last check.
- `test_health_permissions` — oversight, central operator, super admin 200; auditor, department officer 403.
- `test_failures_document_kinds_follow_document_visibility` — a `text_extraction` failure on a private filing is
  listed for the super admin, not for a `reports.state` grantee in a department membership without sight of it.
- `test_queue_list_filters_and_total`; `test_calls_list_never_returns_params`.
- `test_buttons_enqueue_and_audit_without_calling_napix` — each button against the scripted gateway: the gateway
  receives no request; the queue row and the audit row are as decision 9 and 11 say.
- `test_refetch_day_rules` — a `done` row is re-queued; a `running` row stays `running`; a date after tomorrow 400.
- `test_refetch_case_rules` — CNR ref, provisional ref, merged 409 with the target `ref_no`, no reference 409, not
  visible 404.
- `test_refetch_order_rules` — stored 409; `not_available` → `pending` and queued; order of another case 404.
- `test_retry_item_and_retry_failed` — `failed` and `skipped` revive with attempts 0; `pending` 409; a `masters`
  row refused without `admin.masters_sync`; bulk retry returns the count and writes one audit row.
- `test_health_check_one_call_logged_and_audited` — scripted gateway answering Overview from
  `overview_2026-09-03.json`, `napix_configured` monkeypatched (the switch itself is never set): one request, one
  `napix_call_log` row with `api = 'overview'`, one `napix.health_checked` row, payload not in the response.
- `test_health_check_refusals_make_no_call` — switch off 409, a check 10 s ago 429 `check_too_soon`, remaining
  below the floor 429 `napix_budget`; gateway untouched, nothing written.
- `test_health_check_gateway_error_is_an_outcome` — a 5xx from the gateway gives `ok = false` with its family,
  HTTP 200.
- `test_cli_refetch_is_audited`.
- `test_reports_data_health_unchanged` — the shared daily-cycle helper leaves `/reports/data-health` identical.
- Migration: `test_0013_indexes_exist` (and downgrade drops them); `test_schema_metadata` passes.

## Verification
1. `ruff check` clean; `pytest -q` green.
2. `alembic upgrade head` on the dev database (0013); `aslms seed`. `\d audit_log` shows the two new indexes.
3. `aslms audit search --from <today> --to <today> --limit 20` lists today's rows newest first; as the auditor,
   `GET /audit?from=<today>&to=<today>` returns the same first 20 ids; `GET /audit?case=<a claimed case ref_no>`
   returns its `ownership.claim` row; `SELECT count(*) FROM audit_log` is the same before and after.
4. As a department officer `GET /audit` → 403; as the auditor → 200.
5. `aslms data-health` and `GET /admin/data-health` as the central operator: `queue.by_kind` equals `aslms
   queue-status`; `napix.today.calls` equals `SELECT count(*) FROM napix_call_log WHERE called_at >=
   <today 00:00 IST>`; `failures` equals `SELECT kind, count(*) FROM source_failures WHERE resolved_at IS NULL
   GROUP BY kind`.
6. `POST /admin/napix/refetch/day {"date": "2025-01-06"}` → 202, the `causelist_day/2025-01-06` row `pending` at
   priority 20, one `napix.refetch_requested` audit row; `napix_call_log` count unchanged by the request.
7. With the worker's switch off, `POST /admin/napix/health/check` → 409 `napix_off`. The live check (one Overview
   call) is run by the owner in a session with `NAPIX_ENABLED` set for that run, as for `napix-check`.

## Open questions
None.

## Left for later
- A department-scoped audit view filtered by case, document and note visibility (decision 2), if the owner asks.
- `audit.searched` rows for reads of the log (decision 3), if vigilance requires it.
- Export of an audit search to Excel / PDF (reusing `report_export`), if the owner asks.
- A button re-running today's Current Status batches (decision 12).
- The audit and data-health screens in the portal (rows 11 and 39); the `napix_call_log` retention job (row 39).

## Deviations
Written by the developer while building (smallest reasonable choices where the design was silent):
1. **The connectivity check's call-log key is the API path.** `napix_call_log.api` holds the path the client
   called (`overview/overview`, as every other row: `hc-cnr-api/CNR`, …), not the short key `overview`. The last
   check and the `check_too_soon` guard read `api = 'overview/overview'` (`data_health.OVERVIEW_API =
   hc.API["overview"]`). `GET /admin/napix/calls?api=` accepts either the short key or the path.
2. **Services take the caller, not a pre-chosen membership.** `request_masters_sync`, `refetch_day`,
   `refetch_case`, `refetch_order`, `retry_item`, `retry_failed` and `health_check` take the login (or a
   `Member`) and pick the acting membership holding the function (the super admin's first) for the audit snapshot;
   `None` is the CLI before a super admin exists (`system` actor, no visibility check). The CLI passes the super
   admin's own membership.
3. **`aslms refetch-case` takes a case reference** (CNR, `ref_no` or id) and refuses a case the database does not
   hold ("search the court for a new one"), because the shared service needs the case for the visibility, merge
   and provisional-ref rules. Before, it queued any CNR text unaudited.
4. **Extra 400 codes.** `bad_actor` (actor text outside 2-100 characters; the API's query validation answers 422
   first) and `bad_period` / `bad_cursor` on `GET /admin/napix/calls` (the same helpers as the audit search). A
   login id passed as `user` / `about_user` that does not exist answers `unknown_user` like an unknown e-mail.
5. **The check's outcome when the gateway retries.** The client retries a 5xx three times; the outcome reports
   the last attempt's HTTP / NAPIX status, family and `token_verified`, the summed `duration_ms`, and the audit row
   adds `attempts` (each attempt is its own `napix_call_log` row, as for every call).
6. **Failure rows whose `ref` is not a document id** in a document kind (e.g. a stale ref) are shown only to the
   super admin, like the rows of documents without a case (the document rule cannot place them).
7. **Migration 0013 keeps Alembic's generated docstring** (`audit_indexes`): the repository's guard refuses any edit
   of an existing migration file, so the reviewed content (two `create_index`, two `drop_index`) is the
   autogenerated one, formatted by `ruff format`.
8. `QueueStateOut.status`, `priority` and `queue_id` are nullable in the schema for completeness; a button always
   returns the row it wrote.
9. **`aslms data-health` needs no super admin** (counts only, like `aslms queue-status`); `aslms audit search` acts
   as the super admin as designed and refuses when there is none. Checked on the dev database (no logins there
   yet): `queue.by_kind` equals `aslms queue-status`, `napix.today.calls` equals the SQL count since 00:00 IST,
   `failures` equals the open `source_failures` by kind (none).
