# Design: The data-load console: progress, start, pause and order of the backdated NAPIX load, single-case fetch, duplicate checks, and the data-health screen

```
slug: data-load-console
status: approved
author: architect
date: 2026-10-11
approved_by: owner (nayanlhuzuri) on 2026-10-11
```

## Context
Owner's request of 11 Oct 2026 (backlog row 45, built before row 12). The owner confirmed the scope: (1) see the
progress of the backdated load and an estimate: coverage of the period month by month, work left by kind,
failures, the hourly NAPIX allowance used and left, an estimated finish; (2) start a backdated load for a date
range: every cause-list day in it is queued, and the cases, statuses and orders found in those lists follow
automatically; (3) pause, resume and choose what goes first, while live searches and the daily cycle keep running;
(4) fetch single cases from the court by CNR, case number or party name and add them; (5) duplicates checked: one
case never stored twice, duplicates the court itself creates linked; (6) a warning before re-fetching data already
in the database, before any NAPIX call, with the choice to fetch anyway; one new grantable function for managing the
load (super admin by default, grantable to any user type or user). The item also takes over the data-health screen
and the NAPIX buttons (masters sync, re-fetch a day, a case or an order PDF, retry failed items) from row 41.

Plan basis. §3 and §6.1: "scheduler and job queues that run all data collection in the background; retry,
rate-limit and error handling so that a failed call is retried and logged, never lost"; §5.2: "the portal's own
database is searched first; if the case is not found, NAPIX search APIs are queried live, and the case is fetched
and stored"; §5.10: "Data collection health: status of the daily data cycle, and any failed API calls"; §5.11:
reference data from the NAPIX masters. The plan's "migration of existing data" (Phase 1) was withdrawn by the owner
on 25 Sep 2026. The backdated NAPIX load from 2025-01-01 takes its place (decisions log, 1 Oct 2026: "the
historical load runs through NAPIX"). The console is the screen that manages that load. It deviates from no plan
text.

Already in place (reused, not rebuilt):
- `fetch_queue` and `services/queue.py` (`enqueue` with `requeue`, `claim` with `FOR UPDATE SKIP LOCKED`, `fail`
  with up to 5 attempts, `requeue_stale`, `get_state`). `services/runner.py` (`QueueRunner`, `enqueue_days`;
  dispatch per kind; stops below `NAPIX_RATE_RESERVE`). `aslms load --from --to`, `queue-worker` (the Compose
  `worker` service), `daily-cycle`. Celery beat (`scheduler`) only enqueues.
- Priorities today (`queue.PRIORITY`): masters 10; yesterday's, today's and tomorrow's lists 20; status batches
  30; dossiers of a list within 2 days 40; dossiers of an older list 45; weekly re-fetch 50; historical list days
  60; order PDFs 75 (pending case) and 80 (disposed). A person's re-fetch button uses 30 (audit-screens decision 9).
- `services/court_search.py`: `guard` (switch, `NAPIX_SEARCH_FLOOR` 50, `NAPIX_SEARCH_PER_USER_HOUR` 30),
  `search_court` by CNR, case number and party name, `fetch_court`, `fetch_dossier` (the shared dossier fetch),
  `resolve_cnr`, `store_search_rows`; `POST /cases/search-court` and `/cases/{ref}/fetch-court`
  (`cases.search_court`).
- `services/data_health.py`, `services/napix_admin.py`, `api/routers/napix_admin.py` (audit-screens, in
  review): `GET /admin/data-health`, `/admin/napix/health`, `/admin/napix/queue`, `/admin/napix/calls`,
  `/admin/failures`; `POST /admin/napix/sync-masters`, `refetch/day`, `refetch/case`, `refetch/order`,
  `queue/{id}/retry`, `queue/retry-failed`, `health/check`. No portal screen uses them yet.
- `cases.merged_into_case_id` exists and every list already excludes merged rows. **Nothing sets it today.**
  `cases.cnr` is unique. A provisional case (a listed number without a CNR) is found by the exact printed number only.
- The portal (`frontend/`, portal-shell): the relay, TanStack Query, the UI kit, `routes.ts` with a `built` flag
  (the `health` entry exists, `built: false`).

Duplicate paths found while reading the code (fixed by this item, decision 13):
- `court_search.fetch_dossier` creates a new row for a CNR it does not hold (`get_or_create_case(cnr=…,
  case_no=None)`), even when a provisional row with the same case number exists. The result is two rows for one case.
- `runner._dossier` for a provisional ref `<est>|<number>` sets `case.cnr` on the provisional row. When another row
  already holds that CNR (under a differently printed number), the unique index refuses the update and the row fails
  five times.
- Two provisional rows for one printed number can be created at the same time (the worker and an API search), because
  nothing serialises the lookup and the insert.

Not covered: NAPIX search by advocate and filing number (row 21; the console offers the three kinds the API has);
the audit-log screen (row 41); the case screens (row 12); department discovery (row 19); merging a provisional case
that already carries portal records (claims, custody, notes, documents). Such a case is listed for review, not
merged (decision 14, left for later). Re-running today's Current Status batches early (audit-screens decision 12)
is also not covered.

## Decisions
1. **Every queue row carries a lane: `request`, `daily` or `load`.** New column `fetch_queue.lane` (native enum
   `fetch_lane`, in that order of precedence) and `fetch_queue.list_date` (the cause-list date whose loading queued
   the row). `load` means the backdated load. `daily` means the daily cycle (masters, the three list days, status
   batches, their dossiers and order PDFs, the weekly sweep). `request` means work a person asked for (the re-fetch
   buttons, details of found cases). Work a row spawns inherits its lane and `list_date`: a load day's dossiers are
   `load` with that day's date, and their order PDFs too. When the same `(kind, ref)` is asked by two lanes, the row
   takes the higher-precedence lane (`LEAST` over the enum) and the better priority. A load dossier that today's
   list also needs becomes `daily`.
   Alternatives: infer the lane from the priority number (rejected: priorities are what the owner changes,
   decision 3, and a lane must not move with them); a `data_loads` table with a foreign key on each row (rejected:
   the period, the progress and the history are all derivable from the lane, `list_date` and the audit rows, and a
   per-request key would split one load into fragments when ranges overlap).
2. **Pause stops only the `load` lane, and is a setting read by the claim query itself.** `queue.claim` gains
   `AND (lane <> 'load' OR NOT EXISTS (SELECT 1 FROM data_load_settings WHERE is_current AND paused))`, so a pause
   takes effect at the next claim of any worker. Nothing is cached and nothing needs a restart. A row already
   `running` finishes. Live searches never go through the queue. The daily and request lanes keep running.
   Alternatives: stop the worker container (rejected: it also stops the daily cycle); a Redis flag (rejected: a
   second source of truth, lost on a Redis restart, not audited history).
3. **"What goes first" is a preset order of the three load kinds plus an optional period brought forward.**
   - `cases_first` (default; today's behaviour): case details (dossiers) of days already loaded, then the next
     cause-list day, then order PDFs.
   - `lists_first`: every cause-list day of the period first, so every listed case is created and scored (and
     recommendations appear) as early as possible; then details, then order PDFs.
   - `cases_with_orders`: details, then their order PDFs, then the next day.
   A **period to go first** (`first_from`–`first_to`, dates) puts the load rows whose `list_date` falls in it ahead
   of all other load rows, keeping the preset's order inside it. Priorities of the load lane (lower runs first):
   | rank in the preset | brought forward | otherwise |
   |---|---|---|
   | 1st kind | 41 | 44 |
   | 2nd kind | 42 | 46 |
   | 3rd kind | 43 | 48 |
   Every load priority sits behind the masters (10), today's lists (20), status batches and a person's requests
   (30) and today's new dossiers and live order PDFs (40), and ahead of the weekly sweep (50). A change rewrites
   the priority of every `pending` load row in one statement and is applied to rows spawned afterwards.
   Alternatives: free per-kind priority numbers (rejected: easy to put the load ahead of the daily cycle by
   mistake); newest-first or oldest-first ordering of days (rejected: the period brought forward covers "this
   month first" without a second ordering key in the claim query). **Owner check:** the default stays
   `cases_first`.
4. **The daily cycle keeps its share of the hourly allowance even when the load runs.** The runner claims:
   any lane while the remaining quota is at least `NAPIX_RATE_RESERVE` (150); only `daily` and `request` rows while
   it is between `NAPIX_LIVE_RESERVE` (new, default 100) and 150; nothing below 100, when it sleeps to the next
   clock hour as today. Live court searches stay refused below `NAPIX_SEARCH_FLOOR` (50). The order of protection
   is therefore load ≥ 150 > daily ≥ 100 > searches ≥ 50. The settings are validated as
   `search_floor ≤ live_reserve ≤ rate_reserve`. At the start of each pass the runner seeds its remaining count from
   the latest `napix_call_log.rate_limit_remaining` of the current hour. Today every pass starts with an empty
   recorder, so its first item runs even when the reserve is spent. This is the reserve's intended meaning in
   the decisions log of 1 Oct 2026 ("calls kept for the daily cycle; the load queue stops pulling below it"). Today
   the runner stops every kind below it. **Owner check:** `NAPIX_LIVE_RESERVE` = 100.
5. **Order PDFs of live cases from the daily lane move from 75 to 40.** A new order of a pending case otherwise
   waits behind the whole backdated load (load rows are 41–48). Disposed cases' PDFs stay at 80. The new constants
   are `PRIORITY["request"] = 30` and `PRIORITY["order_pdf_live"] = 40`. `PRIORITY["list_history"]` and the
   runner's `dossier_new + 5` for older lists are replaced by the load policy (decision 3).
6. **The backdated period and its progress are derived, not stored.** The period runs from the earliest to the
   latest `list_date` of the load lane's `causelist_day` rows. Coverage per month (`GET
   /admin/data-load/coverage`) is computed live under the report statement timeout from `fetch_queue`,
   `causelists`, `causelist_entries`, `cases` and `orders`:
   - days: calendar, with lists, without a list (`skipped`), waiting, failed, not queued;
   - lists stored, entries, lists that failed to parse;
   - cases listed in the month: total, with details, still provisional;
   - orders dated in the month: referenced, PDF stored, not available, waiting;
   - work left in the load lane with that month's `list_date`, by kind.
   Two percentages are shown: days covered (with or without a list) over calendar days, and cases with details over
   cases listed. Coverage is fetched on demand (it is the heavier query). The progress block (decision 7) is light
   and refreshes every 30 s.
   Alternative: a summary table refreshed by a job (rejected for now: the queries are indexed group-bys over at most
   a few million rows; a table can follow if the timeout is ever hit).
7. **Progress: work left, failures, allowance and an estimate.** `GET /admin/data-load` returns:
   - the settings (paused, preset, period brought forward, who changed them and when);
   - the period and its totals;
   - load work left by kind (pending split into runnable and waiting on `not_before`, running, failed);
   - load failures by kind with the 20 latest failed rows;
   - the allowance of the current clock hour: calls used split by lane (`load`, `daily`, `request`, and calls
     outside the queue, meaning searches and the connectivity check), the latest remaining count, the three
     thresholds, and seconds to the next hour;
   - the estimate.
   The split by lane needs the lane on each logged call: new column `napix_call_log.lane`, set by the runner's
   recorder for the item it is processing and NULL for calls made by the API.
8. **The estimate is computed from measured rates only; no assumed constants.** Over the last 7 days the service
   measures:
   - calls per finished load item of each kind (load-lane calls grouped by the API family: cause-list APIs → day,
     CNR and case-number search → dossier, Show Order → order PDF), divided by the load items of that kind finished
     in the window;
   - dossiers spawned per load day finished, and order PDFs spawned per load dossier finished;
   - load calls per hour over the last 24 h.
   Calls needed = Σ(pending × calls per item) + days left × (dossiers per day × (calls per dossier + PDFs per dossier
   × calls per PDF)) + dossiers left × PDFs per dossier × calls per PDF. Finish = now + calls needed ÷ load calls per
   hour.
   The answer carries the basis (every measured figure) so the screen can show how it was computed. No estimate is
   given while paused (`paused`), with fewer than 24 hours of load history (`not_enough_history`), or when no load
   call was made in the last hour while work is pending (`no_recent_calls`: the worker is stopped or its switch is
   off). Alternative: fixed per-kind call counts from the first live week (rejected: the counts change with the
   number of benches and the order backlog, and inventing them would mislead).
9. **Starting a load is a preview and then an explicit choice about days already held.** `POST
   /admin/data-load/preview {from, to}` writes nothing and makes no call. It returns the calendar days and, among
   them: held with lists (`done`), held without a list (`skipped`: the court published none), waiting, failed, and
   not queued; an estimate of the calls the new days need (decision 8's rates, null without history); and whether
   the masters are older than 24 h.
   `POST /admin/data-load/start {from, to, held}` queues the days: `held` is `skip` (held days are left as they
   are) or `refetch` (held days are queued again, `requeue=True`). When the range contains held days and `held`
   is absent, the API answers 409 `already_held` with the counts and queues nothing. This is the owner's warning
   before any NAPIX call, with the choice to fetch anyway. Failed and skipped days are always revived (as
   `enqueue` does today), and waiting days keep their row and get the load priority if better.
   Bounds: `from ≤ to ≤ yesterday` (IST), `from ≥ 1950-01-01`. Today and tomorrow belong to the daily cycle.
   Start also queues `masters/all` when the last masters sync is older than 24 h (case types are needed to resolve
   provisional numbers). One audit row is written: `data_load.started`. `aslms load` goes through the same service
   (CLI actor) with `held = skip`, or `refetch` with `--requeue`.
10. **Single-case fetch from the console reuses the court search, with a check before any call.** `POST
    /admin/data-load/fetch {kind: cnr | case_number | party, …, force}` (`admin.data_load`) first looks in the
    database, without a call:
    - CNR: a held case with details (`last_full_refresh_at` set) answers 409 `already_held` with its summary, when
      its details were last fetched and `dossier_stale`. A held case without details is fetched directly (its
      details are not in the database).
    - Case number: the same, for a held case of that type, number and year.
    - Party name: an earlier court search with the same name, year and pending/disposed flag (from the
      `case.search_court` audit rows) answers 409 `searched_before` with when it ran and how many cases it stored,
      plus the count of held cases whose party names match locally.
    With `force: true` the call is made, and for CNR and case number the dossier is re-fetched even when held.
    The court-search guard applies unchanged (switch, floor, the per-user hourly limit shared with `POST
    /cases/search-court`). The call is audited as `case.search_court` with `via: "data_load"`, `force` and
    `warned`. A 409 answer writes nothing. Results are case summaries with the `visible` flag of the search rule
    (decision 4 of cases-api), so the console never shows details of a case its user may not see.
    `court_search.search_court` gains `force` (CNR: skip the local short cut; case number: skip the local match).
    `POST /cases/search-court` keeps its behaviour (`force` false).
    Alternative: queue single fetches like the load (rejected: the user expects the case at once, as with the court
    search).
11. **Details of found cases are queued, with the same warning.** A party-name search stores every hit without
    details (cases-api decision 9). `POST /admin/data-load/fetch-details {cases: [ref…] (1–200), force}` queues
    `dossier` rows in the `request` lane at priority 30 for the cases without details. Cases with details answer as
    `already_held` in the result list and are queued only with `force` (`requeue=True`). Merged cases are
    reported with their surviving `ref_no`, and cases without a CNR or a number are reported as `no_reference`. Cases
    the caller cannot see are still queued (the console manages data, not case content) but are returned as
    summaries only. One audit row is written: `data_load.details_requested`, with the count and the refs.
12. **The re-fetch buttons taken over from row 41 get the same warning.** `POST /admin/napix/refetch/day` answers
    409 `already_held` when the day is `done` with lists stored or `skipped`. `POST /admin/napix/refetch/case`
    answers 409 `already_held` when the case has details. Both take `force: true` to queue anyway. The request is
    otherwise unchanged (lane `request`). A stored order PDF keeps answering 409 `already_stored` with no `force`: a
    stored order is the court's signed record, content-addressed, and a re-download would either change nothing or
    produce a second file for one order. **Owner check:** stored order PDFs cannot be re-fetched from the console.
    `POST /admin/napix/queue/retry-failed` gains an optional `lane` filter, so "retry the load's failed details"
    leaves the daily lane alone.
13. **One row per case: every case creation goes through one lookup, serialised.** `services/case_dedupe.py`
    defines the case number key: same court, and either the same compact number (upper case, no spaces; the
    expression the existing `ix_cases_case_no_compact` index serves), or the same case type (`case_type_id`), `reg_no`
    and `reg_year`. Three rules apply:
    - `cases.find_case` matches provisional rows by this key, not only by the exact printed text.
    - `court_search.fetch_dossier`, before creating a row for a CNR it does not hold, looks for a provisional row
      (no CNR, not merged) with the dossier's number and **adopts** it (sets its CNR). This is the same thing
      `get_or_create_case` already does for a list entry that brings a CNR.
    - When a provisional row resolves to a CNR another row already holds (`runner._dossier`, `fetch_court`), the
      provisional row is **merged** into the holder (decision 14) instead of failing on the unique index.
      `fetch_court` stops answering `resolved_elsewhere` for a mergeable row and answers with the surviving case.
    Creation and adoption take `pg_advisory_xact_lock` on a hash of (court id, compact number), so the worker and the
    API cannot create two provisional rows for one number at once. A CNR stays unique by its index.
    Alternative: a partial unique index on the provisional number (rejected: the running dev database may already
    hold such pairs, the migration would fail on them, and the index cannot express the "same type, number and
    year" half of the key).
14. **Merging a provisional row moves only data rows, never portal records.** `merge_provisional(P, C)` runs in
    one transaction, only when P has no CNR, is not merged, and holds no portal record: no `case_ownership`,
    `custody`, `case_notes`, `case_note_drafts`, documents on the case, manual `next_dates`, `ownership_transfers`
    or `assistant_conversations`. It does the following:
    - re-points P's `causelist_entries.case_id` to C (the resolution column; the printed columns never change);
    - moves P's `case_links` to C where C has no identical link (the rest stay on P);
    - expires P's active recommendations (schema: `expired` "when … the case is merged");
    - deletes P's `case_office_scores` (derived, recomputed);
    - fills `office_watchlist.case_id` for C;
    - sets `P.merged_into_case_id = C.id`;
    - refreshes both search vectors and rescores C (C now carries P's listings and their counsel codes);
    - emits `case_merged` on C (new event type, scoped) and writes `case.merged` (system actor when automatic).
    When P holds a portal record it is not merged. A `source_failures` row (kind `case_duplicate`, ref `<P id>|<C
    id>`) lists the pair on the console for review, and the queue row that found it ends `skipped` with the reason
    instead of failing. Resolving such pairs (moving claims, custody and notes) is left for later: it needs the
    owner's rules for a case claimed under two rows. **Deviation (schema note):** `causelist_entries` is "immutable
    once written". Its `case_id` is re-pointed on a merge, and only that column changes. Alternative: leave the
    entries on P and make every reader (listings, matching, search vector, reports) also read merged rows (rejected:
    invasive, and the matching engine would miss counsel codes printed against P).
15. **Duplicates the court creates are linked, never merged.** Two rows with different CNRs and the same case number
    key (same court, type, number and year), or the same filing number key (`filing_case_type_text` or
    `filing_case_type_id`, `filing_no`, `filing_year`), are the court's own duplicate records. Both CNRs are court
    identifiers and both are kept. The newer row gets one `case_links` row to the older (`kind = court_duplicate`,
    new value; `source = dedupe`, new value; `to_case_id`, `to_cnr`, `to_case_no_text` set). `case_linked` is
    emitted on both, and one `case.court_duplicate_linked` audit row is written. Both case pages already show
    links in both directions, and the matching engine already reads every link kind. A department that claimed one
    therefore gets a linked-case recommendation for the other (recommend only; never assigned).
    **Owner check:** the two keys define a court-side duplicate; the link counts as a linked-case signal.
16. **Duplicates are checked inline and swept daily.** Inline after every dossier apply and every search-row store,
    for the touched cases (indexed lookups). A daily beat task `aslms.dedupe_sweep` (03:00 IST) runs the same
    rules over all cases in batches, and `aslms data-load dedupe [--dry-run]` runs it by hand. It clears the pairs
    already in the dev database from the historical load. `POST /admin/data-load/duplicates/scan` runs it from the
    console (`admin.data_load`, audited as `data_load.dedupe_scan` with the counts). `GET
    /admin/data-load/duplicates` lists merged rows, court-duplicate links and pairs needing review, as `ref_no`,
    CNR and case number only.
17. **One new function: `admin.data_load`** ("Manage the data load": "Start, pause and order the backdated NAPIX
    load, fetch single cases from the court, and check duplicates"). No user type holds it by default. The super
    admin holds every function and switches it on for a type (matrix) or a login (override) like any other. Under
    the delegation rule, a grantee who also holds `users.grant` may pass it on within their own scope. Reading the
    progress, coverage and duplicate lists is allowed to `admin.data_load` or any health reader (`reports.state`,
    `admin.napix_refetch`, `admin.masters_sync`, audit-screens decision 6). Every action needs `admin.data_load`.
    The existing buttons keep their functions (`admin.napix_refetch`, `admin.masters_sync`).
18. **Settings history is a versioned master, like the scoring settings.** `data_load_settings`: each pause,
    resume or order change inserts a new version and closes the previous one, with a mandatory reason for a pause
    and an order change. An empty table means the defaults (running, `cases_first`, nothing brought forward).
    Audit rows: `data_load.paused`, `data_load.resumed`, `data_load.order_changed` (before and after, rows
    re-prioritised). No event: operations, not case history.
19. **The portal gets one "Data collection" entry with four tabs.** `/data/load` (the console), `/data/health`
    (the data-health screen and its buttons), `/data/queue` (queue rows and the call log) and `/data/duplicates`.
    The entry shows for `admin.data_load` or a health reader, each tab and button by its function. The API decides
    everything (portal-shell decision 10). Every warning (`already_held`, `searched_before`) is a dialog that names
    what is held and when, with "Fetch anyway" (`force`) and "Cancel". The start dialog shows the preview before the
    choice. The progress block refreshes every 30 s while the page is visible, and the health snapshot every 60 s.
    No GET calls NAPIX. The API process's switch is shown with the note that the worker's switch is set in its own
    environment.
20. **The CLI follows the services.** `aslms data-load status | coverage [--from YYYY-MM --to YYYY-MM] | start
    --from --to [--refetch-held] | pause --reason | resume | order --preset P [--first-from D --first-to D] --reason
    | dedupe [--dry-run]`. Every action acts as the super admin named in `.env` and is audited. `aslms load` stays,
    as decision 9 says.

## Data
Migration **`0014_data_load`** (new file; applied migrations are not edited). Paragraphs for
`docs/schema/schema.md`:

Group 9 (after the `source_failures` row), new table:

> | `data_load_settings` (master, versioned) | id (uuid v7 PK), version integer NOT NULL UNIQUE, paused boolean NOT
> NULL default false, load_order (`load_order` enum: `cases_first` / `lists_first` / `cases_with_orders`) NOT NULL
> default `cases_first`, first_from date NULL, first_to date NULL, reason text NOT NULL, is_current boolean NOT
> NULL default false, valid_from timestamptz NOT NULL default now(), valid_to timestamptz NULL, created_at,
> updated_at, created_by, updated_by (→ users SET NULL) | CHECKs `ck_data_load_settings_current` (is_current =
> (valid_to IS NULL)), `ck_data_load_settings_first` ((first_from IS NULL) = (first_to IS NULL) AND (first_from IS
> NULL OR first_from <= first_to)). Partial unique `ix_data_load_settings_current` (is_current) WHERE is_current. A
> pause, resume or order change inserts a new version and closes the previous one; values never updated in place,
> rows never deleted. Empty table = running, `cases_first`, nothing brought forward. Read by `queue.claim`
> (pause) and by the load priority policy; written only by `services/data_load.py` (design `data-load-console`). |

Group 9 note, replacing the audit-screens note:

> `fetch_queue` (napix_coverage §A) gains `lane` (`fetch_lane` enum: `request` / `daily` / `load`, NOT NULL default
> `daily`; precedence in that order, a row asked by two lanes keeps the higher one) and `list_date` (date NULL: the
> cause-list date whose loading queued the row; inherited by the dossiers and order PDFs it spawns). Indexes
> `ix_fetch_queue_claim` (priority, created_at) WHERE status = 'pending', and `ix_fetch_queue_lane_list_date` (lane,
> list_date). `queue.claim` skips `lane = 'load'` while the current `data_load_settings` row is paused, and the
> runner claims `load` rows only above `NAPIX_RATE_RESERVE` and other lanes only above `NAPIX_LIVE_RESERVE`.
> Priorities: masters 10, the daily list days 20, status batches and a person's requests 30, today's new dossiers and
> live-case order PDFs 40, the load 41–48 (design `data-load-console`, decision 3), the weekly sweep 50,
> disposed-case order PDFs 80. `napix_call_log` gains `lane` (`fetch_lane` NULL: the lane of the queue item that
> made the call; NULL for calls made by the API). `napix_call_log`, `fetch_queue` and `source_failures` are read
> live by `services/data_health.py` and `services/data_load.py` (`/admin/data-health`, `/admin/napix/*`,
> `/admin/data-load*`); buttons write `fetch_queue` rows only through `queue.enqueue`. `source_failures` kind
> `case_duplicate` (ref `<provisional id>|<holder id>`) lists provisional rows that could not be merged.

Group 3, `case_links` row, append to Notes:

> (data-load-console, migration 0014) `link_kind` + `court_duplicate` (two CNRs the court issued for one case
> number or filing number; one row from the newer case to the older, never merged); `link_source` + `dedupe`.

Group 3, `cases` row, append to Notes:

> `merged_into_case_id` is set only by `services/case_dedupe.py::merge_provisional` (a provisional row without
> portal records merged into the row holding its CNR); merged rows keep their `ref_no` and events and leave every
> list.

Group 4, `causelist_entries` row, replace "Immutable once written." with:

> Immutable once written, except `case_id`, which is filled on resolution and re-pointed when a provisional case is
> merged into the row holding its CNR (design `data-load-console`, decision 14).

Group 0: `ref_event_type` + `case_merged` ("Case merged", not on the tracking card), upserted by `aslms seed`.
`ref_permission` + `admin.data_load` (module `admin`), from `aslms seed`. `role_permissions` rows for it are all
disabled by default.

Migration content:
1. `CREATE TYPE fetch_lane AS ENUM ('request','daily','load')`, `CREATE TYPE load_order AS ENUM (...)`. `ALTER
   TYPE link_kind ADD VALUE 'court_duplicate'`, `ALTER TYPE link_source ADD VALUE 'dedupe'` (each in its own
   autocommit block, as Postgres requires before the value is used).
2. `fetch_queue.lane` NOT NULL default `daily`, `fetch_queue.list_date`, the two indexes; `napix_call_log.lane`.
3. `data_load_settings` with its checks, partial unique index, `set_updated_at()` trigger, `COMMENT ON TABLE
   'class=master'`, grants for `aslms_app` (SELECT, INSERT, UPDATE) and `aslms_readonly` (SELECT).
4. Data step (classifies the rows of the running historical load):
   - `causelist_day` rows at priority 60 become `load` with `list_date = ref::date`;
   - `dossier` rows at priority 45 become `load`, with `list_date` the earliest list date of an entry carrying
     that CNR (or that printed number for `<est>|<number>` refs);
   - `order_pdf` rows whose CNR has a `load` dossier row become `load` with its `list_date`;
   - pending load rows take the default `cases_first` priorities (dossier 44, day 46, order PDF 48);
   - daily-lane pending `order_pdf` rows at 75 move to 40.
   `napix_call_log.lane` stays NULL for past calls.
5. Downgrade drops the table, the columns, the indexes and the two new types. Enum values added to `link_kind`
   and `link_source` cannot be dropped and stay, unused. Priorities stay as changed.

Models: `FetchQueueItem.lane`, `.list_date`, `__table_args__` indexes; `NapixCallLog.lane`; new
`DataLoadSettings` (`domain/ops.py`); `FetchLane`, `LoadOrder`, `LinkKind.COURT_DUPLICATE`,
`LinkSource.DEDUPE`, `EventType.CASE_MERGED`, `Permission.ADMIN_DATA_LOAD`, so `test_database_matches_the_models`
stays green.

Settings (`core/config.py`, `.env.example`): `NAPIX_LIVE_RESERVE` (100; validated `NAPIX_SEARCH_FLOOR ≤
NAPIX_LIVE_RESERVE ≤ NAPIX_RATE_RESERVE`), `DATA_LOAD_ESTIMATE_WINDOW_DAYS` (7, 1–30). Reused:
`NAPIX_RATE_RESERVE`, `NAPIX_SEARCH_FLOOR`, `NAPIX_SEARCH_PER_USER_HOUR`, `REPORT_STATEMENT_TIMEOUT_SECONDS`.

## Services
**`services/queue.py`** (changed)
- `enqueue(..., lane=FetchLane.DAILY, list_date=None)`: on conflict `lane = LEAST(existing, new)` while the row is
  pending or being revived, and `list_date = COALESCE(existing, new)`. The return value is unchanged.
- `claim(session, kinds=None, *, lanes=None)`: the pause clause (decision 2) and an optional lane filter; order
  `priority, created_at` (served by `ix_fetch_queue_claim`).
- `PRIORITY` gains `request` 30 and `order_pdf_live` 40, and drops `list_history` (decision 5). The module docstring states the full table.

**`services/data_load.py`** (new)
- `current_settings(session) -> LoadSettings` (defaults when the table is empty).
- `load_priority(settings, kind, list_date) -> int` (decision 3's table).
- `QueueOrigin(lane, list_date)`: passed by the runner into the stages that enqueue
  (`causelists.load_causelist_day` → `apply_entries`; `court_search.fetch_dossier` → `orders.enqueue_order_pdfs`),
  which compute lane and priority from it. The `daily` origin keeps 40 for dossiers and 40 / 80 for order PDFs; the
  `load` origin uses `load_priority`; the `request` origin gives dossiers 30 and order PDFs 40.
- `pause(session, actor, member, reason)`, `resume(session, actor, member)`, `set_order(session, actor, member,
  order, first_from, first_to, reason) -> {version, reprioritised}`: insert a version, close the previous one, and
  for `set_order` run one `UPDATE fetch_queue SET priority = CASE … END WHERE lane = 'load' AND status =
  'pending'`. Each writes one audit row. Pausing while paused, or resuming while running, answers 409
  `no_change`. `first_from > first_to`, or a period outside the load period, gives `LoadInputError("bad_period")`.
- `preview(session, from_, to, today=None) -> Preview` (decision 9; reads only).
- `start(session, actor, member, from_, to, held, today=None) -> StartResult {days, queued, held_skipped,
  held_requeued, revived, masters_queued}`: bounds give `LoadInputError("bad_range")`; held days with `held is
  None` raise `AlreadyHeld(counts)`. It enqueues each day with `lane=load`, `list_date=day`, `load_priority`, and
  `requeue` only for held days under `refetch`. Audit `data_load.started` (range, choice, counts).
- `progress(session, settings, now=None) -> dict` (decision 7) and `estimate(session, settings, now=None) ->
  Estimate {finish_at, hours, calls_needed, basis, reason}` (decision 8). They read only, under `with_timeout`.
- `coverage(session, from_month, to_month) -> list[MonthCoverage]` (decision 6), at most 36 months per call,
  under `with_timeout`; a timeout raises `SearchTimeout`.
- `check_held(session, request) -> Held | None` (decision 10; reads only, makes no call).
- `fetch(session, actor, user, request, *, force, hc, recorder, settings) -> CourtSearchResult`: without `force`,
  `check_held` first and `AlreadyHeld` / `SearchedBefore`. Then `court_search.guard` and
  `court_search.search_court(..., force=force, audit_extra={"via": "data_load", "force": force, "warned": …})`.
- `fetch_details(session, actor, user, refs, force) -> list[DetailState]` (decision 11).

**`services/case_dedupe.py`** (new)
- `number_key(case_type_text | case_type_id, reg_no, reg_year, case_no_text)`, `lock_number(session, court_id,
  key)` (advisory transaction lock).
- `find_provisional(session, court, key) -> Case | None`.
- `adopt(session, provisional, cnr)`: sets the CNR and keeps `is_provisional` until the dossier applies (as today).
- `merge_provisional(session, p, c, actor) -> MergeResult | NeedsReview` (decision 14);
  `portal_records(session, case) -> list[str]` (the record kinds found).
- `link_court_duplicates(session, case) -> int` (decision 15; idempotent by the `case_links` unique key).
- `check_cases(session, case_ids) -> DedupeReport`: inline after an apply.
- `sweep(session, *, dry_run=False, batch=1000) -> DedupeReport {merged, needs_review, court_linked}`: grouped
  queries over provisional rows sharing a key with a CNR row, provisional pairs (the younger merged into the
  older), and CNR pairs sharing a number or filing key.

**Changed modules**
- `services/cases.py`: `find_case` uses `number_key` and `get_or_create_case` takes the lock. `apply_dossier`
  callers run `case_dedupe.check_cases`.
- `services/court_search.py`: `fetch_dossier` adopts a provisional row (decision 13). `search_court` and the
  `_search_*` helpers take `force`, and `_finish` merges `audit_extra`. `fetch_court` merges a mergeable provisional
  row and reports the surviving case. `store_search_rows` runs `check_cases`.
- `services/runner.py`: seeds the remaining count from the call log at the start of a pass; claims by budget band
  (decision 4); sets `recorder.lane` per item; builds the `QueueOrigin` from the item. In `_dossier`, a resolved CNR
  held elsewhere goes to `merge_provisional`, and `NeedsReview` ends the row `skipped`. `enqueue_days` takes the lane
  and policy.
- `services/napix_store.py`: `NapixRecorder.lane` is written to `napix_call_log.lane` on flush.
- `services/causelists.py`, `services/orders.py`, `services/tracking.py`, `services/schedules.py`: lane and
  priority from the origin. Daily schedules pass `daily`.
- `services/napix_admin.py`: `refetch_day` and `refetch_case` take `force` and raise `AlreadyHeld` (decision 12).
  Requests use lane `request`. `retry_failed` takes `lane`.
- `services/data_health.py`: queue depths add the split by lane, and `queue_rows` takes `lane`.
- `services/access_seed.py`: label of `admin.data_load`; no default holder.
- `services/seed.py`: `case_merged` event type.
- `jobs/celery_app.py`: `dedupe-sweep` at 03:00 IST (`job_runs` row with the counters).

## API
Errors `{code, message}` as elsewhere; times in IST; `{case}` an id, `ref_no` or CNR.
`load_reader = require_any(admin.data_load, reports.state, admin.napix_refetch, admin.masters_sync)`.

New router `api/routers/data_load.py` (prefix `/admin/data-load`):

| Method and path | Function | Request | Response |
|---|---|---|---|
| `GET /admin/data-load` | `load_reader` | — | `{as_of, napix_enabled, settings: {version, paused, load_order, first_from, first_to, reason, changed_at, changed_by}, period: {from, to} \| null, totals: {days: {calendar, with_lists, no_list, waiting, failed, not_queued}, cases: {listed, with_details, provisional}, orders: {referenced, stored, not_available, waiting}}, work_left: [{kind, pending, runnable, waiting, running, failed}], failures: {by_kind: [{kind, failed}], latest: [{id, kind, ref, attempts, last_error, finished_at}]}, allowance: {hour_started_at, used: {load, daily, request, outside_queue}, remaining, rate_reserve, live_reserve, search_floor, seconds_to_next_hour}, estimate: {finish_at, hours, calls_needed, reason, basis}}` |
| `GET /admin/data-load/coverage` | `load_reader` | `from`, `to` (`YYYY-MM`; default the load period; at most 36 months) | `{months: [{month, days: {...as totals}, lists, entries, lists_parse_failed, cases: {...}, orders: {...}, work_left: {causelist_day, dossier, order_pdf}, failed: {...}, days_covered_pct, details_pct}]}`; 400 `bad_period`; 503 `search_timeout` |
| `POST /admin/data-load/preview` | `admin.data_load` | `{from, to}` | `{days, held_with_lists, held_no_list, waiting, failed, not_queued, calls_estimate \| null, masters_stale}`; 400 `bad_range` |
| `POST /admin/data-load/start` | `admin.data_load` | `{from, to, held?: "skip" \| "refetch"}` | 202 `{days, queued, held_skipped, held_requeued, revived, masters_queued}`; 409 `already_held` `{held_with_lists, held_no_list}`; 400 `bad_range` |
| `POST /admin/data-load/pause` | `admin.data_load` | `{reason}` (3–500) | `settings`; 409 `no_change` |
| `POST /admin/data-load/resume` | `admin.data_load` | `{reason?}` | `settings`; 409 `no_change` |
| `PUT /admin/data-load/order` | `admin.data_load` | `{load_order, first_from?, first_to?, reason}` | `{settings, reprioritised}`; 400 `bad_period` |
| `POST /admin/data-load/fetch` | `admin.data_load` | `{kind: "cnr", cnr} \| {kind: "case_number", case_type, reg_no, reg_year} \| {kind: "party", name, reg_year, pend_disp}`, `force` (default false) | `CourtSearchOut` (as `/cases/search-court`); 409 `already_held` `{cases: [CaseSearchItemOut + dossier_fetched_at, dossier_stale]}`; 409 `searched_before` `{last_searched_at, stored, local_matches}`; 503 `napix_off` / `napix_budget`; 429 `search_limit`; 502 / 504 as the court search |
| `POST /admin/data-load/fetch-details` | `admin.data_load` | `{cases: [ref] (1–200), force}` | `{items: [{case: CaseSearchItemOut, state: queued \| already_held \| merged \| no_reference \| not_found, queue: QueueStateOut \| null, merged_into_ref_no?}]}` |
| `GET /admin/data-load/duplicates` | `load_reader` | `kind` (`merged` / `court` / `review`), `limit` (1–200, 50), `offset` | `{total, items: [{kind, case: {id, ref_no, cnr, case_no_text}, other: {id, ref_no, cnr, case_no_text}, at, reasons?}]}` |
| `POST /admin/data-load/duplicates/scan` | `admin.data_load` | — | `{merged, needs_review, court_linked}` |

Changed (router `napix_admin.py`, functions unchanged):

| Method and path | Change |
|---|---|
| `POST /admin/napix/refetch/day` | body `{date, force?}`; 409 `already_held` `{status, lists_stored, finished_at}` without `force` |
| `POST /admin/napix/refetch/case` | body `{case, force?}`; 409 `already_held` `{dossier_fetched_at, dossier_stale}` without `force` |
| `POST /admin/napix/queue/retry-failed` | body `{kind, lane?}` |
| `GET /admin/napix/queue` | query `lane`; items carry `lane`, `list_date` |
| `GET /admin/data-health` | `queue.by_kind` items carry `by_lane: {request, daily, load}` |

`QueueStateOut` gains `lane`. The 409 answers write nothing and make no call. No `GET` calls NAPIX. Case summaries
follow the search rule (any non-merged case's summary with `visible`; no details of an invisible case).
`frontend/openapi.json` and `schema.d.ts` are regenerated.

Portal (`frontend/`):
- `routes.ts`: replace the `health` entry with `{key: "data", label: "Data collection", href: "/data/load",
  functions: [admin.data_load, reports.state, admin.napix_refetch, admin.masters_sync], built: true}`, plus
  `DATA_TABS` (Load, Health, Queue and calls, Duplicates) and the crumbs.
- `app/(portal)/data/load/page.tsx`, `components/data/LoadConsole.tsx`:
  - status banner (running or paused, reason, who, since; the API's switch with the worker note);
  - allowance card (used this hour by lane, remaining against the three thresholds, next reset);
  - work left by kind; the estimate with its basis, or the reason there is none;
  - failures, with "Retry failed" per kind in the load lane (`admin.napix_refetch`);
  - the coverage table month by month, loaded on demand; a month opens its days through `GET
    /admin/napix/queue?kind=causelist_day&ref=YYYY-MM`;
  - the actions panel (`admin.data_load`): Start a load (range → preview → choice for held days), Pause / Resume
    (reason), What goes first (preset and optional period, reason), Fetch from the court (three forms, the
    `already_held` / `searched_before` dialog with "Fetch anyway", party-name results with checkboxes and "Fetch
    details").
- `app/(portal)/data/health/page.tsx`, `components/data/Health.tsx`: the snapshot blocks of `GET
  /admin/data-health` and `GET /admin/napix/health`; buttons Sync masters (`admin.masters_sync`), Re-fetch a day,
  case or order PDF (`admin.napix_refetch`, with the warning dialog), Connectivity check (either function; its
  refusals as messages).
- `app/(portal)/data/queue/page.tsx`: queue rows (filters kind, status, lane, ref prefix; Retry) and the call log
  (keyset "More").
- `app/(portal)/data/duplicates/page.tsx`: the three lists and "Scan now" (`admin.data_load`).
- All strings in `messages.ts`; the API's codes become messages.

## Jobs
- **Queue (existing worker):** no new kind. Lanes and priorities as decisions 1–5. Ref formats unchanged
  (`causelist_day/<YYYY-MM-DD>`, `dossier/<CNR>` or `<est>|<number>`, `order_pdf/<CNR>|<order_no>|<date>`,
  `masters/all`).
- **Beat:** `dedupe-sweep` daily at 03:00 IST (`aslms.dedupe_sweep`, `job_runs` row `dedupe-sweep` with
  `{merged, needs_review, court_linked}`); makes no NAPIX call.
- The worker must be restarted on the new image after migration 0014 (the runner's claim and budget change).

## Tests
Unit (`tests/unit/test_data_load_unit.py`, `test_case_dedupe_unit.py`):
- `test_load_priority_table`: each preset × brought forward or not gives decision 3's numbers, and all load
  priorities fall in 41–48.
- `test_estimate_formula_and_reasons`: a measured basis gives the expected calls and hours; paused, under 24 h of
  history and no recent calls give their reasons.
- `test_number_key`: `WP(C)/4326/2025`, `WP (C)/4326/2025` and (type id, 4326, 2025) give one key; another type
  or court gives another.
- `test_reserve_settings_validated`: `live_reserve` outside `[search_floor, rate_reserve]` is refused.

Database (`tests/db/test_queue_lanes.py`):
- `test_lane_precedence_on_enqueue`: a load dossier asked by the daily lane becomes `daily` with priority 40; a
  daily row asked by the load stays `daily`.
- `test_spawned_rows_inherit_lane_and_list_date`: a load day (scripted gateway, sample list) queues its dossiers
  as `load` with the day's date; their order PDFs follow as `load`.
- `test_pause_skips_only_load`: paused, claim returns daily and request rows and never a load row; resumed, the
  load row is claimed.
- `test_budget_bands`: remaining 140 claims daily and not load; remaining 90 claims nothing; remaining 200 claims
  load.
- `test_pass_seeds_remaining_from_call_log`: a call logged this hour with remaining 120 keeps a fresh pass from
  claiming a load row.
- `test_call_log_lane_recorded`: calls made for a load item are logged `load`, and court-search calls NULL.
- `test_live_order_pdfs_at_40`.

Database (`tests/db/test_data_load.py`, `tests/db/test_api_data_load.py`):
- `test_start_preview_counts_exact`: seeded day rows of each state; the preview figures equal the seed.
- `test_start_refuses_without_choice_when_held`: 409 `already_held`; no row written; no audit row.
- `test_start_skip_and_refetch`: `skip` leaves done days done; `refetch` re-queues them; failed days revived; one
  `data_load.started` audit row with the counts; masters queued only when stale.
- `test_start_bounds`: today, tomorrow and `from > to` give 400 `bad_range`.
- `test_pause_resume_versions_and_audit`: versions 1, 2, 3; `no_change` 409; audit rows.
- `test_order_change_reprioritises_pending_load_rows_only`: running, done and daily rows untouched;
  `reprioritised` equals the count; the period brought forward gets 41–43.
- `test_progress_and_allowance_exact`: seeded queue rows, call-log rows this hour by lane and earlier; every figure
  equals the seed.
- `test_coverage_month_figures_exact`: two months of seeded lists, entries, cases with and without details, and
  orders; each month's figures and percentages equal the seed.
- `test_fetch_cnr_already_held_then_force`: held with details gives 409 without a gateway request and without an
  audit row; `force` makes one CNR call, updates the case and writes `case.search_court` with `via`, `force` and
  `warned`.
- `test_fetch_cnr_listed_without_details_fetches_directly`.
- `test_fetch_case_number_held_and_party_searched_before`.
- `test_fetch_guard_shared_with_court_search`: the per-user limit counts both endpoints; switch off gives 503
  `napix_off` with no call.
- `test_fetch_results_respect_visibility`: a manager without sight of the case gets the summary with `visible:
  false` and no details.
- `test_fetch_details_queues_request_lane`: priority 30; held without `force` reported `already_held`; merged
  reported with the surviving `ref_no`.
- `test_refetch_day_and_case_warn_then_force`: 409 `already_held`, then 202 with `force`; the order PDF stays 409
  `already_stored`.
- `test_retry_failed_by_lane`.
- `test_permissions`: no default type holds `admin.data_load`; the super admin and a granted login act; a health
  reader reads the progress but gets 403 on every action; a login without either gets 403 on reading.

Database (`tests/db/test_case_dedupe.py`):
- `test_fetch_dossier_adopts_provisional`: a provisional `WP(C)/4326/2025` and a CNR search for the CNR the court
  gives for that number leave one row (the provisional's `ref_no` kept), not two.
- `test_runner_merges_provisional_into_cnr_holder`: the `<est>|<number>` ref resolving to a CNR held under another
  printed form merges instead of failing. Entries are re-pointed, recommendations expired, the holder rescored,
  `case_merged` event and `case.merged` audit row written, and the queue row is `done`.
- `test_provisional_with_portal_records_not_merged`: a claimed provisional gives a `case_duplicate` failure row and
  a `skipped` queue row, and both cases stay unchanged.
- `test_court_duplicates_linked_not_merged`: two CNRs with one number get one `court_duplicate` link, `case_linked`
  events, and the linked-case signal recommends the claimer's department for the other (never claimed
  automatically).
- `test_filing_number_duplicates_linked`.
- `test_concurrent_provisional_creation_one_row`: two sessions creating the same printed number end with one row
  (advisory lock).
- `test_sweep_dry_run_writes_nothing_and_real_run_counts`.
- `test_merged_case_leaves_lists_and_search`.

Migration (`tests/integration/test_migrations.py` and `tests/db/test_migration_0014.py`):
- `test_0014_classifies_existing_rows`: seeded rows at 60, 45 and 75 before the upgrade come out as load / load /
  daily at 40, with `list_date` from the entries.
- Upgrade → downgrade → upgrade; `test_database_matches_the_models`; `test_schema_metadata`.

Frontend (Vitest, `components/data/*.test.tsx`):
- The console renders progress, allowance and estimate, and the no-estimate reasons.
- Actions show only with `admin.data_load`; retry shows only with `admin.napix_refetch`.
- The start flow: preview, then the held-days choice, then start.
- The `already_held` and `searched_before` dialogs: "Fetch anyway" resends with `force: true`; "Cancel" sends
  nothing.
- Pause needs a reason.
- The health tab's buttons by function; the duplicates lists; the navigation entry and tabs by function.
- `backend/tools/portal_smoke.py` lists `/data/load`, `/data/health`, `/data/queue`, `/data/duplicates`.

## Verification
1. `ruff check` clean, `pytest -q` green; in `frontend/`: `npm run lint`, `typecheck`, `test`, `build` pass and
   `npm run gen:api` leaves no diff; `docker compose build web`.
2. With the owner's go-ahead (this applies 0009–0014 to the dev database): before migrating, record `SELECT kind,
   priority, status, count(*) FROM fetch_queue GROUP BY 1, 2, 3`. Stop `worker`, run `docker compose run --rm
   init`, then start `worker` and `scheduler` on the new image. Afterwards, `SELECT lane, kind, count(*) FROM
   fetch_queue GROUP BY 1, 2` matches the recorded counts: priority-60 days and priority-45 dossiers are `load`,
   with their order PDFs.
3. `aslms data-load status` and `GET /admin/data-load` as the super admin agree. `period.from` is 2025-01-01,
   `work_left` equals `SELECT kind, count(*) FROM fetch_queue WHERE lane = 'load' AND status = 'pending' GROUP BY
   kind`, and `allowance.used` sums to `SELECT count(*) FROM napix_call_log WHERE called_at >= date_trunc('hour',
   now())`.
4. `GET /admin/data-load/coverage?from=2025-01&to=2025-01`: January's `days.calendar` is 31, and
   `with_lists + no_list` equals the done and skipped `causelist_day` rows of January.
5. `POST /admin/data-load/pause {"reason": "verification"}`; for 10 minutes `SELECT count(*) FROM fetch_queue
   WHERE lane = 'load' AND started_at > <pause time>` stays 0, while daily rows (run `aslms daily-cycle lists`) are
   claimed. Resume, and load rows are claimed again. Three `data_load.*` audit rows.
6. `PUT /admin/data-load/order {"load_order": "lists_first", "reason": "verification"}`: pending load days now at
   44 and dossiers at 46; `reprioritised` equals the pending load count. Restore `cases_first`.
7. `POST /admin/data-load/start {"from": "2025-01-02", "to": "2025-01-03"}` gives 409 `already_held`, and
   `napix_call_log` and `fetch_queue` counts are unchanged.
8. `aslms data-load dedupe --dry-run` prints the pairs in the dev database. The real run merges the mergeable
   ones. `SELECT count(*) FROM cases WHERE cnr IS NULL AND merged_into_case_id IS NULL AND <number key shared with
   a CNR row>` is then 0, except the `case_duplicate` review pairs listed by `GET
   /admin/data-load/duplicates?kind=review`.
9. Portal in the Compose `web` service: `portal_smoke.py` passes for the four pages. As a login granted
   `admin.data_load`, the console shows the actions; as the central operator, Health and Queue show their buttons
   but the console shows no actions.
10. A live single fetch (one CNR call) is run by the owner with `NAPIX_ENABLED` set for that run only. Fetching
    the same CNR again shows the "already held" dialog without a call, and "Fetch anyway" makes one call.

## Open questions
None. The owner checks are marked in decisions 3, 4, 12 and 15. Each is a default the owner may change at approval;
none blocks the design.

## Left for later
- Resolving provisional rows that carry portal records (`case_duplicate` review pairs): moving claims, custody,
  notes and documents to the CNR row needs the owner's rules (decision 14).
- A summary table for coverage if the live query ever exceeds the timeout (decision 6).
- NAPIX search by advocate and filing number in the console (row 21).
- A department discovery lane (row 19) would join as a fourth lane or as `load` rows with its own `list_date`-less
  origin.
- Re-running today's Current Status batches early (audit-screens decision 12, row 41).

## Deviations
Written by the developer while building (smallest reasonable choices where the design was silent):
1. **The lane and priority policy lives in `services/load_policy.py`.** `LoadSettings`, `current_settings`,
   `load_priority` and `QueueOrigin` sit in a small module that `causelists`, `orders`, `court_search` and the runner
   import; `services/data_load.py` re-exports them. Keeping them in `data_load.py` would make an import cycle
   (`data_load` → `court_search` → `orders` → `data_load`).
2. **Skipped days count as held.** A `causelist_day` row that ended `skipped` (the court published no list) is
   `held_no_list` and follows the `held` choice like a done day (`skip` leaves it, `refetch` re-queues it), matching
   the 409 body `{held_with_lists, held_no_list}`. "Always revived" applies to failed days only.
3. **Portal records checked before a merge also include `custody_history` and `case_stages`** (both are portal
   records of a case; decision 14 listed the others).
4. **A provisional row sharing its number with several CNR rows** (court duplicates) is merged into the oldest of
   them (deterministic); the court-duplicate link joins the others.
5. **A person's court search queues its order PDFs in the `request` lane** (priority 40): `POST /cases/search-court`,
   `/cases/{ref}/fetch-court` and the console's fetch pass a request origin to `fetch_dossier`.
6. **Linking court duplicates rescores both cases at once**, so the linked-case recommendation appears without
   waiting for the next rescore (decision 15's signal; never an assignment).
7. **The advisory lock is taken only on the creation path**: `get_or_create_case` looks up first and, when nothing
   matches, takes the lock and looks again before inserting. A cause-list day with thousands of known cases takes
   no lock for them, which keeps the transaction's lock count small.
8. **`fetch-details` items carry `ref`** (as sent); `case` is null for `not_found`.
9. **Error bodies are JSON-encoded centrally**: `api/errors.detail` passes the extras through `jsonable_encoder`, so
   the 409 bodies carry IST times as ISO strings.
10. **`aslms load` over a range reaching today**: the days up to yesterday go through `data_load.start` (held days
    skipped, or re-fetched with `--requeue`; audited); today and later are queued in the `daily` lane at 20. The
    old unconditional masters row is queued only when the range has no backdated day (start queues it when stale).
    `aslms refetch-date` and `refetch-case` take `--force` for held data.
11. **Defaults written into rows**: the masters row queued by a start is in the `request` lane at 10; a resume
    without a reason stores "resumed" (`reason` is NOT NULL).
12. **`GET /admin/data-health`'s `by_lane`** counts the pending rows of each kind per lane.
13. **Coverage's `lists`** counts the month's cause lists with a stored PDF; `entries` counts every entry of the
    month's lists; `lists_parse_failed` the lists whose parse failed.
14. **The 409 `already_held` body of `POST /admin/data-load/fetch` is not in the OpenAPI document** (error bodies are
    untyped there); the portal types `HeldCase` by hand from `CaseSearchItemOut`.
15. **`aslms data-load dedupe --dry-run` writes nothing** (no audit row), like the sweep's dry run; the real run and
    the 03:00 job write `data_load.dedupe_scan` (the job as the `system` actor) besides the job's `job_runs` row.
16. **The portal's "Data collection" entry stays current on every `/data/...` page** (the sidebar matches the
    entry's first path segment), and `/data` opens the first tab the login may see.
17. **A zero or negative number makes a key unusable** (review finding). NAPIX gives a filed but unregistered case
    `reg_no` 0 and `reg_year` 0 (printed `WA/0/0`; 203 such CNR rows in the dev database, 42 of them `WA/0/0`). A
    number or year of zero or less, whether given or parsed from the printed number, means the case has no case
    number key (neither the compact form nor type, number and year). A filing number or year of zero or less means
    it has no filing key. So such rows are never merged, never adopted as provisional rows and never linked as the
    court's duplicates. The sweep's candidate query skips them as well. A provisional row printed with a zero number
    takes no number lock and is never found again by its number. The dev database has no cause-list entry like that.
18. **The merge locks the provisional row before it checks for portal records** (review finding). `merge_provisional`
    takes `SELECT ... FOR UPDATE` on P's row, re-reads P and checks `cnr` and `merged_into_case_id` again, and only
    then checks P's portal records. A claim locks the same row, and an uncommitted insert that references P (note,
    document, custody row) holds a key-share lock that conflicts with `FOR UPDATE`. So a write made at the same
    time is either seen by the check, which lists the pair for review, or it waits and then finds P merged. If P
    got a CNR or was merged while the merge waited, `merge_provisional` raises `MergeStale` (a `ValueError`). The
    sweep and the console scan skip the pair. The user's court fetch answers 409 `already_fetched` ("changed while
    it was being merged; open it again"). In the runner the queue item fails and is retried, and the retry finds
    the row as it now stands.
