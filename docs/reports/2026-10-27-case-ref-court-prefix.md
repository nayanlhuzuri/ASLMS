# Report: case-ref-court-prefix (row 157)

Merged to main as 2a896d4; tag `feature/case-ref-court-prefix-done`.

## What changed
- DB_STANDARD v1.3 and `docs/schema/schema.md`: system case numbers are `ASLMS/<court code>/CASE/<year>/<number>`.
- Migration 0028: `courts.ref_code` (GHC on the four Gauhati High Court establishments, format CHECK, btree_gist exclusion, no office takes a court code), `ck_cases_ref_no_court`, counters moved, search vectors recomputed, one summary audit row, reversible downgrade.
- Every creation path numbers on the court; old `GOA` numbers resolve by rule; the portal replaces an old address with the new one; fixtures on GHC.
- Design note: `docs/design/case-ref-court-prefix.md`.

## Gates
- CI on main: success (run 40315786236, head b481490).
- ruff: All checks passed.
- pytest: 2460 passed, 3 skipped (39m16s), every run green.
- docker compose build: succeeded.
- Portal smoke (frontend changed): passed.
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings
1. Advisory: queue masters sync drops `MasterReport.errors`. Open, row 182.
2. Advisory: downgrade drops `btree_gist` unconditionally. Open, row 182 (0028 is not edited).
3. Advisory: Verification step 2 rehearsal has no recorded result. Open, row 182; run before the `migrate` step on dev.

## Deviations
None. `aslms queue-status` did not return within the time limit, so no load status is recorded.

## Follow-ups
Row 182. Owner step: apply 0028 with the `migrate` step (design Verification step 3).

## Push
See the integrator's return value.
