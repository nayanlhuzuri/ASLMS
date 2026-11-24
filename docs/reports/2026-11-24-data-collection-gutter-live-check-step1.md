# Report: data-collection-gutter-live-check, step 1 (row 187, 24 Nov 2026)

Row 187 is NOT done: the design (decision 4) has three steps; this merge is step 1 only. Step 2 is the owner's signed-in
browser check, step 3 follows it. Backlog row 187 stays open with status `review`.

## What changed
- Squash merge of `feature/data-collection-gutter-live-check` as a1527a2; tag `feature/data-collection-gutter-live-check-step1`.
- `frontend/e2e/global-setup.ts`, `checks.ts`, `uicheck-self.spec.ts`: the uicheck writes `layout-probe.js` into the run
  folder from `pageChecks`, with self-tests. Docs: design note, decisions log, runbook section 16, CLAUDE.md item 26.
- No backend, API, table or migration change.
- Merge conflicts in CLAUDE.md and the decisions log: both sides kept; this row's item renumbered 26 after rows 251, 191, 269.

## Gates
- `ruff check .`: all checks passed.
- Backend suite not re-run: `git diff 9f5df06 HEAD -- backend infra` is empty; row 191's full run on the identical backend
  tree stands (3950 passed, 3 skipped; report 2026-11-24-data-collection-redesign-advisories.md).
- Frontend: lint, typecheck clean; `npm test` 112 files, 2835 tests passed; `npm run build` ok; `gen:api` no diff;
  `frontend/e2e` `npx tsc --noEmit` clean.
- Screen check on a private network (temporary images tmp187-web and tmp187-uicheck, removed with the network and container):
  run 20261124-1423, 195 routes and states, 638 screenshots, 0 findings; 926 passed, 14 skipped. `layout-probe.js` written
  into the run folder; the probe self-tests passed at every width.
- `docker compose build`: succeeded (build only; no service touched).
- CI on main before the merge: success (run 45340551243).
- Design status `approved`; decisions-log entry and backlog row 187 present.

## Layout probe copy
`C:/Users/nayan/AppData/Local/Temp/claude/17a36c3288b654ec/f7fdaa41-b6e6-4f16-957b-6f883e4b8d3f/scratchpad/layout-probe.js`
(outside the repository, not committed).

## Review findings, deviations
None given with the cycle. Deviation from the usual merge: the row is left open and the tag carries `-step1`.

## Follow-up
Step 2 (owner pastes the probe on `/data/overview`, `/data/collect`, `/data/automatic` signed in) and step 3 remain in row 187.
Load status: not taken (database not touched).
