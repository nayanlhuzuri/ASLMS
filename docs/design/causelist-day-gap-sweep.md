# Design: Cause-list days nobody asked for — a nightly sweep, the daily cycle's catch-up, and the days named

```
slug: causelist-day-gap-sweep
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 200 (owner, 28 Oct 2026: "yes add it"). Found on 28 Oct 2026 (decisions log, "Operations on 28 Oct"): 2, 3,
4 and 5 October 2026 had never been queued. The backdated load was set up on 1 Oct to end on 1 Oct, and the daily cycle's
first run on 7 Oct began from 6 Oct, so the four days fell between them. The Overview showed "662 of 666 days" and
nothing filled the gap; they were queued by hand (`aslms data-load start --from 2026-10-02 --to 2026-10-05`) and fetched
(666 of 666, 0 failed). The same happens whenever the machine is off for several days. The owner proposed: (1) a nightly
sweep that queues, in the load lane, every day from the start of the collection period to yesterday with no
`causelist_day` row, idempotent, recorded in `job_runs`, with a dry-run CLI; (2) the Overview and `aslms data-load
status` name such days ("Days Not Asked For: n", with the dates) instead of folding them into the total; (3) check
whether the daily cycle catches up the days it missed after an outage, and make it do so if not.

The plan: §6.1 "Every day, before court hours, the scheduler runs the complete collection cycle for the next cause list
date"; §3.1 (scheduler and job queues run all data collection in the background; "a failed call is retried and logged,
never lost"); §5 data collection health ("status of the daily data cycle, and any failed API calls"). CLAUDE.md: NAPIX
only through `backend/aslms/integration/napix/`; `NAPIX_ENABLED` is never turned on in code or tests.

**Finding for (3): the daily cycle does not catch up.** Read from the code (no run was made):
- `schedules.enqueue_daily_lists` (06:30 and 18:30 IST, `lists-daily` / `lists-evening`) queues exactly yesterday,
  today and tomorrow. Nothing looks further back.
- Celery beat keeps its schedule file in `/tmp` (`compose.yml`, scheduler: "lost on recreate, which only means each
  crontab entry next fires at its next due time"). After a recreate a missed 06:30 or 18:30 run is not replayed; after a
  plain restart or a machine waking from sleep beat replays a missed entry at most once. Either way the replayed run
  queues only the three current days.
- So an outage of k days leaves the days from (first day of the outage − 1) to (today − 2) without a row, and the
  scheduler restarted at 10:00 does not queue even today's list until 18:30. Nothing else queues them: the backdated load
  ends where its operator set it (`check_range`: at yesterday at the latest), and the Overview counts them only as the
  difference between "collected" and "calendar".

In place and reused: `fetch_queue` with the unique (`kind`, `ref`) row per day (`causelist_day/<YYYY-MM-DD>`) and its
lanes `request` < `daily` < `load` (a row asked by two lanes keeps the higher one and the better priority);
`queue.enqueue`; `load_policy.load_priority` and `current_settings` (the load's preset, the period brought forward, the
pause); `data_load._day_states` (every `causelist_day` row in the range, any lane, by state), `_day_totals`
(`not_queued` already counted), `load_period`, `overview`, `status_lines`; `schedules.PLAIN_SCHEDULE` and
`schedule_view` (the Automatic Collection tab's plain schedule with last runs); `job_repair.SCHEDULER_JOBS`; the runner,
which already handles a holiday as a `skipped` day after one Cause List Bench call (`causelists.load_causelist_day`:
"False when the gateway has no benches for the date"), and the bands that let the daily lane use the live reserve while
the load lane waits above the rate reserve (`runner.py`, design `data-load-console` decision 4).

No NAPIX field or endpoint is involved: the sweep and the catch-up only write queue rows of the existing kind; the
worker fetches them through the integration layer as today.

Not covered: reviving `failed` days (they have the retry ladder and Retry / Retry All on Problems and Fixes); re-fetching
days held as "no list" (`skipped`); a portal button to queue the days (the nightly sweep does it; Load Control's start
remains for a person); a Prometheus metric or alert for days not asked for (can be a later row); the Month by Month
table (unchanged).

## Decisions
1. **The collection period starts at the earliest day asked for by the load or the daily cycle.** `collection_start` is
   the smallest `ref` of the `causelist_day` rows in the `load` and `daily` lanes (ISO dates, so text order is date
   order); the period runs to yesterday (IST). Rows of the `request` lane are left out of the start, so one person
   fetching a single old date from the Cause List screen does not stretch the period back years. With no such row (a
   new install before its first daily run) there is no period and the sweep does nothing. Alternatives: the load period
   alone (`load_period`, load lane only: an install without a backdated load would never be swept, and a load started
   after go-live would hide earlier gaps); every lane (the request-lane stretch above).
2. **A day "not asked for" is a day with no `causelist_day` row at all**, whatever its lane and status. A `done`,
   `skipped` (holiday, or no list), `pending`, `running` or `failed` row counts as asked: the sweep never re-queues,
   revives or re-prioritises an existing row. This is exactly the `not_queued` of `_day_totals`. Alternative: also
   revive `failed` days (they have their own retry ladder, failure records and Retry buttons; a sweep that revives them
   nightly would defeat the ladder's last step).
3. **Lane by age: recent missing days go to the daily lane, older ones to the load lane.** A missing day within the last
   `CAUSELIST_CATCHUP_DAYS` days (default 7; 0 to 31) is queued in the `daily` lane, priority 22 (a new
   `queue.PRIORITY["list_catchup"]`, after today's lists 20 and their rechecks 21, before status batches 30), and
   tomorrow, today and yesterday at 20 as the daily cycle does; an older missing day is queued in the `load` lane at
   `load_priority(settings, causelist_day, day)` (41-46 by the preset and the period brought forward, as
   `data_load.start` does), `list_date` = the day in both cases, no person. The same rule is used by every caller
   (decisions 4 and 5), so whichever runs first puts a day in the same lane. Reason: an outage of a few days leaves
   recent lists missing whose hearings, next dates and recommendations officers need now; in the load lane they would
   wait behind the backdated load (or its pause). The window keeps the daily lane, which may spend the live reserve, from
   taking months of old days. This applies the owner's proposal (1) "in the load lane" to days older than the window
   and answers (3) for the recent ones; flagged for the owner to confirm. Alternatives: everything in the load lane
   (recent days wait for the backdated load, and do not run at all while it is paused); everything in the daily lane
   (a long gap could take the live reserve for days).
4. **The nightly sweep `causelist-gap-sweep`, 04:15 IST.** A beat entry queues every missing day from
   `collection_start` to yesterday by decision 3, then writes one `job_runs` row `causelist-gap-sweep` with
   `{trigger: "nightly", from, to, missing, queued_daily, queued_load, ranges (at most 20), paused}` (`succeeded`, or
   `failed` with the error, re-raised for the worker log). Never today or tomorrow (the daily cycle's), never before
   `collection_start`. Idempotent: a second run finds the days it queued and queues nothing. No cap on the number of
   days: load-lane days run only in the calls left above the rate reserve, so a long gap costs time, not live work; a
   holiday costs one bench call. While the load is paused, load-lane days wait like the rest of the load (the run
   records `paused: true`). A system enqueue writes no audit row, as `disposed-refresh`. 04:15 is after the 02:30
   disposed refresh, 03:00 dedupe and 03:45 purge, and before the 06:00 masters and 06:30 lists. Alternatives: an
   hourly sweep (gaps arise from outages, and the start-up catch-up of decision 5 covers the morning after one); a cap
   per night (slower recovery for no gain, since the load lane already yields to live work).
5. **The daily cycle catches up after an outage (owner's item 3).** (a) At every scheduler start (`worker_ready`, after
   the job repair) the scheduler dispatches one task `aslms.lists_catchup` that queues, by decision 3, every day from
   today − `CAUSELIST_CATCHUP_DAYS` to tomorrow that has no row, bounded below by `collection_start`; so a scheduler
   started at 10:00 after three days off queues the missed days and today's and tomorrow's lists at once instead of at
   18:30. Days that already have a row are left as they are (the next 06:30 or 18:30 run refreshes the three current
   days as today). On a new install with no row, it queues only yesterday, today and tomorrow, as the first 06:30 run
   would. (b) The 06:30 and 18:30 runs, after their three days, fill the same window's older missing days (today −
   window to today − 2), so beat's replay after a machine wakes from sleep also catches up. Each catch-up that queued at
   least one day writes a `job_runs` row `lists-catchup` with `{trigger: "start" | "morning" | "evening", window_days,
   from, to, queued: [dates]}`; one that queued nothing writes none (no two empty rows a day). The 06:30 / 18:30 task
   results gain `caught_up`. Alternatives: rely on the nightly sweep alone (the morning after an outage would show no
   current list until 18:30 and recent days would land in the load lane); a persistent beat schedule file (replays one
   run, which queues only the three current days).
6. **The days are named on the Overview and in `aslms data-load status`.** `GET /admin/data-load/overview` gains
   `not_asked: {from, to, count, ranges: [{from, to, days}], more_ranges} | null` computed by the sweep's own function
   (decisions 1-2, to yesterday), so the screen names exactly what the next sweep will queue; ranges oldest first, at
   most 20, `more_ranges` counting the rest; `null` without a collection period. The Cause Lists tile keeps "662 of 666
   days" and adds, when `count` > 0, a warning line "Days Not Asked For: 4 · 2 Oct to 5 Oct 2026" (with "and n more
   ranges" past 20) and the tooltip "Days in the collection period that no collection has asked the court for yet. The
   nightly sweep at 04:15 asks for them." `aslms data-load status` prints after the cause-list line "Days not asked for:
   4 (2026-10-02 to 2026-10-05)" or "Days not asked for: none". The Automatic Collection schedule gains the entry
   "04:15 · Ask the court for past days' cause lists never asked for" with its last run and the fact "Last run queued n
   days". Alternatives: a fourth segment in the progress bar (the bar shows work; these days are work nobody has asked
   for, better named in words with their dates); counting to today (today belongs to the daily cycle and would show as a
   gap every night before 06:30 on a fresh period).
7. **The CLI: `aslms data-load gaps [--apply]`.** Without `--apply` (the default, a dry run) it prints the collection
   period, the count and the ranges, and for each the lane it would use; it writes nothing. With `--apply` it runs the
   sweep now (`trigger: "cli"`, the same `job_runs` row) and writes one `audit_log` row `data_load.gaps_queued` (the CLI
   actor, as `data-load start` writes `data_load.started`; after: the counters). Exit 0 in both cases. Alternative: a
   `--dry-run` flag on an applying command (a mistyped command would queue; the module's other actions are explicit).
8. **Nothing else changes.** No table, column, migration, `Permission`, reference code or API endpoint; the overview's
   reader functions (`admin.data_load`, `reports.state`, `admin.napix_refetch`, `admin.masters_sync`) are unchanged; no
   NAPIX call is made by the sweep, the catch-up, the overview or the CLI, and `NAPIX_ENABLED` is not read by them (rows
   queued while the switch is off wait for the worker as the daily cycle's rows do).

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): recent missing
days in the daily lane with a 7-day window, older in the load lane (3); 04:15 and no nightly cap (4); the catch-up at
scheduler start (5); `failed` and `skipped` days never touched by the sweep (2); request-lane rows not stretching the
period (1).

## Data
No table, column, constraint, index or migration. Paragraph for `docs/schema/schema.md` (appended to the operations
addenda, as earlier rows did):

> As built from causelist-day-gap-sweep: no table, column or migration. `job_runs.job` gains the free-text values
> `causelist-gap-sweep` (the nightly 04:15 IST sweep and `aslms data-load gaps --apply`) and `lists-catchup` (the daily
> cycle's catch-up at scheduler start and at 06:30 / 18:30, written only when it queued a day). `fetch_queue` priorities
> gain 22: a `causelist_day` row of the `daily` lane queued by the catch-up for a day older than yesterday within
> `CAUSELIST_CATCHUP_DAYS`. New audit action `data_load.gaps_queued` (a person's `--apply`; the nightly sweep writes no
> audit row).

New setting (`core/config.py`, `.env.example`, the runbook): `CAUSELIST_CATCHUP_DAYS: int = Field(7, ge=0, le=31)`.

## Services
- `services/causelist_gaps.py` (new; writes only `fetch_queue`, `job_runs` and, for `--apply`, `audit_log`; no NAPIX):
  - `collection_start(session) -> date | None` — decision 1 (`min(ref)` over `causelist_day` rows with lane `load` or
    `daily`).
  - `missing_days(session, start, end) -> list[date]` — decision 2, one indexed range read of `fetch_queue` (`kind`,
    `ref` between the two ISO dates), as `_day_states` does.
  - `ranges(days) -> list[tuple[date, date]]` — consecutive days folded.
  - `queue_days(session, days, *, today, settings, catchup_days) -> dict[str, int]` — decision 3; `queue.enqueue(...,
    requeue=False, lane=…, list_date=d)` per day; returns `{queued_daily, queued_load}`.
  - `not_asked(session, *, today=None) -> dict | None` — decision 6's block (start to yesterday, ranges capped at 20).
  - `run_sweep(session, cfg, *, trigger, today=None, actor=None, dry_run=False) -> dict` — decisions 4 and 7: reads the
    load settings once, computes the missing days, and unless `dry_run` queues them and writes the `job_runs` row (and
    the audit row when `actor` is given); a dry run returns the counters with the lane each day would take.
  - `catch_up(session, cfg, *, trigger, today=None) -> dict` — decision 5: window `today − CAUSELIST_CATCHUP_DAYS` to
    `today + 1` for `start`, to `today − 2` for `morning` / `evening`, bounded by `collection_start` (with no start:
    only yesterday to tomorrow, and only for `start`); writes `lists-catchup` when it queued a day.
- `services/queue.py`: `PRIORITY["list_catchup"] = 22`; the module docstring's priority list gains it.
- `services/schedules.py`: `enqueue_morning_lists` and `enqueue_evening_lists` call `catch_up(trigger=…)` after their
  days and return `caught_up`; `PLAIN_SCHEDULE` gains `{"key": "day-gaps", "beat": "causelist-gap-sweep", "when":
  "04:15", "what": "Ask the court for past days' cause lists never asked for", "job": "causelist-gap-sweep"}`;
  `schedule_view` adds the facts `{queued: queued_daily + queued_load, missing}` from the last run.
- `services/job_repair.py`: `SCHEDULER_JOBS` gains `causelist-gap-sweep` and `lists-catchup`.
- `services/data_load.py`: `overview` adds `not_asked` (decision 6) under the same statement timeout.
- `jobs/celery_app.py`: beat entry `"causelist-gap-sweep": crontab(hour=4, minute=15)` → task
  `aslms.causelist_gap_sweep` (`run_sweep(trigger="nightly")`); task `aslms.lists_catchup` (`catch_up(trigger="start")`);
  `on_worker_ready` dispatches `aslms.lists_catchup` after `repair_at_start` (best effort: a broker error is logged and
  the next 06:30 / 18:30 run catches up); the module docstring names both.
- `cli/data_load.py`: command `gaps` (decision 7); `status_lines` prints the line of decision 6.
- `api/schemas.py`: `DaysNotAskedOut {from, to, count, ranges: list[DayRangeOut], more_ranges}`, `DayRangeOut {from, to,
  days}`; `DataLoadOverviewOut.not_asked: DaysNotAskedOut | None`. `frontend/openapi.json` and
  `src/lib/api/schema.d.ts` regenerated.
- Frontend: `components/data/Overview.tsx` (the Cause Lists tile's line and tooltip, also shown under the "no period"
  note when `days` is null but `not_asked` is not); `components/data/AutomaticCollection.tsx` (the `day-gaps` fact);
  `lib/dataCollection.ts` (`notAskedLine(block)`); `lib/messages.ts` (`T.dc.notAsked*`, the schedule text);
  `e2e/fixtures` (the overview fixture gains `not_asked`).
- Documents: `docs/operations.md` (the 04:15 sweep, the catch-up at start, `aslms data-load gaps`,
  `CAUSELIST_CATCHUP_DAYS`), `docs/ASLMS_Process_Workflows.md` (the daily cycle), `docs/ASLMS_Software_Documentation.docx`
  and `docs/ASLMS_Hosting_Guide.docx` (the setting), `.env.example`, `docs/schema/schema.md` (the paragraph above).

Audit and events: `data_load.gaps_queued` for `--apply` only; no `events` row.

## API
One field added to an existing endpoint; no new endpoint.

| Method, path | Function required (`Permission`) | Change | Visibility |
|---|---|---|---|
| `GET /admin/data-load/overview` | any of `admin.data_load`, `reports.state`, `admin.napix_refetch`, `admin.masters_sync` (`data_load.READERS`, unchanged) | response gains `not_asked: {from, to, count, ranges: [{from, to, days}], more_ranges} \| null` | operational facts, the same for every reader |
| `GET /admin/data-load/schedule` | unchanged (`data_load.READERS`) | `entries` gains the `day-gaps` entry with `last_run_at`, `result`, `facts: {queued, missing}` | unchanged |

## Jobs
- `causelist-gap-sweep` — beat 04:15 IST daily, task `aslms.causelist_gap_sweep`; queues `causelist_day/<YYYY-MM-DD>`
  rows: lane `daily`, priority 22 (20 for yesterday) within `CAUSELIST_CATCHUP_DAYS`, else lane `load` at
  `load_priority` (41-46); `job_runs` `causelist-gap-sweep`.
- `lists-catchup` — task `aslms.lists_catchup`, dispatched once at each scheduler start; also run inside the 06:30 and
  18:30 list tasks; same rows and priorities, window `today − CAUSELIST_CATCHUP_DAYS` to tomorrow (start) or to
  today − 2 (list runs); `job_runs` `lists-catchup` when a day was queued.
- The worker fetches the rows as any `causelist_day` row (Cause List Bench, Details, Show Cause List through the
  integration layer); a holiday ends `skipped` after one call.

## Tests
Backend (pytest), `db/test_causelist_gaps.py` (new; no NAPIX, the queue only):
- `test_collection_start_is_earliest_load_or_daily_day_ignoring_request_lane`.
- `test_no_rows_no_period_sweep_does_nothing_and_records_zero_missing`.
- `test_missing_days_count_any_lane_and_any_status_as_asked` (`done`, `skipped`, `pending`, `running`, `failed`).
- `test_reproduces_2_to_5_october` (load rows to 1 Oct, daily rows from 6 Oct, today 28 Oct → the sweep queues exactly
  2-5 Oct in the load lane at the load priority with `list_date`).
- `test_recent_gaps_go_to_the_daily_lane_at_22_and_yesterday_at_20`; `test_window_zero_sends_every_gap_to_the_load_lane`.
- `test_load_priority_follows_the_preset_and_the_period_brought_forward`.
- `test_sweep_never_queues_today_tomorrow_or_before_the_start`.
- `test_sweep_is_idempotent` (second run: 0 queued) and `test_sweep_never_revives_failed_or_skipped_or_reprioritises`.
- `test_sweep_while_paused_queues_and_records_paused`.
- `test_sweep_job_run_counters_and_ranges_capped_at_20`; `test_sweep_failure_marks_run_failed_and_reraises`.
- `test_nightly_sweep_writes_no_audit_row`; `test_cli_apply_writes_gaps_queued_audit_row`;
  `test_dry_run_writes_nothing` (no `fetch_queue`, `job_runs` or `audit_log` row).
- `test_catch_up_at_start_after_a_three_day_outage` (rows to D, today D+4 → D+1 to D+5 queued in the daily lane,
  yesterday to tomorrow at 20, older at 22; one `lists-catchup` row with trigger `start`).
- `test_catch_up_leaves_days_that_have_a_row` (today `done` stays done) and `test_catch_up_bounded_by_collection_start`.
- `test_catch_up_on_an_empty_install_queues_only_the_three_days`.
- `test_morning_and_evening_runs_fill_the_window_and_return_caught_up`; `test_catch_up_with_nothing_missing_writes_no_run`.
- `test_overview_not_asked_matches_the_sweep` (same days; ranges oldest first; `more_ranges`; null without a period).
- `test_schedule_view_has_the_gap_sweep_with_last_run_and_facts`.
- `test_no_napix_call_log_row` (every path above).
Existing tests extended: `unit/test_plain_schedule.py` (the beat entry is described); the job-repair test (the two
names are repaired at start); `db/test_data_collection_overview.py` (the `not_asked` field); the CLI's `status_lines`
test (the new line, "none" when empty); `unit/test_openapi_snapshot.py` fails until `openapi.json` is regenerated.

Frontend (Vitest): the Cause Lists tile shows "Days Not Asked For: 4 · 2 Oct to 5 Oct 2026" only when `count` > 0, with
"and n more ranges" past 20, and also under the no-period note; the Automatic Collection tab shows the 04:15 entry with
"Last run queued n days"; the wording suites stay green.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit. In
   `frontend/`: `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
2. Screen check on a private network against temporary images (runbook section 16): `/data/overview` and
   `/data/automatic` pass with no finding.
3. Deploy: `docker compose build`, then `api`, `worker`, `scheduler` and `web` brought up with the court-data switch on
   the command line as the runbook requires for every `up`. No migration, no seed.
4. `docker compose exec api aslms data-load gaps` (dry run) on the dev database: expected "Days not asked for: none"
   (2-5 Oct were filled on 28 Oct; the overview read 666 of 666 then), and no row written. `aslms data-load status`
   prints the new line.
5. The scheduler's log after the start shows `aslms.lists_catchup` received and finished; with nothing missing, no
   `lists-catchup` row (`select job, counters from job_runs where job in ('lists-catchup','causelist-gap-sweep') order by
   started_at desc limit 5`).
6. The next morning: one `job_runs` row `causelist-gap-sweep`, `succeeded`, `missing` 0; the Automatic Collection tab
   shows the 04:15 entry with its last run; the Overview's Cause Lists tile shows no "Days Not Asked For" line.
7. The outage behaviour is proved by the tests of the catch-up and the 2-5 October reproduction; it is not provoked on
   the dev machine (no service is stopped to make a gap).

## Open questions
None.
