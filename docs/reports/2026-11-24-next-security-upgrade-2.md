# Report: next-security-upgrade-2 (row 269)

Merged 24 Nov 2026 from `feature/next-security-upgrade-2` by squash into `main` (on top of row 191, 20f5955),
merge commit c15dba4, tag `feature/next-security-upgrade-2-done`. Frontend only, no migration.

## What changed
- `frontend/package.json` and `package-lock.json`: `next` and `eslint-config-next` pinned exactly at 16.4.6
  (GHSA-mfr8-8qww-v76h, GHSA-vc7v-qv4w-wrv8).
- `docs/software-documentation/build.js` names 16.4.6; design note `docs/design/next-security-upgrade-2.md`;
  decisions log, CLAUDE.md current focus (item 25) and backlog row 269.
- Merge conflicts only in CLAUDE.md (current focus) and the decisions log; both sides kept, nothing of rows 251 or 191
  rewritten.

## Gates
- `npm ci` in `frontend/`; `node_modules/next/package.json` version 16.4.6.
- `npm audit --omit=dev`: found 0 vulnerabilities.
- `npm run lint` clean; `npm run typecheck` clean; `npm test`: 112 files, 2835 tests passed.
- `npm run build`: exit 0; no SecurityFatalError in the output (the intermittent failure of 16.4.3 did not appear).
- `npm run gen:api`: no diff.
- uicheck (private network `tmp269-net`, images `tmp269-web` and `tmp269-uicheck`, no Compose `up`):
  `uicheck: /out/20261124-1146: 195 routes and states, 638 screenshots, 0 findings, 425 s`; 910 passed, 14 skipped.
  Network, containers and images removed afterwards.
- `ruff check .`: all checks passed.
- `docker compose build`: succeeded (build only; no service touched).
- Backend `pytest -q`: not re-run. `git diff 2053fc8 HEAD -- backend infra` is empty, so the backend is identical to the
  tree that passed 3950 passed, 3 skipped on a fresh pgvector database for row 191 (report
  2026-11-24-data-collection-redesign-advisories.md).
- CI on `main` before the merge: the run for 20f5955 was in progress (not failed).

## Review findings
- Software documentation version (advisory): fixed on the branch in 85ff5f0.

## Deviations
- The commit footer uses the attribution given for this session (Claude Sonnet 5.5).
- `aslms queue-status` took over two minutes to answer; for the load, `order_pdf` pending 75,329 (running 2), `status_batch` done 4,563.

## Follow-ups
None added. Deploy is a `web` rebuild from `main` with the build ID checked (owner's step).
