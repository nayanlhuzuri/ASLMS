# details-first (backlog row 142)

Date: 2026-10-25. Branch `feature/details-first`, squash-merged to `main` as 5a8056d, tag `feature/details-first-done`.

## What changed
19 files, no migration (dev database stays at 0024). Order PDFs from the daily, load and discovery paths queue at priority 60 for a pending case and 80 for any non-pending case, after daily dossiers (40), the load (41-46), the weekly sweep (50) and the disposed refresh (55). Request-lane order PDFs stay at 40. Load presets rank only cause-list days and dossiers. New one-off audited command `aslms data-load pdfs-after-details [--apply]` re-ranks rows already queued (every status but running). Portal preset relabelled. Files: `services/load_policy.py`, `services/orders.py`, `services/data_load.py`, `cli/data_load.py`, `cli/main.py`, `frontend/src/lib/messages.ts`, `backend/tests/db/test_pdfs_after_details.py` and others.

## Gates
- ruff: All checks passed.
- pytest: 2264 passed, 3 skipped (28:47).
- docker compose build: succeeded.
- portal smoke: passed.
- git status clean; CI on main: success at b75ba66, run 40152203335.
- No design note file exists; the change was owner-requested and recorded in the decisions log (24 Oct 2026). Log entry and backlog row exist.

## Review
One blocking finding fixed (13a20ad); the re-check said may merge. Three advisories are row 149.

## Deviations
None.

## Load status
`aslms queue-status` (tail): order_pdf done 137653, pending 165440, skipped 8; status_batch done 1081, skipped 6.
