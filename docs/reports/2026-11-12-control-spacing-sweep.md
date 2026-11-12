# Control spacing sweep (rows 245, 246, 247)

Date: 12 Nov 2026. Branch `feature/control-spacing-sweep`, squash-merged to `main` as `85e6bf3`, tag `feature/control-spacing-sweep-done`. Design: `docs/design/control-spacing-sweep.md`.

## What changed
Frontend only: no migration, no API change, no schema change (45 files).
- Kit: fields and the Office Picker fit Filter Layout B's grid cell; the grid is a size container; the segmented switch hugs its options; the Reports hint sits under its own field.
- Screens (44-item sweep of 11 Nov): Data Collection order form, case rail buttons one per line, Audit log quick periods as chips, Enter Date actions column, calendar month navigator, claim modal footer on phones.
- Row 246: the Case Claim toast closes when an overlay opens. Row 247: every toast is announced, repeats included.
- Screen check: four new kinds (`overlap`, `text-overrun`, `tight-gap`, `split-group`), a 1024 px width, the toast state.
- Merge note: `CLAUDE.md` conflicted in the current-focus paragraph (row 235 deploy note on main versus row 245 on the branch); resolved by keeping both statements and moving 245 to "merged, deploy pending".

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3245 passed, 3 skipped (60 min 44 s).
- `docker compose build`: succeeded (no `up`; shared stack untouched).
- Screen check on a private network with temporary images built from the branch (runbook section 16): 177 routes and states, 569 screenshots, 0 findings; Playwright 841 passed, 11 skipped. Container, network and images removed.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog rows present.
- CI on main before merge: success (`portal-motion: deployed 12 Nov 2026 at 08:13`).

## Review findings and how closed
1. Advisory, phone Modal scrolls as one box (header and Close lost on scroll; footer floats under a short body). Not fixed here; follow-up row 248 (a).
2. Advisory, a flash toast raised on a page that opens an overlay on mount stays above the overlay. No current flash target does this; follow-up row 248 (b).
3. Advisory, `definition-of-done.md` and the decisions log still named three widths. Closed by the integrator: definition of done now names 375, 768, 1024 and 1280 px; the decisions log already records the 1024 px width, the four kinds and the amended decisions.

## Deviations
Seven, listed in the design note. Deviation 4 (phone Modal scrolling as a whole) has the side effects in finding 1.

## Follow-up rows
248 `modal-phone-and-flash-followups`.

## Load status
`aslms queue-status` did not return within 60 s when run; not captured. The deploy of this row is the owner's next step (compose build done; no `up` by the integrator).

## Deployed
- 12 Nov 2026 at 12:40 IST from main `a8821ce` (row 245 plus the designation code rename `c11197c` and a test formatting fix). CI run 43169362327 success; run 43168768306 failed on `ruff format` of one test line (fixed in `a8821ce`), and the superseded run 43168623121 was cancelled.
- `docker compose --profile monitoring up -d --wait` with the court-data switch on, then the same with `--no-deps --force-recreate api worker scheduler web`. Switch on in api and worker; `SMTP_HOST` mailpit; web BUILD_ID `nhsXI7BMA1G_r5YMkvTjz` matches the image; `portal_smoke.py` passed.
- Designation codes: the `init` seed of this deploy ran with the new list before the dev rows were renamed and added seven duplicate rows (created 12:40, unreferenced: no membership, login or audit row). With the owner's approval they were deleted, and the seven original rows were renamed in one transaction with a `designation.update` audit row each (actor `ops`, `before` / `after` the code). Result: 19 designations, the new codes on the original rows. Lesson: for a seeded-code rename, rename the rows before the deploy whose `init` carries the new list.
- Owner checks in the browser: the Audit Log filters, Reports → Pending Actions with Holder Department, the With Me switch, and Administration → Designations.
