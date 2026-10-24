# Court data freshness (backlog row 122) - integration report, 24 Oct 2026

Merge commit: e6e3359d5d3cfb628c0ff9f33f8423e0a2de962a (squash of feature/court-data-freshness). Tag: feature/court-data-freshness-done.

## What changed
73 files. Disposed cases are refreshed monthly for one year after disposal (daily 02:30 IST slice, lane daily,
priority 55, capped); restored cases rejoin the status cycle with a status_changed event. Corrected cause lists are
picked up by the 18:30 run (queue kind causelist_recheck, Show Cause List only); a re-issue is a new causelists
version with its own entries, the old one superseded; readers read current versions. napix_call_log is kept 2 years
by a daily 03:45 IST purge; napix_responses kept without limit. IST dates come from one helper;
`aslms napix-probe-rate` logs every call. Migration 0023 (`0023_court_data_freshness.py`) - not applied by the
integrator; the owner's `migrate` step applies it. Tests: tests/db/test_migration_0023.py,
tests/unit/test_court_data_freshness_unit.py and others.

## Gates
- ruff check: All checks passed.
- pytest -q: 2123 passed, 3 skipped (26m42s).
- docker compose build: succeeded.
- Frontend changed: `docker compose up -d --wait --no-deps web` healthy; portal_smoke: passed.
- git status clean on the branch; design note status approved; decisions-log entry and backlog row present.
- CI on main: latest run success (run 40099314394, "Approve design: followups-oct (row 137)").

## Review findings
Rounds 1-3: one blocking finding and four advisories, fixed in 229f0c7, 4fdcb27, 948dc88, 1337ff9, 76840ad
(Deviations 17-21). Round 4: may merge, no blocking findings; two advisories became rows 138 and 139.

## Deviations
Merge conflict in docs/backlog.md (rows 137 on main, 138/139 on the branch) resolved by keeping both sides.

## Follow-up rows
138 causelist-day-revival-as-new; 139 runner-call-log-timing (both added on the branch).

## Load status
`aslms queue-status` did not answer within 120 s when run; not recorded here.
