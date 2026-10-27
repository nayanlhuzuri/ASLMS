# Design: Data Collection redesign (four tabs, honest progress, live figures, collection on demand, Update From the Court)

```
slug: data-collection-redesign
status: approved
author: architect
date: 2026-10-26
approved_by: owner on 2026-10-26, the four-tab revision as designed (decisions 3, 4, 23, 24, 30, 31, 49, 50 and 52 accepted)
```

**History of this note**
- **26 Oct 2026, first version.** Seven tabs (Overview, Load, Fetch From the Court, Health, Queue and Calls,
  Duplicates, Discovery) in three rounds. The owner approved it (commit 24028e6, rows 172-174).
- **26 Oct 2026, this version.** After a discussion of options, the owner reopened the design and simplified it:
  - **four tabs:** Overview, Collect Now, Automatic Collection, Problems and Fixes;
  - Health and Queue and Calls are removed;
  - manual requests are carried out at once through the court APIs;
  - a bulk request may use the whole hourly allowance;
  - a new **Update From the Court** button on the case page and the claim screens, behind a new function held by
    default only by the Super Administrator (round 4).

  This version replaces the first one. The kit, the honest counts, live polling and the estimate are kept. The
  section "Changes From the First Version" lists every changed decision. Rows 172-174 return to `awaiting-approval`.

## Context

**The owner's requests of 26 Oct 2026:**

1. On the Backdated Load page: "the UI for the whole page looks very bad", and "if the orders stored is not completed
   then why is it showing 100% or 99.9%?".
2. "Where is the page where I can check how much data has been collected and what is left?"
3. The collected and left figures, and the progress, should update live while work is queued.
4. Fetching on demand should sit in one clear area. This includes "refresh the details of every case listed on 23 Oct
   2026" and several cases at once.
5. On a screenshot of the Load tab's Actions: "this is all misaligned. Correct it and categorise it properly, with
   progress bars and animations".
6. On a screenshot of Health: "this whole page also looks misaligned … check all the Data Collection tabs".
7. **After a discussion of options:**
   - four tabs only;
   - the Queue and Calls and Health tabs removed;
   - "these manual requests must be executed immediately via the APIs";
   - a single case gets "everything before showing";
   - a bulk request may "use everything".
8. **On the case:**
   - "if I am claiming a case and I see incomplete details like the case orders are not fetched, there should be a
     button to fetch the order besides";
   - "for the cases that have been claimed, is there an update button to update all the case details and fetch the
     updated court orders … and this API call will take priority";
   - "I don't want to give this feature to every user, otherwise my daily limits will exhaust … by default it will be
     kept only for the superadmin".

"What we discussed previously" means the agreed portal design work:
- the templates of rounds 1 to 5 (`portal-ui-redesign.md`, decision 26);
- `portal-ui-polish.md`: every list a `DataTable` that stacks as cards on phones, and `uicheck`;
- `portal-ui-polish-2.md`: Title Case with the label guard, Filter Layout B, the field-row and checkbox rules, the
  Office Picker, and one primary per page;
- the owner's Department Mapping changes of 26 Oct 2026: a long list scrolls inside its own box, and each item is one
  clear row.

The visual reference is `docs/design/ui/aslms-nav-template.html` and the as-built kit. The owner said designs need no
mockup.

### What the figures say today, checked in the code and the dev database on 26 Oct 2026

- **"With Details" is not about orders.** `services/data_load.py::_month_figures` computes `details_pct` as
  `cases.with_details / cases.listed`: cases listed that month whose details were fetched. It is 99.9% for most
  months.
- **"Orders Stored" is a separate column**, `orders.stored / orders.referenced` by `order_date`, for example 3,055 /
  8,346 in October 2025. Side by side, the two read as if the orders were complete.
- **The orders' own progress is in the data but not on the screen.** `_order_totals` returns `waiting` and
  `not_available`, and the screen never shows them. `failed` is not counted.
  - In the dev database: 320,869 orders known, 137,932 PDFs stored, 182,929 waiting, 8 not available at the court.
  - **Every waiting order has a pending or running `order_pdf` row** (0 without one). So "orders waiting" by
    `order_date` is exactly what is left for those orders, in every lane.
- **"Left" counts the wrong rows.** It counts only `load`-lane `fetch_queue` rows, by `list_date`.
  - An order PDF row carries the listing date that queued it, not the order's date.
  - Most order PDF rows are in the `daily` lane: 167,398 there against 15,531 in the load lane.
  - So October 2025 shows Left 0 while 5,291 of its orders wait.
- **The load works through the dates in order and is at January 2026.** The earliest waiting load day is 2026-01-05,
  with 267 days pending up to 2026-09-29. February to September 2026 therefore show 0% of days but thousands of orders
  (orders of cases found earlier), with no "not reached yet".
- **The estimate leaves out most of the work.**
  - `measure` and `compute_estimate` use the load lane only (about 248 calls an hour).
  - Across lanes the worker made about 900 calls in each full hour. The court allows about 1,000.
  - Order PDFs run after every detail kind: daily dossiers are 40, the load 41-46, and order PDFs 60 and 80.
- **The current month's days include future days** (`_day_totals`), so the month can never reach 100%.
- **The reads are cheap.** On the 2.6 GB database:
  - the period's case totals take 57 ms;
  - the order totals take 25 ms;
  - the queue counts over 381,832 rows take 28 ms;
  - one day of the call log takes 3 ms.
- **A day's current lists hold up to 1,191 distinct cases** (7 Oct 2026), 708 on average.
- **Department discovery has no names yet:** `discovery_terms` has 0 rows.

### How manual fetching works today, and what limits it

- **The worker.** One sequential process, the Compose `worker`, runs `aslms queue-run` in a loop. It claims one
  `fetch_queue` row at a time by priority (`ix_fetch_queue_claim`).
  - When the queue is empty it sleeps 60 s.
  - When the reserve bands block (`runner.budget_lanes`) it sleeps until the expected reset.
- **The reserve bands.** Any lane may run while at least `NAPIX_RATE_RESERVE` (150) calls are left in the hour. Only
  the daily and request lanes may run between `NAPIX_LIVE_RESERVE` (100) and 150. Nothing runs below 100. A person's
  court search is refused below `NAPIX_SEARCH_FLOOR` (50) with 503 `napix_budget`.
- **Today's manual requests are rows in the `request` lane:**
  - re-fetch a day at 20;
  - re-fetch a case (`POST /admin/napix/refetch/case`) at 30;
  - re-fetch an order (`/refetch/order`) at 30;
  - Fetch Details at 30;
  - order PDFs spawned by a person's work at 40.

  They wait for the worker's next pass and are bound by the same bands. The re-fetch buttons sit behind
  `admin.napix_refetch`, held by default by the Super Administrator and the Central Operator. They are used only on
  the Data Collection Health tab. The case page, Case Claim, the large case details modal and the inbox side panel
  have no fetch button.
- **Searches run inside the API request.** A court search (`POST /admin/data-load/fetch`, `POST
  /cases/search-court`) holds one of the API process's six NAPIX request slots (`NAPIX_REQUEST_SLOTS`, row 137). It
  answers 503 `napix_busy` after a 20 s wait for a slot. The portal relay gives up after `RELAY_TIMEOUT_SECONDS` (120
  s).
- **Every order PDF is one Show Order call.** A case can have 100 orders or more.
- **Who caused each call is known.** A request-lane row carries the person in `requested_by`, and the worker writes it
  to `napix_call_log.user_id` (design `napix-window`, decision 10). That is how calls are counted by person.

### Who opens Data Collection today

Every tab reads with `data_load.READERS`: `admin.data_load`, `reports.state`, `admin.napix_refetch` and
`admin.masters_sync`. Health and Queue's own endpoints (`/admin/data-health`, `/admin/napix/*`) take the last three
(`health_reader`). By default:

| User type | Functions among these | Today |
|---|---|---|
| Super Administrator | all four, and `admin.service_health` | every tab and button; System Health |
| State Oversight Officer | `reports.state` | every tab, read only |
| Central Operator | `reports.state`, `admin.napix_refetch`, `admin.masters_sync` | every tab; Retry, re-fetch, Sync Masters and the connection check |

### What System Health (`/system`, `admin.service_health`, row 109) already shows

- **The overview band:** court calls answered in 24 hours, the typical response, **calls left this hour with the next
  reset**, and ASLMS services working.
- **The 17 court API cards,** each with:
  - its last call;
  - 24 hourly bars;
  - 24-hour and 7-day rates;
  - a side panel with a 7-day table and **the API's last 10 calls**;
  - Test Now.
- **Ten service checks:** API, database pool, database direct, Redis, **worker** (liveness), **scheduler**
  (liveness), ClamAV, backups, store, web.
- **The Access Token card** and the request console (row 123).

It does **not** show:
- the full call log across APIs;
- calls by person;
- the recent quota resets;
- the e-mail outbox;
- each scheduled job's last run;
- the call-log clean-up and table sizes.

### Defects, tab by tab, of today's screens

From the 25 Oct uicheck screenshots (`data/uicheck/20261025-1404`) and the components. The "Goes to" column is where
each piece lands in this design.

| # | Tab | Defect | Goes to |
|---|---|---|---|
| D1 | all | No page gutter on the owner's screen: breadcrumb, title and tabs about 3 px from the edge. The fixture screenshots show a normal gutter, so the live data overflows a column (a long error, API path, the estimate's JSON). `DataFrame` renders a bare `<div>` | decision 7 |
| D2 | all | Doubled headings: the panel's `<h2>` is repeated as the table's visible caption (Work Left, Latest Failures, Coverage, Results, Calls by User, Queue, Daily Cycle, Document Text, Queue Rows, Call Log, discovery failures) | decision 10 |
| D3 | all | Upper-case table headers (kit `.table th`), against the owner's Title Case rule and the nav template | decision 8 |
| D4 | all | Two-column boards with unequal panels; wide tables stacking as cards inside half-width panels | decisions 7, 13 |
| D5 | all | Empty states say "Nothing to show." | decision 47 |
| D6 | all | Technical words: "This Window", "Precise", "queue worker's switch", lane names, "Masters", "Jobs", raw statuses | decision 47 |
| L1-L4 | Load | Status as loose lines; the allowance as five tiles in a 2 + 2 + 1 grid; Work Left from the load lane only; the estimate from the load lane only, with raw JSON | decisions 14-21, 36-39 |
| L5 | Load | Coverage hidden behind a button, with misleading columns, bare percentages, Left from one lane, no "not reached yet" | decisions 19-20 |
| L6 | Load | Actions misaligned: unbalanced columns, a bare Pause box, the preview as loose lines, Start always primary, What Goes First with no grid, the fetch form squeezed at the bottom | decisions 36-37, 25 |
| L7 | Load | The fetch results show the raw `dossier_status` | decision 25 |
| H1 | Health | "Period Report" floats alone | decision 11 (Overview toolbar) |
| H2 | Health | Court Gateway: small tiles bunched at the left, loose lines, resets as a bullet list with "Precise" | decision 3 (System Health and Overview) |
| H3-H6 | Health | Calls by User spread over the full width; Queue with eight columns; Masters, Jobs, Mail and Open Failures as bullet lists; Retention as sentences | decision 3 |
| H7 | Health | System checks mixed with re-fetch forms | decisions 28, 29, 43 |
| H8 | Health | Daily Cycle stacked in a half panel, with raw statuses | decision 40 |
| Q1-Q3 | Queue and Calls | Two long unboxed tables, raw statuses and priorities, API paths and HTTP codes | decision 3 |
| U1-U3 | Duplicates | Chips with no explanation, Scan Now unexplained, an unboxed table | decision 44 |
| V1-V3 | Discovery | One panel holding everything, the share as a sentence, Sweep between two tables | decision 41 |

**Elsewhere in the portal.** A source scan found possible doubled headings (a caption equal to a heading in the same
file) in:
- Designations, Tickets, Users, and Mapping (Counsel Codes, Watchlist, Court Search, Scoring);
- the case page (Details, Documents, Hearings, Parties, Next Date);
- the dashboard blocks;
- Profile, System Health (API panel, console) and the Custody tab.

Decision 10 fixes them all at once. The uicheck rule (decision 12) confirms each one. No other page is known to have
the gutter defect; the new rule lists any it finds.

### What this item does not cover

- No migration.
- No change to who may see a case or its records.
- The load's policy and the scoring are unchanged.
- The queue's priorities change only by adding the two "now" priorities for manual requests (decision 24).

## Decisions

### A. Four tabs

1. **Four tabs, in this order:**

   | Tab | Address | Shown with | Holds |
   |---|---|---|---|
   | **Overview** | `/data/overview` (where `/data` opens) | `DATA_READERS` (today's rule) | statistics only: what is held, what is done, what is left, live, month by month, and a count of problems linking to Problems and Fixes (decisions 14-21) |
   | **Collect Now** | `/data/collect` | `admin.data_load`, `admin.napix_refetch` or `admin.masters_sync` | every manual request, carried out at once: one case, a pasted list, one day's cause lists, all cases listed on a day, fetch again, the court reference lists; and the requests with their live progress (decisions 22-33) |
   | **Automatic Collection** | `/data/automatic` | `DATA_READERS` | the past-months load (Load Control, Start, Pause and Resume, What Goes First), the court allowance, the daily schedule in plain words, the daily updates of the last 7 days, and Search by Department Names (decisions 34-41) |
   | **Problems and Fixes** | `/data/problems` | `DATA_READERS` | the court connection line, failed fetches with Retry, possible duplicates to confirm, and data gaps (decisions 42-46) |

   - The side menu's Data Collection children follow `DATA_TABS` (portal-ui-polish-2, decision 15), so they show the
     four tabs.
   - Showing a tab is convenience only. Every endpoint keeps its own check.
   - Alternative: the approved seven tabs. Superseded by the owner's direction.
2. **Old addresses redirect, with the query string kept**, through `OLD_DATA_REDIRECTS` in `src/lib/routes.ts`,
   pinned by `routes.test.ts` and checked as redirects by uicheck (the `OLD_FILES` pattern):

   | Old | New |
   |---|---|
   | `/data/load` | `/data/automatic` |
   | `/data/health` | `/data/overview` |
   | `/data/queue` | `/data/problems` |
   | `/data/duplicates` | `/data/problems#duplicates` |
   | `/data/discovery` | `/data/automatic#department-names` |
   | `/data/fetch` (the first version's address) | `/data/collect` |

3. **Where every piece of the removed Health and Queue and Calls tabs goes.** Nothing is dropped without a reason.

   | Piece today | Now | Reason |
   |---|---|---|
   | Court gateway on/off, the worker note | Overview status line (decision 14) | everyone who reads Data Collection needs it |
   | Calls this window and today, calls remaining, next reset | Overview's Right Now and Automatic Collection's Court Allowance | the progress depends on it; System Health already shows "calls left this hour" |
   | Recent resets | System Health, a new **Court Calls** section (below) | technical; it explains the window detection |
   | Calls by user (operators only) | Automatic Collection's Court Allowance, still only for `admin.napix_refetch` / `admin.masters_sync` as the API decides today | it shows who used the allowance |
   | Last call, last connectivity check, **Connectivity Check** button | Problems and Fixes, the Court Connection line (decision 43) | it is the first thing to check when fetches fail; the Central Operator keeps the button |
   | Sync Masters button, masters' last update | Collect Now, Court Reference Lists (decision 29) | it is a manual request |
   | Queue by kind and lane | Overview, the Still to Fetch tile and its "Waiting Work" table (decision 15) | the summary of waiting work |
   | Queue rows browser (filters, Retry) | Problems and Fixes, Failed Fetches with Retry (decision 44). The browser of pending rows goes; `GET /admin/napix/queue` stays (the month's days dialog uses it) and `aslms queue-status` stays | pending rows are technical; what a person acts on is a failure |
   | Court call log | System Health, Court Calls section | it is a technical record; `/system` is where the court connection is examined |
   | Daily cycle (last 7 days) | Automatic Collection, Daily Updates (decision 40) | it is automatic collection |
   | Jobs (latest run of each) | Automatic Collection, the Daily Schedule's Last Run column (decision 40) | the schedule says what runs when |
   | Mail outbox (queued, failed) | System Health, Court Calls section, an E-mail line | not data collection; it is a service |
   | Open failures by kind | Problems and Fixes, Failed Fetches (decision 44) | — |
   | Document text by status | Problems and Fixes, Data Gaps (decision 45) | documents that cannot be searched are a data gap |
   | Retention: call-log rule, last purge | Automatic Collection, the schedule's 03:45 entry with its last run and rows removed | it is a scheduled job |
   | Retention: table sizes | dropped from the portal | Grafana and `aslms ops metrics` (row 77) already show database size; no reader acts on it |
   | Retention: disposed cases refreshed monthly | Automatic Collection, the schedule's 02:30 entry with "n in their first year, m due now" | a scheduled job |
   | Masters, sync and re-fetch buttons on Health | Collect Now (decisions 28-29) | manual requests |
   | Duplicates tab | Problems and Fixes, Possible Duplicates (decision 44) | — |
   | Discovery tab | Automatic Collection, Search by Department Names (decision 41) | it runs automatically |

   **System Health gets one new section, "Court Calls"** (`/system#calls`, a menu child of System Health). It is
   shown to holders of `admin.service_health` **and** a health-reader function (`reports.state`,
   `admin.napix_refetch` or `admin.masters_sync`), because its data comes from the existing health endpoints with
   their own guards. By default this is the Super Administrator.
   - **It holds:**
     - Recent Resets: a compact table with Time, Calls Left Before, Calls Left After, and Timing ("Seen Exactly" or
       "Estimated");
     - E-mail: Waiting and Failed;
     - the Court Call Log, as today's call log in a `ScrollBox`: When, Court Service (a plain name, with the path in a
       tooltip), Kind of Work, Result, Calls Left, and Person where the API returns it, with More.
   - **No API changes and no widening.**
4. **Nobody loses information they need.** By default:

   | User type | Now finds |
   |---|---|
   | **Super Administrator** | everything: all four tabs and System Health with its new Court Calls section |
   | **State Oversight Officer** (`reports.state`) | Overview (all figures, the dated report link), Automatic Collection (read only), Problems and Fixes (read only, no buttons). They no longer see the raw call log, the browser of pending queue rows or the mail outbox. These are technical records they never acted on, and the API keeps them |
   | **Central Operator** (`reports.state`, `admin.napix_refetch`, `admin.masters_sync`) | Overview; Collect Now with Fetch Again, One Day's Cause Lists and Court Reference Lists (One Case and the bulk cards need `admin.data_load`, as today); Automatic Collection with Calls by Person; Problems and Fixes with Retry, Retry All of a Kind, Try Again for an order, and Check the Court Connection. They lose the raw call log and the mail outbox, which are now on System Health. The Super Administrator can grant `admin.service_health` if a particular operator needs them; that is a grant, not a design change |

5. **The State dashboard links to Overview.** The State block's action area gets **"Data Collection Progress"**,
   shown with a reader function. No figure is added to the dashboard, so it makes no extra query.
6. **One primary per page:**
   - **Overview** has none: it is statistics only;
   - **Collect Now** has none: each card's submit is secondary, and the confirming dialog has the primary;
   - **Automatic Collection**'s primary is **Start a Load**;
   - **Problems and Fixes** has none.

### B. Portal-wide kit changes (kept from the first version, renumbered)

7. **Every page keeps its gutter.**
   - `DataFrame` renders `<div className="stack">`, like `AdminFrame`.
   - Every card has `min-width: 0`.
   - Long values get `overflow-wrap: anywhere`.
   - No raw JSON is shown.
   - The developer first reproduces the owner's 3 px gutter with the live data at the owner's width, and records the
     cause in the report.
8. **No upper-case labels, portal-wide** (owner, decided twice).
   - `text-transform: uppercase` and its letter-spacing go from:
     - the kit's `.table th` and `.dateChip span`;
     - the shell's `.gov` and `.groupLabel`;
     - `admin.module.css:320`, `assistant.module.css:105` and `:204`, `auth.module.css:51` and `:156`,
       `calendar.module.css:62`, `case.module.css:55`, `rail.module.css:36` and `:67`, and `remarks.module.css:108`.
   - This matches the nav template, which sets `text-transform: none` everywhere.
   - It touches every table, menu group and fact label. The developer checks each by eye and fixes any source string
     that shows in lower case.
   - A vitest, `components/styles.test.ts`, fails on any `text-transform: uppercase`.
9. **A kit `ProgressBar` and `ProgressLegend`** (`components/ui/feedback.tsx`).
   - **Segments** with tones `done`, `active`, `waiting`, `unavailable` and `failed`:
     - done is solid `--green`;
     - active is `--accent`, with the live pulse;
     - waiting is `--accent-soft` with diagonal stripes;
     - unavailable is `--slate-soft` with a `--border-strong` edge;
     - failed is `--red`.
   - **Accessibility:** `role="progressbar"`, `aria-valuemin`, `aria-valuemax` and `aria-valuenow` (the done
     segment), and an `aria-valuetext` sentence. The same text is visible, never colour alone.
   - **Sizes:** `sm` (6 px) and `md` (10 px).
   - **Motion:** each segment grows by `transform: scaleX()` over `--slow`.
10. **`DataTable` captions are hidden by default** (`showCaption` shows them). They stay in the markup for the
    accessible name.
    - The developer checks all 69 uses; a table with no visible heading gets `showCaption` or a heading.
    - **A kit `ScrollBox`** (`components/ui/layout.tsx`):
      - `role="region"` with `aria-label` and `tabIndex={0}`;
      - `max-height: min(60vh, 560px)`, `overflow-y: auto`, `overscroll-behavior: contain`;
      - a sticky header row for a table inside it.
    - It is the Department Mapping box, moved into the kit. Mapping may adopt it later.
    - Every growing list in Data Collection, and the new Court Calls section, sits in one.
11. **A tab toolbar line:** "Updated 4 s ago" on the left, the tab's links and secondary buttons on the right (for
    example **Open the Dated Report** on Overview, with `reports.state`). No floating links remain.
12. **Two uicheck rules, run on every page of the portal** (`frontend/e2e/checks.ts`):
    - **`gutter`:** inside `main#main`, at least 12 px of left padding, and every visible element inside the content
      box, unless it is inside `[data-scroll-x]` or `[data-bleed]`, fixed or absolute, or visually hidden;
    - **`doubled-heading`:** a visible `h1`-`h4`, `caption` or `legend` whose normalised text equals the nearest
      visible heading above it in the same `section`, `article`, `[data-ui=card]` or `[role=dialog]`.

    Each rule has a self page that breaks it and one that keeps it. A vitest companion goes into
    `components/tables.test.ts`. The fixtures get long values (`synth.ts`).
13. **Motion on the existing tokens only:**
    - bars grow;
    - numbers count up (`useCountUp`, `tabular-nums`);
    - "Running", "Fetching" and active segments pulse in opacity, `calc(var(--slow) * 5)`;
    - cards ease in with `page-in`, staggered by 40 ms.

    Under `prefers-reduced-motion: reduce` the tokens are 0 ms, so nothing animates. Nothing moves the layout. No
    library.

### C. Overview: statistics only

14. **The status line and four tiles with bars.**
    - **The status line:**
      - **Court Connection**: an On or Off badge, with the worker note in a tooltip;
      - **Automatic Collection**: Running (pulsing), Paused (with the reason in a tooltip), Finished, or Not Started;
      - **Collect Now**: "A request is using the whole court allowance until about 17:20", shown while a bulk request
        runs (decision 30);
      - the period.
    - **The four tiles** (four columns from 1100 px, two from 600 px, one on phones), from `GET
      /admin/data-load/overview`:

      | Tile | Big figure | Bar | Line under it |
      |---|---|---|---|
      | **Cause Lists** | "306 of 664 days" | collected, waiting, failed, of the days in the period up to today | "Working on January 2026", "Paused at January 2026" or "Up to Date" |
      | **Cases** | "59,033 found" | with details | "58,924 with case details · 109 without" |
      | **Order PDFs** | "137,932 of 320,869 stored" | stored, waiting, not available, failed, with the legend | "182,929 waiting · 8 not available at the court" |
      | **Still to Fetch** | the total items left in every lane | none | "267 cause-list days · 33 case details · 182,929 order PDFs" |

    - **The meanings:** cases found are all cases held, not merged. Orders known are all orders held, whatever their
      date. Still to Fetch counts work in every lane, the request lane included.
15. **Each figure says what it measures,** with a one-sentence tooltip per tile. Under Still to Fetch, a `Collapsible`
    **"Waiting Work"** shows a compact table: kinds as rows, then Total and one column per kind of work (decision 47),
    then Fetching and Failed.
16. **A Problems line** under the tiles: "12 failed fetches · 3 possible duplicates · 109 cases without details · 8
    orders not available", each part linking to its section of Problems and Fixes. It reads "No Problems" when every
    count is 0.
17. **Live figures by polling only while the tab is visible.**
    - **The rhythm:**
      - `GET /admin/data-load/pulse` every **5 s**;
      - the overview every **30 s**, and at once after any action;
      - the month table every **120 s**, and on Refresh.
    - Polling stops while the tab is hidden (`refetchIntervalInBackground: false`) and fetches once when it is shown.
    - "Updated n s ago" comes from `dataUpdatedAt` and ticks with no request.
    - **Server-sent events are refused.** They hold an API worker per viewer and still need the server to poll. The
      push alternative, `LISTEN/NOTIFY`, is a session-level feature that PgBouncer's transaction mode breaks (row 78).
    - **Polls never count as activity** for the session timeout (row 169, design `session-timeout`, decision 4: only
      `POST /me/activity` counts).
18. **Right Now**, a slim card from the pulse:
    - **Fetching Now**, by kind, with the pulsing badge;
    - **Calls This Hour**: a bar of calls made of the hourly limit seen, and "Next reset in 12 min" (a countdown in the
      browser, `aria-live="off"`);
    - **Requests in Progress**: the count, linking to Collect Now.
19. **Month by Month, always shown,** in a `ScrollBox`.
    - **Columns:**

      | Column | Shows |
      |---|---|
      | Month | "January 2025" |
      | Cause Lists | a slim bar, "26 of 31 days", and a badge: Done, In Progress, Not Reached Yet, Some Days Failed, Not in a Load |
      | Lists and Entries | "412 lists · 18,220 entries" |
      | Case Details | a bar and "4,120 of 4,130 cases" |
      | Order PDFs | a segmented bar and "2,978 of 9,876 stored · 6,898 waiting" |
      | Still to Fetch | "6,898 order PDFs · 2 days · 10 cases", or "Nothing" |
      | Problems | failed days, case details that could not be fetched, failed order PDFs, linking to Problems and Fixes |
      | (unlabelled) | **Days**: opens the month's days in a `Dialog` |

    - **The legend line:** "Cause lists and cases are counted by hearing date and orders by order date, so a month not
      reached yet can already show orders of cases found earlier."
    - **A last row, "Orders Dated Before January 2025",** makes the rows add up.
    - **A Not Reached Yet month** is muted, never red.
20. **Still to Fetch per month is counted by each column's own date, in every lane:**
    - **days:** calendar days up to today not yet collected;
    - **cases:** cases listed that month without details that have a pending or running `dossier` row in any lane;
    - **order PDFs:** orders dated that month that are pending with no document.

    The old `work_left` and `failed` keys stay in the answer for older clients.
21. **An honest estimate across every lane:**
    - **Two lines:** "Cause lists and case details: about Tuesday 28 Oct 2026" and "Every order PDF as well: about
      Saturday 8 Nov 2026".
    - **The basis line:** "At the pace of the last 24 hours, about 820 court calls an hour of the 1,000 the court
      allows. New cause lists each day, and requests made on Collect Now, add work, so these dates can move."
    - **"How This Is Worked Out"** gives the inputs in words, with no JSON.
    - **The method** (`estimate_all`): measured rates only, over every queue lane (decision 8 of `data-load-console`,
      widened).
    - **No date, with the reason,** while paused (for the details line), with less than a day of history, with no
      queue call in the last hour, or with the connection off.
    - **Today's dev figures:** roughly 1.5 days and 13 days.

### D. Collect Now: manual requests carried out at once

22. **The Collect Now tab, top to bottom:**
    - **Requests** (decision 32), shown first when one is running or finished in the last 7 days;
    - **One Case** (`admin.data_load`, decision 25);
    - **Several Cases** (`admin.data_load`, decision 26);
    - **All Cases Listed on a Day** (`admin.data_load`, decision 27);
    - **One Day's Cause Lists** (`admin.napix_refetch`, decision 28);
    - **Fetch Again**: One Case Again and One Order PDF Again (`admin.napix_refetch`);
    - **Court Reference Lists** (`admin.masters_sync`, decision 29).

    Each card uses the field-row grid and shows by its own function.
23. **"Immediately" means the worker, at the top of its queue, starting within seconds, with the person watching
    live.** It does not mean inside the web request.
    - **Synchronous in the API request is refused:**
      - a case with 100 orders is about 100 Show Order calls, minutes of work, past the relay's 120 s;
      - it would hold one of the API's six NAPIX slots for minutes, and other people's searches would then get
        `napix_busy`;
      - a closed browser tab would cut it off;
      - it would bypass the single place that keeps the call log's lanes and person, the quota window, the probe and
        the fault pause.
    - **The worker way:**
      - The request writes its queue rows at a "now" priority, ahead of everything (decision 24), and returns at once
        with its request id.
      - The worker wakes within 2 s and works the rows one after another through the integration layer.
      - The page polls the request every 2 s and shows each step as it happens.
      - The request continues if the person leaves, and survives a worker restart (stale running rows are re-queued).
      - **The calls count under the person who asked:** each row carries `requested_by`, and the call log records it
        as `user_id`.
    - **The one synchronous part stays:** the search itself on One Case (by CNR, case number or party name) still runs
      in the API request, as today. A search is one call, and its answer is needed to choose the case.
    - **When the worker is not running** (no claimed row for 2 minutes while "now" rows wait, the System Health
      worker-liveness rule), the request card says "Waiting for the collector to start (last active 14:05)".
24. **Two "now" priorities, outside the reserve bands.**
    - `load_policy.NOW_ONE = 3` is for one case, fetch again, one day's cause lists, the court reference lists, and
      Update From the Court (decision 50).
    - `load_policy.NOW_BULK = 5` is for several cases and all cases of a day.
    - Both are in the `request` lane, with the person in `requested_by`. Both sit ahead of the masters (10) and the
      daily lists (20). A one-case request (3) goes ahead of a running bulk request (5).
    - **The runner** (`services/runner.py`):
      - **Claim:** before the bands, `queue.claim(..., max_priority=NOW_BULK)` takes a "now" row whenever the window's
        remaining count is unknown or at least 1. A "now" row ignores `NAPIX_RATE_RESERVE`, `NAPIX_LIVE_RESERVE` and
        the discovery share. Only the court's own limit stops it.
      - **When the court's limit is used up,** the pass stops until the reset, as today. The request's panel says
        "The court's hourly limit is used up; this continues at about 16:35".
      - **Spawned work inherits the priority.** `QueueOrigin` gains `now_priority`, set from the claimed row's
        priority when it is 5 or less. A "now" dossier's order PDFs (`enqueue_order_pdfs`, which queues **every**
        missing PDF of the case) and a "now" day's new dossiers take the same priority.
      - **The worker wakes.** `pipeline.worker_wait` sleeps in slices of `NOW_POLL_SECONDS = 2`, and wakes when
        `queue.has_now()` finds a runnable row at priority 5 or less. This is a cheap `EXISTS` on the partial claim
        index.
      - The fault pause still applies.
      - **No setting is added.** The reserves keep their meaning for everything else.
25. **One Case: "everything before showing".**
    - **Step 1, search (synchronous, as today):** the existing `POST /admin/data-load/fetch` by CNR, case number or
      party name, with its guard and its `already_held` and `searched_before` warnings. The results are a `DataTable`
      in a `ScrollBox`: Case, CNR, Details (in words: "Details Held 21 Oct", "Not Fetched Yet"), and a tick box per
      row, up to 20.
    - **Step 2, Collect Everything:**
      - For a CNR search with one result it starts by itself. Otherwise the person ticks the cases and presses
        **Collect Everything** (secondary).
      - It sends `POST /admin/data-load/collect {kind: "cases", refs}` (1-20 cases, `NOW_ONE`).
      - For each case: its dossier, unless the details were fetched in the last 10 minutes (as a CNR search just did),
        then every order PDF it lacks.
    - **The progress panel** (a kit-level `CollectProgress` component, shared with decision 52):
      - **Case Details**: Waiting, then Fetching, then Done;
      - **Order PDFs**: a `ProgressBar`, "12 of 40 stored · 1 not available at the court", with "about 2 min left at
        the current pace";
      - each step pulses while it is active.
    - **The result is shown only when everything has run.** The dossier is done, and every order PDF is stored, not
      available, or waiting for a retry after a failed attempt. The result card shows:
      - case number, CNR, status, details fetched at;
      - "Order PDFs: 39 stored, 1 not available at the court";
      - "1 will be tried again at about 16:40" for a retry;
      - **Open the Case** (the case page applies its own visibility).
    - **No parties or notes are shown** in Data Collection, as today.
26. **Several Cases (a pasted list), a bulk request.**
    - **The form:** a `TextArea` "Cases, One per Line" (up to 200), then **Check List** (`POST
      /admin/data-load/collect/list/check`, which writes nothing).
    - **Each line is read by `case_filters.parse_query`:**
      - an ASLMS reference or id: the held case;
      - a CNR: the held case, or, when not held, a dossier row by that CNR (the court's own identifier). That creates
        the case from the court, as a person's court search does;
      - a case number: held cases matched as the local search matches. Several matches give "Several Cases Match".
        None gives "Not Held", with the hint "Use One Case to search the court for it.";
      - anything else: "Not a Case Reference".
    - **The check's table:** Will Fetch, Already Has Details (with the date), Not Held, Several Cases Match, Not a Case
      Reference, Merged Into ‹ref›.
    - **"Also Fetch Cases That Already Have Details"** is a checkbox (`force`).
    - **The check also shows** "About 1,250 court calls" and the "use everything" panel (decision 30).
    - **Collect Everything** opens a `ConfirmDialog` that repeats the panel. Its primary sends `POST
      /admin/data-load/collect {kind: "list", lines, force}` at `NOW_BULK`.
    - **Each case gets its dossier and then every missing order PDF.**
27. **All Cases Listed on a Day, a bulk request.**
    - **Date** (up to tomorrow), and **Which Cases**:
      - **Only Cases Never Fetched** (the default);
      - **Every Case Listed**: cases refreshed in the last 6 hours are left out, so a second click soon after spends
        nothing.
    - **Check This Day** (`GET /admin/data-load/collect/day?date=&scope=`) shows:
      - Lists on That Day;
      - Cases Listed;
      - With Details (last refreshed between …);
      - Never Fetched;
      - Refreshed in the Last 6 Hours;
      - No Court Reference;
      - **To Fetch**;
      - the calls estimate and the "use everything" panel.
    - **When there is nothing to fetch,** it says "Every case listed on this day already has details." and shows no
      button.
    - **Collect Everything** → `ConfirmDialog` → `POST /admin/data-load/collect {kind: "day", date, scope}` at
      `NOW_BULK`.
    - **The cases** are the distinct `case_id`s of the date's current lists (`superseded_at IS NULL`), not merged.
    - **The cap** is 2,000 cases (400 `too_many`). A date with no current lists is 400 `no_lists`; a date after
      tomorrow is 400 `date_in_future`.
    - **The counts are recomputed when the request is sent.**
28. **One Day's Cause Lists and Fetch Again**, moved from Health:
    - their existing endpoints, warnings and audit (`napix.refetch_requested`): `/admin/napix/refetch/day`,
      `/refetch/case`, `/refetch/order`, under `admin.napix_refetch`;
    - their priority changes from 20 and 30 to `NOW_ONE`. A day re-fetch's new dossiers then inherit it;
    - each shows the same progress panel, keyed by its audit row;
    - the Cause List page's DayBar re-fetch uses the same endpoint, so it also runs at once.
29. **Court Reference Lists:** **Update Now** (`admin.masters_sync`, the existing `POST /admin/napix/sync-masters`,
    audit `napix.masters_sync_requested`).
    - It moves from 10 to `NOW_ONE`.
    - A table shows each list's last update and rows: Case Types, Benches, Acts, States, Districts.
30. **"Use everything": a bulk request may spend the whole hourly allowance, and says what others experience.**
    - **What happens:** the request's rows run ahead of every other lane, ignoring the reserves, until done or
      stopped. The past-months load, the daily updates (including the 06:30 and 18:30 lists), department-name
      searches and other people's work wait.
    - **What others experience, shown on the check panel, the confirm dialog and the request's card:**
      - "While this request runs:
        - other people's court searches, and other people's Update From the Court, wait or are refused once fewer
          than 50 calls are left in the hour;
        - daily updates and the past-months load wait, and catch up afterwards;
        - nothing already collected is affected."
      - The estimate: "About 1,250 court calls: about 640 in this hour and the rest after the 16:35 reset. It
        finishes about 17:20."
    - **The refusal names the cause.** `court_search.guard` keeps its code (503 `napix_budget`) and its rule. Its
      message adds "The court's hourly allowance is in use by a data collection request until about 17:20. Try again
      after that." when a bulk request is active. The worker does not use the API's six NAPIX slots, so `napix_busy`
      does not arise from this.
    - **The Overview status line** says it too (decision 14).
    - **One bulk request at a time.** A second one answers 409 `bulk_running`, with who asked, what and since when.
      One-case requests, including Update From the Court, are always allowed and go first (3 before 5).
31. **Stop.** A running bulk request's card has **Stop Using Everything** (`admin.data_load`, any holder). It opens a
    `ConfirmDialog`:
    - "The rest of this request (548 cases) will be fetched in the normal turn, after daily updates, within the usual
      limits. Other people's searches work again."
    - It sends `POST /admin/data-load/requests/{id}/stop`, which moves the request's pending rows at `NOW_BULK` to the
      request lane's normal priority (30). The bands apply to them again.
    - Running rows finish.
    - Audit: **`data_load.collect_stopped`**, with `{request_id, moved}`.
    - **Nothing is thrown away.** Alternative: mark the rest `skipped`. Refused: a row the request took over may have
      been daily or load work before (one row per item), and skipping it would lose that work.
32. **Requests, with live progress.**
    - **The card** lists the last 7 days' requests: Collect Now (one or several cases, a list, a day, a day's cause
      lists, fetch again, reference lists) and Update From the Court (decision 50). They come from `GET
      /admin/data-load/requests`.
    - **Each row shows:**
      - What ("Cases Listed on 23 Oct 2026", "List of 12 Cases", "One Case", "Updated From the Case Page");
      - Asked By and When;
      - a segmented `ProgressBar`: Done, Fetching (pulsing), Waiting, Failed;
      - the counts;
      - for a bulk request: "Using the Whole Allowance" (pulsing) or "Stopped".
    - **Show Items** opens a `SidePanel` (`GET /admin/data-load/requests/{id}`, paged by 100).
    - **The request record is its audit row** (no new table):
      - its id is the `audit_log.id`;
      - its refs are `after.refs` (`[{kind, ref}]`);
      - the time asked is `created_at`.
    - **Items include the order PDF rows spawned for the request's cases:** `order_pdf` rows of its CNRs queued or
      updated at a "now" priority after it was asked.
    - **States:** pending and ready is Waiting; pending until later is Waiting to Retry; running is Fetching; done is
      Done; skipped is Not Found at the Court; failed is Failed.
    - **A request is finished** when none of its items is pending-ready or running.
    - **Refreshing:** every 2 s while a progress panel is watched, 5 s for the list while any request runs, 30 s
      otherwise. Only while visible.
33. **The guards.**
    - **One Case, Several Cases, All Cases Listed on a Day and Stop** need `admin.data_load`.
    - **One Day's Cause Lists and Fetch Again** keep `admin.napix_refetch`; **Court Reference Lists** keeps
      `admin.masters_sync`.
    - The description of `admin.data_load` becomes "Start, pause and order the automatic collection, collect cases
      from the court at once and check duplicates" (a seed upsert).
    - No holder gains or loses a power.

### E. Automatic Collection

34. **The Automatic Collection tab, top to bottom:**
    - **Load Control** (wide);
    - **What Goes First** and **Court Allowance** side by side from 1100 px;
    - **Daily Schedule** (wide);
    - **Daily Updates, Last 7 Days** (wide);
    - **Search by Department Names** (wide, anchor `#department-names`).

    The primary is **Start a Load**.
35. **The plain words.** "Backdated load" becomes **"Past-Months Collection"** on screen, with "the backdated load" in
    the tooltip. The card text: "Collects every cause list, case and order from 1 January 2025 up to today, month by
    month, in the court calls left over after daily updates and people's requests."
36. **Load Control:**
    - **a definition list:** Status (Running or Paused), Since, Reason, Period, What Goes First, Court Connection;
    - **Start a Load** opens the Start dialog: a From–To pair, **Check These Dates**, a summary panel of five tiles
      (Days, Already Held, Waiting, Failed, New) with the calls and hours, and Days Already Held as a radio group.
      **Start Load** appears only when something would be fetched; otherwise the panel says "Nothing new to fetch …"
      and the dialog has only Close;
    - **Pause** opens a dialog with the required reason (3 to 500 characters) and a danger **Pause Collection**;
    - **Resume** opens a `ConfirmDialog`;
    - the endpoints and audit are unchanged (`data_load.started`, `data_load.paused`, `data_load.resumed`);
    - read only without `admin.data_load`.
37. **What Goes First:** a three-column grid.
    - **Row 1:** the select, then the **Bring These Dates Forward** fieldset holding From and To.
    - **Row 2:** Reason (two columns) and **Save Priority** (secondary) on the control line.
    - **Under the grid,** a line in words explains the current choice.
    - `PUT /admin/data-load/order`, with the same audit.
38. **Court Allowance:**
    - a `ProgressBar` of calls this hour of the hourly limit seen;
    - Calls Left and Next Reset (the countdown);
    - a compact table "By Kind of Work";
    - **Calls by Person**, shown only when the API sends `by_user` (operators, today's rule);
    - **the rule in one hint:** "Automatic collection stops when fewer than 150 calls are left in the hour, keeps 100
      for daily updates and 50 for people's searches. A request on Collect Now, or Update From the Court, goes first
      and may use them all." The numbers come from the API.
39. **Past-Months Collection waiting.** Today's Work Left becomes a compact line under Load Control: "Waiting: 267
    cause-list days · 33 case details · 15,592 order PDFs", with a link to Problems and Fixes for its failures.
40. **Daily Schedule and Daily Updates, read only, in plain words.**
    - **The schedule** comes from `GET /admin/data-load/schedule`: `schedules.PLAIN_SCHEDULE`, tied to
      `celery_app.beat_schedule` by a test.
    - **Its columns:** When, What, Last Run, Result.

      | When | What (as shown) |
      |---|---|
      | 06:00 | Update the court's reference lists |
      | 06:30 | Fetch yesterday's, today's and tomorrow's cause lists, and check today's again for corrections |
      | 18:30 | Fetch the three days' cause lists again and check today's and tomorrow's for corrections |
      | 20:00 | Check the status of every case that is not disposed |
      | 02:30 | Refresh cases disposed in the last year, monthly ("1,234 in their first year, 56 due now") |
      | 03:00 | Look for duplicate cases |
      | 03:45 | Remove court call records older than 2 years ("last run removed 0") |
      | Sundays 02:00 | Refresh the details of every case not fully fetched |
      | Saturdays 02:00 | Search the court by department names |
      | Always | Past-months collection, in the calls left over |

      Last Run comes from the latest `job_runs` row of the matching job where one is written, else "Not Recorded".
    - **Daily Updates, Last 7 Days:** Date, Status (Done, Waiting, Failed, No List Published), Lists, Entries,
      Corrected, Evening Recheck, from `data_health.daily_cycle`.
41. **Search by Department Names** (today's Discovery, renamed).
    - **The plain line:** "ASLMS searches the court by the names each department registers (such as its own name or
      its officers' titles), to find its cases before they appear in a cause list."
    - **When no names are registered (today: 0):** the empty state "No department names are registered yet.
      Department Administrators add them in Department Mapping → Keywords, with Search the Court switched on." There
      is a link to Department Mapping for `admin.keywords`.
    - **Otherwise:**
      - tiles: Names Searched, Names Paused, Cases Found, Created by This Search, Recommended From It;
      - a `ProgressBar` of this hour's calls against its share;
      - "Searches cases from ‹from_year› on";
      - the waiting work;
      - **Search Every Name Now** (secondary, `admin.data_load`, with today's confirm).
    - The endpoints are unchanged.

### F. Problems and Fixes

42. **The Problems and Fixes tab, top to bottom:**
    - **Court Connection** (one line);
    - **Failed Fetches** (`#failed`);
    - **Possible Duplicates** (`#duplicates`);
    - **Data Gaps** (`#gaps`).

    The section headings carry their counts. Each section has an empty state.
43. **Court Connection line:**
    - "The court answered at 14:31", or "The last call failed at 14:31: ‹reason in words›";
    - **Check the Court Connection** (`admin.napix_refetch` or `admin.masters_sync`, the existing `POST
      /admin/napix/health/check`, audit `napix.health_checked`).
44. **Failed Fetches and Possible Duplicates.**
    - **Failed Fetches:**
      - a summary by kind, each with **Retry All** (the existing `POST /admin/napix/queue/retry-failed` with no lane);
      - a `ScrollBox` table: When, What, Kind of Work, Tries, Problem, and **Retry** (the existing `POST
        /admin/napix/queue/{id}/retry`);
      - paged by 50, from the existing `GET /admin/napix/queue?status=failed`;
      - by function: `admin.napix_refetch`, and `admin.masters_sync` for the reference lists.
    - **Possible Duplicates:** today's Duplicates.
      - The three kinds are a `SegmentedSwitch`, each with a one-line explanation.
      - **Scan Now** is secondary (`admin.data_load`), with the hint "Also runs every night at 03:00.".
      - A `ScrollBox` table: Case, Other Case, When, Reason.
      - The endpoints are unchanged.
45. **Data Gaps:**
    - **Cases Without Details:** a count with its split (Being Fetched, Not Found at the Court, Failed, Not Yet
      Queued), and a `ScrollBox` table: Case, CNR, First Seen, State. **Collect These** (`admin.data_load`) sends the
      listed cases that are not being fetched as a Several Cases request (up to 200).
    - **Orders Not Available or Failed:** a table with Case, Order, Date, State, Problem, and **Try Again** per row
      (`admin.napix_refetch`, the existing `POST /admin/napix/refetch/order`).
    - **Documents Without Searchable Text:** today's Document Text figures with the note. Read only.
    - These come from `GET /admin/data-load/gaps?kind=cases|orders` and the overview's counts.
46. **Who acts here.** Readers without the action functions see every figure and table with no buttons. All the
    actions are existing endpoints with their audit.

### G. Words, visibility, rounds

47. **Plain words throughout, with exact terms only in tooltips.**
    - **Lanes:** `load` is Past Months, `daily` is Daily Updates, `discovery` is Department Names, `request` is Asked
      by People, and calls outside the queue are Searches and Checks.
    - **Kinds:** Court Reference Lists, Cause-list Days, Case Details, Status Checks, Order PDFs, Party-name Searches,
      Advocate Search Results, Cause-list Rechecks.
    - **Statuses:** Waiting, Fetching, Done, Failed, Nothing at the Court.
    - **"This Window"** becomes "This Hour".
    - Every label is Title Case under `labels.test.ts`. The wording guards stay green.
    - **The new audit actions** get names in `T.audit.actionNames`:
      - "Collection Requested";
      - "Collection Stopped";
      - "Case Updated From the Court";
      - "Order Fetched From the Court".
48. **What changes in who may see or do anything, exactly.**
    - The new Data Collection reads use `data_load.READERS`.
    - This adds `admin.data_load`-only holders to two sets of system totals that were behind the health readers: the
      daily cycle and the document-text counts. These are figures with no case content, and in practice that holder is
      the Super Administrator.
    - The request and gap lists show references, CNRs and case numbers, which Duplicates and the queue already show
      to the same readers.
    - **The new Data Collection writes** are `POST /admin/data-load/collect` and `…/requests/{id}/stop`, behind
      `admin.data_load`, audited.
    - **The new case-level writes** (round 4) are behind the new `cases.update_from_court` and the case's
      visibility, audited.
    - **The existing re-fetch and reference-list buttons** change only their priority.
    - **The System Health Court Calls section** needs `admin.service_health` and a health-reader function, so no read
      is widened.
49. **Four rounds, each its own branch, review and report:**
    - **Round 1 (row 172, `feature/data-collection-redesign`): decisions 1, 2 (for the new addresses), 5-21 and
      34-41.**
      - the kit and the portal-wide changes;
      - the four-tab frame;
      - Overview with its services;
      - Automatic Collection with schedule;
      - Collect Now holding the existing forms, moved unchanged (One Case search with Fetch Details, One Day's Cause
        Lists, Fetch Again, Court Reference Lists);
      - the State dashboard link.

      Until round 2, the old Health, Queue and Calls and Duplicates tabs stay as they are, listed after the four.
      Load and Discovery redirect at once.
    - **Round 2 (row 173, `feature/data-collection-redesign-tabs`): decisions 2 (the rest), 3, 4 and 42-46.**
      - Problems and Fixes with the gaps service;
      - the System Health Court Calls section;
      - the old tabs retired with their redirects.
    - **Round 3 (row 174, `feature/data-collection-fetch`): decisions 22-33**, immediate collection:
      - the "now" priorities, the runner's claim and wake, inherited priorities;
      - the collect endpoints, One Case "everything before showing" with the `CollectProgress` panel;
      - the bulk requests with "use everything", one bulk at a time, and Stop;
      - the requests list and items;
      - the priority change of the existing buttons.
    - **Round 4 (a new row at approval, the next free number; 175 is taken by `list-search`;
      `feature/case-update-from-court`): decisions 50-56.**
      - Update From the Court and Fetch Order on the case page, Case Claim, the case details modal and the inbox side
        panel;
      - the new function.

      It builds after round 3, whose engine it uses.
    - Alternative: fewer rounds. Refused: too large for one review.

### H. Update From the Court on the case (round 4)

50. **A new grantable function, `cases.update_from_court`** ("Update Case From the Court": "Fetch a case's details
    and missing order PDFs from the court at once, ahead of other work. Each use spends court calls from the hourly
    allowance.").
    - **It is in the Case Work group.**
    - **The default is only the Super Administrator.** That membership always holds every function. In the seed's type
      matrix, every other type gets the row not granted. The owner wants to protect the daily limit.
    - **It is grantable** through the type matrix and per-user overrides, under the delegation rule (only a holder may
      grant it).
    - **No migration.** `ref_permission` and the type-matrix rows are upserted by the seed on `init` (the precedent of
      `admin.service_health` and `admin.data_load`). The pytest checks the seeded rows.
    - **`admin.napix_refetch` stays as it is** for Data Collection's Fetch Again. That is an operator's tool on the
      Collect Now tab; the case-level button is the owner's separate, scarcer power. Holding one does not imply the
      other.
    - Alternative: reuse `admin.napix_refetch`. Refused: the owner asked for the case button not to follow the Central
      Operator's function.
51. **Where it shows, to holders only:**
    - **The case page:** **Update From the Court** in the action rail (secondary, under the claim and custody actions),
      with "Last updated from the court: 21 Oct 2026, 14:05" (`last_full_refresh_at`) under it.
    - **The incomplete-details notice** on the case page's summary header, when details or orders are missing:
      - "Case details not fetched yet";
      - "3 orders not fetched";
      - "1 order not available at the court".

      This notice is shown to **everyone** who can see the case, because it is a fact about the record. The button
      only to holders.
    - **The large case details modal** (Case Claim, `claim/CaseModal.tsx`) and **the inbox side panel**: the same
      notice, and **Update From the Court** among the secondary actions.
    - **Beside each order without a stored PDF** (the case page's Orders tab, `case/Orders.tsx`, and the modal's
      order list, `claim/OrderRow.tsx`):
      - **Fetch Order** (`sm`, secondary) for holders;
      - "Not fetched yet" or "Not available at the court" for everyone;
      - an order the court marked not available gets **Try Again** instead.
    - **One primary per page holds:** these are secondary actions.
52. **What it does: the same immediate path as Collect Now's One Case** (decisions 23-25), at `NOW_ONE`, in the
    request lane, with the person in `requested_by`.
    - **Update From the Court** queues the case's dossier, then every order PDF the case lacks. They inherit "now"
      through `QueueOrigin`.
    - **Revised orders.** An order that appears in the court data with a new number or date is a new order row, and
      its PDF is fetched. A stored PDF is never fetched again: the court data gives no sign of a revision under the
      same number and date, so re-fetching would spend calls for nothing. This is said in the button's tooltip.
    - **Fetch Order** queues that one `order_pdf` row at `NOW_ONE`. For a `not_available` order it first sets the
      order back to `pending`, as `refetch_order` does.
    - **Live progress:** the button turns into the `CollectProgress` panel, in place: "Updating: case details done ·
      order PDFs 12 of 40", with the pulse. Fetch Order turns its row into "Fetching…".
    - **When it finishes,** the page invalidates the case's queries: summary, details, orders, documents, hearings and
      timeline. The tabs show the new data, and the notice and "Last updated" change, with a flash notice "Case updated
      from the court.".
    - **The update is visible in Data Collection's Requests** as "Updated From the Case Page" (decision 32).
53. **The rules, on the server** (`services/collect.py::update_case`, `fetch_order`):
    - **Function:** `require(cases.update_from_court)`, else 403 `forbidden`. The buttons are hidden without it, and
      the server refuses.
    - **Visibility:** `visibility.require_visible(user, case)`, the rule of the case page and the claim screens. A case
      the caller cannot see answers 404, as everywhere.
    - **A merged case** answers 409 `merged` with the target's reference. A case with no court reference answers 409
      `no_reference`. A stored order answers 409 `already_stored`.
    - **Double clicks.** The button is disabled while a request runs. On the server, an update of a case that already
      has a pending or running "now" request answers **200** with that request's id and `already_running: true`. It
      writes no second audit row and queues nothing. The queue's `(kind, ref)` upsert means nothing is ever doubled.
    - **The court's limit.** When the window's remaining count is known and 0, the answer is still 202 (the work is
      queued). The panel says "The court's hourly limit is used up; this update will run at about 16:35." While a bulk
      request uses everything, the update still goes first (3 before 5).
    - **The six NAPIX request slots are not used:** the worker makes the calls, so `napix_busy` cannot arise from these
      buttons. The note in the tooltip is therefore only about the hourly limit.
    - **Who spent the calls.** Each row carries the person in `requested_by`, so each call logs `user_id`. System
      Health's and Automatic Collection's Calls by Person show who spent the allowance.
    - **Audit:**
      - **`case.update_from_court_requested`** (case_id set; after `{request_refs, orders_missing, details_fetched_at}`);
      - **`case.order_fetch_requested`** (case_id set; after `{order_id, order_no, order_date, status_before}`).
    - **No event is raised** by the request itself. The dossier and the PDFs raise their usual events (`order_found`,
      `order_stored` and the alerts) when they arrive.
54. **No per-person count.** The function's default (Super Administrator only) is the owner's chosen control. The
    calls are visible by person. Alternative: an hourly cap per person. Refused: not asked, and the owner keeps
    control through the grant.
55. **The case detail answers say what is incomplete,** read only.
    - The orders read already carries `download_status` and `document_id` (`services/case_detail.py`), and the summary
      already carries `last_full_refresh_at` and `dossier_status`. The notice and the per-order labels use them.
    - The summary gains only `court_data: {orders_total, orders_missing, orders_not_available, update_running:
      request_id | null}`, counted from rows already held.
    - Visibility is unchanged: the same case readers.
56. **The progress read for the case:** `GET /cases/{ref}/court-update` (`cases.update_from_court`, the case visible)
    returns the latest "now" request of this case from the last hour, with the same states as decision 32. This
    serves holders who are not Data Collection readers.

## Changes From the First Version

**Changed**
- **Tabs:** seven become four (decision 1). Load becomes Automatic Collection; Fetch From the Court becomes Collect
  Now; Duplicates becomes a section of Problems and Fixes; Discovery becomes Search by Department Names; Health and
  Queue and Calls are removed (decisions 2-4).
- **Old decision 2** (the Fetch tab by the fetch functions) becomes decision 1's rule for Collect Now, now including
  `admin.masters_sync`.
- **Old decisions 18-21** (the Load tab) become decisions 34-39. Calls This Hour becomes Court Allowance, with Calls by
  Person moved in. Work Left becomes a line. Latest Problems moves to Problems and Fixes.
- **Old decisions 22-27** (fetch on demand, request lane at 30) become decisions 22-33:
  - manual requests run at the new "now" priorities, outside the reserves, worked by the worker at once;
  - One Case collects details and every order PDF before showing;
  - the bulk requests may use the whole allowance, one at a time, with Stop;
  - the endpoints become `/collect`, `/collect/day`, `/collect/list/check` and `/requests/{id}/stop`;
  - the audit actions become `data_load.collect_requested` and `data_load.collect_stopped`, replacing
    `day_details_requested` and `list_details_requested`.
- **Old decision 28** (Health as cards) is replaced by decision 3. **Old decision 29** (Queue and Calls) is replaced by
  decisions 3 and 44.
- **Old decisions 30 and 31** become decisions 44 and 41.
- **Old decision 33** (three rounds) becomes decision 49 (four rounds).

**New:** decisions 50-56 (Update From the Court, round 4) and decision 16 (the Problems line).

**Kept, renumbered:**

| Old decision | New decision |
|---|---|
| 3 | 5 |
| 4-10 | 7-13 |
| 11-17 | 14-21 |
| 25 | 33 |
| 26 | 32 |
| 27 | 48 |
| 32 | 47 |

## Data

**No new table, column, index or migration.**
- The request record is the existing append-only `audit_log` row.
- The "now" priorities are values of the existing `fetch_queue.priority` (smallint, no constraint).
- The new function `cases.update_from_court` is a `ref_permission` row and type-matrix rows written by the seed's
  upsert on `init`, as `admin.service_health` and `admin.data_load` were. `ref_permission` is a `ref_code` set, not
  a `pg_enum`.
- The reads use existing indexes:
  - `ix_orders_order_date`;
  - `causelists.list_date`;
  - `causelist_entries.causelist_id` and `case_id`;
  - `uq_fetch_queue_kind_ref`;
  - `ix_fetch_queue_claim`;
  - `ix_audit_log_action`;
  - `ix_audit_log_case_id`.
- If a later measurement needs an index, it is its own row and takes the next free number after main's highest
  (0027; rows 157 and 169 both plan 0028).
- **The `schema.md` paragraph** (round 4, in the functions list): "`cases.update_from_court` (design
  `data-collection-redesign`, round 4): Update Case From the Court, in Case Work; held by default only by the Super
  Administrator; grantable; no table or column."
- The seed upserts the new `admin.data_load` description and the new function.

## Services

None of these calls NAPIX directly. The worker fetches through the integration layer.

**Round 1** (`services/data_load.py` unless named)
- **`overview(session, cfg, now)`:**
  - `collection`, `period`, `position`, `days`, `cases`, `orders` (known, stored, waiting, failed, not available,
    `in_period`), `left`, `estimate`;
  - **`problems`**: `{failed, duplicates_review, cases_without_details, orders_not_available, orders_failed}`;
  - **`bulk`**: the active bulk request, or null. It is always null until round 3.
- **`estimate_all`:** `measure_all` over every queue lane, and `compute_two`. The old `measure` and `compute_estimate`
  stay.
- **`pulse(session, cfg, now)`:** window, queue counts by kind (every lane), running items with no refs, calls in
  the last 5 minutes, the last call, requests active.
- **`coverage`:** additive `state`, `left`, `orders.failed`, `cases.without_details`, `cases.queued`,
  `earlier_orders` and `position`; days counted up to today.
- **`services/schedules.py::PLAIN_SCHEDULE`** and **`schedule_view(session, now)`.**
- **`access_seed.py`:** the `admin.data_load` description.
- **CLI:** `aslms data-load status` prints the headline and the two estimate lines.

**Round 2**
- **`gaps(session, kind, limit, offset)`:** `cases` with their dossier-row state, `orders` not available or failed,
  and `documents_text`.

**Round 3**
- **`load_policy`:** `NOW_ONE = 3`, `NOW_BULK = 5`, and `QueueOrigin.now_priority`.
- **`queue`:** `claim(..., max_priority=None)` and `has_now(session)`.
- **`runner.Runner.run`:** the "now" claim first (remaining unknown or at least 1, the fault pause applying), then the
  bands. The claimed row's priority goes into `QueueOrigin`.
- **`cli/pipeline.worker_wait`:** 2 s slices, waking on `has_now`.
- **`services/collect.py`** (new module):
  - `check_day` and `check_list`, which write nothing;
  - `collect` (`cases`, `list`, `day`), with the 409 `bulk_running` check and one audit row
    `data_load.collect_requested`;
  - `stop`, with audit `data_load.collect_stopped`;
  - `requests` and `request_items` over the audit rows of `data_load.collect_requested`, `napix.refetch_requested`,
    `napix.masters_sync_requested`, `data_load.details_requested` (which gains `refs`) and, from round 4,
    `case.update_from_court_requested` and `case.order_fetch_requested`;
  - `active_bulk`.
- **`napix_admin`:** `refetch_day`, `refetch_case`, `refetch_order` and `sync_masters` enqueue at `NOW_ONE`.
- **`court_search.guard`:** the `napix_budget` message names an active bulk request.
- **CLI:** `aslms data-load collect --date D [--all] [--dry-run]` and `aslms data-load stop <request-id>`.

**Round 4**
- **`services/collect.py::update_case(session, actor, user, case)`:**
  - checks the function and visibility, merged and no-reference cases, and the running-request answer;
  - queues the dossier at `NOW_ONE`;
  - audit `case.update_from_court_requested`.
- **`services/collect.py::fetch_order(session, actor, user, case, order_id)`:**
  - checks the function and visibility, and `already_stored`;
  - sets a `not_available` order back to `pending`;
  - queues the order at `NOW_ONE`;
  - audit `case.order_fetch_requested`.
- **`services/collect.py::case_update_state(session, case)`:** for the progress read and `court_data.update_running`.
- **`services/case_detail.py`:** `court_data` on the summary.
- **`access_seed.py`:** `cases.update_from_court` in `PERMISSION_LABELS` (Title Case label), in the Case Work group,
  with no type default.
- **`domain/reference.py`:** `Permission.CASES_UPDATE_FROM_COURT`.

## API

Times are in IST. No endpoint below calls NAPIX. The existing search `POST /admin/data-load/fetch` is the only
Data Collection endpoint that does.

| Method and path | Function (`Permission`) | Round | Request | Response |
|---|---|---|---|---|
| `GET /admin/data-load/overview` | any of `data_load.READERS` | 1 | — | `DataLoadOverviewOut` |
| `GET /admin/data-load/pulse` | any of `data_load.READERS` | 1 | — | `DataLoadPulseOut` |
| `GET /admin/data-load/coverage` (existing) | unchanged | 1 | unchanged | additive keys |
| `GET /admin/data-load/schedule` | any of `data_load.READERS` | 1 | — | `DataLoadScheduleOut {entries: [{key, when, what, last_run_at, result, facts}], daily_cycle}` |
| `GET /admin/data-load/gaps?kind=cases\|orders&limit&offset` | any of `data_load.READERS` | 2 | — | `DataGapsOut {kind, total, items, documents_text}` |
| `GET /admin/data-load/collect/day?date=&scope=never\|all` | `admin.data_load` | 3 | — | `CollectDayCheckOut`; 400 `no_lists`, `date_in_future`, `too_many` |
| `POST /admin/data-load/collect/list/check` | `admin.data_load` | 3 | `{lines (1-200), force}` | `CollectListCheckOut`; writes nothing |
| `POST /admin/data-load/collect` | `admin.data_load` | 3 | `{kind: "cases", refs (1-20)}`, `{kind: "list", lines, force}` or `{kind: "day", date, scope}` | 202 `CollectOut {request_id, kind, to_fetch, queued, already_waiting, left_out, priority, expected_end}`; 409 `bulk_running`; audit `data_load.collect_requested` |
| `POST /admin/data-load/requests/{id}/stop` | `admin.data_load` | 3 | — | `CollectStopOut {request_id, moved}`; 409 `not_running`; audit `data_load.collect_stopped` |
| `GET /admin/data-load/requests?limit=20` | any of `data_load.READERS` | 3 | — | `CollectRequestsOut` |
| `GET /admin/data-load/requests/{id}?limit=100&offset=0` | any of `data_load.READERS` | 3 | — | `CollectRequestOut`; 404 `not_found` |
| `POST /cases/{ref}/update-from-court` | `cases.update_from_court`, the case visible | 4 | — | 202 `CaseUpdateOut {request_id, already_running: false, window_remaining, resumes_at?}`, or 200 with `already_running: true`; 404 (not visible), 409 `merged`, `no_reference`; audit `case.update_from_court_requested` |
| `POST /cases/{ref}/orders/{order_id}/fetch` | `cases.update_from_court`, the case visible | 4 | — | 202 `CaseUpdateOut`, or 200 with `already_running`; 404, 409 `already_stored`, `no_reference`; audit `case.order_fetch_requested` |
| `GET /cases/{ref}/court-update` | `cases.update_from_court`, the case visible | 4 | — | `CaseUpdateStateOut {request_id?, states, finished, steps: {details, orders: {stored, total, not_available}}}` |
| `GET /cases/{ref}` (existing) | unchanged | 4 | — | gains `court_data` (additive); the orders read is unchanged (it already carries `download_status` and `document_id`) |

- **The existing re-fetch and reference-list endpoints** queue at `NOW_ONE` from round 3; their answers and audit are
  unchanged.
- **Unchanged:** `GET /admin/data-load`, preview, start, pause, resume, order, fetch, fetch-details, duplicates,
  `/admin/discovery*`, `/admin/napix/*` reads.
- **`CaseBrief`** is `{id, ref_no, cnr, case_no_text}`.

## Jobs

**No new scheduled job.**
- Round 3 changes the runner's claim (the "now" rows first, outside the bands) and the worker's sleep (it wakes
  within 2 s).
- The beat schedule is unchanged; `PLAIN_SCHEDULE` describes it, and a test keeps them in step.

## Tests

**pytest, round 1:**
- `test_overview_counts_days_cases_and_orders_of_the_period`
- `test_overview_left_counts_order_pdfs_in_every_lane`
- `test_overview_position_is_the_earliest_waiting_load_day`
- `test_overview_states_running_paused_finished_not_started_and_gateway_off`
- `test_overview_problem_counts`
- `test_overview_orders_in_period_and_all_add_up`
- `test_overview_pulse_schedule_need_a_reader_function`
- `test_overview_pulse_coverage_schedule_write_nothing_and_call_no_napix`
- `test_pulse_counts_the_queue_across_lanes_without_refs`
- `test_coverage_left_uses_the_columns_own_dates`
- `test_coverage_state_done_in_progress_not_reached_failed_days_not_in_load`
- `test_coverage_counts_days_only_up_to_today`
- `test_coverage_earlier_orders_and_months_add_up`
- `test_coverage_keeps_work_left_and_failed`
- `test_estimate_all_every_lane_details_before_order_pdfs`
- `test_estimate_all_reasons`
- `test_plain_schedule_matches_celery_beat_schedule`
- `test_schedule_view_last_runs_and_daily_cycle`
- `test_admin_data_load_description_seeded`

**pytest, round 2:**
- `test_gaps_cases_states_being_fetched_not_found_failed_not_queued`
- `test_gaps_orders_not_available_and_failed`
- `test_gaps_paged_and_reader_only`
- `test_gaps_include_documents_text`

**pytest, round 3:**
- `test_now_rows_are_claimed_below_the_live_reserve_and_ignore_the_discovery_share`
- `test_now_rows_stop_only_at_the_courts_limit`
- `test_one_case_now_row_runs_before_a_bulk_now_row`
- `test_now_dossier_spawns_every_missing_order_pdf_at_the_same_priority`
- `test_now_day_spawns_new_dossiers_at_the_same_priority`
- `test_now_rows_log_calls_under_the_person`
- `test_worker_wait_wakes_within_two_seconds_for_a_now_row`
- `test_fault_pause_still_applies_to_now_rows`
- `test_collect_cases_queues_dossier_and_pdfs_skipping_fresh_dossier`
- `test_collect_cases_caps_at_20`
- `test_check_list_reads_cnr_reference_number_and_refuses_text`
- `test_collect_list_unknown_cnr_queued_unknown_number_not_held`
- `test_collect_list_caps_at_200`
- `test_check_day_counts_and_writes_nothing`
- `test_collect_day_never_and_all_with_the_6_hour_rule`
- `test_collect_day_uses_current_lists_only`
- `test_collect_day_refuses_no_lists_future_and_over_2000`
- `test_second_bulk_is_409_bulk_running_one_case_still_allowed`
- `test_collect_writes_one_audit_row_with_refs`
- `test_collect_needs_admin_data_load`
- `test_stop_moves_pending_bulk_rows_to_30_keeps_running_rows_and_audits`
- `test_stop_needs_admin_data_load_and_a_running_bulk`
- `test_requests_list_states_and_spawned_order_pdfs`
- `test_request_finished_when_nothing_ready_or_running`
- `test_requests_include_refetch_and_masters_rows`
- `test_refetch_and_sync_masters_queue_at_now_one`
- `test_court_search_refusal_names_the_active_bulk_request`

**pytest, round 4** (`tests/db/test_case_update_from_court.py`, `tests/unit/test_access_seed.py`):
- `test_update_from_court_function_seeded_for_no_type_super_admin_holds_it`
- `test_update_from_court_label_title_case_in_case_work_group`
- `test_update_from_court_grantable_by_override_under_the_delegation_rule`
- `test_update_case_403_without_the_function`
- `test_update_case_404_when_the_case_is_not_visible`
- `test_update_case_409_merged_and_no_reference`
- `test_update_case_queues_dossier_at_now_one_in_the_request_lane_with_the_person`
- `test_update_case_runs_before_daily_load_and_a_bulk_request` (claim order 3 < 5 < 20 < 40)
- `test_update_case_spawns_every_missing_order_pdf_at_now_one`
- `test_update_case_twice_returns_the_running_request_no_second_audit`
- `test_update_case_writes_audit_with_case_id`
- `test_fetch_order_queues_one_order_and_resets_not_available`
- `test_fetch_order_409_already_stored`
- `test_fetch_order_403_and_404`
- `test_case_summary_court_data_counts`
- `test_court_update_progress_states`
- `test_update_calls_log_user_id_of_the_person`

**vitest, round 1:**
- **kit:** ProgressBar, ProgressLegend, reduced motion, ScrollBox, hidden captions;
- `styles.test.ts` and the `tables.test.ts` companion;
- **`data.test.tsx`:**
  - four tabs and their functions; `/data` opens Overview;
  - the round 1 redirects;
  - the Overview tiles, bars, Problems line, Waiting Work, Right Now, polling intervals and no background polling;
  - "Updated n s ago";
  - the month table;
  - the estimate with no JSON;
  - Automatic Collection's one primary, "Nothing new to fetch", the Pause reason, the What Goes First fieldset,
    Calls by Person only when sent, the schedule, the department-names empty state;
  - no doubled heading;
- `dashboard.test.tsx`, `routes.test.ts` and `labels.test.ts`.

**vitest, round 2:**
- the Problems and Fixes sections, counts and empty states;
- Retry and Retry All by function;
- the Court Connection line;
- the duplicates switch;
- the gaps tables with Collect These and Try Again by function;
- the System Health Court Calls section only with both functions;
- the old tabs gone with their redirects.

**vitest, round 3:**
- One Case: CNR collects at once; `CollectProgress` steps; the result only when finished;
- the list and day checks;
- the "use everything" panel;
- `bulk_running`;
- requests' bars, Stop's confirm, the items panel, the refresh intervals.

**vitest, round 4** (`case.test.tsx`, `rail.test.tsx`, `claim.test.tsx`, `inbox.test.tsx`):
- Update From the Court and Fetch Order are hidden without `cases.update_from_court`, and shown with it, on the
  rail, the modal, the side panel, the Orders tab and `OrderRow`;
- the incomplete notice is shown to every reader, with "Case details not fetched yet" and "3 orders not fetched";
- "Last updated from the court" is shown;
- the button turns into the progress panel; a double click sends one request; the `already_running` answer
  re-attaches to the running request;
- on finish, the case queries are invalidated and the flash notice shows;
- the limit-used-up message;
- Fetch Order turns its row into "Fetching…", and Try Again is shown for not available.

**uicheck:**
- `gutter` and `doubled-heading` on every page at 375, 768 and 1280 px, with self pages;
- the four `/data` routes as page routes, and the old addresses as redirects;
- fixtures with long values;
- **states, each at three widths:**
  - round 1: `data-overview-running`, `data-automatic-start-new`, `data-automatic-start-nothing-new`,
    `data-automatic-pause-dialog`, `data-automatic-priority`, `data-automatic-no-department-names`;
  - round 2: `data-problems-all-sections`, `system-court-calls`;
  - round 3: `data-collect-one-case-progress`, `data-collect-one-case-result`, `data-collect-day-check`,
    `data-collect-list-check`, `data-collect-bulk-running`, `data-collect-stop-dialog`;
  - round 4: `case-update-button` (a holder on a complete case), `case-incomplete` (the notice, with Fetch Order on
    three orders), `case-update-running` (the panel in the rail), `claim-modal-incomplete` (the modal with the notice
    and the button).

## Verification

1. **Each round:** `ruff check` clean and `pytest -q` green; `npm run lint`, `npm run typecheck` and `npm test` green.
2. **Round 1, the figures** (dev; counts move as the worker runs):
   - `orders.waiting` = `select count(*) from orders where download_status='pending' and document_id is null`
     (182,929 on 26 Oct), and it equals `left.order_pdfs` and the pending plus running `order_pdf` rows;
   - `position.working_on_month` = `2026-01`;
   - October 2025 has `left.order_pdfs` about 5,291; February to September 2026 are `not_reached`; the months plus
     `earlier_orders` equal `orders.known`;
   - the estimate's calls an hour is about 820.
3. **Round 1, on screen:**
   - Overview opens first, and `/data/load` lands on Automatic Collection;
   - a hidden tab makes no `/pulse` request;
   - "Nothing new to fetch" over held dates;
   - the department-names empty state;
   - Title Case headers;
   - no motion with reduce motion on.
4. **Round 2:**
   - the old addresses land on their new places;
   - as a Central Operator: Retry and Check the Court Connection work, Collect Now shows only their cards, and
     `/system` is not in their menu;
   - as the Super Administrator: `/system#calls` shows the resets, e-mail and the call log.
5. **Round 3** (with `NAPIX_ENABLED=true` for that run only, with the owner's go-ahead):
   - One Case by CNR shows the steps, and the result appears only at the end; its rows are priority 3 in the
     `request` lane;
   - a day's Every Case Listed runs past the 150 and 100 reserves;
   - another user's search below 50 calls left gets the message naming the request;
   - Stop moves the rest to 30 and writes `data_load.collect_stopped`;
   - the daily lists and the load resume after.
6. **Round 4** (live, the same conditions):
   - as the Super Administrator, on a case with missing orders: the notice shows; **Update From the Court** shows the
     panel and the calls appear in the log with `user_id` = the Super Administrator and priority 3;
   - the tabs refresh with the new orders, and "Last updated" changes;
   - **Fetch Order** on one order stores it;
   - as a Department Officer, the notice shows but no button, and `POST /cases/{ref}/update-from-court` answers 403;
   - after granting the function to one officer by override, the button appears for that officer only, and
     `GET /audit?action=case.update_from_court_requested` lists their use.
7. **The browser check, each round:** `docker compose --profile uicheck run --rm uicheck`. No finding on any page,
   and the new states pass.
8. **The owner's browser check of the four rounds** at 375, 768 and 1280 px becomes a separate backlog row at
   approval.

## Open questions

None. The owner's re-approval covers in particular:
- decision 3: where each piece of Health and Queue and Calls goes, and dropping the table sizes;
- decision 4: the Central Operator and State Oversight Officer no longer see the raw call log or the mail outbox;
- decision 23: the worker at the top of its queue, not inside the web request;
- decision 24: the "now" priorities 3 and 5, outside the reserves;
- decision 30: what others experience during a bulk request, and one bulk at a time;
- decision 31: Stop returns the rest to the normal turn instead of dropping it;
- decision 50: `cases.update_from_court` held by default only by the Super Administrator, with
  `admin.napix_refetch` unchanged;
- decision 52: stored PDFs are not fetched again;
- decision 49: the four rounds.

## Deviations

**Round 1 (row 172, developer, 27 Oct 2026).** Where the note was silent, the smallest reasonable choice:

1. **Problems links before round 2.** Problems and Fixes does not exist yet, so the Problems line (decision 16) links
   the failed fetches to `/data/queue?status=failed` and the possible duplicates to `/data/duplicates`; cases without
   details and orders not available are plain text until round 2 points every part at `/data/problems#…`
   (`PROBLEM_LINKS` in `src/lib/dataCollection.ts`). The month table's Problems cell and Load Control's failed count
   link to the queue's failed rows the same way.
2. **The pulse's `requests_active`** counts the request-lane rows pending or running. Round 3 replaces it with the
   count of active requests once requests are records.
3. **The hourly limit seen** (Right Now, the basis line) is the highest `rate_limit_remaining` read in the last 24
   hours plus the call that read it; null with no reading.
4. **The estimate's rates** (`measure_all`): calls per item, finished items and PDFs per case from every queue lane;
   cases per cause-list day from the load lane (a daily or weekly dossier is not spawned by a day), falling back to every
   lane; the pace is the queue calls of the last 24 hours. `pending` counts pending and running rows. While paused only
   the details line has no date (as decision 21 says); the order-PDF line keeps its date. A line with nothing waiting
   reads "nothing left" whatever else holds.
5. **The Overview's cause-list days** run from the load period's first day to the later of its last day and today, in
   any lane (the daily cycle collects the recent days). Orders `in_period` are those dated inside the load period.
6. **Month by Month's default range** is the load period's first month to the later of its last month and this month,
   at most 36 months (older orders fall into `earlier_orders`), so the months plus `earlier_orders` add up to every
   order known. The two existing tests that pinned "the default range is the load period" were updated.
7. **The month state rules** (decision 19): `done` when every day up to today is collected; `failed_days` when some
   failed and none waits; inside the load period, `not_reached` after the month the load works on, `in_progress` at it
   or while a day waits; otherwise `in_progress` while a day waits, else `not_in_load`. A month after today has 0 days.
8. **Cases queued and failed** (decision 20) match a dossier row by CNR, or by `<est_code>|<case number>` for a
   provisional case (`napix_admin.dossier_ref`). `cases.failed` counts a case without details whose dossier row failed
   and none waits; the month's Problems cell uses it.
9. **Daily Updates, Last 7 Days** are today and the six days before it (`data_health.daily_cycle` gained `back` and
   `forward`, defaults unchanged), shown newest first. A done day with no list stored, or a skipped day, reads "No List
   Published".
10. **The schedule's Last Run** comes from `job_runs` only for the jobs that write one (`disposed-refresh`,
    `dedupe-sweep`, `napix-log-purge`); the others read "Not Recorded". The plain words live on the server
    (`schedules.PLAIN_SCHEDULE`); `schedules.NOT_DATA_COLLECTION` names the beat entries that are not data collection,
    and the test checks that the two together are exactly the beat schedule, at the times the words give.
11. **Health in round 1.** Its re-fetch forms and Sync Masters moved to Collect Now rather than being shown twice; the
    connectivity check stays on Health until round 2 moves it to Problems and Fixes. Everything else on Health, Queue
    and Calls and Duplicates is unchanged.
12. **Collect Now's reference-list table** reads the lists' last update from `GET /admin/data-health` (whose guard
    already admits `admin.masters_sync`); Automatic Collection's Calls by Person reads `GET /admin/napix/health` only
    for `admin.napix_refetch` or `admin.masters_sync`, the API's existing rule. No API change.
13. **Upper case** was also removed from `causelist.module.css` and `claim.module.css`, found by the new
    `styles.test.ts` though not listed in decision 8. Every source string these classes show was already Title Case.
14. **Captions shown** (decision 10), for tables with no visible heading of their own: User Details' functions and
    documents, Keywords' words, the audit entry's Before and After, the transfer directions, the dashboard's recent
    orders, own cases, files, tickets by kind and by department, the overdue-files split, Tracking Summary's two tables,
    the search results and the text search. Every other caption is hidden.
15. **Removed components.** `LoadConsole.tsx` (its fetch form moved unchanged into `CollectNow.tsx`, its load controls
    became Automatic Collection's dialogs) and the Discovery tab's `Discovery.tsx` (now `DepartmentNames` in
    `AutomaticCollection.tsx`).
16. **`aslms data-load status`** prints the headline and the two estimate lines; `--json` keeps the old progress JSON.
17. **uicheck.** The two rules are geometry kinds (dropped on a redirect like the others). The fixtures' stress row
    carries a long `last_error` and a long API path. The Start dialog's check `POST /admin/data-load/preview` (it
    writes nothing and calls no court) is the one POST the checker answers, so the two Start states can be drawn; the
    `/admin/discovery` fixture has no names registered, as the dev database today. The old Load, Discovery and Fetch
    addresses are checked as redirects (the anchor of `/data/automatic#department-names` is not part of the landed path).
18. **The 3 px gutter (D1)** was not reproduced against the live data in this cycle (no browser run against the dev
    database). By reading: `DataFrame` rendered a bare `<div>` and panels held unbroken values (the estimate's raw
    JSON, long errors, API paths) without `overflow-wrap`; decision 7's changes remove both, and the `gutter` rule now
    measures every page.
19. **Collect Now's One Case results** (resumed build, 27 Oct 2026): the results table sits in a `ScrollBox` (decision
    10, a party-name search can return many rows), and an empty answer reads "The court found no case for this
    search." in place of "Nothing to show." (D5). The rest of the card is moved unchanged until round 3.
