# Design: Deployment monitoring (pointer to Part B of the deployment checklist)

```
slug: deployment-monitoring
status: approved
author: architect
date: 2026-10-18
approved_by: owner (nayanlhuzuri) on 2026-10-18, as Part B of docs/design/deployment-checklist.md
```

This note holds no decisions of its own. Backlog row 77 was split out of row 16 at design time. Its design is
Part B of [deployment-checklist.md](deployment-checklist.md), which was approved as one note. This file exists
so that tooling looking for `docs/design/<slug>.md` finds the right place. Read these sections there:

- **Decisions:** "### Part B: row 77, `deployment-monitoring`" (decisions 22-28).
- **Data:** the `pg_monitor` grant to `aslms_readonly` (migration 0020) in "## Data".
- **Services:** the `aslms ops metrics` exporter and the API request metrics in "## Services".
- **Tests:** the "Part B:" paragraph of "## Tests" (`promtool test rules infra/prometheus/rules.test.yml`,
  `test_ops_metrics_exposes_gauges`, `test_api_metrics_use_route_templates`, `test_compose_monitoring_profile`,
  and the migration upgrade, downgrade and upgrade cycle).
- **Verification:** the "Part B adds:" list at the end of "## Verification".
- **Deviations:** "### Deviations made while building Part B (developer, 19 Oct 2026)" under "## Deviations".

If this note and deployment-checklist.md disagree, deployment-checklist.md is the authority. Record any new
deviation for row 77 there, not here.
