# Design: Next hearing highlighted across the portal

```
slug: next-hearing-highlight
status: approved
author: architect
date: 2026-10-27
approved_by: owner on 2026-10-27, as designed (checks 1-3 accepted: no dark theme yet, Today and Tomorrow for the strong band, the header and the other screens unchanged)
```

## Context

Backlog row 190 (rows 187 to 189 are used on other branches). **Owner's request, 27 Oct 2026:** "i would want the section showing next hearings of the cases to be
highlighted in some form so that the information is easily identified."

**Owner's choices, recorded as given (27 Oct 2026):**
- **Where:**
  - the case page summary header and its next-date block;
  - the large case details modal (opened from the inbox and Case Claim);
  - the Next Hearing column of the case lists: the Case inbox tabs, Department Cases, Search results, and any other
    case list that shows a next hearing;
  - the dashboard's upcoming hearings block.
- **How, by how soon:**
  - a coloured date badge: strongest for today and tomorrow, a softer shade for this week, plain for later, greyed out
    when no date is known;
  - colours from the portal's design tokens (light and dark mode);
  - always a text label ("Today", "Tomorrow", "In 3 Days", the date), so colour is never the only signal;
  - labels in Title Case, under the portal's label rule.

**Plan.**
- §5.5: "Calendar of upcoming hearings for the user's cases, with critical (within 48 hours) and this-week
  highlights."
- §5.1: the department dashboard shows "upcoming hearings with those within 48 hours marked".
- §5.3: the case overview leads with the next hearing.

This item takes those highlights to every place the owner named and makes them one visual language.

**What exists (read for this design, branch `main` at 7168aec).**

*Four helpers that disagree with each other:*
- `lib/format.ts::hearingBadge(date)`: "critical" when the 10:30 IST sitting is at most 48 hours away, "week" up to
  7 days ahead (portal-cases, decision 10).
- `lib/cases.ts::hearingCountdown(date)`: whole IST days, "Today" / "Tomorrow" / "In n days" (case-workspace-admin,
  decision 11). That decision says ASLMS does not hold the hearing time, and a guessed 10:30 would be a made-up fact.
- `dashboard/Headline.tsx::dayWords(item)`: reads the API's `critical` and `this_week` flags (portal-ui-polish,
  decision 14).
- `Rail.tsx::hearingFact(date)`: "Wed, 28 Oct 2026 · in 5 days". The owner ruled on 23 Oct 2026 that the date always
  shows with the countdown.
- The IST day itself comes from one frontend helper, `lib/format.ts::istDay` (with `daysBetween` and `addDays`).
  `lib/workflow.ts::todayIst` is a second copy, used by the date inputs.

*Badges today:* "Within 48 Hours" / "48 Hours" in kit `Badge tone="danger"`, and "This Week" in the neutral badge.
They are drawn beside the date in:
- `components/inbox/rows.tsx::NextHearingCell`, used by Working On, Claimed by Me, Disposed, Department Cases,
  Recommended, Pool and the Search side panel;
- the case header fact `CaseFrame.tsx::NextHearingFact`;
- the rail card `Rail.tsx::NextHearing`;
- the Overview card "Next Date From Orders" (`nextdates/CaseNextDate.tsx::NextDateBlock`);
- the dashboard (`Headline.tsx::UpcomingPanel` with a `DateChip` lead, and `Blocks.tsx::HearingList` for the
  Department and State views).

The case details modal (`claim/CaseModal.tsx`) shows the date as plain text. The Search result row shows it inside
the muted `ListingLine` ("… · Next hearing 28 Oct 2026").

*The data each place already receives (no API change needed, see API):*
- every list row carries `case: CaseSummaryOut`, which has `next_hearing_date` (the court's date, NAPIX
  `date_next_list`) and `status` (`pending` / `disposed`);
- the case detail carries `status.next_hearing_date`, `status.status` and `next_date_from_orders` (`NextDateOut`,
  with `review_status`: `pending` means a suggestion waiting for a person; `not_needed`, `confirmed` and the `manual`
  source are firm);
- the dashboard items (`DashboardUpcomingOut`, `DashboardHearingOut`) carry `date`. They come from
  `services/calendar.py::hearing_rows`, which never includes a `pending` next date, so every dashboard date is firm.

*Tokens and kit:*
- `app/globals.css` `:root` holds `--red`, `--red-text`, `--red-soft`, `--amber`, `--amber-soft`, `--slate-soft`,
  `--text`, `--text-2`, `--text-3`, `--surface` and `--border-strong`, with contrast checked by
  `components/ui/tokens.test.ts`;
- **the portal has no dark mode**: no `prefers-color-scheme` block, no theme attribute, no dark tokens anywhere in
  `frontend/src` or the design notes (see decision 13);
- `DataTable` turns rows into label-value cards below 820 px, or when the table cannot fit its box;
- the kit `Badge` truncates its text with an ellipsis, which would cut a date.

**Not covered.**
- The hearing calendar screens (`/calendar`, the Department Hearings view and its agenda). They keep the API's
  `critical` / `this_week` badges: they are calendars, where the date is the axis, not a Next Hearing field.
- The Hearings tab and its "Next Dates" section; the Orders tab reading; the cause list; the Assistant's court-record
  view. These show past or per-order dates, not the case's next hearing.
- The Sent by Me and Pending Action tabs and the Transfers tab. They do not show a next hearing today, and none is
  added (decision 11).
- Which date each place shows does not change. The header, the lists and the modal show the court's date. The Overview
  card shows the next date from orders. The dashboard shows the calendar's date. A case whose court date is empty but
  whose firm order date is known still reads "No Date Yet" in the header; that is how it behaves today. Using the
  order date there would be a new rule, so it is left for the owner (Verification, owner check 7).

## Decisions

1. **One kit component, `HearingDate`, everywhere the owner named.** It lives in `components/ui/HearingDate.tsx`, is
   exported from the kit index and has its own `hearingDate.module.css`. It replaces `NextHearingCell`, `NextHearingFact`,
   the rail card's date line, the Overview card's badges, the modal's plain date and the dashboard's day badges.
   - Alternative: restyle each place's existing badges. Rejected: four helpers already disagree (Context), and one
     component is the only way the same date reads the same on every screen.

2. **One pure band helper, `lib/hearingDate.ts`, in IST whole days.**
   ```ts
   hearingBand(date, { status, now }) -> { band, days }
   ```
   - `band` is one of `today`, `tomorrow`, `week`, `later`, `passed`, `none`, `disposed`;
   - `days` is the whole IST days from `istDay(now)` to the date (`daysBetween`), or null.

   The rule, first match wins:
   - `status === "disposed"` → `disposed`;
   - no date, or not `YYYY-MM-DD` → `none`;
   - days < 0 → `passed`;
   - 0 → `today`;
   - 1 → `tomorrow`;
   - 2 to 7 → `week`;
   - 8 and more → `later`.

   It reads the IST day only through `istDay` (`lib/format.ts`), never the browser's zone and never an hour.
   - It replaces `hearingBadge` (removed from `format.ts`), `hearingCountdown` (removed from `cases.ts`) and `dayWords`
     (removed from `Headline.tsx`); their tests move to `hearingDate.test.ts`.
   - Alternative: keep the 48-hour sitting rule. Rejected: case-workspace-admin decision 11 found the 10:30 time is a
     made-up fact, and the owner asked for today and tomorrow.

3. **The bands are fixed, not settings.**
   - **Strong**: today and tomorrow.
   - **Soft**: 2 to 7 days ahead (the next 7 calendar days after tomorrow, the same window as the calendar's "Next 7
     Days").
   - **Plain**: 8 days and later.

   The constant `HEARING_SOON_DAYS = 7` sits in `lib/hearingDate.ts`. The alert engine's `critical_hours` setting
   (hearing alerts, the e-mail "within 48 hours" severity) and the dashboard KPI "n within 48 hours" stay as they are:
   they are server counts and alert severities, not this badge.
   - Alternative: read the alert settings. Rejected: the owner chose day bands, and a setting would make the badge
     disagree with its own words.
   - **Deviation (small), flagged for the owner:** the plan's "critical (within 48 hours)" highlight is drawn as
     today and tomorrow in IST calendar days. A hearing the day after tomorrow, which the server may count as within
     48 hours, shows the soft band. Its words ("In 2 Days") are exact.

4. **The look of each band (the owner's "how soon"), from existing tokens only.**

   | Band | Words shown (Title Case) | Style |
   |---|---|---|
   | `today` | **Today** · date | **strong**: solid `--red` fill, text `--on-red` (new token, white), word in 600 weight |
   | `tomorrow` | **Tomorrow** · date | strong, as today |
   | `week` | **In n Days** · date | **soft**: `--amber-soft` fill, `--amber` text, word in 600 weight |
   | `later` | date (lists); **In n Days** · date (case page and modal, decision 6) | **plain**: no fill, `--text`; the word in `--text-2` |
   | `passed` | **Date Passed** · date | **warning**: `--slate-soft` fill, `--amber` text, a small warning-triangle icon (aria-hidden) before the word; `title` "The court's next date has passed and no newer date is held yet." |
   | `none` | **No Date Yet** | **greyed**: no fill, `--text-3` text, 1 px dashed `--border-strong` border |
   | `disposed` | **Disposed** | greyed, as `none` (decision 9) |

   - Red and amber keep the portal's fixed meanings (globals.css header: red = urgent or within 48 h, amber = due soon).
   - The strong band is the only solid fill on a list row, so it is the strongest thing on the row, as asked.
   - Every pair meets WCAG 2.1 AA. The new pairs are added to `tokens.test.ts`:
     - `--on-red` on `--red`: 4.8:1;
     - `--amber` on `--amber-soft`: 5.2:1;
     - `--amber` on `--slate-soft`: 4.9:1;
     - `--text-3` on `--surface`: 5.0:1;
     - `--text-3` on `--surface-2`: 4.8:1;
     - `--red-text` and `--amber` on `--surface` (for the outline in decision 5).
   - Alternatives:
     - a soft red for this week. Rejected: amber already means due soon across the portal.
     - amber fill for Date Passed. Rejected: thousands of court dates in the held data are stale. Filling them amber
       would drown the real "this week" rows, so Date Passed keeps the warning colour and icon on the neutral ground.

5. **Suggested dates are outlined and say "Suggested".**
   - A date whose `review_status` is `pending` (read from an order, waiting for a person) has `kind="suggested"`: the
     same band colour as an outline (1 px border in `--red-text` / `--amber` / `--border-strong`, `--surface` fill,
     text in the border colour, `--text` for plain), with the word **Suggested** first. For example: "Suggested · In 3
     Days · 30 Oct 2026", with `title` "Read from an order and not yet confirmed."
   - Firm dates are the court's date, a cause-list listing, a date read from an order that matches the court (the
     `not_needed` status), a confirmed date, and a manual (`NXT`) entry. They are filled.
   - In practice only the Overview card's next date from orders can be suggested. The lists, the header and the modal
     show the court's date, and the dashboard never receives a pending date.
   - Statuses other than `pending` are firm. `next_date_from_orders` only ever holds `not_needed`, `pending` or
     `confirmed`.
   - Alternative: hide suggestions from the badge. Rejected: the Overview card already shows them, and the
     "Waiting for You" panel asks for an answer.

6. **Two sizes, and the countdown rule kept.**
   - **`size="sm"`** (list cells, the Search row, the dashboard department/state table, the rail card's collapsed line):
     - the short date, "28 Oct 2026";
     - the word only in the strong, soft, passed and suggested bands;
     - the later band reads the date alone (the owner's "plain for later").
   - **`size="md"`** (the case header, the rail card body, the modal, the Overview card):
     - the weekday and date, "Wed, 28 Oct 2026";
     - always the word for a future date, including later ("In 20 Days"), which keeps the owner's rule of 23 Oct
       2026 that the case page shows the date with its countdown.
   - The word always comes first, so the eye meets "Today" before the date.
   - `showDate={false}` gives the word alone. It is used only in the personal dashboard's Upcoming Hearings list, where
     the `DateChip` lead already shows the date.

7. **The component never truncates.**
   - It is an inline-flex box with `flex-wrap: wrap`; the word and the date are two `nowrap` parts, so a narrow cell
     or a phone card puts the date on a second line instead of cutting it.
   - The date part is a `<time dateTime="YYYY-MM-DD">`.
   - The root carries `data-band` and `data-kind` for tests and the browser check.
   - It does not reuse the kit `Badge`, because `Badge` ellipsises its text (`.badgeText`). The uicheck "clipped" rule
     only exempts deliberate truncation, and a cut date is not acceptable here.
   - Corners are `--r-sm` rather than a pill, so a wrapped two-line badge still looks deliberate.
   - Minimum heights are 22 px (sm) and 28 px (md).

8. **The words are plain, accessible text.**
   - No `aria-label` overrides the visible words, so a screen reader reads exactly what is seen ("Tomorrow 28 Oct
     2026").
   - Colour is never the only signal: every band has a word, or the date alone for later.
   - The icon is `aria-hidden`.
   - Messages go under `T.hearing.badges` (a `badges` parent, so the Title Case guard checks them):
     - `today` "Today", `tomorrow` "Tomorrow", `inDays(n)` "In n Days";
     - `passed` "Date Passed", `none` "No Date Yet", `disposed` "Disposed", `suggested` "Suggested";
     - the two `title` sentences under `T.hearing.passedHint` and `T.hearing.suggestedHint`, sentence paths.
   - `"hearing.badges.inDays": [3]` is added to `LABEL_FUNCTIONS` in `lib/labelRules.ts`.
   - The retired keys are removed if nothing else reads them (the developer checks with a search): `inbox.within48`,
     `inbox.thisWeek`, `case.within48`, `case.thisWeek`, `case.noNext`, `dash.within48`, `dash.thisWeek`,
     `dash.today`, `dash.tomorrow`, `dash.inDays`, `cases.today`, `cases.tomorrow`, `cases.inDays` and
     `rail.hearingLine`.
   - The `cal.*` keys of the calendar stay.

9. **Disposed cases read "Disposed", greyed.**
   - Where the case status is known (every list row, the header, the modal, the Overview card), a disposed case shows
     the greyed **Disposed** in place of any stored date: once a case is disposed, any next date held for it is stale.
   - This matters most in Working On, which keeps a case with the caller after disposal (case-inbox-merge), and in
     the Disposed tab, where every row reads Disposed. That is honest, and it keeps the columns of the shared
     `MyCases` table the same.
   - The dashboard items carry no status. Their dates are always today or later from the calendar window, so they are
     banded by date alone.
   - Alternative: drop the column on the Disposed tab. Rejected: it would add a per-tab column rule for no new
     information.

10. **A past date is "Date Passed", not hidden.**
    - A pending case whose court date is before today in IST shows **Date Passed** with the date (decision 4). The day
      after a hearing, the case reads Date Passed until the daily cycle stores the court's new date.
    - Alternative: show the old date plainly. Rejected: it reads as a future hearing at a glance.

11. **Where it goes. Every place that shows a next hearing today, and no new places:**

    | Place | File | What changes |
    |---|---|---|
    | Case header fact "Next Hearing" | `case/CaseFrame.tsx::NextHearingFact` | `HearingDate size="md"` with `status`, then the court and item line (`T.rail.courtItem`, muted) when the latest listing is that day (the header's existing rule, `listingOnDay`) |
    | Rail card "Next Hearing" | `case/Rail.tsx::NextHearing`, `RailCard` | the body: `md` plus the court and item line and the existing "Enter Next Date" link when there is no date; the collapsed line below 1100 px: `sm` (`RailCard.fact` widens from `string` to `ReactNode`); `hearingFact` removed |
    | Overview card "Next Date From Orders" | `nextdates/CaseNextDate.tsx::NextDateBlock` | `md` with `kind` from `review_status` and the case `status`; the origin line, the court's sentence and "Waiting for You" unchanged |
    | Case details modal | `claim/CaseModal.tsx` (Case Claim: Recommended, Pool, Transfers) | the "Next Hearing" fact: `md` with the summary's or detail's `status`, then the court and item line |
    | Working On, Claimed by Me, Disposed | `inbox/WorkingOn.tsx`, `inbox/MyCases.tsx` | the Next Hearing column: `sm` with `r.case.status` |
    | Department Cases | `inbox/DepartmentCases.tsx` | the same |
    | Recommended, Pool | `claim/Recommended.tsx`, `claim/Pool.tsx` | the same |
    | Search results | `search/CaseResults.tsx`, `inbox/common.tsx::ListingLine` | the row: `ListingLine` keeps only the last listing, and `sm` sits on its own line under it in the case cell; the side panel: its Next Hearing row uses `sm`, and its Listing row no longer repeats the next hearing |
    | Personal dashboard, Upcoming Hearings | `dashboard/Headline.tsx::UpcomingPanel` | trail: `showDate={false}`; the `DateChip` lead's `hot` follows the band (today or tomorrow), no longer the API's `critical`, so the chip and the word never disagree |
    | Department and State dashboard, Upcoming Hearings / Hearings Across the State | `dashboard/Blocks.tsx::HearingList` | the Date column becomes `sm`; the separate "Within 48 Hours" badge column is removed, since the date cell now carries the band |

    `NextHearingCell` is removed and its callers use `HearingDate` directly.
    - Alternative: add a Next Hearing to Sent by Me, Pending Action, the Working On side panel and Transfers.
      Rejected: the owner asked to highlight what is shown, not to add fields, and these rows' purpose is the custody
      action and its due date.

12. **Frontend only, no API change, no migration.**
    - Every place already receives the date, the case status and, for the Overview card, the review status (Context).
    - No backend module, endpoint, function or audit row changes.
    - The bands are computed when a screen renders. A page left open across IST midnight updates on its next refetch
      (lists refetch on focus); no timer is added.

13. **Dark mode: tokens only, no dark theme in this item. Deviation, flagged for the owner.**
    - The owner asked for colours "from the portal's design tokens (light and dark mode)", but the portal has no dark
      mode (Context).
    - This item uses `var(--…)` tokens only. The one new value is `--on-red` (text on a solid red fill), added to
      `:root` beside the other status colours. A test refuses any literal colour (hex, `rgb`, `hsl`, named) in
      `hearingDate.module.css`.
    - So a portal-wide dark theme that redefines the tokens would cover the badge with no change here. Building that
      theme (a `prefers-color-scheme: dark` or toggle block for every token, contrast-checked, across every screen)
      is a separate piece of work. Adding dark values for these badges alone would put dark badges on a light page.
    - Alternatives:
      - add dark values for the hearing tokens only. Rejected: they would never show, because there is no dark page.
      - build the dark theme here. Rejected: it touches every screen, so it is its own backlog item if the owner wants
        it (Verification, owner check 1).

14. **Tests and the browser check follow the portal's rules:**
    - a vitest for the helper and the component;
    - updated vitests for every screen that uses the component;
    - the Title Case and wording guards in the frontend suite;
    - the backend wording suite, which is untouched, since no server text changes;
    - a new uicheck state at 375, 768 and 1280 px.

## Data

None. No table, column, reference code or migration. One design token, `--on-red: #ffffff`, is added to the `:root`
block of `frontend/src/app/globals.css`, with a comment ("text on a solid `--red` fill, the strong hearing band").

## Services

Backend: none.

Frontend modules (the developer builds; listed so the review can check scope):
- **`frontend/src/lib/hearingDate.ts`** (new, pure):
  - `HEARING_SOON_DAYS = 7`;
  - `type HearingBand`;
  - `hearingBand(date, { status, now })` (decision 2);
  - `hearingWords(band, days, { kind, size })`, which returns the word or null (decisions 5 and 6);
  - `hearingTone(band)`, which maps the band to `strong` / `soft` / `plain` / `warning` / `muted`.

  It imports `istDay` and `daysBetween` from `lib/format.ts` and `T` from `lib/messages.ts`.
- **`frontend/src/components/ui/HearingDate.tsx`** and **`hearingDate.module.css`** (new). Props:
  ```ts
  {
    date: string | null | undefined;
    status?: string | null;
    kind?: "firm" | "suggested";
    size?: "sm" | "md";
    showDate?: boolean;
    now?: Date;
  }
  ```
  - defaults: `firm`, `sm`, `true`;
  - the root `<span data-band data-kind>`, the word, and `<time>`;
  - the date written with `formatDate` (sm) or `formatWeekday`-based "Wed, 28 Oct 2026" (md; `weekdayDate` moves from
    `Rail.tsx` into the component's module or `lib/format.ts` so the kit does not import a screen);
  - exported from `components/ui/index.tsx`.
- **Removed:** `format.ts::hearingBadge`, `cases.ts::hearingCountdown`, `Headline.tsx::dayWords`,
  `Rail.tsx::hearingFact` and `inbox/rows.tsx::NextHearingCell`. Their imports are updated.
- **Changed screens:** decision 11's table.
- **Messages and the label rule:** decision 8.
- **The browser check:**
  - `frontend/e2e/fixtures/index.ts` gets typed overrides with dates relative to the run's IST day (`istDay()` plus
    `addDays`), so the bands are the same whenever the check runs:
    - `GET /inbox/mine`: Working On rows dated today, tomorrow, +3, +20, -5, none, and one disposed case;
    - `GET /dashboard/me`: upcoming rows dated today, tomorrow and +4;
    - the sample case detail: court date tomorrow and a `pending` `next_date_from_orders` at +3;
  - `frontend/e2e/uicheck.spec.ts` gets the states in Tests.

## API

None. No endpoint is added or changed, so no new `Permission`. Each screen keeps its existing function and the
server's visibility filters: the inbox and claim lists by `cases.view_scope` / `cases.view_all` / `cases.claim` as
today, the case page by case visibility, and the dashboard by its blocks.

Each list API already returns `CaseSummaryOut.next_hearing_date` and `CaseSummaryOut.status`:
- `GET /inbox/mine`, `/inbox/claimed`, `/inbox/recommended` and `/inbox/pool`;
- `GET /cases`, `GET /cases/search` and the court search answers (`POST /cases/search-court`).

The case detail returns `status.next_hearing_date`, `status.status` and `next_date_from_orders.review_status`. The
dashboard returns `date` from the calendar, firm only.

## Jobs

None.

## Tests

Frontend (vitest, `npm test` green, `npm run lint` and `npm run typecheck` clean):

- **`lib/hearingDate.test.ts`:**
  - bands from fixed instants: today, tomorrow, 2, 7 (week), 8 (later), -1 (passed), null and a malformed date
    (none), and disposed overriding any date;
  - IST boundaries: at 18:29Z on 26 Oct (23:59 IST) "2026-10-27" is tomorrow; at 18:31Z (00:01 IST on 27 Oct) it is
    today and "2026-10-26" is passed;
  - the browser's zone plays no part (the same instants with `TZ` set to UTC and to America/New_York give the same
    bands);
  - month and year boundaries (31 Dec → 1 Jan is tomorrow);
  - `hearingWords`:
    - "In 3 Days";
    - the later band has no word in `sm` and "In 20 Days" in `md`;
    - "Suggested" comes first for `kind="suggested"`;
    - "Date Passed", "No Date Yet" and "Disposed".
- **`components/ui/hearingDate.test.tsx`:**
  - each band renders its words, the date in a `<time dateTime>` and `data-band`, and suggested renders
    `data-kind="suggested"` with "Suggested";
  - `md` shows the weekday, and `showDate={false}` shows the word alone;
  - passed and suggested carry their `title` sentence;
  - no `aria-label` replaces the text;
  - nothing in the component uses the kit `Badge`'s truncating class.
- **`components/ui/tokens.test.ts`:**
  - `--on-red` exists;
  - the AA contrast pairs of decisions 4 and 5;
  - `hearingDate.module.css` uses only `var(--…)` colours (the dark-mode readiness of decision 13).
- **`lib/labels.test.ts` and `lib/wording.test.ts`:**
  - pass with `T.hearing.badges` (`inDays(3)` checked through `LABEL_FUNCTIONS`);
  - no stale exception;
  - no "allot" and no custody-sense "file".
- **Screens:**
  - `inbox.test.tsx`: Working On, Claimed by Me and Department Cases rows with today, +3, +20 and a disposed case show
    the bands. The old "48 Hours" / "This Week" expectations are replaced.
  - `claim.test.tsx`: the Recommended and Pool columns, and the case modal's fact with weekday and court/item.
  - `search.test.tsx`: the result row shows the band under the listing line, and the side panel's Next Hearing row
    shows it while the Listing row no longer repeats the date.
  - `case.test.tsx` and `rail.test.tsx`:
    - the header fact: "Tomorrow · Wed, 28 Oct 2026" with court and item; Date Passed; No Date Yet; Disposed;
    - the rail body and its collapsed line;
    - `NextDateBlock` with a `pending` row is outlined "Suggested", and with a `confirmed` row is filled.
  - `nextdates.test.tsx`: the same `NextDateBlock` cases where it already tests the block.
  - `dashboard.test.tsx`:
    - the Upcoming Hearings trail words and the `DateChip` `hot` follow the band, not `critical` (the `dayWords` test
      is replaced);
    - `HearingList` has no badge column, and its date cell carries the band.
  - Tests of the removed helpers (`format.test.ts` `hearingBadge`, `cases.test.ts` `hearingCountdown`) move to
    `hearingDate.test.ts`.
- **Browser check (`uicheck`, `docker compose --profile uicheck run --rm uicheck`, 375, 768 and 1280 px):**
  - `/inbox/working (next hearing bands)`: the seven rows, as a table at 1280 px and as cards at 375 and 768 px;
  - `/ (upcoming hearings bands)`;
  - `/cases/<sample> (next hearing header and next date from orders)`.

  All three must report no page overflow, inner scroll, off-screen, clipped, size, alignment or primary finding. Each
  state asserts that a `[data-band="today"]`, `[data-band="passed"]` and `[data-kind="suggested"]` element is visible
  where expected.

Backend: none added. `pytest -q` and `ruff check` stay green, since nothing in `backend/` changes. The OpenAPI
document and `schema.d.ts` are unchanged.

## Verification

1. **On `feature/next-hearing-highlight`, in `frontend/`:**
   - `npm run lint` and `npm run typecheck`;
   - `npm test` (all green, including `labels.test.ts`, `wording.test.ts` and `tokens.test.ts`);
   - `npm run build`;
   - a search finds no remaining `hearingBadge`, `hearingCountdown`, `dayWords`, `NextHearingCell`, `within48` or
     `thisWeek` outside `cal.*`.
2. **Backend unchanged:** `git diff main --stat -- backend/` is empty. `pytest -q` is run once to confirm.
3. **`docker compose build web`, then the browser check** (`docker compose --profile uicheck run --rm uicheck`):
   - the three new states pass at 375, 768 and 1280 px;
   - no other state gains a finding.
4. **The owner's checks in the browser at http://localhost:3000** (signed in, at a phone width and a desktop width):
   1. **Dark mode (decision 13, deviation).** The portal has no dark mode. This item is built on tokens only, so a
      future dark theme covers it. Confirm, or ask for a portal-wide dark theme as a new backlog row.
   2. **48 hours (decision 3, deviation).** The plan's "within 48 hours" highlight is drawn as Today and Tomorrow in IST
      days; the KPI and the alert e-mails still count 48 hours. Confirm.
   3. **Case Inbox, Working On:** a case heard today shows a solid red "Today", this week amber "In n Days", later the
      plain date, a stale date the grey "Date Passed" with its warning icon, no date "No Date Yet" greyed, and a
      disposed case "Disposed". Confirm that the Date Passed style is quiet enough in long lists (decision 4).
   4. **Department Cases, Case Claim (Recommended, Pool), Search and the case details modal:** the same badges.
   5. **A case page:** the header and the rail show "Tomorrow · Wed, 28 Oct 2026" (or the band of the day); the
      Overview card shows a suggested date outlined with "Suggested" and a confirmed one filled.
   6. **The dashboard:** the Upcoming Hearings list (My Work) and the Department / State tables carry the same bands.
   7. **Not changed:** the header shows only the court's date. A case whose court date is empty but whose firm order
      date is known reads "No Date Yet" there, as today; the calendar screens keep their own badges. Say if either
      should follow in a later row.

## Open questions

None. The two deviations (decisions 3 and 13) are flagged for the owner's approval in Verification, step 4.
