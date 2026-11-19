# State Insights review advisories (row 267), integrator report

Merged 19 Nov 2026 as one squash commit on `main` (`b1f244e`), tag `feature/state-insights-review-advisories-done`. Design: `docs/design/state-insights-review-advisories.md` (approved). Backend only, no migration.

## What changed
- `services/insights_facts.py`, `insights_groups.py`, `insights_filters.py`, `insights_rules.py`, `api/routers/insights.py`, `cli/insights.py`, `core/config.py` (`INSIGHTS_DIRTY_LOOKBACK_MINUTES`), `.env.example`.
- Watermark dirty test; per-batch maps and end re-derivation in `rebuild`; `dept` and `band` refused outside the State scope (400 `bad_filter`); phrases folded so every listed phrase can be mapped; seed case-type lines placed by the refresh job and listed by `aslms insights groups check`; real counts from group writes and `sort_order` 0 to 10,000 (400 `bad_sort_order`); `filed` compares the year; `READER_VERSION` 2.
- Generated `frontend/openapi.json` and `schema.d.ts` (description text only). No table, no endpoint added.
- Docs: design note (12 deviations), decisions log, schema.md, operations.md, CLAUDE.md.

## Gates
- CI on `main` (origin/main = main, `823ff1c`): last run success.
- `ruff check .`: All checks passed.
- `pytest -q`: 3794 passed, 3 skipped (1:27:01).
- `docker compose build`: succeeded. No `up` run.
- Screen check (frontend changed only in generated files), private network and temporary images: 866 passed, 14 skipped, exit 0; container, network and images removed.
- `git status` clean on the branch; design status approved; decisions-log entry and backlog row present.

## Review findings
- Advisory (set_case_types insert races a refresh that has placed a seed line but not committed): not fixed in this cycle; recorded as follow-up row 268.

## Deviations
None beyond the design note's twelve.

## Follow-up rows
- 268 `state-insights-case-type-save-race`.

## Push
See the integrator's final answer; the push is the last step after this report is committed.

## Load status
`aslms queue-status` gave no output within 60 s; not recorded.

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
