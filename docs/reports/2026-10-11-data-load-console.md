# Report: data-load-console (backlog row 45), 2026-10-11

Merged to `main` as a squash commit, tag `feature/data-load-console-done`.

## What changed
- Migration 0014 (`backend/migrations/versions/0014_data_load.py`): `data_load_settings` (versioned), fetch lanes on `fetch_queue`, court-duplicate links and merge notes. `docs/schema/schema.md` extended first.
- Services: `data_load.py` (progress, estimate, start, pause, resume, order, single-case fetch, already-held checks), `load_policy.py` (lanes and allowance bands), `queue.py` (lanes), `case_dedupe.py` (one row per case, provisional merge, court-duplicate links, sweep), `cases.py`, `court_search.py`.
- API: `/admin/data-load` and related endpoints behind the new grantable function `admin.data_load`; CLI `aslms data-load`; 03:00 `dedupe-sweep` job; compose note.
- Portal: `/data`, `/data/load`, `/data/queue`, `/data/health`, `/data/duplicates`; `frontend/openapi.json` and generated types refreshed.
- Tests: `test_queue_lanes.py`, `test_case_dedupe_unit.py`, `test_data_load_unit.py`, endpoint auth tests, portal `data.test.tsx`, pipeline test adjustments.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 839 passed, 69 warnings (624 s).
- `docker compose build`: succeeded (api, worker, init, scheduler, web).
- Portal smoke (`web` service): passed, including /data, /data/duplicates, /data/health, /data/load, /data/queue.
- `git status` clean on the branch; design note status `approved`; decisions-log entry and backlog rows 45 and 46 exist.

## Review findings and how they were closed
Closed in the branch (commits 7ad2b56 and f647c39):
- Blocking: zero case or filing number or year collapsed into one key (`WA/0/0`), linking unrelated cases. A number or year of zero or less now makes the key unusable; unit tests added.
- Blocking: `merge_provisional` checked portal records without locking P. It now locks P `FOR UPDATE`, re-reads it and re-checks before `portal_records`.

Open advisories, not blocking, accepted for follow-up (row 46 and below):
- Concurrent setting changes (pause/resume/order) can both pass the unlocked no-change check and race on the version insert (500 instead of 409). Reported three times.
- Migration 0014 dossier classification is a correlated subquery (measured about 19 ms per row, roughly 7 minutes on about 22,100 rows) with the worker stopped.
- Migration moves all pending daily-lane order PDFs from 75 to 40, ahead of the load rows; on dev about 17.7k calls (about a day of allowance) before the backdated load resumes. Owner should expect this on applying 0014.
- Cause-list entries without a CNR are matched only to provisional rows, not to an unmerged CNR row with the same number; unusable-key (zero) listings fall back to no match and create new provisional rows each time.
- Advisory number lock lasts the whole day transaction and can block an API court search past its timeout.
- The dedupe sweep runs in one transaction; one failing pair or a race with inline checks rolls back the run.
- Inline duplicate checks lack supporting indexes on `(court_id, filing_no, filing_year)` and `(court_id, case_type_id, reg_no, reg_year)`.
- `GET /admin/data-load` does not map a statement timeout to 503 `search_timeout`.
- Reviving a finished queue row keeps the old lane (`LEAST`) and priority.
- "This hour" figures use the UTC hour; the NAPIX counter appears to reset on the IST hour.
- LoadConsole "Fetch details" always sends `force: false`; no "fetch anyway" for already-held party-search hits.

## Deviations
None beyond those written back into the design note (deviations section). Compose verification (migration 0014 applied to the dev database, worker moved to the `load` lane) was not run in this merge; it is in row 46.

## Follow-up rows
Row 46 `data-load-console-followups` (todo). The advisories above are not yet separate rows and should be triaged into row 46.

## Load status (`aslms queue-status`, database at migration 0013)
- causelist_day: done 63, pending 540, skipped 43
- dossier: done 22443, failed 294, pending 3051, running 1, skipped 22
- masters: done 1
- order_pdf: pending 182544
- status_batch: done 100, skipped 3
