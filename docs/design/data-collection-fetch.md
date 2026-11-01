# Design: Data Collection redesign, round 3 — Collect Now carried out at once

```
slug: data-collection-fetch
status: approved
author: architect
date: 2026-10-26
approved_by: owner on 2026-10-26, as round 3 of the revised data-collection-redesign
```

This is a pointer note. The whole design is **[data-collection-redesign.md](data-collection-redesign.md)**. The owner
reopened it on 26 Oct 2026 for four tabs and immediate manual requests (its history section); round 3 is re-approved
with it. This cycle (row 174, branch `feature/data-collection-fetch`) builds **decisions 22-33** of that note, and only
those, under its rules, API, tests and verification. It builds after round 2 (row 173) has merged.

- Build from those decisions and the API, Services, Tests and Verification lines marked for round 3.
- Record any deviation of this round in a "Deviations, round 3" section of **this** note.
- The first version of this round (day and list requests at priority 30 in the normal bands, audit actions
  `data_load.day_details_requested` / `data_load.list_details_requested`) is superseded by the "now" priorities,
  "use everything" with Stop, and `data_load.collect_requested` / `data_load.collect_stopped`.
- Round 4 (Update From the Court on the case, decisions 50-56) uses this round's engine and becomes a new row at
  approval.

## Deviations, round 3

**Round 3 (row 174, developer, 29 Oct 2026).** Where the note was silent, the smallest reasonable choice:

1. **Fetch Details' audit row** already carried `refs` (the case references as strings). It gains `queue_refs`
   (`[{kind, ref}]`, the dossier rows queued), which the requests reader uses; a Fetch Details row written before this
   change shows no items.
2. **A pasted line naming a held case with neither a CNR nor a printed number** reads **No Court Reference**
   (`no_reference`), a state the check's table did not list; it is not fetched (no identifier is made up).
3. **Nothing to fetch.** A collect request whose cases are all left out (every line not held, merged or with details,
   a day whose cases all have details) answers 400 `nothing_to_fetch` with the left-out lines and writes nothing. A
   One Case reference that is not held, merged or without a court reference is left out (`not_held`, `merged` with the
   target, `no_reference`). Collect requests check no case visibility, as Fetch Details does: Data Collection shows
   references only, and Open the Case applies the case page's own rule.
4. **A request's items** are its own rows (`after.refs`) and the `order_pdf` rows of its cases' orders in the request
   lane updated at or after the time it was asked (not only "at a now priority": a stopped request's rows moved to 30
   still count as its items). A case whose details were fresh (decision 25) has no dossier row of the request: its
   reference is kept in `after.fresh`, never in `after.refs`, so a dossier row left pending by other work (the load
   at 41-46, the weekly sweep at 50) is not the request's item and does not hold it open; its details read Done, and
   its cases (for the order PDFs it queued, the case count and the result) are found through `after.fresh`. The
   cases are those of its CNRs and, for a provisional row, of its printed number once resolved.
5. **Finished** ignores rows waiting for a retry (decision 32's rule): the result shows with "n will be tried again at
   about hh:mm".
6. **The "use everything" figures** (`CollectPlanOut`): this hour's calls are the lower of the calls and the window's
   remaining count, the rest after the next reset; the finish is reckoned at the court's hourly limit as seen (the
   highest remaining count of the last 24 hours plus one), capped by the client's per-minute rate. With the limit or
   the remaining count unknown there is no finish time (never a guess).
7. **The calls estimate** of a check: one dossier call per case (two for a case known only by its printed number), then
   the order PDFs a held case lacks, and for a case never fetched the average orders per case held.
8. **The existing buttons' answers** (`QueueStateOut`) gain `request_id`, the audit row, so their progress panel is
   keyed by it (decision 28); additive. **Search results** (`CaseSearchItemOut`) gain `dossier_fetched_at`, so One
   Case's Details column can say "Details Held 21 Oct"; additive.
9. **The pulse's `requests_active`** now counts the requests of the last 24 hours that have not finished (round 1,
   deviation 2, said round 3 would replace it).
10. **The worker's wake** (decision 24): the sleep is cut short for a "now" row except after a fault pause, a failed
    window probe or when the court's own limit is used up (remaining 0). Those waits hold for every row, and waking
    would only start a pass that claims nothing.
11. **One bulk request at a time** is checked under a transaction-scoped advisory lock. The bulk request using the
    allowance is the newest bulk `data_load.collect_requested` of the last 7 days that was not stopped and has a row
    waiting or fetching. Stop answers 404 for an unknown id and 409 `not_running` for a request that is not bulk, was
    stopped or has finished.
12. **"Waiting for the collector to start"** uses System Health's worker liveness (`ops_metrics.worker_alive_at`, the
    later of the latest pass and the latest claimed row) older than 2 minutes while a "now" row is runnable.
13. **`refetch-date --recheck`** (the evening recheck of held lists, a CLI and service path of `refetch_day`) also queues
    at `NOW_ONE`.
14. **Collect These** on Problems and Fixes (round 2, deviation 2) now checks the page's cases not being fetched, shows
    the "use everything" panel in a confirm and sends a Several Cases request.
15. **`CollectProgress`** is in the kit (`components/ui/CollectProgress.tsx`), presentational, for round 4's case page.
16. **Words.** The field reads "Cases, One Per Line" (the Title Case rule); a request is worded "One Case", "n Cases",
    "List of n Cases", "Cases Listed on 23 Oct 2026", "Cause Lists of 23 Oct 2026", "One Case Again", "One Order PDF
    Again", "Court Reference Lists" or "Details of n Cases".
17. **uicheck.** The checker never acts, so One Case's progress and result are drawn through the Requests card's Show
    Items (the request's `GET`), and Several Cases' check `POST /admin/data-load/collect/list/check` (it writes nothing
    and calls no court) is answered like the Start dialog's. The six states are in `uicheck.spec.ts`; the run itself is
    the integrator's (definition of done).
18. **A "now" priority ends with its run** (review fix). A finished queue row (`done`, `failed`, `skipped`) still at
    a "now" priority is revived by `queue.enqueue` as with `as_new`: it takes the caller's priority and lane, so the
    weekly sweep, a status batch or the masters schedule re-queues a collected case at its own priority (50, 30, 10)
    and lane, inside the reserves, and its order PDFs inherit nothing. A pending or running "now" row keeps its
    priority (the request still waits on it). `queue-retry-failed` brings a row failed at a "now" priority back at the
    request lane's normal priority (30).
19. **A request's items are bounded by its run** (review fix; refines deviation 4). A pending or running row is still
    the request's when its run had not finished by the time it was asked (`finished_at` before it), or when it is a
    retry of that run (attempts at least 1, at least 2 while running) still at a "now" priority or in the request lane
    with the asker. A row that finished after the request was asked and was queued again later (attempts back to 0)
    is later work and reads Done for the request (its own outcome is not kept apart from the later run's). So a
    weekly sweep never reopens a finished request, never makes it the bulk request using the allowance, and never
    causes a 409 `bulk_running`. Stop moves only the request's own open rows.
20. **A request's rows carry its id** (review round 4, the blocking finding; replaces the time rule of deviations 4
    and 19 for the spawned order PDFs and for the request's own rows). The request's id (`audit_log.id`) is chosen
    before its rows are written and stored on them in `fetch_queue.result.request_ids` (no new column, no migration);
    the audit row says `after.tagged`. `queue.enqueue` gives an inserted or revived row exactly the ids it is called
    with (none for system work, a claim's court refresh, a person's court search or a retry from Problems and Fixes),
    adds them to a pending or running row, and leaves a `done` row's; `queue.complete` keeps them next to the run's
    result and `queue.fail` leaves them, so a retry of the request's run is still its item. The order PDFs a claimed
    row spawns take the ids the row carries when it spawns (`queue.from_parent`). **The exact rule:** a request's items
    are its own rows (`after.refs`) and the request-lane `order_pdf` rows whose `request_ids` contain its id; an item is
    open while it is pending or running and still contains the id. So a claim's court refresh, Fetch Details, a
    person's court search or a One Case request on one of its cases never reopens a finished request, never makes it
    the bulk request using the allowance (`active_bulk`, 409 `bulk_running`, the Overview's bulk line, the court
    search's `napix_budget` sentence). An order PDF of the request that later work queues again leaves the request's
    items (its outcome is not kept apart from the later run's, as deviation 19 said for its own rows). Collect Now,
    the re-fetch and reference-list buttons and Fetch Details all tag their rows; a request record written before
    this change keeps deviation 19's rule for its own rows and has no spawned items. (Round 5: the spawned order PDFs
    are found through the request's own rows, not by lane, and Retry All clears the ids; deviation 27.)
21. **Stop reaches what a running row spawns** (advisory A2). Stop first moves the request's running rows at
    `NOW_BULK` to 30 (their run finishes), then its pending rows. A spawning row re-reads its priority under its row
    lock, so the order PDFs a dossier spawns after Stop take the request lane's normal turn (40), inside the reserves;
    Stop waits for a spawn in progress and then reaches the rows it wrote. The audit row adds `running` (the running
    rows moved); the answer's `moved` still counts the pending rows.
22. **A bulk request with only retries left still holds the allowance** (advisory A4; refines deviations 5 and 11).
    The card's `finished` still ignores rows waiting for a retry (the result shows with "tried again at about …"),
    but the bulk request using the allowance is one with any item open, a retry included: it stays "Using the Whole
    Allowance" (Stop available, a second bulk request 409), and its expected end is no earlier than the retry.
23. **A provisional reference matches its own establishment** (advisory A6): the per-case result of a
    `<est_code>|<printed number>` ref takes the cases with that number on that establishment only, and the case it
    resolved to (the CNR its dossier row found).
24. **More than 200 pasted lines are refused by the request model** (advisory A7): 422, before any line is read or
    de-duplicated (the portal already stops at 200 lines). The service keeps 400 `too_many` for other callers.
25. **The worker's wake check asks only for the kinds a pass can claim** (advisory A3): with the gateway off only
    cause-list days, so a "now" dossier or order PDF no longer wakes the worker every 2 s.
26. **The polled readers are bounded** (advisory A5; corrected in round 5, deviation 27): the items query is index
    lookups of the request's own rows and, through them, of its cases' orders and their `order_pdf` rows (the unique
    (kind, ref) index), then the id check, so its cost follows the request's size and not the queue's history; the
    pulse, the requests list and a request's detail run under the report statement timeout, as the Overview does.

**Round 5 (row 174, developer, 1 Nov 2026), the round-4 review's findings:**

27. **Retry All and the single Retry never reopen a finished request** (B1, A2). `retry_failed` (Retry All, `aslms
    queue-retry-failed`) clears `result.request_ids` as it revives failed rows, as the single Retry already did
    through `queue.enqueue`. The single Retry now brings a row failed at a "now" priority back at 30, as Retry All
    does, and every row stays in its own lane (before, it came back at its now priority in the daily lane). The other
    direct updates of `fetch_queue` only change priorities or put a lost run back (`requeue_stale`, the same run), so
    they keep the ids.
28. **A request's spawns are in the request lane** (A1). When a request takes over a row already running in the daily
    or load lane (its id and priority added to it), the order PDFs that run spawns go to the request lane with the
    id and priority (`queue.from_parent`), so they are the request's items, Stop reaches them and a "now" priority
    never sits in the daily or load lane.
29. **The spawned order PDFs are found through the request's own rows** (A3): its CNRs, its fresh cases and the CNRs
    its provisional dossier rows resolved to (`result.cnr`), their orders, each order's `order_pdf` row by the unique
    index, then the id; no scan of the request lane and no new index. `fetch_queue.result.request_ids` is described in
    `docs/schema/schema.md` with the other `fetch_queue` addenda (A4).
