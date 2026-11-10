# Design: Portal screen fixes, oversight and administration (Search, Reports, Audit Log, Data Collection, System Health, Administration)

```
slug: portal-screen-fixes-oversight
status: proposed
author: architect
date: 2026-11-10
approved_by:
```

## Context
Backlog row 234, row C2 of the portal UI review (row 230, `docs/reviews/2026-11-10-portal-ui-review.md`, screenshots in
`docs/reviews/2026-11-10-portal-ui-review/`). On 10 Nov 2026 the owner approved the review with its recommended answers:
every High and Medium finding is fixed, and Low findings are fixed where they sit in the same files (decisions log,
"2026-11-10 — Portal UI review approved; rows 228 and 229 approved (owner)"). This row holds the screen-specific findings
of the oversight and administration screens:

- Search: S1, S2;
- Cause List: L3 (verification only);
- Reports: R3;
- Data Collection: DC2;
- System Health: Y2;
- Audit Log: U2;
- Administration: AD1 to AD4.

S2 is Medium. The rest are Low and sit in the same files.

**Order and dependencies.** The build order is row 204, 231 `portal-ui-kit-fixes`, 228, 232 `portal-names-and-labels`,
233 `portal-screen-fixes-work`, **234 (this row)**, 229 `portal-navy-cream`, 235. Row 229 changes colours only and takes
its layout baseline after rows 231 to 234, so every layout change of these findings lands here. This row uses, and does
not rebuild:

- **Row 231** (`docs/design/portal-ui-kit-fixes.md`):
  - K1 caption padding, and with it L3 (decision 2 of that note: `.entries caption { display: block; }` in the Cause
    List's phone block). This row only verifies L3.
  - K5 dates with no-break spaces, which already fixes R3's wrapping "Filed" dates and every date column here.
  - K6 card rows, K8 empty states, K10 `plural()` (which already fixes AD4's "123456 case(s) found").
  - K11 `ItemHead` and Y1 (the System Health card titles).
  - DC1 and the `[data-free-text]` marker on the Failed Fetches Problem cell, which DC2 builds on.
- **Row 232** (`docs/design/portal-names-and-labels.md`): the kit `OfficeName` over
  `GET /reference/offices`, which replaces office and department codes with names (S2's owner, U2's "By", AD2's
  department and requester), and the label helper `labelFor(map, code)` of K4 in `lib/displayLabels.ts`, which Title-Cases an unlabelled code (U2's
  record type).
- **Row 233** (`docs/design/portal-screen-fixes-work.md`): its decision 1 puts every Case Inbox count at the head of the
  Layout B summary strip; S1 follows the same rule on Search.

**What exists (read at 6dd84d3).**
- **Search** (`components/search/Search.tsx:96-135`). The Layout B card's strip says "n cases match" (`FilterBar`
  `total`). An `h2` above the results repeats the heading with "· 1,23,456+ cases". `CaseResults` then draws a visible
  caption with the same words (`showCaption`, `CaseResults.tsx:88`). The case cell starts with the parties line
  (`CaseResults.tsx:36-49`), and `StatusCell` stacks up to four lines with the owner's code (`:24-34`).
  - `CaseResults` is also used by the court search (`CourtSearch.tsx:210`), under its own `h2` "Search the Court".
- **Reports.** The Scope / Department select (`reports/ReportForm.tsx:169-175`) is a native select in a grid cell of
  the `FilterCard`, so a long department name is cut ("Department of Schoo"). The Holding Department beside it is
  already the kit `OfficePicker` (design portal-ui-polish-2, decision 30). The report tables are hand-built
  (`ReportView.tsx:100-160`) with server-defined columns of kinds `text`, `int`, `date` and `days`
  (`services/reports.py:69`). The "Petitioner" column in the screenshot is a fixture column
  (`frontend/e2e/fixtures/index.ts:343`). The real case lists have text columns such as Holder office, Officer and
  Pending action.
- **Problems and Fixes** (`data/ProblemsAndFixes.tsx:240-300`):
  - "Retry All" is a small secondary button in the by-kind table;
  - "Retry" is a link-style button in the failed-fetch table;
  - the Problem column prints `last_error`, which the runner writes as `"<ExceptionClass>: <message>"`
    (`services/runner.py:421`). The portal already has plain words for the NAPIX error families (`T.pf.families`,
    `familyWords` in `lib/dataCollection.ts:237-241`).
- **System Health** (`system/SystemHealth.tsx:173-176`): the overview sentence is preceded by a badge of the services'
  overall status, which says the same thing ("Working · Everything is working"). The KPI "Services Working" beside it
  already turns danger when a service is down (`:196-201`).
- **Audit entry** (`audit/AuditEntry.tsx:96-104`): Record prints `entity_type` and the raw `entity_id` (a UUID) in
  mono. "By" ends with the office code. `AuditRowOut` carries no record name.
- **Users** (`admin/Users.tsx:236-247`): the avatar is its own column with the card label "Initials", so on cards
  (phones, and at 1280 px whenever the table cannot fit) it shows as a labelled row "Initials: AB".
- **Tickets** (`admin/Tickets.tsx:92-117, 275-297`): the primary cell and the detail heading are the ticket reference in
  mono. Department is a mono code, and "Requested by … (EDU)" carries a code. `TicketItemOut` carries the target's name
  (`target.user_name`).
- **Recommended From Cause Lists** (`admin/mapping/CounselCodes.tsx:444-463`): `.recTop` is a wrapping flex row, so
  "n entries · last seen" sits beside the code on short rows and under it on long ones. The example case is
  `SearchLink` (`mapping/common.tsx:279-286`), which prints the internal reference in mono. `UnmappedCodeOut` carries
  only `example_case_ref` (`services/matching.py:1195-1220`).
- **Keywords and Name Patterns** (`admin/mapping/Keywords.tsx:65-87`): each row's toggle is a `CheckField` with the
  visible label "Search the Court", the same words as the column header. The kit `CheckField` has no way to hide its
  label.

**Not covered:** the work screens (row 233), names and labels (row 232), the kit fixes (row 231), and colours (row 229).

## Decisions

### A. Search (S1, S2)
1. **One heading, one count (S1).**
   - The results heading is `h2` "Your Cases" or "Results", without a count.
   - The count moves to the head of the Layout B summary strip, as on the Case Inbox (row 233, decision 1).
     `Search.tsx` passes `countLine` with `T.search.total(n, capped)` ("1,23,456+ cases"), which keeps the "+" of a
     capped total, and no longer passes `total`. The strip has one count, and so does the page.
   - `CaseResults` drops `showCaption`. The table keeps its `caption` as its accessible name, visually hidden (the
     kit's `srCaption`). That covers Search and the court search, where the section's `h2` already names the list.
   - Alternative: keep the count in the heading and drop it from the strip. Refused: it would make Search the one list
     whose count is not in the strip.
2. **The case number leads, and Status is one badge with one line (S2, Medium).**
   - **The case cell** (`CaseResults.tsx CaseCell`), top to bottom:
     - the case link (`CaseLink`, as today), with the CNR muted after it;
     - a mark line, only when the case is not visible to the caller: "Court-public Summary Only" (`T.search.notVisible`)
       as a small neutral badge;
     - the parties line;
     - the last listing;
     - the next hearing.

     This is the order of `inbox/rows.tsx CaseCell`. The case number stays a link here: unlike an inbox row, a search
     result is often a case the caller cannot open, and link against plain text is how that shows.
   - **The Status cell:**
     - the case status as a `Badge` (`T.inbox.statuses`, tone `success` for disposed and neutral otherwise, the case
       header's rule moved to `lib/cases.ts statusTone` and shared);
     - under it one muted line: "Owned by" with the owner's name through `OfficeName` (row 232), or "In the Unclaimed
       Pool", or nothing.
   - The column gets a fixed width of `calc(2 * var(--lead-w))`, so the line wraps between words.
   - **"Court Details Not Yet Fetched"** leaves the row and stays in the side panel's facts. On the court search, the
     row's own Fetch Details action already says it.
   - The side panel keeps every fact (status, owner, pool, visibility and fetch state), now through the same two
     pieces.

### B. Cause List (L3)
3. **Verify only.** Row 231 fixes the squeezed "Cause-list Entries" caption at 375 px (its decision 2), and its
   `caption-inset` check guards it. This row adds nothing. The integrator confirms `375/causelist.png` in Verification.

### C. Reports (R3)
4. **The Scope or Department choice is the kit Office Picker.** In `ReportForm.tsx` the native select becomes
   `OfficePicker` over the departments the page already holds, through the existing `holderChoices` helper (renamed
   `departmentChoices`; it builds the same one-level list). No call is added.
   - **A State-scope reader** gets `placeholder={T.reports.wholeState}`. A cleared picker is the whole State, exactly as
     the empty select value is today.
   - **A reader of several departments** gets `required`, so the picker cannot be cleared.
   - An inactive department keeps its "— inactive" suffix in the option's name.
   - The picker shows the full name, cut with an ellipsis only in the closed box, with the full name as its `title`,
     and searches by name or code.
   - The single-department line is unchanged.
5. **Text columns of the report tables have a minimum width.** `ReportView.tsx` gives `kind === "text"` cells and
   headers the class `reports.module.css .textCell`, `min-width: 12ch`. A name or a pending action then wraps between a
   few words, not one per line. The table already scrolls sideways in its own region (design portal-ui-polish, decision
   21), so a wider table costs nothing on the page.
   - Dates no longer wrap after row 231 (K5). `int` and `days` columns are unchanged.
   - Alternative: a minimum width only for named columns. Refused: the columns are the server's, and the portal draws
     them by kind.

### D. Data Collection (DC2)
6. **One look for both retry actions.** In Problems and Fixes, both "Retry All" (failed by kind) and "Retry" (failed
   fetches) are `Button variant="secondary" size="sm"`. Each sits in an action column with `align: "right"` and a fixed
   width of `var(--lead-w)`, at the right edge of its table. Their accessible names (`T.pf.retryAllOf`, and a new
   `T.pf.retryOf(what)` for the row) are unchanged in kind.
7. **The problem in plain words, the raw text behind "Details".**
   - A new helper `problemWords(error: string | null)` in `lib/dataCollection.ts`:
     - it finds the first known NAPIX family name (`Napix…`, the keys of `T.pf.families`) in the text and returns its
       words, Capitalised as a sentence;
     - it appends an HTTP status when one is present as a three-digit 4xx or 5xx. Example: "The court did not answer
       (busy or down) (502)";
     - with no known family it returns `T.pf.otherProblem` "Another problem; see the details.";
     - with no text it returns `T.pf.unknownReason`;
     - every result starts with a capital letter (the family words are written lower-case for use inside sentences).
   - The Problem cell shows the words, then a native `<details>` with the summary `T.pf.details` "Details" and the raw
     `last_error` in a `<code data-free-text>`. Row 231's marker keeps the long path from widening the table.
   - Nothing is parsed on the server, and the raw text the API already sends is still one click away for the operator.
   - Alternative: a family field on the queue row's API. Refused: `fetch_queue` keeps only `last_error`, so it would mean
     a schema change for a Low finding.

### E. System Health (Y2)
8. **The overview sentence alone.** The badge before the sentence (`SystemHealth.tsx:175`) is removed. The sentence
   ("Everything is working", "2 services need attention", "1 service is not working") already says the state. The tone
   stays on the "Services Working" KPI, which turns danger when a service is down. The ring keeps showing the court
   calls' answered rate, a different fact.
   - The review's "the tone carried by the ring" is read this way because the ring measures court calls, not services.

### F. Audit Log (U2)
9. **The record in words; the identifier kept, but not in sight.** On the entry page:
   - Record shows the record type as a label, through row 232's `labelFor` with an empty map (it Title-Cases the code:
     `case_note` becomes "Case Note"). When the entry's `after` or `before` holds a string `ref_no`, it follows, in the
     body font ("Case Note ASLMS/EDU/NOTE/2026/000003"). That is the reference readers know.
   - The raw `entity_id` is no longer drawn. It stays as the value's `title`, in the existing link "All Entries for This
     Record" (unchanged), and in a kit `CopyButton` labelled "Copy Record ID" beside the value, so an auditor can still
     quote it.
   - "By" shows the office through `OfficeName` (row 232).
   - **No API change.** A server-side record name (a person's or an office's name for `user` or `office` records) was
     considered, and is open question 1.

### G. Administration (AD1 to AD4)
10. **Users: the avatar leads the person, with no label (AD1).** The avatar column is removed. The Person cell (primary)
    draws the avatar (`a.avatar`, `aria-hidden`) beside the name and post, in one flex row (`admin.module.css
    .personRow`). On a table row and on a card the avatar sits before the name, and no "Initials" row appears.
    - `T.users.avatar` goes.
    - Alternative: a new kit column option for a card lead. Refused: one screen needs it, and the cell can carry it.
    - The review saw cards at 1280 px. The developer checks with the fixtures whether the table now fits. If it still
      falls back to cards because of the fixture's long strings, that is the kit's designed fallback, not a defect.
11. **Tickets: named by kind and person (AD2).**
    - **List.** The primary cell reads "Head Change: Anita Sharma Baruah": the kind label (`labelOf(ticket_kinds)`), a
      colon, and the target's `user_name`. With no target name it is the kind alone. The operation, when given, follows
      muted ("· add"). Under it the reference is muted, in the body font, at the small size.
      - The cell stays the link to the ticket page.
      - The separate Kind column goes, because its words are now in the primary cell.
      - Department shows through `OfficeName` (row 232); "Requested By" is the name alone.
      - The row's accessible name (`rowLabel`) becomes the same "Head Change: …" text.
    - **Ticket page.** The heading is the same "Head Change: Anita Sharma Baruah", with the reference muted on the line
      under it.
      - The Department fact shows the name, with no mono.
      - "Requested By" shows the name, then `OfficeName` in place of "(EDU)", then the date.
12. **Recommended From Cause Lists: one row layout and the case number (AD3).**
    - **Layout.** `.recTop` becomes a column: the code on the first line, then "n entries · last seen …" on the second,
      on every row and at every width.
    - **The example case shows its case number.** `UnmappedCodeOut` gains `example_case_no: str | None`, the example
      case's `case_no_text` (see API). `SearchLink` gains `label?: string`. The link shows the case number in the body
      font, and the reference only when there is no number (in mono, as a reference). It still searches by the
      reference (`/search?q=<ref_no>`), so it lands on the same case.
    - The Watchlist's case column keeps `SearchLink` without a label. It is not part of AD3 (out of scope).
13. **Keywords: the toggle's label is for screen readers only (AD4).**
    - The kit `CheckField` gains `hideLabel?: boolean`, which puts its `label` in `visually-hidden`, as `FieldFrame`
      already does for text fields.
    - `DiscoverCell` passes `hideLabel`. Its `aria-label` "Search the court for <rule>" stays as the accessible name,
      and the column header says "Search the Court" once.
    - The count line ("1,23,456 cases found") is row 231's K10. Nothing more here.

### Out of scope (other rows)
- **Row 231:** K1 and L3's fix, K5, K6, K8, K9, K10, K11 and Y1, DC1 and the `[data-free-text]` marker.
- **Row 232:** K2 (incl. the owner's name on Search, the audit office, the ticket department and requester), K3, K4, U1
  audit action names, R1 and R2 (report titles and code columns), S3.
- **Row 233:** the work screens.
- **Row 229:** colours.
- Not raised by the review: the Watchlist's case column, and the court search's own result heading.

## Data
None. No table, column, reference code or index is added or changed. **No migration.** `docs/schema/schema.md` is
unchanged.

## Services
- `backend/aslms/services/matching.py`, `unmapped_codes` (`:1195-1220`): the query that already reads the example
  cases selects `Case.case_no_text` beside `Case.ref_no`. `UnmappedCode` gains `example_case_no: str | None`. One query
  as before. It is read-only, with no rule, audit row or event.

## API
Addition only. `frontend/openapi.json` is regenerated and `npm run gen:api` updates `schema.d.ts`. The OpenAPI snapshot
test is updated.
- `GET /admin/counsel-codes/unmapped/page` and the older `GET /admin/counsel-codes/unmapped`. Permission unchanged:
  `admin.counsel_codes`, within the caller's `counsel_code_scope`. `UnmappedCodeOut` gains
  `example_case_no: str | None = None`. The case number is court-public, and the same row already gives the case's
  reference.

## Jobs
None.

## Tests
**pytest**
- `tests/db/test_api_matching.py`: an unmapped code whose example case has a printed number returns
  `example_case_no` equal to it and `example_case_ref` as before. A provisional example case without a number returns
  `example_case_no: null`. The scope rule is unchanged: a department admin still sees only the codes of their scope.
- `tests/unit/test_openapi_snapshot.py`: the one schema addition.

**vitest**
- `components/search/search.test.tsx`:
  - the strip's first element reads "1,23,456+ cases" for a capped total;
  - the results `h2` has no count, and no visible `caption` repeats it (the caption has `srCaption`);
  - in a result row the case link comes before the parties line in DOM order;
  - the Status cell is one badge plus at most one muted line, showing the owner's name (no code) or "In the Unclaimed
    Pool";
  - a not-visible case shows the "Court-public Summary Only" mark;
  - "Court Details Not Yet Fetched" is absent from the row and present in the side panel.
- `components/reports/reports.test.tsx`:
  - a State-scope reader's Scope is an Office Picker whose empty value reads "Whole State" and sends no `department`;
  - a two-department reader's picker is required;
  - a long department name is the option's full text;
  - `text` cells carry `.textCell` and `int` cells do not.
- `components/data/data.test.tsx`:
  - both retry buttons are secondary and small, in right-aligned columns;
  - `problemWords("NapixUnavailable: 502 Bad Gateway from /nic/…")` reads "The court did not answer (busy or down)
    (502)", an unknown text reads "Another problem; see the details.", and `null` reads "No reason given";
  - the cell's `<details>` holds the raw text in `code[data-free-text]`.
- `components/system/system.test.tsx`: the overview sentence has no badge before it, and the "Services Working" KPI
  still carries the danger tone with a service down.
- `components/audit/audit.test.tsx`:
  - the entry page's Record reads "Case Note ASLMS/EDU/NOTE/2026/000003" for an entry whose `after.ref_no` is set;
  - no element shows the raw UUID as text;
  - the value's `title` and the "Copy Record ID" button carry it;
  - the "All Entries for This Record" link is unchanged.
- `components/admin/admin.test.tsx`:
  - the Users table has no "Initials" text or avatar column header, and the Person cell holds the avatar before the name;
  - the Tickets primary cell reads "Head Change: Anita Sharma Baruah" with the muted reference, and there is no Kind
    column and no `.mono` department cell;
  - the ticket page's heading is the same text.
- `components/admin/mapping.test.tsx`:
  - each recommended code's entries line is under the code (a column container);
  - the example link shows the case number and links to `/search?q=<ref_no>`;
  - with no number it shows the reference;
  - in Keywords, the toggle's visible label is hidden (`visually-hidden`) and its accessible name is "Search the court
    for …".
- `components/ui/ui.test.tsx`: `CheckField hideLabel` puts the label in `visually-hidden`; without it the output is
  unchanged.
- `lib/labels.test.ts`: the new strings (`pf.details`, `pf.otherProblem`, `pf.retryOf`, `audit.copyRecordId`) pass the
  Title Case guard or its sentence rule.

**uicheck**
- Fixture additions in `frontend/e2e/fixtures/index.ts`:
  - a failed fetch whose `last_error` names `NapixUnavailable` with a 502;
  - an audit entry with `after.ref_no`;
  - an unmapped code with `example_case_no`;
  - a ticket with a target name.
- The full run passes with no finding (row 231's new kinds included) at 375, 768 and 1280 px.

## Verification
1. The developer and the tester run, in `frontend/`, `npm run lint`, `npm run typecheck` and `npm test`, and in
   `backend/`, `ruff check` and `pytest -q`: all green.
2. The integrator runs uicheck on a **private network against temporary images** (`docs/operations.md` section 16),
   never through Compose on the shared stack:
   - build `frontend/` as `tmp234-web` and `frontend/e2e/Dockerfile` as `tmp234-uicheck` (build argument
     `PLAYWRIGHT_VERSION`);
   - `docker network create tmp234-net`;
   - start `tmp234-web` on it with alias `web`, `API_BASE_URL=http://api:8000`, `PORTAL_BASE_URL=http://web:3000` and
     `COOKIE_SECURE=false`;
   - run `tmp234-uicheck` with an output folder at `/out`.

   Expected: every test passes at 375, 768 and 1280 px with no finding. Then remove the container, the network and both
   images.
3. The integrator compares these screenshots with the review's (same slugs) and attaches them:
   - `1280/search.png`: one count in the strip, a heading without a count, case numbers first, Status one badge and one
     line;
   - `375/causelist.png`: "Cause-list Entries" on one line (L3, fixed by row 231);
   - `1280/reports-pending-cases.png`: the department in full in the picker, text columns not one word per line;
   - `1280/data-problems.png`: two equal retry buttons at the right, the problem in words with Details;
   - `1280/system.png`: the sentence without a badge;
   - `1280/audit-0192a3b4-0000-7000-8000-0000000000a1.png`: Record in words, no UUID in sight;
   - `1280/admin-users.png`, `admin-tickets.png`, `admin-mapping-codes.png` and `admin-mapping-keywords.png`: no
     "Initials" row, tickets by kind and person, one row layout with the case number, no repeated "Search the Court".
4. Deploy: no migration and no `init`. Images (api and web) are built from a clean worktree of `main`, the app services
   are recreated with `--no-deps --force-recreate` carrying the court-data switch, and the web build ID is checked.
5. The owner, at http://localhost:3000 at 1280 px and at a phone width, opens Search (with and without words), a report
   with the department picker, Data Collection's Problems and Fixes, System Health, one audit entry, Users, Tickets, and
   Department Mapping's codes and keywords. Each point of step 3 is checked by eye on live data.

## Open questions
Each has a recommended answer. The design is complete with those answers, so the owner may approve "with the
recommended answers".

1. **A server-side record name on the audit entry (U2).** Decision 9 shows the type and any `ref_no` the entry holds.
   Records without a reference (a user, an office, a designation) then show only their type, with the ID copyable.
   - **Recommended:** not now. The portal-only fix removes the raw UUID from sight, which is the finding. A
     `record_label` on `GET /audit/{id}` (a person's or an office's name) can be a later row if auditors ask for it.
   - Alternative: add `AuditRowOut.record_label`, resolved on the server for `user`, `office`, `designation` and the
     tables with a `ref_no`, on the entry endpoint only.
2. **Search keeps the case number as a link (S2)**, while row 233 makes it plain text on the Case Inbox.
   - **Recommended:** keep the link on Search. Many results are cases the caller cannot open, and link against text
     shows which, together with the mark of decision 2.
   - Alternative: plain text with the mark alone, as on the inbox.

## Build notes
(For the developer: any deviation from this note.)
