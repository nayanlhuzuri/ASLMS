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

## Deploy (14 Nov 2026, 22:10 to 23:06 IST)
- Deployed together with row 189 `assistant-ollama-work` (migration 0037). CI green on `a503b92` and `cb54036`. Images built from a clean `main` (`cb54036`), `migrate` included.
- After the first 22:00 nightly refresh had queued (22:00:05, 8,030 dossier rows), `docker compose stop api worker worker2 scheduler web pgbouncer`, then `docker compose --profile ops run --rm migrate`: preflight passed (dev warnings only), the image matched `./backend`, backup `20261114-2210-pre-migrate` written and listed by `pg_restore`, upgrade 0035 → 0036 → 0037, seed nothing to insert, audit row `system.migrated`. Then `docker compose up -d` and the app services recreated with `--no-deps --force-recreate api worker worker2 scheduler web`, the court-data switch on. Portal down 22:10 to 23:06.
- Checked: `init` exited 0; the switch on in `api`, `worker` and `worker2`; both slots started ("slot main" and "slot second", NAPIX on, one interrupted run each repaired); web build ID `si0gDyIOe_PhmNS_KFM8b`; portal 307 to sign-in, API health 200; `alembic_version` 0037; `ref_office_kind` holds the six new kinds and "Directorate / Commissionerate"; `assistant_scope` includes `my_work`; `aslms assistant check` six zero counts including `work_rows_out_of_rule`; `aslms offices import --help` answers.
- The SEC-EDU rename to School Education happens through the import (the owner's workbook), not by the migration: the office still reads "Department of School Education". The real import waits for row 261.
