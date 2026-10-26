# partial-code-match (row 154), report of 26 Oct 2026

## What changed
- Counsel codes compared as sets of comma-separated parts; new signal kind `counsel_code_partial` (default weight 0.600, inside the possible band, below the counsel code weight). Exact match wins, counts once per department. Engine version 2. Never assigns a case.
- Migration 0027: column `weight_counsel_code_partial` on scoring settings and a new settings version.
- Backend: `aslms/services/matching.py`, scoring settings service and API, unmapped-codes panel marks partly matching codes.
- Portal: Partial Counsel Code weight on the Scoring tab, the partial reason in "Why this is suggested", the "Partly matches" mark (30 files in all, tests in `tests/unit/test_partial_code_match.py` and `tests/db/test_migration_0027.py`).
- Design note: `docs/design/partial-code-match.md`; decisions log and `docs/schema/schema.md` updated.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2424 passed, 3 skipped (40 min), on the branch before the merge.
- `docker compose build`: succeeded.
- Portal smoke (frontend changed): passed. `tsc --noEmit` on the merged tree: clean.
- Design status approved; decisions-log entry and backlog row present.
- CI on main before the merge: last run success (https://github.com/nayanlhuzuri/ASLMS, run 40283441256).
- The branch was behind main (Department Mapping edits, session-timeout design); the squash merged cleanly, including `CounselCodes.tsx`. The tests ran on the branch, not on the merged tree.

## Review findings
1. Advisory, migration 0027 `partial_weight` not bounded by the possible threshold or 0: left open, backlog row 170.
2. Advisory, exact-wins check ignores mappings on inactive offices while the unmapped panel counts them: left open, backlog row 171.
3. Advisory, decisions log and Current focus not updated: closed; the log, schema.md and CLAUDE.md focus were updated on the branch (commit b991f1b).

## Deviations
Recorded in the design note. Load status (`aslms queue-status`) not taken: the command did not answer within 120 s.

## Follow-ups
Rows 170 and 171. Owner step: apply 0027 with the `migrate` step, then `aslms rescore --all`.
