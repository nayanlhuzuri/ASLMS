# Design: One "Case inbox" — the Cases list folded into the Case inbox

```
slug: case-inbox-merge
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25, including decisions 3, 4, 8 and 14 as written
```

## Context
The owner decided on 25 Oct 2026 to merge the two sidebar menus **"Case inbox"** (row 102,
`docs/design/portal-ui-redesign.md`, decision 5) and **"Cases"** (row 135, `docs/design/case-workspace-admin.md`,
decisions 3 and 17-21) into **one menu, "Case inbox"**, with six tabs:

| Tab | Shows | Who sees it |
|---|---|---|
| Working on | cases allotted to me or currently with me (the custody row), each with action needed, due date and the Overdue / Due soon / New lead badge | everyone |
| Sent by me | cases I sent on: who has them now (`current`) and the action asked | everyone |
| Claimed by me | cases I claimed or accepted by transfer | holders of `cases.claim` |
| Disposed | my finished cases | everyone |
| Department cases | everything the department owns, with the full filter grid | whole-department members (heads, admins) and State-wide readers |
| Pending action | everything waiting in the department, overdue first | holders of `custody.track` |

The owner also fixed these points:
- The "Cases" menu entry goes. "Cases with me" folds into Working on, so a case appears once.
- Redirects keep the query string. `/cases/with-me` goes to Working on, `/cases/sent` to Sent by me and
  `/cases/pending` to Pending action. The earlier `/files/*` and `/inbox/files` redirects are re-pointed.
- The case page stays at `/cases/<ref>`.
- No database change and no visibility change.
- The navigation count for Case inbox is the Working on count. The pending figure appears only for trackers.

**What is in place (read for this note).**
- **Case inbox** (`frontend/src/components/inbox/*`, routes `/inbox/*`):
  - Working on, Claimed by me and Disposed come from `GET /inbox/mine?view=…` (API A1, `services/my_cases.py`), with
    counts from `GET /inbox/mine/counts` (A2).
  - Department cases comes from `GET /inbox/claimed` (A3), shown when `/inbox/counts` says `whole_department` or the
    login holds `cases.view_all`.
  - The entry shows only with a department membership or `cases.view_all` (`showsInbox`).
- **Cases list** (`frontend/src/components/files/*`, routes `/cases/(list)/*`):
  - Cases with me comes from `GET /custody/held?scope=me`, or `scope=office` under "Held by: My offices"
    (`?held=offices`).
  - Sent by me comes from `GET /custody/sent`.
  - Pending action comes from `GET /custody/held?scope=owned`, with `TrackingSummary`.
  - Each list has the lead badge, the side panel with the full remark and `FlashNotice` above the tabs.
  - The entry shows with `cases.view_scope`.
- **What `/inbox/mine?view=working` already holds.** The view is "allotted to me, or the custody row's holder is
  me", for active cases only. Each row carries a custody brief (`CustodyBriefOut`): holder office, holder user,
  `with_me`, `pending_action` and its label, `since`, `due_date`, `overdue` and `overdue_days`. It lacks three facts
  the Cases with me row and badge use:
  - `due_soon`;
  - `sent_by` (the From column);
  - the remark, which the brief leaves out on purpose (custody-workflow decision 25).

  It also leaves out a file with me on a disposed case, which Cases with me listed.

**Not covered.** A separate owner request is pending a mockup: Title Case labels across the portal and an
expanding multi-level side menu. It is **row 153**, to be designed after the owner approves the mockup. This note
changes no label casing and no sidebar structure beyond removing one entry.

## Decisions

### A. The API: extend `/inbox/mine`, no new endpoint

1. **Working on keeps reading `GET /inbox/mine?view=working`. It does not get a combined API.** The view is already
   "allotted ∪ with me", with the custody facts batched per page (`case_briefs`, three queries). Three read-only
   changes close the gap with Cases with me (decisions 2 to 4). The remark is not added (decision 9).
   - Alternative: a new `GET /inbox/working` joining `/custody/held?scope=me` with the allotted set. Refused,
     because it would repeat A1's sets and visibility.
   - Alternative: build Working on in the browser from `/inbox/mine` plus `/custody/held`. Refused, because two
     paged lists cannot be merged and paged correctly in the browser, and the counts would disagree.
2. **The custody brief gains `due_soon` and `sent_by`. Both are additive.**
   - `due_soon`: not overdue, and `due_date ≤ today (IST) + request_due_soon_days`. This is the same rule and window
     as the custody card (row 135, decision 19) and `/custody/summary`.
   - `sent_by`: `{name, designation, office_code}`, from the current leg's actor snapshot, or null. It uses the
     existing `CustodySentByOut`.
   - The brief is shared with the department's Claimed list (A3), so those items gain the fields too.
   - **No visibility change.** The sender's snapshot is already shown on the case's journey to every reader of the
     case; only the remark is gated.
3. **The Working on set includes a case with me whatever its status.** The set is
   `(allotted AND status in pending/unknown) OR (custody holder = me)`. Cases with me listed a disposed case still
   held by the person (a compliance step, an appeal decision), so folding it in must not drop that work.
   - Such a case also stays under Disposed, which is unchanged: the disposed cases of the three sets. A case appears
     once per tab.
   - `mine_counts()["working"]` follows the same set.
   - Alternative: keep Working on active-only. Refused, because the holder would lose sight of a pending action.
4. **Working on is ordered by the caller's own due date first.** The order is:
   1. the due date of a custody row held by the caller with a pending action, ascending, nulls last (so overdue
      comes first);
   2. then `next_hearing_date`, ascending, nulls last;
   3. then `case_no_text`, then `id`.

   This puts the person's actions at the top, as Cases with me did, and the allotted cases by hearing after them.
   The other views keep their order.
   - Alternative: keep next hearing first (round 2). Refused, because an overdue action could sit below twenty
     hearings.
5. **Nothing else changes in the API.**
   - `view=files` and the `files` count stay (row 135, decision 2). The portal stops reading them; no consumer
     breaks.
   - `/custody/held`, `/custody/sent`, `/custody/summary`, `/inbox/claimed` and `/inbox/counts` are reused as they
     are.
   - No new `Permission`, no migration and no audit row, because these are reads.

### B. The menu and the tabs

6. **One sidebar entry, "Case inbox"** (key `inbox`, `/inbox`, group Work, functions `CASE_READERS`). The
   `showsInbox` condition is dropped from this entry, because Working on, Sent by me and Disposed are for everyone,
   standing counsel and logins without a department included. The APIs already serve them: `my_conditions` uses
   only the department memberships for "allotted", and `/inbox/counts` answers a login with no department with one
   block, `office_code` null.
   - The `files` entry ("Cases") is removed from `NAV`.
   - Case claim keeps `showsInbox`.
7. **The tabs**, in the owner's order, each its own route, with `INBOX_TABS` extended and a new
   `inboxTabsFor(me, { whole })` in `routes.ts`. It replaces `casesTabsFor`.

   | Tab | Route | Shows when (display only; the API decides) | Data |
   |---|---|---|---|
   | Working on | `/inbox/working` | `cases.view_scope` | `GET /inbox/mine?view=working` (decision 8) |
   | Sent by me | `/inbox/sent` (new) | `cases.view_scope` or `cases.view_all` | `GET /custody/sent`, the existing `Sent` component unchanged |
   | Claimed by me | `/inbox/claimed-by-me` | `cases.claim` held in an active membership | `GET /inbox/mine?view=claimed`, unchanged |
   | Disposed | `/inbox/disposed` | `cases.view_scope` | `GET /inbox/mine?view=disposed`, unchanged |
   | Department cases | `/inbox/department` | `cases.view_all`, or a `/inbox/counts` block with `whole_department` (today's rule) | `DepartmentCases`, unchanged |
   | Pending action | `/inbox/pending` (new) | `tracksDepartment(me)`: a department membership holding `custody.track` | `GET /custody/held?scope=owned` with `TrackingSummary`, the existing `Held tab="pending"` unchanged |

   - Claimed by me follows the owner's table: it is hidden without `cases.claim`. By default `cases.claim` and
     `cases.transfer_decide` come together (`_OWNERSHIP`), so no default login loses it. A login whose `cases.claim`
     was removed by an override no longer sees the tab. The cases themselves are unchanged and stay reachable
     through Department cases or Search.
   - A tab the login may not open shows the "not found" empty state, as `CasesFrame` did.
   - `/inbox` opens the first tab the login may open, or `/search` when there is none (`CasesIndex`'s rule, moved).
8. **Working on, the list.** It uses the Work list template: a `DataTable` that stacks as cards on phones and when it
   cannot fit.
   - **Columns:**
     1. the lead badge, in the 96 px `Lead`;
     2. Case and parties;
     3. Next hearing (with its badge, as now);
     4. Action needed;
     5. Due by (danger text when overdue);
     6. From;
     7. the chevron, hidden on phones.

     Action needed, Due by and From are filled only when `custody.with_me`, as round 2's "Your action" column was.
     For a case allotted to me but with someone else they read "—", and the side panel says where it is. Stage
     leaves the columns (seven would not fit at 1280 px beside the sidebar) and stays a filter.
   - **The lead badge.** `leadBadge(row, "working")` in `lib/cases.ts` reads `row.custody` only when `with_me`, first
     match wins:
     - `overdue` gives **Overdue** (danger);
     - `due_soon` gives **Due soon** (warning);
     - `since` within 48 h gives **New** (info);
     - otherwise no badge.

     A row not with me has no badge; the column keeps its width.
   - **"Show" control.** The segmented control in the filter bar's own controls, first, keyed `held`:

     | Option | `held` | Data |
     |---|---|---|
     | **All** | none, the default | `/inbox/mine?view=working` |
     | **With me** | `me` | `/custody/held?scope=me`, the old Cases with me list exactly |
     | **With my offices** | `offices` | `/custody/held?scope=office`, the old "My offices" |

     The last two render the existing `Held tab="with-me"` with its list key `held`. Nothing row 135 kept is lost,
     the dashboard's "Cases with me" figure has a list that matches it (decision 13), and Working on is still one
     tab.
   - **"Overdue only"** is the URL key `overdue=true` in all three modes. Under All it is sent as `action=overdue`
     (on the caller's own file). Under With me and With my offices it is sent as `overdue=true`, as before.
     - The quick chips stay: "Hearing this week", and "Action overdue", which toggles the same `overdue` key.
     - An incoming `action=overdue` (a round-2 bookmark) is read as `overdue=true`.
     - Query keys a mode does not read stay in the URL and are ignored. `toApiQuery` sends only the list's fields,
       for example `owner` from an old Cases with me link on the `mine` list, which refuses `owner`.
   - **Count line and paging.** "n cases", or "n of m cases" when filtered, where m is the Working on count. Paged by
     50.
9. **The side panel on Working on.** A row opens `FilePanel` ("Case details"), as Cases with me did. The case number
   remains a link to the case page.
   - The facts come from the row's brief: With (`withText`, "(you)" for the caller), Action needed, Since, Due by
     and From.
   - **The remark** is read when the panel opens, from the existing `GET /cases/{ref}/custody?order=desc&limit=1`
     (`card.remark`). It is read only for a row with a custody row.
     - That endpoint applies `shows_remark`, so the rule stays on the server and the list never carries remarks.
     - The panel shows the existing "No remark" text when the card's remark is null.
   - The panel never acts. Sending and recalling stay on the case page.
10. **Counts.**
    - **The sidebar pill** for Case inbox is `/inbox/mine/counts`.`working`, as today. The `files` pill and the
      `NavCount` value `files` are removed.
    - **The tabs:**
      - Working on, Claimed by me and Disposed show their `/inbox/mine/counts` figures.
      - Sent by me and Department cases show no count. Sent by me is a history, not a queue; Department cases is
        read per department.
      - **Pending action** shows the sum of `held` over the departments of `GET /custody/summary`, the figure
        `TrackingSummary` already reads. The request is made only when `tracksDepartment(me)`, so no other login
        makes a call that would answer 403, and no pending figure appears anywhere for a non-tracker. The figure is
        not in the sidebar pill.
11. **The page.**
    - The header is "Case inbox" with the existing subtitle.
    - `FlashNotice` (the one-time notice of a case just sent away) moves from `CasesFrame` into `InboxFrame`, above
      the tabs.
    - `CustodyDialogs`' push after a send that loses sight goes to `/inbox/sent` (it went to `/cases/sent`).
    - `CasesFrame`, `CasesIndex`, `casesTabsFor`, `CASES_TABS` and the `(list)/layout.tsx` are removed.
    - `components/files/Held.tsx`, `Sent.tsx`, `FilePanel.tsx` and `TrackingSummary.tsx` stay where they are and are
      reused. Internal names may stay (row 135, decision 2).

### C. Routes and redirects

12. **Redirects keep the query string** (`redirectTarget`, a client redirect as today). Each old address goes to
    its final place in one hop. `OLD_FILES_REDIRECTS` is re-pointed and a new `OLD_CASES_REDIRECTS` is added:

    | Old URL | Redirects to |
    |---|---|
    | `/cases` | `/inbox`, then the first tab the login may open (decision 7) |
    | `/cases/with-me` | `/inbox/working` (an incoming `?held=offices` is kept) |
    | `/cases/sent` | `/inbox/sent` |
    | `/cases/pending` | `/inbox/pending` |
    | `/files` | `/inbox/working` |
    | `/files/mine` | `/inbox/working` |
    | `/files/offices` | `/inbox/working?held=offices` |
    | `/files/department` | `/inbox/pending` |
    | `/files/sent` | `/inbox/sent` |
    | `/inbox/files` | `/inbox/working` |
    | `/inbox/claimed` | unchanged (`ClaimedRedirect`: Department cases or Working on) |
    | `/inbox/recommended`, `/inbox/pool`, `/inbox/transfers` | unchanged (`/claim/*`) |

    - The pages under `app/(portal)/cases/(list)/` (`with-me`, `sent`, `pending`) become redirect pages. They stay
      static segments, so `[ref]` never catches them; `CASES_LIST_SEGMENTS` keeps the three names and its test stays.
    - The case page stays at `/cases/[ref]`, unchanged.
    - **Breadcrumbs.** The `/cases` crumb above a case page reads **"Case inbox"** and leads to `/inbox` through the
      redirect. `CRUMB_PATHS` gains `/inbox/sent` "Sent by me" and `/inbox/pending` "Pending action". The
      `/cases/with-me`, `/cases/sent` and `/cases/pending` crumbs are removed.
    - Alerts and e-mails link to case pages only (row 135, decision 3), so no backend link changes.
13. **Links on other screens are re-pointed, not left to the redirect.**
    - **Dashboard headline** (`Headline.tsx`):
      - the "Cases with me" figure goes to `/inbox/working?held=me`, the same set as the figure;
      - "Overdue actions" goes to `/inbox/working?overdue=true`.
    - **Dashboard blocks** (`Blocks.tsx`):
      - the "Cases with me" KPI goes to `/inbox/working?held=me`;
      - the department pending link goes to `/inbox/pending`.
    - **Reports form** (`ReportPage.tsx`): the live-list link goes to `/inbox/pending`. Its line now reads "…is
      under Case inbox:".
    - The dashboard's own labels and figures are unchanged.
14. **The phone bottom bar** (`BOTTOM_BAR_KEYS`) becomes Dashboard, Case inbox and **Alerts**, because the Cases
    entry is gone.
    - Alerts carries its own unread pill and is the next most frequent daily screen.
    - Alternatives: My calendar, or two entries only. The owner may pick another at approval.

### D. Redesign rules and checks

15. **The redesign rules hold.**
    - Tokens and the kit only; no new token.
    - The lead badge sits in the 96 px `Lead` on every list.
    - The field-row rule of 23 Oct applies to the Working on filter bar with the Show control.
    - **One primary per page:** Case inbox has none (as the Cases list and the inbox had).
    - **Phones at 375 px:** every list stacks as cards. The tab strip scrolls sideways as `Tabs` already does with
      six items. The side panel is full width.
    - Motion uses the existing helpers, with the reduced-motion fallback.
16. **The wording guard** (`frontend/src/lib/wording.test.ts`, row 135, decision 6) must stay green. New user text:
    - "Sent by me", "Pending action", "All", "With me" and "With my offices";
    - the crumb "Case inbox";
    - the reports line "…is under Case inbox:".

    None uses "file" in the custody sense. `T.tabs.inbox.files` ("Cases with me") and `T.nav.files` are removed.
17. **Plan alignment.** The plan's §5.4 inbox and §5.7 custody tracking keep every function. Only where the screens
    sit changes. This is no **deviation** from the plan, and no business rule changes:
    - recommend-and-claim is untouched;
    - visibility stays on the server for every list;
    - the remark rule stays on the server.

## Data
None. No table, column, reference code or migration. Every list reads existing tables through existing services.

## Services
`backend/aslms/services/my_cases.py`, read-only:
- **`_custody_briefs(session, user, case_ids)`.**
  - The query also selects `leg.actor_name`, `leg.actor_designation` and `leg.actor_office_code`. The current leg is
    already outer-joined.
  - Each brief gains `due_soon` (decision 2, `get_settings().request_due_soon_days`, false when overdue or with no
    due date) and `sent_by` (`{name, designation, office_code}` when `actor_name` is set, else null).
  - Still no remark.
- **`_view_set` / `_state` / `mine_stmt`** for `view="working"`: `or_(and_(c.allotted, active), c.file)`, where active
  is `status in (pending, unknown)` (decision 3). The other views are unchanged. `mine_counts` follows, because it
  calls `mine_stmt`.
- **`mine(..., view="working")`** orders by:
  1. `select(_DUE.due_date).where(_DUE.case_id == Case.id, _DUE.holder_user_id == user.id, _DUE.pending_action != PendingAction.NONE)`,
     a scalar subquery, ascending, nulls last;
  2. then `Case.next_hearing_date`, ascending, nulls last;
  3. then `Case.case_no_text`, then `Case.id`.

  This is decision 4.
- **Unchanged rules:**
  - every view is ANDed with `visibility.visible_case_condition` and excludes merged cases;
  - `cases.view_scope` is required (403 otherwise);
  - reading writes nothing (no row, no audit, no event).
- The module docstring's description of Working on is updated.

`backend/aslms/api/schemas.py`: `CustodyBriefOut` gains `due_soon: bool = False` and
`sent_by: CustodySentByOut | None = None`. The response models of `/inbox/mine` and `/inbox/claimed` change
additively. `frontend/openapi.json` is regenerated and `npm run gen:api` is run.

No other service changes.

## API
No new endpoint, no new `Permission`, no visibility change.

| Method and path | Permission | Change |
|---|---|---|
| `GET /inbox/mine` | `cases.view_scope` | `custody` items gain `due_soon` and `sent_by`. `view=working` adds cases held by the caller whatever their status, and is ordered by the caller's due date, then next hearing (decisions 2-4). |
| `GET /inbox/mine/counts` | `cases.view_scope` | `working` follows the new set. |
| `GET /inbox/claimed` | as today (`cases.view_scope`; whole department with `cases.claim` or `cases.allot`) | `custody` items gain `due_soon` and `sent_by` (shared brief). |
| `GET /custody/held` (`scope=me`, `office`, `owned`) | `cases.view_scope` or `cases.view_all`; `owned` needs `custody.track` | unchanged; read by Working on's With me and With my offices, and by Pending action |
| `GET /custody/sent` | `cases.view_scope` or `cases.view_all` | unchanged; read by Sent by me |
| `GET /custody/summary` | `custody.track` | unchanged; read only for trackers (Pending action count and `TrackingSummary`) |
| `GET /cases/{ref}/custody?order=desc&limit=1` | case visibility (`require_visible`); remark by `shows_remark` | unchanged; read by the Working on side panel for the remark |
| `GET /inbox/counts` | `cases.view_scope` | unchanged; decides the Department cases tab |

## Jobs
None.

## Tests

**Backend** (`backend/tests/db/test_my_cases.py`, the scripted fixtures in `tests/db/conftest.py`):
- `test_working_includes_disposed_case_with_me`: a disposed case whose custody holder is the caller is in
  `view=working` and in `view=disposed`. A disposed case only allotted to the caller is in Disposed, not Working on.
- `test_working_order_my_due_first`: the order is my overdue file, my file due later, then an allotted case with a
  nearer next hearing, then a case with no dates. A case held by someone else with an earlier due date does not
  jump ahead.
- `test_brief_due_soon_window`:
  - `due_soon` is true within `request_due_soon_days`;
  - it is false past the window;
  - it is false when overdue (then `overdue` is true);
  - it is false with no due date.
- `test_brief_sent_by_from_current_leg`: `sent_by` names the current leg's actor snapshot. It is null for a custody
  row whose leg has no actor name.
- `test_brief_has_no_remark`: the brief carries no remark key. The remark stays on the custody card only.
- `test_working_count_matches_list`: `mine_counts()["working"]` equals the unfiltered `mine(view="working").total`.
- `test_claimed_items_carry_new_brief_fields`: an `/inbox/claimed` item's `custody` has `due_soon` and `sent_by`.
- The existing tests still pass: visibility, merged excluded, 403 without `cases.view_scope`, no writes.
- API test: the OpenAPI schema of `CustodyBriefOut` lists `due_soon` and `sent_by`.

**Frontend** (vitest):
- **`lib/routes.test.ts`:**
  - `NAV` has no `files` entry.
  - The Case inbox entry shows for a standing counsel with no department.
  - `inboxTabsFor` gives:
    - a department officer: Working on, Sent by me and Disposed;
    - an officer with `cases.claim`: Claimed by me as well;
    - a department head (whole department and `custody.track`): all six;
    - State oversight (`cases.view_all`, no track): Department cases, no Pending action;
    - no login: nothing.
  - `BOTTOM_BAR_KEYS` is Dashboard, Case inbox and Alerts.
  - `CASES_LIST_SEGMENTS` still reserves `with-me`, `sent` and `pending`.
  - The `/cases`, `/inbox/sent` and `/inbox/pending` crumbs are right.
- **Redirects** (in the inbox tests, replacing `files/cases-list.test.tsx`'s):
  - `/cases/with-me?overdue=true&q=ram` goes to `/inbox/working?overdue=true&q=ram`.
  - `/cases/with-me?held=offices` goes to `/inbox/working?held=offices`.
  - `/cases/sent` goes to `/inbox/sent`.
  - `/cases/pending?holder_department=HEALTH` goes to `/inbox/pending?holder_department=HEALTH`.
  - Every `/files/*` and `/inbox/files` target is a final address (no target is itself in a redirect map).
  - `/cases` and `/inbox` open the first allowed tab, or `/search`.
- **`InboxFrame`:**
  - It shows the six tabs per login.
  - Working on, Claimed by me and Disposed counts come from `/inbox/mine/counts`.
  - The Pending action count comes from `/custody/summary` for a tracker. **No `/custody/summary` request is made
    for a non-tracker.**
  - Sent by me has no count.
  - A tab not allowed shows "not found".
  - `FlashNotice` shows above the tabs.
- **Working on:**
  - Rows come from `/inbox/mine?view=working`.
  - The lead badge is Overdue, Due soon or New only when `with_me`; an allotted row not with me has no badge and
    "—" for Action needed, Due by and From.
  - Show "With me" calls `/custody/held?scope=me`, and "With my offices" `scope=office`.
  - `overdue=true` is sent as `action=overdue` under All and as `overdue=true` under With me; an incoming
    `action=overdue` is read as `overdue=true`.
  - The side panel fetches `/cases/{ref}/custody?order=desc&limit=1` once on opening and shows its remark. It
    fetches nothing for a row with no custody row.
- **`lib/cases.test.ts`:** `leadBadge(row, "working")` gives:
  - Overdue before Due soon before New (48 h boundary);
  - no badge when `with_me` is false;
  - no badge with no custody.
- **Shell:**
  - The sidebar has no "Cases" entry.
  - The Case inbox pill is the `working` figure; no `files` pill is read.
  - The breadcrumbs of `/inbox/sent`, `/inbox/pending` and `/cases/<ref>` ("Case inbox") are right.
- **Dashboard and reports:** the re-pointed links of decision 13 (`dashboard.test.tsx`, `reports.test.tsx`).
- **`CustodyDialogs`:** a send that loses sight pushes `/inbox/sent`.
- **Wording guard** (`lib/wording.test.ts`): green with the new strings.
- `npm run typecheck`, `npm run lint` and `npm test` pass; `ruff check` and `pytest -q` pass.

**uicheck** (`frontend/e2e`):
- **Routes:** `/inbox/working`, `/inbox/sent` and `/inbox/pending` replace `/cases/with-me`, `/cases/sent` and
  `/cases/pending`.
- **States:**
  - `/inbox/working (side panel)` at all three widths replaces `/cases/with-me (side panel)`;
  - `/inbox/working?held=offices`.
- **The redirect map** (`uicheck.spec.ts`): `/files/*` and `/inbox/files` point to the new targets. `/cases/with-me`,
  `/cases/sent` and `/cases/pending` are checked as redirects.
- **Fixtures** (`fixtures/index.ts`, `synth.ts`):
  - `/inbox/mine` working rows include a custody brief with `with_me`, `due_soon`, `overdue` and `sent_by`.
  - The `/inbox/mine` matcher reads the `view` parameter. It reads `tab` today, which the API never sends, so the
    empty-list branch never runs. This is fixed in passing.
  - A tracker login sees Pending action, and a non-tracker does not.

## Verification
1. **Static checks.** `ruff check`, `pytest -q`, and in `frontend/` `npm run typecheck`, `npm run lint` and
   `npm test`, all green.
2. **No migration.** `alembic heads` is unchanged; `docker compose --profile ops run --rm migrate` reports nothing to
   apply.
3. **API checks** (dev proxy, a department officer's session who holds one case allotted and one case sent to them,
   one with a due date tomorrow):
   - `GET /inbox/mine?view=working` lists both. The held one comes first, with `custody.with_me: true`,
     `due_soon: true` and `sent_by` naming the sender.
   - `GET /inbox/mine/counts` shows `working: 2`.
   - The remark appears only in `GET /cases/{ref}/custody`.
4. **Browser checks** (owner and tester, signed in at http://localhost:3000, at 1280, 768 and 375 px):
   - **Sidebar.** There is one "Case inbox" entry and no "Cases"; its pill equals the Working on count.
   - **Tabs per login:**
     - a department officer sees Working on, Sent by me and Disposed (and Claimed by me with `cases.claim`);
     - a department head or admin sees all six;
     - State oversight sees Department cases but not Pending action.
   - **Working on.** Badges, the Show control, Overdue only and the side panel with the remark work. A case sent
     away disappears from Working on and appears under Sent by me with the notice.
   - **Old addresses.** `/cases/with-me?overdue=true`, `/files/offices`, `/cases/pending` and `/inbox/files` land on
     the right tab with the query kept.
   - **Breadcrumb.** The case page's "Case inbox" crumb opens the inbox.
5. **`uicheck`.** `docker compose --profile uicheck run --rm uicheck` exits 0 with `findings.json` empty. The run
   directory under `./data/uicheck/` is recorded in the cycle report.
6. **Scribe.** Records this change in `docs/claude_ASLMS_design_decisions.md`, `docs/ASLMS_Process_Workflows.md`
   (the user sections that name "Cases" and "Cases with me") and CLAUDE.md's current focus.

## Open questions
None. Decisions 3 (a disposed case with me in Working on), 4 (the order), 8 (the Show control) and 14 (the third
bottom-bar entry) go beyond the owner's table. Each keeps something users have today. The owner may override any of
them at approval. Title Case labels and the multi-level side menu are row 153, after the mockup is approved.
