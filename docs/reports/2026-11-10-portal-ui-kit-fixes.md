# Report: portal-ui-kit-fixes (row 231)

Date: 2026-11-10. Branch `feature/portal-ui-kit-fixes`, squash-merged into `main`, tag `feature/portal-ui-kit-fixes-done`.

## What changed
Frontend only (about 100 files), no migration, no API change: caption inset, dates that do not wrap inside
day-month-year, phone-card alignment with empty rows hidden, title before badge, one empty-state rule (compact
`EmptyState`), link placement and plurals; new vitest guards (`emptyState.guard.test.ts`, `messages.plural.test.ts`,
`src/test/dates.ts`); uicheck gained caption-inset, date-wrap, broken-word and card-row checks. The decisions-log
entry and backlog row exist. The decisions log conflicted on merge with row 238's entry (both appended); both kept.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3209 passed, 3 skipped (51 min).
- `docker compose build`: succeeded (api, worker, scheduler, web, pgbouncer built).
- Screen check on a private network against a `web` image built from the branch (runbook section 16): 572 passed
  (phone, tablet, laptop). Temporary images and network removed; the shared stack was not touched.
- CI on `main` before the merge: success (run 42809252978).
- `git status` clean on the branch; design note status `approved`.

## Review findings
- Blocking (Pending Actions card said "No Pending Actions" while the KPI counted some): closed in 1719abb; the card
  is hidden when `items` is null and the empty line says "no overdue actions" unless `held` is 0.
- Advisories (guard misses `x ? ... : <p muted>` forms; remaining muted empty paragraphs; day-month break in a
  same-year range; the empty-row CSS rule and void children): not closed here, filed as row 239.

## Deviations
None beyond the above.

## Follow-ups
Row 239 `portal-ui-kit-fixes-followups`.

## Load status
`aslms queue-status` did not answer within 120 s in this run; not recorded.

## Deployed
10 Nov 2026 at 23:52 IST, images built from clean `main` (f7af1e7) after CI run 42870426230 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`wfTFkvDk4uSlAVNAyZu6a`), and `portal_smoke.py` passed.
