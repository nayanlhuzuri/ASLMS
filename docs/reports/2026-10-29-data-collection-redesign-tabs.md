# Report: data-collection-redesign-tabs (row 173), 29 Oct 2026

## What changed
- Backend: one read, `GET /admin/data-load/gaps` (cases without details, orders not available, documents without text), answering 503 `search_timeout` when the query is cancelled. No migration, no table change; `docs/schema/schema.md` unchanged.
- Portal: the Problems and Fixes tab (`ProblemsAndFixes.tsx`: Court Connection line with the check, Failed Fetches with Retry and Retry All, Possible Duplicates, Data Gaps with Collect These and Try Again); System Health Court Calls section (`CourtCalls.tsx`: recent resets, e-mail, call log) for `admin.service_health` readers; the Health, Queue and Calls and Duplicates tabs removed (`Health.tsx`, `Queue.tsx`, `Duplicates.tsx`) with redirects `/data/health` to `/data/overview`, `/data/queue` and `/data/duplicates` to `/data/problems`.
- Also: `frontend/openapi.json` and `schema.d.ts`, messages, routes, label rules, uicheck fixtures and spec, tests, design note, decisions log.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2949 passed, 3 skipped (52 min 36 s), every run green.
- `docker compose build`: succeeded (api, worker, scheduler, init, web, pgbouncer built). No `up` of any kind.
- Screen check on a private network against `web` and `uicheck` images built from the branch (temporary tags, network, containers and images removed afterwards): run 20261029-1336, 147 routes and states, 350 screenshots, 0 findings; 467 passed, 7 skipped.
- `git status` clean on the branch; design note status `approved`; decisions-log entry and backlog row present.
- CI on `main`: last run success (run 40805934547).

## Review findings and how they were closed
1. Advisory, Collect These with a `done` dossier row reports "queued" while nothing is fetched: not fixed in this cycle; follow-up row 204 (1).
2. Advisory, the 503 `search_timeout` test patches all of `data_load.gaps`: not fixed; follow-up row 204 (2).
3. Advisory, decision 4 role-based live checks not recorded: not recorded; follow-up row 204 (3), an owner browser check.

## Deviations
None beyond those listed in the design note's round 2 section.

## Follow-up rows added
Row 204 `data-collection-redesign-tabs-followups` (proposed).

## Push
See the final result of the integrator run: `main` and tag `feature/data-collection-redesign-tabs-done` pushed fast-forward only when the remote accepted them.

## Load status
`aslms queue-status` answered after the merge: order_pdf 163086 done and 226529 pending, status_batch 1567 done, masters 1 done, dossier rows skipped 70 (excerpt; the historical load continues in the shared worker).

## Deploying
Screen check on a private network against a `web` built from the merged tree (the shared stack untouched):
467 passed, 0 findings (147 routes and states). CI on `main` passed (run 40841538447).

Deployed on 29 Oct 2026 at 14:38 IST (no migration): images built, `up` with the court-data switch (checked true
in api and worker), `portal_smoke.py` passed.
