# Design: Ownership refinements: fresh court data on claim, free local court answers, closing other recommendations, suggestion alerts

```
slug: ownership-refinements
status: approved
author: architect
date: 2026-10-21
approved_by: owner on 2026-10-21, with the architect's recommended answers (a)-(h); migration number by build order (0021)
```

## Context
This is backlog row 120. Section 6 of `docs/ASLMS_Process_Workflows.md` lists 16 behaviours of ASLMS as it works
today. On 21 Oct 2026 the owner chose to change five of them. These are owner decisions and this note does not reopen
them:

1. **On claim, fetch fresh court data** (section 6, point 1).
2. **A court search that the ASLMS database answers is free** (point 3).
3. **The ASLMS search shows only cases the user can open by default** (point 4).
4. **When one department claims, other departments' open recommendations close** (point 6).
5. **A suggestion from another department always raises an alert** (point 7).

The owner kept three behaviours as they are: no automatic court fallback in search (point 2), the State-wide unclaimed
pool (point 5), and a claim giving the whole department sight of the case.

What is in place (code read on 21 Oct 2026):
- **Claim** (`services/ownership.claim`) takes the case row lock and checks the state (`_claim_state`). It then writes
  a `case_ownership` row: `primary` when the case has no active primary, otherwise `watcher`. The claiming
  department's active recommendation becomes `claimed`. The claim writes the audit row `ownership.claim` and the event
  `claimed`, moves custody (primary only), may allot, and rescores linked cases. It makes no NAPIX call and queues
  nothing. A claimed case's court data is refreshed no sooner than any other case's (daily status batch, weekly sweep).
- **Transfer accept** (`decide_transfer`) does the same for the receiving department: it promotes the target's watcher
  row or inserts a primary row, writes `transfer.accept` and `transfer_decided`, and moves custody.
- **Other departments' recommendations stay open after a claim.** recommend-and-claim decision 5 says so, citing the
  plan: "if more than one claims it, one is recorded as the primary owner and the others as watchers". So a second
  department with an open recommendation can still claim and becomes a watcher. Those recommendations keep giving the
  `recommended` sight basis (`visibility.member_bases`, status `recommended`).
- **The engine** (`matching.apply_scores`) never re-opens a recommendation for a department that holds the case, has
  ever held it, or dismissed, suggested away or claimed it (`NEVER_AGAIN` plus `ever_owners`). It **does** still create
  recommendations for *other* departments on a claimed case.
- **Recommendation statuses** (`domain/ownership.RecommendationStatus`, Postgres enum `recommendation_status`) are
  `recommended`, `claimed`, `dismissed`, `suggested_elsewhere` and `expired`. `expired` means "the engine score fell
  below the band, or the case was merged". It is not in `NEVER_AGAIN`, so the engine may re-open such a row.
- **Alerts for recommendations** (`services/alerts._handle_event`) are raised only for a `recommendation_made` event
  whose recommendation is still open, band `high`, on a pending case. A human suggestion (`suggest`) creates a
  recommendation of origin `suggestion` and band `high` only when the target's engine score is already strong.
  - So a suggestion usually arrives as band `medium` and raises no alert.
  - When the target already has an open recommendation, `suggest` creates none and emits no `recommendation_made`
    event at all.
  - The event `suggested_elsewhere` is always emitted, but the alert scan does not read it.
- **Ownership notices to people who cannot see the case** already exist: `recipients.NAMED_RECIPIENT_EVENTS`
  (`case_taken_over`, `transfer_requested`, `transfer_decided`) are shown in the recipient's list with
  `case_visible: false` (`alerts.notification_visible_condition`).
- **Court search** (`POST /cases/search-court`, router `api/routers/cases.py`) calls `court_search.guard` before
  anything else. The guard checks the switch, the quota floor and the per-user limit of 30 audit rows
  `case.search_court` / `case.fetch_court` in the last hour. It then opens the integration client (`_with_napix`,
  which raises `IntegrationError` when `NAPIX_ENABLED` is off) and runs `search_court`.
  - `search_court` answers locally, with no call, when the case is held with its dossier: by CNR (`_search_cnr`), by
    case number (`_local_by_number`) and by filing number (`_local_by_filing`).
  - Such an answer is still refused when the switch is off or the floor is reached, and its audit row (`calls: 0`)
    counts towards the 30.
- **The Search page** (`frontend/src/components/search/Search.tsx`) sends `visible_only=true` only when the "Only cases
  I can open" box is ticked. The box is unticked by default. The API default (`GET /cases/search`) is `false`.
- **The queue** (`services/queue.enqueue`) already supports a person's request: lane `request`, priority 30
  (`PRIORITY["request"]`) and `requested_by`. `napix_admin.refetch_case` uses exactly that for `dossier` rows. With the
  master switch off, `run_queue_once` claims only `causelist_day` rows, so `dossier` rows wait as `pending` and are
  never lost.

Not covered here:
- The other eleven points of section 6. Points 8 to 16 and the technical gaps are left for later backlog rows if the
  owner wants them.
- Updating `docs/ASLMS_Process_Workflows.md` and the decisions log. That is the scribe's work after the build.
- No live NAPIX call is part of the build or the tests. Tests use the scripted gateway only, and `NAPIX_ENABLED` is
  never turned on in code or tests.

## Decisions

**A. Fresh court data on claim (owner point 1)**

1. **When a refresh is queued.** After a successful claim (primary or watcher) and after an accepted transfer, the
   service checks the case. It queues a court refresh when the case has no full court record
   (`last_full_refresh_at IS NULL`) or when that record is older than 24 hours (`last_full_refresh_at < now() - 24 h`).
   Otherwise nothing is queued. The 24 hours is a module constant (`CLAIM_REFRESH_AFTER`), not a setting: the owner
   fixed it, and a setting would need a screen.
   *Alternatives:* refresh primary claims only (rejected: a watcher claim is also "a case is claimed", and the 24-hour
   rule keeps it cheap); also refresh when `dossier_stale` is set (rejected: the tracking refresh already queues those).
2. **How it is queued.** One `dossier` row through `queue.enqueue`:
   - ref from `napix_admin.dossier_ref`: the CNR, or `<est_code>|<case number as printed>` for a provisional case,
     which the runner resolves through Search by Case Number, so no identifier is invented;
   - priority `queue.PRIORITY["request"]` (30), lane `request`, `requeue=True`, so a `done` row from an earlier fetch
     is revived;
   - `requested_by` is the claiming login (the accepting login for a transfer).

   It goes only through the queue and the worker. The request makes no NAPIX call and opens no integration client.
   The worker fetches the row through `aslms.integration.napix` as it fetches every `dossier` row, and the call is
   logged against the person (`napix-window` decision 9).
   - With the master switch off, the row waits as `pending` until the switch is on. It is never failed or dropped
     while it waits.
   - An existing `pending` row (for example from the weekly sweep at priority 50) takes the better priority and the
     `request` lane, as `enqueue` already does.
   - A `running` row is left alone: it is being fetched now.
3. **The claim never waits for or fails on the refresh.** The enqueue runs inside a savepoint
   (`session.begin_nested()`) after the ownership rows are written. Any exception is caught and logged (case `ref_no`
   and exception class only), and the claim goes on.
   - A case with neither a CNR nor a case number cannot be fetched (`NoReference`). The claim still succeeds.
   - The outcome is recorded as `court_refresh` in the claim's audit row, or in the transfer's for an accepted
     transfer. It is one of `queued`, `in_progress`, `fresh`, `no_reference` or `failed`. No separate audit row is
     written: the refresh is part of the claim.
   - No API shape changes. The case page already shows when the court data was last fetched.
   - The worker's claim of a queue row commits before its NAPIX call (`runner.py`, `queue.claim` then
     `s.commit()`), so the upsert never waits behind a running fetch.

**B. A court search answered from the ASLMS database is free (owner point 3)**

4. **Answer locally first, guard only when a call is needed.** A new service step, `court_search.answer_locally`,
   runs before the guard for the kinds `cnr`, `case_number` and `filing`. It reads only. It validates the input exactly
   as today, so bad input answers 400 even when NAPIX is off. It then applies today's local rules unchanged:
   - CNR: the case held with a dossier;
   - case number: `_local_by_number`;
   - filing number: `_local_by_filing`.

   When it finds the case, the router answers at once with `source: "local"` and `calls: 0`. It makes no guard check
   and opens no integration client, so the answer works with the switch off, below the quota floor and over the
   per-user limit.

   When it finds nothing (or for `party` / `advocate`, which always need the court), the router runs
   `court_search.guard` and the NAPIX path as today. `search_court` keeps its own local short cuts, so a case that
   arrives between the two reads is still answered without a call, and the data-load console's `force` path is
   unchanged.
   *Alternative:* move the guard inside `search_court` after the local branch (rejected: the router would still open
   the client first, and `NapixClient.from_settings` raises when the switch is off).
5. **Still audited.** A local answer writes one `case.search_court` audit row with
   `{kind, request, calls: 0, results: 1, created: 0, outcome: "ok", source: "local"}` and the case's `case_id`. The
   NAPIX path's row gains `source` (`court` or `local`) too.
6. **How the per-user count leaves out zero-call rows.** `user_searches_last_hour` (and the oldest-row time it returns
   for `Retry-After`) counts a `case.search_court` / `case.fetch_court` row unless its `after.calls` is the number
   0. In SQL this is `coalesce(after->>'calls', '') <> '0'`, served by the existing index
   `ix_audit_log_actor_created`.
   - The rule is "zero calls are free", whatever the path, so it also leaves out older local answers and any failure
     that ended before a call.
   - A row without `calls` (none exist today) still counts, which is the safe side.

   *Alternative:* exclude by `after.source = 'local'` (rejected: rows written before this change have no `source`).
7. **Fetch from court checks "already fetched" before the guard.** `POST /cases/{ref}/fetch-court` on a case that
   already has its dossier answers 409 `already_fetched` before the guard runs (today the guard runs first, so it can
   answer 503 `napix_off`). The same principle: the guard runs only when a call is needed. The data-load console's
   `fetch` is unchanged: without `force` it already answers from the database before any guard, and with `force` it
   always calls.

**C. Search shows only cases the user can open by default (owner point 4)**

8. **Portal default ticked, API default unchanged.** On the Search page, "Only cases I can open" is ticked unless the
   address says `visible_only=false`.
   - Unticking writes `visible_only=false`. Ticking removes the key.
   - The page sends `visible_only=true` to `GET /cases/search` unless the address says `false`.
   - The filter bar's check control gains a `defaultOn` option for this. With it, the chip shows only the non-default
     state ("Also cases I cannot open"), and removing the chip restores the default.
   - Old links with `visible_only=true` still read as ticked.

   The server default of `GET /cases/search` stays `false`. It is the documented API contract used by tests and by
   other callers, the server already enforces what each item reveals (`visible`, public summary only), and the
   owner's choice is about what the page shows first.
   *Alternative:* change the API default to `true` (rejected: a contract change with no gain in safety, since
   visibility is enforced either way).

**D. Other departments' recommendations close on claim (owner point 6)**

9. **A new status, `claimed_elsewhere`.** A primary claim (from the pool or from a recommendation) sets every other
   department's open recommendation for the case to `claimed_elsewhere`, in the same transaction and under the same
   case row lock. This covers suggestions made before the claim. Each closed row gets `acted_at = now()` and
   `reason = "claimed by <DEPT>"`.
   - `claimed_elsewhere` joins `NEVER_AGAIN` in `matching.py`.
   - A watcher claim closes nothing, because a primary already exists.
   - An accepted transfer closes nothing either. The only recommendations open on a claimed case are suggestions
     made after the claim (decision 12). They stay open across a transfer, because they are human invitations.

   *Alternatives:* reuse `expired` (rejected: it means "score fell or case merged", it is not in `NEVER_AGAIN`, and
   the sweep and the screens could not tell the reason); reuse `claimed` (rejected: that status means "this department
   claimed it"). A new enum value needs a migration (decision 16).
10. **Event, audit, alert.**
    - **Event:** one new event `recommendation_closed` per closed row. It is scoped and not on the tracking card.
      Payload: `{recommendation_id, office_code (the closed department), claimed_by_office_code, ownership_id, origin,
      band}`. Dedupe key: `recommendation_closed:<recommendation id>`. Actor: the claimer.
    - **Audit:** the claim's `ownership.claim` audit row gains
      `closed_recommendations: [{recommendation_id, office_code}]`. The closure is part of the user's claim, so it is
      in that row and not in a separate one.
    - **Alert:** the alert scan raises one `ownership` alert per closed row, addressed to the closed department.
      - Data: `event: "recommendation_closed"`, `claimed_by_office_code`, `actor_name`.
      - Recipients: that department's logins holding `cases.claim` (`Resolver.office_users(..., CASES_CLAIM)`), minus
        the claimer.
      - Severity: the `ownership` default (`normal`).
      - Text: title "Claimed by <DEPT>: <case>"; body "<DEPT> claimed this case; your department's recommendation is
        closed."
      - The closed department can no longer open the case. So `recommendation_closed` joins
        `NAMED_RECIPIENT_EVENTS`, and the notice is shown in their list with `case_visible: false`, as a transfer
        decision already is.
      - When the scan raises the notice, it also closes that department's open `recommendation` alert for the same
        recommendation (`done`, reason `recommendation_claimed_elsewhere`), so the department need not wait for the
        sweep. The sweep's closure stays as the fallback.
      - Channels follow the existing rule: in-app always, e-mail only as the recipient's preferences say.
11. **Sight is lost with the recommendation.** The `recommended` basis reads only status `recommended`, so a closed
    department loses sight of the case with no visibility change.
    - A stale Claim, Dismiss or Suggest pressed by that department answers **409 `claimed_elsewhere`** ("<DEPT> claimed
      this case; your department's recommendation is closed"), not today's 404 "no such case". The service checks
      whether the department's latest recommendation for the case is `claimed_elsewhere`.
    - This tells them no more than the alert already does, and it explains the refusal.
12. **What changes for watchers.** This is a **deviation** from the plan, an owner decision of 21 Oct 2026. The plan
    says "if more than one claims it, one is recorded as the primary owner and the others as watchers". Parallel
    recommendations no longer lead to watchers: the other departments' recommendations close at the first claim.
    - The explicit routes to a watcher row are unchanged:
      - (a) the owning department, or a watcher, suggests another department after the claim. That department gets
        an open `suggestion` recommendation, alerted by decision 14. Its claim makes it a watcher (`_claim_state` and
        the `watcher` branch of `claim` are unchanged).
      - (b) a transfer with `stay_as_watcher`.
    - Stop watching is unchanged.
    - The inbox's Recommended tab shows a case that another department owns only for such a post-claim suggestion, with
      the owner beside it as today.
    - recommend-and-claim decision 5's sentence "Recommendations stay open when another department claims the case" is
      replaced by this decision.
13. **The engine never recommends a claimed case.** In `apply_scores`, a case that has ever had a primary owner
    (`ownership.ever_owned`, true for every claimed case, since a claimed case never returns to the pool) gets no new
    recommendation for any department.
    - The engine changes no band on any open row of such a case either, so no `recommendation_made` event and no
      `high` alert are raised for a claimed case.
    - `case_office_scores` are still written: the "why suggested" signals and the suggest dialog's score read them.
    - Engine expiry of open engine rows below the band works as before.
    - Human suggestions are untouched.
    - Rescoring of *linked* cases after a claim is unchanged: those cases are usually unclaimed, and the linked-case
      signal is how they lean towards the owner.
14. **Cases claimed before this change.** A one-off command closes the open recommendations of other departments on
    cases that already have an active primary owner: `aslms close-claimed-recommendations`, a dry run by default, with
    `--apply` to write.
    - It sets `claimed_elsewhere` with `reason "claimed by <DEPT> (closed on <date>)"`.
    - It emits `recommendation_closed` events with `backfill: true`. The alert scan raises nothing for those, so old
      claims cause no burst of notices.
    - It writes one summary audit row `recommendation.close_claimed_backfill` (system actor `ownership-backfill`,
      `{closed, cases, by_department}`).
    - It is idempotent: a second run closes 0.
    - The integrator runs it once after the merge (Verification).

    *Alternative:* an UPDATE inside migration 0021 (rejected: no events, no audit row, not visible to anyone).

**E. A suggestion always raises an alert (owner point 7)**

15. **Driven by the `suggested_elsewhere` event, not by `recommendation_made`.**
    - `suggest` adds `target_recommendation_id` to its `suggested_elsewhere` payload.
    - The scan reads `suggested_elsewhere` and raises a `recommendation` alert for the target's open recommendation:
      - whatever its band or origin, and also when the target already had an open engine recommendation (where no new
        row and no `recommendation_made` event exist);
      - for a pending or disposed case alike, since a person chose to send it.
    - Alert details:
      - key: `recommendation:<rec id>:suggested:<event id>`, so each suggestion is one alert;
      - recipients: the target department's `cases.claim` holders (`Resolver.for_recommendation`), minus the
        suggesting user, filtered by case access (they now have the `recommended` basis);
      - severity: `high` when the next hearing is within the look-ahead, else `normal`, as for engine recommendations;
      - data: `{recommendation_id, office_code, from_office_code, origin: "suggestion", score, band}`;
      - text: title "Suggested for <TO>: <case>"; body "<FROM or 'Another office'> suggests this case belongs to your
        department; claim or dismiss it in the inbox." The suggestion's reason is not put in the alert or the e-mail
        (ownership alerts already leave `reason` out), because the inbox shows it.
    - A `recommendation_made` event of origin `suggestion` is now skipped by the scan, so a strong suggestion raises
      one alert, not two.
    - `suggested_elsewhere` events pass the scan's "owned case" filter, as `recommendation_made` already does, because
      a suggestion is usually made on an unclaimed case.
    - Engine recommendations keep today's rule: `high` band only.
    - The sweep closes these alerts when the recommendation is decided, as it does today (it reads
      `data.recommendation_id`).

**F. Migration**

16. **Migration 0021 is needed.** It adds the enum value `recommendation_status` + `claimed_elsewhere` and the
    reference row `ref_event_type` `recommendation_closed`. No table or column is added. No new alert kind is needed:
    the notices use `ownership` and `recommendation`. The head is 0020, and applied migrations are not edited.
    `schema.md` is updated first (Data).

## Data

Paragraphs for `docs/schema/schema.md` (Group 5 row `recommendations`, Group 0 row `ref_event_type`):

- **`recommendations`** (transaction class; unchanged keys and FKs: `case_id` → cases RESTRICT, `office_id` and
  `suggested_office_id` → offices RESTRICT; actor snapshot and `created_at` / `updated_at`; never deleted).
  - `status` gains `claimed_elsewhere` (enum `recommendation_status`, migration 0021). It is set on every other
    department's open recommendation when a department claims the case as primary owner, with `acted_at` and
    `reason = "claimed by <DEPT>"`. It is also set once, by `aslms close-claimed-recommendations`, on cases claimed
    before 21 Oct 2026.
  - The actor snapshot keeps the row's creator. The claimer is recorded in the claim's `ownership.claim` audit row
    (`closed_recommendations`).
  - The engine never re-opens a `claimed_elsewhere` row, and it never recommends a case that has ever had a primary
    owner (design `ownership-refinements`, decisions 9 and 13).
  - The only open recommendations on a claimed case are human suggestions made after the claim.
  - The partial unique index `ix_recommendations_active` is unchanged.
  - Replace "`expired` is set by the engine when …" with: "`expired` is set by the engine when an engine score drops
    below the current `threshold_possible` or the case is merged; `claimed_elsewhere` when another department claims
    the case."
- **`ref_event_type`** gains `recommendation_closed` ("Recommendation closed", `timeline_label` the same, not on the
  tracking card, `sort_order` 370, active), by migration 0021 and the seed (`EventType.RECOMMENDATION_CLOSED`).
  - Payload: `{recommendation_id, office_code, claimed_by_office_code, ownership_id, origin, band}`, plus
    `backfill: true` from the one-off command.
  - Shown on the timeline like `dismissed` (`case_detail.DEPARTMENT_EVENTS`): to the named department and to
    State-wide readers.

**Migration `0021_ownership_refinements`**:
1. Autocommit block, as 0014, 0017 and 0018 did: `ALTER TYPE recommendation_status ADD VALUE IF NOT EXISTS
   'claimed_elsewhere'`. The value is not used inside the migration.
2. `INSERT INTO ref_event_type (code, label, timeline_label, is_tracking_card, sort_order, is_active) VALUES
   ('recommendation_closed', 'Recommendation closed', 'Recommendation closed', false, 370, true) ON CONFLICT (code) DO
   NOTHING`. The values are hard-coded, with no application import, as in 0016 and 0018.
3. No grant change: `aslms_app` already has SELECT / INSERT / UPDATE on `recommendations` and INSERT on `events`.
4. Downgrade:
   - It refuses while any `recommendations` row has status `claimed_elsewhere`, because that is legal-record history
     the old code cannot read.
   - Otherwise it deletes the `ref_event_type` row if no event uses it.
   - PostgreSQL cannot drop an enum value, so the value stays (harmless, unused).

No reference codes are added to other `ref_*` sets. No new table, so no table class, key or cascade decision is
needed.

## Services

**`services/ownership.py`**
- `CLAIM_REFRESH_AFTER = timedelta(hours=24)`.
- `_queue_court_refresh(session, case, requester: User | Member) -> str`, used by decisions 1 to 3:
  - It returns `fresh` when `last_full_refresh_at` is within `CLAIM_REFRESH_AFTER`.
  - Otherwise, inside `session.begin_nested()`:
    `ref = napix_admin.dossier_ref(session, case)` (import inside the function if an import cycle appears), then
    `queue.enqueue(session, FetchKind.DOSSIER, ref, queue.PRIORITY["request"], requeue=True, lane=FetchLane.REQUEST,
    requested_by=napix_window.user_id_of(requester))`.
  - It returns `queued` when the row is pending afterwards and `in_progress` when the row is running.
  - It returns `no_reference` on `NoReference`, and `failed` on any other exception, after logging `case_ref` and the
    exception class.
  - It never raises.
- `claim(...)`, after `_flush_unique` and marking its own recommendation `claimed`:
  - When the new row is `primary`: `_close_other_recommendations(session, case, dept)` sets every open recommendation
    of another office to `claimed_elsewhere` (`acted_at`, `reason`) and returns the closed rows.
  - Then `court_refresh = _queue_court_refresh(session, case, actor_user)`.
  - The audit row `ownership.claim` `after` gains `closed_recommendations` and `court_refresh`.
  - After the `claimed` event, one `recommendation_closed` event per closed row (scoped, dedupe
    `recommendation_closed:<id>`, actor the claimer).
  - Custody, allot and linked rescore follow as today.
- `decide_transfer(..., accept=True)`: `court_refresh = _queue_court_refresh(session, case, actor_user)`, put in the
  `transfer.accept` audit `after`. It closes no recommendations.
- `_claim_state`, `_check_dismiss`, `_check_suggest_from` and `_check_suggest`: when the department has no open
  recommendation and its latest recommendation for the case is `claimed_elsewhere`, they raise
  `OwnershipConflict("claimed_elsewhere", "<DEPT> claimed this case; your department's recommendation is closed")`
  (409). The owner's code comes from the case's active primary row.
- `suggest(...)`: the `suggested_elsewhere` event payload gains `target_recommendation_id`. Nothing else changes, and
  post-claim suggestions stay allowed for the owning department and watchers (decision 12).
- `close_claimed_backfill(session, *, apply: bool, now=None) -> dict`, used by decision 14:
  - It finds open recommendations whose case has an active primary row of another office.
  - With `apply`, it closes them as `claimed_elsewhere` and emits `recommendation_closed` with `backfill: true`
    (system actor `ownership-backfill`).
  - It writes one audit row `recommendation.close_claimed_backfill` with `{closed, cases, by_department}`.
  - It returns the same counts in dry-run mode, where it writes nothing.

**`services/matching.py`**
- `NEVER_AGAIN` gains `RecommendationStatus.CLAIMED_ELSEWHERE`.
- `apply_scores`: once the scores are written, it computes `claimed = ownership.ever_owned(session, case)`. Import
  locally or use the same `exists` on `case_ownership` with role `primary`, since `ownership` imports `matching`.
  When `claimed` is true, it creates no recommendation and changes no band or score of open rows. The expiry loop runs
  as today. The module docstring says so.

**`services/court_search.py`**
- `answer_locally(session, actor, user, request) -> CourtSearchResult | None`, used by decisions 4 and 5:
  - For `cnr`, `case_number` and `filing` it validates as today (`CourtSearchError`), applies the local rules and,
    when held, writes the `case.search_court` audit row (`calls: 0`, `source: "local"`) with `write_audit` (no
    recorder) and returns the result.
  - For `party` and `advocate` it returns None.
  - An unknown kind raises `CourtSearchError`.
  - Factor the three local reads out of `_search_cnr`, `_search_case_number` and `_search_filing` into `_local_cnr`,
    `_local_number` and `_local_filing`, shared by both paths.
- `search_court`'s `done()` adds `source` to the audit `after`.
- `user_searches_last_hour` adds the predicate `coalesce(AuditLog.after["calls"].astext, "") != "0"` (decision 6).
  The guard is otherwise unchanged.

**`services/alerts.py`, `services/recipients.py`, `services/alert_rules.py`**
- `HANDLED_EVENTS` gains `SUGGESTED_ELSEWHERE` and `RECOMMENDATION_CLOSED`. The scan's "owned" exemption and the
  `skipped_unowned` count treat `SUGGESTED_ELSEWHERE` like `RECOMMENDATION_MADE`.
- `RECOMMENDATION_MADE`: skip origin `suggestion` (counted `skipped_other`). The rest is unchanged.
- `SUGGESTED_ELSEWHERE`: decision 15. Skip when `target_recommendation_id` is missing (older events), or when the
  recommendation is no longer open or the case is merged.
- `RECOMMENDATION_CLOSED`: decision 10. Skip when `backfill` is true.
  - The office comes from `_ownership_office` (new branch: `office_code`).
  - Recipients come from `Resolver.for_ownership_event("recommendation_closed", p)`, a new branch returning
    `office_users(<office_code>, CASES_CLAIM)`, finalised with `require_case_access=False` and the claimer excluded.
  - After raising, close the open `recommendation` alerts whose `data.recommendation_id` is the closed row (`done`,
    `recommendation_claimed_elsewhere`).
- `recipients.NAMED_RECIPIENT_EVENTS` gains `"recommendation_closed"`.
- `alert_rules.render`:
  - `OWNERSHIP` sub-event `recommendation_closed`: title "Claimed by {claimed_by_office_code}: {label}", body as in
    decision 10.
  - `RECOMMENDATION` with `origin == "suggestion"`: title "Suggested for {office_code}: {label}", body as in
    decision 15.
  - Engine recommendations keep "Strong match for …".

**`services/case_detail.py`**: `DEPARTMENT_EVENTS` gains `RECOMMENDATION_CLOSED`.

**`domain/ownership.py`, `domain/reference.py`, `services/seed.py`**: `RecommendationStatus.CLAIMED_ELSEWHERE =
"claimed_elsewhere"`; `EventType.RECOMMENDATION_CLOSED = "recommendation_closed"` (appended last, seed sort 370, not in
`TRACKING_CARD_EVENTS`).

**CLI**: `aslms close-claimed-recommendations [--apply]` (`cli/matching.py`, registered in `cli/main.py`) prints the
counts and commits only with `--apply`.

**Frontend**
- `components/filters/FilterBar.tsx`: a check control may be `defaultOn`. It is ticked unless the value is `"false"`.
  Unticking writes `"false"` and ticking removes the key. Its chip shows the off state with its own `offLabel`.
- `components/search/Search.tsx`: `visible_only` as `defaultOn` with
  `offLabel: T.search.alsoNotVisible ("Also cases I cannot open")`. It sends `visible_only: true` unless
  `params.visible_only === "false"`.
- `components/search/CourtSearch.tsx`: when `source === "local"`, a notice "Found in the ASLMS database; the court was
  not asked."
- `lib/timeline.ts`: detail for `recommendation_closed`: "<office_code> — claimed by <claimed_by_office_code>".
- `components/case/OwnershipCard.tsx`: recommendation status labels (`T.case.recommendationStatuses`, including
  `claimed_elsewhere`: "Closed: claimed by another department") in place of the raw code.
- Claim, Dismiss and Suggest dialogs: the 409 `claimed_elsewhere` message is shown as returned (existing error
  banner); the inbox list is refetched.
- `lib/api/schema.d.ts` regenerated.

## API

No new endpoint. Changes to existing ones:

| Method and path | Function (`Permission`) | Change |
|---|---|---|
| `POST /cases/{ref}/claim` | `cases.claim` (+ `cases.allot` when allotting) | Unchanged shapes (201 `OwnershipOut`). A primary claim closes other departments' open recommendations and may queue a court refresh (decisions 1 to 3, 9 and 10). New 409 `claimed_elsewhere` when the caller's department's recommendation was closed by another department's claim. |
| `POST /cases/{ref}/dismiss` | `cases.dismiss` | New 409 `claimed_elsewhere` (decision 11); otherwise unchanged. |
| `POST /cases/{ref}/suggest` | `cases.suggest_elsewhere` | New 409 `claimed_elsewhere` for a closed department; the event payload gains `target_recommendation_id`; the target is alerted whatever the band (decision 15). |
| `POST /transfers/{trf}/accept` | `cases.transfer_decide` | Unchanged shapes; may queue a court refresh (decision 1). |
| `POST /cases/search-court` | `cases.search_court` | CNR, case-number and filing searches the database answers return `source: "local"`, `calls: 0` before any guard: not refused by `napix_off`, `napix_budget` or `search_limit`, and not counted. Bad input answers 400 before the guard. Otherwise unchanged (decisions 4 to 6). |
| `POST /cases/{ref}/fetch-court` | `cases.search_court` | 409 `already_fetched` before the guard (decision 7). |
| `GET /cases/search` | `cases.view_scope` (unchanged) | No change; `visible_only` still defaults to `false`; the portal sends `true` by default (decision 8). |
| `GET /alerts`, `/alerts/counts`, `/alerts/{ref}` | `alerts.view` (unchanged) | A `recommendation_closed` ownership notice is listed for its named recipients with `case_visible: false`, as transfer notices are. |

Visibility: unchanged rules. A closed department loses the `recommended` basis by the status change. Every list and
detail still filters on the server (`visibility.visible_case_condition`). The `claimed_elsewhere` 409 names only the
claiming department's code, which the alert already gives.

## Jobs
- **Queued work:** `dossier` rows from claims and accepted transfers.
  - kind `dossier`, ref `<CNR>` or `<est_code>|<case number as printed>`, priority 30, lane `request`,
    `requested_by` the claiming or accepting login, `requeue=True`;
  - picked up by the worker's normal queue run through the integration layer;
  - while `NAPIX_ENABLED` is off, the rows wait as `pending`.
- **No new scheduled job.** The existing event scan (`alerts_events`) raises the two new notices. The existing date
  sweep keeps its recommendation closure.
- **One-off:** `aslms close-claimed-recommendations --apply`, run once by the integrator after the merge.

## Tests

Database tests (`backend/tests/db/`, the scripted gateway only, `NAPIX_ENABLED` never set; new file
`test_ownership_refinements.py` unless named otherwise):

- **Court refresh on claim**
  - `test_claim_of_a_case_without_a_dossier_queues_a_request_dossier`: one `fetch_queue` row `dossier/<CNR>`,
    `pending`, lane `request`, priority 30, `requested_by` the claimer; audit `court_refresh = "queued"`; no NAPIX
    client opened (the app's `napix_factory` is not called).
  - `test_claim_of_a_case_refreshed_within_24_hours_queues_nothing`: `court_refresh = "fresh"`.
  - `test_claim_revives_a_done_dossier_row_older_than_24_hours`: attempts reset to 0.
  - `test_claim_leaves_a_running_dossier_row_alone`: `in_progress`.
  - `test_claim_of_a_provisional_case_queues_by_case_number`: ref `<est>|<number>`. A case with neither CNR nor
    number is claimed and gives `no_reference`.
  - `test_a_failing_enqueue_never_fails_the_claim`: monkeypatched `queue.enqueue` raises; the ownership row, the audit
    row with `failed` and the event exist.
  - `test_queued_refresh_waits_while_the_switch_is_off`: `run_queue_once` with the switch off leaves the row `pending`
    with 0 attempts.
  - `test_accepted_transfer_queues_a_refresh_for_the_accepter`; `test_a_declined_transfer_queues_nothing`.
  - `test_a_watcher_claim_also_queues_a_stale_refresh`.
- **Closing on claim**
  - `test_primary_claim_closes_other_departments_open_recommendations`: B's engine recommendation and C's
    pre-claim suggestion become `claimed_elsewhere` with `acted_at` and reason; A's becomes `claimed`; two
    `recommendation_closed` events; the claim audit lists both.
  - `test_claim_from_the_pool_also_closes_other_recommendations`.
  - `test_closed_department_loses_sight`: `can_view_case` false for B's head; `GET /cases/{ref}` 404; not in B's
    Recommended inbox or dashboard count.
  - `test_stale_claim_dismiss_suggest_answer_409_claimed_elsewhere`.
  - `test_watcher_claim_and_transfer_accept_close_no_post_claim_suggestion`.
  - `test_owner_suggestion_after_claim_still_makes_a_watcher`: the explicit watch route works.
  - `test_two_concurrent_claims_leave_one_primary_and_the_other_409`: two sessions, the row lock.
- **Engine** (`test_matching.py`)
  - `test_engine_never_recommends_a_claimed_case`: a high score for another department creates no row and no event.
  - `test_engine_changes_no_band_on_a_claimed_case`.
  - `test_scores_are_still_written_for_a_claimed_case`.
  - `test_claimed_elsewhere_is_never_reopened`.
- **Alerts** (`test_alerts_generate.py`, `test_alert_recipients.py`)
  - `test_recommendation_closed_notifies_the_closed_departments_claimers`: `ownership` alert, data event, recipients
    `cases.claim` holders of B minus the claimer; listed for them with `case_visible: false`; title "Claimed by A".
  - `test_recommendation_closed_closes_the_open_recommendation_alert`.
  - `test_backfill_events_raise_no_alert`.
  - `test_medium_band_suggestion_alerts_the_target`.
  - `test_strong_suggestion_raises_exactly_one_alert`.
  - `test_suggestion_to_an_already_recommended_department_still_alerts`.
  - `test_suggestion_on_an_unclaimed_case_passes_the_owned_filter`.
  - `test_suggester_is_not_a_recipient`.
  - `test_engine_medium_recommendation_still_raises_none`.
- **Court search** (`test_court_search.py`)
  - `test_held_cnr_answers_locally_with_the_switch_off`: 200, `source: "local"`, `calls: 0`, no client opened, audit
    `calls: 0, source: "local"`.
  - `test_held_case_number_and_filing_answer_locally_with_the_switch_off`.
  - `test_local_answer_ignores_the_quota_floor`.
  - `test_local_answer_ignores_and_does_not_use_the_hourly_limit`: 30 court rows, then a local answer is 200; 30
    local answers, then a court search is allowed.
  - `test_unheld_cnr_with_the_switch_off_still_answers_503`.
  - `test_bad_cnr_answers_400_before_the_guard`.
  - `test_fetch_court_on_a_fetched_case_answers_409_with_the_switch_off`.
  - `test_switch_off_answers_503_without_a_call` updated to use a CNR that is not held.
- **Backfill**
  - `test_close_claimed_backfill_dry_run_writes_nothing`.
  - `test_close_claimed_backfill_apply_closes_emits_and_audits_once`; a second run closes 0.
- **Migration** (the migration test pattern of 0018)
  - `test_0021_adds_the_status_and_event_type`.
  - `test_0021_downgrade_refused_with_claimed_elsewhere_rows`.
  - `test_ref_tables` stays green: every `EventType` has a row after the seed.

Frontend (`vitest`):
- `search.test.tsx`
  - `"only cases I can open" is ticked by default and sent`.
  - `unticking writes visible_only=false and sends no filter`.
  - `the chip shows "Also cases I cannot open" and removing it restores the default`.
  - `an old link with visible_only=true stays ticked`.
- `filters.test.ts`: the `defaultOn` check control.
- `timeline.test.ts`: `recommendation_closed` detail.
- `CourtSearch`: the local-answer notice.
- `OwnershipCard`: the `claimed_elsewhere` label.

## Verification
1. `ruff check` clean; `pytest -q` green; `npm test` and `npm run build` in `frontend/` green.
2. `alembic upgrade head` on the development database. `alembic current` shows `0021`.
   `SELECT enum_range(NULL::recommendation_status)` includes `claimed_elsewhere`. `ref_event_type` has
   `recommendation_closed`.
3. `aslms close-claimed-recommendations` (dry run): record the counts in the report. Then run `--apply`. A second dry
   run reports 0. One `recommendation.close_claimed_backfill` audit row exists. No new alert is raised by the next
   `aslms alerts` scan for those events.
4. In the Compose stack (portal on port 3000), with the master switch as the owner set it (never changed by the
   integrator):
   - Claim a case that has two departments' recommendations.
   - The other department's recommendation shows `claimed_elsewhere`. Its claimer gets "Claimed by <DEPT>" in Alerts
     after the scan, and cannot open the case (404).
   - `fetch_queue` has a `dossier` row for the case in lane `request` with the claimer as `requested_by`, unless the
     case was refreshed within 24 hours.
5. Search: the box "Only cases I can open" is ticked on first load. Search the court for a held CNR: the answer says it
   was found in the ASLMS database. The audit row shows `calls: 0, source: "local"`. The person's hourly count (audit
   rows with calls > 0) is unchanged.
6. Suggest a case to another department where the score is in the possible band. That department's claimers get a
   "Suggested for <DEPT>" alert.

## Open questions
None: every decision is made.

Where the owner's instruction left room, the architect chose. Each choice below can be changed at approval:
- **Decision 1:** watcher claims also queue a refresh.
- **Decision 6:** "zero calls are free" as the count rule.
- **Decision 8:** the API default stays `false`.
- **Decision 10:** e-mail follows the recipient's preferences, besides the in-app notice.
- **Decision 11:** a 409 that names the claiming department.
- **Decision 12:** post-claim suggestions remain the route to a watcher.
- **Decision 14:** a one-off command without alerts for cases claimed before the change.
- **Decision 15:** suggestion alerts also on disposed cases.
