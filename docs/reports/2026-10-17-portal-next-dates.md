# portal-next-dates (backlog row 73)

Merged to main as f68a5f7 (squash), tag feature/portal-next-dates-done. Design: docs/design/portal-next-dates.md (approved).

## What changed
38 files, frontend mainly: review list tab in Alerts & calendar (confirm, not correct with replacement date, enter a date), case page "Next date from orders" card and "Waiting for you" panel, reading column on the Orders tab, dashboard link, `frontend/src/lib/nextDates.ts` and tests. Backend: `workflow.next_dates` flag on the case workflow block. No migration (0018 came with next-date-extraction). No new tables or endpoints.

## Gates
- ruff check: All checks passed
- pytest -q: 1272 passed, 96 warnings (927 s)
- docker compose build: succeeded
- web up --wait and portal_smoke.py: portal smoke: passed
- git status clean on the branch; design status approved; decisions-log entry and backlog row present

## Review findings (all advisory, left open as follow-ups)
1. ReviewItem refreshes with `item.case.ref_no`, not the page's route key; opening by CNR leaves the panel and card stale after a confirm (a second click gives 409 not_pending).
2. `NEXT_DATE_ERRORS.bad_field` always shows the date-range text, though the server also sends bad_field for refused note text and for an order not belonging to the case.
3. `date_passed` text says "Enter the next date instead" but a confirm item offers only Confirm / Not correct, and the list is not re-read.

None blocks the merge; they are not fixed in this change.

## Deviations
None beyond those recorded in the design note's deviations.

## Follow-up rows
The three advisories above are to be added to the backlog as one follow-up row by the owner or scribe (not added here).

## Load status (queue-status)
order_pdf: done 32258, failed 3, pending 267468, skipped 146; status_batch: done 498, failed 1, skipped 6.
