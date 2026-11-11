# Portal names and labels (row 232) - integrator report, 11 Nov 2026

Branch `feature/portal-names-and-labels`, squash-merged into `main` as 1d9bfe1, tag `feature/portal-names-and-labels-done`.
Design note: `docs/design/portal-names-and-labels.md` (approved).

## What changed
153 files. Office and department names in place of codes through one read-only `GET /reference/offices` (api router
`reference.py`, `services/reference.py`, schemas) and a kit `OfficeName`; server labels shown in Title Case by the portal with
one label helper and an enum-label test (owner's option (a): no data change); Case Details tab labels; audit action
registry and names for the Auditor with the code kept on the entry page; Title Case report texts with screen-only columns;
string fixes P4, R2, R1, D1, S3, A3, L2, C3. No table, no migration.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q` (full run, allowed to finish): 3238 passed, 3 skipped, 255 warnings in 46:04.
- `docker compose build`: succeeded (build only, no `up`).
- Screen check (docs/operations.md section 16, private network `tmpig-net`, temporary images, shared stack untouched):
  174 routes and states, 419 screenshots, 0 findings at 375, 768 and 1280 px
  (`data/uicheck-tmpig/20261111-0735/findings.json`). Container, network and both images removed.
- CI on `main` before the merge: last run success (42908098848). `origin/main` equalled local `main` (cdbde5d).
- Design note status approved; git status clean on the branch.

## Review findings
Earlier attempt today stopped at the screen check (9 findings at 1280 px on /audit and /causelist). Fixed on the branch in
8970732 (audit Record cell never splits a word, department badges wrap on the cause list) with four review advisories
in 533ec3e ("Any" for the date presets, no retryOnMount on two hooks, "Database Migrated"). No follow-up row needed
(row 236 already exists for alert titles and office names).

## Deviations
None. `queue-status` ran after the merge; the queue showed no failures attributable to this change.

## Follow-up rows added
None.

## Deployed
11 Nov 2026 at 08:55 IST, images built from clean `main` (deb969a) after CI run 42949508422 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`wPVL2NOlyKdUiEOrwaLmB`), and `portal_smoke.py` passed.
