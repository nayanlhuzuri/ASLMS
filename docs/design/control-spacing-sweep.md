# Design: Control spacing and overlap sweep (filter rows, switches, Reports, rail, four new screen-check kinds, 1024 px)

```
slug: control-spacing-sweep
status: approved
author: architect
date: 2026-11-12
approved_by: owner on 2026-11-12, as written with rows 246 and 247 folded in
```

## Context
Backlog row 245. The owner sent screenshots on 11 Nov 2026 showing three faults:

1. **Case Inbox, With Me.** In the Show switch, "With My Offices" runs into the switch's right edge. The Overdue Only
   checkbox sits against the switch with no gap.
2. **Reports, Pending Cases and Hearings and Disposals.** The Scope picker touches Show Report. Refresh drops to a
   second line, out of line with Show Report.
3. **Reports, Pending Actions with Holder Department.** Holder Department overlaps Scope. The List the Cases checkbox
   (its box hidden) and its hint overlap the Holder Department hint.

The row asks for these things:
- fix the faults in the kit;
- add screen-check (uicheck) kinds that catch this kind of fault anywhere in the portal;
- sweep every route and state, and fix what the sweep finds;
- add a 1024 px width to the screen check. The owner's faults show in full at 1024 px and only mildly at 1280 px.

The survey of 11 Nov 2026 is in `docs/reviews/2026-11-11-spacing-sweep/REPORT.md`, with its crops, `findings.json` and
the temporary detectors `detectors/sweep.ts`. It found 44 items:

| Kind | Items | Marked "check" (uncertain) |
|---|---|---|
| overlap | 7 | 0 |
| text-overrun | 13 | 9 |
| tight-gap | 1 | 0 |
| misaligned-pair (split button groups) | 23 | 8 |

The survey caught all three of the owner's faults. It found four causes:

- **Filter Layout B's field grid.** `components/ui/layout.module.css` `.fcGrid` is
  `repeat(auto-fill, minmax(min(180px, 100%), 1fr))` with `.fcGrid > * { min-width: 0 }`. It gives each control a
  180 px track. Three controls cannot shrink to that, so they spill into the next track and over its control:
  - the Office Picker (`officePicker.module.css` `.field { min-width: 220px }`);
  - the kit field (`controls.module.css` `.field { min-width: 200px }`);
  - the segmented switch (the `.segmented` frame is stretched to the field's width, but its `.segment`s do not shrink).
- **The actions cell.** `.fcActions` sits in one 180 px track, which is too narrow for two buttons, so the second one
  wraps.
- **Data Collection's order form.** `components/data/data.module.css` `.orderGrid` has three `minmax(0, 1fr)` columns,
  narrower than the 200 px date fields at 1280 px.
- **The case rail's button groups.** `components/case/rail.module.css` has two:
  - `.quick`: three equal tracks narrower than "Upload a Document";
  - `.buttons`: two buttons that cannot sit side by side in the 300 px rail.

**Order.** This row runs after row 235 `portal-motion` and before row 238 `rolling-case-refresh`. Row 235 is merged
(commit `2772a3b`). It added the sliding thumb to the segmented switch, and this design keeps the thumb unchanged.

**Scope.** Frontend only, with one exception: the screen-check tooling under `frontend/e2e/`. There is no API change and
no migration. Nothing changes colour, which stays as row 229 left it. Controls move only where an item below needs it.
This row changes layout on purpose, so it regenerates `components/ui/layout-signature.json` (design portal-navy-cream,
decision 14) and says so in its report.

**Rows 246 and 247 folded in.** By the owner's decision of 12 Nov 2026 ("fold them in"), rows 246
`toast-link-persists` and 247 `toast-repeat-announce`, the toast follow-ups of row 235, are part of this row as
decisions 17 to 19. Both backlog rows are parked with a pointer here. Decisions 1 to 16 are unchanged.

**Not covered.**
- The fixed toast drawn over a dialog (row 246) is not something the new overlap kind looks for (decision 11 skips
  fixed layers). Decision 19 proves the fix with an assertion of its own instead.

## Decisions

### A. The kit (fixes most items at once)

1. **A kit field never grows wider than the cell it is given.**
   - `controls.module.css` `.field` changes `min-width: 200px` to `min-width: min(200px, 100%)`.
   - `officePicker.module.css` `.field` changes `min-width: 220px` to `min-width: min(220px, 100%)`.
   - In a flex row (`.row`, Layout A) the percentage resolves against the row, so the floor stays 200 / 220 px as
     today. In a grid track it resolves against the track, so the field fits the cell instead of being drawn into the
     next one.
   - Alternatives considered:
     - remove the floors (fields would collapse in flex rows);
     - raise every grid track to 220 px (at 768 and 1024 px the right zone, about 416 px, would hold only one column).

2. **Filter Layout B tracks of 200 px, and wide items that span two tracks.**
   - `.fcGrid` becomes `repeat(auto-fill, minmax(min(200px, 100%), 1fr))`. 200 px is the kit field's floor, so every
     kit field fits one track, and the Office Picker fits by decision 1.
   - `.fcGrid` becomes a size container (`container-type: inline-size; container-name: fc-fields`).
   - Under `@container fc-fields (min-width: 412px)`, an item marked `data-wide` spans two tracks
     (`grid-column: span 2`). 412 px is two tracks plus the 12 px gap; the CSS comment says so.
   - Below 412 px the grid has one column of the full width, and a span is never applied. A span in a one-column grid
     would create an extra implicit track and overflow.
   - Two kinds of item are marked `data-wide`:
     - the actions cell (`FilterCard` sets `data-wide` on `.fcActions`);
     - the kit `SegmentedField` (it sets `data-wide` on its root).
   - A page that wraps a wide control in its own element puts `data-wide` on that wrapper. The new screen-check kinds
     catch any page that misses it.
   - Two tracks are 412 to 440 px wide. That holds:
     - Show Report and Refresh (about 218 px);
     - Search and More Filters (n) (about 210 px);
     - the Audit log's four buttons (about 380 px);
     - the "Me / With My Offices" switch (about 210 px).
   - At 768 and 1024 px the right zone keeps two columns as today. At 1280 px it keeps three.
   - Alternatives considered:
     - a wrapping flex row in place of the grid (the fields of a line stretch unequally and the columns of the More
       Filters panel stop lining up: a visible layout change);
     - actions on their own line under the fields (moves the buttons);
     - a fixed `span 2` without the container query (overflows on phones).

3. **The segmented switch hugs its options.**
   - Today `SegmentedField`'s `.field` is a flex column, which stretches the `.segmented` frame to the field's width
     while the segments keep their own width. The frame therefore ends up narrower than its options (fault 1).
   - `.segmented` gains `align-self: flex-start`, and `.segment` gains `flex: none`. The frame is then always exactly as
     wide as its options, and the thumb from row 235 (absolute, measured from the chosen segment) is unchanged.
   - `.segmented` gets no `max-width`. If a switch is ever wider than its cell, it overflows visibly and the overlap kind
     reports it, rather than being squeezed quietly again.
   - Alternative considered: let segments shrink with an ellipsis. Rejected: an option of a choice must be readable.

4. **The check field can carry its own hint.**
   - `CheckField` gains `hint?: ReactNode`. The hint is drawn under the check line in the kit's `.hint` style, inside one
     wrapper with the check, and joined to the checkbox by `aria-describedby`.
   - `ReportForm.tsx` replaces the bare `<div>` holding List the Cases and a `muted` span with
     `<CheckField inline hint={T.reports.listFilesHint} …>`.
   - Each hint then sits under its own field: the Holder Department hint under its picker, the List the Cases hint
     under its check (fault 3).
   - Alternative considered: keep the bare `<div>` and only fix the overlap. Rejected: it leaves a hint that is not tied
     to its checkbox for screen readers.

5. **A native select names its whole choice.**
   - A native `select` cuts its chosen text at the arrow area, and no CSS reliably gives it an ellipsis in every
     browser.
   - The kit `SelectField` sets `title` to the label of the chosen option, looked up from `options` and `groups` by the
     current value. There is no title when nothing is chosen.
   - `.select` gains `text-overflow: ellipsis`, which takes effect where the browser supports it.
   - This is how the clipped check already treats deliberate truncation: the full text stays in the title. Items 13 to
     18 are therefore not layout faults (decision 9).
   - Alternative considered: widen the selects. Rejected: a 647 px bench name cannot fit a filter field.

### B. Local fixes

6. **Data Collection's order form wraps instead of overlapping (items 1 and 2).**
   - `data.module.css` `.orderGrid` becomes a wrapping flex row with gap `var(--s3) var(--s4)` and
     `align-items: flex-start`.
   - The order select gets `flex: 1 1 200px`.
   - The forward fieldset gets `flex: 2 1 412px`. Its two date fields sit in their own wrapping row, each
     `flex: 1 1 200px`, so From and To stay side by side and drop together.
   - The reason field and the items after it get `flex: 1 1 100%`. They keep their full line, as `.span2` gives them
     today.
   - Below 700 px everything is one column, as today.
   - The label-line rule `.orderGrid > :first-child { padding-top: var(--label-offset) }` stays, so the select's box is
     level with the date boxes.
   - Alternative considered: keep the three-column grid with a 200 px floor. Rejected: it overflows the card at
     1280 px with the side menu.

7. **Every button group in the case rail is a column of full-width buttons (items 8, 10, 19, 20, 22, 37).**
   - `rail.module.css` `.quick` and `.buttons` become `display: flex; flex-direction: column; gap: var(--s2)`, with the
     buttons at `width: 100%`.
   - Quick Actions (Add Note, Upload a Document, Set Stage) are then one per line at every width. So are See All
     Remarks (n) and Recall Case, and the other two `.buttons` groups in `Rail.tsx`.
   - This adds about 90 px to the rail's height when all three quick actions show.
   - **Amends design portal-screen-fixes-work, decision 17** ("three equal-width buttons in one row"). "Upload a
     Document" does not fit a third of the 320 px rail at any width. Equal width is kept; the single row is not.
   - Alternatives considered:
     - a shorter label (wording is the owner's, and it was settled in row 232);
     - letting the label wrap (breaks the 36 px button height of the size check);
     - unequal flex buttons (a 2 + 1 split group).

8. **The Audit log's quick periods are chips (item 25).**
   - Today, Today / 7 Days / 30 Days are three secondary buttons (about 258 px wide with their gaps) in the 280 px hero,
     whose content is 240 px wide, so 30 Days wraps.
   - They become the kit `Chip` in a `ChipGroup` labelled `T.audit.quickPeriods`. Each chip uses `on` (`aria-pressed`)
     for the period it matches. The three chips take about 221 px and fit on one line.
   - The "Any" link that clears the period stays a link after the chips. A link is not part of a button group
     (decision 12), so it may wrap under them.
   - **Amends design portal-ui-polish-2, decision 23** (the quick choices as buttons). Chips are the kit's control for
     a pressed quick choice.
   - Alternatives considered:
     - `sm` buttons (fail the 36 px phone size check);
     - a wider hero (moves the right zone on every Layout B page).

9. **Decisions on the 17 items marked "check".** There are six faults and eleven non-faults. The full disposition is in
   the table under decision 15.
   - **Faults, fixed:**
     - 12: the Next Date table's Enter Date button. Its column lacks `actions: true` in `ReviewItem.tsx`, so on a card it
       is squeezed into the value column. The column gains `actions: true`, so on a card the button takes the full
       width with no label, as every other actions cell does.
     - 19, 20, 37: decision 7.
     - 43, 44: decision 10.
   - **Not faults:**
     - 13 to 18: a native select's own clipping (decision 5).
     - 38, 39, 41, 42 at 375 px: the group is wider than the phone line it sits on, so it must wrap:
       - 38: Report Wrong Next Date, Correct It, Enter Next Date;
       - 39: Only Changed From Default with Reset to Default;
       - 41: the three calendar chips;
       - 42: Edit, Attach a New File, Delete.
     - 40 (the calendar's Today under the month at 375 px): it wraps for the same reason. The month navigator
       (Previous, the month title, Next) becomes one non-wrapping group (`calendar.module.css` `.monthNav`) beside
       Today. Next and Today are then not one run of buttons, and Today drops under the navigator on phones as a whole
       unit. Markup only; wide screens look the same.
   - The new split-group kind (decision 12) follows the same rule. It reports a wrap only when the buttons would fit on
     one line, so 38 to 42 do not raise it. If any of them does raise it on the real run, the developer fixes the group
     (a non-wrapping group or a phone stack) rather than loosening the kind.

10. **The case claim modal's footer stacks on phones (items 43 and 44).**
    - Below 640 px, `claim.module.css` `.footer` becomes a column, the buttons stretch to the full width and `.spacer` is
      hidden.
    - This applies to both footers in `ModalActions.tsx`: the actions and the inline step's Back / confirm.
    - The order stays the DOM order (Close first, the primary last), so the visual order matches the keyboard order.
    - From 640 px nothing changes.
    - Alternatives considered:
      - `column-reverse` with the primary on top (visual order differs from focus order);
      - leaving the 2 + 2 split with Close and Suggest Elsewhere on the first line and Claim alone on the second.

### C. The screen check

11. **The detectors become four uicheck kinds in `frontend/e2e/checks.ts`, added to `GEOMETRY_KINDS`.** They run
    inside `pageChecks` like the other kinds.
    - **Shared rules** for all four kinds:
      - only visible elements count;
      - visually hidden elements are skipped, as are `aria-hidden` decorations;
      - fixed or absolute layers (the toast, the segmented thumb) are skipped, together with what is inside them;
      - two elements are compared only within the same layer root: the page, or one open `dialog` / `alertdialog` /
        `menu` / `listbox` / `tooltip`;
      - "controls" means kit buttons (`data-ui=button`), fields (`data-ui=field`, the Office Picker's input),
        checkboxes and radios with their label, segments and segmented groups, chips, and badges.
    - **`overlap`**: two controls, neither inside the other, whose boxes (cut by their clipping ancestors) overlap by
      more than 1 px in both directions. It also covers the content of one table cell drawn over a neighbouring cell
      in the same row. Not counted:
      - the parts of one composite control: an input with its icon, code tag or clear button over it inside one
        wrapper, the segments of one switch, joined buttons, tabs;
      - a label over its own control.
    - **`text-overrun`**: the text of a button, segment, chip or badge with `overflow: visible` that either runs more
      than 1 px outside its border box, or uses up more than 2 px of its own inline padding. For a segment, the edge is
      the group's frame when that is nearer. It also covers the content of a table cell with `overflow: visible` that
      spills more than 1 px past its cell. Not counted:
      - a native `select` (decision 5);
      - text fields (as in the clipped check);
      - deliberate `text-overflow: ellipsis`.
    - **`tight-gap`**: two controls on one line closer than 8 px. "On one line" means their boxes share at least half of
      the smaller height. 8 px is `var(--s2)`, the smallest gap the kit puts between controls in a row. The kind also
      covers the texts of two different fields (labels or hints) on one line closer than 8 px. Not counted: composite
      controls as above, a label with its own control, and cells of different table columns.
    - **`split-group`** (the survey's misaligned-pair): a run of two or more consecutive sibling buttons or chips in
      one flex or grid container that is drawn on more than one line, when their widths plus the container's column
      gaps are no more than the content width of the container's parent. In other words, they would have fitted on one
      line. Not counted:
      - a deliberate stack: each button on its own line with the same left edge (decisions 7 and 10);
      - a text link (`Button variant="link"`, a plain `a`), which breaks the run.
    - Each finding names the element (as `describe()` does today) and gives the measure in pixels.
    - Alternatives considered:
      - keep the detectors as a separate sweep (it would not guard later rows);
      - report "check" items as warnings (the screen check has no warning level, and every item is decided here).

12. **The kinds are tuned once, on the real run, with no allow-list.**
    - The thresholds above come from the survey: 1 px, 2 px of padding, and 8 px.
    - If a kind raises something on the full run that is neither among the 44 items nor a fault under these rules, the
      developer narrows the rule in `checks.ts` (with a self-test proving the case) and records it in the report.
    - No per-page or per-element allow-list is added. Row 235's toast allow-list does not apply here.
    - Alternative considered: `data-uicheck-allow` attributes. Rejected: exceptions would spread page by page.

13. **A fourth width: 1024 × 768.**
    - `e2e/playwright.config.ts` `WIDTHS` gains `small-laptop: { width: 1024, height: 768 }`. This is above the 820 px
      breakpoint, so the side menu is shown and the right zone is about 416 px, as on the owner's screens.
    - `global-teardown.ts` `WIDTHS` and the contact sheet's header gain the 1024 px column.
    - A `State` with no `widths` now runs at all four widths. A `State` with explicit `widths` keeps them.
    - The run takes about a third longer.
    - Comments that say "375, 768 and 1280" (`uicheck.spec.ts`, `playwright.config.ts`, runbook section 16 if it names
      them) are updated.
    - Alternative considered: 1366 px, the owner's laptop. Rejected: at 1366 px the faults are mild, and 1024 px is
      where the grid is tightest.

14. **Anything new that the sweep finds is fixed in this row, under the same rules.**
    - The survey did not measure 1024 px, and the kinds will run on every state.
    - Whatever they report beyond the 44 items is fixed here if the fix is layout CSS or kit markup of the kinds above:
      - a floor that fits its cell;
      - `data-wide`;
      - a non-wrapping group;
      - a phone stack;
      - an actions column flag.
    - Each fix is listed in the report with its screen and width.
    - A fix that would need a wording change, a moved control or an API change stops the developer. That finding becomes
      a follow-up row and is not fixed here.

15. **Disposition of the 44 items** (numbers as in `REPORT.md`). Two fixes and both not-fault rules come from earlier
    decisions:
    - "grid" = decisions 1 and 2;
    - "switch" = decision 3;
    - "accepted" = not a fault (decision 9).

    | # | Screen, width | Kind | Disposition |
    |---|---|---|---|
    | 1, 2 | Data Collection Automatic, 1280 | overlap | fixed, decision 6 |
    | 3 | Audit log, 1280 | overlap | fixed, grid |
    | 4, 6 | Reports Hearings and Disposals, Pending Cases, 768 / 1280 | overlap | fixed, grid (owner's fault 2) |
    | 5, 7 | Reports Pending Actions, 768 / 1280 | overlap | fixed, grid (owner's fault 3) |
    | 8, 10 | case rail Upload a Document, 1280 / 375 | text-overrun | fixed, decision 7 |
    | 9, 11 | Case Inbox With Me, 768 | text-overrun | fixed, grid and switch (owner's fault 1) |
    | 12 (check) | case page Next Date table, 375 | text-overrun | fault, fixed, decision 9 |
    | 13 to 18 (check) | department, bench and head selects | text-overrun | accepted, decision 5 (title added) |
    | 19, 20 (check) | case rail Add Note, Set Stage, 375 | text-overrun | fault, fixed, decision 7 |
    | 21 | Reports Pending Actions hints, 1280 | tight-gap | fixed, grid and decision 4 |
    | 22 | case rail See All Remarks / Recall Case, 1280 | split | fixed, decision 7 |
    | 23, 24, 27 to 31, 36 | Search / More Filters on Cause List, My Cases, With Me, Department, Sent, Audit, Search, 768 / 1280 | split | fixed, decision 2 |
    | 25 | Audit log quick periods, 768 / 1280 | split | fixed, decision 8 |
    | 26 | Audit log four buttons, 375 / 1280 | split | 1280 fixed, decision 2; 375 accepted (wider than the phone line) |
    | 32 to 35 | Show Report / Refresh, four report tabs, 768 / 1280 | split | fixed, decision 2 (owner's fault 2) |
    | 37 (check) | case rail Quick Actions 2 + 1, 1280 | split | fault, fixed, decision 7 |
    | 38, 39, 41, 42 (check) | next-date toolbar, access row, calendar chips, note buttons, 375 | split | accepted |
    | 40 (check) | calendar Today, 375 | split | accepted; month navigator grouped, decision 9 |
    | 43, 44 (check) | case claim modal footer, 375 | split | fault, fixed, decision 10 |

16. **The layout signature is regenerated.**
    - Run `UPDATE_LAYOUT_SIGNATURE=1 npx vitest run src/components/ui/layoutSignature.test.ts` once, after the CSS is
      final.
    - The report lists which selectors changed. Only the selectors of decisions 1 to 10 may differ.
    - If the signature's normaliser does not yet read `@container` blocks, it learns them the way it reads `@media`, so
      a later change of the container rule shows in the signature.

### D. The toast follow-ups (rows 246 and 247, folded in on 12 Nov 2026)

17. **The toast closes when a focus-trapping overlay opens (row 246).**
    - **The fault.** Case Claim's toast carries Open Case Page, so by portal-motion decision 4 it never closes on its
      own. Opening the next case modal changes only the query string, so the toast stays. At `z-index: 70` it sits
      above the modal (60) and covers the footer's bottom-right corner: at 1366 × 768 the toast is at x 922–1342,
      y 692–744, and the modal ends at about y 714. On phones it is a strip 76 px above the bottom of the full-screen
      modal. Its link and Close Message are outside the modal's focus trap, so the keyboard cannot reach them.
    - **The fix.** Every overlay that runs `useOverlay` (the kit `Dialog`, `ConfirmDialog`, `Modal`, `SidePanel` and the
      phone drawer in `PortalShell`) closes the toast when it opens. Text-only and link toasts alike close, with the
      normal exit (`--med`; at once under reduced motion).
    - **How.**
      - A new module `components/ui/overlayEvents.ts` holds a listener set with `onOverlayOpen(listener): () => void`
        (it returns the unsubscribe) and `notifyOverlayOpen()`.
      - `useOverlay` calls `notifyOverlayOpen()` once each time it becomes active, **after** `firstFocus` has taken the
        focus. If the focus had been in the toast, `close()` then finds it gone and does not move it.
      - `ToastProvider` subscribes in an effect and calls its `close`.
      - The module exists so that `feedback.tsx` does not import `overlays.tsx`. `overlays.tsx` already imports
        `ErrorBanner` from `feedback.tsx`, and a two-way import would make a cycle.
    - **A toast raised while an overlay is already open stays.** It is the confirmation of something done inside that
      overlay and closes on its own timer. Only text-only toasts are raised that way: a confirmation inside a dialog
      that stays open is inline (portal-motion decision 2). Case Claim raises its link toast in the same handler that
      closes the modal, so the toast is not closed by its own modal.
    - **Kept from row 235.**
      - `z-index: 70`. A text-only toast raised inside an open side panel must stay visible above it.
      - A link toast has no timer. A link that disappears on a timer cannot be reached by keyboard (decision 4). Now
        that a modal no longer hides it, nothing calls for one.
      - Position, look, motion, the pause on hover or focus, Escape, and focus return (deviation 4).
    - **Amends portal-motion decision 4.** A toast now closes on Close, Escape, a new toast, a change of pathname, or
      an overlay opening.
    - **Alternatives considered:**
      - **toast below dialogs (`z-index` 59):** a text-only toast raised inside an open side panel would be hidden by
        the backdrop, and a link toast would still sit over the next modal's page, out of reach;
      - **a long timer for link toasts (for example 20 s, paused on hover or focus):** the toast would still cover the
        modal footer until the timer ran out, and the link could vanish before a keyboard user reaches it;
      - **close only when the claim modal opens (in `ClaimFrame`):** this mends one screen, and the next link toast or
        the phone drawer would show the fault again;
      - **keep the link inline, as for the User Detail notice:** moves the claim confirmation back into the page,
        which row 235 removed.

18. **Every toast is announced, even with the same text as the one showing (row 247).**
    - **The fault.** The visually hidden polite region (`role="status"`, `aria-atomic="true"`) gets unchanged text when
      a second toast repeats the first one's words. Live regions ignore unchanged content, so the second toast is not
      announced. `seq` restarts the timer only.
    - **The fix.** The region itself stays in the document at all times, as portal-motion decision 5 requires. Its
      words are rendered in one inner `<span key={shown.seq}>`. Every `toast()` therefore replaces the span with a new
      node, an addition that screen readers announce even when the text is the same. The words are written at once,
      as today, so `toastStatus()` and the screen tests that read it do not change.
    - The visible card does not change. It keeps its group name, its text hidden from screen readers, and its in-place
      replacement with no second entrance.
    - **Alternatives considered:**
      - **clear the region for one frame, then write:** the words arrive a frame (or more, for some screen readers)
        later, and every screen test reading the region straight after `toast()` would have to wait;
      - **key the region itself on `seq`:** a live region added to the page with its text already in it is often not
        registered in time, the very reason decision 5 keeps the region always present;
      - **alternate an invisible trailing character:** a whitespace-only change is not reliably announced.

19. **A screen-check state proves that the toast leaves when the case modal opens.**
    - The overlap kind skips fixed layers (decision 11), so it cannot see a toast over a modal. The state therefore
      asserts the fix itself.
    - **The state: `/claim/recommended (toast closed by the case modal)`**, at all four widths (decision 13).
      - `init`: `withFlash(...)` writes a confirmation into sessionStorage, as in portal-motion decision 15. The
        fixtures answer no claim, so the flash raises the toast. The rule is the same for text-only and link toasts.
      - `open`: wait for the toast group and hover it. Open the first row's case modal by its row control, as a
        person would, so only the query string changes. Wait for the dialog, then
        `expect(page.getByRole("group", { name: FLASH })).toBeHidden()`.
      - The screenshot shows the modal with no toast.
    - The state must give **0 findings** of every kind, the four new kinds included. If the assertion fails, the state
      fails.
    - The box comparison (Verification 3) lists this state as a new page and moves no existing box.

## Data
None. No table, column or reference code. No migration.

## Services
None.

## API
None. No endpoint is added or changed.

## Jobs
None.

## Tests
Vitest (frontend):
- `SegmentedField` renders its root with `data-wide`.
- `FilterCard`'s actions cell carries `data-wide` and still holds Search, More Filters (n) and the page's actions in
  that order. The existing `fcGrid` test stays.
- `CheckField` with `hint`:
  - renders the hint;
  - the checkbox's `aria-describedby` names the hint's id;
  - without `hint` there is no `aria-describedby`.
- `SelectField`:
  - `title` equals the chosen option's label, for plain options and for options under `groups`;
  - there is no `title` when the value is empty.
- `ReportForm` on Pending Actions: List the Cases is a `CheckField` whose description is the "Adds one row per case…"
  hint, and no bare `muted` span is left.
- `ReviewItem` columns: the actions column is flagged as an actions column, so its cell renders with the kit's
  actions-cell class.
- Rail: Quick Actions and the other button groups render inside the stacked containers. The Quick Actions still follow
  the three workflow flags (existing test unchanged).
- `ModalActions`: there is still one primary in the footer, and the button order is unchanged (existing tests).
- `AuditFilters`: the quick periods are chips in a group named by `T.audit.quickPeriods`. The chip matching the current
  period has `aria-pressed="true"`, and clicking 7 Days sets the period. This updates the test at `audit.test.tsx:168`.
- `MyCalendar`: Previous, the month title and Next sit inside one month-navigator group, and Today is outside it.
- `layoutSignature.test.ts` passes on the regenerated snapshot.
- The toast follow-ups (decisions 17 and 18), in `components/ui/toast.test.tsx` unless named otherwise:
  - **an overlay closes the toast:** with a link toast showing, opening a kit `Modal` empties the card and the status
    region (at once under reduced motion; after `DURATION.med` with motion). The same holds for a text-only toast with
    a `Dialog` and with a `SidePanel`;
  - **an overlay already open:** a text-only toast raised while a `Dialog` is open stays shown, and closes after
    `TOAST_MS`;
  - **closing an overlay** does not close the toast. The existing link test (still shown after 60 s) stays green;
  - **focus:** when a `Dialog` opens, the focus is on the dialog's first control, not given back to an element
    behind it;
  - **`overlayEvents`** (`components/ui/overlayEvents.test.ts`): `onOverlayOpen` listeners run once per
    `notifyOverlayOpen()`, and not after their unsubscribe. `useOverlay` notifies once each time it becomes active,
    never when it closes, and only after the focus has moved in;
  - **Case Claim** (`components/claim/claim.test.tsx`, after the existing claim test at line 315): after the claim,
    the toast with Open Case Page shows. Opening the next row's case modal changes only the query string, and then the
    toast's group, its link and its status words are gone;
  - **the repeat announcement:** `toast("Saved.")` twice keeps the same status region element, with the same text. The
    region's inner node is a different element after the second call. A different text also replaces the node;
  - **the region is always present:** the status region element is the same node before any toast, during a toast and
    after it closes (decision 5 unchanged).

Playwright self-tests (`e2e/uicheck-self.spec.ts`). Each kind gets a small page that breaks the rule and one that keeps
it, measured as the other self-tests are:
- `overlap`:
  - raised: a field drawn 10 px over its neighbour;
  - not raised: an input with its icon inside one wrapper;
  - not raised: a dialog drawn over the page.
- `text-overrun`:
  - raised: a nowrap button narrower than its text;
  - raised: a segment wider than its group's frame;
  - not raised: an ellipsis-truncated badge;
  - not raised: a narrow native select.
- `tight-gap`:
  - raised: a checkbox 0 px after a segmented switch on one line;
  - not raised: the segments of one switch;
  - not raised: a label and its own control.
- `split-group`:
  - raised: two buttons wrapping in a 180 px grid cell inside a 600 px parent;
  - not raised: four buttons wider than their parent wrapping;
  - not raised: a full-width column of buttons;
  - not raised: a link after two chips wrapping.
- `kept()` drops the four new kinds on a redirect. This is covered by `GEOMETRY_KINDS`, and the existing test runs over
  all of them.

The full screen check: every route and every interaction state at 375, 768, 1024 and 1280 px, with zero findings. This
includes the new state `/claim/recommended (toast closed by the case modal)` (decision 19) and its hidden-toast
assertion.

## Verification
The integrator:
1. Runs `npm test`, `npx tsc --noEmit` and `npm run lint` in `frontend/`. The backend suite (`pytest -q`, `ruff check`)
   stays green and unchanged, because no backend file changes.
2. Runs the screen check as in runbook section 16 (private network, temporary images, never through Compose on the
   shared stack):
   - expected: zero findings at all four widths;
   - the contact sheet shows four columns.
3. Runs the box comparison with `UICHECK_BOXES=1` before (on `main`) and after, and checks that every moved box belongs
   to a screen in the disposition table or to a fix listed under decision 14. The report states this.
4. Deploys from a clean worktree of `main`, with the app services force-recreated (frontend only, no `migrate` step).

The owner then checks, at 1024 and 1280 px:
- Case Inbox, With Me: "With My Offices" sits inside the switch with its padding, and Overdue Only has the row's gap;
- Reports, Pending Cases: Scope and the Show Report / Refresh pair are side by side with the gap, and both buttons are on
  one line;
- Reports, Pending Actions with Holder Department: three fields side by side, each hint under its own field, and the
  List the Cases box visible;
- Data Collection, Automatic: the order form has no overlap;
- the case rail: Quick Actions one per line;
- Audit log: the quick periods on one line.

At 375 px the owner checks the case claim modal's footer, stacked in order.

At 1366 px on Case Claim, the owner claims a case, sees the toast with Open Case Page, and then opens the next case.
The toast is gone and the modal's footer is clear (decision 17). With a screen reader, two confirmations with the same
words are each read out (decision 18).

## Open questions
None. Every "check" item is decided in decision 9. Three decisions amend earlier designs and are not plan deviations:
- decision 7 amends portal-screen-fixes-work decision 17 (Quick Actions one per line);
- decision 8 amends portal-ui-polish-2 decision 23 (quick periods as chips);
- decision 17 amends portal-motion decision 4 (a toast also closes when an overlay opens). Decision 18 changes only
  how portal-motion decision 5's region is filled.

The owner approves or changes them when approving this note.

## Deviations
Recorded by the developer while building (12 Nov 2026).

1. **Filter Layout B keeps 180 px tracks (decision 2).** Measured on the real run, the right zone's grid is about
   382 px wide at 1024 px and about 392 px at 768 px, not the 416 px the decision assumed. With 200 px tracks
   (412 px for two) both widths would drop to one column, against the decision's own "at 768 and 1024 px the right
   zone keeps two columns" and the owner's 1024 px checks (fields side by side). Decision 1 already makes every kit
   field and the Office Picker fit any track, so the tracks stay `minmax(min(180px, 100%), 1fr)` and the container
   rule is `@container fc-fields (min-width: 372px)` (two 180 px tracks and the 12 px gap). The size container,
   `data-wide` and the span are as designed.
2. **The four kinds, tuned on the real run (decision 12), each with a self-test.**
   - *split-group:* a run drawn one per line at one left edge counts as a deliberate stack only in a one-column grid or
     when each button fills the line. A 1+1 wrap in a wrapping row (Show Report / Refresh, the owner's fault 2) has
     exactly the geometry of a stack, so "same left edge" alone would have hidden it.
   - *tight-gap:* two badges side by side are not compared. A badge row keeps the kit's `var(--s1)` (4 px); badges are
     labels, not controls one presses. The first run raised only such rows (documents, notes, alerts, cause list).
     A badge next to a button is still measured.
   - *shared layers:* a `position: sticky` box (the Save bar, a table's sticky header) is a layer of its own, like a
     dialog. The Save bar floats over the "Only Changed From Default" chip at 375 px by design.
   - *texts of two fields:* each label or hint is cut by its clipping ancestors first. A label scrolled out of the case
     modal's body was otherwise "on the line" of the footer's Claim For label.
3. **The kit `Chip` and `Badge` carry `data-ui="chip"` and `data-ui="badge"`,** so the kinds find them without reading
   hashed class names. This is markup only; nothing is drawn differently.
4. **Decision 10 needed the phone modal to scroll as a whole.** With the footer stacked (about 200 px), the case claim
   modal's fixed header of case facts and the footer together were taller than a 375 × 812 phone, so Claim sat
   off-screen and could not be clicked (the Assign Now state timed out). Below 820 px the kit `Modal` now scrolls as
   one (`overflow-y: auto`), its body takes its natural height, and its footer sticks to the bottom
   (`overlays.module.css`). This is phone only; the laptop modal is unchanged.
5. **New finds of the 1024 px width fixed here (decision 14).**
   - *User type page, 1024 px (split-group):* "Only Changed From Default" and Reset to Default were split across
     lines. They are now one wrapping group (`admin.module.css` `.rowGroup`) that drops to the next line as a unit.
   - *Cause List, 1024 px (page-overflow and clipped, existing kinds):* the entries table cannot fit a department's
     full name beside the case below about 1100 px. Its existing card layout now applies up to 1099 px instead of
     819 px (`causelist.module.css`). This is the phone stack at a wider breakpoint; nothing changes from 1100 px.
   - *Search, 1024 px (inner-scroll, existing kind):* the kit `DataTable` measured its fit when the rows arrived. A
     department name that resolved later widened the table past its box, and nothing measured again. The fit observer
     now also watches the table and turns it into cards when it grows past the box (`data.tsx` `useFitTable`). This
     is a small kit script change rather than CSS. It was needed for zero findings at 1024 px.
6. **Data Collection's Save Priority (decision 6).** "The reason field and the items after it get `flex: 1 1 100%`",
   so Save Priority is on its own line under the reason. Before, it sat in the third column beside the reason.
7. **`docs/team/definition-of-done.md`** still names the widths as 375, 768 and 1280 px. It is left for the scribe,
   together with the decisions log.

### Build record
- The screen check, run as in runbook section 16 on a private network against temporary images, covered 177 routes
  and states with 569 screenshots at 375, 768, 1024 and 1280 px. It gave **0 findings** in 257 s. Playwright: 841
  passed, 11 skipped (states limited to other widths), self-tests included.
- The layout signature was regenerated. The changed selectors are those of decisions 1 to 10 and of deviations 4 and
  5: `.field` (controls, office picker), `.select`, `.checkField`, `.segmented`, `.segment`, `.fcGrid` and its
  `@container` rule, `.orderGrid` and children, `.span2`, rail `.buttons` / `.quick`, calendar `.monthNav`, claim
  `.footer` / `.spacer` (phone), the cause list's card block (819 → 1099 px), `.rowGroup`, and the phone `.modal`,
  `.modalBody` and `.modalFoot`.
