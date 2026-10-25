# portal-ui-polish-2-admin (row 162)

Merged 2026-10-26 as squash commit 5eeab72 on main, tag `feature/portal-ui-polish-2-admin-done`.

## What changed
Round 2 of the approved navigation mockup (decisions 27-43): `GET /admin/offices/choices`, the `subtree` and `office_subtree` filters, the Office Picker (Add User, Department Mapping, Reports, Audit Log), the Users toolbar, the User Details modal and the simpler Department Mapping page. 53 files. No migration, no new table.

## Gates
- ruff check: all checks passed
- pytest -q: 2368 passed, 3 skipped (29 min)
- docker compose build: succeeded
- portal smoke (frontend changed): passed
- git status clean; design note status approved; decisions-log entry and backlog row present
- CI on main (gh run list): last run success (Secret scan, 2026-10-25)

## Review findings
Two advisories, closed as follow-up rows:
1. Office Picker cache not cleared after an office is created or deactivated (up to 10 minutes stale; server re-checks writes): row 166.
2. Change Office ignores the generic-code rule in the picker (server refuses with 422): row 167.

## Deviations
None beyond those recorded in the design note (deviations 7 and 8 are row 165).

## Follow-up rows
166, 167 (new); 165 existing.

## Push
See the integrator's return values; pushed fast-forward only.

## Load status
`aslms queue-status` gave no output within 60 s; load status unavailable.
