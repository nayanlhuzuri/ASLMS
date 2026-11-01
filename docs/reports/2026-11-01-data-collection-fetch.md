# Report: data-collection-fetch (backlog row 174)

Date: 2026-11-01. Branch `feature/data-collection-fetch`, design `docs/design/data-collection-fetch.md` (approved). Merged by squash into `main` as 78e8175, tag `feature/data-collection-fetch-done`.

## What changed
Data Collection redesign, round 3 of 4: manual requests carried out at once. 46 files (23 backend, the rest frontend, docs and tests). No migration (`alembic` head stays 0034), no new table.
- Two "now" priorities (3 for one case, 5 for bulk) in the request lane outside the reserve bands; the worker wakes within 2 s; spawned order PDFs inherit the priority.
- One Case: details and every missing order PDF before showing, live `CollectProgress`.
- Several Cases (200 lines) and All Cases Listed on a Day (2,000 cap, 6-hour rule): one bulk request at a time (409 `bulk_running`), Stop returns the rest to the normal turn.
- Requests list with live progress from audit rows; re-fetch and reference-list buttons at the "now" priority; `admin.data_load` for the new writes; audited `data_load.collect_requested` / `data_load.collect_stopped`.
- A request's spawned order PDFs are found through request ids in `fetch_queue.result.request_ids`, not a queue scan.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3021 passed, 3 skipped, 249 warnings (42 min 57 s). No failure in any run.
- `docker compose build`: succeeded (all six images built; no service recreated).
- Screen check (frontend changed): private network `tmp174-net`, temporary images `tmp174-web` and `tmp174-uicheck` built from the branch, per `docs/operations.md` section 16: 521 passed, 7 skipped; "163 routes and states, 386 screenshots, 0 findings". Container, network and both images removed afterwards.
- Design status approved; decisions-log entries and backlog row present; `git status` clean on the branch.
- CI on main: latest `gh run list --branch main` run is success (run 41257473339, Dependabot Updates; head of `origin/main` was 1091c1a).

## Review history and how each finding was closed
- Round 3 stopped the original cycle: blocking finding (a request's order-PDF items not limited to its own run, so later work reopened a finished request) plus six advisories. Fixed in round 4 (5ffddf2, 0129908, fe99a9b, 97edf2c) with request ids in `fetch_queue.result.request_ids`.
- Round 4 found one blocking finding (Retry All keeping the ids) and four advisories. Fixed in round 5 (007ca48, 5fc5890, 0cf6773, f41737e, 7111fb2).
- Round 5 re-review: mayMerge true with two advisories: (1) a corrected order date or number drops a waiting tagged PDF from a running request's list (display only), carried to follow-up row 211 `data-collection-fetch-followups`; (2) one schema.md sentence, fixed by the scribe in 189131f.

## Deviations
Deviations 1 to 29 are recorded in the design note. None added by the integrator.

## Follow-up rows
Row 211 `data-collection-fetch-followups` (already in the backlog). Round 4 of the redesign is row 177 `case-update-from-court`.

## Load status
`aslms queue-status` (1 Nov 2026): dossier pending 35,791, skipped 10; masters done 1; order_pdf done 200,734, pending 188,903; status_batch done 2,017, skipped 6.

## Push
After the merge and this report, `main` and the tag are pushed fast-forward only; the result and the CI run's address are returned with the hand-off.

## Deploying
CI on `main` passed (run 41319524069: changes, policy, backend, frontend, compose, ci-ok). Deployed on 1 Nov 2026 at
21:08 IST (no migration): images built (`docker compose build`, `--profile ops build migrate`), `up` with the
court-data switch (checked true in api and worker), `portal_smoke.py` passed.
