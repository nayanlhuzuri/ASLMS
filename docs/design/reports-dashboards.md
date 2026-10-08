# Design: Dashboards per type (State, department, officer) and the department and State reports

```
slug: reports-dashboards
status: approved
author: architect
date: 2026-10-08
approved_by: owner (nayanlhuzuri) on 2026-10-08
```

## Context
Plan §5.1 (Dashboard): "The first screen after login, showing each user what needs their attention. Its
content depends on the user's role." State oversight: case counts by department, upcoming hearings across the
State, overdue actions and compliance status. Department: new recommendations awaiting review, hearings this
week, cases with pending action, and cases in custody of each office. Officer: own cases, own pending actions
and own alerts. Data: the portal database only (cases, alerts, custody), "no direct API calls; data is kept
current by the daily cycle". Annexure B ("Department dashboard"): counts of recommended cases, upcoming
hearings and pending actions; upcoming hearings with those within 48 hours marked; items needing attention,
including next dates read from new orders.

Plan §5.10 (Reports): management information for departments and State oversight: pending cases by
department, court and age; hearings and disposals over a period; pending actions and overdue compliance by
office; data collection health (status of the daily data cycle, failed API calls and SourceTrace ingestions).
Portal database; "Reports can be exported to Excel and PDF". Phasing (§9): the dashboard is Phase 1, reports
Phase 2. Table 1: State oversight has "State-level dashboards and reports". Backlog row 9.

In place today (nothing is rebuilt; this item reads it):
- Functions `dashboard.state`, `reports.state`, `reports.department` (seeded since migration 0003; labels in
  `services/access_seed.py`). Default matrix: `state_oversight` holds all three; `central_operator` holds
  `reports.state`; `dept_head` and `dept_admin` hold `reports.department`. Nothing checks them yet.
- `services/inbox.py::counts` (recommended high / medium, claimed active / disposed, open incoming transfers,
  pool cases with a hearing in 7 days, per department, each under its tab's function) and `claimed_stmt`.
- `services/calendar.py` (`hearing_rows` over cause-list listings, `cases.next_hearing_date` and confirmed next
  dates; `flags` → `critical` within 48 hours, `this_week` within 7 days; `department_owned_condition`).
- `services/custody.py` (`held` with scopes `me` / `office` / `owned`, `summary` per tracked department with
  counts by holder department and holder office/officer; `custody.track` gates the `owned` views,
  custody-workflow decision 24a).
- `services/alerts.py` (`counts_for_user`, `list_for_user`; `compliance_due` alerts from scrutiny
  `compliance_by_date`, open until done or expired).
- `services/visibility.py` (`visible_case_condition`, `state_wide`, `whole_department`, `WORKING_BASES`).
- Operations tables: `fetch_queue` (`causelist_day`, `status_batch`, `dossier`, `order_pdf` rows),
  `causelists`, `napix_call_log`, `source_failures`, `job_runs`, `documents.sourcetrace_status`,
  `sourcetrace_ingestions`; `services/sourcetrace_ingest.py::status`.
- DB_STANDARD §12.1 names `services/dashboard.py` and `services/reports.py`; §8 lists `aslms_readonly` for
  "Grafana, reports, State-tier dashboards".

Not covered: the portal screens (dashboard in `portal-shell`, row 11; the reports screen is proposed as a new
row under "Left for later"); the live data-health screen with queue depths, quota and the re-fetch / sync
buttons and `/admin/napix/health` (`audit-screens`, row 10, which reads the same tables; this item builds the
period report and its export); next dates read from order text (row 26; the dashboard section that shows them
is built here and stays empty until row 26 writes such rows); historical "as of a past date" reports and
trends (no snapshot table, decision 4); scheduled or e-mailed reports.

## Decisions
1. **Dashboards are composed by function and membership, not by user type.** A signed-in user gets the
   *personal* block always; a *department* block for each department where one of their memberships holds
   `cases.claim`, `cases.allot`, `custody.track` or `reports.department`; the *State* block when they hold
   `dashboard.state`. With the default matrix this gives exactly the plan's three dashboards: State oversight →
   State; department head and admin → department; officer, directorate user, standing counsel, referral
   reviewer → personal. A person with several memberships sees one department block per department (one login,
   several offices, user-memberships). Alternative: one dashboard per `users.role` — rejected: authority lives in
   memberships, and user-memberships decided that no rule is addressed to a type as such ("functions, not the
   head type"). The super admin holds every function and sees the State block and the personal block, and any
   department through `?department=` (decision 3).
2. **Every count is computed live in SQL from the tables the workflow already writes; nothing new is stored.**
   Dashboards reuse the existing queries (`inbox` counts, `calendar.hearing_rows`, `custody.held` / `summary`,
   `alerts.counts_for_user` / `list_for_user`) so a number on the dashboard equals the number on the screen it
   links to. Alternative: a nightly `dashboard_snapshots` table — rejected for now: the data changes all day
   (claims, sends, alerts every 5 minutes) and ~100,000 cases aggregate in well under a second with the
   existing indexes plus two added (Data). Each dashboard and report query runs with `SET LOCAL
   statement_timeout` (`REPORT_STATEMENT_TIMEOUT_SECONDS`, 30) so a heavy report cannot hold the database.
3. **Three dashboard endpoints and an index.** `GET /dashboard` says which blocks the caller has (cheap);
   `GET /dashboard/me`, `GET /dashboard/department?department=CODE`, `GET /dashboard/state` return the blocks,
   so the portal loads them in parallel. A `dashboard.state` holder may open any department's block with
   `?department=` (the State view of one department, as `/calendar?office=` does for State-wide readers);
   anyone else only a department of their own memberships (403 otherwise). Without `department` and with
   several eligible departments the endpoint answers 400 `department_required` with the candidate codes (the
   inbox's `OfficeRequired` pattern). Alternative: one `/dashboard` returning everything — rejected: one slow
   section would delay the whole first screen.
4. **Reports are "as of now" for stock measures and dated facts for period measures; no snapshots.** Pending
   cases, pending actions and compliance are counted as they stand at the request; hearings and disposals are
   counted from dated rows within the requested period. A case is attributed to its **current** active primary
   owner (a transferred case counts for the department that owns it now). Alternative: monthly snapshot tables
   for "pending as of 31 March" and trends — deferred ("Left for later"); the plan asks for neither.
5. **The report catalogue (plan §5.10), four reports:**
   - **`pending-cases`** — non-merged cases with status `pending` or `unknown` (the inbox's "Active"; `unknown`
     shown as its own column), counted by group × court × age band. Group: in a State report the owning
     department (primary owner), plus the rows "Not claimed — recommended" (an active recommendation exists) and
     "Not claimed — no recommendation" (never had a primary owner); in a department report the unit the case
     is allotted to (`case_ownership.unit_office_id`; "Department office / not allotted" otherwise). Watched
     cases are a separate `watching` column, never double-counted as owned. Court: `courts.est_code` and name
     (GAHC01–GAHC04). Age: today (IST) minus `registration_date`, else `filing_date`, else `date_first_list`;
     "Age not known" otherwise. Provisional cases are included and counted in a `provisional` column.
   - **`hearings-disposals`** — for `from`..`to` (at most `REPORT_MAX_RANGE_DAYS`, 366): per group,
     `listings` (distinct case and date in a cause list of the period — the court's published listing,
     complete for every loaded day), `proceedings` (distinct case and `case_hearings.business_date` in the
     period, from dossiers; shown separately because a dossier may lag the list), `cases_heard` (distinct cases
     listed), `disposed` (`cases.disposal_date` in the period, status `disposed`), and a second section by
     calendar month over the same columns. Same grouping as `pending-cases`.
   - **`pending-actions`** — files of the scope's owned cases with `custody.pending_action <> 'none'`, grouped
     by holder department, holder office and holder officer (name and designation from the current leg's
     snapshot): `held`, `due_soon` (due within `REQUEST_DUE_SOON_DAYS`), `overdue` (due date before today),
     `no_due_date`, `oldest_since`, `max_overdue_days`. Second section, **overdue compliance by office**: open
     or acknowledged `compliance_due` alerts on the scope's owned cases grouped by the addressed office
     (`alerts.office_id`), `due_soon` and `overdue` (`data.compliance_by_date` before today). Optional third
     section (`include_cases=true`): one row per file (case number, CNR, `ref_no`, holder office, officer,
     pending action label, since, due date, overdue days), filtered by the caller's case visibility. Never the
     custody remark, a note or a document.
   - **`data-health`** — for `from`..`to` (at most `REPORT_HEALTH_MAX_DAYS`, 92), one row per date: the
     `causelist_day` queue row's status and attempts, lists stored and entries parsed (`causelists` of that
     list date, `parse_status = failed` count), `status_batch` rows done / failed for that date, NAPIX calls
     made that day (IST) total / failed / by error family, dossier and order-PDF queue rows finished that day
     done / failed, SourceTrace attempts that day ok / failed. Further sections: NAPIX calls in the period by API
     (total, failed, median duration); open `source_failures` by kind (count, oldest `first_seen`); SourceTrace
     status now (`sourcetrace_ingest.status`: connector state and counts by status). Counts only. A note in the
     report states that `napix_call_log` rows exist only from the first live call and until the retention
     pruning, when one is introduced.
   Alternative: let each department configure its own reports — rejected: not in the plan; the four cover its
   three bullets exactly.
6. **Age bands follow the national judicial data grid (NJDG):** up to 1 year, 1–3, 3–5, 5–10, 10–20, 20–30,
   over 30 years, plus "Age not known". Alternative: free bands from query parameters — rejected: reports from
   different departments would not compare. The bands are a constant in `services/reports.py`, a proposal the
   owner may change at approval (the plan names "age" without bands).
7. **Who may run which report.** Department scope (`department=CODE`): a membership in that department holding
   `reports.department`, or any `reports.state` holder. State scope (no `department`): `reports.state`.
   Without `department`, a caller without `reports.state` gets their single `reports.department` department, or
   400 `department_required` with candidates when there are several; 403 when they hold neither function.
   `data-health` is State scope only (`reports.state`): it describes the whole system's collection, not a
   department. Alternative: a separate `reports.export` function — rejected: the plan attaches export to
   reports, not to a role; holding the report function is enough to export it.
8. **Aggregates follow the function; case rows follow visibility.** A report's counts cover the scope the
   function grants (a department, or the State) and carry no case text. Every row that names a case (the
   `include_cases` section, the dashboard lists of hearings, files and next dates) is additionally ANDed with
   `visible_case_condition` of the caller, so a report never shows a case the caller could not open.
   Alternative: filter the aggregates by visibility too — rejected: a `reports.department` holder below the
   department office (granted by the department admin) would get partial, misleading totals; the counts are
   the management information the grant is for, as `custody.summary` already does for `custody.track`.
9. **Department dashboard sections and their gates.** Within a department block (eligibility per decision 1):
   - *recommendations* (high, medium, open incoming transfers): `cases.claim` in that department or
     `dashboard.state` — exactly `inbox.counts`; `null` otherwise.
   - *cases* (claimed active, claimed disposed, watching, active not allotted to an officer or unit): every
     eligible membership.
   - *hearings* (next 7 days of the department's owned cases: total, critical within 48 hours, list of the
     first `DASHBOARD_LIST_SIZE` with the critical ones first): every eligible membership; the list is filtered
     by visibility (decision 8).
   - *pending actions* (owned files with a pending action: held, due soon, overdue, no due date) and *custody by
     office* (owned files by holder department and holder office: held, with pending action, overdue):
     `custody.track` or `reports.department` in that department, or `dashboard.state` — the owner's rule of
     7 Oct 2026 makes "pending and overdue files of the department wherever held" a granted function, and the
     management-report function is the other grant that already exposes the same counts (decision 7); `null`
     otherwise. The list of the first overdue files appears only with `custody.track` (it is `custody.held`
     `scope=owned`) or `dashboard.state`.
   - *attention*: next dates awaiting review on owned cases (`next_dates.needs_review` and `review_status`
     pending; needs `next_dates.review`, else `null`), next dates read from orders in the last 7 days on owned
     cases (sources `order_specific`, `order_period`; empty until row 26), compliance due soon and overdue (open
     `compliance_due` alerts on owned cases).
   Alternative: show everything to every department-wide member — rejected: it would bypass `custody.track`,
   which the owner made grantable.
10. **Personal block** (`GET /dashboard/me`), for every caller with `cases.view_scope` or `cases.view_all`:
    *own cases* per department membership — allotted to the person or (for a membership below the department)
    to their unit, active and disposed (`inbox.claimed_stmt(..., whole=False)`), and for a standing-counsel
    membership the active cases visible through the `counsel` basis; *files held* by the person
    (`custody.held(scope="me")`: total, with pending action, overdue, the first `DASHBOARD_LIST_SIZE` by due
    date); *own alerts* (`alerts.counts_for_user` and the newest open ones through `list_for_user`); *own
    hearings* (the caller's working-basis calendar for the next 7 days: total, critical, first
    `DASHBOARD_LIST_SIZE`); *drafts* (count of the person's open note drafts). State-wide readers without a
    working basis get zeros, as the calendar already does.
11. **State block** (`GET /dashboard/state`, `dashboard.state`): *by department* — one row per active
    Department-tier office (and any inactive one that still owns cases): claimed active, claimed disposed,
    recommended high, recommended medium, hearings in the next 7 days, files with pending action, overdue
    files, compliance due soon, compliance overdue; plus one *not claimed* row (active never-owned cases, of
    which recommended, of which with a hearing in 7 days) for the central operator's follow-up; *hearings*
    across the State (owned cases, next 7 days: total, critical, the first `DASHBOARD_LIST_SIZE` nearest);
    *overdue actions* (overdue files by owning department and by holder department); *compliance* (totals of
    open `compliance_due` alerts due soon and overdue). Counts only, apart from the hearings list (filtered by
    visibility; `dashboard.state` holders normally hold `cases.view_all`).
12. **Exports: Excel through XlsxWriter, PDF through PyMuPDF.** Every report endpoint takes `format=json`
    (default), `xlsx` or `pdf` and returns the same content: a header (report title, scope, parameters,
    "generated at" in IST, generated by — name, designation, office of the acting membership — and the
    as-of note of decision 4), one worksheet or PDF table per section, totals rows. XlsxWriter (BSD, write-only,
    `constant_memory` mode) is a new dependency; PyMuPDF is already one (`fitz.Story` from simple HTML, A4
    landscape, repeated table headers, page numbers). Case-row sections are capped at `REPORT_XLSX_MAX_ROWS`
    (5,000) and `REPORT_PDF_MAX_ROWS` (1,000); a capped file says "first N of M rows". Files are built in memory
    and streamed with `Content-Disposition: attachment; filename="aslms-<report>-<scope>-<yyyymmdd-hhmm>.<ext>"`
    and `Cache-Control: no-store`; nothing is written to the document store. Alternatives: openpyxl (heavier,
    read-write, not needed), ReportLab or WeasyPrint for PDF (a second PDF library, or system libraries in the
    image) — rejected; CSV — rejected, the plan says Excel.
13. **Audit: exports are audited; views are not.** Each xlsx or pdf export writes `report.exported`
    (entity_type `report`, entity_id NULL, `after` = `{report, scope, department, params, format, rows,
    truncated}`), because a file with case data leaves the portal (as downloads of uploaded documents are
    audited, documents-uploads). Reading a dashboard or a JSON report writes nothing (cases-api decision 15:
    reading is not audited).
14. **The API reads through `aslms_app`, not `aslms_readonly`.** The reports need the server-side visibility
    rule and write the export audit row, both of which live in the application; `aslms_readonly` stays for
    Grafana and ad-hoc SQL as DB_STANDARD §8 lists. Report and dashboard services only SELECT (a test enforces
    that no report builder flushes changes); the export audit row is written by the router after the file is
    built. Alternative: a second engine on `aslms_readonly` — rejected: a second connection string and pool
    for no gain in protection, since the visibility rule is application logic.
15. **No new function, no new table; one migration for two indexes.** The three existing functions are used as
    seeded; the default matrix is unchanged (the owner may give `dashboard.state` to the central operator
    from the type matrix if wanted). Migration 0012 adds `ix_cases_disposal_date` and
    `ix_case_hearings_business_date` for the period report (Data).
16. **CLI for the integrator and for scheduled use outside the portal.** `aslms reports run <report>
    [--department CODE] [--from D --to D] [--format json|xlsx|pdf] [--out PATH]` acting as the `.env` super
    admin (as the other CLIs), audited on xlsx / pdf like the API; `aslms reports dashboard [--department CODE]
    [--state]` prints the block counts.

## Data
No new table or column; no `ref_*` code, enum value or `Permission` added. Migration **0012_report_indexes**
(new file; applied migrations are never edited), indexes only, downgrade drops them:

- `cases`: index **`ix_cases_disposal_date`** on (`disposal_date`) `WHERE disposal_date IS NOT NULL` — the
  disposals of a period (`hearings-disposals`).
- `case_hearings`: index **`ix_case_hearings_business_date`** on (`business_date`) — the proceedings of a
  period. (The unique key (case_id, business_date, purpose) leads with `case_id` and does not serve a date
  range.)

Paragraph for `docs/schema/schema.md` (Group 3, after the `case_snapshots` row note):

> Reporting indexes (reports-dashboards, migration 0012, no table or column): partial index
> `ix_cases_disposal_date` (disposal_date) WHERE disposal_date IS NOT NULL; index
> `ix_case_hearings_business_date` (business_date). Dashboards and reports (`services/dashboard.py`,
> `services/reports.py`) only read; they store nothing. Export files are streamed, never kept in `documents`.

Conventions line in `schema.md` gains: "Report exports write one `audit_log` row (`report.exported`)."

## Services
`backend/aslms/services/reporting_common.py` (new, small):
- `today_ist()`, `ReportConfig.from_settings` (`max_range_days`, `health_max_days`, `xlsx_max_rows`,
  `pdf_max_rows`, `statement_timeout_seconds`, `list_size`, `due_soon_days` = `REQUEST_DUE_SOON_DAYS`).
- `with_timeout(session, seconds)` — `SET LOCAL statement_timeout`.
- `department_rows(session)` — active Department-tier offices plus inactive ones owning cases, ordered by
  name.
- `primary_owner_subquery()` — (case_id, office_id, unit_office_id) of active primary rows.
- `age_band_expr(today)` — the SQL `CASE` of decision 6 over `coalesce(registration_date, filing_date,
  date_first_list)`; `AGE_BANDS` constant.

`backend/aslms/services/dashboard.py` (new):
- `available(session, user) -> dict` — decision 3's index: `{me: bool, departments: [{code, name}],
  state: bool}`.
- `eligible_departments(session, user) -> list[Office]` — decision 1.
- `resolve_department(session, user, code | None) -> (Office, Member | None)` — decision 3; raises
  `DepartmentRequired(candidates)` (400), `Forbidden` (403), `BadDepartment` (400 for an unknown or non-
  department code).
- `me_block(session, user, *, now=None) -> dict` — decision 10.
- `department_block(session, user, department, *, now=None) -> dict` — decision 9; each section is `null` when
  its gate fails.
- `state_block(session, user, *, now=None) -> dict` — decision 11; `access.require(dashboard.state)`.
- Reuses `inbox.counts` / `inbox.claimed_stmt`, `calendar.hearing_rows` / `flags` /
  `department_owned_condition` / `owned_case_condition` / `working_condition`, `custody.held` /
  `custody.summary` logic (the summary loop is factored into `custody.summary_for(session, departments)` so
  that the department block and the reports call it without the `custody.track` check; `custody.summary`
  keeps its check and calls it), `alerts.counts_for_user` / `list_for_user`, `visibility.visible_case_condition`.
- No writes, no audit, no events.

`backend/aslms/services/reports.py` (new):
- Value types: `Column(key, label, kind)` with kind `text` / `int` / `date` / `days`; `Section(key, title,
  columns, rows, totals | None, note | None, total_rows, truncated)`; `Report(key, title, scope
  ("state" | "department"), department_code, params, generated_at, generated_by, as_of_note, sections)`.
- `CATALOGUE` — the four keys with titles, the parameters each takes and the scopes allowed (decision 5).
- `resolve_scope(session, user, report_key, department_code) -> Scope` — decision 7 (403, 400
  `department_required` with candidates, 400 `bad_department`).
- `check_period(from_, to, max_days)` — `to` not before `from`, range limit, no future `from` (422).
- `pending_cases(session, user, scope, *, today=None) -> Report`.
- `hearings_disposals(session, user, scope, *, from_, to) -> Report`.
- `pending_actions(session, user, scope, *, holder_department=None, include_cases=False, row_cap=None) ->
  Report` — the case-row section uses `visible_case_condition` and `row_cap`.
- `data_health(session, user, *, from_, to) -> Report` — State scope only.
- `catalogue_for(session, user) -> list[dict]` — the reports the caller may run and their scopes.
- Every builder calls `with_timeout` first, only SELECTs, and never reads `custody_history.remark`,
  `case_notes`, `case_note_drafts` or document descriptions.

`backend/aslms/services/report_export.py` (new):
- `to_xlsx(report) -> bytes` — XlsxWriter, `constant_memory`, header block, one sheet per section (sheet names
  ≤ 31 characters), dates as Excel dates, column widths, totals in bold, frozen header row.
- `to_pdf(report) -> bytes` — PyMuPDF `fitz.Story`, A4 landscape, header on page 1, repeated table headers,
  "Page n of m", "first N of M rows" note on capped sections. HTML is built with every value escaped.
- `filename(report, ext, now) -> str` — decision 12.
- `audit_export(session, actor, report, fmt) -> None` — decision 13 (`services/audit.write_audit`).

Settings (`core/config.py`, `.env.example`, no secrets): `REPORT_MAX_RANGE_DAYS=366`,
`REPORT_HEALTH_MAX_DAYS=92`, `REPORT_XLSX_MAX_ROWS=5000`, `REPORT_PDF_MAX_ROWS=1000`,
`REPORT_STATEMENT_TIMEOUT_SECONDS=30`, `DASHBOARD_LIST_SIZE=10` (bounds: rows 1–50,000; list 1–50; days 1–1,000;
timeout 1–300). `pyproject.toml` gains `xlsxwriter>=3.2`.

## API
New routers `api/routers/dashboard.py` and `api/routers/reports.py`; errors `{code, message}` as elsewhere;
dates in IST; department codes as in `/admin/offices`. Case references in lists are
`{id, ref_no, cnr, case_no_text}` (the calendar's `case_ref`).

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /dashboard` | `cases.view_scope` or `cases.view_all` (`require_any`) | — | `{me: true, departments: [{code, name}], state: bool}` | Decision 3. |
| `GET /dashboard/me` | `cases.view_scope` or `cases.view_all` | — | `{generated_at, cases: [{department_code, allotted_active, allotted_disposed, counsel_active?}], files: {held, with_pending_action, overdue, items: [{case, pending_action, since, due_date, overdue_days, holder_office_code}]}, alerts: {unread, open: {critical, high, normal}, items: [alert summary]}, hearings: {total, critical, items: [{date, case, court_no, item_no, critical}]}, drafts: int}` | Decision 10; lists are the caller's own or working cases. |
| `GET /dashboard/department?department=CODE` | `cases.view_scope` or `cases.view_all`, then decision 1 / 3 eligibility (403) | `department` optional | `{generated_at, department: {code, name}, recommendations: {high, medium, transfers_in_open} \| null, cases: {claimed_active, claimed_disposed, watching_active, not_allotted_active}, hearings: {total, critical, items: [...]}, pending_actions: {held, due_soon, overdue, no_due_date, items?: [...]} \| null, custody_by_office: [{holder_department_code, office_code, office_name, held, with_pending_action, overdue}] \| null, attention: {next_dates_to_review \| null, recent_order_next_dates: [{case, next_date, source, review_status}], compliance_due_soon, compliance_overdue}}` | Decision 9; 400 `department_required` `{candidates}`; 400 `bad_department`. |
| `GET /dashboard/state` | `dashboard.state` | — | `{generated_at, by_department: [{code, name, is_active, claimed_active, claimed_disposed, recommended_high, recommended_medium, hearings_7d, pending_actions, overdue_actions, compliance_due_soon, compliance_overdue}], not_claimed: {active, recommended, hearing_7d}, hearings: {total, critical, items}, overdue_actions: {total, by_owner: [{code, overdue}], by_holder: [{code, overdue}]}, compliance: {due_soon, overdue}}` | Decision 11. |
| `GET /reports` | `reports.department` or `reports.state` | — | `{reports: [{key, title, params, scopes: ["state"?, "department"?], departments: [codes]}]}` | Decision 7. |
| `GET /reports/pending-cases` | `reports.state`, or `reports.department` in the named department | `department?`, `format=json\|xlsx\|pdf` | JSON: the `Report` (`{key, title, scope, department_code, params, generated_at, generated_by, as_of_note, sections: [{key, title, columns: [{key, label, kind}], rows: [{...}], totals, note, total_rows, truncated}]}`); xlsx / pdf: the file | Decisions 5, 7, 12; xlsx / pdf audited (decision 13). |
| `GET /reports/hearings-disposals` | as above | `from`, `to` (required), `department?`, `format` | as above | 422 on a bad period. |
| `GET /reports/pending-actions` | as above | `department?`, `holder_department?`, `include_cases=false`, `format` | as above; the case section only with `include_cases=true`, filtered by case visibility | Decision 8. |
| `GET /reports/data-health` | `reports.state` | `from`, `to` (default the last 7 days), `format` | as above | State scope only; `department` refused (400). |

No endpoint writes anything except the `report.exported` audit row of an xlsx / pdf export. No NAPIX or
SourceTrace call is made by any of them (plan §5.1: no direct API calls).

## Jobs
None. No scheduled report, no queue kind, no Celery task. (`aslms reports run` covers out-of-portal use.)

## Tests
Unit (`tests/unit/`):
- `test_age_band_boundaries` — 364 days, exactly 1, 3, 5, 10, 20, 30 years, no date at all; leap day.
- `test_period_checks` — `to` before `from`, over the limit, future `from` → errors; 366 days accepted.
- `test_catalogue_scopes` — `data-health` State only; the other three both scopes.
- `test_xlsx_export_shape` — sheet per section, header rows with scope and generated-by, totals, dates as
  dates, cap note when truncated (open the bytes with `zipfile` and read the sheet XML).
- `test_pdf_export_shape` — PyMuPDF opens the bytes; page count; the title, a row and the cap note in the text;
  HTML special characters in an office name are escaped.
- `test_filename_format`.

Database (`tests/db/test_dashboard.py`, with the `world` fixture of `tests/db/world.py`):
- `test_blocks_follow_functions_not_types` — default matrix: oversight → state + me; dept admin and head →
  department + me; officer, directorate user, counsel → me only; a granted `reports.department` officer gets
  the department block; the super admin gets state + me.
- `test_person_with_two_departments_gets_two_blocks` and `test_department_required_lists_candidates`.
- `test_department_block_of_another_department_is_403_unless_dashboard_state`.
- `test_department_counts_equal_inbox_counts` — recommendations and claimed counts match `/inbox/counts`.
- `test_pending_action_sections_need_track_or_reports_function` — `null` for a whole-department member whose
  `custody.track` and `reports.department` are denied; the overdue list only with `custody.track`.
- `test_hearings_7d_and_critical_48h_match_calendar`.
- `test_hearing_list_hides_cases_the_caller_cannot_see` — a `reports.department` grantee below the department
  office sees the count but not the case rows outside their visibility.
- `test_attention_counts_next_dates_to_review_and_compliance`.
- `test_me_block_own_cases_files_alerts_hearings_drafts` — directorate user's unit allotment, counsel basis
  count, held files ordered by due date, alert counts equal `/alerts/counts`.
- `test_state_block_by_department_and_not_claimed_row` — includes a department with zero cases and an inactive
  department that still owns a case; totals equal the sum of rows.
- `test_dashboard_writes_nothing` — no `audit_log`, `events` or other row added; session has no pending
  changes.

Database (`tests/db/test_reports.py`):
- `test_pending_cases_state_groups_by_department_court_age` — primary owner, watcher column, two not-claimed
  rows, provisional column, `unknown` status column, merged cases excluded.
- `test_pending_cases_department_groups_by_unit`.
- `test_transferred_case_counts_for_current_owner`.
- `test_hearings_disposals_counts_listings_proceedings_disposals_and_months`.
- `test_pending_actions_by_holder_office_and_officer` — files held in another department appear under the
  holder department; `none` legs excluded; due soon and overdue against IST today.
- `test_overdue_compliance_by_addressed_office` — done and expired alerts excluded.
- `test_include_cases_respects_visibility_and_never_shows_remark` — the remark text appears nowhere in JSON,
  xlsx or pdf.
- `test_data_health_per_date` — queue rows, causelists, call log, source failures, SourceTrace attempts.
- `test_report_scope_rules` — department holder for own department 200, other department 403, no function 403,
  several departments 400 with candidates, `reports.state` any department, `data-health` with `department`
  400.
- `test_statement_timeout_is_set` — `SHOW statement_timeout` inside a builder.
- `test_builders_do_not_write`.

API (`tests/db/test_api_reports.py`, `tests/db/test_api_dashboard.py`):
- `test_dashboard_endpoints_status_codes` — 401 unsigned, 403 without functions, 200 shapes.
- `test_export_xlsx_and_pdf_headers_and_audit` — content types, `Content-Disposition`, `Cache-Control:
  no-store`, one `report.exported` row with params and row count; JSON writes no audit row.
- `test_export_caps_rows_and_says_so`.
- `test_bad_format_and_bad_period_are_4xx`.
- `test_migration_0012_up_down` — the two indexes exist after upgrade and are gone after downgrade;
  `compare_metadata` empty.

## Verification
1. `ruff check` clean; `pytest -q` green.
2. `alembic upgrade head` on the dev database (0012); `\di ix_cases_disposal_date` and
   `ix_case_hearings_business_date` exist.
3. `aslms reports run data-health --from <7 days ago> --to <today>`: one row per date; the `causelist_day`
   status and lists stored per date equal `SELECT list_date, count(*) FROM causelists WHERE list_date BETWEEN …
   GROUP BY list_date`; NAPIX calls per day equal the `napix_call_log` counts by IST day.
4. `aslms reports run pending-cases`: the sum of all rows equals `SELECT count(*) FROM cases WHERE status IN
   ('pending','unknown') AND merged_into_case_id IS NULL`; the "Not claimed" rows equal the never-owned count of
   `/inbox/pool` for a State reader.
5. `aslms reports run hearings-disposals --from 2025-01-01 --to 2025-01-31`: `listings` total equals the
   distinct (case_id, list_date) count of January 2025 cause-list entries with a case; `disposed` equals
   `SELECT count(*) FROM cases WHERE disposal_date BETWEEN '2025-01-01' AND '2025-01-31'`.
6. `aslms reports run pending-cases --format xlsx --out /tmp/p.xlsx` and `--format pdf --out /tmp/p.pdf`:
   both open (LibreOffice / a PDF viewer); one `report.exported` row each.
7. API with Compose up: `GET /dashboard/state` as a State oversight user and `GET /dashboard/department` as a
   department admin answer 200 in under 2 seconds on the loaded dev data (record the timings in the cycle
   report); an officer gets 403 on `/dashboard/state` and on `/reports/pending-cases`.
8. `EXPLAIN` of the `hearings-disposals` disposals query uses `ix_cases_disposal_date`.

## Open questions
None. Points for the owner to check at approval (decided here, reversible):
- Decision 1: dashboards by function; `central_operator` keeps no `dashboard.state` by default (the super admin
  can enable it in the type matrix).
- Decision 5: a case counts for its current owner; "pending" includes status `unknown` (shown separately);
  hearings are reported as cause-list listings with dossier proceedings beside them; compliance status comes
  from the `compliance_due` alerts (open or acknowledged = outstanding, done = complied).
- Decision 6: the NJDG age bands.
- Decision 8: a `reports.department` holder sees the department's totals even where they cannot open every
  case; case rows are always filtered by visibility.
- Decision 9: `reports.department` also opens the department dashboard's pending-action and custody-by-office
  counts (beside `custody.track`); the overdue file list stays with `custody.track`.
- Decision 12: XlsxWriter added as a dependency; row caps 5,000 (Excel) and 1,000 (PDF).
- Decision 13: exports audited, views not.
- Decision 14: the API does not use `aslms_readonly`.

## Left for later
- Proposed new backlog row `portal-reports`: the reports screen with the four reports, parameters and the
  Excel / PDF buttons (row 11 `portal-shell` takes the dashboard).
- Snapshot tables for "pending as of a past date", month-end figures and trends (decision 4), if the owner asks.
- Scheduled reports by e-mail (e.g. a weekly State summary to oversight users), if the owner asks; they would
  reuse `report_export` and the mailer, and need a rule about attachments containing case data.
- Row 10 (`audit-screens`) reads the same operations tables for the live data-health screen and the re-fetch
  buttons; row 26 fills the dashboard's "next dates read from orders"; a `napix_call_log` retention job (none
  exists yet) bounds the data-health report's call history.
