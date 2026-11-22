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

## Deploy
Rows 260 and 273 deployed together on the night of 21 to 22 Nov 2026 from `main` at 8b6910d (the row 273 merge plus a
test-only fix: `test_data_health_insights_block_has_named_rescore_waiting` read `/openapi.json`, which is 404 outside dev,
and failed CI run 44898459019; it now reads `app.openapi()`, CI run 44928741805 green). Runbook section 27:
- 0: images built from the clean checkout of `main` before the stop.
- 23:14 IST: `napix_call_log` 638,434 rows, revision 0039; `api`, `worker`, `worker2`, `scheduler`, `web` and `pgbouncer`
  stopped.
- 1: `docker compose --profile ops run --rm migrate`: preflight passed (dev, 7 warnings), "the image matches ./backend
  (migrations up to 0041)", backup `20261121-2315-pre-migrate` written and listed by `pg_restore`, 0039 -> 0040 -> 0041,
  seed nothing to insert, audit row `system.migrated`. Done at 23:57.
- 2: `pgbouncer` up alone, then `aslms insights refresh --no-rescore` in a one-off container: `rederived` 22,217,
  `named_changed` 1,282, 21.2 s, 4,576 unmapped phrases. Checks: rows with phrases but no positions 0; engine-3 score
  rows 0; latest settings weight `weight_named_in_title` 0.600.
- 3: `aslms rescore --all --dry-run` (5 min 58 s, nothing written): cases 84,898, claimed 5, `new.medium` 826,
  `new_by_kind.medium.named_in_title` 826, `new_only_with_named.medium` 826, `band_changed` none,
  `band_changed_by_named` 0, `named_withheld` 0, expired 0, failed 0, settings version 3, engine 3.3. Shown to the owner.
- 4: the owner said go on 22 Nov 2026 at 13:42 with the default weight 0.600; services up with the court-data switch and
  `--no-deps --force-recreate api worker worker2 scheduler web`: each container on its new image, running `BUILD_ID`
  `n3V3mjCFopAKezD-SSZAJ` equals the image's, `/api/health` 200, `/signin` 307, the switch on in `api`, `worker` and
  `worker2`, both workers "NAPIX on". The portal was down 23:14 to 13:43 (14.5 h), waiting for the owner's go-ahead.
- `aslms rescore --all` 13:44 to 13:53: 84,898 cases, 2,968 score rows, 40 new by the CLI itself (the scheduler's
  `rescore-dirty` and the refresh drain, running alongside, opened the rest), band changed 0, expired 0, failed 0; one
  `matching.case_deadlock_retried` warning (case ASLMS/GHC/CASE/2026/074110), retried and scored.
- 5: checks: `case_ownership` rows by `matching` 0; score rows not on engine 3 0 (2,968 on 3); score rows carrying
  `named_in_title` 1,282; recommendations created since the deploy 826, all `medium`, status `recommended`, equal to
  the dry run; `named_rescore_waiting` 0, marked rows 0.
