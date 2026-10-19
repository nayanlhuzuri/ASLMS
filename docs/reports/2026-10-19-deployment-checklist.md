# Report: deployment-checklist (backlog row 16, Part A)

Date: 2026-10-19. Branch `feature/deployment-checklist`, squash-merged to `main`, tag `feature/deployment-checklist-done`. Design: docs/design/deployment-checklist.md (approved 18 Oct 2026). Parts B and C are rows 77 and 78.

## What changed
45 files. Compose split (`compose.yml`, `compose.dev.yml`): only the TLS proxy is published, Redis password, hardened unprivileged images, explicit `migrate` step, `backup` service; proxy config in `infra/proxy/`; `aslms ops` commands (backup, restore-check, restore, make-cert, preflight, load-report, sample-cnrs); runbook `docs/operations.md`, README, `.env.example`. No table, column, endpoint or migration.

## Gates
- ruff check: All checks passed
- pytest -q: 1437 passed, 104 warnings (18 min); vitest 597 passed (earlier in the cycle)
- docker compose build: succeeded (init, web, worker, backup, scheduler and others built)
- git status clean on the branch; design note status `approved`; decisions-log entry (2026-10-19, Part A) and backlog row exist
- portal_smoke.py: NOT run. The live stack is still on the old Compose layout; the smoke runs after the owner's switch-over.

## Review findings (advisory) and Windows finding
Fixed in d49217c: on Windows the COMPOSE_FILE list needs `COMPOSE_PATH_SEPARATOR=:`; noted in `.env.example`, README and docs/operations.md.
Advisory findings, all carried to row 86 `deployment-followups`:
1. backups.py: the exporting REPEATABLE READ transaction needs `idle_in_transaction_session_timeout` set to 0 (a dump over 15 minutes otherwise fails every backup and blocks migrations). To be done before the pilot.
2. A backup slot coinciding with the Sunday 04:30 restore check is skipped silently.
3. Tagged backup sets other than pre-migrate are pruned after 48 hours although `--tag before-upgrade` is suggested.
4. The disaster restore replays the superuser's old password hash (restore with a rotated POSTGRES_PASSWORD fails half-done).
5. APP_ENV accepts any string and only `prod` turns the checks on (preflight should refuse an unknown value).
6. `aslms ops make-cert` always creates a new CA (re-running it to renew breaks every pilot PC).
7. The scheduler's superuser refusal fails open if the database check errors.
8. The port-80 redirect ignores PROXY_HTTPS_PORT.

## Deviations
Monitoring and PgBouncer split into rows 77 and 78 (accepted by the owner at design). Smoke test deferred as above.

## Follow-up rows
85 deployment-owner-checks (added by the scribe), 86 deployment-followups (above).

## Load status (`aslms queue-status`, end of tail)
order_pdf done 65480, pending 236270, running 1, skipped 3; status_batch done 596, skipped 6; masters done 1.
