# github-and-ci (backlog row 15), 2026-10-20

Design: docs/design/github-and-ci.md (approved). Branch feature/github-and-ci, squash-merged to main (1215e0e), tag feature/github-and-ci-done.

## What changed
No migration, table or endpoint; docs/schema/schema.md unchanged. 47 files.
- backend/tools/repo_policy.py (tree, range and history checks) with tests in backend/tests/unit/test_repo_policy.py; gitleaks rules; pre-push hook.
- .github/workflows (CI, weekly secret scan) and Dependabot; backend/constraints-ci.txt.
- .claude/hooks/guard.py: refuses forced, mirrored, all-branch and deleting pushes, other remotes, remote configuration and gh secret changes; every line of a multi-line command is checked. Tests in backend/tests/unit/test_guard_push.py.
- A test database per run and the cluster lock; team definitions, runbook section 19, decisions log, backlog.

## Gates
- ruff check: All checks passed.
- pytest -q: 1663 passed, 2 skipped (21m20s).
- docker compose build: succeeded (api, web, worker, init, pgbouncer, backup).
- frontend unchanged: portal smoke not required.
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings and how closed
- Blocking (guard treated a newline as whitespace): closed in commit 613f90d, the guard checks every line of a multi-line command, with tests.
- Advisory, left open and recorded as deviations/follow-ups in the design note, not blocking: git `-c` remote options and `gh -R` flags; wrapper commands (env, time, nohup, xargs, sudo) and `url.*.insteadOf`; `++ ` added-line and quoted-path handling in repo_policy `_added_lines` (gitleaks still covers it); the integrator's CI check looking only at the newest run on main (a docs-only run can hide a red code run); `cancel-in-progress: false` still cancelling a pending run. Until the owner applies the deny list (row 97) the generic ask prompt is the remaining stop.

## Deviations
See the design note's deviations list (deviation 1: the owner applies the settings.json allow and deny entries; deviation 12: discovery runner test flake, row 100).

## Follow-up rows
97 github-first-push, 98 dependency-locks, 99 test-postgres-service, 100 discovery-runner-test-flake (already in the backlog).

## Load status
queue-status (order_pdf done 84518, pending 217326, skipped 4; status_batch done 693, skipped 6; dossier skipped 27; masters done 1).
