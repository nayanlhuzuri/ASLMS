# Report: portal-shell (backlog row 11)

Date: 2026-10-10. Design: docs/design/portal-shell.md (approved by the owner 2026-10-10). Merge commit d94ee73, tag `feature/portal-shell-done`.

## What changed
- `frontend/`: new Next.js portal (96 source files under `frontend/src`, Dockerfile, eslint, vitest, generated API types from `openapi.json`). Backend-for-frontend relay (`/api/backend/...`), tokens in httpOnly cookies, one refresh per expiry. Screens: OTP sign-in, password reset, first-sign-in password and profile, shell, dashboard, user and access administration, profile.
- `backend/aslms` (5 files) and `backend/tests` (6 files): reference labels, users list filters and paging, OpenAPI export, trusted client address from the web service.
- Compose: `web` service. No migration, no new tables, no new backend endpoints beyond the above.

## Gates
- ruff check: All checks passed
- pytest -q: 792 passed, 67 warnings (576 s)
- npm run lint, typecheck: clean; npm test: 14 files, 135 tests passed; npm run build: succeeded; npm run gen:api: no diff
- docker compose build: succeeded (init, api, worker, scheduler, web)
- git status clean; design status approved; decisions-log entry (2026-10-10) and backlog row present

## Review findings and closure
All four are advisory and were not fixed in the cycle; they are carried to backlog rows 43 and 44.
1. Relay drops `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox` on document downloads: row 44.
2. 30 s refresh memory can expire before the new cookies reach the browser on slow uploads (up to the 120 s relay timeout): row 44.
3. Compose verification steps 3 and 5-8 not run against the stack: not run by the integrator (migrations 0009-0013 are not applied to the dev database); row 43.
4. `clientAddress` trusts the browser's `X-Forwarded-For`: row 44 with row 16.

## Deviations
Deviation 13 of the design note stands: verification steps 3 and 5-8 pending. The `npm` gates were added to this run at the owner's request.

## Follow-up rows
43 (portal-hardening, existing), 44 (portal-relay-fixes, new).

## Load status (queue-status)
causelist_day: done 50, pending 559, skipped 36. dossier: done 21575, failed 201, pending 417, skipped 22. masters: done 1. order_pdf: pending 160980. status_batch: done 97, skipped 4.
