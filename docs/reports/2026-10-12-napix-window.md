# napix-window (backlog row 47) - 2026-10-12

Merged to main as ee4b9e2, tag `feature/napix-window-done`.

## What changed
- `backend/aslms/services/napix_window.py`: reset detection from `napix_call_log` readings, expected next reset, resume time, probe rule.
- `backend/aslms/cli/pipeline.py` worker waits for the detected reset plus 60 s margin; one probe call per 3 minutes at most when unsure.
- Budget bands, retry-after, health and console use the detected window; console shows current window start, next reset, recent resets.
- `napix_call_log.user_id`, `fetch_queue.requested_by` (migration 0015, two nullable columns); calls-by-user on the health screen (names only for re-fetch / master-sync holders); lane and user columns in the call log.
- `docs/napix_integration_notes.md` and design corrected; schema.md updated.
- Tests: `tests/unit/test_napix_window.py` and DB/API tests; fixture of readings 2026-10-11.

## Gates
- ruff: All checks passed
- pytest: 865 passed (643 s)
- docker compose build: succeeded
- portal smoke: passed
- git status clean; design status approved; decisions log entry and backlog row present

## Review findings and closure
1. Advisory, napix_window.py:213: with an imprecise anchor seen over 30 min after the real reset, the expected reset can land one window late. Not fixed in this cycle; follow-up row 49.
2. Advisory, cli/pipeline.py:30: on probe failure the log line shows the pre-probe window time, not the probe interval. Not fixed; follow-up row 49.
3. Advisory, tests/db/test_data_load.py:500: audit rows ordered by created_at only, flaky. Not fixed; follow-up row 49 (use created_at, id). It passed in the final full run.

## Deviations
None beyond the open advisories.

## Follow-up rows
- 48 napix-window-tail (already proposed, needs owner decision).
- 49 napix-window-fixes: the three advisories above.

## Load status (queue-status)
causelist_day skipped 44; dossier done 22481, failed 294, pending 3014, skipped 22; masters done 1; order_pdf done 9041, pending 173503; status_batch done 145, failed 1, skipped 3.
