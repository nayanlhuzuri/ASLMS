# portal-ui-polish-2 (row 153, round 1) - integration report

Merged 26 Oct 2026 as a squash of `feature/portal-ui-polish-2` into `main`; tag `feature/portal-ui-polish-2-done`.
Design: `docs/design/portal-ui-polish-2.md` (approved 25 Oct 2026).

## What changed
- 114 files (frontend 82). Title Case labels with a shared helper `frontend/src/lib/titleCase.ts`, a vitest over `messages.ts`, a pytest over function labels.
- Migration 0026 (`backend/migrations/versions/0026_portal_ui_polish_2.py`): full user-type names and Table 1 descriptions, unique name index.
- Endpoint: `PATCH /admin/access/types/{role}/name` (`access.manage_types`, audit `access.type_edited`); full type names in API messages.
- Side menu `NavTree` expanding one level, treeview keys, phone drawer, reduced motion; checkbox alignment rule with a uicheck step; dashboard greeting and view switch.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2356 passed, 3 skipped (30 min 06 s).
- `docker compose build`: succeeded.
- Portal smoke (`web` rebuilt and running): passed.
- Branch clean; design status approved; decisions-log entry and backlog row present.
- CI on main before merge: success (run 40215404961, head b6ec49e, equal to origin/main).
- The Compose uicheck run was not part of the gates.

## Review findings (three advisories, none blocking)
All three are open and tracked in backlog row 164 (`nav-tree-advisories`): NavTree `useHash` stale after client navigation; no `aria-current` on an expanding entry at its landing page; `UserTypes` shows every 422 under Display Name and gives no message for a name over 80 characters.

## Deviations
None beyond those recorded in the design note.

## Follow-ups
Row 164 added. Rounds 2 and 3 are rows 162 and 163. Apply migration 0026 with the `migrate` step after the merge.

## Load status
`aslms queue-status` ran after the merge (slow to return). Notable: order_pdf done 137653, pending 167184; status_batch done 1178; masters done 1; dossier skipped 45.

## Push
See the integrator's return value; the push of `main` and the tag follows this commit.
