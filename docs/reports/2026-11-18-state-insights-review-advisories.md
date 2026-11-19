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
