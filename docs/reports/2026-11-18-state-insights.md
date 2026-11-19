# State Insights, round 1 (row 258), integrator report

Merged 18 Nov 2026 as one squash commit on `main` (`5f59cf0`), tag `feature/state-insights-done`. Design: `docs/design/state-insights.md` (approved). Round 1 is the backend; rounds 2 and 3 are rows 259 and 260.

## What changed
- Migration 0039 `state_insights`: grouping tables (subject groups, categories, case-type lines), `insight_case_facts` (derived, one row per case, never deleted) and `office_title_names` (printed department names mapped to offices); grants without DELETE; 20 kinds of case, 15 subject groups, 235 categories and 57 case-type lines as reference data.
- `services/insights_rules.py` (rule readers, `READER_VERSION` 1), `insights_facts.py` (per-case readings, dirty test, refresh and rebuild), `insights_groups.py`, `insights_scope.py`, `insights_filters.py`, `insights.py`, `insights_export.py` (audited Excel and PDF), `matching_rules.py` title phrases. No AI, no NAPIX, SourceTrace or model call.
- Jobs in the existing scheduler: `insights-refresh` every 10 minutes and `insights-rebuild` at 04:45 IST.
- Functions `insights.state`, `insights.department` and the reserved `admin.insights_groups`; endpoints `/insights`, `/insights/cases`, `/insights/fields`, `/insights/export`, `/admin/insights/*`, `/admin/title-names`; an `insights` block on data-health; `aslms insights refresh|status|groups`; five `INSIGHTS_*` settings.
- Frontend: only generated files (`openapi.json`, `schema.d.ts`, `enumCodes.json`) and `messages.ts`; no screen (row 259).
- Docs: design note, decisions log, runbook, process workflows, guides.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3755 passed, 3 skipped (1 h 12 min 38 s); no failure in the run.
- `docker compose build`: succeeded (build only, no `up`).
- Screen check (private network, `web` and `uicheck` images built from the branch, runbook section 16): 184 routes and states, 594 screenshots, 0 findings; 866 passed, 14 skipped; temporary container, network and images removed.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (run 44148028661). `origin/main` equalled local `main`.
- `git log main..feature/state-insights`: three commits, all row 258.

## Review findings
Seven advisories, none blocking, left open and recorded as row 267 (build before row 259): (1) the dirty test misses a change whose transaction began before the build; (2) a rebuild keeps stale maps across a refresh's newer fingerprint; (3) `dept` and `band` filters accept another department in a department scope; (4) phrases with an apostrophe, quote, `[`, `:` or non-ASCII can be listed but never mapped; (5) on a fresh database case types read `other` until `init` is re-run after the masters sync; (6) group write endpoints return zero counts and `sort_order` is unbounded; (7) `filed` for a year older than the last 8 matches nothing.

## Deviations
None beyond those listed in the design note; deviation 8 (dirty guarantee) is contradicted by advisory 1 and is corrected in row 267.

## Follow-up rows
- 267 `state-insights-review-advisories` (the seven advisories).

## After the merge
Apply 0039 with the `migrate` step, then `init` (seed), `docker compose build`, and the app services recreated as in the deploy notes. Not done here: the deploy is the owner's step.

## Push
See the final line of the cycle: `main` and the tag pushed fast-forward only when the remote accepts them.

## Load status
`aslms queue-status` did not answer within 100 seconds at the time of the report (the worker is under the historical and nightly load); not recorded.

## Deploy
Rows 258 and 267 deployed together on the night of 19 to 20 Nov 2026, from `main` at 8d57f8e after CI was green. The
checkout was on the row 259 branch, so the web image was built from a clean detached worktree of `main`; `backend/` on
the branch is identical to `main`, and the migrate step's source check passed.
- 02:53 IST: `napix_call_log` held 609,245 rows, revision 0038; `api`, `worker`, `worker2`, `scheduler`, `web` and
  `pgbouncer` stopped.
- `docker compose --profile ops run --rm migrate`: preflight passed (dev, 7 warnings), "the image matches ./backend
  (migrations up to 0039)", backup `20261120-0253-pre-migrate` written and listed by `pg_restore`, 0038 -> 0039, seed 30
  rows (`ref_permission` +3, `role_permissions` +27), audit row `system.migrated`. Done at 03:24.
- `up -d --wait` with the court-data switch, then `--no-deps --force-recreate api worker worker2 scheduler`: the switch
  on in `api`, `worker` and `worker2`, both workers "NAPIX on", each container on its new image, `api` health 200.
- `web` could not start: after the reboot of 19 Nov, Windows (WinNAT) reserved the TCP range 2979 to 3078, so port 3000
  cannot be bound ("ports are not available ... forbidden by its access permissions"). Nothing in ASLMS causes it; the
  fix is `net stop winnat` then `net start winnat` in an administrator terminal, then `up` of `web` with the switch and
  the `BUILD_ID` check (the image's is `C02TPJAhWFQ5pkmxo-UMP`). The portal stays down until then.
- `aslms insights refresh --all` 03:26 to 03:28 IST: 84,668 checked and built in 132.8 s, one new category, 0
  re-derived, 4,369 unmapped phrases, 0 case-type lines. `aslms insights status`: `facts_built` = `live_cases` =
  84,668, `waiting` 0, `reader_version` 2; State bases party 53,456, counsel 44,157, title 31,378, officer 1,475, writ
  372; one category not grouped; 4,369 unmapped phrases across 20,375 cases.
