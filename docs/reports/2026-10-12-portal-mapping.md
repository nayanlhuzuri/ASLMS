# Report: portal-mapping (backlog row 50), 2026-10-12

## What changed
Frontend only, 26 files, no migration, no new tables or endpoints. Department mapping tab with counsel codes
and the unmapped-codes panel, keywords and name patterns, watchlist, and scoring settings (weights and bands,
history, expected_version; weight fields only with `admin.scoring`). Routes `/admin/mapping/{codes,keywords,watchlist,scoring}`,
components in `frontend/src/components/admin/mapping/`, `frontend/src/lib/mapping.ts`, `routes.ts`.
Design: docs/design/portal-mapping.md.

## Gates
- ruff check: All checks passed
- pytest -q: 888 passed (an earlier full run showed test_cli_data_load_is_audited failing once; it passed this run)
- docker compose build: succeeded
- portal smoke: passed
- git status clean; design status approved; decisions-log entry and backlog row present

## Review findings (all advisory)
1. OfficePicker typed-code branch lacks `id`, so Map does not move focus there: open, follow-up.
2. Scoring history "changed" mark misses the last row of each 50-row page: open, follow-up.
3. Office picker indentation collapses in option text (use non-breaking spaces): open, follow-up.
4. RuleStatusActions re-reads only on 409, not on the stale 400: open, follow-up.
5. `given()` shows raw 500/503/504 bodies (HTML): open, follow-up.
6. Signed-in verification steps 4, 5, 7 of the design were not run by the integrator (needs a signed-in session): outstanding, to be run by the owner.
7. Flaky test_cli_data_load_is_audited in the full suite (shared state), pre-existing: tracked separately.

## Deviations
None by the integrator. Findings 1-5 and 7 are not fixed in this merge.

## Follow-ups
Row 52 added for findings 1-5, 7 and the signed-in verification.

## Load status
order_pdf: done 17715, failed 3, pending 165434; status_batch: done 145, failed 1, pending 49, skipped 3.
