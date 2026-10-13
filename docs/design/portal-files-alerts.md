# Design: Portal — Files screens, Alerts & calendar screens, their navigation, the bell and the dashboard links

```
slug: portal-files-alerts
status: approved
author: architect
date: 2026-10-13
approved_by: owner (nayanlhuzuri) on 2026-10-13
```

## Context
Backlog row 55, split out of row 13 by the owner at approval (13 Oct 2026): "The Files screens (`/files/mine`,
`/files/offices`, `/files/department` with the tracking summary, `/files/sent`) and the Alerts & calendar screens
(`/alerts` with filters and acknowledge / done, the hearing calendar `/alerts/calendar` month grid and agenda), their
navigation entries, the header bell link and the dashboard links; design as decisions 3, 16, 17 and 18 of
docs/design/portal-workflow.md; after it, a move that hides the case goes to `/files/sent` (decision 6)."

The plan: §5.5 (Alerts and Hearing Calendar) "Calendar of upcoming hearings for the user's cases, with critical
(within 48 hours) and this-week highlights"; "alerts go to the current custody holder". §5.7 (Custody and Workflow)
"which office and officer currently hold it and what action is pending, similar to file movement in eOffice"; links
to dashboard and "reports (pending actions by office)". §5.12 notifications in-app. The owner's custody rules of
7 Oct 2026 (custody-workflow) bind: sending replaces hand-over, tracking is the grantable `custody.track`, ownership
never moves with custody. custody-workflow decision 24 defined the eOffice views (`/custody/held` with scopes
`me | office | owned`, `/custody/sent`, `/custody/summary`) this item draws.

This note keeps decisions 3, 16, 17 and 18 of portal-workflow (approved) and makes them buildable against the code
as it stands after row 13 (merged 13 Oct 2026). It changes nothing in portal-workflow's built parts except
decision 6's destination, as the approval said.

In place (used, not rebuilt):
- API: `GET /alerts` (`status`, `kind`, `severity`, `unread`, `case`, `limit`, `offset`; newest first),
  `GET /alerts/counts` (`unread`, `open.{critical,high,normal}`, open and acknowledged only),
  `POST /alerts/read` (`alert_ids` or `all`), `POST /alerts/{alr}/acknowledge | done` (with `can_act` on every item,
  portal-workflow 20d), `ticket_ref` on a case-less admin-ticket alert, `GET /calendar` (`from`, `to` at most 62
  days, default today … +7; `office` for State-wide readers, who otherwise get an empty list; items carry `critical`
  and `this_week`; `source` is `causelist`, `next_date` or `current_status`), `GET /custody/held`
  (`scope`, `overdue`, `holder_department`; due date then since), `GET /custody/sent` (with `visible`, 20g),
  `GET /custody/summary` (per tracked department), `GET /reference/labels` (with `alert_kinds`, 20f),
  `GET /custody/recipients` (the active departments).
- Portal: `routes.ts` (the unbuilt "Alerts & calendar" entry, `CRUMBS`), the shell (`AlertBell` linking to
  `/#alerts`, `Breadcrumb` by segment), `Dashboard.tsx` (personal block with the "Files I hold" tile and the
  "My alerts" list), `AlertActions` and `SeverityBadge` (row 13), `FlashNotice` and `src/lib/flash.ts`, `CaseLink`
  with its `visible` flag, `Tabs`, `Pagination`, `useDepartments()`, `src/lib/workflow.ts` (`todayIst`), the frame
  pattern of `DataFrame` / `DataIndex`, `lib/params.ts` query-string helpers.

Not covered: the reports screen with "pending actions by office" (row 39); notification preferences (on My profile
already); next dates read from orders (rows 26, 37); SMS (rows 27, 34); the Compose verification of row 13 (row 56).

## Decisions
1. **Routes.** `/files` opens the first tab the login may read (as `/data`), tabs `/files/mine` ("With me"),
   `/files/offices` ("My offices"), `/files/department` ("Department files"), `/files/sent` ("Sent"). `/alerts` is
   the alert list and `/alerts/calendar` the hearing calendar, as two tabs of one frame ("Alerts", "Hearing
   calendar"). Filters and paging live in the query string (row 12's rule), so a link or the back button restores
   the view. Alternative: one page with client-side tabs (no deep links; the bell and the dashboard need targets).
2. **Navigation** (portal-workflow decision 3). "Alerts & calendar" gets `built: true` (shown with `cases.view_scope`
   or `cases.view_all`, as declared). A new entry "Files" after "Search", shown with `cases.view_scope` (anyone may
   be sent a file, standing counsel included; State-wide types, which hold `cases.view_scope` by default, see empty
   lists because they cannot be targets). The sidebar's existing section rule keeps each entry current across its
   tabs. Alternative: Files under the Case inbox (the inbox is per department and ownership-centred; files follow
   the person).
3. **Breadcrumbs.** `Breadcrumb` looks up a full-path label first (a new `CRUMB_PATHS`), then the segment label:
   `/files` "Files", `/files/mine` "With me", `/files/offices` "My offices" (the segment `offices` already means
   Administration → Offices), `/files/department` "Department files", `/files/sent` "Sent", `/alerts` "Alerts &
   calendar" (the segment `alerts` stays "Alerts" for the case tab), `/alerts/calendar` "Hearing calendar".
   Alternative: renaming the segments (`/files/my-offices`) to dodge the clash (the backlog fixes the paths).
4. **The bell and the dashboard links** (decision 3). The header bell links to `/alerts` instead of `/#alerts`, its
   count unchanged (`unread` of `/alerts/counts`, re-read every two minutes) and now read through a shared
   `useAlertCounts()` hook (same query key `["alerts","counts"]`, so the bell and the list header share one fetch).
   On the dashboard's personal block, the "My alerts" heading links to `/alerts` and the "Files I hold" tile links
   to `/files/mine` (`Tile` gains an optional `href`; the whole tile is one link whose name is label and value). The
   `id="alerts"` anchor stays so old links still land. No other dashboard block changes.
5. **What a page offers comes from the server** (row 12 decision 8, portal-workflow decision 4). Acknowledge / Done
   show by each item's `can_act` and status (`AlertActions` reused); a case is a link only when the API says the
   caller can open it (`SentItemOut.visible`; for alerts the new `case_visible`, decision 6); the Department files
   tab and the summary show only for a login that tracks a department (decision 12). The API still decides every
   call.
6. **One read-only API addition: `case_visible` on alert items.** portal-workflow decision 16 shows "for an ownership
   notice about a case the reader can no longer open, the case number as text", but nothing in the API says which
   alerts those are: `notification_visible_condition` lets a named recipient read `case_taken_over`,
   `transfer_requested`, `transfer_decided` (ownership) and `file_recalled` (workflow) notices about a case they no
   longer see. `AlertItemOut` (and so `AlertDetailOut`) and the dashboard's `DashboardAlertOut` gain
   `case_visible: bool` — whether the caller can open the alert's case now; `false` when the alert has no case. It is
   computed by one `visible_case_condition` query over the page's case ids (the method of 20g), never by the
   browser from kinds and events. No schema change, nothing written. Alternatives: the portal guessing from
   `kind` + `data.event` (the rule written twice, and it would drift when a named event is added); linking anyway
   and letting the case page show its neutral 404 (decision 18 of portal-workflow forbids a link to a 404).
7. **Alerts list** (`/alerts`, portal-workflow decision 16): the caller's own alerts (`GET /alerts`), newest first
   as the API orders them, paged by 50. Above the list, the counts of `/alerts/counts`: "Unread n" and open by
   severity (critical, high, normal). Filters, each a query-string key sent as the API's parameter:
   - status (`status`): "Open and acknowledged" (default, the parameter omitted), "Open", "Acknowledged", "Done",
     "Expired", "All";
   - kind (`kind`): "All kinds" or one of `alert_kinds` from `/reference/labels`;
   - severity (`severity`): all, critical, high, normal;
   - "Unread only" (`unread=true`).
   Changing a filter resets the offset. Each row: `SeverityBadge`, kind label, status, `ref_no` (monospace), title,
   body, due (IST), the subject link (decision 8), notified at, read at (or a "New" badge, with a visually hidden
   "unread"), acknowledged by and when; then Mark read (only when unread) and Acknowledge / Done (`AlertActions`).
   Empty list: "No alerts match these filters." (or "You have no open alerts." with the default filters).
8. **The subject of an alert row.** A case alert with `case_visible` true: the case number as a link to the case
   page. With `case_visible` false: the case number as monospace text (`CaseLink visible={false}`) and the line "You
   can no longer open this case." An admin-ticket alert (`case` null, `ticket_ref` set): a link to
   `/admin/tickets/<refPath(ticket_ref)>` ("Ticket …"). Anything else: no link. The link is a small `AlertLink`
   that marks the row read first (decision 9), then navigates.
9. **Reading** (portal-workflow decision 16, confirmed). Opening `/alerts` marks nothing, so the bell's count never
   drops unseen. A row is marked read by: "Mark read" on the row (`POST /alerts/read {alert_ids:[id]}`); "Mark all
   read" above the list (`{all: true}`, shown while `unread` > 0, no confirmation: it changes nothing but the read
   marks); following the row's subject link (marked first; if the mark fails, the navigation still happens — reading
   is a convenience, never a gate). After any mark, acknowledge or done: `["alerts"]` (list, counts, bell) and
   `["dashboard"]` are invalidated, and for a case alert the case's queries (its Alerts tab).
10. **Hearing calendar** (`/alerts/calendar`, portal-workflow decision 17; plan §5.5): `GET /calendar`, two views in
    the query string:
    - "Next 7 days" (default, no parameter): `GET /calendar` without `from` / `to` (the API's default range); the
      agenda only;
    - a month (`?month=YYYY-MM`; "This month", "Previous month", "Next month" buttons): `from` = the first day, `to`
      = the last day of that month (at most 30 days apart, under the API's 62; a range longer than 62 days is never
      requested); the month grid, then the agenda. An unparseable `month` falls back to the default view.
    The month grid is a `<table>` (caption the month and year; weekday column headers Monday to Sunday — courts sit
    on weekdays, so the weekend closes the row); days outside the month are empty cells; each day shows its number,
    the count of hearings and a "critical" mark when any of that day's items has the API's `critical`; today (IST,
    `todayIst()`) is marked; a day with hearings links to its agenda anchor (`#d-YYYY-MM-DD`) with an accessible
    name ("14 October: 3 hearings, 1 within 48 hours"). The agenda (the accessible version) groups items by date
    ascending, each with the case link, court, item, purpose, source label ("Cause list" for `causelist`, "Next
    date" for `next_date`, "Court records" for `current_status`, the code for anything else) and the API's badges
    "Within 48 h" (`critical`) and "This week" (`this_week`) — never computed in the browser. Empty range: "No
    hearings in this period." Alternative: a calendar library (a dependency and CSP surface for at most 42 cells).
11. **State-wide readers on the calendar.** A login holding `cases.view_all` (the super admin holds every function)
    chooses a department first (`?department=CODE`, from `useDepartments()`); until then the page says "Choose a
    department to see its hearings." and requests nothing (the API would answer an empty list). The request then
    passes `office=CODE` and shows that department's owned cases' hearings. Others never send `office` (the API
    answers 403). This follows `visibility.state_wide` (any membership with `cases.view_all` or super admin).
12. **Files** (`/files`, portal-workflow decision 18; the eOffice view of custody-workflow decision 24). A frame with
    up to four tabs, the `FlashNotice` above them (decision 14):
    - "With me" (`/custody/held?scope=me`): case link, pending action label, since, due date with "Overdue by n
      days" (the card's `overdue` / `overdue_days`), sent by (name, designation, office code), remark; filter
      "Overdue only" (`overdue=true`);
    - "My offices" (`scope=office`): the same plus the holder office (code, name) and officer (name, designation);
    - "Department files" (`scope=owned`): shown only when a membership in `/me.memberships` has a `department_code`
      and holds `custody.track` in its `functions` (the API's `_tracked_departments` rule: the super admin's
      State membership has no department and would get 403). At the top, the summary of `GET /custody/summary` per
      tracked department: tiles held, due soon, overdue; then "By holder department" and "By holder" (office code,
      officer, designation) tables, counts only. Below, the list as "My offices" with the filters holder department
      (`holder_department`, options from `useDepartments()`) and "Overdue only". A person tracking two departments
      sees both in one list (the API has no owner filter); the summary separates them;
    - "Sent" (`/custody/sent`): the legs the caller wrote, newest first: when (the leg's started at), the case
      (a link only when `visible`; otherwise text — a case the sender no longer sees is never a link to a 404),
      reason label (sent / recalled), the holder sent to (officer, designation, office), pending action label, due
      date, the caller's own remark.
    Lists keep the API's order and are paged by 50 (`offset` in the query string). A remark is shown clamped to two
    lines with "Show more" (the full text is in the page, so screen readers read it whole). There are no action
    buttons on these lists: sending and recalling happen on the case page, where the card's flags are current.
    Empty lists say what the tab holds ("No file is with you." / "No file is with your offices." / "No file of your
    department matches." / "You have not sent or recalled a file."). Alternative: Send and Recall on the list rows
    (the flags would be stale and the dialogs need the case's drafts count).
13. **Tabs and access to the frames.** The Files tabs "With me", "My offices", "Sent" show with `cases.view_scope`
    or `cases.view_all` (the API's gate); "Department files" as decision 12. The Alerts frame's tabs show to case
    readers; the "Alerts" tab is current only on `/alerts` itself (not on `/alerts/calendar`). A login with no
    readable tab sees the neutral not-found text, as `DataFrame` does.
14. **After a move that hides the case** (portal-workflow decision 6, as the approval said). When the send or recall
    answer's `card` is `null`, the portal stores the same one-time notice ("File sent to <name>. You no longer hold
    this case." plus the finalised notes) with `setFlash`, goes to `/files/sent` instead of the dashboard, and keeps
    row 57's fix (cancel the case's queries and invalidate them without refetching; invalidate `["files"]`,
    `["alerts"]`, `["dashboard"]`). The Files frame shows the notice once; the just-written leg is the first row of
    "Sent". The dashboard keeps its `FlashNotice` (harmless when empty).
15. **Freshness.** Query keys: `["files", scope, filters, offset]`, `["files","sent",offset]`,
    `["files","summary"]`, `["alerts","list",filters]`, `["alerts","counts"]`, `["alerts","calendar",range,
    department]`. Every workflow write of row 13 already invalidates `["files"]`, `["alerts"]` and `["dashboard"]`
    (`useWorkflowRefresh`), so these screens re-read after any send, recall, note or alert action. No polling beyond
    the bell's two minutes; refetch on window focus stays on.
16. **Errors in words.** Each list shows `ErrorBanner` with a retry; `bad_range` (calendar) and `bad_request`
    (an unknown filter value from a hand-edited URL) show the server's message; 403 `forbidden` on the Department
    files tab (tracking withdrawn meanwhile) says "Tracking files of this department is not among your functions."
    `ALERT_ERRORS` (row 13) covers acknowledge / done.
17. **Nothing reaches SourceTrace** and nothing is written by the portal except the existing calls (read marks,
    acknowledge, done). No upload or note is offered on these screens.
18. **Look, language and checks as before.** CSS Modules and the shell tokens, the UI kit (no new component beyond
    `Tile`'s `href`), WCAG 2.1 AA (the grid is a table with headers, the agenda is the accessible list, badges carry
    text, focus visible), strings in `messages.ts` (`T.files`, `T.alerts`, `T.cal`), IST dates, monospace references,
    no new npm dependency. `portal_smoke.py` discovers the seven new pages.

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): the
`case_visible` API addition (6); Monday-first weeks and "Next 7 days" showing the agenda without a grid (10); the
Department files tab keyed to a tracked department membership (12); "Mark all read" without a confirmation (9).

## Data
No table, column, constraint, reference code, `Permission` or setting is added; no migration; `docs/schema/schema.md`
is unchanged. `case_visible` is computed on read from existing rows (`cases`, `case_ownership`, `custody`,
`user_memberships` through `visibility.visible_case_condition`). The portal stores only the one-time notice in
`sessionStorage` (already built, nothing secret).

## Services
Backend (Python), read-only:
- `services/alerts.py`: `alert_item(…, case_visible: bool = False)` adds `case_visible`. A helper
  `_visible_case_ids(session, user, case_ids) -> set[uuid.UUID]` runs one
  `select(Case.id).where(Case.id.in_(ids), visibility.visible_case_condition(session, user))` (empty set without
  ids). `list_for_user` computes it once for the page; `alerts_for_case` passes `True` (the case passed
  `require_visible`); `detail_item` computes it for its one case (so `GET /alerts/{alr}` and the acknowledge / done
  answers carry it). No lock, no write, no audit (reading).
- `services/dashboard.py`: the personal block's alert items keep `case_visible` from `list_for_user` (added to the
  copied keys).
- `api/schemas.py`: `AlertItemOut.case_visible: bool`, `DashboardAlertOut.case_visible: bool`.
  `frontend/openapi.json` and `src/lib/api/schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/lib/routes.ts`: NAV `alerts` built; `files` entry after `search` (`cases.view_scope`); `FILES_TABS`,
  `ALERTS_TABS`, `filesTabsFor(me)` (Department files by `tracksDepartment(me)`), `CRUMB_PATHS`.
- `src/lib/can.ts`: `tracksDepartment(me)` — an active membership with a `department_code` holding `custody.track`.
- `src/lib/workflow.ts`: `monthGrid(month: "YYYY-MM") -> (string | null)[][]` (Monday-first weeks of ISO dates,
  `null` outside the month), `monthRange(month) -> {from, to}`, `shiftMonth(month, ±1)`, `parseMonth(value)`.
- `src/lib/messages.ts`: `T.files`, `T.alerts`, `T.cal`, calendar source labels, the empty and error texts of
  decisions 7-16.
- `src/lib/api/hooks.ts`: `useAlertCounts()` (key `["alerts","counts"]`, the two-minute poll for the bell).
- `src/components/ui`: `Tile` takes `href`.
- `src/components/files/*`: `FilesFrame` (tabs, `FlashNotice`), `FilesIndex`, `Held` (prop `scope`), `Sent`,
  `TrackingSummary`, `Remark` (clamped text).
- `src/components/alerts/*`: `AlertsFrame`, `AlertList` (filters, counts header, rows, `AlertLink`, Mark read,
  Mark all read, `AlertActions`), `Calendar` (`MonthGrid`, `Agenda`, department picker).
- Changed: `shell/PortalShell.tsx` (`AlertBell` → `/alerts`, `useAlertCounts()`; `Breadcrumb` reads `CRUMB_PATHS`),
  `dashboard/Dashboard.tsx` (the heading and tile links; alert items link the case only with `case_visible`),
  `workflow/CustodyDialogs.tsx` (decision 14: `router.push("/files/sent")`).
- Pages: `(portal)/files/{layout,page}.tsx`, `files/mine/page.tsx`, `files/offices/page.tsx`,
  `files/department/page.tsx`, `files/sent/page.tsx`; `(portal)/alerts/{layout,page}.tsx`,
  `alerts/calendar/page.tsx`.

Audit and events: the portal writes none. The actions it offers are existing calls: `POST /alerts/read` (own read
marks, not audited, as built), `alert.acknowledged`, `alert.done` (audited by the API). The API addition writes
nothing.

## API
New or changed (FastAPI):

| Method, path | Function required | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /alerts` (changed) | `cases.view_scope` or `cases.view_all` (unchanged) | unchanged | each item + `case_visible: bool` | unchanged (`notification_visible_condition`); `case_visible` per `visible_case_condition` |
| `GET /alerts/{alr}`, `POST /alerts/{alr}/acknowledge \| done` answers (changed) | read; `alerts.acknowledge` for the POSTs (unchanged) | unchanged | + `case_visible: bool` | unchanged |
| `GET /cases/{ref}/alerts` (changed) | read (unchanged) | unchanged | each item + `case_visible: true` | unchanged (404 for an invisible case) |
| `GET /dashboard/me` (changed) | as today (`cases.view_scope` or `cases.view_all`) | — | `alerts.items[]` + `case_visible: bool` | unchanged |

Used as they are: `GET /alerts/counts` (read); `POST /alerts/read` (signed in, own rows);
`GET /calendar` (read; `office` needs `cases.view_all`); `GET /custody/held` (read; `scope=owned` needs
`custody.track` in a department membership); `GET /custody/sent` (read); `GET /custody/summary` (`custody.track`);
`GET /custody/recipients` (`cases.view_scope`, the department list); `GET /reference/labels` (signed in).

Web server: no new route; the relay is unchanged.

## Jobs
None. Alerts come from the existing `aslms.alerts_scan_events` (every 5 minutes) and `aslms.alerts_sweep_dates`
(hourly).

## Tests
Backend (pytest, `backend/tests/`, the shared world and `tests/db/alerts_support.py`):
- `db/test_api_alerts.py` (added): `test_list_case_visible_true_for_visible_case`;
  `test_recalled_holder_notice_case_visible_false` (the officer a file was recalled from lists the `file_recalled`
  notice with `case_visible` false and the case summary present); `test_taken_over_notice_case_visible_false`
  (the department a case was taken from); `test_admin_ticket_alert_case_visible_false` (no case);
  `test_case_tab_items_case_visible_true`; `test_detail_and_acknowledge_answer_carry_case_visible`;
  `test_case_visible_one_query_per_page` (the statement count does not grow with the page size).
- `db/test_api_dashboard.py` (added): `test_personal_alert_items_carry_case_visible`.
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, the `fakeApi` helper):
- `lib/routes.test.ts` (added): Alerts & calendar shown for case readers; Files shown with `cases.view_scope` and
  after Search; Department files tab only with a department membership holding `custody.track` (not for a super
  admin's State membership); `CRUMB_PATHS` labels `/files/offices` "My offices" and `/alerts` "Alerts & calendar"
  while `/cases/x/alerts` stays "Alerts".
- `lib/workflow.test.ts` (added): `monthGrid` for a month starting on a Monday, on a Sunday, and February in a leap
  year (weeks of seven, `null` padding); `monthRange` first and last day; `shiftMonth` across a year;
  `parseMonth` refuses `2026-13` and junk.
- `components/files/files.test.tsx` (new): each tab calls its endpoint and scope; "Overdue only" and holder
  department are sent as `overdue=true` / `holder_department`; Department files and the summary only with a
  tracked department; the summary renders per department; Sent rows link only `visible` cases and show the others
  as text; no action buttons on any list; a remark longer than two lines has "Show more"; `/files` goes to the first
  tab; the flash notice shows once on the frame.
- `components/alerts/alerts.test.tsx` (new): filters go to the query string and to the API as parameters (status
  omitted by default, `all`, one state; kind from `alert_kinds`; severity; `unread=true`); the counts header; Mark
  read posts `{alert_ids:[id]}` and shows only on unread rows; Mark all read posts `{all:true}` and shows only while
  unread > 0; following a case link marks it read first and navigates even when the mark fails; opening the list
  posts nothing; a `case_visible: false` row shows text and no link; an admin-ticket row links to the ticket;
  Acknowledge / Done only with `can_act` and by status; after an action the list and counts are re-read.
- `components/alerts/calendar.test.tsx` (new): the default view requests `/calendar` without `from` / `to` and shows
  no grid; a month view requests that month's first and last day, never more than 62 days; previous / next month
  change the query string; day cells show counts and the critical mark from the API's flags; the agenda shows
  "Within 48 h" / "This week" only from the flags and the source labels; a `cases.view_all` login sees the
  department picker and no request until a department is chosen, then `office=CODE`; an unparseable `month` falls
  back to the default view.
- `components/shell/shell.test.tsx` (changed): the bell links to `/alerts`; the breadcrumb of `/files/offices`.
- `components/dashboard/dashboard.test.tsx` (changed): "My alerts" heading links to `/alerts`; the "Files I hold"
  tile links to `/files/mine`; an alert item with `case_visible: false` is text.
- `components/workflow/workflow.test.tsx` (changed): a `card: null` answer navigates to `/files/sent` (was `/`)
  with the notice and the finalised notes; the case queries are cancelled and not refetched (row 57's regression
  test kept).

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green with the new
   tests; `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the
   commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`, then `docker compose up -d --wait --no-deps api web` (no migration; the worker
   and scheduler running the historical load are not recreated); `python backend/tools/portal_smoke.py` → every page
   200 including the seven new ones (`/files`, `/files/mine`, `/files/offices`, `/files/department`, `/files/sent`,
   `/alerts`, `/alerts/calendar`), and no error line in the `web` log.
4. Without a session: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/alerts` → 401.
5. Signed-in steps (they need the e-mailed sign-in code, so they are run by the owner or the integrator; if not run
   before merge they are recorded in the cycle report and handed over, as in rows 12, 50 and 53): as a department
   admin, the sidebar shows "Files" and "Alerts & calendar"; the bell opens `/alerts` and its count equals "Unread"
   in the counts header; opening the list leaves the count unchanged; "Mark read" on one row lowers it by one.
   On a claimed case, Send file to an officer of another department → the portal lands on Files → Sent with the
   notice, the new leg first, the case as text if it is no longer visible; that officer's Files → With me lists it.
   As the department admin, Recall it → `docker compose exec api aslms alerts run --events`, then the officer's
   `/alerts` lists the "recalled" notice with the case number as text (no link) and `GET /alerts` shows
   `case_visible: false` for it. Files → Department files shows the summary, and its figures equal
   `GET /custody/summary` for the department.
6. `/alerts/calendar`: the next 7 days' hearings match `GET /calendar` item for item, with the same critical marks;
   "This month" shows the grid with counts equal to the agenda's groups. As the auditor: the department picker
   appears and nothing is requested until a department is chosen.
7. In `psql`: no `audit_log` row was written by opening any of these pages (reading is never audited); one
   `alert.acknowledged` row for each Acknowledge pressed.

## Open questions
None.

## Deviations
Recorded by the developer during the build (13 Oct 2026); none changes a rule of the plan, a business rule or an API
field beyond the design.
1. **Decision 14, Recall.** Only Send can answer `card: null`: a recall brings the file to the recaller, who then
   holds it, so the Recall dialog keeps its in-page notice and only Send goes to `/files/sent`.
2. **A Files tab the login may not open.** Typing `/files/department` without a tracked department shows the neutral
   not-found text (as for a login with no Files tab at all) and requests nothing; the 403 text of decision 16 still
   shows when tracking is withdrawn while `/me` is cached.
3. **"Longer than two lines" (decision 12).** The remark is clamped by CSS (`line-clamp: 2`); "Show more" is offered
   when the text has more than 140 characters or a third line, because a browser test cannot measure rendered lines.
   The full text is always in the page.
4. **`bad_range` on the calendar (decision 16).** The shared `bad_range` text belongs to the load console, so the
   calendar passes the server's own message as its context text.
5. **Small helpers.** `useFilters` (inbox) is reused for every query-string filter; `ALERT_POLL_MS` moved to
   `lib/api/hooks.ts` with `useAlertCounts()`; `crumbLabel(path)` in `routes.ts` reads `CRUMB_PATHS` then `CRUMBS`;
   `monthOf()` joins the calendar helpers in `lib/workflow.ts`; `Tile` with `href` gets a `tileLink` style.
