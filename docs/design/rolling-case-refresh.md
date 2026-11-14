# Design: Rolling nightly case refresh, claimed cases first, with hearing follow-ups and a second worker slot

```
slug: rolling-case-refresh
status: approved
author: architect
date: 2026-11-12
approved_by: owner, 2026-11-12, as revised the same day (case details always first, then order PDFs: decision 11)
```

## Context
Backlog row 238 (owner, 10 Nov 2026: approach approved; 12 Nov 2026: one design with row 220 folded in). Today the
Sunday 02:00 job `weekly-sweep` (`schedules.enqueue_weekly` → `tracking.enqueue_weekly_dossier_sweep`) queues a full
record (`dossier`, priority 50, daily lane, `requeue`) for every case not disposed plus every case never fully fetched,
and retries order PDFs the court had not published. On the dev stack that is about 38,000 rows in one block (about 42
hours at the hourly allowance), about 15% of them cases fully refreshed the day before because their status changed,
and newly found order PDFs (60) wait behind it, so a new order found on a Sunday or Monday can take 1.5 to 2 days to
arrive. On 1-3 Nov 2026 it held order PDFs back for about 44 hours while 2.5% of the refreshed cases had changed (row
220). The owner's directions of 12 Nov 2026:
- (a) every pending case, claimed or unclaimed, is still fully refreshed at least once every 7 days, oldest first,
  skipping a case fully refreshed in the last 7 days for any reason; **claimed cases first each night, then unclaimed**
  (unclaimed cases need current details for recommendations); row 220's 8-week slice is dropped;
- (b) a case heard by the court's own record is re-fetched about 3, 7, 14 and 30 days after the hearing until that
  hearing's order is stored, then no more;
- (c) the revived-priority fix (`queue.enqueue(requeue=True)` keeps `LEAST(priority)`);
- (d) a second worker slot, so a slow Current Status call (25 to 42 s at the court's end) no longer holds up order PDFs
  and other short calls;
- (e) unchanged: the daily status check with a re-fetch on any change, first fetches, the monthly disposed refresh for a
  year, the refresh on claim or accepted transfer.

The plan (Annexure of NAPIX APIs, Search by CNR: "When a case is first seen; weekly full refresh"; §3 "case tracker
(daily refresh of tracked cases)"): both stay true. Every case keeps a weekly full refresh, spread over the nights, and
the daily status check is untouched. No deviation from the plan.

Measured on the dev database (read only, 12 Nov 2026): 37,248 pending cases, 50 never fully fetched, 3 claimed;
fully-refreshed ages 1 day 6,680, 2 days 18,996, 3 days 11,521 (the last Sunday sweep ran Monday to Wednesday);
33,428 revived daily-lane `dossier` rows sit at 44 or 45 (the quirk of (c)); 165,357 disposed-case order PDFs pending
at 80; 274 orders of pending cases `not_available`. Of the pending cases heard 1 to 2 days ago 45% have no order dated on
or after the hearing, 6 to 10 days ago 5% to 23%, 27 to 38 days ago 5% to 23% (listed but not taken up, usually no order).

In place and reused: `fetch_queue` with one row per (`kind`, `ref`) and `queue.enqueue` (`requeue`, `as_new`, lanes,
`LEAST` priority on a pending row); `tracking.non_disposed_cnrs`, `never_fetched_refs`, `run_status_batch`,
`record_status_change`, the disposed refresh (`enqueue_disposed_refresh`, `disposed_window`); `cases.apply_core_fields`
(writes `last_hearing_date` from `date_last_list` in both the status block and the full record) and
`last_full_refresh_at` (set by every full record); `next_dates.claimed_condition` (an active primary ownership);
`orders.enqueue_order_pdfs` and `load_policy.QueueOrigin.order_pdf_priority`; the runner's bands, window detection and
fault pause; `job_repair`, `preflight.connection_budget`, `ops_metrics`, `service_checks.check_worker`;
`schedules.PLAIN_SCHEDULE` and `schedule_view` (the Automatic Collection tab); `data_load.pdfs_after_details`.

No NAPIX field or endpoint is involved: only the existing kinds `dossier` (Search by CNR, or Search by Case Number for
a provisional reference) and `order_pdf` are queued, and both slots call NAPIX only through
`backend/aslms/integration/napix/`.

Not covered: row 221 `show-business-new-hearings` (its own row; it reuses decision 9's "new hearing" condition); any
change to the 20:00 status check, the cause-list days, discovery, the backdated load or Collect Now; a portal control to
change the 7-day period (the owner fixed it); District Court cases (row 224 comes first).

## Decisions
1. **The rolling refresh covers every fetched case not disposed.** Eligible: `status <> 'disposed'` (the status check's
   own set, so `unknown` is included), CNR held, not merged, `last_full_refresh_at IS NOT NULL`. A case never fully
   fetched stays with the first-fetch paths (decision 14). *Alternative:* pending only; rejected, the status check and
   the old sweep both use "not disposed", and a case of unknown status needs its record most.
2. **"7 days" counts IST dates.** A case's age is `D − IST date(last_full_refresh_at)`, D the IST date of the run. Due:
   age ≥ 7. So a case refreshed on Monday at any hour is due the next Monday night, and the gap between two routine
   refreshes is never more than 7 dates. *Alternative:* 168 hours; rejected, a case refreshed at 23:30 would miss the next
   week's 22:00 run and wait 8 days. A case refreshed for any reason (status change, hearing follow-up, Fetch from Court,
   claim or transfer refresh, Collect Now) restarts its 7 days, so it is skipped as the owner directed.
3. **Claimed cases first.** Claimed means an active primary `case_ownership` row (`next_dates.claimed_condition`,
   reused). Each night due claimed cases are queued at **56** and due unclaimed cases at **57**, oldest refresh first
   within each, so every claimed case is fetched before any unclaimed one. Watcher-only cases count as unclaimed (a
   claimed case always has a primary).
4. **A levelled night quota (deviation from "skip a case refreshed in the last 7 days", flagged for the owner).** The
   night's quota is `Q = max over k = 0..3 of ceil(N_k / (k + 1))`, where `N_k` is the number of eligible cases with age
   ≥ 7 − k (due tonight, or due within the next k nights). Due cases always fill Q first; if Q is larger, the oldest
   not-yet-due cases of age 4 to 6 are refreshed **early**: claimed at **58**, unclaimed at **59**. In a steady state Q
   equals tonight's due count and nothing is early; it only acts when a clump is coming. The dev ages above would
   otherwise put about 19,000 cases on one night (about 20 hours of calls, into the working day) every week, because
   the Sunday sweep left the cases bunched on three dates; levelled, the peak is about 7,600 for three or four nights and
   then the dates spread. *Alternatives:* no levelling (the weekly 19,000 night, repeating); a fixed seventh a night
   (breaks the 7-day guarantee whenever more than a seventh are due). An early case is refreshed at 4 to 6 days, which is
   the deviation; the 7-day guarantee is untouched.
5. **A safety cap, not a target.** `ROLLING_REFRESH_DAILY_MAX` (setting, default 12,000, about 13 hours of calls; 0
   switches the rolling refresh off, as `DISPOSED_REFRESH_DAILY_MAX` does) bounds Q. When due cases exceed it, the
   oldest are queued and the rest stay due for the next night (still oldest first); the run records `over_cap` and the
   schedule shows them as not refreshed in 7 days (decision 20). With 37,248 cases the cap is never reached; it guards
   growth and mistakes.
6. **No second fetch of a case refreshed meanwhile.** The queue holds one row per case, so a status change, a follow-up
   or a person's request on a case with a routine row pending merges into that row at the better priority and lane. In
   addition, when the runner claims a `dossier` row at a routine priority (56 to 59) whose case's `last_full_refresh_at`
   is later than the row's `created_at` (refreshed by the portal's own court fetch after queueing), it ends the row
   `done` with result `{"cnr", "fresh_since_queued": true}` and makes no call. A row raised to 50 or better by a status
   change or a request is fetched as usual.
7. **A recently failed case is not revived every night.** A case whose `dossier` row is `failed` and finished in the
   last 7 days is left out of the routine selection and the follow-ups (it has used its six attempts over about four
   days). It comes back after 7 days, which keeps the weekly revival of `safety-fixes` decision 9; the failure stays in
   `source_failures` and on Problems and Fixes, where Retry is immediate.
8. **The night window: one job at 22:00 IST.** Beat entry `nightly-refresh` (`aslms.enqueue_nightly_refresh`) queues the
   hearing follow-ups first, then the routine refresh, and writes one `job_runs` row `nightly-refresh`. 22:00 is after the
   20:00 status check (about 150 Current Status calls) and its re-fetches of changed cases, which run first by priority.
   At about 900 calls an hour (the daily lane runs down to `NAPIX_LIVE_RESERVE`), about 5,300 routine and about 600
   follow-up and new-order calls finish by about 05:00, before the 06:00 masters and the 06:30 lists. There is no hard
   stop: rows left in the morning keep their priority behind every live kind, and the daily lane stops at 100 calls left
   in the window, so people's court searches keep their reserve. *Alternatives:* 02:00 (a shorter night, and on top of the
   02:30 disposed refresh); hourly slices (more jobs and no gain while the queue orders by priority anyway).
9. **Hearing follow-ups (row 220 point 2).** The "new hearing" is the court's own `cases.last_hearing_date` (H), written
   by the status check (a moved date already triggers the same night's re-fetch) and by every full record; never the
   cause list alone. A case is in follow-up while: eligible as in decision 1, H is not null, `3 ≤ D − H ≤ 37`, and no
   `orders` row of the case has `order_date ≥ H` ("the order for that hearing is stored": the order list comes with the
   full record; its PDF then follows the order-PDF path). The step is the largest of 3, 7, 14, 30 not above `D − H`; the
   case is due when `IST date(last_full_refresh_at) < H + step`, so any refresh on or after the step's day (routine,
   status change, a person's fetch) satisfies it and nothing is fetched twice. Days 31 to 37 only catch up a missed
   30-day step (the host off); after day 37 the weekly refresh alone covers the case. Follow-ups are queued at **50**,
   with the status-change re-fetches. Only the latest hearing is followed; an earlier hearing's order arrives with any
   full record, which lists every order. The condition is one function (`tracking.followup_condition`) so row 221 can
   reuse the same trigger. Dev volume: about 300, 100, 70 and 90 cases at steps 3, 7, 14 and 30, about 560 a day.
10. **Priorities, lower first** (unchanged rows in plain text):
    - 3 / 5 "now" requests; 10 masters; 20, 21, 22 cause lists; 30 status batches and people's requests; 40 new cases'
      first fetches and a person's order PDFs; 41-46 the backdated load and discovery;
    - **50** a re-fetch after a status change, a **hearing follow-up**, and the Sunday first fetches (the key
      `dossier_refetch`, value unchanged);
    - 55 the monthly refresh of disposed cases (unchanged);
    - **56** routine refresh, claimed, due; **57** routine refresh, unclaimed, due; **58** early, claimed; **59** early,
      unclaimed (keys `dossier_routine_claimed`, `dossier_routine`, `dossier_early_claimed`, `dossier_early`);
    - 60 order PDFs of pending cases (daily, load and discovery lanes alike, unchanged) and the Sunday retry of missing
      orders;
      80 order PDFs of disposed cases.
11. **Case details always first, then order PDFs (owner, 12 Nov 2026).** The 24 Oct 2026 order stands: every
    order PDF of a pending case stays at 60, behind every detail kind including the routine refresh (56-59); disposed
    cases' PDFs stay at 80. `QueueOrigin.order_pdf_priority` is unchanged. A new order found during the night is
    fetched once the night's routine rows are done (about 05:00), before the working day; on `worker2` it still
    moves while `worker` waits on a Current Status call. *Considered and declined by the owner:* new order PDFs at 52,
    ahead of the routine refresh (the first draft's deviation, from row 238's text).
12. **The monthly disposed refresh keeps 55** (the owner's (e)). It is capped (at most 1,000 a night, its own rule) and
    queued at 02:30, so it runs ahead of the routine rows still waiting then, for about an hour at most.
13. **The revived-priority fix, at the four system refresh callers.** The status-change re-fetch
    (`run_status_batch`), the hearing follow-up, the routine refresh and the Sunday first fetches call `queue.enqueue`
    with `as_new=True`: a `done`, `failed` or `skipped` row comes back at the caller's priority and lane with a fresh
    `created_at`, never at the 44/45 of its first fetch. A pending or running row keeps the better priority, as today.
    *Alternative:* change `enqueue` for every caller; rejected, `created_at` and the request tags of revived rows feed the
    Data Collection estimates and Collect Now (rows 172 and 174), and the disposed refresh and rechecks already use
    `as_new` the same way. The 33,428 rows now at 44/45 are `done` and take their new priority the next time they are
    queued; no one-off command is needed.
14. **The Sunday 02:00 job stays, for first fetches and missing orders only.** `enqueue_weekly` keeps the beat entry
    `weekly-sweep` and the task name but no longer queues fetched cases: it queues `never_fetched_refs` at 50 (daily
    lane, `as_new`; the CNR or `<est_code>|<case number>`, never a made-up reference), and retries `not_available` orders
    at **60**, their place before this row (`enqueue_order_pdfs` with an explicit priority). Dev volume: 68
    cases and 276 orders.
15. **`aslms data-load pdfs-after-details` is unchanged.** Its targets (60 for a pending case, 80 otherwise) already
    match decision 11.
16. **The second worker slot is a second Compose service.** `worker2` runs `aslms queue-worker --slot second`: every
    NAPIX kind except `status_batch`. The `worker` service (`--slot main`, the default) is unchanged and claims every kind,
    so while it waits up to 90 s on a Current Status call, `worker2` keeps fetching order PDFs, cause lists and full
    records. Each slot is its own process with its own NAPIX client and rate limiter; the access token is shared through
    Redis as the api and the worker already share it. *Alternatives:* two loops in one process (the call recorder carries
    the lane, the person and the run per item, so concurrent items would be logged against each other's lane and run);
    `--scale worker=2` (both would take status batches and share one job name, so a restart of one would mark the other's
    run interrupted).
17. **Two slots stay inside the allowance.** Both read the gateway's `X-RateLimit-Remaining` and the detected window, so
    the bands (load above 150, daily and requests above 100, nothing below) hold for both; each may overshoot a band by
    the one call in flight. While the window is unknown each slot may make its one probe, so at most one extra Overview
    call per window. The discovery share may be exceeded by one item. The api's six NAPIX request slots are untouched (the
    worker processes do not use them). The connection budget counts two workers: `BUDGET_WORKER = 2`, so 6 + 2 + 1 + 3 +
    4 = 16 of PgBouncer's 20; `aslms ops pool-check` holds slots + 3.
18. **Each slot repairs only its own runs.** The second slot's passes are `job_runs` rows `queue-run-second`
    (`job_repair.WORKER2_JOBS`, key `worker2` in `ALL_SETS`), so a restart of one slot never marks the other's running pass
    interrupted.
19. **Each slot's liveness is visible.** New gauge `aslms_worker_slot_alive_timestamp{slot="main"|"second"}`: the later
    of the slot's latest pass start and its latest `napix_call_log.called_at` in the last 3 hours whose `job_run_id` is
    one of its runs (an idle slot starts a pass every minute, a busy one calls, a waiting one wakes within about 62
    minutes). New alert `WorkerSlotStalled` (no sign for 2 hours while runnable rows wait), tested with promtool. The
    existing `aslms_worker_alive_timestamp` and `WorkerStalled` keep their meaning (any slot). System Health's Queue
    worker check names both slots in its facts and is `warn` when one slot shows no sign for over 70 minutes while rows
    wait.
20. **Screen and schedule wording** (Data Collection → Automatic Collection; `PLAIN_SCHEDULE`):
    - new entry: key `nightly-refresh`, when "22:00", what "Refresh cases heard recently until their order arrives, then
      every case not disposed whose details are 7 days old, claimed cases first", job `nightly-refresh`; facts
      `{pending, not_refreshed_7d, heard_waiting}`, shown as "37,248 not disposed, 0 not refreshed in 7 days, 560 heard
      and awaiting their order" (`not_refreshed_7d`: eligible cases of age ≥ 8, which is 0 while the refresh keeps up);
    - the Sunday entry: when "Sundays 02:00", what "Fetch cases never fully fetched, and try again for orders the court
      had not published" (was "Refresh the details of every case not fully fetched");
    - nothing else on the screen changes: Overview and the pulse already count daily-lane rows by kind.
21. **Commands and audit.** `aslms daily-cycle nightly` queues what the 22:00 job queues; `--dry-run` prints the counts
    and writes nothing. `aslms daily-cycle weekly` keeps its name (decision 14). As for the disposed refresh, a system
    enqueue writes a `job_runs` row and no audit row: no person acts, and the queue rows and the call log record the work.
22. **Documents.** `docs/ASLMS_Process_Workflows.md` §2.2, §2.4 and §2.6 are rewritten as in Services → Documents, with
    the same facts in §4.1 (two sentences), §6 item 1 and the header's "Describes" line; the Software Documentation
    (`docs/software-documentation/build.js`, then the regenerated `.docx`) §5.4, §5.5 and Annexures A and C;
    `docs/operations.md` (the services table and every list of application services, which gains `worker2`, so the
    migrate step's "no `aslms_app` session" check passes); the `compose.yml` comments.

## Data
No table, column, reference code, index or migration. Paragraph for `docs/schema/schema.md` (after the row 200 entry):

> As built from rolling-case-refresh (row 238): no table, column or migration. `fetch_queue` priorities gain 56 and 57 (the
> nightly routine `dossier` refresh of a claimed and an unclaimed case due its 7-day refresh) and 58 and 59 (the same,
> refreshed early to level the night); 50 now also carries the hearing follow-ups and the Sunday first fetches. The
> nightly, status-change, follow-up and Sunday `dossier` rows revive a finished row `as_new`. `job_runs.job` gains the
> free-text values `nightly-refresh` (the 22:00 IST job and `aslms daily-cycle nightly`) and `queue-run-second` (the
> passes of the second worker slot). The Sunday sweep no longer queues fetched cases. `fetch_queue` stays class
> `derived`, RESTRICT keys, no DELETE.

New setting (not a secret, `.env.example` documented): `ROLLING_REFRESH_DAILY_MAX` (int, default 12000, 0 to 50000).

## Services
- `services/queue.py`: `PRIORITY` gains `dossier_routine_claimed` 56, `dossier_routine` 57,
  `dossier_early_claimed` 58, `dossier_early` 59; `ROUTINE_PRIORITIES = range(56, 60)`. The module docstring's priority
  paragraph follows decision 10. `enqueue` itself is unchanged.
- `services/load_policy.py`: unchanged (order PDF priorities stay as they are, decision 11).
- `services/orders.py`: `enqueue_order_pdfs(session, case, origin=None, *, priority=None)`; `priority` overrides the
  origin's (the Sunday retry passes 60).
- `services/tracking.py`:
  - `refresh_age(D)`: the SQL age in IST dates; `eligible_conditions()` (decision 1); `recently_failed()` (decision 7,
    `NOT EXISTS` on `fetch_queue` kind `dossier`, `ref = cases.cnr`, `failed`, `finished_at > now() − 7 days`).
  - `rolling_quota(counts_by_age: dict[int, int], cap: int) -> RollingPlan` (pure): `due`, `quota` by decision 4,
    `cap`, `over_cap`.
  - `rolling_refresh_refs(session, D, plan)`: due claimed, due unclaimed, then early (age 4 to 6) claimed, early
    unclaimed, each by `last_full_refresh_at, cnr`, up to the quota; returns `(cnr, priority)` pairs.
  - `followup_condition(D)` and `followup_step(D, H, refreshed_on) -> int | None` (pure; decision 9);
    `followup_refs(session, D)`.
  - `enqueue_nightly_refresh(session, D=None, settings=None, *, now=None, dry_run=False) -> dict`: follow-ups at 50, then
    the routine pairs, each `queue.enqueue(DOSSIER, cnr, p, requeue=True, lane=DAILY, as_new=True)`, a CNR already
    queued as a follow-up skipped; returns `{eligible, due_claimed, due_unclaimed, early_claimed, early_unclaimed, quota,
    cap, over_cap, followups, queued}` (`queued` = pending after the calls).
  - `enqueue_weekly_dossier_sweep` → `enqueue_first_fetches`: `never_fetched_refs` only, at 50, `as_new`.
  - `run_status_batch`: the re-fetch on change passes `as_new=True`.
  - counts for the schedule: `pending_count`, `not_refreshed_count(D, days=8)`, `heard_waiting_count(D)`.
- `services/schedules.py`: `run_nightly_refresh(session, settings, *, today=None, now=None)` (a `job_runs` row
  `nightly-refresh` with the counters, failed and re-raised on error, as `run_disposed_refresh`); `enqueue_weekly` calls
  `enqueue_first_fetches` and retries missing orders at 60; `PLAIN_SCHEDULE` and the module docstring per decision 20;
  `schedule_view` adds the `nightly-refresh` facts.
- `services/runner.py`: `QueueRunner._dossier` reads its claimed row's `priority` and `created_at`; at a routine
  priority with the case refreshed after `created_at` it returns `({"cnr", "fresh_since_queued": True}, False)` with no
  call (decision 6). `QueueRunner.run(job=...)` and `run_queue_once(..., job=...)` carry the job name.
  `SLOT_KINDS = {"main": None, "second": every FetchKind except STATUS_BATCH and LOCAL_KINDS}`; `slot_job(slot)` →
  `queue-run` / `queue-run-second`.
- `cli/pipeline.py`: `queue-worker --slot main|second` (default `main`; any other value exits 2) passes the slot's kinds
  through `claim_kinds` and its job name, repairs its own job set, and prints the slot in its start line;
  `daily-cycle` accepts `nightly` and `--dry-run`.
- `services/job_repair.py`: `WORKER2_JOBS = {"queue-run-second"}`; `ALL_SETS["worker2"]`; `SCHEDULER_JOBS` gains
  `nightly-refresh`.
- `services/preflight.py`: `BUDGET_WORKER = 2`, the finding's text "2 workers". `cli/ops.py` pool-check holders slots + 3.
- `services/ops_metrics.py`: `slot_alive_at(session, slot, now)` and the gauge of decision 19 (read only, inside the
  existing statement timeout).
- `services/service_checks.py`: `check_worker` adds the facts "Main slot: last sign of work" and "Second slot: last sign
  of work" and the `warn` rule of decision 19; `down` stays on the combined liveness.
- `services/data_load.py`: `_PDF_TARGET` and `_PDF_ROWS` per decision 15; docstring.
- `jobs/celery_app.py`: beat `nightly-refresh` (`crontab(hour=22, minute=0)`), task `aslms.enqueue_nightly_refresh`;
  docstring.
- `core/config.py`: `rolling_refresh_daily_max: int = Field(12000, ge=0, le=50000)`.
- `compose.yml`: service `worker2`, identical to `worker` (build, env file, `aslms_app` through `pgbouncer:6432`,
  `REDIS_URL`, storage and cause-list dirs, `NAPIX_ENABLED: ${NAPIX_ENABLED:-false}`, volumes, depends_on, restart,
  hardening, logging) with `command: aslms queue-worker --slot second`; the scheduler's comment lists 22:00.
- `infra/prometheus/rules.yml` and `rules.test.yml`: `WorkerSlotStalled`.
- Frontend: `AutomaticCollection.tsx` `facts()` gains the `nightly-refresh` case and `lib/messages.ts`
  `T.dc.scheduleFacts.nightly(pending, notRefreshed, heard)` (Indian digit grouping, `plural`); no other screen.
- Rules kept: no case is assigned to a department (claimed status only orders the queue); NAPIX only through the
  integration layer; `NAPIX_ENABLED` is never set in code, Compose or tests (the new service reads the shell's value like
  `worker`); no identifier is made up.

**Documents** (the scribe writes them from the build; facts, not final wording):
- Process Workflows §2.2: replace the Sunday row with two rows: "22:00 daily | Case refresh | Queues a full record for
  each case heard recently whose order has not arrived (3, 7, 14 and 30 days after the hearing), then for every case not
  disposed whose last full record is 7 days old, claimed cases first, oldest first | Yes (the worker fetches overnight)"
  and "Sunday 02:00 | First fetches and missing orders | Full record of every case never fully fetched; tries again the
  order PDFs the court had not published | Yes".
- §2.4: the diagram's Sunday block becomes "Every night at 22:00" (follow-ups, then the 7-day refresh, claimed first);
  "In short": not-disposed cases get the status daily, a full record whenever the status changes and at least once every
  7 days (a case refreshed for any reason waits a fresh 7 days; a clump is levelled by refreshing a few cases a day or
  two early); a case just heard is checked again 3, 7, 14 and 30 days after the hearing until its order is in; new
  orders go ahead of the routine refresh; a disposed case restored to pending rejoins the status check and the 7-day
  refresh. The warning box about claiming is replaced: a claim queues a fresh record at once (unless one is under a day
  old) and claimed cases come first each night.
- §2.6: the priority table of decision 10, a sentence on the two worker slots (the second never takes Current Status,
  so order PDFs and short calls keep moving) and on a routine row skipped when the case was refreshed meanwhile.
- §4.1 "refreshed by the daily and weekly cycle" and the "until the weekly sweep" bullet; §6 item 1 notes the nightly
  order; the header records row 238.
- Software Documentation §5.4 bullet 1, §5.5 queue paragraph, Annexure A (the 22:00 row and the Sunday row), Annexure C
  (Search by CNR "When first seen, at least weekly, after a hearing, on change, on request").

## API
No new endpoint and no change of shape (`openapi.json` and `schema.d.ts` unchanged).
- `GET /admin/data-load/schedule` (any of `data_load.READERS`: `admin.data_load`, `reports.state`,
  `admin.napix_refetch`; unchanged): `entries` gains `nightly-refresh` with `facts` `{pending, not_refreshed_7d,
  heard_waiting}` (integers; `facts` is already a free object) and the Sunday entry's new `what`. Counts only, no case
  reference, so no per-case visibility applies.
- `GET /admin/system-health` (`admin.service_health`; unchanged): the `worker` check carries two more facts.

## Jobs
- `nightly-refresh`: beat `crontab(hour=22, minute=0)` IST, task `aslms.enqueue_nightly_refresh`, `job_runs` job
  `nightly-refresh`. Queues `dossier` rows, ref the CNR, lane `daily`, `requeue`, `as_new`: follow-ups 50, then 56, 57,
  58, 59 (decisions 3 to 9). Only enqueues; no NAPIX call, no audit row.
- `weekly-sweep` (Sunday 02:00, task `aslms.enqueue_weekly`): first fetches 50 (`as_new`) and missing-order retries 60.
- Status check (20:00): unchanged, except the re-fetch on change revives `as_new` at 50.
- Disposed refresh (02:30): unchanged.
- `worker2`: `aslms queue-worker --slot second`, job `queue-run-second` per pass.

## Tests
Unit:
- `test_rolling_quota_steady_state_is_the_due_count`; `test_rolling_quota_levels_a_clump` (the dev ages: peak at most
  about a quarter of the clump); `test_rolling_quota_never_below_due_unless_capped`; `test_rolling_quota_cap_and_zero`.
- `test_followup_step` (day 2 none; day 3 due when refreshed before H+3; refreshed on H+4 then not due on day 5, due
  on day 7; day 31 to 37 catch-up only when the 30-day step was missed; day 38 none).
- `test_order_pdf_priority_unchanged` (pending 60 in every lane, disposed 80, request 40, now 3/5; no PDF of a
  pending case is ever queued ahead of a routine refresh row).
- `test_plain_schedule` (existing, updated): `nightly-refresh` mirrors beat, the Sunday wording.
- `test_slot_kinds` (second slot without `status_batch` and local kinds; job names); `test_queue_worker_rejects_unknown_slot`.
- `test_connection_budget_counts_two_workers`; compose tests: `worker2` mirrors `worker` (hardening, `aslms_app` through
  PgBouncer, `NAPIX_ENABLED` defaulting to false, the command), `APP_SERVICES` includes `worker2`.
- promtool `rules.test.yml`: `WorkerSlotStalled` fires for one silent slot with rows waiting, not while idle with an
  empty queue, not during a long pass with recent calls.
- Frontend `collection.test.tsx`: the nightly facts sentence.

Database (`tests/db/test_rolling_refresh.py` and the existing files named):
- `test_nightly_queues_claimed_before_unclaimed` (56 and 57, oldest first).
- `test_nightly_skips_a_case_refreshed_within_7_days` (age 6 not queued without a clump, age 7 queued).
- `test_nightly_levels_a_clump_at_58_and_59`.
- `test_nightly_leaves_out_disposed_merged_never_fetched_and_cnrless`.
- `test_nightly_leaves_out_a_recently_failed_case_and_revives_an_old_failure`.
- `test_nightly_revives_a_done_row_at_its_refresh_priority` (a done row at 44 comes back at 56, lane daily, new
  `created_at`) and `test_status_change_refetch_revives_at_50`; `test_pending_row_keeps_its_better_priority`.
- `test_followup_queued_at_3_7_14_30_until_the_order_is_stored`; `test_followup_stops_on_an_order_dated_on_or_after_the_hearing`;
  `test_followup_and_routine_share_one_row`.
- `test_cap_records_over_cap` and `test_cap_zero_queues_nothing`; `test_nightly_job_run_counters`;
  `test_daily_cycle_nightly_dry_run_writes_nothing`.
- `test_weekly_queues_first_fetches_and_missing_orders_only` (fetched pending cases not queued; never-fetched at 50;
  `not_available` orders back at 60) in `test_tracking.py` / `test_safety_fixes.py` (updated).
- Runner with the scripted gateway (`tests/db/conftest.py`): `test_routine_row_already_fresh_ends_done_without_a_call`;
  `test_routine_row_raised_by_a_status_change_is_fetched`; `test_new_order_pdf_is_claimed_before_routine_refresh`.
- `test_two_slots_never_claim_the_same_row_and_second_skips_status_batches`.
- `test_pdfs_after_details_keeps_new_orders_at_52` (and idempotent).
- `test_repair_at_start_second_slot_leaves_main_runs` (`test_deployment_ops.py`).
- `test_slot_alive_gauge` (`test_ops_metrics.py`); `test_worker_check_names_both_slots` (`test_service_checks.py`).
- `test_schedule_view_nightly_facts`.

## Verification
1. `ruff check`, `pytest -q`, the frontend tests, `promtool test rules` green.
2. Dry run on the dev database: `docker compose run --rm --no-deps api aslms daily-cycle nightly --dry-run`. Expected
   with today's ages: `eligible` about 37,250, `followups` a few hundred, `quota` between about 5,300 and 7,600, nothing
   written (`fetch_queue` count unchanged).
3. Deploy from a clean worktree of `main` (runbook): `NAPIX_ENABLED=true docker compose up -d` carrying the switch, then
   the app services recreated with `--no-deps --force-recreate` including `worker2`. `docker compose ps` shows `worker2`
   up; its log prints "queue worker started (slot second, NAPIX on)"; `job_runs` gains `queue-run-second` passes.
4. First 20:00 status check: while `status_batch` rows run on `worker`, `napix_call_log` shows calls of `worker2`'s runs
   (order PDFs, dossiers) in the same minutes; no `status_batch` row is ever claimed by a `queue-run-second` run.
5. First 22:00 run: `job_runs` `nightly-refresh` succeeded with its counters; `fetch_queue` `dossier` rows pending at 50
   and 56 to 59 match them; revived rows carry their new priority (no daily `dossier` row revived tonight at 44 or 45:
   `SELECT priority, count(*) FROM fetch_queue WHERE kind='dossier' AND lane='daily' AND created_at > <22:00> GROUP BY 1`).
6. Next morning: the routine rows are done by about 05:00 and the order PDFs found overnight are fetched after them (or the remainder is small and still behind every live kind); `aslms data-health` shows no new failures.
7. Data Collection → Automatic Collection: the 22:00 row with its facts sentence, the Sunday row's new wording,
   `not_refreshed_7d` 0 after the first week; System Health → Queue worker shows both slots.
8. First Sunday 02:00: only never-fetched cases and missing orders are queued (dev: about 68 and 276), no fetched pending
   case.
9. After 7 nights: every pending case's age is at most 7 (`SELECT max(age)` by the decision 2 rule) and the nightly
   `queued` settles near a seventh of the eligible cases.

## Open questions
None. Decision 4 (refreshing a few cases a day or two early to level a clump) is the one marked deviation for the
owner's approval of this note. Decision 11 follows the owner's direction of 12 Nov 2026: case details always first, then
order PDFs.

## Deviations
Recorded by the developer during the build (the smallest reasonable option where the note was silent):
1. **The Sunday retry raises only the retried orders.** `enqueue_order_pdfs` gains `order_ids` beside `priority`: the
   Sunday job queues the orders it has just turned from `not_available` back to pending at 60, and only those, so a
   disposed case's other PDFs (165,357 at 80 on dev) are never raised to 60 by `LEAST`. The old job's general pass over
   every case with a PDF still lacking (which revives a failed `order_pdf` row) stays, at each PDF's own priority (60
   pending, 80 otherwise); `orders_queued` counts the retried orders plus the other cases' PDFs.
2. **`ROLLING_REFRESH_DAILY_MAX=0` switches the whole 22:00 job off**, follow-ups included (`test_cap_zero_queues_nothing`);
   the run is still recorded with its counters.
3. **Two test names follow decision 11, not the first draft:** `test_new_order_pdf_is_claimed_before_routine_refresh`
   is written as `test_routine_refresh_is_claimed_before_a_new_order_pdf`, and
   `test_pdfs_after_details_keeps_new_orders_at_52` as `test_pdfs_after_details_keeps_pending_order_pdfs_at_60`.
4. **Counters:** the nightly counters also carry `due` (the cases due before the cap, so `over_cap` can be read); the
   routine `due_*` and `early_*` counters are the rows queued in each group (a follow-up case is counted once, as a
   follow-up). A dry run returns `dry_run: true` and `queued` = what would be queued; `--dry-run` with any other
   `daily-cycle` target is refused.
5. **With the gateway off** (`NAPIX_ENABLED=false`) `runner.claim_kinds` narrows a slot's list of kinds to cause-list
   days, so `worker2` never claims a dossier or order PDF it could only fail; `queue-run --kind dossier` is unchanged.
6. **Liveness:** `aslms_worker_alive_timestamp` (and System Health's combined "Last sign of work") reads the passes of
   both slots, so it keeps its "any slot" meaning; a slot with no sign shows "never" in the Queue worker facts. The
   second slot's start-up repair is logged as `queue-worker-second`.
7. **Compose:** `worker` keeps `command: aslms queue-worker` (the default slot `main`); `aslms ops pool-check` holds
   `NAPIX_REQUEST_SLOTS + 3` by default and the runbook example uses `--holders 9`.
8. **Follow-ups are queued oldest hearing first** (then CNR); the note named no order.
