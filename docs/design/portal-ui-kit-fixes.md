# Design: Portal UI kit fixes (captions, dates, phone cards, title before badge, word breaks, empty states, links, plurals)

```
slug: portal-ui-kit-fixes
status: approved
author: architect
date: 2026-11-10
approved_by: owner on 2026-11-10, with the recommended answers to the open questions
```

## Context
Backlog row 231, row A of the portal UI review (row 230, `docs/reviews/2026-11-10-portal-ui-review.md`). On 10 Nov 2026
the owner approved the review with its recommended answers. Every High and Medium finding is fixed, and Low findings
are fixed where they sit in the same files (decisions log, "2026-11-10 — Portal UI review approved; rows 228 and 229
approved (owner)"). This row holds the portal-wide findings that one kit or CSS change can solve on many screens:

- K1 caption padding;
- K5 dates without wrapping;
- K6 phone-card alignment and empty rows;
- K11 title before badge, with Y1, A2's header and the note headers;
- DC1;
- K8 the empty-state rule;
- K9 link placement;
- K10 plurals.

Frontend only: no API change, no migration.

**Order.** The build order is row 204, then **231 (this row)**, 228 `dashboard-my-work-polish`, 232
`portal-names-and-labels`, 233 `portal-screen-fixes-work`, 234 `portal-screen-fixes-oversight`, 229 `portal-navy-cream`,
and then 235.

- Row 228 reuses this row's K1, K9 and K11 changes. Its owner's answers say it uses whatever row 231 already delivers
  and does not build it twice.
- Row 229 changes colours only. Its layout-signature snapshot and screen-box baseline are taken from `main` after rows
  231 to 234 ("Layout findings land first in rows 231 to 234"). So **every spacing, size and alignment change of these
  findings lands here**. None is left for row 229.

**What exists (read at 6dd84d3).**
- **The kit** is `frontend/src/components/ui`.
  - `DataTable` (`data.tsx`) draws one DOM at every width: a table on wide screens, and cards below 820 px or when the
    columns cannot fit (`data-stacked`, `fitTable`).
  - Its CSS (`data.module.css`) pads cells `var(--s3) var(--s4)`. It gives a visible caption only
    `padding: var(--s2) 0` (`:11-15`), so the caption starts at the frame's edge while the cell text starts 16 px in.
  - In card mode each `td` is `display: flex; justify-content: space-between; text-align: right;
    overflow-wrap: anywhere`, with the label drawn from `data-label` by `::before`. That rule is written twice, in the
    phone block (`:112-203`) and in the `data-stacked` block (`:205-290`). Text values therefore sit at the right, while a
    cell whose content is its own flex box (a badge in a row, `HearingDate`) sits at the left, right after the label. A
    cell with nothing in it still draws its label (screenshots `375/inbox-with-me.png` "Status",
    `375/alerts-next-dates.png` "Actions").
  - The caption already gets `display: block` in both card blocks, because a block table would otherwise shrink it to
    its longest word.
- **Visible captions.** `showCaption` is used in `admin/UserDetail.tsx` (2), `audit/BeforeAfter.tsx`,
  `claim/Transfers.tsx`, `dashboard/Blocks.tsx` (6, through `FileList` and directly), `data/AutomaticCollection.tsx`,
  `files/TrackingSummary.tsx` (2), `search/CaseResults.tsx` and `search/TextSearch.tsx`. Three tables outside the kit
  draw their own caption:
  - `causelist/EntryTable.tsx:213`, padded `var(--s2) var(--s4)` but with no `display: block` in its phone block, which
    causes L3 ("Cause- / list / Entries" at 375 px);
  - `reports/ReportView.tsx:112`, with no caption rule;
  - `calendar/DepartmentHearings.tsx:71`, a month heading over a calendar grid.
- **Dates.** `formatDate` and `formatDateTime` (`lib/format.ts:74-96`) join day, month and year with ordinary spaces.
  `DataTable` has no notion of a date column, so in a narrow column a date breaks over three lines ("23 / Oct / 2026",
  K5).
- **Data Collection.** Every panel is `.panel { overflow-wrap: anywhere }` (`data/data.module.css:23`). `anywhere`
  also lowers a word's min-content width to one character, so table columns inside a panel shrink until words and
  numbers break in the middle: "Octob/er 2026", "1,23,4/56" and the header "Tri/es" (DC1, `1280/data-overview.png`,
  `1280/data-problems.png`).
- **Badges before titles.**
  - **System Health.** The court API cards (`system/SystemHealth.tsx:225-233`) and the Access Token card
    (`system/Token.tsx:50-58`) put the status badge in a kit `Lead` (96 px) before the title. The titles do line up,
    but the 96 px column cuts "No Recent Calls" to "No Recent…" and pushes every title 96 px in (Y1,
    `1280/system.png`).
  - **Alerts.** The alert row header on Alerts (`alerts/AlertList.tsx:77-88`) and on the case Alerts tab
    (`workflow/CaseAlerts.tsx:138-144`) runs severity badge, kind, status, the alert's `ref_no` in mono and "New" in
    one line (A2's header).
  - **Notes.** The note headers run kind, `ref_no`, author, date and visibility in one line:
    - `case/Notes.tsx:145-154`;
    - the remarks panel's `NoteHead`, `case/Remarks.tsx:131-141`, which draws the kind itself as a `Badge`;
    - the draft header, `workflow/DraftsPanel.tsx:68-75`: kind, Draft, visibility, dates.
  - Decision 15 of design portal-ui-redesign (the alignment rule) allows a leading badge only in a fixed `Lead`,
    truncated with an ellipsis when too long.
- **Empty states** come in four styles (K8):
  - the kit `EmptyState` with a title (9 uses);
  - `EmptyState` without one (88);
  - about 25 plain muted paragraphs, as an empty branch or as `DataTable`'s `empty`. Examples: `case/Overview.tsx:92`,
    `case/Rail.tsx:250`, `case/Details.tsx:47`, `system/ApiPanel.tsx:70`, `data/Overview.tsx:304`,
    `dashboard/Blocks.tsx:492`;
  - sections that disappear (`dashboard/Blocks.tsx` `FileList` returns `null`, so the department view's Pending
    Actions card vanishes).

  `EmptyState` is a framed box (border, `--s7` padding, a 48 px icon circle), too heavy inside a card.
- **"See all" links** (K9):
  - `T.dash.openCalendar` "Open Calendar →" in the Upcoming Hearings card head (`dashboard/Headline.tsx:132`);
  - `T.case.timelineLink` "Timeline →" in Recent Activity's head (`case/Overview.tsx:126`);
  - the department block's Reports link in the block head (`dashboard/Blocks.tsx:126-129`);
  - bottom-left plain links "Journey and Stage" (`case/Rail.tsx:275`) and "All Next Dates"
    (`nextdates/CaseNextDate.tsx:171`);
  - `T.case.allOrders` "All Orders →", defined but used nowhere.
- **Plurals** (K10):
  - "(s)" in 12 messages (`lib/messages.ts:26, 1186, 1190, 1808, 1863, 2074, 2150, 2235, 2298, 3589, 3592`);
  - unformatted counts in `T.discovery.ruleLine` (`:2234`), `T.offices.users` (`:1249`) and `T.system.courtCount`
    (`:484`);
  - about twenty hand-written `n === 1 ? … : …` messages that print `n` without `formatNumber`.
- **The screen check** (`frontend/e2e/checks.ts`) has ten geometry kinds: overflow, inner scroll, off-screen, clipped,
  size, alignment, primary, gutter, doubled heading and menu clipped. Self-tests are in `uicheck-self.spec.ts`. None
  catches a flush caption, a wrapped date, a word broken mid-word or an empty card row. The review found these by eye.

**Not covered** (see "Out of scope" under Decisions): the names and labels of row 232, the screen-specific findings of
rows 233 and 234, and the colour meanings of row 229.

## Decisions

### A. K1: the caption is inset like the cells
1. **The kit caption is padded like the cells.** `data.module.css` `.table caption` becomes
   `padding: var(--s3) var(--s4) var(--s2)`.
   - In table mode the caption's text then starts exactly where every header and cell text starts: the frame's 1 px
     border plus `--s4`.
   - In card mode the wrapper has no border, and each card is a 1 px border plus `--s4` padding, so the caption sits
     level with the card text, within 1 px.
   - The visually hidden caption (`.srCaption`) keeps its own `padding: 0` (higher specificity), and the `display: block`
     already set in both card blocks stays.
   - On wide screens the caption keeps `display: table-caption`, which already spans the table's full width. The
     review's `display: block; width: 100%` is needed only where the table is a block, and the kit has that already.
     Making a caption `display: block` inside a real table would turn it into an anonymous cell of the first column.
     That is why it is refused for table mode.
   - Alternative: turn every visible caption into a `Card` heading. Refused here. That is the "headings level with the
     column text" kit change that row 228 left to row 230 (row 228, open question 4), and the review did not propose
     it.

   Reaches every `showCaption` table listed in Context: Transfers "To Us", Search "Your Cases", the dashboard
   Department, State and Tickets tables, Automatic Collection, Tracking Summary, User Details and the audit entry's
   Before and After.
2. **The three captions outside the kit follow the same rule.**
   - `causelist.module.css`: in the phone block, `.entries caption { display: block; }` fixes L3 (the padding is
     already `--s4`).
   - `reports.module.css`: a `.scroll caption` rule (or the class the report table uses) with the same padding as its
     cells.
   - The calendar month caption in `DepartmentHearings.tsx` is a heading over a day grid, not a column caption. It gets
     `data-caption="heading"` and is exempt from the check of decision 24.

   L3 is listed under row 234, but its fix is this one line, of the same defect as K1. It is done here and row 234 only
   verifies it (open question 1).

### B. K5: a date never breaks inside itself
3. **The date helpers join a date's parts with no-break spaces (U+00A0).**
   - `formatDate` returns `23 Oct 2026` with U+00A0 between day, month and year. Both paths do this: the IST fallback
     and the `Intl` path, by replacing spaces in the formatted result.
   - `formatDateTime` does the same inside the date part, and keeps an ordinary space after the comma. A narrow cell
     may then put the time on a second line ("23 Oct 2026," / "11:00"), but never splits the date.
   - `formatDateTimeSeconds` and `formatMonthYear` ("October 2026") follow the same rule.
   - `formatTime`, `dayMonth` (the `DateChip` draws day and month on two lines on purpose), `formatWeekday` and the
     long day forms are unchanged.

   Reaches every date in the portal: table cells (Due By, Hearings Date and Next Date, Reports Filed, Mapping and
   Watchlist Updated, Custody Since, System Health's Court Call Log), phone cards, and dates inside sentences ("Please
   answer by 23 Oct 2026").
   - Alternative: a `nowrap` or `kind: "date"` column option on `DataTable`. Refused as the only fix. It reaches only
     columns that someone remembers to mark, and not dates inside a cell's sentence, a phone card or a hand-built table.
4. **Tables may become cards a little sooner.** A date column's minimum width becomes the whole date, about 90 px at
   `--t-md`. A table that only fitted because its dates broke into three lines will now be drawn as cards by `fitTable`.
   At 768 px this is the kit's intended fallback, not a defect (open question 3).
5. **Screen readers and copying are unaffected.**
   - A no-break space is read as a space.
   - The Testing Library matchers already normalise whitespace (`\s` matches U+00A0).
   - Tests that compare exact strings (`toBe("23 Oct 2026")`, 7 lines in the test suite) are updated to the helper's
     output.
   - No date string from these helpers is sent to the API (the API takes ISO dates from the date fields).

### C. K6: phone and stacked cards align their values and hide empty rows
6. **A card row is a two-column grid: fixed label column, values left-aligned.** In both card blocks (phone and
   `data-stacked`), every non-primary `td` becomes:
   - `display: grid; grid-template-columns: var(--card-label-w) minmax(0, 1fr); column-gap: var(--s3);
     align-items: baseline; text-align: left; overflow-wrap: break-word`;
   - `::before` in column 1 and `.cellValue` in column 2 (`min-width: 0`).

   `justify-content: space-between`, `text-align: right` and the `flex: 1 1 auto` on `.cellValue` are removed.
   - Every value of a card starts at the same x, whether it is text, a badge, a button or a multi-line remark ("From
     Joint Secretary to the Govt. of Assam…" no longer right-ragged).
   - A long label ("What the Order Says") wraps inside its column.
   - A non-primary cell without a label keeps the empty first column, so its value still lines up.
   - Right-aligned number columns are left-aligned in cards too. A card has one value per line, so there is no column
     of figures to line up.
7. **New layout token `--card-label-w: 112px`** in `globals.css`, beside `--lead-w`, `--date-w` and `--icon-w` (the
   fixed columns of the alignment rule). At 375 px it leaves about 195 px for the value.
   - Reusing `--lead-w` (96 px) was refused: it is the badge column, and a later language may widen it for a
     different reason.
   - `tokens.test.ts` pins the value.
   - Row 229 leaves sizes alone, so the token passes through its layout signature unchanged.
8. **An empty cell draws no row in card mode.** In both card blocks:
   `td:has(> .cellValue:empty), td:has(> .cellValue > :only-child:empty) { display: none; }`.
   - Table mode is untouched: a column must keep its cell so the columns line up.
   - The two selectors cover a cell whose renderer returns `null` (for example `ReviewActions` for an item with no
     action) and a cell that renders one empty wrapper (for example an empty `Lead` when an inbox row has no state
     badge).
   - The kit's comment on `Column.cell` states the rule: "return `null` when there is nothing to show". A cell that
     shows "—" (an explicit "none") keeps its row.
   - A JavaScript check of each cell's text was refused. It would need to run on every render, and it would miss
     content that arrives later. The CSS is live, and the screen check of decision 24 finds anything left over.
   - The portal already uses `:has` (`globals.css:234`, `filters.module.css:21`).
9. **One rule set, written twice, kept equal.** The phone block and the `data-stacked` block must carry identical
   declarations for `td`, `td::before`, `.cellValue` and the empty-row rule. `data.test.tsx` compares the two blocks,
   so they cannot drift.

   Reaches every `DataTable` drawn as cards: every list at 375 px (Case Inbox, Case Claim, Alerts, Next Dates to
   Enter, Search, case tabs, Administration lists) and every table stacked at 768 or 1280 px (the Custody tab's
   movement record in `1280/cases-…-custody.png`).

### D. K11, Y1, A2's header and the note headers: the title comes first
10. **New kit `ItemHead`** in `data.tsx`:
    `ItemHead({ title, meta, badges, id }: { title: ReactNode; meta?: ReactNode; badges?: ReactNode; id?: string })`.
    - Markup: `<div data-ui="item-head">`, holding `<div class=itemTitle>{title}{meta}</div>` and then
      `<div class=itemBadges>{badges}</div>`.
    - The title always starts at the head's left edge, and the meta (muted: author, date, status words) follows on the
      same line, wrapping between words.
    - The badges sit at the end of the line, never shrink (`flex: none`), and never truncate. When the title needs the
      room they move onto a line of their own below.
    - CSS in `data.module.css`, tokens only. `.itemHead` is a wrapping flex row with gaps `--s1`/`--s3`; `.itemTitle` is
      `flex: 1 1 auto; min-width: 0`; `.itemBadges` is `display: flex; gap: var(--s1); margin-left: auto`.
11. **The alignment rule gains its second form (amends design portal-ui-redesign, decision 15).**
    - A row or card header starts with its title, and badges follow it.
    - A badge may lead only in a list that gives every row a fixed `Lead`. The System Health services list and the
      dashboard's Needs Your Attention keep their `Lead`s.
    - Truncating a badge with an ellipsis stays allowed only inside such a `Lead`.

    This is not a deviation from the plan. The plan does not fix layout. The review recommended it and the owner
    approved it.
12. **System Health cards (Y1).** In `CourtCard` and the Access Token card, the head becomes the title button (`h4`,
    `h3` on the token card, as today) first, then the status badge at the card's top right through `ItemHead`. The
    `Lead` is removed.
    - Every title starts at the card's left padding.
    - "No Recent Calls" shows in full.
    - A long title wraps onto two lines beside the badge.
    - The card's click target, the button's accessible name and `data-status` are unchanged.

    The overview badge's repeated sentence (Y2) is row 234's.
13. **Alert row headers (A2's header)** on Alerts (`AlertRow`) and the case Alerts tab, through `ItemHead`:
    - title: `<strong>{kind_label}</strong>`;
    - meta: the status word (`T.wf.alertStatus`) and, on the case tab, the due time (`T.wf.dueAt`), as today;
    - badges: the `SeverityBadge`, then "New" when unread.

    The alert's `ref_no` is no longer shown (the review: "no alert reference number in sight"). It is not used for
    anything a reader does. A ticket alert keeps its ticket link in the subject line.
    - Row 229 (A1) replaces the severity badge's meaning and tone inside this same end slot, so its badge does not move.
      This is flagged to row 229.
    - The rest of A2 (the case number repeated in the title) is not in this row (open question 2).
14. **Note and draft headers**, through `ItemHead`:
    - **The case Notes tab:**
      - title: `<strong>{kind_label}</strong>`;
      - meta: author text, then the date;
      - badges: visibility.

      The `ref_no` stays in the meta, muted and in mono, exactly as today. Row 233 (the rest of P12) removes it, and row
      232 replaces the office code with the office name (K2).
    - **The remarks panel's `NoteHead`.** The kind changes from a `Badge` to the `<strong>` title, as on the Notes tab.
      Meta and badges are as on the Notes tab.
    - **Drafts:**
      - title: the kind;
      - meta: created and updated;
      - badges: "Draft" (warning), then visibility.

    `case.module.css .noteHead` stays: the case Timeline (title first already, after its `DateChip`) and the
    department hearings agenda (case link first) still use it. `remarks.module.css .noteHead` is removed if nothing
    else uses it.

### E. DC1: words and numbers break only between them
15. **`overflow-wrap: break-word` on the Data Collection panel.** `data/data.module.css .panel` changes from `anywhere`
    to `break-word`.
    - A word that cannot fit its line still breaks, so nothing overflows.
    - A word's min-content width is its full length again, so a table column no longer shrinks until "October" and
      "1,23,456" split.
    - If Month by Month then no longer fits as a table at some width, `fitTable` draws it as cards (the kit's
      fallback).
16. **A free-text marker for long free text: `[data-free-text]`.** `globals.css` gets
    `[data-free-text] { overflow-wrap: anywhere; }`. It is set only where long unbroken machine text can appear in a
    narrow cell, so those cells keep a table a table:
    - the Failed Fetches "Problem" cell (`r.last_error`, raw paths such as `/nic/ecourts/hc-cnr-api/v1.0/…`);
    - the Possible Duplicates "Reason" cell.

    The kit `DataTable` card cells move from `anywhere` to `break-word` in decision 6, for the same reason. The other
    module rules that already say `anywhere` (assistant, audit, rail, remarks…) are left alone unless the new check of
    decision 24 flags them on a screen. Then they are fixed the same way in this row. If more than a handful are flagged,
    the developer lists them in the report rather than widening the row.

### F. K8: one empty-state rule
17. **The rule.**
    - (a) **Lists and panels** use the kit `EmptyState`.
    - (b) The **main list of a page or a case tab** gives it a title:
      - the four Case Inbox tabs and three Case Claim tabs;
      - Alerts and Next Dates to Enter;
      - Cause List entries and Search results;
      - the case tabs Orders, Hearings, Documents, Notes, Custody, Timeline, Links and Alerts;
      - Audit Log;
      - Users, Offices, Designations and Tickets;
      - Failed Fetches and Possible Duplicates;
      - Assistant conversations.
    - (c) An empty list **inside a card or panel** uses the new `compact` form.
    - (d) A plain muted line is allowed only as a value inside a fact or definition list (`KvList`, `DefinitionList`,
      `dl.facts`).
    - (e) A panel that a page always shows keeps its frame and shows its empty state instead of disappearing. A panel
      shown only to some readers or only when relevant may still be left out, when its design says so. Row 228
      decision 4, for example, keeps My Cases and Cases with Me hidden when empty.
18. **Kit `EmptyState` gains `compact?: boolean`.** It renders `data-compact`, with no frame (border and background
    removed), no icon, padding `var(--s3) 0` and left-aligned muted text, with the title in `--text` weight 600 when
    given. The full form is unchanged.
19. **The sweep.**
    - Each muted-paragraph empty branch and each `DataTable` `empty={<p …>}` becomes `EmptyState` (compact inside cards
      and panels).
    - The primary lists of 17(b) gain titles. These are new `messages.ts` strings on the Title Case guard's label paths,
      for example "No Cases With You", "No Notes Yet" and "No Alerts".
    - `FileList` (`dashboard/Blocks.tsx`) takes an optional `empty`. Without it, it still returns `null`, so row 228's
      `PersonalExtras` keeps hiding Cases with Me when empty.
    - The department view's Pending Actions card shows whenever the server sends `pending_actions`. The server sends it
      only to readers with the tracking or reports function (`test_pending_action_sections_need_track_or_reports_function`).
      An empty list then shows a compact "No Pending Actions." inside the card, instead of the card vanishing.

### G. K9: one place and one look for "see all" links
20. **New kit `HeadLink`** in `layout.tsx`: `HeadLink({ href, children, srSuffix })`.
    - It renders a Next `Link` with the visible words, then `<span aria-hidden="true"> →</span>`, then a visually
      hidden `srSuffix` so that two links on a page have distinct accessible names.
    - It is placed in a `Card`'s `actions` slot, or in a `Block`'s `action`.
    - New message `T.viewAll` "View All".

    This is exactly the form row 228 decision 2 sets for the dashboard. Row 228 uses `HeadLink` and `T.viewAll`
    rather than its own `T.dash.viewAll`.
21. **The wording rule.**
    - A link that opens the whole list of what the card shows reads "View All", with the hidden suffix naming it.
    - A link that goes to a different screen keeps that screen's name, with the arrow.
    - A link inside a sentence is a prose cross-reference and stays as it is. Examples are the Reports page's "Data
      Collection Overview" and "Department" lines (`reports/ReportPage.tsx:113-121`).
22. **Places changed in this row.**
    - Upcoming Hearings: "Open Calendar →" becomes `HeadLink` "View All", suffix "Upcoming Hearings", to `/calendar`.
    - Recent Activity: "Timeline →" becomes "View All", suffix "Activity", to the Timeline tab.
    - The department block's Reports link becomes `HeadLink` "Department Reports".
    - The unused `T.case.allOrders`, `T.dash.openCalendar` and `T.case.timelineLink` are removed.
    - The rail's "Journey and Stage" and the Overview's "All Next Dates" have no card head to move into today. Their
      containers' headings are built by row 233 (P7 rail card headers, P8 the Waiting for You block), which places them
      with `HeadLink` "View All". They are not moved twice.

### H. K10: plurals and counts
23. **New helper `plural(n, one, many)`** in `lib/format.ts`. It returns `${formatNumber(n)} ${n === 1 ? one : many}`,
    so `plural(123456, "case", "cases")` gives "1,23,456 cases".
    - The 12 "(s)" messages use it ("2 attempts left", "3 assigned cases, 1 case with them…", "12 pages", "Up to 5
      files").
    - So do the three unformatted counts: `T.discovery.ruleLine`'s found count (AD4's "123456 case(s) found" becomes
      "1,23,456 cases found"), `T.offices.users` and `T.system.courtCount` (`formatNumber` on both numbers).
    - The hand-written `n === 1 ?` messages in `messages.ts` that print a number move to it in the same change (same
      file, Low). Messages that use words for one ("One Case", "1 minute" handled by `minutes`) keep their wording.

### I. Automatic checks
24. **Four new geometry kinds in `frontend/e2e/checks.ts`**, added to `GEOMETRY_KINDS` and the file's header comment:
    - **`caption-inset`** (K1, L3). For every visible `caption` not marked `data-caption="heading"`:
      - when its table is drawn as a table, the first line of the caption's text (a `Range` rect) must start within
        2 px of the content-box left of the table's first visible header cell;
      - when the table is a block (cards), the caption must be at least 90% of the table's width (the L3 squeeze).
    - **`date-wrap`** (K5). In `main#main`, any text node holding a day-month-year date (`\d{1,2}[  ][A-Z][a-z]{2}[
       ]\d{4}`) whose `Range` rects have more than one distinct top is a finding.
    - **`broken-word`** (DC1). In `main#main`, outside `[data-scroll-x]`, `pre`, `code`, `[data-free-text]` and visually
      hidden boxes, a word of four or more letters only (`^[A-Za-z]{4,}$`) or a number of four or more digits and
      commas (`^[\d,]{4,}$`) whose `Range` rects have more than one distinct top is a finding. Words with hyphens,
      slashes or dots are not tested: they have legal break points.
    - **`card-row`** (K6). In every `DataTable` drawn as cards (a block `table` whose cells carry `data-label`):
      - a visible labelled `td` whose value box has no text and no `a`, `button`, `input`, `select`, `img`, `svg`,
        `progress` or `meter` is a finding (an empty row);
      - within one card, the value boxes' left edges must be equal within 1 px.

    Each kind gets a passing and a failing self-test page in `uicheck-self.spec.ts`, in the style of the gutter and
    doubled-heading self-tests.
25. **K8, K10 and K11 are guarded in vitest** (decision 26). They are about source and DOM order, which a geometry
    check would catch only loosely.

### Out of scope (other rows)
- **Row 232:** K2 names where codes show (including the `ref_no` and office codes kept in the note headers), K3 Title
  Case of server labels, K4, P9, U1, P4, R1, R2, D1's strings, and the wording fixes S3, A3, L2, C3 and P12's case.
- **Row 233:** I1 to I5, P1, P2, P5 to P8 (including where the rail's "Journey and Stage" and the Overview's "All Next
  Dates" go), P10, P11, the rest of P12 (the note `ref_no` out of sight), P13, A4 (its passed answer-by date; its empty
  Actions row is fixed here by decision 8), C1, C2, D2 and D3.
- **Row 234:** S1, S2, L3's verification (fixed here by decision 2, open question 1), R3, DC2 (plain-words problems,
  which builds on decision 16's marker), Y2, U2 and AD1 to AD4.
- **Row 229:** K7 notice tones, A1 alert tone by meaning (into the end slot of decision 13), C4 one recommendation
  tone, and every colour value. This row adds no colour and changes no colour token.
- **Row 228:** the nine points of More About My Work. It reuses decisions 1, 13 and 20 here.

## Data
None. No table, column, reference code or index is added or changed. **No migration.** `docs/schema/schema.md` is
unchanged.

## Services
None. No backend module changes.

## API
None. No endpoint, schema or permission changes. `frontend/openapi.json` and `schema.d.ts` are unchanged. Every value
shown comes from fields the portal already reads.

## Jobs
None.

## Tests
**vitest**
26. `components/ui/data.test.tsx`:
    - `.table caption` has `padding: var(--s3) var(--s4) var(--s2)`, and `.srCaption` keeps `padding: 0`.
    - In both card blocks, `td` is `display: grid` with `grid-template-columns: var(--card-label-w) minmax(0, 1fr)`,
      `text-align: left` and `overflow-wrap: break-word`. Neither block contains `justify-content: space-between` or
      `overflow-wrap: anywhere` on `td`.
    - The phone block and the `data-stacked` block carry identical declarations for `td`, `td::before`, `.cellValue` and
      the two empty-row selectors.
    - `DataTable` renders a cell returning `null` as an empty `.cellValue`, and a cell returning an empty `Lead` as one
      empty child. A cell showing "—" or a button is not empty. (jsdom does not run `:has`, so this test checks the
      structure the CSS relies on, and the selectors' presence is checked in the CSS.)
    - `ItemHead` puts the title first in DOM order, then the meta, then the badges. It carries `data-ui="item-head"` and
      contains no `[data-lead]`.
27. `components/ui/ui.test.tsx`:
    - `EmptyState compact` renders `data-compact` and no icon, and with `title` renders the title.
    - Without `compact`, the output is unchanged.
    - `HeadLink` shows its words and an `aria-hidden` arrow, and its accessible name includes `srSuffix`.
28. `components/ui/tokens.test.ts`: `--card-label-w` is pinned at `112px` beside the other fixed columns. The spacing
    check passes for every changed module.
29. `lib/format.test.ts`:
    - `formatDate` of 2026-10-23 is `"23 Oct 2026"`;
    - `formatDateTime` is `"23 Oct 2026, 11:00"` (an ordinary space after the comma);
    - `formatMonthYear` is `"October 2026"`;
    - the `Intl` path gives the same characters.

    `plural(0, "case", "cases")` is "0 cases", `plural(1, …)` is "1 case" and `plural(123456, …)` is "1,23,456 cases".
    The 7 exact-string date assertions elsewhere are updated.
30. `lib/labels.test.ts`, or a new `lib/messages.plural.test.ts`:
    - the source of `messages.ts` contains no `(s)` after a word;
    - `T.discovery.ruleLine(…, 123456)`, `T.offices.users(1234)` and `T.system.courtCount(1234, 12345)` contain
      "1,23,456", "1,234" and "12,345";
    - every changed message function is listed in `LABEL_FUNCTIONS` where it is a label.
31. **Empty-state guard**, new `components/emptyState.guard.test.ts`. It scans `src/components/**/*.tsx` (not tests,
    not `ui/`):
    - it fails on `empty={<p` and `empty={<span`;
    - it fails on an empty-list branch (`length === 0 ? (` followed by `<p className=` with a muted class);
    - for the files of decision 17(b), the empty branch's `<EmptyState` carries `title=`.

    Allowed exceptions live in an allowlist with a reason each: a fact inside a `dl` and the text-search result line.
32. **Screens:**
    - `components/system/system.test.tsx` and `console.test.tsx`: each court API card and the token card has its title
      button before its badge in DOM order. There is no `[data-lead]` in the card head. The badge reads the full word
      ("No Recent Calls" with a fixture card of that status). The existing Lead assertions are replaced.
    - Alerts (`alerts` tests) and the case Alerts tab (`workflow` tests): the head's first element is the kind label,
      the severity and New badges follow it, and the alert's `ref_no` text is not in the row.
    - `components/case/case.test.tsx` and `remarks.test.tsx`: in a note head the kind is a `<strong>`, not a `Badge`. It
      comes first, and the visibility badge is in the badges slot. The draft head shows Draft and the visibility after
      the kind.
    - `components/dashboard/dashboard.test.tsx`:
      - Upcoming Hearings has a "View All" link to `/calendar` with the accessible name "View All Upcoming Hearings";
      - the department block's Pending Actions card shows with "No Pending Actions." when `pending_actions.items` is
        empty and `held` is 0, with "No Overdue Pending Actions." when it is empty and `held` is above 0, and stays
        hidden when `items` is null (see Deviations);
      - `PersonalExtras` still hides Cases with Me when empty.
    - `components/case/case.test.tsx`: Recent Activity's head link is "View All", to the Timeline tab.
    - `components/data/data.test.tsx`: `.panel` has `overflow-wrap: break-word`. The Failed Fetches Problem cell carries
      `data-free-text`. `globals.css` has the `[data-free-text]` rule.
    - `components/causelist/causelist.test.tsx`: the phone block gives `.entries caption` `display: block`.

**uicheck**
33. **Self-tests** in `uicheck-self.spec.ts` for the four kinds of decision 24. Each has a page that passes and one
    that fails:
    - `caption-inset`: a flush caption fails, and an inset one passes;
    - `caption-inset` squeeze: a caption in a 60 px box fails;
    - `date-wrap`: a date in a 40 px cell fails, and the same date with U+00A0 in a wide cell passes;
    - `broken-word`: "October" under `overflow-wrap: anywhere` in a 30 px box fails, and inside `[data-free-text]` it
      passes;
    - `card-row`: an empty labelled cell fails, and two cards with unequal value edges fail.
34. **The full run** (every route and state at 375, 768 and 1280 px): no finding of any kind, old or new. Fixtures need
    no change: they already show a no-action next-date item (`375/alerts-next-dates.png`), inbox rows without a state
    badge, long dates, Month by Month with large counts and a "No Recent Calls" card.

## Verification
1. The developer and the tester run, in `frontend/`, `npm run lint`, `npm run typecheck` and `npm test`: all green.
   The backend is untouched; `pytest -q` stays green.
2. The integrator runs uicheck on a **private network against temporary images**, as `docs/operations.md` section 16
   says, never through Compose on the shared stack:
   - build `frontend/` as `tmp231-web` and `frontend/e2e/Dockerfile` as `tmp231-uicheck` (build argument
     `PLAYWRIGHT_VERSION`);
   - create network `tmp231-net`;
   - start `tmp231-web` on it with alias `web`, `API_BASE_URL=http://api:8000`, `PORTAL_BASE_URL=http://web:3000` and
     `COOKIE_SECURE=false` (every API answer comes from the fixtures);
   - run `tmp231-uicheck` with an output folder at `/out`.

   Expected: every test passes at 375, 768 and 1280 px with no finding, the four new kinds included, and the
   self-tests pass. Then remove the container, the network and both images.
3. The integrator compares these screenshots with the review's (same slugs) and attaches them to the report:
   - `1280/system.png`: titles at the card's left, "No Recent Calls" whole, badge at top right;
   - `375/inbox-with-me.png` and `375/alerts-next-dates.png`: values in one column, no empty "Status" or "Actions"
     row, remarks left-aligned;
   - `1280/data-overview.png` and `1280/data-problems.png`: "October 2026", "1,23,456" and "Tries" whole;
   - `1280/claim-transfers.png`: the "To Us" caption level with the column text;
   - `375/causelist.png`: "Cause-list Entries" on one line;
   - `1280/cases-…-hearings.png`: dates on one line;
   - `1280/alerts.png` and `1280/cases-…-notes.png`: title first, badges after.
4. Deploy: no migration and no `init`. Images are built from a clean worktree of `main`, the app services are recreated
   with `--no-deps --force-recreate` carrying the court-data switch, and the web build ID is checked.
5. The owner looks at http://localhost:3000 at a phone width (or the browser's 375 px view) and at 1280 px: Case Inbox
   With Me, Alerts, Next Dates to Enter, a case's Notes and Hearings tabs, System Health and Data Collection Overview.
   Each point of step 3 is checked by eye.

## Open questions
Each question has a recommended answer. The design is complete with those answers, so the owner may approve "with the
recommended answers".

1. **L3 (the squeezed Cause List caption) is fixed here, not in row 234.** Its fix is one line of the K1 defect
   (decision 2), and the new `caption-inset` check would fail on it otherwise.
   - **Recommended:** fix it here; row 234 only verifies it.
   - Alternative: exempt the cause-list caption from the check until row 234.
2. **The rest of A2: the alert title repeats the case number** on Alerts and the case Alerts tab. No row of 231 to 234
   lists it. A fix that is only in the portal would split the rule that row 228 decision 12 kept on the server.
   - **Recommended:** row 233 carries it, adding row 228's `summary` (from `alert_rules.title_without_case`) to the
     `GET /alerts` items as an additive field, and showing the case once as the link. That is a small API addition in
     row 233.
   - Alternative: leave it as a known Low finding.
3. **Dates never break, so some tables become cards sooner** (decision 4). Most likely affected are wide lists at
   768 px.
   - **Recommended:** accept it. Cards are the kit's designed fallback, and a date over three lines is the defect the
     owner approved fixing.
   - Alternative: also mark date columns `nowrap` and let other columns wrap harder. That gives the same result with
     more code.
4. **Titles on the main empty lists** (decision 17(b)) add about 30 short strings.
   - **Recommended:** yes, Title Case titles on the main list of each page and case tab, and compact untitled empty
     states inside cards.
   - Alternative: titles only on the eight case tabs and the four Case Inbox tabs.
5. **"See all" wording** (decision 20).
   - **Recommended:** visible "View All →" with the target named for screen readers, as row 228 approved for the
     dashboard.
   - Alternative: visible "View All Hearings", "View All Activity". This is clearer out of context, but wider in a card
     head at 375 px.

## Deviations
None from the plan, which does not fix the layout of these elements. Earlier design decisions this row amends:
- **Decision 15 of portal-ui-redesign** gains the title-first form (decision 11). The leading `Lead` with an ellipsis
  stays for lists that give every row one.
- **Design data-collection-redesign's panel rule** ("a long value wraps", `overflow-wrap: anywhere`) becomes
  `break-word`, with `[data-free-text]` for long machine text (decisions 15 and 16).

**Build deviations (developer, 10 Nov 2026).** The smallest choices made where the design was silent or read older
code:
- **`plural` lives in a leaf module.** `messages.ts` cannot import `lib/format.ts` (`format.ts` imports `i18n.ts`, which
  imports `messages.ts`, so `T` would be read before it exists). The helper and the Indian grouping are in the new
  `lib/digits.ts` (no imports); `format.ts` re-exports `plural` and uses the same grouping for English.
- **`T.case.allOrders` was in use** (the Latest Order card's head on the case Overview), not unused as read at 6dd84d3.
  By the wording rule of decision 21 it became `HeadLink` "View All" with the hidden suffix "Orders", and the key was
  removed with the other two.
- **The two attachment messages keep whole phrases** (`wf.attachHint`, `wf.tooManyFiles`): "Up to 1 file; …" / "Up to
  1,234 files; …". Passing "file" and "files" to `plural()` as separate strings fails the wording guard
  (`wording.test.ts`), which allows the computer-file sense only inside "Up to n files" and "At most n files".
- **The cause-list cards follow decisions 6 and 8 too.** `EntryTable` is a hand-built table whose cells carry
  `data-label`, so the `card-row` check reads it. Its labelled cells hold one value box, laid out on the same grid, and
  an empty Action cell draws no row.
- **"New" on the case Alerts tab** shows only for an alert that reached the reader (`notified_at` set, `read_at` null).
  The tab also lists alerts of the case sent to others, whose read state is not the reader's.
- **Copy to Note keeps ordinary spaces.** `noteText` (the Assistant's Copy to Note) puts formatted dates into a note's
  text, which is stored and searched on the server; it turns the no-break spaces back into spaces. `fold` in
  `lib/listSearch.ts` does the same, so a list search for "12 Oct" matches.
- **The report caption needed no rule of its own.** The report table uses the kit's `.table` class, so decision 1's
  caption padding reaches it.
- **The empty-state guard's allow-list** holds one entry: Automatic Collection's "share is off" line, a setting's state
  rather than an empty list. The fact-list values are not caught by its pattern, so they need no entry.
- **`wait()` in `messages.ts`** names its variable `secs`, so the "(s)" guard does not read `isFinite(s)` as a plural.
- **A kit column option `actions`.** With the fixed 112 px label column, two single buttons no longer fit the value
  column of a 375 px card ("Use the Standard Weight" on Department Mapping's scoring table, "Stop Using Everything" on
  Collect Now's Request List; the browser check's `gutter` and `inner-scroll`). A column marked `actions` has no card
  label and runs the card's full width, because its buttons name themselves. Only those two columns use it;
  `expectDataTable` accepts the cell without a label.
- **More `[data-free-text]` marks**, found by the new `broken-word` check on System Health: the request envelope's
  values and headers in the console (a 64-character token) and the token request's body.
- **The Pending Actions card follows the list, not the section** (review finding). Decision 19 read the card as
  showing whenever `pending_actions` is sent, but the server fills `pending_actions.items` only for readers with
  `custody.track` or State scope (others get `null`), and the list holds only overdue files. So the card shows only
  when `items` is a list; empty, it says "No Pending Actions." only when `held` is 0 and otherwise "No Overdue Pending
  Actions.", so it never contradicts the Pending Actions count above it. A reader with the reports function alone sees
  the count and no card, as before this row.

## Owner's answers (10 Nov 2026)

All open questions answered with the recommended answers.
