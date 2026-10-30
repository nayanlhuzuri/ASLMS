# Design: The Case Inbox in four tabs (With Me, My Cases, Sent by Me, Department), and the case page's More menu

```
slug: case-inbox-simplify
status: approved
author: architect
date: 2026-10-29
approved_by: owner on 2026-10-29
```

## Context
The owner said on 29 Oct 2026 that the Case Inbox's six tabs are confusing: "this seems very confusing for a user";
"do this change as the current one seems very confusing". Backlog row 206. The tabs are Working On, Sent by Me,
Claimed by Me, Disposed, Department Cases and Pending Action (row 152, `docs/design/case-inbox-merge.md`). Their rules
overlap:
- a case allotted to me and claimed by me is in Working On and in Claimed by Me;
- a case with me after disposal is in Working On and in Disposed;
- Department Cases and Pending Action both list the department's cases, under different functions.

The owner approved this four-tab shape, then the decisions of this note, on 29 Oct 2026:

| Tab | Answers | Replaces | Who sees it |
|---|---|---|---|
| **With Me** | What do I have to do now? Every case with me, whatever the court status, most urgent due date first, with the action asked and who sent it. The count is on the tab. | Working On's "Show: With Me / With My Offices" | every case reader |
| **My Cases** | Which cases am I connected to? Every case assigned to me or to a unit under my membership, claimed by me or through a transfer I accepted, or with me. Each row has a badge saying why. Active and court-disposed cases are listed together, disposed after active, with no status switch. | Working On, Claimed by Me, Disposed | holders of `cases.view_scope` |
| **Sent by Me** | What did I send that is still out? Overdue first, with Show Earlier for the full history. | Sent by Me (today it shows everything) | every case reader |
| **Department** | The department's cases, active and court-disposed together with disposed after active and no status switch, with the quick filters Overdue and With Another Office. | Department Cases, Pending Action | heads, claimers, trackers and State-wide readers (today's rules for both tabs) |

**There is no Disposed switch or tab anywhere in this row** (owner, 29 Oct 2026).
- In the department's terms a case is **Open** or **Closed**. A court-disposed case is still open until an officer
  closes it.
- Closed arrives only with **row 207 `close-case`**, which follows this row with its own design and migration.
- Until then, a disposed row is told apart by the existing **Disposed** badge: `HearingDate` already reads "Disposed"
  for a disposed case.
- Row 207 adds an Open / Closed switch to My Cases and Department, and takes a closed case out of With Me.

**Row 207 `close-case`, recorded here so this row leaves room for it** (owner's rules, 29 Oct 2026; **row 206 builds
none of it**):
- **The function.** Close Case is a new grantable function. By default it belongs to department heads and department
  officers.
- **Who may close.**
  - The officer the file is with may close the case.
  - The department head may close it.
  - The head also closes a file that sits with the department, or with one of its units, with no named officer.
- **Which cases.** Only claimed cases, and only when the court's status is disposed.
- **Closing itself.**
  - A remark is required. It is saved as an append-only note, with an audit row and a timeline event.
  - Closing ends the file's movement and clears the pending action.
- **Reopening.** There is no manual reopen. The case reopens only when the court's status changes from disposed, with
  an alert to the department.

The owner also added a small portal fix to the same build (29 Oct 2026, section E). On the case page, "More" in the tab
bar opens its menu inside the bar, so only the first item shows and the button's focus outline is cut off.

**What is in place (read for this note).**
- `frontend/src/lib/routes.ts`: `INBOX_TABS`, `inboxTabsFor`, `OLD_FILES_REDIRECTS`, `OLD_CASES_REDIRECTS`,
  `OLD_INBOX_REDIRECTS` and `CASES_LIST_SEGMENTS`.
- `frontend/src/components/inbox/`:
  - `InboxFrame.tsx`: the tabs, the counts and the `InboxIndex` redirect;
  - `WorkingOn.tsx` and `MyCases.tsx`: the `/inbox/mine` lists;
  - `DepartmentCases.tsx`: `/inbox/claimed` on Layout B, with an Active / Disposed `SegmentedSwitch` and the `holder`
    and `action` selects under More Filters;
  - `Redirects.tsx`: `Redirect`, `redirectTarget` and `ClaimedRedirect`.
- `frontend/src/components/files/`: `Held.tsx` (scopes `me`, `office` and `owned`), `Sent.tsx` and
  `TrackingSummary.tsx`.
- **`GET /inbox/mine`** (`services/my_cases.py`):
  - views `working`, `files`, `claimed` and `disposed`;
  - every row already carries `reasons`, a list drawn from `allotted`, `file` and `claimed`;
  - no view gives all three sets whatever the status;
  - `/inbox/mine/counts` returns all four figures.
- **`GET /custody/held`**:
  - `scope=me|office|owned`, `overdue`, `holder_department` and the shared filters;
  - no status rule, so a disposed case with me is listed;
  - ordered by due date, then since;
  - each item carries the custody card, with the remark when `shows_remark` allows it.
- **`GET /custody/sent`**:
  - every leg the caller wrote (`sent` and `recalled`), newest first;
  - `visible`, and `current`, which is null when the caller can no longer open the case (row 135, decision 20);
  - no "still out" filter.
- **`GET /inbox/claimed`**:
  - `case_state=active|disposed|all`; no portal screen sends `all` today;
  - `holder=department|elsewhere` (the file is held outside the department's subtree);
  - `action=overdue|due_week` (the file's due date has passed with an action pending);
  - the shared filters;
  - ordered by next hearing, then claimed-on newest first.

  `/inbox/counts` gives `claimed_active` and `claimed_disposed` per department.
- **Dashboard figures.**
  - The headline "Cases with Me" counts the custody rows held by me on visible cases, whatever the status. A merged case
    never holds custody: `case_dedupe.merge_provisional` refuses a case that has portal records.
  - "Overdue Actions" counts the same rows with an action pending and a due date before today. A due date only exists
    on a send, and a send always names an action (`workflow_common.pending_action`, `check_due`).
- **Links into the tabs.**
  - `Headline.tsx`: `/inbox/working?held=me` and `/inbox/working?overdue=true`.
  - `Blocks.tsx`: `/inbox/working?held=me`, `/inbox/pending` and `/inbox/department?department=…&next_differs=true`.
  - `ReportPage.tsx`: `/inbox/pending`.
  - `CustodyDialogs.tsx` goes to `/inbox/sent` after a send that loses sight of the case.
  - **Alerts and e-mails link only to case pages and tickets** (`alert_rules.py`, `notifications.py`). The digest's
    "in your department's inbox" line has no link and means Case Claim. **No backend link changes.**

**Not covered.**
- Case Claim (Recommended, Unclaimed Pool, Transfers to Us).
- Server-side visibility and the functions.
- The case page itself, apart from section E.
- Closing a case (row 207).
- Sorting on the case lists. That is row 179, approved; decision 21 says how it maps onto the new tabs.

## Decisions

### A. The tabs and what serves them

1. **Four tabs, each its own route, in the owner's order.**

   | Tab | Route | Shows when (display only; the API decides) | Data |
   |---|---|---|---|
   | With Me | `/inbox/with-me` (new) | `cases.view_scope` or `cases.view_all` (the `/custody/held` gate) | `GET /custody/held?scope=me`, or `scope=office` under "With My Offices" |
   | My Cases | `/inbox/my-cases` (new) | `cases.view_scope` | `GET /inbox/mine?view=all` (decision 4) |
   | Sent by Me | `/inbox/sent` (kept) | `cases.view_scope` or `cases.view_all` | `GET /custody/sent?still_out=true`, or without it under Show Earlier |
   | Department | `/inbox/department` (kept) | `cases.view_all`, or a `/inbox/counts` block with `whole_department`, or `tracksDepartment(me)` | `GET /inbox/claimed?case_state=all` (decision 9); the `scope=owned` list for a tracker without whole-department sight (decision 11) |

   - `INBOX_TABS` becomes `with-me`, `mine`, `sent` and `department`. `inboxTabsFor(me, { whole })` follows the table.
   - `/inbox` opens the first tab the login may open (With Me), or `/search` when there is none.
   - A tab the login may not open shows the "not found" empty state, as today.
   - Alternative: new addresses for Sent by Me and Department as well. Refused, because the two addresses already mean
     these lists, and keeping them leaves fewer redirects.
2. **With Me is today's held list, unchanged on the server.**
   - It renders `Held tab="with-me"`, which already does what the owner asked:
     - the API's order puts the due date first, overdue first, then since;
     - the columns show the action asked (`card.pending_action_label`) and From (`cardSender`, the sender);
     - the lead badge reads Overdue, Due soon or New;
     - the side panel shows the full remark under the server's `shows_remark` rule.
   - The "Show" control loses its "All" option. It reads **With Me** (the default, no URL key) and **With My Offices**
     (`held=offices`, `scope=office`). An incoming `held=me` is the default.
   - "Overdue Only" stays (`overdue=true`).
   - **A Next Hearing column with the `HearingDate` badge is added** after Case. Working On had it, and the held items
     already carry `case.next_hearing` and `case.status`. So a disposed case reads "Disposed" there. That makes seven
     columns, which fit at 1280 px as Working On's seven did.
   - Alternative: read `/inbox/mine?view=files`. Refused, because it has no "my offices" scope and its rows carry no
     remark for the panel.
3. **The count on With Me, and the sidebar pill, is `/inbox/mine/counts`.`files`.** That count is "held by me, visible,
   not merged, whatever the status". It equals `GET /custody/held?scope=me` `total` and the dashboard's "Cases with Me"
   figure, and a test pins both equalities.
   - This changes case-inbox-merge decision 10, where the pill was the Working On count. Now the pill counts the work
     waiting on the person. The owner approved this on 29 Oct.
   - My Cases, Sent by Me and Department show no count on the tab. The owner put the count on With Me, and the other
     three are lists to browse, not queues.
   - My Cases shows "n cases", or "n of m cases" when filtered, in its own count line, where m is the new `all` figure.
   - The Pending Action figure (the sum of `held` over `/custody/summary`) leaves the tab strip.
   - Alternative: counts on all four tabs. Refused, because four numbers bring back the noise the owner complained of.
4. **My Cases reads one new view, `view=all`, with no status switch.**
   - The view is `allotted OR file OR claimed`, whatever the court status.
   - **The order puts active cases first, disposed after them** (`Case.status = disposed` sorts last). Inside each
     group it keeps the existing default order: next hearing, then the file's due date, then case number, then id.
   - `/inbox/mine/counts` gains `all`.
   - A disposed row carries the existing Disposed badge through `HearingDate` in the Next Hearing column, on the table
     and on the phone card.
   - **The connection badges come from the existing `reasons`, in this order:**
     - `allotted` reads **Assigned to Me**;
     - `claimed` reads **Claimed by Me**;
     - `file` reads **With Me** (decision 17).

     A row may carry two or three badges. They sit in a "Reason" column after Case, and on phones the card shows them
     under the case.
   - The owner's wording "assigned to me or to a unit under my membership" is exactly the `allotted` set
     (`claimed_conditions(…, whole=False)`), so both read "Assigned to Me".
   - **The other columns:**
     - Stage;
     - Next Hearing (`HearingDate`, which says Disposed for a disposed case);
     - Your Action, filled only when the case is with me;
     - the chevron.

     A row opens the case page, as Claimed by Me and Disposed do today.
   - **The controls:**
     - the quick chip "Hearing This Week";
     - Stage;
     - the shared filters of `LIST_FILTERS.mine`, with Search Words on the first row (row 175).

     There is no `case_state` control, and "Action Overdue" leaves My Cases, because overdue work is With Me's.
   - The `working`, `files`, `claimed` and `disposed` views stay in the API for compatibility. The portal reads only the
     `files` count from them. Row 189's My Work questions read the services, not the views.
   - Row 207 adds an Open / Closed switch here.
   - Alternative: an Active / Disposed switch. Refused by the owner: disposed is a court status, and the department's
     own Open / Closed comes with row 207.
   - Alternative: a reason filter (All / Assigned / Claimed / With Me). Refused, because the owner asked for badges, not
     another control.
5. **A disposed case with me stays in With Me** (owner, 29 Oct 2026). The held list has no status rule, so every case
   with me is listed whatever the court status, with the Disposed badge, and the With Me count includes it.
   - The owner's reason: closing is the officer's responsibility, and the case leaves With Me once it is closed
     (row 207).
   - The case is also in My Cases, among the disposed rows, with the With Me badge.
   - This matches case-inbox-merge decision 3 (25 Oct 2026). **No deviation.**
6. **Sent by Me shows the files still out by default.** One additive filter is added: `GET /custody/sent?still_out=true`
   (decision 12).
   - A leg is still out when all four of these hold:
     - it is a send (`reason = sent`, so recalls are left out);
     - it is still the case's current leg;
     - the caller can open the case now;
     - the case's current holder is not the caller. A send to the caller's own other membership is in With Me.
   - The order is overdue first: the leg's due date ascending, nulls last, then newest first.
   - **Show Earlier** is a check control in the filter bar (URL key `earlier=true`). It drops the filter and shows
     today's list: every send and recall, newest first, with legs that have moved on muted.
   - The lead badge (Overdue, Due soon, Waiting), the columns, the side panel with the sender's own remark and the
     filter bar are unchanged.
   - Alternative: filter in the browser on `current`. Refused, because paging and the total would be wrong.
7. **A send on a case the sender can no longer open is not "still out"** (owner, 29 Oct 2026, as recommended). Row 135,
   decision 20 (owner, 23 Oct 2026) says the sender who lost sight learns nothing about where the case went.
   - Such legs appear only under Show Earlier, as today: the number is plain text and there is no badge.
   - Who loses sight on sending? Mostly an officer who held the case only through its custody, for example a
     directorate returning parawise comments. Heads, claimers and assigned officers keep sight through the ownership
     basis, so their sends are listed.
   - `CustodyDialogs` therefore goes to **`/inbox/sent?earlier=true`** after a send that loses sight. The just-sent leg
     is then the first row, under the notice. The default list would not show it.
8. **Department keeps today's rules for who sees it.** The rules are `cases.view_all`, or the server's whole-department
   reading of the selected department (`cases.claim` or `cases.allot` in the membership), or `custody.track` in a
   department membership (`tracksDepartment`). This is the union of today's Department Cases and Pending Action rules.
   - It includes State-wide readers (Auditor, State Oversight, Central Operator), because today's Department Cases rule
     includes them.
   - Alternative: drop the State-wide readers. Refused, because that would be a visibility change, and the owner said
     visibility does not change.
9. **Department, for a whole-department or State-wide reader, is `DepartmentCases` without its status switch.**
   - **The Active / Disposed `SegmentedSwitch` is removed.**
     - The page always sends `case_state=all`, which the API already accepts.
     - `case_state` leaves `LIST_FILTERS.department.fixed`.
     - An incoming `case_state` in an old link is ignored.
     - The API parameter stays for compatibility.
   - The list shows the department's active and disposed cases together, with active first (decision 13). Disposed rows
     show the Disposed badge through `HearingDate`.
   - The unfiltered m of "n of m" is `claimed_active + claimed_disposed` of the selected `/inbox/counts` block. A test
     pins that it equals the `case_state=all` total.
   - It keeps the department selector, Layout B with Search Words as the hero, Unit, Officer, Stage and Next Hearing,
     and the More Filters.
   - It gains a **Quick Filters** chip row above the filter bar:
     - **Overdue** toggles the existing `action=overdue`;
     - **With Another Office** toggles the existing `holder=elsewhere`.

     The selects under More Filters edit the same keys, so a chip and its select always agree.
   - No new API filter is needed.
   - Row 207 adds an Open / Closed switch here.
10. **"With Another Office" means "held outside this department and its units"** (owner, 29 Oct 2026, as
    recommended). This is the existing `holder=elsewhere` rule, approved in round 2 (row 102).
    - The chip's hint reads "Outside this department and its units."
    - The More Filters option for `elsewhere` is relabelled from "Another Department" to **"Another Office"**, so one
      value has one name.
    - Alternative: "anywhere but the department's own office". Refused, because a file with the department's own unit
      is not "out".
11. **A tracker without whole-department sight sees today's Pending Action list under Department.** By default every
    holder of `custody.track` (Department Head, Department Administrator) also holds `cases.claim` and `cases.allot`.
    Only a per-user override can make a tracker who is not whole-department.
    - For such a login, the selected department's Department tab renders the existing `Held tab="pending"`
      (`/custody/held?scope=owned`, which has no status rule), narrowed to that department through its `owner` filter.
      Its Overdue chip uses the same URL key `action=overdue`, which this list sends as `overdue=true`.
    - Nothing that login sees today is lost.
    - Alternative: show "not found". Refused, because it would remove access the function grants today.
12. **The tracking summary moves into Department, folded.** For a login that tracks the selected department, a closed
    `Collapsible` "Tracking Summary" holds that department's `DepartmentSummary` (held, due soon, overdue, by holder
    department, by holder), read from the `/custody/summary` call `InboxFrame` already makes for trackers.
    - Non-trackers make no `/custody/summary` request, as today.
    - Alternative: drop it. Refused, because the by-holder tables appear only here and in the report export.
13. **Department's order: active first, then the most overdue file when Overdue is on.** `/inbox/claimed` with
    `case_state=all` orders by:
    1. `Case.status = disposed` last;
    2. **when `action` is set**, the file's due date, ascending, nulls last;
    3. `Case.next_hearing_on`, ascending, nulls last;
    4. `claimed_at`, newest first.

    - `case_state=active` and `disposed` without `action` keep today's order exactly.
    - No portal screen sends `case_state=all` today, so no consumer changes.
    - An explicit `sort` from row 179, when it lands, wins after the active-first key.
    - Alternative: next-hearing order only. Refused, because disposed cases with a stale next date would mix into the
      active ones, and a head opening Overdue wants the oldest delay at the top.
14. **Department rows still open the case page.** Pending Action's side panel with the remark is not carried over; the
    case page shows the remark under the same rule.
    - The Reports line becomes "The live list of your department's cases is under Case Inbox:", linking to
      `/inbox/department` (it said "…pending cases, with remarks…" and linked `/inbox/pending`).
    - Alternative: a side panel on Department rows. Refused, because it is a new interaction, and the owner asked for
      less.

### B. Routes, redirects and links

15. **Old addresses redirect in one hop, keeping the query string.** They are client redirects, as today. A pure
    function `oldInboxTarget(path, params)` in `routes.ts` serves the redirects that depend on the query; the static maps
    serve the rest. Every target is final: none is itself in a redirect map. A `case_state` carried by an old address is
    kept in the URL and ignored by both tabs.

    | Old address | Goes to |
    |---|---|
    | `/inbox/working?held=offices` | `/inbox/with-me?held=offices` |
    | `/inbox/working?held=me` | `/inbox/with-me` |
    | `/inbox/working?overdue=true` or `?action=overdue` | `/inbox/with-me?overdue=true` (`action` dropped) |
    | `/inbox/working` (anything else) | `/inbox/my-cases` (`held` and `overdue` dropped; `q`, `next`, `stage` and the shared filters kept) |
    | `/inbox/claimed-by-me` | `/inbox/my-cases` |
    | `/inbox/disposed` | `/inbox/my-cases` (disposed cases are listed after the active ones) |
    | `/inbox/pending`, `/files/department`, `/cases/pending` | `/inbox/department`, with `overdue=true` read as `action=overdue`, and `owner=X` read as `department=X` when no `department` is given (`holder_department` stays and is ignored) |
    | `/inbox/claimed` (`ClaimedRedirect`) | `/inbox/department` for a whole-department reader, else `/inbox/my-cases` |
    | `/inbox/files`, `/files`, `/files/mine`, `/cases/with-me` | `/inbox/with-me` |
    | `/files/offices` | `/inbox/with-me?held=offices` |
    | `/files/sent`, `/cases/sent` | `/inbox/sent` |
    | `/cases` | `/inbox`, then the first allowed tab |
    | `/inbox/recommended`, `/inbox/pool`, `/inbox/transfers` | unchanged (`/claim/*`) |

    - **Pages.** `app/(portal)/inbox/with-me/page.tsx` and `my-cases/page.tsx` are new tab pages. `working`,
      `claimed-by-me`, `disposed` and `pending` become redirect pages. `sent` and `department` stay tab pages.
      `cases/(list)/*` keep their static segments (`CASES_LIST_SEGMENTS`).
    - **Breadcrumbs.** `CRUMB_PATHS` gains `/inbox/with-me` "With Me", `/inbox/my-cases` "My Cases" and
      `/inbox/department` "Department". It loses `/inbox/working`, `/inbox/claimed-by-me`, `/inbox/disposed` and
      `/inbox/pending`. The `/cases` crumb stays "Case Inbox".
16. **Links on other screens are re-pointed, not left to the redirect.**

    | Where | Today | Now |
    |---|---|---|
    | `Headline.tsx`, "Cases with Me" | `/inbox/working?held=me` | `/inbox/with-me` |
    | `Headline.tsx`, "Overdue Actions" | `/inbox/working?overdue=true` | `/inbox/with-me?overdue=true` |
    | `Blocks.tsx`, personal "Cases with Me" | `/inbox/working?held=me` | `/inbox/with-me` |
    | `Blocks.tsx`, department "Pending Actions" | `/inbox/pending` | `/inbox/department?department=<code>` |
    | `Blocks.tsx`, "next dates differ" | `/inbox/department?department=<code>&next_differs=true` | unchanged |
    | `ReportPage.tsx`, Pending Actions report | `/inbox/pending` | `/inbox/department` (decision 14) |
    | `CustodyDialogs.tsx`, after a send that loses sight | `/inbox/sent` | `/inbox/sent?earlier=true` (decision 7) |
    | `PortalShell.tsx`, the Case Inbox pill | `mine.working` | `mine.files` (decision 3) |

    - The department "Pending Actions" KPI counts the files of every case the department owns, disposed included.
      Department now lists active and disposed together, so the list holds every case behind the figure.
    - **Alerts, the bell and e-mails need no change.** They link to case pages and tickets only.

### C. Wording

17. **The wording guards win over two of the owner's first labels** (owner, 29 Oct 2026, as recommended).
    - The custody-sense "file" guard (row 135, case-workspace-admin decision 6) denies `/file (is )?with/i` in every
      `messages.ts` value and in component text.
    - So the badge reads **"With Me"** and the chip reads **"With Another Office"**, in place of "File With Me" and
      "File With Another Office".
    - Alternative: allow-list both labels. Refused, because it would reopen the eOffice vocabulary the owner removed.
18. **New and changed user text**, all in Title Case under the existing helper and both guards.
    - **Tabs:** "With Me", "My Cases", "Sent by Me" and "Department". `T.tabs.inbox` loses `working`, `claimed`,
      `disposed` and `pending`.
    - **Badges:** "Assigned to Me", "Claimed by Me" and "With Me", with the column header "Reason". The Disposed badge is
      `HearingDate`'s existing text.
    - **Controls:**
      - Show: "With Me" and "With My Offices";
      - "Show Earlier";
      - Quick Filters: "Overdue" and "With Another Office";
      - "Tracking Summary".
    - **Empty states:**
      - My Cases: "Cases assigned to you, cases you claimed and cases sent to you appear here.";
      - Sent by Me, still out: "Nothing you sent is still out. Tick Show Earlier to see everything you sent and
        recalled.";
      - With Me reuses `T.files.emptyMine` and `emptyOffices`;
      - Department keeps `T.inbox.emptyViews.department`.
    - **Other text:** the hint "Outside this department and its units."; `T.inbox.holders.elsewhere` "Another Office";
      the Reports line of decision 14.
    - **Removed:** `T.inbox.emptyViews.working`, `claimed` and `disposed`. Department's switch no longer uses
      `T.inbox.caseStates`. The strings stay only if another screen reads them.
    - No eOffice words, and no "allot". The page header and subtitle are unchanged.

### D. Plan and earlier decisions

19. **Plan alignment.** Plan §5.4 lists Recommended, Claimed ("the department's own cases"), Unclaimed pool and
    Transfers.
    - Claimed is the Department tab; the other three stay in Case Claim.
    - Plan §5.7's custody card and tracking keep every function: With Me, the tracking summary in Department, and the
      Pending Actions report.
    - **No deviation from the plan.** Recommend-and-claim, visibility, the remark rule and the functions are untouched.
20. **Earlier decisions this note changes, all approved by the owner on 29 Oct 2026:**
    - case-inbox-merge decision 7: six tabs become four, and the Claimed by Me and Disposed tabs give way to the badges
      and the Disposed badge;
    - case-inbox-merge decision 8: Working On's "Show: All" goes; With Me and With My Offices remain (decision 2);
    - case-inbox-merge decision 10: the pill counts With Me (decision 3);
    - portal-ui-redesign round 2: Department Cases' Active / Disposed switch goes (decision 9);
    - the owner's own "File With …" labels are worded "With …" (decision 17).

    These are kept as they are:
    - case-inbox-merge decision 3 (decision 5);
    - case-workspace-admin decision 20 (decision 7);
    - the portal-ui-polish-2 Layout B rules (decision 9).
21. **Row 179 (sorting on the case lists, approved) maps onto the new tabs.** If this row merges first, row 179's lists
    C1 to C5 become:
    - With Me: `/custody/held`, default `due`;
    - My Cases: `/inbox/mine?view=all`, today's order after the active-first key;
    - Sent by Me: `/custody/sent`, default `due` with `still_out=true`, and `sent` desc under Show Earlier;
    - Department: `/inbox/claimed?case_state=all`, active first, then `next_hearing`, or `due` with `action`.

    The scribe adds this note to row 179's pointer note. If row 179 merges first, this row keeps its sort controls on
    the four tabs, after the active-first key.

### E. The case page's More menu (owner, 29 Oct 2026; a portal fix in the same build)

22. **The defect and its cause.** `.tabs` (`components/ui/layout.module.css`) has `overflow-x: auto`, so the bar
    scrolls sideways on phones. A box that scrolls on one axis clips on both. The kit `Menu` (`ui/overlays.tsx`)
    renders its `.menuList` `position: absolute` inside the bar (`Tabs`' `more` group in `layout.tsx`). So the list is
    cut at the bar's bottom edge: only "Parties" shows.
    - The focus ring is `outline: 2px` with `outline-offset: 1px` and a 4 px `box-shadow` (`globals.css`). It is cut by
      the same box, at the top and bottom of the More button and of every tab link.
23. **Fix: the kit `Menu` always places its list in a portal, `position: fixed`, from the button's rectangle.** It is
    not an option.
    - **Where it mounts.** The list mounts in `document.body`, or in the closest `[role='dialog']` when the menu is
      inside an overlay, so the focus trap holds. This is the Office Picker's and User Picker's approach
      (`createPortal`, `position()`).
    - **Placement:**
      - below the button (`top = rect.bottom + 4`), or above it when the room below is under the list's height and the
        room above is larger;
      - aligned to the button's start or end edge per `align`;
      - kept 8 px inside the viewport on both sides;
      - `z-index` 40, as today, which is above the sticky header (30).
    - **Closing:**
      - on window `resize`;
      - on any `scroll` (capture) whose target is not inside the list;
      - on outside `mousedown`, where "outside" now means outside both the button's wrapper and the list;
      - on choosing an item, as today.
    - **Keyboard is unchanged:**
      - ArrowDown and ArrowUp on the button open the list;
      - Arrow, Home and End move between items;
      - Escape closes and returns focus to the button;
      - Tab closes.

      The items are found through a ref to the list, because the list is no longer inside the wrapper. The first item
      takes focus with `preventScroll: true`, so opening never scrolls a container and closes the menu.
    - **ARIA is unchanged:** `aria-haspopup`, `aria-expanded`, `aria-controls` and `role="menu"`/`menuitem`.
    - Alternative: an opt-in `fixed` option used only by `Tabs`. Refused, because three other menus sit in scrolling
      boxes (decision 25), and an option that must be remembered will be forgotten.
    - Alternative: `overflow: visible` on the bar. Refused, because phones need the sideways scroll.
24. **Fix: the focus ring of the tab bar is drawn inside the tab.** In `.tabs`, `.tab:focus-visible` (the links and the
    More button, which uses `s.tab`) takes `outline-offset: -2px` with an inset `box-shadow: inset 0 0 0 4px
    var(--accent-ring)`. The ring stays within the tab's own box, which the bar does not clip.
    - The bar keeps its sideways scroll, its height and its ink line.
    - Alternative: vertical padding on `.tabs`. Refused, because it moves the ink line and the bar's border, and every
      tab strip in the portal would shift.
25. **Every other `Menu` was checked for the same clipping. The fix in decision 23 covers them all.**

    | Menu | Where | Inside a scrolling box? |
    |---|---|---|
    | Tab bar "More" | `ui/layout.tsx` `Tabs`, used by the case page (`CaseFrame.tsx`, `CASE_TABS` with `more`) | **Yes**, `.tabs` `overflow-x: auto`. This is the defect. |
    | Row actions (`RuleMenu`) | `admin/mapping/common.tsx`, in the Counsel Codes, Keywords and Watchlist tables | **Yes**, `.dataWrap` `overflow-x: auto`. A list opened on the last rows is cut at the table's bottom edge or scrolls inside it. |
    | User Details "More" and each office's "Actions" | `admin/UserDetails.tsx`, inside `SidePanel` | **Yes**, `.panelBody` `overflow: auto`. Near the panel's bottom the list falls below the fold inside the panel. The list now mounts in the panel's dialog. |
    | "More Actions" on the case header | `case/CaseFrame.tsx` `.actions` | No, as read. It gets the same behaviour. |
    | The user menu | `shell/PortalShell.tsx` (sticky header) | No. It gets the same behaviour. |
    | Filter bars (`components/filters/*`) | — | They use no `Menu`. More Filters is an in-page section, so they are not affected. |

## Data
None. No table, column, reference code or migration. Every list reads existing tables through existing services.
`alembic heads` is unchanged. Row 207 brings its own migration; this row adds nothing for it.

## Services
**`backend/aslms/services/my_cases.py`** (read-only):
- `VIEWS` gains `"all"`.
  - `_view_set(c, "all")` is `or_(c.allotted, c.file, c.claimed)`.
  - `_state("all")` is `None`, so there is no status rule.
  - The error text becomes "view is one of working, files, all, claimed, disposed".
- `mine(view="all")` orders by:
  1. `(Case.status == CaseStatus.DISPOSED)` ascending, so active cases come first;
  2. then the default branch: next hearing (nulls last), the file's due date (nulls last), case number, id.

  `reasons` is filled as today.
- `mine_counts` returns `all` as well, because it loops over `VIEWS`.
- The module docstring names what the portal reads: `all` and the `files` count.
- **Unchanged:** `visible_case_condition`, merged cases excluded, `cases.view_scope` required, no writes.

**`backend/aslms/services/custody.py`** (read-only):
- `sent(..., still_out: bool = False)`. When true, the statement adds:
  - `CustodyHistory.reason == "sent"`;
  - an `EXISTS` over an alias of `custody` (`SENT_CUR`, not the bare table, because the visibility rule correlates on
    `custody`): `case_id = leg.case_id`, `current_leg_id = leg.id`, and `holder_user_id IS DISTINCT FROM :me`;
  - `visibility.visible_case_condition(session, user)` on the leg's case.

  The order is then `CustodyHistory.due_date.asc().nulls_last()`, `created_at.desc()`, `id.desc()`. `total` counts the
  filtered statement.
- With `still_out=False`, the statement and order are exactly today's.
- Items are built as today. Under `still_out`, every item has `visible = true` and `current = true`.

**`backend/aslms/services/inbox.py`** (read-only):
- `claimed(...)` builds its order (decision 13):
  1. when `case_state == "all"`, `(Case.status == CaseStatus.DISPOSED)` ascending;
  2. when `action` is set, a scalar subquery of the file's `due_date` (an alias of `custody`), ascending, nulls last;
  3. then today's `Case.next_hearing_on` ascending, nulls last;
  4. then `claimed_at` descending.

  `case_state=active|disposed` without `action` produce exactly today's order.

No other service changes, no audit rows (these are reads), and no events.

**`backend/aslms/api/schemas.py`**: `MyCaseCountsOut` gains `all: int`. The `/inbox/mine` `view` description names
`all`. Then:
- `frontend/openapi.json` is regenerated;
- `npm run gen:api` is run by the developer in the build, not in this design step.

## API
No new endpoint, no new `Permission`, no visibility change.

| Method and path | Permission | Change |
|---|---|---|
| `GET /inbox/mine` | `cases.view_scope` | `view` accepts `all`: the three sets whatever the status, active first, each with `reasons`. |
| `GET /inbox/mine/counts` | `cases.view_scope` | adds `all`. The portal reads `files` (pill, With Me) and `all` (My Cases count line). |
| `GET /custody/sent` | `cases.view_scope` or `cases.view_all` | new `still_out: bool = false`. When true: sends only, still the current leg, on a case the caller can open, not held by the caller, overdue first. When false: unchanged. |
| `GET /inbox/claimed` | as today (`cases.view_scope`; whole department with `cases.claim` or `cases.allot`; another department with `cases.view_all`) | `case_state=all` (now sent by Department) puts active cases first. With `action`, the file's due date comes next. `case_state` stays for compatibility; the filters are unchanged. |
| `GET /custody/held` (`scope=me`, `office`, `owned`) | `cases.view_scope` or `cases.view_all`; `owned` needs `custody.track` | unchanged (no status rule). Read by With Me and the tracker fallback of Department. |
| `GET /custody/summary` | `custody.track` | unchanged. Read only for trackers (the tracking summary in Department). |
| `GET /inbox/counts` | `cases.view_scope` | unchanged. Decides the Department tab (`whole_department`) and gives `claimed_active + claimed_disposed` for "n of m". |

## Jobs
None.

## Tests

**Backend** (`backend/tests/db/`, the scripted fixtures in `tests/db/conftest.py`):
- `test_my_cases.py`:
  - `test_all_view_is_three_sets_any_status`: an allotted case, a claimed case and a case with me, each once active and
    once disposed, are all in `view=all`, each once.
  - `test_all_view_active_first`: every active row comes before every disposed row, including a disposed case that
    still has a past or stale next hearing date. Inside each group the default order holds.
  - `test_all_reasons_badges`: a case both allotted to me and with me carries `reasons == ["allotted", "file"]`. A case
    claimed through an accepted transfer carries `["claimed"]`.
  - `test_disposed_case_with_me_in_with_me_and_all`: it is in `/custody/held?scope=me` and counted in `files`, and it is
    in `view=all` with `file` in its reasons.
  - `test_counts_all_matches_list`: `mine_counts()["all"]` equals the unfiltered `mine(view="all").total`.
  - `test_files_count_equals_held_me_and_headline`: `mine_counts()["files"]` equals `held(scope="me").total`, which
    equals the dashboard headline `files_with_me.total`, disposed cases included. The headline `overdue_actions.total`
    equals `held(scope="me", overdue=True).total`.
  - `test_unknown_view_400`: `view=nope` answers 400 and names `all`.
- `test_custody_sent_still_out.py` (new):
  - `test_still_out_keeps_current_sends_only`: a send still current is kept. A send moved on, a recall leg and a send
    now held by the caller (their other membership) are left out.
  - `test_still_out_hides_cases_no_longer_visible`: a current send on a case the sender can no longer open is absent
    under `still_out=true` and present, with `current: null`, without it (decision 7).
  - `test_still_out_order_overdue_first`: the order is overdue, due later, no due date, then newest first among equals.
  - `test_still_out_total_matches_items`.
  - `test_sent_default_unchanged`: without the parameter, the items and order equal today's (sends and recalls, newest
    first).
  - `test_still_out_writes_nothing`: no audit row and no event.
- `test_inbox_claimed.py`:
  - `test_claimed_all_active_first`: with `case_state=all`, the active rows come before the disposed rows.
  - `test_claimed_all_total_equals_counts`: the total equals `claimed_active + claimed_disposed` of `/inbox/counts`.
  - `test_claimed_action_orders_by_due`: with `case_state=all&action=overdue`, active first and then the most overdue
    first.
  - `test_claimed_active_and_disposed_order_unchanged`: without `action`, `case_state=active` and `case_state=disposed`
    keep today's order.
  - `test_holder_elsewhere_is_outside_subtree`: a file with the department's own unit is not `elsewhere`; a file with
    another department is.
- API: the OpenAPI schema lists `still_out` on `/custody/sent`, `all` in `MyCaseCountsOut`, and `all` in the `view`
  description.
- The existing tests stay green: visibility, merged cases, 403 without `cases.view_scope`, no writes. `ruff check` and
  `pytest -q` pass.

**Frontend** (vitest):
- **`lib/routes.test.ts`:**
  - `inboxTabsFor` gives:
    - an officer: With Me, My Cases and Sent by Me;
    - a head (whole and tracker): all four;
    - State oversight (`cases.view_all` without `cases.view_scope`): With Me, Sent by Me and Department;
    - a tracker by override without whole sight: Department as well;
    - no login: nothing.
  - `oldInboxTarget` covers every row of decision 15, including query translation: `overdue` to `action` and `owner` to
    `department` for `/inbox/pending`; `held`, `overdue` and `action` for `/inbox/working`.
  - No redirect target is itself a redirect source.
  - `CRUMB_PATHS` has the new crumbs and none of the removed ones.
  - `CASES_LIST_SEGMENTS` is unchanged.
- **`components/inbox/inbox.test.tsx`:**
  - The four tabs per login. Only With Me has a count, from `/inbox/mine/counts`.`files`.
  - **No `/custody/summary` request is made for a non-tracker.**
  - `/inbox` opens `/inbox/with-me`.
  - A tab the login may not open shows "not found".
  - `FlashNotice` sits above the tabs.
  - **With Me:**
    - it calls `/custody/held?scope=me`;
    - "With My Offices" calls `scope=office`;
    - Show has no "All";
    - the Next Hearing column shows `HearingDate`, and a disposed row reads "Disposed";
    - "Overdue Only" sends `overdue=true`;
    - the side panel shows the card's remark.
  - **My Cases:**
    - it calls `view=all`;
    - **there is no status switch, and no `case_state` is sent**, even when the URL carries one;
    - a disposed row shows the Disposed badge;
    - the badges come in the order Assigned to Me, Claimed by Me, With Me, with two badges on a two-reason row;
    - "Your Action" is filled only when `custody.with_me`;
    - the count line is "n of m", with m from `all`.
  - **Sent by Me:**
    - the default calls `/custody/sent?still_out=true`;
    - Show Earlier (`earlier=true`) calls it without `still_out`;
    - the still-out empty state text;
    - muted rows appear only under Show Earlier.
  - **Department:**
    - **no Active / Disposed switch is drawn**, and the request carries `case_state=all` whatever the URL says;
    - a disposed row shows the Disposed badge;
    - m is `claimed_active + claimed_disposed`;
    - the Overdue chip sets `action=overdue` and With Another Office sets `holder=elsewhere`, and each chip and its More
      Filters select agree;
    - the tracker fallback renders the `scope=owned` list narrowed to the department, and its Overdue chip sends
      `overdue=true`;
    - the Tracking Summary is closed by default and shown only to a tracker of the selected department.
  - The redirect pages: `/inbox/working?held=offices`, `/inbox/working?overdue=true&q=ram`, `/inbox/working?q=ram`,
    `/inbox/claimed-by-me`, `/inbox/disposed?q=x`, `/inbox/pending?overdue=true&owner=EDU`, `/cases/pending` and
    `/inbox/claimed` (both branches) land as in decision 15.
- **`components/files/cases-list.test.tsx`:** the held and sent expectations follow decisions 2 and 6, and the old
  `/inbox/pending` cases move to Department.
- **`app/pages.test.tsx`:** the routes include `/inbox/with-me`, `/inbox/my-cases`, `/inbox/sent` and
  `/inbox/department`, and the redirect pages `/inbox/working`, `/inbox/claimed-by-me`, `/inbox/disposed` and
  `/inbox/pending`.
- **Shell (`shell.test.tsx`):** the Case Inbox pill is the `files` figure.
- **Dashboard and reports** (`dashboard.test.tsx`, `reports.test.tsx`): the links of decision 16.
- **`CustodyDialogs`:** a send that loses sight pushes `/inbox/sent?earlier=true`.
- **Guards:** `lib/wording.test.ts` and `lib/labels.test.ts` stay green with the new strings. No custody-sense "file"
  and no "allot".
- **The More menu (section E)**, in `components/ui/ui.test.tsx`:
  - `Menu` renders its list outside the wrapper, in `document.body`, with `position: fixed`. `top` is the button's
    rect bottom plus 4. With a mocked rect near the bottom of a short window, it opens above.
  - `left` stays at least 8 px from the right edge with a button at the far right.
  - Inside a `[role='dialog']` the list mounts in the dialog.
  - Keyboard: ArrowDown opens and focuses the first item; Arrow, Home and End move; Escape closes and returns focus;
    Tab closes.
  - A `mousedown` on an item does not close before the click. An outside `mousedown` closes.
  - A `scroll` event on an ancestor closes; a scroll inside the list does not; `resize` closes.
  - `Tabs` with `more`: every "More" item is rendered and none is a descendant of the `nav`.
  - A test pins that `.tabs .tab:focus-visible` declares a negative `outline-offset`. It reads the CSS module text, as
    other style pins do.
- `npm run typecheck`, `npm run lint` and `npm test` pass.

**uicheck** (`frontend/e2e`):
- **Routes:** the page scan picks up `/inbox/with-me`, `/inbox/my-cases`, `/inbox/sent` and `/inbox/department`. The
  four redirect pages are checked as redirects.
- **The redirect map** in `uicheck.spec.ts`:
  - the `/files/*`, `/inbox/files` and `/cases/*` targets follow decision 15;
  - new entries: `/inbox/working` to `/inbox/my-cases`, `/inbox/claimed-by-me` to `/inbox/my-cases`, `/inbox/disposed`
    to `/inbox/my-cases`, and `/inbox/pending` to `/inbox/department`.
- **States**, at 375, 768 and 1280 px. They replace the three `/inbox/working …` states:
  - `/inbox/with-me (side panel)`;
  - `/inbox/with-me?held=offices`;
  - `/inbox/my-cases (badges)`: a row with each badge, one with two, and a disposed row with the Disposed badge after
    the active rows;
  - `/inbox/my-cases (Search Words on the first row)`;
  - `/inbox/my-cases (next hearing bands)`: moved from Working On, with the same band and next-date assertions,
    including the `disposed` band;
  - `/inbox/sent` (still out) and `/inbox/sent?earlier=true`;
  - `/inbox/department (quick filters)`: no status switch, and active and disposed rows;
  - `/inbox/department?action=overdue&holder=elsewhere`.
- **The More menu states:**
  - `/cases/<sample> (More menu open)`: click "More" in the tab bar. Every `[role='menuitem']` (Parties, Linked Cases,
    Journey and Stage, Alerts, Details) lies fully inside the viewport, and `document.elementFromPoint` at each item's
    centre returns the item or a descendant, so it is neither clipped nor covered.
  - `/cases/<sample> (More button focused)`: open with ArrowDown, press Escape, and measure. The focused button's box
    lies inside the bar's client rect vertically, and its computed `outline-offset` is at most minus the outline width,
    so the ring is inside the box.
  - `/admin/mapping/... (row menu on the last row)`: the same full-visibility measure for `RuleMenu`.
- **A new generic check, `menu-clipped`, in `checks.ts`:** for any open `[role='menu']`, each item must be inside the
  viewport and be the element at its own centre. With no menu open it costs nothing.
- **Fixtures:**
  - the `/inbox/mine` matcher answers `view=all` with rows covering every reason, one two-reason row and disposed rows
    last;
  - `/inbox/mine/counts` has `all`;
  - the `/inbox/claimed` fixture for `case_state=all` has active and disposed rows;
  - the `/custody/held` fixture has one disposed row;
  - the `/custody/sent` matcher reads `still_out`: current, visible rows when it is set, today's mixed rows otherwise.

## Verification
1. **Static checks.** `ruff check`, `pytest -q`, and in `frontend/` `npm run typecheck`, `npm run lint` and `npm test`,
   all green.
2. **No migration.** `alembic heads` is unchanged; the `migrate` step reports nothing to apply.
3. **API checks** on the dev proxy, with a department officer's session holding one case assigned, one case sent to
   them due tomorrow, one disposed case still with them, and one case they sent on that is still with the recipient:
   - `GET /inbox/mine/counts`: `files` equals `GET /custody/held?scope=me` `total` (the disposed case included) and the
     dashboard's "Cases with Me". `all` equals `GET /inbox/mine?view=all` `total`.
   - `GET /inbox/mine?view=all`: active rows first, the disposed case last. Each row's `reasons` matches why it is
     there.
   - `GET /custody/sent?still_out=true` lists the case sent on. After the recipient sends it further, it is gone from
     the list and present without the parameter, muted.
   - `GET /inbox/claimed?office=<dept>&case_state=all`: active first; its total equals `claimed_active +
     claimed_disposed`. With `&action=overdue`, the most overdue active case is first.
4. **Browser checks** at http://localhost:3000 by the owner and the tester, at 1280, 768 and 375 px:
   - **Tabs per login:**
     - an officer sees With Me, My Cases and Sent by Me;
     - a head or department administrator sees all four;
     - an Auditor sees With Me, Sent by Me and Department.
   - **The pill** equals the With Me count and the dashboard's "Cases with Me".
   - **With Me:** the most urgent due date is first, with the action and From. A disposed case with me is listed with
     "Disposed". "With My Offices" works. The side panel shows the remark.
   - **My Cases:** the badges are right, disposed cases come after active ones with "Disposed", and there is no status
     switch.
   - **Sent by Me:** only files still out, overdue first. Show Earlier shows the full history. Sending a case out of
     one's sight lands on Sent by Me with Show Earlier on, the case first and the notice above.
   - **Department:** no status switch, active first, disposed with "Disposed"; the Overdue and With Another Office
     chips; the Tracking Summary for a head; the selects agreeing with the chips.
   - **Old addresses** land on the right tab with the query kept: `/inbox/working?held=offices`,
     `/inbox/working?overdue=true`, `/inbox/claimed-by-me`, `/inbox/disposed`, `/inbox/pending?overdue=true`,
     `/cases/with-me`, `/files/department` and `/inbox/claimed`.
   - **Dashboard links:** "Cases with Me", "Overdue Actions" and the department "Pending Actions" open the right tab.
   - **The case page's More:**
     - at each width, More opens a list showing every item (Parties, Linked Cases, Journey and Stage, Alerts, Details)
       over the page;
     - scrolling the page or the bar closes it;
     - the keyboard works;
     - the focus ring of More and of the tabs is whole.
   - The mapping table's row menu on the last row and the User Details menus near the panel's bottom show in full.
5. **`uicheck`** on a private network against temporary images (runbook section 16, never on the shared stack) exits 0
   with `findings.json` empty. The run directory is recorded in the cycle report.
6. **Scribe** records the change in:
   - `docs/claude_ASLMS_design_decisions.md`: the four tabs, no Disposed switch until row 207's Open / Closed, the
     changes of decision 20, and the More menu;
   - `docs/ASLMS_Process_Workflows.md`: the user sections that name the six tabs;
   - CLAUDE.md's current focus;
   - row 179's pointer note (decision 21).

## Open questions
None. The owner answered every point on 29 Oct 2026:
- no Disposed switch or tab in this row; active and disposed together, disposed after, with the Disposed badge; Open /
  Closed comes with row 207;
- With Me keeps disposed cases with me until they are closed (row 207);
- the other recommendations stand: Sent by Me still out with Show Earlier, and a send on a case the sender can no longer
  open only under Show Earlier; "With Another Office" means outside the department and its units; the labels "With Me"
  and "With Another Office"; the pill on the With Me count; the More menu fix and the other clipped menus.

## Deviations
Recorded by the developer during the build (29 Oct 2026); each is the smallest choice where the note was silent.
- **The chip's hint.** The kit `Chip` gains an optional `hint`, drawn as the button's tooltip (`title`) and its
  description (`aria-describedby` on a visually hidden span). With Another Office uses it for "Outside this department
  and its units."
- **Show Earlier survives Clear All.** `earlier` is added to `LIST_FILTERS.sent.fixed`, so clearing the filters keeps
  the chosen view, as Department keeps its department.
- **The tracker's Department list (decision 11).** Its Quick Filters show only Overdue: `/custody/held?scope=owned` has
  no "held elsewhere" filter, so With Another Office is left out there. Its own "Overdue Only" check is dropped, so
  the chip (`action=overdue`, sent as `overdue=true`) is the one control; an `overdue=true` in an old link still
  reads as on. The owner filter of that list offers only the selected department. The Next Hearing column is With
  Me's only.
- **One redirect component.** Every old Case inbox, Files and Cases page renders `OldInboxRedirect from="…"`, which
  calls `oldInboxTarget`; the fixed maps (`OLD_FILES_REDIRECTS`, `OLD_CASES_REDIRECTS` and the new `OLD_TAB_REDIRECTS`)
  serve the addresses with no query rule. `redirectTarget` moved to `routes.ts` and is re-exported from
  `Redirects.tsx`.
- **Tab in an open menu.** Tab closes the list and returns the focus to the button first, so the next Tab moves on
  from the button (the list now sits at the end of the page or dialog, not after the button).
- **Closing on scroll (decision 23).** A scroll outside the list closes the menu only when it moves the button from
  where the list was placed. Pressing More makes the tab bar bring the button into view, and that scroll's event
  arrives just after the list opens; closing on it shut the menu at once (found by a local uicheck run). Scrolling the
  page or the bar while the menu is open still moves the button and closes it.
- **A local uicheck run.** Besides the integrator's run on temporary images, the developer ran the full uicheck on the
  host against `next start` of this branch's build (private port, not the shared stack): 503 passed, 7 skipped by
  width, 0 findings.
