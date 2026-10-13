# Report: department-discovery (backlog row 19)

Merged to `main` as commit 49fe356, tag `feature/department-discovery-done`.

## What changed
- 61 files. Department party names and keywords run through NAPIX Search by Party Name as a new `fetch_queue` kind within a quota share (`NAPIX_DISCOVERY_SHARE`).
- Migration 0017 (tests in `test_migration_0017.py`).
- Discovery service, runner share handling, `hc.py` party search, discovery API (`/inbox/pool?found_for=`, court search endpoints), CLI.
- Portal: Search the court, Court search tab, Discovery data tab (`frontend/src/lib/discovery.ts`, `CourtSearch.tsx`).
- Owner decisions: automatic discovery covers 2025 onwards; older years only when a user enters them; no call counts shown to users; plain-words warning for a repeated search; live check limited to 10 calls, blank `reg_year` first (row 67).

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1060 passed, 89 warnings (14m12s).
- `docker compose build`: succeeded.
- `portal_smoke.py`: portal smoke: passed.
- `git status` clean; design note status `approved`; decisions-log entry (14 Oct 2026) and backlog row present.

## Review findings (all advisory) and closure
All seven were accepted as advisories and moved to follow-up row 68, not fixed in this cycle:
1. Design Verification section not updated (27 rows vs 2025/2026; no blank-year path).
2. Per-runner discovery share count; two runners can exceed the cap.
3. `searches_done` read-then-write can lose an increment.
4. `found_for_condition` ignores the active Department ancestor rule.
5. Already-searched warning has no age limit (deviation 2, owner to confirm).
6. Court search tab fetches at most 200 terms.
7. `parseYears` rejects "2010 - 2014".

## Deviations
- Warning on any earlier done or waiting search, with no age limit (design deviation 2, awaiting owner confirmation).

## Follow-up rows
- Row 67 discovery-live-verification (existing, todo); row 68 discovery-followups (added).

## Load status
`aslms queue-status` (database up): dossier done 32943 / failed 490 / pending 107; order_pdf done 24473 / pending 194284; causelist_day done 89 / pending 491; status_batch done 253; masters done 1. No discovery rows yet (live check pending, row 67).
