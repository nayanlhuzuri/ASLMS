# Design: Problems and Fixes follow-ups (row 173 review advisories)

```
slug: data-collection-redesign-tabs-followups
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 204. The row 173 review (`docs/reports/2026-10-29-data-collection-redesign-tabs.md`, "Review findings")
left three advisories on round 2 of the Data Collection redesign (`docs/design/data-collection-redesign.md`, decisions
4 and 42-46; pointer note `docs/design/data-collection-redesign-tabs.md`, deviations 1-2). Checked against `main`
(eeb3424) and the parked row 174 branch `feature/data-collection-fetch` (6633afc) on 30 Oct 2026.

1. **Collect These reports a case "queued" while nothing is fetched.** The button
   (`frontend/src/components/data/ProblemsAndFixes.tsx:466-476`) posts the page's cases that are not being fetched to
   `POST /admin/data-load/fetch-details` with `force: false`. `data_load.fetch_details`
   (`backend/aslms/services/data_load.py:1840-1902`) calls `queue.enqueue(..., requeue=held)` (1875-1883), and for a case
   without details `held` is false. `enqueue` leaves a `done` row done without `requeue` (`services/queue.py:86-97`)
   and returns False, but the return value is ignored and the case is reported `queued` (1884-1887), counted in the
   audit row's `queued` and in the portal's "n cases sent" note. The Data Gaps list shows exactly such cases as Not Yet
   Queued (a `done` row reads `not_queued`, 1918-1921), so the button promises to fetch them and does not, against
   decision 45 ("sends the listed cases that are not being fetched").
   - **Row 174 changes the button, not the endpoint.** On its branch, Collect These posts
     `POST /admin/data-load/collect {kind: "list"}` (round 3, decision 33), whose service requeues every target
     (`services/collect.py`, `requeue=True`) and counts `queued` and `already_waiting` from the states before the call.
     After row 174 merges (it is the next build), no portal screen calls `fetch-details`, but the endpoint stays in the
     API (round 1, decision 11) with the same false count. The server fix below is therefore still needed, and it is
     right whichever of rows 174 and 204 merges first.
2. **The 503 `search_timeout` test does not exercise the timeout.**
   `tests/db/test_data_collection_gaps.py:218-229` replaces the whole `data_load.gaps` with a function that raises
   `SearchTimeout`. The real path, `with_timeout` (`services/reporting_common.py:108-110`, `SET LOCAL
   statement_timeout`), the Postgres cancellation (`QUERY_CANCELED`) and its conversion in `_timed`
   (`data_load.py:1568-1574`) inside `gaps` (1997-2016), is not tested; only the router's mapping is.
3. **The role-based live checks of decision 4 are not on record.** The parent note's Verification 4 lists them (as a
   Central Operator: Retry and Check the Court Connection work, `/system` absent from the menu; as the Super
   Administrator: `/system#calls` shows the resets, e-mail and call log), but no run is recorded; the round 2 section of
   the pointer note records only the screen check.

Not covered: the Several Cases request and the requests list (row 174); the round 1 advisories (row 191); the owner's
browser check of the four rounds.

## Decisions
1. **`fetch-details` re-queues a case without details whatever its row's state, and reports only what is waiting.**
   - In `fetch_details`, `requeue=True` for every case it queues: a case without details (the person asked for its
     details; a `done` row there means the earlier fetch gave none), and a case with details only with `force`, as
     today. Cases with details and no `force` still answer `already_held` before any queue write.
   - The state comes from `enqueue`'s return value: `True` (the row is pending after the call) → `queued`; `False`
     (the row is running, so it is being fetched) → `queued` too, with `queue.status = running` in the item's queue
     block, which already says so. The audit row `data_load.details_requested` gains `already_running` (the count of
     the second kind) beside `queued`, so the record says how many fetches the request started.
   - The portal's note ("n cases sent") counts `state === "queued"` as today and is now true.
   - No court call at request time (the worker fetches, as today); request lane, priority 30 and `requested_by`
     unchanged. This matches what row 174's `collect` does for the same button.
   - Alternative: keep `requeue=held` and report a `done` row as `not_queued` (refused: the person pressed Collect These
     to fetch exactly those cases; reporting "not queued" would leave them stuck with no way to fetch from this tab).
2. **A test drives the real timeout through `gaps`.** The service test and the API test keep `gaps`, `_timed` and the
   router as they are and only make the database slow:
   - `data_load.with_timeout` is monkeypatched to `SET LOCAL statement_timeout = 50` (milliseconds; the setting's own
     floor is one second, `report_statement_timeout_seconds ge=1`, which would make the test sleep too long);
   - `data_load._gap_cases` is wrapped to run `SELECT pg_sleep(0.2)` and then the original reader.
   Postgres cancels the statement; `_timed` turns `QUERY_CANCELED` into `SearchTimeout`. The test then removes the
   patches and checks that the next request on a new session answers 200 (the cancelled transaction left nothing
   behind). The existing whole-function test is replaced, not kept, since it proves less.
3. **The live role checks are run by the owner and recorded in the pointer note.** The developer appends to
   `docs/design/data-collection-redesign-tabs.md` a section "Live role checks, round 2" with the two checks below as
   a list with an empty result line each; the owner (or the integrator signed in as each type with the owner's
   go-ahead) runs them at http://localhost:3000 after this row deploys, and the scribe writes the results and the date
   there and in the decisions log. No court call is needed except Check the Court Connection, which is one guarded,
   audited call (`napix.health_checked`) and runs only with the court-data switch on, as on the shared stack today.
   - **Central Operator** (a login of that type with no override): on Data Collection, Problems and Fixes, Retry one
     failed fetch and see it leave the list (audit `napix.queue_retry`); press Check
     the Court Connection and see the line change (audit `napix.health_checked`); the side menu has no System Health
     entry and `/system` answers the not-allowed page.
   - **Super Administrator:** `/system#calls` opens at Court Calls and shows Recent Resets, E-mail and the call log
     with More.

## Data
No table, no column, no migration. `schema.md` unchanged.

## Services
- `services/data_load.py` `fetch_details`: `requeue=True`; state and the audit counts from `enqueue`'s return
  (decision 1). Audit action unchanged (`data_load.details_requested`), one row per request.

## API
| Method and path | Function (`Permission`) | Change |
|---|---|---|
| `POST /admin/data-load/fetch-details` | `admin.data_load` (the router's `load_manager`) | a case without details is queued even when its dossier row is `done`; `state` is `queued` only when the row is waiting or running. Request and response shapes unchanged. |

No other endpoint changes; `GET /admin/data-load/gaps` (`admin.data_load` or the data-collection readers, as built) is
unchanged.

## Jobs
None. The worker fetches the re-queued rows in the request lane as for any request.

## Tests
pytest:
- `tests/db/test_api_data_load.py::test_fetch_details_requeues_a_done_row_of_a_case_without_details`: a case without
  details whose `dossier` row is `done` → the row is `pending` in the `request` lane at priority 30 with
  `requested_by` set, the item says `queued`, the audit row has `queued: 1`; the existing
  `test_fetch_details_queues_request_lane` (a held case without `force` is `already_held`; with `force` re-queued)
  and `test_fetch_details_makes_no_court_call` pass.
- `tests/db/test_api_data_load.py::test_fetch_details_reports_a_running_row`: a `running` row → `queued` with
  `queue.status == "running"`, the row unchanged, `already_running: 1` in the audit row.
- `tests/db/test_data_collection_gaps.py::test_gaps_cancelled_query_raises_search_timeout` (service, decision 2) and
  `::test_gaps_slow_query_answers_503_search_timeout` rewritten (API: 503, `detail.code == "search_timeout"`, no audit
  row written, the next request without the patches answers 200).

vitest: no frontend change in this row. The existing `frontend/src/components/data/data.test.tsx` test "Data Gaps: the
cases with their state and Collect These for the ones not being fetched" (line 300) passes as it is (or row 174's
replacement of it, if row 174 has merged first).

## Verification
1. `ruff check` clean; `pytest -q` green; `gen:api` no diff (no schema change).
2. No migration: `alembic heads` unchanged.
3. Dev (no court call at request time): on Problems and Fixes, Data Gaps, a case marked Not Yet Queued whose dossier
   row is `done`, Collect These (or, after row 174, `POST /admin/data-load/fetch-details` with its CNR) → the case
   reads Being Fetched on the next refresh, and `GET /audit?action=data_load.details_requested` shows `queued` equal to
   the cases that changed.
4. The owner's live role checks of decision 3, recorded in the pointer note.

## Open questions
None.
