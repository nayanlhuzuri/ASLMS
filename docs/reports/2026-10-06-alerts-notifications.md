# Report: alerts-notifications (backlog row 5)

Merged to `main` as c7dd8ec (squash), tag `feature/alerts-notifications-done`. Design: `docs/design/alerts-notifications.md` (approved).

## What changed
- Migration `0007_alerts` (alerts, notifications, digests, preferences); `docs/schema/schema.md` updated first.
- Services: `alerts.py` (event scan, date sweep, raise/close, dedupe keys), `alert_rules.py`, `recipients.py`, `notifications.py`, `mailer.py` (Mailtrap API, SMTP, console), `calendar.py`; `visibility.py` and `case_detail.py` adjusted.
- API: `api/routers/alerts.py` (`/alerts`, `/cases/{ref}/alerts`, acknowledge, done, notifications, preferences, calendar); schemas.
- CLI `aslms alerts`; Celery tasks and beat entries in `jobs/celery_app.py`; settings in `.env.example` and `core/config.py`; `compose.yml` two lines.
- Tests: `tests/db/test_alert_recipients.py`, `test_alerts_generate.py`, `test_api_alerts.py`, `test_notifications.py`, `tests/unit/test_alert_rules.py`, `test_mailer.py`, schema metadata.

## Gates
- ruff: All checks passed.
- pytest: 395 passed, 1 skipped.
- docker compose build: succeeded (api, worker, scheduler, init).
- git status clean on the branch; design status approved; decisions-log entry and backlog row present.

## Review findings and closure
Closed in the branch:
- Blocking: `new_document` alert read without the per-document check (case alerts list, alert detail, timeline). Fixed in 2a0fb5a.
- Blocking: alerts of the case readable and actable by any office working on the case. Fixed in 5560bff (an alert is read and acted on only by the office addressed).

Advisory, not changed in this cycle, carried as follow-ups (see below):
- Event-scan window anchored on last SUCCEEDED run (a permanently failing event keeps the window from advancing); failing event ids not recorded.
- Closed dedupe keys never re-raise (date returning to a previous value, repeated status restoration).
- `send_pending` mails inside one transaction with row locks (duplicates on rollback, long transactions on provider timeouts); no re-check of alert openness or recipient visibility before sending or retrying.
- `sweep_dates` has no per-item savepoint; alert tasks write no failed `job_runs` row; `get_mailer` MailError (missing SMTP_FROM) leaves no trace.
- No recency guard on recommendation alerts during the historical load (decision 12): counts to record before go-live.
- Withdrawn transfer notifies the requester and leaves the receiver's `transfer_requested` alert open.
- Digest window has no overlap or cap; ConsoleMailer marks mails `sent`; ALR year taken from UTC; `new_document` body names the uploading office (design decision 19 says type only); `owning_office` called before `case is None` check.

## Deviations
Listed in the design note and decisions log (including deviation 11, per-event savepoints in `scan_events`).

## Follow-ups
Row 27 `alerts-hardening` already covers SMS, compliance directions, department-level setting and live Mailtrap check. The advisory items above were not given a new backlog row by the integrator; they should be folded into row 27 by the owner or architect.

## Load status (`aslms queue-status`)
causelist_day done 8 / pending 623 / skipped 11; dossier done 4932 / failed 38 / pending 75 / running 1 / skipped 4; masters done 1; order_pdf pending 43031; status_batch done 1 / pending 4.
