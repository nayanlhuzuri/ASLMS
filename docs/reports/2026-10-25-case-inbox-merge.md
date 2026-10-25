# Report: case-inbox-merge (row 152)

Date: 2026-10-25. Branch `feature/case-inbox-merge`, squash-merged into `main` as f6c913d, tag `feature/case-inbox-merge-done`.

## What changed
- One "Case inbox" menu with six tabs: Working on, Sent by me, Claimed by me, Disposed, Department cases, Pending action.
- Working on reads `GET /inbox/mine?view=working`, extended read-only: `due_soon` and `sent_by` on the custody brief, cases with me whatever their status, own due date first. Show control and side panel.
- Old `/cases/*`, `/files/*` and `/inbox/files` addresses redirect with the query string.
- No migration, no table, no visibility change. 44 files (frontend components, `services/my_cases.py`, tests, uicheck routes, design note, log).

## Gates
- Repository state at the start: branch clean; `git log main..feature/case-inbox-merge` held only this feature's five commits; design status `approved`; decisions-log entry and backlog row 152 present.
- CI on `main` head (run 40195543168): success.
- `ruff check .`: All checks passed.
- `pytest -q`: 2319 passed, 3 skipped (41 min).
- `docker compose build`: succeeded.
- Portal smoke (`web` up, `portal_smoke.py`): passed.
- The Compose `uicheck` run was not part of these gates.

## Merge notes
- `main` moved on while the branch was open (docs commits and a `compose.dev.yml` backup-profile change). The squash conflicted in `docs/backlog.md` and `docs/claude_ASLMS_design_decisions.md` only. Resolved by keeping main's rows and entries and taking the branch's row 152 and its log section after them. No code conflict.
- The backlog has a duplicated row 156 that was already on `main`; left as it was.
- A first commit attempt failed on the conflict; the tag created by that attempt was deleted and made again on the real merge commit.

## Review findings (advisories) and how closed
1. `/inbox/counts` needs `cases.view_scope`, so a login with `cases.view_all` but no `view_scope` sees an error banner above Sent by me. No default type is affected. Not fixed; follow-up row added.
2. `test_claimed_items_carry_new_brief_fields` asserts only that `due_soon` is a boolean. Follow-up row added.
3. The brief counts a row overdue only with a pending action, while the custody card counts it whatever the action. Follow-up row added.

## Deviations
Six, listed in the design note, none changes a business rule, a visibility rule or the API.

## Pushed
See the final return values; the push is fast-forward only.

## Load status
`aslms queue-status` did not answer within 120 s when run, so no figure is recorded here.
