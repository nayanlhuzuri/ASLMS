# Report: offices-import-followups (row 261)

Date: 2026-11-15. Branch `feature/offices-import-followups`, squash-merged as e50b2e8, tag `feature/offices-import-followups-done`.
Design: [offices-import-followups.md](../design/offices-import-followups.md) (approved by the owner 15 Nov 2026).

## What changed
- `backend/aslms/services/offices_import.py`: every row read whatever stored dimension; codes checked on all rows (Include? = No / To Decide too); inactive designations refused (`designation_inactive`); names over 200 characters refused (`bad_name`, `bad_designation`).
- Tests: `tests/unit/test_offices_import_read.py`, `test_offices_import_rules.py`, `tests/db/test_offices_import.py`, helper `tests/offices_workbook.py`.
- Docs: decisions log, `docs/operations.md`, `docs/design/offices-import.md`, backlog, CLAUDE.md.
- No tables, no endpoints, no migration, no frontend change.

## Gates
- CI on main: last run success (run 43673208995).
- `ruff check .`: All checks passed.
- `pytest -q`: 3515 passed, 3 skipped (1:10:32).
- `docker compose build`: succeeded (frontend unchanged, no screen check needed).
- git status clean on branch; design status approved; decisions-log entry and backlog row present.

## Review findings
None recorded for this cycle.

## Deviations
None.

## Follow-up rows
None.

## Push
See the final commit notes; fast-forward push of `main` and the tag.

## Load status
`aslms queue-status` did not return within the 2-minute limit during the merge (database busy); not recorded.
