# Design: Search in every list, and the full Recommended From Cause Lists

```
slug: list-search
status: awaiting-approval
author: architect
date: 2026-10-26
approved_by: <owner e-mail or name> on YYYY-MM-DD
```

## Context

**The owner's requests of 26 Oct 2026** (backlog row 175):

1. "If there is a list there should be an option for a search in the list, which I find missing in lists."
2. On Department Mapping → Counsel Codes → **Recommended From Cause Lists**: "Is it exhaustive or are there more? If
   there are, list those too."

The owner wants no mockup. The visual rules are the as-built kit and the approved notes:
- `portal-ui-polish-2`: Title Case labels (decisions 1-6), the field-row and checkbox rules (decision 26), the Users
  one-line toolbar (decision 27), one toolbar line per Mapping tab (decision 41), the panel's content (decision 42);
- the decisions log, "Department Mapping layout, owner changes (2026-10-26)": the panel sits below the codes list, one
  row per code where the box is at least 860 px wide, each long list scrolls in its own box of at most
  min(60vh, 560px);
- `data-collection-redesign` (row 172, approved, not built): the kit `ScrollBox`, `DataTable` captions hidden by
  default, no upper-case labels portal-wide, one toolbar line per Data Collection tab. **This row is built after row
  172** and uses its `ScrollBox`. It does not lay out the Data Collection tabs again (rows 173 and 174 do); it only
  adds a search where those rows leave a list without one (decision 24).

The plan has no rule on searching inside lists. §5.2 is the case search, §5.10 makes the audit log "searchable by
user, case and date". This row deviates from nothing.

### Question 2: the panel is not exhaustive (checked 26 Oct 2026)

- `RecommendedCodes` in `CounselCodes.tsx` calls `GET /admin/counsel-codes/unmapped?limit=100`. The API's default is
  200 and its maximum 1,000 (`matching.unmapped_codes`). So the panel shows the 100 codes with the most entries, and
  says "100 to review".
- The dev database holds **1,066 unmapped codes**: 1,018 distinct printed codes in the current cause lists, plus codes
  seen only among the advocates of fetched case details (403 distinct there), normalised by
  `normalise_counsel_code`, less the 2 mapped. The panel has always counted both sources; this row keeps that rule.
  So the panel will read "1,066 codes not mapped" today, not 1,016.
- 245 of the 1,066 codes appear once. 4 have partial matches to a mapping.
- **The cost of listing them all is small.** Timed on the dev database (167,002 cause-list entries, 8,299 lists):
  - the cause-list aggregate (`unnest(counsel_codes)` grouped over current lists): 94 ms;
  - the case-advocate aggregate: 28 ms;
  - the whole `unmapped_codes(limit=100000)` call inside the API container, with normalisation, example references and
    partial matches for all 1,066 codes: **about 200 ms**.
- No index makes a `GROUP BY` over every current entry cheaper. The cost grows with the number of entries, roughly
  linearly. A summary table would be the next step if a page ever takes more than a second; it is not needed now.
  **No migration.**

### Question 1: the inventory

Every `DataTable` (69 uses), every `<ul>` or `<ol>` (67), every hand-written `<table>` (4) and the two order lists built
from `div`s in `frontend/src/components/**` were read. That is **142 places**:
- **28 are not data lists**: navigation, kit internals, static text and chips (listed at the end of the inventory);
- **114 are data lists**:
  - **21 already have a search**;
  - **31 gain one** in this row's three rounds;
  - **62 are left without one**, each with its reason: a summary card of a few rows that links to a full list with a
    search, a list bounded at a few rows, or a list read in date order whose search would match nothing a person
    looks for.

Two more lists gain a search without being separate places in the code: the Search the Court answer (A15), which
reuses the Search page's results table (C11), and row 174's request items (A20), which are not built yet. So the
tables below mark 33 lists for a new search.

The sizes come from the dev database where it has the data (26 Oct 2026), otherwise from the setting that bounds the
list or the expected State-wide size.

**Search today:** "Form" is a filter form applied with Search or Apply (FilterBar, FilterCard, the Users toolbar);
"Instant" filters while typing. **Data:** "Server" is paged or narrowed by the API; "Full" is held whole by the
browser. **R1-R3** are this row's rounds (decision 27).

#### Department Mapping (`components/admin/mapping`)

| # | List | Search today | Data | Usual size | This row |
|---|---|---|---|---|---|
| M1 | Counsel Codes (`CounselCodes.tsx` table) | Instant, server `q`, 300 ms | Server, unpaged | tens to hundreds | **R1** kit toolbar, count, no-match state, `ScrollBox` (decision 13) |
| M2 | Recommended From Cause Lists (`CounselCodes.tsx` `<ul>`) | none | Server, first 100 | **1,066** | **R1** every code, paged, server `q` (decisions 9-12) |
| M3 | Keywords and Name Patterns (`Keywords.tsx`) | Instant, in the browser | Full, unpaged | tens to hundreds | **R1** kit, stays in the browser (decision 14) |
| M4 | Watchlist (`Watchlist.tsx`) | Instant, in the browser | Full, unpaged | tens | **R1** kit, stays in the browser (decision 14) |
| M5 | Court Search → Names Searched (`CourtSearch.tsx`) | none | Server, first 200 | tens | **R1** server `q` (decision 15) |
| M6 | Court Search → Cases Found for a name (`CourtSearch.tsx`) | none ("Only" select) | Server, 50 a page | up to thousands | **R1** server `q`, the case search (decision 15) |
| M7 | Scoring → Rules with Their Own Weight (`Scoring.tsx`) | none | Full | 0 to a few | **R1** in the browser, above 10 rows (decision 16) |
| M8 | Scoring → History (`Scoring.tsx`) | none | Server | tens | left out: versions read by date; a search would match only numbers |
| M9 | Scoring → the save summary (`Scoring.tsx`, confirm dialog) | — | Full | 6 | left out: six fixed weights |

#### Case lists with the shared filters

| # | List | Search today | Data | Usual size | This row |
|---|---|---|---|---|---|
| C1 | Case inbox → Working On (`WorkingOn.tsx`) | Form; **Words hidden under More Filters** | Server | tens | **R1** Words on the first row (decision 17) |
| C2 | Case inbox → Claimed by Me, Disposed (`MyCases.tsx`) | Form; **Words hidden under More Filters** | Server | tens to hundreds | **R1** Words on the first row (decision 17) |
| C3 | Case inbox → Department Cases (`DepartmentCases.tsx`) | Form (Layout B, Words hero) | Server | thousands | **R1** no-match state only (decision 18) |
| C4 | Case inbox → Sent by Me (`files/Sent.tsx`) | Form | Server | tens | **R1** no-match state only |
| C5 | Case inbox → Pending Action (`files/Held.tsx`) | Form | Server | tens to hundreds | **R1** no-match state only |
| C6 | Case Claim → Recommended (`claim/Recommended.tsx`) | Form | Server | hundreds | **R1** no-match state only |
| C7 | Case Claim → Unclaimed Pool (`claim/Pool.tsx`) | Form | Server | tens of thousands | **R1** no-match state only |
| C8 | Case Claim → Transfers (`claim/Transfers.tsx`) | Form | Server | tens | **R1** no-match state only |
| C9 | Alerts (`alerts/AlertList.tsx`) | Form | Server | hundreds | **R1** no-match state only |
| C10 | Next Dates review (`nextdates/ReviewList.tsx`) | Form | Server | tens | **R1** no-match state only |
| C11 | Search → Cases (`search/CaseResults.tsx`) | Form (it is the search) | Server | any | unchanged |
| C12 | Search → Inside Documents (`search/TextSearch.tsx`) | Form (it is the search) | Server | any | unchanged |
| C13 | Cause List entries (`causelist/EntryTable.tsx`) | Form (Search Words) | Server | up to 1,191 a day | unchanged |

#### Administration, audit and other pages

| # | List | Search today | Data | Usual size | This row |
|---|---|---|---|---|---|
| A1 | Users (`admin/Users.tsx`) | Form (toolbar `q`) | Server, 50 a page | hundreds to thousands | **R2** kit count, clear and no-match state (decision 19) |
| A2 | Designations (`admin/Designations.tsx`) | none | Full | 20 to 60 | **R2** in the browser |
| A3 | Offices tree (`admin/Offices.tsx`) | none | Full | about 60 departments and their directorates, hundreds of offices | **R2** in the browser, matches shown with their parents (decision 20) |
| A4 | Admin Tickets (`admin/Tickets.tsx`) | none (status tabs) | Server, 50 a page | tens a year | **R2** server `q` |
| A5 | User Details → Functions tab (`admin/UserDetails.tsx`) | none | Full | about 45 functions | **R2** in the browser |
| A6 | Change Exceptions panel (`admin/UserDetail.tsx` functions table) | none | Full | about 45 | **R2** in the browser |
| A7 | User type page functions (`admin/UserTypes.tsx`) | Instant (Find) | Full | about 45 | unchanged (the model the kit follows) |
| A8 | Audit Log (`audit/AuditTable.tsx`) | Form (Layout B) | Server, cursor | thousands | **R2** no-match state; no count (decision 19) |
| A9 | Assistant → Conversations (`assistant/Assistant.tsx`) | none | Server, newest 50 | tens to hundreds | **R2** server `q`: older conversations are otherwise out of reach |
| A10 | My Calendar → Department Hearings agenda (`calendar/DepartmentHearings.tsx`) | none | Full (up to 62 days) | hundreds for a large department | **R2** in the browser |
| A11 | Case inbox → tracking summary, By Holder Department (`files/TrackingSummary.tsx`) | none | Full | 1 for a department, up to about 60 State-wide | **R2** in the browser, above 10 rows |
| A12 | Tracking summary, By Holder (`files/TrackingSummary.tsx`) | none | Full | tens to hundreds | **R2** in the browser, above 10 rows |
| A13 | State dashboard → By Department (`dashboard/Blocks.tsx`) | none | Full | about 60 | **R2** in the browser |
| A14 | Cause List → View Cause List modal entries (`causelist/ViewCauseList.tsx`) | none | Server, 100 a page | up to 144 a list | **R2** the entries API's existing `q` |
| A15 | Search → Search the Court results (`search/CourtSearch.tsx` with `CaseResults`) | none | Full (one answer) | up to the advocate cap | **R2** in the browser (decision 21) |
| A16 | Search the Court → rows not stored (`search/CourtSearch.tsx` `<ul>`) | none | Full | a few to tens | **R2** the same field as A15 |
| A17 | Reports, each section's table (`reports/ReportView.tsx`) | none | Full, paged by 50 in the browser | up to the report's cap | **R2** in the browser (decision 22) |
| A18 | Data Collection → Duplicates (`data/Duplicates.tsx`) | none | Server, 50 a page | tens to hundreds | **R2** server `q`, the case search, after row 173 (decision 24) |
| A19 | Data Collection → Court Calls (`data/Queue.tsx` call log) | none | Server, cursor | thousands a day | **R2** Court Service and Failed Only filters on existing API parameters, after row 173 (decision 24) |
| A20 | Data Collection → a request's items (row 174's side panel) | none (not built) | Server, 100 a page | up to 2,000 | **R2** server `q`, after row 174 (decision 24) |
| A21 | Data Collection → Work Items (`data/Queue.tsx`) | Form (Reference Starts With) | Server | thousands | unchanged |
| A22 | Load → fetch results of One Case (`data/LoadConsole.tsx`) | Form (it is the search) | Server | a few | unchanged |

#### The case page (`components/case`, `workflow`, `claim`)

| # | List | Search today | Data | Usual size (dev) | This row |
|---|---|---|---|---|---|
| P1 | Parties (`case/Parties.tsx`) | none | Full | average 8, 99% under 59, **largest 1,855** | **R3** in the browser |
| P2 | Advocates (`case/Parties.tsx`) | none | Full | average 2, largest 24 | **R3** the same field as P1 |
| P3 | Hearings (`case/Hearings.tsx`) | none | Server, 50 a page | average 7, largest 161 | **R3** server `q` |
| P4 | Listings (`case/Hearings.tsx`) | none | Server, 50 a page | tens | **R3** server `q` |
| P5 | Orders tab (`case/Orders.tsx`, `div` list) | none | Server, 50 a page | average 5.5, largest 134 | **R3** server `q` |
| P6 | Case details modal → Orders (`claim/OrderRow.tsx` `OrderRows`) | none | Server, 50 a page | as P5 | **R3** the same `q` as P5 |
| P7 | Documents, each group (`case/Documents.tsx`) | none | Server, 50 a page per group | average 5, largest 134 | **R3** server `q` |
| P8 | Notes tab (`case/Notes.tsx`) | none | Server, 50 a page | a few, long cases 100+ | **R3** server `q` (decision 25) |
| P9 | Remarks panel → Remarks (`case/Remarks.tsx`) | none | Server, 50 at a time | a few, long cases 100+ | **R3** server `q` (decision 25) |
| P10 | Remarks panel → Notes (`case/Remarks.tsx`) | none | Server, 50 at a time | as P8 | **R3** the same `q` as P8 |
| P11 | Timeline (`case/Timeline.tsx`) | none | Server, 50 a page | average 10, largest 271 | **R3** server `q`, label and date only (decision 25) |
| P12 | Custody tab → Movement (`workflow/CustodyTab.tsx`) | none | Server, 50 a page | a few, long cases 100+ | **R3** the same `q` as P9 |

#### Left without a search (62)

Each is a summary card of the first few rows that links to a full list with a search, or is bounded at a few rows, or
is read in date order where a word search matches nothing useful.

| Where | Lists | Usual size | Reason |
|---|---|---|---|
| `admin/Tickets.tsx` | a ticket's documents | 1-5 | bounded |
| `admin/UserDetail.tsx` | the exit dialog's hand-over table; a membership's documents | tens; 1-5 | a confirmation read in full before Exit; bounded |
| `admin/UserDetails.tsx` | Offices cards; Activity (latest 20) | 1-5; 20 | bounded; Activity links to the Audit Log, which has the search |
| `admin/UserTypes.tsx` | the user-type cards | about 10 | bounded |
| `audit/BeforeAfter.tsx`, `audit/AuditEntry.tsx` | the fields of one entry; its links | up to 30; a few | one record |
| `case/Details.tsx`, `case/Links.tsx`, `case/Overview.tsx`, `case/OwnershipCard.tsx` ×2, `case/Rail.tsx`, `case/Notes.tsx` (a note's attachments) | facts, linked cases (largest 2), recent activity (4), departments, the journey (4), attachments | a few each | bounded |
| `workflow/CaseAlerts.tsx`, `workflow/CustodyTab.tsx` (stage history), `workflow/DraftsPanel.tsx` ×2, `nextdates/CaseNextDate.tsx` | a case's alerts, stages, drafts (at most `note_drafts_max`), next dates | a few each | bounded |
| `claim/CaseModal.tsx`, `claim/WhyBox.tsx` | links; the match signals | a few | bounded |
| `assistant/Assistant.tsx` ×2 | an answer's sources and related orders | up to 10 | bounded |
| `calendar/DayAgenda.tsx` | one day of My Calendar | a few | one day |
| `causelist/ListStrip.tsx` | the day's lists | up to about 30 | the page's Bench and Search Words narrow it |
| `dashboard/Headline.tsx` ×2; `dashboard/Blocks.tsx`: upcoming hearings, cases with me, recent orders, custody, own cases, attention, alerts, overdue, tickets by kind, tickets by department | summary cards | up to 5-10 each | each links to its full list, which has a search |
| `data/Health.tsx`: Calls by User, Queue by Kind, Daily Cycle, Document Text and five bullet lists | system figures | up to 10 each | bounded; row 173 relays them out |
| `data/LoadConsole.tsx`: Work Left, Latest Failures (20), Month by Month, a month's days | system figures | up to 24 | bounded, read in date order |
| `data/Discovery.tsx`: Work Waiting, Latest Problems (20) | system figures | up to 20 | bounded |
| `profile/Profile.tsx` | devices | a few | bounded |
| `system/ApiPanel.tsx` ×2, `system/Console.tsx` ×3, `system/SystemHealth.tsx` | an API's days and recent calls, request fields, services | up to 30 | bounded, read in time order |
| `admin/mapping/Scoring.tsx` ×2 | M8, M9 | — | above |

#### Not data lists (28)

Navigation (`shell/NavTree.tsx` ×2, `shell/PortalShell.tsx` office switcher, `ui/layout.tsx` breadcrumb and settings
menu, `admin/UserTypes.tsx` Jump To), kit internals (`ui/OfficePicker.tsx` list, which has its own search,
`ui/overlays.tsx` menu, `ui/feedback.tsx` signals, `filters/FilterChips.tsx` chips), the two calendar grids
(`calendar/MonthGrid.tsx`, `calendar/DepartmentHearings.tsx`), and static or message text (`auth/AuthFrame.tsx`,
`auth/WelcomeForms.tsx`, `admin/Offices.tsx` in-use counts, `admin/Users.tsx` ×2 membership lines, `data/LoadConsole.tsx`
×2, `reports/ReportView.tsx` facts, `system/Console.tsx` ×7 outlines and steps, `dashboard/Blocks.tsx` "no dashboard"
text).

### What this row does not cover

- No change to who may see or do anything. No new write, no audit row (searches are reads; list reads are not audited
  today, and the Audit Log's own search is never audited).
- No NAPIX call and nothing sent to SourceTrace. Every search runs in the portal's own database or in the browser.
- No migration, no new table, column or index.
- The Search page, the Cause List page, the Audit Log filters and the Data Collection Work Items keep their forms.
- Row 165's office change on keyword, name-pattern and watchlist rows stays in row 165 (decision 14 settles its search
  half).

## Decisions

### A. One search for lists

1. **Two kinds of list search, by how the list is filtered today.**
   - **Lists with a filter form** (FilterBar, FilterCard, the Users toolbar) already search: their Words field is the
     search. They keep "applied with Search or Enter", because a search there is combined with dates and selects and
     must not run half-typed. This row makes the Words field visible on the first row everywhere (decision 17) and
     gives them the no-match state and the count rule.
   - **Every other list gets the kit's instant search** (decision 2), which filters while typing.
   - Alternative: replace the filter forms with the instant field. Refused: a debounced search alongside dates and
     selects would fire a request per keystroke on the largest lists and reset the page under the user.
2. **The kit search: `ListSearch` in a `ListToolbar`** (`components/ui/listSearch.tsx`, styles in
   `listSearch.module.css`, exported from `components/ui`).
   - **`ListToolbar`** is the list's one toolbar line, at the head of its card or above its `ScrollBox`:
     `{ search, count?, children? }`. The search field first; the list's own controls (switches, segmented choices,
     secondary buttons) after it; the count last, pushed to the right (`margin-inline-start: auto`). All sit on the 36 px
     control line (field-row rule). It wraps on the control line below about 1,000 px and stacks on phones (search full
     width, then controls, then count).
   - **`ListSearch`**: `{ label, placeholder, value, onChange, minChars?, busy? }`.
     - A `type="search"` field in a `role="search"` wrapper named by `label`. The label is visually hidden and the
       placeholder shows it (the Users toolbar rule, `portal-ui-polish-2` decision 27); the minimum length is a
       tooltip.
     - **Width:** 240 px minimum, growing to 360 px; full width on phones.
     - **A clear button** ("Clear Search", an icon button with that accessible name) appears inside the field when it
       holds text. **Escape** clears too. Both return focus to the field. The browser's own cancel button is hidden
       (`::-webkit-search-cancel-button { appearance: none }`), so every browser shows the same control.
     - `busy` shows the kit's small spinner at the field's end while a server search is in flight, with no layout
       shift.
   - **Labels in Title Case** ("Search Codes", "Search Tickets", "Search Parties and Advocates"); placeholders and hints
     in sentence case ("Code or part of a code"). `labels.test.ts` covers the new keys.
   - `RuleToolbar` (`mapping/common.tsx`) becomes a thin wrapper over `ListToolbar`, so the Mapping tabs keep their
     look.
   - Alternative: a bare `TextField type="search"` per list, as Mapping and the user-type page do today. Refused: that
     is how the lists drifted apart (clear button, debounce, counts and empty states differ on every page).
3. **Server-side `q` for paged lists; the browser filters only lists it holds in full.**
   - **Server:** every list the API pages (offset, cursor or "newest n") gains `q`. The browser never filters one
     page of a paged list, which would hide matches on other pages.
   - **Browser:** a list the API answers whole, bounded by its nature: Keywords and Name Patterns, Watchlist, Rules
     with Their Own Weight, Designations, the Offices tree, the two function lists, the Department Hearings agenda,
     the tracking summary's two tables, the State dashboard's By Department, the Search the Court answer, the report
     tables, Parties and Advocates. The inventory marks each.
   - **The browser match** (`lib/listSearch.ts` `matchesWords(query, ...texts)`, replacing `mapping/common.tsx`
     `matches`): the query is split on white space; every word must appear in at least one of the texts given;
     case and accents are ignored (`toLocaleLowerCase` after NFD with combining marks removed). Each list passes the
     texts its columns show, dates in the portal's format ("12 Oct 2025").
4. **A debounce of 300 ms for server searches; none for the browser.**
   - Server: `useDebounced(value, 300)` (`lib/useDebounced.ts`, the `useSettled` of `CounselCodes.tsx` moved to `lib`).
     **Enter** sends at once. A query shorter than the minimum (decision 6) is not sent; the tooltip says "Type at
     least 2 letters."
   - Browser: the filter runs on every keystroke through React's `useDeferredValue`, so typing stays smooth even over
     1,855 parties.
   - The query key includes the settled `q`, so TanStack Query cancels the superseded request.
5. **The search lives in the address where the list already keeps its filters; otherwise in the component.**
   - `useListSearch({ mode: "url" | "local", key = "q", minChars })` (`lib/useListSearch.ts`) returns `{ text,
     setText, applied, clear }`.
   - **URL mode** reads the key from the page's params and writes it with `router.replace` (no history entry per
     keystroke) once settled, dropping `offset`. Used by: Admin Tickets (its status is in the address), the Department
     Hearings agenda (`view`, `month`, `department` are), the View Cause List modal (as `vq`, beside its `view` and
     `vtab`; the page's own `q` is the Cause List's Search Words) and the report tables (as `find`, which
     `reportParams` never sends to the API or puts in an export).
   - **Local mode** everywhere else: the Mapping tabs (today's behaviour), Designations, Offices, the function lists,
     Conversations, the case-page tabs, the Duplicates tab (its kind is local), the court search answer, and any
     second list on a page whose address already holds a `q` for its main list (the tracking summary above Pending
     Action).
   - The filter-form lists keep their `q` in the address, as today.
6. **One validation for list `q`, on the server and in the browser.**
   - Trimmed; at least **2** characters (codes such as "SC" and "GA" are two letters) and at most **100**; at most 8
     words are used. The case lists keep their own rule (3 characters, `case_filters.MIN_QUERY`).
   - A bad value answers **400 `bad_q`** with the message, through the API's `detail()`.
   - LIKE wildcards in the query match literally (`case_filters.like_escape`).
   - **A date matches the list's date columns.** A query that is exactly a date in one of the forms people type
     ("12 Oct 2025", the portal's own; `12-10-2025`; `12/10/2025`; `12.10.2025`; `2025-10-12`) also matches rows whose
     date columns fall on that day (IST for timestamps). A year alone ("2025") is a word, not a date.
7. **The count: "12 of 340".**
   - **`ListCount`** (kit): `{ shown, total?, noun }` with `aria-live="polite"`:
     - not searching: "340 codes";
     - searching, with the unsearched total known: **"12 of 340 codes"**;
     - searching, without it: "12 codes match" (the FilterBar's line).
   - Every API that gains `q` in this row also returns **`total_all`**: the count of what the caller sees in that list
     with the same tab or status but without `q`. It is `null` when no `q` was sent (then `total` is that number).
   - The existing `CountLine` (inbox) becomes `ListCount`. The filter-form lists show "n of m" where the page already
     holds m (the inbox counts, as today) and "n cases match" elsewhere.
   - **The Audit Log shows no count.** It is cursor-paged with no total, by design (`audit-screens`).
   - Alternative: a second request for the unsearched count. Refused: `total_all` costs one count in the same request,
     over a set already narrowed to one case, one caller or one tab.
8. **The no-match state: `NoMatches`** (kit), shown instead of the list's own empty state whenever a search is set and
   nothing matches.
   - The text is **"No matches for “ram”."** (`T.list.noMatches(q)`), with a **Clear Search** button (secondary,
     small) that clears and returns focus to the field.
   - The filter-form lists say "No cases match these filters." with Clear All, which already exists in their chip
     strip.
   - The list's own empty state ("Every code seen in the cause lists is mapped.") still shows when the list is empty
     without a search.
   - **A search box shows only when the list can be searched usefully:** always when a search is set; otherwise when
     the list holds more than **10** rows (browser lists: their length; server lists: `total` of the unsearched
     answer). The constant is `LIST_SEARCH_FROM = 10` in `lib/listSearch.ts`.
   - Alternative: a box on every list, however short. Refused: a search box over three rows is clutter, and the
     owner's own example of an exception is a five-row card.

### B. Recommended From Cause Lists: every code (question 2)

9. **Every unmapped code, paged by 100 inside the panel's scroll box, most entries first.**
   - A new read **`GET /admin/counsel-codes/unmapped/page`** (API) returns `{ items, total, matched, next_cursor }`.
     `total` counts every unmapped code, `matched` those matching `q`.
   - **The order stays:** entries descending, then the code (`matching.unmapped_codes`'s order).
   - **Keyset paging** by the last row's `(entries, code)`, sent back as an opaque `cursor` (base64url JSON). When a
     person maps a code between pages, the next page neither repeats nor skips a code, which offset paging would.
   - The existing `GET /admin/counsel-codes/unmapped` stays unchanged for the CLI and older clients. The portal stops
     calling it.
   - Alternative: headers (`X-Total-Count`, `X-Next-Cursor`) on the existing path. Refused: three values outside the
     response model that the API tests and the OpenAPI document check.
   - Alternative: one answer of all 1,066 codes. Refused: each code carries its own Office Picker and Map form; 1,066
     of them at once is a slow first paint for a list read from the top.
10. **Loading more inside the box, never moving the page.**
    - The panel's list sits in the kit `ScrollBox` (row 172; it replaces `mapping.module.css` `.scrollBox`, same
      `min(60vh, 560px)`, labelled "Recommended From Cause Lists").
    - **The next page loads when the end of the list comes within 200 px of the box's bottom** (an
      `IntersectionObserver` whose root is the `ScrollBox`), through `useInfiniteQuery` with `next_cursor`.
    - **"Show 100 More"** (secondary, small) stays at the end of the list for the keyboard and wherever the observer is
      missing, with **"Showing 300 of 1,066"** beside it. At the end it reads "Showing all 1,066".
    - Pages are joined by code, so a code is never listed twice if entries change between pages.
    - **Virtualisation is refused:** it would unmount rows being edited (an open Office Picker, a typed choice), break
      the browser's find-in-page and the keyboard order through the list, and 1,066 rows in pages of 100 do not need
      it.
11. **The panel's toolbar, count and search.**
    - Under the notice "Nothing is mapped automatically.", one `ListToolbar`:
      - **Search Recommended Codes** (placeholder "Code or part of a code"), server `q`, 300 ms;
      - the count, which replaces "n to review": **"1,066 codes not mapped"**, or **"12 of 1,066 codes"** while
        searching.
    - **The match is on the code only**, ignoring spaces and punctuation: "ga assam" finds "GA, ASSAM" and "DY SGI"
      finds "DY.S.G.I.". The code is the column a person reads; the entries, the date and the example case are not
      searched.
    - No matches: "No matches for “…”." with Clear Search. Empty without a search: the existing "Every code seen in the
      cause lists is mapped."
    - **The row layout stays as the owner approved:** one row per code from 860 px (Code | entries and last seen |
      example case | Office and Map), with "Partly matches" or an error on a full-width line under it; stacked below.
      `mapping.module.css` `.recList` keeps its grid; only `.scrollBox` goes.
    - **Map** posts `POST /admin/counsel-codes` as today. The code then leaves every loaded page, and `total` and
      `matched` drop by one in the cache, without reloading the list. A 409 (someone mapped it meanwhile) reloads the
      panel, as `conflictAware` does today.
12. **The scope rule stays.** Every holder of `admin.counsel_codes` sees every unmapped printed code, as today (they
    are court data printed in public cause lists). Each code's partial matches are still limited to the mappings in the
    caller's office subtree (`matching_rules.counsel_code_scope`; `partial-code-match` decision 16). The example case
    links to the case page, whose own visibility rule decides what opens. A search only narrows this set.

### C. Department Mapping and the case lists (round 1)

13. **Counsel Codes** keeps its server `q` and gains the kit: `ListToolbar` (Search Codes, Include Deactivated), the
    count "12 of 340 codes" from the new `total_all` on `GET /admin/counsel-codes`, the no-match state, and the kit
    `ScrollBox`.
14. **Keywords and Name Patterns, and the Watchlist, keep filtering in the browser**, now with `matchesWords`, the kit
    toolbar, the count and the no-match state, and the kit `ScrollBox`.
    - `GET /admin/keywords`, `/admin/name-patterns` and `/admin/watchlist` answer their whole list, unpaged, and each is
      bounded by the departments' rules. A server `q` would add a request per keystroke and nothing else.
    - **Row 165's search half is therefore not needed:** this note proposes row 165 keep only the office change. A
      server `q` becomes worth adding if these lists are ever paged.
15. **Court Search tab.**
    - **Names Searched** gains server `q` on `GET /admin/discovery/terms` (the name, and the department codes), because
      the list is paged by the API (first 200 today). The toolbar sits above the table.
    - **Cases Found for a name** gains server `q` on `GET /admin/discovery/terms/{id}/cases`, read by
      `case_filters.parse_query` (CNR, reference, case number or words), beside the existing Only select.
16. **Rules with Their Own Weight** filters in the browser (rule text, office) when it holds more than 10 rows.
17. **The Case inbox's own views show Words on the first row.** `LIST_FILTERS.mine` drops `q` from `more`, so Working
    On, Claimed by Me and Disposed show **Search Words** first, before the quick chips and Stage. This was the list the
    owner uses most, and its search was hidden under More Filters. No API change.
18. **Every filter-form list** (C3-C10) shows "No cases match these filters." with Clear All when a filter or Words is
    set and nothing is found, instead of its general empty state. The search engine stays
    `case_filters.parse_query` with `cases.search_vector`; nothing in it changes.

### D. Administration and other pages (round 2)

19. **Users and the Audit Log keep their forms.** Users gains `ListCount` ("12 users match" or "340 users"), the
    no-match state and a clear button in the Name or E-mail field. The Audit Log gains the no-match state only.
20. **The Offices tree** filters in the browser on the office name and code: a matching office shows with its parents
    (so its place in the tree stays visible) and every matched branch opens; the match is marked with `<mark>`. The
    count reads "12 of 340 offices".
21. **Search the Court answers** get a browser filter, **Search These Results**, over the results and the rows not
    stored. Narrowing an answer must not send the court search again: each court search spends the hourly NAPIX
    allowance.
22. **Reports.** One **Find in This Report** field filters every section's rows in the browser (the cell texts as
    shown). While a search is set:
    - each section shows "12 of 340 rows";
    - the totals row is hidden, with the line "Totals cover the whole report. Clear the search to see them.", because
      totals of all rows under filtered rows would mislead;
    - the Excel and PDF downloads stay the whole report, with their audit unchanged.
23. **The rest of round 2** follows the general rules: Designations, the two function lists, the Department Hearings
    agenda, the tracking summary's two tables, By Department in the browser; Admin Tickets and Conversations by server
    `q`; the View Cause List modal by the entries API's existing `q` (as `vq` in the address).
24. **Data Collection, only where rows 172-174 leave a list without a search,** built in round 2 only once rows 173
    and 174 are merged (otherwise they move to round 3):
    - **Duplicates:** server `q` read by `case_filters.parse_query`, matching either case of a row (and, for Needs
      Review, either case the review names). The toolbar sits at the head of the table's card, under the tab's toolbar
      line (Updated n s ago, Scan Now).
    - **Court Calls:** a free-text search would match nothing a person reads (times, codes and counts). It gains two
      filters on its toolbar line instead: **Court Service** (the 17 plain names of row 173) and **Failed Only**, sent
      as the endpoint's existing `api` and `ok`. No API change.
    - **A request's items** (row 174's side panel): server `q` on `GET /admin/data-load/requests/{id}`, read by
      `case_filters.parse_query` against each item's case.
    - Nothing else in Data Collection changes: the remaining lists are bounded (inventory).

### E. The case page (round 3)

25. **Each paged tab gains server `q` over the columns it shows; visibility is applied before the search.**

    | Tab | Endpoint | Words match | Dates match |
    |---|---|---|---|
    | Hearings | `GET /cases/{ref}/hearings` | purpose, bench, judge designation, list type, business text, short order text | hearing date, business date, next date |
    | Listings | `GET /cases/{ref}/listings` | bench label, list type, court number, printed serial, section, remarks | list date |
    | Orders, and the modal's Orders | `GET /cases/{ref}/orders` | order number, kind, order details, judge | order date |
    | Documents | `GET /cases/{ref}/documents` | description, file name, type label, reference | document date, upload date |
    | Notes, and the Remarks panel's Notes | `GET /cases/{ref}/notes` | body, kind label, author name, reference | written date |
    | Remarks panel's Remarks, and the Custody tab's Movement | `GET /cases/{ref}/custody` | holder office name and code, holder name, designation, reason label, pending action label, and the remark **only when `remarks_shown`** | start date, due date |
    | Timeline | `GET /cases/{ref}/timeline` | the event's label only | event date |

    - **Notes:** only notes the caller may read are searched (per-note visibility and the private-record rule of
      `cases.view_private_all`). A hidden note whose body holds the word is neither listed nor counted in `total` or
      `total_all`.
    - **Documents:** the same, by per-document visibility.
    - **Custody:** a remark the caller may not read is never matched, so the search cannot be used to test what a
      hidden remark says.
    - **Timeline:** the payload is never searched. Its one-line details are built in the browser from known keys
      (`lib/timeline.ts`), and the payload can hold values the screen never shows; matching them would reveal them.
    - **Orders:** the Orders tab adds the link **"Search Inside These Orders"** to `/search?tab=documents&case=…`, the
      existing content search over order text. `q` here matches the columns shown, not the PDF's text.
    - **Parties and Advocates** filter in the browser (name, role or side, code), one **Search Parties and Advocates**
      field over both tables, because the API answers both whole. This serves the case with 1,855 parties.
    - A `q` on a case the caller cannot see answers exactly as the same request without `q` does (the existing 404).
    - The search box sits on the tab's toolbar line, with its existing controls (Show Corrections, Include Archived,
      the kind select). The paging resets to the first page on each new search.

### F. Visibility, rounds and order

26. **A search never widens what a caller sees.**
    - On the server, every `q` condition is ANDed with the list's existing conditions (`visible_case_condition`, the
      office scope, per-note and per-document visibility, the caller's own conversations, the ticket panel's scope),
      and `total_all` is counted under the same conditions.
    - In the browser, a filter can only hide rows the API already returned.
    - Each server `q` has a pytest that a search cannot reveal another department's case, note, document, remark,
      ticket or conversation (Tests).
27. **Three rounds, each its own branch, review and report** (the `portal-ui-polish-2` and `data-collection-redesign`
    precedent). About 50 components and 15 endpoints are too many for one review.
    - **Round 1 (row 175, `feature/list-search`), after row 172:** the kit and shared helpers (decisions 1-8), the
      backend helper `services/list_search.py`, the full Recommended From Cause Lists (9-12), the Department Mapping
      lists (13-16) and the case-list consistency (17-18).
    - **Round 2 (new row at approval, `list-search-admin`):** decisions 19-24. Its Data Collection part needs rows 173
      and 174 merged.
    - **Round 3 (new row at approval, `list-search-case-page`):** decision 25.
    - The owner's browser check of the three rounds becomes a separate row at approval.

## Data

**No new table, column, index or reference code. No migration.**

- Every server `q` runs over a set the list already narrows by an indexed key:
  - one case (`case_id` indexes on hearings, listings, orders, documents, notes, custody history and events);
  - one caller (assistant conversations by user);
  - or a small table (admin tickets, discovery terms, counsel codes).

  An `ILIKE` over that set needs no trigram index.
- The case-based searches (term cases, duplicates, request items, the case lists) use `case_filters.parse_query`:
  `cases.ref_no`, `cases.cnr`, the case-number match and the GIN index on `cases.search_vector`, all existing.
- The unmapped-code list is an aggregate over every current cause-list entry. No index helps it, and it takes about
  200 ms (Context).
- Should a later measurement need an index, it belongs to its own row and takes the next free migration number after
  main's highest (0027 today; rows 157 and 169 both plan 0028).
- `docs/schema/schema.md` needs no paragraph.

## Services

None calls NAPIX or SourceTrace. None writes or audits.

- **`services/list_search.py`** (new, round 1), the shared `q` of non-case lists:
  - `MIN_CHARS = 2`, `MAX_CHARS = 100`, `MAX_WORDS = 8`;
  - `class ListSearchError(ValueError)`, mapped to 400 `bad_q`;
  - `@dataclass(frozen=True) class ListQuery: raw: str; words: tuple[str, ...]; day: date | None`;
  - `parse(q: str | None) -> ListQuery | None`: trims, checks the length, splits words on white space (punctuation
    inside a word stays, so "WP(C)" is one word), and reads `day` from the five date forms of decision 6;
  - `condition(lq, text=[...], dates=[...], timestamps=[...]) -> ColumnElement[bool]`:
    - each word ORs `coalesce(col, '') ILIKE '%word%' ESCAPE '\'` over `text`;
    - the words are ANDed;
    - with a `day`, ORs `date_col = day` and `ist_midnight(day) <= ts_col < ist_midnight(day + 1)`
      (`core/clock.py`);
  - each list names its columns in one place next to its query, so "the columns a person reads" are explicit and
    tested.
- **`services/matching.py`** (round 1):
  - `_unmapped_aggregate(session) -> list[tuple[str, dict]]`: today's two aggregates, normalisation and merge, sorted
    by entries descending then code. `unmapped_codes` (CLI, old endpoint) is rebuilt on it with the same signature
    and output.
  - **`unmapped_page(session, *, q=None, limit=100, after: tuple[int, str] | None = None, scope=None) ->
    UnmappedPage(items, total, matched, next_cursor)`**:
    - `total` = all unmapped codes;
    - `q` (validated by `list_search.parse`) keeps codes whose compact form (letters and digits, upper case) contains
      the compact query;
    - `matched` = those kept;
    - `after` skips to the first row after `(entries, code)` in the order;
    - `limit` 1-200;
    - example references and partial matches are worked out **for the page only** (`RuleSet.load` once,
      `partial_matches` filtered by `scope` as today).
  - `encode_cursor` and `decode_cursor`; a bad cursor raises `ListSearchError` (400 `bad_cursor`).
- **`services/matching_rules.py`** (round 1): `list_counsel_codes` returns `total_all` when `q` is set.
- **`services/discovery.py`** (round 1):
  - `terms_view(..., q=None)`: `list_search.condition` on the term text and the department codes;
  - `term_cases(..., q=None)`: `case_filters.query_condition(parse_query(q))` on the case.
  - Both return `total_all`.
- **Round 2:**
  - `services/tickets.py` `list_tickets(..., q=None)`: reference, operation, department code and name, target name,
    requester name; ticket date.
  - `services/assistant.py` `conversations(..., q=None)`: title, and the case's number and CNR; last message date. The
    caller's own conversations only, as today.
  - `services/data_load.py`: `duplicates(..., q=None)` (`parse_query` on either case) and `request_items(..., q=None)`
    (row 174).
  - Each returns `total_all`.
- **Round 3:** `case_detail.hearings`, `listings`, `orders`, `timeline`; `documents` `list_for_case`;
  `notes.list_for_case`; `custody.history`. Each:
  - gains `q=None`;
  - applies the columns of decision 25 after its visibility conditions;
  - returns `total_all`.

  `custody.history` adds the remark column only when `shows_remark` is true. `timeline` joins `ref_event_type` for the
  label (`coalesce(timeline_label, label)`) and never reads `payload` in the condition.

## API

Every change is an additive read: a new optional `q`, and a `total_all: int | null` field in the response (null when
no `q` was sent). Every endpoint keeps its function and its visibility rule. Searches are not audited.

| Method and path | Function (`Permission`) | Round | Request | Response |
|---|---|---|---|---|
| `GET /admin/counsel-codes/unmapped/page` (new) | `admin.counsel_codes` | 1 | `q?`, `limit=100` (1-200), `cursor?` | `UnmappedCodePageOut {items: [UnmappedCodeOut], total, matched, next_cursor}`; 400 `bad_q`, `bad_cursor` |
| `GET /admin/counsel-codes/unmapped` (existing) | `admin.counsel_codes` | — | unchanged | unchanged |
| `GET /admin/counsel-codes` | `admin.counsel_codes` | 1 | `q` (existing) | `CounselCodeListOut` + `total_all` |
| `GET /admin/discovery/terms` | `admin.keywords` | 1 | + `q` | `DiscoveryTermListOut` + `total_all` |
| `GET /admin/discovery/terms/{id}/cases` | `admin.keywords` | 1 | + `q` (case search) | `DiscoveryCaseListOut` + `total_all` |
| `GET /admin/tickets` | `admin.tickets` or `users.propose_head` | 2 | + `q` | `TicketListOut` + `total_all` |
| `GET /assistant/conversations` | `assistant.use` | 2 | + `q` | `AssistantConversationListOut` + `total_all` |
| `GET /admin/data-load/duplicates` | any of `data_load.READERS` | 2 | + `q` (case search) | `DuplicatesOut` + `total_all` |
| `GET /admin/data-load/requests/{id}` (row 174) | any of `data_load.READERS` | 2 | + `q` (case search) | `FetchRequestItemsOut` + `total_all` |
| `GET /cases/{ref}/hearings`, `/listings`, `/orders`, `/timeline` | `cases.view_scope` or `cases.view_all` | 3 | + `q` | each list + `total_all` |
| `GET /cases/{ref}/documents` | `documents.view` | 3 | + `q` | `DocumentListOut` + `total_all` |
| `GET /cases/{ref}/notes` | `cases.view_scope` or `cases.view_all` | 3 | + `q` | `NoteListOut` + `total_all` |
| `GET /cases/{ref}/custody` | `cases.view_scope` or `cases.view_all` | 3 | + `q` | `CustodyHistoryOut` + `total_all` |

- **Used unchanged:**
  - `GET /causelists/{date}/entries?q=` (the View Cause List modal);
  - `GET /admin/napix/calls?api=&ok=` (Court Calls);
  - the browser-filtered lists' endpoints;
  - every case-list endpoint with the shared filters.
- `UnmappedCodeOut` is unchanged: `code`, `entries`, `last_listed`, `example_case_ref`, `partial_matches`.
- The frontend types are regenerated (`schema.d.ts`), and `lib/api/types.ts` exports `UnmappedCodePage`.

## Jobs

None.

## Tests

**pytest, round 1**
- `tests/unit/test_list_search_parse.py`:
  - empty → None;
  - one character → `bad_q`; 101 characters → `bad_q`;
  - words split on white space, at most 8, punctuation kept inside a word;
  - `%` and `_` match literally;
  - each of the five date forms gives `day`; "2025" stays a word.
- `tests/db/test_unmapped_page.py`:
  - **`test_every_unmapped_code_is_listed`**: a world with 250 printed codes and some advocate-only codes; walking
    every cursor yields each unmapped code exactly once, in the order entries descending then code, and the count
    equals `total` and `len(unmapped_codes(limit=10_000))`;
  - `test_q_matches_the_compact_code` ("ga assam" finds "GA, ASSAM"); `matched` counts only matches; `total` is
    unchanged;
  - `test_cursor_survives_a_mapping_between_pages`: map a code from page 1, then page 2 neither repeats nor skips;
  - `test_partial_matches_stay_scoped`: an EDU administrator sees only EDU partial matches, the super admin all;
  - `test_requires_admin_counsel_codes` (403); `test_bad_cursor_is_400`; `test_bad_q_is_400`;
  - `test_old_endpoint_unchanged`: `GET /admin/counsel-codes/unmapped?limit=100` answers the same body as before the
    refactor.
- `tests/db/test_api_matching.py`: `test_counsel_codes_total_all_with_q`.
- `tests/db/test_discovery_q.py`:
  - terms `q` matches the name, and another department's term never appears for a department administrator;
  - term cases `q` by CNR, number and words narrows only, and a CNR of a case not found for this name answers nothing.
- `tests/db/test_case_list_q_scope.py`, parametrised over `/inbox/mine?view=working|claimed|disposed`,
  `/inbox/claimed`, `/inbox/recommended`, `/inbox/pool`, `/inbox/transfers`, `/custody/held`, `/custody/sent`,
  `/alerts`, `/next-dates/review` and `/cases`:
  - with `q` set to another department's case CNR, its number or a party word, that case is not returned;
  - every answer with `q` is a subset of the answer without it.

**pytest, round 2**
- `test_tickets_q_stays_in_scope`: a department administrator searching another department's ticket reference gets
  nothing; `total_all` equals the unsearched total.
- `test_conversations_q_only_own`: another person's conversation title never matches.
- `test_duplicates_q_matches_either_case`.
- `test_request_items_q` (with row 174).

**pytest, round 3** (`tests/db/test_case_tab_q.py`)
- each tab's `q` matches each of its columns and its date columns;
- `test_hidden_note_never_matches`: a private note of another office holding the word is neither listed nor counted
  in `total` or `total_all`;
- `test_hidden_document_never_matches`;
- `test_hidden_remark_never_matches`: with `remarks_shown` false, a remark holding the word does not match;
- `test_timeline_payload_not_searched`: a word only in an event's payload finds nothing;
- `test_q_on_invisible_case_is_404`;
- `test_total_all_is_the_visible_total`.

**vitest, round 1**
- `components/ui/listSearch.test.tsx`:
  - the request waits 300 ms (fake timers) and Enter sends at once;
  - Clear Search and Escape clear the field and return focus to it;
  - the counts: "340 codes", "12 of 340 codes", "12 codes match";
  - `NoMatches` shows the query and its Clear Search;
  - the box is hidden at 10 rows and shown at 11 or with a search set;
  - URL mode writes `q` with `router.replace` and drops `offset`;
  - the native cancel button is hidden.
- `lib/listSearch.test.ts`: every word must match; case and accents are ignored; dates in the portal's format.
- `components/admin/mapping.test.tsx`:
  - the panel reads `/unmapped/page` and follows `next_cursor` on Show 100 More and when the observer fires (mocked);
  - "1,066 codes not mapped" and "Showing 300 of 1,066";
  - the search sends `q` after the debounce and shows "12 of 1,066 codes";
  - Map removes the row from the loaded pages and lowers both counts;
  - the no-match state;
  - the one-row layout class stays;
  - Keywords and Watchlist counts and no-match states;
  - Court Search terms and cases send `q`.
- `components/inbox/inbox.test.tsx`: Working On, Claimed by Me and Disposed draw Search Words on the first row, not
  inside More Filters; a filtered empty list says "No cases match these filters.".
- `lib/labels.test.ts` covers the new labels.

**vitest, round 2:** `admin.test.tsx` (Designations, Tickets with `q` in the address, the Offices tree keeps parents,
the Change Exceptions functions), `userDetails.test.tsx` (Functions tab), `assistant.test.tsx`,
`departmentHearings.test.tsx`, `cases-list.test.tsx` (tracking summary), `dashboard.test.tsx` (By Department),
`causelist.test.tsx` (`vq` in the modal), `search.test.tsx` (court answer narrowed with no second court request),
`reports.test.tsx` (Find hides the totals and leaves the downloads whole), `audit.test.tsx`, `data.test.tsx`
(Duplicates `q`, Court Calls filters).

**vitest, round 3:** `case.test.tsx` (Parties and Advocates in the browser; Hearings, Listings, Orders, Documents,
Timeline send `q`; the link Search Inside These Orders), `remarks.test.tsx`, `workflow.test.tsx` (Movement),
`claim.test.tsx` (the modal's Orders).

**uicheck** (`frontend/e2e/uicheck.spec.ts`, at 375, 768 and 1280 px; the fixtures serve 1,066 synthetic codes on
`/admin/counsel-codes/unmapped/page`):
- round 1:
  - "/admin/mapping/codes (Recommended From Cause Lists: 300 of 1,066 loaded)";
  - "/admin/mapping/codes (Recommended: no matches)";
  - "/admin/mapping/keywords (search typed)";
  - "/inbox/working (Search Words on the first row)";
- round 2: "/admin/tickets (search)", "/admin/offices (tree search)", "/calendar?view=department (search)",
  "/reports/pending-cases (find)";
- round 3: "/cases/[ref]/parties (search)", "/cases/[ref]/notes (no matches)", "/cases/[ref]/orders (search)".

## Verification

1. **Each round:** `ruff check` clean and `pytest -q` green; in `frontend`, `npm run lint`, `npm run typecheck` and
   `npx vitest run` green.
2. **Round 1, the full list against the dev database** (as the super admin, after the merge; the numbers move as
   cause lists arrive):
   - In the API container, `len(matching.unmapped_codes(s, limit=100_000))` gives N (1,066 on 26 Oct 2026).
   - `GET /admin/counsel-codes/unmapped/page` answers `total` = N. Following `next_cursor` to the end yields N distinct
     codes, in the same order as `unmapped_codes`.
   - Each page answers in under 500 ms (about 200 ms measured for the whole aggregate).
   - `q=assam` gives `matched` equal to the number of codes whose compact form contains ASSAM.
3. **Round 1, on screen** at `http://localhost:3000/admin/mapping/codes`:
   - The panel reads "1,066 codes not mapped".
   - Scrolling inside its box loads more until "Showing all 1,066"; the page itself does not grow.
   - Typing "assam" narrows it to "n of 1,066 codes" after a pause.
   - Mapping one code removes it and the count drops by one.
   - Each code is one row at 1280 px.
   - At `/inbox/working`, Search Words is on the first row.
4. **Round 2:** at `/admin/tickets?status=all`, a search for part of a ticket reference narrows the list and survives
   a reload. A Search the Court answer narrowed by Search These Results makes no second court request (the API log
   shows one `POST /cases/search-court`).
5. **Round 3:** on a case with many parties, Search Parties and Advocates narrows at once. On the Notes tab, a word from
   a note shows that note and "1 of n notes".
6. **The browser check, each round:** `docker compose --profile uicheck run --rm uicheck`. No finding at 375, 768 and
   1280 px; the new states pass.
7. **The owner's browser check** of the three rounds becomes a separate backlog row at approval.

## Open questions

None. Every decision above is made. The owner's approval covers in particular:
- decision 8, a search box only on lists of more than 10 rows (or with a search set);
- decision 14, keywords and the watchlist filtered in the browser, so row 165 keeps only its office change;
- decision 11, the total "1,066 codes not mapped", which counts codes seen only in case details as well, as the panel
  always has;
- decision 27, the three rounds, with round 1 after row 172.
