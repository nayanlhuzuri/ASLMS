# Design: October follow-ups: NAPIX connections and failure counts, System health console, ownership and alert fixes, browser check, images

```
slug: followups-oct
status: awaiting-approval
author: architect
date: 2026-10-24
approved_by:
```

## Context
This is backlog row 137. It bundles eight follow-up rows left by recent reviews and merges. Each source row is marked
"merged into 137" in `docs/backlog.md`. The note keeps each item's source number, for example (114-1), so the
developer, tester and reviewer can trace it.

| Row | Source | Items |
|---|---|---|
| 113 | row 110 review | the data-health "failed today" count and failures list still count a token renewal's 401 step |
| 114 | row 110 review | (1) two connections from one pool per NAPIX request; (2) and (3) audit rows lost on an unexpected exception; (4) `response_ids` not reset |
| 126 | `docs/reports/2026-10-21-portal-ui-polish.md` | uicheck drops every finding on a redirect; `DataTable` measures on every render |
| 129 | `docs/reports/2026-10-22-system-health-inspector.md` | an unbounded payload read; party names 200 against 99; the full answer cached, so a reopening is not audited; `edited: false` confirms a hidden sample |
| 130 | `docs/reports/2026-10-22-ownership-refinements.md` | the backfill closes post-claim suggestions; the engine reads claimed state without the case lock; `session.get(..., None)` |
| 132 | owner observation, 22 Oct | an onnxruntime telemetry warning, believed to come from PyMuPDF 1.28.2 |
| 133 | 22 Oct upgrade | `migrate` ran an image older than the code |
| 134 | `docs/reports/2026-10-23-alerts-visibility-roles.md` | (1) remark hidden from a State-plus-department login; (2) 0022 re-apply; (3) a listing counted twice; (4) two order-sensitive discovery tests; uicheck fixtures and small buttons on the System health console |

What is in place (code read on 24 Oct 2026 at `main` 346265e):
- **Connections.** `db/session.get_engine` builds one SQLAlchemy `QueuePool` per process with the defaults: 5
  connections plus 10 overflow, so 15, and a 30 s pool timeout. `api` is one uvicorn process. Sync routes run in
  Starlette's thread pool, which has 40 threads. `api`, `worker` and `scheduler` reach Postgres through PgBouncer in
  transaction mode (`default_pool_size` 20, `max_client_conn` 200). The api's request session (`deps.get_session`)
  takes a connection at its first query, which is the user lookup in `require(...)`. It then keeps that connection
  until the request ends.
- **Apart writes.** These come from design `api-health-checker-followups`, decisions 1, 2, 3 and 11. On the request
  paths, `NapixRecorder` (built with `session_factory`) writes its call rows through `flush_apart`.
  `audit.write_audit_apart` does the same for its audit row. Both open a session of their own from
  `request.app.state.session_factory`. That is **the same engine, so the same pool**, as the request session. There
  are five request paths that call NAPIX, all through `deps.napix_client(request)`:
  - `POST /cases/search-court` and `POST /cases/{ref}/fetch-court` (`routers/cases._with_napix`);
  - the data-load single-case fetch (`routers/data_load`);
  - the connectivity check (`routers/napix_admin` → `napix_admin.health_check`);
  - Test now and the console send (`routers/system_health` → `napix_api_check`);
  - the token check (`routers/system_health` → `napix_token`).
- **Failure counts.** System health leaves a renewal's 401 step out of its rates (`system_health._COUNTED_SQL`:
  `http_status IS DISTINCT FROM 401 OR error_family IS NOT NULL`). Four other readers count every `ok = false` row:
  - `data_health.napix_health`: today's `failed`, `by_family` and `last_failure`;
  - `ops_metrics`: `aslms_napix_calls_last_hour{outcome="failed"}`, which feeds the `NapixErrorsHigh` alert;
  - `reports`: the data-health report's `napix_failed`, its families and the per-API `failed`.
- **PyMuPDF.** Version 1.28.2 is pinned `>=1.24,<2` (design `document-ocr`, decision 2).
  `tests/unit/test_dependencies.py::test_pymupdf_loads_no_neural_runtime` checks only that the Python module
  `onnxruntime` is not in `sys.modules` after `import pymupdf`.

Not covered:
- the `TokenCache`-per-request remark in the row 123 report (it was not raised as a row);
- the MIS screen (row 136);
- the owner's live and browser checks (rows 124, 128);
- CI adoption of uicheck (row 125).

**Overlap with row 135** (`case-workspace-admin`, approved). Row 135 also adds uicheck fixtures and changes `/files/*`
routes. Whichever of the two is built second rebases on the other's `frontend/e2e/fixtures/index.ts`. This note
touches only the System health fixtures.

## Decisions

### A. NAPIX call recording and database connections (114, 113)

1. **The fault (114-1), stated exactly.** A NAPIX request path holds its request connection, inside an open
   transaction, for the whole NAPIX wait. The client's timeout is 40 s per attempt, with retries and the per-process
   rate limiter on top. At every flush it then asks **the same pool** for a second connection. When 15 such requests
   run at once, all 15 pool connections are held by requests that each wait for a 16th. Nobody releases a connection,
   so each `flush_apart` fails after the 30 s pool timeout. The call rows survive only as the warning "napix call rows
   could not be written", which breaks "every call is logged". The same cycle can form one layer down, at PgBouncer.
   A request session that is idle in a transaction keeps its PgBouncer server connection. When all 20 server
   connections are held that way, an apart write queues at PgBouncer behind the very clients that wait for it.

2. **Fix part 1: a separate, small engine for apart writes.**
   - New `db/session.get_apart_engine(url)`, with `pool_size = DB_APART_POOL_SIZE` (default 3), `max_overflow = 0`,
     `pool_timeout = DB_APART_POOL_TIMEOUT_SECONDS` (default 10) and `pool_pre_ping`.
   - `create_app` puts `app.state.apart_session_factory` next to `session_factory`. When a test passes only
     `session_factory`, the apart factory is that same factory, so existing tests are unchanged.
   - Every `flush_apart`, every `write_audit_apart` and every `NapixRecorder(session_factory=...)` on a request path
     takes `apart_session_factory`.
   - Why this removes the cycle: an apart session holds nothing while it waits. It opens, writes one to three
     INSERTs, commits and closes in milliseconds. A writer waiting on the apart pool waits only for other short
     writes, never for a NAPIX holder.
   - Why size 3: with decision 3 at most 6 api requests hold a NAPIX wait at once. Each flushes once per attempt,
     and attempts are seconds apart. Three connections therefore cover the call rows and the apart audit rows with
     no measurable queue, which the load test in decision 5 checks.
   - Alternatives considered:
     - (a) A bigger main pool: this only moves the threshold.
     - (b) Committing the request transaction around each NAPIX call: the case data and its audit row must stay in
       one transaction (api-health-checker-followups, decision 11), and `court_search` interleaves reads, calls and
       writes.
     - (c) Writing the call rows into the request session: a later error loses them again, which is what
       decision 11 fixed.
     - (d) Writing apart rows directly to `postgres:5432`: this breaks the PgBouncer rule of row 78 and the role
       split.

3. **Fix part 2: per-process NAPIX request slots, waited for without a database connection.**
   - New `deps.napix_request(request, session)`, a context manager that yields `(client, hc)`. It replaces
     `napix_client(request)` at all five call sites. It takes a slot from a `threading.BoundedSemaphore(NAPIX_REQUEST_SLOTS)`
     on `app.state`, default 6.
   - Before waiting, it gives the request's connection back by committing the read-only transaction. It first checks
     that nothing was written, in two ways: `session.new`, `dirty` and `deleted` are empty, and
     `SELECT pg_current_xact_id_if_assigned()` is NULL. If either check fails, that is a defect: it raises
     `RuntimeError`, which a test catches. `expire_on_commit=False` keeps `user` and `actor` loaded.
   - It waits up to `NAPIX_REQUEST_WAIT_SECONDS` (default 20) for a slot. When no slot frees in time, it answers
     **503 `napix_busy`** with `Retry-After: 15` and the message "Court searches are busy; try again in a few
     seconds.". Like the guard's refusals ("a refused search writes nothing", court-search decision 13), it writes
     nothing and is not counted against the person's hourly searches.
   - After it takes a slot, the route **runs the guard again** (`court_search.guard`, `check_guard`, the System
     health guards), because the quota or the per-person count may have changed during the wait.
   - The slot is released in a `finally`, after the recorder's last flush.
   - Why this is needed although decision 2 breaks the cycle:
     - It bounds the connections held across NAPIX waits: 6 of the api's 15, which leaves 9 for every other page
       during a burst.
     - It makes the PgBouncer cycle impossible. At most 6 api holders, plus 1 worker item and 1 scheduler task, can
       be idle in a transaction during a NAPIX wait. That is far below 20, so an apart write always finds a server
       connection.
   - Limitation, written into the runbook: up to 40 sync requests share Starlette's thread pool. A burst of more than
     34 simultaneous searches would hold threads while waiting. The per-person hourly limit and the pilot's user
     count make that unlikely.
   - User-visible: the new 503 code. The Search page and the case page's Refresh show the message with the Retry-After
     countdown they already use for `napix_budget`.

4. **The connection budget, written down and checked.**
   - The budget is `NAPIX_REQUEST_SLOTS` (6) + 1 worker + 1 scheduler + `DB_APART_POOL_SIZE` (3) + a reserve of 4
     for short page transactions. That is 15, which must not exceed `PGBOUNCER_DEFAULT_POOL_SIZE` (20).
   - `aslms ops preflight` (component `init`) checks the formula against the variables. It reports an error at
     `APP_ENV=prod` (start refused) and a warning otherwise, and it names the variables, never their values.
   - The main pool stays at 5 + 10 with a 30 s timeout. Now it is set explicitly in `get_engine` and documented,
     not left to library defaults.
   - The runbook (section 18, new subsection "Connection budget") explains the formula, says that more uvicorn
     processes multiply the api terms, and says to raise PgBouncer's pool before raising the slots.

5. **The load test that justifies decisions 2 to 4.** There are two levels, both required:
   - (a) A database test, `tests/db/test_napix_connections_load.py`. It builds the app with a deliberately tiny
     main pool (`pool_size 3`, no overflow, `pool_timeout 3`), an apart pool of 1, 2 slots and a 2 s slot wait. It
     uses the scripted gateway, with every call held on a `threading.Barrier` so the calls really overlap. It fires
     12 concurrent `POST /cases/search-court` requests (four times the pool) from threads. It asserts that:
     - every request finishes within 30 s, with 200 or 503 `napix_busy`;
     - `napix_call_log` holds exactly as many rows as the gateway answered calls;
     - no "napix call rows could not be written" warning was logged;
     - the main pool's checked-out count never went above 3 (pool `checkout` and `checkin` events).
     A **control test** runs the old wiring: the apart factory is the main factory and there are 99 slots. With the
     same 12 requests it must hit the pool timeout and log the warning. This documents why the fix exists and fails
     if the cycle is ever brought back by accident.
   - (b) A read-only Compose check through PgBouncer, `aslms ops pool-check`. It builds engines exactly as `api`
     does, from the same settings, in its own process next to the running stack. It then simulates the load:
     - `--holders` sessions that open a transaction and sleep inside it (`SELECT pg_sleep(n)`), as a NAPIX wait
       does. The default is `NAPIX_REQUEST_SLOTS + 2`.
     - `--pages` short transactions per second.
     - `--apart` apart-style transactions (`SELECT 1`, committed). It writes no rows.
     It prints JSON: holders, pages and apart counts, p50 and max wait for an apart connection, max wait for a page
     connection, and timeouts. It exits 1 when any apart wait exceeds 1 s or any timeout occurs. The integrator runs
     it in Verification and records the numbers in the report.

6. **The audit rows of the System health actions are always written (114-2, 114-3).**
   - `napix_api_check` (Test now, console send): right after `flush_apart` it builds a minimal `after` from the
     attempts:
     - `api`, `path`, `attempts`, `http_status`, `napix_status`, `error_family`, `ok`, `params_sha256`.
     The outcome, structure, inventory diff and summary then enrich it inside one `try`. The `napix.api_tested` row
     is written in a `finally`. When an unexpected exception occurred, `after` carries `unexpected: "<ExceptionClass>"`
     (the class name only, never the text), and the exception is raised again after the write.
   - `napix_admin.health_check` gets the same shape. An exception that is not an `IntegrationError` or
     `httpx.HTTPError` is still recorded in `napix.health_checked` as `ok: false, unexpected: "<Class>"`, then raised
     again.
   - The audit write itself uses the apart factory (decision 2). If it fails, its own exception propagates. The call
     rows were already committed.

7. **`response_ids` always names the last flush (114-4).** `flush_apart` sets `self.response_ids = {}` before its
   `if not self.pending: return 0`. "The responses written by the last flush" is then also true for an empty flush.
   The advocate search reads the ids right after its own flush, before the route's final empty flush, so its
   behaviour is unchanged.

8. **One definition of "a counted call" (113).**
   - New in `domain/ops.py`: `renewal_step()` returns the SQLAlchemy condition `http_status = 401 AND
     error_family IS NULL`, and `COUNTED_CALL_SQL` is its negation as SQL text, the string `system_health` uses
     today. `system_health._COUNTED_SQL` is replaced by the import.
   - The renewal step stays in every **call count**. It is a request to the gateway, and the quota window and the
     per-person counts keep it (api-health-checker-followups, decision 5). It leaves every **failure** reading:
     - `data_health.napix_health`: `today.failed`, `today.by_family` and `last_failure` skip it;
     - `ops_metrics`: `aslms_napix_calls_last_hour` gains a third series, `outcome="renewal"`, and `failed`
       excludes it. `ok + failed + renewal` equals all calls, so the Grafana total is unchanged, and
       `NapixErrorsHigh` no longer counts renewals;
     - `reports`, data-health report: `napix_failed`, the families column and the per-API `failed` skip it, and
       `napix_calls` keeps it.
   - User-visible: the failed counts on the data-health screen, the data-health report and the Prometheus alert go
     down by the number of renewals.

### B. System health console (129, 134 uicheck part)

9. **The size is checked in the database before any payload is read (129-1).** `napix_inspect.latest_answer` reads
   `id, octet_length(payload::text) AS bytes`, as `console`'s full-answer path already does, and fetches `payload` only
   when `bytes <= HEALTH_RAW_MAX_BYTES`. When the payload is larger, `structure` and `inventory_diff` are `null` and a
   new field `response_too_large: true` is set. The card says "This answer is too large to outline here." The
   full-answer button is already refused with 413 for the same size. `ConsoleOut` and the generated types gain the
   field.

10. **The party-name rule matches court search (129-2).**
    - The console's `name` rule splits into `party_name` (3 to `napix_samples.MAX_PARTY` = 200 characters, the
      character set of `court_search.PARTY_NAME_RE`) and `advocate_name` (3 to 99, HC spec §6.8, unchanged).
    - A held party sample, which is capped at 200 by the sample picker, is now sendable unedited.
    - No NAPIX limit for party names is documented, and court search sends party names with no upper bound. The
      console therefore uses the sample cap rather than inventing a spec limit.

11. **Every opening of the full answer is read and audited (129-3).** The full-answer query in `Console.tsx` uses
    `staleTime: 0` and `gcTime: 0` and is fetched on each opening. Each opening then reaches the server and writes its
    own `napix.response_viewed` row, as the audit rule requires. The structure query keeps its cache.

12. **A typed value never confirms a hidden sample (129-4).** `napix_inspect.validate` compares the typed plain string
    with the held sample only when `held.case_visible` is true. When the held sample belongs to a case the sender
    cannot see, the typed form is always `edited: true`, labelled "The values in the form", with no source case. The
    answer and the audit row then say nothing about whether the guess matched. The no-body refusal 409
    `sample_hidden` (row 123 deviation 15) is unchanged.

13. **uicheck fixtures for the console (134).**
    - `frontend/e2e/fixtures/index.ts` gains `GET /admin/system-health/token` (a `NapixTokenOut` with a synthetic,
      non-secret token state) and `GET /admin/system-health/napix/{api}/console` (a `ConsoleOut` for `cnr`, with a
      held sample, a last send and a latest answer). Their shapes are taken from `frontend/openapi.json`, never
      guessed.
    - The fixtures use only synthetic values: a CNR-shaped string in the fixtures' existing synthetic pattern, never
      a real CNR.

14. **No small buttons outside rows on the console (134).** With the fixtures in place, the run of
    `data/uicheck/20261023-1522` found four size findings at 375 px on "/system (API card)": three `Copy` buttons
    (`CopyButton`, `size="sm"`) and the `HelpLink` "NAPIX documentation for this API" drawn as a small button. The run
    of `20261023-1455` adds the error state's small "Try again". Fixes:
    - `CopyButton` gains a `size` prop (default `sm`, so other callers are unchanged).
    - The console's answer toolbar (Copy, Download), the code blocks' Copy, `HelpLink` and the console error state's
      Try again use `md` (36 px) at every width.
    - No change to the kit's sizes or to the checker.

### C. Ownership (130)

15. **The backfill leaves post-claim suggestions open (130-1).** `ownership.close_claimed_backfill` adds the condition
    `NOT (Recommendation.origin = 'suggestion' AND Recommendation.created_at >= primary.claimed_at)`.
    - Decision 12(a) of `ownership-refinements` keeps a suggestion made after the claim open, for the target to claim
      as a watcher.
    - Engine recommendations created after a claim before row 120 are still closed. Closing those was the
      backfill's purpose, so a plain `created_at < claimed_at` cut-off would be wrong.
    - A repeat `--apply` now closes 0 when nothing else changed. The dry run prints the same counts.

16. **The engine takes the case lock before reading claimed state (130-2).**
    - `matching.apply_scores` starts with `SELECT id FROM cases WHERE id = :id FOR UPDATE`, the lock that
      `ownership._lock` takes, before it reads `recs`, `ever_owners` and `claimed`. A claim and an engine pass on one
      case are then serialised. The engine either sees the claim (no recommendation, `claimed_elsewhere` kept) or
      finishes first, in which case the claim's closing step closes what the engine opened.
    - Both engine loops (`matching.py` around lines 707 and 791) process cases in `Case.id` order, so two engine passes
      lock in one order. Postgres's deadlock detector remains the backstop: on `DeadlockDetected` the batch is rolled
      back and retried once, case by case.
    - Alternatives considered:
      - `SKIP LOCKED` was rejected: it would skip a case whose new cause-list entry should be scored, until the next
        pass.
      - Re-checking claimed state after the writes still leaves a window.

17. **No `session.get` with a null key (130-3).** `alerts._suggestion_event` returns early (`skipped_other`) when
    `target_recommendation_id` is missing, before `session.get`.

### D. Alerts and private records (134-1, 134-2, 134-3)

18. **Working bases are read per membership, never from the State-merged list (134-1).**
    - `visibility.visibility_bases` returns only `[("state", true)]` as soon as one membership is State-wide. That is
      right for sight, but four callers use the merged list to decide **work**, so a login with a State-wide
      membership and a working department membership loses its working basis:
      - `custody.shows_remark` (the remark is hidden);
      - `visibility.works_on_case` (the new-note and alerts paths in `alerts.py` around lines 1490 and 1805);
      - `calendar.working_condition` (My calendar is empty);
      - `workflow_common.acting_member`'s error choice (it says `not_working_on_case` when the real reason is the
        missing function).
    - New `visibility.working_names(session, user, case) -> set[str]`: the union over `basis_by_member` of each
      membership's names that are in `WORKING_BASES`.
    - New `visibility.working_condition_any(session, user)`: the OR of `member_working_condition` over all
      memberships.
    - `shows_remark(session, user, case)` returns true when `working_names` is not empty, else `"state" in bases and
      sees_private_all`. `works_on_case`, the calendar and the error choice use the new helpers.
    - Sight (`visible_case_condition`, `access_basis`) is unchanged.
    - User-visible: such a login now sees custody remarks, its own cases in My calendar and the working alerts, as a
      department-only login already does.

19. **0022 is not edited (134-2).** 0022 is applied, so the hooks and CLAUDE.md forbid editing it.
    - Re-applying it after a downgrade adds no `access_changed` event and writes a second `access.rule_changed` row.
      That cannot be undone, because audit is append-only. The owner has been told.
    - What this item delivers:
      - (a) Runbook section 6: a downgrade of a reference-data migration is a restore, not `alembic downgrade`.
        Re-applying writes its audit rows again.
      - (b) A helper, `aslms/db/migration_audit.py`, for the next reference-data migrations (the next free number
        after 0025, built by whichever row needs one). `audit_once(bind, action, key, ...)` writes an audit row only
        when no row with `after->>'migration_key' = key` and the same `action` exists after the latest
        `system.migrated` that went down past this revision. `event_key(migration, application_no, ...)` puts an
        application counter into event dedupe keys, so a real re-application raises its event once.
      - (c) A note in `docs/DB_STANDARD.md`'s migration section pointing to the helper. The DB standard text is the
        owner's: the line is proposed in this note and added only with approval.
    - No migration in this row.

20. **One listing per court item in the listed-for-tomorrow alert (134-3).**
    - `alerts._listed_pass` groups a case's rows by the key (`list_type`, trimmed upper-cased `court_no`, the item as
      printed: `printed_sr_no` or `sr_no`, trimmed).
    - When two sources give the same key, one is kept, preferring `napix` over `ghc_website` over `local_dir`.
      `Causelist.source` is joined for this.
    - `entries` and `entries_total` count distinct listings.
    - Rows with an empty `court_no` are never merged with each other or with others, so a doubtful match never hides
      a listing.
    - User-visible: the alert lists each court item once.

### E. Test hygiene (134-4)

21. **The two discovery tests select their row by ref.** `test_628_is_an_empty_done_row` and
    `test_a_malformed_cino_is_counted_not_stored` (`tests/db/test_discovery_run.py`) read the row the run processed
    by its `ref_no`, as `test_discovery_rules` does on main since b0d6be7, instead of `party_rows(...)[0]`. A check:
    the file passes 20 times in a loop with `-p no:randomly`, and the full suite passes twice.

### F. Portal and browser check (126)

22. **uicheck keeps every non-geometry finding on a redirect (126-1).**
    - `frontend/e2e/checks.ts` exports `GEOMETRY_KINDS`: `page-overflow`, `inner-scroll`, `off-screen`, `clipped`,
      `size`, `alignment` and `primary`.
    - The new pure function `kept(findings, redirected)` in `results.ts` drops only those kinds when the page
      redirected. `missing-fixture`, `not-get`, `console-error` and `page-error` raised before or after the redirect
      are kept, written to the result file and fail the test.

23. **`DataTable` measures when its data changes, not on every render (126-2).**
    - The layout effect in `useFitTable` gets dependencies: the `rows` array, which is stable under React Query's
      structural sharing when the data is unchanged, and a string of the column keys.
    - The `ResizeObserver` on the box and the fonts-ready pass stay.
    - Alternatives considered: comparing only the row and column counts was rejected, because a refetch with the same
      counts and longer text would not re-measure.

### G. Images and deployment (132, 133)

24. **No onnxruntime is in the ASLMS images. The row's premise is corrected (132).** Measured on 24 Oct 2026:
    - The host venv's PyMuPDF 1.28.2 (`backend/.venv/Lib/site-packages/pymupdf`: `_mupdf.pyd`, `mupdfcpp64.dll`,
      `_extra.pyd`, `mupdf-devel`, all `.py`) contains neither "onnx", "onnxruntime", `OrtGetApiBase` nor
      `telemetry_1ds`.
    - In the `aslms-api` image, PyMuPDF 1.28.2 (`libmupdf.so.28.2`, `libmupdfcpp.so.28.2`, `_mupdf.so`,
      `_extra.so`) contains none of them.
    - A scan of every file in the `aslms-worker` image (14,119 files, excluding `/proc`, `/sys` and `/dev`) finds
      "onnxruntime" only in the dpkg status text (libc6's `Breaks` list) and in the pyproject comment.
    - The logs of the running `api`, `worker`, `scheduler`, `backup`, `init` and `clamav` containers hold no
      onnxruntime line.
    - So PyMuPDF 1.28.2 loads no model and has no embedded runtime. `telemetry_1ds.cc` is onnxruntime's Windows
      telemetry, which suggests a Windows process on the host printed the line into the terminal, not a container.
      Verification step 9 settles where it came from.
    - The rule "no local model" is met. The pin stays `>=1.24,<2`. Pinning one release exactly was rejected, because
      the guards below catch an onnxruntime in any future 1.x.

25. **Guards that fail if an onnxruntime ever arrives (132).**
    - (a) New `tests/unit/test_no_local_model.py`, with three tests:
      - no installed distribution's name matches `onnxruntime*`, `pymupdf-layout`, `pymupdf4llm` or `pymupdf_layout`
        (`importlib.metadata`);
      - no file in the installed `pymupdf` package (native libraries included) contains the bytes `onnxruntime`,
        `OrtGetApiBase` or `.onnx`. This catches a runtime linked statically into MuPDF, which a `sys.modules` check
        cannot see;
      - a subprocess opens a stored-style test PDF, extracts text and tables (`page.get_text`, `page.find_tables`),
        and with C-level stderr (fd 2) captured asserts:
        - no "onnxruntime" in the captured output;
        - `'onnxruntime' not in sys.modules`;
        - on Linux, no `/proc/self/maps` line naming `onnxruntime`.
      This is "fails if onnxruntime initialises a model".
    - (b) `aslms ops preflight` gains the check `no_local_model` (the same distribution and byte scans, about 0.3 s
      over 55 MB). It is **fatal at every `APP_ENV`**, like the libpq floor: `preflight fatal: no_local_model:
      onnxruntime found in <file>`. The images are guarded where they run, not only where tests run, because the tests
      are not in the image.
    - The existing `test_pymupdf_loads_no_neural_runtime` stays.

26. **`migrate` refuses an image built from code other than the code on disk (133).**
    - An image cannot know that a newer one exists, and `api` is stopped while `migrate` runs, so the comparison is
      with the source tree the image was built from.
    - Compose mounts `./backend:/src:ro` into `migrate`.
    - `aslms ops migrate` first runs `image_matches_source()`. It hashes the running code (the imported `aslms`
      package's directory) and `/app/migrations`, and compares them with `/src/aslms` and `/src/migrations`:
      - SHA-256 over sorted relative paths and file bytes;
      - `__pycache__` and `*.pyc` are skipped, as `backend/.dockerignore` does.
    - On a difference it exits 5 before any backup or connection-count check, with the message: "migrate: this image
      was built from other code than ./backend (image migrations up to 0022, ./backend up to 0023; aslms package
      differs). Build it: `docker compose build && docker compose --profile ops build migrate`, then run migrate
      again."
    - When `/src` is absent or empty (a pilot loaded with `docker load` and no source tree), it prints "migrate: no
      source tree to compare; this image's newest migration is 0022" and continues.
    - There is no override flag. An old image never has a reason to migrate.
    - `aslms ops restore`, which also runs in the `migrate` service, is not gated: a restore must work with the image
      at hand.
    - Alternatives considered:
      - (a) Sharing the api's image in `migrate` (`image:` without `build:`): image names follow the Compose project
        name, so they differ in worktrees and CI, and a shared fixed name would let parallel worktrees overwrite each
        other's images.
      - (b) Comparing with a stamp that `init` writes: `init` runs after `migrate` in the upgrade, so it records the
        old build.
      - (c) Keeping only the runbook step: that is what failed on 22 Oct.
    - The runbook's step 1 (on main since 22 Oct) stays. The `docker save` list keeps `aslms-migrate`.

## Data
None.
- No table, column, index or reference code is added or changed, and `docs/schema/schema.md` is unchanged.
- **No migration.** Decision 19's helper is for future migrations, which would take the next free number after 0025.
- Configuration only, in `core/config.py` and `.env.example`, each documented in the runbook:
  - `DB_APART_POOL_SIZE` (3, 1 to 10);
  - `DB_APART_POOL_TIMEOUT_SECONDS` (10, 1 to 60);
  - `NAPIX_REQUEST_SLOTS` (6, 1 to 30);
  - `NAPIX_REQUEST_WAIT_SECONDS` (20, 0 to 60).

## Services
- `db/session.py`: `get_apart_engine`, `get_apart_sessionmaker`, and explicit main-pool arguments (5, 10, 30 s)
  (decisions 2 and 4).
- `services/napix_store.py`: `flush_apart` resets `response_ids` first (7). Its callers pass the apart factory (2).
- `services/audit.py`: `write_audit_apart` unchanged. Its request-path callers pass the apart factory.
- `services/napix_api_check.py`, `services/napix_admin.health_check`: the minimal `after`, the audit in `finally`
  and `unexpected` (6).
- `services/court_search.py`: `CourtSearchBusy(CourtSearchFailure)`, code `napix_busy`, HTTP 503, `retry_after` 15
  (3).
- `domain/ops.py`: `renewal_step()`, `COUNTED_CALL_SQL`. Readers: `system_health`, `data_health`, `ops_metrics`,
  `reports` (8).
- `services/preflight.py`: `connection_budget` (an error in prod, a warning otherwise) and `no_local_model` (fatal)
  (4, 25).
- `services/ops_pool_check.py` with CLI `aslms ops pool-check [--holders N] [--pages N] [--apart N] [--seconds N]`:
  read-only (`SELECT 1`, `pg_sleep`), no audit row because it changes no data (5b).
- `services/napix_inspect.py`: `latest_answer` size first (9), the `party_name` / `advocate_name` rules (10),
  `validate` and `case_visible` (12).
- `services/ownership.close_claimed_backfill` (15), `services/matching.apply_scores` and both loops (16),
  `services/alerts._suggestion_event` (17), `alerts._listed_pass` (20).
- `services/visibility.py`: `working_names`, `working_condition_any`. Callers: `custody.shows_remark` (new
  signature), `works_on_case`, `calendar.working_condition`, `workflow_common.acting_member` (18).
- `db/migration_audit.py`: `audit_once`, `event_key` (19b).
- `services/ops_migrate` (or wherever `aslms ops migrate` lives in `cli/ops.py`): `image_matches_source()` (26).

Audit and events: no new action codes. `napix.api_tested` and `napix.health_checked` gain the optional key
`unexpected`. `napix_busy` writes nothing, like the guard's refusals.

## API
No new endpoint. Changes to existing ones:

| Method and path | Permission | Change |
|---|---|---|
| `POST /cases/search-court` | `cases.search_court` | may answer 503 `napix_busy` with `Retry-After: 15`; guard re-run after the slot |
| `POST /cases/{ref}/fetch-court` | `cases.search_court` (as today) | same |
| `POST /admin/data-load/fetch` | `admin.data_load` (as today) | same |
| `POST /admin/napix/health/check` (the connectivity check) | `admin.napix_refetch` or `admin.masters_sync` (as today) | same; audit row always written (6) |
| `POST /admin/system-health/napix/{api}/test`, the console send, `POST /admin/system-health/token/check` | `admin.service_health` | same; audit row always written (6) |
| `GET /admin/system-health/napix/{api}/console` | `admin.service_health` | `latest_answer.response_too_large` (bool) added; structure null when too large (9) |
| console validation (preview, send) | `admin.service_health` | party names up to 200 characters (10); `edited` always true against a hidden sample (12) |
| `GET /admin/data-health` | as today | `napix.today.failed`, `by_family`, `last_failure` exclude renewal steps (8) |
| `GET /reports/data-health` and exports | as today | failure columns exclude renewal steps (8) |
| `GET /cases/{ref}/custody`, case card | `cases.view` (as today) | remark shown to a login that works on the case through any membership (18) |
| `GET /me/calendar` | as today | includes working cases of every membership (18) |

Visibility rules are unchanged except where decision 18 corrects them. `frontend/openapi.json` and `schema.d.ts` are
regenerated for `response_too_large`. The portal's error messages add `napix_busy`.

## Jobs
None new. The worker and scheduler keep their main pools. The runner's window probe is unchanged. The listed pass
(decision 20) and the engine (decision 16) change inside existing jobs.

## Tests
Backend, database (`tests/db`):
- `test_napix_connections_load.py`:
  - `test_twelve_searches_on_a_pool_of_three_lose_no_call_row`;
  - `test_old_wiring_starves_and_warns` (the control);
  - `test_busy_answers_503_after_the_wait_and_writes_nothing`;
  - `test_guard_runs_again_after_the_slot`;
  - `test_slot_refuses_a_session_that_has_written` (`RuntimeError`).
- `test_napix_api_check_audit.py`:
  - `test_exception_in_summary_still_writes_api_tested`;
  - `test_exception_in_structure_still_writes_api_tested_with_unexpected`;
  - `test_health_check_unexpected_exception_writes_health_checked`.
- `test_data_health_renewals.py`:
  - `test_renewal_step_counts_as_call_not_failure` (today, by_family, last_failure);
  - `test_report_failures_skip_renewals`;
  - `test_ops_metric_has_renewal_series_and_total_is_unchanged`.
- `test_system_health_console_followups.py`:
  - `test_latest_answer_over_limit_reads_no_payload` (spy on the payload SELECT);
  - `test_held_party_sample_of_150_chars_is_sendable_unedited`;
  - `test_advocate_name_still_capped_at_99`;
  - `test_typed_value_equal_to_hidden_sample_is_edited`.
- `test_ownership_followups.py`:
  - `test_backfill_keeps_post_claim_suggestion_open`;
  - `test_backfill_still_closes_post_claim_engine_rows`;
  - `test_repeat_apply_closes_zero`;
  - `test_engine_waits_for_claim_lock` (two sessions: claim holds the lock, the engine blocks and then sees the
    claim; no engine recommendation, `claimed_elsewhere` kept);
  - `test_engine_passes_lock_in_case_id_order`;
  - `test_suggestion_event_without_target_is_skipped_without_warning` (`-W error::sqlalchemy.exc.SAWarning`).
- `test_state_plus_department_login.py`:
  - `test_remark_shown_to_state_and_department_login`;
  - `test_remark_hidden_from_state_only_login_without_view_private_all`;
  - `test_my_calendar_lists_department_cases`;
  - `test_works_on_case_true_through_department_membership`;
  - `test_missing_function_says_forbidden_not_not_working`.
- `test_alerts_listed_tomorrow.py` additions:
  - `test_same_listing_from_pdf_and_napix_counted_once_napix_kept`;
  - `test_rows_without_court_no_are_not_merged`.
- `test_migration_audit_helper.py`:
  - `test_audit_once_writes_once_per_application`;
  - `test_event_key_differs_after_a_downgrade_and_reapply`.
- `test_discovery_run.py`: the two tests changed (decision 21).

Backend, unit (`tests/unit`):
- `test_napix_store.py::test_empty_flush_apart_resets_response_ids`.
- `test_routes_use_napix_request.py`: no router calls `napix_client(` outside `deps.napix_request`.
- `test_connection_budget.py`: the defaults satisfy the formula; preflight reports a budget over
  `PGBOUNCER_DEFAULT_POOL_SIZE` (an error in prod, a warning in dev).
- `test_no_local_model.py`: the three tests of decision 25a, plus a test that preflight's `no_local_model` is fatal
  when a fake distribution named `onnxruntime` is on the path.
- `test_migrate_source_check.py`:
  - identical trees pass;
  - a file only in `/src/migrations` gives exit 5 with both heads named;
  - a changed `aslms` file gives exit 5;
  - a missing `/src` continues with the note;
  - `__pycache__` is ignored.
- `test_compose.py`: `migrate` mounts `./backend:/src:ro`.
- Prometheus: `infra/prometheus/rules.test.yml` gains a case where 150 renewals and 10 failures do not fire
  `NapixErrorsHigh`. Run with `promtool test rules`.

Frontend (`vitest`):
- `data.test.tsx`:
  - `fitTable runs once for unchanged rows across re-renders`;
  - `fitTable runs again when rows change`.
- `Console.test.tsx`:
  - `each opening of the full answer fetches again`;
  - `too-large answer shows the note`;
  - `Copy, Download, Help and Try again are md`.
- `search.test.tsx`: `napix_busy shows the busy message with the countdown`.

uicheck (Playwright, `frontend/e2e`):
- `uicheck-self.spec.ts`:
  - `kept drops only geometry kinds on a redirect`;
  - `kept keeps everything without a redirect`.
- With the new fixtures, "/system" and "/system (API card)" have no findings at 375, 768 and 1280 px.

## Verification
The integrator, on `feature/followups-oct`:
1. `ruff check .` clean. `pytest -q` with `ASLMS_TEST_REQUIRE_DB=1` green, run twice (decision 21). Frontend `npm test`
   and `npm run build` green. `promtool test rules infra/prometheus/rules.test.yml` passes.
2. `docker compose build` **and** `docker compose --profile ops build migrate`, then `docker compose up -d --wait`.
3. **Load check through PgBouncer:** `docker compose exec api aslms ops pool-check --holders 8 --pages 20 --apart 200
   --seconds 30`. Expected: `timeouts: 0` and an apart max wait under 1000 ms, exit 0. Record the JSON in the report.
4. `docker compose exec api aslms ops preflight` prints no `connection_budget` and no `no_local_model` finding.
5. `curl` (signed in as the super admin, through the BFF or with a token) `GET /admin/data-health`: `napix.today.failed`
   equals `SELECT count(*) FROM napix_call_log WHERE called_at >= <IST midnight> AND NOT ok AND NOT (http_status = 401
   AND error_family IS NULL)`.
6. uicheck: `docker compose --profile uicheck run --rm uicheck`. Expected: `findings.json` is `[]`, including "/system"
   and "/system (API card)" at all three widths.
7. Migrate refusal: change one comment in a file of `backend/aslms` without rebuilding, then run
   `docker compose --profile ops run --rm migrate`. Expected: exit 5 with the message of decision 26, and no backup
   file written. Revert the change and rebuild, then rerun. The guard passes and migrate continues to its
   connection-count check: stop the app first, as runbook section 6 says, or accept its refusal there. Do not apply
   anything to the dev database beyond what the owner has approved. The dev database's revision is unchanged by this
   row, which has no migration.
8. `aslms close-claimed-recommendations` (dry run) after the change prints `closed: 0` on the dev database when the
   backfill was already applied, and leaves any post-claim suggestion open.
9. **Where the onnxruntime line comes from:** `docker compose up -d --force-recreate api worker scheduler`, then
   `docker compose logs --no-color api worker scheduler | grep -c onnxruntime`. Expected: 0. If the owner's terminal
   still shows the line, it is printed by a host process, not ASLMS. Record which in the report and in the decisions
   log.

## Open questions
Each question has a recommended answer, and this note is written on that answer. Approving the note accepts the
recommendations unless the owner chooses otherwise, so none of them leaves a decision unmade.

1. **When every court-search slot is in use, wait or refuse at once?** (decision 3) Recommended: wait up to 20 s
   without holding a database connection, then answer "Court searches are busy; try again in a few seconds" (503,
   retry after 15 s). The refusal does not count against the person's hourly searches. Six slots per api process.
2. **A listing held on both the website PDF list and the NAPIX list: which copy does the listed-for-tomorrow alert
   show?** (decision 20) Recommended: one listing, the NAPIX copy. A row with no court number is never merged.
3. **A future PyMuPDF that brings onnxruntime: stop the start or only warn?** (decision 25) Recommended: stop the
   start at every `APP_ENV`, because the "no local model" rule has no exceptions.
4. **`migrate` refusal: any difference in the code or only in migrations?** (decision 26) Recommended: any difference
   in `aslms/` or `migrations/`. The 22 Oct failure was a missing function (`admin.service_health`) as well as a
   missing migration.
5. **Token renewals in the counts** (decision 8). Recommended: they stay in "calls" (they reach the gateway and use
   quota) and leave "failed" everywhere, as System health already does.
6. **The DB standard line on migration audit rows** (decision 19c). Recommended: add one sentence to the migrations
   section of `docs/DB_STANDARD.md`: "A reference-data migration writes its audit rows and events through
   `aslms/db/migration_audit.py`, so that a re-application after a downgrade is recorded once and raises its events
   again".
