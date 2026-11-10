# Design: More About My Work, polished (cards, aligned alerts, colours with fixed meanings, names and one Due column)

```
slug: dashboard-my-work-polish
status: proposed
author: architect
date: 2026-11-10
approved_by: (pending)
```

## Context
Backlog row 228. The owner approved the work on 10 Nov 2026; this note is the design to approve. The owner checked the
dashboard's "More About My Work" section against live dev data, signed in as a department head of SEC-EDU, and listed
nine defects. Plan section 5.1 (Dashboard) says the officer view shows "own cases, own pending actions and own alerts"
and links to the case inbox and the alerts. This row comes before row 229 (navy and cream colours) and row 230 (review
of every screen), so it uses today's tokens and adds no colour.

**What is there now (checked in the code at a956b9d).**
- `frontend/src/components/dashboard/Blocks.tsx:292-354`, `PersonalExtras`, is shown inside the `Collapsible` "More
  About My Work" (`Dashboard.tsx:198`). It has three headline `Kpi`s, then:
  - **My Cases**: a `DataTable` with `showCaption` (`:312-332`). The department cell is
    `<span className="mono">{c.department_code}</span>`.
  - **Cases with Me**: `FileList` (`:86-107`, also used by the Department view's Pending Actions card at `:227`) with
    `showCaption`. Its columns are Case, Pending Action (`f.pending_action`), Due (`formatDate(f.due_date)`) and Overdue
    (`overdue_days` or "—").
  - **My Alerts**: `<div id="alerts"><h3><Link href="/alerts">` and a `<ul>` (`:335-352`). Each row is
    `<Badge tone={severity…}>{kind_label}</Badge> {title} <CaseLink/> · {formatDate(due_at ?? created_at)}`.
- Defect 1 explained. The kit's visible caption (`data.module.css:11-15`) is drawn inside the table frame with
  `padding: var(--s2) 0`, so it starts at the frame's edge. The cells pad `var(--s4)`, so the columns start 16 px further
  in.
- Defect 3 explained. Every alert title with a case ends in `": " + case_label(case)`. `alert_rules.render_alert` and
  its helpers (`backend/aslms/services/alert_rules.py:214-330`, 337-468) build it that way. `case_label` (`:204-206`) is
  the printed case number, else the CNR, else `ref_no`. Admin ticket titles have no case. The `CaseLink` then prints
  the same number again.
- Defect 5 explained. The tone comes from `severity`. The engine raises a recommendation `high` when the case's hearing
  is within the look-ahead, `normal` otherwise (`alerts.py:595`, `:1044`). Hearing alerts are `high` or `critical`
  depending on whether the 48 hours have started (`alert_rules.severity_for_hearing`). So one Recommendation shows
  orange and two hearings show red and orange.
- **What the alert payload carries.** `alert_item` (`alerts.py:1882-1918`) returns `data`, `notified_at` and
  `created_at`. The dashboard keeps only ten keys plus `created_at` (`dashboard.py:285-303`), so `data` and
  `notified_at` are dropped.
  - Recommendation alerts hold `data.band` (`high` | `medium`) and `data.score`, from both the engine path
    (`alerts.py:597-602`) and the suggestion path (`:1046-1053`). The engine path raises only `high`, while a suggestion
    may carry either band (`ownership.py:728`).
  - `hearing_due` holds `data.hearing_date` (`alerts.py:1431-1443`), and so does `listed_tomorrow` (`:1258`).
  - The band and the hearing date are therefore held. Only the dashboard's response leaves them out.
- Defect 6 explained. `list_for_user` orders by the latest in-app notification's time, newest first
  (`alerts.py:1992`). The row shows `due_at` (the hearing time for hearing and some recommendation alerts) or the
  alert's `created_at`. An alert is notified again when its severity rises (`raise_alert`, `alerts.py:308-322`). So the
  shown date neither matches the order nor means one thing.
- Defect 7 explained. `kind_label` comes from `ref_alert_kind.label` (`alerts._labels`, `:1878`). Seeded labels are in
  sentence case ("Hearing due", "Listed for tomorrow"; `seed.py:156-165`). The seed only inserts missing codes, so
  relabelling existing rows needs a reference-data migration. Design portal-ui-polish-2, open question 3 (approved),
  left reference values out of the Title Case pass "for a later row".
- Defect 8 explained. `me_block` builds `{"department_code": m.department.code, …}` (`dashboard.py:239-260`).
  `m.department` is the membership's Department-tier `Office`, whose `name` is at hand.
- Defect 9, and a further finding. `file_item` (`dashboard.py:105-114`) returns `pending_action` as the **code**
  (`PendingAction(...).value`, for example `parawise_comments`). Every other screen shows `pending_action_label` from
  `PENDING_ACTION_LABELS` (`domain/workflow.py:65-79`; the With Me tab, the case rail, the Custody tab). The dashboard
  is the only place that prints the code.

**Not covered.**
- The rest of the dashboard: My Work's headline, Upcoming Hearings and Needs Attention panels, and the Department and
  State views. The Department view's Pending Actions card (same split Due and Overdue columns) and its other panels are
  left to row 230's findings. Its Action cell gets the label only (decision 9), a text change with no layout change.
- The Alerts page, the case Alerts tab and the e-mails (open question 1).
- Colours themselves (row 229).

## Decisions

### A. The three sections as cards (defects 1 and 2, View All)
1. **Each section is a kit `Card` with its title in the card head and a View All link in `actions`.** The sections are
   My Cases, Cases with Me and My Alerts. My Work's Upcoming Hearings panel uses the same pattern
   (`Headline.tsx:132`, "Open Calendar →"), and so do the Department view's panels. The `Block` heading pattern was
   considered but refused: it is the page-region `h2` with the generated time, a level above these sections. Inside
   each card the `DataTable` keeps its `caption` (the table's accessible name) but **drops `showCaption`**, because the
   card's heading already names it (design data-collection-redesign, decision 10). The heading then starts at the
   card's padding (`--s5`), level with the inner table's frame, exactly as on the panels above it.
   - Alternative: a flush card whose table loses its own frame, so the column text sits under the heading. Refused
     here: it is a kit change that would move every `Card` holding a table across the portal, which is a layout change
     outside this row. Row 230 can propose it (open question 4).
2. **View All targets.**
   - My Cases goes to `/inbox/my-cases` (the Case Inbox's My Cases tab, the same cases the counts come from:
     `inbox.claimed_stmt(..., whole=False)`).
   - Cases with Me goes to `/inbox/with-me`.
   - My Alerts goes to `/alerts`.
   - The visible text is `T.dash.viewAll` "View All", followed by an arrow `→` in an `aria-hidden` span, as "Open
     Calendar →" does. A visually hidden suffix names the section ("View All My Alerts"), so the three links have
     distinct accessible names.
   - The links are plain links, not gates. The target screens check their own functions.
3. **My Alerts keeps its anchor.** It becomes `<Card id="alerts">`. Nothing links to `#alerts` today; the id is kept so
   nothing breaks.
4. **Shown or hidden as today.** My Cases shows only when `cases` is not empty. Cases with Me shows only when
   `files.items` is not empty. My Alerts always shows, with its empty state "No open alerts." inside the card. Each card
   stays full width and they stay in today's order: My Cases, Cases with Me, My Alerts. Side by side was refused: at
   1280 px a half-width Cases with Me table cannot fit three columns and would fall back to cards.

### B. My Alerts as an aligned table (defects 3, 4, 5, 6 and 7)
5. **A `DataTable` with four columns: Type, Case, What Happened, Raised** (`T.dash.alertCols`). The backlog names three
   columns (type, what happened, date raised). The case gets its own column so the number appears **once**, is a link,
   and lines up from row to row for scanning, like the Case column of the other two cards.
   - **Type**: fixed width `calc(2 * var(--lead-w))` (192 px), following the alignment rule of design
     portal-ui-redesign, decision 15 (status columns get a fixed width). That width fits "Hearing · In 7 Days" on one
     line. The width follows `--lead-w`, so a later language can widen it.
   - **Case**: `CaseLink value={a.case} visible={a.case_visible}`, as today. A case the reader can no longer open is
     plain text, and an alert without a case (admin ticket) shows "—".
   - **What Happened**: the new server field `summary`, which is the title without its trailing case number
     (decision 12). It is the phone card's primary cell. It is a sentence, so it keeps sentence case.
   - **Raised**: `formatDate(a.notified_at)` in a `<time>`, with `formatDateTime` as its title.
6. **Type badges with fixed meanings; the severity no longer colours the dashboard.**
   - **Hearing alerts** (`hearing_due`, `listed_tomorrow`) show the kit `HearingDate` badge of the alert's
     `hearing_date` with `showDate={false}` and the new kit prop `label="Hearing"` (decision 13). Examples: "Hearing ·
     Tomorrow" (strong red), "Hearing · Today" (strong red), "Hearing · In 4 Days" (soft amber), "Hearing · In 12 Days"
     (plain), "Hearing · Date Passed" (warning). These are the bands of design next-hearing-highlight, counted in IST
     days by `hearingBand`. The word always says what the colour means.
     - Both kinds read "Hearing" because both are about one hearing, and What Happened says which: "Hearing on 11 Nov
       2026" or "Listed tomorrow, 11 Nov 2026, court 5". Using the kind label would read "Listed for Tomorrow ·
       Tomorrow" on the day it is raised.
     - An "around" date is not marked in the badge. The summary already says "Hearing around …".
     - A hearing alert without a `hearing_date` falls back to the neutral kind badge.
   - **Recommendation alerts** show a `Badge tone="info"` reading "Recommendation".
     - `band` `high` (strong) uses `look="solid"`; `medium` (possible) uses `look="outline"`. The `look` prop is new
       in the kit (decision 14).
     - The band is also in words: the badge's `title` and a visually hidden suffix read "Strong Match" or "Possible
       Match" (`T.dash.matchBadges`). The summary says "Strong match for SEC-EDU" or "Suggested for SEC-EDU". So colour
       and fill are never the only signal, and the visible text does not repeat "Strong Match".
     - Without a `band` (none is expected), the badge is neutral.
     - The colour is `--accent`, today's blue. Row 229 must map it to navy, not to the orange of the main button. This is
       flagged to row 229's design.
   - **Every other kind** shows a neutral `Badge` (no tone), whatever its severity. Its text is the kind label in Title
     Case (decision 7).
   - Alternatives considered:
     - Keep severity for the other kinds. Refused: severity is the engine's urgency for e-mail, and the owner asked for
       fixed meanings.
     - Colour `next_date_changed` and `next_date_review` by their date. Refused: they are not hearing alerts in the
       owner's list. Row 230 may revisit.
7. **Title Case for the kind label, in the portal, on the dashboard.** The badge text is
   `titleCase(a.kind_label)` (`frontend/src/lib/titleCase.ts`, the helper of design portal-ui-polish-2, decision 2).
   Results: "Hearing Due", "New Order", "Compliance Due", "Next Date to Review", "Next Date Reported as Wrong". A badge
   is a label under that rule. `titleCase` is idempotent, so a later relabel by migration changes nothing here. The
   labels come from seeded reference data, not from anything a person typed.
   - Alternative: a reference-data migration relabelling `ref_alert_kind` in Title Case. It would fix every screen and
     e-mail at once, but it is a migration (about an hour's deploy with the pre-migrate backup) for one word on this
     screen. Recommended as its own row (open question 1).
8. **The date shown is the date raised to you, and the order is newest first by that same date.**
   - The value is `notified_at`, the time of the alert's latest in-app notice to the reader. `list_for_user` already
     orders by it, so the date matches the order with no change to the query.
   - For almost every alert, this is when it was raised. An alert raised again because it became more urgent (a
     hearing entering its last 48 hours) counts from then and moves to the top. That is news to the reader.
   - The hearing date is no longer shown in this column: it is in the summary and drives the badge's band. `due_at` is
     no longer read by the dashboard.
   - The header is "Raised", the owner's word.
   - Alternative: the alert's first `created_at`, ordered by it. Refused: it needs a second ordering in
     `list_for_user`, and it would bury an alert that has just become urgent (open question 3).

### C. My Cases and Cases with Me (defects 8 and 9)
9. **The pending action shows the server's label, exactly as given.** `DashboardFileOut` gains `pending_action_label`
   from `PENDING_ACTION_LABELS`, the words the Send Case dialog offered and every other screen shows (for example
   "Parawise comments", "Other - see remark"). It is shown as given, not re-cased and not cut. This applies in the
   shared `FileList`, so the Department view's Pending Actions card also stops printing the code. That is a text-only
   change with no column or layout change there. The free remark typed when sending is not shown on the dashboard, as
   today (open question 2).
10. **Cases with Me: one Due column.** The Overdue column is removed. The Due cell shows one of:
    - **overdue** (`overdue_days > 0`): `Badge tone="danger"` reading "Overdue by N Days" (`T.dash.overdueByBadge(n)`,
      "Overdue by 1 Day" for one), with the due date as its title;
    - **no due date**: a muted "No Due Date" (`T.dash.dueNoneLabel`);
    - **otherwise**: `formatDate(due_date)`.

    The server's `overdue_days` decides; the portal computes nothing. Red keeps the kit meaning: urgent or overdue.
    Columns: Case (primary), Pending Action, Due. The order stays the server's (due date first, no date last). The
    Department view's Pending Actions card keeps its two columns (it is outside this row): `FileList` takes a
    `mergedDue` prop that only `PersonalExtras` sets.
11. **My Cases shows the department name, in a compact table.**
    - `DashboardOwnCasesOut` gains `department_name` (the membership's department `Office.name`). The Department cell
      shows it in the body font, with the code as its `title`; there is no mono span.
    - The number columns (Assigned, Active; Disposed; As Counsel when shown) are right-aligned with a fixed width of
      `var(--lead-w)`, so the figures sit together at the right and the name takes the rest. The row keeps the kit's
      table density, with no new size.
    - Known edge, unchanged and noted for row 230: a person with two memberships in one department gets two rows with
      the same code, and the same React key.

### D. Server and kit additions
12. **`summary` is made on the server.** A new helper `alert_rules.title_without_case(title, case)` removes a
    trailing `": " + X` from the title, where X is the case's current `case_no_text`, `cnr` or `ref_no` (the
    candidates of `case_label`, tried in that order).
    - The title is returned whole when there is no case, when no candidate matches, or when stripping would leave
      nothing. No match happens for a title cut at 300 characters, or one raised under a number since changed (a
      provisional case later numbered, or a renumbered `ref_no`). The number then shows twice in that rare row, which
      is better than a wrong cut.
    - The server already holds `case_label` and the titles, and the portal stays dumb ("the portal computes nothing",
      the `Blocks.tsx` header). Stored titles are not changed, and the alert e-mails and the Alerts page keep the full
      title.
    - Alternative: strip in the portal. Refused: the rule would be split between the two places.
13. **Kit `HearingDate` gains `label?: string`.** It is drawn first inside the badge as its own unbreakable part, then
    the separator " · " hidden from screen readers (as "Suggested" and "Around" are drawn), then the band word. Band,
    tone, `data-band` and every other prop are unchanged, and it is optional (no current caller changes). In a narrow
    cell the label and the word wrap between the parts, never inside one.
14. **Kit `Badge` gains `look?: "solid" | "outline"`**, rendered as `data-look`, for the tone's colour as a fill or as
    an outline. It uses today's tokens only:
    - `info` + `solid`: background `var(--accent)`, text `var(--surface)`;
    - `info` + `outline`: background `var(--surface)`, text `var(--accent)`, and a 1 px inset ring in `currentColor`,
      so the 22 px height does not change;
    - the other tones accept `look` the same way, but only `info` is used now.

    `tokens.test.ts` adds the pairs `--surface` on `--accent` and `--accent` on `--surface` (both above 4.5:1 today).
    Row 229 must keep them in its contrast list.

### E. Wording
15. **New strings in `messages.ts`, on the label paths of the Title Case guard** (`labels.test.ts`):
    - `dash.viewAll` "View All";
    - `dash.alertCols` `{ type: "Type", case: "Case", what: "What Happened", raised: "Raised" }`;
    - `dash.alertHearingBadge` "Hearing";
    - `dash.matchBadges` `{ high: "Strong Match", medium: "Possible Match" }`;
    - `dash.overdueByBadge(n)` (listed in `LABEL_FUNCTIONS` with samples 1 and 12);
    - `dash.dueNoneLabel` "No Due Date".

    `dash.overdueCol` stays: the Department and State views use it.

## Data
None. No table, column, reference code or index is added or changed. **No migration.** `docs/schema/schema.md` is
unchanged.

## Services
- `backend/aslms/services/alert_rules.py`: new `title_without_case(title: str, case: dict | None) -> str` (decision 12),
  taking the case reference dict of `calendar.case_ref` (`ref_no`, `cnr`, `case_no_text`). It is pure, with no
  database access.
- `backend/aslms/services/dashboard.py`:
  - `me_block`, own cases: each entry adds `"department_name": m.department.name`.
  - `me_block`, alerts: each item adds the following, built from the `alert_item` that `list_for_user` already
    returns:
    - `notified_at`: the item's `notified_at`;
    - `summary`: `title_without_case(item["title"], item["case"])`, the case reference dict already in the item, so
      no extra query;
    - `hearing_date`: `data.hearing_date` parsed as a date, only for `hearing_due` and `listed_tomorrow`, otherwise
      `null`, and `null` when missing or malformed;
    - `band`: `data.band` only for `recommendation` when it is `high` or `medium`, otherwise `null`.
  - Order, limit (`list_size`) and the visibility filter are unchanged. `case_visible` is unchanged.
  - `file_item` adds `"pending_action_label": PENDING_ACTION_LABELS[PendingAction(held.pending_action)]`. This serves
    both the personal block and the department block's pending items, which share it (`dashboard.py:323`, `:622`).
- Visibility: unchanged. Every new value comes from rows the reader already receives:
  - their own notifications, whose `data` the same reader already gets from `GET /alerts`;
  - their own memberships' departments;
  - their own held files.

  No query is added beyond what is already loaded.
- Audit and events: none. The dashboard writes nothing (design reports-dashboards, decision 13).

## API
- `GET /dashboard/me`. Permission: `cases.view_scope` or `cases.view_all` (the router's `reader`, unchanged). The
  response gains:
  - `cases[]` (`DashboardOwnCasesOut`): `department_name: str`.
  - `files.items[]` (`DashboardFileOut`): `pending_action_label: str`.
  - `alerts.items[]` (`DashboardAlertOut`):
    - `summary: str`;
    - `notified_at: datetime | None`, always set for items from `list_for_user`;
    - `hearing_date: date | None = None`;
    - `band: Literal["high", "medium"] | None = None`.
- `GET /dashboard/department?department=CODE`. Permission unchanged (an eligible membership in that department, or
  `dashboard.state`). `pending_actions.items[]` gains `pending_action_label: str` through the shared
  `DashboardFileOut`.
- All additions only; nothing is removed or renamed. `due_at` and `created_at` stay in `DashboardAlertOut` for
  compatibility, although the portal no longer reads them.
- `frontend/openapi.json` is regenerated (`backend/tools/export_openapi.py`), then `npm run gen:api` updates
  `frontend/src/lib/api/schema.d.ts`. The OpenAPI snapshot test is updated.

## Jobs
None.

## Tests
**pytest**
- `tests/unit/test_alert_rules.py`, `test_title_without_case_*`:
  - strips `": WP(C)/2695/2025"` when it is the case's `case_no_text`;
  - strips the CNR when there is no printed number, and the `ref_no` when there is neither;
  - leaves a title whose end matches no candidate (a since-renumbered case);
  - leaves a title cut at 300 characters (ending in "…");
  - leaves a case-less admin ticket title;
  - never returns an empty string;
  - for every `render_alert` kind with a case, the round trip `title_without_case(render_alert(kind, case, data)[0],
    calendar.case_ref(case))` drops exactly the case label.
- `tests/db/test_dashboard.py`:
  - `test_me_block_own_cases_files_alerts_hearings_drafts` is updated: own-case entries carry `department_name`
    ("Education" for EDU), and file items carry `pending_action_label` matching `PENDING_ACTION_LABELS`.
  - New `test_me_block_alert_items_carry_summary_notified_at_band_and_hearing_date`:
    - a hearing alert from `sweep_dates` has `hearing_date` equal to the hearing day and `band` null;
    - an engine recommendation alert has `band == "high"` and `hearing_date` null;
    - a suggestion with a `medium` recommendation has `band == "medium"`;
    - a `new_order` alert has both null;
    - every `summary` equals its title without the case label;
    - the ticket alert's `summary` equals its title.
  - New `test_me_block_alerts_newest_notice_first`: two alerts raised a day apart come newest first. When the older
    one's severity rises (a second notice), it comes first and its `notified_at` is the new notice's time. The
    `notified_at` values are non-increasing down the list.
  - `test_pending_action_sections_need_track_or_reports_function` also asserts `pending_action_label` on the
    department block's items.
- `tests/db/test_api_dashboard.py`:
  - `test_personal_alert_items_carry_case_visible` also asserts that the new keys are present and validate (summary
    non-empty, `notified_at` set).
  - A case the reader cannot open still yields `case_visible: false` with its `summary` (visibility unchanged).
- `tests/unit/test_openapi_snapshot.py`: the snapshot is updated for the four schema additions.

**vitest**
- `components/dashboard/dashboard.test.tsx`, under "More About My Work", using a `PERSONAL` fixture extended with the
  new fields:
  - Three cards with headings My Cases, Cases with Me and My Alerts. Each has a View All link with the hrefs of
    decision 2 and distinct accessible names. No table shows a visible caption, but each table is named by its caption.
  - My Cases shows "Education" and not "EDU"; the department cell has no `.mono`.
  - Cases with Me has the column headers `["Case", "Pending Action", "Due"]`. The rows show a date, an "Overdue by 3
    Days" badge with the danger tone, and "No Due Date". The action cell shows the label ("Parawise comments") and not
    the code.
  - My Alerts has the column headers `["Type", "Case", "What Happened", "Raised"]`. In each row the case number occurs
    exactly once, and the rows follow the API's order.
  - The Raised cell shows `notified_at`'s date, never `due_at`.
  - With the time faked at 12:00 IST on 10 Nov 2026:
    - a `hearing_due` with `hearing_date` the 11th has `[data-band="tomorrow"]` reading "Hearing · Tomorrow";
    - one on the 14th has `data-band="week"`;
    - a `critical` and a `high` hearing alert on the same day look the same.
  - A strong recommendation's badge has `data-look="solid"` and a possible one has `data-look="outline"`. Both have
    the tone class `info` whatever their severity, and both carry "Strong Match" or "Possible Match" as title and
    hidden text.
  - A `compliance_due` with severity `high` has no tone and reads "Compliance Due".
  - A ticket alert shows "—" in the Case column.
- The Department view's existing test still sees its "Overdue" column, and its Action cell shows the label.
- `components/ui/hearingDate.test.tsx`: `label` is drawn first, the separator is `aria-hidden`, the band and
  `data-band` are unchanged, there is no `<time>` with `showDate={false}`, and without `label` the output is byte-equal
  to today's.
- `components/ui/ui.test.tsx`: `Badge look="solid"` and `look="outline"` render `data-look`, and without `look` there
  is no attribute.
- `components/ui/tokens.test.ts`: the two new contrast pairs (decision 14).
- `lib/labels.test.ts`: passes with the new keys (and the `LABEL_FUNCTIONS` entry for `dash.overdueByBadge`).

**uicheck**
- A new interaction state, `"/ (More About My Work open)"`, at 375, 768 and 1280 px. It clicks "More About My Work"
  and waits for the My Alerts card.
- The fixture (`frontend/e2e/fixtures/index.ts`, `dashboardMe()`) adds, typed from `openapi.json`:
  - two own-case rows with names;
  - three files: overdue, no due date, and due in 5 days;
  - six alerts: hearing today and in 4 days (dates from `istDayPlus`), a strong and a possible recommendation, a
    `new_order`, and a case-less ticket.
- Expected: no finding from any rule (overflow, gutter, doubled heading, one primary). On phones the three tables
  stack as cards with What Happened on top.

## Verification
1. The developer and the tester:
   - `ruff check` clean and `pytest -q` green in `backend/`;
   - `npm run lint`, `npm run typecheck` and `npm test` green in `frontend/`;
   - `openapi.json` and `schema.d.ts` regenerated and committed.
2. The integrator runs uicheck on a private network against temporary images (runbook `docs/operations.md`
   section 16, never through Compose on the shared stack). The new state passes at all three widths, with no new
   finding elsewhere.
3. Deploy: no migration and no `init`. Images are built from a clean worktree of `main`, then the app services are
   recreated with `--no-deps --force-recreate`, carrying the court-data switch, and the web build ID is checked.
4. The owner checks, signed in at http://localhost:3000 as the SEC-EDU department head of the screenshot, with "More
   About My Work" open. Each of the nine points is checked:
   1. the card headings are level with the tables' frames;
   2. My Alerts is a card like the other two, and each heading has View All on the right, going to My Cases, With Me
      and Alerts;
   3. each alert shows its case number once;
   4. Type, Case, What Happened and Raised start at the same place on every row;
   5. hearing badges read "Hearing · Today", "Hearing · Tomorrow" (red) or "Hearing · In N Days" (soft), and
      recommendations are solid for strong and outlined for possible, with no orange among them;
   6. Raised dates run newest first;
   7. no "Hearing due" in sentence case;
   8. My Cases shows the department's name;
   9. Cases with Me has one Due column, and the pending action reads as on the case page.

   At 375 px the three lists are cards with nothing cut off.

## Open questions
Each question has a recommended answer. The design is complete with those answers; the owner may approve "with the
recommended answers".

1. **Alert kind labels in Title Case beyond the dashboard.** This row Title Cases them on the dashboard only (decision
   7). The Alerts page, the case Alerts tab, the kind filter and the e-mails keep "Hearing due" until `ref_alert_kind`
   is relabelled.
   - **Recommended:** a separate small row with one reference-data migration relabelling all 15 kinds in Title Case
     (plus `seed.ALERT_KIND_LABELS` for new databases). Row 230's report can carry it.
   - Alternative: add that migration to this row (about one hour of deploy downtime for the pre-migrate backup).
2. **"The pending action stays as typed".** The dashboard prints the action's code today (for example
   `parawise_comments`). The pending action is chosen from a list, not typed.
   - **Recommended:** show the chosen action's label exactly as the case page and the With Me tab show it ("Parawise
     comments"), not re-cased (decision 9).
   - If "as typed" meant the free remark written when sending the case: that remark is not on the dashboard today, and
     adding it would need its own visibility check. It is not proposed.
3. **Which date is "Raised".**
   - **Recommended:** the date the alert last reached you (`notified_at`), which is also the order. An alert that
     became more urgent comes back to the top with its new date.
   - Alternative: the first raise date, ordered by it, with a new ordering in the alerts query.
4. **Heading alignment.**
   - **Recommended:** the portal's panel pattern. The card heading is level with the inner table's frame, and the
     column text is 16 px further in, as on every panel of the Department view (decision 1).
   - Alternative: headings level with the column text. This is a kit change to every card holding a table across the
     portal, so it is better proposed by row 230.

## Deviations
None from the plan. Plan section 5.1 is unchanged in substance: own cases, own pending actions and own alerts, with
links to the case inbox and the alerts.
