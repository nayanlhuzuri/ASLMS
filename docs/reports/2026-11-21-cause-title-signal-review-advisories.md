# Report: cause-title-signal-review-advisories (row 273)

Merged 21 Nov 2026 as one squash commit on `main` (tag `feature/cause-title-signal-review-advisories-done`), from
`feature/cause-title-signal-review-advisories`. Design: `docs/design/cause-title-signal-review-advisories.md` (status approved).
Row 260 is still not deployed; rows 260 and 273 deploy together (runbook section 27).

## What changed

- Engine (`services/matching.py`): the cause-title signal no longer counts a respondent party row that a keyword or name pattern of the same
  department already scored; the engine reads only `insight_case_facts` (no maps loaded, so a full rescore cannot use stale maps).
- `services/insights_facts.py`: a durable rescore marker on `insight_case_facts` committed with the fact row, replacing the in-memory list;
  each phrase stored with the department it names, so a change of the shown phrase marks the row; re-derivation in case-id order
  (commit 54e5701, no lock-order inversion with the engine's mark clear).
- Migration 0041 `cause_title_signal_marker` (`docs/schema/schema.md` extended first). `named_rescore_waiting` added to the Insights status
  (`frontend/openapi.json`, `schema.d.ts`; no screen change).
- Docs: runbook sections 26 and 27 (`docker compose build` first, new steps), workflows, Software Documentation 1.14, decisions log.
- Tests: `tests/unit/test_cause_title_signal.py` extended, `tests/db/test_migration_0041.py`, `test_migration_0033.py` adjusted.

## Gates

- `ruff check .`: All checks passed.
- `pytest -q` (test database tmpos-273, `ASLMS_TEST_REQUIRE_DB=1`): 3865 passed, 3 skipped (1:37:25), no failure. The 3 skips are the
  non-database ones (no POSIX sh, and similar), none a database test.
- `docker compose build`: succeeded (every image built).
- Screen check on a private network (temporary `web` and `uicheck` images from the branch, removed afterwards): 195 routes and states,
  638 screenshots, 0 findings; 910 passed, 14 skipped; 432 s.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: success (44870857578). No `docker compose up` was run; the shared stack was not touched.

## Review findings and how each was closed

One advisory (lock-order inversion: `rederive_departments` updated fact rows in heap order while the engine's mark clear writes in case-id
order, a possible deadlock between a drain and a refresh): closed by the owner session's commit 54e5701, which orders the re-derivation select by
`case_id`. Included in this merge.

## Deviations

None recorded beyond the design note.

## Follow-up rows

None added.

## Load status

`aslms queue-status` did not answer within 120 s from the host (the dev database is not reachable on the host port while WinNAT reserves it),
so no load status is recorded.
