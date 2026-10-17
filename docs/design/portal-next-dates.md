# Design: Portal — next dates read from orders: the review list, the case page's next-date block, the Orders tab reading and the dashboard link

```
slug: portal-next-dates
status: approved
author: architect
date: 2026-10-17
approved_by: owner (nayanlhuzuri) on 2026-10-17
```

## Context
Backlog row 73, split out of row 26 at its approval (owner, 17 Oct 2026): "Portal screens for next dates from orders:
the review queue page (confirm, reject with a replacement date, enter a date), the case page's next-date block with
Enter next date, the reading column on the Orders tab, the dashboard link to the queue; design as
docs/design/next-date-extraction.md decision 1."

The plan:
- §5.3 / §5.7: "Next dates from orders: specific dates are read directly; periods such as 'list after two weeks' are
  ... counted from the order date; unclear directions are flagged for manual review (Figure 6)." The case overview
  shows "the latest order with the next date read".
- §5.1: the department dashboard shows "items needing attention, including next dates read from new orders".
- §5.5: the hearing calendar and alerts are fed by the resulting date (Figure 6).
- §7 Table 8: "next dates (with source: specific date / period ... / manual review)".

The backend is row 26 (`next-date-extraction`, approved; being finished on `feature/next-date-extraction`). This item
builds on that branch as it stands at commit `3c488d4` and on the owner's decision of 17 Oct 2026 at the top of that
note: periods are always confirmed by a person; a date after `after` / `on or after` / `from` / `onwards` / `not
before` / `commencing` is a suggestion that needs confirmation; another matter's date, or two dates in one direction,
reads unclear (an *enter* item); only a plain direction ("List on 15.11.2026") is firm. Those rules change which
readings land where, not the API's shape, so they change nothing here except one label (decision 12).

In place on the branch (used as they are):
- `GET /next-dates/review` (`next_dates.review`): items `{kind: confirm | enter, id (next date id / order id), case
  {id, ref_no, cnr, case_no_text}, order {id, order_no, order_date, document_id}, phrase, rule, next_date (null for
  enter), act_by, alert_ref_no, departments: [office code]}`, `total`; `kind` and the shared case filters
  (`case_filter_query`, so `q` = a case uuid narrows to one case), `limit`, `offset`; sorted by `act_by`, then case.
- `POST /next-dates/{id}/confirm` (`{}` → `NextDateOut`); `POST /next-dates/{id}/reject` (`{note?, next_date?}` →
  `{rejected, entered}`); `POST /cases/{ref}/next-dates` (`{next_date, note?, order?}` → `NextDateOut`, 201);
  `GET /cases/{ref}/next-dates` (every source, newest first, each with `effective`).
- `GET /cases/{ref}` gains `next_date_from_orders: NextDateOut | null` (decision 9's row; null when none or when the
  newest is still waiting for review) and `next_dates_to_review: int` (the case's queue items the caller may act on).
- `GET /cases/{ref}/orders` items gain `next_date_status` (`pending` / `specific` / `period` / `unclear` / `none` /
  `no_text`), `next_date_found`, `next_date_rule`, `next_date_phrase`.
- `GET /dashboard/department` `attention.next_dates_to_review` (both kinds, the department's claimed cases; null
  without the function) and `recent_order_next_dates[]` with `source` and `review_status`.
- Errors: 400 `bad_field`, 403 `forbidden` / `not_working_on_case`, 404 `not_found`, 409 `not_owned` / `not_pending` /
  `already_entered`.
- Events on the timeline: `next_date_extracted`, `next_date_reviewed`, `next_date_entered`; alert kind
  `next_date_review` (label from `GET /reference/labels`).

In the portal (reused, not rebuilt): the Alerts & calendar frame (`AlertsFrame`, `ALERTS_TABS`), `FilterBar` and
`LIST_FILTERS`, `Overview.tsx` cards, `Orders.tsx` and `fileUrl`, `Hearings.tsx`, `Dashboard.tsx` `DepartmentBlock`,
`AlertList.tsx`, `lib/timeline.ts` `DETAIL`, `useWorkflowRefresh`, `useAction`, `ConfirmDialog`, `Dialog`,
`TextArea` with `CharCounter`, `Remark` (clamped text, from Files), `CaseLink`, `Pagination`, `ErrorBanner` with
per-screen error texts, `todayIst()`, `formatDate`.

**Not on the branch, needed here:** nothing in `GET /cases/{ref}` says whether the caller may *enter* a next date on
the case (decision 10's rule: the function, a working basis in the same membership, a claimed case).
`next_dates_to_review` counts queue items only, so a case with a firm date and no queue item would give no way to
know whether to offer "Enter next date". Decision 3 adds that one flag as this item's only backend change (read-only,
the rule already approved). Also not exposed: the `NEXT_DATE_MAX_AHEAD_DAYS` setting (default 548), so the date
field cannot show the exact upper bound (decision 9).

Not covered: SourceTrace readings of periods (row 37); compliance directions (row 27); OCR of scanned orders; the
review follow-ups parked by the owner's decision point 5 (two orders on the same date, a newer order without a stored
document, batch locks); any change to the reader's rules.

## Decisions
1. **The review list is a third tab of Alerts & calendar: `/alerts/next-dates`, "Next dates to confirm".** Shown
   with `next_dates.review` (the API's gate; every case-work type holds it by default). The `next_date_review` alerts
   and the hearing calendar live in the same frame, and the date the person confirms goes straight to that calendar.
   Filters and paging in the query string (row 12's rule). Breadcrumb `CRUMB_PATHS["/alerts/next-dates"]` = "Next dates
   to confirm". Alternatives: a sidebar entry of its own (one more top-level item for a list that is often empty);
   a Case inbox tab (the inbox is per department, the queue is per person across memberships).
2. **What a page offers comes from the server** (row 12 decision 8, portal-workflow decision 4). The review list shows
   what `GET /next-dates/review` returns, and every row there may be acted on. The case page offers Confirm / Not
   correct / Enter date only for the items the same API returns for that case, and "Enter next date" only by the new
   `workflow.next_dates` flag (decision 3). The tab shows by the function in `/me` only as convenience: the API decides
   every call. The browser never works out review state, readings or who may act from codes.
3. **One read-only API addition: `workflow.next_dates: bool` on `GET /cases/{ref}`** (not on the branch; flagged).
   True when the case has an active primary owner and one of the caller's memberships with a working basis on the
   case holds `next_dates.review` — `visibility.acting_member_for_case(session, user, case,
   Permission.NEXT_DATES_REVIEW)`, the same computation as `set_stage` (portal-workflow decision 20a) and the check
   `next_dates._check_write` runs before every confirm / reject / enter. One flag covers all three actions: they share
   one rule (next-date-extraction decision 10). No lock, no write, no audit. Alternatives: the portal guessing from
   `/me` functions and `access_basis` (the rule written twice, forbidden by decision 2); offering the button to every
   holder of the function and letting the API answer 403 (a button that fails for State readers).
4. **The review list** (`/alerts/next-dates`): `GET /next-dates/review`, paged by 50, in the API's order (the date to
   answer by, then case). Above it the shared `FilterBar` (new list key `next_dates`: the case fields `q`, listed,
   next, case type, year, case status, court, bench, and `owner`) with one own control "Show": "Everything" (default,
   `kind` omitted), "Dates to confirm" (`kind=confirm`), "Dates to enter" (`kind=enter`); total "n items". Each row:
   - the case (`CaseLink`, number and CNR);
   - the order: "Order of 12 Oct 2026" with the order number, and "View order" when `order.document_id` is set and
     the login holds `documents.view` (the existing `fileUrl(..., "inline")`);
   - "What the order says": the court's sentence (`phrase`) in quotation marks, clamped to two lines with "Show more"
     (`Remark`); none for a scanned order;
   - *confirm*: "Suggested from the order — please confirm" and the date in bold, with a one-line hint from the rule
     (decision 12); buttons **Confirm** and **Not correct…**;
   - *enter*: "No date could be read from this order — please enter the next date" (a scanned order: "This order is
     a scanned copy and could not be read — please open it and enter the next date"); button **Enter date…**;
   - "Please answer by <act_by>"; the department (`departments`) only when the login has more than one department
     membership.
   Not shown: `alert_ref_no`, the rule code, any score or confidence. Empty list: "Nothing to confirm. New orders of
   your cases are checked every few minutes." With filters: "No item matches these filters." Under the list, a muted
   line: "Only cases your office works on are listed here."
5. **Confirm** opens a `ConfirmDialog`: "Confirm <date> as the next date of <case>?" with the court's sentence and "It
   will appear in the hearing calendar and the hearing alerts." → `POST /next-dates/{id}/confirm`. Notice:
   "Confirmed. <date> is now the next date of <case>." Alternative: one click without a dialog (a confirmation cannot
   be undone through the API: only a later entered date replaces it).
6. **Not correct…** opens a `Dialog` "This date is not right": the suggested date and sentence; "The correct next
   date (if the order gives one)" — an optional date field (`min` today, IST); "Reason (optional)" — a `TextArea`
   with `CharCounter` (300) and the hint "Shown to everyone who can see the case. Do not write internal remarks." →
   `POST /next-dates/{id}/reject` with `next_date` and `note` only when filled. Notice: "Saved. The next date is now
   <entered.next_date>." when `entered` is set, else "Saved. The suggested date will not be used."
7. **Enter date…** (an *enter* item) and **Enter next date** (the case page, decision 8) open one `EnterNextDate`
   dialog: "Next date" (required, `min` today), "Note (optional)" with the same 300-character counter and hint, and
   the line "The date you enter is used for the hearing calendar and alerts until a newer order of the case
   arrives." → `POST /cases/{ref}/next-dates` with `order` = the item's order id when opened from an *enter* item
   (so the item leaves the list) and no `order` from the case page's button. Notice: "Saved. <date> is the next date
   of <case>."
8. **The case page's next-date block: a new Overview card "Next date from orders"** after "Next hearing":
   - `next_date_from_orders` set: the date in bold (with the existing "Within 48 hours" / "This week" badges of
     `hearingBadge`); where it came from in words (decision 12): "Fixed in the order of 12 Oct 2026", "Counted from
     the order of 12 Oct 2026 · confirmed by <name> on <date>", "Entered by <name> on <date>"; the court's sentence
     (`order.phrase`) in a `<details>` "What the order says"; the note of an entered date, if any.
   - null: "No next date from the orders yet."
   - `next_dates_to_review` > 0: a highlighted panel "Waiting for you" with the case's items, read from `GET
     /next-dates/review?q=<case id>` (the queue API narrowed by the shared `q` filter; no new endpoint), each with the
     row's text and buttons of decision 4.
   - `workflow.next_dates`: the button **Enter next date**.
   - the link "All next dates" to `/cases/<ref>/hearings#next-dates`.
   The court's own next hearing date stays in the "Next hearing" card unchanged (the court record and the reading
   are different facts; the calendar shows both by source). The "Latest order" card gains one line with the order's
   reading in the words of decision 11 ("Next date found in the order: 20 Nov 2026"), as plan §5.3 asks.
   Alternative: merge into "Next hearing" (two dates from different sources in one card confuse which is the court's).
9. **Dates and their limits.** Every date field is `type="date"` with `min` = `todayIst()`; no `max`, because the
   upper bound is a server setting not exposed by any API. A date the server refuses (400 `bad_field`) shows "The
   date must be today or later, and not more than about 18 months ahead." (the default 548 days). Dates shown with
   `formatDate` (IST), as everywhere.
10. **All next dates of the case: a "Next dates" section on the Hearings tab** (`id="next-dates"`), under the
    hearings and above the cause-list appearances: `GET /cases/{ref}/next-dates`, newest first, paged by 50, a table
    with Date, Where it came from (decision 12), Status (decision 12), Order (number and date, View order when
    stored and allowed), By (the person who entered or reviewed it, and when), Note, and a "Used for the calendar"
    badge on the row with `effective`. Every reader of the case sees it (court data and notes shown to every case
    reader, next-date-extraction decision 17). The `NXT` reference of an entered date is shown in monospace (the
    portal's rule for references). Alternative: a new case tab (one more tab for a short list).
11. **The Orders tab's reading column: "Next date read"**, from the order's own fields, in plain words:
    `specific` → the date ("Date in the order"); `period` → the date and "counted from the order"; `unclear` → "No
    clear date"; `none` → "No next date given"; `no_text` → "Could not be read (scanned copy)"; `pending` → "Not read
    yet". When `next_date_phrase` is set, a `<details>` "What the order says" under it. The column never shows the
    review state (that belongs to the next date, decision 10) nor the rule code.
12. **Plain words, one table in `messages.ts` (`T.nd`).** Sources: `causelist` "Cause list", `current_status` "Court
    records", `order_specific` "Date in the order", `order_period` "Counted from the order", `manual` "Entered by
    hand". Statuses: `not_needed` "In use", `pending` "Suggested from the order — please confirm" (for a reader
    without the action: "Waiting for confirmation"), `confirmed` "Confirmed", `rejected` "Not accepted",
    `superseded` "Replaced by a later date", `expired` "Date passed before it was confirmed". Rule hints (one line
    under a suggested date, never the code): `returnable_date` "The order gives this as the returnable date of the
    notice"; `list_after_period`, `after_returnable_period`, `returnable_period` "Counted from the order date — the
    order gives a period, not a date"; `conflicting_dates` "The order gives more than one date"; `no_countable_date`
    "The order gives no date that could be counted". The rule name the developer gives the owner's point 2 ("after /
    from / not before <date>") is not on the branch yet; its hint will be "The order says not before this date —
    please check the exact day", added to the table when the name is fixed. An unknown rule shows no hint line, an
    unknown code shows the code with underscores as spaces (the portal's fallback). No screen shows confidence,
    rule codes, "rule", "extraction", job or call figures.
13. **The dashboard link.** In the department block's "Items needing attention", "Next dates to review" becomes
    "Next dates to confirm"; when its count is above zero the line is a link to `/alerts/next-dates?owner=<department
    code>` (a link, not a gate, as portal-reports decision 10). The count is the department's total
    (next-date-extraction decision 18); the list shows the items the reader may act on, so for an officer working on
    only some of the department's cases the list may be shorter than the count — the list's muted line (decision 4)
    says why. The "Recent next dates from orders" table gains "Where it came from" and "Status" (decision 12).
14. **Alerts.** On the Alerts list and the case's Alerts tab, a `next_date_review` alert whose case is visible
    (`case_visible`) gets a second link "Answer it" to `/alerts/next-dates?q=<case id>` (a navigation; the list asks
    the API). Marking read on following it works as for the case link (portal-files-alerts decision 9). The hearing
    calendar is unchanged (its source label "Next date" already covers dates from orders).
15. **Timeline lines** (`lib/timeline.ts` `DETAIL`, payload keys only, never a note): `next_date_extracted` → "Order
    <order_no> of <order_date> · <next_date or 'no date read'> · to be confirmed" (the last part only when `review`
    and a date); `next_date_reviewed` → "Confirmed" / "Not accepted" · <next_date> · <office_code>;
    `next_date_entered` → <next_date> · <office_code> · <ref_no>. Labels of the event types come from the API, as
    today.
16. **After every action** (confirm, reject, enter): `useWorkflowRefresh(caseRef)` (the case, `["alerts"]` with the
    calendar and counts, `["files"]`, `["dashboard"]`) plus `["next-dates"]` (the review list). Query keys:
    `["next-dates","review",filters,offset]`, the case's `[...caseKey(ref),"next-dates",offset]` and
    `[...caseKey(ref),"next-dates","review"]`. No polling; refetch on focus stays on.
17. **Errors in words** (`NEXT_DATE_ERRORS` over the shared texts): `bad_field` decision 9's text; `not_pending` "This
    date has already been answered or replaced by a newer order. The list has been read again." (and the list and
    case are re-read); `already_entered` "This date is already entered for the case."; `not_owned` "The case is no
    longer claimed by a department, so its next dates cannot be changed."; `not_working_on_case` and `forbidden` the
    shared texts; 404 the shared neutral text.
18. **Nothing reaches SourceTrace** and the portal writes only through the three existing calls. No case note, upload
    or internal document is involved; the note on a next date is a short public remark, as the hint says.
19. **Look, language and checks as before.** CSS Modules and the shell tokens; the UI kit (no new kit component);
    WCAG 2.1 AA (the list is a table with headers; dialogs trap focus and return it; status words carry the meaning,
    never colour alone; `<details>` for the court's sentence; buttons name the case for screen readers, e.g.
    "Confirm next date of WP(C)/123/2026"); strings in `messages.ts` (`T.nd`); IST dates; no new npm dependency.
    `portal_smoke.py` discovers the one new page.

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): the review list
as a tab of Alerts & calendar (1); the one API addition `workflow.next_dates` (3); a confirmation dialog before
Confirm (5); a separate "Next date from orders" card beside the court's "Next hearing" (8); the dashboard count being
the department's total while the list shows the reader's own items (13); "about 18 months" as the wording of the
upper bound (9); the wording table (12).

## Data
No table, column, constraint, reference code, `Permission` or setting is added; no migration; `docs/schema/schema.md`
is unchanged. `workflow.next_dates` is computed on read from existing rows (`case_ownership`, `user_memberships`,
`custody`, the working bases of `visibility`). The portal stores nothing new.

## Services
Backend (Python), read-only:
- `services/workflow_actions.py`: `available()` adds `next_dates = owned and acting_member_for_case(session, user,
  case, Permission.NEXT_DATES_REVIEW) is not None`; the module docstring names it.
- `api/schemas.py`: `CaseWorkflowActionsOut.next_dates: bool`. `frontend/openapi.json` and
  `src/lib/api/schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/lib/routes.ts`: `ALERTS_TABS` gains `{key: "next-dates", label: "Next dates to confirm", href:
  "/alerts/next-dates", functions: ["next_dates.review"]}`; `CRUMB_PATHS["/alerts/next-dates"]`.
- `src/lib/filters.ts`: `ListKey` gains `next_dates`; `LIST_FILTERS.next_dates = {fields: [...ALL_CASE, "owner"],
  fixed: ["kind"]}`.
- `src/lib/nextDates.ts` (new, pure): `sourceLabel(code)`, `statusLabel(code, {canAct})`, `ruleHint(rule)`,
  `readingLabel(order)` (decision 11), `originLine(row)` (decision 8's "Fixed in the order of …" / "Entered by …"),
  `isScannedItem(item)` (an *enter* item with neither `rule` nor `phrase`).
- `src/lib/messages.ts`: `T.nd` (labels, hints, notices, empty texts, dialog texts), `NEXT_DATE_ERRORS`.
- `src/lib/api/types.ts`: `NextDate`, `CaseNextDate`, `CaseNextDateList`, `NextDateReviewItem`,
  `NextDateReviewList`, `NextDateRejectOut` aliases.
- `src/lib/timeline.ts`: the three `DETAIL` entries (decision 15).
- `src/components/nextdates/*` (new): `ReviewList` (the tab: `FilterBar`, rows, paging), `ReviewItem` (one row, used
  by the list and the case panel), `ConfirmNextDate`, `RejectNextDate`, `EnterNextDate` (dialogs, `useAction`,
  `NEXT_DATE_ERRORS`), `useNextDateRefresh(caseRef)` (decision 16), `nextdates.module.css`.
- Changed: `components/case/Overview.tsx` (the "Next date from orders" card and the Latest order line),
  `components/case/Orders.tsx` (the column), `components/case/Hearings.tsx` (the "Next dates" section),
  `components/dashboard/Dashboard.tsx` (decision 13), `components/alerts/AlertList.tsx` and
  `components/workflow/CaseAlerts.tsx` (the "Answer it" link), `components/alerts/AlertsFrame.tsx` (third tab).
- Page: `src/app/(portal)/alerts/next-dates/page.tsx`.

Audit and events: the portal writes none of its own. The actions are the existing calls, audited by the API
(`next_date.confirm`, `next_date.reject`, `next_date.enter`) with the events `next_date_reviewed` /
`next_date_entered`. Reading pages writes no audit row.

## API
Changed (FastAPI):

| Method, path | Function required (`Permission`) | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /cases/{ref}` (changed) | `cases.view_scope` or `cases.view_all` (unchanged) | — | `workflow` gains `next_dates: bool` | unchanged (404 for an invisible case); the flag per decision 3 |

Used as they are (from `feature/next-date-extraction`): `GET /next-dates/review` (`next_dates.review`; working basis on
a claimed case), `POST /next-dates/{id}/confirm` and `POST /next-dates/{id}/reject` (`next_dates.review`; working
basis; claimed), `POST /cases/{ref}/next-dates` (`next_dates.review`; working basis; claimed), `GET
/cases/{ref}/next-dates` (`cases.view_scope` or `cases.view_all`; `require_visible`), `GET /cases/{ref}/orders`
(read), `GET /dashboard/department` (as today), `GET /alerts` (read), `GET /reference/labels` (signed in), the order
file `GET /cases/{ref}/orders/{id}/file` (`documents.view`). Web server: no new route; the relay is unchanged.

## Jobs
None. Readings come from the existing `aslms.next_dates_read` (every 5 minutes, row 26); review alerts from the event
scan; hearing alerts from the hourly date sweep.

## Tests
Backend (pytest):
- `db/test_workflow_actions.py` (added): `test_next_dates_flag_true_for_owner_admin`;
  `test_next_dates_flag_false_on_unclaimed_case`; `test_next_dates_flag_false_for_state_reader_with_function` (no
  working basis); `test_next_dates_flag_false_without_function` (function denied by a per-user override);
  `test_next_dates_flag_matches_enter_outcome` (the flag is true exactly when `POST /cases/{ref}/next-dates`
  succeeds, over the four cases above).
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, `fakeApi`):
- `lib/nextDates.test.ts`: every source and status label; `statusLabel("pending")` differs with and without the
  action; rule hints for the known rules, none for an unknown rule; `readingLabel` for the six statuses; `originLine`
  for a fixed, a confirmed counted and an entered date; `isScannedItem`.
- `lib/routes.test.ts` (added): the "Next dates to confirm" tab only with `next_dates.review`; its breadcrumb.
- `lib/timeline.test.ts` (added): the three event lines; no line prints a note.
- `components/nextdates/nextdates.test.tsx`: the list calls `/next-dates/review` with `kind` omitted by default,
  `kind=confirm` / `enter` from "Show", and the shared filters; rows render confirm and enter items (scanned wording
  when neither rule nor phrase); "View order" only with `document_id` and `documents.view`; no confidence, rule code
  or alert reference in the page; Confirm posts `{}` after the dialog and shows the notice; Not correct posts only the
  filled fields and shows the notice with `entered`; Enter date posts `order` = the item id; the date fields have
  `min` = today (IST); `bad_field`, `not_pending` (list re-read), `already_entered`, `not_owned` texts; after each
  action the list, the case and the dashboard queries are invalidated; the department shown only with more than one
  department membership; empty texts.
- `components/case/case.test.tsx` (added): the "Next date from orders" card with a fixed, a confirmed and an entered
  date and with none; "Waiting for you" requests `/next-dates/review?q=<case id>` only when `next_dates_to_review` >
  0; "Enter next date" only with `workflow.next_dates`; the Latest order line; the Orders tab column for the six
  statuses with "What the order says"; the Hearings tab "Next dates" section with the "Used for the calendar" badge
  on the `effective` row and the `NXT` reference.
- `components/dashboard/dashboard.test.tsx` (changed): the count is a link with `owner=<code>` when above zero, plain
  text at zero, absent when null; the recent table's two new columns.
- `components/alerts/alerts.test.tsx` (added): "Answer it" on a visible `next_date_review` alert only; the third tab.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`, `docker compose up -d --wait --no-deps api web`; `python
   backend/tools/portal_smoke.py` → every page 200 including `/alerts/next-dates`, and no error line in the `web` log.
4. Without a session: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/next-dates/review` →
   401.
5. Signed-in steps (they need the e-mailed sign-in code, so they are run by the owner or the integrator; if not run
   before merge they are recorded in the cycle report and handed over, as in rows 12, 50 and 53). Row 26's
   verification step 4 leaves two claimed dev cases, one with a counted period (pending) and one with a written date.
   As that department's admin: the dashboard's "Next dates to confirm" shows the count and opens the list filtered to
   the department; the list shows the period case with the court's sentence and "Suggested from the order — please
   confirm"; Confirm → the row leaves the list, the case page's card shows the date "confirmed by <you>", the hearing
   calendar lists it, the case timeline shows "Confirmed". On the other case, "Enter next date" with a date and a
   short note → the card shows "Entered by <you>", the Hearings tab's "Next dates" lists it with its `NXT` reference
   and "Used for the calendar". The Orders tab shows a reading for each read order. As a State-wide reader of the same
   case: no "Enter next date" button, no "Waiting for you" panel, the card and the history visible.
6. In `psql`: one `audit_log` row each for `next_date.confirm` and `next_date.enter`, none from opening the pages.

## Open questions
None.
