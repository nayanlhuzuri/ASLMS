# Report: cause-title-signal (row 260)

Merged 21 Nov 2026 as one squash commit on `main` (tag `feature/cause-title-signal-done`), from `feature/cause-title-signal`.
Design: `docs/design/state-insights.md` (status approved), decisions 36 to 40 and deviations 34 to 43.

## What changed

- Recommend-and-claim: new signal `named_in_title` (a department named among the respondents, read from the Insights facts and the
  mapped cause-title names); default weight 0.600, inside the possible band; never assigns a case. Engine version 3.
  Files: `services/matching.py`, `services/scoring_settings.py`, `services/insights_facts.py`, `domain/ownership.py`,
  `jobs/celery_app.py`, `cli/matching.py` (rescore dry run counts), `cli/insights.py`, `api/schemas.py`.
- Migration 0040 `cause_title_signal` (new scoring_settings column and rescore marker); `docs/schema/schema.md` extended first.
- Portal: the Named in Cause Title weight on Department Mapping, Scoring; the reason in Case Claim; `lib/signals.ts`, `lib/mapping.ts`,
  `lib/messages.ts`, regenerated `openapi.json` and `schema.d.ts`.
- Docs: runbook section 27 (deploy and dry run), workflows, software documentation, decisions log, design note, CLAUDE.md.
- Tests added: `tests/unit/test_cause_title_signal.py`, `tests/db/test_migration_0040.py`, portal tests for signals, mapping and claim.

## Gates

- `ruff check .`: All checks passed.
- `pytest -q`: 3829 passed, 3 skipped (1:10:19); no failure in the run.
- `docker compose build`: succeeded (every image built).
- Screen check on a private network (temporary `web` and `uicheck` images from the branch, removed afterwards): 195 routes and states,
  638 screenshots, 0 findings; 910 passed, 14 skipped; 447 s.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (44716492809). No `docker compose up` was run.

## Review findings and how each was closed

Five advisories, none blocking, all recorded as follow-up row 273 (none fixed in this cycle):
1. `_named_hits` counts a respondent party name that keyword and pattern rules already score (a possible match can become strong with no new
   evidence); the owner rules on it before runbook section 27 step 3.
2. `rescore_all` loads the cause-title maps once, so a name save during a full rescore can be overwritten.
3. The rescore list of the rebuild and refresh is in memory only, so a failed or interrupted run can leave fact rows never rescored.
4. `rederive_departments` rescored only on department-id change, not on a change of the shown phrase.
5. Runbook section 27 step 3 puts `docker compose build` after steps that already need the new image.

## Deviations

None beyond deviations 34 to 43 in the design note.

## Follow-up rows

273 (the advisories above). Row 272 (deploy dry run, owner's weight decision, browser check, post-rescore checks) stays todo.

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

## Load status (`aslms queue-status`, 21 Nov 2026)

dossier skipped 70; masters done 1; order_pdf done 296,842, pending 102,131, skipped 227; status_batch done 4,112, skipped 9 (other kinds as printed
by the command, head of the table not captured).
