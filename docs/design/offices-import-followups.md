# Design: Offices import follow-ups (the four review advisories of row 257)

```
slug: offices-import-followups
status: awaiting-approval
author: architect
date: 2026-11-14
approved_by: 
```

## Context

Backlog row 261 records the four advisories from the review of row 257 `offices-import` (report
`docs/reports/2026-11-14-offices-import.md`, "Review findings"). None blocked the merge. Row 257 was deployed on
14 Nov 2026 at 23:06 with migration 0036. The import has **not been run** on the owner's workbook yet: the dry run
and the apply wait for the filled copy. Each advisory is a way the dry run could give the owner a wrong or
incomplete listing, or a second run could plan work that is already done. They need fixing before the first real run.

The plan does not change. It names "departments, directorates and offices, in the government hierarchy", and the
designations a person holds ("each note records the author's name, designation and office at the time"). The
design `offices-import` (approved 14 Nov 2026) stays in force. This note narrows four of its rules (decisions 8, 10,
11 and 13) and keeps everything else.

**What exists (checked 14 Nov 2026 on `main` at 0483c8f, `backend/aslms/services/offices_import.py`, openpyxl 3.1.5):**
- **(1) Stale stored dimension.** `read_workbook` opens the file with
  `openpyxl.load_workbook(..., read_only=True, data_only=True)`, and `_rows` walks `ws.iter_rows(values_only=True)`.
  In read-only mode, `ReadOnlyWorksheet._cells_by_row` stops at `max_row` and cuts each row at `max_column`. Both come
  from the sheet's stored `<dimension ref="…"/>` element. Excel and openpyxl write that element correctly, but other
  tools (some LibreOffice saves, online converters, scripts that append rows) can leave it stale. Then:
  - rows below the stored range are dropped silently;
  - columns to the right of it are cut, so an optional column such as Website is dropped silently, or a required
    column gives a misleading "no column" error;
  - a range that claims far more rows than exist (`A1:Z1048576`) makes the reader produce a million empty rows
    before it ends.

  openpyxl's documented remedy is `ws.reset_dimensions()`. It sets `_max_row` and `_max_column` to `None`, so the
  parser reads every row in the XML and nothing more.
- **(2) Codes on skipped rows.** `_Checker.departments()` and `_Checker.office()` return early for Include? = No
  (`include_no`) and for To Decide or blank (`include_wait`). That happens *before* `check_code`, which is the only
  place a code enters `codes_seen`, so a code on a skipped row is never compared:
  - Departments row 10 "No" and Offices row 30 "Yes" can share `HFW-X` and the dry run says nothing. The owner
    finds out only when row 10 is later switched to "Yes".
  - The parent index built in `departments()` registers each department row's code with `index.setdefault`, so the
    first row wins. If a "No" department and a "Yes" department share a code, an office that names its parent by
    that code is reported as `parent_left_out`, which is misleading.
- **(3) Inactive designations.** `_Checker.designation` sorts the designations active first and then accepts the
  first match by code or name, **including an inactive one**, and reports nothing. `memberships.insert_membership`
  and `offices.resolve_head` accept any existing designation id. So `--apply` would give a new head, administrator
  or office head a designation that Administration has turned off. That designation is hidden in every portal picker
  (`set_designation_active`: "the pickers hide them"). On the dev database today all 19 designations are active.
- **(4) Names over 200 characters.** `check_existing` plans a rename when `name != existing.name` and stores
  `name[:200]`. The column is `offices.name varchar(200)`, and `update_office` and `create_office` also cut at 200.
  For a workbook name over 200 characters, the stored name never equals the full name. So every run plans the
  rename again: a `rename` notice, `has_changes` true, and an `office.update` audit row that changes nothing. A second
  run never answers "nothing to change". This breaks decision 15 of `offices-import`.

  The same fault exists for a **new designation** typed over 200 characters. `NewDesignation.name` is `typed[:200]`,
  and the next run matches the full typed text against the stored cut name and fails. It then plans *another*
  designation with the code suffix `_2`. The portal refuses both cases: `OfficeCreateIn.name` and
  `OfficePatchIn.name` have `max_length=200`, and designation text fields also have `max_length=200`.

**Not covered:** any new problem in the workbook format, the No Head Yet rule, SEC-EDU, the welcome mail, the portal.
No schema, API or frontend change.

## Decisions

1. **Reset the stored dimensions before reading a sheet (advisory 1).** `read_workbook` calls `ws.reset_dimensions()`
   on the Departments and Offices Under Departments worksheets right after `_sheet` finds them, before `_rows`. It
   is a plain call because `read_only=True` always gives a `ReadOnlyWorksheet`. `_rows` already accepts rows of
   different lengths (`values[i] if i < len(values) else ""`), and trailing empty rows are already skipped as empty.
   So nothing else changes. The 5 MB file cap stays, and it bounds how many rows the XML can hold.
   *Alternatives:* `read_only=False` (it reads the whole workbook into memory and computes the dimension itself; it
   is slower, and keeping read-only mode was the reviewed choice); comparing the stored dimension with the rows read
   and refusing the file (it refuses a workbook that can be read correctly).

2. **Every row's code is checked for duplicates, whatever its Include? says (advisory 2).** A new first pass,
   `_Checker.register_codes()`, runs at the start of `run()` before `departments()`. It walks the Departments rows
   and then the Offices rows in sheet order, and collects each row whose code (trimmed, upper case) matches
   `OFFICE_CODE_RE`. Empty codes and malformed codes are left out of this pass. A malformed code on an included row
   already gets `bad_code` or `code_too_long`, and one problem per cell is enough. For each code found on more than
   one row:
   - **At least one of the rows has Include? = Yes:** the first such row in sheet order keeps the code and is
     checked as usual. Every other row with that code gets `duplicate_code_in_file` (**error**, column "Code"),
     whether it is included, left out or waiting. The message names the row that keeps the code and its state, for
     example "the code is also used on Offices row 30 (included)", or on a skipped row "… (Include? = No) — every row
     needs its own code, even one left out".
   - **None of the rows is included:** nothing is reported. A skipped row's other cells are not checked either
     (decision 13 of `offices-import`), and the clash is reported as soon as either row says Yes.

   `check_code` keeps the format checks. It no longer keeps its own `codes_seen` map. It returns `None` for a row the
   first pass marked, without adding a second problem.

   *Why an error, even on a row that is left out:* the error costs the owner one cell to fix. Without it, an office
   that names its parent by that code can resolve to the wrong row in the same run (the `index.setdefault` case
   above), and a later run fails on the clash. The blocking error makes the misleading `parent_left_out` harmless,
   because the file cannot be applied until the code is fixed.
   *Alternatives:* a notice when one row is skipped (the index ambiguity would go unreported, so a misrouted parent
   could reach `--apply`); reporting clashes between two skipped rows too (it checks cells of rows the owner has not
   decided on, which `offices-import` decision 13 does not do).

3. **A turned-off designation is refused for a new membership (advisory 3).** Matching still prefers an active
   designation: a typed text that matches an active row by code or name uses it, as today. When the only match is
   an inactive designation:
   - It is still matched, never re-created under a second code with the same name. The checker remembers its code in
     `self.inactive_designation_codes`.
   - `plan_membership` is called only for a membership the run would create: a head `create_with` / `set`, an admin
     `add`, an office head `add`. If the person's designation code is in that set, it adds `designation_inactive`
     (**error**, column "<Head | Admin | Office Head>: Designation", message 'the designation "<name>" (<code>) is
     turned off in ASLMS; turn it on in Administration → Designations, or type another') and plans nothing.
   - A row matched to an **existing** membership (head or admin `match`, office head `match`) writes nothing. So an
     inactive designation there is not reported. This keeps a later run from being blocked because a designation was
     turned off after the first run.

   *Alternatives:* a notice and use it anyway (the import would do what no portal picker allows); reactivating it
   during `--apply` (it hides an Administration decision inside a data load); treating it as unknown and creating a
   new one (two designations with one name).

4. **Office names and new designations over 200 characters are errors, and the rename test compares what would be
   stored (advisory 4).**
   - A Department Name or Office Name longer than 200 characters (after `clean`) is `bad_name` (**error**, the name
     column, "the name has N characters; an office name is at most 200"). This matches the portal's
     `max_length=200`. The row is not planned.
   - A designation typed for a person that is longer than 200 characters, and that matches no existing designation,
     is the new problem `bad_designation` (**error**, column "<label>: Designation", "the designation has N
     characters; a designation is at most 200"). The length check runs before matching. A long text cannot match any
     stored name, so the check only ever fires on text that would have become a new designation.
   - With both checks in place, every name the plan stores is the cleaned workbook text itself. `check_existing`
     plans a rename only when that text differs from `existing.name`, so a second run finds them equal and plans
     nothing. The `[:200]` cuts in the plan become dead code and are removed from `offices_import.py`. They stay in
     `offices.py`, whose other callers are unchanged.

   *Alternatives:* comparing `name[:200]` with the stored name and storing the cut name with a notice (the import
   would store a name the owner did not write, which the portal refuses); leaving designations as they are (the same
   fault, a new `_2` designation on every run).

5. **The fingerprint and the earlier dry runs.** These decisions change the plan's problems and, through decisions
   2 to 4, which actions are planned. `ImportPlan.canonical()` and `fingerprint()` are unchanged. A fingerprint
   printed by a dry run before this change may no longer match, and `--apply` refuses it with exit 3 as designed. No
   real dry run has been approved yet, so nothing is lost. The runbook already says to run the dry run again before
   `--apply`.

## Data

No table, column, reference code or migration. `schema.md` is unchanged.

## Services

`backend/aslms/services/offices_import.py` only:
- `read_workbook`: `ws.reset_dimensions()` on both data sheets before `_rows` (decision 1).
- `_Checker.register_codes()` and the set of rows it marks; `run()` calls it first; `check_code` drops `codes_seen`
  and returns `None` for a marked row (decision 2).
- `_Checker.designation`: the length check (`bad_designation`), active-first matching kept, inactive codes remembered
  in `self.inactive_designation_codes`. `plan_membership` adds `designation_inactive` (decision 3).
- `department()` and `office()`: `bad_name` for names over 200 characters before any other check of the row. The
  `[:200]` cuts on names are removed (decision 4).
- The problem-code list in the module docstring and the design's list gain `designation_inactive` and
  `bad_designation`. `duplicate_code_in_file` and `bad_name` keep their codes with wider use.
- No other module changes. No audit row and no event changes: the dry run writes nothing, and `--apply` writes the
  same rows as before, minus the empty `office.update` rows the rename fault made.

Docs: `docs/operations.md` section 24 gains two lines under the dry run: "Every row needs its own code, even one left
out or waiting" and "A designation turned off in Administration → Designations is refused for a new head,
administrator or office head; turn it on or type another". The scribe adds the decisions-log entry.

## API

None. The import stays a command-line tool (`aslms offices import`). It acts as the Super Administrator and needs
`offices.manage`, `users.create` and `admin.designations` through the services, unchanged.

## Jobs

None.

## Tests

Unit (`backend/tests/unit/test_offices_import_read.py`). The workbook comes from `tests/offices_workbook.py`, and a
new helper `with_stale_dimension(data, sheet_title, ref)` rewrites the `<dimension ref>` of that sheet's XML inside
the zip. It finds the sheet file through `xl/workbook.xml` and its relationships, not by number.
- `test_stale_dimension_short_reads_every_row`: 6 department rows and 8 office rows, with each sheet's dimension set
  to `A1:E5`. Every row and every column, Website included, is read.
- `test_stale_dimension_oversized_reads_only_real_rows`: dimension `A1:Z1048576`. The rows read equal the real rows,
  and the read finishes without producing the empty tail. The test asserts the row count, not a time.

Unit (`backend/tests/unit/test_offices_import_rules.py`, faked lookup):
- `test_code_shared_by_left_out_row_and_included_row_is_error`: both orders (skipped first, included first) and both
  sheet pairings. The included row is planned, the other row carries `duplicate_code_in_file`, and the plan has errors.
- `test_code_shared_by_waiting_row_and_included_row_is_error` (To Decide and blank Include?).
- `test_code_shared_by_two_included_rows_still_error_on_later_row` (today's behaviour kept).
- `test_code_shared_only_by_skipped_rows_not_reported`.
- `test_malformed_code_reported_once`: an included row with a bad code that a skipped row repeats gets only
  `bad_code`.
- `test_inactive_designation_refused_for_new_membership`: a head, an admin and an office head on a new department or
  office each give `designation_inactive`, and no new designation is planned.
- `test_active_designation_preferred_over_inactive`: the typed text matches an inactive row's code and an active
  row's name. The active one is used and nothing is reported.
- `test_inactive_designation_ignored_for_matched_membership`: an existing head whose row names a now-inactive
  designation gives no problem.
- `test_office_name_over_200_is_error` (Departments and Offices) and `test_name_of_exactly_200_accepted`.
- `test_designation_over_200_is_error_and_not_planned`.

Database (`backend/tests/db/test_offices_import.py`):
- `test_inactive_designation_refused_then_accepted_after_reactivation`: the dry run reports the error. After
  `set_designation_active(..., True)` the dry run is clean, and `--apply` gives the membership that designation.
- `test_second_apply_changes_nothing_with_200_character_name`: an office created through the import with a
  200-character name. The second dry run plans no rename and answers "nothing to change", and the second apply writes
  no `office.update` row.
- `test_new_designation_matched_on_second_run`: a new designation of 200 characters is created once. The second run
  matches it, and no `_2` code appears.
- The existing `test_second_apply_changes_nothing` and `test_output_has_no_names_or_mobiles` stay green. The new
  messages print codes and masked e-mails only.

## Verification

The integrator, on the branch, then on `main` after the merge:
1. `ruff check` is clean and `pytest -q` is green. No frontend change, so `vitest`, `tsc` and `lint` are not needed.
2. Build the import image: `docker compose build api`. No migration and no `init`. Recreate the app services with
   the court-data switch carried, as usual.
3. A smoke dry run with a test workbook built by `tests/offices_workbook.py` in a scratch directory outside the
   repository: `docker compose exec -T api aslms offices import - < <scratch>.xlsx`. Use one office whose code a
   left-out department repeats, and one head with a designation turned off in Administration before the run
   (audited as usual). Expect exit 1 with `duplicate_code_in_file` and `designation_inactive` listed,
   e-mails masked, and no names or mobiles printed. Take the counts of `offices`, `users`, `user_memberships`,
   `designations` and `audit_log` just before and just after the dry run (read-only); they are equal. Turn the
   test designation on again afterwards.
4. The owner's workbook is not needed for this row. Its first dry run (row 257's deployment steps) uses this build.

## Open questions

None.
