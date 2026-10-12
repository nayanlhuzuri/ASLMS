# Design: NAPIX quota window detected, not assumed; the user behind each NAPIX call

```
slug: napix-window
status: approved
author: architect
date: 2026-10-11
approved_by: owner (nayanlhuzuri) on 2026-10-12
```

## Context
Owner's request of 11 Oct 2026, backlog row 47. It is built before row 12 (`portal-cases`).

**Evidence.** The call log of 1–11 Oct (48,830 rows) shows the following:
- **The reset is not on the hour.** `X-RateLimit-Remaining` jumps back to 999 once an hour. In every window
  where calls were made just before and just after the reset, the jump falls between HH:33:18 and HH:34:53 IST.
  Some 11 Oct examples: 00:34:28, 02:34:53, 04:34:30, 10:33:30, 12:34:30, 14:33:27, 16:34:53 and 18:33:28. This is
  neither the IST clock hour nor the UTC clock hour (HH:30 IST).
- **Why half the windows are lost.** The worker runs in a UTC container. When the budget is spent, it sleeps
  until the next UTC hour (`queue_worker`: `(60 - now.minute) * 60`). The runner seeds its remaining count from
  `date_trunc('hour', now())`. So at HH:30:0x IST the first call finds the *old* window with 148 calls left. The
  worker then sleeps a full hour and misses the reset four minutes later.
- **Measured cost.** The log shows `HH:30:06 148 → HH+1:30:06 999` (a 3,600 s gap) every second hour. Windows
  from HH:34 to HH+1:34 on 11 Oct alternate between about 820–950 calls and about 230–240 calls (the 4 minutes
  from HH:30 to HH:34 spent at the 60-a-minute local ceiling). The last 24 h averaged 548 calls an hour, against
  roughly 850 possible.
- **Why the 1 Oct measurement went wrong.** It (notes §6, `aslms napix-probe-rate`, 13:08–13:20) saw no reset in
  12 minutes and concluded "reset on the hour". The reset came at about 13:34, after the probe had ended.
- **Noise.** Inside a window the count sometimes goes *up* by 1–2 (for example 512 → 513 at the same
  `called_at`). The cause is that `called_at` is the flushing transaction's `now()`, so all calls of one queue
  item share one timestamp. Concurrent API calls also interleave. A reset can therefore only be recognised as a
  large jump.

**Plan basis.** §3 and §6.1 call for "retry, rate-limit and error handling so that a failed call is retried and
logged, never lost". §5.10 calls for "Data collection health: status of the daily data cycle, and any failed API
calls". This item corrects how the rate limit is honoured. It is not a plan change.

**In place.**
- The integration layer reads both rate headers (`RateLimiter`, `client.py`). At 0 remaining it waits a whole
  `NAPIX_RATE_WINDOW_SECONDS`.
- `NapixRecorder` writes `napix_call_log.rate_limit_remaining` and `lane` (data-load-console, migration 0014).
- The runner's budget bands are from data-load-console decision 4: load at 150 or more remaining, daily and
  request work at 100 or more, searches at 50 or more.
- These all use the clock hour: `court_search.latest_remaining_this_hour` and `seconds_to_next_hour`, the
  connectivity-check guard (audit-screens decision 10), the health block's "hour" (audit-screens decision 5), and
  the console's allowance card (data-load-console decision 7).
- The call log records the lane but not the person. People's searches are traceable only through `audit_log`.

**This item**
- Detects the window from the remaining count.
- Waits for the expected reset plus a margin, and probes every few minutes when the reset is late or the timing
  is not known.
- Bases every budget band, refusal and "this hour" figure on the detected window.
- Shows the window on the console and the health screen.
- Records the user who caused each call, with calls by user on the health screen.
- Corrects `docs/napix_integration_notes.md`.

**Not covered**
- Redis hardening for the shared token: row 16, added by the owner on 11 Oct.
- Spending the reserve in the last minutes of a window (decision 12).
- Applying 0014 or 0015 to the dev database and restarting the worker. The integrator does this (see
  Verification). The running worker still writes `lane` NULL: 0 load-lane calls in the last 24 h.

## Decisions
1. **A reset is a jump of the remaining count, not a time on the clock.** Readings are the call-log rows that
   carry `rate_limit_remaining`, ordered by the attempt's real time.
   - A reading is a **reset** when its count exceeds the previous reading by at least `NAPIX_WINDOW_RESET_JUMP`
     (new setting, default 50). The observed 1–2 upticks never come close, and the smallest real jump seen is
     370 → 999.
   - Jumps less than a quarter window (15 min) apart are one reset, timed by the first of them. This covers an
     in-flight call answered across the boundary.
   - A reset is **precise** when the previous reading is at most 300 s older (`PRECISE_GAP`, a module constant).
     Otherwise it only says that a new window has begun since the previous reading.
   - Alternatives considered:
     - The client tracks resets in memory. Rejected: each runner pass opens a new client, so the state is lost.
       The API and the worker are separate processes.
     - A Redis key. Rejected: Redis is not a source of truth, and the token is all it should hold (row 16).
2. **The phase comes only from precise resets.** The anchor is the latest precise reset in the last 6 hours
   (`LOOKBACK`, a module constant). S is the latest reset of any kind.
   - The expected next reset is E = anchor + k × `NAPIX_RATE_WINDOW_SECONDS`, for the smallest k with E later
     than S + half a window.
   - Without an anchor, E is unknown.
   - Alternatives considered:
     - E = S + window from imprecise resets. Rejected: S is then the time the worker woke, so each window would
       drift later by the margin until a window is missed.
     - Intersecting the brackets of imprecise resets. Rejected: the brackets are about 40 minutes wide in this
       pattern, so the intersection tells nothing.
   - The window length stays the setting (3,600 s). The 10 days of data agree with it: the same minute every
     hour. Verification checks it again.
3. **Four states, computed by one pure function** `napix_window.assess(readings, now, cfg)`. The function
   returns `WindowState` (fields in API).

   | status | when | remaining used by the guards |
   |---|---|---|
   | `current` | E is known and now < E + `NAPIX_WINDOW_MARGIN_SECONDS` | the latest reading |
   | `reset_due` | E is known, now ≥ E + margin, and no reading since E | unknown (`None`) |
   | `overdue` | E is known, now ≥ E + margin, and a reading after E showed no jump | the latest reading if younger than `NAPIX_WINDOW_PROBE_SECONDS`, else unknown |
   | `unknown` | no anchor in the last 6 h | the latest reading if younger than the probe interval, else unknown |

   An unknown remaining means "the next call will tell". The guards allow work then, as they allow a fresh hour
   today. A reading older than one window is never used. This follows from E: S lies in the lookback, so E
   passes within one window.
4. **The runner waits for the reset, not for the clock hour, and probes only when it must.** Each pass reads
   the state.
   - **When the remaining count is unknown.** If runnable work is waiting (`queue.has_runnable`, which uses the
     same pause clause as `claim`), the runner first makes one **probe**. The probe is a single Overview call
     through the integration layer, logged like any call: lane NULL, user NULL, the pass's `job_run_id`. The
     runner then re-reads the state.
   - **When the bands block every claimable row** (decision 4 of data-load-console, unchanged), the pass stops
     with `resume_at`. In state `current` that is E + margin. In `overdue` or `unknown` it is the latest reading
     plus the probe interval.
   - **The worker sleeps until `resume_at`.** When only the load lane is blocked and daily or request rows may
     still arrive, it sleeps the shorter of `resume_at` and its idle time.
   - **Counts.** At most one probe per pass. Expected cost: about one probe a window when anchored, at most one
     every 3 minutes while overdue or unknown.
   - Alternatives considered:
     - Run the next queue item as the probe. Rejected: a cause-list day is many calls, and they would come out of
       the old window below the reserve.
     - Probe continuously instead of predicting. Rejected: about 15 probe calls a window, and the owner asked
       for a wait until the expected reset.
5. **Defaults: margin 60 s, probe interval 180 s.** These are new settings, validated as 0 ≤ margin ≤ 600 and
   60 ≤ probe ≤ 300. The probe interval is capped at `PRECISE_GAP`, so consecutive probes always time a reset
   precisely.
   - **Why the exact values hardly matter.** The load spends its share of a window (about 850 calls at the local
     60-a-minute ceiling) in about 15 minutes. Waking a few minutes late costs no allowance. Only missing a whole
     window does.
   - **Owner check:** 60 s and 180 s.
6. **Every guard and figure uses the window.** `court_search.latest_remaining_this_hour` and
   `seconds_to_next_hour` are replaced by `napix_window.current(session, settings, now)` in these places:
   - the court-search guard (cases-api decision 13);
   - the connectivity-check guard (audit-screens decision 10);
   - the runner's seed (data-load-console decision 4);
   - the health NAPIX block (audit-screens decision 5);
   - the console's allowance card (data-load-console decision 7).

   A `napix_budget` refusal's `retry_after` is the seconds to E + margin in state `current`, and the probe
   interval otherwise. "This hour" figures become "this window": calls and failures since S, and calls by lane
   since S. The estimate is unchanged: its `calls_per_hour` is a rolling 24-hour rate and its `no_recent_calls`
   is a rolling 60 minutes, so neither depends on the clock. This revises the cited decisions; it is not a plan
   deviation.
7. **The real time of each attempt is logged.** `NapixResult.called_at` is set in `NapixClient._attempt`, after
   the local limiter's wait and before the request. `NapixRecorder.flush` writes it to
   `napix_call_log.called_at`, falling back to `now()` when it is missing. Ordering readings by the time a
   transaction started puts calls out of order, and can shift a reset seen during a long item by the item's
   duration. No column changes.
8. **The integration layer stops sleeping a whole window at 0 remaining.** `RateLimiter._header_delay` waits
   `min(window_seconds, zero_wait_seconds)` at 0 remaining. `zero_wait_seconds` comes from
   `NAPIX_WINDOW_PROBE_SECONDS` through `from_settings`.
   - A runner pass holding a `running` row would otherwise sleep through the reset, which is the same defect.
   - The pacing under 10 % remaining (window ÷ remaining per call) stays. It only applies below 100 remaining,
     where the bands already limit work to the daily cycle, requests and searches.
9. **Calls by user: `napix_call_log.user_id`.** The user is recorded as follows:
   - **Court searches.** A person's court search and fetch (`POST /cases/search-court`,
     `POST /cases/{ref}/fetch-court`, `POST /admin/data-load/fetch`) use `NapixRecorder(user_id=user.id)`.
   - **The connectivity check.** `POST /admin/napix/health/check` records its caller the same way.
   - **Queue rows a person asked for.** These are `request`-lane rows: re-fetch buttons and their CLI forms
     (super admin's id, or NULL for the `system` actor), "fetch details" of found cases, and the order PDFs a
     person's search queues. They carry the person in the new `fetch_queue.requested_by`. The runner copies it
     into the recorder for that item, and spawned rows inherit it through `QueueOrigin.requested_by`.
   - **System work.** Daily and load lane calls, probes and CLI checks carry no user. Who started a load is
     already in `audit_log` (`data_load.started`).
   - Alternatives considered:
     - Attribute the load to the admin who started it. Rejected: about 850 calls an hour under one name would
       hide the people the screen is for.
     - Infer users from audit rows. Rejected: an audit row does not say which calls it caused.
   - Past rows stay NULL.
10. **`requested_by` follows the row's pending run.**
    - **Enqueue.** On insert, revive or requeue, the row takes the caller's value, which is NULL for system
      callers. While the row is pending or running it keeps the first person: `COALESCE(existing, new)`.
    - **Only request-lane rows carry a person.** CHECK `ck_fetch_queue_requested_by` enforces
      (`requested_by IS NULL OR lane = 'request'`). Lanes only ever move towards `request` (LEAST), so the
      constraint holds through every enqueue.
    - **`retry-failed`** passes no person, because it may revive load rows.
11. **Who sees user attribution.** The `by_user` block of the health snapshot, the user fields of
    `GET /admin/napix/calls` and its `user_id` filter are given only to holders of `admin.napix_refetch` or
    `admin.masters_sync` (the NAPIX operators, super admin by default).
    - A reader who holds only `reports.state` gets `by_user: null` and null user fields. The `user_id` filter
      answers that reader 403 `forbidden`.
    - Reason: names next to call times show who searched when. `audit_log`, which records what they searched,
      is limited to the super admin and the Auditor type, so the call log should not reveal more widely who was
      searching.
    - The snapshot's docstring changes accordingly: one block now depends on the caller.
12. **Not now: letting the load spend the reserve just before the reset.** Calls left at a reset are lost, and
    the reserve's 150 often is. A rule such as "in the last 5 minutes before E the load may go down to the live
    reserve" would add about 50–100 calls an hour. It is left out because it relies on the phase being right to
    the minute and changes the reserve's meaning. A follow-up row is proposed (see Verification).
13. **Documentation corrections in the same change.**
    - `docs/napix_integration_notes.md` §6: the 1 Oct conclusion is replaced. The new text: 1,000 calls per
      one-hour window; the reset is at a fixed minute of the hour (HH:33–HH:35 IST from 1 to 11 Oct), not the
      clock hour; it is detected from `X-RateLimit-Remaining`, never assumed; the evidence query. The §9 line is
      closed.
    - `docs/napix_integration_design.md`: the `RateLimiter` paragraph and the settings table get the three
      `NAPIX_WINDOW_*` settings.
    - `docs/schema/napix_coverage.md`: the stale line "`window_seconds` stays 60" gets a dated pointer to notes
      §6. The approved text is kept.
    - The scribe appends the decisions-log entry.

## Data
Migration **0015** (`0015_napix_window.py`), new. Applied migrations are not touched.

Paragraph for `schema.md`, Group 9 (a note under the table, like the 0014 note):

> `napix_call_log` gains `user_id` (uuid NULL, → users **RESTRICT**; users are never deleted): the person whose
> action caused the call — a court search or fetch, the connectivity check, or a `request`-lane queue row they
> asked for. NULL for daily and load lane work, window probes, CLI checks and rows written before 0015. Partial
> index `ix_napix_call_log_user_called` (user_id, called_at) WHERE user_id IS NOT NULL. `called_at` is the
> attempt's own time (`NapixResult.called_at`), not the flushing transaction's. `fetch_queue` gains
> `requested_by` (uuid NULL, → users **RESTRICT**): the person who asked for the row's pending run; set on insert,
> revive or requeue from the caller, kept (`COALESCE`) while pending; CHECK `ck_fetch_queue_requested_by`
> (`requested_by IS NULL OR lane = 'request'`); copied by the runner to the calls the row makes and inherited by
> the rows it spawns. The quota window is derived, not stored: `services/napix_window.py` reads the call-log
> readings (`rate_limit_remaining` NOT NULL) of the last 6 hours; a reset is a rise of at least
> `NAPIX_WINDOW_RESET_JUMP`, precise when the previous reading is at most 300 s older; the phase comes from the
> latest precise reset (design `napix-window`, migration 0015). Both tables stay class `derived`; `aslms_app`
> grants unchanged (INSERT / SELECT on `napix_call_log`; SELECT / INSERT / UPDATE on `fetch_queue`).

- **No new table, no `ref_*` code and no enum.** The readings already exist. A table of detected resets was
  considered and rejected: several processes commit calls out of order, so the table would need deduplication and
  locking that a read-time query does not.
- **No audit columns.** Both tables are system-written logs (DB_STANDARD §5 applies to tables users write).
- **Upgrade.** Two nullable columns, the FK constraints `fk_napix_call_log_user_id_users` and
  `fk_fetch_queue_requested_by_users` (RESTRICT), the CHECK (every existing row passes because the column is
  NULL), and the partial index. No backfill.
- **Downgrade.** Drop the index, the CHECK and the two columns. These are log attributions, not legal records.
- **Models.** `NapixCallLog.user_id` and `FetchQueueItem.requested_by` with the check in `__table_args__`.
- **Settings** (`core/config.py`, `.env.example`):
  - `NAPIX_WINDOW_MARGIN_SECONDS`: 60, from 0 to 600.
  - `NAPIX_WINDOW_PROBE_SECONDS`: 180, from 60 to 300.
  - `NAPIX_WINDOW_RESET_JUMP`: 50, from 10 to 500.
  - The `NAPIX_RATE_WINDOW_SECONDS` comment changes to "window length; the phase is detected (design
    napix-window)".

## Services
- **`services/napix_window.py` (new):**
  - `Reading(at, remaining)` and `Reset(observed_at, previous_at, previous_remaining, remaining, precise)`.
  - `readings(session, now) -> list[Reading]`: one indexed range query on `called_at` over the last 6 h, ordered
    by `(called_at, id)`.
  - `detect(readings, jump) -> list[Reset]`: decision 1, pure, with the jump clusters collapsed.
  - `assess(readings, now, *, window_seconds, margin, probe, jump) -> WindowState`: decisions 2 and 3, pure.
  - `WindowState` fields:
    - `status`, `remaining`, `started_at` (E − window in `current` / `overdue`, E in `reset_due`, S in
      `unknown`), `observed_at` (S, or None in `reset_due`), `next_reset_at` (E or None);
    - `anchor_at`, `last_reading_at`;
    - `recent_resets`, newest first, from the lookback;
    - the methods `seconds_to_reset(now)`, `resume_at(now)` (decision 4) and `retry_after(now)` (decision 6).
  - `current(session, settings, now=None) -> WindowState`: `readings` + `assess`, read-only.
  - `calls_since(session, start, *, lane_split=False)`: calls and failures since S, split by lane when asked.
  - `by_user(session, start, limit=10)`: rows `{user_id, name, calls, failed}`, most calls first. Used for the
    window and for today (IST).
- **`integration/napix/client.py`:**
  - `NapixResult.called_at: datetime | None`, set per attempt (decision 7).
  - `RateLimiter(per_minute, window_seconds, zero_wait_seconds)` (decision 8).
  - `from_settings` passes `napix_window_probe_seconds`.
  - The client still never touches the database.
- **`services/napix_store.py`:**
  - `NapixRecorder(job_run_id=None, user_id=None)`. `user_id` can change per item (the runner sets and clears it
    like `lane`) and is recorded per attempt alongside the lane.
  - `flush` writes `user_id` and `called_at` (`COALESCE(:called_at, now())`).
- **`services/queue.py`:**
  - `enqueue(..., requested_by=None)`: decision 10's conflict clause. A non-request lane with a person raises
    `ValueError` before any SQL.
  - `has_runnable(session, kinds=None, lanes=None) -> bool`: the claim's conditions and pause clause, without
    locking.
- **`services/load_policy.py`:** `QueueOrigin.requested_by` (None by default). The `request` origin's spawned
  rows pass it.
- **`services/runner.py`:**
  - `seed_remaining` becomes `self.window = napix_window.current(...)`, with
    `recorder.last_remaining = window.remaining`.
  - `probe()`: one `hc.overview()` call. The recorder is flushed and committed in its own session. The pass's
    `probes` counter goes up. An integration error is logged and the pass stops with `resume_at = now + probe
    interval`.
  - The claim loop follows decision 4. The item's `requested_by` is set on the recorder for that item and
    cleared afterwards.
  - `RunReport` gains `resume_at: datetime | None` and `probes: int`. `stopped_reason` reads, for example,
    `rate budget: 148 left < reserve 150; window current, next reset about 15:34 IST`.
  - `job_runs.counters` gains `probes`.
  - The module docstring drops "sleeps to the next clock hour".
- **`cli/pipeline.py::queue_worker`:**
  - The worker sleeps until `report.resume_at`, at least 5 s, capped by `--idle` when only the load is blocked.
  - Its line: `waiting for the window reset at about HH:MM:SS IST (+60 s)` or `reset overdue: probing in 180 s`.
  - No local-clock arithmetic remains; everything is UTC-aware and printed in IST.
- **`services/court_search.py::guard`:** refuses `napix_budget` when `window.remaining` is known and below
  `NAPIX_SEARCH_FLOOR`, with `retry_after = window.retry_after(now)`. `latest_remaining_this_hour` and
  `seconds_to_next_hour` are removed; their callers move to `napix_window`.
- **`services/napix_admin.py`:**
  - `check_guard` applies the same rule. Its "last check" query and `check_too_soon` consider Overview calls with
    `job_run_id IS NULL` only, so window probes, which carry the pass's `job_run_id`, neither block nor pose as
    an administrator's connectivity check.
  - `health_check` records its caller (decision 9).
  - `refetch_*` enqueue with `requested_by` = the acting user (the `system` actor gives NULL).
- **`services/data_load.py`:**
  - `allowance` becomes window-based: `window_started_at`, `next_reset_at`, `seconds_to_next_reset`,
    `window_status`, `used` by lane since S, `remaining`, and the three thresholds.
  - `fetch_details` and `fetch_court` pass the user (decision 9). `estimate` is unchanged.
- **`services/data_health.py`:**
  - `napix_health(session, settings, now, *, operator: bool)`: `hour` is replaced by `window` (API).
  - `by_user` is filled for operators, with the window's and today's top 10.
  - `snapshot` computes `operator = access.has(… admin.napix_refetch) or access.has(… admin.masters_sync)`
    (False for the CLI without a super admin).
  - `call_rows` selects `user_id` and the user's `full_name` (LEFT JOIN users) and takes `user_id`. Both apply
    only when `operator`.
- **CLI.**
  - `aslms data-health` prints the window line (status, started about, next reset about, remaining, probes in the
    last hour) and the recent resets.
  - `aslms napix-probe-rate` is unchanged; its docstring points to notes §6.
- **Audit.** No new action. Probes are system calls, recorded in `napix_call_log` and `job_runs`. Reading the
  window writes nothing. Court searches and checks keep their existing audit rows.

## API
No new endpoint. Every changed endpoint keeps its function. No `GET` calls NAPIX.

| Endpoint | Function (`Permission`) | Change |
|---|---|---|
| `GET /admin/napix/health` | `reports.state` or `admin.napix_refetch` or `admin.masters_sync` (`health_reader`) | `hour: NapixHourOut` → `window: NapixWindowOut`; adds `by_user: {window: [UserCallsOut], today: [UserCallsOut]} \| null` (operators only, decision 11) |
| `GET /admin/data-health` | as above | its `napix` block as above |
| `GET /admin/napix/calls` | as above | items gain `lane`, `user_id`, `user_name` (null unless operator); query `user_id` (uuid; non-operator → 403 `forbidden`) |
| `GET /admin/data-load` | `load_reader` (`admin.data_load` or `reports.state` or the two NAPIX operator functions, unchanged) | `allowance`: `hour_started_at`, `seconds_to_next_hour` → `window_started_at`, `next_reset_at`, `seconds_to_next_reset`, `window_status`; `used`, `remaining`, thresholds unchanged; no user data |
| `POST /cases/search-court`, `POST /cases/{ref}/fetch-court` | `cases.search_court` (unchanged) | 503 `napix_budget`'s `retry_after` from the window; calls recorded with the user |
| `POST /admin/data-load/fetch`, `/fetch-details` | `admin.data_load` (unchanged) | same; request rows carry `requested_by` |
| `POST /admin/napix/health/check` | `admin.napix_refetch` or `admin.masters_sync` (unchanged) | 429 `napix_budget`'s `retry_after` from the window; probes do not count as checks |
| `POST /admin/napix/refetch/day`, `/case`, `/order` | `admin.napix_refetch` (unchanged) | rows carry `requested_by` |

`NapixWindowOut` fields:

| field | type | note |
|---|---|---|
| `status` | `"current" \| "reset_due" \| "overdue" \| "unknown"` | |
| `started_at` | datetime \| null | IST |
| `observed_at` | datetime \| null | IST |
| `next_reset_at` | datetime \| null | IST |
| `seconds_to_next_reset` | int \| null | negative while due or overdue |
| `anchor_at` | datetime \| null | |
| `calls` | int | since `observed_at`; 0 in `reset_due` |
| `failed` | int | since `observed_at`; 0 in `reset_due` |
| `remaining` | int \| null | |
| `last_reading_at` | datetime \| null | |
| `recent_resets` | list of `{observed_at, previous_at, previous_remaining, remaining, precise}` | last 6 h, newest first |
| `window_seconds`, `margin_seconds`, `probe_seconds` | int | |
| `reserve`, `live_reserve`, `search_floor` | int | |

`UserCallsOut` is `{user_id, name, calls, failed}`.

Visibility: State-level readers as today. User attribution goes only to the NAPIX operators (decision 11).
Credentials never appear. The OpenAPI document and `frontend/src/lib/api/schema.d.ts` are regenerated.

**Portal (`frontend/`):**
- **`components/data/LoadConsole.tsx`.** The allowance card's title becomes "Court gateway allowance, this
  window". It gains the line `Current window started about 14:34; next reset about 15:34`, or for the other
  states:
  - "A new window was due at about 15:34; no call since";
  - "The reset expected at about 15:34 has not been seen; checking every 3 minutes";
  - "Window timing not known yet; it is found at the next call".

  `remainingUnknown` becomes "No call in this window yet."
- **`components/data/Health.tsx`.**
  - The "This hour" tile becomes "This window", with the same status line.
  - A "Recent resets" list (time, previous → new remaining, "precise" mark).
  - For operators, a "Calls by user" table with the window and today side by side, shown only when `by_user`
    is present.
- **`app/(portal)/data/queue/page.tsx`.** The call log gains a "Lane" and a "User" column. The user column is
  shown only when the API returns users.
- **Strings.** All new strings go in `messages.ts`. `napix_budget`'s text keeps "hourly allowance" and its
  `retry_after` wait.

## Jobs
- **Queue (existing worker).** No new kind or lane. The runner may make one probe (an Overview call) per pass,
  under decision 4. `job_runs` row `queue-run` / `queue-worker` counters gain `probes`.
- **Beat.** No change. Daily list and status-batch schedules stay as they are: the daily lane runs down to the
  live reserve in any window.
- **Restart.** The worker must be restarted on the new image after migration 0015, because the runner's wait
  changes. The API too, because the guards and response shapes change.

## Tests
Unit (`tests/unit/test_napix_window.py`):
- `test_jump_detects_reset_and_ignores_upticks`: the sequence 822, 823, 821, 999, 998 gives one reset at the 999
  reading; +1 and +2 rises give none.
- `test_jumps_within_quarter_window_are_one_reset`: 822 → 999 → 820 → 998 within seconds gives one reset, timed
  by the first jump.
- `test_precise_needs_previous_reading_within_300s`: a 3,600 s gap gives an imprecise reset; 7 s gives a precise
  one.
- `test_expected_reset_from_anchor_not_from_imprecise_reset`: an anchor at 12:34:30, an imprecise S at 14:35:30
  and now 14:50 give E = 15:34:30.
- `test_states`: one case for each of `current`, `reset_due`, `overdue` and `unknown`, with the remaining each
  exposes (decision 3's table), including a reading older than the probe interval in `overdue` giving `None`.
- `test_resume_at_and_retry_after`: E + margin in `current`; last reading + probe interval otherwise.
- `test_evidence_sequence_11_oct`: readings copied from the 11 Oct log (fixture `napix_readings_2026-10-11.json`,
  only times and counts). At 15:30:06 IST with 148 left: the state is `current`, next reset about 15:34 IST, and
  `resume_at` before 15:36. The old rule gave 16:30.
- `test_window_settings_validated`: margin and probe interval bounds; the probe interval is at most
  `PRECISE_GAP`.

Unit (`tests/unit/test_napix_client.py`, additions):
- `test_result_carries_attempt_time`: two attempts of one call have increasing `called_at`.
- `test_zero_remaining_waits_probe_interval_not_window`: with the sleep mocked, the delay at 0 remaining is
  `zero_wait_seconds`.

Database (`tests/db/test_napix_window.py`, scripted gateway; `Gateway.rate_headers` is changed between calls, and
the db router answers `overview/overview` from the sample):
- `test_recorder_writes_attempt_time_and_user`: call-log rows carry `called_at` from the result (distinct within
  one item) and `user_id`.
- `test_runner_waits_for_expected_reset_not_clock_hour`: call-log readings with an anchor at :34 and 148 left at
  :30. The pass claims no load row, writes no call, and returns `resume_at` = :35 (E + 60 s).
- `test_runner_probes_when_reset_due_then_runs_load`: now past E + margin, the gateway answers 999. One Overview
  call (lane NULL, user NULL, `job_run_id` set) is made, then load rows run, and `probes` = 1.
- `test_runner_overdue_probes_every_interval`: the gateway still answers 140 after E. The pass stops with
  `resume_at` = probe + 180 s and makes no second probe in the same pass.
- `test_no_probe_without_runnable_work`: an empty queue (or a paused load with no other lane) with an unknown
  remaining makes no call.
- `test_request_row_user_reaches_call_log`: a re-fetch button queues a request row with `requested_by`. The
  runner's calls for it carry that `user_id`, its spawned order PDFs inherit `requested_by`, and daily and load
  rows' calls have none.
- `test_requested_by_conflict_rules`: insert, revive and pending (COALESCE). A load-lane enqueue with a person
  raises before SQL. `retry-failed` sets none.
- `test_requested_by_check_constraint`: a direct UPDATE setting `requested_by` on a load row fails
  `ck_fetch_queue_requested_by`.

Database (`tests/db/test_court_search.py`, `test_api_napix_admin.py`, `test_api_data_load.py`,
`test_data_health.py`, additions or changes):
- `test_search_guard_uses_window`: 40 left in a `current` window is refused with `retry_after` up to E + margin;
  the same reading in `reset_due` is allowed. The clock hour plays no part: a reading from before the UTC hour
  still counts.
- `test_search_records_user_on_calls`: `POST /cases/search-court` rows carry the caller's `user_id`.
- `test_check_guard_ignores_probes`: a probe 10 s ago does not trigger `check_too_soon` and is not `last_check`.
- `test_health_window_block_exact`: seeded readings give the expected `status`, `started_at`, `next_reset_at`,
  `calls`, `failed` and `recent_resets`.
- `test_by_user_operator_only`: the super admin sees `by_user` and the call-log user fields. A `reports.state`-only
  user gets `by_user: null` and null user fields, and gets 403 with `user_id`.
- `test_allowance_window_based`: `used` by lane counts from S, not from the clock hour.

Migration (`tests/db/test_migration_0015.py`):
- `test_0015_columns_fk_check_index`: both columns are nullable; both FKs are RESTRICT; the CHECK and the partial
  index exist.
- `test_0015_downgrade_upgrade`: a round trip on a database holding rows.

Portal (`frontend/src/components/data/data.test.tsx`):
- The allowance card and the health tile render each status line.
- The recent resets list renders.
- The calls-by-user table is shown when present and absent otherwise.
- The call log shows the user column only when users are returned.

## Verification
1. **Suites.** `ruff check` is clean; `pytest -q` and the portal tests are green.
2. **Apply in Compose.** Stop `worker` and `scheduler`, build the images, `docker compose run --rm init` (applies
   0014 if still pending, then 0015), and start `api`, `worker`, `scheduler` and `web` on the new image. Then
   `SELECT column_name FROM information_schema.columns WHERE table_name IN ('napix_call_log','fetch_queue') AND
   column_name IN ('user_id','requested_by','lane')` returns 3 rows.
3. **Watch the worker.** `docker compose logs -f worker` shows `waiting for the window reset at about HH:3x:xx
   IST`, not "sleeping until the next hour". Within a minute or two of the reset, it shows a probe (or the first
   call) answering about 999 and the load resuming.
4. **No missed window.** After at least 3 hours, the windows since the restart (HH:34 to HH+1:34 IST, the
   observed minute) each show at least 800 calls; before the fix, every second window showed about 240:
   `SELECT date_trunc('hour', called_at - interval '34 minutes') + interval '34 minutes' AS w, count(*) FROM
   napix_call_log WHERE called_at > <restart> GROUP BY 1 ORDER BY 1`.
   - The longest gap between consecutive calls is under 50 minutes: `SELECT max(called_at - lag) FROM (SELECT
     called_at, lag(called_at) OVER (ORDER BY called_at) AS lag FROM napix_call_log WHERE called_at >
     <restart>) t`.
   - Calls a day rise from about 13,150 to at least 19,000.
5. **Few probes.** Probes per hour stay at 3 or fewer once anchored: `SELECT date_trunc('hour', called_at),
   count(*) FROM napix_call_log WHERE api = 'overview/overview' AND job_run_id IS NOT NULL GROUP BY 1`.
6. **Screens.**
   - `GET /admin/data-health` as the super admin: `napix.window.status = current`, `started_at` about HH:34,
     `next_reset_at` one hour later, and `recent_resets` with `precise = true` rows.
   - `/data/load` and `/data/health` in the `web` service show the status line. `aslms data-health` prints the
     same window.
7. **Calls by user.** Run a court search by party name as a department user with `cases.search_court`. Its call
   rows carry that user's `user_id`. `by_user.window` lists them for the super admin. A `reports.state`-only user
   sees `by_user: null`, and `GET /admin/napix/calls?user_id=…` answers 403.
8. **Window length.** The gaps between consecutive precise resets in `recent_resets` are whole multiples of 3,600
   s, within ±2 minutes. If they are not, stop and report: the window length setting would need revisiting.
9. **Documents.** Notes §6 and §9 and the integration design are corrected (decision 13). The backlog gets the
   proposed follow-up row "napix-window-tail": decision 12's end-of-window spending, if the owner wants it.

## Open questions
None. Owner checks at approval:
- Margin 60 s and probe interval 180 s (decision 5).
- Load and daily lane calls carry no user (decision 9).
- User attribution is shown only to the NAPIX operators (decision 11).

## Deviations
Recorded by the developer while building (12 Oct 2026).
1. **Decision 1, clustering.** Taken literally ("jumps less than 15 minutes apart are one reset, timed by the
   first"), the rule merges two real resets in the 11 Oct log: a window seen late (12:30:07, imprecise, after the
   one-hour sleep) and the next window's reset minutes later (12:34:30, precise). Every precise reset of that day is
   lost, no anchor is found, and `test_evidence_sequence_11_oct` cannot pass. Built instead: a jump within a quarter
   window of the previous reset is the same reset only when a reading fell back by at least the jump in between (an
   answer from the old window interleaved, as in 822 → 999 → 820 → 998); otherwise it is a new reset. Both tests of
   decision 1 hold (`test_jumps_within_quarter_window_are_one_reset`, `test_two_real_resets_minutes_apart_are_kept`).
2. **No observed reset.** When no reset lies in the lookback (`unknown` with S unknown), "calls since S" is 0, the
   allowance's `used` is all zeros and `by_user.window` is empty; `today` is unaffected.
3. **`current` and old readings.** In `current`, a reading older than one window is not used (remaining unknown), so
   decision 3's "never older than one window" holds explicitly rather than by inference.
4. **Runner.** When the bands block after items have run in the pass, the window is read again; if its remaining has
   become unknown (the expected reset fell due during the pass), the pass goes on (to its one probe, or to claim)
   instead of stopping. `RunReport` also carries `load_only` and `window`, which the worker uses for its wait and its
   line; the `rate budget:` / `load waits:` prefixes of `stopped_reason` are kept.
5. **Last check.** The health block's `last_check`, like `check_guard`, counts only Overview calls without a
   `job_run_id`, so a probe never shows as an administrator's connectivity check.
6. **`retry_item`.** The single-row retry (as before, through `queue.enqueue` with no person) also leaves
   `requested_by` NULL, like `retry-failed`.
7. **CLI.** `aslms data-health` prints the window line and the recent resets before the JSON snapshot (stdout is no
   longer pure JSON; the JSON starts at the first `{`). "Probes in the last hour" counts Overview calls with a
   `job_run_id`.
8. **Console text.** The allowance block carries no probe setting, so the console's overdue line uses the default
   ("checking every 3 minutes"); the health tile uses `probe_seconds` from the API.
9. **Migration.** Autogenerated against the dev database (at 0014) and reviewed: autogenerate does not detect CHECK
   constraints, so `ck_fetch_queue_requested_by` was added by hand.
