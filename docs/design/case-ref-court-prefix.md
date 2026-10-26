# Design: Case reference numbers carry the court's code

```
slug: case-ref-court-prefix
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25 (approved in advance of the note, with the recommended answers a-h: keep year and number; GHC on all four Gauhati High Court establishments; discovery cases on the court; alerts stay on GOA; one summary audit row; office codes may not equal a court code; timeline shows the current number; old numbers looked up)
```

## Context
**Owner decision of 25 Oct 2026.** A case reference number made by the system carries the **court's code**
instead of `GOA`:
- `ASLMS/GHC/CASE/2026/054584` for the Gauhati High Court;
- later `ASLMS/SCI/CASE/…` for the Supreme Court of India. The code is `SCI`, never `SC`, because `SC` means
  Standing Counsel in the cause lists;
- district courts later, each with its own short code.

The reason: not every case is a Government of Assam matter, so the prefix should name the court the case belongs
to. **The cases held today are renumbered once, now, while the data is development-only.** This is an owner
exception to DB_STANDARD §3 ("allocated once at insert; never changed"). Records that departments create keep
their office code: notes, documents, tickets, transfers and manual next dates do not change.

The plan does not fix a reference-number format. The format comes from DB_STANDARD §3 and Appendix C, so this is
an amendment to the standard, not a deviation from the plan.

**What exists**
- `services/refno.py::allocate_ref_no(session, office_code, record_type, when)` takes one counter row per
  (office_code, record_type, year) in `ref_sequences` (Appendix C). `format_ref_no` and `parse_ref_no` /
  `REF_NO_RE` cover the format.
- `services/cases.py::get_or_create_case` is the **only** place a `cases` row is created (checked: no other
  `Case(` constructor, no raw `INSERT INTO cases`). It allocates on `ref_office`, which defaults to `ROOT_OFFICE`
  = `"GOA"`. Every creation path goes through it: cause list, dossier, court search, watchlist, data load and
  discovery. Department discovery passes the term's department code when the term's rules all belong to one
  department (design `department-discovery`, decision 8: `ASLMS/EDU/CASE/…`), and `GOA` otherwise.
- `services/cases.py::ref_no_from_url` turns the dash form into the slash form. `resolve_case_ref` accepts an
  id, a `ref_no` or a CNR, and every case route, `GET /audit?case=`, `GET /alerts?case=` and the CLI `--case`
  options go through it. `services/case_filters.py::parse` reads a typed `ref_no` as kind `ref_no` and compares
  `cases.ref_no` for equality.
- `cases.search_vector` (migration 0005, `aslms_case_search_vector`) includes `ref_no` at weight C.
- `courts` is the master of court establishments: `GAHC01` (Principal Seat at Guwahati) to `GAHC04` (Kohima,
  Aizawl, Itanagar benches), all pointing to the `high_courts` row 18 "Gauhati High Court". The seed creates the
  rows, and `services/masters.py::sync_bench_master` may add more. **No column holds a short code that fits**:
  `est_code` is NAPIX's establishment code (`GAHC01`), not a code for the court of record.
- `ALR` (alerts) is allocated on `GOA` (`services/alerts.py::REF_OFFICE`). It is a system record, not a case, so it
  stays on `GOA`.

**What the dev database holds** (read-only queries on 25 Oct 2026, at migration 0025; the historical load is still
adding cases, so the numbers grow until the migration runs):
- **54,667 cases**, all numbered `ASLMS/GOA/CASE/2026/000001` to `…/054667`, all on court `GAHC01`. No case has
  a department prefix (discovery has created none). 550 cases are provisional, 15 have no CNR and 14 are merged
  provisional rows.
- `ref_sequences` has one CASE row, (`GOA`, `CASE`, 2026), with `last_value` 54,667.
- Other places that store a case number as text, found by scanning every text, varchar, json and jsonb column of
  every table (`napix_responses` and `case_snapshots` excluded, since they hold court data only):
  - `events.payload`: 66 rows (`case_linked` 52 with `from_ref_no` / `to_ref_no`, `case_merged` 14 with
    `merged_ref_no` / `into_ref_no`);
  - `audit_log.before` / `after`: 41 rows (`case.court_duplicate_linked` 26, `case.merged` 14,
    `napix.api_tested` 1);
  - `fetch_queue.result`: 6 rows (dossier merges, `into` / `merged`).
  - `alerts`, `notifications`, `digests`, documents, notes, assistant and SourceTrace records hold no case number
    as text. There are no alerts or notifications in dev. SourceTrace is never sent a `ref_no` (connector rule).
- No office has the code `GHC` or `SCI`. The counsel code `SC, GHC` (Standing Counsel, Gauhati High Court) appears
  in cause lists, but it is a counsel code, not an office code.
- Code and tests that hard-code `GOA/CASE` or `GOA-CASE`: `services/cases.py` (a docstring), 14 backend test files
  and 22 frontend test or fixture files, including the uicheck fixtures `frontend/e2e/fixtures/synth.ts` and
  `index.ts`. No production screen text names the prefix.

**Not covered.** Supreme Court and district-court cases, and their codes: those rows come with their own items. The
format of any other record type. Changing a CNR or any court identifier.

## Decisions

### A. The standard
1. **DB_STANDARD §3 is amended, and the document becomes v1.3 (25 Oct 2026).** The new §3 text, which replaces the
   paragraph after the pattern and the table:

   > `OFFICE` is the code of the allocating office, from `offices.code`. For `TYPE = CASE` it is instead the
   > **court's code**, `courts.ref_code` of the case's court (`GHC` for the Gauhati High Court; later `SCI` for
   > the Supreme Court of India and a short code for each district court). The court's code is used however the
   > case is created: cause list, dossier, court search, watchlist, data load or department discovery. `TYPE`
   > comes from `ref_record_type`. There is one sequence per (code, type, year) in `ref_sequences` (Appendix C);
   > its column `office_code` holds the office code, or the court code for `CASE`. A `ref_no` is at most 40
   > characters. **A number is allocated once at insert and never changed: not on claim, transfer or merge.** The
   > only exception was the owner's one-time renumbering of 25 Oct 2026 (design `case-ref-court-prefix`). On
   > development data, `ASLMS/GOA/CASE/<YYYY>/<NNNNNN>` became `ASLMS/GHC/CASE/<YYYY>/<NNNNNN>` with the same year
   > and number. The API still accepts the old numbers (§3a). The API accepts a `ref_no` wherever it accepts an `id`
   > (`resolve_case_ref` accepts an `id`, a `ref_no`, an old `GOA` case number or a CNR).

   The table row for `CASE` becomes: `cases` | the court's code (`courts.ref_code`). A new line **§3a Old case
   numbers** reads: "A case number of the form `ASLMS/GOA/CASE/<YYYY>/<NNNNNN>`, in the slash or dash form, names
   the case `ASLMS/GHC/CASE/<YYYY>/<NNNNNN>`. Every `GOA` case number ever issued was a Gauhati High Court case.
   No `GOA` case number is allocated again (CHECK `ck_cases_ref_no_court`)." The `ALR` row stays `GOA`, and the
   example in the pattern line becomes `ASLMS/GHC/CASE/2026/001842`. CLAUDE.md's "DB_STANDARD v1.2" becomes
   "v1.3" (scribe).
   Alternative considered: keep v1.2 and add a footnote. Rejected because an exception to a "never" rule must be
   visible in the version history.
2. **The court's code is a new column, `courts.ref_code`** (no existing column fits, and `est_code` is NAPIX's
   establishment code). It is `varchar(10) NOT NULL` with these constraints:
   - format CHECK `^[A-Z][A-Z0-9]{1,9}$`;
   - never `GOA`;
   - **unique per court of record**: two establishments of one High Court share the code, and two different
     courts never do.

   `GHC` goes on all four Gauhati High Court establishments. The Principal Seat and the Kohima, Aizawl and Itanagar
   benches are one High Court, and the owner named "GHC for the Gauhati High Court" (open question b).
   The rule is enforced by an exclusion constraint
   `EXCLUDE USING gist (ref_code WITH =, (COALESCE(high_court_id, id)) WITH <>)`, which needs the trusted extension
   `btree_gist`. That extension ships with PostgreSQL 16, is available on the dev cluster and is created by the
   migration.
   Alternatives considered:
   - a code on `high_courts`: SCI and district courts have no row there;
   - a plain UNIQUE on `courts.ref_code`: the four benches would need four codes, which is against the owner's
     wording;
   - a plpgsql trigger: less clear than a declared constraint.

   The worst case for the 40-character limit is `ASLMS/` + 10 + `/CASE/` + `YYYY/` + 6 = 33 characters.
3. **An office code may not equal a court code.** `services/offices.py::create_office` refuses a code that is some
   court's `ref_code` (`OfficeError`, HTTP 400). The migration refuses to run if an office already holds `GHC`. The
   sequences cannot collide, because they are keyed by type, but a `GHC` office would make `ASLMS/GHC/NOTE/…`
   ambiguous to a reader (open question f).
4. **Allocation reads the court.** `get_or_create_case` loses its `ref_office` parameter and allocates with
   `allocate_case_ref_no(session, court)`, a new function in `services/refno.py` that calls
   `allocate_ref_no(session, court.ref_code, "CASE")`. If the court has no code, it raises `CourtCodeMissing`, so a
   code is never made up. `court_search.store_search_rows` and `discovery` drop `ref_office`. **Design
   `department-discovery` decision 8 is superseded:** a case first found by discovery is numbered on the court,
   like every other case (open question c). The `first_seen_source = discovery` value and the origin `discovery` of
   its recommendations stay. `cases.ROOT_OFFICE` is removed. Its only use was the case allocation, and the root
   office code `GOA` used by the offices, users and alerts code is defined there separately.
5. **Records departments create are unchanged.** `NOTE`, `DOC`, `TRF`, `NXT` and `TKT` keep the acting office's
   code. `ALR` stays on `GOA` (open question d). `REQ` is retired. Only `CASE` changes.

### B. The one-time renumbering
6. **The year and the number are kept** (the owner's recommended option). `ASLMS/GOA/CASE/2026/054584` becomes
   `ASLMS/GHC/CASE/2026/054584`. Every case keeps its sequence position. The old number maps to the new one by a
   prefix rule, with no lookup table. Every bookmark, e-mail link and piece of history text keeps resolving, and
   the sequence continues from the same counter (open question a).
   Alternative considered: fresh numbering in `created_at` order. Rejected because it needs a 54,667-row alias table
   and gives no benefit, since the numbers would come out the same.
7. **Every case row is renumbered, provisional and merged ones included.** Merged rows keep their own `ref_no`
   (design `data-load-console`), so they move with the rule too. The CNR and every court identifier are untouched.
8. **The migration refuses anything the rule cannot map.** It stops with a plain message, and changes nothing, if any
   of these holds:
   - a case number does not match `^ASLMS/GOA/CASE/[0-9]{4}/[0-9]{6}$`. A discovery-made department prefix would
     collide with a `GOA` number of the same year and number. Today there are none;
   - a case's court is not a Gauhati High Court establishment;
   - an office holds the code `GHC`;
   - a `GHC` CASE counter already exists.
9. **The sequence rows move.** Each (`GOA`, `CASE`, year) row becomes (`GHC`, `CASE`, year) with
   `last_value = greatest(the counter, the highest number held for that year)`, and the `GOA` CASE rows are deleted.
   `ref_sequences` is a counter table, not a legal record (DB_STANDARD §6 does not list it). The next case is
   `ASLMS/GHC/CASE/2026/<last_value + 1>`.
10. **`updated_at` is not bumped by the renumbering.** The migration disables the trigger `cases_updated_at` for its
   two UPDATEs and enables it again in the same transaction. A new reference number is not a change to the case's
   court data, and `updated_at` orders lists and "recently changed" views.
11. **The search vector is recomputed** with `aslms_case_search_vector(id)` for every case, because the `simple`
   parser keeps the whole `ref_no` as one lexeme, so the old one has to go.
12. **A CHECK stops `GOA` case numbers for good.** `ck_cases_ref_no_court` on `cases`:
    `ref_no ~ '^ASLMS/[A-Z][A-Z0-9]{1,9}/CASE/[0-9]{4}/[0-9]{6}$' AND ref_no NOT LIKE 'ASLMS/GOA/%'`. Matching
    the case's own court is a service rule with a test. A CHECK cannot read `courts`.
13. **One summary audit row, not one per case.** Through `aslms/db/migration_audit.py::audit_once`, action
    `case.ref_renumbered`, entity_type `system`, `actor_name` "migration <n>". `after` holds:
    - `from_prefix` `ASLMS/GOA/CASE/` and `to_prefix` `ASLMS/GHC/CASE/`;
    - `cases` (the count), `provisional`, `merged`, `first` and `last`;
    - `sequences` [{year, last_value}];
    - `rule` "same year and number";
    - `owner_decision` "2026-10-25".

    The rule is the per-case record, and 54,667 identical rows would add nothing (open question e). No event is
    raised.
14. **Reversible downgrade.** It refuses if any case number has a court code other than `GHC`, because only `GHC`
    can map back. Otherwise it drops `ck_cases_ref_no_court` and rewrites `ASLMS/GHC/CASE/` back to
    `ASLMS/GOA/CASE/` for every row, including cases created after the upgrade. Their numbers continue the same
    counter, so nothing collides. It then:
    - moves the counter rows back;
    - recomputes the vectors (trigger disabled as in decision 10);
    - drops the exclusion constraint, the format CHECK, the column and the extension `btree_gist` (created by this
      migration only);
    - calls `record_downgrade` last.

    The audit rows stay (append-only), and a re-application writes its summary row again (`audit_once` rules).
15. **Number: the next free one at build time.** 0026 is approved for `partial-code-match` (row 154). The user-type
    names of `portal-ui-polish-2` (row 153) and `storage-tidy-up` (row 156) may take 0027 and 0028. The developer
    takes the next free number and writes `down_revision` to match. It is hand-written: autogenerate cannot write
    the data steps, the exclusion constraint or the extension.
16. **It runs through the `migrate` step only**, which refuses while an `aslms_app` session is connected, so the
    worker and the load stop, and which writes a `pre-migrate` backup first. Two UPDATEs and a vector refresh over
    about 55,000 rows take minutes, with `cases` locked. That is acceptable on dev with services stopped.

### C. Old numbers keep working
17. **A rule, not an alias table.** `services/refno.py` gains `LEGACY_CASE_PREFIX = ("GOA", "GHC")` and
    `current_case_ref_no(ref_no: str) -> str`. It maps a parsed `ASLMS/GOA/CASE/<YYYY>/<NNNNNN>` to
    `ASLMS/GHC/CASE/<YYYY>/<NNNNNN>` and returns any other value unchanged. The mapping is a frozen historical fact
    (every `GOA` case number was a Gauhati High Court case), so it is a constant, not a setting.
18. **Where the rule applies:**
    - `resolve_case_ref`, after `ref_no_from_url`. That covers every `/cases/{ref}/…` route, `GET /audit?case=`,
      `GET /alerts?case=`, and the case argument of the CLI commands;
    - `case_filters.parse`, for the kind `ref_no`, so the shared filter bar and Search find a case by its old
      number.

    The resolvers of other record types (alerts, documents, notes, transfers, next dates, tickets) are unchanged,
    because their numbers never change.
19. **The API resolves and does not redirect.** `GET /cases/ASLMS-GOA-CASE-2026-054584` answers 200 with the case.
    Its `ref_no` in the body is the new one. A 308 on every case sub-route and POST action would break the relay,
    which re-sends bodies, and the clients gain nothing from it (open question h).
20. **The portal redirects.** `components/case/CaseFrame.tsx`: once the case has loaded, if the address's `[ref]` is
    a `ref_no` form (it starts with `ASLMS-` or `ASLMS/`) and differs from `refPath(c.ref_no)`, the portal calls
    `router.replace` to the same tab and query string on the new number. This is generic: no prefix rule is
    repeated in the frontend. Addresses by id or CNR are left alone. Old links in e-mails already sent therefore
    land on the new address.
21. **What is rewritten and what stays as history:**

    | Where | Holds | Action |
    |---|---|---|
    | `cases.ref_no`, `cases.search_vector` | the live number | **rewritten** by the migration |
    | `ref_sequences` (CASE rows) | the counter | **moved** by the migration |
    | `events.payload` (66 rows) | numbers at the time of the event | **stays**: append-only (`events_append_only`) |
    | `audit_log.before` / `after` (41 rows) | numbers at the time of the action | **stays**: append-only |
    | `fetch_queue.result` (6 rows) | finished job results | **stays**: a log of what ran |
    | e-mails already sent | dash-form links | cannot change; the portal redirect (decision 20) answers them |
    | alerts, notifications, digests, documents, notes, assistant, SourceTrace records | no case number as text | nothing to do |
    | uicheck fixtures, vitest and pytest fixtures | `GOA` case numbers | **rewritten** to `GHC` (one alias test keeps a `GOA` number on purpose) |

22. **History shown on screens reads the current number.**
    - **Case timeline:** `services/case_detail.py`, when it returns timeline events, passes the payload keys that
      hold case numbers (`merged_ref_no`, `into_ref_no`, `from_ref_no`, `to_ref_no`) through
      `current_case_ref_no`. Only the presented copy changes; the stored payload is untouched. The timeline then
      shows `ASLMS/GHC/CASE/…`, like every other screen.
    - **Audit entry page:** `/audit/[id]` shows `before` / `after` **as recorded**. It is evidence. A link there
      still opens the case through the alias (open question g).

### D. Portal-wide
23. **Every screen that shows a case number shows the new prefix**, with no screen change: lists, the case page,
    Case inbox, Search, Cause list, Alerts, calendar, dashboard, reports and their Excel and PDF exports, data
    collection, audit filters and e-mails. They all read `cases.ref_no`. No label, help text or message names the
    prefix today (checked), so `messages.ts` does not change.
24. **A format guard.** It has two parts:
    - a unit test scans `backend/aslms`, `frontend/src` and `frontend/e2e` for `GOA[/-]CASE`. It allows only
      `services/refno.py` (the alias constant), the renumbering migration and the alias tests;
    - a database test checks that every case created by every path matches `^ASLMS/GHC/CASE/[0-9]{4}/[0-9]{6}$`
      and that its code equals its court's `ref_code`.

## Data
New migration `00NN_case_ref_court_prefix` (next free number, decision 15). These are the schema.md changes:

- **Conventions, "Reference numbers"** (schema.md line 21) is rewritten to match §3 v1.3. The pattern becomes
  `ASLMS/<OFFICE or COURT>/<TYPE>/<YYYY>/<NNNNNN>` (`ASLMS/GHC/CASE/2026/001842`, `ASLMS/EDU/NOTE/2026/000042`).
  `CASE` is allocated on the case's court code (`courts.ref_code`); other types are allocated on the acting
  office, and `ALR` on `GOA`. The one-time renumbering of 25 Oct 2026 is recorded, and the API also accepts an old
  `ASLMS-GOA-CASE-…` number (rule in `refno.current_case_ref_no`).
- **Group 2, `courts` (master)**, added to the row: `ref_code varchar(10) NOT NULL`. It is the court's short code
  in case reference numbers (`GHC` on `GAHC01`–`GAHC04`), written by the seed and the migration, never by NAPIX
  sync. A new establishment added by `sync_bench_master` takes the code its High Court's other establishments
  already hold, and is skipped with a report error when they hold none. The row is never deleted, and FKs to it
  stay RESTRICT. Constraints:
  - CHECK `ck_courts_ref_code_format` (`ref_code ~ '^[A-Z][A-Z0-9]{1,9}$' AND ref_code <> 'GOA'`);
  - exclusion `ex_courts_ref_code_one_court` `EXCLUDE USING gist (ref_code WITH =, (COALESCE(high_court_id, id))
    WITH <>)`: establishments of one High Court share a code, and different courts never do. It needs
    `btree_gist`.

  An office code may not equal a court code; `services/offices.py` enforces this. The audit columns are unchanged
  (`created_at`, `updated_at`, `is_active`, `deactivated_at`).
- **Group 3, `cases` (transaction)**, added to the notes: CHECK `ck_cases_ref_no_court` (`ref_no ~
  '^ASLMS/[A-Z][A-Z0-9]{1,9}/CASE/[0-9]{4}/[0-9]{6}$' AND ref_no NOT LIKE 'ASLMS/GOA/%'`). `ref_no` is allocated on
  the court's `ref_code` (service rule, tested) and never changed after the renumbering of 25 Oct 2026. The
  discovery sentence at line 152, "its `ref_no` allocated on the Department-tier office of the term…", is replaced
  by "numbered on the court like every case (design `case-ref-court-prefix`, decision 4)".
- **Appendix / `ref_sequences`** (line 88), added to the notes: "`office_code` holds the office code, or for
  `CASE` the court's `ref_code`."
- **Extensions:** `btree_gist` (trusted; created by migration `00NN`).

Migration steps, upgrade, in one transaction:
1. `CREATE EXTENSION IF NOT EXISTS btree_gist`.
2. Add `courts.ref_code` (nullable), set `GHC` where `high_court_id` is the `high_courts` row with
   `napix_state_code = 18`, refuse if any court is left without a code, then SET NOT NULL and add the CHECK and the
   exclusion.
3. The guards of decision 8.
4. Disable `cases_updated_at`. Rewrite with
   `UPDATE cases SET ref_no = regexp_replace(ref_no, '^ASLMS/GOA/CASE/', 'ASLMS/GHC/CASE/')`. Then
   `UPDATE cases SET search_vector = aslms_case_search_vector(id)` and enable the trigger again.
5. Move the counter rows (decision 9).
6. Add `ck_cases_ref_no_court`.
7. Write the `audit_once` summary row (decision 13).

Downgrade: decision 14. No grant changes: `aslms_app` already has SELECT on `courts`, and UPDATE on `cases` and
`ref_sequences` is only the migration's (owner role).

## Services
- `services/refno.py`: `CourtCodeMissing`, `allocate_case_ref_no(session, court)`, `LEGACY_CASE_PREFIX` and
  `current_case_ref_no(ref_no)`. `allocate_ref_no`, `format_ref_no` and `parse_ref_no` are unchanged.
- `services/cases.py`:
  - `get_or_create_case` allocates with `allocate_case_ref_no(session, court)` and loses `ref_office`;
  - `ROOT_OFFICE` is removed;
  - `resolve_case_ref` applies `current_case_ref_no` after `ref_no_from_url`;
  - the `ref_no_from_url` docstring example becomes `ASLMS-GHC-CASE-2026-001842`.
- `services/court_search.py::store_search_rows` and `services/discovery.py` drop `ref_office` and the
  term-department choice. The discovery docstring at line 691 is updated.
- `services/case_filters.py::parse`: the `ref_no` kind carries `current_case_ref_no(ref_no)`.
- `services/case_detail.py`: the timeline presentation maps the four payload keys (decision 22).
- `services/offices.py::create_office`: refuses a court's `ref_code` (decision 3). This writes no audit row,
  because a refused create changes nothing.
- `services/seed.py`: `GAUHATI_HC_COURTS` gains `ref_code` `GHC`. `seed_courts` sets it on insert and fills a
  missing one.
- `services/masters.py::sync_bench_master`: a new establishment takes its High Court's existing code, or is
  skipped with an error in the report (no fabricated code).
- Audit: the migration's summary row only. Allocation is unchanged in kind, and a case's creation is already
  recorded as the `case_created` event.

## API
No new endpoint and no change to any endpoint's `Permission`. Behaviour changes:
- every route taking a case `{ref}` (functions as today: `cases.view_scope` and the route's own function)
  resolves an old `GOA` case number to the case. The response's `ref_no` is the new one, and visibility is
  checked on the resolved case exactly as before;
- `GET /cases?q=ASLMS/GOA/CASE/…`, the shared filter `q` and `GET /cases/search` find the case by its old number;
- `GET /audit?case=` (`audit.view`) and `GET /alerts?case=` (the function it needs today, unchanged) accept an old
  number;
- `POST /admin/offices` (`offices.manage`) answers 400 for a code that is a court's code.
- `frontend/openapi.json` and `schema.d.ts` do not change, because no shape changes.

Frontend: `CaseFrame` redirect (decision 20); fixtures and tests rewritten to `GHC`. Nothing else.

## Jobs
None. The migration is run once with the `migrate` step (decision 16). The historical load resumes on the same
counter afterwards.

## Tests
Unit (`backend/tests/unit/`):
- `test_current_case_ref_no_maps_goa_to_ghc_with_same_year_and_number` (slash form; dash form after
  `ref_no_from_url`).
- `test_current_case_ref_no_leaves_other_numbers_alone` (GHC, NOTE, DOC, ALR on GOA, a non-ref string).
- `test_no_goa_case_numbers_in_code` (decision 24, with its allow-list).
- `test_case_filters_ref_no_kind_uses_current_number`.

Database (`backend/tests/db/`), on the test database, never the dev database `aslms`:
- `test_every_creation_path_numbers_on_the_court`, parametrised over cause list, dossier, court search, watchlist,
  data-load single fetch and discovery: each ref is `ASLMS/GHC/CASE/<year>/<n>`, its code equals
  `court.ref_code`, and **discovery no longer uses the department code**.
- `test_case_without_court_code_is_refused` (no fabricated identifier: `CourtCodeMissing`, no row, no counter
  consumed).
- `test_ck_cases_ref_no_court_refuses_goa_and_bad_format`.
- `test_courts_ref_code_format_and_one_code_per_court` (four Gauhati establishments share `GHC`; another High
  Court's court cannot take `GHC`; `GOA`, lower case and 11 characters refused).
- `test_office_code_equal_to_court_code_refused`.
- `test_resolve_case_ref_accepts_old_number` (slash and dash forms, by API `GET /cases/ASLMS-GOA-CASE-…` → 200 and
  the new `ref_no`).
- `test_old_number_does_not_widen_visibility`: a user who cannot see the case gets the same 404 for the old number,
  the new number and the CNR.
- `test_audit_and_alert_filters_accept_old_number`.
- `test_timeline_shows_current_number_for_stored_payload` (a `case_merged` event with a `GOA` payload shows `GHC`;
  the stored payload is unchanged).
- `test_bench_sync_gives_new_establishment_the_high_court_code` and `..._skips_without_one`.
- `test_migration_case_ref_court_prefix` (modelled on `test_migration_0016` / `0022`), on the test database:
  - seed 0025-era rows: GOA cases including provisional, CNR-less and merged rows, a GOA CASE counter, a `GOA` ALR
    and an EDU NOTE counter, and an event and an audit row carrying a GOA number;
  - **up**: every case is GHC with the same year and number; the CNR column is identical (compared by
    `md5(string_agg(cnr, ',' ORDER BY id))`); `updated_at` is unchanged; the search vector finds the new number;
    the counter is moved; the NOTE and ALR counters are untouched; events and audit rows are unchanged; one
    `case.ref_renumbered` row;
  - **next allocation** continues at `last_value + 1` on GHC;
  - **down**: the GOA numbers are back, counters back, column, constraint and extension gone;
  - **up again**: same state, and a second summary row (re-application recorded);
  - **guards**: a department-prefixed case, an office `GHC` and an existing GHC counter each stop the upgrade with
    nothing changed; a non-GHC case code stops the downgrade.
- `test_migrations.py` round trip and `compare_metadata` empty, with the model carrying `ref_code`, the CHECK and
  the exclusion.

Frontend (vitest): `CaseFrame` replaces an old-number address with the new one and keeps the tab and query; an
id or CNR address is not replaced. All fixtures use `GHC`. uicheck: `SAMPLE.caseRef` = `ASLMS/GHC/CASE/2026/000001`,
and one uicheck step opens the old dash form and lands on the new address.

## Verification
1. `ruff check` clean, `pytest -q` green, frontend `npm test` green.
2. On a scratch database created and dropped by the developer (never `aslms`): restore a copy of the dev dump,
   then `alembic upgrade head`, `downgrade -1`, `upgrade head`. Expected: case count unchanged, 0 rows
   `WHERE ref_no NOT LIKE 'ASLMS/GHC/CASE/%'`, the CNR checksum equal before and after, and
   `(GHC, CASE, 2026).last_value` equal to the old GOA value.
3. On dev, after merge (owner step): `docker compose stop api worker scheduler`,
   `docker compose --profile ops build migrate`, `docker compose --profile ops run --rm migrate`, then
   `docker compose up -d`. Check:
   - `SELECT count(*) FROM cases WHERE ref_no LIKE 'ASLMS/GOA/%'` is 0;
   - `SELECT * FROM ref_sequences WHERE record_type = 'CASE'` shows one GHC row per year;
   - the next case created by the load is `ASLMS/GHC/CASE/2026/<last + 1>`;
   - one `case.ref_renumbered` row in `GET /audit?action=case.ref_renumbered`.
4. Browser at http://localhost:3000: open `/cases/ASLMS-GOA-CASE-2026-000001/orders`. It lands on
   `/cases/ASLMS-GHC-CASE-2026-000001/orders`. Search for `ASLMS/GOA/CASE/2026/000001` finds the case. The Case
   inbox, Cause list and dashboard show `ASLMS/GHC/CASE/…`. A merged case's timeline names the provisional number
   with `GHC`.
5. `docker compose --profile uicheck run --rm uicheck` passes the redirect step.

## Open questions
The owner decides these at approval. Each recommended answer is the one written into the design above, so the
design is complete as it stands; a different answer changes only the decision named.
- **a. Number kept or fresh?** Recommended: **keep the year and number** (decision 6). Old numbers then resolve by
  rule, and the counter simply continues.
- **b. Which establishments carry `GHC`?** Recommended: **all four Gauhati High Court establishments** (Principal
  Seat, Kohima, Aizawl, Itanagar), as one High Court (decision 2). Separate bench codes would be a later change to
  their rows, and the cases there are not renumbered.
- **c. Discovery-made cases?** Recommended: **numbered on the court too**, as the owner's "every way a case is
  created" says. This supersedes `department-discovery` decision 8 (decision 4).
- **d. Alerts (`ALR`)?** Recommended: **stay on `GOA`**. An alert is a system record, not a case, and its number is
  not court-specific (decision 5).
- **e. Audit of the renumbering?** Recommended: **one summary row** with counts, range, counters and the rule, and
  no per-case rows or events (decision 13).
- **f. Office codes equal to a court code?** Recommended: **refused** (`GHC` now, `SCI` and district codes as they
  are added). An office for the High Court's own administration would take another code (decision 3).
- **g. Old numbers inside history on screens?** Recommended: the **case timeline shows the current number**, and
  the **audit entry page shows what was recorded**, with working links (decision 22).
- **h. API redirect or resolve?** Recommended: the **API resolves** an old number and answers with the new
  `ref_no`, and the **portal** replaces the address (decisions 19–20).

## Deviations
Recorded by the developer while building (the smallest reasonable choice each time; no business rule changed).
1. **Migration number 0028** (decision 15: the next free number; 0026 and 0027 are taken). Autogenerated against the
   dev database (it found only `courts.ref_code`), then written by hand.
2. **The guards run first.** The upgrade checks decision 8's four guards before creating the extension or the
   column, not after (Data, step 3). A refusal rolls the whole transaction back either way; checking first only makes
   the message come before any work.
3. **No summary row on an empty database.** The `case.ref_renumbered` row is written only when there was something to
   renumber (a case or a `GOA` CASE counter). A fresh database built by `alembic upgrade head` has nothing to record,
   and an audit row saying "0 cases renumbered" would mislead. Every database with cases gets the row.
4. **The timeline test uses `case_linked`.** `case_merged` is not one of the event types the case timeline shows
   (`COURT_EVENTS` / `OWNERSHIP_EVENTS` in `services/case_detail.py`), so a merged case's timeline never displays its
   `merged_ref_no` today. The presentation maps all four keys (`merged_ref_no`, `into_ref_no`, `from_ref_no`,
   `to_ref_no`) as decision 22 says, and the database test stores a `case_linked` event carrying all four keys with
   `GOA` numbers. Verification step 4's "a merged case's timeline names the provisional number with GHC" therefore
   cannot be seen in the browser; a court-duplicate link (`case_linked`) shows its numbers with `GHC`. Showing
   `case_merged` on the timeline would be a separate change.
5. **`seed_courts` sets the code on insert only.** "Fills a missing one" cannot happen: the column is NOT NULL, so every
   existing row already holds a code (the migration gives it one or refuses).
6. **The bench sync also skips a new establishment when its High Court holds more than one code** (not only none),
   because the code to take is then ambiguous. `MasterReport` gains `errors` (a list of plain messages), printed in red
   by `aslms sync-masters`.
7. **The format guard** (decision 24) also catches the URL-encoded (`GOA%2FCASE`) and regex-escaped (`GOA\/CASE`) forms,
   which the first fixture rewrite missed. Its allow-list: `services/refno.py`, the migration, the backend alias tests
   (outside the scanned trees), `frontend/src/lib/refs.test.ts`, `frontend/src/components/case/caseRefRedirect.test.tsx`
   and `frontend/e2e/fixtures/legacy.ts` (the old number the uicheck step opens).
8. **Frontend test layout.** The portal redirect is a pure helper `currentCaseHref` in `src/lib/refs.ts`, called by
   `CaseFrame` once the case has loaded. The case-page detail fixture moved from `case.test.tsx` to
   `src/test/caseDetail.ts` so the new `caseRefRedirect.test.tsx` can share it. The uicheck step is a test of its own in
   `e2e/uicheck.spec.ts`, using the constant from `e2e/fixtures/legacy.ts`.
9. **DB_STANDARD v1.3** is written in this change (decision 1); CLAUDE.md's version mention stays for the scribe.
10. **One more reader of a stored number.** `services/napix_inspect.py::params_shown` decides whether a past System
    health send's sample values may be shown by looking up the case named in its audit row (`after.sample.case_ref_no`);
    the dev database holds one such `napix.api_tested` row with a `GOA` number. The lookup now passes the stored number
    through `current_case_ref_no`, so the values stay visible to a reader of that case and to no one else (tested). The
    audit row itself is unchanged. `causelist_view` reads the parsed query of `case_filters`, so it already maps.
11. **Two older migration tests** build their 0017- and 0015-era rows differently, because today's ORM `Court` carries
    `ref_code`: `test_migration_0018` makes its case at head before downgrading, and `test_migration_0016`'s seed leaves
    out the courts step below 0028 (as it already left out the scoring settings below 0027).
