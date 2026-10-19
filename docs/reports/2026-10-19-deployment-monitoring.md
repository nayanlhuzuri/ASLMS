# Report: deployment-monitoring (backlog row 77)

Merged 2026-10-20 (cycle built 19 Oct 2026). Branch `feature/deployment-monitoring`, tag `feature/deployment-monitoring-done`.
Design: Part B (decisions 22-28) of `docs/design/deployment-checklist.md`, approved; `docs/design/deployment-monitoring.md` is a pointer.

## What changed
- Compose profile `monitoring`: Prometheus, Alertmanager, Grafana, Flower, postgres and redis exporters, the ASLMS operations exporter; all interfaces on 127.0.0.1. Profile `monitoring-host` adds node-exporter and cadvisor.
- `aslms ops metrics` (`services/ops_metrics.py`): read-only, as `aslms_readonly`. Queue, jobs, worker liveness, NAPIX window, mail, backups, disk, ClamAV signatures, portal probe and certificate expiry.
- API request metrics (`api/metrics.py`) on internal port 9100.
- 17 alert rules (`infra/prometheus/rules.yml`) with promtool tests (`rules.test.yml`), mailed by Alertmanager; three provisioned Grafana dashboards.
- Migration 0020: `GRANT pg_monitor TO aslms_readonly` (no new tables; no endpoints added). Preflight now requires `ASLMS_READONLY_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `FLOWER_BASIC_AUTH`.
- 38 files changed in the squash.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q` (full, to completion): 1471 passed, 109 warnings in 25m42s. No file failed; no re-runs needed.
- `docker compose build` (root): succeeded (api, worker, scheduler, web, backup, init built). The owner had added the Grafana, Flower and alert-mail values to `.env` (not read).
- Portal smoke: skipped, `frontend/` unchanged.
- `git status` clean on the branch; design note status `approved`; decisions-log entry and backlog row 77 present.
- promtool (tester): `check` and `test rules` SUCCESS.

## Review findings (advisory) and closure
None blocks the merge. All are in follow-up row 88 (row 87 holds the owner-run checks).
1. WorkerStalled is measured from a pass's start, so it fires falsely during long load passes. **Fix before the pilot** (row 88 item 1).
2. No alert on the ops exporter's own scrape errors (row 88 item 2).
3. JobLate cannot fire for a job that never succeeded (row 88 item 3).
4. The required Grafana and Flower secrets break every compose command until set; now set on the dev machine (row 88 item 4).
5. Preflight checks only `COMPOSE_PROFILES`, not `--profile` (row 88 item 5).

## Deviations
Listed in the design note, "Deviations made while building Part B": two extra gauges, an `unmatched` route label, JobLate as three rules with a `late_after` label, ServiceDown also on `pg_up == 0`, the ops exporter on `default` and `edge`, the three secrets required even without the profile. Also: the scribe's follow-up row 87 covered only owner checks, so the integrator added row 88 for the review findings.

## Follow-up rows
- 87 monitoring-owner-checks (apply migration 0020 through `migrate`, start the profile, test alert e-mail, dashboards, pilot SMTP and `OPS_ALERT_EMAIL`).
- 88 monitoring-followups (review findings above).

## Load status
`aslms queue-status` after the merge (tail): order_pdf done 69890, pending 231861, skipped 3; status_batch done 693, skipped 6; masters done 1; dossier skipped 27 (head rows not captured). The load is still running. Migration 0020 is not yet applied to the dev database (row 87).
