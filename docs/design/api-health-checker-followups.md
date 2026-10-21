# Design: System health follow-ups: call records that survive a failed request, token renewals, the per-person limit

```
slug: api-health-checker-followups
status: approved
author: architect
date: 2026-10-21
approved_by: owner on 2026-10-21
```

## Context
This is backlog row 110. The review of row 109 `api-health-checker` (report `docs/reports/2026-10-21-api-health-checker.md`,
"Review findings") left six advisory findings open. Row 109 was merged with them carried forward. This item closes all
six. Two more defects of the same kind, found while designing, are closed with them (decisions 3 and 7).

The rule that decides the main fix comes from CLAUDE.md: "NAPIX calls go only through `backend/aslms/integration/napix/`
… Every call is logged; failures are recorded, never lost". The plan's §3 says the same: "retry, rate-limit and error
handling so that a failed call is retried and logged, never lost".

What is in place:
- **Test now** (`services/napix_api_check.run`) and the data-health connectivity check (`services/napix_admin.health_check`)
  both attach a `NapixRecorder` to a fresh client. They make one call and then `recorder.flush(session)` into the
  **request's** session.
  - `deps.get_session` commits that session only when the endpoint returns. Any exception rolls it back.
  - So an unexpected exception after the call loses the `napix_call_log` rows and the `napix_responses` row: in the
    summary's database reads, in `write_audit`, or in building the response model.
  - `health_check` has no `finally` at all. An exception that is not an `IntegrationError` or `httpx.HTTPError` skips
    the flush.
- **The queue runner already does it right.** Its window probe (`QueueRunner.probe`) "flushed and committed in its own
  session" from the runner's `session_factory`. `finish_job` and each item also flush into their own session and commit
  it. This design reuses that pattern.
- **Token renewal in the client.** `NapixClient._attempt` handles an HTTP 401 by renewing the token and calling itself
  once more. The 401 attempt's hook fires in its `finally`, **after** the repeated attempt's hook.
  - So the order in the call log is reversed: the repeated attempt first, then the 401 attempt.
  - The 401 attempt's `duration_ms` includes the whole repeated attempt.
  - When the repeated attempt fails, its exception passes through the outer `except` and is copied onto the 401 attempt
    too, so one failure is logged twice.
  - `napix_api_check.final_attempt` works around the order. `health_check` reads `attempts[-1]`, which is the 401 row,
    so it reports a renewed success as failed.
  - `system_health._ANSWERED_SQL` counts the 401 row as a failed call in every rate.
- **One person, many tests.** `run` takes a per-API advisory lock, but the per-person hourly cap
  (`HEALTH_TEST_PER_USER_HOUR`) is counted before any lock. A person firing tests of several APIs at once can pass the
  count in each request and go over the cap. The per-API interval and the quota floor bound the excess.
- `napix_api_check._present()` treats only `""` and `0000-00-00` as "no date". `napix_values.NO_DATE` also holds the
  court's sentinels `5000-01-01` and `1900-01-01`, and `as_date` also rejects "Next Date Not Given".
- `docs/schema/schema.md`'s `ref_permission` row stops at data-load-console (51 rows, 49 active). The seed now has 52
  rows, 50 active (`Permission` has 52 members, `RETIRED_PERMISSIONS` 2; checked 21 Oct 2026).
- `docs/design/api-health-checker.md` has two `approved_by` lines. The second, `(pending)`, is a leftover from before
  approval.

Not covered here:
- **The court search routes.** `POST /cases/search-court`, the data-load `fetch` and `fetch-details` have the same
  shape: they flush into the request session and commit only on the errors they handle. An unhandled exception there
  loses the call rows too. They are left for a follow-up row (recommended to the owner, not added by this note), so
  this item stays the size of its findings.
- **Data health.** Its "failed today" count and its failures list read `ok = false` and still include a renewal's
  401 row. That screen is outside row 110.
- **No live NAPIX call** is part of the build or the tests (scripted gateway only; `NAPIX_ENABLED` is never set).

## Decisions

1. **The call rows are committed in a session of their own, at once, before anything else is done with the result.**
   - `NapixRecorder` gains `flush_apart(session_factory) -> int`. It opens a session from the factory, calls the
     existing `flush`, commits and closes. The `napix_call_log` rows (one per attempt) and the `napix_responses` row (a
     JSON answer, deduplicated as today) are therefore committed whatever the request does next.
   - Both `run` and `health_check` call it in a `finally` around the call.
   - The factory is passed explicitly: `request.app.state.session_factory`, the factory `get_session` itself uses. This
     is the same parameter the queue runner takes. Under PgBouncer it is a second pooled connection, held for one short
     insert.
   - If the separate write itself fails (the database is unreachable), the service logs a structlog warning and the
     exception propagates as a 500.
     - The warning names each attempt by `api`, `http_status`, `napix_status`, `error_family`, `duration_ms` and
       `called_at`.
     - It never includes the parameters, the payload or the error text.
   - Alternatives considered:
     - A savepoint: rolled back with the outer transaction.
     - Committing the request session in the middle of the request: this releases the advisory locks and commits
       half-done work.
     - Deriving a session from `session.get_bind()`: implicit, and it silently joins the transaction when the bind is a
       connection.

2. **The audit row is also committed separately, after the summary. The request transaction itself writes nothing.**
   - The order in `run` is:
     1. the call;
     2. the call rows, committed separately (decision 1);
     3. the outcome and the summary, built with reads on the request session;
     4. the audit row `napix.api_tested`, committed separately through the new `audit.write_audit_apart(session_factory,
        actor, action, entity_type, entity_id, *, before=None, after=None, case_id=None)`;
     5. the response.
   - So the per-API interval and the per-person cap, which count those audit rows (row 109 decision 13), see every test
     that made a call, even when building the response fails afterwards.
   - **If the summary raises an unexpected exception**, the audit row is still written separately, with `summary: null`
     and `summary_error: "<exception class name>"`. Then the exception is raised again, and the request answers 500.
     - Nothing is lost, and the defect is not hidden.
     - A court failure is still an outcome (`ok: false`), as today. This applies only to ASLMS's own defects.
   - If the separate audit write fails, the call rows are already committed. The 500 propagates.
   - The request transaction keeps only its reads and the transaction-scoped advisory locks (decision 6). They are
     released when `get_session` commits it.
   - Alternatives considered:
     - The audit row in the request transaction: lost on a later failure, and then the interval misses a real call.
     - Degrading to an empty summary and a 200: hides defects.
     - Call rows and audit row in one separate transaction: a failing audit insert would take the call rows with it.

3. **The data-health connectivity check gets the same treatment.** `napix_admin.health_check(session, session_factory,
   actor, user, settings, client, hc)`:
   - wraps the call in `try/finally`, which closes the missing-`finally` defect;
   - writes the call rows with `flush_apart`;
   - writes `napix.health_checked` with `write_audit_apart`.

   The audit `after` keys are unchanged.

4. **The client logs a token renewal in the order it happened, as one 401 step and one real attempt.** In
   `NapixClient._attempt`, on an HTTP 401 with `refresh_token=True`:
   1. The token is renewed. If the renewal fails (the token endpoint refuses or cannot be reached), the failure is
      recorded on this 401 attempt with its family, as today. It is then the only row, so the failure is in the log.
   2. Once the renewal succeeds, the 401 attempt is closed and handed to `on_call` **before** the call is repeated:
      - `ok = false`, `http_status = 401`;
      - `error_family` NULL;
      - `error` = "HTTP 401: the token had expired; it was renewed and the call repeated";
      - `duration_ms` = the 401 round trip plus the renewal.
   3. The attempt is marked as emitted, so the `finally` does not hand it over again. A later failure of the repeated
      attempt is never copied onto it.
   4. The repeated attempt (`refresh_token=False`) is logged as its own row. A second 401 there is `NapixAuthError`, as
      today.

   The effects:
   - The hook order is chronological, and the last attempt is always the one that decided the outcome.
   - Durations no longer nest, so the outcome's `duration_ms` (the sum of the attempts) is no longer counted twice.
   - `recorder.last_remaining` comes from the latest answer.
   - `napix_api_check.final_attempt` is removed. Both services read the last attempt, so `health_check` stops reporting
     a renewed success as failed.
   - Every attempt is still logged. Nothing else in the client changes: retries, rate limiting, encryption and errors
     are as before.

   Alternatives considered:
   - Keep the client and pair the rows in SQL: not reliable, because the rows carry no link.
   - A new family label such as `NapixTokenRenewed`: rejected, because the existing successful-renewal rows already have
     a NULL family, and one predicate (decision 5) then covers both the old rows and the new ones.

5. **The answered rates count API calls, not token renewal steps.**
   - A renewal step is a row with `http_status = 401 AND error_family IS NULL`, the shape decision 4 writes.
   - `services/system_health.py` gains `_COUNTED_SQL = "(http_status IS DISTINCT FROM 401 OR error_family IS NOT NULL)"`.
     It is added to the `WHERE` of `_hourly`, `_day`, `_latest` and `_recent`.
   - So renewal steps are left out of all of these:
     - the 24-hour and 7-day calls and answered counts, and the hourly bars;
     - the median and p95;
     - the "last three all failed" rule and the card's last result;
     - the detail's last 10 calls.
   - They stay in `napix_call_log`, in the quota window (`napix_window`) and in the calls-by-person counts. The gateway
     received them, and ASLMS goes on counting them as it does today.
   - Past rows:
     - A past successful renewal already has this shape and drops out at once.
     - A past renewal whose repeat failed was copied (decision 4's old defect), so it counts twice until it leaves the
       7-day window.
     - `napix_call_log` is not rewritten: no data migration.
   - The predicate only filters rows already selected through `ix_napix_call_log_called_at`, so no index is needed.

6. **One test at a time per person: a per-person advisory lock, then both limits checked again.**
   - `run` takes `pg_try_advisory_xact_lock(hashtextextended('napix-api-test-user:<user uuid>', 0))` after `guard`
     and before the per-API lock. The order is always person, then API.
   - If it fails, the refusal is **409 `user_test_running`**, "Your other test is still running; try again when it has
     finished". There is no call, and nothing is written.
   - Once both locks are held, `run` checks again:
     - the per-API interval (as today);
     - the person's hourly count (`system_health.user_tests`): 429 `test_limit`, with `retry_after`.
   - The other request's audit row is committed (decision 2) before its locks are released, so the second check
     always sees it.
   - The lock is transaction-scoped, so it is safe under PgBouncer's transaction mode. It has the same form as the
     existing per-API lock and `case_dedupe.lock_number`, which the session-feature scan of row 78 allows.
   - Alternatives considered:
     - A blocking lock: it holds a pooled connection for the length of another person's call, up to 30 s.
     - SERIALIZABLE with retries: too heavy for a counter.
     - A Redis counter: a second store for one rule.

7. **The connectivity check shares the Connection test's lock** (an addition beyond the six findings, flagged here).
   - `health_check` takes `pg_try_advisory_xact_lock(hashtextextended('napix-api-test:overview', 0))`. This is the key
     a Connection "Test now" uses.
   - It runs `check_guard` again after taking the lock. A failed lock is **409 `check_running`**, "A connectivity check
     or a test of the connection is running; try again in a moment".
   - Today two checks, or a check and a Connection test, can both pass the interval at the same moment and make two
     Overview calls. The lock and the second check close that race.
   - The owner may drop this decision at approval without reopening the note.

8. **Dates in the summary are read with `napix_values`.**
   - "A next hearing date is present" uses `napix_values.as_date(record.get("date_next_list")) is not None`. The
     sentinels `5000-01-01`, `1900-01-01` and `0000-00-00`, a blank and "Next Date Not Given" all read "no".
   - "Business text is present" stays a non-blank text check, `_text_present`, because business text is not a date.
   - `_present` is replaced by these two.

9. **Documentation.**
   - In `docs/schema/schema.md`, the `ref_permission` row gains the clause "`admin.service_health` ("System health",
     module `admin`, enabled for no type by default) added by `api-health-checker` (52 rows, 50 active, seed only)".
   - The System health paragraph and the `napix_call_log` notes gain the sentences in "Data" below.
   - In `docs/design/api-health-checker.md`, the second header line `approved_by: (pending)` is deleted. The status
     `approved` and `approved_by: owner on 2026-10-20` stay, and the history stays in git.
   - The cause is the wording of step 2 in `.claude/skills/team-approve/SKILL.md` ("set … `approved_by:`"), which was
     read as "add" rather than "replace". That file is the owner's team configuration. *At approval (21 Oct 2026),
     the owner had the wording changed to "replace the existing `approved_by:` line"; the change is on `main`.*

11. **Added at approval by the owner (21 Oct 2026): the other request paths that call NAPIX get the same treatment.**
    These routes write their call rows into the request session and commit them only on the errors they handle, so an
    unhandled exception after the call loses those rows. That breaks the same CLAUDE.md rule:
    - `POST /cases/search-court` and `POST /cases/{ref}/fetch-court` in `backend/aslms/api/routers/cases.py`;
    - `POST /admin/data-load/fetch` and `POST /admin/data-load/fetch-details` in `backend/aslms/api/routers/data_load.py`.
    Each route uses `NapixRecorder.flush_apart(session_factory)` in a `finally` right after the call, as in decision 1,
    so the call rows and the verbatim responses are committed whatever happens next. Their existing audit rows and the
    case data they write stay in the request transaction (a failed request must not leave half-written case data). The
    developer first reads any other request-time caller of the integration layer (`grep` for the recorder and for
    `NapixClient(` under `backend/aslms/api/` and `backend/aslms/services/`). Every such caller is either converted or
    listed in the report with the reason it is already safe. Callers that run in the worker already commit apart and are
    not changed.
    - Tests (scripted gateway): for each of the four routes, an unexpected error raised after the call (monkeypatched
      into the step that follows) → the request answers 500, and the `napix_call_log` row and the `napix_responses`
      row of that call are present in a fresh session; no case data from that request is committed.

10. **No migration, no new table, column or setting.** The head stays 0020. The responses keep their shapes. The only
    API changes are the two new refusal codes (decisions 6 and 7) and a 500, instead of a silent loss, for ASLMS's own
    defects after a call.
    - The portal gains the two messages in `frontend/src/lib/messages.ts`.
    - The endpoint docstrings name the new codes, so `frontend/src/lib/api/schema.d.ts` is regenerated
      (`npm run gen:api`). CI fails on drift.

## Data
**No table, no column, no reference code, no migration** (head 0020). `aslms_app` already has INSERT on
`napix_call_log`, `napix_responses` and `audit_log`, so the separate sessions need no grant. The classes, keys and FK
behaviour are unchanged.

The text for `docs/schema/schema.md`:

- The `ref_permission` row: append the clause of decision 9 (52 rows, 50 active, seed only).
- Add this to the end of the System health paragraph:

  > The test's `napix_call_log` rows and `napix_responses` row are committed in a session of their own as soon as the
  > call ends, and its `audit_log` row in another, so a failure later in the request loses neither; the request
  > transaction holds only reads and the advisory locks `napix-api-test:<key>` and `napix-api-test-user:<user>`. The
  > data-health connectivity check commits its rows the same way and takes `napix-api-test:overview`
  > (design `api-health-checker-followups`, no migration).

- Add this to the napix-window note on `napix_call_log`:

  > A token renewal is logged as two rows in the order they happened: the HTTP 401 step (`ok` false, `http_status`
  > 401, `error_family` NULL, `error` naming the renewal) and the repeated attempt with its own outcome; a renewal that
  > fails is recorded on the 401 row with its family. The System health rates leave the 401 step out
  > (`http_status = 401 AND error_family IS NULL`); the quota window and per-person counts include it
  > (design `api-health-checker-followups`).

## Services
- **`integration/napix/client.py` — `NapixClient._attempt`.** Decision 4.
  - On 401 with `refresh_token=True`: renew the token, then set `error` on the attempt and its `duration_ms`, emit it
    through the existing hook (the same guarded `try`/`log.exception` as the `finally`) and mark it `emitted`. Then
    return the repeated attempt.
  - The `except IntegrationError` and `except Exception` branches set `error`, `error_family` and `napix_status` only
    while `emitted` is false.
  - The `finally` sets `duration_ms` and calls the hook only while `emitted` is false.
  - `call()` and the token cache are unchanged.
- **`services/napix_store.py` — `NapixRecorder.flush_apart(session_factory: sessionmaker[Session]) -> int`.**
  Decision 1: `with session_factory() as s: n = self.flush(s); s.commit()`.
  - If it fails: log the non-secret fields of each pending attempt and re-raise.
  - The docstring names the runner's probe as the same pattern.
- **`services/audit.py` — `write_audit_apart(session_factory, actor, action, entity_type, entity_id, *, before=None,
  after=None, case_id=None) -> uuid.UUID`.** `write_audit` in a session of its own, committed; it returns the row's id.
  It is not a new kind of audit: the same row, the same append-only table.
- **`services/napix_api_check.py`.**
  - `run(session, session_factory, actor, user, settings, client, hc, key)`:
    1. `acting_member`, then `guard`;
    2. `lock_user(session, user_id)` (decision 6; skipped only when no user id, which an authenticated request never
       has);
    3. `lock(session, key)`;
    4. `_too_soon` and `_over_cap` checked again;
    5. the call inside `try/finally` with `recorder.flush_apart(session_factory)`;
    6. `last = attempts[-1]` (decision 4), the outcome as today, the summary in `try`;
    7. `write_audit_apart(...)` with `after` as today, plus `summary_error` only when set;
    8. re-raise a summary exception (decision 2), or return the outcome.
  - `lock_user(session, user_id)` raises `TestRefused("user_test_running", …, 409)`.
  - `_over_cap(session, settings, user, now)` is the per-person check moved out of `guard`, so `guard` and `run` share
    it.
  - `final_attempt` is deleted.
  - `_present` is replaced by `_date_present` (`napix_values.as_date`) and `_text_present` (decision 8).
  - The module docstring is updated: rows committed separately, the person lock, the renewal order.
- **`services/napix_admin.py`.**
  - `health_check(session, session_factory, actor, user, settings, client, hc)`:
    1. `acting_member`, then `check_guard`;
    2. the Overview lock (`CheckRefused("check_running", …, 409)`), then `check_guard` again;
    3. the call in `try/finally` with `flush_apart`;
    4. `last = attempts[-1]`, the outcome as today;
    5. `write_audit_apart(... "napix.health_checked" ...)`.
  - `CheckRefused`'s docstring lists `check_running`.
- **`services/system_health.py`.** `_COUNTED_SQL` (decision 5) in `_hourly`, `_day`, `_latest` and `_recent`.
  `ANSWERED_FAMILIES`, `card_status` and `plain_reason` are unchanged; the 401 wording stays for the data-health list.
- **Routers.**
  - `api/routers/system_health.py` `test_api` passes `request.app.state.session_factory`. Its docstring adds 409
    `user_test_running` and the 500 case: "the call and its audit row are recorded before the error".
  - `api/routers/napix_admin.py` `health_check` passes the factory. Its docstring adds 409 `check_running`.
- **Audit and events.** The same two actions as today, `napix.api_tested` and `napix.health_checked`, one row per call
  made. A refusal writes nothing. No event, no alert.
- **Visibility.** Unchanged. The sample label still names a case only when the caller may see it (row 109 decision 5),
  and nothing here reads case data for display.

## API
No new endpoint, no request or response shape change.

| Method and path | Function required (`Permission`) | Change |
|---|---|---|
| `POST /admin/system-health/napix/{api}/test` | `ADMIN_SERVICE_HEALTH` | New refusal 409 `user_test_running`. The per-person cap is checked again after the locks (429 `test_limit`). ASLMS's own failure after the call answers 500 with the call rows and the audit row already committed. `ApiTestOut` unchanged; `attempts` counts the 401 step and the repeat; `duration_ms` is no longer counted twice on a renewal. |
| `POST /admin/napix/health/check` | `ADMIN_NAPIX_REFETCH` or `ADMIN_MASTERS_SYNC` (`napix_operator`) | New refusal 409 `check_running`. A renewed success reads `ok: true`. Rows committed separately. `HealthCheckOut` unchanged. |
| `GET /admin/system-health` | `ADMIN_SERVICE_HEALTH` | Card counts, rates, bars, percentiles and last result leave out renewal steps. Shape unchanged. |
| `GET /admin/system-health/napix/{api}` | `ADMIN_SERVICE_HEALTH` | The same for the daily buckets and the last 10 calls. Shape unchanged. |

Visibility rule: unchanged (administrator functions; no case data in any of these answers).

Portal:
- `frontend/src/lib/messages.ts` gains `user_test_running: () => "Your other test is still running. Try again when it has
  finished."` and `check_running: () => "A connectivity check or a test of the connection is running. Try again in a
  moment."`.
- `schema.d.ts` is regenerated.

## Jobs
None. The queue runner is unchanged. It already commits its rows in its own sessions, and it gains the chronological
renewal order of decision 4 for free.

## Tests
All tests use the scripted gateway (`tests/unit/conftest.py` `Gateway`, `tests/db/conftest.py` `router`); none calls NAPIX,
and `NAPIX_ENABLED` is never set. Where needed, the tests patch `Settings.napix_configured` as row 109's tests do.

Unit (`backend/tests/unit/test_napix_client.py`):
- `test_renewal_logs_the_401_step_first`: 401, then an envelope → hook results `[401 step, answered]`. The step has
  `ok` false, `http_status` 401, `error_family` None and an `error` naming the renewal. The `called_at` values are
  ascending.
- `test_renewal_then_failure_is_logged_once`: `max_attempts = 1`, 401 then 503 → `[401 step (family None), 503
  NapixUnavailable]`. Exactly one row has a family, and `call` raises `NapixUnavailable`.
- `test_second_401_is_an_auth_error` (extended): the rows are `[401 step, 401 NapixAuthError]`.
- `test_failed_renewal_is_recorded_on_the_401_attempt`: the client's `token` is wrapped so the forced renewal raises
  `NapixAuthError` → one row, with `http_status` 401 and `error_family` `NapixAuthError`.
- `test_renewal_step_duration_excludes_the_repeat`: a transport that sleeps on the second call → the 401 step's
  `duration_ms` is below the repeat's.

Unit (`backend/tests/unit/test_system_health.py`):
- `test_next_date_sentinels_read_absent`: `summarise_payload("cnr", …)` with `date_next_list` set to `5000-01-01`,
  `1900-01-01`, `0000-00-00`, `""`, `None` or "Next Date Not Given" → "no"; with `2026-11-03` → "yes".
- `test_business_text_presence_is_a_text_check`.
- `test_final_attempt_after_a_token_renewal` is removed with the function.

Database, through the API (`backend/tests/db/test_api_system_health.py`):
- `test_token_renewal_counts_two_attempts` (updated):
  - the result reads `ok` true, `attempts` 2, `http_status` 200;
  - two call rows, in the order 401 then 200;
  - the card's `h24.calls` is 1 and `answered` 1, status `ok`;
  - the detail's last calls hold only the 200.
- `test_renewal_failure_counts_once`: 401 then 500 → the outcome is `down` with `NapixUnavailable`; the card's
  `h24.calls` is 1 and `answered` 0.
- `test_past_renewal_rows_are_not_counted`: logged rows (401 with a NULL family) plus 200 OK → `h24.calls` 1, rate 1.0;
  the last-three rule ignores the 401.
- `test_call_rows_survive_a_failure_after_the_call`:
  - `napix_api_check._summary` is patched to raise `RuntimeError`, and the request raises (500);
  - one `napix_call_log` row with the caller's `user_id` and one `napix_responses` row are committed;
  - an audit row `napix.api_tested` has `summary_error` "RuntimeError" and `summary` null;
  - the next test of that API answers 429 `test_too_soon`, with no call.
- `test_call_rows_survive_a_failed_audit`: `audit.write_audit_apart`, as used by the service, is patched to raise → the
  call row and the response row are committed, and there is no audit row.
- `test_a_person_runs_one_test_at_a_time`: another connection holds `napix-api-test-user:<root id>` → 409
  `user_test_running`, no gateway call, no audit row. After it is released, a test of a different API answers 200.
- `test_cap_checked_again_after_the_locks`: the cap is 1. A `napix.api_tested` row of the caller is committed between
  the guard and the locks (the test patches `lock_user` to insert it first) → 429 `test_limit`, no call.
- `test_request_transaction_writes_nothing`: after a successful test, the rows the request session itself added are
  zero. The test patches `get_session` to record `session.new` before the commit, or checks that the rows exist before
  the response returns. The developer picks the seam and names it in Deviations.
- The existing tests stay green: refusals in order, one call per API, no case data written, nothing personal or secret
  returned.

Database (`backend/tests/db/test_api_napix_admin.py`):
- `test_health_check_renewed_success_is_ok`: 401 then an envelope → `ok` true, `http_status` 200; the audit row's
  `attempts` is 2.
- `test_health_check_rows_survive_a_failed_audit`: `write_audit_apart` is patched to raise → one Overview row
  committed.
- `test_health_check_rows_survive_an_unexpected_error`: the client's call raises a `RuntimeError` (not an integration
  error) after the hook ran → the row is committed, and the request raises.
- `test_health_check_and_connection_test_exclude_each_other`: another connection holds `napix-api-test:overview` →
  the check answers 409 `check_running` with no call.

Frontend:
- `errorText` returns the two new messages. This goes in the test that already covers `errorText`
  (`src/server/api.test.ts`), or in a new `src/lib/messages.test.ts` if that file is not a natural home.

## Verification
The integrator runs:
1. `ruff check` (clean) and `pytest -q` (green; the new tests above included).
2. `alembic heads` → `0020` (no migration). `git diff --stat` shows no file under `backend/aslms/db/migrations/versions/`.
3. In `frontend`: `npm run gen:api`, then `git diff --exit-code -- src/lib/api/schema.d.ts` after commit. Also
   `npm test`, `npm run lint` and `npm run build`.
4. `docker compose build` succeeds, and the portal smoke test passes with `/system` included.
5. On the dev database, with `NAPIX_ENABLED` false:
   - `POST /admin/system-health/napix/state/test` as the super admin still answers 409 `napix_off`, with no call row and
     no audit row.
   - `GET /admin/system-health` answers in about the time it did before (row 109 measured 332 ms for `napix_cards`);
     the extra filter must not slow it materially.
6. `grep -n "approved_by" docs/design/api-health-checker.md` → exactly one line, `approved_by: owner on 2026-10-20`.
7. The `ref_permission` row of `docs/schema/schema.md` reads "52 rows, 50 active".
8. No live check is needed. The behaviour is proved with the scripted gateway. If the owner wants one, it is the owner's
   run with `NAPIX_ENABLED=true` for that run only, as in row 109's Verification step 6: one Connection test, then a
   look at the card.

## Open questions
None. Every decision is made.

The owner may, at approval and without reopening the note:
- drop decision 7 (the connectivity check's lock);
- change the wording of the two new messages.

Separately, two recommendations for the owner, not part of this item:
- a follow-up row giving the court search routes the same separate commit;
- the clearer wording of step 2 of the team-approve skill.

## Deviations
Written by the developer while building (21 Oct 2026).

1. **`POST /admin/data-load/fetch-details` makes no NAPIX call.** Decision 11 lists it among the request paths that
   call NAPIX, but it only queues `dossier` rows in the `request` lane; the worker makes the calls and commits its own
   rows. It is listed here as already safe and is not converted. Its test (`test_fetch_details_makes_no_court_call`)
   proves no gateway call and no call row; the "row survives an unexpected error" test covers the three routes that
   do call: `POST /cases/search-court`, `POST /cases/{ref}/fetch-court` and `POST /admin/data-load/fetch`.
2. **The inventory of request-time callers** (`grep` for `NapixRecorder(`, `NapixClient(` and `napix_client(` under
   `backend/aslms/api/` and `backend/aslms/services/`): the System health test (`napix_api_check.run`), the
   connectivity check (`napix_admin.health_check`) and the two `_with_napix` helpers in `api/routers/cases.py` and
   `api/routers/data_load.py`; all four are converted. The queue runner (`services/runner.py`) and the CLI
   (`aslms napix-check`, `aslms pipeline`) already commit in their own sessions and are unchanged.
3. **How the court routes commit apart.** In the court search the call and the case writes are interleaved inside
   the service (`court_search._finish` and the advocate search flush the recorder mid-way; the advocate search needs
   the response ids for its `search_rows` queue rows). Rather than change each call site, `NapixRecorder` takes an
   optional `session_factory`; when it is set (only by the two API `_with_napix` helpers), every `flush(session)`
   commits apart through `flush_apart`. `_with_napix` also calls `flush_apart` in a `finally` around the service call,
   so attempts still pending when an unexpected error escapes are kept. The case data, the queue rows and the audit
   row stay in the request transaction.
4. **`flush_apart` details.** It opens no session when nothing is pending, and it clears the pending attempts only
   after the commit, so a failed write leaves them pending (and named in the warning) rather than silently dropped.
5. **The connectivity check's lock** is `napix_admin.lock_check` with the constant `CHECK_LOCK =
   "napix-api-test:overview"`, the key `napix_api_check.lock(session, "overview")` takes. `napix_api_check` imports
   `napix_admin`, so the check cannot call `napix_api_check.lock` without an import cycle.
6. **The seam for `test_request_transaction_writes_nothing`**: `get_session` is replaced through
   `app.dependency_overrides` by a copy that reads `pg_current_xact_id_if_assigned()` just before the commit.
   PostgreSQL assigns a transaction id only on a write (reads and advisory locks do not), so NULL proves the request
   transaction wrote nothing.
7. **`test_health_check_rows_survive_an_unexpected_error`** wraps the client's `call` so that it raises a
   `RuntimeError` after the real call (and its hook) completed.
