# Spacing and overlap sweep of the portal (row 245 `control-spacing-sweep`)

Survey only: run against a clean worktree of `origin/main` with temporary detectors added to a copy of the uicheck spec; no tracked file changed. Fixtures only, widths 375, 768 and 1280 px, every route and interaction state of `frontend/e2e/uicheck.spec.ts`.

## Counts

229 raw detections, deduplicated to **44 items** (the same fault at several widths or states is one item).

| Kind | Items | of which marked check | Raw detections |
|---|---|---|---|
| overlap | 7 | 0 | 21 |
| text-overrun | 13 | 9 | 94 |
| tight-gap | 1 | 0 | 1 |
| misaligned-pair | 23 | 8 | 113 |

| Screen | overlap | text-overrun | tight-gap | misaligned-pair | total |
|---|---|---|---|---|---|
| `/audit` | 1 | 0 | 0 | 3 | 4 |
| `/reports/pending-actions` | 2 | 0 | 1 | 1 | 4 |
| `/data/automatic` | 2 | 0 | 0 | 0 | 2 |
| `/reports/hearings-disposals` | 1 | 0 | 0 | 1 | 2 |
| `/reports/pending-cases` | 1 | 0 | 0 | 1 | 2 |
| `/cases/[case] (case page, every tab)` | 0 | 5 | 0 | 4 | 9 |
| `/inbox/with-me` | 0 | 2 | 0 | 1 | 3 |
| `/claim/recommended` | 0 | 1 | 0 | 2 | 3 |
| `/inbox/department` | 0 | 1 | 0 | 2 | 3 |
| `/causelist` | 0 | 1 | 0 | 1 | 2 |
| `/admin/tickets/new` | 0 | 1 | 0 | 0 | 1 |
| `/claim/pool` | 0 | 1 | 0 | 0 | 1 |
| `/claim/transfers` | 0 | 1 | 0 | 0 | 1 |
| `/inbox/my-cases` | 0 | 0 | 0 | 1 | 1 |
| `/inbox/sent` | 0 | 0 | 0 | 1 | 1 |
| `/reports/data-health` | 0 | 0 | 0 | 1 | 1 |
| `/search` | 0 | 0 | 0 | 1 | 1 |
| `/calendar` | 0 | 0 | 0 | 2 | 2 |
| `/admin/access/dept_officer` | 0 | 0 | 0 | 1 | 1 |

## The owner's three faults (validation of the detectors)

All three are caught. In the fixtures they are milder at 1280 px than on the owner's screenshots, so the
detectors were also run once at 1024 px (an extra validation run, not part of the counts): there each fault
appears in its full form. Validation crops are in `crops/validation-*`.

1. **Case Inbox, With Me, Show switch and Overdue Only** — caught. At 768 px the "With My Offices" segment is
   6 px wider than the switch's frame and its text sits 6 px from the frame's edge against 12 px of padding
   (text-overrun). At 1024 px the segment is 18 px wider than the frame, its text runs 6 px past the frame and
   the segment is drawn 5 px over the Overdue Only checkbox (overlap): exactly the owner's screenshot
   (`validation-inbox-with-me-1024.png`). At 1280 px the fixtures give the field enough room and nothing shows.
2. **Reports filter row, Scope against Show Report, Refresh on a second line** — caught on Pending Cases and
   Hearings and Disposals: the Scope (Department) Office Picker is drawn 3 px (1280) / 11 px (768) / 23 px
   (1024) over the Show Report button (overlap), and Show Report and Refresh fall on two lines (misaligned-pair)
   on all four report tabs at 768 and 1280 px.
3. **Reports, Pending Actions with Holder Department** — caught: the Scope picker overlaps the Holder Department
   picker (3 px at 1280, 11 px at 768, 23 px at 1024), the Holder Department picker is drawn 3 px over the
   List the Cases checkbox (overlap), and the List the Cases hint starts 3.7 px after the Holder Department hint
   on the same lines (tight-gap). In the fixtures the two hints touch rather than overprint; at 1024 px the
   Holder Department field runs past the card's right edge (the existing `gutter` check also flags this at
   1024 px only) and List the Cases drops below (`validation-reports-pending-actions-1024.png`).

**Common cause** (quick read): Filter Layout B's field grid, `components/ui/layout.module.css` `.fcGrid`
(`grid-template-columns: repeat(auto-fill, minmax(min(180px, 100%), 1fr))` with `.fcGrid > * { min-width: 0 }`),
gives each control a 180 px track, but the Office Picker (`officePicker.module.css` `.field { min-width: 220px }`,
input plus icon and code), the segmented switch (`controls.module.css` `.segmented` is `inline-flex`, its
`.segment`s do not wrap or shrink) and `controls.module.css` `.field { min-width: 200px }` cannot shrink to it,
so they spill into the next track and over its control. `.fcActions` (Show Report + Refresh) sits in one track of
the same grid, too narrow for both buttons, so Refresh wraps.


## Faults that recur across screens

The same element pattern on three or more screens; fixing the component fixes them all.

- **text-overrun** select[data-ui=field].controls:input.controls:select "…" — 6 screens (`/admin/tickets/new`, `/causelist`, `/claim/pool`, `/claim/recommended`, `/claim/transfers`, `/inbox/department`), widths 375, 768, 1280; items #13, #14, #15, #16, #17, #18
- **misaligned-pair** button[data-ui=button].controls:button.controls:control "…" / button[data-ui=button].controls:button.controls:control "…" — 13 screens (`/calendar`, `/cases/[case] (case page, every tab)`, `/causelist`, `/claim/recommended`, `/inbox/department`, `/inbox/my-cases`, `/inbox/sent`, `/inbox/with-me` …), widths 375, 768, 1280; items #22, #23, #24, #27, #28, #29, #31, #32, #33, #34, #35, #36 …

## Findings by screen

Screens ordered by their most severe finding; within a screen: overlaps, text overruns, tight gaps, misaligned pairs; items marked **check** are uncertain. Screenshots are in `crops/` (red outline = first element, blue = second).

### `/audit`

- **#3 overlap** at 1280 px — field and field overlap by 3×36 px
  - Elements: `input[role=combobox][data-ui=field].controls:input.controls:control "input:Any office"` ↔ `select[data-ui=field].controls:input.controls:select "select:Any Action"`
  - Where: /audit; /audit (Layout B with the Office Picker open)
  - Likely cause: the kit Office Picker (`officePicker.module.css` `.field { min-width: 220px }`, input with icon and code) in a filter grid track narrower than it, so it is drawn into the next track; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/003-overlap-audit-1280-1.png
- **#25 misaligned-pair** at 768, 1280 px — 3 buttons of one group fall on 2 lines (2+1) in a flex parent div[role=group]._3K9Cxq_quick
  - Elements: `button[data-ui=button].controls:button.controls:control "Today"` ↔ `button[data-ui=button].controls:button.controls:control "7 Days" | button[data-ui=button].controls:button.controls:control "30 Days"`
  - Where: /audit; /audit (Layout B with the Office Picker open)
  - Likely cause: `components/case/rail.module.css` `.quick` equal-width grid; the third button takes a second row (by design per `Rail.tsx`, but the tracks are narrower than "Upload a Document")
  - Screenshot: crops/025-misaligned-pair-audit-1280-2.png
- **#26 misaligned-pair** at 375, 1280 px — 4 buttons of one group fall on 2 lines (2+2) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters" | button[data-ui=button].controls:button.controls:control "Clear" | button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /audit; /audit (Layout B with the Office Picker open)
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/026-misaligned-pair-audit-1280-3.png
- **#30 misaligned-pair** at 768 px — 4 buttons of one group fall on 3 lines (1+2+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters" | button[data-ui=button].controls:button.controls:control "Clear" | button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /audit; /audit (Layout B with the Office Picker open)
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/030-misaligned-pair-audit-768-2.png

### `/reports/pending-actions`

- **#5 overlap** at 768, 1280 px — field and field overlap by 11×36 px
  - Elements: `input[role=combobox][data-ui=field].controls:input.controls:control "input:Choose an office"` ↔ `input[role=combobox][data-ui=field].controls:input.controls:control "input:All holders"`
  - Where: /reports/pending-actions
  - Likely cause: the kit Office Picker (`officePicker.module.css` `.field { min-width: 220px }`, input with icon and code) in a filter grid track narrower than it, so it is drawn into the next track; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/005-overlap-reports-pending-actions-1280-1.png
- **#7 overlap** at 1280 px — field and check overlap by 3×16 px
  - Elements: `input[role=combobox][data-ui=field].controls:input.controls:control "input:All holders"` ↔ `input "input:checkbox"`
  - Where: /reports/pending-actions
  - Likely cause: the kit Office Picker (`officePicker.module.css` `.field { min-width: 220px }`, input with icon and code) in a filter grid track narrower than it, so it is drawn into the next track; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/007-overlap-reports-pending-actions-1280-2.png
- **#21 tight-gap** at 1280 px — 3.7 px between texts of two neighbouring fields (hint / hint) on one line
  - Elements: `span.controls:hint "Narrows the cases with a pending action; overdue compliance "` ↔ `span.muted "Adds one row per case you may open, 50 per page."`
  - Where: /reports/pending-actions
  - Likely cause: `ReportForm.tsx` puts List the Cases and its `muted` hint in a bare `<div>` as a `.fcGrid` item beside the Holder Department Office Picker, which is wider than its 180 px track and runs up to the hint; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/021-tight-gap-reports-pending-actions-1280-3.png
- **#34 misaligned-pair** at 768, 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Show Report"` ↔ `button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /reports/pending-actions
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/034-misaligned-pair-reports-pending-actions-1280-4.png

### `/data/automatic`

- **#1 overlap** at 1280 px — field and field overlap by 53×36 px
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Case Details First"` ↔ `input[data-ui=field].controls:input.controls:control "input:date"`
  - Where: /data/automatic; data-automatic-no-department-names; data-automatic-pause-dialog; data-automatic-priority; +2 more
  - Likely cause: `components/data/collection.module.css` `.orderGrid` (`repeat(3, minmax(0, 1fr))`, fieldset spanning 2 with `repeat(2, minmax(0, 1fr))`) while each date field keeps `controls.module.css` `.field { min-width: 200px }`: the columns are narrower than the fields at 1280 px with the side menu
  - Screenshot: crops/001-overlap-data-automatic-1280-1.png
- **#2 overlap** at 1280 px — field and field overlap by 55×36 px
  - Elements: `input[data-ui=field].controls:input.controls:control "input:date"` ↔ `input[data-ui=field].controls:input.controls:control "input:date"`
  - Where: /data/automatic; data-automatic-no-department-names; data-automatic-pause-dialog; data-automatic-priority; +2 more
  - Likely cause: `components/data/collection.module.css` `.orderGrid` (`repeat(3, minmax(0, 1fr))`, fieldset spanning 2 with `repeat(2, minmax(0, 1fr))`) while each date field keeps `controls.module.css` `.field { min-width: 200px }`: the columns are narrower than the fields at 1280 px with the side menu
  - Screenshot: crops/002-overlap-data-automatic-1280-2.png

### `/reports/hearings-disposals`

- **#4 overlap** at 768, 1280 px — field and button overlap by 11×36 px
  - Elements: `input[role=combobox][data-ui=field].controls:input.controls:control "input:Choose an office"` ↔ `button[data-ui=button].controls:button.controls:control "Show Report"`
  - Where: /reports/hearings-disposals
  - Likely cause: the kit Office Picker (`officePicker.module.css` `.field { min-width: 220px }`, input with icon and code) in a filter grid track narrower than it, so it is drawn into the next track; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/004-overlap-reports-hearings-disposals-1280-1.png
- **#33 misaligned-pair** at 768, 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Show Report"` ↔ `button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /reports/hearings-disposals
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/033-misaligned-pair-reports-hearings-disposals-1280-2.png

### `/reports/pending-cases`

- **#6 overlap** at 768, 1280 px — field and button overlap by 11×36 px
  - Elements: `input[role=combobox][data-ui=field].controls:input.controls:control "input:Choose an office"` ↔ `button[data-ui=button].controls:button.controls:control "Show Report"`
  - Where: /reports/pending-cases
  - Likely cause: the kit Office Picker (`officePicker.module.css` `.field { min-width: 220px }`, input with icon and code) in a filter grid track narrower than it, so it is drawn into the next track; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/006-overlap-reports-pending-cases-1280-1.png
- **#35 misaligned-pair** at 768, 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Show Report"` ↔ `button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /reports/pending-cases
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/035-misaligned-pair-reports-pending-cases-1280-2.png

### `/cases/[case] (case page, every tab)`

- **#8 text-overrun** at 1280 px — button text runs 1 px past its left edge
  - Elements: `button[data-ui=button].controls:button.controls:control "Upload a Document"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001; /cases/ASLMS-GHC-CASE-2026-000001 (Assign dialog); /cases/ASLMS-GHC-CASE-2026-000001 (More button focused); /cases/ASLMS-GHC-CASE-2026-000001 (More menu open); +21 more
  - Likely cause: `components/case/rail.module.css` `.quick` (`repeat(auto-fit, minmax(5.5rem, 1fr))`) makes equal tracks narrower than the longest label; the kit button keeps `white-space: nowrap`, so the text eats its padding and runs past its edge
  - Screenshot: crops/008-text-overrun-cases-aslms-ghc-case-2026-000001-1280-1.png
- **#10 text-overrun** at 375 px — button text runs 20 px past its right edge
  - Elements: `button[data-ui=button].controls:button.controls:control "Upload a Document"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001 (rail cards open)
  - Likely cause: `components/case/rail.module.css` `.quick` (`repeat(auto-fit, minmax(5.5rem, 1fr))`) makes equal tracks narrower than the longest label; the kit button keeps `white-space: nowrap`, so the text eats its padding and runs past its edge
  - Screenshot: crops/010-text-overrun-cases-aslms-ghc-case-2026-000001-rail-cards-open-375-4.png
- **#12 text-overrun** (check) at 375 px — cell content spills 7 px past its cell
  - Elements: `td "Enter Date…"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001; /cases/ASLMS-GHC-CASE-2026-000001 (Assign dialog); /cases/ASLMS-GHC-CASE-2026-000001 (More button focused); /cases/ASLMS-GHC-CASE-2026-000001 (More menu open); +8 more
  - Likely cause: the Next Date review table drawn as cards at 375 px: the Enter Date button is wider than its value cell (`components/ui/data.module.css` card rows)
  - Screenshot: crops/012-text-overrun-cases-aslms-ghc-case-2026-000001-375-1.png
- **#19 text-overrun** (check) at 375 px — button text eats into its padding (13 px left, 13 px right of 16/16 px)
  - Elements: `button[data-ui=button].controls:button.controls:control "Add Note"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001 (rail cards open)
  - Likely cause: the rail's Quick Actions at phone width (`rail.module.css` `.quick`): buttons squeezed below their label width
  - Screenshot: crops/019-text-overrun-cases-aslms-ghc-case-2026-000001-rail-cards-open-375-3.png
- **#20 text-overrun** (check) at 375 px — button text eats into its padding (13 px left, 13 px right of 16/16 px)
  - Elements: `button[data-ui=button].controls:button.controls:control "Set Stage"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001 (rail cards open)
  - Likely cause: the rail's Quick Actions at phone width (`rail.module.css` `.quick`): buttons squeezed below their label width
  - Screenshot: crops/020-text-overrun-cases-aslms-ghc-case-2026-000001-rail-cards-open-375-5.png
- **#22 misaligned-pair** at 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div._479l4W_buttons
  - Elements: `button[data-ui=button].controls:button.controls:control "See All Remarks (5)"` ↔ `button[data-ui=button].controls:button.controls:control "Recall Case"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001; /cases/ASLMS-GHC-CASE-2026-000001 (Assign dialog); /cases/ASLMS-GHC-CASE-2026-000001 (More button focused); /cases/ASLMS-GHC-CASE-2026-000001 (More menu open); +19 more
  - Likely cause: `components/case/rail.module.css` `.buttons` (flex-wrap) in the 300 px rail: the two buttons do not fit side by side; check whether stacking is intended
  - Screenshot: crops/022-misaligned-pair-cases-aslms-ghc-case-2026-000001-1280-2.png
- **#37 misaligned-pair** (check) at 1280 px — 3 buttons of one group fall on 2 lines (2+1) in a grid parent div._479l4W_quick
  - Elements: `button[data-ui=button].controls:button.controls:control "Add Note"` ↔ `button[data-ui=button].controls:button.controls:control "Upload a Document" | button[data-ui=button].controls:button.controls:control "Set Stage"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001; /cases/ASLMS-GHC-CASE-2026-000001 (Assign dialog); /cases/ASLMS-GHC-CASE-2026-000001 (More button focused); /cases/ASLMS-GHC-CASE-2026-000001 (More menu open); +21 more
  - Likely cause: `components/case/rail.module.css` `.quick` (`repeat(auto-fit, minmax(5.5rem, 1fr))`) makes equal tracks narrower than the longest label; the kit button keeps `white-space: nowrap`, so the text eats its padding and runs past its edge
  - Screenshot: crops/037-misaligned-pair-cases-aslms-ghc-case-2026-000001-1280-3.png
- **#38 misaligned-pair** (check) at 375 px — 3 buttons of one group fall on 2 lines (1+2) in a flex parent div.xaUKiG_toolbar
  - Elements: `button[data-ui=button].controls:button.controls:control "Report Wrong Next Date"` ↔ `button[data-ui=button].controls:button.controls:control "Correct It" | button[data-ui=button].controls:button.controls:control "Enter Next Date"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001; /cases/ASLMS-GHC-CASE-2026-000001 (Assign dialog); /cases/ASLMS-GHC-CASE-2026-000001 (More button focused); /cases/ASLMS-GHC-CASE-2026-000001 (More menu open); +8 more
  - Likely cause: the next-date toolbar (`CaseNextDate.tsx`, `.toolbar`, flex-wrap) at phone width
  - Screenshot: crops/038-misaligned-pair-cases-aslms-ghc-case-2026-000001-375-3.png
- **#42 misaligned-pair** (check) at 375 px — 3 buttons of one group fall on 2 lines (2+1) in a flex parent div.row
  - Elements: `button[data-ui=button].controls:button.controls:control "Edit"` ↔ `button[data-ui=button].controls:button.controls:control "Attach a New File" | button[data-ui=button].controls:button.controls:control "Delete"`
  - Where: /cases/ASLMS-GHC-CASE-2026-000001/notes
  - Likely cause: the global `.row` utility (flex-wrap) at phone width
  - Screenshot: crops/042-misaligned-pair-cases-aslms-ghc-case-2026-000001-notes-375-1.png

### `/inbox/with-me`

- **#9 text-overrun** at 768 px — segment is 6 px wider than its group's frame; its text sits 6.0 px from the frame's edge (own padding 12 px)
  - Elements: `button[role=radio].controls:segment "With My Offices"` ↔ `div[role=radiogroup].controls:segmented "Show"`
  - Where: /inbox/with-me; /inbox/with-me (Ready to Close chip); /inbox/with-me (side panel)
  - Likely cause: `components/ui/controls.module.css` `.segmented` (inline-flex) / `.segment` (nowrap, does not shrink) inside a `.fcGrid` track narrower than the switch; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/009-text-overrun-inbox-with-me-768-1.png
- **#11 text-overrun** at 768 px — segment is 6 px wider than its group's frame; its text sits 6.0 px from the frame's edge (own padding 12 px)
  - Elements: `button[role=radio].controls:segment.controls:segmentOn "With My Offices"` ↔ `div[role=radiogroup].controls:segmented "Show"`
  - Where: /inbox/with-me?held=offices
  - Likely cause: `components/ui/controls.module.css` `.segmented` (inline-flex) / `.segment` (nowrap, does not shrink) inside a `.fcGrid` track narrower than the switch; `components/ui/layout.module.css` `.fcGrid` (Filter Layout B: `repeat(auto-fill, minmax(min(180px, 100%), 1fr))`, `.fcGrid > * { min-width: 0 }`) gives the control a 180 px track it cannot shrink to
  - Screenshot: crops/011-text-overrun-inbox-with-me-held-offices-768-1.png
- **#27 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /inbox/with-me; /inbox/with-me (Ready to Close chip); /inbox/with-me (side panel); /inbox/with-me?held=offices
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/027-misaligned-pair-inbox-with-me-768-2.png

### `/claim/recommended`

- **#15 text-overrun** (check) at 375, 768, 1280 px — select's chosen text "Directorate of Secondary Education, Kahi" is 396 px, room 297 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Directorate of Secondary Education, Kahilipara, Guwahati-19"`
  - Where: /claim/recommended; /claim/recommended (case claim modal); /claim/recommended (case claim modal, Assign Now)
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/015-text-overrun-claim-recommended-1280-1.png
- **#43 misaligned-pair** (check) at 375 px — 4 buttons of one group fall on 2 lines (2+2) in a flex parent div.pueZSa_footer
  - Elements: `button[data-ui=button].controls:button.controls:control "Close"` ↔ `button[data-ui=button].controls:button.controls:control "Suggest Elsewhere" | button[data-ui=button].controls:button.controls:control "Dismiss" | button[data-ui=button].controls:button.controls:control "Claim"`
  - Where: /claim/recommended (case claim modal)
  - Likely cause: the case claim modal footer (flex-wrap) at phone width
  - Screenshot: crops/043-misaligned-pair-claim-recommended-case-claim-modal-375-2.png
- **#44 misaligned-pair** (check) at 375 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.pueZSa_footer
  - Elements: `button[data-ui=button].controls:button.controls:control "Back"` ↔ `button[data-ui=button].controls:button.controls:control "Claim for Sample value with a fair length"`
  - Where: /claim/recommended (case claim modal, Assign Now)
  - Likely cause: the case claim modal footer (flex-wrap) at phone width
  - Screenshot: (none: beyond the crop limit)

### `/inbox/department`

- **#13 text-overrun** (check) at 375, 768, 1280 px — select's chosen text "Directorate of Secondary Education, Kahi" is 396 px, room 297 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Directorate of Secondary Education, Kahilipara, Guwahati-19"`
  - Where: /inbox/department; /inbox/department (quick filters); /inbox/department?action=overdue&holder=elsewhere; /inbox/department?closure=closed
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/013-text-overrun-inbox-department-1280-1.png
- **#28 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /inbox/department; /inbox/department (quick filters); /inbox/department?closure=closed
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/028-misaligned-pair-inbox-department-768-2.png
- **#31 misaligned-pair** at 768, 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters (2)"`
  - Where: /inbox/department?action=overdue&holder=elsewhere
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/031-misaligned-pair-inbox-department-action-overdue-holder-elsewhere-1280-2.png

### `/causelist`

- **#14 text-overrun** (check) at 375, 768, 1280 px — select's chosen text "Court 1 · HONOURABLE THE CHIEF JUSTICE, " is 647 px, room 151 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Court 1 · HONOURABLE THE CHIEF JUSTICE, HONOURABLE MR. JUSTICE SOUMITRA SAIKIA · 58"`
  - Where: /causelist (More Filters open); /causelist (View Cause List modal, Original PDF); /causelist (View Cause List modal, Printed Entries)
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/014-text-overrun-causelist-more-filters-open-1280-1.png
- **#23 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /causelist; /causelist (All Benches, note and heading PDF links); /causelist (Choose a Bench open); /causelist (Choose a Bench, Original PDF); +3 more
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/023-misaligned-pair-causelist-768-1.png

### `/admin/tickets/new`

- **#18 text-overrun** (check) at 375 px — select's chosen text "Set a head (the department has none)" is 250 px, room 247 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Set a head (the department has none)"`
  - Where: /admin/tickets/new; /admin/tickets/new (Incoming Head)
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/018-text-overrun-admin-tickets-new-375-1.png

### `/claim/pool`

- **#16 text-overrun** (check) at 375, 768, 1280 px — select's chosen text "Directorate of Secondary Education, Kahi" is 396 px, room 297 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Directorate of Secondary Education, Kahilipara, Guwahati-19"`
  - Where: /claim/pool
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/016-text-overrun-claim-pool-1280-1.png

### `/claim/transfers`

- **#17 text-overrun** (check) at 375, 768, 1280 px — select's chosen text "Directorate of Secondary Education, Kahi" is 396 px, room 297 px (cut off by the arrow area)
  - Elements: `select[data-ui=field].controls:input.controls:select "select:Directorate of Secondary Education, Kahilipara, Guwahati-19"`
  - Where: /claim/transfers
  - Likely cause: a native `select` (`controls.module.css` `.select`) narrower than its chosen option; the browser cuts the text without an ellipsis
  - Screenshot: crops/017-text-overrun-claim-transfers-1280-1.png

### `/inbox/my-cases`

- **#24 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /inbox/my-cases; /inbox/my-cases (Search Words on the first row); /inbox/my-cases (badges); /inbox/my-cases (next hearing bands); +1 more
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/024-misaligned-pair-inbox-my-cases-768-1.png

### `/inbox/sent`

- **#29 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /inbox/sent; /inbox/sent (still out); /inbox/sent?earlier=true
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/029-misaligned-pair-inbox-sent-768-1.png

### `/reports/data-health`

- **#32 misaligned-pair** at 768, 1280 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Show Report"` ↔ `button[data-ui=button].controls:button.controls:control "Refresh"`
  - Where: /reports/data-health
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/032-misaligned-pair-reports-data-health-1280-1.png

### `/search`

- **#36 misaligned-pair** at 768 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.JvSkDG_fcActions
  - Elements: `button[data-ui=button].controls:button.controls:control "Search"` ↔ `button[data-ui=button].controls:button.controls:control "More Filters"`
  - Where: /search; /search (Layout B)
  - Likely cause: `components/ui/layout.module.css` `.fcActions` (flex-wrap) sits in one `.fcGrid` track (about 180 px), too narrow for both buttons, so the second wraps under the first
  - Screenshot: crops/036-misaligned-pair-search-768-1.png

### `/calendar`

- **#40 misaligned-pair** (check) at 375 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div.lszbQG_head
  - Elements: `button[data-ui=button].controls:button.controls:control "Next Month"` ↔ `button[data-ui=button].controls:button.controls:control "Today"`
  - Where: /calendar
  - Likely cause: the calendar header (flex-wrap) at phone width
  - Screenshot: crops/040-misaligned-pair-calendar-375-1.png
- **#41 misaligned-pair** (check) at 375 px — 3 buttons of one group fall on 2 lines (2+1) in a flex parent div[role=group].JpILRG_chips
  - Elements: `button.controls:chip.controls:chipOn "Hearings"` ↔ `button.controls:chip.controls:chipOn "My Action Due" | button.controls:chip.controls:chipOn "Next Date to Enter"`
  - Where: /calendar
  - Likely cause: `components/ui/controls.module.css` `.chips` (flex-wrap) at phone width
  - Screenshot: crops/041-misaligned-pair-calendar-375-2.png

### `/admin/access/dept_officer`

- **#39 misaligned-pair** (check) at 375 px — 2 buttons of one group fall on 2 lines (1+1) in a flex parent div[role=search].row
  - Elements: `button.controls:chip "Only Changed From Default"` ↔ `button[data-ui=button].controls:button.controls:control "Reset to Default"`
  - Where: /admin/access/dept_officer; /admin/access/dept_officer (Edit Name dialog); /admin/access/dept_officer (two switches changed, Save bar)
  - Likely cause: `components/ui/controls.module.css` `.chips` (flex-wrap) at phone width
  - Screenshot: crops/039-misaligned-pair-admin-access-dept-officer-375-1.png

