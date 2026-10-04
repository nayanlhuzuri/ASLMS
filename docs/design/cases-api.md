# Design: Cases API — server-side visibility, search, the case detail data, search-the-court

```
slug: cases-api
status: awaiting-approval
author: architect
date: 2026-10-04
approved_by:
```

## Context
Plan §1.1 Table 1 (what each user type sees), §5.2 (Search), §5.3 (Case Detail Page), §6.3 (Searching for a
case, Figure 7), §3.1 Table 4 (Search by Case Number / Filing Number, Party Name / Advocate Name, Search by CNR
"on user search"), §8.1 ("the visibility hierarchy (State, department, directorate) applied to every request").
CLAUDE.md: visibility is enforced on the server for every query; NAPIX only through
`backend/aslms/integration/napix/`; `NAPIX_ENABLED` is the master switch; never fabricate identifiers; every
significant action is audited. Backlog row 3.

The plan's rules, in substance:
- Search by CNR (CINO), case number, party name or advocate name, with filters for status, year, case type and
  department. The portal's own database first; if the case is not found, the NAPIX search APIs are queried live
  and the case is fetched and stored, so the next search finds it locally. "Results respect visibility rules:
  users see full details only for cases within their access." A case found by search can be claimed from the
  inbox.
- The case detail page: overview (status, next hearing, court and bench, registration details, owning
  department, current custody); parties and advocates; hearings and proceedings timeline; orders with view and
  download; linked cases with a relationship graph; custody and the notes and files trail; documents; the Case
  Assistant.
- Table 1: State oversight reads every case; a department head all cases of the department and its
  directorates; a department admin reviews and claims the department's cases; a department officer the cases
  allotted to them; a directorate user the cases of their directorate and requests sent to it; a standing
  counsel the cases they appear in; the central operator follows unclaimed cases; the auditor reads every case.

Earlier decisions in the log that this design follows (still in force; the recommend-and-claim note relies on
the same 26 Sep block):
- 25 Sep: visibility tiers STATE (read-only all) → DEPARTMENT (self + directorates) → DIRECTORATE (own +
  requests); the custody tracking card is visible to every signed-in user, its contents scoped.
- 26 Sep "Allotment": directorate users see cases allotted to their unit; officers see cases allotted to them or
  their unit.
- 26 Sep "Standing counsel scope": a standing-counsel user belongs to a counsel office under a department and
  sees cases where a counsel code mapped to that department appears, plus documents shared with counsel and
  court records.
- 26 Sep "Scope widened by workflow": an office also sees cases it currently holds and cases with a request
  addressed to it (directorates; referral departments asked for views); for department officers and referral
  reviewers this access is personal only (held by, or addressed to, them).
- 25 Sep "Search: portal DB first; if not found, NAPIX Case No./Filing No./Party/Advocate search, then Search
  by CNR, then store."
- recommend-and-claim decisions 15–17: the inbox carries summary data only, full detail stays behind this
  item's visibility; `services/visibility.py` holds `department_of` and `owned_case_filter` "so that
  `cases-api` extends them (custody, requests, counsel)"; `resolve_case_ref` accepts id, `ref_no` (slash or
  dash form) or CNR. A case another department owns is 404 to the caller on the ownership endpoints.

What is in place:
- Group 3 tables and every NAPIX field in its typed home (`cases`, `case_parties`, `case_advocates`,
  `case_hearings`, `case_acts`, `case_applications`, `case_lower_courts`, `case_objections`, `case_transfers`,
  `case_writ_info`, `case_links`, `case_snapshots`), `orders`, `causelist_entries`, `events`; all written by the
  pipeline (`services/cases.py::apply_dossier` / `apply_status`, `services/causelists.py::apply_entries`).
- `cases.search_vector tsvector` exists (migration 0001) but nothing fills it and it has **no index**, although
  `schema.md` says "tsvector, GIN". `case_parties.name_normalised` has a b-tree index (useless for word search).
  Cases created from a cause-list entry carry no party summary (`get_or_create_case` sets none); their party
  text lives only in `causelist_entries`.
- `services/visibility.py` (`department_of`, `user_department`, `in_subtree`, `whole_department`,
  `claimed_conditions`, `owned_case_filter`); `services/inbox.py` (`summaries` = the `CaseSummaryOut` shape,
  `primary_codes`, `never_owned`, `_NORMALISED_CODE` / `_state_party_condition` — the SQL normalisation of
  counsel codes, recommend-and-claim deviation 3); `services/ownership.py::case_ownership_view`;
  `services/cases.py::resolve_case_ref`, `get_or_create_case` (never fabricates a CNR), `apply_dossier`;
  `services/runner.py::QueueRunner._dossier` and `_resolve_cnr` (dossier by CNR, CNR by case number through
  Search by Case Number), `open_hc`; `services/napix_store.py::NapixRecorder` (one `napix_call_log` row per
  attempt, one `napix_responses` row per distinct response).
- The integration layer already has `NapixHighCourt.search_case_number`, `search_party`, `search_advocate`,
  `search_filing`. **Verified live** (`docs/napix_integration_notes.md` §7, samples in `docs/specs/samples/`):
  Search by CNR, Search by Case Number (`est_code|case_type|reg_no|reg_year`, numeric `case_type`), Search by
  Party Name (`est_code|pend_disp|litigant_name|reg_year`; `pend_disp` must match the case). **Not verified, no
  sample, no response fields in the repository:** Search by Advocate Name and Search by Filing Number (stubs
  only, "not needed yet"; coverage addendum §E: "when one is added, its paths join this file first").
- Functions: `cases.view_scope` (every case-reading type), `cases.view_all` (State oversight, central operator,
  auditor; the super admin holds every function), `cases.search_court` (dept head, dept admin, dept officer,
  central operator; not the directorate user), `cases.claim`, `cases.allot`.
- The scripted gateway (`tests/db/conftest.py::router`) answers every verified API from the samples except the
  two searches (they fall through to 628 today).

Not covered: document and order-PDF download and upload (`documents-uploads`; this item lists orders with
`document_id` and `download_status` only); notes, requests, stages, hand-overs and their timeline entries
(`custody-workflow`, which reuses the visibility rule written here); alerts (`alerts-notifications`); the Case
Assistant (`assistant`); the portal screens (`portal-cases`); re-fetching an already fetched case
(`admin.napix_refetch`, `audit-screens`); NAPIX Search by Advocate Name and by Filing Number (decision 12, new
backlog row 21); department discovery (row 19).

## Decisions
1. **One visibility rule, written once, as named SQL conditions.** `services/visibility.py` gains
   `visibility_bases(session, user) -> list[tuple[str, ColumnElement[bool]]]`: each element is a basis name and
   a boolean condition over `cases` (correlated `EXISTS` subqueries; codes and ids bound as parameters). From it:
   `visible_case_condition(session, user)` = the OR of the bases (a filter for every list and a selected boolean
   column for search), `can_view_case(session, user, case) -> bool` and `access_basis(session, user, case) ->
   list[str]` (one `SELECT` evaluating every basis for that case id; returned on the detail so a user and a
   tester can see *why* a case is visible). Alternative: a Python check per case beside a SQL filter for lists —
   rejected, two implementations drift and a list would show what the detail refuses. Nothing is filtered in
   the portal; nothing is filtered after the query.
2. **The bases.** A case is visible when any basis applies (merged cases: decision 11). "Department" below is
   `user_department(user)`; "subtree" is the caller's own office and its descendants (`offices.path` prefix);
   "department-wide caller" is a holder of `cases.claim` or `cases.allot` (`visibility.whole_department`).

   | Basis | Who | Condition |
   |---|---|---|
   | `state` | super admin, or holder of `cases.view_all` (State oversight, central operator, auditor) | every case |
   | `owner` | department-wide callers (dept admin, dept head) | an **active** `case_ownership` row (primary or watcher) of the department, whatever `cases.status` |
   | `recommended` | department-wide callers | an active (`status = recommended`) recommendation to the department |
   | `pool` | holders of `cases.claim` in a department | the case has never had a primary owner (`inbox.never_owned`); the plan: any department can search and claim the pool, so it reads what it would claim |
   | `allotted` | every other caller in a department | `visibility.claimed_conditions(..., case_state="all")`: rows of the department allotted to the caller (`officer_user_id`), or, when the caller sits below the department, to a unit in the caller's subtree |
   | `custody` | office-wide for department-wide callers (department subtree) and for callers below the department (own subtree); **personal** for callers in the department office without `cases.claim` / `cases.allot` (dept officers) and for referral reviewers | `custody.holder_office_id` in the subtree / `custody.holder_user_id` = caller |
   | `request` | as `custody` | a `requests` row not `withdrawn` (open or answered) with `to_office_id` in the subtree / `to_user_id` = caller (the table stays empty until `custody-workflow`; the basis is written now so that item inherits it) |
   | `counsel` | users of type `standing_counsel` | an active, non-generic `counsel_codes` row whose office lies in the counsel's department subtree, matched after the SQL normalisation (`NORMALISED_CODE_SQL`, moved from `inbox._NORMALISED_CODE` to `visibility.py`) against any element of the case's `causelist_entries.counsel_codes` or any current `case_advocates.counsel_code` |

   Every basis except `state` also requires `cases.view_scope`; a caller with neither `cases.view_scope` nor
   `cases.view_all` sees no case (403 on every endpoint here). The `counsel` basis is keyed on the user type
   because Table 1 defines it by type and no function expresses "appears as counsel"; the counsel's other
   functions still come from the matrix. Alternatives for counsel: (a) only cases explicitly allotted to the
   counsel — narrower than Table 1 ("cases they appear in"); (b) matching by advocate name — the HC backend
   returns no bar registration number (coverage §C), so names would be guessed.
3. **A department loses sight of a case it transferred away** unless it stayed as a watcher
   (`stay_as_watcher`, recommend-and-claim decision 8): the `owner` basis reads *active* rows only. Its notes on
   the case remain governed by per-note visibility in `custody-workflow`. Alternative: read access for every
   former owner — rejected: the transfer is the department saying the case is not theirs; ownership history
   stays visible to State-wide readers and in the audit log.
4. **Search shows a summary of any case and full detail only within access** (plan §5.2). `GET /cases/search`
   returns every matching non-merged case as `CaseSummaryOut` (court data printed in cause lists and returned by
   the public eCourts services: number, CNR, party summaries, status, dates) plus `visible`, `owner_office_code`
   (the active primary owner's code, null in the pool), `in_pool` and `claimable` (in the pool, and the caller
   holds `cases.claim` and belongs to a department). The detail endpoints of a case that is not visible answer
   **404** "no such case", as the ownership endpoints do (one convention across the API). `GET /cases` lists
   visible cases only (the work list of users without an inbox tab — officers, directorate users, standing
   counsel — and of the State readers). Alternative: search returns visible cases only — rejected: the plan
   withholds *details*, not results, and a department must be able to find a pool case or learn that another
   department already owns a case before asking for a transfer.
5. **Local search** (plan §6.3, "portal's own database first"). One box `q` with `field=auto|cnr|number|party|
   advocate|text` (default `auto`). Auto-detection, in order: a UUID → id; `ASLMS/…` or `ASLMS-…` → `ref_no`
   (`ref_no_from_url`); `^[A-Z]{4}\d{12}$` after upper-casing → CNR (exact); a case number `<type> <no>/<year>`
   or `<type>/<no>/<year>` (`^(?P<type>[A-Z][A-Z().\-\s]*?)\s*[/\s]\s*(?P<no>\d{1,7})\s*/\s*(?P<year>\d{4})$`) →
   number: the type compared with `case_types.short_name` and `aliases` and with `cases.case_type_text`, all
   upper-cased without white space, plus `reg_no` and `reg_year`; the same compact string is compared with
   `cases.filing_no_text` too (filing numbers are searched locally); anything else → text (party and advocate
   words). Filters: `status` (`pending` / `disposed` / `unknown`), `year` (`reg_year`), `case_type` (short name,
   compared as above), `office` (a Department-tier code: cases whose active primary owner is that department),
   `listed_from` / `listed_to` (a cause-list appearance in the range). `q` is at least 3 characters; it is
   optional on `GET /cases` (filters only) and required on `/cases/search`. Order: exact identifier matches
   first, then `ts_rank` for text, then next hearing date ascending (nulls last), then `reg_year` descending.
   Pagination as the inbox (`limit` ≤ 200, default 50, clamped; `offset`); `total` is counted up to 10,000 and
   `total_capped` says when the count stopped (a search for "STATE OF ASSAM" matches most of the database).
6. **Word search through `cases.search_vector`**, now filled and indexed (Data). One SQL function
   `aslms_case_search_vector(case_id)` with config `simple` (names; no stemming) builds three weights: **A**
   party names (current `case_parties.name`, `petitioner_summary`, `respondent_summary`, the distinct
   `causelist_entries.petitioner_text` / `respondent_text` — so a provisional case known only from a cause list
   is findable); **B** advocates (current `case_advocates.name_as_listed` and `counsel_code`, `pet_advocate`,
   `res_advocate`, the distinct `causelist_entries.pet_advocate_text` / `res_advocate_text`); **C** identifiers
   (`cnr`, `case_no_text`, `filing_no_text`, `ref_no`). The query is built in Python from the words of `q`
   (`[0-9A-Za-z]+`, at most 8 words, one-letter words dropped), each as `word:*` restricted to `A` (party), `B`
   (advocate) or `AB` (text), joined with `&`, and passed as one bound parameter to
   `to_tsquery('simple', :q)` — never interpolated. `services/cases.py::refresh_search_vector(session,
   case_ids)` runs `UPDATE cases SET search_vector = aslms_case_search_vector(id) WHERE id = ANY(:ids)`; it is
   called at the end of `apply_dossier`, at the end of `apply_entries` for the touched cases (before scoring),
   and after a court search stores cases (decision 9). Alternatives: triggers on `case_parties`,
   `case_advocates` and `causelist_entries` (one recomputation per child row during a dossier apply); `ILIKE
   '%…%'` as in the inbox (sequential scans over every party row — acceptable for department-bounded inbox
   lists, not for a State-wide search); `pg_trgm` (a new extension for no gain on whole words).
7. **The case detail is one overview call plus one call per heavy tab.** `GET /cases/{ref}` returns every
   typed `cases` column of the coverage table (grouped: identity, status, bench and classification, place and
   police, parties as printed, portal state), the court and bench, the small child lists (current parties,
   current advocates, acts, lower courts, applications, objections, court transfers `case_transfers`, writ
   information), the compact ownership (primary office code and name, unit, officer; watchers' office codes),
   the custody card (holder office and officer, pending action, since, due date; null until a holder exists),
   `access_basis`, `claimable`, `dossier_status` (`fetched` when `last_full_refresh_at` is set, else
   `not_fetched`) and the counts of the tab lists. Paginated sub-resources: `/hearings`, `/orders`, `/listings`
   (cause-list appearances), `/links` and `/links/graph`, `/timeline`, and `/parties?include_former=true` for
   parties and advocates no longer current. The raw payloads (`case_snapshots`, `napix_responses`) are not
   exposed here (data-health screens, `audit-screens`). Alternatives: one large payload (a case with years of
   hearings and orders would make every page open slow); one call per field group (too chatty for the
   overview).
8. **Linked cases and the relationship graph.** `/links` returns both directions (`case_links.from_case_id` =
   this case; rows whose `to_case_id` is this case or whose `to_cnr` is its CNR), each with kind, number and CNR
   as printed, `filing_number_text`, source and — when the other case is held — its summary and `visible`.
   `/links/graph?depth=1..3` (default 2) walks the same edges breadth-first, at most 200 nodes (`truncated:
   true` when cut); nodes are summaries with `visible`; unresolved links are leaf nodes carrying only the
   printed number. A non-visible node never carries more than the summary of decision 4.
9. **Search the court (`cases.search_court`)** — `POST /cases/search-court`, synchronous, through the
   integration layer only. Kinds:
   - `cnr` `{cnr}`: validated (`^[A-Z]{4}\d{12}$`); held with a dossier → returned, **no call**; otherwise
     Search by CNR → `get_or_create_case(source=search)` + `apply_dossier` + `enqueue_order_pdfs` (1 call).
   - `case_number` `{case_type, reg_no, reg_year}`: `case_type` is a short name (`WP(C)`) or the master's
     numeric code, resolved through `case_types` (unknown → 400, no call). Held locally with a dossier →
     returned, no call. Otherwise Search by Case Number; every returned row is stored (below); the row whose
     `reg_no` and `reg_year` equal the request gets its dossier at once (1 + 1 calls); no exact row → the rows
     are returned, none fetched.
   - `party` `{name, reg_year, pend_disp}`: `name` ≥ 3 characters; `reg_year` required by the API (1950 to the
     current year); `pend_disp` `P` (default), `D` or `both` (two calls; notes §7: `P` does not find a disposed
     case). Every returned row is stored; **no dossier is fetched** for party hits (a common name can return
     hundreds of cases and the quota is shared with the daily cycle): each result carries `dossier_status`, the
     user fetches the one they need (decision 10), and the weekly sweep fetches pending ones anyway.

   Storing a search row (coverage §D): only rows whose `cino` matches `^[A-Z]{4}\d{12}$` (others are returned as
   `unmatched` and never stored — no fabricated identifiers); `get_or_create_case(court, cnr=cino,
   case_no="<type_name>/<reg_no>/<reg_year>", source=search)`; the search fields (`pet_name`, `res_name`,
   `reg_no`, `reg_year`, `type_name`, `case_type_id`, `police_st_code`, `uniform_code`) fill only empty columns
   (a dossier, when present, is authoritative). Then `refresh_search_vector` and
   `matching.score_cases(origin=RecommendationOrigin.SEARCH)` for the new or changed cases (inline, in
   savepoints, as the pipeline does); the verbatim response goes to `napix_responses` through the recorder. The
   response uses the item shape of `/cases/search` (with `visible`), plus `source` (`local` / `court`),
   `calls`, `created`, `unmatched`. The court is `NAPIX_EST_CODE` (Principal Seat, `GAHC01`), as for the daily
   cycle. Alternative: a queued search with polling — `fetch_queue.kind` is a native enum (a migration), its
   `(kind, ref)` uniqueness does not fit per-user searches, and the user is waiting for one or two calls.
10. **Fetch a found case** — `POST /cases/{ref}/fetch-court` (`cases.search_court`), for a case without a
    dossier (`last_full_refresh_at IS NULL`) only. A provisional case without a CNR is first resolved through
    Search by Case Number (the runner's `_resolve_cnr`, moved to the shared service); not resolvable → 404 with
    code `not_found_at_court`, the case stays provisional. A case that already has a dossier → 409
    `already_fetched` (re-fetching is `admin.napix_refetch`, `audit-screens`). Open to any holder of
    `cases.search_court` whatever the visibility: the call only fills court data; reading it still needs
    visibility.
11. **Shared court-fetch service; merged cases.** `services/court_search.py` owns the dossier fetch
    (`fetch_dossier(session, hc, court, cnr, *, source)`), CNR resolution by number (`resolve_cnr`) and search
    ingestion; `QueueRunner._dossier` and `_resolve_cnr` call it, so the queue and the API apply a dossier the
    same way. Merged cases (`merged_into_case_id` set) are excluded from search and lists; their detail answers
    with `merged_into_ref_no` and the stored data, visibility evaluated on the merged case itself.
12. **NAPIX Search by Advocate Name and by Filing Number are deferred — deviation (scope), flagged for the
    owner.** Plan §5.2 and Table 4 list both. Neither has been called live: no sample, no response fields in the
    repository, the notes mark them "not needed yet", and the coverage addendum requires their paths to be added
    before use; CLAUDE.md forbids guessing NAPIX fields. This item searches advocate names and filing numbers
    **locally** (decisions 5 and 6) and calls NAPIX for CNR, case number and party name. New backlog row 21
    `search-court-advocate-filing`: probe both APIs live (`aslms napix-check` with the switch set for that run),
    save samples, extend `napix_coverage.md`, then add the two kinds to decision 9 in the same shape. The backlog
    line of this item names only CNR, number and party, so nothing promised there is dropped.
13. **Quota and abuse guard for court searches** (settings from `.env`, defaults in `core/config.py` and
    `.env.example`):
    - `NAPIX_ENABLED` false or credentials missing → 503 `{code: "napix_off"}`, no call (never switched in code).
    - `NAPIX_SEARCH_FLOOR` (default 50): when the latest `napix_call_log.rate_limit_remaining` recorded in the
      current clock hour is below it → 503 `{code: "napix_budget", retry_after}` (seconds to the next hour). The
      runner stops at `NAPIX_RATE_RESERVE` (150) to keep calls for the daily cycle; user searches may go lower,
      down to the floor, because they are few and someone is waiting.
    - `NAPIX_SEARCH_PER_USER_HOUR` (default 30): `audit_log` rows `case.search_court` and `case.fetch_court` of
      the caller in the last 60 minutes; at the limit → 429 `{code: "search_limit", retry_after}`. No new table.
    - `NAPIX_SEARCH_TIMEOUT_SECONDS` (default 60): the whole request, retries included; exceeded → 504
      `{code: "napix_timeout"}`.
    - Gateway failures → 502 `{code: "napix_unavailable"}`; `NapixNotFound` → 200 with no results;
      `NapixInputError` → 400.

    Failures are recorded, never lost: the service flushes the recorder (`napix_call_log` rows) and writes the
    audit row with its `outcome`, and the router commits **before** raising the HTTP error (the request session
    otherwise rolls back on an exception — the pattern of recommend-and-claim deviation 2). Alternative: share
    the runner's reserve — the historical load keeps the remaining count near 150 for hours, which would block
    every user search.
14. **Audit.** `case.search_court` (entity `napix_search`, `after` = kind, the request fields, calls, result
    count, created count, `outcome` `ok` / `not_found` / `failed:<code>`) and `case.fetch_court` (entity
    `case`, `case_id`, `after` = CNR, calls, outcome): both spend the shared quota and write case data on a
    user's behalf. New cases emit the existing `case_created` event (source `search`) through
    `get_or_create_case`. **Reading** a case, a list or a local search writes no audit row (plan §5.13 lists
    logins, ownership decisions, custody moves, notes, uploads and configuration changes; a row per page view
    would dwarf the log). Read auditing of State-wide readers can be added later if the owner asks.
15. **Timeline** (`/timeline`): `events` of the case, newest first, with `ref_event_type.timeline_label`,
    `icon_key`, the actor's name and the payload, restricted to an allow-list: court events (`case_created`,
    `case_updated`, `case_disposed`, `case_linked`, `listed`, `listed_supplementary`, `next_date_extracted`,
    `next_date_changed`, `status_changed`, `order_found`, `order_stored`) and ownership events (`claimed`,
    `allotted`, `case_taken_over`, `transfer_requested`, `transfer_decided`, `ownership_released`,
    `custody_moved`); `recommendation_made`, `dismissed` and `suggested_elsewhere` only for the caller's own
    department unless the caller holds `cases.view_all` (the inbox rule for other departments'
    recommendations). Note, document, request, stage and alert events join the allow-list in their own items,
    with per-note and per-document visibility; until then they are not shown.
16. **Permissions on the endpoints.** Reading: `cases.view_scope` **or** `cases.view_all` (new dependency
    `require_any(*permissions)` in `api/deps.py`), then the visibility rule per case. Court search and fetch:
    `cases.search_court`. No new function, no matrix change.

## Data
No new table or column. One migration, **0005_case_search** (new; 0001–0004 are applied and are not edited):
- `CREATE FUNCTION aslms_case_search_vector(p_case_id uuid) RETURNS tsvector LANGUAGE sql STABLE` (decision 6:
  weight A parties, B advocates, C identifiers; `string_agg(DISTINCT …)` over current child rows and cause-list
  entries; `setweight(to_tsvector('simple', coalesce(…, '')), …)` per weight), owned by `aslms_owner`,
  `GRANT EXECUTE` to `aslms_app` and `aslms_readonly`.
- `CREATE INDEX ix_cases_search_vector_gin ON cases USING gin (search_vector)`.
- `CREATE INDEX ix_cases_case_no_compact ON cases (upper(regexp_replace(case_no_text, '\s', '', 'g')))` for
  number search.
- Backfill in the migration: `UPDATE cases SET search_vector = aslms_case_search_vector(id)`. Downgrade drops
  the two indexes and the function and sets `search_vector` to NULL.

Paragraph for `docs/schema/schema.md`, Group 3, replacing "search_vector (tsvector, GIN)" in the `cases` row by
`search_vector (tsvector, derived — see below)` and adding under the table:

> `cases.search_vector` (tsvector) is derived: `aslms_case_search_vector(case_id)` (migration 0005, SQL
> function, config `simple`) builds it from the current party names, the party summaries and the cause-list
> party texts (weight A), the current advocates, counsel codes and cause-list advocate texts (weight B) and the
> CNR, case number, filing number and `ref_no` (weight C). It is refreshed by
> `services/cases.py::refresh_search_vector` after every dossier apply, cause-list apply and court-search store;
> never written by hand. GIN index `ix_cases_search_vector_gin`; expression index `ix_cases_case_no_compact` on
> the upper-cased case number without white space.

And under "Conventions", after "scope checks use `offices.path` prefix matching, in SQL only":

> Case visibility is one rule (`services/visibility.py::visibility_bases`, design `cases-api`): the bases
> `state`, `owner`, `recommended`, `pool`, `allotted`, `custody`, `request`, `counsel`, OR-ed in SQL for every
> list and evaluated for one case on every detail; summaries of any case are searchable, details only within
> the rule.

No `ref_*` codes, no enum change, no new function in `ref_permission`. `.env.example` gains
`NAPIX_SEARCH_FLOOR=50`, `NAPIX_SEARCH_PER_USER_HOUR=30`, `NAPIX_SEARCH_TIMEOUT_SECONDS=60` (no secrets).

## Services
`backend/aslms/services/visibility.py` (extended):
- `NORMALISED_CODE_SQL` (moved from `inbox._NORMALISED_CODE`; `inbox` imports it).
- `visibility_bases(session, user) -> list[tuple[str, ColumnElement[bool]]]` (decision 2; empty when the caller
  holds neither `cases.view_scope` nor `cases.view_all`; `[("state", true())]` for State-wide readers).
- `visible_case_condition(session, user)`, `can_view_case(session, user, case)`, `access_basis(session, user,
  case)`; `require_visible(session, user, case)` raises `NotVisibleCase` (→ 404).

`backend/aslms/services/case_search.py` (new):
- `parse_query(q, field) -> ParsedQuery` (kind `id` / `ref_no` / `cnr` / `number` / `text`; words, type, number,
  year; `SearchError` on bad input) — pure, unit-tested.
- `tsquery_text(words, weights) -> str` — pure.
- `search(session, user, *, q, field, status, year, case_type, office, listed_from, listed_to, visible_only,
  limit, offset) -> Page` (decision 5): items = `inbox.summaries` + `visible` (the visibility condition as a
  selected column), `owner_office_code`, `in_pool`, `claimable`, `match`.
- `list_visible(session, user, *, q=None, the same filters, case_state, next_from, next_to, limit, offset)` —
  `GET /cases`.

`backend/aslms/services/case_detail.py` (new): `overview(session, user, case)`, `parties(…, include_former)`,
`hearings(…, limit, offset)`, `orders(…)`, `listings(…)`, `links(…)`, `link_graph(…, depth)`, `timeline(…,
limit, offset)`. Each starts with `visibility.require_visible`; linked-case summaries carry `visible` from
`visible_case_condition`. Read-only: no audit, no events.

`backend/aslms/services/court_search.py` (new; async functions driven from the sync router with `asyncio.run`,
as the 26 Sep "Synchronous services" decision does for the CLI and Celery; the client and recorder come from
`runner.open_hc` and `NapixRecorder`):
- `guard(session, user, settings)` — decision 13 checks (switch, floor, per-user limit); raises
  `CourtSearchUnavailable(code, retry_after)` / `SearchLimit(retry_after)`.
- `fetch_dossier(session, hc, court, cnr, *, source) -> Case` (get or create, `case_by_cnr`, `apply_dossier`,
  `enqueue_order_pdfs`); `resolve_cnr(session, hc, court, case_no) -> str | None` (moved from the runner).
- `store_search_rows(session, court, rows) -> StoreReport` (decision 9: valid CNRs only, fill-empty-only,
  `refresh_search_vector`, `matching.score_cases(origin=RecommendationOrigin.SEARCH)`).
- `search_court(session, actor, user, request, *, hc, recorder) -> CourtSearchResult` and `fetch_court(session,
  actor, user, case, *, hc, recorder)`: both write the audit row of decision 14 with the outcome and flush the
  recorder; the router commits, also before raising an HTTP error.

`services/runner.py::QueueRunner._dossier` / `_resolve_cnr` call `court_search.fetch_dossier` / `resolve_cnr`
(behaviour unchanged; `tests/db/test_pipeline.py` must stay green).

`backend/aslms/services/cases.py`: `refresh_search_vector(session, case_ids)`, called at the end of
`apply_dossier`; `services/causelists.py::apply_entries` calls it for the touched cases before scoring.

CLI: `aslms cases reindex-search [--all | --case REF]` (re-runs the function; for repairs) and `aslms cases
show REF --as EMAIL` (prints `access_basis` for a user; the integrator's tool for visibility checks), both
wrapping tested services.

## API
New router `backend/aslms/api/routers/cases.py` (tag `cases`), mounted in `api/main.py`. `{ref}` = case id,
`ref_no` (slash or dash form) or CNR (`resolve_case_ref`). "Read" = `cases.view_scope` or `cases.view_all`
(`require_any`). Unknown or not visible → 404 `no such case`. Lists return `{items, total}` (`total_capped` on
the two case lists), `limit` ≤ 200 default 50, `offset`. Routes `/cases/search` and `/cases/search-court` are
declared before `/cases/{ref}`.

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /cases` | read | `?q=` (optional, ≥ 3), `field`, `status`, `case_state=active\|disposed\|all` (default `all`), `year`, `case_type`, `office`, `listed_from`, `listed_to`, `next_from`, `next_to`, `limit`, `offset` | `{items: [CaseSearchItemOut], total, total_capped}` | visible cases only |
| `GET /cases/search` | read | `?q=` (required, ≥ 3), `field=auto\|cnr\|number\|party\|advocate\|text`, `status`, `year`, `case_type`, `office`, `listed_from`, `listed_to`, `visible_only=false`, `limit`, `offset` | `{items: [CaseSearchItemOut {case: CaseSummaryOut, visible, owner_office_code?, in_pool, claimable, match}], total, total_capped}` | every non-merged case as a summary; `visible` per row |
| `GET /cases/{ref}` | read | | `CaseDetailOut` (decision 7: identity, status, bench, place, parties as printed, portal state; `court {est_code, name}`, `bench {bench_id, judge_names, bench_name}?`, `parties[]`, `advocates[]`, `acts[]`, `lower_courts[]`, `applications[]`, `objections[]`, `court_transfers[]`, `writ_info[]`, `ownership {primary {office_code, office_name, unit {code, name}?, officer {id, full_name}?, claimed_at}?, watchers [office_code]}`, `custody {holder_office {code, name}, holder_user {id, full_name}?, pending_action?, since, due_date?}?`, `access_basis [str]`, `claimable`, `dossier_status`, `merged_into_ref_no?`, `counts {hearings, orders, listings, links, timeline}`) | `can_view_case` |
| `GET /cases/{ref}/parties` | read | `?include_former=false` | `{parties: [PartyOut {role, party_no, name, address?, has_legal_heir, is_current}], advocates: [AdvocateOut {side, name_as_listed, counsel_code?, bar_reg_no?, is_current}]}` | same |
| `GET /cases/{ref}/hearings` | read | `limit`, `offset` | `{items: [HearingOut {business_date, hearing_date?, purpose?, bench_text?, judge_designation?, causelist_type?, next_date?, business_text?, short_order_text?, case_number_text?, source}], total}`, newest first | same |
| `GET /cases/{ref}/orders` | read | `limit`, `offset` | `{items: [OrderOut {id, order_no, order_date, kind, order_details?, order_judge_name?, date_judgement_pronounced?, date_judgement_reserved?, is_reportable?, download_status, document_id?}], total}`, newest first (the file itself: `documents-uploads`) | same |
| `GET /cases/{ref}/listings` | read | `limit`, `offset` | `{items: [ListingOut {list_date, list_type, bench_label?, bench_id?, court_no?, sr_no, printed_sr?, counsel_codes [str], remarks?, source}], total}`, newest first | same |
| `GET /cases/{ref}/links` | read | | `{items: [LinkOut {direction: out\|in, kind, case_no_text?, cnr?, filing_number_text?, source, case: CaseSummaryOut?, visible}]}` | same; linked summaries per decision 8 |
| `GET /cases/{ref}/links/graph` | read | `?depth=2` (1–3) | `{nodes: [{key, case: CaseSummaryOut?, case_no_text?, visible}], edges: [{from, to, kind}], truncated}` | same |
| `GET /cases/{ref}/timeline` | read | `limit`, `offset` | `{items: [TimelineOut {type, label, icon_key?, occurred_at, actor_name?, payload}], total}` | same; types per decision 15 |
| `POST /cases/search-court` | `cases.search_court` | `{kind: "cnr", cnr}` \| `{kind: "case_number", case_type, reg_no, reg_year}` \| `{kind: "party", name, reg_year, pend_disp: "P"\|"D"\|"both"}` | 200 `{source: local\|court, calls, created, items: [CaseSearchItemOut + dossier_status], unmatched: [{type_name?, reg_no?, reg_year?, pet_name?, res_name?}]}`; 400 bad input; 429 `search_limit`; 502 `napix_unavailable`; 503 `napix_off` / `napix_budget`; 504 `napix_timeout` (error body `{code, message, retry_after?}`) | results carry `visible`; details still need visibility |
| `POST /cases/{ref}/fetch-court` | `cases.search_court` | | 200 `CaseSearchItemOut + dossier_status`; 404 `not_found_at_court`; 409 `already_fetched`; the errors above | the case need not be visible (decision 10) |

`GET /cases/{ref}/ownership` (recommend-and-claim) is unchanged.

## Jobs
None new. `search-court` and `fetch-court` queue the found case's order PDFs through the existing
`enqueue_order_pdfs` (`order_pdf`, priority 80). Cases created by search join the daily Current Status batches
and the weekly dossier sweep like every non-disposed case (`services/tracking.py`), and the dirty rescore like
every case.

## Tests
Unit (`tests/unit/test_case_search_parse.py`):
- `parse_query` detects id, `ref_no` (both forms), CNR (lower case accepted), `WP(C)/4326/2025`,
  `WP(C) 4326/2025`, `wa 435/2024`, text; refuses `q` under 3 characters; `field=party` forces text;
- `tsquery_text` keeps at most 8 words, drops one-letter words, strips punctuation, applies `:*A` / `:*B` /
  `:*AB`; an input such as `x' | !(y` yields only word characters and the operators it wrote itself.

Database (`tests/db/test_case_visibility.py`, the shared world plus an `EDU-SC` unit with a `standing_counsel`
user and the active code `SC, EDU` mapped to `EDU-DSE`):
- the super admin, oversight, auditor and central operator see every case (`access_basis == ["state"]`);
- the `EDU` admin and head see a case `EDU` owns (primary and watcher), a case recommended to `EDU`, a pool
  case; not a case `HEALTH` owns (`can_view_case` false, detail 404);
- a pool case is not visible to an `EDU` officer (no `cases.claim`) and is visible to the `EDU` admin;
- an `EDU` officer sees only the case allotted to them; `dse_user` sees cases allotted to `EDU-DSE`, not those
  allotted to `EDU-DHE`;
- after an accepted transfer `EDU` → `HEALTH`, `EDU` loses sight of it; with `stay_as_watcher` it keeps it;
- custody: a custody row at `EDU-DSE` makes the case visible to `dse_user`; a custody row held by `edu_off2`
  makes it visible to `edu_off2`, not to `edu_off1`;
- request: an open request to `EDU-DHE` makes the case visible to `dhe_user`, a withdrawn one does not; a
  request addressed to the referral reviewer personally makes it visible to them, one addressed only to the
  `EDU` office does not;
- counsel: a case whose cause-list entry carries `SC,EDU` (unnormalised) is visible to the standing counsel; one
  with only `PP, ASSAM` (generic) or `SC, HEALTH` is not; a current `case_advocates.counsel_code` match counts,
  a non-current one does not; a deactivated code stops matching;
- a user whose `cases.view_scope` is denied by override sees nothing (403 on `GET /cases`);
- **one rule**: for every world user and a fixed set of 12 cases, `GET /cases` returns exactly the cases for
  which `can_view_case` is true, and `GET /cases/search` marks exactly those `visible`.

Database (`tests/db/test_case_search.py`):
- the migration backfill fills `search_vector`; `apply_dossier` and `apply_entries` refresh it (a party added
  by a new dossier is found with `field=party`);
- a provisional case known only from a cause list is found by a petitioner word of its entry;
- `field=party` does not match an advocate-only word and `field=advocate` does not match a party-only word;
- number search finds `WP(C)/4326/2025` from `wp(c) 4326/2025` and through a case-type alias; a filing number is
  found;
- filters `status`, `year`, `case_type`, `office` (active primary owner), `listed_from` / `listed_to` narrow the
  result; merged cases never appear;
- `total` stops at 10,000 with `total_capped` true (generated rows);
- items carry `owner_office_code`, `in_pool`, `claimable` (true for the `EDU` admin on a pool case, false for
  an officer).

Database (`tests/db/test_case_detail.py`, a case loaded from `cnr_pending.json` through `apply_dossier`):
- the overview carries every typed column of coverage §C that the sample fills (checked against the sample's
  keys, so a column missing from the response fails), the court and bench, the child lists, ownership, custody,
  `access_basis`, `dossier_status`, counts;
- `/parties?include_former=true` adds a party marked not current by a second dossier;
- `/hearings`, `/orders`, `/listings` are newest first and paginate; `/orders` exposes `download_status` and
  `document_id`, no file;
- `/links` lists an outgoing `main_matter` link resolved to a held case with `visible` false for a caller who
  cannot see it (summary only), and an incoming link; `/links/graph` stops at the depth and at 200 nodes with
  `truncated`;
- `/timeline` shows court and ownership events, hides `HEALTH`'s `recommendation_made` from the `EDU` admin and
  shows it to the auditor, and shows no `note_added` event;
- every detail endpoint answers 404 for an unknown ref and for a case not visible, 401 without a token.

Database (`tests/db/test_court_search.py`, the scripted gateway extended with Search by Case Number and Search
by Party Name from `case_search_2026-09-03.json` and `party_name_2026-09-03.json`):
- switch off → 503 `napix_off` and no `napix_call_log` row (settings overridden in the test, never in code);
- `cnr` for a held case with a dossier → `source: local`, `calls: 0`; for a new CNR → one call, a case with
  `first_seen_source = search`, the dossier applied, order PDFs queued, an audit row `case.search_court`;
- `case_number` `WA 435/2024` → one search call and one dossier call, the row stored; an unknown `case_type` →
  400 and no call;
- `party` stores the three sample rows (the I.A. row included) with summaries and `case_type_id`, fetches no
  dossier, scores them (a keyword rule matching a sample party yields a score row), stores the verbatim response
  in `napix_responses`; `pend_disp: both` makes two calls;
- a row with an invalid `cino` is returned in `unmatched` and creates no case;
- search fields never overwrite a dossier-filled column;
- floor: a `napix_call_log` row this hour with `rate_limit_remaining` below `NAPIX_SEARCH_FLOOR` → 503
  `napix_budget` with `retry_after`; a row from the previous hour does not block;
- the 31st search of a user within an hour → 429, and the audit count stays 30;
- a gateway 500 on every retry → 502, and the `napix_call_log` rows and the audit row with `outcome: failed`
  are committed (read back in a new session);
- `fetch-court` on a party hit → dossier applied; again → 409 `already_fetched`; on a provisional case without
  CNR whose number resolves → the CNR filled from the court (never invented); unresolvable → 404
  `not_found_at_court`, the case unchanged; a directorate user (no `cases.search_court`) → 403;
- `tests/db/test_pipeline.py` stays green with the runner calling `court_search`.

## Verification
With Compose up (`docker compose up -d`), migrations at head `0005`, `aslms seed`, the January 2025 week loaded,
and the recommend-and-claim verification world in place (`EDU`, `EDU-DSE`, `HEALTH`, their admins and officers,
a few counsel codes):
1. `SELECT count(*) FILTER (WHERE search_vector IS NULL), count(*) FROM cases` → 0 NULL;
   `\di ix_cases_search_vector_gin` exists.
2. Create `EDU-SC` (unit under `EDU`) and a `standing_counsel` user there; map `SC, EDU` to `EDU`. As that user,
   `GET /cases?limit=5` → only cases with `SC, EDU` in an entry or a current advocate row; `aslms cases show
   <ref> --as <counsel e-mail>` prints `["counsel"]`.
3. As the `EDU` admin: `GET /cases/search?q=STATE%20OF%20ASSAM` → rows mixing `visible` true and false;
   `GET /cases/search?q=<a CNR of the week>` → that case first with `match: "cnr"`;
   `GET /cases/search?q=WP(C)%20<no>/<year>` → the case; a party word from a cause-list entry finds a
   provisional case.
4. `GET /cases/<a visible ref>` → 200 with `access_basis`, parties, ownership; `/hearings`, `/orders`,
   `/listings`, `/links`, `/links/graph`, `/timeline` → 200. The same refs as the `HEALTH` officer → 404.
5. As an `EDU` officer, `GET /cases` → only the cases allotted to them (compare with `SELECT case_id FROM
   case_ownership WHERE officer_user_id = … AND status = 'active'`).
6. As the auditor, `GET /cases?limit=1` → `total` equals `SELECT count(*) FROM cases WHERE merged_into_case_id
   IS NULL` (or 10,000 with `total_capped`).
7. With `NAPIX_ENABLED=false` (the default): `POST /cases/search-court {"kind":"cnr","cnr":"<a CNR not held>"}`
   → 503 `napix_off`.
8. Only if the owner runs a live check with the switch set for that run: as the `EDU` admin, `POST
   /cases/search-court {"kind":"party","name":"<a department party name>","reg_year":2024}` → items with
   `dossier_status: not_fetched`; `POST /cases/<first ref>/fetch-court` → `fetched`; `GET
   /cases/search?q=<that CNR>` finds it locally; `SELECT api, count(*) FROM napix_call_log WHERE called_at >
   now() - interval '10 minutes' GROUP BY 1` shows the party-name and CNR calls; `SELECT action,
   after->>'outcome' FROM audit_log WHERE action LIKE 'case.%court' ORDER BY created_at DESC LIMIT 5`.
9. `pytest -q` green, `ruff check` clean.

## Open questions
None. Points the owner may wish to overrule at approval:
- decision 2, the standing-counsel rule taken from the 26 Sep log (a counsel user in a counsel office under a
  department sees every case carrying a code mapped to that department, claimed or not), keyed on the user type;
- decision 2, department-wide callers (holders of `cases.claim`) read the full detail of every pool case;
  officers and directorate users do not;
- decision 3, a department that transferred a case away no longer sees it unless it stayed as a watcher;
- decision 4, any user who can read cases sees the **summary** of every case in search (court-public data),
  including the owning department's code; details only within access;
- decision 9, party-name hits are stored but their dossiers are fetched only on demand (`fetch-court`) or by the
  weekly sweep;
- decision 12 (**deviation, scope**), NAPIX Search by Advocate Name and by Filing Number wait for live samples
  (backlog row 21); both are searched locally meanwhile;
- decision 13, the defaults: search floor 50 calls, 30 court searches per user per hour, 60-second timeout;
- decision 14, reading cases is not audited.
