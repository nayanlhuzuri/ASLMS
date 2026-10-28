# Cycle report: next hearing highlight (row 190), 28 Oct 2026

Design: `docs/design/next-hearing-highlight.md` (approved). Branch `feature/next-hearing-highlight`, squash-merged as 082286c, tag `feature/next-hearing-highlight-done`. Frontend only: no backend file, no API change, no migration.

## What changed
- Kit `HearingDate` badge and the IST band helper `hearingBand`: Today and Tomorrow strong red, 2 to 7 days soft amber, a suggested date outlined, Date Passed, No Date Yet and Disposed in words.
- Used on the case header, rail, case details modal, every Next Hearing column (Case inbox tabs, Department cases, Search, Claim lists) and the dashboard hearings. `hearingBadge`, `hearingCountdown`, `dayWords` and `NextHearingCell` retired. New token `--on-red` with contrast tests.
- uicheck states at 375, 768 and 1280 px.

## Merge conflicts
`CLAUDE.md` (kept main's row 188 entry and added the row 190 entry), `docs/claude_ASLMS_design_decisions.md` (both sections kept), `frontend/e2e/fixtures/index.ts` (took main's richer `partial_matches` fixture from row 197). Backlog merged automatically; row 190 set to done, no renumbering.

## Gates
- `ruff check .`: all checks passed.
- `pytest -q tests/unit` (includes the OpenAPI snapshot): 1171 passed, 3 skipped.
- Frontend: `npm run lint` clean, `npm run typecheck` clean, `npx tsc --noEmit` in `frontend/e2e` clean, `npx vitest run` 82 files, 1695 passed, `npm run gen:api` no diff.
- Full uicheck, run on a private Docker network against a `web` image built from the merged tree under temporary tags (shared stack untouched; container, network and images removed afterwards): 132 routes and states, 314 screenshots, 0 findings; 422 passed, 7 skipped, 0 failed.
- Design note status `approved`; decisions-log entry and backlog row present.
- CI on main at the time: run 40619478342 for 057cf62 still in progress (not failed).

## Push
See the final report of the integrator run for the pushed commit and CI run address.

## Review findings
No blocking findings. Advisories 2 and 3 fixed in 5c47969; advisory 1 (run the full uicheck) closed by the run above.

## Follow-up and load status
No follow-up rows. Load status not taken: `aslms queue-status` did not return within 120 s in this run. After the merge, `docker compose build` and the owner's usual `up` for `web` carry the change.
