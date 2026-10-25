# case-workspace-admin (backlog row 135)

Date: 2026-10-25. Branch `feature/case-workspace-admin`, squash-merged to `main` as c72009b, tag `feature/case-workspace-admin-done`. Design `docs/design/case-workspace-admin.md` (approved 23 Oct 2026).

## What changed
105 files, migration 0025 (reference-data relabelling of `file_noting` and `custody_moved`; head is 0025). Case page as template A with a sticky action rail and the full remarks history; the Cases list (Cases with me / Sent by me / Pending action); plain-language vocabulary with wording guard tests in both suites and `/files/*` redirects; Administration hub with the Users side panel and user-type cards with grouped switches and one batch `PUT /admin/access/types/{role}`; read-only API additions (`order`, `remarks_shown`, `due_soon`, `current`, permission groups, `/admin/access/defaults`, `/overview`, users `status`); uicheck fixtures, routes and states.

## Gates
- ruff: All checks passed.
- pytest: 2311 passed, 3 skipped (38:47).
- docker compose build: succeeded.
- portal smoke: passed.
- git status clean; design status approved; decisions-log entry and backlog row present.
- CI on main before the merge: success (run 40156308064).

## Push
See the integrator's return value; the push is attempted after this commit (fast-forward only).

## Review findings (all advisory) and how they were closed
1. Batch PUT 400 codes `reserved_function` / `retired_function` differ from the design's `reserved` / `retired`; the page falls back to the generic message and the vitest fakes a code the server never sends. Not closed; follow-up row 150.
2. The Users side panel refreshes only the single-user query, not the list behind it. Follow-up row 150.
3. Two strings still say "Custody" (Audit log action group, Offices in-use line) where the wording is "Journey". Follow-up row 150.
4. "Corrected by NOTE/..." anchor fails when the correcting note is on an unloaded page. Follow-up row 150.

## Deviations
Those recorded in the design note's Deviations section; finding 1 is not yet written there.

## Follow-up rows
Row 150 `case-workspace-admin-advisories`.

## Load status (`aslms queue-status`)
order_pdf done 137653, pending 165796, skipped 8; status_batch done 1081, skipped 6 (other kinds as printed by the command).
