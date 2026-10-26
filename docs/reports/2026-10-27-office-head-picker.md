# office-head-picker (backlog row 176) - integration report, 27 Oct 2026

## What changed
- Backend: `HeadIn` takes `user_id` (email kept for the CLI, new-login fields retired with 422); heads chosen from current logins; logins with no office yet (`users.office_id` and `role` nullable, CHECK `ck_users_placed`); `login_no_office` retired. Migration 0029 `0029_office_head_picker.py`.
- Portal: kit `UserPicker` (`frontend/src/components/ui/UserPicker.tsx`, `userPicker.module.css`, tests) over `GET /admin/users?q=`; head section in New Office and Reactivate; head-change request uses the same picker; No Office Yet badge and filter; link to Users keeps the half-filled form.
- 42 files, about 2820 insertions. Design note `docs/design/office-head-picker.md` (approved).

## Gates
- ruff check: all checks passed.
- pytest -q: 2487 passed, 3 skipped (32m54s), every run green.
- docker compose build: succeeded.
- portal smoke (web recreated with `--no-deps`): passed.
- git status clean; design status approved; decisions-log entry and backlog row present.
- CI on main before merge: success (run 40376584024).

## Push
See the final return of the integrator (merge commit 938d741, tag `feature/office-head-picker-done`).

## Review findings (advisory, all four left open as follow-up row 185)
1. Offices.tsx 229-238: stale `aslms.officeDraft` wins over `?parent=`.
2. Tickets.tsx 350 and 484: `stateWideUsers` wider than the server's State-wide test, 403 possible.
3. UserPicker.tsx 296-298: failed search shows the empty-state text.
4. Offices.tsx 357: `?reactivate=1` not checked against office state or `offices.manage`.

## Deviations
None beyond those written into the design note. Commit footer follows the session's attribution line.

## Follow-up rows
Row 185 `office-head-picker-followups` (above); row 184 already existed.

## Load status
`aslms queue-status`: order_pdf done 138481, pending 206167, skipped 8; status_batch done 1286, skipped 6; masters done 1; dossier skipped 58 (tail of the output).
