# Report: state-insights-portal (row 259)

Merged 20 Nov 2026 (squash commit a200318, tag `feature/state-insights-portal-done`). Design: docs/design/state-insights.md (approved), round 2 of 3.

## What changed
- `/insights` page first under Oversight: Recharts 3.10.1 pinned exactly and loaded only on that route (118 KB gzipped chunk), filters in the URL, cross-filtering charts and headline figures, View As Table, the export dialog (Excel, PDF).
- Insights Groups screen (`/admin/insights-groups`) and the Names in Cause Titles list on Department Mapping (`/admin/mapping/title-names`).
- Frontend only: no migration, no table, no new endpoint. Strings in `messages.ts`, process workflows and Software Documentation 1.12, decisions log, follow-up rows 269 and 270.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3794 passed, 3 skipped (1:23:03).
- `docker compose build`: succeeded (no service recreated; no `compose up`).
- Screen check on a private network (temporary `web` and `uicheck` images from the branch, removed afterwards): 195 routes and states, 638 screenshots, 0 findings; 910 passed, 14 skipped.
- `git status` clean on the branch; design status approved; decisions-log entry and backlog row present.
- CI on main: last run success (run 44659289627, "Deploy rows 258 and 267").

## Review findings (advisories, from the cycle's inputs)
The five advisories were passed to the integrator as review findings: (1) Compliance bar click in the State scope drops `dept`/`band` when the same department and Claimed band are already selected; (2) a shared link with `scope=state`, another department or State-only filters does not fall back to the viewer's own view; (3) the State Cases figure shows pressed but a second click does nothing; (4) the chart grid is two columns at a 680 px container, so 768 px shows two columns against the design's one; (5) `npm audit --omit=dev` shows one moderate advisory on `next` 16.4.3 (also on main; deviation 30 awaits the owner's acceptance or a `next` 16.4.6+ bump).
They are not closed in this merge: the integrator does not change code. See follow-up rows below.

## Deviations
Deviations 22 to 32 of the design note stand; deviation 30 (the `next` advisory) needs the owner.

## Follow-up rows
Rows 269 and 270 (scribe) and row 271 (the advisories above). The review advisories above are row 271.

## Load status
`aslms queue-status` (database up): order_pdf done 293,402, pending 105,060, skipped 119; status_batch done 3,962, skipped 9.

## Push
See the integrator's return: main and the tag pushed fast-forward only.
