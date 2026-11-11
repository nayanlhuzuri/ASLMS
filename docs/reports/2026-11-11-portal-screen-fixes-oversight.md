# Portal screen fixes, oversight and administration (row 234 `portal-screen-fixes-oversight`)

Merged 2026-11-11 as squash commit 06f9367 on `main`, tag `feature/portal-screen-fixes-oversight-done`. Design:
`docs/design/portal-screen-fixes-oversight.md` (approved).

## What changed
47 files, 958 insertions, 153 deletions. Frontend components, kit controls and vitest suites for Search (S1, S2),
Cause List (L3, verified only), Reports (R3), Audit Log (U2: entry page and Before/After), Data Collection (DC2),
System Health (Y2) and Administration (AD1 to AD4: Users, Tickets, Department Mapping lists, Office Picker), with new
uicheck fixtures. One read-only additive API field: `example_case_no` on each unmapped counsel code item
(`UnmappedCodeOut`), read in the same query as the example reference. No table, column, reference code or index; no
migration; `docs/schema/schema.md` unchanged.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q` (backend, whole suite): 3245 passed, 3 skipped, 255 warnings in 52:29.
- `docker compose build`: succeeded (no service recreated).
- Screen check (runbook section 16: private network, temporary `web` and `uicheck` images built from the branch, all
  removed afterwards): 174 routes and states, 419 screenshots, 0 findings; 575 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (run 42983440422).

## Review findings
- Advisory, `recordRef` in `AuditEntry.tsx` can name another record's `ref_no` (a `case.merged` entry; a
  `ticket.document_archived` entry). The code follows decision 9 as written; closed as follow-up row 242
  `audit-record-ref-owner`.
- Advisory, the reviewer's full backend run did not finish in its window. Closed: the integrator's full run above is
  green.

## Deviations
None beyond the design note.

## Follow-up rows
242 `audit-record-ref-owner`.

## Push and CI
See the integrator's return values; the push of `main` and the tag follows this commit.

## Load status
`aslms queue-status` printed nothing within its timeout from the host in this run; load status not recorded.

## Deployed
11 Nov 2026 at 19:04 IST, images built from clean `main` (48e8137) after CI run 43025104992 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`oVaAuZHCioEuqKiDKnSx1`), and `portal_smoke.py` passed.
