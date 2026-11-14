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
