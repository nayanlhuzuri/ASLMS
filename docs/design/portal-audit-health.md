# Design: Portal — the Audit log screen (search, entry view, links from the case, user and office pages)

```
slug: portal-audit-health
status: approved
author: architect
date: 2026-10-14
approved_by: owner (nayanlhuzuri) on 2026-10-14
```

## Context
Backlog row 41: "The portal screen for the audit log search (`/audit`; the data-health screen and the NAPIX buttons
moved to row 45); with it, if the owner or vigilance asks: a department-scoped audit view, `audit.searched` rows,
export of an audit search, a button re-running Current Status batches."

The plan: §5.13 (Audit Log) "A permanent record of every significant action in the portal. Logins, ownership
decisions, custody moves, notes, file uploads and configuration changes. Searchable by user, case and date; read-only
for auditors." Data: "Portal database (append-only)". Links to: "All modules". Table 1: the Auditor ("Audit /
vigilance") has "read-only access to case records and the audit log". §8.1: visibility on the server for every
request. The plan asks for no export of the audit log, no trail of reads and no department-level audit reader.

In place and used (built by audit-screens, 8 Oct 2026; nothing here changes it):
- `GET /audit` (filters `user` id or e-mail, `actor` name text 2–100, `about_user` id or e-mail, `case` id / `ref_no` /
  CNR with the cases merged into it, `office` code with its subtree, `action` exact or a prefix ending in `.`,
  `entity_type`, `entity_id`, IST `from` / `to`; `limit` 1–200, default 50; newest first; keyset `cursor` /
  `next_cursor`, no total); `GET /audit/actions` (the distinct codes); `GET /audit/{id}` (one row). Row shape
  `AuditRowOut {id, at, action, entity_type, entity_id, case {id, ref_no, cnr, case_no_text} | null, actor {user_id,
  name, designation, office_code}, ip, user_agent, before, after}`. Errors: 400 `unknown_user`, `bad_office`,
  `bad_cursor`, `bad_period`, `bad_actor`; 404 `not_found` (unknown case or row); 403 without `audit.view`, 403
  `audit_scope` for a holder outside a State-wide membership; 503 `search_timeout`; 422 for malformed query values
  (FastAPI). Reading writes nothing (audit-screens decision 3). Note bodies and custody remarks appear in rows only as
  `{length, sha256}` (custody-workflow decision 21).
- Who reads it (audit-screens decision 2, owner's answer of 8 Oct 2026): `audit.view` in a State-wide membership —
  the super admin, or a membership also holding `cases.view_all` (the default Auditor type has both; seeded in
  `access_seed.py`). The super admin can switch access off for the type or one user.
- Portal: `routes.ts` already declares the unbuilt entry `{ key: "audit", label: "Audit log", href: "/audit",
  functions: ["audit.view"], built: false }`; `/me.memberships[].role` and `.functions`; `can`, `isSuperAdmin`
  (`lib/can.ts`); `useDepartments()` and `useDepartmentPeople()` (`/custody/recipients`, needs `cases.view_scope`,
  which the Auditor holds; `units` gives the offices inside a department); the keyset "More" pattern of the call log
  (`components/data/Queue.tsx`, `useInfiniteQuery`); `Table`, `TextField`, `SelectField`, `Button`, `ErrorBanner`,
  `Loading`, `EmptyState`, `Notice`, `DefinitionList`, `CaseLink` (`components/ui`); `formatDate`,
  `formatDateTime`, `istDay`, `addDays` (`lib/format.ts`); `plainParams`, `queryString` (`lib/params.ts`); the
  parameters-in-the-URL pattern of the Reports screen (portal-reports decision 3, deviation 1); the relay.

Not covered: the data-health screen and the NAPIX buttons (row 45, built as Data collection → Health and Queue and
calls); the hardening of the audit API (row 42); the four optional follow-ups (decision 11).

## Decisions
1. **Routes.** `/audit` is the search (`app/(portal)/audit/page.tsx`, reading `searchParams` on the server and
   rendering `<AuditSearch params={…} />`, as the Reports and Cause list pages do); `/audit/[id]` is one entry
   (`<AuditEntry id={…} />`) for deep links, over `GET /audit/{id}`. No tabs: there is one screen. Alternative: the
   entry in a dialog over the list (no link an auditor can quote in a finding).
2. **Navigation shows the entry only to those the API will serve.** The "Audit log" entry becomes `built: true` with
   `functions: ["audit.view"]` and a `show` condition `readsAudit(me)` (new in `lib/can.ts`): an active membership
   whose role is `super_admin`, or whose `functions` include both `audit.view` and `cases.view_all` — the API's
   decision-2 rule, so a department membership granted `audit.view` alone does not see an entry that would answer
   403. Display only; the API decides. A direct visit by anyone else shows the API's 403 as "The audit log is read
   only by the super admin and the Auditor." and requests nothing more. The entry stays between "Reports" and "Data
   collection" as declared. `CRUMBS.audit = "Audit log"`; the last crumb of `/audit/<id>` reads "Entry" (a rule in
   `crumbLabel`, since the id is not a label).
3. **Filters live in the query string; the search runs on open.** The form reads `user`, `actor`, `about_user`,
   `case`, `office`, `action`, `entity_type`, `entity_id`, `from`, `to` from the URL — the API's own parameter names,
   so a screen URL and an API URL carry the same filters — and requests the first page at once. With no filter that
   is the newest 50 entries (served by `ix_audit_log_created_at`). "Search" writes the filters to the URL
   (`router.push`), so a link, a bookmark or Back restores the same search; "Clear" goes to `/audit`; "Refresh"
   re-reads from the newest entry. Query key `["audit", params]` (`useInfiniteQuery`, `staleTime` 30 seconds). Empty
   fields are omitted. Alternative: search only on a button (an empty screen on every visit; the API bounds the cost).
4. **The filter form** (the plan's user, case and date first):
   - **Person** (`user`): an e-mail address or a login id, as the API takes it; "Name contains" (`actor`, 2–100
     characters, checked in the browser so the API's 422 is not reached).
   - **Case** (`case`): a `ref_no` or a CNR; the hint says the cases merged into it are included.
   - **Office** (`office`): a department select from `useDepartments()` ("Any office" by default) and, once a
     department is chosen, a unit select from `useDepartmentPeople(department).units` ("The whole department" by
     default); the API includes the chosen office's subtree. A code in the URL that the lists do not hold (an inactive
     office, from a link) is kept and shown as its code.
   - **Action** (`action`): one select built from `GET /audit/actions`, grouped by the part before the first `.`;
     each group starts with "All <group> actions" (the prefix `group.`), then its codes as stored. Group names come
     from a `T.audit.groups` map in `messages.ts` (for example `custody` "Custody", `ownership` "Ownership",
     `auth` "Sign-in and passwords"); an unknown group shows its prefix. Codes are not translated one by one (about 90,
     and they grow with every item); the code is what an auditor quotes.
   - **Period** (`from`, `to`): quick choices "Any time" (the default), "Today", "Last 7 days", "Last 30 days" and
     "Choose dates" (two date inputs, `max` today, IST). The browser checks `to` is not before `from`.
   - **More filters** (collapsed unless one is set): "About the user" (`about_user`, e-mail or login id: rows about a
     login and its memberships), "Record type" (`entity_type`) and "Record id" (`entity_id`, checked as a UUID in the
     browser).
   API refusals are shown under the field they concern: `unknown_user` under Person or About the user (whichever was
   sent; both if both), 404 `not_found` under Case ("No case with this reference"), `bad_office` under Office,
   `bad_period` under Period; no list is shown for a refused search.
5. **The list.** A `Table` with caption "Audit log entries", newest first, columns: When (IST, to the second, a new
   `formatDateTimeSeconds` in `lib/format.ts`), Action (the code, monospace), By (name, designation, office code; "System"
   when the row has no actor name), Case (`CaseLink` by `ref_no`, else "—"), Record (`entity_type`), and a "View" link
   to `/audit/<id>`. The person's name is a link to the same search narrowed to that login (`user=<user_id>`), the
   office code to `office=<code>`, the action to `action=<code>`. "More" fetches the next page by `next_cursor`
   (50 at a time); no total and no page numbers (the API has none, by design). An empty result says "No entries match
   these filters." A 503 `search_timeout` shows the API's message ("the search took too long; narrow the search") in
   the `ErrorBanner` with "Try again". IP address, browser and the before / after values are on the entry page only,
   so the list stays readable.
6. **The entry page.** `GET /audit/{id}`: a `DefinitionList` of When, Action, By (name, designation, office), Case
   (link), Record (type and id), IP address and Browser (`user_agent`), then **Before and after**: one table with a
   row per key of the union of `before` and `after` (keys in the order they appear), columns Field, Before, After, and a
   "changed" mark where the two differ; a value that is an object or list is shown as indented JSON (`<pre>`); a value
   shaped exactly `{length, sha256}` is shown as "Text not kept in the log (N characters; fingerprint <first 12 hex>)"
   so an auditor sees that note text was withheld, not lost; `null` or absent as "—". When both are empty: "This
   action records no values." Links under it: "All entries for this case" (`/audit?case=<ref_no>`), "All entries by
   this person" (`user=<id>`), "All entries for this record" (`entity_type` + `entity_id`), "Back to the search"
   (browser back when the referrer is the search, else `/audit`). 404 → "No audit entry with this id."
7. **Links from other screens** (plan §5.13 "links to all modules"), each shown only when `readsAudit(me)`, and each a
   plain link the API re-checks:
   - case page header (`CaseHeader`): "Audit trail" → `/audit?case=<ref_no>`;
   - Administration → Users → a user: "Entries by this user" (`user=<id>`) and "Entries about this user"
     (`about_user=<id>`);
   - Administration → Offices → an office: "Entries by this office" (`office=<code>`).
   The super admin holds both `users.view` and the audit functions, so the two administration links reach them; the
   Auditor does not open administration screens (no `users.view`) and reaches the same searches through the form.
8. **The screen writes nothing and shows only what the API returns.** No audit row is written by searching or
   viewing (audit-screens decision 3 stands; see decision 11 for `audit.searched`). The rows are shown as stored: the
   API already withholds note text and custody remarks, and the reader is State-wide by rule, so the screen hides no
   field and adds none.
9. **No API change.** Every filter, the action list, the entry and the errors exist. The screen uses the API's
   parameter names unchanged. Alternatives considered and not taken: a person picker (needs a user search the Auditor
   may call; `/admin/users` requires `users.view`, which the Auditor lacks, and a new reader endpoint is not needed
   for e-mail entry); office names in each row (the code is what the row stores; names change over time).
10. **No migration, no schema change, no new function, no new setting.** `audit.view` (with `cases.view_all`, or the
    super admin) gates the screen as seeded; the type matrix is unchanged. `frontend/src/lib/api/types.ts` exports
    `AuditRow`, `AuditPage`, `AuditActions` from the already generated `schema.d.ts` (no `gen:api` change needed;
    regenerate only if the build finds drift).
11. **The four optional follow-ups are not built in this item.** The row names them "if the owner or vigilance
    asks"; neither has asked, the plan asks for none, and each needs a rule only the owner can give:
    - a department-scoped audit view — who reads it (which type or function), which rows (actions by the
      department's offices, or actions on its cases, documents and notes), and which payload fields of rows about
      other departments' cases may be shown (audit-screens decision 2 left this for an owner rule);
    - `audit.searched` rows — whether vigilance wants a trail of who read the log, and whether it records the filters
      only (audit-screens decision 3's proposal) or also opened entries;
    - export of an audit search to Excel / PDF — whether audit rows (IP addresses, e-mail addresses, the file names of
      private filings) may leave the portal as a file at all, with what row cap, and whether an export is itself
      audited;
    - a button re-running today's Current Status batches — already in row 46 (`data-load-console-followups`, "re-run
      today's Current Status batches early"), a Data collection matter, not an audit screen.
    At approval the row's title is trimmed to the screen, and one `parked` row `audit-followups` holds the first three
    (the fourth stays in row 46). Alternative: build them on a guessed rule (CLAUDE.md: never invent a business rule).

## Data
No table, column, index, `ref_*` code, enum value or `Permission` is added; `docs/schema/schema.md` is unchanged. No
migration (the head stays at 0017).

## Services
Backend: no change. `services/audit_search.py` and `api/routers/audit.py` are used as built.

Portal (`frontend/src`):
- `lib/audit.ts` (new, pure): `AUDIT_PARAMS` (the ten parameter names); `auditParams(searchParams)` — the
  non-empty parameters as sent to the API; `periodChoice(choice, today)` for "Today", "Last 7 days", "Last 30 days"
  (IST dates; "Any time" omits both); `checkFilters(form, today)` — Name contains 2–100 characters, `to` not before
  `from`, `from` not after today, Record id a UUID; `actionGroups(codes, groupLabels)` — `[{prefix, label, codes}]`
  sorted by label, codes sorted; `diffRows(before, after)` — `[{key, before, after, changed}]`; `isTextDigest(value)`
  (exactly the keys `length` and `sha256`); `fieldOfError(code, sent)` — which field shows an API refusal.
- `lib/can.ts`: `readsAudit(me)` (decision 2).
- `lib/format.ts`: `formatDateTimeSeconds` (IST, `14 Oct 2026, 14:34:07`).
- `components/audit/AuditSearch.tsx` (form, query, list, More), `AuditFilters.tsx` (decision 4), `AuditTable.tsx`
  (decision 5), `AuditEntry.tsx` (decision 6), `BeforeAfter.tsx` (the diff table), `audit.module.css`.
- `app/(portal)/audit/page.tsx` and `app/(portal)/audit/[id]/page.tsx`.
- `lib/api/hooks.ts`: `useAuditActions()` (`GET /audit/actions`, key `["audit","actions"]`, `staleTime` 10 minutes,
  not retried on 403).
- `lib/routes.ts`: the entry `built: true` with `show: readsAudit`; `CRUMBS.audit`; the "Entry" crumb rule in
  `crumbLabel`.
- `components/case/CaseFrame.tsx` (`CaseHeader`), `components/admin/UserDetail.tsx`, `components/admin/Offices.tsx`
  (`OfficeDetailView`): the links of decision 7.
- `lib/messages.ts`: an `audit` group with every string above (field labels and hints, period choices, group names,
  column headers, empty, 403, 404 and digest texts, link texts).

No write, audit row or event is added anywhere.

## API
Unchanged endpoints, listed for completeness; the portal calls them only through the relay (`/api/backend/...`).

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /audit` | `audit.view` in a State-wide membership (super admin, or with `cases.view_all`) | `user`, `actor`, `about_user`, `case`, `office`, `action`, `entity_type`, `entity_id`, `from`, `to`, `limit` (the screen sends 50), `cursor` | `{items: [AuditRowOut], next_cursor}` | 403 / 403 `audit_scope`; 400 `unknown_user`, `bad_office`, `bad_period`, `bad_cursor`, `bad_actor`; 404 `not_found` (case); 503 `search_timeout`. Writes nothing. |
| `GET /audit/actions` | same | — | `{actions: [str]}` | Writes nothing. |
| `GET /audit/{id}` | same | — | `AuditRowOut` | 404 `not_found`. Writes nothing. |

The links of decision 7 open screens whose own endpoints check their own functions (`cases.view_scope` /
`cases.view_all` with case visibility, `users.view`, `offices.manage` / `users.view`). No endpoint calls NAPIX or
SourceTrace.

## Jobs
None.

## Tests
Backend: none new (no backend change). The existing `tests/db/test_audit_search.py` and `tests/db/test_api_audit.py`
stay green.

Portal unit (`frontend/src/lib/audit.test.ts`):
- `auditParams` — empty values omitted; the ten names passed unchanged; unknown names dropped.
- `periodChoice` — "Today", "Last 7 days", "Last 30 days" inclusive of today, in IST near midnight UTC; "Any time"
  sends neither date.
- `checkFilters` — Name contains of 1 and 101 characters refused, 2 and 100 accepted; `to` before `from` refused;
  `from` after today refused; a Record id that is not a UUID refused.
- `actionGroups` — codes grouped by prefix with the "All … actions" prefix entry; an unknown prefix labelled by
  itself; a code without a `.` in its own group.
- `diffRows` — union of keys in order of appearance; `changed` for differing values, including nested objects
  compared by value; one side `null`.
- `isTextDigest` — `{length, sha256}` true; with an extra key false.
- `fieldOfError` — `unknown_user` to Person when only `user` was sent, to About the user when only `about_user` was
  sent, to both when both; `not_found` to Case; `bad_office`, `bad_period`.
- `readsAudit` (in `lib/can.test.ts` or `routes.test.ts`) — super admin true; Auditor (`audit.view` +
  `cases.view_all`) true; a department membership with `audit.view` only false; `audit.view` and `cases.view_all` in
  two different memberships false; an inactive membership ignored.
- `formatDateTimeSeconds` (`format.test.ts`) — IST with seconds across midnight UTC.

Portal components (`frontend/src/components/audit/audit.test.tsx`, mocked API):
- `the Audit log entry shows for the super admin and the Auditor only` (and the shell test's nav list updated).
- `the search runs on open with the URL's filters` — the request carries exactly the URL's parameters and `limit=50`;
  with none, the newest entries are listed.
- `Search writes the filters to the URL; Clear goes to /audit`.
- `More appends the next page by cursor and disappears without next_cursor`.
- `rows render` — time to the second, action code, actor name with designation and office, "System" for a row with no
  name, case link by `ref_no`, "—" without a case; the name, office and action links narrow the search.
- `the action list is grouped with All … actions entries`.
- `the unit select appears after a department is chosen and sends the unit's code`.
- `API refusals show under their fields` — `unknown_user`, case `not_found`, `bad_office`, `bad_period`; no list shown.
- `a 503 shows the narrow-the-search message with Try again`; `a 403 shows the readers sentence and no form`.
- `browser checks stop the request` — one-character name, `to` before `from`, bad record id: no API call.
- `the entry page shows before and after` — changed marks, nested JSON, the digest sentence for `{length, sha256}`,
  "This action records no values." for empty rows, the three "All entries …" links; 404 text.
- `nothing is written` — the mocked API sees GET requests only.
- Case (`case.test.tsx`), admin (`admin.test.tsx`): the "Audit trail", "Entries by / about this user" and "Entries
  by this office" links show with `readsAudit` and not without, with the right query strings.

`ruff check` clean, `pytest -q` green; in `frontend/`: `npm run lint`, `npm run typecheck`, `npm test` green.

## Verification
1. `ruff check`, `pytest -q`; in `frontend/`: `npm run lint`, `npm run typecheck`, `npm test`.
2. `docker compose up -d --build api web`; sign in at `http://localhost:3000` as the super admin.
3. Audit log, no filter: the first 20 rows equal `docker compose exec api aslms audit search --limit 20` (same ids,
   same order). `SELECT count(*) FROM audit_log` is the same before and after every step below.
4. Period "Today": the rows equal `aslms audit search --from <today> --to <today>`; "More" continues without a gap or a
   repeat (the last row of page 1 is followed by the next older row).
5. Case: a claimed case's `ref_no` lists its `ownership.claim` row; the case page's "Audit trail" link opens the same
   search. Action "All custody actions" lists only `custody.*` rows. Office: a department lists rows by its offices
   and the units under it.
6. Open an entry of a `note.added` row: the note text shows as the digest sentence; an `office.update` row shows the
   changed fields marked. The entry URL opened in a new tab shows the same entry.
7. Person: an unknown e-mail shows "no such user" under Person; Case: a made-up reference shows "No case with this
   reference" (no CNR is invented; the field takes what the user typed).
8. Sign in as a user of the Auditor type: the Audit log entry shows and step 3 gives the same rows. Sign in as a
   department officer: no entry, and `/audit` shows the readers sentence. Grant `audit.view` alone to a department
   membership (super admin, Users → functions): still no entry, and `/audit` shows the same sentence (API 403
   `audit_scope`); revoke the grant afterwards.
9. Record in the cycle report any search taking more than 5 seconds on the dev data (with its filters).

## Open questions
None. Points for the owner to check at approval (decided here, reversible):
- Decision 3: the audit log opens on the newest entries at once; filters are kept in the page address so a search can
  be bookmarked or sent to a colleague who may read the log.
- Decision 4: the action list shows the stored codes (for example `custody.sent`) grouped under plain names, not a
  plain-words label for each of about 90 codes.
- Decision 7: links to the audit log from the case page, the user page and the office page, shown only to the super
  admin and the Auditor.
- Decision 11: the department-scoped audit view, a record of who searched the log, and export of an audit search are
  not built until you ask; each needs your rule (who reads what; whether reads are recorded; whether audit rows may
  leave the portal as a file). They move to one parked backlog row `audit-followups`. The Current Status re-run
  button is already in row 46.

## Left for later
- Row `audit-followups` (parked, decision 11): the department-scoped audit view; `audit.searched` rows; export of an
  audit search (reusing `report_export`).
- Row 46: re-running today's Current Status batches early.
- Row 42 (`audit-screens-hardening`): the API review findings (none changes this screen).
- A person picker for the Person field, if the owner wants the Auditor to choose people by name (needs a read-only
  user lookup for audit readers).

## Deviations
Written by the developer while building (14 Oct 2026); each is the smallest reading of a point the design left open.
1. `readsAudit(me)` also requires `audit.view` in `/me.functions` for the super admin membership, as the API's
   `require(audit.view)` runs before the State-wide check: a super admin whose audit access was switched off sees no
   entry and no links.
2. A URL whose own filters fail the browser checks (a hand-typed one-character name, `to` before `from`, a malformed
   record id) is not sent: the form shows the problem under its field and the search waits for a corrected Search.
3. The action list (`GET /audit/actions`) is requested once the search has answered (or at once when the URL's
   filters are not sent), so a 403 requests nothing more.
4. The 503 `search_timeout` text is the screen's own ("The search took too long; narrow the search."), passed to the
   `ErrorBanner`, because the shared text for that code belongs to the Reports screen ("Ask for fewer months").
5. With "Choose dates" the period refusal (browser or API `bad_period`) shows under "To", as on the Reports screen;
   with a quick choice it shows under "Period".
6. "Back to the search": the "View" link records the entry's id in `sessionStorage`; the entry's Back link goes back
   in the browser only for that entry, else to `/audit` (`document.referrer` does not change on client-side
   navigation).
7. The entry page treats a 422 (an id that is not a UUID) like a 404: "No audit entry with this id."
8. An `office` code in the URL that is not an active department (a unit code from a row's office link, or an inactive
   office) is kept and shown as its code in the department select, without a unit select; the units of a department
   appear only once that department is chosen.
9. "More filters" is a native `<details>` element, open when one of its filters is set or refused.
