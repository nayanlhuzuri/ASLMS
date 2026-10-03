# Backlog

The team takes the top row whose status is `todo` (`/team-cycle`). Reorder rows to change priority; add rows
for new work. Statuses: `todo`, `designing`, `awaiting-approval`, `blocked`, `approved`, `building`, `review`,
`done`, `parked`. Slugs are branch names (`feature/<slug>`) and design-note names (`docs/design/<slug>.md`).

| # | slug | title | status | design | report |
|---|---|---|---|---|---|
| 1 | offices-admin | Offices administration: departments and directorates (create, edit, deactivate, tree), designations, the super admin's first department admins | awaiting-approval | [docs/design/offices-admin.md](design/offices-admin.md) | |
| 2 | recommend-and-claim | Counsel codes, keywords, name patterns, watchlist; the scoring engine over cause-list entries and dossiers; recommendations (≥ 0.85 strong, 0.50–0.85 possible, < 0.50 unclaimed pool); claim, dismiss, suggest elsewhere, transfer request/decide, allot, release; the case inbox API | todo | | |
| 3 | cases-api | Case endpoints with server-side visibility (State → Department → Directorate), search by CNR / number / party, the case detail page data (dossier, hearings, orders, parties, advocates, links), NAPIX search-the-court behind `cases.search_court` | todo | | |
| 4 | documents-uploads | Uploads (PDF, Word, images; size limit; virus scan before storage), per-document visibility, download with visibility checks, order PDFs served from the store, text extraction status | todo | | |
| 5 | alerts-notifications | Alert generation from events and next dates (hearing due, next date changed, new order, status changed, compliance due, request due, recommendation), in-app and e-mail (Mailtrap) notifications, daily digest, preferences | todo | | |
| 6 | custody-workflow | Custody and moves, requests and answers, case stages, the append-only notes trail with attachments and per-note visibility (Phase 2 tables already exist) | todo | | |
| 7 | otp-and-profile | OTP sign-in and password reset by e-mail, new-device OTP, profile confirmation on first login, notification preferences | todo | | |
| 8 | sourcetrace-connector | The SourceTrace connector interface with a fake implementation; ingestion of court orders and uploaded court filings only (never notes or internal documents); ingestion records | todo | | |
| 9 | reports-dashboards | Dashboards per type (State, department, officer) and the department and State reports of the plan §5.1 and §5.10 | todo | | |
| 10 | audit-screens | Audit log API (searchable by user, case, date) for auditors; the data-health screen (queue depths, calls used, failures) and `/admin/napix/health`, re-fetch and sync buttons | todo | | |
| 11 | portal-shell | Next.js portal: sign-in, shell, dashboard, user and access administration screens, Compose `web` service | todo | | |
| 12 | portal-cases | Portal: case inbox, search, case detail (timeline, orders, parties, notes, documents), claim/dismiss/transfer | todo | | |
| 13 | portal-workflow | Portal: custody, requests, stages, notes, uploads, alerts and calendar | todo | | |
| 14 | assistant | Case Assistant conversations through the SourceTrace connector, with citations | todo | | |
| 15 | github-and-ci | Git remote, GitHub Actions running `ruff` and `pytest` against a Postgres service, so cycles can be verified outside a Claude Code session | todo | | |
| 16 | deployment-checklist | Load counts and the sample-of-20 CNR check in the decisions log, `pg_dump` / restore procedure, PgBouncer and monitoring services in Compose, the deployment runbook | todo | | |
