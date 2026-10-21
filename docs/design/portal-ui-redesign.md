# Design: Portal UI redesign — one design system, Government of Assam branding, responsive screens, the new Case inbox, Case claim, My calendar, dashboard and case page

```
slug: portal-ui-redesign
status: approved
author: architect
date: 2026-10-20
approved_by: owner (nayanlhuzuri) on 2026-10-20
```

> **Owner's decision at approval (20 Oct 2026):** approved with every open question decided as recommended: (1) yes, the sight-only `transfer_in` basis for the receiving department's admin and head while a transfer is requested (read only, lost on decline or withdraw); (2) Inter replaces IBM Plex Sans and Source Serif; (3) the phone bottom bar in addition to the drawer; (4) the Department cases tab by the function rule (`cases.claim` or `cases.allot`) and for State-wide readers; (5) directorate users' unit-allotted cases count in Working on; (6) the department-wide hearing calendar stays as a second view of My calendar; (7) Export, Switch post and the green Pending badge are not built.


## Context
The owner reviewed four interactive mock-ups of a new portal look on 19-20 Oct 2026 and approved the last one. Its
copy is in the repository as the visual reference: `docs/design/ui/aslms-ui-direction-v4.html` (open it in a
browser; the tabs at the top show the design system, Dashboard, Case claim, Case inbox, Case page, My calendar and
Phone). The design tokens in its `:root`, its components and its six screen templates (Work list, Record page,
Dashboard, Action dialog, Settings, Report) are the reference for every screen. The owner's nine decisions of 19-20
Oct (look and motion; uniformity and "everything lines up"; Government of Assam branding; responsive on every device;
English now, other languages later; Case inbox and Case claim; My calendar and Alerts; dashboard; case page) are
written into the decisions below, each where it applies.

The plan: Annexure B shows "indicative UI screens ... design mockups" for the department dashboard, case inbox,
department mapping, case detail, documents and the Case Assistant. It fixes what each screen contains, not its
colours or fonts, so the new look is not a deviation from the plan. §5.1 (dashboards), §5.3 (case detail), §5.4
(department case inbox: Recommended, Claimed, Unclaimed pool, Transfers), §5.5 (hearing calendar and alerts) and
§4.2 / Table 6 (recommend-and-claim) give the content. Every one of these remains; only where things sit changes.
The one arrangement change against §5.4 is marked as a deviation (decision 9).

In place today (kept, restyled, not rebuilt): the Next.js portal in `frontend/` (TanStack Query, CSS Modules, the
backend-for-frontend relay with httpOnly cookies, CSP with nonce), the UI kit `src/components/ui`, the shell
`src/components/shell/PortalShell.tsx`, every screen of rows 11, 12, 13, 39, 41, 45, 50, 55, 59, 60 and 73, the
shared `FilterBar`, `messages.ts` (every user-facing string, apart from the navigation labels still in `routes.ts`),
`format.ts` (IST dates, Indian number grouping) and the 41+ pages that `backend/tools/portal_smoke.py` opens. Every
rule of those designs stays unless a decision below changes it. Decision 10 lists each behaviour change. The ones
that matter most: the server decides what each page offers (`actions`, `can_*`, `claimable`, counts); visibility is
enforced on the server; a case is never claimed, allotted or transferred without the user pressing the button and
confirming; there is no release or return-to-pool button; score colours and labels come from the API's `band`; IST
dates; filters in the query string, applied on the server; a case the caller cannot open is text, never a link;
reading is never audited.

Because the redesign touches every screen, it is built in five rounds (decision 2), each its own backlog row
(97-101) and team cycle. Each round keeps `portal_smoke.py` passing, adds tests, and ends with checks the owner can
make in the portal (Verification).

Not covered here: translation into Assamese or other languages, which is not built now (decision 8: only the seams
are). If it is done later with Bhashini or Sarvam AI, those are AI services, and CLAUDE.md says "All AI goes
through SourceTrace", so the owner must grant an explicit, written exception before that work is designed. Also not
covered: the Case Assistant tab (row 14); the real SourceTrace connector (row 36); the `github-and-ci` cycle built in
parallel (row 15), which this note does not touch; the official emblem file, which the owner supplies (decision 5).

## Decisions

### A. Build plan

1. **One design note for the whole redesign, five build rounds.** One note keeps the design system, the
   information architecture and the API additions consistent across screens. Each round is a separate backlog row,
   so one team cycle can build, test and review it. Alternatives: one row for everything (too large to review, and
   every screen would sit half-converted on one branch for days); a note per round (the rounds share tokens,
   components and rules, which would drift).

2. **The rounds, in order.** Each round depends only on the ones before it.
   - **Round 1, row 101 `portal-ui-foundation`: the design system and the shell.** Tokens, fonts, motion and reduced
     motion, the restyled and extended UI kit (decisions 11-20), the header with the emblem slot, the grouped sidebar
     with the phone drawer and bottom bar, breadcrumbs inside the page, the page header, the alignment rule, and the
     language seams (`lang`, locale-aware formatting, labels moved into `messages.ts`). Because every screen uses the
     kit, every page takes on the new look in this round. Their layouts are converted in rounds 2-5. No API change.
   - **Round 2, row 102 `portal-ui-inbox-claim`: Case inbox, Case claim and the case details modal.** API additions
     A1-A4 (and A5 if the owner approves question 1). The Case inbox with Working on, Files with me, Claimed by me,
     Disposed and Department cases (the full filter bar). Case claim with Recommended, Unclaimed pool and Transfers
     to us. The large details modal with its tabs, the "Why this is suggested" box, the ownership actions fixed at
     the bottom, and the collapsible orders with the PDF shown inline, Print and Download. The old inbox URLs
     redirect. Both menu entries show their counts.
   - **Round 3, row 103 `portal-ui-case-calendar`: the case page, its dialogs and My calendar.** The summary header
     with one primary action, the tabs Overview, Hearings, Orders, Documents, Notes, Timeline and More, the new
     Overview with secondary facts folded away, Send file as a three-step dialog, and the other workflow dialogs on
     the Action dialog template. API addition A6 (`GET /me/calendar`), My calendar, Alerts as its own menu entry,
     and the redirect from `/alerts/calendar`.
   - **Round 4, row 104 `portal-ui-dashboard-work`: the dashboard and the remaining work screens.** API addition A7
     (headline, upcoming and attention on `/dashboard/me`). The dashboard with greeting, five headline numbers and
     two panels, and the Department and State views. Files, Search, Cause list and My profile move onto the Work
     list and Settings templates, with cards on phones and details in a side panel.
   - **Round 5, row 105 `portal-ui-oversight-settings`: oversight, settings and the final sweep.** Reports (Report
     template), Audit log, Data collection, Administration with Department mapping and Tickets (Settings template),
     the sign-in, code, reset and first-sign-in pages and the error pages with the brand. The deprecated token
     aliases are removed (decision 11), and the whole portal is checked for alignment and at phone, tablet and
     laptop widths.
   Alternatives: four rounds as first sketched, with dashboard, administration, reports, audit and data collection
   in one round (about twenty screens and the dashboard API in one cycle; split in two so each cycle can be tested in
   a day); building the Case inbox before the design system (its screens would be built twice).

3. **The mock-up is the visual reference; this note is the specification.** Where the mock-up shows sample data or
   chrome (the dark "mockup" bar, the sample order text, a "Pending" badge drawn in green), the rules here win. Four
   mock-up elements are not built:
   - "Export" on Case claim: no list export API exists. Exports live in Reports.
   - "Switch post" under the membership: there is no acting-membership switch. The API picks the membership that
     holds the function for each action (portal-shell decision 12, user-memberships decision 6).
   - The green "Pending" badge: green means done or confirmed, so a pending case gets the neutral badge and a
     disposed case the green one.
   - The side panel's "Claim case" footer: in Case claim the large modal takes its place (owner decision 6).
   Question 7 asks the owner to confirm.

### B. Information architecture (owner decisions 6-9)

4. **Navigation, declared once in `routes.ts`, labels in `messages.ts`.** Three groups, as in the mock-up:
   - **Work:** Dashboard; Case inbox (count); Case claim (count); Cause list; Files (count); My calendar; Alerts
     (count); Search.
   - **Oversight:** Reports; Audit log.
   - **Settings:** Data collection; Administration.
   An entry shows by the same function rules as today. The new entries:
   - Case inbox: `showsInbox`, unchanged.
   - Case claim: `cases.claim`, `cases.view_all`, `cases.transfer_request` or `cases.transfer_decide`. Its tabs show
     by the API's `/inbox/counts`, as today.
   - My calendar and Alerts: the case readers, as "Alerts & calendar" today.

   Counts come from the server only:
   - Case inbox: `working` from `/inbox/mine/counts`.
   - Case claim: the sum over the login's departments of `recommended_high + recommended_medium +
     transfers_in_open` from `/inbox/counts`.
   - Files: `files` from `/inbox/mine/counts`.
   - Alerts: `unread` from `/alerts/counts`, the bell's query.

   The counts are re-read on window focus and every two minutes, like the bell. A group heading with no visible
   entry is hidden. Alternatives: Data collection under Oversight (it is operations, not oversight of cases); counts
   computed in the browser from lists (the lists are paged; the owner asked that nothing like this be computed in
   the browser).

5. **Case inbox = the user's own work** (`/inbox/*`, owner decision 6). The tabs, each its own route with its
   filters in the query string:
   - **Working on** (`/inbox/working`): active cases allotted to me or whose file is with me.
   - **Files with me** (`/inbox/files`): every file I hold, whatever the case's status, with the pending action and
     the due date.
   - **Claimed by me** (`/inbox/claimed-by-me`): active cases I claimed, or whose transfer I accepted.
   - **Disposed** (`/inbox/disposed`): disposed cases from the three sets above.
   - **Department cases** (`/inbox/department`): only where `/inbox/counts` says `whole_department: true` for the
     selected department (A4).

   The exact definitions are API A1. "Allotted to me" keeps today's Claimed-tab rule for the login's own
   membership: the officer is me, or, when my office sits below the department, the unit is in my subtree. So a
   directorate user keeps seeing the cases allotted to their directorate (question 5).

   Rows (Work list template):
   - Case number with parties under it.
   - Stage.
   - Next hearing, with the "48 h" or "This week" badge from IST dates (portal-cases decision 10).
   - "Your action": the pending action and due date of a file with me, with a red "Overdue n days" or amber "Due
     <date>" badge.
   - A chevron.

   Clicking a row opens the case page. The filter bar has quick chips (Hearing this week → `next_from` / `next_to`;
   Action overdue → `action=overdue`), Stage, and "More filters" (words, case type, year, court). It shows "n
   cases", or "n of m cases" when filtered (m = the tab's unfiltered count).

   **Department cases** has the full filter bar of the mock-up, as labelled selects:
   - Search (words), Unit, Officer (with "Not allotted"), Stage, Next hearing (Any date / This week / Next 30 days /
     Choose dates…).
   - "More filters": Case type, Year, Court, File is with (Anyone / Our department / Another department), Action
     (Any / Overdue / Due this week).
   - Removable chips for the active filters, "Clear all", and "n of m cases".
   - Its rows show unit · officer, stage, next hearing and who holds the file.
   - Active and Disposed are the Status filter (default Active).
   - The department selector of portal-cases decision 4 stays for logins in several departments, and for State-wide
     readers, who may pick any department and read it as the API allows.

   The bar keeps portal-filters' "Apply" rule: Enter or Apply applies the whole form, so a date range is never half
   applied; removing a chip or "Clear all" applies at once.
   Alternatives: Department cases visible to every member (the owner said department admins only; the server's
   whole-department rule is used, question 4); Working on computed by merging `/inbox/claimed` and
   `/custody/held` in the browser (two paged lists cannot be merged and counted correctly).

6. **Case claim = suggestions to decide on** (`/claim/*`, owner decision 6). The page subtitle keeps the rule's
   notice: "Cases suggested for your department from counsel codes and keywords. Open a case to see everything
   before you decide. Nothing is assigned automatically." The tabs:
   - **Recommended** (`/claim/recommended`, `/inbox/recommended`):
     - Columns: Case (number, case type), Parties, Next hearing (with the 48 h badge), Match.
     - Match is a badge from the API's `band`: blue "Strong · 0.950" for `high`, neutral "Possible · 0.620" for
       `medium`. The score is shown as stored, to three decimals (portal-cases decision 5).
     - Filter chips: Strong, Possible, Listed this week, Court, + More filters (the portal-filters fields of this
       list).
   - **Unclaimed pool** (`/claim/pool`, `/inbox/pool`):
     - Columns: Case, Parties, Next hearing, best score and the department it was for, departments that dismissed it.
     - The pool's portal-filters fields.
   - **Transfers to us** (`/claim/transfers`, `/inbox/transfers`):
     - Default direction In with status requested.
     - A two-way switch "To us | From us" keeps Out transfers (Withdraw) reachable, and the status filter stays.

   Rows no longer carry action buttons or signal chips. A click (or Enter on the focused row) opens the details
   modal (decision 7), where the signals and actions are. The department selector stays (portal-cases decision 4),
   and every action names the selected department. Alternatives: keeping the row buttons as well (two places for
   the same decision, and the owner asked to see everything before claiming); a side panel as in the earlier
   mock-ups (the owner chose the large modal in v4).

7. **The case details modal in Case claim.** It is a large modal (1040 px wide, up to 86% of the window height;
   full screen on phones). Its address is in the query string (`?case=<ref in dash form>`), so Back closes it and a
   link reopens it.

   **Header.**
   - Origin line: "Suggested for your department · cause list of 21 Oct", from the recommendation's origin and the
     summary's `last_listing`. A suggestion from another department shows "Suggested by FIN: <reason>".
   - Case number and parties.
   - Match badge.
   - Close (✕).
   - Four facts: Next hearing (date · court, item), Status, Filed, Owner ("Not claimed", or "Owned by FIN, claiming
     adds you as a watcher").

   **Tabs**, each loaded when first opened:
   - **Parties & advocates**: `GET /cases/{ref}/parties`.
   - **Hearings & listings**: `/hearings` and `/listings`.
   - **Orders**: `/orders`.
   - **Linked cases**: `/links`, with visible ones as links that open the case page in a new tab.
   - **Case details**: the identity and classification fields of `GET /cases/{ref}`.

   **"Why this is suggested" box**, beside the tabs (below them on phones):
   - One line per signal of the recommendation row ("Counsel code SC, SEC. EDU." with its contribution, "Keyword
     …", "Name …", "Linked …", "Watchlist", "Suggested unit …", as `signalText`).
   - A match-strength meter filled to the stored score.
   - For a pool case: the best score, its department and who dismissed it.
   - The line "Claiming makes this case your department's. It never returns to the unclaimed pool."

   **Footer**, fixed at the bottom:
   - Close on the left.
   - Then the actions the server allows, by `GET /cases/{ref}/ownership.actions` (portal-cases decision 8): Suggest
     elsewhere, Dismiss, and the one primary button "Claim for <department>".
   - For a Transfers-to-us row: Decline and the primary "Accept transfer" (`decide_transfer`, with the row's
     transfer id).
   - A State-wide reader who may not act sees Close only.

   Pressing an action does not open a second dialog on top. The footer turns into a short inline step, sliding up,
   with Back and Confirm:
   - Claim: optional note (≤ 500) and, with `cases.allot` in that department, optional unit and officer.
   - Dismiss: optional reason.
   - Suggest elsewhere: target department and required reason.
   - Accept or Decline: optional note.
   The fields, limits and refusal texts are the existing dialogs' (portal-cases decision 7).

   **After a success**: the modal closes; a notice names the action with "Open case page"; the lists, counts and
   case queries are invalidated (portal-cases decision 16). `office_required` opens the department choice.

   **Orders tab.** Each order is a collapsible row: the date in the fixed leading column, then the kind or order
   details, then a chevron. It expands smoothly to show:
   - a toolbar with Print and Download PDF, by `documents.view` and `documents.download`;
   - the stored PDF inline in an `<iframe>` of the relay's `…/orders/{id}/file?disposition=inline`, mounted only on
     first expand, while `INLINE_PDF` is true. The browser's own viewer is used: no PDF library, no new dependency,
     and the API's `Content-Security-Policy: sandbox` and `nosniff` stay.

   Print opens the same inline URL in a new tab, where the browser's viewer prints. The portal cannot script into
   the sandboxed frame, so it never calls `print()` on it. When the PDF is not stored, the row says "Not yet
   published" or "Fetch pending" (as the Orders tab). When `INLINE_PDF` is false, or the frame cannot show the PDF
   (row 53's browser check), the expanded row shows "Open in a new tab" and Download instead.

   The same collapsible order row is used on the case page's Orders tab (round 3).

   **A case the caller cannot open** (404, for example a transfer when question 1 is answered no): the modal shows
   only the row's own facts (summary, from department, reason, requested by and when), with "The full case opens
   after you accept."
   Alternatives: a PDF.js viewer (a large dependency and CSP surface; portal-cases decision 15 rejected it);
   rendering the extracted text instead of the PDF (scanned orders have no text; the owner asked for the stored PDF).

8. **My calendar and Alerts** (owner decision 7).

   **My calendar** (`/calendar`) is a month grid of the user's own dates from `GET /me/calendar` (A6), in three
   colours:
   - red: hearings of my cases;
   - amber: my action due dates;
   - blue: next dates waiting for my confirmation.

   The grid:
   - Today is marked with the blue circle (IST). Weekends are muted. Days outside the month are dimmed.
   - Previous and next month buttons and "Today". `?month=YYYY-MM&day=YYYY-MM-DD` in the query string.
   - The legend chips filter the kinds on screen. This is display only; the API returns all three.
   - A day shows up to two events and "+n more". Clicking a day fills the agenda panel (right on laptops, below on
     tablets and phones) with that day's items. Each item has a fixed-width leading badge (Hearing / Due /
     Confirm), the case link and the detail (court and item, pending action, or "Next date from order · confirm"
     with a link to the review item).
   - On phones the events become coloured dots.

   The grid is a `<table>` with a caption and weekday headers. The agenda is the accessible version (portal-files-
   alerts decision 10).

   **Department hearings view.** Whole-department members (A4's rule) and State-wide readers also get a two-way
   switch "My dates | Department hearings" (`?view=department`). It shows today's hearing calendar of
   `GET /calendar` unchanged, with the department picker for State-wide readers (portal-files-alerts decisions
   10-11), so no one loses the view they have now (question 6).

   **Alerts** (`/alerts`) becomes its own menu entry, with the tabs Alerts and Next dates to confirm
   (`next_dates.review`). Their content and rules are unchanged (portal-files-alerts decisions 7-9, portal-next-dates
   decision 1).

   `/alerts/calendar` becomes a client redirect to `/calendar?view=department` for whole-department members and
   State-wide readers, and to `/calendar` for everyone else.
   Alternatives: replacing the department calendar with the personal one (a regression for department admins,
   whose current calendar shows the whole department); a calendar library (a dependency for 42 cells).

9. **Deviation (arrangement only) from plan §5.4, flagged for the owner, who decided it.** The plan's single
   "department case inbox" with four tabs becomes two menu entries:
   - Case claim holds Recommended, Unclaimed pool and Transfers.
   - Case inbox holds the user's own work, plus Department cases, which replaces the Claimed tab.
   Every list and action of §5.4 remains, and the Claimed tab's content lives on in Department cases (whole
   department) and Working on (allotted), so nothing of the plan is lost. Recorded as a deviation because §5.4 names
   one inbox.

10. **Behaviour changes, each explicit.** Everything not listed here keeps its current rule.
    1. **Look.** portal-shell decision 17 (navy sidebar, serif headings, IBM Plex Sans) becomes the v4 tokens: a
       neutral base, a single blue accent `#1D4ED8`, the Inter typeface, and headings in Inter 600. Case numbers
       become semibold Inter with tabular figures. CNRs and `ref_no` stay monospace, because they are identifiers
       people copy (decision 12).
    2. **Header and breadcrumbs.** The header shows the emblem slot, "Government of Assam" and the portal name, then
       the search box, the bell and the avatar menu. The breadcrumb moves from the header into the page, above the
       title.
    3. **Navigation.** It is grouped, with counts. New entries: Case claim and My calendar. "Alerts & calendar"
       becomes "Alerts". Data collection moves under Settings.
    4. **Inbox split.** The Case inbox is re-scoped to the user's own work. The Claimed tab is replaced by Working
       on, Claimed by me and Disposed, plus Department cases for whole-department readers. Recommended, Unclaimed
       pool and Transfers move to Case claim. Old URLs `/inbox/recommended`, `/inbox/pool`, `/inbox/transfers` and
       `/inbox/claimed` redirect on the client, keeping the query string. `/inbox/claimed` goes to
       `/inbox/department` when the API says `whole_department`, else to `/inbox/working`.
    5. **Case claim rows.** Rows lose their Claim, Dismiss and Suggest buttons and their signal chips. The details
       modal shows the signals, and its footer holds the actions, confirmed in an inline footer step instead of a
       separate dialog. The fields, limits, refusal texts and audit are unchanged.
    6. **Score badge.** The text reads "Strong · 0.950" instead of "0.950 STRONG". The label and colour still come
       from the API's `band`, never from comparing numbers.
    7. **Calendar.** The hearing calendar becomes My calendar (personal dates of three kinds). The current
       calendar remains as the Department hearings view for whole-department and State-wide readers.
       `/alerts/calendar` redirects.
    8. **Dashboard.** A personal headline (greeting, five numbers, Upcoming hearings, Needs your attention) comes
       first for every case reader. The existing department, State and ticket blocks move, with the same figures,
       into the Department and State views and the Administration tickets panel (decision 21).
    9. **Case page tabs.** Six tabs plus More. Parties, Linked cases, Custody and stage, Alerts and Details move
       under More. The routes are unchanged.
    10. **Case page overview.** The new Overview holds Latest order and Recent activity. Parties, advocates and acts,
        and the ownership details, are folded into collapsibles. The custody card's facts move into the summary
        header; the full card stays on the Custody and stage tab.
    11. **Send file.** It becomes a three-step dialog. The fields, checks and outcome are unchanged.
    12. **Inline order PDF.** Orders show the PDF inline when expanded, in the claim modal and on the Orders tab.
        View in a new tab stays as the fallback.
    13. **Phones and tablets.** Below 820 px the sidebar is a drawer, a bottom bar appears, tables become cards and
        dialogs and modals fill the screen.
    14. **Loading.** Text-only "Loading…" becomes skeletons. The screen-reader text "Loading" stays.
    15. **Status badge colours.** Pending is now neutral (amber before) and disposed green (green before);
        "unknown" is neutral. Amber is kept for due soon only.

### C. The design system (owner decisions 1, 2 and 4; Round 1)

11. **Tokens, from the mock-up's `:root`, in `src/app/globals.css`.**
    - Colours: `--bg #F5F7FA`, `--surface #FFF`, `--surface-2 #F9FAFB`, `--border #E4E7EC`, `--border-strong
      #D0D5DD`, `--text #101828`, `--text-2 #475467`, `--text-3 #667085`, `--accent #1D4ED8` (hover `#1E40AF`, soft
      `#EEF2FF`, ring `rgba(29,78,216,.25)`), `--red #D92D20` / `--red-soft`, `--amber #B54708` / `--amber-soft`,
      `--green #067647` / `--green-soft`, `--slate-soft`.
    - Spacing: `--s1`…`--s7` = 4, 8, 12, 16, 24, 32, 48 px (the 8-point scale).
    - Type: `--t-xs`…`--t-3xl` = 12, 13, 14, 16, 20, 24, 30 px.
    - Radii: `--r-sm`…`--r-xl` = 6, 8, 12, 16.
    - Shadows: three.
    - Motion: `--ease` and `--fast 150ms`, `--med 220ms`, `--slow 320ms`.
    - Sizes: `--control-h 36px`, `--sidebar 248px`, `--lead-w 96px`, `--date-w 48px`, `--icon-w 20px`.

    Status colours have fixed meanings: red = urgent, overdue or within 48 h; amber = due soon; green = done or
    confirmed; blue = action or selection; neutral = everything else. Every text and background pair meets WCAG 2.1
    AA (4.5:1). A unit test checks the pairs used for text: the body text, `--text-3` on `--bg` and `--surface`, and
    each badge.

    The old token names (`--navy-*`, `--ink*`, `--line`, `--page`, `--danger*`, `--success*`, `--warning*`,
    `--space-*`, `--text-*` sizes, `--radius`) stay as aliases of the new values during rounds 1-4, so no CSS module
    breaks. Round 5 removes them, with a test that no stylesheet uses an alias. Alternatives: renaming every module
    in round 1 (one huge diff across all screens before their layouts are redone); a CSS-in-JS or utility framework
    such as Tailwind (a new toolchain and dependency for what CSS variables already do).

12. **Fonts, self-hosted.** Inter, through `@fontsource-variable/inter` (OFL licence, served from the portal, so the
    CSP `font-src 'self'` stays and no request leaves the network), replaces `@fontsource/ibm-plex-sans` and
    `@fontsource/source-serif-4`. `@fontsource/ibm-plex-mono` stays for CNRs and `ref_no`. That is one dependency
    added and two removed (question 2). The mock-up's Google Fonts link is mock-up chrome only. Alternatives: the
    system font stack (no dependency, but the look the owner approved differs across Windows, Android and iOS);
    keeping IBM Plex (not the approved look).

13. **Motion, with reduced motion respected.** Short transitions everywhere they help, all from the tokens:
    - fades and short slides for page content and panes (`--slow`, 6-12 px);
    - the sliding tab underline (`--med`);
    - count-up numbers on the dashboard headline (about 12 frames);
    - skeleton shimmer while loading;
    - dialog and modal easing (scale .96 → 1 with fade, `--med`), the side panel and drawer slide (`--slow`), and
      collapsibles (`grid-template-rows 0fr → 1fr`, `--slow`);
    - button hover lift (1 px), the meter fill (700 ms), and the bell dot pulse.

    Under `prefers-reduced-motion: reduce`, the tokens become 0 ms and every animation and transition is off. The
    JavaScript parts read the same media query through one `usePrefersReducedMotion()` hook: count-up shows the
    final number at once, and dialogs mount and unmount without delay. Closing dialogs and panels keep the element
    mounted for the exit duration through a small `usePresence(open, ms)` hook. No animation library. A test
    renders under reduced motion and checks that the final values show immediately and no exit delay remains.
    Alternatives: Framer Motion (a dependency, CSP-sensitive inline styles, more than these transitions need).

14. **One size per component; one control height.**
    - Buttons are 36 px (primary, secondary, ghost, danger). The `sm` size is 30 px and is used only in toolbars
      inside a row (Print, Download).
    - Inputs and selects are 36 px. Textareas are 96 px tall and resizable.
    - Badges are 22 px with a dot. Filter chips are 30 px; removable filter chips are 26 px.
    - Tabs pad 12/16 px. Cards have a 12 px radius and 16/24 px padding. Table cells pad 12/16 px.

    Every gap and padding comes from the spacing scale. A source test fails on a raw pixel spacing value (a margin,
    padding or gap that is not `0`, a token, or 1-2 px for borders) in any `*.module.css` touched by the round. It
    widens to every module in round 5.

15. **Everything lines up** (the owner's alignment rule). A badge, date or icon that leads a row sits in a
    fixed-width column, so the text after it always starts at the same place, whatever the badge says. The kit
    gives three leading columns:
    - `Lead`: `--lead-w` 96 px, for status badges.
    - `DateChip`: `--date-w` 48 px, day over month.
    - `LeadIcon`: `--icon-w` 20 px.

    `ListRow` composes them with a body and an optional trailing slot. Tables give their status columns a fixed
    width through the `DataTable` column `width`. A badge longer than its column is truncated with an ellipsis and
    its full text as the accessible name and title. This leaves room for later languages, where `--lead-w` can be
    widened per locale.

    Used by: the dashboard's Needs your attention and Upcoming hearings, the calendar agenda, the Orders rows,
    Alerts, the Files rows and the case Timeline. Tests render each of these lists and assert the leading element is
    inside a `Lead`, `DateChip` or `LeadIcon`. The reviewer treats a leading element outside them as a blocking
    finding.

16. **One primary action per screen; summary first, details on demand.**
    - `PageHeader` (breadcrumb, title, subtitle, one `primary` slot, secondary actions) gives each page at most one
      blue button.
    - Dialogs and modals have one primary in their footer.
    - Pages open on the few facts that matter. Details open in tabs, collapsibles (`Collapsible`, a `<details>`-like
      component with the animated body), the side panel (`SidePanel`) or the large modal (`Modal`).
    - A test on each converted page counts at most one element with the primary style.

17. **The UI kit after Round 1** (`src/components/ui`, CSS Modules; the existing exports keep their names and props,
    so screens compile unchanged):
    - **Restyled:** `Button` (with new variants `ghost` and size `sm`), `TextField`, `TextArea`, `SelectField`,
      `CheckField`, `RadioGroup`, `FileField`, `Table`, `Badge` (tones `danger`, `warning`, `success`, plus `info`
      for blue), `Dialog`, `ConfirmDialog`, `Tile`, `EmptyState` (with an icon circle and a title), `ErrorBanner`,
      `Notice`, `Loading` (now a skeleton with the visually hidden status text), `Pagination`, `ScoreBadge`
      (decision 10.6), `SeverityBadge`, `CaseLink`, `DefinitionList`.
    - **`Tabs`** gains the sliding underline (measured with a `ResizeObserver`) and a `count` per tab. It also takes
      a `more` group shown as a "More ▾" menu whose trigger shows the current tab's label when one of its items is
      active.
    - **New:** `Card` (with head and body), `PageHeader`, `Chip` and `ChipGroup`, `FilterChip` (removable), `Kpi`
      (label, count-up value, sub line in a status tone, optional link), `Skeleton`, `Collapsible`, `Menu` (an
      accessible dropdown: button, `aria-expanded`, arrow keys, Escape), `SidePanel` (right drawer, 480 px, full
      width on phones), `Modal` (large, header / scrolling body / fixed footer, full screen on phones), `Stepper`
      (the progress bars and "Step n of 3 · …" line), `Lead`, `DateChip`, `LeadIcon`, `ListRow`, `Meter`, `KvList`
      (two-column facts), `DataTable` (decision 18), `SegmentedSwitch` (two or three options, `role="radiogroup"`).
    - **Shared dialog behaviour:** `Dialog`, `Modal` and `SidePanel` share one focus trap, Escape to close, focus
      return, `aria-modal`, scroll lock of the page, and the easing of decision 13.

18. **Responsive on every device (owner decision 4), laptop first.** Three widths:
    - **Laptop, ≥ 1100 px:** the full layout.
    - **Tablet, 820-1099 px:** the sidebar stays; two-column panels stack; the headline numbers drop to three per
      row; the filter grid to two per row.
    - **Phone, < 820 px:**
      - The sidebar becomes a drawer, opened by the menu button in the header (slide, overlay, Escape and overlay
        click close it, focus trapped). The header shows only the emblem slot, the portal name, the bell and the
        avatar, and the search box moves into the drawer's top.
      - A bottom bar shows up to three of the login's first entries among Dashboard, Case inbox and Files, plus
        "More", which opens the drawer (question 3).
      - Tables become cards: `DataTable` renders each row as a card with its primary cell on top and the other
        cells as label-value lines. Columns marked `hideOnPhone` are left out.
      - Dialogs, modals and the side panel fill the screen. The headline numbers sit two per row. The calendar shows
        dots.

    `DataTable` is one DOM: a real `<table>` on wide screens and the same rows restyled as cards by CSS, with
    `data-label` on each cell, so screen readers get one structure. Existing `Table` uses scroll horizontally on
    phones until their screen's round converts them. Touch targets are at least 36 px tall, as the control height.
    Alternatives: two DOMs, a table and a card list (double the markup and tests); a component library (a large
    dependency and a second design language).

19. **Skeletons and empty states everywhere.** While a list or panel loads it shows skeleton rows in the shape of
    its content, keeping the visually hidden `role="status"` "Loading" text. An empty list shows the icon circle,
    a title ("Nothing waiting") and one line saying when items appear. Errors keep `ErrorBanner` with Retry.

20. **Accessibility stays at WCAG 2.1 AA**, as portal-shell decision 17:
    - visible focus (the 4 px accent ring);
    - labels on every field;
    - `aria-current` on the navigation and on tabs;
    - `aria-selected` and `role="tablist"` on in-page tabs (the modal's);
    - keyboard use of rows (Enter opens), menus, chips and the calendar grid;
    - the skip link.
    Colour is never the only signal: badges carry words, and calendar dots carry an accessible name ("22 October: 1
    hearing, 1 action due").

### D. Screens (owner decisions 3, 8, 9)

21. **Header with Government of Assam branding (owner decision 3, Round 1).** From left to right: the menu button
    (phones only), the emblem slot, the brand text, the search box, the bell, the avatar menu. The brand text is
    "GOVERNMENT OF ASSAM" in small capitals over "Legal Case Monitoring Portal". On phones only the portal name
    shows.

    **The emblem slot.** No emblem is drawn, traced or approximated anywhere in the code or the repository.
    - Until the owner supplies the official file, the slot is a clearly marked placeholder: a 40 × 40 dashed box
      reading "Emblem", titled "Place for the official Government of Assam emblem", hidden from screen readers.
    - The configuration point is one module, `src/lib/brand.ts`, with `BRAND.emblem: { src, width, height } |
      null` (null today). To install the emblem, the owner places the official file in `frontend/public/brand/`
      (SVG, or PNG at least 160 px high) and sets `src`, then the `web` image is rebuilt.
    - With a file set, the header shows `<img alt="Emblem of the Government of Assam">` at 40 px high.

    The same slot and brand appear on the sign-in, code and reset pages (round 5) and in the drawer's top. Tests
    cover the placeholder when null, the image and alt text when set, and that nothing under `public/brand/` is
    committed by the build team.
    Alternatives: an environment variable for the path (it is a build-time asset; a constant is simpler and
    tested); drawing a stand-in emblem (forbidden by the owner).

22. **Sidebar and memberships (Round 1).**
    - Groups with uppercase labels. Entries are 38 px high with an icon in the 20 px leading column. The current
      entry has the soft accent fill and the 3 px bar on its left.
    - Counts sit in a pill at the right.
    - At the foot is the membership card: the person, the primary membership's designation and office, and the
      existing "n offices" disclosure (portal-shell decision 12). There is no "Switch post" (decision 3).
    - Icons are inline SVG components in `src/components/shell/icons.tsx` (stroke 2, 18 px), with no icon library.

23. **Dashboard (owner decision 8, Round 4).**

    **Greeting.** "Good morning / afternoon / evening, <first name>", by the IST hour, with the primary membership's
    office and the IST date ("Tuesday, 21 October") under it.

    **Primary action.** "Review cases to claim" when `headline.to_claim` is above zero and Case claim shows, else
    none.

    **Five headline numbers** (`Kpi`, count-up), each a link to its list:
    - Cases to claim: "5 strong · 7 possible" → `/claim/recommended`.
    - Hearings this week: "2 within 48 hours" in red → `/calendar`.
    - Files with me: "1 due today" in amber → `/inbox/files`.
    - Overdue actions: "Oldest 6 days" in red → `/inbox/files?action=overdue`.
    - Next dates to confirm: "From new orders" → `/alerts/next-dates`.
    All figures come from `headline` (A7). A number whose gate fails (`null`) is not shown, and the grid closes up.

    **Two panels.**
    - Upcoming hearings: `upcoming`. Each row has the `DateChip` (red within 48 h), the case number and parties, and
      a badge (Tomorrow / In 2 days / This week from the API's `critical` and `this_week`, with the day words from
      IST dates). "Open calendar →" links to `/calendar`.
    - Needs your attention: `attention`. Each row has a `Lead` badge (red Overdue, amber Confirm, amber Due soon,
      blue New), a bold title and a muted line (case number · detail). Each row links to the case, or to the review
      item for a next date.

    **The Department and State views.** A `SegmentedSwitch` "My work | Department | State" shows only when the login
    has more than one view: the department view when `/dashboard` lists departments, the State view with
    `dashboard.state`. The department and State views keep today's figures (reports-dashboards decisions 9-11) in
    the Dashboard template: their numbers as `Kpi`s, their lists as panels. A State-wide reader without personal work
    opens on State. The tickets panel (dashboard ticket panel, 11 Oct) stays in the State view for the super admin.
    Nothing is computed in the browser beyond the greeting and day words.

24. **Case page (owner decision 9, Round 3).**

    **Summary header** (a card):
    - Case number (24 px), the status badge (decision 10.15) and an ownership badge ("Your department" when the
      caller's department is the primary owner, else the owner's code).
    - The parties line.
    - Four facts:
      - Next hearing: date · court, item from the latest listing, with the 48 h or week badge.
      - File is with: "You · <designation>", or the holder officer and designation, or the office.
      - Stage: label.
      - Owner: department name, or "Not claimed".
    - The banners for provisional, merged and not-fetched cases stay (portal-cases decision 10).

    **Primary actions at the right**, one primary at most, chosen by a fixed order among the flags the server
    returns:
    - the primary is Send file (`custody.can_send`), else Claim (`ownership.actions.claim`), else Accept transfer
      (`decide_transfer`);
    - Add note shows as a secondary button when `note_mode` is set;
    - a "More actions" `Menu` holds Recall (`can_recall`), Set stage, Upload document (`upload`), Enter next date,
      Allot, Take over, Request transfer, Stop watching, Suggest, Dismiss and Audit trail, each shown by its existing
      flag or function.

    **Tabs**, each its own route as today, with the API's `counts`: Overview, Hearings, Orders, Documents, Notes,
    Timeline, and More ▾ (Parties, Linked cases, Custody and stage, Alerts, Details).

    **Overview**, two columns stacking below 1100 px:
    - **Latest order** card: date, kind and the order's short text (`order_details`) when given. The collapsible
      order viewer of decision 7 shows the PDF. The next-date block of portal-next-dates (the amber notice "Next date
      suggested from this order: 19 Nov — please confirm", with Confirm / Not correct / Enter next date by the
      `next_dates` flag) and "All orders →" follow. A collapsible "Show parties, advocates and acts" holds the first
      petitioner and respondent with advocates, the counsel codes and the acts, with "+ n more" to Parties.
    - **Recent activity** card: the five latest timeline entries on the timeline rail, with "Timeline →".
    - Below, a collapsible "Ownership and recommendations" holds today's Ownership card (primary owner, unit,
      officer, watchers, recommendations with signals, open transfer).
    - The muted line "You see this case as: …" stays at the foot.

25. **Action dialogs (Round 3).** Every workflow dialog uses the Action dialog template:
    - fixed width 560 px (720 px for the note composer);
    - header with title and the case number;
    - scrolling body;
    - footer with Cancel or Back on the left and one primary on the right;
    - full screen on phones.

    **Send file** is a three-step dialog with the `Stepper`:
    1. Who receives it: department, search, and the people as selectable cards (avatar initials, name,
       designation), from `/custody/recipients`.
    2. What they should do: pending action (required), due date within the bounds and its hint, optional stage.
    3. Remark and confirm: remark (required, with the character counter), the drafts notice ("Your 2 draft notes
       become permanent when the file is sent"), and the summary line.

    Continue checks the step's required fields before moving on. Back keeps what was entered. The last step's
    primary is "Send file". The request, the refusal texts, the send-away handling (portal-files-alerts decision 14)
    and the audit are unchanged.

    Recall, Set stage, the note composer, the upload dialog, document visibility and archive, and the next-date
    dialogs keep their fields and rules on the new template.

26. **The remaining screens onto the templates (Rounds 4 and 5).**
    - **Work list** (DataTable, filter bar, cards on phones, details in a `SidePanel`): Files (the row's card details
      and full remark in the panel), Search (local results; court search keeps its form and outcome texts), Cause
      list (the day bar and bench choice on top, entries in court order with the fixed leading column for
      court · item, Claim through the existing dialog), and Alerts (the alert's body and actions in the panel).
    - **Report:** Reports, with the choices on top, results below and the Excel and PDF downloads always in the
      header's secondary actions.
    - **Settings** (a sub-menu of tabs on the left on laptops, a select on phones, one setting group at a time):
      Administration (users, user types, offices, designations, Department mapping, tickets) and My profile.
    - **Audit log** and **Data collection**: Work list and Dashboard templates respectively, with their rules
      unchanged (portal-audit-health, data-load-console).
    - **Public pages:** the sign-in, code, reset and first-sign-in pages with the brand (decision 21). The error
      and not-found pages use the empty-state pattern.
      *Amended by the owner, 20 Oct 2026:* template **A, the split panel**, replaces the centred card. The visual
      reference is `docs/design/ui/aslms-sign-in-templates.html`, tab A. On laptops:
      - the left half is a deep-blue panel with "Government of Assam", the full name "Assam State Litigation
        Management System", one line on what it is for, and three short benefit tiles;
      - the right half is white, with the official emblem (`BrandLockup`), the form, the two-step indicator
        ("Password, then a code sent to your e-mail") and "Forgot password?".
      On phones the panel shrinks to a header above the form and the benefit tiles are hidden. The same frame serves
      the code, reset and first-sign-in pages, with only the right half changing. Every password field has the
      show / hide button that is already in `TextField`. The Gauhati High Court is not named on these pages. The
      tiles' text lives in `messages.ts` like all other text.

### E. Languages (owner decision 5; Round 1)

27. **English only now, ready for other languages.** These are seams only; no second language is built.
    - **Strings.** Every user-facing string lives in `src/lib/messages.ts`. The navigation, tab, breadcrumb and
      group labels move there from `routes.ts`. A test fails on a JSX text literal or a `label: "…"` outside
      `messages.ts`, apart from an allowlist: code, symbols, case data.
    - **The `Messages` type.** `messages.ts` exports it (`typeof T`). A new `src/lib/i18n.ts` holds `LOCALES = {
      en: { code: "en", htmlLang: "en", intl: "en-IN", dir: "ltr" } }`, `DEFAULT_LOCALE = "en"` and
      `messagesFor(code): Messages`, which returns the English catalogue for now. A test checks that every
      catalogue in `LOCALES` has the same keys and function arities as English, so a future catalogue cannot miss a
      string.
    - **The page's language.** `<html lang dir>` comes from the locale, as `lang="en" dir="ltr"`.
    - **Dates and numbers.** `format.ts` takes the locale. For `en` it keeps today's fixed month names and Indian
      grouping, so every output and every existing test is unchanged. For any other locale it uses
      `Intl.DateTimeFormat(locale.intl, { timeZone: "Asia/Kolkata", … })` and `Intl.NumberFormat`. Weekday and month
      names on the calendar and the greeting come from the same functions.
    - **Longer text.** No fixed widths on text containers except the leading columns (`--lead-w`, adjustable per
      locale). Buttons, tabs and chips may wrap or scroll rather than clip; tab rows scroll sideways.
    - **The translation provider seam.** Catalogues are static files produced offline and reviewed by people. The
      portal never calls a translation service at run time. A future tool may draft catalogues through a provider
      such as Bhashini or Sarvam AI only after the owner's written exception to the SourceTrace rule (Context).
      Nothing of that is built now, and no provider interface or credential is added.
    Alternatives: an i18n library such as next-intl (a dependency before a second language exists; the seams above
    make adopting one later mechanical); run-time machine translation (an AI call outside SourceTrace, forbidden
    without the exception).

### F. Server additions (read-only; Rounds 2-4)

28. **The new lists and figures are computed on the server, with visibility applied.** "Working on", "Claimed by
    me", the Department cases filters, the whole-department flag, My calendar and the dashboard headline are
    read-only API additions A1-A7 (section API). The browser only displays them. Every one is ANDed with
    `visibility.visible_case_condition`, needs the same function as its neighbour endpoint, writes nothing (no
    row, no audit, no event; reading is never audited), and adds no table, column or migration. If the integrator
    measures a list above one second on the dev database, an index migration becomes a follow-up row, not part of
    this item.

## Data
None. No table, column, reference code or migration. `docs/schema/schema.md` and `napix_coverage.md` are unchanged.
The new endpoints read `case_ownership` (including its `actor_user_id` snapshot), `custody`, `case_stages`,
`next_dates`, `causelist_entries` and `cases` through the existing visibility rules. The latest migration stays
0020.

## Services

### Backend (Rounds 2-4)
- **`backend/aslms/services/my_cases.py`** (new, round 2):
  - `MyConditions` (dataclass: `allotted`, `file`, `claimed`, conditions over `Case`) and `my_conditions(session,
    user)`. For each active membership with a department: `allotted` is `EXISTS case_ownership` under
    `visibility.claimed_conditions(session, m, m.department, case_state="all", whole=False)`, OR-ed over the
    memberships. `file` is `EXISTS custody WHERE holder_user_id = user.id`. `claimed` is `EXISTS case_ownership WHERE
    role = primary AND status = active AND actor_user_id = user.id AND office_id IN (the caller's active membership
    departments)`.
  - `my_cases_condition(session, user)`: `allotted OR file OR claimed`, OR the counsel basis of a standing-counsel
    membership (used by the calendar and the dashboard).
  - `mine(session, user, *, view, filters, stage, action, limit, offset) -> inbox.Page`: the views of A1, always
    ANDed with `visible_case_condition` and `merged_into_case_id IS NULL`. It needs `cases.view_scope` (`Forbidden`
    otherwise); a bad `view`, `stage` or `action` raises `InboxError` (400).
  - `mine_counts(session, user) -> dict`.
  - `case_briefs(session, user, case_ids) -> dict[case_id, {stage, custody, allotment, owner_code}]`: batched, with
    the latest `case_stages` row per case (DISTINCT ON), `custody` joined to offices, users and memberships, and the
    active primary ownership (unit, officer, office code). It is shared with `inbox.claimed`.
- **`services/inbox.py`** (round 2):
  - `claimed(...)` and `claimed_stmt(...)` gain `unallotted`, `stage`, `holder` and `action`.
  - `ownership_item` adds `stage` and `custody` from `case_briefs`.
  - `_counts_for` adds `whole_department`: `view_all or (mine is not None and visibility.whole_department(session,
    mine))`.
- **`services/visibility.py`** (round 2, only if question 1 is answered yes): in `member_bases`, for a
  whole-department membership, the sight basis `("transfer_in", EXISTS ownership_transfers WHERE case_id = Case.id
  AND to_office_id = dept.id AND status = 'requested')`. It is not in `WORKING_BASES`, so it grants no write; the
  record rules for notes and documents apply as for `recommended`. `case_ownership_view` and `available_actions` in
  `services/ownership.py` treat `transfer_in` like `recommended` for reading.
- **`services/calendar.py`** (round 3): `my_calendar(session, user, *, from_, to, now, critical_hours, sitting_time,
  review_cfg)`, as A6. It reuses `hearing_rows` with `my_cases_condition`, `custody` for action dues, and
  `next_dates.queue_subquery` / `review_condition` for the confirm items. The range rules are those of
  `calendar_for_user` (`CalendarError` → 422).
- **`services/dashboard.py`** (round 4): `me_block` adds `headline`, `upcoming` and `attention` (A7), reusing
  `my_calendar` for the hearings, the `HELD` alias for files, `inbox.recommended_stmt` for the claim counts, and
  `next_dates.queue_count` for the confirm count. The existing fields are unchanged, under the same statement
  timeout.
- **Routers:** `routers/inbox.py` (`GET /inbox/mine`, `GET /inbox/mine/counts`, the new `/inbox/claimed` query
  parameters), `routers/alerts.py` (`GET /me/calendar`, next to `/calendar`), `routers/dashboard.py` (unchanged
  path). **`api/schemas.py`:** `StageBriefOut`, `CustodyBriefOut`, `AllotmentOut`, `MyCaseOut`, `MyCaseListOut`,
  `MyCaseCountsOut`, `MyCalendarItemOut`, `MyCalendarOut`, `DashboardHeadlineOut`, `DashboardAttentionOut`; added
  fields on `OwnershipOut`, `InboxCountsOut` and `DashboardMeOut`. **`frontend/openapi.json`** and
  `src/lib/api/schema.d.ts` are regenerated (`test_openapi_snapshot`).

### Portal (`frontend/src`)
- **Round 1:**
  - `app/globals.css` (tokens, aliases, reduced motion).
  - `app/layout.tsx` (Inter, `lang` and `dir` from `lib/i18n.ts`).
  - `components/ui/*` (decision 17; split into `ui/index.tsx` re-exporting `ui/controls.tsx`, `ui/feedback.tsx`,
    `ui/overlays.tsx`, `ui/data.tsx`, `ui/layout.tsx` so no file passes about 600 lines).
  - `components/ui/motion.ts` (`usePrefersReducedMotion`, `usePresence`, `useCountUp`).
  - `components/shell/*` (header, brand, sidebar groups and counts, drawer, bottom bar, icons, breadcrumbs inside
    `PageHeader`).
  - `lib/brand.ts`, `lib/i18n.ts`; `lib/format.ts` (locale parameter); `lib/routes.ts` (groups, labels from
    `messages.ts`); `lib/messages.ts` (labels, brand, new screens' strings).
- **Round 2:**
  - `components/inbox/*` re-scoped: `InboxFrame` (five tabs), `MyCases.tsx` (four views), `DepartmentCases.tsx` (the
    filter grid, chips, columns).
  - `components/claim/*`: `ClaimFrame`, `Recommended`, `Pool`, `Transfers`, `CaseModal`, `WhyBox`, `ModalActions`
    (the inline footer steps reusing the bodies of `inbox/dialogs.tsx`), `OrderRow` (shared with the case Orders
    tab).
  - `lib/filters.ts` (new list keys `mine`, `department`, with `unit`, `officer`, `stage`, `holder`, `action`).
  - The routes `app/(portal)/inbox/{working,files,claimed-by-me,disposed,department}` and
    `app/(portal)/claim/{,recommended,pool,transfers}`, and the client-redirect pages for the old paths.
- **Round 3:**
  - `components/case/CaseFrame.tsx` (summary header, More tabs, actions menu), `Overview.tsx`, `Orders.tsx` (uses
    `OrderRow`).
  - `components/workflow/CustodyDialogs.tsx` (Send file stepper) and the other dialogs on the template.
  - `components/calendar/*` (`MyCalendar`, `MonthGrid` with three kinds and dots, `DayAgenda`; the old `Calendar`
    becomes the Department hearings view).
  - `components/alerts/AlertsFrame.tsx` (two tabs).
  - `app/(portal)/calendar/page.tsx`, the `/alerts/calendar` redirect.
- **Round 4:** `components/dashboard/*` (headline, panels, views), `components/files/*`, `components/search/*`,
  `components/causelist/*`, `components/profile/*`.
- **Round 5:** `components/reports/*`, `components/audit/*`, `components/data/*`, `components/admin/**`,
  `components/auth/*`, `app/(public)/layout.tsx`, `app/(welcome)/layout.tsx`, `app/error.tsx`, `app/not-found.tsx`;
  token aliases removed.

No new npm dependency other than `@fontsource-variable/inter` (decision 12). No audit or event is written by any
portal change: every write still goes through the existing endpoints, which audit as today.

## API
All additions are read-only and need no new `Permission`. Every response is filtered on the server by the caller's
case visibility.

- **A1. `GET /inbox/mine`.** Function: `cases.view_scope` (403 without it). Query:
  - `view`, required: `working` | `files` | `claimed` | `disposed`;
  - the inbox case filters (`inbox_filter_query`: `q`, `listed_from`, `listed_to`, `court_no`, `bench`,
    `next_from`, `next_to`, `case_type`, `year`, `case_status`);
  - `stage`: a `ref_case_stage` code, or `none` for no stage set;
  - `action`: `overdue` | `due_week`, on the caller's file;
  - `limit` (≤ 200, default 50) and `offset`.

  The views, with A = allotted, F = file and C = claimed as in Services:

  | view | rows | order |
  |---|---|---|
  | `working` | (A ∪ F) and the case is `pending` or `unknown` | next hearing (nulls last), then due date, then case |
  | `files` | F, any status | as `/custody/held?scope=me` |
  | `claimed` | C, active | as `working` |
  | `disposed` | (A ∪ F ∪ C) and the case is `disposed` | as `working` |

  Response `MyCaseListOut { items: MyCaseOut[], total }`. Each `MyCaseOut`:
  - `case`: `CaseSummaryOut`;
  - `owner_code`;
  - `stage`: `StageBriefOut { stage, label, phase } | null`;
  - `custody`: `CustodyBriefOut | null`, with `holder_office`, `holder_user { full_name, designation } | null`,
    `with_me`, `pending_action`, `pending_action_label`, `since`, `due_date`, `overdue`, `overdue_days`. There is
    no remark; the remark stays on the case's custody card under custody-workflow decision 25;
  - `allotment`: `{ unit: OfficeRefOut | null, officer: UserRefOut | null } | null`;
  - `reasons`: the subset of `allotted`, `file`, `claimed` that put the row here.

  Errors: 400 for a bad `view`, `stage`, `action` or filter (the shared messages). An `owner` filter is refused as on
  the other inbox lists.
- **A2. `GET /inbox/mine/counts`.** Function: `cases.view_scope`. Response `{ working, files, claimed, disposed }`,
  unfiltered, under A1's rules.
- **A3. `GET /inbox/claimed`, additions.** Function and department rules unchanged (`cases.view_scope`; the
  department named by `office` under `target_department`). New query parameters:
  - `unallotted`: `true` keeps rows with no officer. Combined with `officer_user_id` it is a 400.
  - `stage`: a `ref_case_stage` code, or `none`. It matches the case's latest `case_stages` row.
  - `holder`: `department` | `elsewhere`. The custody holder office is inside or outside the department's subtree.
  - `action`: `overdue` (custody `due_date` < today IST, pending action not `none`) | `due_week` (today ≤ due ≤
    today + 7, pending action not `none`).
  Items (`OwnershipOut`) gain `stage: StageBriefOut | null` and `custody: CustodyBriefOut | null` (where `with_me`
  is relative to the caller). Errors: 400 for bad values.
- **A4. `GET /inbox/counts`, addition.** Each department block gains `whole_department: bool`: the caller's
  membership there holds `cases.claim` or `cases.allot`, or the caller holds `cases.view_all`. The portal shows
  Department cases and the Department hearings view by it.
- **A5. Visibility basis `transfer_in`.** Only if the owner answers question 1 yes. It changes no path. A case with
  a requested transfer to the caller's department becomes readable (`GET /cases/{ref}` and its tabs,
  `/cases/{ref}/ownership` with `actions.decide_transfer`) by that department's whole-department memberships, as
  `recommended` does today. It is sight only, never a working basis.
- **A6. `GET /me/calendar`.** Function: `cases.view_scope` or `cases.view_all` (the `/calendar` dependency).
  Query: `from`, `to` (IST dates; at most 62 days; default the current month's grid, from the Monday on or before
  the 1st to the Sunday on or after the last day). 422 for a bad range.

  Response `MyCalendarOut { items: MyCalendarItemOut[] }`. Each item has `date`, `kind`, `case` (`AlertCaseOut`)
  and `critical`, plus the fields of its kind:

  | kind | rows | extra fields |
  |---|---|---|
  | `hearing` | `calendar.hearing_rows` over `my_cases_condition`; one row per case and date | `court_no`, `item_no`, `purpose`, `source`, `this_week`; `critical` from `calendar.flags` |
  | `action_due` | `custody.holder_user_id` = caller, pending action not `none`, due date in range | `pending_action`, `pending_action_label`, `overdue`; `critical` = overdue or due within 48 hours |
  | `confirm` | the caller's next-date review queue items of kind `confirm` (`review_condition`), dated by the proposed next date; none without `next_dates.review` | `next_date_id`, `source` |

  Order: date, then kind (hearing, action_due, confirm), then case. Every row is ANDed with
  `visible_case_condition`.
- **A7. `GET /dashboard/me`, additions.** Function and rules unchanged.
  - `headline`:
    - `to_claim: { high, medium } | null`: summed over the departments where the caller's membership holds
      `cases.claim`; null when none.
    - `hearings_week: { total, within_48h }`: A6 hearings, today to today + 7.
    - `files_with_me: { total, due_today }`.
    - `overdue_actions: { total, oldest_days }`: files with me whose pending action is overdue.
    - `next_dates_to_confirm: int | null`: null without `next_dates.review`.
  - `upcoming`: up to `list_size` A6 hearing items in the next 7 days (`date`, `case`, `court_no`, `item_no`,
    `critical`, `this_week`).
  - `attention`: up to `list_size` items `{ kind, case, title, date, detail }`, in this order:
    1. `overdue_action`: files with me overdue, oldest first;
    2. `confirm_next_date`: earliest first, with `next_date_id`;
    3. `due_soon`: files with me due within the existing `request_due_soon_days` setting;
    4. `file_received`: files with me received in the last 7 days and not listed above, newest first, with the
       sender's name and designation.

Unchanged endpoints the new screens call: `/inbox/recommended | pool | transfers | counts`, `/cases/{ref}` and its
tabs, `/cases/{ref}/ownership`, the claim, dismiss, suggest and transfer writes, `/custody/recipients`,
`/custody/held`, `/calendar`, `/alerts*`, `/next-dates/*`, `/reference/labels`, `/workflow/codes`, the order and
document file endpoints.

## Jobs
None.

## Tests
Each round adds its own and keeps every existing test green. Existing tests that assert texts changed by
decision 10 (the score badge text, the tab lists, the navigation entries, the Claimed tab) are updated to the new
texts in the same round, never deleted.

**Round 1 (row 101, Vitest):**
- `tokens.test.ts`:
  - contrast of the text pairs and badges ≥ 4.5:1;
  - the spacing-scale source check on the round's modules.
- `motion.test.tsx`:
  - under reduced motion, `useCountUp` returns the final value at once and `usePresence` unmounts with no delay;
  - without reduced motion the exit waits for the duration (fake timers).
- `ui.test.tsx`:
  - every control renders at the 36 px class;
  - `Tabs` marks the current tab and places the underline;
  - `Menu` opens and closes by keyboard;
  - `Collapsible` toggles `aria-expanded`;
  - `Dialog`, `Modal` and `SidePanel` trap focus, close on Escape and return focus;
  - `DataTable` renders `data-label` on every cell and leaves out `hideOnPhone` columns from the card labels;
  - `Lead`, `DateChip` and `ListRow` put the leading element in the fixed column;
  - `ScoreBadge` shows "Strong · 0.950" from `band: high`, and the same label for any score when the band says so.
- `shell.test.tsx` (updated):
  - the groups and their entries by function;
  - the emblem placeholder with `BRAND.emblem = null`, and the image with alt text when set;
  - the drawer opens from the menu button, traps focus and closes on Escape and overlay click;
  - the bottom bar shows at most three entries plus More;
  - the breadcrumb renders inside the page header.
- `i18n.test.ts`:
  - `<html lang="en" dir="ltr">`;
  - every catalogue has the English keys and arities;
  - `formatDate` and `formatNumber` outputs for `en` are unchanged (the existing cases);
  - a non-English locale goes through `Intl`;
  - no navigation label is left in `routes.ts`;
  - the JSX literal check.
- `portal_smoke.py` passes: every page 200, no error line.

**Round 2 (row 102):**
- pytest `tests/db/test_my_cases.py`:
  - `working` lists a case allotted to me and one whose file I hold, not a case allotted to a colleague;
  - a directorate user sees their unit's allotted case;
  - `files` equals `/custody/held?scope=me` (same rows, same order);
  - `claimed` lists the case I claimed and the one whose transfer I accepted, not one a colleague claimed;
  - `disposed` holds only disposed cases from the three sets;
  - visibility: a case leaves every view once the caller loses sight of it (for example their membership ends), and
    another department's officer sees nothing;
  - merged cases are excluded;
  - the shared filters, `stage` and `action` narrow;
  - bad `view`, `stage` and `action` give 400;
  - no `audit_log` row is written;
  - the counts equal the totals.
- pytest `tests/db/test_api_inbox.py`, additions:
  - `unallotted`, `stage` (including `none`), `holder` and `action` narrow `/inbox/claimed`;
  - `unallotted` with `officer_user_id` gives 400;
  - items carry `stage` and `custody`;
  - `whole_department` is true for a department admin and a department head and false for a department officer;
  - a State-wide reader gets true for any `office`.
- If A5 is approved, pytest `tests/db/test_visibility_transfer_in.py`:
  - the receiving department's admin reads the case and its ownership with `decide_transfer`, while the transfer is
    requested, and loses sight after it is declined or withdrawn;
  - an officer of that department without claim or allot does not see it;
  - no write is allowed through the basis.
- Vitest:
  - `inbox.test.tsx`: the five tabs shown by counts and `whole_department`; the Department cases filter grid, More
    filters, chips and "n of m"; the Not allotted option sends `unallotted=true`; rows open the case page.
  - `claim.test.tsx`:
    - the tabs by counts;
    - a row click opens the modal with `?case=` and Back closes it;
    - the modal tabs load on first open;
    - the Why box shows each signal;
    - the footer buttons appear only by `actions`;
    - Claim, Dismiss, Suggest, Accept and Decline go through the inline step and send the selected department;
    - `office_required` opens the department choice;
    - a 404 case shows the row facts only;
    - the order row expands, mounts the frame once and shows Print and Download by function;
    - `INLINE_PDF` false shows "Open in a new tab";
    - the old `/inbox/recommended?band=high` lands on `/claim/recommended?band=high`.
- `portal_smoke.py` with the new routes.

**Round 3 (row 103):**
- pytest `tests/db/test_my_calendar.py`:
  - the three kinds for an officer (a hearing of an allotted case, a due date of a held file, a confirm item);
  - a colleague's case and an unseen case are absent;
  - without `next_dates.review` there are no confirm items;
  - range limits give 422;
  - the default range covers the month grid;
  - the order is as specified;
  - nothing is written.
- Vitest:
  - `case.test.tsx` (updated):
    - the header's four facts and the single primary action picked from the flags;
    - the More menu holds the five tabs and shows the current one;
    - the folded sections expand;
    - Recent activity lists five entries.
  - `workflow.test.tsx` (updated): Send file walks three steps, Continue refuses a missing required field, Back
    keeps values, and the request body is unchanged.
  - `calendar.test.tsx`:
    - My calendar draws three kinds with the right tones;
    - the legend hides a kind;
    - today is marked;
    - previous and next month change the query;
    - a day click fills the agenda with `Lead` badges;
    - the dot mode has accessible names;
    - the Department hearings switch shows only with `whole_department` or a State-wide login and calls
      `/calendar`;
    - `/alerts/calendar` redirects.
  - `alerts.test.tsx`: Alerts has two tabs.

**Round 4 (row 104):**
- pytest `tests/db/test_dashboard.py`, additions:
  - each headline figure against a hand-built fixture: claim counts only where `cases.claim` is held; hearings
    within 48 hours; due today; the oldest overdue days; the confirm count, null without the function;
  - `upcoming` and `attention` order and limits;
  - visibility on every item;
  - existing fields unchanged.
- Vitest:
  - `dashboard.test.tsx`:
    - the greeting by IST hour;
    - five `Kpi`s with links, hiding the null ones;
    - count-up under reduced motion shows the final number;
    - the attention rows use `Lead`;
    - the view switch appears only with more than one view.
  - Files, Search and Cause list tests updated: cards on the phone class, the side panel opens and closes, one
    primary per page.

**Round 5 (row 105):**
- Vitest:
  - the Reports, Audit, Data and Admin tests updated to the templates;
  - the public pages show the brand slot;
  - `tokens.test.ts` widened: no stylesheet uses a removed alias, and the spacing check covers every module;
  - a page-level test renders each page component with a fake `/me` and asserts at most one primary button.
- `portal_smoke.py` over every page.

## Verification
The commands are the same each round, adding that round's pages and endpoints.

1. Backend, rounds 2-4: `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q`
   green. Then `python backend/tools/export_openapi.py` and `git diff --exit-code frontend/openapi.json` are clean
   after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test` and `npm run
   build`.
3. Compose:
   - Run `docker compose build web` (rounds 2-4: `build api web`), then `docker compose up -d --wait --no-deps web`
     (rounds 2-4: `api web`; no migration, and the worker and scheduler running the load are not recreated).
   - Then `python backend/tools/portal_smoke.py`: every page answers 200, including the new and redirect pages, and
     no error line appears in the `web` log.
4. Without a session, `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/inbox/mine?view=working`
   answers 401 (round 2), and the same for `/api/backend/me/calendar` (round 3).
5. API spot checks with a department officer's and a department admin's sessions (rounds 2-4), against psql:
   - `/inbox/mine/counts` equals the counts of the matching SQL;
   - `/inbox/claimed?unallotted=true` equals the department's active primary rows with no officer;
   - `/me/calendar` for the current month lists the officer's held-file due dates;
   - `/dashboard/me` `headline.files_with_me.total` equals `/inbox/mine/counts.files`;
   - no `audit_log` row is written by any of these reads.
6. The signed-in owner checks below are run in the browser at http://localhost:3000 (they need the e-mailed sign-in
   code). If they are not run before the merge, the cycle report records them and hands them over, as in rows 53
   and 56.

**What the owner checks in the portal after each round.**
- **After round 1:**
  - The header shows the dashed "Emblem" box, "GOVERNMENT OF ASSAM" and "Legal Case Monitoring Portal". The
    sidebar is white, with the groups Work, Oversight and Settings and a blue bar on the current entry.
  - Every button and field on any page is the same height. Badges are red, amber, green or blue only with their
    meanings.
  - Tabs slide their underline. A dialog (for example Administration → Users → New) fades and scales in, and fades
    out on close. Loading lists show grey shimmering rows.
  - With Windows Settings → Accessibility → Visual effects → Animation effects off, and the page reloaded, nothing
    moves.
  - With the browser window narrowed below 820 px (or on a phone): the menu button opens the menu as a drawer, a
    bottom bar shows Dashboard, Case inbox, Files and More, and a dialog fills the screen.
  - Dates and numbers read exactly as before ("25 Sep 2026", "1,28,400"). View source shows `<html lang="en"`.
- **After round 2:**
  - The menu shows "Case inbox" and "Case claim" with counts.
  - As a department officer, Case inbox shows Working on, Files with me, Claimed by me and Disposed, and no
    Department cases.
  - As the department admin, Department cases appears with the filter grid. Choose Officer "Not allotted" and
    Next hearing "This week": the chips appear with "n of m cases", removing a chip widens the list, and More
    filters slides open.
  - Case claim → Recommended: click a case. The large window shows the facts, the five tabs and "Why this is
    suggested" with the signals and the meter. In Orders, click an order: it expands and shows the PDF, Print opens
    it in a new tab for printing, and Download saves it.
  - Press "Claim for <department>", add a note, Confirm. The case leaves Recommended and appears in Claimed by me
    and in Department cases.
  - Open an old bookmark `/inbox/recommended`: it lands on Case claim. On a phone the window fills the screen.
- **After round 3:**
  - A case page shows the summary card (next hearing, file is with, stage, owner) with one blue button. The tabs
    are Overview, Hearings, Orders, Documents, Notes, Timeline and More, and More lists Parties, Linked cases,
    Custody and stage, Alerts and Details.
  - Overview shows Latest order and Recent activity, and "Show parties, advocates and acts" opens smoothly.
  - Send file shows three steps with a progress bar: Continue is refused without a person, Back keeps the choices,
    and the last step sends.
  - My calendar shows the month with red hearings, amber due dates and blue next dates to confirm, and today
    circled. The legend chips hide a kind. Previous and next change the month. Clicking a day lists that day on the
    right, with the badges in one column. On a phone the events are dots.
  - Alerts is a separate menu entry with "Next dates to confirm" as a tab. As the department admin, "Department
    hearings" shows the department's calendar as before.
- **After round 4:**
  - The dashboard greets by name and time of day. The five numbers count up, and each opens a list whose count
    matches. Upcoming hearings has the date chips (red within 48 hours). In Needs your attention, every title
    starts at the same place whatever its badge says.
  - As the department admin, the "Department" view shows the department figures as before.
  - Files, Search and Cause list show compact tables; on a phone they become cards. Clicking a Files row opens the
    side panel.
- **After round 5:**
  - Reports, Audit log, Data collection and Administration follow the same layout. The sign-in page shows the
    emblem slot.
  - At 375, 768 and 1280 px widths every page reads without sideways scrolling (except wide report tables), and no
    row anywhere has text starting at different places.
  - Before the pilot, the owner supplies the official emblem file and the placeholder is replaced (decision 21).

## Open questions
None blocks the design. Each point below is decided as recommended, and the build follows that unless the owner
answers otherwise at approval.

1. **May the receiving department see a case while a transfer to it is requested?** Today the receiving
   department cannot open a case owned by another department, so the details modal for "Transfers to us" can show
   only the transfer's own facts. The owner asked to see all details before deciding.
   **Recommended: yes.** Add the sight-only basis `transfer_in` (A5) for the receiving department's
   whole-department memberships while the transfer is requested. They see the court record and the case-scope
   notes and documents, as a recommended department does today. They cannot write, and they lose sight when the
   transfer is declined or withdrawn.
2. **Inter replacing IBM Plex Sans and Source Serif.** **Recommended: yes**, through `@fontsource-variable/inter`,
   self-hosted: one dependency added, two removed, IBM Plex Mono kept for identifiers.
3. **The phone bottom bar shown in the mock-up's Phone view, in addition to the drawer.** **Recommended: yes**,
   with at most three of Dashboard, Case inbox and Files (as the login has them) plus More.
4. **"Department cases — department admins only".** **Recommended:** show the tab by the server's existing
   whole-department rule (the membership holds `cases.claim` or `cases.allot`: department admin and department
   head by default, or anyone granted those functions) and to State-wide readers, not by user type. Screens are
   composed by function and membership, never by user type (reports-dashboards decision 1).
5. **Directorate users' unit-allotted cases.** **Recommended:** count them as "allotted to me" in Working on, as the
   Claimed tab counts them today, so no directorate user loses cases from their inbox.
6. **The Department hearings view.** **Recommended:** keep today's department-wide hearing calendar as a second
   view of My calendar for whole-department members and State-wide readers.
7. **Mock-up elements not built.** "Export" on Case claim (no API), "Switch post" (no acting-membership switch), the
   green "Pending" badge (green means done). **Recommended: not built.**


> Row numbers renumbered when the design was brought into `main` on 20 Oct 2026 (rows 97-100 were taken by github-and-ci follow-ups): 97 -> 101, 98 -> 102, 99 -> 103, 100 -> 104, 101 -> 105.

## Deviations

### Round 1, row 101 `portal-ui-foundation` (developer, 20 Oct 2026)
Choices made where the note is silent, each the smallest reasonable option:

1. **No separate note.** Backlog row 101 links this note; there is no `docs/design/portal-ui-foundation.md`. Round 1
   was built from decisions 2 (round 1), 10.1-10.2, 10.6, 10.13-10.15, 11-22 and 27, "Portal (round 1)" and "Tests,
   round 1".
2. **`--red-text #B42318` for red text.** `--red #D92D20` on `--red-soft` is 4.45:1 and on `--bg` 4.49:1, below the
   4.5:1 that decision 11 requires. `--red` stays for fills (the bell dot, borders); red text (danger badges, errors,
   the danger button, the `hot` date chip) uses `--red-text` (6.0:1 on `--red-soft`), and the `--danger` alias points
   to it. `tokens.test.ts` checks every pair.
3. **Navigation counts in round 1.** Only the Alerts entry has its pill (`unread` from `/alerts/counts`, the bell's
   query). The Case inbox and Files counts read `/inbox/mine/counts` (A2), which arrives in round 2. Case claim and
   My calendar are declared in `routes.ts` with `built: false` until rounds 2 and 3, and the entry keeps the label
   "Alerts & calendar" until round 3 moves the calendar out (decision 10.3).
4. **Breadcrumb in the page.** Every frame's title is now a `PageHeader` (breadcrumb above the title). The case page
   shows the breadcrumb at the top of its summary header until round 3 rebuilds that header. The sign-in, code,
   reset and error pages are round 5 and keep their headings.
5. **Dialog width.** `Dialog` keeps its 760 px width until round 3 puts the workflow dialogs on the Action dialog
   template (560 px; 720 px through the new `wide` prop); its look, easing, focus trap and full screen on phones are
   in place now.
6. **No `matchMedia`, no motion.** Where the reduced-motion query cannot be read (jsdom in tests, very old browsers),
   the motion hooks behave as under reduced motion: count-up shows the final number and overlays unmount at once.
7. **The bell** shows the mock-up's pulsing dot when there are unread alerts; the number stays in its accessible name
   ("7 unread alerts") and in the Alerts entry's pill.
8. **Date helpers.** `format.ts` gains `dayMonth` (the `DateChip`), `formatWeekday` and `formatMonthYear` (for the
   calendar and the greeting in rounds 3 and 4); English names are fixed there like the existing month abbreviations.
9. **The JSX literal check** (`i18n.test.ts`) scans every non-test `.ts`/`.tsx` under `src/` except `src/test/`, the
   generated API types and `messages.ts`, with the TypeScript parser. Its allowlist is text without a word of two or
   more letters (symbols, dashes, separators); case data always come from the API. The two literals it found
   ("HTTP" in the queue table, "vs" in the parties line) moved into `messages.ts`.
10. **Case numbers** in `CaseLink` carry the global `cno` class (semibold, tabular figures); a bare `ref_no` stays
    monospace (decision 10.1). The one test that asserted `mono` on a case number now asserts `cno`.

### Round 2, row 102 `portal-ui-inbox-claim` (developer, 20 Oct 2026)
Choices made where the note is silent, each the smallest reasonable option:

1. **No separate note.** Backlog row 102 links this note; there is no `docs/design/portal-ui-inbox-claim.md`. Round 2
   was built from decisions 2 (round 2), 4-7, 9, 10.4-10.6 and 28, A1-A5 (A5 approved: question 1), "Backend (round
   2)", "Portal (round 2)" and "Tests, round 2".
2. **Claimed by me also counts the transfer the person accepted when a watcher row was promoted.** On accept, an
   existing watcher row of the receiving department becomes the primary and keeps its own actor snapshot. So C is
   the active primary rows of the caller's departments whose `actor_user_id` is the caller, OR whose accepted
   transfer (`ownership_transfers`, same case and receiving office) the caller decided.
3. **Row order "then case"** is the case number text, then the id, after the next hearing (nulls last) and the
   custody due date (nulls last). `files` keeps `/custody/held?scope=me`'s order exactly (due date, since, case id).
4. **`action` needs a due date and a pending action.** `overdue` (due date before today, IST) and `due_week` (today to
   today + 7) match only a custody row with a due date and a pending action other than `none`, on `/inbox/mine` (the
   caller's own file) and `/inbox/claimed` (any holder). The row brief's `overdue` follows the same rule, so a file
   left on an ownership leg with no action is never shown as overdue in the lists.
5. **Department cases' default department.** Without `?department`, the tab reads the first of the caller's own
   departments that the server reads whole; a State-wide reader without one chooses a department first.
6. **Quick chips.** "Hearing this week" is `next=n7` (today to today + 6, IST), "Action overdue" `action=overdue`,
   "Listed this week" on Recommended `listed=d7`, Strong / Possible `band=high|medium`. Recommended has no separate
   Court chip: Court stays under "More filters" with the other portal-filters fields. Department cases' Next hearing
   offers Any date / This week (`n7`) / Next 30 days (`n30`) / Choose dates (a range).
7. **Transfers to us: the status default.** No `status` in the URL means `requested` for To us and any status for From
   us; the select's "Any" writes `status=all`. Withdraw for an outgoing transfer is in the modal's footer (by
   `actions.withdraw_transfer`), through the same inline step with Back and Confirm.
8. **The transfer modal has no "Why this is suggested" box** unless the receiving department also holds a
   recommendation for the case (a transfer is not a suggestion); the tabs then take the full width.
9. **A 404 transfer row** (the caller cannot open the case): the footer still offers Decline and Accept transfer when
   the row is requested and the membership in the selected department holds `cases.transfer_decide`; the API decides
   the call, as everywhere.
10. **The success notice stays on Case claim** (above the tabs, with "Open case page"), not carried to another page.
11. **The Case column** shows the case number; the case type is part of the printed number (the list summary has no
    separate case type field).
12. **Department cases rows carry no Allot button.** The old Claimed tab's row Allot is gone with the tab; Allot stays
    on the case page's ownership actions (round 3 puts it in the "More actions" menu).
13. **Kit and filter-bar additions.** `FilterBar` gained per-list `more`, `hidden` and `nextChoices` (in
    `LIST_FILTERS`) and own controls with `first` (drawn after Words); `buttonClass()` draws a link as a button (the
    order toolbar's Print and Download); `CaseLink` gained `newTab` (the modal's Linked cases).
14. **"Your action"** on the own-work rows shows the pending action only when the file is with the caller.
15. **The Case claim count** in the navigation is read only when Case claim shows for the login; every count is
    re-read every two minutes and on window focus.
16. **Round-1 review fixes.** A closing overlay carries `inert` and `pointer-events: none`, its overlay click is
    ignored, and `ConfirmDialog` drops a submit that arrives while closed or busy. The drawer closes when the
    `(min-width: 820px)` query starts to match, which also releases the scroll lock and the focus trap.

### Emblem (20 Oct 2026, on `main` between rounds 2 and 3)
- The official file the owner supplied is installed (decision 21): the lion capital cut from it is in the header, and the whole emblem is on the sign-in and first-sign-in pages, ahead of round 5. `/brand/` is outside the page gate, and the `web` image copies `public/`. Round 5 keeps `BrandLockup` when it redesigns the public pages.

### Round 3, row 103 `portal-ui-case-calendar` (developer, 20 Oct 2026)
Choices made where the note is silent, each the smallest reasonable option:

1. **No separate note.** Backlog row 103 links this note; there is no `docs/design/portal-ui-case-calendar.md`. Round
   3 was built from decisions 2 (round 3), 8, 10.3, 10.7, 10.9-10.12, 15, 16, 24 and 25, A6, "Backend (round 3)",
   "Portal (round 3)" and "Tests, round 3".
2. **A6 with one bound.** Both `from` and `to` missing give the current month's grid; with only one given, the other
   is the grid edge of that date's month (`from` alone ends on the Sunday after its month's last day; `to` alone starts
   on the Monday before its month's 1st). The 62-day limit and `to` before `from` answer 422 `bad_range`.
3. **A6 `critical`.** A hearing: `calendar.flags` (within `ALERT_CRITICAL_HOURS` of the court's sitting time). An
   action due date: overdue, or its IST day ends within `ALERT_CRITICAL_HOURS`. A next date to confirm: the hearing
   rule on the proposed date.
4. **A6 rows.** `action_due` is every custody row the caller holds with a pending action other than `none` and a due
   date in range, ANDed with the visibility rule (it is not narrowed to `my_cases_condition`, which holds it anyway).
   `confirm` items are the review queue's (`queue_subquery`, kind `confirm`), so they need an active primary owner and a
   proposed date from today on. "Then case" in the order is the case number text, then `ref_no`.
5. **The header's next hearing** names the court and item only when the latest listing is on the next hearing day
   (otherwise the latest listing is an earlier day and would mislead). The header does not repeat the CNR, court,
   registration date and `ref_no`; they stay on the Details tab.
6. **More actions** also holds Claim and Accept transfer when another action is the primary (Send file first). Decline
   and Withdraw stay on the Ownership card in the folded "Ownership and recommendations", whose buttons are all
   secondary there, so the page keeps one primary.
7. **Add note** opens the composer in a 720 px dialog; the composer keeps its own Cancel and Add note / Save draft
   buttons at the foot of its form. The Notes tab keeps its inline composer.
8. **The Action dialog template is the kit's `Dialog`.** Every `Dialog` is now 560 px (720 px `wide`), the
   administration dialogs included until round 5 restyles them. `ConfirmDialog` puts Cancel (or Back) left and its one
   primary right in a footer fixed at the bottom, submitting the form through the button's `form` attribute. The
   subtitle is the case number from the case already loaded on the page (`useCaseTitle`, no request), so it is absent
   where no case page is open (the claim modal shows the number in its own header). The next-date dialogs take the
   name from their item; Enter next date's body line with the name moved into the subtitle.
9. **Send file, step 1:** the people are native radio inputs drawn as cards (keyboard and screen readers work without
   extra code); a missing department says "Required.", a missing person "Choose the person who receives the file."
10. **Orders tab:** under each collapsible row, always visible, the judge and "Next date read" with the reading (a new
    `after` slot on `Collapsible`). With `INLINE_PDF` false the expanded row offers "Open in a new tab" and "Download
    PDF" (decision 7) in place of "Download" with the "Opens as a download" hint. On the Overview's Latest order card
    the row's summary reads "Show the order" (`OrderRow` `label`), because the card shows the details above it. The
    next-date block of portal-next-dates is reused unchanged inside the card.
11. **Timeline tab** rows lead with the `DateChip` (decision 15).
12. **My calendar:** the chosen day defaults to today when the current month is shown, else none; the legend is screen
    state, not in the query string; an event shows the case number; Today is a secondary button; switching views drops
    `month`, `day` and `department`. The view switch shows when any of the caller's departments is read whole on
    `/inbox/counts` (not per selected department), or for a State-wide reader.
13. **Department hearings view:** the old `alerts/Calendar.tsx` moved to `calendar/DepartmentHearings.tsx` unchanged,
    except that its "Next 7 days | This month" pair became chips, so the page keeps one primary.
14. **`/alerts/calendar`** keeps its query string on the redirect (adding `view=department` when allowed); it shows the
    Alerts frame with a loading line for the moment before the redirect.
15. **The spacing check** (`tokens.test.ts`) now covers the round's modules: `case`, `calendar`, `hearings` and
    `workflow`.
