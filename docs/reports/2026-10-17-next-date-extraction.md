# Report: next-date-extraction (backlog row 26)

Merged 2026-10-17 as squash commit fa6e5fd on main, tag `feature/next-date-extraction-done`.

## What changed
- Migration 0018 (next dates: `next_dates` table and related reference data); schema.md updated first.
- Services: `next_date_rules.py` (text rules), `next_dates.py` (reader, court match, confirm / reject / enter), changes in alerts, calendar, case detail, cases, causelists, dashboard, visibility, seed, dedupe.
- API: next-dates endpoints (review queue, confirm, reject, enter) behind `next_dates.review`; `frontend/openapi.json` and `schema.d.ts` regenerated.
- Owner decision (option B): a date read from an order is firm only when it equals the court's own date (`cases.next_hearing_date` or a cause-list listing); otherwise it is a suggestion a person confirms. Matched suggestions close by themselves.
- Tests: test_next_date_rules, test_next_dates_read, test_next_dates_court_match, test_next_dates_review, test_api_next_dates, test_migration_0018.

## Gates
- ruff: All checks passed
- pytest: 1267 passed, 96 warnings (21m40s)
- docker compose build: succeeded
- portal smoke (frontend changed): passed
- git status clean; design note status approved; decisions-log entry (line 1730) and backlog row present

## Review findings (all advisory, none blocking)
1. `read_pending` matches rows before taking case locks in the batch (lock order differs from confirm / reject / enter; possible deadlock). Left open; recorded in row 74 (case locks held for the whole reader batch).
2. A prayer in the same sentence as the court's direction ("prays for time ..., list on 20.11.2026") reads `unclear` with no date, so it cannot match. Left open as a follow-up.
3. "Due to strike list on <date>" reads `unclear` (cautious side; goes to a person). Left open as a follow-up.

## Deviations
See design deviations in docs/design/next-date-extraction.md (deviation 16 is option B as built). Portal screens were split out as row 73.

## Follow-ups
Row 73 (portal-next-dates), row 74 (next-dates-followups). Findings 2 and 3 above are to be added to row 74's scope.

## Load status (queue-status)
order_pdf: done 32160, failed 3, pending 263721, skipped 146; status_batch: done 498, failed 1, skipped 6. Migration 0018 is not yet applied to the dev database (row 74).
