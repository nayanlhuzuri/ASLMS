# Design: Alerts and notifications — alert generation, in-app and e-mail notifications, daily digest, preferences

```
slug: alerts-notifications
status: approved
author: architect
date: 2026-10-06
approved_by: product owner (nayan.semt@gmail.com) on 2026-10-06
```

## Context
Plan §5.5 (Alerts and Hearing Calendar: "Makes sure no hearing or court direction is missed"; a calendar of
upcoming hearings with **critical (within 48 hours)** and **this-week** highlights; next dates from orders;
compliance alerts for actions the court has directed, with due dates; "alerts go to the current custody
holder"), §5.12 (Notifications: "In-app and email for all alerts; SMS for high-priority alerts"; "Recipients
chosen from the case owner, custody holder and watchers"; "Daily digest option to avoid excessive messages"),
§5.11 ("notification settings"), §5.1 (dashboard: own alerts), §6.1 ("By the time users log in … alerts are up
to date"), §6.2 (from court order to alert), §7 Table 8 ("Alerts and notifications: next dates, alerts, and the
notifications sent"), §9 (Phase 1: "alerts for orders with specific dates", "in-app and email notifications";
Phase 2: "SourceTrace-based alerts for orders that state a period", "SMS notifications"). CLAUDE.md: visibility
on the server for every query; an audit row for every significant action; secrets only in `.env`. Backlog row 5.

Earlier decisions in the log that this design follows:
- 25 Sep "ALERTS" (within 48 h = critical, this week highlighted; alerts go to case owner and custody holder) and
  "Channels" (in-app + e-mail baseline, SMS for high priority, daily digest option).
- 26 Sep "Request alerts" (open requests due within two days → high, overdue → critical, to the receiving office
  or addressee; case alerts also go to the custody holder).
- 27 Sep "Mail service: Mailtrap" (`MAIL_BACKEND` `auto` / `api` / `smtp` / `console`; `auto` prefers the API
  token, then SMTP, then the console; the sender on a verified domain; a mail failure never crashes; the token
  is never logged).
- DB-1 "Alerts allocate a number only when new" (look the dedupe key up before inserting; no serial burnt per
  re-run). DB_STANDARD §3: `ALR` reference numbers are allocated on `GOA`.
- recommend-and-claim "Left for later": alerts on `recommendation_made`, `case_taken_over` and the other
  ownership events; documents-uploads "Left for later": alerts on a new document; cases-api decision 4: a case
  the caller cannot see is 404; reading is not audited.

What is in place:
- Tables (migration 0001): `next_dates`, `alerts` (ref_no, case_id, kind → `ref_alert_kind`, due_at, severity
  `critical` / `high` / `normal`, status `open` / `acknowledged` / `done` / `expired`, title, body,
  source_event_id, dedupe_key unique, acknowledged_by_user_id, acknowledged_at), `notifications` (alert_id
  CASCADE, user_id CASCADE, channel `in_app` / `email` / `sms`, status `queued` / `sent` / `failed` / `read`,
  title, body, sent_at, read_at, error, dedupe_key unique), `digests` (user_id, digest_date unique per user,
  sent_at, alert_ids), `user_notification_preferences` (user_id, channel unique per user, enabled, digest
  `none` / `daily`, critical_only). None is written by any service yet.
- `AlertKind` (7 codes) with `ref_alert_kind.default_severity` seeded (`hearing_due`, `next_date_changed`,
  `new_order`, `compliance_due` high; the others normal); `EventType.ALERT_RAISED`; function
  `alerts.acknowledge` (dept head, dept admin, dept officer, directorate user, referral reviewer);
  `RecordType.ALR`.
- Events already written: `next_date_changed` and `status_changed` / `case_disposed`
  (`services/tracking.py::record_status_change`, from the daily Current Status batch, with `next_dates` rows of
  source `current_status`), `case_disposed` (`services/cases.py`, dossier apply), `order_found` / `order_stored`
  (`services/orders.py`), `recommendation_made` (engine and suggestions), `claimed`, `allotted`,
  `case_taken_over`, `transfer_requested`, `transfer_decided`, `custody_moved`, `document_uploaded`.
  `emit_event` deduplicates by key; events are append-only.
- `custody` is written on claim, allotment, take-over and transfer (`services/custody.py::move_custody`);
  `requests` exists but is written only from `custody-workflow`; `case_objections.compliance_by_date` is filled
  from the NAPIX `objections` block (empty in every sample so far).
- No mail code exists in the new build. `httpx` is a dependency; `smtplib` is in the standard library. The
  Compose `scheduler` service (Celery worker with beat) reads `.env`.
- The historical load from 2025-01-01 is running: it emits many events **now** about **old** court data (orders
  of 2025, disposals of 2025). The generator must not turn those into alerts (decision 4).

Not covered: next-date extraction from order text and the review queue for extracted dates (proposed new
backlog row `next-date-extraction`, decision 3); SourceTrace reading of period directions (`sourcetrace-connector`
or that row); SMS (plan Phase 2, no gateway); OTP sign-in and password reset by e-mail (`otp-and-profile`, which
reuses the mailer written here); the dashboard counts (`reports-dashboards`); the bell, alert list and calendar
screens (`portal-workflow`); requests and their due dates (`custody-workflow` writes them; this item only reads
them).

## Decisions
1. **Two generators, one alert table.** (a) An **event scan** turns new rows of `events` into alerts
   (`next_date_changed`, `new_order`, `status_changed`, `recommendation`, `ownership`, `new_document`); (b) a
   **date sweep** raises and updates alerts from dates that come due (`hearing_due`, `compliance_due`,
   `request_due`) and closes alerts that no longer apply. Both are idempotent through `alerts.dedupe_key`.
   Alternatives: call an alert hook from every service that writes an event — rejected, it couples a dozen
   services to alerting and a failure in alerting would roll back the court data; a database trigger —
   rejected, recipients and visibility need the Python rules.
2. **The event scan reads a time window, not a fragile cursor.** Each run processes events with `created_at ≥
   window_from`, where `window_from` = the previous succeeded run's `started_at` − `ALERT_EVENT_OVERLAP_MINUTES`
   (30); the run records `window_from` and its counters in `job_runs` (job `alerts_events`). The overlap covers
   transactions that committed after the previous run read (`created_at` is the transaction's start time); the
   dedupe keys make re-reading harmless. **The first run starts at "now − overlap"**: history is never
   back-filled into alerts. Alternative: a cursor on `events.id` (UUID v7) — rejected, ids from concurrent
   transactions commit out of order and an event could be skipped forever; a new cursor table — not needed.
3. **Scope split: next dates read from order text are a separate item.** This item consumes `next_dates` of
   any source (the date sweep reads them, decision 6) but does not write `order_specific` / `order_period` rows
   or build the review queue (`next_dates.review`). The plan's Phase 1 line "alerts for orders with specific
   dates" therefore completes when the proposed row `next-date-extraction` (rule-based reading of specific
   dates from the stored order text, period phrases flagged for review, manual `NXT` dates, the review
   endpoints) is built; until then hearing dates come from Current Status and the cause lists, which NAPIX
   updates daily. Flagged for the owner (**scope**, not a deviation of the plan's content). Alternative: build
   the extractor here — rejected, it doubles the item and needs its own sample study of the January 2025 orders.
4. **Only current court events alert.** An event becomes an alert only when its court date is recent: order
   date (`new_order`), disposal date (`status_changed` on disposal) within `ALERT_EVENT_MAX_AGE_DAYS` (14) of
   today; a changed next date only when the new date is today or later. This keeps the running 2025 load from
   raising thousands of alerts about old orders. Alternative: generate everything and expire it — rejected, it
   floods mailboxes before expiry.
5. **Case alerts exist only for cases someone works on.** `hearing_due`, `next_date_changed`, `new_order`,
   `status_changed`, `compliance_due`, `new_document` are raised only for cases with an **active primary owner
   or an active watcher** (`case_ownership.status = 'active'`), filtered in SQL. Unclaimed cases have no
   recipient under the plan (owner, custody holder, watchers) and are handled through recommendations and the
   central operator's pool. `recommendation` alerts are the only alerts about unclaimed cases.
6. **Hearing alerts.** A case's hearing dates are the union of `cases.next_hearing_date`, its listings in cause
   lists dated today or later (`causelist_entries.case_id` → `causelists.list_date`), and its latest
   `next_dates` row of source `manual`, `order_specific` or `order_period` whose review status is `not_needed`
   or `confirmed`. For each date D from today to today + `ALERT_HEARING_LOOKAHEAD_DAYS` (7) one alert, key
   `hearing_due:<case_id>:<D>`, `due_at` = D at `COURT_SITTING_TIME` (10:30 IST). Severity `high` (this week);
   raised to `critical` when `due_at − now ≤ ALERT_CRITICAL_HOURS` (48) — the same alert, upgraded, and each
   recipient is notified again at the new severity (decision 11). The body names the source ("listed in the
   cause list of …, item …, court …" or "next date per court records"). The alert **expires** when D is no
   longer among the case's hearing dates (date changed) or `due_at` passed by 12 hours. The sweep runs hourly so
   the 48-hour upgrade happens on time and the evening cause list (fetched from 18:30) reaches users before
   morning.
7. **Next date changed.** From `next_date_changed` events whose payload has both an old and a new
   `next_hearing_date` (a first date is not a change) and the new date ≥ today. Key
   `next_date_changed:<case_id>:<new date>`; severity from `ref_alert_kind` (high); `data` keeps both dates.
8. **New order.** From `order_stored` events (the PDF is in the store, so the alert links to something that
   opens); order date within decision 4's window. Key `new_order:<case_id>:<order_no>:<order_date>`; severity
   high (`ref_alert_kind`); `data.order_id`, `data.document_id`. An order whose PDF NAPIX does not yet serve
   alerts when the weekly retry stores it, if still within the window. Alternative: alert on `order_found` —
   rejected, the link would be dead for orders NAPIX answers with 628.
9. **Status changed.** From `case_disposed` events (disposal date within the window or unknown) and
   `status_changed` events whose payload contains `status` (pending ↔ disposed ↔ unknown). Changes of purpose,
   bench or last date alone do not alert (they are on the timeline). Key
   `status_changed:<case_id>:<new status>:<disposal_date>`; severity high for a disposal, normal otherwise.
10. **Compliance due (Phase 1 source).** From `case_objections.compliance_by_date` — the court registry's
    date for complying with scrutiny objections, the one court-directed compliance date NAPIX returns. One
    alert per (case, scrutiny date), key `compliance_due:<case_id>:<scrutiny_date>`, raised when the date is
    within 7 days or past; `high`, `critical` from 2 days before and when overdue; done by a user (decision 15)
    or expired 30 days after the date (`ALERT_COMPLIANCE_EXPIRE_DAYS`). Compliance directions written in orders
    ("file affidavit within four weeks") need the order to be read and arrive with SourceTrace (plan §3.2, §5.5);
    the generator accepts them later as `next_dates`-like rows without a schema change (`alerts.data.source`).
    Flagged for the owner.
11. **Request due.** Open `requests` with a `due_date`: within `REQUEST_DUE_SOON_DAYS` (2) → `high`; overdue →
    `critical` (26 Sep decision). One alert per request, key `request_due:<request_id>`, upgraded in place;
    **done** automatically when the request is answered or withdrawn. Recipients: the addressee
    (`to_user_id`) or, when none, users of `to_office_id` holding `requests.answer`. Built now against the
    existing table; it starts producing alerts when `custody-workflow` writes requests.
12. **Recommendation alerts — strong matches of pending cases only.** From `recommendation_made` events whose
    recommendation is still `recommended`, band `high` (≥ the current strong threshold) and case status
    `pending`. One alert per recommendation (`recommendation:<recommendation_id>`), addressed to the
    recommended department, recipients its users holding `cases.claim`; severity high when the case has a
    hearing within 7 days, else normal; **done** automatically when the recommendation is claimed, dismissed,
    suggested elsewhere or expired. Possible matches (medium band) are not alerted one by one: they appear in
    the inbox and as a count in the daily digest. Alternative: an alert per recommendation of any band —
    rejected, the running load would create one alert per case per department. Flagged for the owner.
13. **Two kinds added to `ref_alert_kind` (seed only):** `ownership` (normal; `transfer_requested` high) for
    `allotted` (to the new officer, or the unit's users), `case_taken_over` (to the officer it was taken
    from), `transfer_requested` (to the receiving department's holders of `cases.transfer_decide`) and
    `transfer_decided` (accepted or declined, to the requesting department's holders of
    `cases.transfer_request`); and `new_document` (normal) for `document_uploaded`, to the case's recipients
    who may see that document (`can_view_document`), never the uploader. Both were left to this item by the
    recommend-and-claim and documents-uploads cycles; the backlog line lists the seven existing kinds.
    Key `<kind>:<event_id>`.
14. **Recipients, resolved when the alert is raised (or upgraded), and always filtered by visibility.**
    For case alerts (decision 5's kinds):
    - the **custody holder**: `custody.holder_user_id`; when the custody is with an office and no user, the
      active users of that office holding `alerts.acknowledge` — except a Department-tier office, where only
      its users holding `cases.allot` (the nodal officers: dept admin, dept head) receive;
    - the **primary owner**: the allotted officer; else the allotted unit's users holding
      `alerts.acknowledge`; else the department's users holding `cases.allot`;
    - each **watcher** row: its officer, else that department's users holding `cases.allot`.
    The set is de-duplicated; inactive users, the user whose action caused the event, and anyone for whom
    `visibility.can_view_case` is false are removed (and for `new_document`, anyone for whom
    `can_view_document` is false). Standing counsel are not recipients (the plan's list is owner, custody
    holder and watchers). A department with no such user gets the alert row and no notification; the run's
    counters report `alerts_without_recipients`. Alternative: every user of the owning department — rejected,
    officers would receive the alerts of every colleague's cases.
15. **Alert life cycle.** `open` → `acknowledged` (a user saw it and owns the action) → `done` (action
    complete), or `expired` / `done` by the system (decisions 6, 9–12; informational kinds —
    `next_date_changed`, `new_order`, `status_changed`, `ownership`, `new_document` — expire after
    `ALERT_INFO_EXPIRE_DAYS` (14)). Acknowledge and done are shared by all recipients (one alert per case
    event, not per user) and need `alerts.acknowledge` plus a working relation to the case
    (`visibility.works_on_case`) or being a recipient; each writes an audit row (`alert.acknowledged`,
    `alert.done`, with an optional note of up to 500 characters). System transitions write no audit row (they
    are recorded on the alert: `closed_at`, `data.closed_reason`). No reopening; a new court event raises a new
    alert. Each new alert emits one scoped `alert_raised` event (`alert_raised:<alert_id>`), so the case
    timeline can show it under the existing event allow-list rules.
16. **Notifications: one in-app row per recipient, e-mail by preference.** Raising (or upgrading) an alert
    writes, per recipient, an `in_app` notification (status `sent` at once — the in-app list is the delivery;
    `read` when the user reads it) and, when the preferences allow an immediate e-mail (decision 17), an
    `email` notification `queued`. Keys: `n:<alert_id>:<user_id>:<channel>:<severity>`, so an upgrade to
    critical notifies again and nothing else does. The in-app list is read through the alerts' cases with the
    visibility rule applied at query time, so a user who lost access no longer sees them.
17. **Preferences (self-service, defaults when no row).** `in_app` is always on (it is the record of what the
    user was told; the API refuses `enabled = false` for it). `email`: `enabled` (default **true**), `digest`
    (default **`daily`**), `critical_only` (default false). An immediate e-mail is sent when e-mail is enabled
    and (the severity is `critical`, or `digest = none` and not `critical_only`). The daily digest is sent when
    e-mail is enabled and `digest = daily`. So by default critical alerts are e-mailed at once and everything
    else arrives once a day at 08:00. `sms` is refused (422 `channel_not_available`) until an SMS gateway exists
    (plan Phase 2). Each change writes an audit row (`notification_preferences.changed`, before / after).
    Alternatives: e-mail every alert by default — rejected, the plan names the digest to avoid excessive
    messages; a department-wide setting — not in the plan (§5.11 "notification settings" is met by these plus
    the alert-kind severities editable in `ref_alert_kind`). This item owns the preferences API; `otp-and-profile`
    reuses it (its line "notification preferences" is covered here).
18. **The daily digest at 08:00 IST** for each user whose preferences ask for it: the in-app notifications
    created for the user since the previous digest (or the last 24 hours) that were **not** e-mailed
    immediately, grouped by kind, plus the user's hearings today and in the next 7 days (decision 20's calendar,
    capped at 50 rows with a count), plus the count of open medium-band recommendations of the user's
    department when the user holds `cases.claim`. Nothing to say → no e-mail and no row. One `digests` row per
    (user, date) makes the job idempotent; failure → `failed` with the error, retried by the sender.
19. **Mail delivery through one interface.** `services/mailer.py`: `Mailer` protocol `send(to, subject, text,
    html | None) -> None` raising `MailError`; `MailtrapApiMailer` (HTTPS POST to `MAILTRAP_API_URL` with the
    bearer token, `httpx`, timeout `MAIL_TIMEOUT_SECONDS`), `SmtpMailer` (`smtplib`, STARTTLS when
    `SMTP_STARTTLS`), `ConsoleMailer` (logs the masked recipient and the subject only), `RecordingMailer` for
    tests; `get_mailer(settings)` chooses by `MAIL_BACKEND` exactly as the 27 Sep decision. The sender job sends
    queued e-mail notifications and digests in batches, records `sent_at` or `error` (the exception class and
    message, never the token or the SMTP password), retries a failure up to `NOTIFY_MAX_ATTEMPTS` (3) with
    `next_attempt_at` at 5, 30 and 120 minutes, then leaves it `failed` (listed by `aslms alerts status`; the
    data-health screen of `audit-screens` reads the same rows). **Content rule:** a mail carries the alert
    title, the case number, CNR, court, the date and a link (`PORTAL_BASE_URL` + `/cases/<ref>`), never note
    text, document descriptions or internal document names; `new_document` mails say only the document type.
    Tests never reach the network.
20. **Hearing calendar endpoint.** `GET /calendar?from&to` returns the caller's hearings (decision 6's dates)
    for cases visible through a **working** basis (`owner`, `allotted`, `custody`, `request`, `counsel`),
    each flagged `critical` (within 48 hours) or `this_week`; range at most 62 days. State-wide readers (who
    have no working basis) pass `office=<department code>` to see that department's owned cases' hearings. The
    portal's calendar (`portal-workflow`) and the dashboard (`reports-dashboards`) read it. Alternative: leave
    it to the dashboard item — rejected, the plan's §5.5 module is "Alerts and Hearing Calendar".
21. **No new function.** Reading alerts and the calendar needs `cases.view_scope` or `cases.view_all`
    (`require_any`, as the cases API); acting on an alert needs `alerts.acknowledge`; preferences and marking
    one's own notifications read need only a signed-in user. Reading is not audited (cases-api decision 15).

**Points for the owner to check at approval** (the architect's proposals; none blocks the design): the scope
split of decision 3 and the new backlog row; the compliance source of decision 10; strong-match-only
recommendation alerts (12); the two added kinds (13); recipients without the whole department (14); the
default "critical at once, the rest in the 08:00 digest" (17); the numbers 7 days, 48 hours, 10:30, 14 days,
30 days, 2 days, 3 attempts.

## Data
Migration **0007_alerts** (new; 0001–0006 are applied and not edited). Written by hand like 0005 and 0006 and
checked with `compare_metadata` against the models in `domain/alerts.py`.
- `alerts`: `ADD COLUMN office_id uuid NOT NULL REFERENCES offices(id) ON DELETE RESTRICT` (the office the
  alert is addressed to: the owning department, the recommended department, the request's receiving office,
  the transfer's department; the table is empty, so NOT NULL needs no default), `ADD COLUMN data jsonb NOT
  NULL DEFAULT '{}'`, `ADD COLUMN closed_at timestamptz`, `ADD COLUMN closed_by_user_id uuid NULL REFERENCES
  users(id) ON DELETE SET NULL`. CHECK `ck_alerts_closed`: `(status IN ('done','expired')) = (closed_at IS NOT
  NULL)`; CHECK `ck_alerts_acknowledged`: `status <> 'acknowledged' OR acknowledged_at IS NOT NULL`. Index
  `ix_alerts_case_status` (case_id, status); partial index `ix_alerts_open_kind` (kind, due_at) WHERE status IN
  ('open','acknowledged'); index `ix_alerts_office_id` (office_id).
- `notifications`: `ADD COLUMN severity alert_severity NOT NULL DEFAULT 'normal'` (the severity notified),
  `ADD COLUMN attempts smallint NOT NULL DEFAULT 0`, `ADD COLUMN next_attempt_at timestamptz`. CHECK
  `ck_notifications_read`: `status <> 'read' OR (channel = 'in_app' AND read_at IS NOT NULL)`. Index
  `ix_notifications_user_inbox` (user_id, channel, status); partial index `ix_notifications_outbox`
  (next_attempt_at) WHERE channel = 'email' AND status IN ('queued','failed').
- `digests`: `ADD COLUMN status notification_status NOT NULL DEFAULT 'queued'`, `ADD COLUMN attempts smallint
  NOT NULL DEFAULT 0`, `ADD COLUMN next_attempt_at timestamptz`, `ADD COLUMN error text`, `ADD COLUMN
  item_count integer NOT NULL DEFAULT 0`, `ADD COLUMN body text` (the text sent, for the record).
- No change to `user_notification_preferences`, `next_dates` or `events`. No enum change (the enum types
  `alert_severity` and `notification_status` exist). The tables are empty, so every check holds.
- Downgrade drops the added indexes, checks and columns.

Seed (no migration): `AlertKind` + `ownership`, `new_document`; `seed.ALERT_SEVERITY` gains `ownership:
normal`, `new_document: normal`; labels "Ownership change", "New document". `ref_event_type.alert_raised`
exists.

Paragraphs for `docs/schema/schema.md`, Group 7, replacing the `alerts`, `notifications` and `digests` rows:

> | `alerts` (transaction) | ref_no (unique, `ASLMS/GOA/ALR/<yyyy>/<n>`, allocated only for a new dedupe key), case_id (→ cases RESTRICT), kind (→ `ref_alert_kind`: `hearing_due`, `next_date_changed`, `new_order`, `status_changed`, `compliance_due`, `request_due`, `recommendation`, `ownership`, `new_document`), office_id (→ offices RESTRICT; the office addressed), due_at, severity (`critical` / `high` / `normal`; may only rise), status (`open` / `acknowledged` / `done` / `expired`), title, body, data jsonb (links and dates: `order_id`, `document_id`, `recommendation_id`, `request_id`, `transfer_id`, `hearing_date`, `previous_date`, `source`, `closed_reason`), source_event_id (→ events), dedupe_key (unique, `<kind>:<subject>`), acknowledged_by_user_id, acknowledged_at, closed_at, closed_by_user_id (→ users SET NULL), created_at, updated_at | CHECKs `ck_alerts_closed` (done/expired ⇔ closed_at), `ck_alerts_acknowledged`. Indexes `ix_alerts_case_status`, partial `ix_alerts_open_kind`, `ix_alerts_office_id`. Written by the event scan and the date sweep (design `alerts-notifications`); raised only for cases with an active owner or watcher, except `recommendation`. Never deleted; closed by state. |
> | `notifications` (derived) | alert_id (CASCADE), user_id (CASCADE), channel (`in_app` / `email`; `sms` reserved), status (`queued` / `sent` / `failed` / `read`), severity (the level notified), title, body, attempts, next_attempt_at, sent_at, read_at, error, dedupe_key (unique, `n:<alert>:<user>:<channel>:<severity>`), created_at | CHECK `ck_notifications_read` (`read` only for in-app, with read_at). Indexes `ix_notifications_user_inbox`, partial `ix_notifications_outbox`. In-app rows are `sent` on insert; e-mail rows are sent by the sender job, retried up to 3 times. |
> | `digests` (derived) | user_id (CASCADE), digest_date (unique per user), status (`queued` / `sent` / `failed`), item_count, alert_ids uuid[], body, attempts, next_attempt_at, sent_at, error, created_at | Daily 08:00 IST digest; no row when there is nothing to send. |

`.env.example` (no values for secrets): `MAIL_BACKEND=auto`, `MAILTRAP_API_TOKEN=`, `MAILTRAP_API_URL=` (the
sending or sandbox URL), `SMTP_HOST=`, `SMTP_PORT=587`, `SMTP_USER=`, `SMTP_PASSWORD=`, `SMTP_STARTTLS=true`,
`SMTP_FROM=`, `SMTP_FROM_NAME=ASLMS`, `MAIL_TIMEOUT_SECONDS=20`, `PORTAL_BASE_URL=http://localhost:3000`,
`ALERT_HEARING_LOOKAHEAD_DAYS=7`, `ALERT_CRITICAL_HOURS=48`, `COURT_SITTING_TIME=10:30`,
`ALERT_EVENT_MAX_AGE_DAYS=14`, `ALERT_EVENT_OVERLAP_MINUTES=30`, `ALERT_INFO_EXPIRE_DAYS=14`,
`ALERT_COMPLIANCE_EXPIRE_DAYS=30`, `REQUEST_DUE_SOON_DAYS=2`, `NOTIFY_MAX_ATTEMPTS=3`, `NOTIFY_BATCH=200`.
`MAILTRAP_API_TOKEN` and `SMTP_PASSWORD` are `SecretStr` in `core/config.py`.

## Services
- `services/alert_rules.py` (pure, unit-tested): `severity_for_hearing(due_at, now, critical_hours)`,
  `severity_for_due(due_date, today, soon_days)` (request and compliance), `hearing_due_at(date,
  sitting_time)`, `is_recent(court_date, today, max_age_days)`, `dedupe_key(kind, *parts)`,
  `immediate_email(prefs, severity) -> bool`, `wants_digest(prefs) -> bool`, `effective_preferences(rows) ->
  Prefs` (defaults of decision 17), `render_alert(kind, case, data) -> (title, body)` (title ≤ 300 characters;
  no note or document text), `render_digest(...)`.
- `services/alerts.py`:
  - `raise_alert(session, *, case, kind, key, office, due_at, severity, title, body, data, source_event_id)
    -> tuple[Alert, bool]`: looks the key up (`SELECT … FOR UPDATE`); new → allocate `ALR` on `GOA`, insert in a
    savepoint (a unique race re-reads the winner), emit `alert_raised`, notify; existing and open with a higher
    severity → raise severity, notify again; otherwise nothing. Returns (alert, changed).
  - `close_alert(session, alert, status, reason, actor_user=None)`: sets status, `closed_at`,
    `closed_by_user_id`, `data.closed_reason`; refuses a closed alert.
  - `scan_events(session, *, now=None) -> dict`: decision 2's window; reads events of the handled types
    joined in SQL to "case has an active ownership row" (except `recommendation_made`); per event the rule of
    decisions 7–9, 12, 13; returns counters (`events_read`, `alerts_new`, `alerts_upgraded`,
    `skipped_old`, `skipped_unowned`, `alerts_without_recipients`, `notifications`).
  - `sweep_dates(session, *, now=None) -> dict`: hearing alerts (decision 6, one SQL over owned cases with
    dates in the window), compliance (10), requests (11), and the closures: hearing alerts whose date left the
    case or passed, informational alerts past their age, recommendation alerts whose recommendation is no
    longer `recommended`, request alerts whose request is closed, compliance alerts past the expiry.
  - `acknowledge(session, actor, user, alert, note=None)` / `mark_done(session, actor, user, alert,
    note=None)`: function `alerts.acknowledge`; the user must be a recipient (has a notification) or
    `works_on_case`; the case must be visible (`NotVisibleCase` → 404); `acknowledge` only from `open`
    (else 409 `not_open`), `done` from `open` or `acknowledged`; audit `alert.acknowledged` / `alert.done`
    with before / after and `case_id`. No event (the audit row is the record; the timeline keeps
    `alert_raised`).
  - `list_for_user(session, user, *, status, kind, severity, unread, case_ref, limit, offset)`: the user's
    in-app notifications joined to alerts and filtered by `visibility.visible_case_condition` in SQL; newest
    first; `counts_for_user` (unread, open by severity).
  - `alerts_for_case(session, user, case)`: open and recent alerts of a visible case for callers who work on
    it or read State-wide; others see none (an alert reveals who is responsible).
  - `mark_read(session, user, alert_ids | all)`: own in-app rows only; sets `read`, `read_at`.
- `services/recipients.py`: `case_recipients(session, case, *, exclude_user_id)`, `department_holders(session,
  office, permission)`, `office_users(session, office, permission)`, `for_recommendation`, `for_request`,
  `for_ownership_event`, and the final filter (`is_active`, `can_view_case`, `can_view_document` for
  `new_document`). Function checks use `access.effective_permissions` per user, cached for the run.
- `services/notifications.py`: `notify(session, alert, users, severity)` (decision 16, preferences from
  `effective_preferences`); `send_pending(session, mailer, *, now=None, batch)` (queued and due-for-retry
  e-mail notifications and digests, `FOR UPDATE SKIP LOCKED`, one mail per row, attempts and backoff);
  `build_digests(session, *, today=None)` (decision 18; one row per user per date, `ON CONFLICT DO NOTHING`);
  `get_preferences(session, user)` / `set_preferences(session, actor, user, changes)` (validation of decision
  17, upsert by (user, channel), audit).
- `services/calendar.py`: `hearing_dates_query(...)` shared with the sweep; `calendar_for_user(session, user,
  from_, to, office=None)` (decision 20).
- `services/mailer.py`: decision 19.
- No change to the services that write events: the generators read what they already write
  (`tracking.record_status_change` already puts the old and new values in the payload).

## API
New router `api/routers/alerts.py` (included in `api/main.py`). `{alr}` is an alert id or its `ref_no` in dash
form (`ASLMS-GOA-ALR-2026-000042`); `{ref}` a case as in the cases API. Errors use the existing `{code,
message}` shape.

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /alerts` | `cases.view_scope` or `cases.view_all` | `status` (default open + acknowledged), `kind`, `severity`, `unread`, `case`, `limit` ≤ 200 (50), `offset` | `{items: [{id, ref_no, kind, kind_label, severity, status, title, body, due_at, case: {id, ref_no, cnr, case_no_text}, data, notified_at, read_at, acknowledged_by, acknowledged_at}], total}` | The caller's own in-app notifications; cases filtered by the visibility rule in SQL. |
| `GET /alerts/counts` | same | — | `{unread, open: {critical, high, normal}}` | Same filter. |
| `GET /alerts/{alr}` | same | — | one item plus `recipients_count` | Recipient or `works_on_case`, case visible; else 404. |
| `POST /alerts/{alr}/acknowledge` | `alerts.acknowledge` | `{note?}` (≤ 500) | the item | 409 `not_open`; audited. |
| `POST /alerts/{alr}/done` | `alerts.acknowledge` | `{note?}` | the item | 409 `closed`; audited. |
| `POST /alerts/read` | signed in | `{alert_ids: [...]}` or `{all: true}` | `{marked}` | Own in-app rows only. |
| `GET /cases/{ref}/alerts` | `cases.view_scope` or `cases.view_all` | `status`, `limit`, `offset` | `{items, total}` | Case visible (else 404); items only for callers who work on the case or read State-wide, otherwise an empty list. |
| `GET /calendar` | `cases.view_scope` or `cases.view_all` | `from`, `to` (dates, ≤ 62 days, default today … +7), `office` (State-wide readers) | `{items: [{date, case: {...}, source: causelist / current_status / next_date, court_no, item_no, purpose, critical, this_week}]}` | Decision 20. 422 on a longer range; 403 `office` from a caller without `cases.view_all`. |
| `GET /me/notification-preferences` | signed in | — | `{in_app: {enabled: true}, email: {enabled, digest, critical_only}, sms: {available: false}}` | Own only; defaults when no row. |
| `PUT /me/notification-preferences` | signed in | `{email: {enabled?, digest?, critical_only?}, in_app?: {enabled}}` | same as GET | 422 `in_app_required`, 422 `channel_not_available` for `sms`; audited when something changed. |

## Jobs
Celery tasks in `jobs/celery_app.py` (the Compose `scheduler` service), each writing a `job_runs` row with its
counters; no NAPIX call, no `fetch_queue` kind:
- `aslms.alerts_scan_events` — beat every 5 minutes (`job = alerts_events`, records `window_from`).
- `aslms.alerts_sweep_dates` — beat hourly at minute 10 (`job = alerts_dates`).
- `aslms.notifications_send` — beat every 2 minutes, also dispatched after a scan or sweep that queued e-mail
  (`job = notifications_send`; batch `NOTIFY_BATCH`).
- `aslms.digests_build` — beat daily 08:00 IST (`job = digests`), then dispatches the sender.
CLI `aslms alerts run [--events] [--dates]` (one pass of the generators), `aslms alerts send`, `aslms alerts
digest [--date]`, `aslms alerts status` (open alerts by kind and severity, queued and failed e-mails, last run
of each job), `aslms alerts test-mail --to <address>` (one test message through the configured backend; prints
the backend name, never the token).

## Tests
Unit (`tests/unit/test_alert_rules.py`, `tests/unit/test_mailer.py`):
- hearing severity: 47 h → critical, 49 h → high, past → none; `due_at` at 10:30 IST from a date.
- request and compliance severity: 3 days → none, 2 days → high, today and overdue → critical.
- `is_recent`: 14 days in, 15 out, future dates in; `immediate_email` over the four preference combinations
  plus disabled; defaults with no rows = enabled, daily, not critical-only.
- `render_alert` titles ≤ 300 characters and contain no document description for `new_document`.
- `get_mailer`: `auto` with a token → API, with SMTP only → SMTP, nothing → console; `MailtrapApiMailer`
  against an `httpx.MockTransport` sends the bearer header, maps a 4xx / 5xx to `MailError` whose message
  does not contain the token; `ConsoleMailer` logs no body.
DB (`tests/db/test_alerts_generate.py`, `test_alert_recipients.py`, `test_notifications.py`,
`test_api_alerts.py`, using `tests/db/world.py`):
- the event scan's first run ignores events older than the overlap; a second run in the overlap creates no
  duplicate; an event committed "late" inside the overlap is processed.
- `order_stored` of a claimed case with a recent order → one `new_order` alert, one in-app notification per
  recipient; an order of 2025 → none (`skipped_old`); an unclaimed case → none (`skipped_unowned`).
- `next_date_changed` with old and new dates → alert; first date only → none; new date in the past → none.
- `status_changed` without `status` in the payload → none; `case_disposed` recent → high alert.
- hearing: next date in 3 days → high; the sweep at 46 hours before → same alert upgraded to critical and a
  second notification per recipient; date changed → the old alert expired; listing in tomorrow's cause list
  without a next date → alert with source causelist.
- compliance from `case_objections.compliance_by_date`; request due soon → high, overdue → critical, answered
  → done.
- recommendation: high band, pending case → alert to the department's `cases.claim` holders only; medium band
  → none; claimed afterwards → the sweep closes it `done`.
- ownership: allotment notifies the new officer; take-over notifies the previous officer, not the taker;
  transfer request notifies the receiving department's deciders.
- `new_document`: a `private_to_office` upload notifies no one outside the office; the uploader is never
  notified.
- recipients: allotted officer + custody holder; no officer → unit users; neither → department nodal users;
  watcher department included; an inactive user and a user who cannot see the case are excluded.
- ref numbers: a re-run allocates no `ALR` serial for an existing key.
- notifications: default preferences → critical e-mailed now, high only in the digest; `digest = none` →
  immediate; `critical_only` → only critical; e-mail disabled → in-app only; the sender marks `sent` with the
  recording mailer; a failing mailer → attempts 1, 2, 3 with backoff, then `failed`; the error text never holds
  the token.
- digest: built once per user per day (a second run adds nothing); nothing new → no row; contents exclude
  e-mailed alerts; upcoming hearings listed.
- API: `GET /alerts` 401 without a token; lists only own notifications; a case whose visibility was lost
  disappears from the list; `acknowledge` by a non-recipient officer of another department → 404; by a
  referral reviewer without a working basis → 404; by a recipient without `alerts.acknowledge` (override deny)
  → 403; acknowledge writes one audit row; acknowledge twice → 409; `POST /alerts/read` touches only own rows;
  `/calendar` > 62 days → 422, State reader without `office` → empty, with `office` → that department's
  hearings; preferences GET defaults, PUT `sms` → 422, PUT `in_app.enabled=false` → 422, PUT change → audit
  row with before and after.
- migration: upgrade → downgrade → upgrade including 0007; `compare_metadata` empty; schema metadata test
  updated for the new columns and checks.

## Verification
With Compose up (`docker compose up -d`; `NAPIX_ENABLED` stays off — no NAPIX call is needed):
1. `docker compose run --rm init` applies 0007 and seeds; `aslms alerts status` shows nine alert kinds and no
   alerts.
2. `pytest -q` green; `ruff check` clean.
3. With the loaded January 2025 data: claim three cases through the API as a department admin of a test
   department and allot one to an officer; give that case a hearing tomorrow by inserting a `next_dates` row
   of source `manual` (review status `not_needed`) with `psql` in the dev database (no NAPIX call).
   `aslms alerts run --dates` → one `hearing_due` alert, critical, with notifications for the officer (owner
   and custody holder) only; the department admin receives none.
4. `aslms alerts run --events` on the running load → `skipped_old` large, `alerts_new` 0 for 2025 orders (the
   load must not raise alerts); record the counters in the cycle report.
5. `aslms alerts test-mail --to <owner's Mailtrap sandbox address>` with the sandbox URL in `.env` → one
   message in the Mailtrap sandbox inbox; `aslms alerts send` delivers the critical alert's e-mail; `aslms
   alerts digest` builds the officer's digest (the high alerts) and the sender delivers it to the sandbox.
6. `GET /alerts`, `/alerts/counts`, `POST /alerts/{alr}/acknowledge`, `GET /calendar` as the officer; the
   audit log holds `alert.acknowledged`; the same calls as an officer of another department show nothing and
   answer 404 on the alert.
7. `docker compose logs scheduler` shows the four beat entries running and no token or password in the log.

## Open questions
None. The proposals the owner should confirm are listed at the end of "Decisions"; the proposed backlog row
`next-date-extraction` (decision 3) is added to `docs/backlog.md` as `todo`.

## Deviations
Written by the developer while building (2026-10-06); each is the smallest option where the design was silent
or two of its decisions met.
1. **Ownership notices to a recipient who cannot see the case.** Decision 13 names the officer a case was
   taken from (`case_taken_over`), the department asked to take it (`transfer_requested`) and the department
   told of the decision (`transfer_decided`) as recipients; decision 14's filter removes anyone for whom
   `can_view_case` is false — and none of those three can see the case (the previous officer lost the
   allotment basis; the receiving department has no basis before it accepts; the requesting department loses
   ownership on acceptance). Taken literally, the three notices would never be delivered. These three events
   (`services/recipients.py::NAMED_RECIPIENT_EVENTS`) skip the case-visibility filter (inactive users, the
   actor and standing counsel are still removed), and the readers (`GET /alerts`, `/alerts/counts`,
   `/alerts/{alr}`, acknowledge / done, the digest) admit a user's own notification of such a notice although
   the case is not visible (`alerts.notification_visible_condition`). The notice carries the case number the
   recipient already knew, nothing else of the case. Every other kind keeps decision 14 as written.
2. **The in-app list shows one row per alert, not per notification.** An upgrade to critical writes a
   second in-app row (decision 16); `GET /alerts` lists the alert once with its latest notification's
   `notified_at` and `read_at` (DISTINCT ON the alert), so the bell does not show the same hearing twice.
   `counts.unread` counts alerts whose latest notification is unread; `counts.open` counts alerts in `open`
   or `acknowledged` (the default list's states).
3. **`alert_raised` on the timeline through the department rule.** The event's payload carries
   `office_code` (the office addressed) and the type joins `case_detail.DEPARTMENT_EVENTS`, so the
   department named sees it and State-wide readers see all, under the existing allow-list.
4. **Compliance severity uses a window of 7 days and a critical band of 2 days** (`severity_for_compliance`);
   the request rule (`severity_for_due`) keeps "within 2 days → high, today and overdue → critical". One
   alert per (case, scrutiny date); when several objection blocks share a scrutiny date the first one's
   compliance date is used.
5. **Request alerts do not repeat the request's subject.** The body names the request kind and the sending
   office (a subject may hold internal wording; decision 19's content rule applies to the mail, and the alert
   body is copied into the mail).
6. **The sender's message for a single alert** is the alert title, the case number, CNR, court, the due date
   (IST) and the portal link, as decision 19 lists; the subject is `[ASLMS <SEVERITY>] <title>`. The digest's
   subject is `ASLMS daily digest - <date>`; its text is stored in `digests.body`.
7. **The digest's "since the previous digest"** is the previous digest row's `created_at` for that user
   (whatever its date) or, with none, the last 24 hours; the medium-band count is included only for holders of
   `cases.claim` with a department. A user with only upcoming hearings still gets a digest (decision 18 lists
   the hearings as content).
8. **`get_mailer` refuses `api` and `smtp` without `SMTP_FROM`** (the sender address serves every backend;
   the design lists no separate variable) and raises `MailError` for an unknown backend; `auto` falls back to
   the console as the decision says. `test-mail` prints the backend name and the masked recipient only.
9. **Migration 0007 was written as a new file after the autogenerated scaffold was removed** (as 0006 was: the
   repository guard treats every file under `versions/` as applied). Autogenerate produced `sa.Enum(...)` for
   the two enum columns (which would try to create the types again) and could not see the CHECKs; the
   reviewed revision uses `postgresql.ENUM(..., create_type=False)` and adds the three CHECKs by hand. The
   `uuid_fk` helper gives `closed_by_user_id` an index (`ix_alerts_closed_by_user_id`), not listed in "Data".
10. **The pre-existing 0006 cycle test asserted the literal head `0006`**; it now compares with the script
    directory's head so later migrations do not break it.
11. **Each event is handled in its own savepoint**; an event whose handler raises is counted in `errors`, logged
    and skipped, and the run is recorded `partial` rather than lost. `scan_events` and `sweep_dates` take an
    `AlertConfig` (the design's numbers as defaults; built from `Settings` in the jobs and the CLI) and an
    optional `now`, so the tests drive time without patching.
12. **A `new_document` alert is read only with its document** (review of 2026-10-06, blocking). Decision 14
    limited the *recipients* of a `new_document` alert to users who can see the document; three other reads
    skipped that check and returned the document's id, type, uploading office and the title "New <type>
    uploaded": `GET /cases/{ref}/alerts`, `GET /alerts/{alr}` for a caller who works on the case, and the
    timeline's `alert_raised` row. The per-document rule (`documents-uploads`, decision 7) now applies to every
    read of an alert: `visibility.alert_document_condition` (over `alerts`: any kind but `new_document` passes;
    a `new_document` alert passes only when `data.document_id` names a document visible to the caller under
    `document_visible_condition`; a missing or unknown id hides the alert) is ANDed into
    `alerts.notification_visible_condition` (the in-app list, counts, the digest), `alerts_for_case`, and the
    timeline's department rule for `alert_raised` rows (joined through the alert the row names);
    `visibility.can_view_alert_document` gates `_may_act_on` (`GET /alerts/{alr}`, acknowledge, done). A user
    notified of a document that later stops being visible to them loses the notification from the list too.
    No event payload changed. The finding's aside that State-wide readers were also affected does not hold:
    under `documents-uploads` decision 7 they see every document, private ones included, so they see the
    alert too; the test uses the auditor as a positive control.
13. **An alert is read and acted on only by the office it is addressed to** (review of 2026-10-06, blocking).
    `GET /cases/{ref}/alerts` listed, and `GET /alerts/{alr}`, acknowledge and done accepted, every alert of a
    case for anyone who works on it, whatever `alerts.office_id`: a HEALTH officer of a claimed case saw
    "Strong match for EDU" with its score (the `recommendation` alert addressed to EDU, which the timeline
    hides from HEALTH) and could close it for every EDU claimer; `transfer_requested` notices addressed to
    the receiving department were read the same way. The office addressed now gates every read:
    `visibility.alert_office_condition` (over `alerts`: a State-wide reader passes all; anyone else passes an
    alert addressed to an office of their own department — the department or any office under it, the
    smallest reading of the Department tier — or one they were themselves notified of) is ANDed into
    `alerts_for_case`; `visibility.addressed_to_department` gates `_may_act_on` (`GET /alerts/{alr}`,
    acknowledge, done): a recipient acts as before; a non-recipient must both work on the case and belong
    to the department addressed (or read State-wide). `GET /alerts` and `/alerts/counts` were already the
    caller's own notifications and are unchanged. The case tab's "work on it or read State-wide" gate
    stays: a recipient who does not work on the case (the EDU admin of the recommendation) still reads the
    alert by reference and in their own list, not in the case tab.
