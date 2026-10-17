# Report: search-court-advocate-filing (backlog row 21), 2026-10-18

Merged to `main` as c8b03bb (squash), tag `feature/search-court-advocate-filing-done`. No migration.

## What changed
- Live probe: 5 of the 10 allowed NAPIX calls, samples `docs/specs/samples/advocate_name_2026-10-18-p1/p3/p4.json` and `filing_2026-10-18-p5.json`; `docs/napix_integration_notes.md` section 7, `docs/schema/napix_coverage.md` section D and `docs/specs/napix_field_inventory.md` updated.
- `backend/aslms/cli/napix_check.py`: `advocate_name` and `filing` steps, `--max-calls`, every attempt recorded in `napix_call_log`.
- `POST /cases/search-court` gains kinds `advocate` and `filing` (`services/court_search.py`, `api/schemas.py`, `case_search.items_for`; `NapixHighCourt.search_advocate`).
- Portal Search page: Advocate name and Filing number; court-call counts removed for every kind.
- Tables: none added or changed. Endpoint: the two new kinds on the existing POST.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1318 passed (947 s). Two earlier attempts showed many errors because two pytest runs overlapped on the shared `aslms_test` database; the test schema was reset and the suite rerun alone, green.
- `docker compose build`: succeeded. Web service rebuilt and healthy; `portal_smoke.py`: passed.
- `git status` clean; design note status approved; decisions-log entry and backlog row present.

## Review findings and closure
1. Advocate search can store very many rows (court matches part of a name, minimum 3 characters, no row cap, synchronous storing). Advisory, accepted for this merge; not fixed. Follow-up row added.
2. napix_check recorder flushed inside `finally`; a failing flush hides the run's error and loses the attempts. Advisory, accepted; follow-up row added.
3. Decisions log: the entry for this row (probe outcomes, no call counts on Search, filing and advocate behaviour) is present in the log; the decisions-log entry still says "in review", which this merge supersedes.
4. `tests/db/test_discovery_rules.py::test_save_queues_the_first_sweep` failed once in an earlier full run; it passed in the final full run. Not related to this diff. Follow-up row added to watch it.

## Deviations
Listed in the design note's Deviations section: build split at the probe gate; filing rows carry no registration number; `type_name` of a filing row fills only `case_type_text`.

## Load status
`aslms queue-status`: dossier done 30156, pending 23750, failed 736; order_pdf done 33162, pending 268505; causelist_day done 203, pending 322, skipped 127; status_batch done 498. Historical load still running.
