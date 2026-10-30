# Design: Data Collection redesign, the five review advisories of round 1

```
slug: data-collection-redesign-advisories
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context

Backlog row 191, a follow-up of row 172 `data-collection-redesign` (round 1 of 4, merged 27 Oct 2026). The review of
row 172 left five advisories, none blocking, carried here unfixed (report `docs/reports/2026-10-27-data-collection-redesign.md`):

1. the Problems links `/data/queue?status=failed` are not read by the Queue tab and show to readers without
   `/admin/napix/queue` access;
2. the `overview()` queries are not wrapped in `_timed`, so a cancelled query answers 500 instead of 503
   `search_timeout`;
3. Load Control's Status badge says Running when Overview says Finished or Not Started (use `collection_state`);
4. `useCountUp` restarts from 0 on each poll, so live figures flash to zero;
5. `causelist_recheck` calls are counted in the `causelist_day` family without finished days, which overstates the
   calls per cause-list day and delays both estimate dates.

Since then, **row 173** `data-collection-redesign-tabs` (deployed 29 Oct 2026) retired the Health, Queue and Calls and
Duplicates tabs, built Problems and Fixes, and repointed every Problems link. **Row 174** `data-collection-fetch` is
built on `feature/data-collection-fetch`, not merged (parked with one blocking review finding). It changes
`data_load.overview()` (the `bulk` summary from `services/collect.py`), `pulse()`, `Overview.tsx`, `CollectNow.tsx`,
`ProblemsAndFixes.tsx`, `dataCollection.ts` and `messages.ts`. It does not touch `AutomaticCollection.tsx`,
`motion.ts`, `progress()` or `measure_all()`.

**Each advisory, checked against `main` (eeb3424) and row 174's branch on 30 Oct 2026:**

| # | State | Why |
|---|---|---|
| 1 | **Fixed by row 173; dropped** | `PROBLEM_LINKS` (`frontend/src/lib/dataCollection.ts`) now points at `/data/problems#failed`, `#duplicates` and `#gaps`. Overview's Problems line, the month table's Problems cell and Load Control's failed count all use it. Problems and Fixes is shown to `DATA_READERS`, the same set as Overview. A reader without a health-reader function gets the summary by kind with a note in place of the failed rows (round 2, deviation 3), so a link never leads to a 403. `/data/queue?status=failed` survives only as a redirect to `/data/problems` that keeps the query string and does not read it. That is harmless, and a bookmark still lands somewhere useful. Pinned by `collection.test.tsx` (the four links) and `data.test.tsx` (the failed-rows read and the redirects) |
| 2 | **Open, on `main` and on row 174's branch** | `overview()` calls `with_timeout` and then runs its reads bare. `get_overview` catches nothing, so `QUERY_CANCELED` becomes a 500. Row 174 adds `collect.active_bulk_summary` to the same function, which widens the exposure. `progress()` (`GET /admin/data-load`), which Automatic Collection polls every 30 s, has the same defect and is fixed with it |
| 3 | **Open** | `LoadControl` (`AutomaticCollection.tsx`) reads `GET /admin/data-load`. That answer has no collection state, so the badge is `settings.paused ? Paused : Running` |
| 4 | **Open, portal-wide** | `useCountUp` (`components/ui/motion.ts`) resets `frame` to 0 whenever `target` changes, so the first render after each poll shows 0. It is used by Overview's figures and by the kit `Kpi` on every dashboard |
| 5 | **Open** | `measure_all` counts every queued call to `causelist_bench`, `causelist_details` and `show_causelist` as the cause-list day family. The evening and morning rechecks (`causelist_recheck`, row 122) call `show_causelist` in the daily and request lanes and are not in the denominator. Row 174's deviation 13 adds rechecks at the "now" priority, so the error persists. The old load-lane `measure()` is not affected, because rechecks never run in the load lane |

**Not covered:** row 204 (the row 173 advisories); the pulse, which sets no statement timeout and so cannot be
cancelled by it; any layout question (row 187).

## Decisions

1. **Advisory 1 is closed as fixed by row 173, with no code change.** Alternative: also read `status=failed` on
   `/data/problems` to open Failed Fetches. Rejected: the section is already the first list on that tab, and old
   links land there through the redirect.
2. **The Overview and the old progress read answer 503 `search_timeout` when their statements are cancelled.**
   - `data_load.overview()` runs everything after `with_timeout` inside the existing `_timed` helper, with the message
     "the overview took too long; try again shortly". This includes, once row 174 has merged,
     `collect.active_bulk_summary`.
   - `data_load.progress()` does the same, with the message "the progress took too long; try again shortly".
   - `get_overview` and `get_progress` catch `HANDLED` and raise `_http(exc)`, as `get_coverage` and `get_gaps` do.
   - Alternative: a FastAPI exception handler for `OperationalError`. Rejected: it would hide other database errors
     behind a 503 across every router. The data-load module already has a single pattern.
3. **The portal's `search_timeout` words become "That took too long. Try again in a moment, or ask for a shorter
   period."**
   - Today's "Ask for fewer months." is wrong for the Overview, the gaps lists and the audit search, which share the
     code.
   - The code stays the same (the advisory names it, and three screens use it).
   - Alternative: a new code `overview_timeout`. Rejected: one more code for the same condition.
4. **Load Control's Status badge reads the same collection state as the Overview.**
   - `GET /admin/data-load` gains `collection: "running" | "paused" | "finished" | "not_started"` (additive), computed
     by the existing `data_load.collection_state(session, settings, period)`: one count of load-lane rows waiting or
     fetching.
   - A shared `CollectionStateBadge` (in `components/data/`) gives both screens the same words (`T.dc.states`) and
     tones (Running info with the pulse, Paused warning with the reason in a tooltip, Finished success, Not Started
     neutral). Load Control and the Overview status line both use it.
   - The Pause and Resume buttons still follow `settings.paused`, unchanged.
   - Alternative: Load Control reads `GET /admin/data-load/overview`. Rejected: that adds a second, heavier 30 s poll
     to the tab for one word.
5. **`useCountUp` counts from the value on screen to the new value, never through 0.**
   - On first mount it counts up from 0, as today (the entry motion).
   - On a change it counts from the value shown at that moment, up or down, over the same frames. A change in the
     middle of a count starts from the value then shown.
   - Under reduced motion, or with a target that is null or 0, the target is returned at once, as today.
   - The hook's signature is unchanged, so the Overview figures and every `Kpi` get the fix with no call-site change.
   - Alternative: animate only on first mount. Rejected: the owner asked for live figures that visibly move (row 172,
     decision 13).
6. **Recheck calls are left out of the cost of a cause-list day.**
   - `measure_all` subtracts the Show Cause List calls made by `causelist_recheck` rows from the cause-list family's
     call count, clamped at 0.
   - These are the rows that finished (`done` or `skipped`) inside the measuring window, as `sum((result->>'called')::int)`.
     `RecheckReport.called` is already stored in `fetch_queue.result` by `queue.complete`.
   - `BasisAll` and `EstimateAllBasisOut` gain `recheck_calls: int` (additive).
   - "How This Is Worked Out" adds one sentence: "Calls that check lists already held for corrections (n in the last
     7 days) are not counted in the cost of a cause-list day."
   - **Known limit:** a token renewal inside a recheck (the 401 step and its repeat), and the calls of a recheck
     attempt that failed and was retried, stay in the family's count. These are a handful against hundreds of calls a
     day, recorded here and not corrected.
   - Alternatives:
     - measure the day's cost from the load lane only. Rejected: the rate disappears once the load finishes, and the
       daily lane's days are the larger share of new work.
     - attribute calls to the recheck row running at that moment. Rejected: it relies on a single sequential worker,
       and `started_at` keeps only the last attempt.
     - a `kind` column on `napix_call_log`. Rejected: it needs a migration for a follow-up, and the stored count is
       enough.
7. **In passing, the leftovers of round 2 on the same files:**
   - the `T.data` keys that no source file reads once row 174 has merged (round 2, deviation 9);
   - `DataFrame.tsx`'s doc comment that still says the old tabs follow "until round 2".

   No behaviour change. Keys that row 174 reads stay.
8. **This row builds after row 174 merges.** Row 174 edits `overview()`, `Overview.tsx` and `messages.ts`, so building
   on top of it avoids a conflicting merge. The `_timed` wrapper then covers the bulk summary from the start. No
   migration; `docs/schema/schema.md` is unchanged.

Nothing here deviates from the plan.

## Data

None. No table, column or reference code changes; no migration. The two additive answer fields (`collection` on
`DataLoadOut`, `recheck_calls` on `EstimateAllBasisOut`) are API shapes, not schema.

## Services

- `backend/aslms/services/data_load.py`
  - `overview()`: everything after `with_timeout` runs through `_timed(..., "the overview took too long; try again
    shortly")`, so a cancel raises `SearchTimeout`.
  - `progress()`: the same, with its own message. Its answer gains `collection` from `collection_state(session,
    settings, period)`.
  - `measure_all()`: a new read, `recheck_calls`, the summed `result->>'called'` of `causelist_recheck` rows finished
    (`done`, `skipped`) at or after `since`, with null or missing values counting 0.
    - `calls["causelist_day"] = max(0, family_calls - recheck_calls)`.
    - `recheck_calls` is carried on `BasisAll`.
    - `compute_two` is unchanged; it reads the corrected `calls_per_item`.
- No audit rows: reads only, as today. No NAPIX call anywhere.

## API

| Method and path | Function | Change |
|---|---|---|
| `GET /admin/data-load/overview` | any of `data_load.READERS` (`admin.data_load`, `reports.state`, `admin.napix_refetch`, `admin.masters_sync`), unchanged | 503 `search_timeout` when a statement is cancelled (was 500). `estimate.basis.recheck_calls` added |
| `GET /admin/data-load` | the same readers, unchanged | 503 `search_timeout` when a statement is cancelled. New field `collection`. `estimate` is unchanged: the old load-lane `measure()` never sees a recheck |

- No new endpoint and no change to who may read.
- Answers carry system totals only, no case content.
- `frontend/openapi.json` and `src/lib/api/schema.d.ts` are regenerated (`npm run gen:api`).

## Jobs

None.

## Tests

**Backend** (`backend/tests/db/test_data_collection_overview.py`):
- `test_overview_cancelled_query_answers_503_search_timeout`: through the API client. One inner reader is patched to
  run `SET LOCAL statement_timeout = 1` and then `SELECT pg_sleep(0.2)` on the request's session, so the real
  `QUERY_CANCELED` passes through `_timed` and the router. The test expects 503 with code `search_timeout`, never 500.
  (The same helper can serve row 204's item 2.)
- `test_progress_cancelled_query_answers_503_search_timeout`: the same for `GET /admin/data-load`.
- `test_progress_collection_state_matches_overview`: running, paused, finished and not started give the same
  `collection` on both answers for the same data.
- `test_measure_all_leaves_recheck_calls_out_of_cause_list_days`:
  - setup: finished `causelist_day` rows with their call-log rows; one `causelist_recheck` row (daily lane, `done`,
    `result.called = k`) with k `show_causelist` call-log rows in the daily lane;
  - `calls["causelist_day"]` and `calls_per_item["causelist_day"]` equal the figures without the recheck;
    `recheck_calls == k`;
  - a recheck row finished before the window, or a `failed` one, is not subtracted;
  - the count never goes below 0.
- `test_estimate_dates_not_delayed_by_rechecks`: `compute_two` gives the same two finish times with and without
  recheck calls in the log.

**Frontend:**
- `components/ui/motion.test.tsx`:
  - `useCountUp` keeps the shown value on the first render after a new target (120 to 180 renders 120, then climbs to
    180);
  - it counts down (180 to 90);
  - a change mid-count starts from the value shown;
  - no render after the first mount shows 0 for a non-zero target;
  - reduced motion is unchanged.
- `components/data/collection.test.tsx`:
  - Load Control's Status reads Finished, Not Started, Paused (with the reason as a tooltip) or Running from
    `collection`, with the same words as the Overview status line;
  - a second Overview poll with new totals never renders "0" in a tile;
  - "How This Is Worked Out" shows the recheck sentence when `recheck_calls > 0`.
- `lib/messages`: the `search_timeout` wording (an existing errors test, or one line in it).
- uicheck fixtures (`frontend/e2e/fixtures/index.ts`): `/admin/data-load` answers gain `collection`, and every
  overview's estimate basis gains `recheck_calls`. The image build runs `tsc --noEmit` and fails without them (the
  cause of row 197).

## Verification

1. `ruff check .` clean, `pytest -q` green; in `frontend/`, `npm run lint`, `npm run typecheck` and `npm test` green.
   `npm run gen:api` leaves no diff.
2. The screen check on a private network against images built from the branch, as `docs/operations.md` section 16
   says (never Compose on the shared stack): 0 findings on `/data/overview`, `/data/automatic`, `/data/collect` and
   `/data/problems` at 375, 768 and 1280 px.
3. Dev, after deploying (no migration, `docker compose build`, `up` carrying the court-data switch):
   - with the historical load still running, Automatic Collection's Status reads Running, the same as Overview's
     status line;
   - on the Overview, a figure that changes between polls moves from its old value to the new one and never shows 0;
   - `aslms data-load status --json` (read only; it prints the progress block) carries `collection: "running"`;
   - on the Overview, "How This Is Worked Out" shows the recheck sentence with a count above 0 (the rechecks run at
     06:30 and 18:30);
   - `aslms data-load status` (read only) prints the two estimate lines. Run it just before and just after the
     deploy: neither date is later at the same pace.

## Open questions

None.
