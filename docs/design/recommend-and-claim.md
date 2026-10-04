# Design: Recommend and claim — matching rules, the scoring engine, recommendations, ownership actions, the case inbox

```
slug: recommend-and-claim
status: approved
author: architect
date: 2026-10-04 (revised 2026-10-04 after the owner's review)
approved_by: product owner (nayan.semt@gmail.com) on 2026-10-04
```

## Context
Plan §4 (Department Case Mapping), §4.1 (codes and signals), §4.2 (score, Table 6), §5.4 (Department Case
Inbox), §5.11 (code-to-department mapping, keywords and name patterns), §1.1 Table 1 (the department admin
"manages the department's users, codes and keywords; reviews recommended cases and claims the department's
cases"; the central operator "oversees unclaimed cases"), §6.1 ("by the time users log in, the day's cases have
been matched to departments"). CLAUDE.md: recommend-and-claim; a case belongs to a department only after it
claims it. Backlog row 2.

The plan's rules, in substance:
- Signals: a mapped standing-counsel code in the cause-list entry (strongest); keywords and name patterns in
  party names; linked-case history (a related case already claimed leans the new case to that department); the
  department's watchlist. Combined into one score in [0, 1] per department.
- ≥ 0.85 strong recommendation (top of the inbox); 0.50–0.85 possible match; < 0.50 not recommended, kept in
  the unclaimed pool that any department can search and claim.
- A department claims or dismisses; on dismissal it can suggest another department, which then gets the
  recommendation. A case may be recommended to several departments; if several claim it, one is the primary
  owner and the others are watchers. Unclaimed cases are visible to the central operator for follow-up.
- Inbox tabs: Recommended (strongest first, with the signals behind the score), Claimed, Unclaimed pool,
  Transfers.

What is in place:
- Group 5 tables from migration 0001 (`counsel_codes`, `office_name_patterns`, `office_keywords`,
  `office_watchlist`, `case_office_scores`, `recommendations`, `case_ownership`, `ownership_transfers`) and their
  models in `domain/ownership.py`; `custody` / `custody_history` (Phase 2 tables, empty). There are no partial
  unique indexes yet: "one active primary owner per case" and "one active recommendation per (case, office)"
  are documented in `schema.md` but not enforced by the database. The rule tables are empty (no administration
  endpoint writes them yet).
- All ownership functions exist in `Permission` and in the default matrix (`access_seed.py`):
  `admin.counsel_codes`, `admin.keywords`, `admin.watchlist` (dept admin; watchlist also central operator),
  `cases.claim`, `cases.dismiss`, `cases.suggest_elsewhere`, `cases.transfer_request`, `cases.transfer_decide`,
  `cases.allot`, `cases.release` (dept admin and dept head; `cases.suggest_elsewhere` also central operator),
  `cases.view_scope`, `cases.view_all`. `seed_ref_tables` and `seed_matrix` add missing codes and matrix rows on
  every `aslms seed` run.
- Event types `recommendation_made`, `claimed`, `dismissed`, `suggested_elsewhere`, `transfer_requested`,
  `transfer_decided`, `ownership_released`, `allotted`, `custody_moved`, `config_changed`; record type `TRF`.
- `cases.status` (`pending` / `disposed` / `unknown`) is kept from NAPIX by the pipeline.
- The pipeline writes `causelist_entries` (`counsel_codes text[]`, `petitioner_text`, `respondent_text`,
  `case_id`) in `services/causelists.py::apply_entries`, and dossiers (`case_parties`,
  `case_advocates.counsel_code`, `case_links`) in `services/cases.py::apply_dossier`. A case without a CNR keeps
  its row when the CNR arrives (`get_or_create_case` fills it in place), so ownership on such a case is never
  orphaned.
- `services/offices.py` (`DEPARTMENT_TIER_KINDS`, `tier_of`, `find_office`; deactivation is refused while active
  ownership or custody points at the office), `services/access.py` (`require`, `has`, `in_scope`,
  `is_super_admin`, `actor_for`), `services/audit.py::write_audit`, `services/cases.py::emit_event` and
  `normalise_name`, `services/refno.py::allocate_ref_no`, `services/queue.py::enqueue`.
- Earlier decisions in the log that this design follows: recommendations go to departments, and signals on a
  directorate roll up to its department with the directorate kept as the suggested unit; generic State codes
  (`PP, ASSAM`, `GA, ASSAM`) add nothing; a department's dismissal or claim is never re-opened by the engine;
  allotment to a unit and/or officer after claiming; custody is derived (claim → department, allotment → unit
  and/or officer, transfer accepted → new department). The 26 Sep entry "release → the next primary owner" is
  **superseded** by decision 10 (owner review 2026-10-04); the decisions log records this when the item is built.

**Owner review 2026-10-04** — the changes made in this revision (each is marked in the decision it touches):
1. Scoring is accepted as proposed, but the signal weights and the band thresholds become settings the super
   admin edits in the application (decisions 2, 4, 5, 13, 20, 21; Data). The fixed numbers in CLAUDE.md are
   flagged as a deviation (decision 21).
2. Release is removed: once claimed, a case never returns to the unclaimed pool; it stays with the last holder
   and leaves a department only by an accepted transfer. Claimed cases are split into Active and Disposed by
   `cases.status` (decisions 4, 6, 8, 10, 11, 15, 23).
3. New function: take over an allotted case within the same department (decisions 20, 22).
4. Department discovery stays deferred and never creates departments (decision 18).

Not covered: department discovery through NAPIX Search by Party Name (decision 18, backlog row 19);
alerts and notifications for recommendations and ownership events (`alerts-notifications` reads the events this
item writes, including `case_taken_over` to notify the previous holder); the full case visibility rule and the
case detail (`cases-api`); requests and hand-overs (`custody-workflow`); the portal screens (`portal-cases`,
including the scoring-settings screen); tuning weights from claims and dismissals (dropped from scope, decisions
log "Superseded decisions").

## Decisions
1. **Scores and recommendations are per Department-tier office** (`department`, `central`, `advocate_general`;
   `offices.DEPARTMENT_TIER_KINDS`). A rule attached to a directorate or unit counts for its Department-tier
   ancestor (the second segment of `offices.path`); the most specific office of the strongest hit is kept as
   `suggested_unit` in the signals and offered as the default unit at claim time. Rules on inactive offices, and
   rules whose Department-tier ancestor is inactive, are ignored. Alternative: recommend to directorates
   directly — rejected by the 26 Sep decision; a directorate is reached by allotment.
2. **The score formula** (the plan names the signals and the bands but not the arithmetic; accepted by the owner
   on 2026-10-04). For each department, take the strongest weight within each signal kind, then combine the
   kinds by "noisy OR": `score = 1 − Π (1 − w_kind)`, rounded to 3 decimals. *Owner review 2026-10-04:* the
   weight of each kind and the two band thresholds are no longer code constants or schema defaults; they are read
   from the current `scoring_settings` version (decision 21). The defaults (version 1):

   | Signal kind | Default weight | Alone gives (default bands) | Effective weight of a hit |
   |---|---|---|---|
   | `counsel_code` | 0.950 | strong | the rule's `weight` override if set, else the setting |
   | `name_pattern` | 0.800 | possible | the rule's `weight` override if set, else the setting |
   | `watchlist` | 0.750 | possible | the rule's `weight` override if set, else the setting |
   | `linked_case` | 0.700 | possible | the setting (there is no rule row) |
   | `keyword` | 0.400 | pool | the rule's `weight` override if set, else the setting |

   Examples at the defaults: pattern + keyword = 0.880 (strong); keyword + linked case = 0.820 (possible); two
   keywords = 0.400 (the maximum within a kind, so repeated weak hits never add up to a recommendation). Band:
   `high` when score ≥ `threshold_strong` (default 0.850), `medium` when `threshold_possible` (default 0.500)
   ≤ score < `threshold_strong`, no recommendation below `threshold_possible`. The engine version written on
   every score row is `"<ENGINE_VERSION>.<settings version>"` (`1.1` at the defaults), so every settings change
   is a new engine version. Alternatives: a weighted sum capped at 1 (one strong and one weak signal saturate at
   once and the kinds lose their meaning), a trained model (no labelled data; tuning from claims was dropped).
3. **What each signal reads.**
   - `counsel_code`: every code in `causelist_entries.counsel_codes` of the case's entries and every
     `case_advocates.counsel_code` with `is_current`, both sides (the State also appears as appellant), compared
     after `normalise_counsel_code` (upper case, whitespace collapsed, no space before and one space after a
     comma, trailing commas stripped: `SC,EDU` → `SC, EDU`). Codes with `is_generic_state = true` score nothing
     (they only mark "the State is a party", used by the pool filter of decision 15).
   - `keyword`: whole-word, case-insensitive match in the normalised party names
     (`cases.normalise_name`) of the case: `case_parties.name` with `is_current`,
     `causelist_entries.petitioner_text` and `respondent_text`, `cases.petitioner_summary` and
     `respondent_summary`.
   - `name_pattern`: on each party name separately: `exact` = the normalised name equals the normalised
     pattern; `prefix` = the name starts with it; `regex` = `re.search(pattern, name, re.IGNORECASE)` on the
     normalised name. Regexes are validated on save (compile, ≤ 300 characters, must not match the empty string).
   - `linked_case`: a `case_links` row in either direction (`from_case_id`, or `to_case_id` / `to_cnr` resolved to
     a held case) whose other case has an **active** `case_ownership` row (primary or watcher) of the department.
   - `watchlist`: an active `office_watchlist` row of the department for the case's CNR.
   Each hit is one element of `case_office_scores.signals` (shape in Data). Matching runs in Python over the
   loaded rule set; no SQL is built from rule text.
4. **When scoring runs.** (a) Inline, at the end of `apply_entries` for every case the list touched, and at the
   end of `apply_dossier` for that case, in the same transaction, inside a savepoint: a scoring error is recorded
   in `source_failures` (kind `scoring`, ref the case `ref_no`) and never fails the cause-list or dossier item.
   (b) After a claim, a transfer accept or a watcher's stop-watching (*owner review 2026-10-04*, was "release"),
   for the cases linked to that case (linked-case signal). (c) After a watchlist add or change, for that case.
   (d) The **dirty rescore**: a Celery beat task every 15 minutes compares the latest `created_at` / `updated_at`
   of `counsel_codes`, `office_keywords`, `office_name_patterns`, `office_watchlist`, `offices` and (*owner
   review 2026-10-04*) `scoring_settings` with the start of the last succeeded `job_runs` row `rescore`; when one
   is newer it rescores every non-merged case in batches of 500 (one commit per batch, counters in `job_runs`). A
   settings save also dispatches the task at once after its commit (decision 21). (e) `aslms rescore [--all |
   --case REF]` by hand. Rule edits therefore take effect within 15 minutes; the API response says so.
   Alternatives: rescore inline on every rule edit (a counsel-code change touches tens of thousands of cases
   inside one HTTP request); a new `fetch_queue` kind (that queue is NAPIX work, and its kinds are a native enum).
5. **Recommendation lifecycle (engine side).** For every (case, department) with score ≥ `threshold_possible`
   (*owner review 2026-10-04*: the current setting, default 0.50):
   - nothing is written when the department already has an active `case_ownership` row for the case, or has
     **ever** dismissed it (`dismissed`, `suggested_elsewhere`) or claimed it (`claimed`) — "never re-opened by
     the engine";
   - otherwise the active `recommended` row is created (event `recommendation_made`) or its `score` / `band`
     updated (a new `recommendation_made` event only when the band changes). Origin: `cause_list` from
     `apply_entries`; from `apply_dossier` the case's `first_seen_source` mapped `causelist → cause_list`,
     `search → search`, otherwise `rescore`; `watchlist` for (c); `rescore` for (b), (d), (e).
   An active engine-made row (origin other than `suggestion`) whose score falls below `threshold_possible`
   becomes `expired` (`acted_at` set) — including rows pushed below by a settings change. Rows of a case with
   `merged_into_case_id` are expired. Engine writes carry the system actor snapshot (`actor_name = 'matching'`)
   and write **no** `audit_log` rows (they are not user actions; events and `case_office_scores` are their
   record). `case_office_scores` keeps only rows with score > 0; rows that drop to 0 are deleted (a derived table
   on the cascade list, where `aslms_app` holds DELETE).
   Recommendations stay open when another department claims the case (the plan: several departments may claim;
   the second becomes a watcher); the inbox shows the current owner beside them.
6. **Claim.** `cases.claim`. The claim is for the actor's department (the Department-tier ancestor of the
   actor's office); a super admin, who sits at `GOA`, must name `office_code`. Allowed when the case has never
   had a primary owner (the pool — decision 10, *owner review 2026-10-04*) or the department has an active
   `recommended` row; otherwise 404 (the case is not visible to it) — taking a case another department owns,
   without a recommendation, is a transfer. Under a row lock on the case (`SELECT … FOR UPDATE` on `cases`): no
   active primary → the new row is `primary`; an active primary of another department → `watcher`; the
   department already active on the case → 409. The department's active recommendation becomes `claimed`
   (`acted_at`). Optional `unit_code` / `officer_user_id` allot in the same step (needs `cases.allot` too;
   decision 9). Audit `ownership.claim`; event `claimed` (`tracking_card`); custody per decision 11 when primary.
7. **Dismiss and suggest elsewhere.** `cases.dismiss` sets the department's active recommendation to
   `dismissed` with an optional `reason` (no active recommendation → 404). `cases.suggest_elsewhere` takes
   `office_code` (an active Department-tier office other than the actor's) and a required `reason`: the actor's
   active recommendation, if any, becomes `suggested_elsewhere` with `suggested_office_id`; the target gets an
   active `recommended` row with origin `suggestion`, its engine score (0 when none), band `high` if that score
   ≥ `threshold_strong` else `medium`, the suggesting user in the actor snapshot and the reason — even when the
   target dismissed the case before (a human suggestion is not the engine re-opening it). Refused (409) when the
   target actively owns the case; when the target already has an active recommendation it is left as it is and
   the response says `target_already_recommended: true`. The central operator (who holds
   `cases.suggest_elsewhere` and has no recommendation of their own) uses this to route pool cases. Audit
   `recommendation.dismiss` / `recommendation.suggest`; events `dismissed` / `suggested_elsewhere`
   (+ `recommendation_made` for the target).
8. **Transfers** — the only way a primary owner hands a case on (*owner review 2026-10-04*). Only the primary
   owner's department may request (`cases.transfer_request`): `to_office_code` (an active Department-tier
   office, not itself), a required `reason`, `stay_as_watcher` (default false). One open request per case
   (partial unique index); `ref_no` `ASLMS/<from office>/TRF/<yyyy>/<n>`. The target decides
   (`cases.transfer_decide`): **accept** → the old primary row becomes `transferred` (`released_at`); the
   target's active watcher row, if any, is promoted to `primary`, else a new primary row is inserted; with
   `stay_as_watcher` the old department gets a new `watcher` row; custody moves to the target. **Decline** →
   `declined` with `decision_note`; the case stays with the requester. The requester's department may
   **withdraw** while `requested` (`withdrawn_at`). `decided_by_user_id` and `decided_at` are set on accept and
   decline. Audit `transfer.request` / `transfer.accept` / `transfer.decline` / `transfer.withdraw`; events
   `transfer_requested`, `transfer_decided` (payload `decision`). (The earlier rule "releasing a primary with an
   open request is refused" is gone with decision 10.)
9. **Allot.** `cases.allot`, on the actor's department's active ownership row (primary or watcher):
   `unit_code` — an active office strictly inside the department's subtree; `officer_user_id` — an active user
   whose office is in the department's subtree, of any type except `super_admin`, `state_oversight`, `auditor`,
   `central_operator` (the "eligible officer" rule, reused by decision 22); either may be cleared with `null`.
   Sets `allotted_at` and `allotted_by_user_id` (new columns). Re-allotment overwrites; the history is in
   `audit_log` (`ownership.allot`, before/after) and in the `allotted` events. Custody per decision 11 when the
   row is primary.
10. **No return to the pool; a watcher may stop watching** (*owner review 2026-10-04 — replaces the former
    decision 10 "Release"*). Once any department has claimed a case it can **never** return to the unclaimed
    pool: there is no release of a primary row, no promotion of a watcher on release, and no custody reason
    `returned_to_pool`. The case stays with the last primary owner — also after disposal — and leaves that
    department only by a transfer accepted by the target (decision 8). The unclaimed pool is therefore "cases that
    have never had a primary owner". A **watcher** row (a second department that claimed, decision 6, or the old
    owner kept with `stay_as_watcher`) may end its watching: `cases.release` (code kept, relabelled "Stop
    watching", decision 20) with a required `reason` (stored in the new `release_reason`) sets the watcher row
    `released` (`released_at`); the primary owner and custody are untouched; the department's recommendation stays
    `claimed`, so the engine does not recommend the case to it again. Asked of a primary row → 409
    `primary_cannot_release` ("transfer the case instead"); a CHECK backs this in the database (Data). Audit
    `ownership.unwatch`; event `ownership_released` (payload `role: watcher`). Consequence: an office holding a
    primary case cannot be deactivated until its cases are transferred (the offices-admin deactivation check
    already refuses while active ownership or custody points at it). Alternatives: drop `cases.release` entirely
    (a department that claimed as a watcher by mistake could never leave); keep primary release to the
    earliest watcher (ruled out by the owner).
11. **Custody follows primary ownership only** — minimal, written by this item because alerts (backlog row 5,
    before `custody-workflow`) go to the custody holder and must find one. `services/custody.py::move_custody(
    session, actor, case, *, office, user=None, reason)` upserts `custody` (holder, `since`,
    `pending_action='none'`), appends a `custody_history` leg (`seq_no` = max + 1 under the case lock; office code
    and user name snapshots; actor snapshot) and emits `custody_moved` (`tracking_card`). Reasons (*owner review
    2026-10-04*): `claimed` (department office), `allotted` (unit office if set, else the department; holder user
    = the officer), `taken_over` (decision 22: the new unit, else the department; holder user = the taker),
    `transferred` (target department). `released` and `returned_to_pool` are removed with decision 10: a claimed
    case always has a department holder, never the root `GOA`. Watcher rows never move custody.
    `custody-workflow` later adds requests and hand-overs on the same function.
12. **Uniqueness in the database** (migration 0004, partial unique indexes): one active primary per case; one
    active row per (case, office); one active `recommended` row per (case, office); one `requested` transfer per
    case; one current `scoring_settings` version (*owner review 2026-10-04*). The services check first (clean
    409s); the indexes catch races (`IntegrityError` → 409).
13. **Who manages the rules.** `admin.counsel_codes` for counsel codes; `admin.keywords` for keywords and name
    patterns; `admin.watchlist` for the watchlist. A non-super-admin acts only on rules whose office is in their
    subtree (`access.in_scope`), so a department admin maps codes to the department or its directorates, never to
    another department. Generic State codes (`is_generic_state = true`) must be mapped to the root `GOA`, so only
    the super admin creates them. Uniqueness as in the schema (`counsel_codes.code` globally — one code, one
    office; (office, keyword); (office, pattern, kind); (office, cnr)); re-adding a deactivated rule reactivates
    it (audited as `*.reactivate`). A counsel code may be re-pointed to another office in scope (`office_code` in
    PATCH, audited) because the code is unique. Rules are deactivated, never deleted. *Owner review 2026-10-04:*
    a rule's `weight` is an optional override of its kind's setting (NULL = use the setting); setting or clearing
    it also requires `admin.scoring` (decision 21), so a department admin cannot outweigh the super admin's
    settings.
14. **Watchlist by CNR only.** The CNR must match `^[A-Z]{4}\d{12}$` (no made-up identifiers). When the case is
    not held yet, a `dossier` row is enqueued (`queue.enqueue(session, FetchKind.DOSSIER, cnr,
    PRIORITY["dossier_new"])` — the NAPIX call happens in the runner, through the integration layer); `case_id` is
    filled and the case scored when the dossier is applied. The office defaults to the actor's department.
15. **The inbox.** Summary data only (`ref_no`, CNR, case number, petitioner and respondent summaries, status,
    next hearing date, last listed date, the current primary owner's code) — full case detail stays behind
    `cases-api` visibility.
    - *Recommended*: the department's active recommendations, `band high` first, then score, then next hearing
      date (nulls last); each with its signals (from `case_office_scores`) and the current owner, if any.
      Requires `cases.claim` for the caller's own department; `?office=` for any office requires `cases.view_all`
      (read-only).
    - *Claimed*: the active ownership rows of the department, split into **Active** and **Disposed** (decision
      23, *owner review 2026-10-04*). Whole department for callers holding `cases.claim` or `cases.allot`;
      otherwise rows allotted to the caller (`officer_user_id`), or to a unit in the caller's subtree when the
      caller sits below the department (a directorate user sees its directorate's cases, an officer the cases
      allotted to them — plan Table 1). Requires `cases.view_scope`; `?office=` needs `cases.view_all`.
    - *Unclaimed pool*: non-merged cases that have never had a primary owner (*owner review 2026-10-04*;
      dismissed and low-score cases included), filters `q` (CNR, case number, party text; ≥ 3 characters),
      `listed_from` / `listed_to`, `status`, `case_type`, `year`, `min_score` (any department's), `state_party` (a
      generic or mapped counsel code appears); ordered by next hearing date ascending (nulls last), then first
      seen. Requires `cases.claim` or `cases.view_all` (the plan: any department can search and claim; the central
      operator follows up).
    - *Transfers*: `direction=in|out`, `status`. Requires `cases.transfer_request` or `cases.transfer_decide` for
      the own department, `cases.view_all` for any.
    - *Counts* for the dashboard (`recommended_high`, `recommended_medium`, `claimed_active`, `claimed_disposed`,
      `transfers_in_open`, `pool_with_hearing_7d`), each under the rule of its tab.
    Lists are paginated (`limit` ≤ 200, default 50; `offset`) and return `{items, total}`.
16. **`services/visibility.py`** holds `department_of(session, office)` and `owned_case_filter(session, user)`
    (the Claimed-tab predicate of decision 15, in SQL), so that `cases-api` extends them (custody, requests,
    counsel) instead of re-deriving ownership scope.
17. **`resolve_case_ref(session, ref)`** in `services/cases.py`: accepts the case id, the `ref_no` (also in the
    URL form `ASLMS-GOA-CASE-2026-001842`) or the CNR (DB_STANDARD §3); unknown → 404. Used by every endpoint here
    and by `cases-api`.
18. **Department discovery is deferred — deviation (scope), flagged for the owner; kept deferred by the owner
    review 2026-10-04.** Plan §5.4 lists "Party Name Search APIs" beside Cause List Details as inbox inputs
    (department party names run periodically through NAPIX Search by Party Name). It needs a new `fetch_queue`
    kind (a native enum, so a migration), a share of the 1,000-calls-an-hour quota beside the historical load,
    and the keyword rules this item creates. It is backlog row 19 `department-discovery`; the cases it finds will
    be scored by this engine unchanged. Every case listed in a cause list — the plan's main source — is covered
    now. Departments are set up manually by the super admin (offices administration): discovery only finds cases
    for departments already configured there, from their keywords and name patterns, and never creates a
    department or any other office.
19. **Unmapped codes report.** `GET /admin/counsel-codes/unmapped` lists the codes seen in cause lists and
    dossiers that have no mapping (normalised, with entry count, last listed date and one example case ref), so
    departments can compile the mapping from the cause lists as the decisions log requires. Nothing is mapped
    automatically.
20. **Two new functions, one relabelled, one new event type** (*owner review 2026-10-04 — replaces "No new
    function, no seed change"*). `Permission.ADMIN_SCORING = "admin.scoring"` ("Scoring settings", "Change the
    matching weights and recommendation thresholds") — enabled for no user type in the default matrix, so only
    the super admin (who always has every function) holds it until it is granted to someone.
    `Permission.CASES_TAKE_OVER = "cases.take_over"` ("Take over a case", "Take over a case allotted to a
    colleague in the same department") — added to `_CASE_WORK`, so enabled by default for `dept_head`,
    `dept_admin`, `dept_officer` and `directorate_user` and for no other type. `cases.release` keeps its code
    and is relabelled ("Stop watching", "End the department's watcher role on a case"). `EventType.CASE_TAKEN_OVER
    = "case_taken_over"` (a tracking-card event). All four reach the database through `aslms seed`:
    `seed_ref_tables` adds the new codes and `seed_matrix` the missing matrix rows; `seed_ref_tables` is extended
    to refresh `label` and `description` of existing `ref_permission` rows from `PERMISSION_LABELS` (DB_STANDARD
    §0: reference tables are "upserted on code"; label editing by administrators is not built). Alternative for
    scoring: reuse `admin.config` (system configuration is broader and would hand scoring to whoever gets
    configuration).
21. **Scoring settings, edited by the super admin** (*owner review 2026-10-04*). The five kind weights and the
    two thresholds live in `scoring_settings`, a versioned master table: each save inserts a new version
    (`version` = previous + 1, `is_current = true`) and closes the previous one (`is_current = false`,
    `valid_to`); nothing is updated in place or deleted, so every score can be traced to the settings it used.
    Version 1 holds the plan's defaults (decision 2) and is inserted by `aslms seed` when the table is empty; on an
    empty table the engine uses the same defaults as version 0, so a fresh database still scores by the plan.
    Rules: each weight in (0, 1]; `0 < threshold_possible < threshold_strong ≤ 1`; a required `reason`;
    `expected_version` must equal the current version (409 otherwise — two administrators cannot overwrite each
    other); a save identical to the current values writes nothing (`changed: false`). Each save writes an audit
    row `scoring_settings.update` (before/after values and version numbers) and a `config_changed` event (payload
    `{entity: "scoring_settings", id, action: "update", version}`), then, after the commit, dispatches the Celery
    task `aslms.rescore_if_dirty` (the 15-minute beat picks it up if the dispatch fails). The new version is the
    new engine version (decision 2); the full rescore updates scores, bands and expiries (decision 5); suggestion
    rows keep their band. Function `admin.scoring` to change and to read the history; the current values are also
    readable with `admin.counsel_codes` or `admin.keywords` (a department admin can see why a case scored as it
    did). **Deviation, flagged for the owner:** plan §4.2 (Table 6) and CLAUDE.md ("Score ≥ 0.85 = strong
    recommendation, 0.50–0.85 = possible match, < 0.50 = unclaimed pool") state the thresholds as fixed numbers;
    with this decision they are defaults the super admin can change. CLAUDE.md must be updated by the owner to say
    so (the architect does not edit it). Alternatives: a key-value settings table (no typed columns, no CHECKs);
    values edited in place with only the audit log as history (scores could not name the settings they used).
22. **Take over a case within the same department** (*owner review 2026-10-04*). `cases.take_over`. When a
    department's active ownership row (primary or watcher) is allotted to an officer (`officer_user_id` set), any
    other user of the same department — the actor active, an eligible officer (decision 9), with an office in the
    department's subtree — may take the case over for themselves, e.g. when the holder is absent. No approval.
    Under the case row lock: the active row of the actor's department must exist (else 404, as for any case
    another department owns — users outside the department can never take it over); it must be allotted to an
    officer other than the actor (no officer → 409 `not_allotted`, use allot; the actor already holds it → 409);
    an optional `expected_officer_user_id` guards against a race (differs → 409). The row's `officer_user_id`
    becomes the actor; `allotted_at` = now, `allotted_by_user_id` = the actor. **Directorate scoping:** the unit
    follows the taker, so that the case appears in the taker's directorate and custody stays coherent — if the
    current unit is set and the taker's office lies inside the unit's subtree, the unit stays; otherwise the unit
    becomes the taker's office when that is below the department, or `null` when the taker sits at the department
    office itself. A directorate user may therefore take over a case of a sibling directorate of the same
    department (the owner's "same department"); the case then leaves the old directorate's Claimed list, and the
    audit row and event record it. The taker needs no prior visibility of the case beyond belonging to the
    department (they name it by ref, CNR or case number). The super admin and State-wide users sit outside every
    department and cannot take over. When the row is primary, custody moves to the new unit (or the department)
    with the taker as holder user (reason `taken_over`); a watcher row moves no custody. Audit
    `ownership.take_over` (before/after: officer, unit); event `case_taken_over` (`tracking_card`, payload
    `{ownership_id, office_code, role, from_user_id, from_user_name, to_user_id, to_user_name, from_unit_code,
    to_unit_code, reason, taken_at}`) — the record `alerts-notifications` will use to notify `from_user_id`. An
    optional `reason` (≤ 500 characters). Alternatives: the department head's approval (the owner chose none);
    only within the same unit (the owner said the department); keep the unit unchanged (a taker from another
    directorate would hold custody at an office they do not belong to).
23. **Active and Disposed claimed cases** (*owner review 2026-10-04*). The Claimed tab, its counts and
    `owned_case_filter` take `case_state=active|disposed|all` (default `active`): `active` = `cases.status IN
    ('pending', 'unknown')`, `disposed` = `cases.status = 'disposed'`. The NAPIX-maintained `cases.status` is the
    single source: a restored case moves back to Active by itself on the next refresh, with no second flag to keep
    in step. Disposed cases stay with their holder (decision 10). Alternative: a flag on `case_ownership` (a
    duplicate of `cases.status` that the pipeline would have to keep in step).

## Data
Migration **0004_ownership_rules** (new; 0001–0003 untouched). The models in `domain/ownership.py` gain the same
columns, `CheckConstraint`s and `Index(..., unique=True, postgresql_where=...)` entries, and the new
`ScoringSettings` model, so `test_database_matches_the_models` stays green.

For `docs/schema/schema.md`, Group 5 (as built, recommend-and-claim, migration 0004):
- `scoring_settings` (master, versioned — *owner review 2026-10-04*) — `id` uuid v7 PK; `version integer NOT
  NULL UNIQUE`; `weight_counsel_code`, `weight_name_pattern`, `weight_watchlist`, `weight_linked_case`,
  `weight_keyword` `numeric(4,3) NOT NULL`, each `> 0 AND <= 1` (CHECK `ck_scoring_settings_weights`);
  `threshold_strong`, `threshold_possible` `numeric(4,3) NOT NULL`, CHECK `ck_scoring_settings_thresholds`
  (`threshold_possible > 0 AND threshold_possible < threshold_strong AND threshold_strong <= 1`); `reason text
  NOT NULL`; `is_current boolean NOT NULL DEFAULT false`; `valid_from timestamptz NOT NULL DEFAULT now()`,
  `valid_to timestamptz NULL`, CHECK `ck_scoring_settings_current` (`is_current = (valid_to IS NULL)`); partial
  unique index `ix_scoring_settings_current` UNIQUE (`is_current`) WHERE `is_current`; `created_at` /
  `updated_at`, `created_by` / `updated_by` → `users` ON DELETE SET NULL (the master audit columns). No other FK.
  A save inserts a new version and closes the old one; rows are never deleted. Version 1 (0.950, 0.800, 0.750,
  0.700, 0.400; 0.850, 0.500; reason "Plan §4.2 defaults") is inserted by `aslms seed`.
- `counsel_codes` (master) — `code` stored normalised (`SC, EDU`), unique; `office_id` → `offices` RESTRICT
  (any office; its Department-tier ancestor receives the score); `is_generic_state` rows are mapped to `GOA` and
  score nothing; `weight` becomes NULL-able with no default (*owner review 2026-10-04*: NULL = the kind's
  setting; a value is an override set by `admin.scoring` holders), CHECK `ck_counsel_codes_weight` (`weight IS
  NULL OR (weight > 0 AND weight <= 1)`); deactivated, never deleted; `created_by` / `updated_by`.
- `office_keywords`, `office_name_patterns` (master) — `weight` NULL-able with no default, same meaning; CHECK
  `weight IS NULL OR (weight > 0 AND weight <= 1)` (`ck_office_keywords_weight`,
  `ck_office_name_patterns_weight`); keywords and exact/prefix patterns stored normalised (upper case, dots as
  spaces, whitespace collapsed); regex patterns validated by the service; `created_by` / `updated_by`.
- `office_watchlist` (master) — `weight` NULL-able with no default, same meaning; CHECK
  `ck_office_watchlist_weight` (same expression); `cnr` a 16-character CNR checked by the service; `case_id`
  (→ `cases` RESTRICT) filled when the case is held; actor snapshot.
- `case_office_scores` (derived, CASCADE → cases) — one row per (case, Department-tier office) with score > 0;
  `signals` is a JSON array of `{kind, rule_id, rule_office_code, weight, matched, where, ref}`, `kind` ∈
  `counsel_code`, `keyword`, `name_pattern`, `linked_case`, `watchlist`; `weight` is the effective weight used;
  `matched` is the code, keyword, pattern or linked case number; `where` ∈ `causelist_entry`, `case_advocates`,
  `case_parties`, `case_summary`, `case_links`, `watchlist`; `ref` is the entry's `{list_date, sr_no}`, the party
  `{role, party_no}` or the linked case `ref_no`; plus one element `{kind: "suggested_unit", office_code}` when
  the strongest rule sat below the department. `engine_version` is `"<engine>.<scoring_settings version>"`
  (`1.1` at the defaults).
- `recommendations` (transaction) — `office_id` is always a Department-tier office; partial unique index
  `ix_recommendations_active` UNIQUE (`case_id`, `office_id`) WHERE `status = 'recommended'`; CHECK
  `ck_recommendations_score_range` (`score >= 0 AND score <= 1`); engine rows carry the system actor snapshot
  (`actor_name = 'matching'`), suggestion rows the suggesting user; `expired` is set by the engine when an engine
  score drops below the current `threshold_possible` or the case is merged. FKs RESTRICT (unchanged).
- `case_ownership` (transaction) — new columns `allotted_at timestamptz NULL`, `allotted_by_user_id uuid NULL`
  → `users` ON DELETE SET NULL (an actor column, like `officer_user_id`; set by allot and take-over),
  `release_reason text NULL` (a watcher's stop-watching reason); partial unique indexes
  `ix_case_ownership_active_primary` UNIQUE (`case_id`) WHERE `status = 'active' AND role = 'primary'` and
  `ix_case_ownership_active_office` UNIQUE (`case_id`, `office_id`) WHERE `status = 'active'`; CHECK
  `ck_case_ownership_release_watcher` (`status <> 'released' OR role = 'watcher'`) — a primary row is never
  released (decision 10, *owner review 2026-10-04*). `office_id` is always a Department-tier office;
  `unit_office_id` an office strictly inside it. Other FKs RESTRICT (unchanged); actor snapshot. Status values
  unchanged (`released` is used by watchers only).
- `ownership_transfers` (transaction) — new columns `decision_note text NULL`, `stay_as_watcher boolean NOT NULL
  DEFAULT false`; partial unique index `ix_ownership_transfers_open` UNIQUE (`case_id`) WHERE `status =
  'requested'`; `ref_no` allocated under the `from_office_id` code (type `TRF`).
- `custody` / `custody_history` — first written by this item, for primary-ownership moves only (decision 11);
  `custody_history.reason` codes `claimed`, `allotted`, `taken_over`, `transferred`.

Reference codes (through `aslms seed`, decision 20): `ref_permission` gains `admin.scoring` and
`cases.take_over`, and `cases.release` gets its new label; `ref_event_type` gains `case_taken_over`
(`is_tracking_card = true`). No native enum changes.

Index names take the `ix_` prefix with an explicit suffix because the convention's generated name
(`ix_<table>_<column>`) is already used by the plain indexes. The upgrade sets any existing rule `weight` equal to
its old schema default to NULL (the rule tables are expected to be empty). The downgrade drops `scoring_settings`,
the indexes, checks and columns, and restores `NOT NULL` and the old defaults on the rule weights (filling NULLs
with the old defaults first).

## Services
`backend/aslms/services/scoring_settings.py` (new, *owner review 2026-10-04*):
- `DEFAULTS` (version 0: the decision 2 numbers); `@dataclass(frozen=True) Settings {version, weights:
  dict[kind, float], threshold_strong, threshold_possible}`; `class SettingsError(ValueError)`, `class
  StaleSettings(SettingsError)` (→ 409).
- `current(session) -> Settings` (the `is_current` row, else `DEFAULTS`); `history(session, actor_user, *,
  limit, offset)` (`admin.scoring`).
- `update(session, actor, actor_user, *, weights, threshold_strong, threshold_possible, reason,
  expected_version) -> tuple[Settings, bool]` (the bool: changed) — `access.require(admin.scoring)`, the
  validation of decision 21, `SELECT … FOR UPDATE` on the current row, version check, insert + close,
  `write_audit('scoring_settings.update')`, `emit_event(config_changed)`. The router dispatches
  `rescore_if_dirty.delay()` after the commit (a dispatch error is logged, not raised).
- `seed_default(session, report)`, called by `services/seed.py` (inserts version 1 when the table is empty).

`backend/aslms/services/matching.py` (new) — the engine:
- `ENGINE_VERSION = "1"`, `CNR_RE`. No weight or threshold constants (*owner review 2026-10-04*): they come from
  `scoring_settings.current`.
- `normalise_counsel_code(code) -> str`; `normalise_term(text) -> str` (= `cases.normalise_name`).
- `combine(weights_by_kind: dict[str, float]) -> float` (noisy OR, rounded); `band_of(score, settings) ->
  ScoreBand | None`; `engine_version(settings) -> str`.
- `RuleSet.load(session) -> RuleSet`: the current settings; the active rules of active offices, each resolved to
  its Department-tier office with its effective weight (override or setting); compiled regexes; codes by
  normalised text; the generic codes.
- `CaseEvidence.gather(session, case) -> CaseEvidence`: entry codes and party texts, current advocates' codes,
  current parties, summaries, linked cases with their active owners, watchlist hits.
- `score_case(rules, evidence) -> dict[office_id, ScoredOffice(score, signals)]` — pure, unit-tested without a
  database.
- `apply_scores(session, case, scores, *, origin, settings) -> ScoreReport` — writes `case_office_scores`;
  creates, updates and expires recommendations by decision 5; emits `recommendation_made`.
- `score_cases(session, case_ids, *, origin, rules=None) -> ScoreReport` — a savepoint per case, failures to
  `source_failures` (kind `scoring`); called by `causelists.apply_entries` and `cases.apply_dossier` (one
  `RuleSet.load` per call).
- `rescore_all(session_factory, *, batch=500) -> ScoreReport` (a `job_runs` row `rescore` with counters `cases`,
  `scores`, `recommended_new`, `band_changed`, `expired`, `failed`, and the settings version used);
  `rules_changed_since(session, ts) -> bool` (includes `scoring_settings`); `rescore_if_dirty(session_factory)
  -> ScoreReport | None`.
- `unmapped_codes(session, *, limit=200) -> list[UnmappedCode]` (decision 19).

`backend/aslms/services/matching_rules.py` (new) — rule administration:
- `class RuleError(ValueError)`, `class DuplicateRule(RuleError)` (→ 409).
- `create_counsel_code(session, actor, actor_user, *, code, office, weight=UNSET, is_generic_state=False,
  notes=None)`, `update_counsel_code(..., office=None, weight=UNSET, notes=None)`,
  `set_counsel_code_active(..., enabled)`; the same three for keywords (`keyword`, `weight`) and name patterns
  (`pattern`, `kind`, `weight`, regex validation); watchlist `add_watch(session, actor, actor_user, *, cnr,
  office=None, reason=None, weight=UNSET) -> tuple[OfficeWatchlist, bool]` (the bool: dossier queued),
  `update_watch`, `set_watch_active`.
- Each: `access.require(<function>)`, `access.in_scope(office)` unless super admin; a given `weight` (a value, or
  `None` to clear the override) also requires `admin.scoring` (*owner review 2026-10-04*) and passes the range
  check; normalisation, duplicate check (reactivate when the duplicate is inactive), `created_by` / `updated_by`
  or the actor snapshot (watchlist), and an audit row: `counsel_code.create|update|deactivate|reactivate`,
  `keyword.*`, `name_pattern.*`, `watchlist.*` (before/after summaries; an update that changes nothing writes
  nothing). Rule writes also emit one `config_changed` event (`scoped`, payload `{entity, id, action}`).
  Watchlist writes rescore that case inline (origin `watchlist`).

`backend/aslms/services/ownership.py` (new) — the human decisions:
- `class OwnershipError(ValueError)`, `class OwnershipConflict(OwnershipError)` (→ 409), `class
  NotVisible(OwnershipError)` (→ 404).
- `acting_department(session, actor_user, office_code=None) -> Office` (decision 6; `office_code` honoured for
  the super admin only; a user with no Department-tier ancestor → `OwnershipError`).
- `eligible_officer(session, department, user) -> bool` (decision 9; shared by allot and take-over).
- `claim(session, actor, actor_user, case, *, office_code=None, unit_code=None, officer_user_id=None,
  note=None) -> CaseOwnership`;
  `dismiss(session, actor, actor_user, case, *, reason=None) -> Recommendation`;
  `suggest(session, actor, actor_user, case, *, office_code, reason) -> SuggestResult`;
  `allot(session, actor, actor_user, case, *, unit_code=UNSET, officer_user_id=UNSET) -> CaseOwnership`
  (the sentinel distinguishes "not given" from `None`);
  `take_over(session, actor, actor_user, case, *, expected_officer_user_id=None, reason=None) ->
  TakeOverResult` (the row and the previous officer; decision 22, *owner review 2026-10-04*);
  `stop_watching(session, actor, actor_user, case, *, reason) -> CaseOwnership` (decision 10, replaces
  `release`; a primary row → `OwnershipConflict('primary_cannot_release')`);
  `request_transfer(session, actor, actor_user, case, *, to_office_code, reason, stay_as_watcher=False) ->
  OwnershipTransfer`; `decide_transfer(session, actor, actor_user, transfer, *, accept: bool, note=None)`;
  `withdraw_transfer(session, actor, actor_user, transfer)`.
- Each: `access.require(...)`, the case row lock, the state checks of decisions 6–10 and 22, `write_audit(...,
  case_id=case.id)`, the event, custody (decision 11), then `matching.score_cases(linked case ids,
  origin=rescore)` for claim, transfer accept and stop-watching.
- `case_ownership_view(session, actor_user, case) -> dict` (primary, watchers, the own recommendation or all of
  them with `cases.view_all`, the open transfer).

`backend/aslms/services/custody.py` (new, minimal): `move_custody` (decision 11).
`backend/aslms/services/inbox.py` (new): `recommended`, `claimed` (with `case_state`), `pool` (never-owned
cases), `transfers`, `counts` — SQL queries returning summary rows and `total`, with the filters and ordering of
decisions 15 and 23.
`backend/aslms/services/visibility.py` (new): `department_of`, `owned_case_filter(session, user, *,
case_state='active')` (decisions 16, 23).
`backend/aslms/services/cases.py`: `resolve_case_ref` (decision 17); `apply_dossier` calls
`matching.score_cases` at its end. `services/causelists.py::apply_entries` collects the touched case ids and calls
`matching.score_cases` once.
`backend/aslms/domain/reference.py`: `Permission.ADMIN_SCORING`, `Permission.CASES_TAKE_OVER`,
`EventType.CASE_TAKEN_OVER`. `services/access_seed.py`: the two labels, `cases.release` relabelled,
`CASES_TAKE_OVER` in `_CASE_WORK`. `services/seed.py`: `CASE_TAKEN_OVER` in `TRACKING_CARD_EVENTS`;
`seed_ref_tables` refreshes `ref_permission` labels and descriptions; calls `scoring_settings.seed_default`.
`backend/aslms/jobs/celery_app.py`: task `aslms.rescore_if_dirty`, beat entry `rescore-dirty` every 15 minutes.
`backend/aslms/cli/matching.py` (new): `aslms rescore [--all] [--case REF]` and `aslms codes unmapped
[--limit N]`, registered in `cli/main.py`.

## API
Errors: 400 `RuleError` / `OwnershipError` / `SettingsError`, 403 `Forbidden` (missing function), 404 unknown or
not visible (indistinguishable), 409 `DuplicateRule` / `OwnershipConflict` / `StaleSettings` / a unique-index
race. `{ref}` is a case id, `ref_no` (slash or dash form) or CNR; `{trf}` is a transfer id or `ref_no`. Lists take
`limit` (≤ 200, default 50) and `offset` and return `{items: [...], total}`.

Router `api/routers/matching.py` (prefix `/admin`, tag `matching`):

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /admin/scoring-settings` | `admin.scoring`, `admin.counsel_codes` or `admin.keywords` | | `ScoringSettingsOut {version, weights {counsel_code, name_pattern, watchlist, linked_case, keyword}, thresholds {strong, possible}, reason, valid_from, updated_by {id, full_name}?, engine_version}` | State-wide values; read-only without `admin.scoring` |
| `PUT /admin/scoring-settings` | `admin.scoring` | `ScoringSettingsIn {weights {all five}, thresholds {strong, possible}, reason, expected_version}` | `ScoringSettingsOut` + `changed`, `rescore_dispatched`, `applies_within_minutes: 15` | super admin by default |
| `GET /admin/scoring-settings/history` | `admin.scoring` | `?limit=`, `?offset=` | `{items: [ScoringSettingsOut + valid_to], total}` | |
| `GET /admin/counsel-codes` | `admin.counsel_codes` | `?office=`, `?q=`, `?include_inactive=` | `{items: [CounselCodeOut {id, code, office {code, name}, weight_override?, effective_weight, is_generic_state, notes, is_active, updated_at}], total}` | rules whose office is in the caller's subtree, plus generic codes (read-only); all for the super admin |
| `POST /admin/counsel-codes` | `admin.counsel_codes` (+ `admin.scoring` when `weight` given) | `CounselCodeIn {code, office_code, weight?, is_generic_state?, notes?}` | 201 `CounselCodeOut` + `applies_within_minutes: 15` | office in the caller's subtree; generic → `GOA` → super admin only |
| `PATCH /admin/counsel-codes/{id}` | `admin.counsel_codes` (+ `admin.scoring` when `weight` given) | `{office_code?, weight?: number\|null, notes?}` | `CounselCodeOut` | old and new office in scope |
| `POST /admin/counsel-codes/{id}/deactivate`, `…/reactivate` | `admin.counsel_codes` | | `CounselCodeOut` | in scope |
| `GET /admin/counsel-codes/unmapped` | `admin.counsel_codes` | `?limit=` | `list[{code, entries, last_listed, example_case_ref}]` | court text only |
| `GET`, `POST /admin/keywords`; `PATCH /admin/keywords/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` (+ `admin.scoring` when `weight` given) | `KeywordIn {keyword, office_code, weight?}` | `KeywordOut {id, keyword, office, weight_override?, effective_weight, is_active}` | caller's subtree |
| `GET`, `POST /admin/name-patterns`; `PATCH /admin/name-patterns/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` (+ `admin.scoring` when `weight` given) | `NamePatternIn {pattern, kind, office_code, weight?}` | `NamePatternOut {id, pattern, kind, office, weight_override?, effective_weight, is_active}` | caller's subtree |
| `GET`, `POST /admin/watchlist`; `PATCH /admin/watchlist/{id}`; `…/deactivate`, `…/reactivate` | `admin.watchlist` (+ `admin.scoring` when `weight` given) | `WatchIn {cnr, office_code?, reason?, weight?}` | `WatchOut {id, cnr, case_ref?, office, reason, weight_override?, effective_weight, is_active}`; POST adds `dossier_queued` | caller's subtree |
| `GET /admin/matching/cases/{ref}/scores` | `cases.view_all` | | `list[{office {code, name}, score, band, signals, computed_at, engine_version}]` | State-wide readers only |

Router `api/routers/inbox.py` (prefix `/inbox`, tag `inbox`); `?office=` other than the caller's department
needs `cases.view_all`:

| Method, path | Function | Request | Response |
|---|---|---|---|
| `GET /inbox/recommended` | `cases.claim` (own department) or `cases.view_all` | `?office=`, `?band=high\|medium`, `?q=` | `{items: [RecommendationOut {id, case: CaseSummaryOut, score, band, origin, signals, suggested_by_office_code?, reason?, created_at, current_owner_code?}], total}` |
| `GET /inbox/claimed` | `cases.view_scope` (rows by decision 15) | `?office=`, `?case_state=active\|disposed\|all` (default `active`), `?role=primary\|watcher`, `?unit=`, `?officer_user_id=`, `?q=` | `{items: [OwnershipOut {id, case: CaseSummaryOut, office_code, role, unit {code, name}?, officer {id, full_name}?, claimed_at, allotted_at?}], total}` |
| `GET /inbox/pool` | `cases.claim` or `cases.view_all` | `?q=`, `?listed_from=`, `?listed_to=`, `?status=`, `?case_type=`, `?year=`, `?min_score=`, `?state_party=` | `{items: [PoolCaseOut {case: CaseSummaryOut, best_score?, best_office_code?, dismissed_by: [office_code]}], total}` |
| `GET /inbox/transfers` | `cases.transfer_request` or `cases.transfer_decide` (own) or `cases.view_all` | `?office=`, `?direction=in\|out`, `?status=` | `{items: [TransferOut {id, ref_no, case: CaseSummaryOut, from_office_code, to_office_code, status, reason, stay_as_watcher, decision_note?, requested_by, requested_at, decided_at?}], total}` |
| `GET /inbox/counts` | `cases.view_scope` | `?office=` | `{recommended_high, recommended_medium, claimed_active, claimed_disposed, transfers_in_open, pool_with_hearing_7d}` (a count is null when the caller lacks that tab's function) |

`CaseSummaryOut = {id, ref_no, cnr?, case_no_text?, is_provisional, petitioner_summary?, respondent_summary?,
status, next_hearing_date?, last_listed_on?}`.

Router `api/routers/ownership.py` (tag `ownership`):

| Method, path | Function | Request | Response |
|---|---|---|---|
| `GET /cases/{ref}/ownership` | `cases.view_scope` | | `{primary?: OwnershipOut, watchers: [OwnershipOut], recommendations: [RecommendationOut], open_transfer?: TransferOut}`. Visible when the caller's department owns, watches or has a recommendation for the case, or the case is in the pool and the caller holds `cases.claim`, or the caller holds `cases.view_all`; other departments' recommendations only with `cases.view_all` |
| `POST /cases/{ref}/claim` | `cases.claim` (+ `cases.allot` when `unit_code` / `officer_user_id` given) | `ClaimIn {office_code? (super admin), unit_code?, officer_user_id?, note?}` | 201 `OwnershipOut` (`role` tells primary or watcher) |
| `POST /cases/{ref}/dismiss` | `cases.dismiss` | `{reason?}` | `RecommendationOut` |
| `POST /cases/{ref}/suggest` | `cases.suggest_elsewhere` | `{office_code, reason}` | `{own?: RecommendationOut, target: RecommendationOut, target_already_recommended}` |
| `POST /cases/{ref}/allot` | `cases.allot` | `{unit_code?: str\|null, officer_user_id?: uuid\|null}` | `OwnershipOut` |
| `POST /cases/{ref}/take-over` | `cases.take_over` (caller in the owning department's subtree, else 404) | `{expected_officer_user_id?, reason?}` | `OwnershipOut` + `taken_from {id, full_name}` |
| `POST /cases/{ref}/stop-watching` | `cases.release` (the caller's department's watcher row; on a primary row → 409) | `{reason}` | `OwnershipOut` (`status: released`) |
| `POST /cases/{ref}/transfers` | `cases.transfer_request` | `{to_office_code, reason, stay_as_watcher?}` | 201 `TransferOut` |
| `POST /transfers/{trf}/accept`, `…/decline` | `cases.transfer_decide` (caller's department = `to_office`) | `{note?}` | `TransferOut` |
| `POST /transfers/{trf}/withdraw` | `cases.transfer_request` (caller's department = `from_office`) | | `TransferOut` |

There is no release endpoint for a primary owner (decision 10, *owner review 2026-10-04*). `main.py` includes the
three routers.

## Jobs
- Celery beat `rescore-dirty` → task `aslms.rescore_if_dirty` every 15 minutes (the `scheduler` service):
  rescores everything only when a rule, an office or the scoring settings changed since the last succeeded
  `rescore` run; a `job_runs` row `rescore`. A scoring-settings save also dispatches the task at once. No NAPIX
  call.
- No new `fetch_queue` kind. A watchlist add for an unknown CNR enqueues an existing `dossier` row (ref
  `<CNR>`, priority 40). Inline scoring runs inside the existing `causelist_day` and `dossier` items.

## Tests
Unit (`tests/unit/test_matching_rules.py`, no database):
- `normalise_counsel_code`: `SC,EDU`, `sc , edu`, `SC, EDU,` → `SC, EDU`; `DY.S.G.I.` unchanged;
- `combine`: a single weight passes through; pattern 0.8 + keyword 0.4 = 0.880; two keywords = 0.400 (maximum
  within a kind); never above 1; `band_of` at the defaults at 0.499 / 0.500 / 0.849 / 0.850, and with custom
  settings (strong 0.900, possible 0.600) at 0.599 / 0.600 / 0.899 / 0.900;
- `score_case` on hand-built rule sets and evidence: a counsel code → 0.950 high; a generic code → nothing; a
  directorate rule rolls up to its department with `suggested_unit`; keywords match whole words only
  (`EDUCATION` matches, `REEDUCATIONAL` does not); exact / prefix / regex patterns; rules of an inactive office
  ignored; signals carry `kind`, `rule_id`, `matched`, `where`, `ref` and the effective `weight`;
- effective weight: a rule without an override uses the setting; an override wins; a keyword setting of 0.500
  makes a keyword-only score 0.500 (medium at the default thresholds); `engine_version` is `1.<version>`;
- regex validation refuses an uncompilable pattern, a 301-character one and `.*` (matches the empty string).

Database (`tests/db/test_scoring_settings.py`, *owner review 2026-10-04*):
- `aslms seed` on an empty table inserts version 1 with the plan defaults, and a second run inserts nothing;
  `current()` on an empty table returns the defaults as version 0;
- the super admin's update inserts version 2, closes version 1 (`is_current = false`, `valid_to` set), and writes
  one audit row `scoring_settings.update` with before/after and one `config_changed` event;
- a dept admin (no `admin.scoring`) → `Forbidden`; a user granted `admin.scoring` through `user_permissions` can
  update;
- a stale `expected_version` → `StaleSettings`; an identical save writes no row, audit or event; weights 0 and
  1.2, `possible ≥ strong` and a missing reason → `SettingsError`; the CHECKs reject a direct INSERT with
  `threshold_possible = 0.9, threshold_strong = 0.8`; the partial index rejects a second `is_current` row;
- raising `threshold_strong` to 0.960 and running `rescore_all` turns a 0.950 counsel-code recommendation from
  `high` to `medium` (one `recommendation_made` event) and writes `engine_version = '1.2'`; raising
  `threshold_possible` above a medium score expires that engine recommendation and leaves a `suggestion` row
  untouched;
- `rescore_if_dirty` runs after a settings change and not again on the next tick.

Database (`tests/db/test_matching.py`):
- `apply_entries` over a parsed list with `SC, EDU` mapped to `EDU` writes a `case_office_scores` row and a
  `recommended` high recommendation with origin `cause_list` and one `recommendation_made` event; loading the
  same list again writes nothing new (idempotent);
- a keyword-only case gets a 0.400 score row and no recommendation (pool);
- `apply_dossier` adding a respondent matching a name pattern gives 0.800 (medium) alone and high with the keyword;
- a scoring exception is recorded in `source_failures` (kind `scoring`) and the cause-list item still commits;
- deactivating the code and running `rescore_all` expires the engine recommendation, leaves a `suggestion`
  recommendation untouched, deletes the zero score row and writes a `job_runs` row with counters;
- `rescore_if_dirty` does nothing when no rule changed since the last run and runs after a keyword edit;
- a department that dismissed a case is not re-recommended by a rescore, nor one that claimed it as a watcher
  and stopped watching;
- linked case: claiming the main matter raises the linked case's score for the claimant (`linked_case` signal);
- `unmapped_codes` lists an unmapped `SC, REVENUE` with its count and omits mapped and generic codes.

Database (`tests/db/test_matching_rules_admin.py`):
- each rule's create / update / deactivate / reactivate writes its audit row and a `config_changed` event;
  duplicates → `DuplicateRule`; re-adding a deactivated rule reactivates it;
- an `EDU` dept admin cannot map a code to `HEALTH` (`Forbidden`), can map one to `EDU-DSE`, cannot create a
  generic code; a dept officer without `admin.counsel_codes` gets `Forbidden`;
- a dept admin creating a rule without `weight` stores NULL; the same with `weight` → `Forbidden`; the super
  admin sets and clears an override; weights 0 and 1.2 refused by the service, and the CHECK constraint rejects a
  direct UPDATE to 1.5;
- watchlist: a malformed CNR refused; an unknown CNR enqueues one `dossier` row and returns `queued=True`; a held
  CNR scores the case inline with origin `watchlist`.

Database (`tests/db/test_ownership.py`):
- claim from the pool → primary, recommendation `claimed`, audit `ownership.claim`, event `claimed`, a custody row
  at `EDU` and one `custody_history` leg (`claimed`); a second department with a recommendation claims →
  `watcher`, custody unchanged; the same department again → `OwnershipConflict`; a department without a
  recommendation on an owned case → `NotVisible`;
- two concurrent claims on a pool case (two sessions) end with exactly one primary (the partial index);
- claim with `unit_code=EDU-DSE` and an officer: one call, two audit rows (`ownership.claim`, `ownership.allot`),
  custody at `EDU-DSE` with the officer; a unit of another department refused;
- dismiss without a recommendation → `NotVisible`; with one → `dismissed`, reason kept, audit, event;
- suggest: own recommendation `suggested_elsewhere` with `suggested_office_id`; the target gets an active
  `suggestion` row even after an earlier dismissal; a target already owning → conflict; a target already
  recommended → flag true and no second row; the central operator (no own recommendation) can suggest a pool case;
- allot by a watcher changes only its own row and moves no custody; clearing with `null` works; an auditor as
  officer is refused;
- no return to the pool (*owner review 2026-10-04*): `stop_watching` on the primary row →
  `OwnershipConflict('primary_cannot_release')` and nothing written; a watcher stops watching → `released`,
  `release_reason` stored, audit `ownership.unwatch`, event `ownership_released`, primary and custody unchanged;
  the CHECK rejects a direct UPDATE setting a primary row to `released`; after an accepted transfer the case is
  not in the pool and the old department holds no active primary;
- take over (*owner review 2026-10-04*): an `EDU` dept officer takes over a case allotted to another `EDU`
  officer → `officer_user_id` and `allotted_by_user_id` are the taker, audit `ownership.take_over` with
  before/after, one `case_taken_over` event with `from_user_id` / `to_user_id`, custody holder user the taker
  (reason `taken_over`); a directorate user of `EDU-DHE` taking over a case allotted within `EDU-DSE` moves the
  unit and custody to `EDU-DHE`; a directorate user of `EDU-DSE` keeps the unit `EDU-DSE`; a user at the `EDU`
  office clears the unit; a `HEALTH` user → `NotVisible`; the super admin → `NotVisible`; a case with no officer
  allotted → conflict `not_allotted`; the current holder → conflict; a stale `expected_officer_user_id` →
  conflict; a referral reviewer (no `cases.take_over`) → `Forbidden`; on a watcher row no custody moves;
- transfers: request by a watcher refused; a request gets `ref_no` `ASLMS/EDU/TRF/<yyyy>/000001`; a second open
  request → conflict; accept → old row `transferred`, the target primary (its watcher row promoted when it
  existed), `stay_as_watcher` adds an `EDU` watcher row, custody to the target; decline keeps ownership and stores
  `decision_note`; withdraw only by the requesting department; a decision by a third department → `NotVisible`;
- every action leaves exactly the expected `audit_log` rows (action, `case_id`, `entity_id`) and none on refusals;
- seed (*owner review 2026-10-04*): `ref_permission` has `admin.scoring` and `cases.take_over`, and
  `cases.release` carries the label "Stop watching"; `role_permissions` enables `cases.take_over` for exactly
  `dept_head`, `dept_admin`, `dept_officer`, `directorate_user`, and `admin.scoring` for no type;
  `ref_event_type` has `case_taken_over` as a tracking card;
- migration 0004: `scoring_settings`, the five partial indexes and the CHECKs exist; the rule weights are
  nullable; the existing upgrade → downgrade → upgrade test covers the new revision.

API (`tests/db/test_api_inbox.py`, `TestClient` as in `test_api_offices.py`):
- `EDU` dept admin: `/inbox/recommended` lists only `EDU` rows, high before medium, with signals;
  `?office=HEALTH` → 403; a state-oversight user with `?office=EDU` → 200 (read-only) and `POST …/claim` → 403;
- `/inbox/claimed`: the dept admin sees all of `EDU`'s ownership; a directorate user of `EDU-DSE` sees only cases
  allotted to `EDU-DSE`; a dept officer only cases allotted to them; a `HEALTH` user none of `EDU`'s (visibility);
  the default `case_state=active` hides a disposed case, `?case_state=disposed` shows only it, `all` both;
  `/inbox/counts` gives `claimed_active` and `claimed_disposed` matching the lists;
- `/inbox/pool` excludes owned and once-owned cases, includes dismissed and low-score ones, filters by `q`,
  `state_party`, `min_score`; a dept officer without `cases.claim` → 403;
- `/inbox/transfers?direction=in` for the target lists the request; `/inbox/counts` agrees with the tabs;
- `POST /cases/{ref}/claim` accepts the id, the `ref_no` (dash form) and the CNR; an unknown ref → 404; a second
  claim → 409; `GET /cases/{ref}/ownership` as a `HEALTH` user with no recommendation on an `EDU`-owned case → 404;
- `POST /cases/{ref}/take-over` → 200 for an `EDU` officer, 404 for a `HEALTH` officer, 409 when not allotted;
  `POST /cases/{ref}/stop-watching` → 409 for the primary department, 200 for a watcher; there is no
  `/cases/{ref}/release` route;
- `GET /admin/scoring-settings` → 200 for the super admin and an `EDU` dept admin, 403 for a dept officer;
  `PUT` → 200 with `changed: true` for the super admin, 403 for the dept admin, 409 on a stale
  `expected_version`, 400 on `possible ≥ strong`; `GET …/history` lists both versions;
- rule endpoints: 201 / 409 / 403 / 404 outside scope as in the admin tests; 403 for a dept admin sending
  `weight`; 401 without a token.

`tests/unit/test_schema_metadata.py` and `test_database_matches_the_models` stay green with the new table,
columns, checks and indexes.

## Verification
From the repository root with Compose up (`docker compose up -d postgres redis api worker scheduler`) on the
development database that holds the loaded January 2025 days:
1. `docker compose run --rm api alembic upgrade head` → revision `0004`; `\d case_ownership` shows the three new
   columns and `ix_case_ownership_active_primary`; `\d scoring_settings` exists; `alembic downgrade -1 && alembic
   upgrade head` succeeds.
2. `docker compose run --rm api aslms seed` → `SELECT version, threshold_strong, threshold_possible FROM
   scoring_settings WHERE is_current` gives `1 | 0.850 | 0.500`; `SELECT code, label FROM ref_permission WHERE
   code IN ('admin.scoring', 'cases.take_over', 'cases.release')` gives the three labels of decision 20.
3. As the super admin: create `EDU` (department), `EDU-DSE` and `EDU-DHE` (directorates) and `HEALTH`
   (department) if absent, an `EDU` and a `HEALTH` dept admin, two `EDU` dept officers and an `EDU-DHE`
   directorate user.
4. `docker compose run --rm api aslms codes unmapped --limit 20` → the most frequent codes of the loaded lists
   (expect `GA, ASSAM` and several `SC, …` codes); record the top five in the cycle report.
5. As the super admin, `POST /admin/counsel-codes {"code":"GA, ASSAM","office_code":"GOA","is_generic_state":true}`
   → 201. As the `EDU` admin, `POST /admin/counsel-codes {"code":"<the education code seen in step 4>",
   "office_code":"EDU"}` → 201 with `effective_weight` 0.950; `POST /admin/keywords {"keyword":"SECONDARY
   EDUCATION","office_code":"EDU"}` → 201; mapping a code to `GOA` as the `EDU` admin → 403; a POST with
   `"weight":0.9` as the `EDU` admin → 403.
6. `docker compose run --rm api aslms rescore --all` → counters printed; `SELECT band, status, count(*) FROM
   recommendations GROUP BY 1, 2` shows high rows for `EDU`, and their number equals
   `SELECT count(DISTINCT case_id) FROM causelist_entries WHERE '<code>' = ANY(counsel_codes)` plus the cases where
   the code appears only in a dossier; no recommendation exists for `GOA`; `SELECT DISTINCT engine_version FROM
   case_office_scores` → `1.1`.
7. As the super admin, `GET /admin/scoring-settings` → version 1; `PUT` with `threshold_strong` 0.960 (other
   values unchanged), a reason and `expected_version: 1` → version 2, `rescore_dispatched: true`; within a few
   minutes a `job_runs` row `rescore` succeeds, the `EDU` counsel-code recommendations are `medium` and
   `engine_version` is `1.2`; an audit row `scoring_settings.update` and a `config_changed` event exist; the same
   `PUT` as the `EDU` admin → 403. `PUT` back to 0.850 with `expected_version: 2` → version 3; after the rescore
   the bands are `high` again.
8. As the `EDU` admin: `GET /inbox/recommended` → items high first, each with a `counsel_code` signal showing the
   list date and serial; `POST /cases/<first ref>/claim` with `officer_user_id` = the first `EDU` officer → 201
   `role=primary`; `GET /inbox/claimed` lists it under the default `case_state=active`; `SELECT holder_office_id,
   holder_user_id FROM custody WHERE case_id = …` → `EDU`, the first officer. Claim a recommended disposed case
   too and check it appears only with `?case_state=disposed` and in `claimed_disposed`.
9. As the second `EDU` officer, `POST /cases/<first ref>/take-over {"reason":"holder on leave"}` → 200 with
   `taken_from` = the first officer; the custody holder user is the second officer; an `events` row
   `case_taken_over` names both. As the `EDU-DHE` directorate user, take it over again → unit `EDU-DHE`, custody at
   `EDU-DHE`. As the `HEALTH` admin, the same call → 404.
10. `POST /cases/<second ref>/dismiss`; `POST /cases/<third ref>/suggest {"office_code":"HEALTH","reason":"…"}` →
    the third case appears in the `HEALTH` admin's `/inbox/recommended` with origin `suggestion`.
11. As the `EDU` admin, `POST /cases/<first ref>/stop-watching {"reason":"…"}` → 409; `POST /cases/<first
    ref>/transfers {"to_office_code":"HEALTH","reason":"…"}` → `ref_no` `ASLMS/EDU/TRF/2026/000001`; as the
    `HEALTH` admin `POST /transfers/<id>/accept` → `HEALTH` primary, custody at `HEALTH`; the case is not in
    `/inbox/pool`.
12. After a keyword edit, wait one beat interval (or call the task `aslms.rescore_if_dirty`) → a new `job_runs`
    row `rescore` with `status=succeeded`; without an edit the next tick writes none.
13. `SELECT action, count(*) FROM audit_log WHERE action ~
    '^(ownership|transfer|recommendation|counsel_code|keyword|scoring_settings)\.' GROUP BY 1` matches the
    actions taken above; `pytest -q` green; `ruff check` clean.

## Deviations
Written by the developer while building (4 Oct 2026); each is the smallest option where the note was silent
or where two of its paragraphs did not agree.
1. **A State-wide reader without a department must name `?office=`** on `/inbox/recommended`,
   `/inbox/claimed` and `/inbox/transfers` (400 `office is required`); the note gives `?office=` for "any
   office" but says nothing about the default for a caller who has no department. `/inbox/counts` for such a
   caller returns the department counts as `null` and the pool count. A `cases.view_all` holder reading their
   own department (if any) sees the whole department.
2. **`rescore_dispatched` reports the real dispatch.** The settings `PUT` commits the session itself when a
   new version was written and then dispatches `aslms.rescore_if_dirty` synchronously (`send_task`, no retry),
   so the response says what happened. With no broker configured (`REDIS_URL` unset, as in the tests) the
   dispatch is skipped and `rescore_dispatched` is `false`; the 15-minute beat picks the change up either way.
   The test replaces `matching_router.dispatch_rescore`.
3. **The pool's `state_party` filter runs in SQL** with a normalisation expression that mirrors
   `normalise_counsel_code` (upper case, whitespace collapsed, `, ` after commas, trailing commas stripped)
   over `causelist_entries.counsel_codes` and current `case_advocates.counsel_code`, compared with the active
   `counsel_codes` (generic and mapped). Decision 3's "no SQL is built from rule text" concerns scoring; the
   codes are bound as parameters, never interpolated. `state_party=false` gives the complement.
4. **Pool filters.** `case_type` compares `cases.case_type_text` case-insensitively; `year` is `cases.reg_year`;
   `min_score` is any department's `case_office_scores.score`; `q` shorter than 3 characters → 400. `limit`
   above 200 is clamped to 200 rather than refused.
5. **Claimed-tab filters.** `?unit=` must be an office strictly inside the department (400 otherwise);
   `?role=primary|watcher`; `?officer_user_id=`. The list is ordered by next hearing date (nulls last), then
   newest claim.
6. **Rule endpoints outside the caller's subtree are 404** (`PATCH`, `deactivate`, `reactivate`), as the API
   paragraph requires; a generic State code is loadable by every holder of `admin.counsel_codes` (read-only in
   the list) and a write on it by a non-super-admin is the service's 403. Unknown `office_code` in a body → 400.
7. **Response shapes carry a few fields beyond the table** so the portal needs no second call:
   `RecommendationOut.office_code` and `status`; `OwnershipOut.status`, `released_at`, `release_reason`;
   `TransferOut.decided_by`, `withdrawn_at`. `OwnershipOut.unit` and `officer` are `{code, name}` /
   `{id, full_name}`. The 409 body of the ownership endpoints is `{code, message}` (`already_claimed`,
   `primary_cannot_release`, `not_allotted`, …) so a screen can act on the code.
8. **`GET /admin/scoring-settings` on an empty table** returns version 0 with the defaults, `reason` and
   `valid_from` null (the seeded database always has version 1).
9. **The CLI has no tests of its own** (`aslms rescore`, `aslms codes unmapped` wrap the tested services and were
   checked with `--help`); like the other CLI groups.
10. **No new Compose service or variable.** The `scheduler` service already runs beat (the `rescore-dirty` entry
    is in its comment); the `api` service already has `REDIS_URL`, so the settings save dispatches in Compose.
11. **"Has ever claimed" is read from `case_ownership`, not only from `claimed` recommendations** (review
    finding, 4 Oct 2026). A claim from the pool writes no recommendation row, so decision 5's "never re-opened by
    the engine" was only enforced for departments that had been recommended first. `apply_scores` now blocks
    every office with any `case_ownership` row for the case, whatever its status (`active`, `transferred`,
    `released`), in addition to the `dismissed` / `suggested_elsewhere` / `claimed` recommendation statuses.
    Test: `test_pool_claim_without_recommendation_blocks_the_engine_after_transfer`.

## Open questions
None. Points the owner may wish to overrule at approval:
- decision 10 (owner review 2026-10-04), a **watcher** may still stop watching (`cases.release`, relabelled
  "Stop watching"); only the primary owner can never let go except by an accepted transfer;
- decision 11, minimal custody moves written now (ahead of `custody-workflow`) so that alerts find a holder;
- decisions 13 and 21 (owner review 2026-10-04), per-rule weight overrides are kept but only `admin.scoring`
  holders may set them; department admins create rules at their kind's setting;
- decision 15, the Recommended tab and the pool are shown only to holders of `cases.claim` (department admins and
  heads), not to every officer;
- decision 18 (**deviation, scope**), department discovery through Search by Party Name stays in backlog row 19;
- decision 21 (**deviation**), the thresholds of plan §4.2 and CLAUDE.md become defaults the super admin can
  change; CLAUDE.md needs the owner's wording change;
- decision 22 (owner review 2026-10-04), take-over requires an existing officer allotment, moves the unit to the
  taker's office when the taker sits outside the current unit, and lets a directorate user take over a case of a
  sibling directorate in the same department.
