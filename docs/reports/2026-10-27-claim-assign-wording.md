# claim-assign-wording (row 178), merged 2026-10-27

## What changed
- "Assign" replaces "Allot" in the portal: claim dialogs ("Assign Now (Optional)", Responsible Unit, Dealing Officer), the Assign This Case dialog, the ownership card, Department Cases column and filters, dashboard, inbox, exit dialog and error texts.
- Server texts: alert and e-mail texts, the custody reason label, the `cases.allot` function label, the report grouping. Codes, API and rules unchanged.
- "allot" guard added to both wording suites.
- Migration 0030 (reference data): relabels the `allotted` timeline label and the Department Officer description, only while they hold the seeded text. Not applied to the dev database; the owner's `migrate` step applies it.
- 35 files, 717 insertions, 125 deletions. No new tables or endpoints.

## Gates
- ruff check: clean; ruff format --check: 470 files formatted.
- pytest -q: 2511 passed, 3 skipped (33 min, test database per run).
- Frontend: eslint clean, tsc clean, vitest 76 files / 1540 tests passed, next build succeeded (security-advisory notice recorded as data; no upgrade run).
- docker compose build: succeeded.
- Portal smoke: passed.
- CI on main before merge: success (run 40409351379).
- Design note status: approved. Decisions-log entry and backlog row present.

## Push
See the integrator's final message; recorded below if pushed.

## Review findings
- Only finding: `ruff format` advisory on `backend/tests/unit/test_assign_alert_text.py`; closed in commit fa263e2.

## Deviations
None beyond those in the design note.

## Follow-ups
None added.

## Load status
`aslms queue-status` did not answer within 120 s at merge time; not recorded.

## Owner steps
Apply migration 0030 with the `migrate` step, then `docker compose build` (every `up` with the court-data switch on the command line).
