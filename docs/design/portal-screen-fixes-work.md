# Design: Portal screen fixes, work screens (Dashboard, Case Inbox, Case Claim, Case page, Alerts, Cause List)

```
slug: portal-screen-fixes-work
status: approved
author: architect
date: 2026-11-10
approved_by: owner on 2026-11-10, with the recommended answers to the open questions
```

## Context
Backlog row 233, row C1 of the portal UI review (row 230, `docs/reviews/2026-11-10-portal-ui-review.md`, screenshots in
`docs/reviews/2026-11-10-portal-ui-review/`). On 10 Nov 2026 the owner approved the review with its recommended answers:
every High and Medium finding is fixed, and Low findings are fixed where they sit in the same files (decisions log,
"2026-11-10 — Portal UI review approved; rows 228 and 229 approved (owner)"). This row holds the screen-specific findings
of the work screens:

- Case Inbox: I1 to I5;
- Case page: P1, P2, P5 to P8, P10, P11, the rest of P12, P13;
- Alerts: A4, and the rest of A2 (handed over by row 231, open question 2 of `portal-ui-kit-fixes`);
- Case Claim: C1, C2;
- Dashboard: D2, D3.

Medium findings here: I1, I5, P2, P6 and D3. High: P11. The rest are Low and sit in the same files.

**Order and dependencies.** The build order is row 204, 231 `portal-ui-kit-fixes`, 228 `dashboard-my-work-polish`, 232
`portal-names-and-labels`, **233 (this row)**, 234 `portal-screen-fixes-oversight`, 229 `portal-navy-cream`, 235. Row 229
changes colours only and takes its layout baseline from `main` after rows 231 to 234, so every layout change of these
findings lands here. This row uses, and does not rebuild:

- **Row 231** (`docs/design/portal-ui-kit-fixes.md`):
  - `formatDate` with no-break spaces (K5), so no date in this row needs its own `nowrap`;
  - the card-row grid and the hidden empty card row (K6), which already fixes A4's empty "Actions" row on phones;
  - `ItemHead` (title first, badges at the end) for the note and alert heads (K11);
  - `HeadLink` and `T.viewAll` for every "View All →" link (K9). Row 231 decision 22 leaves the rail's "Journey and
    Stage" and the Overview's "All Next Dates" to this row, once their headings exist;
  - `EmptyState compact` and the empty-state rule (K8);
  - `plural()` (K10), which already fixes P13's "2 page(s)".
- **Row 228** (`docs/design/dashboard-my-work-polish.md`): `alert_rules.title_without_case` and the `summary` field on the
  dashboard's alerts; the Due rule "date, Overdue by N Days, No Due Date" and its strings.
- **Row 232** (`docs/design/portal-names-and-labels.md`): the read-only `GET /reference/offices` and
  the kit `OfficeName` (props `code`, `name`, `href`; helper `officeName(code, map)`), the K2 sweep that replaces office and department codes with names (including P3, L1, the
  Custody tab, note authors, Pool and Transfers), Title Case of server labels (K3), the label helper (K4), P4 (order
  kind) and the wording fixes S3, A3, L2, C3 and the case of P12's correction words. Where this note says
  `OfficeName`, it means row 232's component; this row only moves cells around it. Row 232 first names the codes
  inside `T.inbox.fromTo`, `T.inbox.best` and `T.claim.poolBest`; decisions 20 and 21 here then retire those strings,
  and row 232's Title Case of `T.case.corrects` / `T.case.correctedBy` is replaced by decision 14's dated sentences
  (its decision 33 leaves that to this row).

**What exists (read at 6dd84d3).** Each finding's cited code was read; the facts that shape a decision are given with the
decision. In short:

- The four Case Inbox tabs (`components/inbox/InboxFrame.tsx`) draw With Me through `files/Held.tsx`, Sent by Me through
  `files/Sent.tsx`, My Cases through `inbox/MyCases.tsx` and Department through `inbox/DepartmentCases.tsx`. Only
  Department uses `FilterBar layout="card"` (Filter Layout B, design portal-ui-polish-2 decision 22). With Me and Sent
  by Me draw a 96 px lead column whose header is hidden (`Held.tsx:160-167`, `Sent.tsx:53-59`), and two `CaseCell`
  components exist: a `CaseLink` in `Held.tsx:65-85` and plain text in `inbox/rows.tsx:16-30`.
- The case header (`case/CaseFrame.tsx:335-389`) draws the status badge and a fifth fact "Status" (hidden on phones).
  `case.module.css .facts` is a five-column grid that `workflow/CustodyTab.tsx` also borrows for the custody card and
  the stage card, so the custody remark (the sixth item) wraps into the first column (P11's cramped card).
- The header's `NextHearingFact` and the rail's `NextHearing` both draw `HearingDate size="md"` with its explanation
  lines; the Overview's next-date block draws a third badge with its origin line (P2).
- The Movement Record asks `GET /cases/{ref}/custody` with the API's default `order=asc`
  (`lib/api/hooks.ts:219-224`), while the rail's journey and the remarks panel ask `order=desc` (P11).
- The kit `Tabs` (`ui/layout.tsx:136-230`) scrolls sideways (`data-scroll-x`) and has a fixed `more` group.
  `RAIL_MIN_WORKSPACE` is 936 px, so beside the rail the tab column can be as narrow as 600 px (P6).

**Not covered:** the oversight screens (row 234), names and labels (row 232), the kit fixes (row 231), the colour
meanings K7, A1 and C4 (row 229), and More About My Work (row 228).

## Decisions

### A. Case Inbox (I1 to I5)

1. **Layout B on all four tabs (I1).** With Me, My Cases and Sent by Me move to `FilterBar layout="card"` with
   `hero="q"`, as Department already is. The tracker's Department list (the `Held tab="pending"` branch) follows With Me.
   - **The button reads "Search"** on every tab (the card's submit, as on Search, Cause List and Department). The bar's
     "Apply" remains only on the lists outside the inbox that keep `layout="bar"`.
   - **The count is always at the head of the summary strip**, through the page's `countLine` and the shared
     `CountLine` (`ListCount`): "n cases", or "n of m cases" when filtered. The unfiltered m is:
     - With Me (Show With Me): `files` of `/inbox/mine/counts`, which `InboxFrame` already reads, passed down as a new
       `unfiltered` prop of `Held`. With My Offices and the tracker's list have no unfiltered figure, so they read
       "n cases match" when filtered and "n cases" otherwise (the `ListCount` rule);
     - Sent by Me: none (the same rule);
     - My Cases and Department: as today (`all_open` / `all_closed`, `claimed_open` / `claimed_closed`).

     `FilterBar`'s own `total` line is no longer passed by the four tabs, so no tab shows two counts.
   - **The fields**, each tab drawing only the fields it takes today (no filter, URL key or API change):

     | Tab | Hero | Right zone | More Filters |
     |---|---|---|---|
     | With Me | Words | Show (With Me / With My Offices, applies at once), Overdue Only, Next Hearing, Case Type | Cause-List Date, Year, Status, Court, Bench, Department, Next Date Differs |
     | Sent by Me | Words | Show Earlier, Next Hearing, Case Type | as With Me |
     | My Cases | Words | Stage, Case Type | Year, Court, Next Date Differs |
     | Department | Words | unchanged (Unit, Officer, Stage, Next Hearing, Case Type) | unchanged |

     Each tab passes `more` (the shared fields under More Filters) and marks its own controls `first` or `more` to
     give this table. The words box keeps `T.filters.wordsShort` with `T.filters.wordsHint`, as on Department.
   - **The quick controls sit above the card on every tab**, in the one switch row (`inbox.module.css .switchRow`):
     With Me's Ready to Close chip, My Cases' Open / Closed switch and Hearing This Week chip, Department's switch and
     chips. Sent by Me has none.
   - Alternative: Layout A (the stacked bar) on all four. Refused: Department moved to Layout B by the owner's mock-up
     (row 163), and Search and Cause List use it.
2. **One case cell, plain bold, on all four tabs (I2).** `inbox/rows.tsx CaseCell` becomes the only case cell of the
   inbox; `files/Held.tsx CaseCell` is removed and Held and Sent import the shared one. The case number is plain
   (`cno`, or `mono` for a bare reference) on every tab, because every row is itself the click target: My Cases and
   Department rows open the case page, With Me and Sent by Me rows open the side panel, whose footer already carries
   "Open Case Page". One link inside a clickable row would be a second tab stop per row.
   - The cell gains `marks?: { label: string; tone?: Tone }[]`, drawn as small badges on one line under the number and
     before the parties (decision 4).
   - Alternative: a link everywhere. Refused for the double tab stop, but it keeps one-click access to the case from
     With Me; open question 1.
3. **No lead column (I3).** The unlabelled 96 px column of With Me and Sent by Me is removed with `LeadCell` and the
   `leadBadge` calls of those tabs. Its words go where they mean something:
   - "Overdue" and "Due Soon" become the Due line of decision 5;
   - "New" (received in the last 48 hours, With Me only) becomes a mark under the case number (`T.cases.lead.new`,
     tone `info`);
   - "Waiting" (Sent by Me, the file still with the addressee) is dropped: by default Sent by Me lists only files still
     out, and in Show Earlier the rows that moved on are already muted (`s.mutedRow`).

   `leadBadge`'s `working` branch has no caller left after this and is removed with the function's tests for it; the
   other branches go too if nothing else calls them (the developer checks with a search).
   - Alternative: keep the column with a visible "State" header. Refused: after decision 5 it would hold only "New", and
     a column for one word is the empty column the review reports.
4. **"Ready to Close" and "Closed" are marks of the case, not of the hearing (I4).** `ClosureBadge` leaves the Next
   Hearing cell on With Me, My Cases and Department. Its value (`Closed`, neutral; `Ready to Close`, warning) becomes a
   mark under the case number through decision 2, with the same rule as today (`closed`, or `closed === false` and
   status `disposed`). Sent by Me's "Recalled" (today a text `mark`) becomes a neutral mark in the same place. The Next
   Hearing cell then holds only `HearingDate`, and `inbox.module.css .nextCell` goes.
5. **One "Action Needed" cell with one Due line (I5).** A new `ActionDueCell` in `inbox/rows.tsx`: the pending action
   label on the first line and the shared `DueLine` under it. It replaces With Me's separate Action Needed and Due By
   columns, Sent by Me's two columns and My Cases' "Your Action" (`ActionCell`, removed). The header is
   `T.files.action` "Action Needed" on all three tabs. A case with no pending action shows "—".
   - **`DueLine`** (exported from `inbox/rows.tsx`, used by the cell and by the side panels' Due fact):
     - no due date: a muted "No Due Date";
     - overdue: `Badge tone="danger"` "Overdue by N Days" with the due date as its `title`;
     - due soon: `Badge tone="warning"` "Due 12 Nov 2026" (`T.inbox.dueOn`);
     - otherwise: the date as text.
   - **Who decides.** With Me and My Cases read the server's `overdue`, `overdue_days` and `due_soon` from the custody
     card or brief. Sent by Me legs carry no flags, so it keeps today's rule from `lib/cases.ts` (overdue when the
     current leg's date is before today in IST; due soon within `SENT_DUE_SOON_DAYS`), and counts the days with
     `daysUntil`.
   - **Strings.** Row 228's `dash.overdueByBadge(n)` and `dash.dueNoneLabel` move to a shared `T.due` group
     (`overdueBy(n)`, `none`). The dashboard and the inbox both read it, so the words are the same in both places. The
     old `T.inbox.overdueDays` and `T.files.overdueBy` go.
   - **Deviation from row 228's three states, flagged:** the inbox keeps a fourth state, "Due soon", because the With
     Me lead badge showed it (design case-workspace-admin, decision 19) and the server sends `due_soon`. The dashboard's
     payload has no due-soon flag, so it keeps its three states.
   - Columns after decisions 3 to 5:
     - With Me: Case, Next Hearing, Action Needed, From, chevron;
     - Sent by Me: Case, Action Needed, Sent To, chevron;
     - My Cases: Case, Reason, Stage, Next Hearing, Action Needed, chevron;
     - Department: unchanged (Case, Unit · Officer, Stage, Next Hearing, File Is With, chevron).
   - Alternative: separate Action Needed and Due By columns on all three. Refused: My Cases would have seven columns and
     would fall back to cards at 1280 px.

### B. Case page (P1, P2, P5 to P8, P10 to P13)

6. **The status shows once, as the badge beside the title (P1).** The "Status" fact is removed from the header facts
   (`CaseFrame.tsx:381-383`) with `Fact`'s `status` prop and `case.module.css .factStatus`. The badge already shows at
   every width. `.facts` becomes `repeat(4, minmax(0, 1fr))` (two columns below 820 px, as today).
7. **The custody and stage cards get their own facts grid (P11, and needed by decision 6).** `CustodyTab.tsx` stops
   borrowing the header's `.facts`. A new `case.module.css .cardFacts` is
   `grid-template-columns: repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, with `.cardFacts .wide` set to
   `grid-column: 1 / -1`. The custody card's Remark and the stage card's Note are `wide`, so a long remark takes the
   card's full width under the short facts instead of one word per line in the first column.
8. **The explanation of the next hearing lives in one place, the rail's Next Hearing card (P2).**
   - **Header:** `NextHearingFact` draws `HearingDate` with `lines={false}`. That is the badge with its band word and
     date, and the "Order Differs" chip with its sentence as the `title`. The court and item line stays when the latest
     listing places the case on that day, because it is a fact of the date, one short line. The "Reported as possibly
     wrong" line leaves the header.
   - **Rail card:** unchanged. It keeps the basis line, the differs sentence and the reported line, at every width. Below
     1100 px it is the collapsible card right under the header, with the badge in its closed summary.
   - **Overview:** decision 10 turns the next-date block's badge into a plain line about the order.
   - Alternative: keep the explanation in the Overview block. Refused: the Overview is one tab among eight, while the
     rail shows on every tab.
9. **The Latest Order card says the order date once (P5).**
   - The bold date and the kind stay. Row 232 maps the kind through `A.orderKinds` (P4).
   - `OrderRow` gains `showDate?: boolean` (default `true`). The Overview passes `showDate={false}` with its
     `label="Show the Order"`, so the collapsible's summary reads "Show the Order" without the date again.
   - The line "Next date found in the order: …" (`readingLabel`) shows only when the latest order's reading is not the
     one in use, that is when `c.next_date_from_orders?.order?.id !== o.id`. An example is an order that gives no clear
     date while an earlier date stands. Otherwise the next-date card of decision 10 says it.
   - `NextDateBlock` gains `latestOrderId?: string`. When the row's order is that order, the origin line reads "Fixed in
     this order" or "Counted from this order" (`T.nd.fixedInThis`, `T.nd.countedFromThis`) instead of repeating the date.
10. **"Next Date From Orders" becomes its own card under Latest Order (P2, P8).** In the Overview's left column (a stack),
    a kit `Card` titled `T.nd.card` "Next Date From Orders", with `actions={<HeadLink href=…#next-dates
    srSuffix="Next Dates">{T.viewAll}</HeadLink>}` (row 231's K9 form). It holds `NextDateBlock`, and the block's
    bottom link "All Next Dates" goes.
    - **The date in use is a plain line**, not a third badge: "14 Nov 2026 · Counted from this order", or "Around 14 Nov
      2026 · …" for a period reading (`T.nd.readingLine(date, origin, around)`). The quoted sentence ("What the order
      says") and the note stay.
    - **One toolbar** (`nextdates.module.css .toolbar`, a wrapping flex row with `--s2` gaps) holds Report Wrong Next
      Date, Correct It and Enter Next Date, each still by its own `workflow` flag. Today they sit on two rows. At 1280 px
      beside the rail the Overview is one column of about 600 px, so the three secondary buttons fit on one line. On a
      phone they wrap.
11. **Waiting for You is easier to read (P8).**
    - The Next Date column gets a fixed width of `calc(2 * var(--lead-w))` (192 px, the width row 228 gives a status
      column), so "The order gives no clear date" wraps between a few words, not one per line. Its dates no longer break
      (row 231, K5).
    - `reviewColumns` takes the rows (`items`). It leaves out the Actions column when no row has an action (`kind !==
      "enter"` on every row). Row 231's K6 already hides the empty row in card mode. This is the table-mode half.
    - The same applies on Next Dates to Enter, where `ReviewTable` is shared (decision 22).
12. **Hearings tab: no internal numbers (P10).**
    - In the Next Dates section, the next-date row's `ref_no` is no longer drawn under the date. It stays as the date
      cell's `title`, so it can still be quoted when needed.
    - The order cell reads "Order of 12 Oct 2026" with "No. 3" muted under it (`T.nd.orderOf`, `T.nd.orderNo`,
      as on the review list), not the number in mono.
    - Wrapped dates are fixed by row 231 (K5); nothing more here.
13. **Custody tab (P11, High).**
    - **Newest first.** The Movement Record reads `GET /cases/{ref}/custody?order=desc` through `useJourney(caseRef,
      PAGE, offset)`, the hook the rail and the remarks panel already use. The current move is first on page 1, and the
      card above it shows where the file is now. `useCustodyHistory` loses its last caller and is removed.
      - The `#` column (`seq_no`) stays, so the move numbers still read in order (12, 11, 10 …).
      - **Deviation from design portal-workflow, decision 8** ("oldest first"), flagged. The plan does not fix the order.
        Newest first matches the rail's journey and the remarks panel (design case-workspace-admin, decisions 14 and
        15), and the API already supports it.
      - The notes trail stays oldest first by `seq_no`: it is a written record read in order, not a "where is it now"
        list.
    - **The cramped card** is decision 7.
    - **No code before the office.** The holder cell and the custody card's Holder fact show the office through
      `OfficeName` (or the name the leg already carries, `holder_office.name`), never `code — name` or a mono code. The
      code stays as the `title`. "Sent By" and "Set By" lose their trailing office code the same way (row 232's
      sweep). This row removes the `mono` spans in these cells.
    - **The stage note's header** is `T.wf.stageNoteHead` "Note" (today `T.wf.stageNote` "Note (Optional)", a form
      label). The form keeps its label.
    - **Stage history** rows use row 231's `ItemHead` (stage label as the title; response mode, who and when as meta), so
      each row starts at the same x.
14. **Notes tab, the rest of P12.**
    - **No internal number in sight.** The note head (row 231's `ItemHead`) no longer shows `n.ref_no`. The hidden
      anchor `<span id={noteRefAnchor(ref_no)}>` stays, because the closure line and the remarks panel link to it.
    - **A correction is named by its date, as a link.** `superseded_by` reads "Corrected by the note of 21 Oct 2026,
      11:00", linking to `#note-<seq>`. `supersedes` reads "Corrects the note of 20 Oct 2026, 16:30"
      (`T.case.correctedByNote(when)`, `T.case.correctsNote(when)`, sentences under the Title Case guard's sentence
      rule). The date comes from the read-only addition `NoteRefOut.created_at` (see API). When it is null (a
      superseded note the reader may not read), the text reads "Corrects an earlier note", with no link.
    - **The list sits in a card.** The trail becomes a kit `Card` titled `T.case.notes` "Notes", with the Hide
      Corrected Notes check in its `actions`, like Write a Note and My Drafts beside it. Its empty state is
      `EmptyState compact` with row 231's title for the Notes tab.
15. **Documents tab (P13).**
    - **No empty uploader column.** `docColumns` takes the page's rows and leaves out "Uploaded By" when no row on the
      page has `uploaded_by` or `office`. Court orders, which come from the court, are then shown without a column of
      "—". The rule is per page, so a row that does carry an uploader is never hidden.
    - **The visibility cell** draws its badges (In the Assistant / Not Sent, and the visibility) in one wrapping row, then
      the text state on its own line under them (`case.module.css .docState`). It no longer stacks badges and a
      sentence in one column.
    - **"2 page(s)"** becomes "2 pages" through row 231's `plural()` (K10). Nothing more here.
    - **One hint under Description** (the Upload panel). The `TextArea`'s static hint "3 to 500 characters." is removed,
      and the kit `CharCounter` gains `min?: number`, reading "0 / 500 characters, at least 3"
      (`T.wf.charactersMin(n, max, min)`). The error message is unchanged.

16. **Case tabs that do not fit move into More, after a check on live data (P6, Medium, estimated).**
    - **Step 0, before any code: measure on the live dev stack.**
      - Who: the developer, or the owner when the developer has no login there. It is read-only.
      - Where: http://localhost:3000, signed in, in a 1280 px window with the side menu open and the rail beside the
        tabs, and again at the narrowest rail layout (a 1100 px window).
      - Cases: the three cases with the most hearings, found with the read-only role:
        `SELECT c.ref_no, count(*) FROM case_hearings h JOIN cases c ON c.id = h.case_id GROUP BY 1 ORDER BY 2 DESC
        LIMIT 3`. Also any case the owner knows to have many orders, documents or notes, opened as an officer who has
        the Assistant tab.
      - What: in the browser console,
        `(n => n.scrollWidth - n.clientWidth)(document.querySelector('nav[aria-label="Case Sections"]'))`, on the
        Overview tab and on the Notes tab.
      - Recording: the developer writes the six numbers in this note's "Build notes".
      - Outcome: if any is above 0, the row overflows on real data and the rest of this decision is built. If all are 0,
        P6 is closed as "checked, no overflow on live data" and nothing below is built. Phones keep scrolling the tab
        row, as design portal-ui-polish decision 21 allows.
    - **The kit `Tabs` gains `overflow?: "scroll" | "more"`** (default `"scroll"`, today's behaviour). Only the case page
      passes `"more"`.
      - A measuring copy of the row (`aria-hidden`, `visibility: hidden`, absolutely placed, `white-space: nowrap`)
        draws every item with its count, plus the More trigger.
      - In the layout effect that already places the underline (so before paint), the row keeps as many leading items
        as fit in the nav's width with the More trigger. The rest move, in order, to the front of the `more` group.
      - A `ResizeObserver` on the nav and on the measuring copy, and `document.fonts.ready`, re-measure it. That covers a
        count arriving, the rail appearing or a window resize.
    - **The current tab.** If it moved into More, the More button takes its label and the underline, as it already does
      for the fixed More items.
    - **Counts.** They stay on every visible tab. A moved tab shows its count in the menu ("Notes (12)").
    - The server-rendered first paint shows every tab, as today. `data-scroll-x` stays on the row as the fallback when
      not even one tab and More fit.
    - With `"more"` the rule applies at every width, so on a phone the hidden tabs are in More rather than off-screen.
      This amends design portal-ui-polish decision 21 for the case tabs only. Other tab rows keep scrolling.
    - Alternative: counts only on the active tab. Refused: the counts are information (design portal-cases), and the
      row could still overflow with long labels in a later language.
17. **One card header style in the rail (P7).**
    - **Every rail card shows its title** in `rail.module.css .cardTitle` at every width.
      - Your Task loses the `eyebrow` prop and the visually hidden heading.
      - The title is `T.rail.yourTask` "Your Task" when the file is with the reader. Otherwise it is
        `T.rail.currentTask` "Current Task", because "Your Task" would be wrong for someone else's file.
      - The blue "With …" eyebrow becomes the first row of the card's `dl`: "With: Joint Secretary, …". The closed state's
        "Closed" badge moves into the body's first line.
    - **Journey of This Case** gets `HeadLink` "View All" (suffix "Journey and Stage") in its head, to the Custody tab.
      The bottom link `T.rail.journeyLink` goes (row 231, decision 22).
      - `RailCard` gains `action?: ReactNode`. From 1100 px it draws `action` at the right of the title row.
      - Below 1100 px it passes `action` to the kit `Collapsible`'s new `aside?: ReactNode`. That draws it beside the
        summary button, outside it, because a link cannot sit inside a button.
    - **Below 1100 px no empty band.** The kit `Collapsible` gains `bare?: boolean`, with no top border, padding or
      margin. `RailCard` passes it, so a collapsed card starts with its title.
    - **Left-aligned summaries.** The kit `layout.module.css .summary` gains `text-align: start`. A wrapped summary
      (the Journey's "With …" fact) was centred because a button centres its text by default. This also helps every
      other collapsible with a long summary.
    - **Quick Actions as equal-width buttons:** `.quick` becomes
      `display: grid; grid-template-columns: repeat(auto-fit, minmax(5.5rem, 1fr))`. The three buttons share one row in
      the 320 px rail, and on a narrow phone they fall onto two rows, still of equal width.

### C. Alerts (A4, the rest of A2)
18. **A missed answer-by date says so (A4).** In `ReviewItem.tsx`, when `item.act_by` is before today in IST (`istDay`),
    the line reads "Answer was due 23 Oct 2026" (`T.nd.answerWasDue`) in the danger text class (`--red-text`, as the
    inbox's overdue date). Otherwise it stays the muted "Please answer by …". The empty Actions row on phones is fixed
    by row 231 (K6), and the empty column on wide screens by decision 11.
19. **The alert title without its case number (the rest of A2, handed to this row by row 231).**
    - **Server:** `alerts.alert_item` adds `summary`, from row 228's `alert_rules.title_without_case(title, case_ref)`.
      The case reference dict is already built for the item, so no query is added. `AlertItemOut` gains
      `summary: str`, so `GET /alerts`, `GET /alerts/{id}` (through `AlertDetailOut`) and `GET /cases/{ref}/alerts`
      carry it.
      - Row 228's dashboard `me_block` may read the item's `summary` instead of computing it again. Same value; the
        developer keeps one call site.
      - Stored titles, e-mails and the dialogs' titles are unchanged.
    - **Portal:**
      - The Alerts page row (`AlertRow`) shows `summary` as its bold line, and the case once, as the `AlertSubject`
        link.
      - The case Alerts tab (`CaseAlerts.tsx:146`) shows `summary` with no case link, because it is the case's own page.
      - The Acknowledge and Done dialogs keep the full `title`, because they show no case link.
    - The head of the row (kind, status, badges, no alert `ref_no`) is row 231's decision 13.

### D. Case Claim (C1, C2)
20. **One score format: the kit `ScoreBadge`, three decimals, with the department's name (C1).**
    - **Three decimals everywhere.** That is the stored precision (`Numeric(4, 3)`) and the format of `ScoreBadge`, the
      scoring settings and the Why box. Two decimals would show 0.845 as "Possible · 0.85" beside a 0.85 strong band.
    - **New kit `ScoreLine({ office, score, band })`** in `ui/feedback.tsx`: the department (`OfficeName`) first, then
      `ScoreBadge` after it. This follows row 231's title-before-badge rule. In a narrow cell the badge wraps under the
      name, never inside itself. Without a band (a best score below the possible band) it shows the name and the muted
      plain score "0.312", with no badge, because no recommendation exists below 0.50.
    - **Where it is used:**
      - **Pool**, Best Score column (`claim/Pool.tsx:54`): `ScoreLine` with `best_office_code`, `best_score` and the new
        read-only `best_band` (see API). "Best 0.912 for EDU" goes, with `T.inbox.best`.
      - **The claim modal's Why box** (`claim/WhyBox.tsx:43`), pool line: the same, after "Best Score" (`T.claim.best`).
        `T.claim.poolBest` goes.
      - **Cause List** (`causelist/OwnershipCell.tsx:29-33`): each recommendation is a `ScoreLine`. `recommendationText`
        and its two decimals go.
      - **Recommended:** unchanged. It already draws `ScoreBadge` for the caller's own department, where a name adds
        nothing.
    - **Colour.** On the Cause List this moves the strong recommendation from orange to the kit tone. C4's final colours
      (strong solid navy, possible outlined) remain row 229's.
21. **Transfers: names, one direction, one "requested" (C2).**
    - **The direction column names only the other department.** The In / Out switch above the list already says the
      direction. On In it reads From Department (`from_office_code`); on Out, To Department (`to_office_code`). Both are
      shown through `OfficeName` in the body font. `T.inbox.fromTo` and the mono span go.
    - **The Requested cell** reads "Anita Sharma Baruah, 21 Oct 2026" (`T.inbox.requestedCell(who, date)`), with "Will
      Stay as Watcher" on a muted second line when `stay_as_watcher`. The header stays "Requested".

### E. Dashboard (D2, D3)
22. **"Item" with a capital (D2).** `T.dash.courtItem` writes "Item 12", as the rail does.
23. **The hearing badge goes under the case number on phones (D3).** The kit `ListRow` gains `stackTrail?: boolean`
    (rendered as `data-stack-trail`). Below 820 px the trail moves onto its own line under the body, aligned with the
    body's left edge: the lead column is kept and the row wraps. Upcoming Hearings passes it, so the case number gets the
    row's full width and the court and item line no longer wraps one word per line. From 820 px nothing changes.
    - Alternative: drop the badge on phones because the date chip carries the band colour. Refused: the badge's words
      ("Today", "Around") are the non-colour signal (design next-hearing-highlight).

### Out of scope (other rows)
- **Row 231:** K1 (incl. L3), K5, K6, K8, K9 (the `HeadLink` component), K10, K11 (`ItemHead`), DC1.
- **Row 232:** K2 names everywhere (incl. P3, L1, the codes in the Custody, Notes, Documents, Pool and Transfers
  cells), K3, K4, P4, P9, U1, R1, R2, D1's strings, S3, A3, L2, C3 and P12's case.
- **Row 228:** More About My Work.
- **Row 229:** K7, A1 (alert tone and the severity counts and filter), C4's colours, every colour value.
- **Row 234:** the oversight screens.
- Not raised by the review and not changed here: the Watchlist's case column, the dashboard's Needs Your Attention
  (row 232 has D1), and the order of the notes trail.

## Data
None. No table, column, reference code or index is added or changed. **No migration.** `docs/schema/schema.md` is
unchanged.

## Services
Read-only additions; no rule, audit row, event or visibility rule changes.
- `backend/aslms/services/inbox.py`, `pool`: each item adds `"best_band"`, `matching.band_of(best_score, settings)`
  as its value (`"high"`, `"medium"` or `None`), with `settings = scoring_settings.current(session)` read once per page.
  It is `None` when there is no score. The band uses the super admin's current thresholds, the same function the engine
  uses, so the portal computes nothing.
- `backend/aslms/services/notes.py`, `note_out`:
  - `superseded_by` adds `"created_at": by.created_at`. `by` is already filtered by `note_visible_condition`.
  - `supersedes` adds `"created_at"` only when the superseded note passes `note_visible_condition` for the caller (one
    `select(CaseNote.id)` with the condition, only for correction notes), else `None`. `ref_no` and `seq_no` are
    unchanged, so nothing that was given before is withdrawn.
- `backend/aslms/services/alerts.py`, `alert_item`: adds `"summary": alert_rules.title_without_case(alert.title,
  case_ref)` (row 228's helper; the dict `alert_item` already builds for `case`).

## API
All additions only; nothing is removed or renamed. `frontend/openapi.json` is regenerated
(`backend/tools/export_openapi.py`) and `npm run gen:api` updates `frontend/src/lib/api/schema.d.ts`. The OpenAPI snapshot
test is updated.
- `GET /inbox/pool`. Permission unchanged: `cases.claim` or `cases.view_all` (`inbox._pool_allowed`).
  `PoolCaseOut` gains `best_band: Literal["high", "medium"] | None = None`.
- `GET /cases/{ref}/notes`. Permission unchanged: `cases.view_scope` or `cases.view_all`, then the note visibility rule.
  `NoteRefOut` gains `created_at: datetime | None = None`, given as in Services.
- `GET /alerts`, `GET /alerts/{id}` and `GET /cases/{ref}/alerts`. Permissions unchanged: the routers' `read` and the
  alert recipient and visibility rules. `AlertItemOut` gains `summary: str`.

## Jobs
None.

## Tests
**pytest**
- `tests/db/test_api_inbox.py`: a pool case scored 0.912 has `best_band == "high"`, one scored 0.612 has `"medium"`, one
  scored 0.312 has `None`, and an unscored one has `best_score` and `best_band` both `None`. After the super admin raises
  the strong threshold to 0.95, the 0.912 case reads `"medium"`.
- `tests/db/test_notes.py`:
  - a correction's `superseded_by.created_at` equals the correcting note's `created_at`;
  - a correction note's `supersedes.created_at` equals the original's when the caller may read the original;
  - it is `None`, with `ref_no` still present, when the original is private to an office the caller is not in;
  - a note without corrections has both links `None`, as today.
- `tests/db/test_api_alerts.py`:
  - every item of `GET /alerts` and `GET /cases/{ref}/alerts` carries `summary`;
  - a `hearing_due` alert's summary is its title without ": <case number>";
  - a ticket alert's summary equals its title;
  - `GET /alerts/{id}` carries it too.
- `tests/unit/test_openapi_snapshot.py`: the three schema additions.

**vitest**
- `components/inbox/inbox.test.tsx` and `components/files/cases-list.test.tsx`:
  - each of the four tabs renders a `FilterCard` (`data-zone="hero"` holding the words box) whose submit reads
    "Search", and none renders "Apply";
  - the strip's first element is the count line: With Me shows "3 of 9 cases" with a filter and `files: 9`, Sent by Me
    "3 cases match" with a filter, and no tab shows a second total;
  - the right zone and More Filters hold the fields of the table in decision 1;
  - the case number is the same plain `cno` element on all four tabs, with no link inside the row's case cell;
  - With Me and Sent by Me have no hidden-header column and no `[data-lead]`;
  - "New" (With Me, received an hour ago), "Recalled" (Sent by Me), "Ready to Close" and "Closed" render as marks under
    the case number, and never inside the Next Hearing cell;
  - the Action Needed cell shows the label over the Due line: an overdue card shows "Overdue by 3 Days" (tone danger,
    the date as title), a due-soon card "Due 12 Nov 2026" (warning), a later date the plain date, a card with no date
    "No Due Date", and a case with no pending action "—";
  - My Cases' headers are Case, Reason, Stage, Next Hearing and Action Needed (plus the hidden chevron header).
- `components/claim/claim.test.tsx`:
  - Pool's Best Score cell shows the department's name and a `ScoreBadge` reading "Strong · 0.912" for
    `best_band: "high"`, and the name with a muted "0.312" and no badge for `best_band: null`. No code text or "Best … for"
    appears;
  - the Why box's pool line is the same;
  - Transfers In has the header "From Department" and the name, Out has "To Department", and neither has a `.mono`
    cell;
  - the Requested cell reads "Anita Sharma Baruah, 21 Oct 2026", and "Will Stay as Watcher" shows on its own line.
- `components/causelist/causelist.test.tsx`: a recommendation renders a `ScoreLine` (the name, then "Strong · 0.950" with
  three decimals). `recommendationText` is gone.
- `components/case/case.test.tsx`:
  - the header has four facts and no "Status" fact, and the status badge is present;
  - the header's next hearing has no basis or differs line but keeps the "Order Differs" chip, while the rail's card
    has both lines;
  - the Overview's Latest Order summary reads "Show the Order" without a date;
  - with the reading of the latest order in use, there is no "Next date found in the order" line, and the next-date
    card's line reads "… · Counted from this order";
  - "Next Date From Orders" is a card with a "View All" head link to `#next-dates`, and the three buttons share one
    toolbar element;
  - in the Hearings tab's Next Dates, no `.mono` element holds a next-date reference, the reference is the date cell's
    `title`, and the order cell reads "Order of …";
  - the notes trail is inside a card headed "Notes" with the Hide Corrected Notes check in its head;
  - no note head contains the note's `ref_no` text, while the anchor id is still present;
  - a correction reads "Corrected by the note of 21 Oct 2026, 11:00" and links to `#note-<seq>`;
  - with `supersedes.created_at: null` it reads "Corrects an earlier note" with no link;
  - Documents: with court orders that have no uploader there is no "Uploaded By" header, and with one uploaded document
    on the page the column is present;
  - the visibility cell's text state is a separate line after the badges row.
- `components/case/rail.test.tsx`:
  - each rail card has a visible title (Your Task, or Current Task when the file is with another officer), and there is
    no `.visually-hidden` card heading;
  - the "With …" line is a `dt` and `dd` pair;
  - the Journey card's head has a "View All" link to the Custody tab, both wide and stacked (where it is outside the
    summary button), and the old bottom link is gone;
  - stacked cards render `Collapsible` with `data-bare`;
  - Quick Actions renders a grid container.
- `components/workflow/workflow.test.tsx`:
  - the Movement Record calls `/custody` with `order=desc`, and its first row is the highest `seq_no`;
  - the custody card uses `.cardFacts`, with the remark in a `.wide` item;
  - no holder cell contains `.mono`;
  - the stage card's header reads "Note".
- `components/nextdates/nextdates.test.tsx`:
  - with the time faked at 10 Nov 2026, an item with `act_by` 23 Oct reads "Answer was due 23 Oct 2026" with the danger
    class, and one with `act_by` 12 Nov reads "Please answer by 12 Nov 2026";
  - with only non-enter items there is no Actions header;
  - the Next Date column has the fixed width.
- `components/alerts/alerts.test.tsx` and `workflow.test.tsx` (case Alerts tab):
  - the Alerts row shows `summary` and the case number exactly once (in the link);
  - the case tab shows `summary` and no case link;
  - the dialog still shows the full title.
- `components/dashboard/dashboard.test.tsx`:
  - the Upcoming Hearings row reads "Court 5 · Item 12";
  - the `ListRow` carries `data-stack-trail`.
- `components/ui/ui.test.tsx`:
  - `Tabs overflow="more"` with mocked widths (nav 400 px, tabs of 120 px, More 80 px) shows two tabs and puts the rest
    in More in order;
  - a moved current tab gives the More button its label;
  - menu items carry their counts;
  - with `overflow` absent, the output is as today;
  - `Collapsible bare` renders `data-bare`, and `aside` renders outside the summary button;
  - `ListRow stackTrail` renders `data-stack-trail`;
  - `CharCounter min` reads "0 / 500 characters, at least 3";
  - `ScoreLine` puts the name before the badge, and shows no badge without a band.
- `lib/labels.test.ts`: the new strings pass the Title Case guard (labels) or its sentence rule (sentences).
  `LABEL_FUNCTIONS` lists `due.overdueBy` (samples 1 and 12), `inbox.requestedCell` and `nd.readingLine`.

**uicheck**
- Fixture additions in `frontend/e2e/fixtures/index.ts`:
  - a held item with a due date in the past and one due soon;
  - a pool case with `best_band: "high"`;
  - a note with a correction carrying `created_at`;
  - an alert item with `summary`;
  - a next-date item with a passed `act_by`;
  - a documents page of court orders with no uploader.
- The full run passes with no finding of any kind (row 231's four new kinds included) at 375, 768 and 1280 px.

## Verification
1. The developer and the tester run, in `frontend/`, `npm run lint`, `npm run typecheck` and `npm test`, and in
   `backend/`, `ruff check` and `pytest -q`: all green.
2. **P6's step 0** is done first and its six numbers are written in "Build notes" (decision 16).
3. The integrator runs uicheck on a **private network against temporary images** (`docs/operations.md` section 16),
   never through Compose on the shared stack:
   - build `frontend/` as `tmp233-web` and `frontend/e2e/Dockerfile` as `tmp233-uicheck` (build argument
     `PLAYWRIGHT_VERSION`);
   - `docker network create tmp233-net`;
   - start `tmp233-web` on it with alias `web`, `API_BASE_URL=http://api:8000`, `PORTAL_BASE_URL=http://web:3000` and
     `COOKIE_SECURE=false` (every API answer from the fixtures);
   - run `tmp233-uicheck` with an output folder at `/out`.

   Expected: every test passes at 375, 768 and 1280 px with no finding. Then remove the container, the network and both
   images.
4. The integrator compares these screenshots with the review's (same slugs) and attaches them:
   - `1280/inbox-with-me.png`, `inbox-my-cases.png`, `inbox-sent.png` and `inbox-department.png`: four Layout B cards
     with Search and the count in the strip, the same case cell, no unlabelled column, marks under the number, and one
     Action Needed cell;
   - `1280/claim-pool.png`, `claim-transfers.png` and `causelist.png`: name and three-decimal badge, From or To
     Department by name, the Requested cell on one line;
   - `1280/cases-aslms-ghc-case-2026-000001.png` and its `375` twin:
     - four facts and one status;
     - the header's next hearing without the explanation;
     - every rail card titled, Quick Actions equal, and no empty band at 375;
     - the Next Date From Orders card;
     - the tab row with More reachable (if P6 was built);
   - `…-custody.png`: newest move first, the remark full width, no codes, "Note";
   - `…-notes.png`: the list in a card, no `ASLMS/…/NOTE/…` in sight, the correction by date;
   - `…-documents.png`: no all-dash Uploaded By, the text state on its own line, one hint;
   - `…-hearings.png`: no reference under the dates;
   - `375/alerts-next-dates.png`: "Answer was due …";
   - `375/dashboard.png`: the case number whole, the badge under it.
5. Deploy: no migration and no `init`. Images (api and web) are built from a clean worktree of `main`, the app services
   are recreated with `--no-deps --force-recreate` carrying the court-data switch, and the web build ID is checked.
6. The owner, at http://localhost:3000 at 1280 px and at a phone width, opens the four Case Inbox tabs, Case Claim's Pool
   and Transfers, the Cause List, one case's Overview, Custody, Notes, Documents and Hearings tabs, Next Dates to Enter
   and the dashboard. Each point of step 4 is checked by eye, on live data.

## Open questions
Each has a recommended answer. The design is complete with those answers, so the owner may approve "with the
recommended answers".

1. **The case number on With Me and Sent by Me (I2).** Plain bold everywhere means opening a case from With Me takes two
   clicks: the row (side panel), then Open Case Page.
   - **Recommended:** plain bold on all four tabs. One target per row, and the side panel shows the full remark first,
     which is why it was designed (case-workspace-admin, decision 20).
   - Alternative: a link on all four tabs (one click to the case from With Me; two tab stops per row).
2. **Movement Record newest first (P11)** changes design portal-workflow decision 8.
   - **Recommended:** newest first, like the rail and the remarks panel. The `#` column keeps the order readable.
   - Alternative: keep oldest first but open on the last page. Refused as recommended: page numbers then run backwards
     from what a reader expects.
3. **P6 on phones.** If step 0 shows overflow, the case tabs collapse into More at every width, including phones,
   where today they scroll.
   - **Recommended:** every width. Notes and Timeline off-screen on a phone is the same defect.
   - Alternative: collapse only from 820 px and keep the phone's scrolling row.
4. **The inbox's "Due soon" state** is a fourth state beside row 228's three (decision 5).
   - **Recommended:** keep it in the inbox, where the server sends `due_soon`; the dashboard keeps three until its
     payload carries the flag.
   - Alternative: three states everywhere, which drops the amber due-soon signal from With Me and My Cases.

## Build notes
(For the developer: P6 step 0 measurements, then any deviation from this note.)

## Owner's answers (10 Nov 2026)

All open questions answered with the recommended answers.
