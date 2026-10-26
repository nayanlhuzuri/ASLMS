# Design: Search and Sort in every list, and the full Recommended From Cause Lists

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
3. Added the same day: "Whatever lists you find, there should be an option to sort also, which I find missing."

The owner wants no mockup. This note keeps the slug `list-search`, so the branch and links stay.

**The visual rules** are the as-built kit and the approved notes:
- `portal-ui-polish-2`:
  - Title Case labels (decisions 1-6);
  - the field-row and checkbox rules (decision 26);
  - the Users one-line toolbar (decision 27);
  - one toolbar line per Mapping tab (decision 41);
  - the content of the Recommended panel (decision 42).
- The decisions log, "Department Mapping layout, owner changes (2026-10-26)":
  - the panel sits below the codes list;
  - one row per code where the box is at least 860 px wide;
  - each long list scrolls in its own box of at most min(60vh, 560px).
- `data-collection-redesign` (row 172, approved, not built):
  - the kit `ScrollBox`;
  - `DataTable` captions hidden by default;
  - no upper-case labels anywhere in the portal;
  - one toolbar line per Data Collection tab.

**This row is built after row 172** and uses its `ScrollBox`. It does not lay out the Data Collection tabs again (rows
173 and 174 do that). It only adds search and sort where those rows leave a list without them (decision 24).

The plan has no rule on searching or sorting inside lists. §5.2 is the case search, and §5.10 makes the audit log
"searchable by user, case and date". This row deviates from nothing.

### Question 2: the panel is not exhaustive (checked 26 Oct 2026)

- `RecommendedCodes` in `CounselCodes.tsx` calls `GET /admin/counsel-codes/unmapped?limit=100`. The API's default is
  200 and its maximum 1,000 (`matching.unmapped_codes`). So the panel shows the 100 codes with the most entries, and
  says "100 to review".
- The dev database holds **1,066 unmapped codes**. They are:
  - the 1,018 distinct printed codes in the current cause lists;
  - plus codes seen only among the advocates of fetched case details (403 distinct there);
  - normalised by `normalise_counsel_code`;
  - less the 2 mapped.

  The panel has always counted both sources, and this row keeps that rule. So the panel will read "1,066 codes not
  mapped" today, not 1,016.
- 245 of the 1,066 codes appear once. 4 partly match a mapping.
- **Listing them all costs little.** Timed on the dev database (167,002 cause-list entries, 8,299 lists):
  - the cause-list aggregate (`unnest(counsel_codes)` grouped over current lists): 94 ms;
  - the case-advocate aggregate: 28 ms;
  - the whole `unmapped_codes(limit=100000)` call inside the API container: **about 200 ms**. That covers
    normalisation, example references and partial matches for all 1,066 codes.
- No index makes a `GROUP BY` over every current entry cheaper. The cost grows roughly in line with the number of
  entries. If a page ever takes more than a second, the next step is a summary table; it is not needed now. **No
  migration.**

### What sorts today

**No list lets the user choose its order.** Every server list has one fixed order. The only `order` parameter,
`asc|desc` on `GET /cases/{ref}/custody`, is used by the case rail and the Remarks panel; nobody can change it on
screen. Three browser lists sort themselves in code: membership cards, user-type functions and the agenda dates.

Some fixed orders have **no unique last key**, so a page boundary can repeat or skip a row when two rows tie:
- the inbox lists: Claimed, Recommended and Transfers;
- the case tabs: Hearings (`business_date, purpose`), Orders (`order_date, order_no`), Documents (`doc_date,
  created_at`) and Listings;
- discovery Names Searched, which is sorted in Python by name.

Decision 31 fixes this wherever a list gains sort.

**The cost of the sorts this note offers on the large tables** (dev database, 26 Oct 2026, `EXPLAIN ANALYZE`):

| Table (rows) | Sort | Plan | Time |
|---|---|---|---|
| `cases` (59,872) | case number: type, then number, then year, then id, with `LIMIT 50 OFFSET 5000` | top-N heapsort | 36 ms |
| `cases` | next hearing, last hearing | top-N heapsort | 13 ms |
| `cases` with a words match | year | top-N heapsort | 22 ms |
| `audit_log` | `created_at, id` ascending (and descending) | `ix_audit_log_created_at`, incremental sort | 0.08 ms |
| `napix_call_log` (283,574) | `called_at, id` ascending (and descending) | `ix_napix_call_log_called_at` | 0.05 ms |
| `fetch_queue` (384,858) | added on, tries | top-N heapsort | 26-30 ms |
| `orders` (323,150) | per case only (`ix_orders_case_id`), largest case 134 | in memory | <1 ms |
| `causelist_entries` (167,002) | none offered (court order, decision 30) | — | — |

At three times today's data, the slowest of these stays near 120 ms. **No index or migration is needed** (Data).

### Question 1: the inventory

Every `DataTable` (69 uses), every `<ul>` or `<ol>` (67), every hand-written `<table>` (4) and the two order lists built
from `div`s in `frontend/src/components/**` were read. That is **142 places**:
- **28 are not data lists**: navigation, kit internals, static text and chips (listed at the end of the inventory);
- **114 are data lists**.

Two more lists have no place of their own in the code:
- the Search the Court answer (A15), which reuses the Search page's results table (C11);
- row 174's request items (A20), not built yet.

So **116 data lists** are counted below.

| | Search | Sort |
|---|---|---|
| Have it today | 21 | **0** (fixed orders only) |
| Gain it in this row | **33** | **42** |
| Left without it, with a reason | 62 | 74 |

The sizes come from the dev database where it has the data, otherwise from the setting that bounds the list or the
expected State-wide size.

**How to read the tables:**
- **Search today:**
  - "Form" is a filter form applied with Search or Apply (FilterBar, FilterCard, the Users toolbar);
  - "Instant" filters while typing.
- **Data:**
  - "Server" means the API pages or narrows the list;
  - "Full" means the browser holds it whole.
- **Sort:**
  - the keys offered, with **(d)** marking the default order kept today;
  - "dir" means direction only (Newest First or Oldest First);
  - "browser" means sorted in the browser.
- **R1-R4** are this row's rounds (decision 40).

#### Department Mapping (`components/admin/mapping`)

| # | List | Search today | Data | Usual size | Search in this row | Sort in this row |
|---|---|---|---|---|---|---|
| M1 | Counsel Codes (`CounselCodes.tsx` table) | Instant, server `q`, 300 ms | Server, unpaged | tens to hundreds | **R1** kit toolbar, count, no-match state, `ScrollBox` (decision 13) | **R1** browser: Code (d, A to Z), Office, Status, Updated |
| M2 | Recommended From Cause Lists (`CounselCodes.tsx` `<ul>`) | none | Server, first 100 | **1,066** | **R1** every code, paged, server `q` (decisions 9-12) | **R1** server: Entries (d, Most First), Code, Last Seen (decision 39) |
| M3 | Keywords and Name Patterns (`Keywords.tsx`) | Instant, in the browser | Full, unpaged | tens to hundreds | **R1** kit, stays in the browser (decision 14) | **R1** browser: Office (d, office order), Word or Pattern, Kind, Status |
| M4 | Watchlist (`Watchlist.tsx`) | Instant, in the browser | Full, unpaged | tens | **R1** kit, stays in the browser (decision 14) | **R1** browser: Office (d), CNR, Case Number |
| M5 | Court Search → Names Searched (`CourtSearch.tsx`) | none | Server, first 200 | tens | **R1** server `q` (decision 15) | **R1** server: Name (d, A to Z), Last Searched, Cases Found |
| M6 | Court Search → Cases Found for a name (`CourtSearch.tsx`) | none ("Only" select) | Server, 50 a page | up to thousands | **R1** server `q`, the case search (decision 15) | **R1** server: Last Found (d, Newest First), Case Number, Year |
| M7 | Scoring → Rules with Their Own Weight (`Scoring.tsx`) | none | Full | 0 to a few | **R1** in the browser, above 10 rows (decision 16) | **R1** browser: Office (d), Rule, Own Weight |
| M8 | Scoring → History (`Scoring.tsx`) | none | Server | tens | left out: versions read by date | left out: the newest version first is the meaning |
| M9 | Scoring → the save summary (`Scoring.tsx`, confirm dialog) | — | Full | 6 | left out: six fixed weights | left out |

#### Case lists with the shared filters

| # | List | Search today | Data | Usual size | Search in this row | Sort in this row (server) |
|---|---|---|---|---|---|---|
| C1 | Case inbox → Working On (`WorkingOn.tsx`) | Form; **Words hidden under More Filters** | Server | tens | **R1** Words on the first row (decision 17) | **R2** Your Due Date First (d), Due Date, Next Hearing, Case Number |
| C2 | Case inbox → Claimed by Me, Disposed (`MyCases.tsx`) | Form; **Words hidden under More Filters** | Server | tens to hundreds | **R1** Words on the first row | **R2** today's order (d), Next Hearing, Case Number, Claimed On; Disposed adds Disposal Date |
| C3 | Case inbox → Department Cases (`DepartmentCases.tsx`) | Form (Layout B, Words hero) | Server | thousands | **R1** no-match state only (decision 18) | **R2** Next Hearing (d), Case Number, Claimed On |
| C4 | Case inbox → Sent by Me (`files/Sent.tsx`) | Form | Server | tens | **R1** no-match state only | **R2** Sent On (d, Newest First), Case Number, Due Date |
| C5 | Case inbox → Pending Action (`files/Held.tsx`) | Form | Server | tens to hundreds | **R1** no-match state only | **R2** Due Date (d, Earliest First), Since, Case Number |
| C6 | Case Claim → Recommended (`claim/Recommended.tsx`) | Form | Server | hundreds | **R1** no-match state only | **R2** Best Match First (d), Match Score, Next Hearing, Case Number |
| C7 | Case Claim → Unclaimed Pool (`claim/Pool.tsx`) | Form | Server | tens of thousands | **R1** no-match state only | **R2** Next Hearing (d), Best Score, Case Number |
| C8 | Case Claim → Transfers (`claim/Transfers.tsx`) | Form | Server | tens | **R1** no-match state only | **R2** Requested On (d, Newest First), Case Number |
| C9 | Alerts (`alerts/AlertList.tsx`) | Form | Server | hundreds | **R1** no-match state only | **R2** Raised On (d, Newest First), Due |
| C10 | Next Dates review (`nextdates/ReviewList.tsx`) | Form | Server | tens | **R1** no-match state only | **R2** Found On (d, Newest First), Next Date, Case Number |
| C11 | Search → Cases (`search/CaseResults.tsx`) | Form (it is the search) | Server | any | unchanged | **R2** Best Match First (d, with words) or Next Hearing (d, without), Case Number, Year |
| C12 | Search → Inside Documents (`search/TextSearch.tsx`) | Form (it is the search) | Server | any | unchanged | **R2** Best Match First (d), Document Date |
| C13 | Cause List entries (`causelist/EntryTable.tsx`) | Form (Search Words) | Server | up to 1,191 a day | unchanged | left out: court order is the meaning (decision 30) |

#### Administration, audit and other pages

| # | List | Search today | Data | Usual size | Search in this row | Sort in this row |
|---|---|---|---|---|---|---|
| A1 | Users (`admin/Users.tsx`) | Form (toolbar `q`) | Server, 50 a page | hundreds to thousands | **R3** kit count, clear, no-match state (decision 19) | **R3** server: E-mail (d, A to Z), Name, Last Signed In |
| A2 | Designations (`admin/Designations.tsx`) | none | Full | 20 to 60 | **R3** in the browser | **R3** browser: Order (d), Code, Name |
| A3 | Offices tree (`admin/Offices.tsx`) | none | Full | hundreds of offices | **R3** in the browser, matches with their parents (decision 20) | left out: the tree's order (parent above child) is the meaning |
| A4 | Admin Tickets (`admin/Tickets.tsx`) | none (status tabs) | Server, 50 a page | tens a year | **R3** server `q` | **R3** server: Opened (d, Oldest First), Department, Kind |
| A5 | User Details → Functions tab (`admin/UserDetails.tsx`) | none | Full | about 45 | **R3** in the browser | left out: functions keep the catalogue's groups and order, as on the user-type page |
| A6 | Change Exceptions panel (`admin/UserDetail.tsx`) | none | Full | about 45 | **R3** in the browser | left out: as A5 |
| A7 | User type page functions (`admin/UserTypes.tsx`) | Instant (Find) | Full | about 45 | unchanged | left out: as A5 |
| A8 | Audit Log (`audit/AuditTable.tsx`) | Form (Layout B) | Server, cursor | thousands | **R3** no-match state; no count (decision 19) | **R3** server: Newest First (d) or Oldest First only (decision 34) |
| A9 | Assistant → Conversations (`assistant/Assistant.tsx`) | none | Server, newest 50 | tens to hundreds | **R3** server `q` | **R3** server: Latest Message (d), Started, Title |
| A10 | My Calendar → Department Hearings agenda (`calendar/DepartmentHearings.tsx`) | none | Full (up to 62 days) | hundreds | **R3** in the browser | left out: an agenda by day, then court and item, is the meaning |
| A11 | Tracking summary, By Holder Department (`files/TrackingSummary.tsx`) | none | Full | 1 to about 60 | **R3** in the browser, above 10 rows | **R3** browser: Department (d), each count column |
| A12 | Tracking summary, By Holder (`files/TrackingSummary.tsx`) | none | Full | tens to hundreds | **R3** in the browser, above 10 rows | **R3** browser: Holder (d), each count column |
| A13 | State dashboard → By Department (`dashboard/Blocks.tsx`) | none | Full | about 60 | **R3** in the browser | **R3** browser: Department (d), each count column; "Not Claimed" stays the last row |
| A14 | View Cause List modal entries (`causelist/ViewCauseList.tsx`) | none | Server, 100 a page | up to 144 a list | **R3** the entries API's existing `q` | left out: court order |
| A15 | Search the Court answer (`search/CourtSearch.tsx` with `CaseResults`) | none | Full (one answer) | up to the advocate cap | **R3** in the browser (decision 21) | **R3** browser: as the court answered (d), Case Number, Next Hearing, Year |
| A16 | Search the Court → rows not stored (`search/CourtSearch.tsx` `<ul>`) | none | Full | a few to tens | **R3** the same field as A15 | left out: a few lines in the court's order |
| A17 | Reports, each section's table (`reports/ReportView.tsx`) | none | Full, paged by 50 in the browser | up to the report's cap | **R3** in the browser (decision 22) | **R3** browser: every column, per section (d: the report's order) |
| A18 | Data Collection → Duplicates (`data/Duplicates.tsx`) | none | Server, 50 a page | tens to hundreds | **R3** server `q`, the case search, after row 173 | **R3** server: When, Newest First (d) or Oldest First |
| A19 | Data Collection → Court Calls (`data/Queue.tsx`) | none | Server, cursor | thousands a day | **R3** Court Service and Failed Only filters, after row 173 | **R3** server: Newest First (d) or Oldest First only (decision 34) |
| A20 | Data Collection → a request's items (row 174) | none (not built) | Server, 100 a page | up to 2,000 | **R3** server `q`, after row 174 | **R3** server: as queued (d), Case Number, State, Tries |
| A21 | Data Collection → Work Items (`data/Queue.tsx`) | Form (Reference Starts With) | Server | thousands | unchanged | **R3** server: Runs First (d, priority), Added, Tries, Next Try |
| A22 | Load → fetch results of One Case (`data/LoadConsole.tsx`) | Form (it is the search) | Server | a few | unchanged | left out: a few rows of one search |

#### The case page (`components/case`, `workflow`, `claim`)

| # | List | Search today | Data | Usual size (dev) | Search in this row | Sort in this row (server) |
|---|---|---|---|---|---|---|
| P1 | Parties (`case/Parties.tsx`) | none | Full | average 8, 99% under 59, **largest 1,855** | **R4** in the browser | left out: the court's numbering (role, then party number) is the meaning; the search finds a name |
| P2 | Advocates (`case/Parties.tsx`) | none | Full | average 2, largest 24 | **R4** the same field as P1 | left out: a few, by side |
| P3 | Hearings (`case/Hearings.tsx`) | none | Server, 50 a page | average 7, largest 161 | **R4** server `q` | **R4** dir: Newest First (d) or Oldest First |
| P4 | Listings (`case/Hearings.tsx`) | none | Server, 50 a page | tens | **R4** server `q` | **R4** dir: Newest First (d) or Oldest First |
| P5 | Orders tab (`case/Orders.tsx`) | none | Server, 50 a page | average 5.5, largest 134 | **R4** server `q` | **R4** Order Date (d, Newest First), Order Number |
| P6 | Case details modal → Orders (`claim/OrderRow.tsx`) | none | Server, 50 a page | as P5 | **R4** the same `q` as P5 | **R4** as P5 |
| P7 | Documents, each group (`case/Documents.tsx`) | none | Server, 50 a page per group | average 5, largest 134 | **R4** server `q` | **R4** Date (d, Newest First), Name, Type, Uploaded On |
| P8 | Notes tab (`case/Notes.tsx`) | none | Server, 50 a page | a few, long cases 100+ | **R4** server `q` (decision 25) | **R4** dir: Oldest First (d) or Newest First |
| P9 | Remarks panel → Remarks (`case/Remarks.tsx`) | none | Server, 50 at a time | a few, long cases 100+ | **R4** server `q` | **R4** dir through the existing `order`: Newest First (d) or Oldest First |
| P10 | Remarks panel → Notes (`case/Remarks.tsx`) | none | Server, 50 at a time | as P8 | **R4** the same `q` as P8 | **R4** dir, as P8 |
| P11 | Timeline (`case/Timeline.tsx`) | none | Server, 50 a page | average 10, largest 271 | **R4** server `q`, label and date only | left out: the owner's own example; newest first is its meaning |
| P12 | Custody tab → Movement (`workflow/CustodyTab.tsx`) | none | Server, 50 a page | a few, long cases 100+ | **R4** the same `q` as P9 | **R4** dir through the existing `order`: Oldest First (d) or Newest First |

#### Left without search or sort (62)

Each of these is one of three things:
- a summary card of the first few rows that links to a full list which has search and sort;
- a list bounded at a few rows;
- a list read in date order, where a word search or another order would help nobody.

| Where | Lists | Usual size | Reason |
|---|---|---|---|
| `admin/Tickets.tsx` | a ticket's documents | 1-5 | bounded |
| `admin/UserDetail.tsx` | the exit dialog's hand-over table; a membership's documents | tens; 1-5 | a confirmation read in full before Exit; bounded |
| `admin/UserDetails.tsx` | Offices cards; Activity (latest 20) | 1-5; 20 | bounded; Activity links to the Audit Log |
| `admin/UserTypes.tsx` | the user-type cards | about 10 | bounded |
| `audit/BeforeAfter.tsx`, `audit/AuditEntry.tsx` | the fields of one entry; its links | up to 30; a few | one record |
| `case/Details.tsx`, `case/Links.tsx`, `case/Overview.tsx`, `case/OwnershipCard.tsx` ×2, `case/Rail.tsx`, `case/Notes.tsx` (a note's attachments) | facts, linked cases (largest 2), recent activity (4), departments, the journey (4), attachments | a few each | bounded |
| `workflow/CaseAlerts.tsx`, `workflow/CustodyTab.tsx` (stage history), `workflow/DraftsPanel.tsx` ×2, `nextdates/CaseNextDate.tsx` | a case's alerts, stages, drafts (at most `note_drafts_max`), next dates | a few each | bounded |
| `claim/CaseModal.tsx`, `claim/WhyBox.tsx` | links; the match signals | a few | bounded |
| `assistant/Assistant.tsx` ×2 | an answer's sources and related orders | up to 10 | bounded; the citation number is the order |
| `calendar/DayAgenda.tsx` | one day of My Calendar | a few | one day |
| `causelist/ListStrip.tsx` | the day's lists | up to about 30 | the page's Bench and Search Words narrow it |
| `dashboard/Headline.tsx` ×2; `dashboard/Blocks.tsx`: upcoming hearings, cases with me, recent orders, custody, own cases, attention, alerts, overdue, tickets by kind, tickets by department | summary cards | up to 5-10 each | each links to its full list |
| `data/Health.tsx`: Calls by User, Queue by Kind, Daily Cycle, Document Text and five bullet lists | system figures | up to 10 each | bounded; row 173 lays them out again |
| `data/LoadConsole.tsx`: Work Left, Latest Failures (20), Month by Month, a month's days | system figures | up to 24 | bounded, read in date order |
| `data/Discovery.tsx`: Work Waiting, Latest Problems (20) | system figures | up to 20 | bounded |
| `profile/Profile.tsx` | devices | a few | bounded |
| `system/ApiPanel.tsx` ×2, `system/Console.tsx` ×3, `system/SystemHealth.tsx` | an API's days and recent calls, request fields, services | up to 30 | bounded, read in time order |
| `admin/mapping/Scoring.tsx` ×2 | M8, M9 | — | above |

The other 12 lists left without sort, though most gain search, are C13, A3, A5, A6, A7, A10, A14, A16, A22, P1, P2 and
P11. Each has its reason in the tables above.

#### Not data lists (28)

- **Navigation:** `shell/NavTree.tsx` ×2, the `shell/PortalShell.tsx` office switcher, the `ui/layout.tsx` breadcrumb
  and settings menu, `admin/UserTypes.tsx` Jump To.
- **Kit internals:** the `ui/OfficePicker.tsx` list (it has its own search), the `ui/overlays.tsx` menu,
  `ui/feedback.tsx` signals, `filters/FilterChips.tsx` chips.
- **The two calendar grids:** `calendar/MonthGrid.tsx`, `calendar/DepartmentHearings.tsx`.
- **Static or message text:**
  - `auth/AuthFrame.tsx`, `auth/WelcomeForms.tsx`;
  - the `admin/Offices.tsx` in-use counts, the `admin/Users.tsx` membership lines ×2;
  - `data/LoadConsole.tsx` ×2, the `reports/ReportView.tsx` facts;
  - `system/Console.tsx` ×7 outlines and steps;
  - the `dashboard/Blocks.tsx` "no dashboard" text.

### What this row does not cover

- **No change to who may see or do anything.** There is no new write and no audit row. Searching and sorting are reads.
  List reads are not audited today, and the Audit Log's own search is never audited.
- **No NAPIX call, and nothing sent to SourceTrace.** Every search and sort runs in the portal's own database or in the
  browser.
- **No migration**, and no new table, column or index.
- **Forms kept:** the Search page, the Cause List page, the Audit Log filters and the Data Collection Work Items keep
  their filter forms.
- **Row 165** keeps its office change on keyword, name-pattern and watchlist rows. Decision 14 settles its search half.

## Decisions

### A. One search for lists

1. **Two kinds of list search, by how the list is filtered today.**
   - **Lists with a filter form** (FilterBar, FilterCard, the Users toolbar) already have a search: their Words field.
     - They keep "applied with Search or Enter", because a search there combines with dates and selects and must not
       run half-typed.
     - This row puts the Words field on the first row everywhere (decision 17).
     - They gain the no-match state and the count rule.
   - **Every other list gets the kit's instant search** (decision 2), which filters while typing.
   - Alternative: replace the filter forms with the instant field. Refused: a debounced search next to dates and
     selects would send a request per keystroke on the largest lists and reset the page under the user.
2. **The kit search: `ListSearch` in a `ListToolbar`.** Both live in `components/ui/listSearch.tsx`, with styles in
   `listSearch.module.css`, and are exported from `components/ui`.
   - **`ListToolbar`** is the list's one toolbar line, at the head of its card or above its `ScrollBox`. Its props are
     `{ search, sort?, count?, children? }`.
     - Order on the line: the search field, then the sort (decision 33), then the list's own controls (switches,
       segmented choices, secondary buttons), then the count, pushed right (`margin-inline-start: auto`).
     - Everything sits on the 36 px control line (field-row rule).
     - Below about 1,000 px it wraps on the control line. On phones it stacks: search full width, then sort, then
       controls, then count.
   - **`ListSearch`**: `{ label, placeholder, value, onChange, minChars?, busy? }`.
     - A `type="search"` field in a `role="search"` wrapper named by `label`.
     - The label is visually hidden and the placeholder shows it (the Users toolbar rule, `portal-ui-polish-2` decision
       27). The minimum length is a tooltip.
     - **Width:** at least 240 px, growing to 360 px; full width on phones.
     - **The clear button** ("Clear Search", an icon button with that accessible name) appears inside the field when it
       holds text. **Escape** also clears. Both return focus to the field.
     - The browser's own cancel button is hidden (`::-webkit-search-cancel-button { appearance: none }`), so every
       browser shows the same control.
     - `busy` shows the kit's small spinner at the end of the field while a server search runs. Nothing else moves.
   - **Labels are in Title Case** ("Search Codes", "Search Tickets", "Search Parties and Advocates"). Placeholders and
     hints are in sentence case ("Code or part of a code"). `labels.test.ts` covers the new keys.
   - `RuleToolbar` (`mapping/common.tsx`) becomes a thin wrapper over `ListToolbar`, so the Mapping tabs keep their
     look.
   - Alternative: a bare `TextField type="search"` per list, as Mapping and the user-type page have today. Refused:
     that is how the lists drifted apart; the clear button, debounce, counts and empty states differ on every page.
3. **Server-side `q` for paged lists. The browser filters only lists it holds in full.**
   - **Server:** every list the API pages (by offset, cursor or "newest n") gains `q`. The browser never filters one
     page of a paged list, because that would hide matches on the other pages.
   - **Browser:** lists the API answers whole and that are bounded by nature. The inventory marks each one.
   - **The browser match** is `matchesWords(query, ...texts)` in `lib/listSearch.ts`. It replaces `matches` in
     `mapping/common.tsx`.
     - The query is split on white space, and every word must appear in at least one of the texts.
     - Case and accents are ignored (`toLocaleLowerCase` after NFD, with combining marks removed).
     - Each list passes the texts its columns show, with dates in the portal's format ("12 Oct 2025").
4. **Server searches wait 300 ms; browser searches do not wait.**
   - **Server:** `useDebounced(value, 300)` in `lib/useDebounced.ts` (the `useSettled` of `CounselCodes.tsx`, moved to
     `lib`).
     - **Enter** sends at once.
     - A query shorter than the minimum (decision 6) is not sent, and the tooltip says "Type at least 2 letters."
   - **Browser:** the filter runs on every keystroke through React's `useDeferredValue`, so typing stays smooth even
     over 1,855 parties.
   - The query key includes the settled `q`, so TanStack Query cancels a request that has been overtaken.
5. **The search and the sort are kept in the address where the list already keeps its filters; otherwise in the
   component.**
   - `useListState({ mode: "url" | "local", sortKeys, defaultLabel, minChars })` in `lib/useListState.ts` replaces the
     earlier `useListSearch`. It returns:
     - `q`, `setQ`, `applied` and `clear` for the search;
     - `sort`, `setSort` and `resetSort` for the sort (decision 35).
   - **URL mode** reads `q`, `sort` and `dir` from the page's params. Once the value settles, it writes them with
     `router.replace` (no history entry per keystroke) and drops `offset`.
     - **The filter-form lists** (C1-C12) keep `q`, `sort` and `dir` in the address, as they keep their filters.
     - **The other lists in URL mode:**
       - Admin Tickets (its status is in the address);
       - Users, the Audit Log and the Data Collection Work Items (their filters are);
       - the View Cause List modal, as `vq` beside its `view` and `vtab`. The page's own `q` is the Cause List's
         Search Words.
   - **Local mode** everywhere else:
     - the Mapping tabs (today's behaviour), Designations, Offices and the function lists;
     - Conversations, the case-page tabs, Duplicates and Court Calls;
     - the court search answer;
     - the report tables: several sections share one page, and one address cannot hold a sort per section
       cleanly;
     - any second list on a page whose address already holds a `q` for its main list (the tracking summary above
       Pending Action).
   - **The report find** is in the address as `find`. `reportParams` never sends it to the API or puts it in an
     export.
6. **One validation for list `q`, on the server and in the browser.**
   - The query is trimmed. It must be at least **2** characters (codes such as "SC" and "GA" are two letters) and at
     most **100**. At most 8 words are used.
   - The case lists keep their own rule (3 characters, `case_filters.MIN_QUERY`).
   - A bad value answers **400 `bad_q`** with the message, through the API's `detail()`.
   - LIKE wildcards in the query match literally (`case_filters.like_escape`).
   - **A date also matches the list's date columns.** A query that is exactly a date matches rows whose date columns
     fall on that day (in IST for timestamps). The accepted forms:
     - "12 Oct 2025", the portal's own;
     - `12-10-2025`, `12/10/2025` and `12.10.2025`;
     - `2025-10-12`.

     A year on its own ("2025") is a word, not a date.
7. **The count: "12 of 340".**
   - **`ListCount`** (kit) takes `{ shown, total?, noun }` and has `aria-live="polite"`. It reads:
     - not searching: "340 codes";
     - searching, with the total before the search known: **"12 of 340 codes"**;
     - searching, without it: "12 codes match" (the FilterBar's line).
   - **`total_all`:** every API that gains `q` in this row also returns it. It is the count of what the caller sees in
     that list, with the same tab or status but without `q`. It is `null` when no `q` was sent, and `total` is then
     that number.
   - The existing `CountLine` (inbox) becomes `ListCount`.
   - The filter-form lists show "n of m" where the page already holds m (the inbox counts, as today), and "n cases
     match" elsewhere.
   - **The Audit Log shows no count.** It is cursor-paged with no total, by design (`audit-screens`).
   - Alternative: a second request for the count before the search. Refused: `total_all` costs one count in the same
     request, over a set already narrowed to one case, one caller or one tab.
8. **The no-match state: `NoMatches`** (kit). It shows instead of the list's own empty state whenever a search is set
   and nothing matches.
   - The text is **"No matches for “ram”."** (`T.list.noMatches(q)`). A **Clear Search** button (secondary, small)
     clears the search and returns focus to the field.
   - The filter-form lists say "No cases match these filters.", with the Clear All their chip strip already has.
   - The list's own empty state ("Every code seen in the cause lists is mapped.") still shows when the list is empty
     with no search set.
   - **When the search box shows:**
     - always, when a search is set;
     - otherwise when the list holds more than **10** rows. Browser lists count their own rows; server lists use the
       `total` of the answer without a search.

     The constant is `LIST_SEARCH_FROM = 10` in `lib/listSearch.ts`.
   - Alternative: a box on every list, however short. Refused: a search box over three rows is clutter, and the
     owner's own example of an exception is a five-row card.

### B. Recommended From Cause Lists: every code (question 2)

9. **Every unmapped code, paged by 100 inside the panel's scroll box, most entries first.**
   - **A new read, `GET /admin/counsel-codes/unmapped/page`** (API), returns `{ items, total, matched, next_cursor }`:
     - `total` counts every unmapped code;
     - `matched` counts those matching `q`.
   - **The default order stays:** entries descending, then the code. Decision 39 adds the other sorts.
   - **Keyset paging:** the last row's sort value and code go back as an opaque `cursor` (base64url JSON, decision 34).
     When a person maps a code between pages, the next page neither repeats nor skips a code, which offset paging
     would.
   - The existing `GET /admin/counsel-codes/unmapped` stays unchanged for the CLI and older clients. The portal stops
     calling it.
   - Alternative: headers (`X-Total-Count`, `X-Next-Cursor`) on the existing path. Refused: three values outside the
     response model, which the API tests and the OpenAPI document check.
   - Alternative: one answer with all 1,066 codes. Refused: each code carries its own Office Picker and Map form, and
     1,066 of them at once make a slow first paint for a list read from the top.
10. **More codes load inside the box, never moving the page.**
    - The panel's list sits in the kit `ScrollBox` (row 172). It replaces `.scrollBox` in `mapping.module.css`, with
      the same `min(60vh, 560px)`, and is labelled "Recommended From Cause Lists".
    - **The next page loads when the end of the list comes within 200 px of the box's bottom.** An
      `IntersectionObserver` with the `ScrollBox` as its root triggers it, through `useInfiniteQuery` with
      `next_cursor`.
    - **"Show 100 More"** (secondary, small) stays at the end of the list, for the keyboard and wherever the observer
      is missing.
      - Beside it: **"Showing 300 of 1,066"**.
      - At the end it reads "Showing all 1,066".
    - Pages are joined by code, so a code is never listed twice if entries change between pages.
    - **Virtualisation is refused:**
      - it would unmount rows being edited (an open Office Picker, a typed choice);
      - it would break the browser's find-in-page and the keyboard order through the list;
      - 1,066 rows loaded in pages of 100 do not need it.
11. **The panel's toolbar, count, search and sort.**
    - Under the notice "Nothing is mapped automatically." sits one `ListToolbar` with:
      - **Search Recommended Codes** (placeholder "Code or part of a code"), server `q`, 300 ms;
      - **Sort By** (decision 39);
      - the count, which replaces "n to review": **"1,066 codes not mapped"**, or **"12 of 1,066 codes"** while
        searching.
    - **The search matches the code only, ignoring spaces and punctuation:** "ga assam" finds "GA, ASSAM", and "DY SGI"
      finds "DY.S.G.I.".
    - No matches: "No matches for “…”." with Clear Search. Empty with no search set: the existing "Every code seen in
      the cause lists is mapped."
    - **The row layout stays as the owner approved it:**
      - one row per code from 860 px: Code | entries and last seen | example case | Office and Map;
      - "Partly matches" or an error goes on a full-width line under the row;
      - stacked below 860 px.

      `.recList` in `mapping.module.css` keeps its grid; only `.scrollBox` goes.
    - **Map** posts `POST /admin/counsel-codes`, as today.
      - The code then leaves every loaded page, and `total` and `matched` drop by one in the cache, with no reload.
      - A 409 (someone mapped it in the meantime) reloads the panel, as `conflictAware` does today.
12. **The scope rule stays.**
    - Every holder of `admin.counsel_codes` sees every unmapped printed code, as today. These are court data, printed in
      public cause lists.
    - Each code's partial matches stay limited to the mappings in the caller's office subtree
      (`matching_rules.counsel_code_scope`, `partial-code-match` decision 16).
    - The example case links to the case page, whose own visibility rule decides what opens.
    - Searching and sorting only narrow or order this set.

### C. Department Mapping and the case lists' search (round 1)

13. **Counsel Codes** keeps its server `q` and gains the kit:
    - `ListToolbar` with Search Codes and Include Deactivated;
    - the count "12 of 340 codes", from the new `total_all` on `GET /admin/counsel-codes`;
    - the no-match state;
    - the kit `ScrollBox`.
14. **Keywords and Name Patterns, and the Watchlist, keep filtering in the browser.**
    - They now use `matchesWords`, the kit toolbar, the count, the no-match state and the kit `ScrollBox`.
    - `GET /admin/keywords`, `/admin/name-patterns` and `/admin/watchlist` answer their whole list, unpaged, and each
      list is bounded by the departments' rules. A server `q` would add a request per keystroke and nothing else.
    - **So row 165's search half is not needed.** This note proposes that row 165 keep only the office change. A server
      `q` becomes worth adding if these lists are ever paged.
15. **Court Search tab.**
    - **Names Searched** gains server `q` on `GET /admin/discovery/terms`, matching the name and the department codes.
      The API pages this list (first 200 today). The toolbar sits above the table.
    - **Cases Found for a name** gains server `q` on `GET /admin/discovery/terms/{id}/cases`, read by
      `case_filters.parse_query` (CNR, reference, case number or words), beside the existing Only select.
16. **Rules with Their Own Weight** filters in the browser, by rule text and office, when it holds more than 10 rows.
17. **The Case inbox's own views show Words on the first row.**
    - `LIST_FILTERS.mine` drops `q` from `more`. Working On, Claimed by Me and Disposed then show **Search Words**
      first, before the quick chips and Stage.
    - These are the lists the owner uses most, and their search was hidden under More Filters.
    - No API change.
18. **Every filter-form list** (C3-C10) shows "No cases match these filters." with Clear All when a filter or Words is
    set and nothing is found, instead of its general empty state. The search engine stays `case_filters.parse_query`
    with `cases.search_vector`, unchanged.

### D. Administration and other pages' search (round 3)

19. **Users and the Audit Log keep their forms.**
    - Users gains `ListCount` ("12 users match" or "340 users"), the no-match state, and a clear button in the Name or
      E-mail field.
    - The Audit Log gains the no-match state only.
20. **The Offices tree** filters in the browser on the office name and code.
    - A matching office shows with its parents, so its place in the tree stays visible, and every matched branch opens.
    - The match is marked with `<mark>`.
    - The count reads "12 of 340 offices".
21. **Search the Court answers** get a browser filter, **Search These Results**, over the results and the rows not
    stored. Narrowing an answer must not send the court search again: each court search spends the hourly NAPIX
    allowance.
22. **Reports.** One **Find in This Report** field filters every section's rows in the browser, on the cell texts as
    shown. While a search is set:
    - each section shows "12 of 340 rows";
    - the totals row is hidden, with the line "Totals cover the whole report. Clear the search to see them.", because
      totals of all rows under filtered rows would mislead;
    - the Excel and PDF downloads stay the whole report, with their audit unchanged.
23. **The rest of round 3** follows the general rules:
    - **in the browser:** Designations, the two function lists, the Department Hearings agenda, the two tracking-summary
      tables, By Department;
    - **server `q`:** Admin Tickets and Conversations;
    - **the existing `q` of the entries API:** the View Cause List modal (as `vq` in the address).
24. **Data Collection gets search and sort only where rows 172-174 leave a list without them.** These parts are built
    in round 3 once rows 173 and 174 are merged; otherwise they move to round 4.
    - **Duplicates:**
      - server `q`, read by `case_filters.parse_query`, matching either case of a row (for Needs Review, either case
        the review names);
      - its toolbar sits at the head of the table's card, under the tab's toolbar line (Updated n s ago, Scan Now).
    - **Court Calls:** a free-text search would match nothing a person reads (times, codes and counts). Instead, its
      toolbar line gains two filters, both sent as the endpoint's existing parameters, with no API change:
      - **Court Service**, the 17 plain names of row 173, sent as `api`;
      - **Failed Only**, sent as `ok`.
    - **A request's items** (row 174's side panel): server `q` on `GET /admin/data-load/requests/{id}`, read by
      `case_filters.parse_query` against each item's case.
    - Nothing else in Data Collection changes. The remaining lists are bounded (see the inventory).

### E. The case page's search (round 4)

25. **Each paged tab gains server `q` over the columns it shows. Visibility is applied before the search.**

    | Tab | Endpoint | Words match | Dates match |
    |---|---|---|---|
    | Hearings | `GET /cases/{ref}/hearings` | purpose, bench, judge designation, list type, business text, short order text | hearing date, business date, next date |
    | Listings | `GET /cases/{ref}/listings` | bench label, list type, court number, printed serial, section, remarks | list date |
    | Orders, and the modal's Orders | `GET /cases/{ref}/orders` | order number, kind, order details, judge | order date |
    | Documents | `GET /cases/{ref}/documents` | description, file name, type label, reference | document date, upload date |
    | Notes, and the Remarks panel's Notes | `GET /cases/{ref}/notes` | body, kind label, author name, reference | written date |
    | Remarks panel's Remarks, and the Custody tab's Movement | `GET /cases/{ref}/custody` | holder office name and code, holder name, designation, reason label, pending action label, and the remark **only when `remarks_shown`** | start date, due date |
    | Timeline | `GET /cases/{ref}/timeline` | the event's label only | event date |

    - **Notes:** only notes the caller may read are searched (per-note visibility, and the private-record rule of
      `cases.view_private_all`). A hidden note whose body holds the word is not listed, and not counted in `total` or
      `total_all`.
    - **Documents:** the same, by per-document visibility.
    - **Custody:** a remark the caller may not read is never matched, so the search cannot be used to probe what a
      hidden remark says.
    - **Timeline:** the payload is never searched.
      - The one-line details are built in the browser from known keys (`lib/timeline.ts`).
      - The payload can hold values the screen never shows, and matching them would reveal them.
    - **Orders:**
      - `q` here matches the columns shown, not the PDF's text;
      - the Orders tab adds the link **"Search Inside These Orders"** to `/search?tab=documents&case=…`, the existing
        content search over order text.
    - **Parties and Advocates** filter in the browser (name, role or side, code), with one **Search Parties and
      Advocates** field over both tables. The API answers both whole. This serves the case with 1,855 parties.
    - A `q` on a case the caller cannot see gets the same answer as the request without `q` (the existing 404).
    - The search box sits on the tab's toolbar line, next to the existing controls (Show Corrections, Include Archived,
      the kind select). Each new search goes back to the first page.

### F. Visibility

26. **A search or a sort never widens what a caller sees.**
    - **On the server:**
      - every `q` condition is ANDed with the list's existing conditions: `visible_case_condition`, the office scope,
        per-note and per-document visibility, the caller's own conversations, the ticket panel's scope;
      - `total_all` is counted under the same conditions;
      - a sort only reorders the rows those conditions already allow (decision 36).
    - **In the browser,** a filter or a sort only acts on rows the API already returned.
    - Each server `q` and `sort` has a pytest showing that it cannot reveal another department's case, note, document,
      remark, ticket or conversation (Tests).

### G. Sorting

27. **The kit's sortable header** (`components/ui/data.tsx`, a new `SortHeader` also exported for hand-written tables).
    - **The column declares it:** `Column.sort?: { key: string; type: "text" | "number" | "date" | "caseNo"; firstDir?:
      "asc" | "desc"; value?: (row) => Sortable; labels?: [asc: string, desc: string] }`.
    - **`DataTable` takes:**
      - `sort?: { key, dir } | null` (null is the list's default order);
      - `onSort?(next)`;
      - `defaultSort?: { key, dir }`, when the default order is one of the columns.
    - **The header:**
      - a sortable header's text is a `<button type="button">` inside the `<th>`, keeping its Title Case text;
      - an arrow icon (`aria-hidden`) shows ascending (up) or descending (down) on the sorted column;
      - a faint two-way arrow shows on other sortable headers on hover and focus only, so the header row stays calm;
      - the button is reached by Tab and pressed with Enter or Space.
    - **`aria-sort`** (`ascending` or `descending`) is set on the sorted column's `<th>` only, as the ARIA pattern for
      sortable tables asks. The default column carries it when the list is in its default order.
    - **Clicks cycle through three states:**
      1. the column's first direction;
      2. the other direction;
      3. the list's default order (sort is cleared).

      The first direction is ascending for text and case numbers, descending for numbers and past dates ("Newest
      First"), and ascending for dates ahead (Next Hearing, Due Date: "Earliest First"). A column can set `firstDir`.
    - **Pressing a header never moves focus.** The button keeps focus while the rows change, and a visually hidden live
      region says "Sorted by Next Hearing, Earliest First".
    - **Hand-written tables** use the same `SortHeader`: the report tables.
28. **Exactly one sorted column at a time.**
    - Each list's own second keys, and the unique tie-breaker of decision 31, decide the order among equal values. For
      example, a case-number sort breaks ties by id.
    - No list in the inventory needs a second chosen key. Its useful second orders are already fixed in each list's
      default (for example due date, then next hearing).
    - Alternative: Shift-click for more columns. Refused: no use was found, it cannot be discovered on a touch screen,
      and it needs an index per combination on the large tables.
29. **Direction words by type, all in Title Case,** shown in the Sort By select, the live region and the toolbar's
    order line:
    - text: "A to Z" or "Z to A";
    - number: "Highest First" or "Lowest First";
    - past date: "Newest First" or "Oldest First";
    - date ahead: "Earliest First" or "Latest First";
    - case number: "In Number Order" or "Reverse Number Order".

    A column may name its own pair (Recommended codes: "Most First" or "Fewest First").
30. **Sorting is offered where an order chosen by the reader helps, and left out where the order is the meaning.**
    - **42 lists gain sorting** (inventory): 7 in Mapping, 12 case lists, 14 on other pages and 9 on the case page.
    - **The 74 left out are of five kinds:**
      - **court order:** the cause list, the View Cause List modal, the parties' numbering. The court calls items in
        that order, and another order would mislead;
      - **ranked or set orders:** the functions catalogue, scoring versions, an answer's citations;
      - **tree and agenda:** the Offices tree, the Department Hearings agenda;
      - **the timeline:** the owner's own example;
      - **lists of a few rows or summary cards** (the 62 of the bounded table).
    - **Direction only** (Newest First or Oldest First) where a list is a trail read in time:
      - the case tabs: Hearings, Listings, Notes, Remarks and Movement;
      - Duplicates;
      - and the two cursor lists, the Audit Log and Court Calls (decision 34).
31. **Every sorted server list ends its order with a unique key, so paging never repeats or skips a row.**
    - The service appends the table's `id` (or the list's natural unique key: `code` for the unmapped codes, `seq_no`
      for notes and custody legs) after the chosen key, **in the same direction**.
    - The fixed default orders that lack one gain it in the same round as their list's sort:
      - `Case.id` in Claimed, Recommended and Pool;
      - `OwnershipTransfer.id` in Transfers;
      - `CaseHearing.id` in Hearings;
      - `Order.id` in Orders;
      - `Document.id` in Documents;
      - `CauselistEntry.id` in Listings;
      - the term `id` in Names Searched.
32. **Server sort through an allow-list: `sort=<key>&dir=asc|desc`.** The module is `services/list_sort.py`
    (Services).
    - Each list declares its keys once, as a `SortSpec`: a dict of key → SQL expressions, type and first direction, the
      default order and the tie-breaker.
    - **The request only picks a key name from that dict.** A column name, an expression or SQL in `sort` is never read
      as one. Any value outside the dict answers **400 `bad_sort`**, with the allowed keys in the body.
    - `dir` with no `sort` answers `bad_sort`. `sort` with no `dir` takes the key's first direction.
    - **Blanks go last in both directions:** `asc().nulls_last()` and `desc().nulls_last()`, always written out.
    - **Text compares** as `lower(col)`, then `col`, under the database's `en_US.utf8` collation, so "Revenue" and
      "revenue" sit together and Title Case names order as people expect.
    - Dates and numbers compare by their types, never as text.
    - **The portal checks a sort from the address against the list's keys before sending it.** An unknown key (an old
      link) falls back to the default order quietly, with no 400 banner.
33. **The phone "Sort By" select, and lists that are not tables.**
    - **`ListSort`** (kit) is a **Sort By** select plus a direction button, on the list's `ListToolbar` beside the search.
      - The select's options are "Default (Newest First)", naming the list's default order, then each sortable column.
      - The button's accessible name is the current direction ("Earliest First"). Pressing it swaps the direction.
      - Choosing "Default" hides the button.
    - **When it shows:**
      - for a `DataTable`, whenever the table is drawn as cards: below 820 px, or wider when `fitTable` sets
        `data-stacked`. `DataTable` reports this through a new `onStackedChange(stacked)`, and `useListState` hands it
        to the toolbar;
      - always, for lists that are not tables: Recommended codes, Notes, the Remarks panel, the Orders lists and
        Conversations.
    - It drives the same `sort` state as the headers, so turning the phone round keeps the sort.
34. **Sort with keyset or cursor paging: the cursor carries the sort.**
    - **Recommended codes:** the cursor holds `[sort, dir, value, code]`. The server compares
      `(value, code)` in the chosen direction, with blanks after values (`last_listed` is blank for codes seen only in
      case details).
      - A cursor whose sort or direction differs from the request answers 400 `bad_cursor`.
      - The portal starts a new infinite query whenever the sort changes, because the query key includes it.
    - **The Audit Log and Court Calls are keyset lists over `(created_at, id)` and `(called_at, id)`.** They allow
      **only the direction** (`dir=desc`, the default, or `asc`):
      - the cursor gains the direction and compares with `<` or `>` to match;
      - `ix_audit_log_created_at` and `ix_napix_call_log_called_at` serve both directions (Context).
      - Sorting these by person, action or service is refused: each would need its own cursor shape and an index on
        tables that grow without end, for orders nobody reads the log in. The filters already narrow by person,
        action and service.
    - **Remarks and Notes in the panel** page by offset with `useInfiniteQuery`. A change of direction starts the query
      again.
35. **Defaults and memory.**
    - **Each list keeps its current order as its default** and says so. On the toolbar, next to the count, an order
      line reads either:
      - "Order: Newest First" in the default; or
      - "Sorted by Next Hearing, Earliest First", with a small **Default Order** button that clears the sort.

      The default's name is written per list, for example:
      - "Your Due Date First" (Working On);
      - "Best Match First" (Recommended, the searches);
      - "Most Entries First" (Recommended codes);
      - "Runs First" (Work Items);
      - "Office Order" (Keywords).
    - **The sort follows decision 5:** in the address (`sort`, `dir`) wherever the list keeps its search and filters,
      so a shared link or Back keeps it; local otherwise.
      - FilterBar's **Clear All keeps the sort.** A sort is not a filter.
      - A new sort goes back to the first page.
    - **Browser sorts** use the same comparators as the server, so a browser list and a server list order the same
      values the same way:
      - `compareText`: `Intl.Collator("en-IN", { sensitivity: "base", numeric: true })`;
      - `compareNumber`;
      - `compareDate`: ISO strings compared as dates;
      - `compareCaseNumbers` (decision 37);
      - all in `lib/sort.ts`, blanks last in both directions.

      `Array.prototype.sort` is stable, so equal values keep the API's order.
36. **Sorting never reveals a value the caller cannot see.**
    - A sort key is offered only on a column the list shows to everyone who can read the list.
    - No list sorts by note text, by a remark (shown only to some), or by any hidden column. Ordering by a hidden value
      would leak it, through where a row lands.
    - The sort is applied to the rows the visibility conditions already allow, and `total` and `total_all` do not
      change with it.
37. **Case numbers sort by type, then number, then year, never as plain text.** "WP(C) 9/2025" comes before
    "WP(C) 10/2025".
    - **On the server,** the `case_no` key is:
      1. `compact_sql(coalesce(case_types.short_name, cases.case_type_text))`, the case search's own compact type
         (`case_filters.compact_sql`, upper case without white space);
      2. then `cases.reg_no`;
      3. then `cases.reg_year`;
      4. then `cases.id`.

      Blanks are last, so a case with no registration number (only a filing number, or a provisional case) comes after
      the numbered ones.
    - **In the browser,** `compareCaseNumbers(a, b)` parses `case_no_text` with the case search's pattern, ported from
      `case_filters.NUMBER_RE` (`<type> <no>/<year>` or `<type>/<no>/<year>`):
      - the type is compared as the compact upper-case text, then the number as a number, then the year;
      - text that does not parse comes after parsed numbers, in natural text order;
      - blanks come last.
    - **Measured:** the server key takes 36 ms over all 59,872 cases at offset 5,000 (Context). No index is needed.
38. **The sorts offered on the large tables stay fast with today's indexes** (Context table):
    - `cases`: next hearing (`ix_cases_next_hearing_date`), case number, year, claimed on (narrowed by department
      first), best score;
    - `audit_log` and `napix_call_log`: direction only, on their time indexes;
    - `fetch_queue`: added on, tries, next try, priority (`ix_fetch_queue_priority`);
    - `orders`: only within a case;
    - `causelist_entries`: no sort.

    **No migration.** If a later measurement passes 500 ms for a page, the index belongs to its own row and takes the
    next free migration number after main's highest (0027 today; rows 157 and 169 both plan 0028).
39. **Recommended From Cause Lists sorts by Entries, Code and Last Seen.**
    - **Entries** (the default, "Most First", then code A to Z).
    - **Code** ("A to Z" or "Z to A").
    - **Last Seen** ("Newest First" or "Oldest First", blanks last).

    The sort runs in Python over the aggregate (about 1,066 rows, under 1 ms), with the code as the tie-breaker. It
    goes in the panel's toolbar as a `ListSort`, because the panel is a list, not a table. It is local, like the
    panel's search.

### H. Rounds

40. **Four rounds, each with its own branch, review and report.** Sorting adds 29 endpoints and the kit header to the
    earlier three rounds, which is too much for three reviews.
    - **Round 1 (row 175, `feature/list-search`), after row 172:**
      - the kit: `ListToolbar`, `ListSearch`, `ListCount`, `NoMatches`, `SortHeader` in `DataTable`, `ListSort`,
        `lib/sort.ts`, `useListState`, `useDebounced` (decisions 1-8, 27-29, 32-37);
      - the backend helpers `services/list_search.py` and `services/list_sort.py`;
      - the full Recommended From Cause Lists with its search and sort (9-12, 39);
      - the Department Mapping lists' search and sort (13-16);
      - the case lists' search consistency (17-18).
    - **Round 2 (new row at approval, `list-search-case-lists`):** sorting on the 12 case lists (C1-C12): the server
      `case_no` key, the tie-breakers, `sort` and `dir` in the FilterBar address.
    - **Round 3 (new row at approval, `list-search-admin`):** search and sort on Administration and the other pages
      (decisions 19-24). Its Data Collection part needs rows 173 and 174 merged.
    - **Round 4 (new row at approval, `list-search-case-page`):** search and sort on the case page (decision 25).
    - The owner's browser check of the four rounds becomes a separate row at approval.

## Data

**No new table, column, index or reference code. No migration.**

- **Every server `q`** runs over a set the list already narrows by an indexed key, so an `ILIKE` over it needs no
  trigram index. Checked in `pg_indexes` on 26 Oct 2026:
  - one case: the `case_id` indexes on `case_hearings`, `causelist_entries`, `orders`, `documents`, `case_notes`,
    `custody_history` and `events`;
  - one caller: `ix_assistant_conversations_user_last`;
  - or a small table: admin tickets, discovery terms, counsel codes.
- **The case-based searches** (term cases, duplicates, request items, the case lists) use `case_filters.parse_query`:
  `cases.ref_no`, `cases.cnr`, the case-number match and the GIN index on `cases.search_vector`, all existing.
- **Every sort offered** is within the timings of the Context table (decision 38).
- **The unmapped-code list** is an aggregate over every current cause-list entry. No index helps it, and it takes about
  200 ms (Context).
- **A later index** belongs to its own row and takes the next free migration number after main's highest (0027 today;
  rows 157 and 169 both plan 0028).
- `docs/schema/schema.md` needs no paragraph.

## Services

None calls NAPIX or SourceTrace. None writes or audits.

- **`services/list_search.py`** (new, round 1), the shared `q` of the lists that are not case lists:
  - `MIN_CHARS = 2`, `MAX_CHARS = 100`, `MAX_WORDS = 8`.
  - `class ListSearchError(ValueError)`, carrying a `code`: `bad_q` or `bad_cursor`; mapped to 400.
  - `@dataclass(frozen=True) class ListQuery: raw: str; words: tuple[str, ...]; day: date | None`.
  - **`parse(q: str | None) -> ListQuery | None`:**
    - trims and checks the length;
    - splits words on white space, keeping punctuation inside a word, so "WP(C)" is one word;
    - reads `day` from the five date forms of decision 6.
  - **`condition(lq, text=[...], dates=[...], timestamps=[...]) -> ColumnElement[bool]`:**
    - each word ORs `coalesce(col, '') ILIKE '%word%' ESCAPE '\'` over the `text` columns;
    - the words are ANDed;
    - with a `day`, it ORs `date_col = day` and `ist_midnight(day) <= ts_col < ist_midnight(day + 1)`
      (`core/clock.py`).
  - Each list names its columns in one place next to its query, so "the columns a person reads" are explicit and
    tested.
- **`services/list_sort.py`** (new, round 1):
  - `class ListSortError(ValueError)`, code `bad_sort`; 400 with `allowed`.
  - `@dataclass(frozen=True) class SortKey: name: str; exprs: tuple[ColumnElement, ...]; type: str; first_dir: str`.
  - `@dataclass(frozen=True) class SortSpec: keys: dict[str, SortKey]; default: tuple[ColumnElement, ...]; tiebreak:
    ColumnElement`.
  - **`parse(spec, sort, dir) -> Sort | None`:** looks the name up in `spec.keys` only, and applies the rules of
    decision 32.
  - **`order_by(spec, sort) -> list[ColumnElement]`:**
    - with no sort: the default order plus the tie-breaker;
    - otherwise: each expression in the direction, `nulls_last()`, then the tie-breaker in the same direction;
    - a text key orders by `lower(expr), expr`.
  - **`case_no_exprs(case=Case)`:** the four expressions of decision 37, through a left join to `case_types`. Shared by
    every case list.
  - A `SortSpec` sits next to each list's query: `inbox.py`, `my_cases.py`, `custody.py`, `alerts.py`,
    `next_dates.py`, `case_search.py`, `documents.py`, `discovery.py`, `tickets.py`, the users router's query,
    `assistant.py`, `data_load.py`, `data_health.py`, `case_detail.py`, `notes.py`.
- **`services/matching.py`** (round 1):
  - **`_unmapped_aggregate(session) -> list[tuple[str, dict]]`:** today's two aggregates, normalisation and merge.
    `unmapped_codes` (the CLI and the old endpoint) is rebuilt on it, with the same signature and output.
  - **`unmapped_page(session, *, q=None, sort="entries", dir=None, limit=100, cursor=None, scope=None) ->
    UnmappedPage(items, total, matched, next_cursor)`:**
    - `total` is all unmapped codes;
    - `q`, validated by `list_search.parse`, keeps codes whose compact form (letters and digits, upper case) contains
      the compact query; `matched` counts those kept;
    - the sort is one of `entries`, `code` or `last_seen` (decision 39);
    - the cursor skips past the row it holds, in the chosen order;
    - `limit` is 1-200;
    - example references and partial matches are worked out **for the page only**: `RuleSet.load` once, then
      `partial_matches` filtered by `scope`, as today.
  - **`encode_cursor` and `decode_cursor`:** a bad cursor, or one from another sort, raises `ListSearchError`
    (`bad_cursor`).
- **Round 1, other services:**
  - `services/matching_rules.py`: `list_counsel_codes` returns `total_all` when `q` is set.
  - `services/discovery.py`:
    - `terms_view(..., q=None, sort=None)`: `list_search.condition` on the term text and the department codes; sorts
      `name`, `last_searched`, `cases_found`;
    - `term_cases(..., q=None, sort=None)`: `case_filters.query_condition(parse_query(q))` on the case; sorts
      `last_found`, `case_no`, `year`;
    - both return `total_all`.
- **Round 2:** each case-list service gains `sort=None` and its `SortSpec`, as the API table lists.
  - `case_search` keeps the rank first when `sort` is unset and words are given, and offers `relevance` only with
    words.
- **Round 3:**
  - `services/tickets.py` `list_tickets(..., q=None, sort=None)`:
    - search: reference, operation, department code and name, target name, requester name; ticket date;
    - sorts: `opened`, `department`, `kind`.
  - `services/assistant.py` `conversations(..., q=None, sort=None)`:
    - search: the title, and the case's number and CNR; the last message date;
    - sorts: `last_message`, `started`, `title`;
    - the caller's own conversations only, as today.
  - `services/data_load.py`: `duplicates(..., q=None, dir=None)` and `request_items(..., q=None, sort=None)`.
  - `services/data_health.py`: `queue_rows(..., sort=None)`, and `calls` with `dir` in its cursor.
  - `services/audit_search.py`: `dir` in its cursor.
  - The users list query: sorts `email`, `name`, `last_login`.
  - Each service that gains `q` returns `total_all`.
- **Round 4:** `case_detail.hearings`, `listings`, `orders` and `timeline` (`q` only); `documents.list_for_case`;
  `notes.list_for_case`; `custody.history`. Each:
  - gains `q=None` (and `sort` or `dir`, as the API table lists);
  - applies the columns of decision 25 after its visibility conditions;
  - returns `total_all`.

  Two more rules in round 4:
  - `custody.history` adds the remark column to the search only when `shows_remark` is true, and keeps its `order`.
  - `timeline` joins `ref_event_type` for the label (`coalesce(timeline_label, label)`) and never reads `payload` in the
    condition.

## API

**Every change is an additive read:**
- an optional `q`;
- optional `sort` and `dir` (`asc` | `desc`), checked against the list's allow-list (400 `bad_sort`);
- `total_all: int | null` in the response where `q` is added (null when no `q` was sent).

Every endpoint keeps its function and its visibility rule. Searching and sorting are not audited.

| Method and path | Function (`Permission`) | Round | New request parameters | Sort keys (**default**) | Response |
|---|---|---|---|---|---|
| `GET /admin/counsel-codes/unmapped/page` (new) | `admin.counsel_codes` | 1 | `q?`, `sort?`, `dir?`, `limit=100` (1-200), `cursor?` | **`entries` desc**, `code`, `last_seen` | `UnmappedCodePageOut {items: [UnmappedCodeOut], total, matched, next_cursor}`; 400 `bad_q`, `bad_sort`, `bad_cursor` |
| `GET /admin/counsel-codes/unmapped` (existing) | `admin.counsel_codes` | — | unchanged | — | unchanged |
| `GET /admin/counsel-codes` | `admin.counsel_codes` | 1 | `q` (existing) | sorted in the browser | `CounselCodeListOut` + `total_all` |
| `GET /admin/discovery/terms` | `admin.keywords` | 1 | `q`, `sort`, `dir` | **`name` asc**, `last_searched`, `cases_found` | + `total_all` |
| `GET /admin/discovery/terms/{id}/cases` | `admin.keywords` | 1 | `q` (case search), `sort`, `dir` | **`last_found` desc**, `case_no`, `year` | + `total_all` |
| `GET /inbox/mine` | as today (`cases.view_scope`) | 2 | `sort`, `dir` | **today's order**, `due`, `next_hearing`, `case_no`, `claimed`, `disposed` (Disposed view) | unchanged |
| `GET /inbox/claimed` | as today | 2 | `sort`, `dir` | **`next_hearing` asc**, `case_no`, `claimed` | unchanged |
| `GET /inbox/recommended` | as today | 2 | `sort`, `dir` | **best match**, `score`, `next_hearing`, `case_no` | unchanged |
| `GET /inbox/pool` | as today | 2 | `sort`, `dir` | **`next_hearing` asc**, `best_score`, `case_no` | unchanged |
| `GET /inbox/transfers` | as today | 2 | `sort`, `dir` | **`requested` desc**, `case_no` | unchanged |
| `GET /custody/held` | as today | 2 | `sort`, `dir` | **`due` asc**, `since`, `case_no` | unchanged |
| `GET /custody/sent` | as today | 2 | `sort`, `dir` | **`sent` desc**, `case_no`, `due` | unchanged |
| `GET /alerts` | as today | 2 | `sort`, `dir` | **`raised` desc**, `due` | unchanged |
| `GET /next-dates/review` | as today | 2 | `sort`, `dir` | **`found` desc**, `next_date`, `case_no` | unchanged |
| `GET /cases`, `GET /cases/search` | `cases.view_scope` or `cases.view_all` | 2 | `sort`, `dir` | **`relevance`** (with words) or **`next_hearing`**, `case_no`, `year` | unchanged |
| `GET /documents/search` | as today | 2 | `sort`, `dir` | **`relevance`**, `date` | unchanged |
| `GET /admin/users` | as today | 3 | `sort`, `dir` | **`email` asc**, `name`, `last_login` | unchanged |
| `GET /admin/tickets` | `admin.tickets` or `users.propose_head` | 3 | `q`, `sort`, `dir` | **`opened` asc**, `department`, `kind` | + `total_all` |
| `GET /audit` | as today (super admin, Auditor) | 3 | `dir` (cursor carries it) | **desc** only, or asc | unchanged |
| `GET /assistant/conversations` | `assistant.use` | 3 | `q`, `sort`, `dir` | **`last_message` desc**, `started`, `title` | + `total_all` |
| `GET /admin/data-load/duplicates` | any of `data_load.READERS` | 3 | `q` (case search), `dir` | **desc** on when | + `total_all` |
| `GET /admin/napix/calls` | as today | 3 | `dir` (cursor carries it) | **desc** only, or asc | unchanged |
| `GET /admin/napix/queue` | as today | 3 | `sort`, `dir` | **`priority`**, `created`, `attempts`, `not_before` | unchanged |
| `GET /admin/data-load/requests/{id}` (row 174) | any of `data_load.READERS` | 3 | `q` (case search), `sort`, `dir` | **as queued**, `case_no`, `state`, `attempts` | + `total_all` |
| `GET /cases/{ref}/hearings`, `/listings` | `cases.view_scope` or `cases.view_all` | 4 | `q`, `dir` | **desc** on date | + `total_all` |
| `GET /cases/{ref}/orders` | `cases.view_scope` or `cases.view_all` | 4 | `q`, `sort`, `dir` | **`date` desc**, `order_no` | + `total_all` |
| `GET /cases/{ref}/timeline` | `cases.view_scope` or `cases.view_all` | 4 | `q` | — (no sort) | + `total_all` |
| `GET /cases/{ref}/documents` | `documents.view` | 4 | `q`, `sort`, `dir` | **`date` desc**, `name`, `type`, `uploaded` | + `total_all` |
| `GET /cases/{ref}/notes` | `cases.view_scope` or `cases.view_all` | 4 | `q`, `dir` | **asc** on `seq_no` | + `total_all` |
| `GET /cases/{ref}/custody` | `cases.view_scope` or `cases.view_all` | 4 | `q` (`order` existing) | **asc**, or desc by `order` | + `total_all` |

- **Used unchanged:**
  - `GET /causelists/{date}/entries?q=` (the View Cause List modal);
  - `GET /admin/napix/calls?api=&ok=` (the Court Calls filters);
  - the endpoints of the lists searched and sorted in the browser.
- `UnmappedCodeOut` is unchanged: `code`, `entries`, `last_listed`, `example_case_ref`, `partial_matches`.
- The frontend types are regenerated (`schema.d.ts`), and `lib/api/types.ts` exports `UnmappedCodePage`.

## Jobs

None.

## Tests

### pytest, round 1

- **`tests/unit/test_list_search_parse.py`:**
  - empty → None;
  - one character → `bad_q`; 101 characters → `bad_q`;
  - words split on white space, at most 8, punctuation kept inside a word;
  - `%` and `_` match literally;
  - each of the five date forms gives `day`; "2025" stays a word.
- **`tests/unit/test_list_sort.py`:**
  - **`test_allow_list_only`:** a key outside the spec, a column name such as `cases.ref_no`, `id; drop table`, an empty
    string, and `dir` without `sort`, each raise `bad_sort` with the allowed keys;
  - `test_first_direction_used_without_dir`;
  - `test_tiebreak_follows_the_direction`;
  - `test_blanks_last_both_directions` (the compiled SQL has `NULLS LAST` on every key);
  - `test_text_keys_order_by_lower_then_value`;
  - `test_case_no_exprs`: the compact type, then `reg_no`, then `reg_year`, then id.
- **`tests/db/test_unmapped_page.py`:**
  - **`test_every_unmapped_code_is_listed`:** a world with 250 printed codes and some codes seen only in case details.
    Walking every cursor yields each unmapped code exactly once, entries descending then code. The count equals `total`
    and `len(unmapped_codes(limit=10_000))`.
  - **`test_every_sort_pages_stably`:** for `entries`, `code` and `last_seen`, each in both directions, walking pages
    of 7 yields every code once, in the order of that sort, with blank `last_seen` last in both directions.
  - `test_q_matches_the_compact_code` ("ga assam" finds "GA, ASSAM"). `matched` counts only matches, and `total` does
    not change.
  - `test_cursor_survives_a_mapping_between_pages`: map a code from page 1; page 2 neither repeats nor skips.
  - `test_cursor_from_another_sort_is_400`.
  - `test_partial_matches_stay_scoped`, under every sort: an EDU administrator sees only EDU partial matches, the super
    admin sees all.
  - `test_requires_admin_counsel_codes` (403); `test_bad_cursor_is_400`; `test_bad_q_is_400`; `test_bad_sort_is_400`.
  - `test_old_endpoint_unchanged`: `GET /admin/counsel-codes/unmapped?limit=100` answers the same body as before the
    refactor.
- **`tests/db/test_api_matching.py`:** `test_counsel_codes_total_all_with_q`.
- **`tests/db/test_discovery_q.py`:**
  - terms `q` matches the name; another department's term never appears for a department administrator, under any
    sort;
  - term cases `q` by CNR, number and words only narrows, and a CNR of a case not found for this name answers nothing;
  - each terms and term-cases sort pages stably (pages of 3);
  - `bad_sort`.
- **`tests/db/test_case_list_q_scope.py`,** parametrised over `/inbox/mine?view=working|claimed|disposed`,
  `/inbox/claimed`, `/inbox/recommended`, `/inbox/pool`, `/inbox/transfers`, `/custody/held`, `/custody/sent`,
  `/alerts`, `/next-dates/review` and `/cases`:
  - with `q` set to another department's case CNR, its number or a party word, that case is not returned;
  - every answer with `q` is a subset of the answer without it.

### pytest, round 2

**`tests/db/test_case_list_sort.py`,** parametrised over every case-list endpoint × each allowed key × both
directions:
- **`test_pages_never_repeat_or_skip`:** walking pages of 7 yields each row once, and the same set as the default order;
- **`test_scope_unchanged_by_sort`:** another department's case never appears under any sort, and `total` equals the
  unsorted `total`;
- **`test_case_no_order`:** "WP(C) 9/2025" before "WP(C) 10/2025"; "WA 1/2024" before "WP(C) 1/2024"; a case with no
  `reg_no` last in both directions;
- `test_bad_sort_400` with the allowed keys;
- `test_relevance_only_with_words`.

### pytest, round 3

- `test_tickets_q_stays_in_scope`: a department administrator searching another department's ticket reference gets
  nothing, and `total_all` equals the total without the search.
- `test_tickets_sort_pages_stably`.
- `test_conversations_q_only_own`: another person's conversation title never matches, under any sort.
- `test_users_sort_pages_stably`, with scope unchanged.
- `test_queue_sort_pages_stably`.
- `test_duplicates_q_matches_either_case`.
- `test_request_items_q_and_sort` (with row 174).
- **`test_audit_cursor_both_directions`:** walking `dir=asc` yields every row oldest first, once each; a cursor from
  `desc` sent with `asc` answers `bad_cursor`.
- `test_calls_cursor_both_directions`, the same.

### pytest, round 4 (`tests/db/test_case_tab_q.py`)

- Each tab's `q` matches each of its columns and its date columns.
- `test_hidden_note_never_matches`: a private note of another office holding the word is not listed, and not counted
  in `total` or `total_all`.
- `test_hidden_document_never_matches`.
- `test_hidden_remark_never_matches`: with `remarks_shown` false, a remark holding the word does not match.
- `test_timeline_payload_not_searched`: a word found only in an event's payload finds nothing.
- `test_q_on_invisible_case_is_404`.
- `test_total_all_is_the_visible_total`.
- `test_case_tab_sorts_page_stably`: Hearings, Listings, Orders, Documents and Notes, both directions, pages of 3.
- `test_custody_order_still_accepted`.

### vitest, round 1

- **`components/ui/listSearch.test.tsx`:**
  - the request waits 300 ms (fake timers), and Enter sends at once;
  - Clear Search and Escape clear the field and return focus to it;
  - the counts: "340 codes", "12 of 340 codes", "12 codes match";
  - `NoMatches` shows the query and its Clear Search;
  - the box is hidden at 10 rows and shown at 11 or with a search set;
  - the native cancel button is hidden.
- **`components/ui/sort.test.tsx`:**
  - **header sort:** a sortable header is a button inside the `th` with its Title Case text; Enter and Space press it;
  - the three-click cycle: first direction by type, then the other direction, then the default;
  - **`aria-sort`** is on the sorted `th` only, and on the default column when no sort is set;
  - the arrow is `aria-hidden`, and the live region names the column and the direction;
  - focus stays on the header button after a sort;
  - **the phone Sort By select:** shown when `onStackedChange(true)` fires or below 820 px; it lists "Default (…)"
    and every sortable column; the direction button swaps the direction and is named by it; it drives the same state
    as the headers;
  - **URL round-trip:** in URL mode, `sort` and `dir` are written with `router.replace`, drop `offset`, are read back on
    load, and Back restores the earlier sort;
  - an unknown key in the address gives the default order and no request with `sort`;
  - Clear All keeps the sort.
- **`lib/sort.test.ts`:**
  - **`compareCaseNumbers`:**
    - "WP(C) 9/2025" < "WP(C) 10/2025";
    - same type and number, earlier year first;
    - "WA 1/2024" < "WP(C) 1/2024";
    - `WP(C)/9/2025` parses as `WP(C) 9/2025`;
    - unparsable text after parsed numbers;
    - blanks last in both directions;
  - `compareText` ignores case and accents and orders numbers inside text naturally;
  - `compareDate` and `compareNumber`, with blanks last;
  - the sort is stable.
- **`lib/listSearch.test.ts`:** every word must match; case and accents are ignored; dates in the portal's format.
- **`components/admin/mapping.test.tsx`:**
  - the Recommended panel:
    - reads `/unmapped/page` and follows `next_cursor`, on Show 100 More and when the observer fires (mocked);
    - shows "1,066 codes not mapped" and "Showing 300 of 1,066";
    - sends `q` after the debounce and shows "12 of 1,066 codes";
    - restarts from the first page with `sort=code` when Sort By changes;
    - Map removes the row from the loaded pages and lowers both counts;
    - shows the no-match state;
    - keeps the one-row layout class;
  - Counsel Codes, Keywords, Watchlist and Rules with Their Own Weight sort in the browser by each header;
  - their counts and no-match states;
  - Court Search terms and cases send `q`, `sort` and `dir`.
- **`components/inbox/inbox.test.tsx`:** Working On, Claimed by Me and Disposed draw Search Words on the first row, not
  inside More Filters. A filtered empty list says "No cases match these filters.".
- **`lib/labels.test.ts`** covers the new labels: Sort By, Default Order, the direction words.

### vitest, rounds 2-4

- **Round 2:** `inbox.test.tsx`, `claim.test.tsx`, `cases-list.test.tsx`, `alerts.test.tsx`, `nextdates.test.tsx`,
  `search.test.tsx`. Each header sends `sort` and `dir` from the address, and the toolbar names the default ("Your
  Due Date First").
- **Round 3:**
  - `admin.test.tsx`: Designations; Tickets with `q` and `sort` in the address; the Offices tree keeps parents; the
    Change Exceptions functions;
  - `userDetails.test.tsx`, `assistant.test.tsx`, `departmentHearings.test.tsx`;
  - `cases-list.test.tsx` (tracking summary sorts);
  - `dashboard.test.tsx`: By Department sorts, and "Not Claimed" stays last;
  - `causelist.test.tsx` (`vq`);
  - `search.test.tsx`: the court answer is narrowed and sorted with no second court request;
  - `reports.test.tsx`: section header sort; Find hides the totals; the downloads stay whole;
  - `audit.test.tsx` (Oldest First);
  - `data.test.tsx`: Duplicates `q`, the Court Calls filters and direction, Work Items sorts.
- **Round 4:**
  - `case.test.tsx`: Parties and Advocates in the browser; Hearings, Listings, Orders, Documents and Timeline send `q`,
    and each sort; the link Search Inside These Orders;
  - `remarks.test.tsx` (direction restarts the list);
  - `workflow.test.tsx` (Movement);
  - `claim.test.tsx` (the modal's Orders).

### uicheck

In `frontend/e2e/uicheck.spec.ts`, at 375, 768 and 1280 px. The fixtures serve 1,066 synthetic codes on
`/admin/counsel-codes/unmapped/page`.

- **Round 1:**
  - "/admin/mapping/codes (Recommended From Cause Lists: 300 of 1,066 loaded)";
  - "/admin/mapping/codes (Recommended: sorted by Code)";
  - "/admin/mapping/codes (Recommended: no matches)";
  - "/admin/mapping/codes (Counsel Codes sorted by Office)", which at 375 px shows the Sort By select;
  - "/admin/mapping/keywords (search typed)";
  - "/inbox/working (Search Words on the first row)".
- **Round 2:**
  - "/inbox/department (sorted by Case Number)";
  - "/claim/pool (sorted by Best Score)";
  - "/search?q=… (sorted by Next Hearing)".
- **Round 3:**
  - "/admin/tickets (search and sort)";
  - "/admin/offices (tree search)";
  - "/audit (Oldest First)";
  - "/reports/pending-cases (find and a sorted section)".
- **Round 4:**
  - "/cases/[ref]/parties (search)";
  - "/cases/[ref]/documents (sorted by Name)";
  - "/cases/[ref]/notes (no matches)".

## Verification

1. **Each round:** `ruff check` clean and `pytest -q` green; in `frontend`, `npm run lint`, `npm run typecheck` and
   `npx vitest run` green.
2. **Round 1, the full list against the dev database.** Run as the super admin, after the merge. The numbers move as
   cause lists arrive.
   - In the API container, `len(matching.unmapped_codes(s, limit=100_000))` gives N (1,066 on 26 Oct 2026).
   - `GET /admin/counsel-codes/unmapped/page` answers `total` = N.
   - Following `next_cursor` to the end yields N distinct codes, in the same order as `unmapped_codes`. The same holds
     with `sort=code` (A to Z) and `sort=last_seen`.
   - Each page answers in under 500 ms (about 200 ms measured for the whole aggregate).
   - `q=assam` gives `matched` equal to the number of codes whose compact form contains ASSAM.
   - `sort=raw_sql` answers 400 `bad_sort`.
3. **Round 1, on screen** at `http://localhost:3000/admin/mapping/codes`:
   - the panel reads "1,066 codes not mapped";
   - scrolling inside its box loads more until "Showing all 1,066", and the page itself does not grow;
   - typing "assam" narrows it to "n of 1,066 codes" after a pause;
   - Sort By → Code reorders it from A, and the toolbar reads "Sorted by Code, A to Z";
   - mapping one code removes it, and the count drops by one;
   - each code is one row at 1280 px;
   - the Counsel Codes headers sort, with the arrow and `aria-sort`, and a third click returns to Code, A to Z;
   - at `/inbox/working`, Search Words is on the first row.
4. **Round 2:**
   - At `/inbox/department`, Case Number sorts "WP(C) 9/2025" before "WP(C) 10/2025".
   - The address carries `sort=case_no&dir=asc`. A reload and Back keep it.
   - Paging through shows no case twice.
5. **Round 3:**
   - At `/admin/tickets?status=all`, a search for part of a ticket reference narrows the list and survives a reload.
   - The Audit Log at Oldest First pages forward from the first entry.
   - A Search the Court answer narrowed and sorted makes no second court request: the API log shows one
     `POST /cases/search-court`.
6. **Round 4:**
   - On a case with many parties, Search Parties and Advocates narrows at once.
   - On the Notes tab, a word from a note shows that note and "1 of n notes". Newest First reverses the trail.
7. **The browser check, each round:** `docker compose --profile uicheck run --rm uicheck`. No finding at 375, 768 and
   1280 px, and the new states pass.
8. **The owner's browser check** of the four rounds becomes a separate backlog row at approval.

## Open questions

None. Every decision above is made. The owner's approval covers in particular:
- decision 8: a search box only on lists of more than 10 rows, or with a search set;
- decision 14: keywords and the watchlist filtered in the browser, so row 165 keeps only its office change;
- decision 11: the total "1,066 codes not mapped", which also counts codes seen only in case details, as the panel
  always has;
- decision 28: one sorted column at a time;
- decision 30: the 74 lists left without sorting, notably the cause list and the parties in court order and the
  timeline;
- decision 34: the Audit Log and Court Calls sorted by direction only;
- decision 40: the four rounds, with round 1 after row 172.
