# Portal colours, navy and cream with orange (row 229 `portal-navy-cream`)

Merged 2026-11-11 as squash commit c785046 on `main`, tag `feature/portal-navy-cream-done`. Design:
`docs/design/portal-navy-cream.md` (approved).

## What changed
93 files, 3588 insertions, 391 deletions. Frontend only: tokens in `globals.css` and recoloured component modules,
orange fills carrying navy text, due soon on ochre, the one orange headline tile (Kpi emphasis on Cases with Me while
above 0), notice and alert tones by meaning, one recommendation tone, colour guards and contrast pairs in
`tokens.test.ts`, a layout signature test with a snapshot of main's CSS (positions, sizes and spacing unchanged),
the uicheck `boxes` mode and `boxdiff`, and the approved samples as the visual reference. No table, endpoint, reference
code or migration; `docs/schema/schema.md` unchanged.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q` (backend, whole suite): 3245 passed, 3 skipped, 255 warnings in 57:57.
- `docker compose build`: succeeded (no service recreated).
- Screen check (runbook section 16: private network, temporary `web` and `uicheck` images built from the branch, all
  removed afterwards): 174 routes and states, 419 screenshots, 0 findings; 587 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success: `portal-screen-fixes-oversight: deployed 11 Nov 2026 at 19:04`).

## Review findings
- Advisory, the Save bar's Discard Changes button loses its label on hover (cream on cream, about 1.2:1; same on
  main). Closed as follow-up row 243 `save-bar-discard-hover`.
- Advisory, `layoutSignature.test.ts` writes a snapshot and passes when `layout-signature.json` is missing. Closed as
  follow-up row 244 `layout-signature-missing-fails`.

## Deviations
None beyond the design note (its deviations were written back before review).

## Follow-up rows
243 `save-bar-discard-hover`, 244 `layout-signature-missing-fails`.

## Push and CI
See the integrator's return values; the push of `main` and the tag follows this commit.

## Load status
Not recorded in this run (the host `aslms queue-status` was not run; no backend or database change in this row).

## Deployed
11 Nov 2026 at 22:15 IST, images built from clean `main` (152895f) after CI run 43055726382 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`XJynA7aen5DVPm-ISCv_m`), and `portal_smoke.py` passed. The owner's browser check of the new colours is next.
