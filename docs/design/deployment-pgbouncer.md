# Design: Deployment PgBouncer (pointer to Part C of the deployment checklist)

```
slug: deployment-pgbouncer
status: approved
author: architect
date: 2026-10-18
approved_by: owner (nayanlhuzuri) on 2026-10-18, as Part C of docs/design/deployment-checklist.md
```

This note holds no decisions of its own. Backlog row 78 was split out of row 16 at design time. Its design is
Part C of [deployment-checklist.md](deployment-checklist.md), which was approved as one note. This file exists
so that tooling looking for `docs/design/<slug>.md` finds the right place. Read these sections there:

- **Decisions:** "### Part C: row 78, `deployment-pgbouncer`" (decision 29).
- **Data:** "Part C: none." in "## Data" (no migration).
- **Services:** "Part C (row 78)" in "## Services" (`infra/pgbouncer/Dockerfile` and `entrypoint.sh`, the Compose
  service and URLs).
- **Tests:** the "Part C:" paragraph of "## Tests" (`test_no_session_level_postgres_features`,
  `test_compose_pgbouncer_urls`).
- **Verification:** the "Part C adds:" list at the end of "## Verification".
- **Deviations:** "### Deviations made while building Part C (developer, 20 Oct 2026)" under "## Deviations".

If this note and deployment-checklist.md disagree, deployment-checklist.md is the authority. Record any new
deviation for row 78 there, not here.
