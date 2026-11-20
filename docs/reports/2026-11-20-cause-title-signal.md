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

Not deployed. Migration 0040 is not applied to the dev database; it is applied at a late-night deploy with the `migrate` step after a
`pre-migrate` backup, followed by the runbook section 27 dry run shown to the owner before services return.

## Load status (`aslms queue-status`, 21 Nov 2026)

dossier skipped 70; masters done 1; order_pdf done 296,842, pending 102,131, skipped 227; status_batch done 4,112, skipped 9 (other kinds as printed
by the command, head of the table not captured).
