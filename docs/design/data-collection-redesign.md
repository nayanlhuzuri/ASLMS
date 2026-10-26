# Design: Data Collection redesign (every tab, honest progress, live figures, fetch on demand)

```
slug: data-collection-redesign
status: awaiting-approval
author: architect
date: 2026-10-26
approved_by:
```

## Context

**The owner's requests of 26 Oct 2026**, made while looking at Data Collection (backlog row 172):

1. On the Backdated Load page, "the UI for the whole page looks very bad. Change it as we discussed previously", and
   "if the orders stored is not completed then why is it showing 100% or 99.9%?".
2. "Where is the page where I can check how much data has been collected and what is left?"
3. The collected and left figures and the progress should update live while work is queued.
4. Fetching on demand should sit in one clear "Fetch From the Court" area. The owner also wants a new action:
   "refresh the details of every case listed on 23 Oct 2026", and a way to give several cases at once.
5. On a screenshot of the Load tab's Actions section: "this is all misaligned. Correct it and categorise it properly,
   with progress bars and animations".
6. On a screenshot of Health: "this whole page also looks misaligned. What did you even correct? Check all the Data
   Collection tabs, as I see those issues on every page."

"What we discussed previously" means the agreed portal design work:
- the templates of rounds 1 to 5 (`portal-ui-redesign.md`, decision 26: Data Collection on the Dashboard template);
- `portal-ui-polish.md`: every list a `DataTable` that stacks as cards on phones, and `uicheck`;
- `portal-ui-polish-2.md` (approved 25 Oct, built in rows 153, 162 and 163):
  - Title Case labels with the label guard (decisions 1-6);
  - Filter Layout B, `FilterCard` (decisions 21-23);
  - the checkbox and field-row rules (decision 26);
  - the Office Picker (decision 28);
  - one primary per page (decision 47);
- the owner's Department Mapping changes of 26 Oct 2026 (decisions log, "Department Mapping layout, owner changes"):
  - a long list scrolls inside its own box, at most min(60vh, 560px), as a labelled region the keyboard can reach;
  - one clear row per item.

The visual reference is the approved `docs/design/ui/aslms-nav-template.html` and the as-built kit. The owner said
designs need no mockup.

**Rows 153, 162 and 163 never laid out the Data Collection tabs.** Only the Queue got Filter Layout B (row 163). The
tabs still have the round 5 layout of `data-load-console` (decision 19) and `audit-screens`, with loose lines of text,
doubled headings and technical words. This item redoes every tab: Load, Health, Queue and Calls, Duplicates and
Discovery. It adds two tabs: Overview, the owner's "how much is collected and what is left" page, and Fetch From the
Court.

### What the figures say today, checked in the code and the dev database on 26 Oct 2026

- **"With Details" is not about orders.** In `services/data_load.py::_month_figures`, `details_pct` is
  `cases.with_details / cases.listed`: the cases listed that month whose case details were fetched
  (`last_full_refresh_at`). It is 99.9% for most months.
- **"Orders Stored" is a separate column**, `orders.stored / orders.referenced` by `order_date`, for example 3,055 /
  8,346 in October 2025. Read side by side, 99.9% next to 3,055 / 8,346 looks as if the orders were complete.
- **The orders' own progress is already in the data but not on the screen.** `_order_totals` returns `waiting` and
  `not_available`, and the screen never shows them. `failed` (`download_status = 'failed'`) is not counted at all.
  - In the dev database: 320,869 orders are known, 137,932 PDFs are stored, 182,929 are waiting and 8 are not
    available at the court.
  - **Every waiting order has a live queue row.** A check found 0 waiting orders without a pending or running
    `order_pdf` row. So "orders waiting" counted from `orders` by `order_date` is exactly what is left for those
    orders, in every lane.
- **"Left" counts the wrong rows.** It counts only `fetch_queue` rows of the `load` lane by `list_date`. An order PDF
  row carries the listing date that queued it, not the order's date, and most order PDF rows are in the `daily` lane:
  167,398 pending there against 15,531 in the load lane. So October 2025 shows Left 0 while 5,291 of its orders
  wait.
- **The load works through the dates in order and is now at January 2026.** The earliest waiting load day is
  2026-01-05, and 267 cause-list days are pending up to 2026-09-29. So February to September 2026 show 0% of days
  covered, yet thousands of orders: these are orders of cases found in earlier months. Nothing says "not reached
  yet", so it looks like a failure.
- **The estimate leaves out most of the work.** `measure` and `compute_estimate` use the load lane only: its pending
  rows and its calls per hour (about 248 in the last 24 hours). The 167,398 order PDFs in the daily lane are not in
  it.
  - Across lanes the worker made about 900 calls in each full hour (901-913 per hour in the last 12 hours). The
    court allows about 1,000 an hour, and ASLMS keeps 100 for daily updates and searches (`NAPIX_LIVE_RESERVE`).
  - The queue runs by priority: daily dossiers 40, load dossiers and days 41-46, then order PDFs at 60 (live cases)
    and 80 (others). So cause lists and case details finish well before the order PDFs.
- **The month's day count includes future days.** `_day_totals` counts every calendar day of the month, so the
  current month can never reach 100%.
- **The queries are cheap enough to refresh often.** On the 2.6 GB dev database:
  - the period's case totals take 57 ms;
  - the order totals 25 ms;
  - the queue counts by kind, lane and status over 381,832 rows 28 ms;
  - the call-log count for 24 hours 3 ms.
- **Per-day case counts, for the fetch-a-day action:** a day's current lists hold up to 1,191 distinct cases (7 Oct
  2026), 708 on average.

### Defects, tab by tab

The 25 Oct uicheck screenshots (`data/uicheck/20261025-1404`) and the components were read for this list.

**Every tab (`DataFrame.tsx`, `data.module.css`)**
- D1. **No page gutter on the owner's screen.** The breadcrumb, title and tabs start about 3 px from the edge.
  - The fixture screenshots of 25 Oct show the normal 24 px gutter at 375, 768 and 1280 px. So the cause is the live
    data, not the frame. The likely cause is an element wider than its column that makes the content area scroll
    sideways: a long unbroken `last_error`, an API path, the estimate's JSON `pre`, or a table of eight number
    columns.
  - `DataFrame` also renders a bare `<div>` with no page `stack`, unlike `AdminFrame`.
  - The page-overflow check in `uicheck` cannot see it, because the fixtures' values are short.
- D2. **Doubled headings.** Each panel's `<h2>` repeats as the `DataTable`'s visible caption:
  - Work Left, Latest Failures, Coverage Month by Month and Results on Load;
  - Calls by User, Queue, Daily Cycle and Document Text on Health;
  - Queue Rows and Call Log on Queue and Calls;
  - the failures table on Discovery.
- D3. **Uppercase table headers** ("KIND", "PENDING", "THIS WINDOW"). This comes from the kit's
  `components/ui/data.module.css` (`.table th { text-transform: uppercase }`). It goes against the owner's Title Case
  rule, and the approved nav template sets `text-transform: none` on every table header.
- D4. **Two-column boards with unequal panels.** A short panel sits beside a tall one, leaving a large empty area.
  Tables of six or more number columns stack as cards inside a half-width panel at 1280 px (Latest Failures, Daily
  Cycle).
- D5. **Empty states say "Nothing to show."** (`T.data.noDuplicates`) on the queue, calls and fetch results.
- D6. **Technical words:**
  - "This Window", "Court Gateway Allowance, This Window" and "Precise";
  - "The queue worker's switch is set in its own environment.";
  - the lane names "Requests" and "Backdated Load";
  - "Masters", "Jobs" and "Status Batches";
  - raw status codes (`pending`, `skipped`) and raw job codes.

**Load (`LoadConsole.tsx`)**
- L1. **Status** is a panel of loose lines: a badge, "changed by", the reason, the switch note and the period.
- L2. **The allowance** is five headline numbers in a 2 + 2 + 1 grid, then three loose lines. The thresholds are a
  technical sentence.
- L3. **Work Left** covers the load lane only, and its title does not say so.
- L4. **Estimated Finish** covers the load lane only (see Context), and "How This Was Worked Out" prints raw JSON.
- L5. **Coverage Month by Month** is hidden behind "Show Coverage". It has the misleading columns described above,
  bare percentages, Left counted from one lane, no "not reached yet", and the month as `2026-01` in monospace. The
  Days list shows raw statuses.
- L6. **Actions** (the owner's screenshot):
  - the two columns are unbalanced: Start a Load on the left, Pause alone on the right with a bare reason box and a
    pale button;
  - the preview is two loose lines, then a full-width select, then a primary Start even when 0 calls are needed;
  - What Goes First has a very wide select, the second date wraps alone onto the next row, the Reason box spans the
    width and Save sits under it, with no grid;
  - Fetch From the Court is squeezed at the bottom;
  - every heading has the same weight, with no grouping.
- L7. The fetch results' Details column shows the raw `dossier_status`.

**Health (`Health.tsx`)**
- H1. **"Period Report"** floats alone above the cards.
- H2. **Court Gateway:**
  - two small number tiles bunched at the left;
  - loose lines for the window, the calls remaining, the last call and the last check;
  - Recent Resets as a bullet list ("15:36: 98 → 999") with a stray "Precise" tag.
- H3. **Calls by User** spans the full width for one or two rows, with the numbers far to the right.
- H4. **Queue** is a table of eight columns with lane names as headers (doubled heading, D2).
- H5. **Masters, Jobs, Mail Outbox and Open Failures** are bullet lists or bare text: "1,23,456 / 1,23,456" with no
  labels, and job and failure codes in monospace.
- H6. **Retention** is a bullet list of sentences.
- H7. **Actions** mixes system checks (Sync Masters, Connectivity Check) with three re-fetch forms that belong with
  fetching.
- H8. Daily Cycle stacks as cards in a half-width panel and shows raw statuses (`done`, `skipped`).

**Queue and Calls (`Queue.tsx`)**
- Q1. Two long tables are stacked one after the other with no box, so the page runs very long. They have doubled
  headings.
- Q2. Statuses are raw codes, and Priority is a bare number.
- Q3. The call log shows API paths, HTTP codes and "OK" for a non-technical owner. Empty states say "Nothing to
  show.".

**Duplicates (`Duplicates.tsx`)**
- U1. The three kinds are chips, with no line saying what each one means.
- U2. Scan Now sits beside the chips with no hint of what it does.
- U3. The table is not boxed, the case and the other case are stacked inside cells, and the empty state is generic.

**Discovery (`Discovery.tsx`)**
- V1. One panel holds everything: a share sentence, the window line, the year line, five headline numbers, "last
  searched", a table, a button and a second table.
- V2. The share of court calls is a sentence, with no bar.
- V3. Sweep Every Name Now sits in the middle of the panel, between two tables.

**Elsewhere in the portal.** A source scan found the same pattern, a `DataTable` caption equal to a heading or card
title in the same file, in:
- Designations, Tickets (documents), Users, and Mapping (Counsel Codes, Watchlist, Court Search, Scoring's own-weight
  list);
- the case page (Details, Documents, Hearings, Parties, Next Date);
- the dashboard blocks;
- Profile (devices);
- System Health (the API panel and the console);
- the case's Custody tab.

Some may already hide their caption. The new uicheck rule (decision 9) confirms each one. Decision 7 fixes them all at
once. The gutter defect could not be reproduced with fixtures. The new rule runs on every page, and the build report
lists any page it flags.

### What this item does not cover

- No change to who may see or do anything. The existing functions guard every read and write (decision 27).
- No migration. No change to the load's policy, the queue's priorities or the scoring.
- System Health (`/system`) keeps its own layout. It gets only the portal-wide kit changes (decisions 6-9).

## Decisions

### A. The structure of Data Collection

1. **Seven tabs, Overview first.** The tabs, in this order:

   | Tab | Address | Shown with | Holds |
   |---|---|---|---|
   | **Overview** | `/data/overview` | the readers (`DATA_READERS`, today's rule) | Progress: the headline block (decision 11), Right Now (decision 14), the estimate, Month by Month (decision 15) |
   | **Load** | `/data/load` | the readers | the Load Control and Priority cards, Calls This Hour, Past-Months Load Waiting, Latest Problems (decisions 18-21) |
   | **Fetch From the Court** | `/data/fetch` | `admin.data_load` or `admin.napix_refetch` | every on-demand fetch, and the requests with their progress (decisions 22-26) |
   | **Health** | `/data/health` | the readers | the court connection, daily updates, checks and housekeeping (decision 28) |
   | **Queue and Calls** | `/data/queue` | the readers | the work items and the court calls (decision 29) |
   | **Duplicates** | `/data/duplicates` | the readers | as today, laid out (decision 30) |
   | **Discovery** | `/data/discovery` | the readers | as today, laid out (decision 31) |

   - `/data` opens the first tab the login may open, which is now Overview.
   - The side menu's Data Collection children follow `DATA_TABS` (portal-ui-polish-2, decision 15), so they show the
     new tabs with no other change.
   - The owner's four groups are placed like this:
     - **Progress** is the Overview tab: the first thing the owner sees and the answer to "where is the page";
     - **Load Control** and **Priority** are the Load tab;
     - **Fetch From the Court** is its own tab.
   - Alternative: the headline block above the Load tab's cards. Refused: the owner looked for this page and did not
     find it under "Load", and the Load tab's controls are for the Super Administrator alone.
   - Alternative: one long page. Refused: about 15 cards on one page is what the owner complained of.
2. **The Fetch tab shows by the fetch functions, not by the read rule.** A reader with only `reports.state` cannot
   fetch anything, so the tab would be empty for them. Each card inside shows by its own function. This is navigation
   only: every endpoint keeps its own check.
3. **The State dashboard links to Overview.** The State block's action area gets a **"Data Collection Progress"**
   link to `/data/overview`, shown when the login holds a reader function (`canAny(me, DATA_READERS)`).
   - No figure is added to the dashboard, so it makes no extra query and needs no new rule.
   - Alternative: a progress tile on the dashboard. Refused: it would add the overview queries to every State
     dashboard load, for the few people who need it.

### B. Portal-wide kit changes (asked by the owner: "check for all")

4. **Every tab keeps a page gutter.**
   - `DataFrame` renders `<div className="stack">`, like `AdminFrame`.
   - Every Data Collection card has `min-width: 0`.
   - Long unbroken values (errors, references, API paths) get `overflow-wrap: anywhere` in their cells.
   - The raw JSON block goes (decision 17).
   - The developer first reproduces the owner's 3 px gutter with the live data at the owner's width, and records the
     cause in the report.
   - The uicheck rule (decision 9) and long values in the fixtures (`synth.ts`: a 300-character `last_error`, a long
     API path, a long reference) keep it from coming back.
5. **Table headers and other small labels are no longer upper case, portal-wide** (owner, decided twice: "the first
   letter of each word is capital").
   - `text-transform: uppercase` and its `letter-spacing` go from:
     - the kit's `.table th` and `.dateChip span` (`components/ui/data.module.css`);
     - the shell's `.gov` and `.groupLabel` (`shell.module.css`);
     - `admin.module.css:320`, `assistant.module.css:105` and `:204`, `auth.module.css:51` and `:156`,
       `calendar.module.css:62`, `case.module.css:55`, `rail.module.css:36` and `:67`, and `remarks.module.css:108`.
   - This matches the approved nav template, which sets `text-transform: none` on the brand line, the menu groups,
     table headers, list header rows and fact keys.
   - **It touches every table, menu group and fact label in the portal.** The text itself is already Title Case
     (`labels.test.ts`). The developer checks each changed place by eye, and a source string that shows in lower
     case is fixed in `messages.ts`.
   - Header weight and colour stay (600, `--text-3`).
   - **A guard:** a new vitest `components/styles.test.ts` fails on any `text-transform: uppercase` in `src/**/*.css`.
   - Alternative: change only the Data Collection tables. Refused: the owner's rule is portal-wide, and one rule for
     one area would leave the mismatch everywhere else.
6. **A kit `ProgressBar` and its legend** (`components/ui/feedback.tsx`, styles in `feedback.module.css`).
   - **Props:**
     - `label`;
     - `total`;
     - `segments: { key, value, tone: "done" | "waiting" | "unavailable" | "failed", label }[]`;
     - `size?: "sm" | "md"` (6 px and 10 px high);
     - `live?: boolean`;
     - `valueText?`.
   - **Accessibility:**
     - `role="progressbar"`, `aria-valuemin=0`, `aria-valuemax=total` and `aria-valuenow` = the `done` segment;
     - `aria-valuetext`, for example "137,932 of 320,869 stored (43%); 182,929 waiting; 8 not available";
     - the same text is visible beside or under the bar, never colour alone.
   - **The look, distinct without colour:**
     - **done** is solid `--green`;
     - **waiting** is `--accent-soft` with diagonal stripes (`repeating-linear-gradient`);
     - **not available** is `--slate-soft` with a 1 px `--border-strong` edge;
     - **failed** is solid `--red`;
     - the track is `--surface-2`.
   - **`ProgressLegend`** draws the swatches with their labels and counts. It is used where a bar has more than one
     segment.
   - **Motion** (decision 10): each segment grows by `transform: scaleX()` from the left over `--slow` with `--ease`.
     The bar's height and width never change, so nothing moves the layout.
   - `Meter` stays for match strength.
   - Alternative: reuse `Meter`. Refused: it is one value from 0 to 1 with `role="meter"`, which is the wrong role
     for progress.
7. **`DataTable` captions are hidden by default** (`showCaption` shows them), and a kit **`ScrollBox`** is added.
   - **The caption** is still rendered, inside `.visually-hidden`, so the table keeps its accessible name. The
     doubled headings of D2 and the other pages go in one change.
   - **The developer checks all 69 `DataTable` uses.** A table with no visible heading of its own gets `showCaption`
     or a heading.
   - **`ScrollBox`** (`components/ui/layout.tsx`): `{ label, children, maxHeight? }`. It renders a `role="region"`
     with `aria-label`, `tabIndex={0}`, `max-height: min(60vh, 560px)`, `overflow-y: auto`,
     `overscroll-behavior: contain` and a visible focus ring. A table inside it keeps its header row visible while
     scrolling (`position: sticky` on `thead th` inside a ScrollBox).
   - It is the Department Mapping box (`mapping.module.css` `.scrollBox`), moved into the kit. Mapping may adopt it
     later; this row does not change Mapping.
   - **Every list in Data Collection that can grow sits in a `ScrollBox`:** months, problems, queue items, calls,
     duplicates, discovery failures, request items and the search results.
8. **A tab toolbar line.** Under the tab row, each tab may have one line (`data.module.css` `.toolbar`):
   - on the left, **"Updated 4 s ago"** (decision 13);
   - on the right, the tab's links and secondary buttons, such as **Open the Dated Report** on Health (H1) and
     **Scan Now** on Duplicates.

   No floating links remain.
9. **Two new uicheck rules, run on every page of the portal** (`frontend/e2e/checks.ts`).
   - **`gutter`.**
     - Inside `main#main`, the left padding must be at least 12 px.
     - Every visible element must lie inside main's content box (left ≥ content left − 1 px, right ≤ content right +
       1 px), unless it is inside `[data-scroll-x]` or `[data-bleed]`, or is fixed or absolutely positioned, or
       visually hidden.
     - The finding names the element and its offset.
   - **`doubled-heading`.** A visible heading (`h1`-`h4`, `caption`, `legend`) fails when its normalised text (trimmed,
     white space collapsed, case ignored) equals the nearest visible heading above it inside the same card or section
     (`section`, `article`, `[data-ui=card]`, `[role=dialog]`).
   - `uicheck-self.spec.ts` gets one page that breaks and one that keeps each rule.
   - A vitest companion goes into `components/tables.test.ts`: a `DataTable` with `showCaption` must not sit in a file
     where the same caption expression is also a heading or card title.
10. **Motion for progress, on the existing tokens only** (portal-ui-redesign, decision 13):
    - **Bars** grow smoothly when figures update (decision 6).
    - **Numbers** count to their new value with `useCountUp` (the `Kpi` behaviour). Number cells and tiles use
      `tabular-nums`, which is already in the kit, so digits do not shift.
    - **The live pulse.** "Running" and "Fetching" badges, and the waiting segment of a live bar, get a soft opacity
      pulse: `animation: pulse calc(var(--slow) * 5) ease-in-out infinite`.
    - **Cards ease in** with the kit's `page-in` keyframes over `--slow`, staggered by 40 ms through a `--i` index on
      each card.
    - **Reduced motion.** Under `prefers-reduced-motion: reduce` the tokens are 0 ms, so bars jump, numbers show at
      once, cards appear, and the pulse has zero duration and so does not run. No JavaScript decides this, except
      `useCountUp`, which already reads the media query.
    - **Nothing moves the layout:** bars have fixed heights, "Updated n s ago" has a fixed width (`min-width: 9ch`),
      and the pulse is opacity only.
    - No animation library.

### C. Overview: what is collected and what is left (the owner's first question)

11. **The headline block: four tiles with bars, filling the width.** Four columns at 1100 px or wider, two from 600
    px, one on phones. All figures come from `GET /admin/data-load/overview` (API).

    | Tile | Big figure | Bar | Line under it |
    |---|---|---|---|
    | **Cause Lists** | "306 of 664 days" | days collected of days in the period up to today (done = with lists + no list published; waiting; failed) | "Working on January 2026" while the load runs; "Paused at January 2026" when paused; "Up to Date" when every day is collected |
    | **Cases** | "59,033 found" | with case details of found | "58,924 with case details · 109 without" |
    | **Order PDFs** | "137,932 of 320,869 stored" | stored, waiting, not available, failed, with the legend | "182,929 waiting · 8 not available at the court" |
    | **Still to Fetch** | the total items left | none (a breakdown) | "267 cause-list days · 33 case details · 182,929 order PDFs", across every lane |

    - **Above the tiles, one status line:**
      - **Court Connection**: an On or Off badge, with the worker note in the tooltip;
      - **Past-Months Load**: Running (pulsing), Paused (with the reason and who paused it, in the tooltip),
        Finished, or Not Started;
      - the load period ("From 1 Jan 2025 to Today").
    - **The meanings:**
      - **Cases found** are all cases held, whatever found them (cause lists, searches, discovery), not merged;
      - **orders known** are all orders held, whatever their date;
      - **Still to Fetch** counts work across every lane, so it matches what the queue will really do.
    - **Orders before the period** are part of "orders known" and of the waiting count: older orders of cases found in
      the period. Month by Month shows them on their own line (decision 15), so the figures add up.
12. **Each figure says what it measures.** The tile titles name the thing counted, and each tile has an info tooltip
    with the one-sentence rule:
    - "Days whose cause lists were collected. A day the court published no list counts as collected.";
    - "A case has details once its full record was fetched from the court.";
    - "Each order's PDF, stored once fetched. Not available means the court has no PDF for it.".
13. **Live figures by polling only while the tab is visible.** These are the owner's live statistics.
    - **The rhythm:**
      - `GET /admin/data-load/pulse` (cheap, decision 14) every **5 s**;
      - `GET /admin/data-load/overview` every **30 s**, and at once after any action on the page;
      - `GET /admin/data-load/coverage` (the month table) every **120 s**, and on its **Refresh** button;
      - Health's snapshot stays at 60 s, with its court figures from the pulse.
    - **Hidden tabs do not poll.** TanStack Query's `refetchIntervalInBackground` stays `false`, so polling stops
      while the tab is hidden and resumes, with one immediate fetch, when it is shown again.
    - **"Updated 4 s ago"** comes from the query's `dataUpdatedAt`. It is re-rendered every second with no request,
      and reads "Updating paused while this tab is hidden" after a hidden period.
    - **Server-sent events are refused.** They would hold an API worker and a connection per viewer, and the server
      would still have to poll the database. The push alternative, `LISTEN/NOTIFY`, is a session-level Postgres
      feature that PgBouncer's transaction mode breaks (row 78; the source scan refuses it).
    - **Cost.** Each poll is a short read transaction. The pulse is a few grouped counts, about 30 ms. A handful of
      administrators at 5 s is negligible on PgBouncer.
    - **The session timeout is untouched** (row 169, design `session-timeout`, decision 4). Only `POST /me/activity`
      counts as activity, and polling never sends it. No poll here keeps a session alive.
14. **Right Now, a slim card under the tiles, from the pulse:**
    - **Fetching now**: the running items by kind ("Case Details 1 · Order PDFs 3"), with the pulsing badge;
    - **Calls this hour**: a bar of calls made of the hourly limit last seen, and "Next reset in 12 min" (a countdown
      ticking each second in the browser, `aria-live="off"`);
    - **Requests in progress**: the count, linking to the Fetch tab.
    - Nothing here calls the court. The pulse reads the call log and the queue.
15. **Month by Month, always shown on Overview** (no "Show Coverage" button), in a `ScrollBox`, newest month at the
    bottom as today.
    - **Columns:**

      | Column | Shows | Tooltip |
      |---|---|---|
      | **Month** | "January 2025" | — |
      | **Cause Lists** | a slim bar and "26 of 31 days", and a state badge: Done, In Progress, Not Reached Yet, Some Days Failed, Not in a Load | "Days counted up to today. A day with no list published counts as collected." |
      | **Lists and Entries** | "412 lists · 18,220 entries" (muted) | "Cause lists stored that month and the case entries printed in them." |
      | **Case Details** | a slim bar and "4,120 of 4,130 cases" | "Cases listed that month whose full record was fetched." |
      | **Order PDFs** | a slim segmented bar and "2,978 of 9,876 stored · 6,898 waiting" | "Orders dated in that month, whatever case they belong to." |
      | **Still to Fetch** | "6,898 order PDFs · 2 days · 10 cases", or "Nothing" | "What is still to fetch for that month, counted by the same dates as the columns." |
      | **Problems** | failed days, case details that could not be fetched, and failed order PDFs, linking to Queue and Calls filtered to failed | — |
      | (unlabelled) | **Days**: opens the month's days in a `Dialog`, with Date, Status (plain words) and Tries | — |

    - **One legend line above the table:** "Cause lists and cases are counted by hearing date and orders by order
      date, so a month not reached yet can already show orders of cases found earlier."
    - **A last row, "Orders Dated Before January 2025",** shows stored, waiting and not-available counts, so that the
      rows add up to the Order PDFs tile.
    - **A Not Reached Yet month** has its row muted, with its days bar empty in the waiting style, never in red.
    - **On phones** the rows stack as cards (the `DataTable` rule), with the bars inside.
16. **"Still to Fetch" for a month is counted by the column's own date, in every lane.** The service replaces the
    lane-bound count (API, coverage):
    - **days**: the month's calendar days up to today not yet collected (waiting, failed, not queued);
    - **cases**: cases listed that month without details that have a pending or running `dossier` row, in any lane;
    - **order PDFs**: orders dated in that month with `download_status = 'pending'` and no document. This equals the
      waiting rows in every lane, as checked in Context.

    The old `work_left` and `failed` keys stay in the answer for the CLI and older clients, and the portal stops
    reading them.
    - Alternative: relabel Left as "Load Lane Items". Refused: the owner asked what is really left.
    - Alternative: match `order_pdf` refs to orders by their date part. Refused: it reads the same truth from the
      queue's text keys, more slowly. The `orders` table already holds it.
17. **An honest estimate across every lane, in two lines and one basis line.**
    - **The two lines:**
      - "Cause lists and case details: about Tuesday 28 Oct 2026."
      - "Every order PDF as well: about Saturday 8 Nov 2026."
    - **The basis line:** "At the pace of the last 24 hours, about 820 court calls an hour of the 1,000 the court
      allows. New cause lists each day add work, so these dates can move."
    - **"How This Is Worked Out"** (`Collapsible`) gives the inputs in words, with no JSON: items waiting by kind,
      calls per item, calls an hour and the hourly limit seen.
    - **The method** (`services/data_load.py::estimate_all`):
      - It keeps decision 8 of `data-load-console`: measured rates only, no assumed constant.
      - It measures over every queue lane (`lane IS NOT NULL`) instead of the load lane.
      - **Calls per item** are calls of each API family ÷ items of that kind finished, over 7 days, all lanes.
      - **Calls per hour** are queue-lane calls in the last 24 hours ÷ 24.
      - **The hourly limit seen** is the largest `remaining + 1` of the recent resets (`napix_window`), or none.
      - **Details finish** = (days left × the day's calls without PDFs + case details left × calls per dossier) ÷
        calls per hour.
      - **All finish** adds order PDFs left × calls per PDF, and the PDFs the days left will bring (days left ×
        dossiers per day × PDFs per dossier × calls per PDF).
      - The detail kinds run before order PDFs by priority (40-46 before 60 and 80), so the details line finishes
        first.
    - **No date is given, with the reason in plain words,** while the load is paused (for the details line only;
      order PDFs in the daily lane still run), with less than a day of history, with no queue call in the last hour,
      or while the court connection is off.
    - **For today's dev figures** this gives roughly 1.5 days for cause lists and details (about 29,000 calls) and
      roughly 13 days for everything (about 276,000 calls). The load-lane estimate shown today leaves out the daily
      lane's 167,398 PDFs.
    - The old `estimate` stays in `GET /admin/data-load` for the CLI. The portal shows only the new one.

### D. Load: Load Control and Priority (the owner's screenshot)

18. **The Load tab, top to bottom:**
    - **Load Control** (wide);
    - **Priority** and **Calls This Hour** side by side from 1100 px, as two equal cards;
    - **Past-Months Load Waiting** and **Latest Problems**, both wide.

    Every card uses the field-row rule (labels above boxes, controls on the 36 px line) and the checkbox rule.
    **One primary on the page: Start a Load.**
19. **Load Control card:**
    - **A definition list:**
      - Status (Running with the pulse, or Paused);
      - Since (who changed it and when);
      - Reason, shown when paused;
      - Load Period ("1 Jan 2025 to 26 Oct 2026");
      - What Goes First (the current choice in words);
      - Court Connection (an On or Off badge, with the worker note in the tooltip).
    - **Buttons:** **Start a Load** (primary, `admin.data_load`), and **Pause** or **Resume** (secondary, the same
      function). Without `admin.data_load` the card is read only and has no buttons.
    - **Start a Load opens a `Dialog`** ("Start a Load", `wide`):
      - **Dates**: a From–To pair, as one aligned group "Dates to Load", with two date fields on one line;
      - **Check These Dates** (secondary) calls the existing preview, `POST /admin/data-load/preview`;
      - **the result is a summary panel, not loose lines:** five small tiles (Days, Already Held, Waiting, Failed,
        New), then one line, "About 3,400 court calls, about 4 hours at the current pace" (from `calls_estimate` and
        the overview's calls per hour). When there is no history: "No call estimate yet";
      - **Days Already Held** is a `RadioGroup` (Leave Them As They Are, the default; Fetch Them Again), shown when
        some are held;
      - **Start Load** is the dialog's primary, and appears **only when something would be fetched**: new or failed
        days exist (`not_queued + failed > 0`), or held days exist and Fetch Them Again is chosen;
      - **otherwise the panel says so** ("Nothing new to fetch: every day in these dates is already held or waiting.
        Choose Fetch Them Again to fetch the held days again."), and the dialog has only Close;
      - the call is the existing `POST /admin/data-load/start`, with the same audit (`data_load.started`).
    - **Pause opens a `Dialog`** ("Pause the Past-Months Load"):
      - the required **Reason** (3 to 500 characters, with a counter);
      - the note "Daily updates, people's searches and requests keep running. Only the past-months load stops.";
      - **Pause Load** as a danger button;
      - the existing `POST /admin/data-load/pause` (audit `data_load.paused`).
    - **Resume opens a `ConfirmDialog`**, calling the existing `POST /admin/data-load/resume`.
    - **Both refresh the overview at once.**
20. **Priority card ("What Goes First"):**
    - **The grid:** three equal columns from 1100 px, one on phones.
      - **Row 1:** **What Goes First** (select, one column); then **Bring These Dates Forward**, a `fieldset` whose
        legend is the label, holding **From** and **To** date fields that span the other two columns.
      - **Row 2:** **Reason for the Change** (two columns), then **Save Priority** (secondary) on the control line of
        the third column.
    - **Under the grid**, a line explains the current choice in words: "Case details are fetched before cause lists.
      Order PDFs always come after case details."
    - The call is the existing `PUT /admin/data-load/order`, with the same audit and its "n rows re-prioritised"
      notice.
    - Read only without `admin.data_load`.
21. **The other Load cards:**
    - **Calls This Hour** (replaces the allowance):
      - a `ProgressBar` of calls made of the hourly limit seen;
      - a two-column definition list (Calls Left, Next Reset with the countdown, Current Hour Started);
      - a compact `DataTable` "By Kind of Work", in plain lane names (decision 32), with Calls right-aligned in a
        narrow column;
      - the thresholds as one plain hint: "ASLMS stops the past-months load when fewer than 150 calls are left this
        hour, keeps 100 for daily updates and 50 for people's searches." The numbers come from the API.
    - **Past-Months Load Waiting** (today's Work Left, now titled honestly as the load lane):
      - a `DataTable` with Kind, Waiting, Ready Now, Waiting to Retry, Fetching, Failed and Retry Failed;
      - Retry Failed with `admin.napix_refetch`, as today, through `POST /admin/napix/queue/retry-failed`.
    - **Latest Problems** (today's Latest Failures): a `DataTable` in a `ScrollBox`:
      - When;
      - What, the kind and the reference;
      - Tries;
      - Problem, wrapped and muted, with the full text in a tooltip.

### E. Fetch From the Court (one area for every on-demand fetch)

22. **The Fetch tab, top to bottom:**
    - **Requests** (decision 26): what was asked and how far it has got;
    - **One Case** (`admin.data_load`): today's search by CNR, Case Number or Party Name with Fetch Details, moved
      from the Load tab unchanged in rules;
    - **Several Cases** (`admin.data_load`, decision 24);
    - **All Cases Listed on a Day** (`admin.data_load`, decision 23);
    - **Fetch Again** (`admin.napix_refetch`): three aligned rows moved from Health, each with its existing endpoint,
      warning and audit (`napix.refetch_requested`): One Day's Cause Lists (date), One Case (CNR or reference), One
      Order PDF (case and order).

    Each card uses the field-row grid. Each form's submit is secondary, and each confirming dialog has its own
    primary. The page has no primary of its own, because no action leads.
23. **"Fetch Details of All Cases Listed on a Day"** (the owner's new action).
    - **Step 1, check (writes nothing):**
      - **Date** (up to tomorrow), and **Which Cases**, a `RadioGroup`:
        - **Only Cases Never Fetched** (the default);
        - **Every Case Listed**: cases whose details were refreshed in the last 6 hours are left out, so a second
          click soon after does not spend the calls again.
      - **Check This Day** calls `GET /admin/data-load/day-details?date=&scope=`.
      - **The summary panel** shows:
        - Lists on That Day;
        - Cases Listed;
        - With Details, with "last refreshed between 21 Oct and 26 Oct 2026";
        - Never Fetched;
        - Refreshed in the Last 6 Hours;
        - No Court Reference (provisional rows without a usable number);
        - **To Fetch**;
        - "About 1,250 court calls, about 1 h 30 min at the current pace. This hour has 640 calls left. Requests run
          before daily updates and the past-months load."
    - **Step 2, confirm:** **Fetch Details** opens a `ConfirmDialog` that repeats To Fetch. Its primary calls
      `POST /admin/data-load/day-details` with `{date, scope}`.
    - **When there is nothing to fetch,** the panel says "Every case listed on this day already has details." and
      shows no Fetch Details.
    - **Rules** (`services/data_load.py::day_details_preview` and `day_details`):
      - **The cases** are the distinct `case_id`s of the date's **current** lists (`superseded_at IS NULL`), not
        merged.
      - **Each case's dossier ref** comes from `napix_admin.dossier_ref`. A case with none counts as "No Court
        Reference".
      - **Each case is queued** with `queue.enqueue(kind=dossier, ref, REQUEST_PRIORITY (30), lane=request,
        requested_by=<the person>, requeue=<held>)`, in batches of 500 in one transaction.
      - **Idempotent:** the queue's `(kind, ref)` upsert means a repeat adds no row. A row already pending keeps its
        place. A held case under Every Case Listed is re-queued only if its last refresh is older than 6 hours.
      - **The cap** is `DAY_DETAILS_MAX = 2,000` cases (the most seen in a day is 1,191). A larger day answers 400
        `too_many`, which says to use Several Cases.
      - **Errors:** a date with no current lists is 400 `no_lists`; a date after tomorrow (IST) is 400
        `date_in_future`.
      - **The counts are recomputed when the request is sent**, not trusted from the check.
      - **Audit:** one row, **`data_load.day_details_requested`**, with `after = {date, scope, lists, cases,
        to_fetch, queued, already_waiting, held_left_out, recent_left_out, no_reference, dossier_refs: [...]}`.
      - **No NAPIX call is made by the endpoint.** The worker fetches through the integration layer as for every
        dossier.
    - **The function is `admin.data_load`** (decision 25).
24. **Several Cases (a pasted list).**
    - **The form:** a `TextArea` labelled **"Cases, One per Line"**, with the hint "CNRs, case numbers such as
      WP(C)/1234/2024, or ASLMS case references; up to 200." Then **Check List** calls `POST
      /admin/data-load/list-details/preview`, which writes nothing.
    - **The result** is a `DataTable` of the items, each with what will happen:
      - Will Fetch;
      - Already Has Details, with the date;
      - Not Held;
      - Several Cases Match;
      - Not a Case Reference;
      - Merged Into ‹ref›.
    - **Fetch Again for held cases** is a checkbox, "Also Fetch Cases That Already Have Details". This is `force`, as
      in today's Fetch Details.
    - **Fetch Details** (secondary, then a `ConfirmDialog` with its primary) calls `POST
      /admin/data-load/list-details`.
    - **How each line is read:** `case_filters.parse_query(line, "auto")`, the local search's own parser:
      - an **ASLMS reference** or **id**: a held case;
      - a **CNR**: the held case, or, when not held, a dossier row by that CNR, which creates the case from the court
        as a person's court search does. A CNR is the court's own identifier, never made up;
      - a **case number**: matched against held cases as the local search matches numbers. One match is used.
        Several (court duplicates) give "Several Cases Match", with their references. None gives "Not Held", with
        the hint "Use One Case to search the court for it.";
      - **anything else**: "Not a Case Reference".
    - **The rest** is as in decision 23:
      - request lane at priority 30, with the person;
      - `force` re-queues held cases;
      - 1 to 200 distinct lines (`DETAILS_MAX`), otherwise 400 `bad_input`;
      - one audit row, **`data_load.list_details_requested`**, with `after = {count, queued, force, items: [{line,
        state, ref_no}], dossier_refs: [...]}`.
    - Alternative: widen `POST /admin/data-load/fetch-details`. Refused: it serves the search results with its own
      answer shape, and CNRs not held are new behaviour.
25. **The guard for the bulk fetches is `admin.data_load`.**
    - A day or a list spends hundreds of calls, up to 2,000, which can be two hours of the court allowance. It
      competes with the past-months load, which `admin.data_load` governs.
    - The existing multi-case action (`fetch-details`) is already behind `admin.data_load`.
    - The function's description already says "fetch single cases". It becomes "Start, pause and order the
      historical load, fetch cases from the court and check duplicates", a seed upsert with no migration.
    - **`admin.napix_refetch`** ("Fetch a cause list, a case or an order again", held by default by the Central
      Operator) stays for single re-fetches.
    - No holder gains or loses a power.
    - Alternative: `admin.napix_refetch`. Refused: it would let a single-item function spend a day's worth of calls.
26. **Requests, with live progress.**
    - **The card** lists the requests of the last 7 days: day, list, and the existing "Fetch Details" from One Case.
      It is fed by `GET /admin/data-load/requests`.
    - **Each request is one row:**
      - What ("Cases Listed on 23 Oct 2026", "List of 12 Cases", "Cases Chosen From a Search");
      - Asked By;
      - When;
      - a segmented **ProgressBar**: Done (green), Fetching (accent, pulsing), Waiting (striped), Failed (red);
      - the counts, for example "Done 640 · Fetching 2 · Waiting 548 · Failed 1 · Not Found at the Court 9".
    - **Show Items** opens a `SidePanel` with the request's items (`GET /admin/data-load/requests/{id}`, paged by
      100): Case, State in plain words, Tries, Last Problem.
    - **The request record is its audit row; no new table.**
      - The request's id is the `audit_log.id`.
      - The refs are `after.dossier_refs`.
      - The time asked is the row's `created_at`.
      - The existing `data_load.details_requested` row gains `dossier_refs`, an additive field. Rows written before
        this change have none and are not listed.
    - **How each item's state is read** from its `fetch_queue` row (`kind = 'dossier' AND ref = ANY(:refs)`, through
      `uq_fetch_queue_kind_ref`):

      | Queue row | Shown as |
      |---|---|
      | pending, ready | Waiting |
      | pending, `not_before` in the future | Waiting to Retry |
      | running | Fetching |
      | done | Done |
      | skipped | Not Found at the Court |
      | failed | Failed |

    - **Refreshing:** every 5 s while any request is unfinished and the tab is visible, otherwise every 30 s.
    - Alternative: a `fetch_requests` table. Refused: it needs a migration, and the audit row already records exactly
      who asked for what and when.
    - Alternative: track by `requested_by`. Refused: one person's requests overlap, and a done row loses nothing that
      identifies the request.
27. **No change to who may see or do anything.**
    - The overview, pulse, coverage, request list and request items read with today's reader rule for
      `/admin/data-load` (`data_load.READERS`: `admin.data_load`, `reports.state`, `admin.napix_refetch`,
      `admin.masters_sync`). They show system figures, plus references, CNRs and case numbers, which the Queue and
      Duplicates tabs already show to the same readers.
    - The only new writes are the two bulk fetches, behind `admin.data_load`, and both are audited.
    - Start, pause, order, retry and the re-fetch forms keep their current endpoints, guards and audit.

### F. Health, Queue and Calls, Duplicates, Discovery (the rest of "every tab")

28. **Health**, in plain words, as these cards:
    - **The toolbar:** Updated n s ago, and **Open the Dated Report** (with `reports.state`, H1).
    - **Court Connection** (wide):
      - **a row of four tiles filling the width:** Calls This Hour (with a `ProgressBar` of the hourly limit seen),
        Calls Today (with failed calls in red under it), Calls Left This Hour, and Next Reset (with the countdown);
      - **a definition list:** Court Connection (On or Off, with the worker note in the tooltip), Last Call, and
        Last Connection Check (time and "Answered" or the problem in words);
      - **Recent Resets** in a `Collapsible` ("Recent Resets (3)"): a compact `DataTable` with Time, Calls Left
        Before, Calls Left After and Timing ("Seen Exactly" or "Estimated", with the meaning in the tooltip),
        replacing "Precise".
    - **Calls by Person** (`by_user`, only when the API sends it) and **Daily Updates, Last 7 Days** side by side from
      1100 px:
      - Calls by Person is a compact table (Person; then This Hour, Today and Failed in narrow number columns);
      - Daily Updates has Date, Status (Done, Waiting, Failed, No List Published), Lists, Entries, Corrected and
        Evening Recheck.
    - **Work Waiting by Lane** (wide, H4): kinds as rows; Total, then one column per lane in plain names (decision
      32), Fetching and Failed. The table is not doubled.
    - **Checks** (wide), with each button as today:
      - **Update Court Reference Lists** (`admin.masters_sync`; today's Sync Masters);
      - **Check the Court Connection** (either function).
    - **Court Reference Lists** and **Scheduled Jobs** side by side, H5:
      - Court Reference Lists: List (each `MasterSyncRun.master` in a plain name: Case Types, Benches, Acts, States, Districts), Last Updated,
        Rows;
      - Scheduled Jobs: Job (a plain label map, the code in the tooltip), Last Run, Result badge.
    - **E-mail** tiles (E-mails Waiting, E-mails Failed) and **Problems to Look At** (kind in words, open count,
      linking to Queue and Calls filtered to failed) side by side.
    - **Document Text:** unchanged figures, with plain headers and no doubled heading.
    - **Keeping Records** (today's Retention, H6), a definition list:
      - Court Call Records Kept ("2 years");
      - Oldest Record Kept;
      - Last Clean-up;
      - Storage Used (call records; court answers, kept for ever);
      - Disposed Cases Refreshed Monthly ("1,234 in their first year, 56 due now; last run …").
    - **The three re-fetch forms move to the Fetch tab** (decision 22, H7).
29. **Queue and Calls:**
    - **A `SegmentedSwitch`, "Work Items" or "Court Calls"**, kept in the address (`?view=calls`), so only one long
      table shows at a time (Q1).
    - **Work Items:**
      - keeps Filter Layout B as built (row 163);
      - its table sits in a `ScrollBox`, with Item (kind and reference), Lane, Status badge (Waiting, Fetching, Done,
        Failed, Nothing at the Court), Tries, Last Problem and Retry;
      - Priority moves into the Item cell's tooltip ("Runs before items with a higher number");
      - Pagination stays.
    - **Court Calls:**
      - a `ScrollBox` with When; Court Service (a plain name from a map of the 17 API paths, with the path in the
        tooltip); Lane; Person (when returned); Result badge (Answered or Failed, with the problem in words); HTTP
        Code (hidden on phones); Calls Left;
      - More stays.
    - **Empty states** read "No work items match these filters." and "No court call yet today." (Q3).
30. **Duplicates:**
    - the three kinds as a `SegmentedSwitch` ("Needs Review", "Merged", "Court Duplicates"), each with a one-line
      explanation under it (U1);
    - **Scan Now** in the toolbar (secondary, `admin.data_load`), with the hint "Checks every case for duplicates now;
      it also runs every night at 03:00." (U2);
    - the table sits in a `ScrollBox`, with Case, Other Case and When on one line each, and Reason (Needs Review
      only) (U3);
    - empty states per kind: "No case needs review." and so on.
31. **Discovery:**
    - **a tile row:** Names Searched (Active), Names Paused, Cases Found, Created by Discovery, Recommended From
      Discovery;
    - **Share of Court Calls:** a `ProgressBar` of discovery calls this hour against its share, with "Searches cases
      from ‹from_year› on" (the setting) and the next reset;
    - **Discovery Work Waiting**, a `DataTable`;
    - **Latest Problems**, in a `ScrollBox`;
    - **Search Every Name Now** in the toolbar (secondary, `admin.data_load`), with today's confirm (V1-V3).
32. **Plain words throughout, with exact terms only in tooltips.**
    - **Lanes:**

      | Code | Name shown |
      |---|---|
      | `load` | Past Months |
      | `daily` | Daily Updates |
      | `discovery` | Department Discovery |
      | `request` | Asked by People |
      | outside the queue | Searches and Checks |

    - **Kinds:**

      | Code | Name shown |
      |---|---|
      | `masters` | Court Reference Lists |
      | `causelist_day` | Cause-list Days |
      | `dossier` | Case Details |
      | `status_batch` | Status Checks |
      | `order_pdf` | Order PDFs |
      | `party_search` | Party-name Searches |
      | `search_rows` | Advocate Search Results |
      | `causelist_recheck` | Cause-list Rechecks |

    - **Statuses:**

      | Code | Name shown |
      |---|---|
      | `pending` | Waiting |
      | `running` | Fetching |
      | `done` | Done |
      | `failed` | Failed |
      | `skipped` | Nothing at the Court |

    - **"This Window"** becomes "This Hour". The window line becomes "This hour started about 15:35; the next reset is
      about 16:35.", with the detected-window explanation in the tooltip.
    - Every label is Title Case and passes `labels.test.ts`. Sentences sit under sentence keys.
    - The wording guards (`lib/wording.test.ts`, `tests/unit/test_wording_guard.py`) stay green.
    - The new audit actions get names in `T.audit.actionNames`: "Details Requested for a Day" and "Details Requested
      for a List".

### G. Rounds

33. **Three rounds, in this order, each its own branch, review and report** (the portal-ui-polish-2 precedent):
    - **Round 1 (row 172, `feature/data-collection-redesign`): decisions 1-21 and 27.**
      - The kit and portal-wide changes: gutter, no upper case, `ProgressBar`, `ScrollBox`, hidden captions, the
        toolbar and the two uicheck rules.
      - The Overview tab and its services: overview, pulse, coverage and the estimate across lanes.
      - The Load tab.
      - The State dashboard link.
      - The Fetch tab holding the **existing** forms, moved: One Case from Load, Fetch Again from Health.
      - It goes first because it answers the owner's two questions and fixes the misleading numbers.
    - **Round 2 (new row at approval, `data-collection-redesign-tabs`): decisions 28-32**, the Health, Queue and
      Calls, Duplicates and Discovery layouts. Frontend only, using round 1's kit.
    - **Round 3 (new row at approval, `data-collection-fetch`): decisions 22-26**, the bulk fetches, the requests and
      their progress. These are the new writes.
    - Alternative: one cycle. Refused: about 30 files, four new endpoints, two new writes and every table in the
      portal is too much for one review.

## Data

**No new table, column, index or reference code. No migration.**
- The request record is the existing append-only `audit_log` row (decision 26). Its `after` gains `dossier_refs`, a
  JSON field, which needs no schema change.
- The reads use existing indexes:
  - `orders.order_date` (`ix_orders_order_date`);
  - `causelists.list_date`;
  - `causelist_entries.causelist_id` and `case_id`;
  - `fetch_queue (kind, ref)` (`uq_fetch_queue_kind_ref`) and `(lane, list_date)`;
  - `audit_log.action` (`ix_audit_log_action`).
- The timings in Context show these are enough. If a later measurement shows otherwise, the index belongs to its
  own row and takes the next free migration number after main's highest (0027 today; rows 157 and 169 both plan
  0028).
- `docs/schema/schema.md` needs no paragraph.
- The seed upserts the new description of `admin.data_load` (decision 25), as row 135 did for labels.

## Services

All in `backend/aslms/services/data_load.py` unless named. None calls NAPIX.

- **`overview(session, cfg, now=None) -> dict`** (round 1), under `with_timeout(cfg.report_statement_timeout_seconds)`:
  - **`collection`:** `gateway_on` (`cfg.napix_configured`), `load_state` (`running` | `paused` | `finished` |
    `not_started`), `paused_reason`, `changed_by`, `changed_at`.
  - **`period`:** from `load_period`, with `to` capped at today (IST).
  - **`position`:** `next_day` is the smallest `ref` of pending or running `causelist_day` rows in the load lane;
    `working_on_month` is that day's month; `last_collected_day` is the largest held day not after `next_day`. All
    are null when nothing waits.
  - **`days`:** `_day_totals` over the period up to today, plus `collected` = with lists + no list.
  - **`cases`:**
    - `found` = cases not merged;
    - `with_details` = `last_full_refresh_at` not null;
    - `without_details` = found − with details;
    - `queued` = cases without details with a pending or running `dossier` row in any lane;
    - `provisional`.
  - **`orders`**, over all orders: `known`, `stored` (document set), `waiting` (pending, no document), `failed`,
    `not_available`; and `in_period` (the same five by `order_date` in the period).
  - **`left`:** `days` (waiting + failed + not queued, up to today), `cases` (queued, above), `order_pdfs` (orders
    waiting), `total` (their sum), and `by_kind_lane` (pending + running `fetch_queue` rows by kind and lane, every
    lane).
  - **`estimate`:** `estimate_all` (below).
- **`estimate_all(session, cfg, settings, now) -> dict`** (round 1):
  - `measure_all` is `measure` with the lane filter `NapixCallLog.lane.isnot(None)` and every lane's queue rows;
  - `compute_two(basis, paused, gateway_on, now)` gives `{details: {finish_at, hours, calls_needed, reason}, all:
    {…}, calls_per_hour, hourly_limit_seen, basis}`, as decision 17;
  - unit-testable without a database, like `compute_estimate`;
  - `measure` and `compute_estimate` stay unchanged for `GET /admin/data-load` and the CLI.
- **`pulse(session, cfg, now=None) -> dict`** (round 1), a cheap read:
  - `as_of`, `gateway_on`, `load_paused`;
  - `window`: from `napix_window.current`, with calls since the observed reset, `remaining`, `limit_seen`,
    `next_reset_at`, `seconds_to_reset` and `status`;
  - `queue`: pending, running and failed counts by kind, every lane, in one grouped query;
  - `running`: up to 10 running rows, with kind, lane and `started_at`, no refs;
  - `calls_last_5_min`, `last_call_at`;
  - `requests_active`: the requests of decision 26 with any item pending or running, counted over the last 7 days'
    request audit rows.
- **`coverage` / `_month_figures`** (round 1), additive:
  - the days are counted up to today in the current month, and a month after today is refused as today (`bad_period`
    beyond the period);
  - `orders` gains `failed`;
  - `cases` gains `without_details` and `queued`;
  - new **`left`** = `{days, cases, order_pdfs}` by the column's own dates (decision 16);
  - new **`state`**: `done` when every counted day is collected; `failed_days` when some failed and none wait;
    `not_reached` when none is collected and every waiting day is on or after `position.next_day`; `not_in_load` when
    no day is collected or queued; otherwise `in_progress`;
  - `work_left` and `failed` are kept unchanged;
  - `coverage()` also returns `earlier_orders`: the five order counts with `order_date` before the first month shown;
  - the result becomes `{months, earlier_orders, position}`. The router's `CoverageOut` gains the two keys.
- **`day_details_preview(session, list_date, scope, cfg, today=None)`** and **`day_details(session, actor, user,
  list_date, scope, cfg)`** (round 3), as decision 23.
  - They use `napix_admin.dossier_ref` and `queue.enqueue`, with `requested_by = napix_window.user_id_of(user)`.
  - `require(admin.data_load)` comes through the router.
  - The audit row is written by `write_audit` in the same transaction as the queue rows.
  - `RECENT_REFRESH = timedelta(hours=6)`, `DAY_DETAILS_MAX = 2000`.
  - The estimate comes from `estimate_all`'s calls per dossier and PDFs per dossier, and the window's remaining.
- **`list_details_preview(session, lines, force)`** and **`list_details(session, actor, user, lines, force, cfg)`**
  (round 3), as decision 24. They use `case_filters.parse_query` and the local number match of
  `services/case_search.py`.
- **`fetch_details`** (existing) adds `dossier_refs` to its audit `after` (round 3).
- **`requests(session, now=None, limit=20)`** and **`request_items(session, audit_id, limit=100, offset=0)`** (round
  3):
  - They read `audit_log` rows with `action IN ('data_load.day_details_requested', 'data_load.list_details_requested',
    'data_load.details_requested')`, from the last 7 days, newest first, that hold `dossier_refs`.
  - Each request's states come from one grouped query on `fetch_queue`, as in decision 26.
  - Items join `cases` by CNR (or by the provisional `est|number`) for the reference and case number.
  - An unknown id, or an audit row of another action, is `NotFound`.
- **`access_seed.py`:** the new description of `admin.data_load` (decision 25).
- **The CLI:** `aslms data-load status` prints the overview's headline and the two estimate lines (round 1).
  `aslms data-load day-details --date D [--all] [--dry-run]` acts as the Super Administrator named in `.env` and is
  audited (round 3).

## API

Every endpoint below is in `api/routers/data_load.py`, under `/admin/data-load`. All answers are JSON with IST times.
None calls NAPIX.

| Method and path | Function (`Permission`) | Round | Request | Response |
|---|---|---|---|---|
| `GET /admin/data-load/overview` | any of `data_load.READERS` (`admin.data_load`, `reports.state`, `admin.napix_refetch`, `admin.masters_sync`) | 1 | — | `DataLoadOverviewOut` = the `overview()` dict (Services) |
| `GET /admin/data-load/pulse` | any of `data_load.READERS` | 1 | — | `DataLoadPulseOut` = the `pulse()` dict |
| `GET /admin/data-load/coverage` (existing) | any of `data_load.READERS` (unchanged) | 1 | `from`, `to` (unchanged) | `CoverageOut` gains `earlier_orders` and `position`; each month gains `state`, `left`, `orders.failed`, `cases.without_details`, `cases.queued` (additive) |
| `GET /admin/data-load/day-details?date=YYYY-MM-DD&scope=never\|all` | `admin.data_load` | 3 | — | `DayDetailsPreviewOut {date, scope, lists, cases, with_details, last_refreshed: {oldest, newest}, never_fetched, recent_left_out, no_reference, to_fetch, cap, calls_estimate, hours_estimate, window_remaining}`; 400 `no_lists`, `date_in_future`, `too_many` |
| `POST /admin/data-load/day-details` | `admin.data_load` | 3 | `{date, scope}` | 202 `DayDetailsOut {request_id, to_fetch, queued, already_waiting, held_left_out, recent_left_out, no_reference}`; audit `data_load.day_details_requested`; the same 400s |
| `POST /admin/data-load/list-details/preview` | `admin.data_load` | 3 | `{lines: [str] (1-200), force}` | `ListDetailsOut {items: [{line, state, case: CaseBrief?, cases: [CaseBrief]?, held_at?}], to_fetch}`; writes nothing; 400 `bad_input` |
| `POST /admin/data-load/list-details` | `admin.data_load` | 3 | `{lines, force}` | 202 `ListDetailsOut` plus `request_id`; audit `data_load.list_details_requested` |
| `GET /admin/data-load/requests?limit=20` | any of `data_load.READERS` | 3 | — | `FetchRequestsOut {items: [{id, kind: day\|list\|search, label_date?, count, asked_by: {name}, asked_at, states: {waiting, waiting_retry, fetching, done, not_found, failed}, finished}]}` |
| `GET /admin/data-load/requests/{id}?limit=100&offset=0` | any of `data_load.READERS` | 3 | — | `FetchRequestItemsOut {request, total, items: [{ref, case: CaseBrief?, state, attempts, last_error, finished_at}]}`; 404 `not_found` |

- `CaseBrief` is the Duplicates brief: `{id, ref_no, cnr, case_no_text}`. It carries reference, CNR and case number
  only, never parties or notes.
- **Unchanged:** `GET /admin/data-load`, the preview, start, pause, resume and order, fetch and fetch-details, the
  duplicates endpoints, and `/admin/napix/*` (refetch day, case and order, retry, health, queue, calls), each with its
  function and audit.
- The frontend types are regenerated (`schema.d.ts`), and `lib/api/types.ts` exports the new types.

## Jobs

**No new scheduled job.**
- The bulk fetches add `dossier` rows in the `request` lane at priority 30 (`load_policy.REQUEST_PRIORITY`), with the
  person in `requested_by`. The existing runner claims them through the integration layer, with its reserves and the
  quota window.
- Their order PDFs follow today's request rule (40, `REQUEST_ORDER_PDF`).
- A day of about 1,200 cases is about 1.3 hours of the allowance, which the check shows before anything is queued.

## Tests

**pytest, round 1** (`backend/tests/db/test_data_load_overview.py`, `tests/unit/test_data_load_estimate_all.py`,
additions to `tests/db/test_data_load*.py` and `test_api_data_load.py`):
- `test_overview_counts_days_cases_and_orders_of_the_period`
- `test_overview_left_counts_order_pdfs_in_every_lane`: daily-lane PDFs are counted.
- `test_overview_position_is_the_earliest_waiting_load_day`
- `test_overview_states_running_paused_finished_not_started_and_gateway_off`
- `test_overview_orders_in_period_and_all_add_up`
- `test_overview_and_pulse_need_a_reader_function`: 403 without one; 200 for each of the four functions.
- `test_overview_pulse_coverage_write_nothing_and_call_no_napix`: no audit row, no `napix_call_log` row, the scripted
  gateway unused.
- `test_pulse_counts_the_queue_across_lanes_and_lists_running_items_without_refs`
- `test_coverage_left_uses_the_columns_own_dates`: an order dated October queued from a January listing in the daily
  lane counts in October's left, not January's.
- `test_coverage_state_done_in_progress_not_reached_failed_days_not_in_load`
- `test_coverage_counts_days_only_up_to_today`
- `test_coverage_earlier_orders_and_months_add_up_to_all_orders`
- `test_coverage_keeps_work_left_and_failed_for_old_clients`
- `test_estimate_all_uses_every_lane_and_finishes_details_before_order_pdfs` (unit)
- `test_estimate_all_reasons_paused_no_history_no_recent_calls_gateway_off` (unit)
- `test_estimate_all_includes_pdfs_the_days_left_will_bring` (unit)
- `test_admin_data_load_description_seeded_title_case_label_unchanged`

**pytest, round 3** (`backend/tests/db/test_data_load_fetch_requests.py`, `test_api_data_load.py`):
- `test_day_details_preview_counts_lists_cases_held_never_fetched_recent_and_no_reference`
- `test_day_details_queues_dossiers_in_the_request_lane_with_the_person`
- `test_day_details_never_scope_skips_held_cases`
- `test_day_details_all_scope_leaves_out_cases_refreshed_within_6_hours`
- `test_day_details_twice_adds_no_row_and_keeps_priority`: idempotent.
- `test_day_details_uses_only_current_lists`: a superseded list's cases are left out.
- `test_day_details_refuses_no_lists_future_date_and_over_2000`
- `test_day_details_needs_admin_data_load_napix_refetch_alone_is_403`
- `test_day_details_writes_one_audit_row_with_dossier_refs`
- `test_list_details_reads_cnr_reference_number_and_refuses_text`
- `test_list_details_unknown_cnr_is_queued_unknown_number_is_not_held`
- `test_list_details_several_matches_are_listed_not_queued`
- `test_list_details_preview_writes_nothing`
- `test_list_details_force_requeues_held_cases`
- `test_list_details_caps_at_200_distinct_lines`
- `test_fetch_details_audit_now_carries_dossier_refs`
- `test_requests_lists_the_last_7_days_newest_first_with_states`
- `test_request_states_waiting_retry_fetching_done_not_found_failed`
- `test_request_items_paged_and_404_for_other_actions`
- `test_requests_need_a_reader_function`

**vitest, round 1:**
- `components/ui/ui.test.tsx`:
  - ProgressBar has `role="progressbar"`, `aria-valuenow`, `aria-valuemax` and `aria-valuetext`, segments in order,
    and the legend's counts;
  - under reduced motion it has no transition (the token class);
  - ScrollBox is a labelled, focusable region;
  - a DataTable caption is visually hidden by default and visible with `showCaption`.
- `components/styles.test.ts`: no `text-transform: uppercase` in any CSS file.
- `components/tables.test.ts`: no `showCaption` caption that equals a heading or card title in the same file.
- `components/data/data.test.tsx`:
  - the tabs are Overview, Load, Fetch From the Court, Health, Queue and Calls, Duplicates, Discovery, with Fetch only
    for `admin.data_load` or `admin.napix_refetch`;
  - `/data` opens Overview;
  - Overview renders the four tiles with their bars and the "Working on January 2026" line from a fixture;
  - Still to Fetch sums the three kinds;
  - the month table shows Not Reached Yet, "Still to Fetch" by its own dates, and the earlier-orders row;
  - there is no "Show Coverage" button;
  - the polling intervals are 5 s for pulse, 30 s for overview and 120 s for coverage, and none polls in the
    background;
  - "Updated n s ago" ticks without a request;
  - the estimate shows two dated lines and the basis line, a reason when paused, and no JSON;
  - the Load tab has one primary (Start a Load);
  - Start: the preview panel with five tiles; "Nothing new to fetch" hides Start Load; choosing Fetch Them Again
    shows it;
  - Pause opens a dialog that needs a reason of 3 or more characters;
  - Priority: From and To sit in one fieldset;
  - each Data Collection card has no doubled heading (no visible caption equal to its title).
- `components/dashboard/dashboard.test.tsx`: the State block shows "Data Collection Progress" only with a reader
  function.
- `lib/labels.test.ts`: passes over the new strings, with no new exception without a reason.

**vitest, round 2:** Health renders the four court tiles, the reset table instead of a list and no "Precise"; Queue's
switch keeps `view` in the address; the plain lane, kind and status names; the Duplicates explanations; the Discovery
share bar.

**vitest, round 3:**
- the day check panel and its confirm;
- "Every case listed on this day already has details." with no button;
- the list check's states;
- the requests' segmented bars;
- the item panel;
- 5 s refresh only while a request is unfinished.

**uicheck** (`frontend/e2e/checks.ts`, `uicheck.spec.ts`, `uicheck-self.spec.ts`, fixtures):
- **The rules:** `gutter` and `doubled-heading` run on every page at 375, 768 and 1280 px. The self pages break and
  keep each one.
- **The routes:** `/data/overview` and `/data/fetch` join the route list automatically, as page routes.
- **The fixtures:** `overview`, `pulse`, and `coverage` with the new keys, a Not Reached Yet month and the
  earlier-orders row. Long values in `synth.ts`: a 300-character problem text, a long API path, a long reference.
- **New interaction states, each at 375, 768 and 1280 px:**
  - `data-overview-running`: a running load with partly filled bars and the pulse;
  - `data-load-start-new`: the Start dialog with new days and Start Load;
  - `data-load-start-nothing-new`: the panel saying so, with no Start Load;
  - `data-load-pause-dialog`;
  - `data-load-priority`: the Priority card filled in;
  - round 2: `data-health-resets-open`, `data-queue-calls`, `data-duplicates-review`;
  - round 3: `data-fetch-day-check`, `data-fetch-list-check`, `data-fetch-requests-running`.

## Verification

1. **Each round:** `ruff check` clean and `pytest -q` green; in `frontend`, `npm run lint`, `npm run typecheck` and
   `npm test` green.
2. **Round 1, the figures against the database** (dev, after the merge; the counts move as the worker runs):
   - `GET /admin/data-load/overview` as the Super Administrator gives:
     - `orders.known` = `select count(*) from orders`;
     - `orders.waiting` = `select count(*) from orders where download_status='pending' and document_id is null`
       (182,929 on 26 Oct);
     - `left.order_pdfs` equal to `orders.waiting`, and equal to `select count(*) from fetch_queue where
       kind='order_pdf' and status in ('pending','running')`;
     - `position.working_on_month` = `2026-01` while `min(ref)` of pending load `causelist_day` rows is in January
       2026.
   - `GET /admin/data-load/coverage` shows October 2025 with `left.order_pdfs` about 5,291 (not 0) and `state`
     `done`, and February to September 2026 with `state` `not_reached`.
   - The sum of every month's orders plus `earlier_orders` equals `orders.known`.
   - The estimate's two dates are in the order details-then-all, with `calls_per_hour` near the call log's last 24
     hours ÷ 24 over queue lanes (about 820).
3. **Round 1, on screen** at `http://localhost:3000/data`, as the Super Administrator:
   - Overview opens first. The four tiles match the API. A month row shows its bars. October 2025 shows "5,291 order
     PDFs" still to fetch.
   - "Updated n s ago" counts. With the tab hidden for a minute, the API log shows no `/pulse` request.
   - The Load tab: Start a Load, Check These Dates over a held range shows "Nothing new to fetch" with no Start Load.
     Pause asks for a reason; pausing, then resuming, writes `data_load.paused` and `data_load.resumed`.
   - The State dashboard shows the Data Collection Progress link.
   - Every table header in the portal is in Title Case, not capitals.
   - With "reduce motion" set in the operating system, bars and numbers change at once and nothing pulses.
4. **Round 3:**
   - Fetch From the Court → All Cases Listed on a Day → 23 Oct 2026, Only Cases Never Fetched → the panel shows the
     day's counts.
   - Every Case Listed → To Fetch about the day's case count. Fetch Details queues them: `select count(*) from
     fetch_queue where lane='request' and kind='dossier' and status='pending'` rises by that number, and
     `GET /audit?action=data_load.day_details_requested` has one row.
   - The request's bar moves from Waiting to Done as the worker runs.
   - A second Every Case Listed within 6 hours shows To Fetch 0.
   - A pasted list of 3 CNRs and 1 unknown case number shows three Will Fetch and one Not Held.
5. **The browser check, each round:** `docker compose --profile uicheck run --rm uicheck`. No finding at 375, 768 and
   1280 px on any page, including the new `gutter` and `doubled-heading` rules. Pages they flag outside Data
   Collection are fixed in the same round where the fix is the hidden caption, or else listed in the report as
   follow-up rows. The new states pass.
6. **The owner's browser check of the three rounds** at 375, 768 and 1280 px becomes a separate backlog row at
   approval.

## Open questions

None. Every decision above is made. The owner's approval covers in particular:
- decision 5, removing upper case portal-wide;
- decision 25, `admin.data_load` for the bulk fetches;
- decision 23, the 6-hour rule and the 2,000 cap;
- decision 33, the three rounds.
