# Report: followups-oct (backlog row 137)

Date: 2026-10-25. Branch `feature/followups-oct`, squash-merged into `main` as a030c81, tag `feature/followups-oct-done`.

## What changed
- Rows 113, 114, 126, 129, 130, 132, 133, 134 bundled; no migration (dev database stays at 0024).
- Apart-write engine and per-process NAPIX request slots (503 `napix_busy`); renewal steps left out of failure counts, window card and load report.
- Audit rows kept when Test now, console sends and Check token raise unexpectedly.
- Working bases per membership; one listing per court item in listed-for-tomorrow.
- No-local-model guards (tests, preflight); `migrate` refuses an image built from other code.
- uicheck and DataTable fixes; console full-answer handling; token card test pinned to a fixed clock and a no-Redis requests-today fix (Deviation 20).
- 82 files, 3243 insertions, 280 deletions in the squash.

## Gates
- ruff check: all checks passed.
- pytest: 2255 passed, 3 skipped (28 min 29 s).
- docker compose build and `docker compose --profile ops build migrate`: succeeded.
- Portal smoke (web rebuilt and healthy): passed.
- git status clean; design note `approved`; decisions-log entry and backlog row present.
- CI on main before merge: success, run 40114362851.

## Review
One blocking finding (renewals counted as failures in napix_window), fixed in cc9f091. Advisories 2 and 5 fixed. Re-check: may merge. Earlier attempt stopped on `test_token_card_states` (IST midnight dependence), fixed in d765535.

## Follow-up rows
143 to 148 (recorded in the backlog).

## Deviations
In `docs/design/followups-oct.md`.

## Load status
`aslms queue-status` printed no output within 60 s; not recorded.
