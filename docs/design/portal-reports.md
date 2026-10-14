# Design: Portal — the Reports screen (the four reports with parameters and the Excel / PDF buttons)

```
slug: portal-reports
status: approved
author: architect
date: 2026-10-14
approved_by: owner (nayanlhuzuri) on 2026-10-14
```

## Context
Backlog row 39, proposed by reports-dashboards ("Left for later") on 8 Oct 2026: "The reports screen: the four
reports (pending-cases, hearings-disposals, pending-actions, data-health) with parameters and the Excel / PDF buttons
over `/reports` (row 11 `portal-shell` takes the dashboard); with it, optional follow-ups the owner may ask for:
snapshot tables for past-date figures and trends, scheduled e-mailed reports, a `napix_call_log` retention job."

The plan: §5.10 (Reports) "Management information for departments and State oversight": pending cases by department,
court and age; hearings and disposals over a period; pending actions and overdue compliance by office; data collection
health (the daily data cycle, failed API calls, failed SourceTrace ingestions). "Portal database. Reports can be
exported to Excel and PDF." "Links to: Dashboard, case inbox, custody." §5.7 links custody to "reports (pending actions
by office)". Table 1: State oversight has "State-level dashboards and reports". §8.1: visibility on every request.
Phase 2 (§9). The plan does not ask for snapshots, trends, scheduled reports or a retention job.

In place and used (nothing here changes what a report counts):
- API (reports-dashboards, built 8 Oct 2026): `GET /reports` (the caller's catalogue: `key`, `title`, `params`,
  `scopes`, `departments` as codes; 403 without `reports.department` or `reports.state`), and
  `GET /reports/pending-cases | hearings-disposals | pending-actions | data-health` with `format=json|xlsx|pdf`. A JSON
  report is `{key, title, scope, department_code, params, generated_at, generated_by {name, designation,
  office_code}, as_of_note, sections: [{key, title, columns: [{key, label, kind}], rows, totals, note, total_rows,
  truncated}]}`; column kinds `text`, `int`, `date`, `days`. Files are streamed with `Content-Disposition:
  attachment`, `Cache-Control: no-store`, and audited as `report.exported`; JSON is not audited (reports-dashboards
  decision 13). Scope rules (decision 7): a department needs `reports.department` there or `reports.state`; no
  department needs `reports.state`, else the caller's single department, else 400 `department_required`;
  `data-health` is State only (400 with `department`). Periods: 422 `bad_period` (`to` before `from`, over
  `REPORT_MAX_RANGE_DAYS` 366 or `REPORT_HEALTH_MAX_DAYS` 92, `from` in the future); `data-health` defaults to the
  last 7 days and takes `from` and `to` together or neither. The `include_cases` section of `pending-actions` is
  filtered by the caller's case visibility, carries `ref_no`, and is capped at `REPORT_XLSX_MAX_ROWS` in JSON and
  Excel and `REPORT_PDF_MAX_ROWS` in PDF ("first N of M rows"). Every builder runs under `SET LOCAL
  statement_timeout` (`REPORT_STATEMENT_TIMEOUT_SECONDS`, 30); a timeout surfaces today as an unhandled 500.
- Portal: `routes.ts` already declares the unbuilt entry `{ key: "reports", href: "/reports", functions:
  ["reports.department", "reports.state"], built: false }`; the frame pattern of `DataFrame` / `DataIndex`; `Tabs`,
  `Table`, `numCell`, `SelectField`, `CheckField`, `TextField`, `Button`, `ErrorBanner`, `Loading`, `EmptyState`,
  `Notice`, `Pagination`, `CaseLink` (`components/ui`); `formatDate`, `formatDateTime`, `formatNumber`, `istDay`,
  `addDays` (`lib/format.ts`); `plainParams`, `queryString`, `PAGE` (`lib/params.ts`); `useMe`, `useDepartments`
  (`lib/api/hooks.ts`); `can`, `canIn`, `tracksDepartment` (`lib/can.ts`); `refPath` (`lib/refs.ts`); the relay, which
  already passes `content-disposition` and `cache-control` and is used by every document download link; the
  dashboard's `StateBlock` and `DepartmentBlock`; the Data collection Health tab (`components/data/Health.tsx`).

Not covered: the dashboard (row 11, built); the live data-health screen (row 45, built); the review follow-ups of the
report counts (row 40 `reports-hardening`); the three optional follow-ups (decision 12); drill-down from a report's
aggregate rows to case lists (Left for later).

## Decisions
1. **Routes and frame.** A "Reports" frame (`components/reports/ReportsFrame.tsx`) with one tab per report the caller
   may run: `/reports/pending-cases` ("Pending cases"), `/reports/hearings-disposals` ("Hearings and disposals"),
   `/reports/pending-actions` ("Pending actions"), `/reports/data-health` ("Data collection health"); `/reports` opens
   the first tab the caller may run (as `DataIndex`). The tabs come from `GET /reports`, not from a function table in
   `routes.ts`, because the server already says which reports and scopes the caller has (`data-health` only for
   `reports.state`); the frame waits for that call. A report path the caller's catalogue does not contain shows "This
   report is not available to you." and requests nothing. Four static page files (`app/(portal)/reports/<key>/
   page.tsx`) each render `<ReportPage reportKey="…" />`. Alternatives: one page with a report selector (no deep
   links per report); a dynamic `[key]` route (the static pages match every other frame and make an unknown key a
   plain 404).
2. **Navigation and breadcrumbs.** The existing "Reports" entry becomes `built: true` (shown with `reports.department`
   or `reports.state`, as declared, between "Alerts & calendar" and "Data collection"). `CRUMBS.reports = "Reports"`;
   `CRUMB_PATHS` gains the four paths with the tab labels of decision 1. Showing the entry is convenience only; the
   API decides.
3. **Parameters live in the query string; the report runs on open.** Each tab reads its parameters from the URL
   (`department`, `from`, `to`, `holder_department`, `include_cases`), fills defaults (decisions 4 and 5) and requests
   the JSON report at once (all four aggregate well within the 30-second timeout on the dev data; reports-dashboards
   verification 7). The parameter form above the report has a "Show report" button that writes the parameters to the
   URL (`router.push`), so a link, a bookmark or the back button restores the same report. A "Refresh" button re-reads
   the same parameters (stock figures are "as of now"). The query key is `["reports", key, params]` with
   `staleTime` 60 seconds. While loading: "Preparing the report…". Alternative: run only on a button press (an empty
   screen on every visit for no protection; the API bounds the cost).
4. **Scope: "Whole State" or one department.** A `department` select:
   - a caller whose catalogue item has the `state` scope sees "Whole State" (the default; the parameter omitted) and
     every department of the item's `departments`;
   - a caller with only the `department` scope sees their departments; without `department` in the URL the page
     writes the first one (`router.replace`), so the API's 400 `department_required` never reaches the screen; with
     one department the select is shown read-only (its name as text);
   - `data-health` has no select (State only).
   Department names come from a new read-only field of `GET /reports` (decision 9a), so departments no longer active
   that still own cases (included in a State reader's list) are named too. The report header names the scope as the
   API returned it (`scope`, `department_code`), never as the form shows it.
5. **Periods.** `hearings-disposals`: default "This month" (the first of the current IST month to today, IST);
   quick choices "This month", "Last month", "This year" (1 January to today) and "Choose dates" (two date inputs,
   `max` today). `data-health`: default "Last 7 days" (the parameters omitted, the API's default); quick choices "Last
   7 days", "Last 30 days", "Choose dates". The browser checks only that both dates are given, `to` is not before
   `from` and `from` is not after today (IST); the range limits (366 and 92 days) are the server's settings and are not
   copied into the portal: a 422 `bad_period` is shown under the period fields with the API's message ("the period is
   at most 92 days"), and no report or download link is shown for it. Alternative: hard-code the limits (two places to
   change when a setting changes).
6. **Pending actions: holder department and the file list.** A "Holder department" select ("All holders", the
   default, or one department from `useDepartments()`, all active departments, because a file may be sent to any
   department) sent as `holder_department`; it narrows the two file sections, not the compliance section (built
   deviation 10, said under the select). A tick "List the files" (`include_cases=true`) adds the per-file section;
   without it the report has the aggregates only. The per-file rows are paged in the browser by `PAGE` (50) with
   `Pagination` (the API returns the whole capped section). Each row's case number is a link to the case page by
   `ref_no` (`refPath`), since the API returns only cases the caller can open. When the caller tracks a department
   (`tracksDepartment`), a line under the report links to Files → "Department files" (`/files/department`) for the
   live list with remarks, which the report never shows (plan §5.10 "links to custody").
7. **One generic renderer for every section.** `ReportView` draws the header and the sections from the JSON alone, so
   a column added to a report on the server appears without a portal change:
   - header: the API's `title` (h2), scope ("Whole State" or the department's name and code), the parameters in words
     (period as "1 Oct 2026 – 14 Oct 2026", holder department, "with the file list"), "Generated at" (IST,
     `formatDateTime`), "Generated by" (name, designation, office code) and the `as_of_note` as a `Notice`;
   - each section: a `Table` with the section `title` as caption and `<th scope="col">` from `columns`; cells by
     `kind`: `int` and `days` right-aligned with `formatNumber` (`numCell`), `date` with `formatDate`, `text` as
     given; `null` or empty as "—"; the `totals` row in `<tfoot>` (bold, the label the API put in it); the section
     `note` under the table; when `truncated`, "First {rows} of {total_rows} rows; narrow the report to see the
     rest.";
   - a section with no rows says "Nothing to report for these parameters." under its caption;
   - a wide table (`data-health` has 17 columns, `pending-cases` by court has the age bands) sits in a horizontal
     scroll region (`role="region"`, `aria-label` the section title, `tabIndex={0}`) so it can be scrolled by keyboard;
     the first column is sticky.
   Rendering per report key with hand-written columns was rejected (the column lists would be written twice and
   drift).
8. **Excel and PDF buttons are links to the same report.** Under the header, "Download Excel" and "Download PDF" are
   `<a download>` links to `/api/backend/reports/<key>?<the same parameters>&format=xlsx|pdf` (built by one helper,
   `exportUrl`), the pattern of every document download in the portal (the relay passes `Content-Disposition` and
   `Cache-Control: no-store`; the file name comes from the API). They are shown only once the JSON report for exactly
   those parameters has loaded without error, so a download never carries parameters the API refused; the file is
   built afresh at the click and states its own "generated at". A line under the buttons: "Downloads are recorded in
   the audit log. The PDF lists at most the first rows of a long file list; the Excel file holds more." Nothing is
   written by the screen itself: the API writes the `report.exported` row. Alternative: fetch the file into a `blob:`
   URL to show errors in the page (a second download mechanism and a CSP change for an error the preceding JSON run
   already rules out; a rare timeout shows the relay's JSON error, as a document download does today).
9. **Two small, read-only API additions** (no table, no function, no audit change):
   - (a) `GET /reports` gains a top-level `departments: [{code, name, is_active}]`: every department code that appears
     in any item's `departments`, in the same order (active Department-tier offices and inactive ones still owning
     cases, for a `reports.state` holder; the caller's own departments otherwise). Additive; the items keep their code
     lists. Alternative: `useDepartments()` (active departments only: an inactive department owning cases would show
     as a bare code).
   - (b) A report that runs past the statement timeout answers **503 `report_timeout`** ("the report took too long;
     choose a shorter period or one department") instead of an unhandled 500, as the audit search and the coverage
     query already do (`search_timeout`): `reports.build` catches `OperationalError` whose `sqlstate` is
     `QUERY_CANCELED` and raises `ReportError("report_timeout", …, 503)`; the router's `http_error` already maps
     `ReportError`. The screen shows the message in the `ErrorBanner` with "Try again". The same applies to an export
     (the relay returns the JSON error).
10. **Links between the screens** (plan §5.10 "links to dashboard, case inbox, custody"):
    - dashboard State block: a "Reports" link (`/reports/pending-cases`) beside its heading when the login holds
      `reports.state`;
    - dashboard department block: a "Department reports" link (`/reports/pending-cases?department=CODE`) when the
      login holds `reports.department` in that department (`canIn`) or `reports.state`;
    - Data collection → Health: a "Period report" link to `/reports/data-health` when the login holds `reports.state`;
      the `data-health` report links back to `/data/health` ("Live health") — `reports.state` is a data-collection
      reader, so the link always opens;
    - `pending-actions` → Files (decision 6).
    No link is a gate; each target checks its own function.
11. **No case text beyond what the API sends.** The screen adds nothing to the reports: no remark, note, document or
    party name is fetched or shown; the per-file rows are the API's visibility-filtered columns. Reading a JSON report
    writes nothing; only the API's export writes `report.exported`.
12. **The three optional follow-ups are not built in this item.** The owner has not asked for them and the plan asks
    for none; each needs a rule only the owner can give, so each would be its own backlog row designed when asked:
    snapshot tables for past-date figures and trends (which figures, how often, how long kept); scheduled e-mailed
    reports (who receives what, how often, and whether an attachment with case rows may leave the portal by e-mail at
    all); a `napix_call_log` retention job (the retention period: DB_STANDARD §6 allows pruning this log only, and
    the log also feeds the quota-window detection, the Queue and calls screen and this item's 92-day health report).
    The backlog row's title is trimmed to the screen when this note is approved, and one `parked` row
    `reports-followups` holds the three items. Alternative: build a retention job with a guessed period (CLAUDE.md:
    never invent a business rule).
13. **No migration, no schema change, no new function, no new setting.** `reports.department` and `reports.state`
    gate the screen as seeded; the default type matrix is unchanged.

## Data
No table, column, index, `ref_*` code, enum value or `Permission` is added; `docs/schema/schema.md` is unchanged. No
migration (the head stays at 0017).

## Services
`backend/aslms/services/reports.py` (changed, small):
- `catalogue_for(session, user)` returns `{reports: [...], departments: [{code, name, is_active}]}` (decision 9a);
  the names come from the same `department_rows(session)` read (State) or the caller's memberships' departments.
- `build(...)` wraps the builder call: an `OperationalError` with `sqlstate == QUERY_CANCELED` becomes
  `ReportError("report_timeout", "the report took too long; choose a shorter period or one department", 503)`
  (decision 9b); any other error is re-raised. The transaction is left for the request's session handling to roll
  back, as in `audit_search._timed`.
- No write, audit or event is added. `report_export` is unchanged.

`backend/aslms/api/schemas.py`: `ReportDepartmentOut {code, name, is_active}`; `ReportCatalogueOut` gains
`departments: list[ReportDepartmentOut]`. `api/routers/reports.py`: `catalogue` returns the new dict; the report
endpoints' docstrings name the 503. `frontend/openapi.json` and `src/lib/api/schema.d.ts` regenerated
(`npm run gen:api`); `src/lib/api/types.ts` exports `ReportCatalogue`, `Report`, `ReportSection`, `ReportColumn`.

Portal (`frontend/src`):
- `lib/reports.ts` (new, pure): `REPORT_TABS` (key, label, href in order); `reportParams(key, params, today)` — the
  parameters of decisions 3–6 with defaults, as sent to the API; `periodChoice(choice, today)` for "This month",
  "Last month", "This year", "Last 7 days", "Last 30 days" (IST dates); `checkPeriod(from, to, today)` (decision 5's
  browser checks); `exportUrl(key, params, format)`; `cellText(value, kind)`; `scopeLabel(report, departments)`.
- `components/reports/ReportsFrame.tsx` (frame, tabs from the catalogue, `ReportsIndex`), `ReportPage.tsx` (form,
  query, header, buttons), `ReportForm.tsx` (scope, period, holder department, file-list tick), `ReportView.tsx`
  (decision 7), `reports.module.css` (scroll region, sticky first column, totals row).
- `app/(portal)/reports/layout.tsx`, `page.tsx` (`ReportsIndex`) and the four tab pages.
- `lib/api/hooks.ts`: `useReportCatalogue()` (`GET /reports`, key `["reports","catalogue"]`, `staleTime` 5 minutes,
  not retried on 403).
- `lib/routes.ts`: the entry `built: true`, `CRUMBS.reports`, `CRUMB_PATHS` for the four tabs.
- `components/dashboard/Dashboard.tsx` and `components/data/Health.tsx`: the links of decision 10.
- `lib/messages.ts`: a `reports` group with every string above (labels, period choices, empty and error texts, the
  download line).

## API
Unchanged endpoints are listed for completeness; only `GET /reports` changes shape (additively) and every report
endpoint gains the 503.

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /reports` | `reports.department` or `reports.state` | — | `{reports: [{key, title, params, scopes, departments: [code]}], departments: [{code, name, is_active}]}` (new top-level field, decision 9a) | 403 without either function. |
| `GET /reports/pending-cases` | `reports.state`, or `reports.department` in the named department | `department?`, `format=json\|xlsx\|pdf` | the `Report` JSON, or the file | Unchanged; 503 `report_timeout` (decision 9b); xlsx / pdf audited `report.exported` by the API. |
| `GET /reports/hearings-disposals` | as above | `from`, `to`, `department?`, `format` | as above | Unchanged; 422 `bad_period`; 503 `report_timeout`. |
| `GET /reports/pending-actions` | as above | `department?`, `holder_department?`, `include_cases`, `format` | as above; file rows only those the caller can open | Unchanged; 503 `report_timeout`. |
| `GET /reports/data-health` | `reports.state` | `from?`, `to?` (together), `format` | as above | Unchanged; 400 with `department`; 503 `report_timeout`. |

The portal calls them only through the relay (`/api/backend/...`); the Excel and PDF links are plain GETs through the
same relay. No endpoint calls NAPIX or SourceTrace.

## Jobs
None.

## Tests
Backend (`backend/tests/db/test_api_reports.py`, additions; the `world` fixture and `report_support.py`):
- `test_catalogue_names_its_departments` — a `reports.state` holder gets every Department-tier office in
  `departments` with names, including an inactive department that still owns a case (`is_active` false); a
  department admin gets only their own department; the codes equal the union of the items' lists, in order.
- `test_report_timeout_is_503` — with `REPORT_STATEMENT_TIMEOUT_SECONDS` patched to make a builder exceed it (or a
  builder patched to raise `OperationalError` carrying `QUERY_CANCELED`), JSON and xlsx both answer 503
  `report_timeout`; no `report.exported` row is written; a different `OperationalError` is not mapped.

Portal unit (`frontend/src/lib/reports.test.ts`):
- `periodChoice` — "This month" on 1 Oct (one day), on 14 Oct; "Last month" across a year end (January → December);
  "This year"; "Last 7 days" and "Last 30 days" inclusive of today; all in IST near midnight UTC.
- `checkPeriod` — missing date, `to` before `from`, `from` after today refused; the range length is never checked.
- `reportParams` — defaults per report; `include_cases` only when ticked; `data-health` never sends `department`;
  empty values omitted.
- `exportUrl` — the same parameters plus `format`, encoded, under `/api/backend/reports/<key>`.
- `cellText` — `int`, `days`, `date`, `text`, `null`.

Portal components (`frontend/src/components/reports/reports.test.tsx`, mocked API):
- `the Reports entry shows with reports.department or reports.state and not without` (and the shell test's nav
  list updated).
- `tabs follow the catalogue` — a State reader gets four tabs, a department reader three (no data-health);
  `/reports` opens the first; a path not in the catalogue says it is not available and makes no report request.
- `a department-only reader gets their first department written to the URL`; `a single department shows as text`;
  `a State reader defaults to Whole State and may pick an inactive department by name`.
- `sections render from columns` — caption, column headers, number and date formatting, "—" for null, totals in
  `tfoot`, the note, the truncated line, the empty-section text; a column unknown to the portal is rendered.
- `file rows link to the case page and are paged by 50`.
- `download links carry the shown parameters and appear only after the report loaded` — absent while loading, on
  422 and on 503; present with `format=xlsx` / `format=pdf` after success; the audit line is shown.
- `a bad period shows the API message under the period fields`; `a 503 shows the message with Try again`.
- `holder department lists all active departments and says it does not narrow compliance`.
- `the Department files link shows only to a tracker`.
- Dashboard (`dashboard.test.tsx`) and data (`data.test.tsx`): the Reports, Department reports and Period report
  links show by their functions; the data-health report links to Live health.

`ruff check` clean, `pytest -q` green; `npm run lint`, `npm run typecheck`, `npm test` green.

## Verification
1. `ruff check`, `pytest -q`; in `frontend/`: `npm run lint`, `npm run typecheck`, `npm test`.
2. `docker compose up -d --build api web`; sign in at `http://localhost:3000` as the super admin.
3. Reports → Pending cases (Whole State): the totals row equals `docker compose exec api aslms reports run
   pending-cases --format json` (same totals); pick one department: the totals equal `aslms reports run pending-cases
   --department CODE`.
4. Hearings and disposals → Last month: listings and disposals totals equal `aslms reports run hearings-disposals
   --from <first> --to <last>`; "Choose dates" with a range over 366 days shows the API's message and no download
   links.
5. Pending actions with "List the files": the file rows link to case pages; Data collection health → Last 30 days:
   one row per date; "Choose dates" over 92 days shows the message.
6. Download Excel and Download PDF on each report: the files open (LibreOffice and a PDF viewer) with the same totals
   as the screen; `GET /audit?action=report.exported` shows one row per download with the parameters; showing a report
   adds no audit row.
7. Sign in as a department admin: three tabs (no data-health), the department fixed to theirs; as an officer without
   a reports function: no Reports entry, and `/reports` says it is not available.
8. Dashboard State block "Reports" link, department block "Department reports" link, Health "Period report" link and
   back; record any report taking more than 5 seconds on the dev data in the cycle report.

## Open questions
None. Points for the owner to check at approval (decided here, reversible):
- Decision 3: a report runs as soon as its tab opens, with defaults ("This month" for hearings and disposals, the last
  7 days for data health).
- Decision 8: the Excel and PDF buttons download directly; every download is recorded in the audit log (already so).
- Decision 9: two small API changes (department names in the report list; a clear "took too long" answer instead of
  an error page).
- Decision 12: snapshots and trends, scheduled e-mailed reports and the call-log retention job are left out until
  you ask; each needs your rule (what to keep and for how long, who receives what by e-mail, the retention period).
  They move to one parked backlog row `reports-followups`.

## Left for later
- Row `reports-followups` (parked, decision 12): snapshot tables and trends; scheduled e-mailed reports (reusing
  `report_export` and the mailer); the `napix_call_log` retention job.
- Drill-down from an aggregate row (a department, a holder office) to the matching case or file list, once the list
  screens accept the same grouping as filters.
- Row 40 (`reports-hardening`) corrects two counts of the dashboard department block; the reports themselves are
  unaffected.
