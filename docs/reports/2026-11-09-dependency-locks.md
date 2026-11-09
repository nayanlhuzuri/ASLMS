# Report: dependency-locks (row 98), 9 Nov 2026

## What changed
- `backend/uv.lock` and exported pinned files `backend/requirements/dev.txt` (CI, tests) and `backend/requirements/image.txt` (images); `backend/constraints-ci.txt` removed.
- `backend/tools/deps.py` (lock, check, sync); `backend/pyproject.toml`, `backend/Dockerfile` and `.github/workflows/ci.yml` install from the exported files.
- `backend/aslms/services/source_check.py` follows the new layout; tests `test_dependency_lock`, `test_deps_tool`, updated CI workflow and source-check tests.
- Docs: runbook section 23, Hosting Guide 1.3, decisions log, design note, CLAUDE.md focus line.
- No tables, endpoints or migration.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3206 passed, 3 skipped (56m47s), every run green.
- `docker compose build`: succeeded (all images built).
- Screen check: not required, `frontend/` unchanged.
- Design status approved; decisions-log entry and backlog row present; `git status` clean.
- CI on main before merge: latest run success (Secret scan, run 42539398805).

## Review findings
- Advisory: `deps.py sync` does not check it runs in a virtual environment and could uninstall global packages. Not fixed in this cycle; recorded as backlog row 227.

## Deviations
- Hosting Guide contents page numbers not refreshed (row 226, from the build).

## Merge and push
- Squash commit 9538a7d on main, tag `feature/dependency-locks-done`. Push result: see the final return.

## Load status
- `aslms queue-status` did not answer within 120 s (database busy with the full test run); not captured.
