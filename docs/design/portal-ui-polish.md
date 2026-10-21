# Design: Portal UI polish — the advisories of the five redesign rounds, no sideways scrolling, and a real-browser check at 375, 768 and 1280 px

```
slug: portal-ui-polish
status: awaiting-approval
author: architect
date: 2026-10-21
approved_by: (pending)
```

## Context
The five redesign rounds are built (rows 101-105, design `docs/design/portal-ui-redesign.md`, approved on 20 Oct 2026).
Their reviews left advisory findings in rows 106, 107, 108, 111 and 112. On 21 Oct 2026 the owner chose "go with the
polished UI", and backlog row 115 bundles those rows into one cycle. It adds one more check: the whole portal seen in a
real browser at 375, 768 and 1280 px, because round 5 did its responsive sweep in code only (round 5, deviation 10).

The plan says nothing about screen widths, so this item does not depart from it. It keeps every rule of
`portal-ui-redesign`, in particular decisions 14 (sizes), 15 (alignment), 16 (one primary action), 18 (responsive) and
25 (Action dialogs). The advisories are taken from the review reports:
- `docs/reports/2026-10-20-portal-ui-foundation.md`, findings 3-7 (findings 1 and 2 were fixed in round 2, deviation 16);
- `2026-10-20-portal-ui-inbox-claim.md`, findings 1-5;
- `2026-10-20-portal-ui-case-calendar.md`, findings 1-2;
- `2026-10-21-portal-ui-dashboard-work.md`, findings 1-2;
- `2026-10-21-portal-ui-oversight-settings.md`, both findings.

Already in place and reused:
- the kit's `DataTable`, which shows cards on phones (`frontend/src/components/ui/data.tsx`);
- `Pagination` and `PAGE` (50, `src/lib/params.ts`);
- the `secondaryOnly` pattern of `OwnershipCard`;
- the server-file guard and the one-primary page test in `src/app/pages.test.tsx`;
- `backend/tools/portal_smoke.py`;
- the `web` service in `compose.dev.yml`;
- `tests/db/test_visibility_transfer_in.py` and `tests/db/test_dashboard_headline.py`.

Two backend reads change, and there are no new endpoints:
- `GET /cases/{ref}/ownership` adds the `cases.view_scope` check to the `transfer_in` sight;
- `GET /dashboard/me` lists a case once in "Needs your attention".

Not covered here:
- pixel-baseline (golden image) comparison of screenshots;
- running the browser check in CI;
- screenshots signed in on real data (that look stays the owner's browser checklist, as in rows 53 and 56);
- the follow-ups of reports (row 70) and audit (row 71);
- the cause-list follow-ups (row 64);
- anything needing an API field not already served.

## Decisions

### A. Round 1 advisories (row 106)
1. **The tab underline follows a tab's own width.**
   - Change: `Tabs` (`ui/layout.tsx`) observes the `<nav>` and every tab element with one `ResizeObserver`. It also
     measures again once `document.fonts.ready` resolves, when the browser has it. This covers counts arriving and
     Inter loading after first paint.
   - Alternatives: measure again on every render (layout thrash); a CSS-only underline per tab (loses the slide that
     decision 13 asks for).
2. **A bare `ref_no` in the case header stays monospace.**
   - Change: the `<h1>` in `CaseFrame.tsx` takes `cno` only when the case has `case_no_text`, and `mono` otherwise.
     This is the rule `CaseLink` already follows (redesign decision 10.1, round 1 deviation 10).
   - Alternative: always `cno`, which breaks decision 10.1.
3. **An overlay's first focus goes to the first field, never the header's Close.**
   - `useOverlay` (`ui/overlays.tsx`) focuses, in this order:
     - the first `input` (not `hidden`), `select` or `textarea` in the overlay's body;
     - else the first enabled control in the body;
     - else the footer's first control;
     - else the overlay itself (`tabIndex = -1`).
   - The header's Close is focused only when it is the only control.
   - The body and footer are marked `data-overlay-part="body|footer"` in `Dialog`, `Modal` and `SidePanel`.
   - Alternative: an `autoFocus` prop on every dialog (every caller would have to remember it).
4. **i18n lookups use `Object.hasOwn`.**
   - Change: `localeOf` and `messagesFor` (`src/lib/i18n.ts`) test `Object.hasOwn(LOCALES | CATALOGUES, code)` (ES2022
     is the target). Without this, `"toString"` or `"constructor"` resolves to an inherited property instead of
     English.
   - Alternative: `Map` catalogues, a larger change for the same effect.
5. **The Dialog `wide` JSDoc is already correct.**
   - Round 3 made `Dialog` 560 px and `wide` 720 px, and the JSDoc says so (round 3, deviation 8).
   - Nothing changes in the code. A kit test pins it: `wide` adds the wide class and the default has none.

### B. Round 2 advisories (row 107)
6. **The Transfers modal shows the clicked row's transfer.**
   - Change: in `CaseModal.tsx`, on the Transfers tab, `transfer` is the clicked row's transfer when a row was clicked.
     The server's `open_transfer` is used only when the modal was opened from an address (no row).
   - Why: "From us" with `status=all` lists accepted, declined and withdrawn transfers. Clicking one of those must not
     show a different, open transfer, and the footer's actions stay those of the clicked row's status.
7. **The modal's Orders tab pages past 50 orders.**
   - Change: `OrderRows` (`claim/OrderRow.tsx`) uses `PAGE` and the kit's `Pagination`, exactly as the case page's
     Orders tab does (`case/Orders.tsx`).
   - Alternative: "Show more" infinite loading (a second paging pattern in the portal).
8. **`transfer_in` in `case_ownership_view` also needs `cases.view_scope`.**
   - Change: in `services/ownership.py`, the sight-only check is true only for an active membership that meets all of:
     - in the receiving department;
     - reads the whole department (`whole_department`: `cases.claim` or `cases.allot`);
     - holds `cases.view_scope`.
   - This is exactly the `transfer_in` basis of `visibility.member_bases`, which returns no basis without
     `cases.view_scope`. The ownership panel and the case visibility therefore agree for every membership.
   - `mine` and `pool` in the same function are unchanged: they are recommend-and-claim's rule, outside this finding.
   - Alternative: the login-level check the router already does through `require(Permission.CASES_VIEW_SCOPE)`. It
     passes when another membership holds the function, which is exactly the gap.
9. **A test for the `inFlight` double-confirm guard** (`claim/ModalActions.tsx`). The test fires two confirms before
   the first request resolves and asserts one request. No code change.
10. **Closing a URL overlay leaves consistent history.**
    - A small shared hook, `useUrlOverlay(param)` (`src/lib/useUrlOverlay.ts`):
      - `open(value)` pushes the address with the parameter and remembers, in `history.state`, that this page pushed
        it;
      - `close()` calls `router.back()` when the current entry is the one this page pushed;
      - otherwise (an address opened directly, a bookmark or a mail link) `close()` replaces the address without the
        parameter.
    - Used by `ClaimFrame` (`?case=`) and by System health (`?api=`), which has the same push / replace pair.
    - Why: today Back after closing returns to the same list, a duplicate entry.
    - Alternative: replace on open too, which loses Back-to-close on phones.

### C. Round 3 advisories (row 108)
11. **Send file on the custody card is secondary.**
    - Change: `CustodyActions` (`workflow/CustodyDialogs.tsx`) draws Send file as `secondary`. It is used only on the
      Custody and stage tab, under the case header, which already holds the page's one primary (decision 16; round 3,
      deviation 6).
    - Alternative: a `secondaryOnly` prop as on `OwnershipCard` (no caller would pass `false`).
12. **The header's next hearing shows the printed item number.**
    - Change: `NextHearingFact` (`CaseFrame.tsx`) shows `printed_sr ?? sr_no` of the latest listing, as the Hearings
      tab does and as My calendar's `item_no` is built (`services/calendar.py`: printed number, else `sr_no`).

### D. Round 4 advisories (row 111)
13. **"Needs your attention" lists a case once for "File received".**
    - Change: in `dashboard.me_block` the `confirm_next_date` loop adds its case to `listed`, so `file_received` skips a
      case already listed as overdue, as a next date to confirm or as due soon.
    - An overdue or due-soon file action and a next date to confirm on the same case both stay. They are two different
      things to do, each with its own badge and link.
    - "File received" is only information, with no action of its own, so it is the row that gives way.
    - The headline numbers are unchanged.
    - Alternative: one row per case whatever the kinds (hides a real task).
14. **Every Upcoming hearings row has a badge.**
    - `dayWords` (`dashboard/Headline.tsx`) gives, in order:

      | Day | Badge |
      |---|---|
      | today | Today |
      | the next day | Tomorrow (red when `critical`) |
      | `critical` | In n days, red |
      | `this_week` | This week |
      | any other day of the 8-day window | In n days, neutral |

    - The last line covers hearings 2 to 7 days ahead that fall in the next calendar week. The existing message
      `T.dash.inDays` is reused.
    - Alternative: "Next week" (a new message, and less exact than the number of days next to the date chip).

### E. Round 5 advisories (row 112) and no sideways scrolling
15. **Every remaining legacy `Table` becomes a `DataTable`, and `Table` leaves the kit.**
    - Why the whole portal: row 115 asks that no screen scroll sideways on phones. Row 112 named Data collection and
      Administration, but the same `Table` is also on the case tabs, the dashboard blocks and other screens.
    - The 26 files that convert:
      - Data collection: `LoadConsole`, `Health`, `Queue`, `Duplicates`, `Discovery`.
      - Administration: `Access`, `Designations`, `UserDetail`, `Tickets`; Department mapping: `CounselCodes`,
        `CourtSearch`, `Keywords`, `Scoring`, `Watchlist`.
      - The case page: `Details`, `Documents`, `Hearings`, `Links`, `Parties`, the custody movement table in
        `CustodyTab`.
      - Elsewhere: dashboard `Blocks`, audit `BeforeAfter`, files `TrackingSummary`, next dates `CaseNextDate` and
        `ReviewList`, the `Profile` devices.
    - What stays a raw `<table>`:
      - `ReportView` (the wide report tables, kept scrollable by redesign Verification, "After round 5");
      - the cause list's `EntryTable` (already cards on phones, round 4 deviation 12);
      - the month grids `MonthGrid` and `DepartmentHearings`.
    - A source test fails on a `<table>` anywhere else under `src/components` and `src/app`.
    - Rules for the conversion:
      - Columns keep their order and headers. The case, name or other identifying cell is the `primary` cell on phones.
      - Status columns take `width: var(--lead-w)` (decision 15).
      - Numbers take `align: "right"`.
      - `hideOnPhone` is allowed only for a column whose content the card already reaches (an "Open" or "View" link
        when the row itself opens). No data is dropped on phones.
      - Inputs inside rows (scoring weights, mapping toggles) stay in their cells and become the card's label-value
        lines.
      - Long values wrap (`overflow-wrap: anywhere`) inside a card.
    - Alternative: convert only row 112's screens and keep `Table`. The browser check would then still find sideways
      scrolling on the case tabs and dashboard blocks.
16. **The server-file guard follows the components that server files render.**
    - Change: `pages.test.tsx` starts from every server file (no `"use client"`) under `src/app`. It follows their `@/`
      and relative imports through `src/components` and `src/lib`, stopping at `"use client"` files, which are the
      client boundary.
    - It checks every server file it reaches, so `AuthFrame` and anything it imports are covered.
    - The rule it enforces: a server file may import from a `"use client"` module only components (capitalised names)
      and types, never a function it would call on the server, which is the `buttonClass()` crash of round 5.
    - Alternative: list `AuthFrame` by hand (the next server component would be missed again).
17. **Recorded against round 5.** The developer appends "Round 5 follow-up, row 115" to the Deviations section of
    `portal-ui-redesign.md`, saying the legacy tables were converted here (row 112 asked for this record). Nothing
    earlier in that note is rewritten.

### F. The real-browser check (new)
18. **A Playwright check, `uicheck`, runs in Compose against the real `web` service, with a synthetic API.**
    - What it runs against:
      - the portal's real server rendering, CSS, fonts and the browser's layout engine;
      - a dummy session cookie that passes the page gate, as `portal_smoke.py` does;
      - every `/api/backend/**` and `/api/session/**` request answered in the browser from typed fixtures (Playwright
        `page.route`).
    - Why synthetic data:
      - The real sign-in needs the e-mailed code, and no code bypass is added: a dev-only token minting command would
        be a sign-in bypass on a government system.
      - No real party or note text ends up in screenshots.
      - The data can be chosen to stress the layout.
    - Not chosen:
      - a sign-in bypass;
      - reading codes from a Mailtrap inbox (a new secret and API);
      - a person typing the code into a scripted run (cannot run unattended).
19. **Where it lives.**
    - `frontend/e2e/` is a separate small package, so the portal's dependencies, its Docker image and the CI frontend
      job are unchanged:
      - `package.json` and `package-lock.json` pin `@playwright/test` exactly, plus `typescript`;
      - `playwright.config.ts`;
      - `tsconfig.json`, which maps `@/*` to `../src/*` for `import type` only;
      - `fixtures/`, `uicheck.spec.ts`, `checks.ts`, `Dockerfile`.
    - The Dockerfile:
      - is `FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble`;
      - fails the build when `PLAYWRIGHT_VERSION` differs from the exact version in `package.json`;
      - copies `frontend/src` (for the page list and the types) and the e2e package;
      - runs `npm ci` and `tsc --noEmit`, so a fixture that no longer matches `schema.d.ts` breaks the build.
    - The Compose service `uicheck` is in `compose.dev.yml` only, under profile `uicheck`:
      - build context `./frontend`, dockerfile `e2e/Dockerfile`;
      - it joins only the `edge` network and reaches `http://web:3000`;
      - `depends_on: web: service_healthy`;
      - no `env_file` and no secret;
      - it runs as the image's non-root `pwuser` with `no-new-privileges`;
      - the only volume is `./data/uicheck:/out`, which is gitignored with `data/`.
    - Run: `docker compose --profile uicheck run --rm uicheck`.
20. **What it covers.**
    - Every page route read from `src/app` at run time, as `portal_smoke.py` reads it:
      - dynamic segments are filled from the fixtures' sample case, user, office, ticket and audit ids;
      - redirect pages are followed once and recorded as redirects;
      - the public pages are opened without the cookie.
    - Three projects in Chromium: phone 375×812, tablet 768×1024 and laptop 1280×800. 768 px is below the kit's 820 px
      breakpoint, so it shows the phone layout (decision 18); 1280 px is the laptop layout.
    - Five interaction states:
      - the phone drawer open (375);
      - the Case claim modal (`/claim/recommended?case=…`);
      - System health's API card (`?api=…`);
      - the Files side panel (first row clicked);
      - the Send file dialog, step 1, on the case page.
    - The fixtures:
      - The login holds every function read from the generated schema, as `pages.test.tsx` does, with two memberships:
        a department and a directorate, both with long official names.
      - Every list carries one stress row: a party line of about 160 characters, a 60-character office name, the
        longest case number shape `WP(C)/12345/2025`, a 40-character designation, and counts above 1,00,000 in the
        Indian grouping.
      - A few lists are also seen empty (Case inbox Working on, Alerts, Files), so the empty states are checked too.
21. **What fails the run** (each finding names the route, width and element):
    - **Page overflow:** `documentElement` or `body` with `scrollWidth > clientWidth + 1`.
    - **Inner sideways scrolling:** an element with `overflow-x` `auto` or `scroll` whose `scrollWidth > clientWidth +
      1`, unless it or an ancestor carries `data-scroll-x`. Only two places carry it, with reasons in their JSDoc:
      - the `Tabs` row ("tab rows scroll sideways rather than clip");
      - `ReportView`'s scroll region.
    - **Off-screen content:** a visible element whose right edge is past the viewport, outside such a region.
    - **Sizes (decision 14):**
      - a kit `Button` (`data-ui="button"`, with the existing `data-variant` and a new `data-size`) not 36 px tall, or
        30 px for `sm`;
      - a kit text input or select (`data-ui="field"`) not 36 px;
      - at 375, a button or a link drawn as a button shorter than 36 px, except `sm` toolbars inside rows.
    - **Alignment (decision 15):** within one list, elements with the same `data-lead` kind (`lead`, `date`, `icon`)
      not of equal width (±0.5 px).
    - **One primary (decision 16):** more than one visible primary on a page outside an open dialog. The primary is
      `data-variant="primary"` or `.button-link`.
    - **Missing fixture:** a `GET` with no fixture. It is answered 404 and fails the run, so the fixtures keep up with
      the pages. Any non-`GET` request is answered 405 and fails too: the check never acts.
    - **Errors:** a console error or an uncaught page error.
22. **What it writes:**
    - `./data/uicheck/<YYYYMMDD-HHMM>/<width>/<route-slug>.png`, full-page screenshots;
    - `findings.json`;
    - an `index.html` contact sheet (routes down, the three widths across) for the owner to look through.
    - Exit status 0 only with no finding. Screenshots are not committed, and no golden image is kept: font and
      anti-aliasing churn would make a pixel diff noisy, so this item checks geometry, not pixels.
23. **The definition of done gains one line.** When `frontend/src` changes, the integrator runs `uicheck` after
    `portal_smoke.py` and records the result in the cycle report. `docs/team/definition-of-done.md` is updated in the
    same change. If the owner prefers to keep it to this item, the line is struck at approval and nothing else changes.
24. **Not in CI now.** The browser image is about 2 GB and the CI compose job does not start `web` with data. CI can
    adopt `uicheck` later without changing it.

## Data
No table, column, reference code or migration. `docs/schema/schema.md` is unchanged.

## Services
- `backend/aslms/services/ownership.py`, `case_ownership_view` (decision 8): `transfer_in` requires, on one and the same
  active membership:
  - `m.department.id == open_transfer.to_office_id`;
  - `whole_department(session, m)`;
  - `m.holds(Permission.CASES_VIEW_SCOPE)`.

  The docstring names the A5 basis and its three conditions. It is read only, so no audit row is written.
- `backend/aslms/services/dashboard.py`, `me_block` (decision 13): the `confirm_next_date` loop adds `c.id` to `listed`.
  The docstring says that `file_received` leaves out any case already listed. It is read only, so no audit row is
  written.
- Portal (`frontend/src`):
  - `ui/layout.tsx` (1); `ui/overlays.tsx` (3), with `data-overlay-part` on `Dialog`, `Modal` and `SidePanel`;
  - `ui/controls.tsx`: `data-ui` and `data-size` on `Button`, and `data-ui="field"` on the text, select and textarea
    controls;
  - `ui/data.tsx`: `Table` and its CSS removed, `numCell` removed if nothing uses it;
  - `lib/i18n.ts` (4);
  - `lib/useUrlOverlay.ts` (new, 10), used in `claim/ClaimFrame.tsx` and `system/SystemHealth.tsx`;
  - `claim/CaseModal.tsx` (6); `claim/OrderRow.tsx` (7);
  - `case/CaseFrame.tsx` (2, 12); `workflow/CustodyDialogs.tsx` (11); `dashboard/Headline.tsx` (14);
  - the 26 files of decision 15;
  - `data-scroll-x` on `Tabs` and on `ReportView`'s region.
- `frontend/e2e/` (new, decisions 18-22).
- `compose.dev.yml`: the `uicheck` service.
- `docs/team/definition-of-done.md` (23); `docs/design/portal-ui-redesign.md`, a Deviations line only (17).

## API
No new endpoint and no change of shape, so `frontend/openapi.json` stays unchanged.
- `GET /cases/{ref}/ownership`:
  - requires `Permission.CASES_VIEW_SCOPE` at login level, unchanged;
  - the visibility rule is now that of decision 8;
  - a whole-department member of the receiving department whose membership lacks `cases.view_scope` gets 404
    `no such case`, as from `GET /cases/{ref}`.
- `GET /dashboard/me`:
  - the reader dependency is unchanged: `cases.view_scope` or `cases.view_all`;
  - `attention` no longer repeats a case as `file_received` when it is already listed as `confirm_next_date`.

## Jobs
None.

## Tests
Backend (database):
- `tests/db/test_visibility_transfer_in.py`:
  - `test_ownership_view_refuses_transfer_in_without_view_scope`: a department admin membership of the receiving
    department with `cases.view_scope` removed by a per-user override gets 404 on `/cases/{ref}/ownership` while the
    transfer is requested. With the function it gets 200.
  - `test_ownership_view_transfer_in_needs_scope_on_the_same_membership`: `cases.view_scope` held only on the login's
    other membership, in another department, does not open the panel. This mirrors `member_bases`.
- `tests/db/test_dashboard_headline.py`:
  - `test_attention_lists_a_confirm_case_once`: a case with a next date to confirm and a file received within 7 days
    gives one `confirm_next_date` row and no `file_received` row.
  - `test_attention_keeps_overdue_and_confirm_on_one_case`: the two kinds stay, as decision 13 says.

Portal (vitest):
- `ui.test.tsx`:
  - `tab underline re-measures when a tab's width changes`: a fake `ResizeObserver` fires for a tab element and the ink
    moves.
  - `overlay focuses the first field, not Close`.
  - `overlay without fields focuses the body's first control`.
  - `Dialog wide adds the wide class`.
  - `Button carries data-ui and data-size`.
- `i18n.test.ts`: `inherited keys fall back to English`, for `toString`, `constructor` and `__proto__`.
- `claim.test.tsx`:
  - `a declined From-us row shows its own transfer, not open_transfer`.
  - `modal Orders pages past 50` (the second page is requested with `offset=50`).
  - `double confirm sends one request` (the `inFlight` guard).
  - `closing a modal opened from a row goes back`.
  - `closing a modal opened from an address replaces`.
- `systemHealth` test: `closing the API card goes back after opening it`.
- `case.test.tsx`:
  - `header h1 is monospace for a bare ref_no`.
  - `header next hearing shows printed_sr`.
  - `custody tab has one primary` (Send file is secondary).
- `dashboard` test: `dayWords gives In n days for a hearing in the next calendar week`. The cases are today, tomorrow,
  critical, this week, and next week on day 2 and day 6.
- One test per converted screen: `<screen> renders a DataTable with a primary cell`. It asserts the table has the
  `dataTable` class and every non-primary cell has a `data-label`. The 26 files are grouped in their module's test
  file.
- `tables.test.ts` (new, source test): `no raw <table> outside the kit, ReportView, EntryTable, MonthGrid and
  DepartmentHearings`, and `nothing imports Table from the kit`.
- `pages.test.tsx`:
  - `the guard follows server components rendered by server layouts`: the walk reaches `components/auth/AuthFrame.tsx`.
  - `a server component importing a lowercase name from a "use client" module fails`: a fixture string is passed to the
    checker function.
- `tokens.test.ts`: the spacing check covers the touched modules (it already scans every `*.module.css`).

Browser (`frontend/e2e`):
- `uicheck.spec.ts` is the check of decisions 20-21. Its helpers in `checks.ts` (overflow, inner scrollers, sizes, lead
  widths, primary count) run in the page through `page.evaluate`.

## Verification
1. Backend: `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` are green. Then
   `python backend/tools/export_openapi.py` and `git diff --exit-code frontend/openapi.json` show no diff.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test` and
   `npm run build`.
3. Compose (no migration; the worker and scheduler running the load are not recreated):
   - `docker compose build api web`, then `docker compose up -d --wait --no-deps api web`.
   - `backend/.venv/Scripts/python backend/tools/portal_smoke.py` passes.
4. `docker compose --profile uicheck build uicheck`, then `docker compose --profile uicheck run --rm uicheck`:
   - it exits 0;
   - `findings.json` is `[]`;
   - the run directory under `./data/uicheck/` holds three screenshots per non-redirect route plus the five interaction
     states, and `index.html`.
   - The cycle report records the run directory, the number of routes and screenshots, and the run time.
5. Against psql, as a department admin of a receiving department with an open transfer, after removing
   `cases.view_scope` from that membership by override:
   - `/api/backend/cases/<ref>/ownership` answers 404;
   - after restoring the function it answers 200;
   - no `audit_log` row is written by either read.
6. `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/dashboard/me` without a session answers 401.

**What the owner checks in the portal** (signed in, real data). If these are not run before the merge, the cycle report
hands them over, as in rows 53 and 56:
- On a phone, or the window narrowed to about 375 px: Data collection, Administration (Users, a user's page, Access,
  Designations, Department mapping's five tabs), a case's Hearings, Parties and Documents tabs, and the Department
  dashboard show cards. Nothing scrolls sideways except a tab row and a report table.
- A case page:
  - the header's next hearing shows the item number as printed in the cause list;
  - a case without a case number shows its `ref_no` in monospace;
  - the Custody and stage tab has one blue button, in the header.
- Administration → Users → New: the cursor is in the first field.
- Case claim → Transfers → From us → status Any: clicking a declined transfer shows that transfer. Close the window and
  press Back: the browser leaves Case claim instead of showing the same list again.
- Dashboard:
  - every Upcoming hearings row has a badge;
  - a case with a next date to confirm appears once in Needs your attention.
- Open `./data/uicheck/<run>/index.html` and look through the three widths.

## Open questions
None. The decisions that widen row 112's wording were taken within the owner's "go with the polished UI" direction, and
the owner may narrow them at approval without changing the rest:
- every legacy table across the portal (15);
- the definition-of-done line (23).
