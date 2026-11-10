# Portal UI review (backlog row 230 `portal-ui-review`)

10 Nov 2026, on `main` at a956b9d. Review only: no application code was changed. This report is for the owner to approve. The approved fixes become build rows before or with row 229 (`portal-navy-cream`).

## How the review was done

- **Screens.** The screen check (`uicheck`) ran on a private network, as `docs/operations.md` section 16 describes: `frontend/` was built as `tmp230-web` and `frontend/e2e/Dockerfile` as `tmp230-uicheck` (Playwright 1.64.1), on network `tmp230-net` with every API answer from `frontend/e2e/fixtures`. Result: **551 passed, 416 screenshots** at 375, 768 and 1280 px, and no geometry findings. The container, network and both images were removed afterwards. The shared stack was not touched.
- **Screenshots** referenced by the findings are kept beside this report in `2026-11-10-portal-ui-review/` (written below as `2026-11-10-portal-ui-review/`), in folders `375/`, `768/` and `1280/`, with file names from the uicheck slug (for example `2026-11-10-portal-ui-review/1280/inbox-with-me.png`). The full set of 416 was not kept in the repository.
- **What was looked at.** Every route at 1280 px, the dense routes at 375 px, and a code sweep of `frontend/src/components` for `className="mono"`, `severity ===`, `*_code`, `showCaption`, `?? code` fallbacks, `replace(/_/g, " ")`, empty states, `(s)` plurals and server-supplied labels, with the backend checked where a label comes from the server.
- **Limits of the fixtures.** The fixtures fill every field with "Sample value with a fair length", `kind_0`, `status_0` and counts of 1,23,456. Those placeholders are **not** reported. Where a defect only appears with real data, the finding says **(code)**: it was inferred from the code, not seen in a screenshot.
- **Not reported:** colour choices themselves (row 229 replaces them; colour with no consistent meaning *is* reported), and the nine defects of row 228 in `PersonalExtras` (the dashboard's "More About My Work").

**Severity.** **High**: the defect misleads a reader or affects many screens. **Medium**: a reader sees it on a main screen and it slows them down. **Low**: polish. **Effort**: S = under 2 hours, M = half a day to a day, L = more than a day.

## Summary

59 findings: **4 High, 23 Medium, 32 Low**. 48 are tied to one screen and 11 are portal-wide patterns (K1 to K11), where a single kit fix solves them across many screens.

Top 10:
1. **K2**: office and department codes appear where people read names, in more than 25 places, because most API objects carry only the code.
2. **K3**: labels that come from the server are in sentence case and bypass the Title Case guard: stages, alert kinds, pending actions, document types, report titles and headers.
3. **P9**: the case Details tab uses raw NAPIX field names as labels ("Cnr", "Reg no", "Date filing disp", "Reason for rej").
4. **P11**: the Movement Record lists the oldest moves first, so the latest move ends up on the last page; the Journey card squeezes the remark into a narrow column.
5. **I1**: the Case Inbox has four sibling tabs drawn with three different filter layouts, two button words and three places for the count.
6. **K1**: a visible table caption sits flush with the card edge while the columns are inset (row 228 defect 1, here found in 21 places).
7. **A1**: alert severity (Critical, High or Normal) drives the badge colour, the counts and a filter on Alerts and on the case Alerts tab.
8. **K5**: dates in table cells wrap onto three lines ("23 / Oct / 2026").
9. **C4**: a strong recommendation is blue on Case Claim and on the case page but orange on the Cause List.
10. **P2**: the case header and the action rail both show the next-hearing date with the same three-line explanation, and the Overview shows it a third time.

---

## Findings by screen

### Dashboard (`/`)

**D1. In Needs Your Attention, the badge repeats the title or detail, and the titles are in mixed case.** Medium.
- Seen at 1280 and 375. Screenshots: `2026-11-10-portal-ui-review/1280/dashboard.png`, `2026-11-10-portal-ui-review/375/dashboard.png`.
- Code: `frontend/src/components/dashboard/Headline.tsx:183-207`, `T.dash.leads` in `frontend/src/lib/messages.ts:1040-1046`, `backend/aslms/services/dashboard.py:346-354, 482, 495`.
- **Defect:** each row starts with a badge that the text beside it repeats: "Overdue" next to the detail "Overdue 3 days"; "Ready to Close" next to the title "Ready to Close"; "Due Soon" next to "Due in 2 days"; and the bare badge "Enter" next to "Next date to enter". The titles come from the server in mixed case ("Parawise comments", "Case received", "Next date to enter", but "Ready to Close"). **(code)** The fixture also repeats the remark as both title and detail, but that is a fixture effect.
- **Why it matters:** the row says the same thing twice, and "Enter" on its own does not tell a reader what to do.
- **Fix:** keep one statement of state. Either the badge names the kind ("Overdue Action", "Next Date to Enter", "Ready to Close", "Due Soon", "Case Received") and the detail gives the extra fact ("3 days", "Disposed 2 Nov 2026"), or drop the badge text from the detail. Put the titles in Title Case (see K3).
- **Effort:** S. **API:** the detail and title strings are built on the server; a text-only backend change, or the portal maps them by `kind` and `pending_action`.

**D2. "Court 5 · item 12": "item" is lowercase here and "Item" elsewhere.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/dashboard.png`.
- Code: `T.dash.courtItem` at `messages.ts:1047-1048`. The case rail writes "Item" (`messages.ts:2060, 3348`).
- **Fix:** write "Item".
- **Effort:** S. **API:** no.

**D3. In Upcoming Hearings at 375 px, the date badge cuts off the case number.** Medium.
- Seen at 375. Screenshot: `2026-11-10-portal-ui-review/375/dashboard.png`.
- Code: `Headline.tsx:139-155` (`ListRow` with a `trail` badge).
- **Defect:** the trailing badge ("Around · Today") takes the right half of the row. The case number is clipped ("WP(C)/12345/20…") and the court and item text wraps one word per line.
- **Why it matters:** the case number is the one thing the reader needs from that row.
- **Fix:** below 820 px, move the badge under the case number, or drop it there because the date chip already carries the band.
- **Effort:** S. **API:** no.

### Case Inbox (`/inbox/with-me`, `/inbox/my-cases`, `/inbox/sent`, `/inbox/department`)

**I1. Four sibling tabs use three filter layouts and three places for the count.** Medium.
- Seen at 1280 and 375. Screenshots: `2026-11-10-portal-ui-review/1280/inbox-with-me.png`, `inbox-my-cases.png`, `inbox-sent.png`, `inbox-department.png`.
- Code: `frontend/src/components/filters/FilterBar.tsx` and `frontend/src/components/inbox/MyCases.tsx:118-125`. Department uses Layout B from row 163.
- **Defect:**
  - With Me and Sent by Me: a stacked filter card with an "Apply" button and "n cases match" inside the card.
  - My Cases: the same card, but "9 cases" sits outside it, below.
  - Department: Layout B, with Words in a left panel, the button reading "Search", and "3 cases" in a footer strip.
- **Why it matters:** moving between tabs, the reader has to find the controls and the count again each time.
- **Fix:** Layout B on all four tabs, one button word ("Search", as on Search and Cause List), and the count always in the footer strip.
- **Effort:** M. **API:** no.

**I2. The case number is a link on two tabs and bold text on the other two.** Low.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/inbox-with-me.png` and `inbox-sent.png` (blue, underlined) compared with `inbox-my-cases.png` and `inbox-department.png` (bold black).
- Code: `frontend/src/components/files/Held.tsx:168` compared with `frontend/src/components/inbox/rows.tsx:16`.
- **Fix:** one `CaseCell` on all four tabs. The row already opens the case, so plain bold everywhere, or a link everywhere.
- **Effort:** S. **API:** no.

**I3. With Me and Sent by Me have an unlabelled status column.** Low.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/inbox-with-me.png`, `2026-11-10-portal-ui-review/1280/inbox-sent.png`.
- Code: `Held.tsx:163` (the header is hidden from sight).
- **Defect:** a column about 140 px wide with no visible header holds a floating "Overdue", "Due Soon", "New" or "Waiting" badge. It is empty on rows with no state, and "Overdue" repeats the red Due By date.
- **Fix:** either give the column a visible header ("State") and a narrow fixed lead, or drop it and let the Due column say "Overdue by N days" (the rule row 228 point 9 sets for the dashboard).
- **Effort:** S. **API:** no.

**I4. "Ready to Close" appears under the Next Hearing column.** Low.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/inbox-with-me.png`, `inbox-my-cases.png`, `inbox-department.png`.
- Code: `rows.tsx` (`ClosureBadge`) and `MyCases.tsx:96-101`.
- **Defect:** "Ready to Close" is a state of the file, not of the hearing, but it sits below "Disposed" in the Next Hearing cell.
- **Fix:** move it to the state or reason column (or the column from I3).
- **Effort:** S. **API:** no.

**I5. The same due date is drawn two ways on sibling tabs.** Medium.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/inbox-with-me.png` compared with `2026-11-10-portal-ui-review/1280/inbox-my-cases.png`.
- Code: `Held.tsx:180` (`DueCell`) and `rows.tsx` (`ActionCell`).
- **Defect:** With Me and Sent by Me have a "Due By" column with a red date. My Cases puts the due date inside "Your Action" as a badge ("Overdue 12 days", "Due 1 Jan 2099").
- **Fix:** one Due cell everywhere: the date, "Overdue by N days" or "No Due Date".
- **Effort:** S. **API:** no.

### Case Claim (`/claim/recommended`, `/claim/pool`, `/claim/transfers`, case claim modal)

**C1. The score has three decimals on Case Claim and two on the Cause List, and the Pool cell wraps.** Low.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/claim-pool.png`, `claim-recommended.png`, `causelist.png`.
- Code: `frontend/src/components/claim/Pool.tsx:54`, `T.inbox.best` (`messages.ts:1560`), `frontend/src/lib/causelist.ts` (`recommendationText`).
- **Defect:** Pool shows "Best 0.912 for EDU" (with a code, wrapping over three lines). Recommended shows "· 0.912". The Cause List shows "EDU · 0.91".
- **Fix:** one score format, using the kit `ScoreBadge` everywhere, with the department name.
- **Effort:** S. **API:** no.

**C2. Transfers: Direction is two codes in mono, and "Requested" appears twice.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/claim-transfers.png`.
- Code: `frontend/src/components/claim/Transfers.tsx:58-72`.
- **Defect:** Direction reads "EDU → EDU" in mono and wraps over three lines. The column header "Requested" is followed in every cell by "Requested by … on …".
- **Fix:** show names (see K2), and write the cell as "Anita Sharma Baruah, 21 Oct 2026".
- **Effort:** S. **API:** see K2.

**C3. The claim modal says "Owner: Owned by EDU" and its tabs use "&".** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/claim-recommended-case-claim-modal.png`.
- Code: `frontend/src/components/claim/CaseModal.tsx`, `messages.ts:1661-1664`.
- **Defect:** the label and the value both say "own", and the value is a code. The tabs read "Parties & Advocates" and "Hearings & Listings"; the rest of the portal writes "and" (for example "Show Parties, Advocates and Acts").
- **Fix:** "Owner Department: Directorate of …", and "and" in the tab names.
- **Effort:** S. **API:** see K2.

**C4. A strong recommendation is blue on one screen and orange on another.** Medium.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/causelist.png` (orange), compared with the kit `ScoreBadge` (blue) on Case Claim and the case Ownership card.
- Code: `frontend/src/components/causelist/OwnershipCell.tsx:31` (`tone={r.band === "high" ? "warning" : undefined}`) compared with `frontend/src/components/ui/feedback.tsx:116`.
- **Why it matters:** the same fact has two colours, and orange elsewhere means "due soon".
- **Fix:** use `ScoreBadge` in the Cause List cell. Row 228 point 5 already sets the target: strong is solid navy, possible is outlined. Do this with row 229.
- **Effort:** S. **API:** no.

### Case page (`/cases/<ref>` and its tabs)

**P1. The status is shown twice in the header.** Low.
- Seen at 1280 and 375. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`.
- Code: `frontend/src/components/case/CaseFrame.tsx:358` (badge) and `CaseFrame.tsx:381-383` (Status fact).
- **Defect:** a "Pending" badge sits beside the title and the facts row shows "Status: Pending" again.
- **Fix:** keep the badge and drop the Status fact, or the reverse.
- **Effort:** S. **API:** no.

**P2. The next hearing appears three times on one screen.** Medium.
- Seen at 1280 and 375. Screenshots: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`, `2026-11-10-portal-ui-review/375/cases-aslms-ghc-case-2026-000001.png`.
- Code: `CaseFrame.tsx:98-115` (`NextHearingFact`), the Next hearing card in `frontend/src/components/case/Rail.tsx`, and `frontend/src/components/case/Overview.tsx:101-109`.
- **Defect:** the header fact shows the date, "Order Differs" and the three-line explanation ("The order of 12 Oct 2026 gives 14 Nov 2026; the court's record gives 11 Nov 2026…"). The rail's Next Hearing card repeats exactly that. The Overview's next-date block shows it a third time.
- **Fix:** the header shows the date and its badge only; the explanation lives in one place (the rail card, or the Overview block).
- **Effort:** S. **API:** no.

**P3. Owner and recommendations are shown by code.** Medium.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`, folded section "Ownership and Recommendations".
- Code: `CaseFrame.tsx:124-129` (`OwnerBadge` shows another department's code), and `frontend/src/components/case/OwnershipCard.tsx:31, 35, 116, 126` (owner, unit, other recommendations and transfer, all as mono codes).
- **Defect:** the facts row shows the owner's name, but the badge beside the title and the whole Ownership card show codes.
- **Fix:** names, through K2.
- **Effort:** S once K2 exists. **API:** see K2. `OwnershipOut`, `RecommendationOut` and `TransferOut` carry only codes.

**P4. The Latest Order card shows the raw order kind.** Medium.
- Seen at 1280 and 375. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`; the fixture shows `kind_0`.
- Code: `Overview.tsx:96` (`· {o.kind}`). The real values are `interim`, `final` and `judgment` (`backend/aslms/domain/documents.py:193-196`). `frontend/src/components/assistant/CourtOrderView.tsx:57` already maps them through `A.orderKinds`.
- **Defect:** the card reads "23 Oct 2026 · interim", in lowercase.
- **Fix:** use `A.orderKinds[o.kind]`.
- **Effort:** S. **API:** no.

**P5. The Latest Order card shows the order date three times.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`.
- Code: `Overview.tsx:94-106`.
- **Defect:** the bold date, then "23 Oct 2026  Show the Order", then "Counted from the order of 23 Oct 2026".
- **Fix:** keep the bold date, label the collapsible "Show the Order", and say "Counted from this order".
- **Effort:** S. **API:** no.

**P6. At 1280 px the case tab row overflows and hides "More".** Medium. Confidence: medium.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png` (only "N…" shows at the right edge), `…-more-menu-open.png` (the row has to be scrolled to reach More).
- Code: the case tabs in `CaseFrame.tsx`, and the kit `Tabs` (a `data-scroll-x` row).
- **Defect:** with the rail open, Notes, Timeline, Assistant and More are off-screen, with no visible scroll cue. The fixture counts (1,23,456) widen each tab, but an estimate with two-digit counts still overflows the 630 px column.
- **Why it matters:** readers do not find Notes or the More menu.
- **Fix:** move tabs that do not fit into More automatically (measure, then collapse), or show counts only on the active tab.
- **Effort:** M. **API:** no.

**P7. The rail cards use different headings.** Low.
- Seen at 1280 and 375. Screenshots: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`, `2026-11-10-portal-ui-review/375/cases-aslms-ghc-case-2026-000001.png`.
- Code: `Rail.tsx` and `frontend/src/components/case/rail.module.css`.
- **Defect:**
  - At 1280 or more, the Your Task card has no "Your Task" heading; it opens with a small blue "With …" line. The other cards have small grey labels.
  - At 375, each collapsed card draws an empty band and a divider above its title, and the Journey summary is centred while the others are left-aligned.
  - Quick Actions stacks three buttons of three different widths.
- **Fix:** one card header in the rail ("Your Task", "Next Hearing", "Quick Actions", "Journey of This Case") with the same style and alignment, and Quick Actions as equal-width buttons in a row.
- **Effort:** S. **API:** no.

**P8. The Overview's "Waiting for You" table is cramped.** Low.
- Seen at 1280 and 375. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001.png`, lower half.
- Code: `frontend/src/components/nextdates/CaseNextDate.tsx`.
- **Defect:** the Next Date column wraps one word per line ("The / order / gives / no / clear / date", "by / 23 / Oct / 2026") while the Actions column stays empty on rows that have no action. Below it, Report Wrong Next Date, Correct It and Enter Next Date break onto two lines, with "All Next Dates" set tight underneath.
- **Fix:** give Next Date a minimum width and do not wrap dates (K5); hide the Actions column when no row has an action; put the three buttons on one toolbar line and the link in the card header (K9).
- **Effort:** S. **API:** no.

**P9. The Details tab uses raw NAPIX field names as labels.** High.
- Seen at 1280 and 375. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-details.png` (also at 375).
- Code: `frontend/src/components/case/Details.tsx:19-22` (`fieldLabel` turns `reg_no` into "Reg no"), `Details.tsx:41-50` and `55-75`.
- **Defect:** the labels read "Case no text", "Cnr", "Court est name", "Filing no text", "Reg no", "Est code", "Date filing disp", "Reason for rej", "Goshwara no". Values are raw too: "Status: pending". Each card is its own definition list, so the label column is a different width in Identity, Status and Classification.
- **Why it matters:** this is where an officer checks the court's record, and the labels are database column names.
- **Fix:** a label map for every field shown ("CNR", "Case Number", "Registration Number", "Date of Filing Disposal", "Reason for Rejection", …), checked against the NAPIX notes so no field loses its home. Values through K4. One label width across the tab.
- **Effort:** M. **API:** no.

**P10. Hearings tab: dates wrap, and next-date rows show internal numbers.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-hearings.png`.
- Code: `frontend/src/components/case/Hearings.tsx`, `CaseNextDate.tsx:212` (`row.ref_no` in mono) and `CaseNextDate.tsx:229` (`order_no` in mono).
- **Defect:** the Date and Next Date columns wrap onto three lines (K5). Each Next Dates card shows its own internal reference ("ASLMS/GHC/CASE/2026/000001") in mono under the date.
- **Fix:** no wrapping on dates; drop the internal reference from view (keep it as a tooltip if the audit trail needs it).
- **Effort:** S. **API:** no.

**P11. Custody tab: the newest move is on the last page, and the Journey card is cramped.** High.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-custody.png`.
- Code: `frontend/src/components/workflow/CustodyTab.tsx:74-75` (`useCustodyHistory` with the default ascending order), `CustodyTab.tsx:97-107`, and the Stage card's columns. The rail's `useJourney` asks for `order: "desc"` (`frontend/src/lib/api/hooks.ts:231-236`).
- **Defect:**
  - The Movement Record lists move 1 first. With more than 50 moves, the current one is on the last page, while the rail and the remarks panel list newest first.
  - The Journey card's five-column grid puts the long remark in the narrow first column, one word per line, and leaves the rest of the card empty.
  - Every office has "EDU" in mono before its name.
  - The Stage card's column header reads "Note (Optional)", which is a form label.
- **Why it matters:** an officer looking for where the file is now sees the oldest moves.
- **Fix:** ask for `order=desc` (the API already supports it); give the remark the full width under the grid; drop the code; header "Note".
- **Effort:** S. **API:** no.

**P12. Notes tab: notes are referred to by number, in mixed case, and the list is styled differently.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-notes.png`.
- Code: `frontend/src/components/case/Notes.tsx:146-170`; `T.case.corrects` and `T.case.correctedBy` at `messages.ts:2176-2177` (lowercase) compared with `messages.ts:3378-3379` (Title Case).
- **Defect:**
  - A correction reads "corrected by ASLMS/EDU/NOTE/2026/000003" in lowercase; the readers never see that number anywhere else.
  - Each note header shows the internal reference in mono and ends the author with an office code.
  - The note list sits on the page background, while My Drafts and Write a Note beside it are cards.
- **Fix:** "Corrected by the note of 21 Oct 2026, 11:00" (a link), Title Case, no internal number in sight, and the list in a card.
- **Effort:** S. **API:** no.

**P13. Documents tab: an empty column and a ragged visibility cell.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-documents.png`.
- Code: `frontend/src/components/case/Documents.tsx:56-66` and the visibility column; `T.case.pages` at `messages.ts:2150`.
- **Defect:**
  - **(code)** Court orders come from the court and have no uploader, so the "Uploaded By" column of the Court Orders group is "—" on every row.
  - The Visibility cell runs badges straight into a long "Text: …" sentence.
  - The size reads "2 page(s)".
  - Two hints are stacked under Description ("3 to 500 characters." and "0 / 500 characters").
- **Fix:** hide Uploaded By for the court-record group (or say "From the Court"); put the text state on its own line; plurals (K10); one hint.
- **Effort:** S. **API:** no.

### Alerts (`/alerts`, `/alerts/next-dates`, case Alerts tab)

**A1. Alert severity sets the colour, the counts and a filter.** Medium.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/alerts.png` ("Unread · Critical · High · Normal"), `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-alerts.png`.
- Code: `frontend/src/components/ui/feedback.tsx:120-123` (`SeverityBadge`), `frontend/src/components/alerts/AlertList.tsx:78, 134, 201`, `frontend/src/components/workflow/CaseAlerts.tsx:139`; the severities are seeded in `backend/aslms/services/seed.py:144-153`.
- **Defect:** this is row 228 point 5, beyond the dashboard. "Critical", "High" and "Normal" are internal priorities ("Listed for tomorrow" is critical, "Hearing due" is high, "New note" is normal). They lead every alert row as a coloured badge and appear as summary counts and a filter.
- **Why it matters:** a reader cannot tell why "High" is amber or what "Critical" asks of them.
- **Fix:** with row 229 and row 228 point 5: the kind label leads, and the tone follows the meaning (hearing alerts take the hearing-date band; the rest are neutral). Replace the severity counts and filter with counts by kind or "Hearings", or keep severity only as the sort order.
- **Effort:** M. **API:** no.

**A2. The alert row shows its case number twice.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-alerts.png`. **(code)** For the Alerts page, the fixture list is empty.
- Code: `AlertList.tsx:47-55, 83-91`; titles end in ": <case number>" (`backend/aslms/services/alert_rules.py:223-274`).
- **Defect:** this is row 228 point 3 on the Alerts page and on the case Alerts tab. The title "Hearing on 11 Nov 2026: WP(C)/12345/2025" is followed by the case link again. On the case's own page, the case number in the title adds nothing. The row header also runs severity, kind, status, the alert's reference number in mono and "New" together (K11).
- **Fix:** the server title without the case label (or the portal strips it), with the case shown once as the link; no alert reference number in sight.
- **Effort:** S. **API:** text only, if done on the server.

**A3. Next-date work has three names.** Low.
- Code: `messages.ts:423, 960, 1032, 3677` ("Next Dates to Enter"), `messages.ts:3485` ("Next Date to Confirm" in the calendar legend), and the My Calendar subtitle ("next dates waiting for your confirmation").
- Screenshot: `2026-11-10-portal-ui-review/1280/calendar.png`.
- **Fix:** "Next Dates to Enter" everywhere.
- **Effort:** S. **API:** no.

**A4. Next Dates to Enter: a missed answer-by date looks like any other, and empty Actions rows show.** Low.
- Seen at 375 and 1280. Screenshot: `2026-11-10-portal-ui-review/375/alerts-next-dates.png`.
- Code: `frontend/src/components/nextdates/ReviewItem.tsx:111`.
- **Defect:** "Please answer by 23 Oct 2026" stays muted grey after that date has passed. On phone cards, an "Actions" label is shown with nothing beside it (K6).
- **Fix:** mark a passed answer-by date the way the inbox marks overdue ("Answer was due 23 Oct 2026").
- **Effort:** S. **API:** no.

### Cause List (`/causelist`)

**L1. Ownership is shown by code although the names are already loaded.** Medium.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/causelist.png`.
- Code: `frontend/src/components/causelist/OwnershipCell.tsx:16-33`. The `names` map is passed in but used only as a hover `title`.
- **Defect:** the cell reads "Claimed by EDU" and "Strong · EDU · 0.91".
- **Fix:** show `names[code]`, with the code as the tooltip if wanted.
- **Effort:** S. **API:** no.

**L2. The Cause List writes "versus"; everywhere else writes "vs".** Low.
- Code: `messages.ts:1903` compared with `messages.ts:926`.
- **Effort:** S. **API:** no.

**L3. At 375 px the "Cause-list Entries" caption is squeezed into three lines.** Low.
- Seen at 375. Screenshot: `2026-11-10-portal-ui-review/375/causelist.png`.
- Code: the entry table caption (K1).
- **Defect:** the caption is boxed into a column about 60 px wide ("Cause- / list / Entries").
- **Fix:** K1.
- **Effort:** S. **API:** no.

### Search (`/search`)

**S1. The result count and the heading are said twice.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/search.png`.
- Code: `frontend/src/components/search/CaseResults.tsx:88` (`showCaption`) and `frontend/src/components/search/Search.tsx`.
- **Defect:** the filter footer says "1,23,456 cases match". The section heading says "Your Cases · 1,23,456+ cases". The card caption then repeats "Your Cases", flush with the card edge. The automatic doubled-heading check misses it because the heading sits outside the card.
- **Fix:** one heading with the count; drop the caption or keep it for screen readers only.
- **Effort:** S. **API:** no.

**S2. Result rows lead with the parties, and the Status column stacks four facts.** Medium.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/search.png`.
- Code: `CaseResults.tsx:25-50`.
- **Defect:** every other list starts with the case number; here the parties line comes first and the case number follows. The Status column stacks "Pending / Owned by EDU / In the Unclaimed Pool / Court Details Not Yet Fetched" in about 100 px, wrapping one word per line, with a code.
- **Fix:** case number first (as `inbox/rows.tsx` `CaseCell`); Status as one badge plus one muted line; the owner's name (K2).
- **Effort:** S. **API:** see K2.

**S3. The header search box says "CINO".** Low.
- Seen at every size. Screenshot: `2026-11-10-portal-ui-review/1280/dashboard.png`, top bar.
- Code: `messages.ts:1758`.
- **Defect:** every other screen says "CNR".
- **Fix:** "Search by CNR, case number or party name".
- **Effort:** S. **API:** no.

### Reports (`/reports/*`)

**R1. Report titles and column headers come from the server in sentence case.** Medium.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/reports-pending-cases.png`, `reports-data-health.png`.
- Code: `backend/aslms/services/reports.py:81-96` (titles) and `reports.py:411-719` (columns, for example "Holding department", "Due soon", "Status pending", "Cases with a pending action", "Watching (not owned)").
- **Defect:** the on-screen report is headed in lowercase, and its column headers are outside the Title Case guard. The fixture title "pending cases" shows the risk.
- **Fix:** Title Case in the backend catalogue and in the column labels; the same strings go into Excel and PDF.
- **Effort:** S. **API:** text only.

**R2. Report tables carry code columns, and one "name" column holds a code.** Medium.
- Code: `reports.py:411-412, 514, 689-691, 703-704` ("Department code", "Court code", "Holder office code"…) and **`reports.py:714`, where `Column("holder_office_code", "Holder office")` shows a code under a name label**. **(code)**
- **Why it matters:** the on-screen report doubles its width with codes, and one column is mislabelled.
- **Fix:** keep the code columns in the Excel export only (or behind "Show Codes"); on screen, show the name; fix the label at line 714.
- **Effort:** S. **API:** yes, a small backend change (a column flag or label).

**R3. The department picker is cut off, and the case list wraps hard.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/reports-pending-cases.png`.
- Code: `frontend/src/components/reports/ReportForm.tsx`, `frontend/src/components/reports/ReportView.tsx`.
- **Defect:** the Department select shows "Department of Schoo". In the case list, Petitioner wraps one or two words per line and Filed wraps onto three lines (K5).
- **Fix:** a wider select (or the kit Office Picker); a minimum width for Petitioner; no wrapping on dates.
- **Effort:** S. **API:** no.

### Audit Log (`/audit`, `/audit/<id>`)

**U1. The Action column shows raw action codes.** Medium.
- Seen at 1280 and 375. Screenshots: `2026-11-10-portal-ui-review/1280/audit.png`, `2026-11-10-portal-ui-review/1280/audit-0192a3b4-0000-7000-8000-0000000000a1.png`.
- Code: `frontend/src/components/audit/AuditTable.tsx:44-53`, `actionName` in `frontend/src/lib/audit.ts:106-108`; `T.audit.actionNames` (`messages.ts:2389`) names only **3** of about 100 action codes the backend writes.
- **Defect:** rows read "ownership.claim", "custody.sent" and "notes.added" in mono, broken mid-word ("ownership.c / laim").
- **Why it matters:** the Auditor reads names, not codes. The design kept the code as a narrowing link, but a name can carry the same link.
- **Fix:** names for every action code, with a test that every backend code has one; the code stays as the tooltip and in the entry page.
- **Effort:** M. **API:** no (or the API supplies labels).

**U2. The entry page shows a raw ID for Record.** Low.
- Code: `frontend/src/components/audit/AuditEntry.tsx`.
- **Defect:** "Record: <type> 0192a3b4-…" shows a raw UUID, and By ends with an office code.
- **Fix:** show the record's reference or name where one exists; office name (K2).
- **Effort:** S. **API:** possibly, for record names.

### Data Collection (`/data/*`)

**DC1. Data Collection cards break words and numbers in the middle.** Medium.
- Seen at 1280. Screenshots: `2026-11-10-portal-ui-review/1280/data-overview.png` (Month by Month: "Octob/er 2026", "1,23,4/56"), `2026-11-10-portal-ui-review/1280/data-problems.png` (header "Tri/es").
- Code: `frontend/src/components/data/data.module.css:23` (`overflow-wrap: anywhere` on every data card).
- **Fix:** `overflow-wrap: break-word` on the card, and `anywhere` only on the long free-text cells.
- **Effort:** S. **API:** no.

**DC2. Problems and Fixes draws one action two ways and shows raw errors.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/data-problems.png`.
- Code: `frontend/src/components/data/ProblemsAndFixes.tsx`.
- **Defect:** "Retry All" is a button in the middle of the by-kind table, while "Retry" is a right-aligned link in the failed-fetch table. The Problem column shows the raw exception ("IntegrationError: NapixUnavailable 502 Bad Gateway from /nic/ecourts/hc-cnr-api/v1.0/…?est_code=GAHC01&attempt=5").
- **Fix:** both as small secondary buttons in a right-aligned action column; the problem in plain words ("The court did not answer (502)"), with the raw text behind "Details".
- **Effort:** S. **API:** no.

### System Health (`/system`)

**Y1. API card titles start wherever the status badge ends.** Medium.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/system.png`.
- Code: `frontend/src/components/system/ApiPanel.tsx:31` (badge before the title).
- **Defect:** "Working Connection Check", "Unsteady High Courts List" and "No Recent… Benches List" (the badge itself truncated) are the ragged-row defect of row 228 point 4: across the grid, the titles start at different x positions.
- **Fix:** title first, badge on its own line or at the card's right edge.
- **Effort:** S. **API:** no.

**Y2. The overview badge repeats the sentence.** Low.
- Screenshot: `2026-11-10-portal-ui-review/1280/system.png`.
- **Defect:** "Working · Everything is working".
- **Fix:** the sentence alone, with the tone carried by the ring.
- **Effort:** S. **API:** no.

### Administration (`/admin/*`)

**AD1. The Users list has an "Initials" row.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/admin-users.png`.
- Code: `frontend/src/components/admin/Users.tsx:244`.
- **Defect:** the list is drawn as cards even at 1280 px, and the avatar appears as a labelled field, "Initials: AB".
- **Fix:** the avatar as the card's lead, without a label.
- **Effort:** S. **API:** no.

**AD2. Tickets are identified by reference number and department code.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/admin-tickets.png`.
- Code: `frontend/src/components/admin/Tickets.tsx:98, 113, 275, 285, 297`.
- **Defect:** the card title is the ticket reference in mono; Department is a mono code; "Requested by … (EDU)".
- **Fix:** title as the kind and the person ("Head Change: Anita Sharma Baruah") with the reference muted; department name (K2).
- **Effort:** S. **API:** see K2 (`TicketItemOut` has only `department_code`).

**AD3. Recommended From Cause Lists: rows are laid out differently, and the sample case shows its internal reference.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/admin-mapping-codes.png`.
- Code: `frontend/src/components/admin/mapping/CounselCodes.tsx` (the unmapped panel), `frontend/src/components/admin/mapping/common.tsx:282`.
- **Defect:** in the first row, "entries · last seen" sits under the code on the left; in the next rows it sits on the right. The example case is shown by its internal reference ("ASLMS/GHC/CASE/2026/000001") in mono rather than its case number.
- **Fix:** one row layout; show the case number (keep the link).
- **Effort:** S. **API:** possibly (the sample carries only `ref_no`).

**AD4. Keywords: "Search the Court" is repeated in every cell.** Low.
- Seen at 1280. Screenshot: `2026-11-10-portal-ui-review/1280/admin-mapping-keywords.png`.
- Code: `frontend/src/components/admin/mapping/Keywords.tsx:65-85`.
- **Defect:** the header "Search the Court" is repeated beside every checkbox, and the line reads "123456 case(s) found." with an unformatted number and "(s)".
- **Fix:** checkbox with a label hidden from sight under the header; a formatted, pluralised count (K10).
- **Effort:** S. **API:** no.

---

## Portal-wide patterns (one kit or helper fix each)

**K1. A visible table caption sits flush with the card edge.** Medium.
- Code: `frontend/src/components/ui/data.module.css:11-15` (`caption { padding: var(--s2) 0 }`, while cells are inset by `--s4`).
- **Defect:** this is row 228 point 1, from the kit. `showCaption` is used in 21 places: Transfers "To Us", Search "Your Cases", the dashboard's Department, State and Tickets tables, Problems and Fixes, Tracking Summary and others. At 375 px the caption can also be squeezed into a narrow box (L3).
- **Fix:** give the caption the cells' left padding (or make it a real card heading), with `display: block; width: 100%`.
- **Effort:** S. **API:** no.

**K2. Office and department codes appear where people read names.** High.
- **Seen in** (examples):
  - With Me "From … , EDU" (`frontend/src/lib/cases.ts:50-54`).
  - Department "Responsible Unit" as a mono code (`frontend/src/components/inbox/DepartmentCases.tsx:69`).
  - Department "With … · HEALTH".
  - Case owner badge and Ownership card (P3).
  - Cause List (L1), Pool and Transfers (C1, C2), Search status (S2).
  - Custody tab (P11), notes, documents and audit authors.
  - Tickets (AD2).
  - Dashboard: State "by Holder" and "by Owner" (`frontend/src/components/dashboard/Blocks.tsx:457`), Tickets by Department (`Blocks.tsx:514`), and name plus mono code in `Blocks.tsx:243, 406`.
  - Tracking Summary (`frontend/src/components/files/TrackingSummary.tsx:31, 47, 57`).
  - Report "Generated by …, GOA".
  - Seven department pickers that lead with the code and get cut off ("EDU — Directorate of Secondary Education, I…": `FilterBar.tsx:335`, `Held.tsx:140`, `DepartmentHearings.tsx:194`, `DepartmentCases.tsx:131`, `frontend/src/components/inbox/dialogs.tsx:64, 117, 534`, `frontend/src/components/inbox/selection.tsx:48`), while the Reports picker shows names only.
- **Cause:** most API objects carry only the code: `CustodySentByOut`, `NoteAuthorOut`, `DocumentUploaderOut`, `AuditActorOut`, `CustodyLegOut.actor_office_code`, `OwnershipOut`, `RecommendationOut`, `TransferOut`, `EntryRecommendationOut`, `DashboardCodeCountOut`, `DepartmentCustodySummaryOut`, `TicketItemOut`, `DashboardOwnCasesOut`. Only `PrimaryOwnerOut` and the cause-list `names` map carry names.
- **Fix:** rather than a dozen schema additions, add one small read-only endpoint (for example `GET /reference/offices`: code to short name for active offices, for any signed-in user), cached once, and a kit `OfficeName` component. Then replace every mono code with it (the code stays as the tooltip), and show pickers as the name with the code muted. Row 228 point 8 (My Cases department) can use the same component.
- **Effort:** M for the endpoint and kit, plus M for the sweep. **API:** yes, one endpoint. No migration.

**K3. Server labels are outside the Title Case guard.** High.
- **Defect:** the portal's guard covers only `T`, but readers see many labels from the server:
  - Every `ref_*` label created by the seed's `_label()` is sentence case (`backend/aslms/services/seed.py:54-55`, for example `counsel_briefed` becomes "Counsel briefed"), plus the explicit maps at `seed.py:76-81, 98-110, 156-200`: alert kinds ("Hearing due", "Listed for tomorrow", "Next date reported as wrong"), case stages, document types ("Government order / notification"), note kinds, timeline events ("Cause list corrected", "Case moved").
  - Pending actions (`backend/aslms/domain/workflow.py:65-79`: "No action pending", "File in court", "Parawise comments", "Instructions to counsel", "Other - see remark").
  - Dashboard attention titles (D1) and report titles and columns (R1).
- **Why it matters:** these appear on every case and list screen next to Title Case portal labels. Row 228 point 7 fixes only one of them ("Hearing due").
- **Fix:** two choices for the owner.
  - (a) Display side: pass every server label through the existing `titleCase()` (`frontend/src/lib/titleCase.ts:64`, today used by nothing) in `labelOf` and the label helpers. No API change, and it also covers labels that administrators edit.
  - (b) Data side: a reference-data migration relabelling the `ref_*` rows, plus backend constants for pending actions, reports and dashboard text.
  - Recommendation: (a) now, with (b) for the backend constants that also go into exports and e-mails.
- **Effort:** M. **API:** (a) none; (b) text and a reference-data migration.

**K4. Raw codes leak through label fallbacks.** Medium.
- Code:
  - `?? code` and `replace(/_/g, " ")` fallbacks in `frontend/src/lib/nextDates.ts:13`, `frontend/src/lib/timeline.ts:42, 101`, `frontend/src/lib/signals.ts:28`, `CustodyTab.tsx:139`, `ProblemsAndFixes.tsx:313`.
  - Many `T.x[code] ?? code` lookups (statuses, transfer statuses, severities, visibilities).
  - Unmapped values: `Overview.tsx:96` (P4), and `Details.tsx` values such as "pending" (P9).
- **Defect:** a value without a label shows as a lowercase code.
- **Fix:** one `labelFor(map, code)` helper that Title-Cases a fallback, and a unit test that every enum in `openapi.json` used on screen has a label.
- **Effort:** M. **API:** no.

**K5. Dates wrap inside table cells.** Medium.
- Seen in: Due By (Inbox), Date and Next Date (Hearings), Filed (Reports), Updated (Mapping and Watchlist), Since (Custody); "23 / Oct / 2026" on three lines.
- Code: the kit `DataTable` has no notion of a date column.
- **Fix:** a `nowrap` (or `kind: "date"`) column option in `DataTable`, or `formatDate` joining the parts with non-breaking spaces.
- **Effort:** S. **API:** no.

**K6. Phone and stacked cards align values unevenly and show empty rows.** Medium.
- Seen at 375 and 768, and on stacked tables at 1280. Screenshots: `2026-11-10-portal-ui-review/375/inbox-with-me.png`, `2026-11-10-portal-ui-review/375/alerts-next-dates.png`, `2026-11-10-portal-ui-review/1280/cases-aslms-ghc-case-2026-000001-custody.png`.
- Code: `data.module.css:157-170`.
- **Defect:** text values are right-aligned, but badges and buttons sit left, right after the label (Status, Next Hearing, Actions). Long text (remarks) is right-aligned over several lines. A labelled row shows when its cell is empty ("Actions", "Status").
- **Fix:** values left-aligned in a second grid column (label column of fixed width), and the row hidden when the cell renders nothing.
- **Effort:** S to M. **API:** no.

**K7. Notice has one tone, the success green, for every kind of message.** Medium. Do it with row 229.
- Code: `frontend/src/components/ui/feedback.tsx:59-65` and `feedback.module.css:70-83`. 67 of 81 Notices use the default green.
- **Defect:** the same green carries warnings ("Court calls are switched off on this server… tests are not possible", "Earlier Version: this list was replaced"), neutral information ("Nothing is mapped automatically", the Cause List's bench note) and confirmations ("As it stands today").
- **Fix:** add `info` (neutral) beside `success` and `warning` and choose the tone per notice. The colour values themselves come from row 229.
- **Effort:** S for the kit, plus S for choosing per notice. **API:** no.

**K8. Empty states come in four styles.** Low.
- Code: kit `EmptyState` with a title (9 uses), `EmptyState` without one (88), a plain muted paragraph (about 25, for example `Overview.tsx:92, 131`, `Rail.tsx:250`, `Details.tsx:47`), and sections that disappear when empty (`Blocks.tsx` `FileList` returns `null`).
- **Fix:** one rule: lists and panels use `EmptyState` (with a title on primary panels); a muted line only inside a fact or definition list.
- **Effort:** M. **API:** no.

**K9. "View all" links sit in different places.** Low.
- Seen in: card header right with an arrow ("Open Calendar →", "All Orders →", "Timeline →"), bottom-left plain links ("Journey and Stage", "All Next Dates", "Data Collection Overview"), block headers (the dashboard Reports link), and inside sentences.
- **Fix:** every "see all" link in the `Card` `actions` slot, worded "View All …". Row 228 point 2 sets the same for the dashboard.
- **Effort:** S. **API:** no.

**K10. Plurals and counts.** Low.
- Code: "(s)" in 12 messages (`messages.ts:26, 1186, 1190, 1808, 1863, 2074, 2150, 2235, 2298, 3589, 3592`, and others); unformatted counts in `T.discovery.ruleLine`, `T.offices.users` and `T.system.courtCount`.
- **Fix:** a `plural(n, one, many)` helper with `formatNumber`.
- **Effort:** S. **API:** no.

**K11. Titles and text start after a badge.** Medium.
- Seen in: System Health cards (Y1), the alert row headers (A2), note and draft headers (kind, Draft, visibility, date in one run), and the case Alerts tab.
- **Defect:** across a list, the text starts at a different x position on each row: the alignment rule of decision 15 and row 228 point 4.
- **Fix:** a kit rule: the title first, badges after it or in a fixed `Lead` column (as `AttentionPanel` already does).
- **Effort:** S per list. **API:** no.

---

## Proposed build rows, in order

Row 228 (`dashboard-my-work-polish`) uses K1, K2 and K11, so build it after row A or fold it into row C.

1. **Row A, `portal-ui-kit-fixes`. Before row 229.** Frontend only; no API change; no migration.
   - Scope: K1 caption padding, K5 dates without wrapping, K6 phone-card alignment and empty rows, K11 title-before-badge (with Y1, A2's header and the note headers), DC1, K8 empty-state rule, K9 link placement, K10 plurals.
   - Effort: about 2 to 3 days, plus the full screen check.
   - These change spacing and alignment, so they belong before the colour change: row 229 promises that "every position, size, spacing and layout stays as it is".

2. **Row B, `portal-names-and-labels`. Before row 229.** One small read-only API endpoint; no migration if the owner picks K3 option (a).
   - Scope:
     - K2: one endpoint `GET /reference/offices`, the kit `OfficeName` component, the sweep, and pickers showing names.
     - K3: Title Case of server labels, plus the backend constants for reports and dashboard text (R1, D1's strings).
     - K4: the `labelFor` helper and the enum-label test.
     - P9: Details labels. U1: audit action names. P4. R2.
     - Small wording: S3, A3, L2, C3, P12's case.
   - Effort: about 3 to 4 days.

3. **Row C, `portal-screen-fixes`. Before row 229, after A and B.** Frontend only, except the D1 and A2 text if done on the server.
   - Scope: the screen-specific layout findings: I1 to I5, P1, P2, P5 to P8, P10, P11, P12 (the rest of it), P13, A4, S1, S2, C1, C2, D2, D3, L3, R3, DC2, Y2, U2, AD1 to AD4. P3 and L1 are covered by row B's names sweep.
   - Effort: about 4 days. It can be split in two: (C1) work screens (Dashboard, Case Inbox, Case Claim, Case page, Alerts, Cause List) and (C2) oversight and administration (Search, Reports, Audit, Data Collection, System Health, Administration).

4. **With row 229 (`portal-navy-cream`).** These are about what colour means, so they fold best into row 229 itself.
   - Scope: K7 Notice tones (`info`, `success`, `warning`); A1 alert tone by meaning in place of severity (together with row 228 point 5); C4 one recommendation tone (strong solid navy, possible outlined) on every screen.
   - Effort: about 1 day added to row 229.

## Confidence and open questions

- Marked **(code)**: D1's real repetition, A2 on the Alerts page, P13's empty Uploaded By, R2 line 714. Each one is clear in the code, but the fixtures do not show it. P6 (the tabs overflow at 1280 px) is estimated from the tab widths with real counts; it should be checked once on the live stack.
- **Decision for the owner on K3:** Title Case the server labels in the portal at display time (no data change, and it also covers labels that administrators edit), or relabel them in the database by a reference-data migration.
- **Decision for the owner on U1:** the Audit Log showed action codes on purpose (row 41 design). Should the Auditor see names, with the code kept as the tooltip and on the entry page?
- The fixtures could be improved so the screen check shows real-looking values: department names, alert lists, real `kind`, `status` and `role` codes. That would let the next review see more and infer less from code.
