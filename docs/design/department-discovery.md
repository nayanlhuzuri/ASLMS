# Design: Department discovery — department party names and keywords run periodically through NAPIX Search by Party Name

```
slug: department-discovery
status: approved
author: architect
date: 2026-10-14
approved_by: owner (nayanlhuzuri) on 2026-10-14
```

> **Owner's decisions at approval (14 Oct 2026), replacing the note where they differ:**
> 1. **Automatic discovery covers registration years 2025 onwards only** (`DISCOVERY_FROM_YEAR=2025`): the system addresses cases from January 2025, and older cases come in only through case links from those cases (as today). The 90-day full sweep back to 2000 is dropped; the first sweep of a term and the weekly sweep both cover 2025 to the current year.
> 2. **Older years only on a user's request**: on the Court search tab a user enters a name and the year or years to search and presses Search. **No call counts, quota or allowance are shown to users**; the searches go into the discovery lane within its share and the screen says the court is being searched and results appear as found. If the same name and year were searched recently, the user is asked in plain words ("This was already searched on <date>; search again?") before anything is queued (the owner's already-held rule). Each such request is audited (`discovery.sweep`). Call counts and the allowance appear only on the Data collection screens.
> 3. **Live verification is limited to 10 NAPIX calls**: `NAPIX_DISCOVERY_SHARE=10` for that run only, so searches and the dossiers of found cases together cannot exceed 10. First try the party-name search with `reg_year` blank and record in `napix_integration_notes.md` §7 whether the gateway accepts it and returns all years (if it does, report it; do not change the design without the owner); then search one name for 2025 and 2026. Anything left over stays queued. Afterwards the share returns to the default (100).


## Context
Backlog row 19, moved up on 13 Oct 2026 after the review of the department's `docs/Case_Handling.docx` (decisions
log, "Department input: Case_Handling.docx"): departments find contempt cases by searching their officers' names, and
contempt is instituted against the officer responsible for compliance, often before the case appears in a cause list.

The plan: §3.1 Table 4 (Search by Party Name "On user search; **scheduled department discovery**", feeding "Search,
department mapping") and the paragraph under it: "Department discovery. Besides the daily cause lists, each
department's registered party names and keywords will be run periodically through the Search by Party Name API.
This finds a department's pending cases even before they appear in a cause list." §5.4 (the inbox is fed by the
"Matching engine output (from Cause List Details and Party Name Search APIs)"). §4 / §4.2 (recommend-and-claim; no
automatic assignment). Table 4: Search by CNR "when a case is first seen". Coverage addendum §D: a search row's
`cino` creates or finds the case and "the dossier is fetched on first sight". DB_STANDARD §3: a `CASE` ref_no is
allocated on "the claiming office when created by discovery". Decisions log of 25 Sep: "the database is filled
only through the NAPIX daily cycle, user searches and department discovery". recommend-and-claim decision 18: the
cases discovery finds are scored by the engine unchanged, and discovery never creates a department or any office.
data-load-console "Left for later": a discovery lane beside `request`, `daily` and `load`.

In place and reused:
- `NapixHighCourt.search_party(name, reg_year, pend_disp)` (`/hc-party-name-api/partyname`, input
  `est_code|pend_disp|litigant_name|reg_year`, verified live 1 Oct; `reg_year` required, `pend_disp` must match the
  case; sample `docs/specs/samples/party_name_2026-09-03.json`, answered by the scripted gateway in
  `tests/db/conftest.py::router`). Every response field already has a home (coverage §D); no field is added.
- `services/court_search.py::store_search_rows` (valid `cino` only, search fields fill empty columns, search vector,
  scoring, dedupe check), `PARTY_NAME_RE`, `MIN_PARTY_NAME`; `fetch_dossier`; `POST /cases/search-court`
  kind `party` (a person's search, unchanged by this item).
- `fetch_queue` with lanes (`services/queue.py::enqueue`, `claim`, `LEAST` lane precedence over the native enum),
  `services/load_policy.py::QueueOrigin`, `services/runner.py::QueueRunner` (bands: any lane ≥ `NAPIX_RATE_RESERVE`
  150, daily and request ≥ `NAPIX_LIVE_RESERVE` 100), `services/napix_window.py` (`current`, `calls_since(...,
  lane_split=True)`, `LANES`), `cli/pipeline.py::worker_wait` (a load-only block sleeps at most the idle time).
- The rule tables `office_keywords`, `office_name_patterns` (texts stored normalised by `matching.normalise_term`:
  upper case, dots as spaces, whitespace collapsed; kinds `exact` / `prefix` / `regex`), their service
  `services/matching_rules.py` (audited `keyword.*` / `name_pattern.*`, `config_changed` events) and endpoints
  `/admin/keywords`, `/admin/name-patterns` (`admin.keywords`, scoped to the caller's subtree).
- `FirstSeenSource.DISCOVERY` already exists in the `first_seen_source` enum (migration 0001) and is unused.
- `matching.origin_for_dossier`, the inbox pool with `scored_for` (`services/inbox.py`), the shared filters
  (`services/case_filters.py`, `api/filters.py`), `ClaimDialog`, the mapping frame and `MAPPING_TABS`, `DATA_TABS`.

The dev database (14 Oct 2026, read-only queries): 33,452 cases (14,725 pending), oldest pending registration year
2002 (2002–2009: 40 cases; 2010 onward: 14,345; 340 with year 0, not yet registered); 1,416 contempt cases, the
oldest pending from 2014; no party-name call has ever been made through the backend (only the Postman sample of
3 Sep); no department office and no keyword or name pattern yet; 194,049 load rows pending.

What the court's party-name search matches (whole name or part, first-named party only or all parties, upper or
mixed case, any cap on rows) has not been observed: the only sample searched one full name. The design does not
depend on it (every returned row is stored, then scored on its dossier); the verification records it in
`docs/napix_integration_notes.md` §7 (decision 16).

Not covered: alerts to the officer named in a contempt case (row 62, parked); search by advocate name or filing
number (row 21); disposed cases (decision 4); any change to the scoring formula or its signals (decision 9);
creating departments or offices (never, recommend-and-claim decision 18).

## Decisions
1. **The search terms are the departments' own keywords and name patterns, chosen per rule.** A new boolean
   `discover` on `office_keywords` and `office_name_patterns` ("Search the court"). A rule is *discoverable* when its
   stored text is 3 to 200 characters and matches `PARTY_NAME_RE` (letters, digits, spaces and `. , ' & ( ) / -`; the
   same rule as a person's party search, cases-api deviation 16, so no text can alter the gateway's `k=v|k=v` input)
   and, for a pattern, its kind is `exact` or `prefix`. A `regex` pattern is never discoverable (a regular expression
   cannot be sent as a name); a CHECK backs this. On create, `discover` defaults to *discoverable* (the plan: "each
   department's registered party names and keywords will be run"); asking `discover: true` for a text that is not
   discoverable is a 400 (`not_discoverable`). The department admin unticks a rule to keep it out of the court search
   (for example a generic word that would return thousands of cases). The 13 Oct note already tells departments to
   enter officer names as name patterns. Alternatives: a separate "discovery terms" list per department (a second
   list to keep in step with the matching rules, and found cases would not match any rule); every rule always run
   (no way to keep a generic keyword off the court's quota). **Owner check:** default on.
2. **A term is the normalised text, shared by every department that uses it.** `discovery_terms` holds one row per
   distinct discoverable text (`PRITAM SAIKIA`). The departments of a term are derived live from its active
   discoverable rules whose office and Department-tier ancestor are active (the engine's rule, recommend-and-claim
   decision 1); a term with none is *inactive*: nothing is queued for it and a pending row for it ends `skipped`
   without a call. Two departments entering the same name cost one search. Alternatives: one term per (office, text)
   (the same call made twice); terms only in `fetch_queue.ref` (the queue is not a register: "last searched" and
   "cases found" per term would be lost when rows are revived).
3. **One queue row per (term, registration year): new kind `party_search`, ref `<est_code>|P|<reg_year>|<term>`.**
   The API requires `reg_year` (cases-api decision 9), so a term is searched year by year. The est code is
   `NAPIX_EST_CODE` (`GAHC01`, Principal Seat), as for the daily cycle and court searches. `(kind, ref)` uniqueness
   dedupes across departments and sweeps. Alternatives: one row per term looping the years inside (a failure in
   year 14 would redo years 1–13; the queue's retry is per row); a queued search kind keyed by a person (searches by
   people stay synchronous, cases-api decision 9).
4. **Pending cases only (`pend_disp = P`).** The plan's purpose is "a department's pending cases"; notes §7: `P` does
   not find a disposed case, so `D` would double every sweep for cases needing no action. A found case that is later
   disposed is followed by the daily Current Status batches as any other. Alternative: `both` (twice the calls, for
   closed cases). **Owner check.**
5. **Sweeps: a full sweep once, then the recent years weekly, and the full sweep again every 90 days.**
   - *Full sweep*: registration years from `DISCOVERY_FROM_YEAR` (default 2000; the oldest pending case held is from
     2002) to the current year, newest first: 27 rows per term in 2026. Queued when a term first becomes active
     (a rule saved, reactivated or ticked with `discover`), and again by the weekly job for every active term whose
     `full_sweep_queued_at` is older than `DISCOVERY_FULL_SWEEP_DAYS` (default 90) or empty.
   - *Recent sweep*: the last `DISCOVERY_RECENT_YEARS` registration years (default 2: the current and the previous
     year, which covers the year boundary), every week for every active term (Saturday 02:00 IST). New cases,
     including new contempt cases, are registered in the current year; older years change only when a party is added
     to an old case, which the 90-day full sweep catches.
   Re-queued rows use `requeue=True` (a `done` row runs again; a pending one keeps its place).
   Cost at the defaults: 27 calls for a new term, then 2 calls a week, plus one dossier call per newly found case.
   Alternatives: every year every week (27 calls per term per week for years that rarely change); recent years only
   (old pending cases would never be found, which is the plan's point). **Owner check:** 2000, 2 years, 90 days.
6. **A fourth lane, `discovery`, with a capped share of each window.** `fetch_lane` gains `discovery` between `daily`
   and `load` (precedence request < daily < discovery < load, so a dossier also wanted by the daily cycle stays
   `daily`, and a load dossier also wanted by discovery runs as discovery). Rules of the runner:
   - band: discovery rows are claimed only while the window's remaining count is at least `NAPIX_RATE_RESERVE`, like
     the load (the order of protection stays load and discovery ≥ 150 > daily ≥ 100 > searches ≥ 50);
   - share: at most `NAPIX_DISCOVERY_SHARE` calls (default 100 of the 1,000) per detected window are made by
     discovery-lane rows, counted from `napix_call_log.lane = 'discovery'` since the window's `started_at` (the last
     3,600 s when the window is unknown) plus the calls the pass itself made for discovery rows. When the share is
     spent the runner claims from the other lanes only; when they hold nothing runnable the pass ends as a load-only
     block (`load_only=True`), so the worker sleeps at most its idle time and daily work is never delayed;
   - `NAPIX_DISCOVERY_SHARE=0` stops discovery claims (rows wait; nothing is lost).
   Priorities inside the lane (lower runs first): dossiers of found cases 41, recent-sweep searches 42, full-sweep
   searches 43, order PDFs of found cases 49. All are behind the daily cycle (≤ 40) and, at 41–43, ahead of the load
   outside a period brought forward (44–48); inside such a period they tie with the load's first kind and run in
   arrival order. Because of the share the backdated load still gets at least 750 of each window's calls.
   The load's pause does not pause discovery. Alternatives: discovery rows inside the `load` lane (paused with the
   load, counted with it, and starved behind 194,000 load rows); a share as a priority trick without a count (the
   lane would take the whole window whenever it has work); app-editable settings (the other quota settings are in
   `.env`; the console shows them). **Owner check:** share 100 per window.
7. **A found case is stored, its dossier fetched, then scored.** The runner's `party_search` handler:
   (1) re-reads the term's active rules (none → `skipped`, no call); (2) calls `hc.search_party(term, year, "P")`
   through the integration layer (628 RECORD_NOT_FOUND is a valid empty answer: the row is `done` with 0 rows);
   (3) stores the rows with `store_search_rows(..., source=FirstSeenSource.DISCOVERY,
   origin=RecommendationOrigin.DISCOVERY, ref_office=...)`: only rows whose `cino` is a valid CNR become cases,
   the rest are counted as `unmatched` and never stored (no fabricated identifiers), the verbatim response is kept
   in `napix_responses` by the recorder; (4) records each stored case in `discovery_hits`; (5) queues a `dossier` row
   (lane `discovery`, priority 41) for every stored case without a dossier (`last_full_refresh_at IS NULL`), because
   the search row carries only the first-named parties (`THE STATE OF ASSAM AND 3 ORS`) and an officer named as
   third respondent is visible to the engine only in the dossier's parties (Table 4 and coverage §D: the dossier on
   first sight); (6) updates the term's counters. Cases already held are only recorded as hits. Alternatives: no
   dossier until the weekly sweep (as for a person's party search, cases-api decision 9: the department would wait
   up to a week, and the score would read only the first-named parties).
8. **Ref numbers of cases created by discovery follow DB_STANDARD §3.** A case first created by a discovery search is
   allocated on the Department-tier office of the term when the term's active rules all belong to one department
   (`ASLMS/EDU/CASE/2026/…`), and on `GOA` when they belong to several. The number never changes on claim or
   transfer (§3). `get_or_create_case` gains `ref_office` (default `GOA`); `first_seen_source = discovery`.
9. **Scoring is the recommend-and-claim engine, unchanged.** No new signal kind, weight or setting: a found case is
   recommended to a department only through the existing signals (its keyword or name pattern matching the dossier's
   parties, a counsel code, a linked case, the watchlist) and the current bands. Recommendations made for a case
   first seen by discovery carry the new origin `discovery` (`origin_for_dossier` maps `discovery → discovery`;
   `store_search_rows` scores with the origin passed). A keyword alone still scores 0.40 (pool) and a name pattern
   0.80 (possible). Alternative: a new "found by the department's court search" signal (changes plan §4.1's signals
   and Table 6, and the scoring settings; recommend-and-claim decision 18 says "scored by this engine unchanged").
   **Owner check:** if the owner wants such a signal, it is a separate item.
10. **Found cases the engine does not recommend stay reachable.** The pool gains the filter `found_for=<department
    code>`: never-owned cases recorded in `discovery_hits` for a term of that department (the actionable rest, since
    recommended ones are on the Recommended tab). The department's "Court search" screen (decision 13) lists every
    case found by its terms with its owner and the department's recommendation, if any. Both show summaries only,
    the court-public fields that Search already shows to every case reader (cases-api decision 4); details keep the
    case visibility rule. Claim follows the existing rule (pool, or recommended to the department; otherwise a
    transfer). Alternative: a fifth inbox tab (plan §5.4 names four tabs; a pool filter adds none).
11. **System work is not audited; people's actions are.** Discovery searches and the dossiers they spawn are system
    work, like the daily cycle: their record is `napix_call_log` (lane `discovery`), `napix_responses`, `fetch_queue`,
    `discovery_hits`, the `case_created` event (source `discovery`) and the engine's `recommendation_made` events
    (which raise the usual `recommendation` alerts). Audited: ticking or unticking `discover` (inside the existing
    `keyword.create|update|reactivate` and `name_pattern.*` rows, whose summaries gain `discover`); a manual sweep
    (`discovery.sweep`, from the API or the CLI).
12. **No new function.** Reading and choosing terms is `admin.keywords` (who manages keywords and name patterns,
    scoped to the caller's subtree); a manual sweep, which spends quota, is `admin.data_load` (super admin by default,
    grantable); the discovery block of the data console is read with the console's readers (`data_load.READERS`);
    the pool filter is read under the pool's rule, and `found_for` another department needs `cases.view_all`.
13. **Portal, kept small.** (a) Keywords and name patterns tab: a "Search the court" checkbox on the add forms
    (pre-ticked when the text is discoverable, disabled for regex) and per row a toggle with "last searched" and
    "cases found". (b) New Department mapping tab "Court search" (`/admin/mapping/discovery`, `admin.keywords`): the
    department's terms (text, rules and offices, years searched / waiting / failed, last searched, cases found, new in
    the last 7 days) and, per term, the found cases with owner, recommendation band and Claim (the existing
    `ClaimDialog`). (c) The Unclaimed pool's filter bar gains "Found by our court search". (d) New data console tab
    "Discovery" (`/data/discovery`, data readers): the share and the calls used in the current window, rows waiting
    and failed by kind, terms active, cases found and created by discovery, and the two sweep buttons for
    `admin.data_load`. (e) The console's calls-by-lane figures show `discovery`. (f) The recommendation origin label
    "Court search (discovery)".
14. **Settings** (`core/config.py`, `.env.example`, validated at start): `NAPIX_DISCOVERY_SHARE` (0–1000, default
    100), `DISCOVERY_FROM_YEAR` (1950 to the current year, default 2000), `DISCOVERY_RECENT_YEARS` (1–5, default 2),
    `DISCOVERY_FULL_SWEEP_DAYS` (7–365, default 90). No secret; `NAPIX_ENABLED` is untouched (with it off the rows
    simply wait, as every other kind does).
15. **Migration 0017** adds the enum values, the two columns and the two tables (Data). Enum values cannot be dropped
    in PostgreSQL; the downgrade refuses while a `party_search` row is pending or running and otherwise drops the
    tables and columns, leaving the unused enum values in place (harmless).
16. **The live behaviour is recorded once.** The integrator's live step (owner's go-ahead, quota spent: one term,
    about 27 searches plus dossiers) records in `docs/napix_integration_notes.md` §7 how the court matches
    `litigant_name` (full name or part, which parties, case, dots), the largest row count seen, and saves a decrypted
    sample of a multi-row answer as `docs/specs/samples/party_name_<date>.json` (no credentials). If the court
    matches only whole names or only the first-named party, the owner is told before departments rely on officer
    names; the design does not change.

## Data
Migration **0017** (`0017_department_discovery.py`, new; no applied migration is edited).

Enum values (in an `autocommit_block`, as 0014 did): `ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'party_search'`;
`ALTER TYPE fetch_lane ADD VALUE IF NOT EXISTS 'discovery' BEFORE 'load'`; `ALTER TYPE recommendation_origin ADD VALUE
IF NOT EXISTS 'discovery'`. Python: `FetchKind.PARTY_SEARCH`, `FetchLane.DISCOVERY` (declared between `DAILY` and
`LOAD`), `RecommendationOrigin.DISCOVERY`. No `ref_*` code is added (no new event type, record type or function).

Paragraphs for `docs/schema/schema.md`:

Group 5, rows changed:
> `office_name_patterns` (master) … gains `discover` boolean NOT NULL default false: the pattern's text is run
> through NAPIX Search by Party Name (design `department-discovery`). CHECK `ck_office_name_patterns_discover`
> (`kind <> 'regex' OR NOT discover`). The service sets it on create to whether the text is discoverable (3–200
> characters of `[A-Z0-9 .,'&()/-]`, kind `exact` / `prefix`) unless the caller chooses; changing it is audited in the
> rule's `name_pattern.*` row. The migration sets it true on existing non-regex rows whose text is discoverable.

> `office_keywords` (master) … gains `discover` boolean NOT NULL default false, with the same meaning and rules
> (keywords have no kind). The migration sets it true on existing rows whose text is discoverable.

Group 5, new tables:
> `discovery_terms` (derived) | id (uuid v7 PK), term varchar(200) NOT NULL UNIQUE (the normalised rule text sent as
> `litigant_name`; CHECK `ck_discovery_terms_term`: `term ~ '^[A-Z0-9 .,''&()/-]{3,200}$'`), full_sweep_queued_at
> timestamptz NULL, recent_sweep_queued_at timestamptz NULL, last_searched_at timestamptz NULL (the latest completed
> search of any year), searches_done integer NOT NULL default 0, cases_found integer NOT NULL default 0 (distinct
> cases in `discovery_hits`), created_at, updated_at (trigger `set_updated_at`) | One row per distinct discoverable
> text of any department; created by `services/discovery.py` when a rule makes the text active, never deleted. Its
> departments and its active state are derived live from the active discoverable rules (office and Department-tier
> ancestor active), never stored. No FK to the rules (several rules of several offices share one term). `aslms_app`
> SELECT / INSERT / UPDATE.

> `discovery_hits` (derived) | id (uuid v7 PK), term_id (→ discovery_terms RESTRICT), case_id (→ cases RESTRICT),
> reg_year integer NOT NULL (the year searched), first_found_at timestamptz NOT NULL default now(), last_found_at
> timestamptz NOT NULL default now(), created_at, updated_at (trigger `set_updated_at`) | Unique (term_id, case_id);
> index `ix_discovery_hits_case_id` (case_id). One row per case a term's search returned; `last_found_at` bumped on
> every later return. Written only by the `party_search` handler. Never deleted (not on the DB_STANDARD §6 cascade
> list); `aslms_app` SELECT / INSERT / UPDATE. Read by the pool filter `found_for` and the Court search screen.

Group 9, the `fetch_queue` note gains:
> (department-discovery, migration 0017) `fetch_kind` gains `party_search` (ref `<est_code>|P|<reg_year>|<term>`);
> `fetch_lane` gains `discovery` between `daily` and `load` (precedence request < daily < discovery < load).
> Discovery rows are claimed only at or above `NAPIX_RATE_RESERVE` and while the discovery calls of the current window
> are below `NAPIX_DISCOVERY_SHARE`; priorities 41 (dossiers of found cases), 42 (recent-year searches), 43
> (full-sweep searches), 49 (order PDFs of found cases). The load's pause does not apply to them.
> `napix_call_log.lane` carries `discovery` for their calls.

Group 3 (cases), note added:
> A case first created by a discovery search has `first_seen_source = discovery` and its `ref_no` allocated on the
> Department-tier office of the term when the term belongs to one department, else `GOA` (DB_STANDARD §3).
> `recommendations.origin` gains `discovery`.

## Services
- **`services/discovery.py`** (new):
  - `discoverable(text, kind=None) -> bool` (decision 1) and `TERM_RE`.
  - `term_departments(session, term) -> list[Office]`: the Department-tier offices of the active discoverable rules
    with that text (`department_of`, inactive offices and ancestors excluded); `is_active(session, term)`.
  - `ensure_term(session, text) -> DiscoveryTerm`: get or insert (`ON CONFLICT (term) DO NOTHING`, then select).
  - `years(scope, today, settings) -> list[int]`: `full` = current year down to `DISCOVERY_FROM_YEAR`; `recent` = the
    last `DISCOVERY_RECENT_YEARS` years, newest first.
  - `enqueue_term(session, term, scope, *, requeue=True) -> int`: `queue.enqueue(FetchKind.PARTY_SEARCH,
    f"{est}|P|{year}|{term.term}", 42 or 43, lane=FetchLane.DISCOVERY, requeue=requeue)` per year, newest first; sets
    `full_sweep_queued_at` or `recent_sweep_queued_at`; returns the rows now pending.
  - `on_rule_saved(session, rule)`: called by `matching_rules` after a create, update, reactivate or `discover` change
    in the same transaction; when the rule is active and `discover` is true, `ensure_term` and, if the term's
    `full_sweep_queued_at` is empty, `enqueue_term(..., "full")`. Deactivating or unticking queues nothing (pending
    rows of a term left inactive end `skipped` at run time).
  - `enqueue_weekly(session, today) -> dict`: for every active term, `recent`; for those whose full sweep is due
    (decision 5), `full`. Returns counts.
  - `sweep(session, actor, *, scope, term_id=None) -> dict`: the manual sweep (decision 12): one term or every active
    term; requires `admin.data_load`; audit `discovery.sweep` (`after`: scope, term ids, rows queued).
  - `run_party_search(session, hc, court, ref, origin) -> (result, skipped)`: decision 7. The est code in the ref
    must be the court's (else `NapixInputError`, skipped). Hits upserted with `INSERT … ON CONFLICT (term_id, case_id)
    DO UPDATE SET last_found_at = now()`; `cases_found` recomputed for the term; `searches_done` + 1;
    `last_searched_at = now()`. Dossiers queued via `queue.enqueue(FetchKind.DOSSIER, cnr, 41, lane=DISCOVERY)` for
    stored, non-merged cases with `last_full_refresh_at IS NULL`. Result `{term, reg_year, rows, stored, created,
    unmatched, dossiers_queued}`. Writes no audit row.
  - `terms_view(session, user, *, office=None, limit, offset)`, `term_cases(session, user, term_id, *, limit,
    offset)`, `summary(session, settings)` for the API (decision 12 rules; summaries through `inbox.summaries`).
  - `found_for_condition(session, office)`: the SQL predicate for the pool filter (EXISTS over `discovery_hits` and
    `discovery_terms` whose text equals an active discoverable rule in the department's subtree).
- **`services/matching_rules.py`**: `create_keyword`, `update_keyword`, `create_name_pattern`, `update_name_pattern`
  take `discover` (`UNSET` = default on create, unchanged on update); `discover: true` on a non-discoverable text or a
  regex → `RuleError("not_discoverable")` (400); a pattern changed to `regex` sets `discover` false. Summaries gain
  `discover`, `discoverable`. After each save (and `set_*_active`), `discovery.on_rule_saved`.
- **`services/court_search.py::store_search_rows`** gains keyword arguments `source` (default `SEARCH`), `origin`
  (default `RecommendationOrigin.SEARCH`) and `ref_office` (default `GOA`), passed to `get_or_create_case` and
  `matching.score_cases`; the person's search is unchanged.
- **`services/cases.py::get_or_create_case`** gains `ref_office: str = ROOT_OFFICE` for the allocation.
- **`services/matching.py::origin_for_dossier`**: `DISCOVERY → RecommendationOrigin.DISCOVERY`.
- **`services/load_policy.py`**: constants `DISCOVERY_DOSSIER = 41`, `DISCOVERY_RECENT = 42`, `DISCOVERY_FULL = 43`,
  `DISCOVERY_ORDER_PDF = 49`; `QueueOrigin.dossier_priority` / `order_pdf_priority` return them for the discovery
  lane.
- **`services/runner.py`**: `dispatch` handles `FetchKind.PARTY_SEARCH` (`discovery.run_party_search`; NAPIX off →
  `RuntimeError` as for the other kinds). `budget_lanes` adds the share (decision 6): `discovery_used` is read with
  the window (`napix_window.calls_since(window.started_at, lane_split=True)["by_lane"]["discovery"]`, or the last
  3,600 s when `started_at` is None) and increased by the calls of each discovery item in the pass; when it reaches
  `NAPIX_DISCOVERY_SHARE` the lanes are `[request, daily, load]` (or `[request, daily]` below the reserve); a claim
  that then finds nothing ends the pass through `_blocked(..., load_only=True)` with the reason `discovery share
  spent: <used> of <share>; <window>`.
- **`services/napix_window.py`**: `LANES` gains `discovery` (the calls-by-lane split otherwise raises on the new value).
- **`services/inbox.py`** pool: parameter `found_for: Office | None`; caller must be able to act for it
  (`claim_departments`) or hold `cases.view_all` (else `AccessDenied`).
- **`services/data_health.py` / `data_load.py`**: allowance-by-lane blocks include `discovery` (no other change).
- **`jobs/celery_app.py`**: task `aslms.enqueue_discovery` → `discovery.enqueue_weekly`; beat entry
  `discovery-weekly` Saturday 02:00 IST.
- **CLI `aslms discovery`** (`cli/discovery.py`): `status` (the summary as JSON), `terms [--office CODE]`,
  `sweep [--full] [--term TEXT]` (audited `discovery.sweep` with the CLI actor, as other CLI writes).

## API
All endpoints answer 401 without a session; summaries only, details stay behind the case visibility rule.

| Method and path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `POST /admin/keywords`, `PATCH /admin/keywords/{id}` | `admin.keywords` (weight still needs `admin.scoring`) | existing body + `discover?: bool` | `KeywordOut` + `discover`, `discoverable`, `discovery?: {term_id, last_searched_at, cases_found}`; 400 `not_discoverable` | rule office in the caller's subtree (unchanged) |
| `POST /admin/name-patterns`, `PATCH /admin/name-patterns/{id}` | `admin.keywords` | existing body + `discover?: bool` | `NamePatternOut` + the same three fields; 400 `not_discoverable` (regex or text) | unchanged |
| `GET /admin/keywords`, `GET /admin/name-patterns` | `admin.keywords` | unchanged, + `discover=true\|false` filter | items carry the three fields | unchanged |
| `GET /admin/discovery/terms` | `admin.keywords` | `?office=CODE`, `status=active\|inactive\|all` (default active), `limit` ≤ 200 (50), `offset` | `{items: [{id, term, active, departments: [code], rules: [{kind: keyword\|exact\|prefix, rule_id, office_code}], years: {done, waiting, failed}, last_searched_at, cases_found, found_last_7_days, full_sweep_queued_at, recent_sweep_queued_at}], total}` | terms with at least one rule in the caller's subtree; rules outside it are not listed; the super admin sees all |
| `GET /admin/discovery/terms/{id}/cases` | `admin.keywords` | `only=all\|pool\|recommended\|owned` (default all), `limit`, `offset` | `{items: [{case: CaseSummaryOut, reg_year, first_found_at, last_found_at, owner_office_code?, recommendation?: {office_code, band, score, status}, claimable}], total}` | 404 when the term has no rule in the caller's subtree; `recommendation` only for the caller's departments (all departments with `cases.view_all`) |
| `GET /admin/discovery` | any of `data_load.READERS` | — | `{settings: {share, from_year, recent_years, full_sweep_days}, window: {status, started_at, next_reset_at, discovery_calls, share_left}, queue: {by_kind: {party_search, dossier, order_pdf}: {pending, waiting, running, failed}}, terms: {active, inactive}, cases: {found, created_by_discovery, recommended_from_discovery}, last_searched_at, latest_failures: [{ref, last_error, finished_at}] (20)}` | system figures only, no case data |
| `POST /admin/discovery/sweep` | `admin.data_load` | `{scope: "recent"\|"full", term_id?: uuid}` | `{terms, rows_queued}`; 404 unknown term; 409 `term_inactive` | audited `discovery.sweep` |
| `GET /inbox/pool` | unchanged (`cases.claim` or `cases.view_all`) | + `found_for=CODE` | unchanged | `found_for` must be a department the caller acts for, or the caller holds `cases.view_all` (else 403) |

Errors use the existing `{code, message}` body. `frontend/openapi.json` and `schema.d.ts` are regenerated.

## Jobs
- Queue kind `party_search`, lane `discovery`, ref `<est_code>|P|<reg_year>|<term>`, priority 42 (recent) or 43
  (full); its spawned dossiers 41 and order PDFs 49 (60 for a pending case, 80 otherwise, since the owner's "case details
  before order PDFs" of 24 Oct 2026), lane `discovery`. Claimed under the reserve band and the share
  (decision 6). Retries as every queue row (5 attempts, 10 minutes after an integration error).
- Beat `discovery-weekly` (Saturday 02:00 IST, task `aslms.enqueue_discovery`): recent sweep of every active term,
  full sweep of the terms that are due. Only enqueues; the worker does the fetching.
- Rule saves queue a new term's full sweep at once (in the request's transaction).

## Tests
Unit (`tests/unit/`):
- `test_discovery_terms.py`: `discoverable` accepts `PRITAM SAIKIA`, `DIRECTOR OF SECONDARY EDUCATION`, refuses 2
  characters, 201 characters, `|`, `=`, `%`, and every regex pattern; `years("full")` in 2026 with from-year 2000 is
  2026…2000 (27, newest first); `years("recent")` is [2026, 2025]; the ref format round-trips.
- `test_load_policy.py` (additions): the discovery lane's dossier priority is 41 and its order-PDF priority 49.
- `test_runner_share.py`: `budget_lanes` with remaining ≥ reserve and share left → all lanes; share spent →
  `[request, daily, load]`; below the reserve → `[request, daily]` whatever the share; share 0 → never discovery.
- `test_settings.py` (additions): the four settings' ranges are validated.

Database (`tests/db/`, scripted gateway):
- `test_migration_0017.py`: upgrade adds the values with `discovery` ordered between `daily` and `load`
  (`enqueue` of a dossier asked by discovery then daily ends `daily`; by load then discovery ends `discovery`);
  the CHECKs exist; existing discoverable rules get `discover = true`, regex rows false; downgrade refuses while a
  `party_search` row is pending, otherwise drops the tables and columns.
- `test_discovery_rules.py`: a keyword or exact/prefix pattern is created with `discover` true by default; a regex
  pattern false, and `discover: true` on it is 400 `not_discoverable`; a text with a refused character defaults to
  false and 400 when asked true; the save queues 27 `party_search` rows (lane `discovery`, priority 43, newest year
  first) and the audit row's `after` carries `discover`; a second department's identical pattern creates no term and
  no row; unticking queues nothing; a rule on an inactive office makes no term active.
- `test_discovery_run.py`: a `party_search` row runs through `QueueRunner` against the scripted gateway: the three
  sample rows are stored (the I.A. row included), new cases have `first_seen_source = discovery`, `ref_no` on the
  department's code when the term has one department and on `GOA` when two; `discovery_hits` holds three rows and a
  second run only bumps `last_found_at`; dossier rows are queued (lane `discovery`, priority 41) only for cases
  without a dossier; the call is in `napix_call_log` with lane `discovery` and no `user_id`; the response is in
  `napix_responses`; no `audit_log` row is written; a 628 answer ends `done` with 0 rows and sets `last_searched_at`;
  a row whose term lost its last rule ends `skipped` with no call; a row with a malformed `cino` is counted unmatched
  and creates no case.
- `test_discovery_scoring.py`: after the dossier of a discovered case is applied, a name pattern matching its third
  respondent gives a `recommendation` with origin `discovery`, band `medium`, score 0.800 at the default settings;
  `case_office_scores.signals` contains only existing kinds; a keyword-only hit stays in the pool.
- `test_runner_share_db.py`: with 100 discovery calls logged since the window's start, a pending discovery row is not
  claimed while a daily row is; with only discovery rows pending the pass ends `load_only` with the share reason;
  below the reserve no discovery row is claimed.
- `test_discovery_weekly.py`: `enqueue_weekly` queues the recent years of every active term (revives `done` rows),
  the full sweep only for terms queued more than 90 days ago or never, nothing for inactive terms.
- `test_api_discovery.py`: terms list scoped to the department admin's subtree (another department's term is absent,
  its cases 404); the super admin sees all; term cases carry `claimable` per the claim rule and the department's
  recommendation only; `GET /admin/discovery` for a data reader, 403 for a department officer; `POST
  /admin/discovery/sweep` 403 without `admin.data_load`, audited with it, 409 for an inactive term; `/inbox/pool?
  found_for=` returns only never-owned found cases of that department, 403 for another department without
  `cases.view_all`.
- `test_cli_discovery.py`: `aslms discovery sweep --term` queues and audits; `status` prints JSON.
- The guard tests stay green: no module outside `integration/napix/` calls the gateway; `NAPIX_ENABLED` is never set
  in code or tests (the switch is reported through `Settings.napix_configured` patching, cases-api deviation 11).

Portal (`frontend/`, Vitest):
- `mapping.test.tsx` (additions): the add forms pre-tick "Search the court" for a discoverable text and disable it
  for regex; the row toggle sends `PATCH {discover}` and shows a 400 `not_discoverable` message.
- `discovery.test.tsx`: the Court search tab lists terms and opens a term's cases with Claim through `ClaimDialog`;
  the tab shows only with `admin.keywords`; the Discovery data tab shows the share and hides the sweep buttons
  without `admin.data_load`.
- `filterbar.test.tsx` / `inbox.test.tsx` (additions): the pool's "Found by our court search" filter writes
  `found_for` to the query string and the request.
- `routes.test.ts`: the new mapping and data tabs and their functions.

## Verification
1. `ruff check` clean; `pytest -q` and the portal tests green.
2. `docker compose stop worker scheduler`, build `api`, `worker`, `scheduler`, `web`; `docker compose run --rm init`
   applies 0017; `docker compose up -d --wait`. `SELECT enum_range(NULL::fetch_lane)` →
   `{request,daily,discovery,load}`; `\d discovery_terms`, `\d discovery_hits` match Data.
3. The worker log shows the passes continuing; `GET /admin/discovery` answers with `share: 100`, `discovery_calls: 0`.
4. As the super admin, create a test department (`aslms offices`, or the offices screen) and its department admin.
   As that admin, add a name pattern `prefix` for an officer name taken from a held contempt case's respondents (a
   real party name, read from `case_parties`, not invented). The response shows `discover: true`; `SELECT count(*)
   FROM fetch_queue WHERE kind = 'party_search'` = 27; the audit row `name_pattern.create` carries `discover`.
5. **Live step, owner's go-ahead (spends real quota: about 27 searches plus one dossier per new case).** With the
   Compose worker running as it does for the historical load, watch `SELECT lane, count(*) FROM napix_call_log WHERE
   called_at > now() - interval '1 hour' GROUP BY 1`: discovery calls stay ≤ 100 per window; load calls continue.
6. After the sweep: `SELECT term, searches_done, cases_found FROM discovery_terms` → 27 searches; the case the name
   was taken from is in `discovery_hits`; new cases (if any) have `first_seen_source = 'discovery'`, a `ref_no` under
   the test department's code and a dossier queued or applied; `GET /inbox/recommended` for the department shows the
   cases whose dossier names the officer, origin `discovery` for new ones; `GET /inbox/pool?found_for=<code>` lists
   the found, unrecommended, never-owned ones.
7. Portal (`web`): the Keywords and name patterns tab shows the toggle; the Court search tab lists the term and its
   cases; the pool filter works; the Discovery data tab shows the window's discovery calls.
8. Record in `docs/napix_integration_notes.md` §7 how `litigant_name` matched (decision 16) and the largest row count;
   save a multi-row sample; put the counts (terms, searches, rows, cases found, created, recommended) in the cycle
   report.
9. Untick the pattern: the term turns inactive; any pending row of it ends `skipped` with no call.

## Open questions
None. The owner checks are marked in decisions 1 (default on), 4 (pending cases only), 5 (from 2000, two recent
years, full sweep every 90 days), 6 (share of 100 calls per window) and 9 (no new scoring signal). Each is a default
the owner may change at approval; none blocks the design. Decision 16's live step needs the owner's go-ahead because
it spends quota.

## Deviations
Written by the developer while building (smallest reasonable choices where the design was silent, and the owner's
decisions of 14 Oct 2026 carried into the build):
1. **One year range for every automatic sweep (owner's decision 1).** `DISCOVERY_FROM_YEAR` defaults to 2025 and
   `DISCOVERY_RECENT_YEARS` / `DISCOVERY_FULL_SWEEP_DAYS` are not added: a new term's first sweep (priority 43) and the
   weekly sweep (42, Saturday 02:00 IST) both cover 2025 to the current year, newest first. `discovery_terms.
   full_sweep_queued_at` records when the first sweep was queued and `recent_sweep_queued_at` the latest weekly or
   manual sweep. `POST /admin/discovery/sweep` takes `{term_id?}` only (no `scope`), and `aslms discovery sweep` takes
   `--term` only (no `--full`). `services/discovery.py::sweep_years(today, from_year)` replaces `years(scope, ...)`.
2. **A user's request for older years (owner's decision 2) is `POST /admin/discovery/search`** (`admin.keywords`, the
   Court search tab's function): body `{name, years: [int] (1-30, 1950 to the current year), force}`, answer 202
   `{term_id, term, years, queued}` with no call counts. The name must be one of the caller's terms (an active rule
   ticked "Search the court" in the caller's subtree; any active term for the super admin), else 400 `not_a_term`, so
   every found case has a department that sees it on the tab and a rule the engine scores with. Before anything is
   queued, a chosen year whose `party_search` row is `done` (its date) or still waiting answers 409 `searched_before`
   `{term, last_searched_at, years: [{reg_year, state, searched_at}]}` and writes nothing; "recently" is read as "ever,
   while the queue row exists", as the data-load console's `searched_before` rule does. `force: true` ("Search again")
   re-queues with `requeue=True`. The rows go to the discovery lane at 42 and carry no `requested_by` (the CHECK keeps a
   person to the `request` lane); the person is in the audit row `discovery.sweep` (`scope: "request"`, `term`, `years`,
   `rows_queued`, `force`, `warned`). Bad text is 400 `not_discoverable`, bad years 400 `bad_years`.
3. **Re-adding a deactivated rule through create** keeps its `discover` value when the caller leaves it out (still only
   while the text is discoverable); a new rule takes the discoverable default.
4. **The terms list** shows terms with a ticked rule (active or not) in the caller's subtree; `departments` and
   `rules` are both limited to that subtree (the super admin sees all); each rule item also carries `is_active`.
5. **A term's cases**: `recommendation` is the highest-scored active recommendation shown to the caller
   (`ownership.shown_recommendations_condition`); `claimable` is `ownership.claimable_condition`; merged cases are
   left out; a hit returned for a case merged meanwhile is recorded on the surviving case.
6. **`GET /admin/discovery`**: `queue.by_kind.<kind>.waiting` counts pending rows whose `not_before` is still ahead;
   `latest_failures` items carry `kind`; `window.discovery_calls` counts from the window's `started_at` (the last
   3,600 s when unknown), as the runner does.
7. **The runner**: when the share is spent and only discovery rows are runnable, the pass ends as a load-only block
   with `discovery share spent: <used> of <share>; <window>`; when nothing at all is runnable it ends "queue empty".
   A re-read of the window that finds the share freed (a new window) lets the pass go on.
8. **Other lane lists**: `RetryFailedIn` accepts kind `party_search` and lane `discovery`; `LaneCountsOut` and
   `AllowanceUsedOut` gain `discovery`; the portal's Load tiles, Health queue table and Queue lane filter show it.
9. **The weekly job creates missing term rows** for active ticked rules (rules ticked by the migration's data step have
   no term until then).
10. **Tests are grouped**: the unit additions (discoverable texts, years, ref, discovery-lane priorities, the runner's
    share bands, the two settings) are in `tests/unit/test_discovery_terms.py`; the share and scoring database tests
    are in `tests/db/test_discovery_run.py`; the portal's Court search and Discovery tab tests are in
    `components/admin/discovery.test.tsx`, the pool filter test in `inbox.test.tsx`.
11. **The portal**: the add forms send `discover` only when the user changed the box (the API defaults it from the
    text); the row toggle is disabled only for a regex (other refusals come back from the API and are shown as given).
    The Court search tab's name field offers the department's active terms; years are typed as `2010, 2012-2014`.
