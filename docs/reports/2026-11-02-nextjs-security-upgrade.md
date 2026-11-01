# Report: Next.js security upgrade (row 205, `nextjs-security-upgrade`)

Merged 2 Nov 2026 as squash commit bfb07c2 on `main`, tag `feature/nextjs-security-upgrade-done`.

## What changed
- `frontend/package.json` and `frontend/package-lock.json`: `next` and `eslint-config-next` pinned exactly at 16.4.3 (three advisories: GHSA-2464-fhr4-w9xw, GHSA-673q-mjm6-r5xr, GHSA-p3m5-59mp-jv5r). `npm audit --omit=dev`: 0 vulnerabilities.
- Docs: design note, decisions log, backlog, `CLAUDE.md` focus line.
- Tests only (commit 1882fad): `backend/tests/db/test_api_napix_admin.py::test_by_user_operator_only` and `backend/tests/db/test_collect_now.py::test_collect_day_refuses_no_lists_future_and_over_2000` made independent of the run time.
- No tables, endpoints or migration. Frontend only.

## Gates
- First merge run (1-2 Nov 2026) stopped on `pytest -q`: 2 failed, 3019 passed (the two tests above). Both were date-dependent and the run crossed midnight IST. Fixed by 1882fad (tests only; both files pass in full, 43 passed). The merge was run again from the start.
- CI on main: green, run 41322493328 (head of `origin/main` = 33fa57e).
- `ruff check .`: All checks passed.
- `pytest -q`: 3021 passed, 3 skipped, 249 warnings in 2699.84s (0:44:59). Every run green.
- `docker compose build`: succeeded.
- Screen check (private network, temporary images `tmp205-web` and `tmp205-uicheck` built from the branch, runbook section 16; no Compose `up`, shared stack untouched, all temporary resources removed): `uicheck: /out/20261102-0053: 163 routes and states, 386 screenshots, 0 findings, 263 s` (521 passed, 7 skipped).
- `git status` clean on the branch; design status `approved`; decisions-log entry (29 Oct 2026) and backlog row exist.

## Review findings
- Advisory: full `npm audit` (dev dependencies included) still reports one high finding, GHSA-mrhx-c7xc-m3w5, in `zod` 4.6.5 (`frontend/package-lock.json`, reached through `eslint-config-next` 16.4.3 -> `eslint-plugin-react-hooks` 7.1.1). Same version on main, lint tooling only, nothing exposed at runtime; the design checks only `--omit=dev`. Left open and noted here; to be handled as a separate dev-only bump.

## Deviations
None. No follow-up rows added by the integrator.

## Load status (`aslms queue-status`)
dossier pending 31,294 (skipped 20); order_pdf done 200,734, pending 188,929; status_batch done 2,017 (skipped 6); masters done 1.
