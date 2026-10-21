# Report: system-health-inspector (backlog row 123)

Date: 2026-10-22. Merge commit on main: 71a5754. Tag: feature/system-health-inspector-done.

## What changed
- Request console behind each court API card on `/system` (`?api=<key>`): Request, Response, History, Documentation tabs; Access token card with "Check token" (audited `napix.token_checked`); NAPIX PDFs served behind `admin.service_health`; full decrypted JSON only with `cases.view_all` (audited `napix.response_viewed`).
- Backend: `services/napix_inspect.py`, `services/napix_api_check.py`, `api/routers/system_health.py`, request preview and token metadata in the integration layer; `frontend/openapi.json` and `schema.d.ts` regenerated.
- Frontend: `components/system/Console.tsx` and related; 47 files changed.
- No migration, no new table.

## Gates
- ruff: All checks passed.
- pytest: 1966 passed, 3 skipped (24m30s).
- docker compose build: succeeded.
- portal smoke (frontend changed): passed.
- git status clean on the branch; design note status approved; decisions-log entry and backlog row present.
- CI on main: gh not installed, so CI status unknown.

## Review findings and closure
- Blocking 1 (no-body send used a hidden held sample; plain string returned and audited): closed in cb166d7. A no-body send is now refused with 409 `sample_hidden` when the sample carries values of a case the caller cannot see (deviation 15).
- Blocking 2 (console `last_send` showed anyone's plain string): closed in cb166d7. Values shown only to the sender, a `cases.view_all` holder, or a viewer of the case; otherwise "not shown" and `params_sha256` withheld (deviation 16). Tests added in `test_api_system_health_console.py`.
- Advisory, left open (no blocking effect): unbounded read of the latest stored payload in `latest_answer` before the size check (two findings); a new `TokenCache` per request; party-name 200 vs 99 character limit mismatch; `staleTime: Infinity` hiding repeated `napix.response_viewed` audit rows; `edited: false` confirming a guessed value equals a hidden sample.

## Deviations
Recorded in the design note (deviations 15 and 16 from review).

## Follow-up rows
- Row 128 (owner live check) already exists. Advisory items above are recorded here and not yet a backlog row.

## Push
See the integrator's return values (pushed or not, with the reason).

## Load status
`aslms queue-status` did not answer within 120 s when run during the merge, so no figure is recorded.
