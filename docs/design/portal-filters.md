# Design: Portal — one filter bar on every list (inbox, Files, Alerts, Search) and the server-side filters behind it

```
slug: portal-filters
status: approved
author: architect
date: 2026-10-13
approved_by: owner (nayanlhuzuri) on 2026-10-13
```

## Context
Backlog row 59, the owner's request of 13 Oct 2026 ("there should be a filter everywhere"): "Recommended, Claimed
(active and disposed), Unclaimed pool, Transfers, Files (all tabs), Alerts and Search get one consistent filter bar —
cause-list date as any date or range (the Recommended tab has only today / 7 / 30 days today), next hearing date
range, case type, year, status, court / bench, department where relevant, and words; filters in the query string;
server-side filtering in the list APIs where a filter is missing." Recorded in the decisions log under "Owner
decisions of 13 Oct 2026".

The plan: §5.2 (Search) "with filters for status, year, case type and department"; §5.3 the overview shows "court and
bench"; §5.4 the inbox tabs and the Unclaimed pool "that the department can search and claim"; Annexure B "Case inbox"
shows a cause-list date filter; the cause-list rows of §4 ("Cause List Bench — all cases listed before each bench").
Visibility rules (CLAUDE.md, plan §6) bind: a filter only ever narrows what the API already returns to the caller.

What each list API filters today (the gaps this item closes):

| List | API | Has | Missing |
|---|---|---|---|
| Recommended | `GET /inbox/recommended` | `band`, `q` (substring), `listed_from` / `listed_to` | next hearing, case type, year, status, court, bench |
| Claimed (Active / Disposed) | `GET /inbox/claimed` | `case_state`, `role`, `unit`, `officer_user_id`, `q` (substring) | cause-list date, next hearing, case type, year, court, bench |
| Unclaimed pool | `GET /inbox/pool` | `q` (substring), listed range, `status`, `case_type` (exact text only), `year`, `min_score`, `state_party` | next hearing, court, bench, department |
| Transfers | `GET /inbox/transfers` | `direction`, `status` (of the transfer) | every case filter, the other department |
| Files (With me, My offices, Department files) | `GET /custody/held` | `scope`, `overdue`, `holder_department` | every case filter, owning department |
| Files (Sent) | `GET /custody/sent` | — | every case filter, owning department |
| Alerts | `GET /alerts` | `status`, `kind`, `severity`, `unread`, `case` | every case filter, owning department |
| Search (no words) | `GET /cases` | `q`, `status`, `case_state`, `year`, `case_type`, `office`, listed range, next range | court, bench |
| Search (words) | `GET /cases/search` | `q`, `field`, `status`, `year`, `case_type`, `office`, listed range, `visible_only` | next hearing, court, bench |
| Search (order and document text) | `GET /documents/search` | `q`, `case`, `group`, `doc_type`, `date_from` / `date_to` | nothing; the portal sends only `q` |

The portal screens (rows 12, 13, 55) each draw their own few controls (`useFilters` in `inbox/common.tsx`, `params.ts`),
so the same filter looks and behaves differently from tab to tab; "words" means a substring on the inbox and parsed
words on Search; the pool's case type matches only the exact text while Search also matches the master's short name
and aliases.

In place and reused: `services/case_search.py` (`parse_query`, `_case_type_filter`, `_office_filter`,
`_listed_filter`, `_status`), `services/inbox.py` (`_q_condition`, `_listed_condition`, the `*_stmt` builders used by
the dashboard), `services/custody.py::held | sent`, `services/alerts.py::list_for_user`, the `require_any` dependency,
`GET /reference/case-types` with `useCaseTypes()`, `useDepartments()`, `useDocumentTypes()`, `useFilters`,
`params.ts`, the UI kit, `messages.ts`, `format.ts` (`istDay`, `addDays`). The data in the dev database (13 Oct 2026):
29,627 cases, all at GAHC01 (Principal Seat; the Kohima, Aizawl and Itanagar establishments hold none); 57,744
cause-list entries from 3 Jan 2025 to 13 Oct 2026, every one with `court_no` (27 values, `1`-`25`, `111`, `115`) and
`bench_text` (81 distinct judge-name strings, division benches as "HONOURABLE THE CHIEF JUSTICE, HONOURABLE MR.
JUSTICE …"); indexes on `causelist_entries.case_id` and `causelists.list_date` already exist.

Not covered: the Cause list screen for a date and bench (row 60, which builds its own per-date cause-list API); the
hearing calendar (its range is its filter, row 55); sort orders (each list keeps the API's order); the reports screen
(row 39) and the audit screen (row 41), which have their own filters in their APIs; administration lists (users,
offices, mapping, tickets, data console).

## Decisions
1. **One shared set of case filters, the same names in every list API and every portal URL.**
   | Filter | API parameter(s) | Meaning |
   |---|---|---|
   | Words | `q` | As the Search box (decision 3) |
   | Cause-list date | `listed_from`, `listed_to` | The case has a cause-list entry dated in the range (either end open; one date = both ends equal) |
   | Court | `court_no` | That same entry was in this court number, as printed in the cause list |
   | Bench | `bench` | That same entry's bench (judge names) contains this text (decision 4) |
   | Next hearing | `next_from`, `next_to` | `cases.next_hearing_date` in the range |
   | Case type | `case_type` | As Search: the master's short name or aliases, or the case's type text |
   | Year | `year` | `cases.reg_year` |
   | Status | `case_status` | `pending`, `disposed` or `unknown` (`cases.status`) |
   | Department | `owner` | The department holding the active primary ownership (where relevant, decision 5) |
   Every condition is ANDed with the list's own rules; none widens what the caller sees. Alternatives: adding the
   missing parameters list by list under each list's current names (the same filter would keep three names and three
   behaviours, which is what the owner asked to end).
2. **Old names stay accepted where they already meant the same thing.** On `GET /cases`, `GET /cases/search` and
   `GET /inbox/pool`, `status` stays an accepted name for `case_status`, and on `/cases` and `/cases/search` `office`
   stays an accepted name for `owner` (both marked deprecated in OpenAPI); giving both names with different values is
   400. On `/inbox/transfers` and `/alerts`, `status` keeps meaning the transfer's or the alert's status, which is why
   the case's status is `case_status`; on the inbox endpoints `office` keeps meaning the department the inbox is read
   for, which is why the owning department is `owner`. The portal sends only the new names. Alternative: renaming
   outright (only the portal calls these today, but the existing tests and any bookmarked API call would break for no
   gain).
3. **Words mean the same everywhere: the Search box's parsing.** `q` (at least 3 characters) is read by
   `parse_query` in auto mode: a CNR, a case number (`WP(C) 4326/2025`), a `ref_no`, or words matched as prefixes over
   `cases.search_vector` (party names and summaries and cause-list party texts, advocates, counsel codes and
   cause-list advocate texts, CNR and numbers). The inbox's substring match (`_q_condition`, ILIKE over CNR, case
   number and party texts) is replaced. Gains: advocates and counsel codes become searchable on the inbox, a typed case
   number works on every tab, the GIN index is used. Loss: a fragment in the middle of a word ("ssam") no longer
   matches; prefixes ("Assa") still do. The `field` parameter stays on the two Search endpoints only. On lists the
   words narrow; the order stays the list's own (only Search ranks by relevance). Alternative: keeping the substring
   on the inbox (the owner asked for one behaviour; the substring scan cannot use an index as the data grows).
4. **Court and bench are read from the cause list, on the same entry as the cause-list date.** "Court" is the court
   number printed in the list (`causelist_entries.court_no`, exact match after trimming), "bench" the judges printed
   for that entry (`causelist_entries.bench_text`): the condition is one `EXISTS` over the case's entries with every
   given part (date range, court, bench) on the same entry, so "listed on 25 Sep in court 3" means that day in that
   court, not two different days. Without a date the court and bench match any listing of the case. The bench text
   matches when the entry's text, upper-cased with white space collapsed, contains the given text normalised the same
   way (LIKE wildcards in the input escaped; 3 to 200 characters): choosing "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA"
   also finds that judge's division-bench listings, and typing a surname ("SAIKIA") works. Not used: the court
   establishment (`courts`: every case is at the Principal Seat today, so the choice would change nothing; a filter can
   be added when an outlying bench's cases arrive), the NAPIX bench id (it changes daily, schema `benches`), and the
   case's dossier bench (`cases.bench_id`, the last bench seen, often stale). Alternatives: bench as the case's
   current dossier bench (stale; differs from what the cause list says); a judge master (none exists in NAPIX;
   splitting the printed strings into judges would be guesswork).
5. **"Department where relevant", per list.**
   - Search (both modes), Files (all four tabs) and Alerts: `owner`, the owning department (primary, active); with
     `owner` set, unclaimed cases drop out. Options: every active department (`useDepartments()`); on Department files,
     only the departments the login tracks (the list holds nothing else).
   - Unclaimed pool: no owner exists, so the new `scored_for` (a department code) keeps cases with a score row for that
     department (`case_office_scores`); with `min_score` the same row must reach it ("matched to FIN at 0.40 or more").
     Label "Matched to department".
   - Transfers: the new `other_office`, the department on the other side (`from` for In, `to` for Out, either side
     without a direction).
   - Recommended and Claimed: none (the tab is already read for one department, `office`).
   Alternatives: the owner filter on the pool (always empty there); the pool's "best department" only (narrower: a case
   matched to two departments would show under one).
6. **Server-side everywhere; one filter module.** A new `services/case_filters.py` holds `CaseFilters` (a frozen
   dataclass of decision 1), `parse(...)` (validation, decision 7) and `conditions(session, filters, case=Case) ->
   list[ColumnElement[bool]]` (SQL over a `Case` entity or alias). The SQL pieces now in `case_search.py`
   (`parse_query`, the case type, owner, listing and status conditions) move into it; `case_search.py` and `inbox.py`
   import them from there (it imports neither, so no import cycle). Every list service takes `filters: CaseFilters |
   None = None` and ANDs `conditions(...)`; the `*_stmt` builders keep their current parameters so the dashboard
   and reports calls are unchanged. The pool's exact-text case type is replaced by the shared condition (widening it
   to the master's short names and aliases, as Search does). Alternative: filtering in the browser (lists are paged by
   50; a filter must be in SQL to be right).
7. **Validation on the server, the same messages everywhere.** `CaseFilterError(ValueError)` → 400 with the message
   (the routers already map `ValueError` to 400): a range whose start is after its end ("listed_from is after
   listed_to", "next_from is after next_to"); `year` outside 1900-2100; `case_status` not one of the three; `q` under 3
   characters or without a searchable word; `bench` under 3 or over 200 characters; `court_no` over 20 characters;
   `owner`, `scored_for` or `other_office` not a department; `case_type` empty. The portal checks the same before
   sending (decision 11) and shows the server's message if one still comes back.
8. **Filters on cases a list shows without the caller seeing them.** Files → Sent lists legs for cases the sender may
   no longer open, and an alert can name such a case (`case_visible` false); the filters there match the facts the row
   already shows (the court-public summary, the owner code that Search shows for any case), so they reveal nothing
   new. With any case filter set, alerts without a case (admin-ticket notices) drop out of the Alerts list; the bar
   says so under the filters ("Alerts without a case are hidden while case filters are set.").
9. **One filter bar component in the portal.** `FilterBar` (`src/components/filters/`) draws the shared fields a list
   declares plus that list's own controls, in one form:
   - first row: Words, Cause-list date, Next hearing, Case type, and the list's main own control (match strength,
     alert status, Overdue only …);
   - "More filters" (a disclosure, open whenever one of its fields is set): Year, Status, Court, Bench, Department and
     the list's remaining own controls;
   - under the form, one chip per applied filter ("Cause list: 25 Sep 2026", "Bench: … SAIKIA", "Department: FIN"),
     each with a remove button, and "Clear all";
   - the filtered `total` above the list ("128 cases match" / "128 alerts match").
   The whole bar applies with "Apply" (Enter in any field submits), so a date range is never half-applied; removing a
   chip and "Clear all" apply at once. Any change resets the page offset (existing `useFilters`). Tab badges keep the
   unfiltered counts of `/inbox/counts` (they say what is waiting, not what matches). Alternative: applying each
   select on change as today (a two-field range would fire a request on the first field; the tabs did it differently).
10. **Dates: presets plus any date or range, in the query string.**
    - Cause-list date: Any, Today, Tomorrow (the next day's list is published the evening before), Last 7 days, Last
      30 days, A date, Between dates. URL: a preset as `listed=today|tomorrow|d7|d30` (worked out in IST each time the
      page opens, so a bookmarked "Today" stays today; the existing Recommended links keep working), or explicit
      `listed_from` / `listed_to` (A date writes both the same). Explicit dates win over a preset.
    - Next hearing: Any, Today, Next 7 days, Next 30 days, A date, Between dates. URL `next=today|n7|n30` or
      `next_from` / `next_to`.
    Dates are shown and entered as IST days; the API receives ISO dates.
11. **Which fields each list shows** (one table, `LIST_FILTERS` in `src/lib/filters.ts`):
    | List | Shared fields | Its own controls (kept) |
    |---|---|---|
    | Recommended | words, cause-list date, next hearing, case type, year, status, court, bench | match strength |
    | Claimed → Active / Disposed | words, cause-list date, next hearing (Active only), case type, year, court, bench (status is the Active / Disposed split) | role, unit, officer (with `cases.allot`) |
    | Unclaimed pool | all except department; plus "Matched to department" | minimum score, State is a party |
    | Transfers → In / Out | all except department; plus "Other department" | transfer status |
    | Files → With me, My offices | all, department = owner | Overdue only |
    | Files → Department files | all, department = owner (tracked departments only) | Overdue only, holder department |
    | Files → Sent | all, department = owner | — |
    | Alerts | all, department = owner | alert status, kind, severity, Unread only |
    | Search → Cases | all, department = owner | "Only cases I can open" (with words) |
    | Search → Order and document text | — (not case filters) | document group, document type, document date range (the existing API parameters, now offered) |
    On Search the separate Active / Disposed / All control of the no-words list is replaced by Status (one control for
    one fact; the API keeps `case_state`). Pickers: case types from `useCaseTypes()`, departments from
    `useDepartments()`, court numbers and bench texts from the new `useBenches()` (decision 12); Bench is a text field
    with suggestions (`<datalist>`), Court a select.
12. **One read-only reference endpoint for the court and bench pickers.** `GET /reference/benches?days=` (default 90,
    1-400): the court numbers and bench texts seen in cause lists dated in the last `days` days up to today (IST), each
    with the last date it appeared and its entry count; court numbers ordered numerically then as text, benches by
    text. Court-public data (what the published cause list prints), the same for every reader; gated like
    `/reference/case-types`. Row 60 may reuse it; its per-date bench list is its own. Alternative: typing the court
    and bench by hand only (judge names are long and must match the printed text).
13. **Old portal links keep working.** On Search and the pool, a URL `status=` (the case status, row 12) is read as
    `case_status`, and on Search `office=` as `owner`, once, and rewritten to the new keys at the next apply. The Recommended
    `listed=` presets keep their meaning.
14. **Look, language and checks as before.** CSS Modules and the shell tokens, the UI kit (new `FilterBar`,
    `DateRangeField`, `FilterChips`), WCAG 2.1 AA (each field labelled, the disclosure a button with `aria-expanded`,
    chips' remove buttons named "Remove filter Bench: …", errors linked with `aria-describedby`), strings in
    `messages.ts` (`T.filters`), no new npm dependency. Nothing is written, audited or sent to SourceTrace by
    filtering: reading lists is never audited, as today.

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): court and
bench read from the cause-list entry, on the same entry as the date, with the bench as "contains" (4); words parsed as
the Search box everywhere, ending the substring match on the inbox (3); the department filter per list, with
"Matched to department" on the pool and "Other department" on Transfers (5); the whole bar applying on "Apply" (9);
Status replacing Active / Disposed / All on Search (11).

## Data
No table, column, constraint, index, reference code, `Permission` or setting is added; no migration;
`docs/schema/schema.md` is unchanged. Every filter reads existing columns: `cases` (`status`, `reg_year`,
`case_type_id`, `case_type_text`, `next_hearing_date`, `search_vector`), `causelists.list_date`,
`causelist_entries` (`case_id`, `court_no`, `bench_text`), `case_ownership`, `case_office_scores`,
`ownership_transfers`. The listing condition uses the existing `ix_causelist_entries_case_id` and
`ix_causelists_list_date`; words use `ix_cases_search_vector_gin`. If the integrator's timing (Verification step 4)
exceeds the bound, an index is proposed as a new row with its own migration, not added here.

## Services
Backend (Python):
- `services/case_filters.py` (new): `CaseFilterError(ValueError)`; `@dataclass(frozen=True) CaseFilters` with `q`,
  `listed_from`, `listed_to`, `court_no`, `bench`, `next_from`, `next_to`, `case_type`, `year`, `case_status`,
  `owner` and `is_empty`; `parse(**values) -> CaseFilters` (trims, upper-cases codes, normalises the bench text,
  validates as decision 7; parses `q` once); `conditions(session, f, case=Case) -> list` — `parse_query` condition
  (moved, with `_number_condition`, `matching_case_types`, `case_type_ids`, `compact`, `words_of`, `tsquery_text`),
  `listing_condition(listed_from, listed_to, court_no, bench, case)` (one `EXISTS` over `causelist_entries` ⋈
  `causelists`, decision 4), next-hearing range, `case_type_condition` (moved `_case_type_filter`), `reg_year`,
  `status`, `owner_condition` (moved `_office_filter`); `text_rank(f, case)` for Search's ordering. Pure SQL building;
  no write, no audit.
- `services/case_search.py`: `search` and `list_visible` take `filters: CaseFilters` (plus `field_`, `visible_only`,
  `case_state`) and use `case_filters`; `parse_query` and the helpers are re-exported for existing imports
  (`court_search`, tests).
- `services/inbox.py`: `recommended`, `claimed`, `pool`, `transfers` take `filters: CaseFilters | None`;
  `recommended_stmt`, `claimed_stmt`, `pool_stmt`, `transfers_stmt` take an optional `filters` (default none, so the
  dashboard's counts are unchanged); `_q_condition` and `_listed_condition` removed (their callers use
  `case_filters`); `pool_stmt` gains `scored_for: Office | None` (with `min_score` on the same score row) and uses the
  shared case-type condition; `transfers_stmt` gains `other: Office | None`.
- `services/custody.py`: `held` and `sent` take `filters: CaseFilters | None` (conditions on the joined `Case`).
- `services/alerts.py`: `list_for_user` takes `filters: CaseFilters | None`; with a non-empty filter the outer join to
  `Case` behaves as inner (case-less alerts drop out, decision 8).
- `services/reference.py`: `benches(session, *, days: int, today: date | None = None) -> dict` — `{from, to,
  court_numbers: [{court_no, last_listed, entries}], benches: [{text, last_listed, entries}]}` from
  `causelist_entries` ⋈ `causelists` with `list_date` in the window (`today` defaults to `today_ist()`).
- `api/filters.py` (new): the FastAPI dependency `case_filter_query(...) -> CaseFilters` declaring the shared query
  parameters once (types, descriptions), raising 400 on `CaseFilterError`; `with_legacy(f, status=…, office=…)` for
  decision 2.
- Routers: `inbox.py`, `cases.py`, `workflow.py` (`/custody/held`, `/custody/sent`, the latter now catching `HANDLED`),
  `alerts.py` add `filters: CaseFilters = Depends(case_filter_query)` and pass it on; `inbox.py` adds `scored_for`
  (pool) and `other_office` (transfers); `reference.py` adds `/benches`.
- `api/schemas.py`: `BenchesOut`, `CourtNumberOut`, `BenchTextOut`. `frontend/openapi.json` and
  `src/lib/api/schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/lib/filters.ts` (new, plain module): `FILTER_KEYS`, `LIST_FILTERS` (decision 11), `resolveDates(params, now)`
  (presets to IST dates, decision 10), `toApiQuery(params, list, now)`, `legacyParams(params, list)` (decision 13),
  `chipsOf(params, labels)`, `validate(form) -> errors`.
- `src/lib/api/hooks.ts`: `useBenches()` (key `["reference","benches"]`, 30 minutes).
- `src/components/filters/*` (new): `FilterBar`, `DateRangeField` (preset select plus one or two date inputs),
  `FilterChips`.
- Changed to use `FilterBar`: `inbox/Recommended.tsx`, `inbox/Claimed.tsx`, `inbox/Pool.tsx`, `inbox/Transfers.tsx`,
  `files/Held.tsx`, `files/Sent.tsx`, `alerts/AlertList.tsx`, `search/Search.tsx`, `search/TextSearch.tsx` (document
  group, type and date range); each list's query key carries the API query, so a filter change re-reads it.
- `src/lib/messages.ts`: `T.filters` (field labels, presets, chips, the "n match" line, the case-less alerts line, the
  validation messages).

Audit and events: none. Filtering is reading; no list read writes an `audit_log` or `events` row (as today), and the
reference endpoint writes nothing.

## API
Changed or new (FastAPI). "Shared filters" are the parameters of decision 1: `q`, `listed_from`, `listed_to`,
`court_no`, `bench`, `next_from`, `next_to`, `case_type`, `year`, `case_status`, `owner`. Every function gate and
visibility rule is unchanged; filters only narrow.

| Method, path | Function required (unchanged) | Request (added) | Response | Visibility |
|---|---|---|---|---|
| `GET /inbox/recommended` | `cases.claim` in the department, or `cases.view_all` | shared filters except `owner` | unchanged | the department's active recommendations, then the filters |
| `GET /inbox/claimed` | `cases.view_scope` | shared filters except `owner` | unchanged | `claimed_conditions`, then the filters |
| `GET /inbox/pool` | `cases.claim` or `cases.view_all` | shared filters except `owner`; `scored_for`; `status` kept as an alias of `case_status` | unchanged | never-owned non-merged cases, then the filters |
| `GET /inbox/transfers` | `cases.transfer_request` or `cases.transfer_decide` in the department, or `cases.view_all` | shared filters except `owner`; `other_office` | unchanged | the department's transfers, then the filters |
| `GET /custody/held` | `cases.view_scope` or `cases.view_all` (`scope=owned`: `custody.track` in a department) | shared filters | unchanged | as today (`visible_case_condition` and the scope), then the filters |
| `GET /custody/sent` | `cases.view_scope` or `cases.view_all` | shared filters | unchanged; 400 on a bad filter | the caller's own legs, then the filters on their cases |
| `GET /alerts` | `cases.view_scope` or `cases.view_all` | shared filters | unchanged | `notification_visible_condition`, then the filters (case-less alerts drop out when any is set) |
| `GET /cases` | `cases.view_scope` or `cases.view_all` | `court_no`, `bench`, `case_status`, `owner` (`status`, `office` kept as aliases) | unchanged | visible cases only, then the filters |
| `GET /cases/search` | `cases.view_scope` or `cases.view_all` | `court_no`, `bench`, `next_from`, `next_to`, `case_status`, `owner` (`status`, `office` kept as aliases) | unchanged | every match as a court-public summary with `visible` (unchanged), then the filters |
| `GET /reference/benches` (new) | `cases.view_scope` or `cases.view_all` (`require_any`) | `days` (1-400, default 90) | `{from, to, court_numbers: [{court_no, last_listed, entries}], benches: [{text, last_listed, entries}]}` | court-public cause-list data, the same for every reader |

Errors: 400 with the `CaseFilterError` message (decision 7); a legacy name and a new name with different values → 400
"status and case_status differ" / "office and owner differ". Used as they are: `GET /documents/search`
(`documents.view`; `group`, `doc_type`, `date_from`, `date_to` now sent by the portal), `/reference/case-types`,
`/custody/recipients`, `/inbox/counts`, `/me`.

Web server: no new route; the relay passes query strings as today.

## Jobs
None.

## Tests
Backend (pytest, `backend/tests/`, the shared world of `tests/db/world.py` with cause-list entries on two dates, two
courts and two benches, one of them a division bench):
- `unit/test_case_filters.py` (new): `test_parse_rejects_reversed_listed_range`; `test_parse_rejects_reversed_next_range`;
  `test_parse_rejects_year_out_of_range`; `test_parse_rejects_unknown_case_status`; `test_parse_short_q_and_bench`;
  `test_bench_normalised_and_wildcards_escaped` (`%` and `_` in the input match literally); `test_empty_filters_add_no_condition`.
- `db/test_case_filters.py` (new): `test_listing_date_court_bench_on_same_entry` (listed 1 Oct in court 3 and 2 Oct in
  court 5: `listed_from=listed_to=1 Oct&court_no=5` finds nothing); `test_court_without_date_matches_any_listing`;
  `test_bench_contains_finds_division_bench_listings`; `test_next_hearing_range`; `test_case_type_matches_master_alias`;
  `test_owner_is_active_primary_only` (a watcher's department does not match); `test_words_parse_cnr_number_and_prefix`.
- `db/test_api_inbox.py` (added): `test_recommended_filters_case_type_year_status_court_bench_next`;
  `test_claimed_filters_listed_and_next`; `test_pool_case_type_uses_master_names`; `test_pool_scored_for_with_min_score_same_row`;
  `test_pool_status_alias_and_conflict_400`; `test_transfers_case_filters_and_other_office`;
  `test_inbox_words_match_advocate_and_case_number`; `test_filters_never_widen_claimed_scope` (an officer's Claimed
  with filters returns a subset of the same list without them); `test_dashboard_counts_unchanged_by_filters_module`.
- `db/test_custody_held.py` or the existing custody list tests (added): `test_held_filters_each_scope`;
  `test_held_owner_filter_for_two_tracked_departments`; `test_sent_filters_invisible_case_rows`; `test_sent_bad_filter_400`.
- `db/test_api_alerts.py` (added): `test_alert_list_case_filters`; `test_case_filters_hide_caseless_alerts`;
  `test_alert_filters_keep_visibility`.
- `db/test_api_cases.py` (added): `test_list_court_and_bench`; `test_search_next_range_court_bench`;
  `test_owner_and_office_alias_and_conflict_400`; `test_case_status_alias`.
- `db/test_api_reference.py` (added): `test_benches_window_counts_and_order` (court numbers `2` before `10` before
  `111`); `test_benches_days_bounds_400`; `test_benches_need_case_reading`; `test_benches_signed_out_401`.
- `db/test_filters_write_nothing.py` (new): reading every filtered list writes no `audit_log` or `events` row.
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, the `fakeApi` helper):
- `lib/filters.test.ts` (new): presets resolve in IST near midnight (`today`, `tomorrow`, `d7`, `d30`, `n7`, `n30`);
  explicit dates win over a preset; `toApiQuery` sends only the fields `LIST_FILTERS` allows for that list (no
  `owner` on Recommended, `scored_for` on the pool, `other_office` on Transfers); `legacyParams` maps `status` and
  `office` on Search and the pool; `validate` refuses a reversed range, a 3-digit year, a 2-character word; chips for
  every field.
- `components/filters/filterbar.test.tsx` (new): nothing is requested until Apply; Enter submits; "More filters"
  opens by itself when one of its fields is in the URL; a chip's remove button drops that key and resets the offset;
  Clear all keeps only the tab's own fixed keys (department, direction, case state); validation errors are linked to
  their fields and block the request; the bench field offers the suggestions of `/reference/benches`.
- `components/inbox/inbox.test.tsx` (changed): each tab sends its shared filters with the API names; tab badges stay
  the unfiltered counts; the Recommended `listed=today` link still filters today; the filtered total is shown.
- `components/files/files.test.tsx` (changed): each tab sends the shared filters and `owner`; Department files offers
  only tracked departments as owner.
- `components/alerts/alerts.test.tsx` (changed): case filters sent with the alert filters; the case-less line shows
  only while a case filter is set.
- `components/search/search.test.tsx` (changed): no words → `/cases` with `case_status`, `owner`, court, bench, next
  range; words → `/cases/search` with the same; an old `status=disposed&office=FIN` URL is sent as `case_status` and
  `owner`; the text tab sends `group`, `doc_type`, `date_from`, `date_to`.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green with the new tests;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`, then `docker compose up -d --wait --no-deps api web` (no migration; the worker and
   scheduler running the historical load are not recreated); `python backend/tools/portal_smoke.py` → every page 200
   and no error line in the `web` log; without a session `curl -s -o /dev/null -w "%{http_code}"
   http://localhost:3000/api/backend/reference/benches` → 401.
4. Server checks against the dev database (with a super admin token, or the same queries in `psql`): `GET
   /reference/benches` lists the court numbers seen in the last 90 days (at most the 27 values in the data, equal to `select distinct trim(court_no)` over that window) and the bench texts;
   for one recent date D and court C, `GET /cases?listed_from=D&listed_to=D&court_no=C` `total` equals `select
   count(distinct ce.case_id) from causelist_entries ce join causelists cl on cl.id = ce.causelist_id join cases c on
   c.id = ce.case_id where cl.list_date = D and trim(ce.court_no) = C and c.merged_into_case_id is null`; `GET
   /cases?bench=SAIKIA` returns cases listed before both judges named Saikia; each list endpoint with every shared
   filter set answers in under one second on the 29.6k-case dev database (recorded in the cycle report).
5. Signed-in steps (they need the e-mailed sign-in code, so they are run by the owner or the integrator; if not run
   before merge they are recorded in the cycle report and handed over, as in rows 12, 50, 53 and 55): as a department
   admin, Recommended → Cause-list date "Between dates" over last week and Bench a judge → the list and its total
   change, the URL carries `listed_from`, `listed_to` and `bench`, reload and Back restore it, the tab badge is
   unchanged; Claimed → Disposed with Year 2025; Unclaimed pool "Matched to department" with minimum score 0.5;
   Files → With me with Case type; Alerts with Next hearing "Next 7 days"; Search with no words, Status Disposed and
   Department; a chip's × removes one filter; a reversed range shows the message and sends nothing.
6. In `psql`: no `audit_log` row was written by any filtered list (reading is never audited).

## Open questions
None.

## Deviations
Recorded by the developer during the build (13 Oct 2026); none changes a rule of the plan, a business rule or an API
field beyond the design.
1. **Department codes are checked where the session is.** `case_filters.parse` has no session, so it only trims and
   upper-cases `owner`; the "is not a department" check (400, the same message shape `owner 'X' is not a
   department`) runs when the conditions are built, and in `inbox.pool` / `inbox.transfers` for `scored_for` and
   `other_office`.
2. **Lengths answer 400, not 422.** `court_no` and `bench` are declared without FastAPI length limits so the over-long
   value answers 400 with the decision-7 message, like every other filter error. The shared-filter 400 from the
   dependency is a plain-string `detail` on every router; a service-level filter error (an unknown `owner`) keeps the
   router's own shape (`{code: "bad_field" | "bad_request", message}` on the workflow and alerts routers). The portal
   reads both.
3. **`owner` on the inbox.** The inbox endpoints do not declare `owner` (an unknown query parameter is ignored by
   FastAPI); the service refuses an `owner` passed in a `CaseFilters` there ("owner is not a filter of this list").
4. **Next-hearing presets.** "Next 7 days" is today through today + 6 and "Next 30 days" today through today + 29
   (IST), mirroring "Last 7 days" / "Last 30 days".
5. **Where each list's own controls sit.** First row: match strength (Recommended), role (Claimed), minimum score
   (pool), transfer status (Transfers), Overdue only (Files), alert status (Alerts), "Only cases I can open" (Search,
   with words); under "More filters": unit and officer (Claimed), State is a party (pool), holder department
   (Department files), kind, severity and Unread only (Alerts). The document-text tab has no "More filters" (its
   group, type and date range are on the first row) and its date range is checked like the case ranges. "More
   filters" is shown only when the list has something under it.
6. **Search's total** stays in the existing results heading ("Results · 128 cases") rather than repeated in the bar;
   every other list shows "n … match" in the bar. A Search URL's old `case_state=` no longer filters (Status replaces
   the control; Active is pending and unknown together, so it has no single Status value).
7. **Chip names** are short ("Words", "Cause list", "Bench"); the field labels stay as designed.
8. **`/reference/benches` normalises** as the filters match: court numbers trimmed (blank ones left out), bench texts
   upper-cased with white space collapsed and trimmed, so spacing variants of one bench are one choice.
9. **Test files.** `tests/db/test_api_cases.py` did not exist and is new; the custody list tests are in the new
   `tests/db/test_custody_held.py`. The existing pool test refreshes the search vectors of its cases, since inbox words
   now match `cases.search_vector` (decision 3).
10. **Timing (Verification step 4), measured by the developer on the dev database (13 Oct 2026, read-only):**
    `/reference/benches` 0.06 s (23 court numbers, 34 benches in 90 days); `/cases` for the latest date and court
    0.02 s with `total` equal to the SQL count (8); `/cases?bench=SAIKIA` 0.50 s (5,608); `/cases` and `/cases/search`
    with every shared filter 0.04 s and 0.06 s; `/inbox/pool` with every filter 0.01 s. No index proposed.
