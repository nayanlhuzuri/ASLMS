# Design: Recommend and claim — matching rules, the scoring engine, recommendations, ownership actions, the case inbox

```
slug: recommend-and-claim
status: awaiting-approval
author: architect
date: 2026-10-04
approved_by: (pending)
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
  are documented in `schema.md` but not enforced by the database.
- All functions exist in `Permission` and in the default matrix (`access_seed.py`): `admin.counsel_codes`,
  `admin.keywords`, `admin.watchlist` (dept admin; watchlist also central operator), `cases.claim`,
  `cases.dismiss`, `cases.suggest_elsewhere`, `cases.transfer_request`, `cases.transfer_decide`, `cases.allot`,
  `cases.release` (dept admin and dept head; `cases.suggest_elsewhere` also central operator),
  `cases.view_scope`, `cases.view_all`.
- Event types `recommendation_made`, `claimed`, `dismissed`, `suggested_elsewhere`, `transfer_requested`,
  `transfer_decided`, `ownership_released`, `allotted`, `custody_moved`, `config_changed`; record type `TRF`.
- The pipeline writes `causelist_entries` (`counsel_codes text[]`, `petitioner_text`, `respondent_text`,
  `case_id`) in `services/causelists.py::apply_entries`, and dossiers (`case_parties`,
  `case_advocates.counsel_code`, `case_links`) in `services/cases.py::apply_dossier`. A case without a CNR keeps
  its row when the CNR arrives (`get_or_create_case` fills it in place), so ownership on such a case is never
  orphaned.
- `services/offices.py` (`DEPARTMENT_TIER_KINDS`, `tier_of`, `find_office`), `services/access.py` (`require`,
  `has`, `in_scope`, `is_super_admin`, `actor_for`), `services/audit.py::write_audit`,
  `services/cases.py::emit_event` and `normalise_name`, `services/refno.py::allocate_ref_no`,
  `services/queue.py::enqueue`.
- Earlier decisions in the log that this design follows: recommendations go to departments, and signals on a
  directorate roll up to its department with the directorate kept as the suggested unit; generic State codes
  (`PP, ASSAM`, `GA, ASSAM`) add nothing; a department's dismissal or claim is never re-opened by the engine;
  allotment to a unit and/or officer after claiming; custody is derived (claim → department, allotment → unit
  and/or officer, transfer accepted → new department, release → next primary owner).

Not covered: department discovery through NAPIX Search by Party Name (decision 18, new backlog row 19);
alerts and notifications for recommendations and ownership events (`alerts-notifications` reads the events this
item writes); the full case visibility rule and the case detail (`cases-api`); requests and hand-overs
(`custody-workflow`); the portal screens (`portal-cases`); tuning weights from claims and dismissals (dropped
from scope, decisions log "Superseded decisions").

## Decisions
1. **Scores and recommendations are per Department-tier office** (`department`, `central`, `advocate_general`;
   `offices.DEPARTMENT_TIER_KINDS`). A rule attached to a directorate or unit counts for its Department-tier
   ancestor (the second segment of `offices.path`); the most specific office of the strongest hit is kept as
   `suggested_unit` in the signals and offered as the default unit at claim time. Rules on inactive offices, and
   rules whose Department-tier ancestor is inactive, are ignored. Alternative: recommend to directorates
   directly — rejected by the 26 Sep decision; a directorate is reached by allotment.
2. **The score formula** (the plan names the signals and the bands but not the arithmetic; this is the proposal
   for approval). For each department, take the strongest weight within each signal kind, then combine the kinds
   by "noisy OR": `score = 1 − Π (1 − w_kind)`, rounded to 3 decimals. Weights:

   | Signal kind | Weight | Alone gives | Source of the weight |
   |---|---|---|---|
   | `counsel_code` | the rule's `weight`, default 0.950 | strong | `counsel_codes.weight` (schema default) |
   | `name_pattern` | the rule's `weight`, default 0.800 | possible | `office_name_patterns.weight` (schema default) |
   | `watchlist` | the rule's `weight`, default 0.750 | possible | `office_watchlist.weight` (schema default) |
   | `linked_case` | 0.700 (engine constant) | possible | `matching.LINKED_CASE_WEIGHT` |
   | `keyword` | the rule's `weight`, default 0.400 | pool | `office_keywords.weight` (schema default) |

   Examples: pattern + keyword = 0.880 (strong); keyword + linked case = 0.820 (possible); two keywords = 0.400
   (the maximum within a kind, so repeated weak hits never add up to a recommendation). Weights are editable per
   rule in (0, 1]. Band: `high` when score ≥ 0.850, `medium` when 0.500 ≤ score < 0.850, no recommendation
   below 0.500. `ENGINE_VERSION = "1"` is written on every score row. Alternatives: a weighted sum capped at 1
   (one strong and one weak signal saturate at once and the kinds lose their meaning), a trained model (no
   labelled data; tuning from claims was dropped from scope).
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
   (b) After a claim, transfer accept or release, for the cases linked to that case (linked-case signal).
   (c) After a watchlist add or change, for that case. (d) The **dirty rescore**: a Celery beat task every
   15 minutes compares the latest `created_at` / `updated_at` of `counsel_codes`, `office_keywords`,
   `office_name_patterns`, `office_watchlist` and `offices` with the start of the last succeeded `job_runs` row
   `rescore`; when a rule is newer it rescores every non-merged case in batches of 500 (one commit per batch,
   counters in `job_runs`). (e) `aslms rescore [--all | --case REF]` by hand. Rule edits therefore take effect
   within 15 minutes; the API response says so. Alternatives: rescore inline on every rule edit (a counsel-code
   change touches tens of thousands of cases inside one HTTP request); a new `fetch_queue` kind (that queue is
   NAPIX work, and its kinds are a native enum).
5. **Recommendation lifecycle (engine side).** For every (case, department) with score ≥ 0.50:
   - nothing is written when the department already has an active `case_ownership` row for the case, or has
     **ever** dismissed it (`dismissed`, `suggested_elsewhere`) or claimed it (`claimed`) — "never re-opened by
     the engine";
   - otherwise the active `recommended` row is created (event `recommendation_made`) or its `score` / `band`
     updated (a new `recommendation_made` event only when the band changes). Origin: `cause_list` from
     `apply_entries`; from `apply_dossier` the case's `first_seen_source` mapped `causelist → cause_list`,
     `search → search`, otherwise `rescore`; `watchlist` for (c); `rescore` for (b), (d), (e).
   An active engine-made row (origin other than `suggestion`) whose score falls below 0.50 becomes `expired`
   (`acted_at` set). Rows of a case with `merged_into_case_id` are expired. Engine writes carry the system actor
   snapshot (`actor_name = 'matching'`) and write **no** `audit_log` rows (they are not user actions; events and
   `case_office_scores` are their record). `case_office_scores` keeps only rows with score > 0; rows that drop
   to 0 are deleted (a derived table on the cascade list, where `aslms_app` holds DELETE).
   Recommendations stay open when another department claims the case (the plan: several departments may claim;
   the second becomes a watcher); the inbox shows the current owner beside them.
6. **Claim.** `cases.claim`. The claim is for the actor's department (the Department-tier ancestor of the
   actor's office); a super admin, who sits at `GOA`, must name `office_code`. Allowed when the case has no active
   primary owner (the pool) or the department has an active `recommended` row; otherwise 404 (the case is not
   visible to it) — taking a case another department owns, without a recommendation, is a transfer. Under a row
   lock on the case (`SELECT … FOR UPDATE` on `cases`): no active primary → the new row is `primary`; an active
   primary of another department → `watcher`; the department already active on the case → 409. The
   department's active recommendation becomes `claimed` (`acted_at`). Optional `unit_code` / `officer_user_id`
   allot in the same step (needs `cases.allot` too; decision 9). Audit `ownership.claim`; event `claimed`
   (`tracking_card`); custody per decision 11 when primary.
7. **Dismiss and suggest elsewhere.** `cases.dismiss` sets the department's active recommendation to
   `dismissed` with an optional `reason` (no active recommendation → 404). `cases.suggest_elsewhere` takes
   `office_code` (an active Department-tier office other than the actor's) and a required `reason`: the actor's
   active recommendation, if any, becomes `suggested_elsewhere` with `suggested_office_id`; the target gets an
   active `recommended` row with origin `suggestion`, its engine score (0 when none), band `high` if that score
   ≥ 0.85 else `medium`, the suggesting user in the actor snapshot and the reason — even when the target dismissed
   the case before (a human suggestion is not the engine re-opening it). Refused (409) when the target actively
   owns the case; when the target already has an active recommendation it is left as it is and the response says
   `target_already_recommended: true`. The central operator (who holds `cases.suggest_elsewhere` and has no
   recommendation of their own) uses this to route pool cases. Audit `recommendation.dismiss` /
   `recommendation.suggest`; events `dismissed` / `suggested_elsewhere` (+ `recommendation_made` for the target).
8. **Transfers.** Only the primary owner's department may request (`cases.transfer_request`):
   `to_office_code` (an active Department-tier office, not itself), a required `reason`, `stay_as_watcher`
   (default false). One open request per case (partial unique index); `ref_no` `ASLMS/<from office>/TRF/<yyyy>/<n>`.
   The target decides (`cases.transfer_decide`): **accept** → the old primary row becomes `transferred`
   (`released_at`); the target's active watcher row, if any, is promoted to `primary`, else a new primary row is
   inserted; with `stay_as_watcher` the old department gets a new `watcher` row; custody moves to the target.
   **Decline** → `declined` with `decision_note`. The requester's department may **withdraw** while `requested`
   (`withdrawn_at`). `decided_by_user_id` and `decided_at` are set on accept and decline. Releasing a primary with
   an open request is refused (withdraw first). Audit `transfer.request` / `transfer.accept` / `transfer.decline` /
   `transfer.withdraw`; events `transfer_requested`, `transfer_decided` (payload `decision`).
9. **Allot.** `cases.allot`, on the actor's department's active ownership row (primary or watcher):
   `unit_code` — an active office strictly inside the department's subtree; `officer_user_id` — an active user
   whose office is in the department's subtree, of any type except `super_admin`, `state_oversight`, `auditor`,
   `central_operator`; either may be cleared with `null`. Sets `allotted_at` and `allotted_by_user_id` (new
   columns). Re-allotment overwrites; the history is in `audit_log` (`ownership.allot`, before/after) and in the
   `allotted` events. Custody per decision 11 when the row is primary.
10. **Release.** `cases.release`, required `reason` (kept in the new `release_reason`). A watcher row simply
    becomes `released`. A primary row becomes `released`; the earliest-claimed active watcher, if any, is
    promoted to primary (its own claim is its consent, as the 26 Sep decision "release → the next primary owner"
    says), otherwise the case returns to the pool. The releasing department's recommendation stays `claimed`, so
    the engine does not recommend the case to it again; it can still claim it from the pool. Audit
    `ownership.release` (+ `ownership.promote` for the successor, with the releasing actor); events
    `ownership_released`, and `claimed` with payload `promoted: true` for the successor.
11. **Custody follows primary ownership only** — minimal, written by this item because alerts (backlog row 5,
    before `custody-workflow`) go to the custody holder and must find one. `services/custody.py::move_custody(
    session, actor, case, *, office, user=None, reason)` upserts `custody` (holder, `since`,
    `pending_action='none'`), appends a `custody_history` leg (`seq_no` = max + 1 under the case lock; office code
    and user name snapshots; actor snapshot) and emits `custody_moved` (`tracking_card`). Reasons: `claimed`
    (department office), `allotted` (unit office if set, else the department; holder user = the officer),
    `transferred` (target department), `released` (successor's department), `returned_to_pool` (root `GOA`, so a
    department is never left holding a case it released, and can later be deactivated). Watcher rows never move
    custody. `custody-workflow` later adds requests and hand-overs on the same function.
12. **Uniqueness in the database** (migration 0004, partial unique indexes): one active primary per case; one
    active row per (case, office); one active `recommended` row per (case, office); one `requested` transfer per
    case. The services check first (clean 409s); the indexes catch races (`IntegrityError` → 409).
13. **Who manages the rules.** `admin.counsel_codes` for counsel codes; `admin.keywords` for keywords and name
    patterns; `admin.watchlist` for the watchlist. A non-super-admin acts only on rules whose office is in their
    subtree (`access.in_scope`), so a department admin maps codes to the department or its directorates, never to
    another department. Generic State codes (`is_generic_state = true`) must be mapped to the root `GOA`, so only
    the super admin creates them. Uniqueness as in the schema (`counsel_codes.code` globally — one code, one
    office; (office, keyword); (office, pattern, kind); (office, cnr)); re-adding a deactivated rule reactivates
    it (audited as `*.reactivate`). A counsel code may be re-pointed to another office in scope (`office_code` in
    PATCH, audited) because the code is unique. Rules are deactivated, never deleted.
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
    - *Claimed*: the active ownership rows of the department. Whole department for callers holding `cases.claim`
      or `cases.allot`; otherwise rows allotted to the caller (`officer_user_id`), or to a unit in the caller's
      subtree when the caller sits below the department (a directorate user sees its directorate's cases, an
      officer the cases allotted to them — plan Table 1). Requires `cases.view_scope`; `?office=` needs
      `cases.view_all`.
    - *Unclaimed pool*: non-merged cases with no active primary owner (dismissed and low-score cases included),
      filters `q` (CNR, case number, party text; ≥ 3 characters), `listed_from` / `listed_to`, `status`,
      `case_type`, `year`, `min_score` (any department's), `state_party` (a generic or mapped counsel code
      appears); ordered by next hearing date ascending (nulls last), then first seen. Requires `cases.claim` or
      `cases.view_all` (the plan: any department can search and claim; the central operator follows up).
    - *Transfers*: `direction=in|out`, `status`. Requires `cases.transfer_request` or `cases.transfer_decide` for
      the own department, `cases.view_all` for any.
    - *Counts* for the dashboard (`recommended_high`, `recommended_medium`, `claimed`, `transfers_in_open`,
      `pool_with_hearing_7d`), each under the rule of its tab.
    Lists are paginated (`limit` ≤ 200, default 50; `offset`) and return `{items, total}`.
16. **`services/visibility.py`** holds `department_of(session, office)` and `owned_case_filter(session, user)`
    (the Claimed-tab predicate of decision 15, in SQL), so that `cases-api` extends them (custody, requests,
    counsel) instead of re-deriving ownership scope.
17. **`resolve_case_ref(session, ref)`** in `services/cases.py`: accepts the case id, the `ref_no` (also in the
    URL form `ASLMS-GOA-CASE-2026-001842`) or the CNR (DB_STANDARD §3); unknown → 404. Used by every endpoint here
    and by `cases-api`.
18. **Department discovery is deferred — deviation (scope), flagged for the owner.** Plan §5.4 lists "Party Name
    Search APIs" beside Cause List Details as inbox inputs (department party names run periodically through
    NAPIX Search by Party Name). It needs a new `fetch_queue` kind (a native enum, so a migration), a share of
    the 1,000-calls-an-hour quota beside the historical load, and the keyword rules this item creates. It becomes
    backlog row 19 `department-discovery`; the cases it finds will be scored by this engine unchanged. Every case
    listed in a cause list — the plan's main source — is covered now.
19. **Unmapped codes report.** `GET /admin/counsel-codes/unmapped` lists the codes seen in cause lists and
    dossiers that have no mapping (normalised, with entry count, last listed date and one example case ref), so
    departments can compile the mapping from the cause lists as the decisions log requires. Nothing is mapped
    automatically.
20. **No new function, no seed change.** All the functions used here exist; the default matrix is unchanged.

## Data
Migration **0004_ownership_rules** (new; 0001–0003 untouched). The models in `domain/ownership.py` gain the same
columns, `CheckConstraint`s and `Index(..., unique=True, postgresql_where=...)` entries so
`test_database_matches_the_models` stays green.

For `docs/schema/schema.md`, Group 5 (as built, recommend-and-claim, migration 0004):
- `counsel_codes` (master) — `code` stored normalised (`SC, EDU`), unique; `office_id` → `offices` RESTRICT
  (any office; its Department-tier ancestor receives the score); `is_generic_state` rows are mapped to `GOA` and
  score nothing; CHECK `ck_counsel_codes_weight` (`weight > 0 AND weight <= 1`); deactivated, never deleted;
  `created_by` / `updated_by`.
- `office_keywords`, `office_name_patterns` (master) — CHECK `weight > 0 AND weight <= 1`
  (`ck_office_keywords_weight`, `ck_office_name_patterns_weight`); keywords and exact/prefix patterns stored
  normalised (upper case, dots as spaces, whitespace collapsed); regex patterns validated by the service;
  `created_by` / `updated_by`.
- `office_watchlist` (master) — CHECK `ck_office_watchlist_weight`; `cnr` a 16-character CNR checked by the
  service; `case_id` (→ `cases` RESTRICT) filled when the case is held; actor snapshot.
- `case_office_scores` (derived, CASCADE → cases) — one row per (case, Department-tier office) with score > 0;
  `signals` is a JSON array of `{kind, rule_id, rule_office_code, weight, matched, where, ref}`, `kind` ∈
  `counsel_code`, `keyword`, `name_pattern`, `linked_case`, `watchlist`; `matched` is the code, keyword, pattern
  or linked case number; `where` ∈ `causelist_entry`, `case_advocates`, `case_parties`, `case_summary`,
  `case_links`, `watchlist`; `ref` is the entry's `{list_date, sr_no}`, the party `{role, party_no}` or the linked
  case `ref_no`; plus one element `{kind: "suggested_unit", office_code}` when the strongest rule sat below the
  department. `engine_version` `"1"`.
- `recommendations` (transaction) — `office_id` is always a Department-tier office; partial unique index
  `ix_recommendations_active` UNIQUE (`case_id`, `office_id`) WHERE `status = 'recommended'`; CHECK
  `ck_recommendations_score_range` (`score >= 0 AND score <= 1`); engine rows carry the system actor snapshot
  (`actor_name = 'matching'`), suggestion rows the suggesting user; `expired` is set by the engine when an engine
  score drops below 0.50 or the case is merged. FKs RESTRICT (unchanged).
- `case_ownership` (transaction) — new columns `allotted_at timestamptz NULL`, `allotted_by_user_id uuid NULL`
  → `users` ON DELETE SET NULL (an actor column, like `officer_user_id`), `release_reason text NULL`; partial
  unique indexes `ix_case_ownership_active_primary` UNIQUE (`case_id`) WHERE `status = 'active' AND role =
  'primary'` and `ix_case_ownership_active_office` UNIQUE (`case_id`, `office_id`) WHERE `status = 'active'`.
  `office_id` is always a Department-tier office; `unit_office_id` an office strictly inside it. Other FKs
  RESTRICT (unchanged); actor snapshot.
- `ownership_transfers` (transaction) — new columns `decision_note text NULL`, `stay_as_watcher boolean NOT NULL
  DEFAULT false`; partial unique index `ix_ownership_transfers_open` UNIQUE (`case_id`) WHERE `status =
  'requested'`; `ref_no` allocated under the `from_office_id` code (type `TRF`).
- `custody` / `custody_history` — first written by this item, for primary-ownership moves only (decision 11);
  `custody_history.reason` codes `claimed`, `allotted`, `transferred`, `released`, `returned_to_pool`.

Index names take the `ix_` prefix with an explicit suffix because the convention's generated name
(`ix_<table>_<column>`) is already used by the plain indexes. No `ref_*` code is added; no enum type changes.
The downgrade drops the indexes, checks and columns.

## Services
`backend/aslms/services/matching.py` (new) — the engine:
- `ENGINE_VERSION = "1"`, `LINKED_CASE_WEIGHT = 0.70`, `HIGH = 0.85`, `MEDIUM = 0.50`, `CNR_RE`.
- `normalise_counsel_code(code) -> str`; `normalise_term(text) -> str` (= `cases.normalise_name`).
- `combine(weights_by_kind: dict[str, float]) -> float` (noisy OR, rounded); `band_of(score) -> ScoreBand | None`.
- `RuleSet.load(session) -> RuleSet`: the active rules of active offices, each resolved to its Department-tier
  office; compiled regexes; codes by normalised text; the generic codes.
- `CaseEvidence.gather(session, case) -> CaseEvidence`: entry codes and party texts, current advocates' codes,
  current parties, summaries, linked cases with their active owners, watchlist hits.
- `score_case(rules, evidence) -> dict[office_id, ScoredOffice(score, signals)]` — pure, unit-tested without a
  database.
- `apply_scores(session, case, scores, *, origin) -> ScoreReport` — writes `case_office_scores`; creates,
  updates and expires recommendations by decision 5; emits `recommendation_made`.
- `score_cases(session, case_ids, *, origin, rules=None) -> ScoreReport` — a savepoint per case, failures to
  `source_failures` (kind `scoring`); called by `causelists.apply_entries` and `cases.apply_dossier` (one
  `RuleSet.load` per call).
- `rescore_all(session_factory, *, batch=500) -> ScoreReport` (a `job_runs` row `rescore` with counters `cases`,
  `scores`, `recommended_new`, `band_changed`, `expired`, `failed`); `rules_changed_since(session, ts) -> bool`;
  `rescore_if_dirty(session_factory) -> ScoreReport | None`.
- `unmapped_codes(session, *, limit=200) -> list[UnmappedCode]` (decision 19).

`backend/aslms/services/matching_rules.py` (new) — rule administration:
- `class RuleError(ValueError)`, `class DuplicateRule(RuleError)` (→ 409).
- `create_counsel_code(session, actor, actor_user, *, code, office, weight=None, is_generic_state=False,
  notes=None)`, `update_counsel_code(..., office=None, weight=None, notes=None)`,
  `set_counsel_code_active(..., enabled)`; the same three for keywords (`keyword`, `weight`) and name patterns
  (`pattern`, `kind`, `weight`, regex validation); watchlist `add_watch(session, actor, actor_user, *, cnr,
  office=None, reason=None, weight=None) -> tuple[OfficeWatchlist, bool]` (the bool: dossier queued),
  `update_watch`, `set_watch_active`.
- Each: `access.require(<function>)`, `access.in_scope(office)` unless super admin, weight range,
  normalisation, duplicate check (reactivate when the duplicate is inactive), `created_by` / `updated_by` or the
  actor snapshot (watchlist), and an audit row: `counsel_code.create|update|deactivate|reactivate`, `keyword.*`,
  `name_pattern.*`, `watchlist.*` (before/after summaries; an update that changes nothing writes nothing). Rule
  writes also emit one `config_changed` event (`scoped`, payload `{entity, id, action}`). Watchlist writes
  rescore that case inline (origin `watchlist`).

`backend/aslms/services/ownership.py` (new) — the human decisions:
- `class OwnershipError(ValueError)`, `class OwnershipConflict(OwnershipError)` (→ 409), `class
  NotVisible(OwnershipError)` (→ 404).
- `acting_department(session, actor_user, office_code=None) -> Office` (decision 6; `office_code` honoured for
  the super admin only; a user with no Department-tier ancestor → `OwnershipError`).
- `claim(session, actor, actor_user, case, *, office_code=None, unit_code=None, officer_user_id=None,
  note=None) -> CaseOwnership`;
  `dismiss(session, actor, actor_user, case, *, reason=None) -> Recommendation`;
  `suggest(session, actor, actor_user, case, *, office_code, reason) -> SuggestResult`;
  `allot(session, actor, actor_user, case, *, unit_code=UNSET, officer_user_id=UNSET) -> CaseOwnership`
  (the sentinel distinguishes "not given" from `None`);
  `release(session, actor, actor_user, case, *, reason) -> ReleaseResult` (successor or pool);
  `request_transfer(session, actor, actor_user, case, *, to_office_code, reason, stay_as_watcher=False) ->
  OwnershipTransfer`; `decide_transfer(session, actor, actor_user, transfer, *, accept: bool, note=None)`;
  `withdraw_transfer(session, actor, actor_user, transfer)`.
- Each: `access.require(...)`, the case row lock, the state checks of decisions 6–10, `write_audit(...,
  case_id=case.id)`, the event, custody (decision 11), then `matching.score_cases(linked case ids,
  origin=rescore)` for claim, transfer accept and release.
- `case_ownership_view(session, actor_user, case) -> dict` (primary, watchers, the own recommendation or all of
  them with `cases.view_all`, the open transfer).

`backend/aslms/services/custody.py` (new, minimal): `move_custody` (decision 11).
`backend/aslms/services/inbox.py` (new): `recommended`, `claimed`, `pool`, `transfers`, `counts` — SQL queries
returning summary rows and `total`, with the filters and ordering of decision 15.
`backend/aslms/services/visibility.py` (new): `department_of`, `owned_case_filter` (decision 16).
`backend/aslms/services/cases.py`: `resolve_case_ref` (decision 17); `apply_dossier` calls
`matching.score_cases` at its end. `services/causelists.py::apply_entries` collects the touched case ids and calls
`matching.score_cases` once.
`backend/aslms/jobs/celery_app.py`: task `aslms.rescore_if_dirty`, beat entry `rescore-dirty` every 15 minutes.
`backend/aslms/cli/matching.py` (new): `aslms rescore [--all] [--case REF]` and `aslms codes unmapped
[--limit N]`, registered in `cli/main.py`.

## API
Errors: 400 `RuleError` / `OwnershipError`, 403 `Forbidden` (missing function), 404 unknown or not visible
(indistinguishable), 409 `DuplicateRule` / `OwnershipConflict` / a unique-index race. `{ref}` is a case id,
`ref_no` (slash or dash form) or CNR; `{trf}` is a transfer id or `ref_no`. Lists take `limit` (≤ 200, default
50) and `offset` and return `{items: [...], total}`.

Router `api/routers/matching.py` (prefix `/admin`, tag `matching`):

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /admin/counsel-codes` | `admin.counsel_codes` | `?office=`, `?q=`, `?include_inactive=` | `{items: [CounselCodeOut {id, code, office {code, name}, weight, is_generic_state, notes, is_active, updated_at}], total}` | rules whose office is in the caller's subtree, plus generic codes (read-only); all for the super admin |
| `POST /admin/counsel-codes` | `admin.counsel_codes` | `CounselCodeIn {code, office_code, weight?, is_generic_state?, notes?}` | 201 `CounselCodeOut` + `applies_within_minutes: 15` | office in the caller's subtree; generic → `GOA` → super admin only |
| `PATCH /admin/counsel-codes/{id}` | `admin.counsel_codes` | `{office_code?, weight?, notes?}` | `CounselCodeOut` | old and new office in scope |
| `POST /admin/counsel-codes/{id}/deactivate`, `…/reactivate` | `admin.counsel_codes` | | `CounselCodeOut` | in scope |
| `GET /admin/counsel-codes/unmapped` | `admin.counsel_codes` | `?limit=` | `list[{code, entries, last_listed, example_case_ref}]` | court text only |
| `GET`, `POST /admin/keywords`; `PATCH /admin/keywords/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` | `KeywordIn {keyword, office_code, weight?}` | `KeywordOut {id, keyword, office, weight, is_active}` | caller's subtree |
| `GET`, `POST /admin/name-patterns`; `PATCH /admin/name-patterns/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` | `NamePatternIn {pattern, kind, office_code, weight?}` | `NamePatternOut {id, pattern, kind, office, weight, is_active}` | caller's subtree |
| `GET`, `POST /admin/watchlist`; `PATCH /admin/watchlist/{id}`; `…/deactivate`, `…/reactivate` | `admin.watchlist` | `WatchIn {cnr, office_code?, reason?, weight?}` | `WatchOut {id, cnr, case_ref?, office, reason, weight, is_active}`; POST adds `dossier_queued` | caller's subtree |
| `GET /admin/matching/cases/{ref}/scores` | `cases.view_all` | | `list[{office {code, name}, score, band, signals, computed_at, engine_version}]` | State-wide readers only |

Router `api/routers/inbox.py` (prefix `/inbox`, tag `inbox`); `?office=` other than the caller's department
needs `cases.view_all`:

| Method, path | Function | Request | Response |
|---|---|---|---|
| `GET /inbox/recommended` | `cases.claim` (own department) or `cases.view_all` | `?office=`, `?band=high\|medium`, `?q=` | `{items: [RecommendationOut {id, case: CaseSummaryOut, score, band, origin, signals, suggested_by_office_code?, reason?, created_at, current_owner_code?}], total}` |
| `GET /inbox/claimed` | `cases.view_scope` (rows by decision 15) | `?office=`, `?role=primary\|watcher`, `?unit=`, `?officer_user_id=`, `?q=` | `{items: [OwnershipOut {id, case: CaseSummaryOut, office_code, role, unit {code, name}?, officer {id, full_name}?, claimed_at, allotted_at?}], total}` |
| `GET /inbox/pool` | `cases.claim` or `cases.view_all` | `?q=`, `?listed_from=`, `?listed_to=`, `?status=`, `?case_type=`, `?year=`, `?min_score=`, `?state_party=` | `{items: [PoolCaseOut {case: CaseSummaryOut, best_score?, best_office_code?, dismissed_by: [office_code]}], total}` |
| `GET /inbox/transfers` | `cases.transfer_request` or `cases.transfer_decide` (own) or `cases.view_all` | `?office=`, `?direction=in\|out`, `?status=` | `{items: [TransferOut {id, ref_no, case: CaseSummaryOut, from_office_code, to_office_code, status, reason, stay_as_watcher, decision_note?, requested_by, requested_at, decided_at?}], total}` |
| `GET /inbox/counts` | `cases.view_scope` | `?office=` | `{recommended_high, recommended_medium, claimed, transfers_in_open, pool_with_hearing_7d}` (a count is null when the caller lacks that tab's function) |

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
| `POST /cases/{ref}/release` | `cases.release` | `{reason}` | `{released: OwnershipOut, successor?: OwnershipOut, returned_to_pool: bool}` |
| `POST /cases/{ref}/transfers` | `cases.transfer_request` | `{to_office_code, reason, stay_as_watcher?}` | 201 `TransferOut` |
| `POST /transfers/{trf}/accept`, `…/decline` | `cases.transfer_decide` (caller's department = `to_office`) | `{note?}` | `TransferOut` |
| `POST /transfers/{trf}/withdraw` | `cases.transfer_request` (caller's department = `from_office`) | | `TransferOut` |

`main.py` includes the three routers.

## Jobs
- Celery beat `rescore-dirty` → task `aslms.rescore_if_dirty` every 15 minutes (the `scheduler` service):
  rescores everything only when a rule or an office changed since the last succeeded `rescore` run; a
  `job_runs` row `rescore`. No NAPIX call.
- No new `fetch_queue` kind. A watchlist add for an unknown CNR enqueues an existing `dossier` row (ref
  `<CNR>`, priority 40). Inline scoring runs inside the existing `causelist_day` and `dossier` items.

## Tests
Unit (`tests/unit/test_matching_rules.py`, no database):
- `normalise_counsel_code`: `SC,EDU`, `sc , edu`, `SC, EDU,` → `SC, EDU`; `DY.S.G.I.` unchanged;
- `combine`: a single weight passes through; pattern 0.8 + keyword 0.4 = 0.880; two keywords = 0.400 (maximum
  within a kind); never above 1; `band_of` at 0.499 / 0.500 / 0.849 / 0.850;
- `score_case` on hand-built rule sets and evidence: a counsel code → 0.950 high; a generic code → nothing; a
  directorate rule rolls up to its department with `suggested_unit`; keywords match whole words only
  (`EDUCATION` matches, `REEDUCATIONAL` does not); exact / prefix / regex patterns; rules of an inactive office
  ignored; signals carry `kind`, `rule_id`, `matched`, `where`, `ref`;
- regex validation refuses an uncompilable pattern, a 301-character one and `.*` (matches the empty string).

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
- a department that dismissed a case is not re-recommended by a rescore, nor one that claimed and released it;
- linked case: claiming the main matter raises the linked case's score for the claimant (`linked_case` signal);
- `unmapped_codes` lists an unmapped `SC, REVENUE` with its count and omits mapped and generic codes.

Database (`tests/db/test_matching_rules_admin.py`):
- each rule's create / update / deactivate / reactivate writes its audit row and a `config_changed` event;
  duplicates → `DuplicateRule`; re-adding a deactivated rule reactivates it;
- an `EDU` dept admin cannot map a code to `HEALTH` (`Forbidden`), can map one to `EDU-DSE`, cannot create a
  generic code; a dept officer without `admin.counsel_codes` gets `Forbidden`;
- weights 0 and 1.2 refused by the service, and the CHECK constraint rejects a direct UPDATE to 1.5;
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
- release: watcher → `released`; primary with a watcher → the earliest watcher promoted, custody to its
  department, audit `ownership.release` + `ownership.promote`; primary alone → pool, custody to `GOA`
  (`returned_to_pool`); primary with an open transfer → conflict; `release_reason` stored;
- transfers: request by a watcher refused; a request gets `ref_no` `ASLMS/EDU/TRF/<yyyy>/000001`; a second open
  request → conflict; accept → old row `transferred`, the target primary (its watcher row promoted when it
  existed), `stay_as_watcher` adds an `EDU` watcher row, custody to the target; decline keeps ownership and stores
  `decision_note`; withdraw only by the requesting department; a decision by a third department → `NotVisible`;
- every action leaves exactly the expected `audit_log` rows (action, `case_id`, `entity_id`) and none on refusals;
- migration 0004: the four partial indexes and five CHECKs exist; the existing upgrade → downgrade → upgrade test
  covers the new revision.

API (`tests/db/test_api_inbox.py`, `TestClient` as in `test_api_offices.py`):
- `EDU` dept admin: `/inbox/recommended` lists only `EDU` rows, high before medium, with signals;
  `?office=HEALTH` → 403; a state-oversight user with `?office=EDU` → 200 (read-only) and `POST …/claim` → 403;
- `/inbox/claimed`: the dept admin sees all of `EDU`'s ownership; a directorate user of `EDU-DSE` sees only cases
  allotted to `EDU-DSE`; a dept officer only cases allotted to them; a `HEALTH` user none of `EDU`'s (visibility);
- `/inbox/pool` excludes owned cases, includes dismissed and low-score ones, filters by `q`, `state_party`,
  `min_score`; a dept officer without `cases.claim` → 403;
- `/inbox/transfers?direction=in` for the target lists the request; `/inbox/counts` agrees with the tabs;
- `POST /cases/{ref}/claim` accepts the id, the `ref_no` (dash form) and the CNR; an unknown ref → 404; a second
  claim → 409; `GET /cases/{ref}/ownership` as a `HEALTH` user with no recommendation on an `EDU`-owned case → 404;
- rule endpoints: 201 / 409 / 403 / 404 outside scope as in the admin tests; 401 without a token.

`tests/unit/test_schema_metadata.py` and `test_database_matches_the_models` stay green with the new columns,
checks and indexes.

## Verification
From the repository root with Compose up (`docker compose up -d postgres redis api`) on the development database
that holds the loaded January 2025 days:
1. `docker compose run --rm api alembic upgrade head` → revision `0004`; `\d case_ownership` shows the three new
   columns and `ix_case_ownership_active_primary`; `alembic downgrade -1 && alembic upgrade head` succeeds.
2. As the super admin: create `EDU` (department), `EDU-DSE` (directorate) and `HEALTH` (department) if absent,
   and an `EDU` and a `HEALTH` dept admin.
3. `docker compose run --rm api aslms codes unmapped --limit 20` → the most frequent codes of the loaded lists
   (expect `GA, ASSAM` and several `SC, …` codes); record the top five in the cycle report.
4. As the super admin, `POST /admin/counsel-codes {"code":"GA, ASSAM","office_code":"GOA","is_generic_state":true}`
   → 201. As the `EDU` admin, `POST /admin/counsel-codes {"code":"<the education code seen in step 3>",
   "office_code":"EDU"}` → 201; `POST /admin/keywords {"keyword":"SECONDARY EDUCATION","office_code":"EDU"}` → 201;
   mapping a code to `GOA` as the `EDU` admin → 403.
5. `docker compose run --rm api aslms rescore --all` → counters printed; `SELECT band, status, count(*) FROM
   recommendations GROUP BY 1, 2` shows high rows for `EDU`, and their number equals
   `SELECT count(DISTINCT case_id) FROM causelist_entries WHERE '<code>' = ANY(counsel_codes)` plus the cases where
   the code appears only in a dossier; no recommendation exists for `GOA`.
6. As the `EDU` admin: `GET /inbox/recommended` → items high first, each with a `counsel_code` signal showing the
   list date and serial; `POST /cases/<first ref>/claim` → 201 `role=primary`; `GET /inbox/claimed` lists it;
   `SELECT holder_office_id FROM custody WHERE case_id = …` → `EDU`.
7. `POST /cases/<second ref>/dismiss`; `POST /cases/<third ref>/suggest {"office_code":"HEALTH","reason":"…"}` →
   the third case appears in the `HEALTH` admin's `/inbox/recommended` with origin `suggestion`.
8. `POST /cases/<first ref>/transfers {"to_office_code":"HEALTH","reason":"…"}` → `ref_no`
   `ASLMS/EDU/TRF/2026/000001`; as the `HEALTH` admin `POST /transfers/<id>/accept` → `HEALTH` primary, custody at
   `HEALTH`, two `custody_history` legs.
9. After a keyword edit, wait one beat interval (or call the task `aslms.rescore_if_dirty`) → a new `job_runs`
   row `rescore` with `status=succeeded`; without an edit the next tick writes none.
10. `SELECT action, count(*) FROM audit_log WHERE action ~ '^(ownership|transfer|recommendation|counsel_code|keyword)\.'
    GROUP BY 1` matches the actions taken above; `pytest -q` green; `ruff check` clean.

## Open questions
None. Points the owner may wish to overrule at approval:
- decision 2, the score formula and weights (noisy OR of the strongest hit per kind; linked case 0.70);
- decision 10, a released primary passes to the earliest-claimed watcher rather than back to the pool;
- decision 11, minimal custody moves written now (ahead of `custody-workflow`) so that alerts find a holder;
- decision 15, the Recommended tab and the pool are shown only to holders of `cases.claim` (department admins and
  heads), not to every officer;
- decision 18 (**deviation, scope**), department discovery through Search by Party Name moved to its own backlog
  row 19 `department-discovery`.
