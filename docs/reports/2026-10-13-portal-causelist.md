# Report: portal-causelist (backlog row 60), 13 Oct 2026

Merge commit on `main`: 64d46d9 (squash of `feature/portal-causelist`), tag `feature/portal-causelist-done`.
Design: [docs/design/portal-causelist.md](../design/portal-causelist.md), approved by the owner 13 Oct 2026.

## What changed
- Backend: `services/causelist_view.py` (dates, a day with benches and lists, entries in court order with recommendation, owner and `claimable`, list PDF), `api/routers/causelists.py`, schemas in `api/schemas.py`, small additions to `services/documents.py` and `services/ownership.py`, router registered in `api/main.py`.
- Endpoints: `GET /causelists/dates`, `GET /causelists/{list_date}`, `GET /causelists/{list_date}/entries`, and the list PDF.
- Tables: none added or changed. No migration. `docs/schema/schema.md` unchanged.
- Portal: `/causelist` screen (day bar, bench select, list strip, entry table, ownership cell, Claim with department choice, toggles with counts), Hearings tab links from the case page, menu item, `lib/causelist.ts`, messages, hooks, regenerated `openapi.json` and `schema.d.ts`.
- Tests: backend `test_api_causelists.py`, `test_causelist_view.py`, `causelist_support.py`, unit `test_causelist_view.py`; frontend `causelist.test.tsx`, `causelist.test.ts`, additions to case, shell and routes tests.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1004 passed, 71 warnings (1117 s).
- `docker compose build`: succeeded (api, worker, scheduler, init, web).
- Portal smoke (`docker compose up -d --wait --no-deps web`, `portal_smoke.py`): portal smoke: passed.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.

## Review findings (all advisory) and how each was closed
1. Entries sort by each row's own `court_no` first, so rows with NULL `court_no` (read before the first court heading) move to the end, away from their bench and list. Not fixed in this cycle; recorded as follow-up row 65.
2. A non-State user sees their department's recommendation band and score on rows for cases they cannot open (visible=false), which is wider than `case_ownership_view`. This is disclosed as deviation 7 and fits the approved wording. Left as approved; follow-up row 65 asks the owner whether parity with the case page is wanted.
3. The day state looks only at `causelists`, so a date with `causelist_bench_days` rows but no list reports `not_loaded` or `loading` while benches show as sitting. Cosmetic, no data leak. Recorded as follow-up row 65.

## Deviations
As listed in the design note's Deviations section and the decisions log entry (serve_stored signature, `done` day row with no list counts as `no_list`, lone `from` or `to`, numeric court sort, case-number words also match the printed number, and others).

## Follow-up rows
- Row 64 (already present): Compose browser check of the screen with row 56; index only if day-entries timing exceeds one second.
- Row 65 (added): the three advisory findings above.

## Load status (`aslms queue-status`, tail)
dossier skipped 30; masters done 1; order_pdf done 22510, failed 5, pending 192295, skipped 47; status_batch done 194, failed 1, skipped 3.
