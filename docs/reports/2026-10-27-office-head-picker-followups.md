# Report: office-head-picker-followups (row 185), 27 Oct 2026

Merge commit on `main`: c1cb8b9. Tag: `feature/office-head-picker-followups-done`. Design note: `docs/design/office-head-picker-followups.md` (approved).

## What changed
19 files (frontend, one backend test, docs); no migration, no table, no endpoint.
- `Offices.tsx`: the saved office draft no longer overrides an explicit `?parent=`, is kept only under `?draft=1`, and Cancel on New User clears it; `?reactivate=1` opens Reactivate only for an inactive Department-tier office when the caller holds `offices.manage`.
- `Tickets.tsx` / `can.ts`: `usersStateWide` mirrors the server's State-wide user rule (Super Administrator or `cases.view_all`), so `include_ended=true` no longer answers 403 for a `users.view` State-office reader.
- `UserPicker.tsx` and the Office Picker: an error note with Try Again for a failed search or list, instead of the empty-state text; a status span for screen readers.
- Backend test `test_api_users_list.py` pins the State-wide user-list rule. Frontend guards and e2e updated (`can.test.ts` new).

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2513 passed, 3 skipped, 224 warnings (49:51). An earlier first run was killed by the integrator after more than 100 minutes of slow progress and rerun in full; the rerun is the one counted.
- `docker compose build`: succeeded.
- Portal smoke (frontend changed): `portal smoke: passed`; api and worker both confirmed `NAPIX_ENABLED=true` afterwards.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run `success` (claim-assign-wording, push 40439485209).

## Review findings
- Advisory: `UserPicker.tsx:282` Enter refetches whenever the last settled search failed, not only while the error note is shown (decision 5). One wasted request, nothing wrong shown or chosen. Not fixed in this cycle; follow-up row 186.

## Deviations
None beyond those recorded in the design note.

## Follow-up rows
- 186 `user-picker-enter-retry`: gate Enter on `errorNote && canRetry`.

## Load status
`aslms queue-status` did not answer within 60 seconds during the merge (the dev worker is busy with the historical load); not recorded here.
