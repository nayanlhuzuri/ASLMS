# portal-ui-oversight-settings (row 105, round 5 of 5)

Date: 2026-10-21. Squash-merged to main as af2e2b3, tag feature/portal-ui-oversight-settings-done.

## What changed
Frontend only, no migration, no tables or endpoints. Reports, Audit log, Data collection and Administration
(Department mapping, Tickets) moved onto the Report, Work list, Dashboard and Settings templates; Users, Tickets
and Audit became DataTables; sign-in, code, reset, first-sign-in and error pages carry the brand (StatusPage);
deprecated token aliases removed; one primary action per page; responsive sweep.

## Gates
- ruff check: all checks passed
- pytest -q: 849 passed, 951 skipped
- docker compose build: succeeded
- web up (healthy), portal_smoke.py: passed
- git status clean on branch; design note status approved; decisions-log entry and backlog row present
- CI on main: no remote and no gh; CI status unknown

## Push
Not pushed: no remote (origin not configured). The owner pushes later (row 97).

## Review findings
- Advisory: legacy Tables remain on Data collection and some Administration screens (scroll sideways on phones) while the log says "Deviations: none". Not fixed; carried to row 112 (and should be recorded as a deviation).
- Advisory: the pages.test.tsx guard scans only src/app, not components used by server layouts (AuthFrame). Not fixed; carried to row 112.

## Deviations
The two items above (legacy tables left unconverted).

## Follow-up rows
112 portal-ui-oversight-followups.

## Load status
`aslms queue-status` did not return within 120 s during the run; load status not captured.
