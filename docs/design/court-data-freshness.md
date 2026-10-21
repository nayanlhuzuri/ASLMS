# Design: Court data freshness: disposed cases refreshed for a year, corrected cause lists, call-log retention

```
slug: court-data-freshness
status: awaiting-approval
author: architect
date: 2026-10-21
approved_by: (pending)
```

## Context
This is backlog row 122. `docs/ASLMS_Process_Workflows.md` §2 (where the data comes from) and §6 (points worth a
decision) list three court-data gaps. The owner settled them on 21 Oct 2026, and these decisions are not reopened here:

- **10.** Disposed cases are refreshed monthly for one year after disposal.
- **11.** A corrected cause list re-issued under the same list number is picked up by the 18:30 evening run.
- **12.** `napix_call_log` is kept for 2 years and then removed. `napix_responses` (the court's answers as received) are
  kept for as long as the case they belong to lives.

§6 also lists technical gaps. Two small ones are closed here: `aslms napix-probe-rate` does not log its calls, and job
dates use the container's UTC clock.

**The plan.** §3.1 Table 4 gives Search by CNR as "When a case is first seen; weekly full refresh". It gives Current
Status as "Daily, for all tracked cases" and Show Cause List as "Daily". The plan has no retention rule.
`docs/DB_STANDARD.md` §6 is the binding rule on deletion.

**What is in place** (code read on 21 Oct 2026):
- **Disposed cases.** `services/tracking.py`: the 20:00 status batches and the Sunday sweep cover only
  `status <> 'disposed'` (`non_disposed_cnrs`). The sweep also covers cases never fully fetched (`never_fetched_refs`).
  So once a disposed case is fully fetched, it is never refreshed again.
- **Restored cases.** `services/cases.py::apply_core_fields` sets `status` from `pend_disp` (`P` / `D`) and sets
  `closed_at` on disposal. `apply_dossier` emits `case_disposed` when a case becomes disposed. A case that goes from
  disposed back to pending gets no event, and its `closed_at` stays set.
- **Cause lists.** `services/causelists.py::_load_napix_list` returns early when a list is `parsed`, before any Show
  Cause List call. Every run of a day still calls Cause List Bench and Cause List Details. The two daily runs are
  06:30 and 18:30 (`schedules.enqueue_daily_lists`, for yesterday, today and tomorrow).
- **The list key.** `causelists` is unique on (court, date, bench, NAPIX list id, source, list type), so a re-issue
  has no place to go. `causelist_entries` is immutable by rule, keyed (causelist_id, source, sr_no).
- **Readers.** Fifteen services read `causelist_entries` through a join to `causelists`.
- **Call-log retention.** `napix_call_log` is class `derived`, and its model docstring says "Pruned after the retention
  period". `docs/schema/schema.md` Group 9 says the same: "pruned after a retention period (the one allowed deletion)".
  No job exists. Row 70 parked the job, waiting for the owner's rule, which decision 12 now gives.
- **Grants.** `aslms_app` already holds DELETE on `napix_call_log` (migration 0001, `CASCADE_TABLES`). It has no DELETE
  on `napix_responses`.
- **Readers of the call log.** The quota window reads the last 6 hours (`napix_window.LOOKBACK`). System health reads
  the last 24 hours and 7 days. The data-load estimate reads the last 1 and 24 hours and its window. The data-health
  report reads a chosen period.
- **`aslms napix-probe-rate`** (`cli/napix_probe.py`) collects its results in a list and writes nothing.
- **UTC dates.** 21 calls to `date.today()` in `backend/aslms` run on the container's UTC clock. A job between 00:00
  and 05:30 IST gets yesterday's date: the 03:00 dedupe sweep, the Sunday 02:00 sweep, Saturday 02:00 discovery
  (years from 2025 "to now"), queue passes after midnight, and membership and office `valid_to` dates written then.

**Not covered here:**
- §6 items 1–9 and 13–16.
- The status-batch skip/repeat gap.
- Row 114 (the connection pool).
- A "listed for tomorrow" or "removed from the list" alert. That is §6 item 8 and needs its own decision.
- Corrections to website-path lists (files on disk). Only NAPIX lists are re-checked.
- Inferring that a list was withdrawn.
- Any purge of `napix_responses` (decision 21).
- Row 70's other two items (snapshots, e-mailed reports). Row 70 keeps them; the scribe removes the retention job from
  its text.

## Decisions

### A. Disposed cases: monthly for one year (owner decision 10)

1. **A daily slice, not one monthly burst.** At 02:30 IST every day, ASLMS queues a dossier fetch for each eligible
   disposed case whose last full refresh is older than 28 days. The oldest refresh goes first, and the run is capped
   (decision 3).
   - Because each case becomes due 28 days after its own last refresh, the work spreads itself through the month. After
     the first days, about 1/28 of the eligible cases fall due each night.
   - *Alternative:* the first Sunday at 03:30. That puts every eligible case into one night. It meets the Sunday 02:00
   sweep, which takes priority 50 ahead of it. It could use several hours of allowance in one night. One failed night
   would delay the whole month.
   - 02:30 IST lies between the 00:30 and 06:30 backups. It is before the 06:00 masters sync and the 06:30 lists, in
     the quietest hours of the allowance.
2. **Lane `daily`, priority 55** (new key `PRIORITY["dossier_disposed"]`), with `requeue=True` as the weekly sweep uses.
   - 55 runs after every live kind: masters 10, lists 20, status and requests 30, live dossiers and PDFs 40, the weekly
     sweep 50. It runs before disposed-case order PDFs (80).
   - *Alternatives:*
     - The `load` lane: it pauses with the backdated load and follows its order presets, which is the wrong owner.
     - The `discovery` lane: it has a share cap meant for keyword searches.
     - Priority 50: this would compete with the weekly sweep.
   - The daily lane runs down to `NAPIX_LIVE_RESERVE`, as the weekly sweep does today. People's searches keep their
     floor (`NAPIX_SEARCH_FLOOR`).
3. **Eligibility and settings.** A case qualifies when all of these hold:
   - `status = 'disposed'`, `cnr IS NOT NULL`, `merged_into_case_id IS NULL`, and `last_full_refresh_at IS NOT NULL`.
     A case never fully fetched is already the Sunday sweep's.
   - `last_full_refresh_at < now() − DISPOSED_REFRESH_EVERY_DAYS` (default 28).
   - Its disposal day is within the last `DISPOSED_REFRESH_DAYS` IST days (default 365), counting today.
   - The disposal day is `COALESCE(disposal_date, closed_at` as an IST date`)`. Some court records give `D` without
     `date_of_decision`. For those, the day ASLMS first saw the disposal stands in.
   - A disposal date later than today counts as today.

   The daily cap is `min(DISPOSED_REFRESH_DAILY_MAX, ceil(eligible / 28))`. `DISPOSED_REFRESH_DAILY_MAX` defaults to
   1,000, about one hour of allowance at night. All three settings are in `.env`, with ranges of 90–730 days, 7–60 days
   and 0–5,000. A cap of 0 switches the job off.
4. **A restored case rejoins the daily cycle by itself.** The monthly dossier carries `pend_disp = P`, so
   `apply_core_fields` sets `status = pending`. From then on `non_disposed_cnrs` includes the case:
   - in the next 20:00 status batches;
   - in the next Sunday sweep;
   - and it leaves the disposed-refresh selection.

   No new code is needed for that. Two gaps around it are fixed in `apply_dossier`:
   - On a change from `disposed` to `pending`, it emits `status_changed` with payload
     `{"status": ["disposed", "pending"]}` and dedupe `status_changed:<cnr>:pending:<IST date>`. The existing event scan
     turns this into a `status_changed` alert (normal severity) for owners and watchers.
   - It sets `closed_at = NULL`, because the case is open again. `closed_at` marks the disposal lifecycle
     (DB_STANDARD §6) and is set again by the next disposal.

   New orders a monthly refresh finds (a review order, a restoration order) already raise `order_found` and the
   `new_order` alert. Their PDFs queue at 80 as disposed-case PDFs. If the case is pending again, they queue at 40.
5. **Deviation (accepted by owner decision 10).** Plan Table 4 says "weekly full refresh" for Search by CNR. Pending
   cases keep the weekly refresh. Disposed cases get a monthly refresh for one year after disposal, and none after that.
   Today the build gives disposed cases none at all, so this moves closer to the plan. The owner's decision fixes the
   cadence.
6. **Record.** Each run writes one `job_runs` row `disposed-refresh` with `{eligible, due, cap, queued}`. The run is
   added to `SCHEDULER_JOBS` (job repair) and to the JobLate rule (late after 26 h). It writes no audit row: it is a
   system enqueue, like the weekly sweep and the daily lists.

### B. Corrected cause lists (owner decision 11)

7. **A new queue kind `causelist_recheck`** (ref `YYYY-MM-DD`), not a flag on `causelist_day`.
   - Eight services find the day's queue row by `kind = causelist_day` and ref = the ISO date: the cause-list screen,
     data health, the reports, the console, `napix_admin.day_held`, the load report and others. A different ref
     would break them.
   - `fetch_queue` has no parameter column.
   - Adding the kind needs `ALTER TYPE fetch_kind ADD VALUE`, as 0017 and 0019 did.
8. **What the 18:30 run does.** It keeps the three `causelist_day` rows (yesterday, today, tomorrow) as today. It adds
   one `causelist_recheck` row each for today and tomorrow: priority 21 (new key `PRIORITY["list_recheck"]`), lane
   `daily`, `requeue=True`. They run after the day rows.

   A recheck makes **only Show Cause List calls**, one per current version of a NAPIX list of that date that:
   - has a stored PDF and `fetch_status = fetched`;
   - was neither fetched nor checked in the last `CAUSELIST_RECHECK_FRESH_MINUTES` (default 180). That is,
     `greatest(fetched_at, last_checked_at)` is older.

   The call's reference is rebuilt from the stored row (`list_date`, `bench_id`, `napix_causelist_id`), which is all
   `hc.show_causelist` sends. There is no second Cause List Bench or Details call, because the day row has just made
   them and stored any new list.

   Lists without a PDF, a 628 or a failed fetch stay with the day row, which already retries them. Tomorrow's lists
   that the 18:30 day row fetched minutes earlier are skipped by the freshness rule. A retried recheck row does not
   call again for lists it has already checked.
9. **A re-issue is a new version of the list.** Each version is its own `causelists` row with:
   - `version` (1, 2, …) and `supersedes_id` (→ the previous version);
   - its own document and its own `causelist_entries`.

   The previous version gets `superseded_at` set. Its entries are never deleted or changed. A partial unique index
   allows one current version per list identity.

   This mirrors `case_notes.supersedes_id`: the new row points at the old one, so the old row exists before the link
   does and no deferred constraint is needed.

   *Alternatives:*
   - A version column on the entries. Marking old entries would edit immutable rows, and the (causelist_id, source,
     sr_no) key would need to change.
   - A separate versions table. Every reader would need another join.
10. **A new version only when the entries change.** The bytes' sha256 is compared first. When it matches the stored
    document's, the list is unchanged: only `last_checked_at` is set.

    When the bytes differ, the PDF is parsed, as the owner decided, and the result is compared with the current
    version's **entries fingerprint**. The fingerprint is the sha256 of the ordered entries, each with these fields as
    they are stored (after the truncation `_entry_row` applies):
    - `printed_sr_no`, `court_no`, `bench_text`, `section`;
    - `cnr`, `case_no_text`, `is_connected`;
    - `petitioner_text`, `respondent_text`, `pet_advocate_text`, `res_advocate_text`;
    - `counsel_codes`, `with_text`, `remarks`.

    `raw_lines` are left out because they only add whitespace noise. The fingerprint is stored in
    `causelists.entries_sha256` at every parse, and computed once from the stored entries for older rows.
    - **Same entries:** the difference is in the file only. It is counted as `same_entries`, and neither a version nor
      a document is written.
    - **Different entries:** this is a re-issue.

    Reason: nobody knows whether NAPIX builds identical PDFs for the same list. A generation stamp inside the file would
    otherwise make a new version of every list every evening. A re-issue that changes only the PDF's heading, not its
    rows, is therefore not versioned (owner check (c)).
11. **A bad download never replaces a good list.** The current version stays current, and the new PDF is not stored,
    when:
    - the new PDF fails to parse;
    - it yields no entries;
    - or the answer is not a PDF.

    The case is recorded in `source_failures` as kind `causelist_reissue`, ref `<current list id>|<new sha256>`, and
    tried again the next evening. A later recheck that ends in "unchanged" or a new version resolves it.

    A 628 on a list that is already held is counted (`not_available`) and changes nothing. ASLMS does not infer that a
    list was withdrawn from it, because NAPIX hiccups return 628 too.
12. **Every reader reads the current version.** The rule is `causelists.superseded_at IS NULL`, as a helper
    `causelists.CURRENT_LIST` and the SQL text `cl.superseded_at IS NULL`. It is added to:
    - `calendar.hearing_rows` (My calendar, the hearing calendar, hearing alerts, the dashboard's upcoming hearings);
    - `case_filters` (listed filters);
    - `inbox` (latest listing);
    - `matching.CaseEvidence.gather` and `matching.unmapped_codes`;
    - `visibility.codes_condition` (the standing-counsel basis; a code printed by mistake must not grant sight);
    - `next_dates.court_date_condition`;
    - `reports` (hearings-disposals);
    - `reporting_common` (lists per day);
    - `reference.benches`;
    - `data_load` (coverage, case totals);
    - `napix_admin` (lists held for a day);
    - `causelist_view` (dates, day, entries when no list is named);
    - `case_detail` (the listing count);
    - `causelists._get_or_create_list` (so the day run sees the current version).

    Deliberate exceptions:
    - `causelist_view.entries` with an explicit `list_id` (an earlier version can be opened);
    - `case_detail.listings` (all rows, each flagged `superseded`);
    - the list file download;
    - `load_report` and backup counts (all rows);
    - `case_dedupe` merges (all rows move);
    - the `cases.search_vector` SQL function of migration 0005. It is kept as it is: a name printed in any version
      still finds the case, which is harmless and avoids replacing the function.

    A source-scan test enforces the rule.
13. **How cases, recommendations, next dates and alerts react.** After a new version is written:
    - **Cases.** New rows go through `apply_entries` as any list does: get-or-create, a provisional case and a dossier
      row for a number without a CNR, then scoring. A case printed only in the old version keeps its row and its
      entries in the superseded version, and nothing is deleted. Its dossier row proceeds as queued. A misprinted
      number ends "not found by case number".
    - **Recommendations.** Every case in the old or new version is rescored. The new version's cases are scored by
      `apply_entries` (origin `cause_list`). Cases only in the old version are scored with origin `rescore`. Because
      evidence now comes from current versions only, an engine recommendation whose only signal was a code or name in
      the withdrawn rows falls below its band. It **expires** under the existing rule (`matching.apply_scores`). Human
      suggestions, claims and ownership are never touched, and a claimed case never returns to the pool.
    - **Next dates.** `next_dates.match_after_court_change` runs for the cases of both versions, so a listing in the
      new version can make an order's suggested date firm. A row already made firm by a listing that is now superseded
      stays firm, with no reversal. The court's own `next_hearing_date` from the 20:00 status corrects the case's date.
    - **Alerts.** The hourly date sweep (minute 10) reads `calendar.hearing_rows`, now current-only, so within the hour
      after the 18:30 recheck:
      - A **removed** listing's open `hearing_due` alert is closed `expired` / `date_changed`, unless the case's
        `next_hearing_date` still gives that date.
      - An **added** listing raises as usual.
      - A **moved** listing (same date, different court or item) keeps its alert, since the dedupe key is case + date.
        The sweep refreshes its `data` (`court_no`, `item_no`), title and body in place, with no new notification and
        no severity change, so the alert never shows the old item.
      - No new alert kind is added (§6 item 8 is a separate decision).
    - **Timeline.** One event `listing_changed` per case whose placement changed, with payload:
      `{list_date, bench_id, causelist_id, version_from, version_to, change: added | removed | moved, before, after}`.
      `before` and `after` are lists of `{court_no, printed_sr_no, section}`. The dedupe key is
      `listing_changed:<new list id>:<case id>`. It is a tracking-card court event, because cause-list placement is
      public court data.
14. **Extra NAPIX cost.** A recheck costs one Show Cause List call per already-held list of the date, and nothing more:
    - **Today's lists:** a bench day has 22–24 benches (live test, 1 Oct 2026) with one or two lists each, about 30–45
      lists, all fetched before 18:30, so about 30–45 calls.
    - **Tomorrow's lists** were mostly fetched by the 18:30 day row minutes before and are skipped, so 0–5 calls.

    **About 35–50 calls per evening**, roughly 4–5 % of one hour's 1,000, spent between 18:30 and the 20:00 status
    batches. Parsing happens only when the bytes differ.

    *Owner check (a):* a correction to tomorrow's list published **after** 18:30 (overnight or early morning) is not
    caught before the hearing. The next evening's recheck sees it only as "today's list", after the court has sat. A
    recheck of today's lists in the 06:30 run would catch it, for another 30–45 calls. It is built behind
    `CAUSELIST_RECHECK_MORNING` (default `false`, as decided).
15. **One writer per date.** `load_causelist_day` and the recheck both take
    `pg_advisory_xact_lock(hashtext('causelist-day:' || <date>))`. A day row and a recheck of the same date on two
    workers therefore never create two versions or race a parse. A transaction-level lock is safe under PgBouncer
    transaction pooling.
16. **The operator's recheck.**
    - `aslms refetch-date <date> --recheck` queues `causelist_recheck` for a date from yesterday to tomorrow (IST): lane
      `request`, priority 20, `requested_by` the CLI actor. It goes through `napix_admin.refetch_day(..., recheck=True)`
      with the existing audit action `napix.refetch_requested` and `after.kind = "causelist_recheck"`.
    - It needs `admin.napix_refetch`, as `refetch-date` does.
    - It is CLI only in this item. *Alternative:* a data-health button, left out to keep the screen unchanged apart
      from figures.
17. **What people see.**
    - **The Cause list screen** shows the current version. A corrected list carries a "Corrected list" chip with the
      time it was received and a link "Earlier version", which opens the superseded version's entries and PDF.
    - **The case page's Listings** show superseded rows greyed out with "Replaced by a corrected list".
    - **Data health:** the daily-cycle rows gain `lists_corrected` and the recheck row's state.

### C. Retention (owner decision 12)

18. **Removing old call-log rows is allowed by the standard.** No question arises:
    - DB_STANDARD §6 says that "`napix_call_log` pruning (already planned) is the one exception and is a log, not a
      record".
    - §0 puts `napix_call_log` in the Derived / log class, whose "INSERT-only" rule governs how the application writes
      rows, not their lifetime.
    - `schema.md` Group 9 says the same.
    - `aslms_app` already has DELETE on it (0001).

    Confirmed: no deviation.
19. **The purge job.**
    - **Schedule:** daily at 03:45 IST, Celery task `aslms.napix_log_purge`. That is after the 03:00 dedupe sweep,
      clear of the backups (minute 30 of 00, 06, 12 and 18 h) and finished well before Sunday's 04:30 restore check.
    - **Cut-off:** IST midnight of `today_ist − NAPIX_CALL_LOG_KEEP_DAYS` (default 730, about 2 years; allowed range
      365–3650). Rows with `called_at` before the cut-off are deleted.
    - **Batches:**
      ```sql
      DELETE FROM napix_call_log WHERE id IN (
          SELECT id FROM napix_call_log WHERE called_at < :cutoff ORDER BY called_at LIMIT :batch)
      ```
      `NAPIX_CALL_LOG_PURGE_BATCH` defaults to 5,000 and uses `ix_napix_call_log_called_at`. Each batch commits on its
      own. The run stops after `NAPIX_CALL_LOG_PURGE_MAX_SECONDS` (default 600). If rows older than the cut-off remain,
      the run ends `partial` and the next night continues. In steady state, one night removes one day's rows.
    - **Record:** one `job_runs` row `napix-log-purge` with
      `{keep_days, cutoff, deleted, batches, more, oldest_kept_at, seconds}`. When `deleted > 0`, one `audit_log` row
      `napix.call_log_purged`: system actor `napix-log-purge`, `entity_type` `napix_call_log`, `entity_id` NULL,
      `after = {cutoff, keep_days, deleted, first_called_at, last_called_at}`. The job joins `SCHEDULER_JOBS` and the
      26 h JobLate rule.
    - **Manual run:** `aslms ops purge-call-log [--dry-run]` runs the same code. The dry run counts and writes nothing.
    - *Alternatives:* a weekly run, which means bigger batches and longer locks. Monthly partitions dropped whole, which
      means a table rewrite by migration; that is not worth it at a few thousand rows a day, and it can come later.
    - The first real deletion is in October 2028: the oldest dev rows are from October 2026.
20. **How the purge meets the other readers of the call log.** Nothing that matters is affected:
    - **Quota-window detection** (last 6 hours), **System health** (24 h and 7 days), the data-health screen (today) and
      the data-load estimate (1 h, 24 h, its window) all read far inside the kept 2 years. The 365-day floor on the
      setting guarantees this.
    - **The data-health report** over a period that starts before the cut-off would show zero calls for those days. The
      report gains `calls_kept_from` (the oldest kept day) in its meta, and the Reports screen says "Calls are kept for
      2 years; earlier days show no call figures" when the period starts before it.
    - **The load report and the console's "first load call"** are totals and dates only, and simply move forward.
    - **Backups.** A dump keeps the rows it had until that dump set ages out under `BACKUP_KEEP_*`. A restored older dump
      brings old rows back, and the next night's purge removes them again. The restore check's counted tables do not
      include the call log.
    - **`job_runs`.** It is not purged. The foreign key runs call log → job_runs (CASCADE from job_runs), so deleting
      call-log rows touches nothing else. No other table references `napix_call_log`.
    - **PgBouncer.** It is a plain DELETE with no session features, which the session-feature scan accepts.
21. **`napix_responses`: all of it is kept, and nothing is purged.**
    - **Kept forever** (cases are never deleted, so "as long as the case lives" means forever):
      - every dossier answer, Current Status batch and search answer (case number, party, advocate, filing), including
        searches whose rows were never stored because they carried no CNR;
      - masters, Cause List Bench and Details;
      - Overview probes and System health tests.
    - **Not kept**, as today: PDFs (stored in `documents`) and error answers (kept as short text in the call log).
    - **Recommendation: purge no orphans.**
      - `napix_responses` has no case link. "Belongs to a case" could only be guessed by parsing payloads.
      - An answer whose rows were not stored is the only evidence of what the court returned. It shows that no
        identifier was made up.
      - CLAUDE.md wants every answer stored verbatim.
      - DB_STANDARD §6 allows only the call-log exception. Purging responses would need a change to the standard and a
        grant migration (`aslms_app` has no DELETE there), which would be a row of its own.

    To revisit this with real numbers, `aslms ops retention-report` prints row counts and the on-disk size of
    `napix_call_log` and `napix_responses` per API and per year. Data health shows both table sizes in its new
    `retention` block.

    *Owner check (b).*

### D. The two technical gaps

22. **`aslms napix-probe-rate` logs every call.**
    - It refuses to start without the database (`napix_check.database_ready`, which moves to `services/napix_store.py`
      as `require_call_log` so both commands share it).
    - It attaches a `NapixRecorder` built with a session factory, so every attempt is committed on its own **as it
      happens**: lane, user and job NULL, as an operator's command. A 10-minute probe therefore appears in the call log
      while it runs.
    - If a write fails, it makes no further call. It exits with code 1, and the failed attempt's non-secret fields are
      in the recorder's warning.
    - The summary prints the number of attempts recorded.
    - Its `rate_limit_remaining` readings join the quota-window detection like any reading. That is welcome: the probe
      exists to observe the reset.
23. **IST dates from one helper.**
    - A new `aslms/core/clock.py` holds `IST`, `today_ist(now=None)` and `ist_midnight(d) -> datetime (UTC)`.
    - The 21 `date.today()` calls in `backend/aslms` become `today_ist()`. The existing helpers
      (`next_dates.today_ist`, `reporting_common.today_ist`, `workflow_common.today_ist`, `alert_rules.today_ist`)
      call it, with unchanged signatures.
    - A unit test fails on any new `date.today(` in `backend/aslms`.
    - `TZ` is **not** set in Compose. The application's datetimes are UTC-aware and stay so, logs stay UTC, and an
      explicit IST date can be tested.
    - This fix is small (one-line changes and one test), so it stays in this item rather than a row of its own.

### Owner checks (recommended answers are built in; say otherwise at approval)
- **(a) Morning recheck of today's lists** (decision 14). Recommended: **yes**, set `CAUSELIST_RECHECK_MORNING=true`.
  It costs about 30–45 calls at 06:30 and catches overnight corrections before the hearing. Built with the default
  `false`, which honours decision 11 as given.
- **(b) Orphaned `napix_responses`** (decision 21). Recommended: **purge none**, and review the sizes after the pilot.
- **(c) A file-only change** (different bytes, same entries) is not a new version (decision 10). Recommended: **as
  designed**.
- **(d) Daily cap of 1,000 disposed refreshes** (decision 3). Recommended: **as designed**. It is adjustable in `.env`.

## Data

Migration **0021 `0021_court_data_freshness`**: head is 0020 today; take the next free number when building. The
paragraphs below go into `docs/schema/schema.md`, Group 4 and Group 9, before the migration is written.

> **`causelists`** (transaction; court-data-freshness, migration 0021) gains the following columns:
> - `version smallint NOT NULL DEFAULT 1`;
> - `supersedes_id uuid NULL` (→ causelists **RESTRICT**): the version this row replaces;
> - `superseded_at timestamptz NULL`: set when a later version replaces this row;
> - `last_checked_at timestamptz NULL`: the latest evening recheck that found the list unchanged or replaced it;
> - `entries_sha256 varchar(64) NULL`: the fingerprint of the row's entries, written at every parse.
>
> The six-column unique constraint becomes **unique (court_id, list_date, bench_id, napix_causelist_id, source,
> list_type, version) NULLS NOT DISTINCT**. A partial unique index `ix_causelists_current` on the six identity columns
> NULLS NOT DISTINCT WHERE `superseded_at IS NULL` allows one current version per list. A partial unique index
> `ix_causelists_supersedes` (supersedes_id) WHERE `supersedes_id IS NOT NULL` means a version is replaced at most once.
>
> CHECKs:
> - `ck_causelists_version`: `(version = 1) = (supersedes_id IS NULL)`;
> - `ck_causelists_not_self`: `supersedes_id IS NULL OR supersedes_id <> id`.
>
> **How a re-issue is written** (`services/causelists.py`, one transaction): it sets the current row's `superseded_at`,
> then inserts the new row with `version + 1`, `supersedes_id`, its own document and its own entries. Nothing else on
> the old row and nothing on its entries changes; neither is deleted. Every reader filters `superseded_at IS NULL`,
> except the named exceptions of design `court-data-freshness`, decision 12. `aslms_app` grants are unchanged
> (SELECT / INSERT / UPDATE). `audit_log` is not written: system writes of court data are recorded by events.

> **`causelist_entries`**: unchanged and still immutable. An entry belongs to exactly one version of its list.

> **`fetch_kind`** gains `causelist_recheck` (ref `YYYY-MM-DD`): the evening recheck of the held NAPIX lists of a date,
> making Show Cause List calls only. Lane `daily`, priority 21, or `request` and 20 from `aslms refetch-date --recheck`.
> The value is added in an autocommit block, as 0017 and 0019 did. Priorities gain 21 (list rechecks) and 55 (dossiers
> of disposed cases within a year of disposal, lane `daily`).

> **`ref_event_type`** gains `listing_changed` (label "Listing changed", timeline label "Cause list corrected",
> `is_tracking_card` true), inserted by migration 0021 with `ON CONFLICT (code) DO NOTHING` and by `aslms seed`.

> **`source_failures`** gains the kinds `causelist_reissue` (ref `<causelist id>|<sha256 of the new PDF>`: a re-issued
> PDF that did not parse or had no entries) and `fetch_causelist_recheck` (the queue kind's failure).

> **`napix_call_log` retention** (owner decision 12, DB_STANDARD §6): rows are kept for `NAPIX_CALL_LOG_KEEP_DAYS`
> (default 730) IST days. The daily 03:45 IST job `napix-log-purge` deletes rows with `called_at` before the IST
> midnight of that many days ago, in batches of `NAPIX_CALL_LOG_PURGE_BATCH` (5,000), each committed on its own, for at
> most `NAPIX_CALL_LOG_PURGE_MAX_SECONDS` (600). It writes a `job_runs` row and, when it deleted rows, one `audit_log`
> row `napix.call_log_purged` (system actor). This is the only deletion of this table and needs no new grant
> (`aslms_app` DELETE since 0001).

> **`napix_responses` retention:** kept without limit and never purged (design `court-data-freshness`, decision 21).

> **`cases`**: no new column. `closed_at` is cleared when a dossier shows a disposed case pending again (restoration),
> and that change emits `status_changed`.

> **`job_runs.job`** gains the free-text values `disposed-refresh` and `napix-log-purge`. New audit action:
> `napix.call_log_purged`.

**What migration 0021 does:**
- adds the five columns and the two CHECKs;
- replaces the unique constraint (the existing six-column one, by its generated name) with the seven-column one;
- creates `ix_causelists_current` and `ix_causelists_supersedes`;
- inserts the `ref_event_type` row;
- adds the `fetch_kind` value, last, in an autocommit block.

Existing rows become version 1 and current. `entries_sha256` stays NULL until their first recheck computes it from the
stored entries.

**Its downgrade:**
- refuses while any `causelists` row has `version > 1` (that is legal-record history);
- refuses while a `causelist_recheck` queue row is pending or running;
- otherwise drops the indexes, CHECKs and columns and restores the six-column constraint;
- deletes the `ref_event_type` row only when no event uses it;
- leaves the enum value, which PostgreSQL cannot drop.

## Services

**`aslms/core/clock.py`** (new): `IST`, `today_ist(now=None) -> date`, `ist_midnight(d) -> datetime` (UTC-aware).
Every `date.today()` in `backend/aslms` is replaced (decision 23).

**`services/tracking.py`**
- `disposed_refresh_refs(session, today, *, keep_days, every_days) -> list[str]` returns the eligible CNRs, oldest
  `last_full_refresh_at` first (decision 3).
- `enqueue_disposed_refresh(session, today=None, settings=None) -> dict` applies the cap, then calls
  `queue.enqueue(DOSSIER, cnr, PRIORITY["dossier_disposed"], requeue=True, lane=DAILY)`. It returns
  `{eligible, due, cap, queued}`.

**`services/queue.py`**: `PRIORITY` gains `list_recheck: 21` and `dossier_disposed: 55`. The module docstring gains the
new kind and both priorities.

**`services/schedules.py`**
- `enqueue_evening_lists(session, today=None) -> dict` calls `enqueue_daily_lists`, then `enqueue_rechecks(session,
  [today, today + 1])`.
- `enqueue_morning_lists` calls `enqueue_daily_lists` plus a recheck of today when `CAUSELIST_RECHECK_MORNING`.
- `enqueue_rechecks(session, days, *, lane=DAILY, priority=21, requested_by=None) -> int`.
- `today` defaults to `today_ist()`.

**`services/causelists.py`**
- `CURRENT_LIST` (the SQL condition) and `day_lock(session, list_date)` (the advisory lock, decision 15).
  `load_causelist_day` takes the lock. `_get_or_create_list` looks up and creates only the current version.
- `entries_fingerprint(rows) -> str` over the stored-form fields (decision 10). `apply_entries` writes
  `causelist.entries_sha256`.
- `recheck_day(session, hc, court, list_date, store, *, now, fresh_minutes, origin) -> RecheckReport`. Under the lock,
  for each candidate list (decision 8):
  1. Call `show_causelist`. A 628 counts `not_available`; an answer that is not a PDF counts `failed`. Both set
     `last_checked_at`.
  2. If the sha256 matches, count `unchanged`.
  3. Otherwise parse. A failure or empty result counts `unparsed` and records `causelist_reissue` (decision 11).
  4. If the fingerprint is equal, count `same_entries`.
  5. Otherwise call `_new_version`, which:
     - runs `store_pdf` (dedupe by sha256);
     - supersedes the old row, then inserts the new one;
     - runs `apply_entries` with the origin (daily lane, the list's date);
     - runs `_listing_changes` (decision 13: events, then `matching.score_cases` for old-only cases with origin
       `rescore`, then `next_dates.match_after_court_change` for both versions);
     - resolves any `causelist_reissue` of the list.

  `RecheckReport` = `{list_date, candidates, called, unchanged, same_entries, versions_new, unparsed, not_available,
  failed, skipped_fresh, cases_changed, warnings}`.

**`services/runner.py`**: `dispatch` handles `CAUSELIST_RECHECK` → `recheck_day`. With NAPIX off it raises as the other
kinds do. The item is `skipped` when there were no candidates. `JobRun.run_date` uses `today_ist()`.

**`services/cases.py::apply_dossier`**: on `disposed → pending` it clears `closed_at` and emits `status_changed`
(decision 4).

**`services/alerts.py::sweep_dates`**: for an open `hearing_due` alert whose current row has a different `court_no` or
`item_no`, it updates `data`, `title` and `body` (`alert_rules.render_alert`). It sends no notification and leaves the
severity unchanged. A new counter `refreshed_hearing`.

**`services/matching.py`, `calendar.py`, `case_filters.py`, `inbox.py`, `visibility.py`, `next_dates.py`, `reports.py`,
`reporting_common.py`, `reference.py`, `data_load.py`, `napix_admin.py`, `causelist_view.py`, `case_detail.py`**: they
add the current-version condition (decision 12). On top of that:
- `causelist_view`: `_list_out` adds `version`, `supersedes_id`, `superseded_at`, `corrected_at` (the version's
  `fetched_at` when `version > 1`) and `last_checked_at`. `entries` accepts a superseded `list_id`, and the answer's
  `list.superseded` tells the screen.
- `case_detail.listings`: items add `superseded` and `list_version`. The listing count is current-only.
- `case_detail.COURT_EVENTS` and `seed.TRACKING_CARD_EVENTS` gain `EventType.LISTING_CHANGED`.

**`services/retention.py`** (new)
- `purge_call_log(session_factory, settings, *, now=None, dry_run=False) -> PurgeReport` (decision 19). It writes the
  `job_runs` row and, when rows were deleted, the audit row with `services/audit.write_audit(Actor.system(
  "napix-log-purge"), "napix.call_log_purged", "napix_call_log", None, after=...)`.
- `retention_report(session) -> dict`: counts per API and year and `pg_total_relation_size` for both tables. It is
  read-only.

**`services/napix_store.py`**: `require_call_log()`, moved from `cli/napix_check.database_ready`. `napix_check` imports
it.

**`cli/napix_probe.py`**: `require_call_log()` before the first call, a `NapixRecorder(session_factory=
get_sessionmaker())` flushed after every call, a stop on a write failure, and the recorded count in the summary.
Display times are IST (decision 22).

**`services/napix_admin.py::refetch_day`** gains `recheck: bool = False`. It queues `causelist_recheck` (request lane,
priority 20) for yesterday to tomorrow, refuses other dates with `date_out_of_range`, and audits
`napix.refetch_requested` with `after.kind`. The `already_held` guard does not apply to a recheck.

**CLI**
- `aslms refetch-date <date> --recheck` (decision 16).
- `aslms daily-cycle disposed`: a new choice that calls `enqueue_disposed_refresh`.
- `aslms ops purge-call-log [--dry-run]` and `aslms ops retention-report [--format md|json]` (`cli/ops.py`).

**`api/schemas.py`**: the queue-kind literal gains `causelist_recheck`.

**`services/data_health.py`**: `daily_cycle` rows gain `lists_corrected` and `recheck` (the state of the date's
`causelist_recheck` row). A new block `retention` = `{call_log_keep_days, call_log_oldest_at, last_purge_at,
last_purge_deleted, last_purge_status, call_log_bytes, responses_bytes, disposed_refresh: {eligible, due_now,
queued_last_run, last_run_at}}`.

**`services/reports.py`** (data-health report): the meta gains `calls_kept_from`.

**`services/job_repair.py`**: `SCHEDULER_JOBS` gains `disposed-refresh` and `napix-log-purge`.

**`core/config.py`**: the settings, with ranges:
- `DISPOSED_REFRESH_DAYS` 365 (90–730);
- `DISPOSED_REFRESH_EVERY_DAYS` 28 (7–60);
- `DISPOSED_REFRESH_DAILY_MAX` 1000 (0–5000);
- `CAUSELIST_RECHECK_FRESH_MINUTES` 180 (30–720);
- `CAUSELIST_RECHECK_MORNING` false;
- `NAPIX_CALL_LOG_KEEP_DAYS` 730 (365–3650);
- `NAPIX_CALL_LOG_PURGE_BATCH` 5000 (500–50000);
- `NAPIX_CALL_LOG_PURGE_MAX_SECONDS` 600 (60–3600).

All of them are added to `.env.example` (no secrets).

**Frontend** (small):
- Cause list screen: the "Corrected list" chip, its time and the "Earlier version" link (decision 17).
- Case Listings tab: superseded rows greyed out with their label.
- Data collection → Data health: the `lists_corrected` and recheck columns and the Retention block.
- Reports, data-health tab: the `calls_kept_from` note.

**Rules kept:**
- NAPIX is called only through `NapixHighCourt` / `NapixClient`. Every attempt is logged by the runner's recorder, or
  by the probe's.
- `NAPIX_ENABLED` is untouched.
- No legal record is deleted or edited: entries are immutable, and a superseded list only gains `superseded_at`.
- The only deletion is the call-log purge sanctioned by DB_STANDARD §6.
- Visibility is unchanged except that a superseded code no longer grants the counsel basis.
- Every new system action has a `job_runs` row, and the deletion has an audit row.

## API
No new endpoint and no new `Permission`. Changed responses (additive):

| Method and path | Permission (unchanged) | Change |
|---|---|---|
| `GET /causelists/{list_date}` | `cases.view_scope` or `cases.view_all` | Each list adds `version`, `supersedes_id`, `superseded_at`, `corrected_at`, `last_checked_at`. Only current versions are listed. |
| `GET /causelists/{list_date}/entries` | same | Without `list_id`: current versions only. With a superseded `list_id`: that version's entries, `list.superseded = true`. The visibility of claim and owner columns is unchanged. |
| `GET /causelists/lists/{id}/file` | inline `documents.view`, attachment `documents.download` | Works for any version. |
| `GET /causelists/dates` | same | Counts current versions only. |
| `GET /cases/{ref}/listings` | the case read (`cases.view_scope` / `cases.view_all`, case visible) | Items add `superseded`, `list_version`. |
| `GET /cases/{ref}` | same | `counts.listings` is current-only. Timeline events may include `listing_changed`. |
| `GET /admin/data-health` | `reports.state` or `admin.napix_refetch` or `admin.masters_sync` | `daily_cycle[].lists_corrected`, `daily_cycle[].recheck`, the new `retention` block. |
| `GET /reports/data-health` (and its exports) | as today (row 39) | The meta adds `calls_kept_from`. |

The OpenAPI snapshot test is updated for these fields.

## Jobs

| Job | Schedule (IST) | What it does | NAPIX | Record |
|---|---|---|---|---|
| `aslms.enqueue_morning_lists` (replaces the 06:30 `enqueue_daily_lists` entry) | 06:30 daily | `causelist_day` × 3, plus `causelist_recheck` for today only when `CAUSELIST_RECHECK_MORNING` | via the runner | queue rows |
| `aslms.enqueue_evening_lists` (replaces the 18:30 entry) | 18:30 daily | `causelist_day` × 3 (priority 20), `causelist_recheck` for today and tomorrow (21, daily lane) | via the runner, about 35–50 Show Cause List calls | queue rows; the runner's `queue-run` job_runs |
| `aslms.enqueue_disposed_refresh` | 02:30 daily | dossier rows (priority 55, daily lane, `requeue`) for eligible disposed cases, capped | via the runner, about eligible ÷ 28 calls a night | `job_runs` `disposed-refresh` |
| `aslms.napix_log_purge` | 03:45 daily | deletes call-log rows older than the cut-off in batches | none | `job_runs` `napix-log-purge`; `audit_log` `napix.call_log_purged` when rows were deleted |
| queue kind `causelist_recheck` | as queued | `recheck_day` | Show Cause List only | the queue row's `result` (`RecheckReport`) |

**Prometheus.** The JobLate 26 h rule's job pattern becomes `dedupe-sweep|digests|disposed-refresh|napix-log-purge`,
with promtool tests for the two new jobs (`infra/prometheus/rules.yml`, `rules.test.yml`). The runbook line in
`docs/operations.md` is left to the scribe.

## Tests

All database tests use the scripted gateway (`tests/db/conftest.py::router` / `napix`). `NAPIX_ENABLED` is never set.
Re-issue tests wrap `router` so the second Show Cause List answer is a second fixture PDF: the fixture with one row
removed, one moved and one added, built from `tests/fixtures/causelists`.

**Unit**
- `test_clock.py`: `today_ist` gives the IST date at 23:00 UTC (the next day) and at 18:00 UTC. `ist_midnight` is
  18:30 UTC of the day before.
- `test_no_naive_today.py`: no `date.today(` in `backend/aslms`.
- `test_disposed_refresh_cap`: the cap is `min(max, ceil(eligible/28))`, and 0 switches the job off.
- `test_entries_fingerprint`: equal for re-ordered dict keys and different `raw_lines`. It differs for a changed item
  number, counsel code or party text. It matches the stored-form truncation.
- `test_settings_ranges`: the new settings reject out-of-range values. `NAPIX_CALL_LOG_KEEP_DAYS` below 365 fails.
- `test_current_list_scan`: every module under `services/` whose SQL joins `causelist_entries` to `causelists` uses
  `CURRENT_LIST` / `superseded_at IS NULL`, or is on the named exception list.
- `test_napix_probe_logs`: with a fake client and recorder, every attempt is flushed after its call. A failed flush
  stops the loop. The command refuses to start when `require_call_log` raises.
- The promtool test for the two JobLate cases.

**Database (`tests/db/test_court_data_freshness.py` and additions)**
- **Disposed refresh: selection.** A disposed case refreshed 29 days ago with disposal 100 days ago is queued at 55,
  lane daily. These are not queued:
  - one refreshed 10 days ago;
  - one disposed 400 days ago;
  - one never fully fetched (left to the sweep);
  - a merged row;
  - a pending case.
- **Disposed refresh: fallback date.** A disposed case without `disposal_date` uses `closed_at`.
- **Disposed refresh: order.** The cap takes the oldest refresh first. A `job_runs` row `disposed-refresh` holds the
  counters.
- **Disposed refresh: restoration.** A disposed case whose dossier (scripted, `pend_disp = P`) is applied:
  - becomes pending with `closed_at` NULL;
  - emits `status_changed` with `["disposed", "pending"]`;
  - appears in `non_disposed_cnrs`, so the next `enqueue_status_batches` covers it;
  - leaves the disposed-refresh selection;
  - raises a `status_changed` alert for its owner.
- **Recheck: unchanged.** A list identical to the stored PDF makes one Show Cause List call, no Bench or Details call,
  sets `last_checked_at`, and writes no version.
- **Recheck: freshness.** A list fetched 10 minutes ago is skipped with no call. A retried recheck item calls nothing
  for lists already checked.
- **Recheck: re-issue.** A list with different entries:
  - creates version 2 with `supersedes_id`. Version 1 has `superseded_at` set, and its entries are byte-for-byte
    unchanged (same ids, same values) and still present;
  - has its entries under version 2;
  - leaves exactly one current version (the partial index rejects a second).
- **Recheck: same entries, different bytes.** It counts `same_entries` and writes no version or document.
- **Recheck: unparsable PDF.** It keeps version 1 current, writes `causelist_reissue` to `source_failures` and stores
  no document. A later unchanged recheck resolves it.
- **Recheck: 628.** On a held list it counts `not_available` and changes nothing.
- **Reaction: removed case.** A case only in version 1:
  - loses its engine recommendation when that was its only signal (`expired`);
  - keeps a claim untouched;
  - gets a `listing_changed` event with `removed`;
  - has its `hearing_due` alert for that date closed `date_changed` by the next `sweep_dates`, unless
    `next_hearing_date` equals the date;
  - is no longer returned by `calendar.hearing_rows`.
- **Reaction: moved case.** Its open alert's `data.item_no` and body are refreshed with no new notification row. It
  gets a `listing_changed` event with `moved`.
- **Reaction: added case.** It is created or found, scored and queued as by a normal list.
- **Readers.** `causelist_view.day` lists only version 2. `entries(list_id=<v1>)` returns version 1's rows with
  `superseded`. `case_detail.listings` returns both rows with the flag and counts one. `visibility.codes_condition` no
  longer matches a code only in version 1.
- **Locking.** `load_causelist_day` and `recheck_day` of the same date in two sessions: the second waits, and exactly
  one version 2 exists.
- **Schedules.** `enqueue_evening_lists` writes three `causelist_day` rows and two `causelist_recheck` rows (21,
  daily). With `CAUSELIST_RECHECK_MORNING`, `enqueue_morning_lists` writes one recheck.
  `refetch_day(recheck=True)` writes a request-lane row with `requested_by` and an audit row with `kind`. It refuses a
  date two days back.
- **Purge.** With rows 731, 730 and 729 days old (IST boundaries), the purge:
  - deletes only those before the cut-off;
  - batches by `NAPIX_CALL_LOG_PURGE_BATCH`, with one commit per batch;
  - writes `job_runs` `napix-log-purge` and one audit row `napix.call_log_purged`;
  - writes no audit row when nothing is old enough;
  - with `--dry-run`, deletes nothing and writes no audit row;
  - ends `partial` with `more = true` when the time limit stops it;
  - leaves `napix_window.current` and the System health figures, computed before and after, identical when only old
    rows were removed;
  - runs as `aslms_app` (the `app_engine` fixture) without a permission error;
  - never deletes a `napix_responses` row.
- **Migration.** 0021 upgrades a database holding causelists and entries, and its rows become version 1, current. The
  downgrade refuses while a version 2 exists. The `ref_event_type` row exists after the upgrade without a seed.
- `test_schema_metadata` stays green with the new columns, indexes and CHECKs.

## Verification

1. `ruff check` is clean, and `pytest -q` is green: unit and database, with the migration cycle test including 0021.
2. On the dev stack, run the explicit `migrate` step (`aslms ops migrate`), then restart (`init` runs `seed`).
   - `SELECT version, count(*) FROM causelists GROUP BY 1` shows only version 1, equal to the earlier total.
   - `SELECT count(*) FROM ref_event_type WHERE code = 'listing_changed'` returns 1.
3. Size the disposed refresh:
   ```sql
   SELECT count(*) FROM cases
   WHERE status = 'disposed' AND cnr IS NOT NULL AND merged_into_case_id IS NULL
     AND last_full_refresh_at IS NOT NULL
     AND COALESCE(disposal_date, (closed_at AT TIME ZONE 'Asia/Kolkata')::date)
         >= (now() AT TIME ZONE 'Asia/Kolkata')::date - 365;
   ```
   Record the eligible number N. Then run `aslms daily-cycle disposed`, a new choice of the existing command that
   calls `enqueue_disposed_refresh`. The `queued` count is at most `min(1000, ceil(N/28))` on a stack whose cases were
   all refreshed recently: only those older than 28 days are due. Record N in the decisions log.
4. Count the lists a recheck will call:
   ```sql
   SELECT list_date, count(*) FROM causelists
   WHERE source = 'napix' AND superseded_at IS NULL AND document_id IS NOT NULL
   GROUP BY 1 ORDER BY 1 DESC LIMIT 7;
   ```
   Expect about 30–45 a day. This is the per-evening call estimate.
5. Live (owner-run, master switch set for that run only):
   - Run `aslms refetch-date <today> --recheck`, then let the worker run.
   - The queue row's `result` shows `called` equal to step 4's count for today, minus fresh lists. `versions_new` is
     normally 0.
   - `napix_call_log` gains exactly `called` rows of API `show_causelist` and no `causelist_bench` or
     `causelist_details` rows for that item.
6. `aslms ops purge-call-log --dry-run` prints `deleted 0` and the cut-off date (two years back) on the dev database.
   `aslms ops retention-report` prints the two table sizes. Record them in the decisions log as the baseline for owner
   check (b).
7. Run `aslms napix-probe-rate --calls 3 --interval 5` (master switch set for that run only). Then
   `SELECT count(*) FROM napix_call_log WHERE api = 'overview' AND called_at > now() - interval '5 minutes'` rises by
   3 (more if a renewal happened). Each row has `user_id`, `lane` and `job_run_id` NULL.
8. Run `docker compose exec scheduler python -c "from aslms.core.clock import today_ist; print(today_ist())"` between
   00:00 and 05:30 IST: it prints the IST date. The next `dedupe-sweep` `job_runs.run_date` equals the IST date of its
   03:00 run.
9. In the browser (owner's checklist): a corrected list (from the test data or a real one) shows the chip and the
   earlier version. The case Listings tab greys the replaced row. Data health shows the Retention block.

## Open questions
None. The four owner checks above have recommended answers built in. The owner may change any of them at approval
without a redesign.
