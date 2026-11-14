# Report: assistant-ollama-work (row 189)

Date: 2026-11-14. Design: docs/design/assistant-ollama-work.md (approved). Branch feature/assistant-ollama-work, squash-merged into main.

## What changed
The sidebar Assistant gains My Work (nine fixed work questions run through the existing services with the asker's own rights; the local model only picks a question and validated parameters, keyword fallback; no note, remark or document contents; claim questions added). The case page Assistant is about its own case only. Migration 0037 (`my_work` scope value) is written, not applied: the main session deploys it with 0036. New tests: backend/tests/unit/test_assistant_work.py, backend/tests/db/test_assistant_work.py, frontend assistant tests. Fix round e024aab (frontend only, Deviation 16): uicheck fixture court answers send `work: null` / `suggest_work: false`; error state with Try Again for a failed GET /assistant/status.

## Gates
- ruff check: all checks passed (re-run on the merged tree).
- pytest: 3499 passed, 3 skipped on 48e5675. `git diff --stat 48e5675 e024aab` touches only the design note and three frontend files (no backend file), so the earlier result was relied on; the 56-minute suite was not re-run.
- Frontend: eslint clean, tsc clean, vitest 106 files, 2694 passed (re-run by the integrator).
- Screen check: the developer's run on a private network with temporary images built from the working tree holding exactly the changes then committed as e024aab (findings written at 20:10, the commit at 20:10:28 IST): 854 passed, 14 skipped, 0 failed, 0 findings (findings.json empty; logs data/uicheck-aow2/, gitignored). Judged sufficient; the earlier failed run (838 passed, 16 failed) is explained by the fixture, fixed.
- docker compose build: succeeded (api, worker, worker2, web).
- CI on main before the merge: success (run 43576345704). git status clean; design status approved.

## Review findings
Finding 4 (status read had no error state) closed by e024aab. The advisories went to row 262: (1) keyword rule for "to claim" too loose; (2) engine/checks in ollama mode for work answers; (3) no overall 45 s deadline; (4) `suggest_work` too broad; (5) import guard test missing assistant_work.py.

## Deviations
Not deployed; migrate step not run (0037 with 0036 later). See Deviations in the design note (16 entries).

## Follow-ups
Row 262 assistant-ollama-work-followups.

## Load status
Not taken (no deployment in this run).

## Deploy (14 Nov 2026, 22:10 to 23:06 IST)
- Deployed together with row 257 `offices-import` (migration 0036). CI green on `a503b92` and `cb54036`. Images built from a clean `main` (`cb54036`), `migrate` included.
- After the first 22:00 nightly refresh had queued (22:00:05, 8,030 dossier rows), `docker compose stop api worker worker2 scheduler web pgbouncer`, then `docker compose --profile ops run --rm migrate`: preflight passed (dev warnings only), the image matched `./backend`, backup `20261114-2210-pre-migrate` written and listed by `pg_restore`, upgrade 0035 → 0036 → 0037, seed nothing to insert, audit row `system.migrated`. Then `docker compose up -d` and the app services recreated with `--no-deps --force-recreate api worker worker2 scheduler web`, the court-data switch on. Portal down 22:10 to 23:06.
- Checked: `init` exited 0; the switch on in `api`, `worker` and `worker2`; both slots started ("slot main" and "slot second", NAPIX on, one interrupted run each repaired); web build ID `si0gDyIOe_PhmNS_KFM8b`; portal 307 to sign-in, API health 200; `alembic_version` 0037; `ref_office_kind` holds the six new kinds and "Directorate / Commissionerate"; `assistant_scope` includes `my_work`; `aslms assistant check` six zero counts including `work_rows_out_of_rule`; `aslms offices import --help` answers.
- Still open: the owner's live tool-call and browser checks of My Work (design Verification).
