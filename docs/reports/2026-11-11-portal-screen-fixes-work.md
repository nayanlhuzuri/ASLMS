# Report: portal-screen-fixes-work (row 233)

Date: 2026-11-11. Branch `feature/portal-screen-fixes-work`, squash-merged to `main`, tag `feature/portal-screen-fixes-work-done`.

## What changed
Row C1 of the portal UI review (row 230): screen-specific fixes on Dashboard, Case Inbox, Case Claim, the case page, Alerts and Cause List (I1 to I5, P1, P2, P5 to P8, P10, P11, rest of P12, P13, A4, C1, C2, D2, D3). 79 files, mostly under `frontend/src` (kit layout with the case tab overflow into a More menu, workflow dialogs, messages) plus seven read-only API additions. No migration, no new table. Design: `docs/design/portal-screen-fixes-work.md`.

## Gates
- CI on main (`gh run list --branch main`): success (portal-names-and-labels, run 42953079479).
- `ruff check .`: All checks passed.
- `pytest -q`: 3243 passed, 3 skipped (59 min), every run green.
- `docker compose build`: succeeded.
- Screen check on a private network against a `web` image built from the branch: 174 routes and states, 419 screenshots, 0 findings; 575 passed, 7 skipped. Temporary containers, network and images removed; no Compose `up`.
- `git status` clean; design status `approved`; decisions-log entry and backlog row present.

## Push
See the final line of this report's commit message trail; main and the tag are pushed fast-forward only after this commit (outcome returned to the caller).

## Review findings (all advisory)
1. More trigger measured as "More" but may show the current tab's label (`layout.tsx:191`, `:294-297`): open, follow-up row 241.
2. Decision 16 built without its step 0 measurements (recorded as Deviation 1): the owner's six numbers are owed, row 241.
3. Upload description lost its `aria-describedby` hint; `CharCounter` has no id (`Upload.tsx:183-187`): open, row 241.

## Deviations
Deviation 1 of the design note (decision 16 step 0 not measured) stands.

## Follow-up rows
241 `portal-screen-fixes-work-followups`.

## Load status
`aslms queue-status` was requested but did not return within 2 minutes (run in background); load status not recorded here.

## Deployed
11 Nov 2026 at 13:25 IST, images built from clean `main` (a4299f3) after CI run 42979868899 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`6JN7R0nHF4hIc5HGj9wKY`), and `portal_smoke.py` passed. The six P6 measurements (Verification step 6) are still the owner's.
