# offices-import (row 257), 14 Nov 2026

## What changed
- Migration 0036 `office_kinds`: six new office kinds in `ref_office_kind` with placement rules and labels; Directorate widened to Directorate / Commissionerate; `OfficeKind` enum, seed and `schema.md` updated.
- `aslms offices import <file.xlsx>` (`backend/aslms/services/offices_import.py`): dry run by default, `--apply` creates offices, department heads and first admins in one audited run; idempotent; no password read from the workbook; runbook section 24.
- Office codes up to 17 characters; a department may have no head yet; `passwords.py`, `users.py`, `refno.py`, `reference.py` adjusted.
- Portal: Offices screen kinds by parent and No Head Yet badge, Watchlist kinds from labels; `openapi.json` and `schema.d.ts` regenerated.
- Tests: unit (read, rules, users, refno, repo policy), database (migration 0036, office kinds, import, offices API), portal (`officeKinds.test.tsx`).

## Gates
- Remote CI on main (head c853231): success. Branch had only offices-import commits.
- `ruff check .`: All checks passed.
- `pytest -q`: 3457 passed, 3 skipped (50:44).
- `docker compose build`: succeeded.
- Screen check (private network, temporary images, no Compose up): 179 routes and states, 574 screenshots, 0 findings.
- Design status approved; decisions-log entry and backlog row present; branch clean.

## Review findings (4 advisories, none blocking, none fixed in the branch)
All four are recorded as follow-up row 261: stale workbook dimension (rows silently skipped), duplicate code across an included and a waiting row, inactive designation reuse without notice, rename test against truncated 200-character names.

## Deviations
None. Note: design rows 209/210 plan migration 0036 for TOTP; 0036 is now taken, so that migration takes the next number.

## Push
See the final handoff: main and the tag pushed when the remote accepts them.

## Load status (`aslms queue-status`)
order_pdf pending 147,210 (done 247,508); status_batch done 3,364; dossier skipped 69; masters done 1.
Migration 0036 is not yet applied to the dev database: apply with the `migrate` step.
