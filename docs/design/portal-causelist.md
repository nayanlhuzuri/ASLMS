# Design: Portal — the Cause list screen (a date, a bench, the day's list as published, with Claim) and its API

```
slug: portal-causelist
status: approved
author: architect
date: 2026-10-13
approved_by: owner (nayanlhuzuri) on 2026-10-13
```

## Context
Backlog row 60, the owner's request of 13 Oct 2026 (decisions log, "Owner decisions of 13 Oct 2026: filters, cause list
screen, counsel code variants"): "pick any date and a bench, see the day's list as published, in court order (court
number, item number, section), each entry with case number, parties, advocates and counsel codes, its recommendation
(band and department) or its owner, and a Claim button with the usual department choice and audit; already-claimed
cases marked with the department; the original cause-list PDF to open; the cause-list API it needs (list dates,
benches, entries) with server-side visibility."

The plan: §3.1 Table 4 (Cause List Bench "list of benches sitting on a date", Cause List Details "all cases listed
before each bench" feeding the "cause list archive", Show Cause List "official cause list document" feeding the
"cause list archive, parser"); §4 and §4.2 (the cause list is where recommendations come from; no case is assigned
automatically, a department claims; ≥ 0.85 strong, 0.50–0.85 possible, < 0.50 the unclaimed pool); §5.4 (claim from
the inbox); §7 Table 8 ("Cause lists: daily cause lists and the case entries listed in them"); §8.1 (visibility applied
to every request). CLAUDE.md: recommend-and-claim, visibility on the server, audit of ownership decisions, NAPIX only
through the integration layer, no fabricated identifiers.

In place and reused (nothing here changes how lists are fetched, parsed or scored):
- Tables `causelists` (one row per NAPIX bench list: `bench_id`, `napix_causelist_id`, `list_type`, `list_type_text`,
  `bench_label`, `document_id`, `fetch_status`, `parse_status`, `entry_count`; one row per court-wide website file with
  `bench_id` null), `causelist_entries` (`sr_no` sequence, `printed_sr_no`, `court_no`, `bench_text`, `section`, `cnr`,
  `case_id`, `case_no_text`, `is_connected`, `with_text`, party and advocate texts, `counsel_codes`, `remarks`,
  `source`, `resolution_status`), `causelist_bench_days`, `documents` (kind `causelist`, `court_record`, scan
  `skipped`), `fetch_queue` (`causelist_day/<date>` rows), `recommendations`, `case_ownership`.
- `services/visibility.py` (`visible_case_condition`, `never_owned`, `claim_departments`), `services/inbox.py`
  (`summaries`, `primary_codes`), `services/ownership.py` (`available_actions`, `_claim_state`,
  `_super_admin_claim_departments`, `case_ownership_view`: "other departments' recommendations only with
  `cases.view_all`"), `services/case_filters.py` (`parse_query`), `services/napix_admin.py` (`day_held`,
  `refetch_day`), `services/documents.py` (`open_file`, `record_failure`, `FileMissing`), `services/queue.py`
  (`get_state`), `reporting_common.today_ist`.
- Endpoints `POST /cases/{ref}/claim` (`cases.claim`, audited `ownership.claim`), `GET /cases/{ref}/ownership`
  (`actions.claim_departments`), `POST /admin/napix/refetch/day` (`admin.napix_refetch`, audited, 409 `already_held`).
- Portal: `ClaimDialog` without departments (reads `GET /cases/{ref}/ownership`, as Search results do; design
  `portal-cases-followups`, decision 7), the UI kit, `messages.ts`, `format.ts`, the relay (`/api/backend/*`).

The data in the dev database (13 Oct 2026, read-only queries): 3,021 NAPIX lists (1,499 daily, 1,180 supplementary,
182 Lawazima, 160 other) on 84 dates between 3 Jan 2025 and 13 Oct 2026 (the historical load is still running, so many
dates are not loaded yet); no website lists; 62,157 entries, every one resolved to a case (7 without a CNR,
provisional); the busiest day 7 Oct 2026 with 1,191 entries, a typical day 650–780; 20 benches on 13 Oct, each bench
printed under one court number on a date; 6 lists without a stored PDF (`not_available` or pending).

Not covered: the Search, inbox and Files lists (rows 12, 59); a calendar of hearings (row 55); department discovery
(row 19); fetching lists in any new way (the existing refetch endpoint is only offered as a button); the reports and
audit screens (rows 39, 41). The Search result's `claimable` stays as it is (in the pool and the caller may claim); the
cause list computes the fuller rule of decision 7, and the owner may ask for Search to use it as a follow-up row.

## Decisions
1. **The published list is court-public; the portal's own facts on each row follow the existing rules.** Every
   stored row of the chosen date is returned to any reader of cases (`cases.view_scope` or `cases.view_all`), with the
   printed text as stored (number, CNR, parties, advocates, counsel codes, section, remarks), as `cases-api`
   decision 4 does for search summaries: the cause list is a public court document, and "as published" means every
   row. What the portal adds per row is scoped on the server: `visible` (the detail endpoints will answer; the case
   number links to the case page only then), `owner_office_code` (the active primary owner, shown to every reader as
   Search shows it), `held_by_you`, the recommendations (decision 6) and `claimable` (decision 7). Alternatives: only
   rows of cases the caller may see (not "as published"; a department could not spot its own unclaimed case listed
   today); a separate public endpoint without the portal facts (two calls for one screen).
2. **A bench is the NAPIX bench list of the day; "All benches" is the whole day in court order.** For a date the API
   names each bench that sat or published a list: NAPIX lists grouped by `bench_id` (one bench may have several lists
   that day: Daily, Supplementary, Lawazima, Production …), plus benches in `causelist_bench_days` with no list (shown
   as "no list published"); a court-wide website file (bench id null, fallback source) is one entry of its own,
   chosen by its list id. Each bench carries its label (`bench_label`, the judges as NAPIX names them), the court
   numbers printed on its entries, its lists and its entry count. Benches are ordered by their smallest court number
   numerically (`2` before `10` before `111`, none last), then bench id; lists in a bench as Daily, Supplementary,
   Lawazima, Vacation, Other, then `napix_causelist_id`. Without a bench the screen shows the whole day, which is how
   the court publishes it. Alternative: bench as the printed bench text (`/reference/benches`, row 59): the same
   judges sit in different combinations, and the NAPIX bench id is what a list and its PDF belong to on that date.
3. **Court order.** Entries are ordered by court number (numerically, then as text, none last), bench id, list order
   (decision 2), then `sr_no` — the sequence in which the parser read the printed rows, which keeps the item numbers
   (`printed_sr_no`), the section headings and the connected matters ("with WP(C) 2087/2025", which have no item
   number of their own) exactly in printed order. The screen draws a heading when the court, the bench, the list or the
   section changes. Alternative: ordering by the printed item number (connected rows have none; Supplementary lists
   restart at 1).
4. **The dates: any date, with what is known about it.** The date control accepts any date. `GET /causelists/dates`
   returns, for a range, the dates with lists or with a `causelist_day` queue row, each with a state, and the date the
   screen opens on: the first date on or after today (IST) with lists — the next day's list is published the evening
   before — or else the latest date with lists. The day carries `previous_date` and `next_date` (the nearest dates with
   lists) for "Previous list" and "Next list". Day states: `held` (lists stored), `loading` (queue row pending or
   running, no list yet), `no_list` (queue row skipped: the court published none), `failed` (queue row failed, no list
   yet), `not_loaded` (no queue row and no list). A day with nothing is an empty answer with its state, never 404.
5. **Fetching a missing day is the existing button, not new NAPIX code.** For a day that is `not_loaded`, `failed` or
   `no_list`, holders of `admin.napix_refetch` see "Fetch this day from the court", which calls `POST
   /admin/napix/refetch/day` (request lane, priority 20, audited, quota-guarded; "a cause list can be fetched up to
   tomorrow"); its 409 `already_held` (a `no_list` day) is shown with "Fetch anyway" (`force`), as the data console
   does. Nobody else sees the button; the screen then shows `loading` until the queue row finishes. Alternative: no
   button (an officer opening an unloaded date would have to find the data console).
6. **Recommendations shown on a row: the per-case rule already in force.** A row shows the active recommendations
   (`status = recommended`) to the caller's departments (any membership), each with department code, band (`high`
   → "Strong", `medium` → "Possible") and score; a caller with `cases.view_all` (State-wide readers, the super admin)
   sees every department's. This is `case_ownership_view`'s rule (recommend-and-claim / portal-cases: "other departments'
   recommendations only with `cases.view_all`"). The owner of a claimed case is shown instead of "Unclaimed" on every
   row (decision 1), with "Your department" when one of the caller's departments holds the case as primary or watcher
   (`held_by_you`: `primary` / `watcher`). A row whose case has neither shows "Unclaimed" (in the pool) or nothing (a
   claimed case's recommendation to a department the caller cannot see). Alternative: every department's
   recommendations to everyone (would reveal to each department what the engine suggests for the others; the inbox
   and the case page withhold it).
7. **Claim from the row, with the usual department choice and audit.** `claimable` is computed in SQL for the page as
   the twin of `available_actions(...)["claim"]`: the case is not merged and, for some department D where the caller's
   membership holds `cases.claim`, D holds no active ownership row and either the case has never had a primary owner
   or D has an active recommendation (so a department recommended a case another department already owns can claim it
   as a watcher, plan §4.2); for the super admin: never owned, or an active recommendation to an active department that
   does not hold it. The Claim button opens `ClaimDialog` without departments: it reads `GET /cases/{ref}/ownership`
   for `claim_departments` (one department → preselected; several → the choice; the super admin on a pool case → any
   department) and posts `POST /cases/{ref}/claim`, which decides, writes `case_ownership`, the `ownership.claim`
   audit row and the event as today. On success the cause list re-reads its rows, so the row shows "Claimed by …" /
   "Your department". Rows without a case are never claimable. Alternative: a claim endpoint for the cause list (a
   second write path for one decision).
8. **Filters on this screen.** The date (one day) and the bench are the page's place; on top: list type (`list_type`,
   only the types the day has), court number (`court_no`, with "All benches"), words (`q`) and `only`:
   `recommended` (a recommendation the caller is shown, decision 6), `mine` (held by one of the caller's departments),
   `claimable`, `unclaimed` (never had a primary owner), `claimed` (an active primary owner), `visible` (the caller can
   open the case). Words are parsed as the Search box (`parse_query`, auto mode, ≥ 3 characters): a CNR matches the
   row's `cnr` or its case's; a case number or `ref_no` matches the row's case; other words match as word prefixes
   (case-insensitive, `~* ('\m' || :word)`, each word bound as a parameter, every word required) over the row's printed
   text — case number, petitioner, respondent, both advocate texts and counsel codes. **Deviation from portal-filters
   decision 3** (not from the plan): that decision reads words over the case's `search_vector`; here the rows are
   printed entries, so words are matched on the row itself (a row matches on what it prints, and a row without a case
   is still found). Rows of one date are bounded (≤ 1,200 today), so no index is needed. The response carries counts
   for the place (date, bench or list, list type, court) before `q` and `only`: entries, recommended, mine,
   claimable, claimed, unclaimed — "65 entries · 4 recommended to you · 12 claimed". Alternative: the shared
   `FilterBar` of row 59 (its fields are case filters over ranges; this screen is one date and one bench).
9. **The original PDF.** Each list with a stored document offers "View" (inline, `documents.view`) and "Download"
   (attachment, `documents.download`) through `GET /causelists/lists/{id}/file`; a list without one says "PDF not
   available from the court" (`fetch_status` `not_available` / `failed` / `pending`). Cause-list documents belong to no
   case, so the case-based document rule cannot serve them; they are court records published by the court, served to
   any reader of cases holding the file function, and not audited (as order PDFs are not). A file missing from the
   store answers 404 `file_missing` and records a `source_failures` row, as documents do. The serving code is shared:
   `documents.serve_stored(session, doc, disposition)` is extracted from `open_file` (path check, missing-file failure,
   `ServedFile`), and `open_file` keeps its checks and audit unchanged. Alternative: putting cause-list documents under
   `/documents/{doc}/file` with a special case in `document_visible_condition` (widens the one document rule for a
   kind it was never meant for).
10. **Read gates and reading.** Every endpoint here is a read gated by `cases.view_scope` or `cases.view_all`
    (`require_any`, as `/cases`, `/reference/benches`); the file additionally needs `documents.view` (inline) or
    `documents.download` (attachment). No new `Permission`: the screen shows what readers of cases may already
    search. Reading writes nothing: no `audit_log`, no `events`, no NAPIX call (tested). Paging: `limit` default 200,
    at most 500 (one bench's lists are shown whole; a whole day pages), `offset`; `total` exact (one date is bounded).
11. **The portal screen.** Route `/causelist`, navigation entry "Cause list" after Search (`CASE_READERS`). URL keys
    `date`, `bench_id` or `list_id`, `list_type`, `court_no`, `q`, `only`, `offset`, so a bookmarked or shared list
    reopens as it was. Layout: the date (date input, "Previous list", "Next list", and the default date when none
    is given), the bench select ("All benches", then "Court 6 · HONOURABLE MR. JUSTICE MANISH CHOUDHURY · 53"), the
    day-state banner (decision 4) with the fetch button (decision 5), the lists of the chosen bench with their type,
    entry count and PDF buttons, the counts line, the filters, then one table: Item (printed number; connected rows
    indented with "with …"), Case (number linked when `visible`, CNR beneath, "provisional" when there is none),
    Parties (petitioner / "versus" / respondent), Advocates (petitioner's / respondent's, line breaks kept), Counsel
    codes (as printed), Ownership ("Claimed by EDU" badge, "Your department", recommendation badges "Strong · EDU ·
    0.95", "Unclaimed") and the Claim button. Headings rows for court, bench, list and section (`<th scope="colgroup">`).
    Departments are named from `useDepartments()`. CSS Modules and the shell tokens, the UI kit, WCAG 2.1 AA, strings
    in `messages.ts` (`T.causelist`), no new npm dependency.
12. **One link from the case page.** Each listing on the case's Hearings tab (`/cases/{ref}/listings`) gets "Open the
    cause list" to `/causelist?date=<list_date>&bench_id=<bench_id>` (date only for a court-wide file). Frontend only;
    the listing already carries both fields.

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): every
published row shown to every reader of cases, with the portal facts scoped (1); other departments' recommendations
only for State-wide readers (6); the fuller `claimable` that includes "recommended to my department, owned elsewhere"
as a watcher claim (7); words matched on the printed row (8, a deviation from portal-filters decision 3); the fetch
button only for `admin.napix_refetch` (5).

## Data
No table, column, constraint, index, reference code, `Permission` or setting is added; no migration;
`docs/schema/schema.md` is unchanged. Every read uses existing columns of `causelists`, `causelist_entries`,
`causelist_bench_days`, `documents`, `fetch_queue`, `recommendations`, `case_ownership`, `cases`, through the existing
indexes `ix_causelists_list_date`, the unique (`causelist_id`, `source`, `sr_no`) on `causelist_entries`,
`ix_causelist_entries_case_id`, `ix_recommendations_active`, `ix_case_ownership_active_primary` and
`ix_case_ownership_active_office`. If the integrator's timing (Verification step 4) exceeds one second, an index is
proposed as a new row with its own migration, not added here.

## Services
Backend (Python):
- `services/causelist_view.py` (new, read-only; writes nothing, audits nothing, calls no NAPIX):
  - `ORDER_OF_LIST_TYPE` (daily, supplementary, lawazima, vacation, other); `court_sort_key(court_no)` (numeric then
    text, none last) and its SQL twin for ordering (`NULLIF(regexp_replace(trim(court_no), '\D', '', 'g'), '')::int`
    then `trim(court_no)`).
  - `day_state(session, list_date) -> tuple[str, FetchQueue | None]` — decision 4, from `causelists` and
    `queue.get_state(session, FetchKind.CAUSELIST_DAY, iso)`.
  - `dates(session, *, date_from: date | None, date_to: date | None, today: date | None = None) -> dict` —
    `{from, to, today, default_date, items: [{date, state, lists, benches, entries}]}`; range defaults to today − 60 to
    today + 7 (IST); `CauselistViewError(ValueError)` when `from` > `to` or the range exceeds 400 days.
  - `day(session, list_date) -> dict` — `{date, state, queue_status, queue_finished_at, previous_date, next_date,
    totals: {benches, lists, entries}, benches: [...]}` (decision 2), each bench `{bench_id, label, court_nos, source,
    entries, lists: [{id, list_type, list_type_text, label, napix_causelist_id, source, entry_count, entries_stored,
    fetch_status, parse_status, has_pdf}]}`.
  - `entries(session, user, list_date, *, bench_id=None, list_id=None, list_type=None, court_no=None, q=None,
    only=None, limit=200, offset=0) -> dict` — `{date, total, counts, items}`; the place conditions, then `q`
    (decision 8) and `only`; ordering of decision 3; per row the `CaseSummaryOut` of the case (`inbox.summaries`),
    `visible` (`visible_case_condition` selected as a column), `in_pool` (`never_owned`), `owner_office_code`
    (`inbox.primary_codes`), `held_by_you`, `recommendations` (decision 6) and `claimable` (decision 7), each
    computed in SQL for the page, never filtered in Python. Validation (`CauselistViewError` → 400): `bench_id` and
    `list_id` together; `list_id` not a list of that date; `list_type` or `only` not one of their values; `q` under 3
    characters or without a searchable word; `court_no` over 20 characters; `limit` outside 1–500; negative `offset`.
  - `list_file(session, user, causelist_id, *, store, disposition) -> ServedFile` — decision 9: requires
    `cases.view_scope` or `cases.view_all` and the file function of the disposition (`NotAllowed`), the list and its
    document (kind `causelist`; `NoPdf` with the list's `fetch_status` when none), then `documents.serve_stored`;
    file name `Causelist_<date>_bench-<bench_id>_<list_type>.pdf` (`court-wide` for a website file). Not audited.
- `services/ownership.py`: `claimable_condition(session, user) -> ColumnElement[bool]` over `Case` — decision 7, the
  SQL twin of the claim half of `available_actions` (documented as such; `available_actions` is unchanged), and
  `shown_recommendations_condition(session, user)` over `Recommendation` (active; the caller's departments, or every
  department with `cases.view_all`).
- `services/documents.py`: `serve_stored(session, doc, disposition) -> ServedFile` extracted from `open_file`
  (inline MIME check, store path, missing-file `record_failure` + `FileMissing`, served name); `open_file` calls it
  after its own checks and audit, behaviour unchanged.
- `api/routers/causelists.py` (new, `prefix="/causelists"`, tag `causelists`), included in `api/main.py`; static
  routes `/dates` and `/lists/{id}/file` declared before `/{list_date}`. Errors: `CauselistViewError` → 400 (plain
  message); `NotAllowed` → 403; unknown list → 404 "no such cause list"; `NoPdf` → 404 `{code: "no_pdf", message,
  fetch_status}`; `FileMissing` → 404 `{code: "file_missing", message}` with the failure row kept (the session is
  committed before raising, as the documents router does).
- `api/schemas.py`: `CauselistDatesOut`, `CauselistDateOut`, `CauselistDayOut`, `CauselistBenchOut`, `CauselistOut`,
  `CauselistEntriesOut`, `CauselistCountsOut`, `CauselistEntryOut`, `EntryRecommendationOut`. `frontend/openapi.json`
  and `src/lib/api/schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/app/(portal)/causelist/page.tsx` (new) and `src/components/causelist/` (new): `CauseList.tsx` (the screen),
  `DayBar.tsx` (date, previous / next, state banner, fetch button), `BenchSelect.tsx`, `ListStrip.tsx` (the bench's
  lists with PDF buttons), `EntryTable.tsx` (headings and rows), `OwnershipCell.tsx`, `causelist.module.css`.
- `src/lib/api/hooks.ts`: `useCauselistDates(from, to)`, `useCauselistDay(date)`, `useCauselistEntries(date,
  params)`, keys under `["causelists", …]`; the Claim dialog's `onDone` invalidates `["causelists"]`.
- `src/lib/causelist.ts` (new, plain module): URL ⇄ API query (`toApiQuery`), the heading breaks of decision 3
  (`headingsOf(items)`), the band and state labels.
- `src/lib/routes.ts`: `NAV` entry `{ key: "causelist", label: "Cause list", href: "/causelist", functions:
  CASE_READERS, built: true }` after Search.
- `src/components/case/Hearings.tsx`: "Open the cause list" link per listing (decision 12).
- `src/lib/messages.ts`: `T.causelist` (headings, states, banner texts, fetch button and its confirmation, counts
  line, `only` choices, PDF texts, column names).

Audit and events: none written by this item. The Claim it offers writes `ownership.claim` through the existing
endpoint; the fetch button writes `napix.refetch_requested` through the existing endpoint.

## API
New (FastAPI). Dates are ISO in requests and IST days in responses; timestamps IST.

| Method, path | Function required (`Permission`) | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /causelists/dates` | `cases.view_scope` or `cases.view_all` (`require_any`) | `from`, `to` (optional dates; ≤ 400 days) | `{from, to, today, default_date, items: [{date, state, lists, benches, entries}]}` | court-public facts, the same for every reader |
| `GET /causelists/{list_date}` | `cases.view_scope` or `cases.view_all` | — | `{date, state, queue_status, queue_finished_at, previous_date, next_date, totals: {benches, lists, entries}, benches: [{bench_id, label, court_nos, source, entries, lists: [{id, list_type, list_type_text, label, napix_causelist_id, source, entry_count, entries_stored, fetch_status, parse_status, has_pdf}]}]}` | court-public, the same for every reader |
| `GET /causelists/{list_date}/entries` | `cases.view_scope` or `cases.view_all` | `bench_id` or `list_id`, `list_type`, `court_no`, `q`, `only` (`recommended` / `mine` / `claimable` / `unclaimed` / `claimed` / `visible`), `limit` (1–500, default 200), `offset` | `{date, total, counts: {entries, recommended, mine, claimable, claimed, unclaimed}, items: [{id, causelist_id, list_type, bench_id, bench_label, court_no, sr_no, printed_sr_no, section, is_connected, with_text, case_no_text, cnr, petitioner_text, respondent_text, pet_advocate_text, res_advocate_text, counsel_codes, remarks, source, resolution_status, case: CaseSummaryOut \| null, visible, owner_office_code, held_by_you, in_pool, recommendations: [{office_code, band, score}], claimable}]}` | every stored row (decision 1); `visible` from `visible_case_condition`; recommendations per decision 6; `claimable` per decision 7 |
| `GET /causelists/lists/{id}/file` | `cases.view_scope` or `cases.view_all`, and `documents.view` (`disposition=inline`) or `documents.download` (`attachment`, default) | `disposition` | the PDF (`Content-Disposition` with the file name of Services) | court record; not audited |

Errors: 401 signed out; 403 without the read functions or the file function; 400 with the validation message; 404
"no such cause list", `no_pdf`, `file_missing`. Used as they are: `POST /cases/{ref}/claim` (`cases.claim`), `GET
/cases/{ref}/ownership` (`cases.view_scope`), `POST /admin/napix/refetch/day` (`admin.napix_refetch`), `GET
/custody/recipients` via `useDepartments()`, `/me`.

Web server: no new route; the relay passes `/api/backend/causelists/*` and the PDF stream (inline viewing keeps the
API's headers, design `portal-cases`, decision 15).

## Jobs
None. The lists are loaded by the existing daily cycle and historical load; the fetch button queues the existing
`causelist_day` kind through the existing endpoint.

## Tests
Backend (pytest, `backend/tests/`, the shared world extended with: two dates, three benches — one division bench
with Daily and Supplementary lists, one registrar bench with a Lawazima list, one bench day with no list — court
numbers `2`, `10`, `111`, sections and a connected row, one row without a case, one list without a PDF, one website
file on a third date; cases in the pool, recommended to EDU strong and FIN possible, claimed by EDU, owned by FIN and
recommended to EDU, merged):
- `db/test_causelist_view.py` (new):
  `test_dates_default_is_first_held_on_or_after_today_else_latest`; `test_dates_states_held_loading_no_list_failed`;
  `test_dates_range_bounds_and_reversed_400`; `test_day_benches_ordered_by_court_number_then_bench`;
  `test_day_lists_in_type_order_with_pdf_flag`; `test_day_includes_bench_day_without_list`;
  `test_day_website_file_is_its_own_bench`; `test_day_without_anything_is_empty_with_state`;
  `test_day_previous_and_next_held_dates`;
  `test_entries_in_court_order_with_sections_and_connected_rows` (court `2` before `10` before `111`, `sr_no` order
  inside a list); `test_entries_every_row_for_a_directorate_user` (rows of cases they cannot open come back with
  `visible` false, the owner code, no recommendation); `test_entries_recommendations_only_own_departments`;
  `test_entries_recommendations_all_for_view_all`; `test_entries_owner_and_held_by_you_primary_and_watcher`;
  `test_claimable_matches_available_actions` (for every row and each of dept admin EDU, dept admin FIN, dept officer,
  directorate user, standing counsel, central operator, super admin: `claimable` equals `available_actions(...)["claim"]`);
  `test_recommended_case_owned_elsewhere_is_claimable_as_watcher`; `test_row_without_case_never_claimable`;
  `test_merged_case_rows_point_to_survivor`; `test_only_filters_each_value`; `test_counts_ignore_q_and_only`;
  `test_words_cnr_case_number_and_prefixes_on_printed_text` (a counsel code prefix "SC, REV" finds the row; a
  mid-word fragment does not); `test_bench_and_list_filters_and_conflict_400`; `test_list_of_another_date_400`;
  `test_limit_and_offset_bounds`; `test_reading_writes_nothing` (no `audit_log`, `events`, `napix_call_log` or
  `fetch_queue` row after every read).
- `db/test_api_causelists.py` (new): `test_signed_out_401`; `test_without_case_reading_403`;
  `test_dates_day_entries_shapes`; `test_file_inline_needs_documents_view`; `test_file_attachment_needs_documents_download`;
  `test_file_no_pdf_404_with_fetch_status`; `test_file_missing_404_records_failure`; `test_file_not_audited`;
  `test_unknown_list_404`; `test_claim_from_entry_then_row_shows_owner` (claim through `POST /cases/{ref}/claim`
  writes `ownership.claim`; the next entries read shows `owner_office_code` and `held_by_you`, `claimable` false).
- `db/test_api_documents.py` (existing) stays green after `serve_stored` is extracted (uploads still audited on
  download, orders not).
- `unit/test_causelist_view.py` (new): `test_court_sort_key`; `test_only_and_list_type_values`.
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, the `fakeApi` helper):
- `components/causelist/causelist.test.tsx` (new): opens on `default_date` and writes `date` to the URL; Previous
  list / Next list move to the API's dates; the bench select lists the day's benches with court number, label and
  count, and choosing one writes `bench_id` (a website file writes `list_id`); rows render in API order with a heading
  at each court, bench, list and section change; a connected row shows "with …" and no item number; the case number
  links only when `visible`; "Claimed by EDU" and "Your department" badges; recommendation badges with band, department
  and score; Claim shows only when `claimable`, opens the dialog that reads `/cases/{ref}/ownership`, and a success
  re-reads the entries; View shows with `documents.view`, Download with `documents.download`, neither when `has_pdf`
  is false ("PDF not available from the court"); each day state shows its banner; the fetch button shows only with
  `admin.napix_refetch` on `not_loaded` / `failed` / `no_list`, posts `/admin/napix/refetch/day`, and a 409
  `already_held` asks before resending with `force`; `q`, `only`, `list_type`, `court_no` are sent with their API
  names and reset the offset; the counts line.
- `lib/causelist.test.ts` (new): `toApiQuery`, `headingsOf`, labels.
- `lib/routes.test.ts` (changed): "Cause list" shows for `cases.view_scope` and for `cases.view_all`, not without them.
- `components/case/case.test.tsx` (changed): each listing on the Hearings tab links to
  `/causelist?date=…&bench_id=…` (date only without a bench id).

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green with the new tests;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`, then `docker compose up -d --wait --no-deps api web` (no migration; the worker and
   scheduler running the historical load are not recreated); `python backend/tools/portal_smoke.py` → every page 200
   (including `/causelist`) and no error line in the `web` log; without a session `curl -s -o /dev/null -w
   "%{http_code}" http://localhost:3000/api/backend/causelists/dates` → 401.
4. Server checks against the dev database (with a super admin token, or the same queries in `psql`):
   `GET /causelists/2026-10-07/entries?limit=500` → `total` 1,191, equal to `select count(*) from causelist_entries e
   join causelists c on c.id = e.causelist_id where c.list_date = '2026-10-07'`; `GET /causelists/2026-10-13` → as
   many benches as `select count(distinct bench_id)` over that date's `causelists` and `causelist_bench_days` (20 on
   13 Oct), ordered by court number; for one bench of 12 Oct (bench 1854) `total` 53 (Daily 51 + Supplementary 2);
   `GET /causelists/dates` → `default_date` on or after 13 Oct 2026 when that day is held; the PDF of one list with
   `disposition=inline` → 200 `application/pdf`, and of a list without a document → 404 `no_pdf`; the whole-day
   entries page and the day call each answer in under one second (recorded in the cycle report).
5. Signed-in steps (they need the e-mailed sign-in code, so they are run by the owner or the integrator; if not run
   before merge they are recorded in the cycle report and handed over, as in rows 12, 50, 53, 55 and 59): as a
   department admin, open Cause list → the next list date opens; choose a bench → its lists and rows in court order
   with sections; View opens the PDF in the browser; a row recommended to the department shows "Strong · EDU"; Claim
   → the department is preselected (or chosen), the row then shows "Your department" and `audit_log` has one
   `ownership.claim` row for the case; a case another department claimed shows its code; as a directorate user the
   same date shows every row, with case links only for cases they can open and no Claim; choose a date the load has
   not reached → "Not loaded yet", and as the super admin "Fetch this day from the court" queues it.
6. In `psql`: no `audit_log`, `events` or `napix_call_log` row was written by any read of this screen.

## Open questions
None.

## Deviations
Recorded by the developer while building (none changes the plan or a decision above).
1. `documents.serve_stored(session, doc, disposition, *, store, filename=None)` takes the store and an optional served
   name (the cause-list file name of Services). `open_file` calls it after its own checks and before its download
   audit, so a file missing from the store still writes no `document.downloaded` row (behaviour unchanged).
2. Day states: a `causelist_day` queue row that is `done` with no list stored counts as `no_list` (the design names
   only `skipped`); `default_date` is today when no list is held at all, so the field is never empty.
3. `GET /causelists/dates` with one bound only takes the other 67 days away (the default span) instead of today − 60 /
   today + 7, so a lone `from` in the past is not refused as a range over 400 days.
4. The court-number ordering casts to `numeric` rather than `int`, so a long digit string in `court_no` cannot
   overflow; the Python twin `court_sort_key` orders the same way.
5. Words: a case number in `q` also matches the printed case number of a row without a case (compact form), besides
   the row's case.
6. A row whose case was merged points to the survivor (`COALESCE(merged_into_case_id, case_id)`, one level); merges
   already re-point entries, so this only matters for a row left behind.
7. Tests: the world's second department HEALTH stands for the design's FIN. Decision 6 ("the caller's departments, any
   membership") means a directorate user under EDU is shown EDU's recommendations; their test checks that a case they
   cannot open shows `visible` false, its owner and no other department's recommendation.
8. Portal: the state label beside the date is shown for a held day only (the banner says the other states); the list
   type and court number selects appear when the place has more than one value; "Visible to me" carries no count
   (the counts block has none). Cause list sits after Search, so Files moves one place down (the shell and routes
   tests now expect Files after Cause list); a breadcrumb label for `/causelist`.
