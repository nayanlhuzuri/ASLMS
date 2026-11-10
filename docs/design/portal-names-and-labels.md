# Design: Portal names and labels (office names, Title Case server labels, one label helper, case Details labels, audit action names)

```
slug: portal-names-and-labels
status: proposed
author: architect
date: 2026-11-10
approved_by: (pending)
```

## Context
Backlog row 232, row B of the portal UI review (row 230, `docs/reviews/2026-11-10-portal-ui-review.md`). The owner
approved the review on 10 Nov 2026 (decisions log, "Portal UI review approved; rows 228 and 229 approved"):
- every High and Medium finding is fixed, and Low ones in the same files;
- K3 option (a): server labels are put in Title Case by the portal when shown, with no data change and no migration;
- U1: the Audit Log shows action names to the Auditor, with the code kept on the entry page. This changes row 41's
  design (`docs/design/portal-audit-health.md`, decision 5).

Build order: after row 231 `portal-ui-kit-fixes` and row 228 `dashboard-my-work-polish`, before rows 233, 234 and 229.

**This row covers:**

| Finding | Severity |
|---|---|
| K2: office names where codes show | High |
| K3: server labels in Title Case | High |
| P9: case Details tab labels | High |
| K4: one label helper and an enum-label test | Medium |
| U1: audit action names | Medium |
| P4: order kind on the Latest Order card | Medium |
| R1: report titles and column headers | Medium |
| R2: report code columns | Medium |
| D1: Needs Your Attention strings | Medium |
| S3, A3, L2, C3, P12's case wording | Low |
| P3 and L1, closed by the K2 sweep (review, "Proposed build rows" item 3) | Medium |

**What is there now (checked at 6dd84d3).**
- *Office names.*
  - `offices` has `code` (unique) and `name` (up to 200 characters). There is no short name column.
  - Most response objects carry only the office code (review K2, "Cause"). Only these carry names:
    `PrimaryOwnerOut.office_name`, the cause-list `names` map, `OfficeRefOut`, the dashboard's `custody_by_office`,
    and, from row 228, `DashboardOwnCasesOut.department_name`.
- *Who may read office names today.* The rules, read in the code:
  - `GET /custody/recipients` (`cases.view_scope`) lists every active Department-tier office to every case reader.
    With `?department=` it lists every active office inside that department (`services/custody.py::recipients`).
  - `GET /admin/offices` and `/tree` (`users.view`) are limited to the caller's subtree. Inactive offices need
    `offices.manage` there, because the list is an administration screen used for reactivation.
  - `GET /admin/offices/choices?purpose=audit` gives every office, inactive ones included, to a State-wide holder of
    `audit.view`.
  - The codes of inactive offices remain in history: custody legs, note authors, audit actor snapshots
    (`audit_log.actor_office_code`).
- *Title Case.* `frontend/src/lib/titleCase.ts` and `backend/aslms/core/titlecase.py` share one rule, pinned by the
  same tests in both suites (design portal-ui-polish-2, decision 2). The portal guard (`labels.test.ts` with
  `labelRules.ts`) covers only `T`. Nothing applies `titleCase()` to a server label: `labelOf`
  (`lib/api/hooks.ts:50`) returns the stored label, or else the raw code.
- *Where server labels reach the screen.*
  - `GET /reference/labels`: user types, office kinds, ticket kinds and alert kinds, all from `ref_*` tables.
  - Fields in other responses:
    - `kind_label`: alerts and notes;
    - `doc_type_label`;
    - `pending_action_label`, from `PENDING_ACTION_LABELS` in `domain/workflow.py:65-79`;
    - `reason_label`, `role_label`, `group_label` and `response_mode_label`;
    - stage `label`, timeline `label`, `NoteKindOut.label`, `DocumentTypeOut.label` and `PendingActionOut.label`;
    - the dashboard attention `title`.
  - The seed writes these labels in sentence case (`seed.py:54-55`, `76-81`, `98-110`, `156-200`).
- *Details tab.* `frontend/src/components/case/Details.tsx:19-22`, `fieldLabel`, turns API keys into labels
  ("Reg no", "Date filing disp"). The keys are the column groups of `services/case_detail.py:54-125`, plus the
  list-block dicts built inline in `overview()` (`:322-383`).
- *Audit actions.* Actions are free strings passed to `services/audit.py::write_audit`. A scan of the code finds about
  115 distinct codes. Several are built at run time, for example `f"{entity}.{action}"` in
  `services/matching_rules.py`, and the `data_load.collect_*` codes. `T.audit.actionNames` names 3 of them.
- *Reports.* `services/reports.py`:
  - `CATALOGUE` titles, `Section` titles and `Column` labels are in sentence case.
  - Code columns sit beside name columns.
  - `Column("holder_office_code", "Holder office")` (`:714`) shows a code under a name label.
  - `generated_by` carries `office_code` only, and `report_export.generated_by_text` prints it ("…, GOA").

**Not covered (out of scope).**
- Layout and screen-specific fixes:
  - row 231: K1, K5, K6, K11, the alert row header of A2;
  - row 233: I1-I5, P1, P2, P5-P8, P10, P11, the rest of P12, P13, A4, C1's score format, C2's "Requested" wording,
    D2, D3;
  - row 234: S1, S2's layout, R3, U2's record id, AD1-AD4's layout, DC1, DC2, Y1, Y2.

  This row changes only which words those screens show. Office codes become names, and labels move to Title Case.
- Colour meanings (K7, A1, C4): row 229.
- **Alert titles and e-mail texts that embed office codes**, for example "Transfer requested by EDU: …" and "Case
  received from EDU: …" (`alert_rules.py:278-453`). They are rendered when the alert is raised and stored in
  `alerts.title` and `alerts.body`, so the portal cannot rename them. Open question 3.
- **Server label data.** No `ref_*` row is relabelled (owner's option (a)). E-mails and exports that carry a `ref_*`
  label keep its stored sentence case. The alert kind label `next_date_review` ("Next date to review") stays as
  stored and is shown as "Next Date to Review" (A3 covers only the portal's own wording).
- Fixture realism for the screen check (review, last bullet). Only the one fixture this row needs is added
  (decision 8).
- No table, column, reference code or index changes. **No migration.**

## Decisions

### A. Office and department names (K2, with P3, L1 and the name part of C1, C2, C3, S2, U2, AD2)

1. **One read-only endpoint, `GET /reference/offices`, returns the name of every office.**
   - **Content.** Every office, active and inactive, at every tier, ordered by `path`. Each item has `code`, `name`,
     `kind`, `tier` (`state` / `department` / `directorate`, from `services/offices.py::tier_of`), `department_code`
     and `is_active`.
     - `department_code` is the Department-tier ancestor's code (the office's own code for a department), or null at
       the State tier. It comes from `path`, with the same rule as `access.department_of`.
     - Nothing else is returned: no notes, parent id, head, counts or people.
   - **Alternatives considered.**
     - About a dozen `*_name` fields on the response objects the review lists. Refused: each is its own join and
       test, and the next response would forget it.
     - `GET /admin/offices/choices` with a new purpose. Refused: that endpoint serves pickers bound by a function's
       scope. This one serves display, which needs every code a reader can come across.
2. **Gate: `require_any(cases.view_scope, cases.view_all, users.view, audit.view)`.**
   - These are the functions behind every screen that shows an office code: case screens, Administration, the Audit
     Log. By default every user type holds at least one of them (`access_seed.DEFAULT_MATRIX`), and the super admin
     holds all.
   - A login with no office yet (row 176) holds no function, so it gets 403. The portal then shows codes, and such a
     login sees no case anyway.
   - Logins in the first-sign-in steps get 403 through `current_user`.
   - **Visibility is unchanged.**
     - Office names are not case data. Case readers already see the name of every active department and its units
       through `/custody/recipients`.
     - No case, note, document or person is reachable through this endpoint.
     - The State → Department → Directorate tiers keep governing what a reader may *open*, not which office names
       they may read.
   - **Inactive offices are included** (open question 1). Their codes stand in old custody legs, notes and audit rows.
     Without the names, those rows would keep showing codes.
     - The `offices.manage` rule on `GET /admin/offices?include_inactive=true` is about the administration list (what
       may be reactivated), not about secrecy.
     - The State auditor already reads inactive names through `choices?purpose=audit`.
3. **No audit row.** The endpoint only reads, like the other `/reference/*` endpoints.
4. **Caching.**
   - The response carries `Cache-Control: private, max-age=300`.
   - The portal's `useOfficeNames()` (TanStack Query, key `["reference", "offices"]`) uses `staleTime` 10 minutes
     and `gcTime` 60 minutes.
   - It is invalidated after every office create, edit, deactivate and reactivate made in Administration, which is
     where those writes happen in the portal.
   - There is no paging. An office tree is hundreds of rows. The database test asserts the endpoint runs in at most
     2 statements.
5. **A kit component, `OfficeName`, in `frontend/src/components/ui/`, is the one way an office is shown.**
   - Props: `code` (string or null), optional `name`, optional `href`.
   - **Name source.**
     - A `name` from the payload wins. This keeps `PrimaryOwnerOut.office_name`, the cause-list `names`, row 228's
       `department_name` and `custody_by_office.office_name` on the same path.
     - Otherwise the name comes from `useOfficeNames()`.
   - **Look.**
     - The text is the name in the body font, never `mono`.
     - Its `title` is the code, with " · Inactive" added for an inactive office.
     - A long name is cut with an ellipsis inside table cells and wraps elsewhere.
   - **Fallbacks.**
     - While the map loads, after a 403, or for a code the map does not hold, it shows the code as plain muted text.
       It never invents a name.
     - A null code shows "—".
   - **Links.** With `href` it renders a `Link`. The Audit Log uses this to narrow by office, keeping row 41's link.
   - **Helper.** `officeName(code, map)` is the same rule as a pure function. It is used in strings: `T.inbox.fromTo`,
     `T.inbox.best`, `T.claim.poolBest`, `T.claim.transferFrom`, `T.claim.suggestedBy`, the author lines of notes,
     documents, custody legs and remarks, and `lib/cases.ts:50-54` "From …".
6. **The sweep: every office code a reader sees goes through `OfficeName` or `officeName`.** The code stays in
   tooltips, URLs and request bodies. The places, from the review and a code search:
   - **Case page.**
     - `CaseFrame.tsx:128`: the `OwnerBadge`, which shows another department's code.
     - `OwnershipCard.tsx:31, 70, 116, 126`: owner, primary, other recommendations and transfer (P3).
     - `Notes.tsx:150`, `Remarks.tsx:130`, `Documents.tsx:64`, and the Custody tab's office column and journey.
   - **Claim.**
     - `claim/Pool.tsx:54`, `claim/Transfers.tsx:61` (no longer `mono`), `claim/WhyBox.tsx:43`.
     - `claim/CaseModal.tsx:182-195, 266`, with C3's "Owner Department" (decision 31).
   - **Cause List.** `causelist/OwnershipCell.tsx:16-33` shows `names[code]` and keeps the code as the tooltip (L1).
   - **Case Inbox and Files.**
     - `inbox/DepartmentCases.tsx:69`, the responsible unit.
     - The "With … · HEALTH" line.
     - `files/TrackingSummary.tsx:31, 47, 57`, `files/Held.tsx`.
   - **Search.** The status column's owner (`search/CaseResults.tsx`, the name only; the layout belongs to row 234).
   - **Dashboard.**
     - `dashboard/Blocks.tsx:243, 406`: name followed by a mono code. The code is dropped and kept as the title.
     - `Blocks.tsx:318`: row 228's `department_name` through `OfficeName`.
     - `Blocks.tsx:457, 514`: by Holder, by Owner, Tickets by Department.
   - **Administration.**
     - `admin/Tickets.tsx:113, 285, 297`: the department and "Requested by … (EDU)".
     - `admin/Users.tsx:60, 563`, `admin/UserDetail.tsx:317`, `ui/UserPicker.tsx:96`, `inbox/dialogs.tsx:75`: a
       membership's office.
     - `admin/mapping/CourtSearch.tsx:98, 299, 306`.
   - **Audit Log.**
     - `audit/AuditTable.tsx:95-101`: `OfficeName` with `href` narrowing by office.
     - `audit/AuditEntry.tsx:77`.
   - The developer finds any others with the guard of decision 7.
7. **A guard keeps codes out of sight.** A vitest source scan, `officeNames.test.ts`, reads every `.tsx` under
   `src/components`.
   - **It fails when:**
     - a JSX child expression reads a property named `office_code`, `department_code`, `*_office_code` or
       `*_department_code` (for example `>{t.department_code}<` or `<span className="mono">{r.office_code}</span>`);
     - one of those properties is passed to a `T.*` string builder.
   - **It does not fail when** the property sits in an attribute (`key`, `rowKey`, `value`, `title`, `href`), in a
     request body, in the `code` prop of `OfficeName`, or in `officeName(...)`.
   - **Exceptions.** An allowlist names a file and line pattern with a reason. Example: the Department Mapping
     screen's code field, where the code *is* the thing being edited.
8. **Pickers show names.**
   - The seven department pickers that lead with the code: `FilterBar.tsx:335`, `files/Held.tsx:140`,
     `calendar/DepartmentHearings.tsx:194`, `inbox/DepartmentCases.tsx:131`, `inbox/dialogs.tsx:64, 117, 534`,
     `inbox/selection.tsx:48`.
   - Each option becomes the name alone, sorted by name, so a cut-off select shows the start of the name.
   - When two options share a name, both get " (CODE)" after the name.
   - The value stays the code.
   - These pickers keep reading `/custody/recipients`, which already returns names.
   - The screen-check fixture gets a hand-written `/reference/offices` answer
     (`frontend/e2e/fixtures/index.ts`). It names the codes the synthetic fixtures use and gives the stress row the
     60-character `STRESS.office`, so the screen check sees names at full length.
9. **Server-built sentences carry names on the server.** Where the server writes the office into a sentence, the
   portal cannot replace it, so the server writes the name:
   - `dashboard.py::_sender_text` falls back to the office's name, not its code, when a move has no person (D1).
   - `reports._generated_by` adds `office_name`, and `report_export.generated_by_text` prints the name. The on-screen
     report's "Generated by …" line uses `office_name` through `OfficeName`.

   Alert titles are out of scope (open question 3).

### B. Server labels in Title Case (K3, owner's option (a))

10. **`serverLabel(text)` puts a label that comes from the server into Title Case when it is shown.** It is
    `titleCase(text)`, and `titleCase` is idempotent, so a label already in Title Case, or one an administrator types
    in Title Case, is unchanged.
    - **Applied to (labels):**
      - every list from `GET /reference/labels`, through `labelOf`;
      - `kind_label`, `doc_type_label`, `pending_action_label`, `reason_label`, `role_label`, `group_label` and
        `response_mode_label`;
      - stage `label` (`StageOut`, `StageBriefOut`, `StageBlockOut`, `StageCodeOut`), timeline `label`,
        `NoteKindOut.label`, `DocumentTypeOut.label`, `PendingActionOut.label`;
      - the dashboard attention `title`;
      - the option lists of dialogs built from those lists, such as Set Stage, Send Case's pending action, and
        document and note types.
    - **Never applied to (names, sentences and data):** person names, office names, designations, bench and judge
      text, party names, case numbers, alert titles and bodies, note text, the court's own texts (short order,
      purpose, disposal nature) and report cell values.
11. **Row 228's decision 9 changes on one point.** Row 228 showed the pending action "exactly as given, not re-cased".
    Under the owner's later portal-wide choice (K3 lists pending actions by name), it becomes "Parawise Comments"
    wherever it is shown as a label, including row 228's Cases with Me and the Department view's Pending Actions card.
    Row 228's decision 7 (`titleCase(kind_label)` on the dashboard) becomes `serverLabel(kind_label)`, with the same
    result.
12. **A guard: `serverLabels.test.ts`.**
    - A vitest source scan fails when a `.tsx` under `src/components` renders one of the properties of decision 10
      (`.kind_label`, `.doc_type_label`, `.pending_action_label`, `.reason_label`, `.role_label`, `.group_label`,
      `.response_mode_label`; stage and timeline `.label` in the files that read those types) outside `serverLabel(`
      or `labelOf(`.
    - It names the file and line. An allowlist with reasons covers non-display uses, such as a `key` or a comparison.
13. **Report titles and headers are Title Case at the source, not in the portal (R1).** They also go into Excel and
    PDF, where the portal cannot help.
    - The constants are rewritten in `services/reports.py`:
      - catalogue titles, for example "Pending Cases by Department, Court and Age", "Hearings and Disposals Over a
        Period", "Pending Actions and Overdue Compliance by Office", "Data Collection Health";
      - section titles, for example "Cases with a Pending Action, by Who Has Them";
      - every `Column` label;
      - the `AGE_BANDS` labels;
      - the "By department or unit" builders.
    - This is code text, not data: no migration.
    - The `pending_action` cell of the pending-actions case list is written as
      `title_case(PENDING_ACTION_LABELS[...])`, so the screen, Excel and PDF match the case page.
    - A pytest checks every title and label with `core.titlecase.is_title_case`.

### C. One label helper and the enum-label test (K4)

14. **A new module, `frontend/src/lib/displayLabels.ts`, holds the three label helpers.**
    - `labelFor(map, code)`:
      - returns "—" for a null or empty code;
      - returns `map[code]` when the code has a label;
      - otherwise returns `titleCase` of the code with `_` and `.` read as spaces, so `not_found` becomes "Not Found".
      - A code without a label never shows as a lowercase code.
    - `serverLabel(text)`: decision 10.
    - `labelOf(list, code)`, moved here from `lib/api/hooks.ts`: the server list's label through `serverLabel`, else
      `labelFor(undefined, code)`. Its imports are updated; no re-export is kept.
    - **Call sites that change:**
      - the `?? code` and `replace(/_/g, " ")` fallbacks in `lib/nextDates.ts:13`, `lib/timeline.ts:42, 101`,
        `lib/signals.ts:28`, `workflow/CustodyTab.tsx:139` and `data/ProblemsAndFixes.tsx:313`;
      - every `T.x[code] ?? code` lookup: statuses, transfer statuses, severities, visibilities, order kinds.
    - A source guard in the same test fails on a new `] ?? code`, `] ?? r.`-style fallback or `.replace(/_/g, " ")`
      outside `displayLabels.ts`.
15. **The enum codes the backend can send are exported for the portal's test.**
    - A new tool, `backend/tools/export_enum_codes.py`, writes `frontend/src/lib/enumCodes.json`, with sorted keys
      and a trailing newline, the same convention as `export_openapi.py`. It holds:
      - `enums`: every `enum.StrEnum` defined in `aslms.domain.*` (found by import, not by a hand list), each with its
        values in declaration order;
      - `audit_actions`: the registry of decision 22;
      - `case_detail_fields`: the key tuples of decision 18.
    - A pytest snapshot test (`test_enum_codes_snapshot.py`) fails when the committed file differs from the tool's
      output. This is the same contract as `test_openapi_snapshot.py`.
    - Alternative considered: hand-copying enum values into the portal. Refused: a new value would be missed silently.
16. **The enum-label test, `enumLabels.test.ts`, with the registry `frontend/src/lib/enumLabels.ts`.**
    - **The enums it checks:**
      - every string `enum` in `frontend/openapi.json`, named schemas (`OfficeKind`, `Role`, …) and inline
        properties named `Schema.property`, for example `NextHearingOut.basis`;
      - every enum in `enumCodes.json`. These are the domain enums the API sends as plain `str`, such as
        `CaseStatus`, `OrderKind`, `FirstSeenSource` and `LowerCourtLevel`.
    - **Each enum must sit in exactly one of three lists:**
      - `LABELLED`: the enum name with its portal map (for example `CaseStatus` → `T.case.statuses`, `OrderKind` →
        `A.orderKinds`). Every value must have a Title Case label in the map.
      - `SERVER_LABELLED`: labels arrive from the server, through `ref_*` tables or a `*_label` field (`Role`,
        `OfficeKind`, `AlertKind`, `Stage`, `PendingAction`, `Permission`, …), with the field named.
      - `NOT_SHOWN`: never shown to a reader, with a reason of more than five characters (for example `FetchLane`:
        "Only the request lane's state is shown, as a sentence").
    - **It also fails when:**
      - a list names an enum that no longer exists;
      - a map has a label for a value the enum lacks, which is a stale label.
    - This is the "every enum used on screen has a label" test of K4.

### D. The case Details tab (P9)

17. **One label map, `frontend/src/lib/caseFields.ts`, replaces `fieldLabel`'s de-snaking.**
    - Every key the overview can send has a plain label (table below).
    - The labels follow the NAPIX specifications and the coverage table (`docs/schema/napix_coverage.md` §C).
    - Where a meaning is not documented, the label is the field's own words written out in full, without an added
      meaning, and the field is listed under open question 2.
    - Keys holding a UUID are hidden by name (`HIDDEN_FIELDS`), no longer by testing the value:
      - `case_type_id`, `filing_case_type_id`, `bench_id`, `state_id`, `district_id`, `merged_into_case_id`,
        `created_by`, `updated_by`, `id`;
      - also `is_tracked`, a portal flag that no service writes (always false since migration 0001). Showing it would
        be noise.
    - Every NAPIX field with a home stays visible, as the Details tab's own rule requires (design portal-cases,
      decision 10).

    | Block | Key | Label | Basis |
    |---|---|---|---|
    | Identity | `cnr` | CNR | `cino`, "16 digit unique CNR" (HC spec 6.1.6) |
    | | `court` / `est_code` | Court / Establishment Code | `court_est_name`, `est_code` ("Court establishment code") |
    | | `court_est_name` | Court Establishment | "Court establishment" |
    | | `case_type_text` | Case Type | `type_name_reg`, "Registration case type name" |
    | | `reg_no` / `reg_year` | Registration Number / Registration Year | spec |
    | | `case_no_text` | Case Number | derived from `reg_no`, `reg_year` (coverage §C) |
    | | `filing_case_type_text` | Filing Case Type | `type_name_fil`, "Filing case type name" |
    | | `filing_no` / `filing_year` | Filing Number / Filing Year | spec |
    | | `filing_no_text` | Filing Case Number | derived from `fil_no`, `fil_year` (coverage §C) |
    | | `filing_date` | Date of Filing | `date_of_filing` |
    | | `registration_date` | Date of Registration | `dt_regis` |
    | | `date_first_list` | First Hearing Date | spec |
    | Status | `status` | Status | `pend_disp` P/D; value through `labelFor(T.case.statuses)` |
    | | `disposal_date` | Date of Decision | `date_of_decision` |
    | | `disposal_nature` | Nature of Disposal | status `disp_nature` |
    | | `disposal_type` | Disposal Type | spec "Disposal type" |
    | | `short_order` | Short Order | spec |
    | | `date_filing_disp` | Filing Disposal Date | **not documented** (open question 2) |
    | | `reason_for_rej` | Reason for Rejection | **not documented** (open question 2) |
    | | `date_judgement_pronounced` / `date_judgement_reserved` | Judgment Pronounced On / Judgment Reserved On | field names (coverage §C) |
    | | `goshwara_no` | Goshwara Number | **open question 2** |
    | | `next_hearing_date` | Next Date in the Court's Record | `date_next_list`; the portal's own next hearing is elsewhere |
    | | `next_purpose` | Purpose or Stage | `purpose_name`, "Purpose or current stage of the case" |
    | | `last_hearing_date` | Last Hearing Date | `date_last_list`, "Last proceeding date" |
    | Classification | `napix_bench_id` | Bench ID | spec "Bench id" |
    | | `bench_name` | Bench Name | spec |
    | | `bench_type_code` | Bench Type Code | `bench_type`, spec "Bench type" |
    | | `coram` | Coram | spec |
    | | `coram_designation` | Judge's Designation | `desgname`, "Designation of judicial officer" (DC spec 5.2.6) |
    | | `judicial_branch` | Judicial Branch | spec |
    | | `category` / `category_code` / `sub_category` | Category / Category Code / Sub-category | `category_details` |
    | | `sitting_bench` / `judges` | Sitting Bench / Judges | the `benches` row |
    | Place | `state_name_as_listed` / `district_name_as_listed` | State / District | `state_name`, `dist_name` |
    | | `filing_state_code` / `filing_district_code` | Case State Code / Case District Code | `document_details.case_state_code`, `case_dist_code`: **not documented**, labelled by the field name (open question 2) |
    | | `fir_no` / `fir_year` / `police_station` | FIR Number / FIR Year / Police Station | spec |
    | | `police_st_code` | Police Station Code | DC spec 5.2.6 |
    | | `uniform_code` | National Police Station Code | DC spec 5.2.6 (open question 2) |
    | | `main_matter_text` | Main Case Number | `main_matter` (spec sample "Case Number - …") |
    | Parties as printed | `petitioner_summary` / `respondent_summary` | Petitioner / Respondent | `pet_name`, `res_name` |
    | | `pet_advocate` / `res_advocate` | Petitioner's Advocate / Respondent's Advocate | `pet_adv`, `res_adv` |
    | Acts | `act_name_as_listed` / `national_act_code` / `section` | Act / National Act Code / Section | `acts[]` |
    | Lower courts | `level` | Court Level, value "Lower Court" (`appellate`, `lower_court_*`) or "Trial Court" (`trial`, `trial_lower_court_*`) | spec "Lower court designation", "Trial court designation" |
    | | `court_name` / `case_no_text` / `decision_date` | Court / Case Number / Date of Decision | spec |
    | Applications | `ia_number` / `party_name` / `status` / `filing_date` | IA Number / Party / Status (P "Pending", D "Disposed") / Date of Filing | `iafiling[]`; `ia_pend_disp` P/D like `pend_disp` |
    | Objections | `seq` / `objection` / `scrutiny_date` / `compliance_by_date` / `receipt_date` | No. / Objection / Scrutiny Date / Comply By / Date Received | `objections` |
    | Court transfers | `transfer_date` / `from_court_text` / `to_court_text` | Date of Transfer / From Court / To Court | `transfer[]` |
    | Writ information | `appellate_case_number` / `appellate_authority` | Appellate Case Number / Appellate Authority | `writinfo[]` |
    | Portal | `is_provisional` | Provisional (No CNR Yet) | portal |
    | | `first_seen_source` | First Seen From; values Cause List, Court Search, Department Discovery, Linked Case | portal |
    | | `last_full_refresh_at` / `last_status_refresh_at` | Court Details Last Fetched / Status Last Checked | portal |
    | | `dossier_stale` | Court Details Need Refreshing | set when Current Status changes, cleared by a dossier fetch (`services/cases.py:711, 821`) |
    | | `closed_at` | Recorded as Disposed | set on disposal (`services/cases.py:300`; schema.md `cases`) |
    | | `created_at` / `updated_at` | Added to ASLMS / Last Changed | portal |

18. **The list-block keys move to named tuples in `services/case_detail.py`.**
    - The tuples: `ACT_FIELDS`, `LOWER_COURT_FIELDS`, `APPLICATION_FIELDS`, `OBJECTION_FIELDS`, `TRANSFER_FIELDS`,
      `WRIT_FIELDS`.
    - `overview()` builds each dict from its tuple. The response is unchanged.
    - The export tool writes these tuples with `IDENTITY` … `PORTAL` and the portal-added keys (`court`, `est_code`,
      `sitting_bench`, `judges`) into `enumCodes.json` → `case_detail_fields`.
    - `caseFields.test.ts` fails when an exported key has neither a label nor a place in `HIDDEN_FIELDS`, or when a
      label names a key the backend no longer sends.
    - The `fieldLabel` fallback is deleted.
19. **Values on the Details tab go through K4, and the tab uses one label width.**
    - `status`, `first_seen_source`, `level` and the application `status` are labelled through `labelFor`.
    - Dates and booleans are shown as today.
    - Every `DefinitionList` on the tab, and in `IdentityDetails` (the claim modal), takes one shared label column
      width. The tab sets a CSS custom property that the kit's `DefinitionList` reads, so the Identity, Status and
      Classification cards line up.

### E. Audit action names (U1; a change to row 41's design)

20. **The Audit Log shows each action by name.**
    - **This changes row 41's design.** `docs/design/portal-audit-health.md`, decision 5, said "Action (the code,
      monospace)". The owner decided on 10 Nov 2026 that the Auditor reads names.
    - **List (`AuditTable.tsx`).**
      - The Action cell is the name from `T.audit.actionNames` in the body font. It is no longer `mono` and no longer
        broken mid-word.
      - It is still the link that narrows the search to that code (`action=<code>`).
      - Its `title` is the code.
    - **Action filter.** It lists the names within their groups (`T.audit.groups`). The URL still carries the code.
    - **Entry page (`AuditEntry.tsx`).** Action shows the name, then the code in mono muted text, for example
      "Case Claimed · `ownership.claim`". The code an auditor quotes stays on the page.
    - **A code with no name** shows the code itself, as today. An auditor never sees an invented name.
21. **`T.audit.actionNames` names every action code.**
    - About 120 entries, each a Title Case label in the past tense of the event, for example `ownership.claim` →
      "Case Claimed", `custody.sent` → "Case Sent", `note.added` → "Note Added", `auth.otp_sent` → "Sign-in Code
      Sent".
    - `T.audit.groups` names every prefix.
    - `labelRules.ts` treats every path under `audit.actionNames.` as a label path, because the keys contain dots.
    - The developer writes the names. The reviewer checks them against what each action does.
22. **A backend registry of action codes, so "every backend code has a name" can be tested.**
    - `backend/aslms/domain/audit_actions.py` defines `AUDIT_ACTIONS: tuple[str, ...]`. It lists every code the code
      writes, including the ones built at run time (the expansions of `f"{entity}.{action}"` in
      `services/matching_rules.py`, the `data_load.collect_*` codes, the court-search actions and any written by a
      migration helper), plus retired codes still in `audit_log` (decision 23).
    - `write_audit` is not changed in production.
    - **Two tests hold the registry complete:**
      - a unit test scans `backend/aslms/**/*.py` for `write_audit(` and `write_audit_apart(` calls whose action
        argument is a string literal, and asserts each literal is registered;
      - `backend/tests/db/conftest.py` registers a test-only SQLAlchemy `before_insert` listener on `AuditLog`. It
        fails the test that writes an unregistered action, which catches the codes built at run time across the whole
        database suite.
    - The export tool carries the registry into `enumCodes.json`. The vitest
      `auditNames.test.ts` asserts that every registered code has a Title Case name and every prefix has a group
      label, and that no name is left for a code outside the registry.
23. **Retired codes.** The integrator's verification lists `SELECT DISTINCT action FROM audit_log` on the dev
    database (read only). Any code there that is missing from the registry is added as retired, with a name, before
    merge. The `GET /audit/actions` list is read from the table, so every code it can offer has a name.

### F. Needs Your Attention strings (D1)

24. **One statement of state per row.**
    - **The badge names the kind** (`T.dash.leads`):
      - Overdue (`overdue_action`);
      - Next Date to Enter (`confirm_next_date`; was "Enter");
      - Due Soon;
      - Ready to Close;
      - Case Received (`file_received`; was "New").
    - **The title is the thing to act on**, shown through `serverLabel` (decision 10).
    - **The detail is the extra fact**, never the badge's words.
    - `services/dashboard.py` constants change (text only, no schema change):

      | Kind | Title (server) | Detail (server) |
      |---|---|---|
      | `overdue_action` | `PENDING_ACTION_LABELS[act]` (unchanged) | "Was due 2 Nov 2026, 3 days ago" ("1 day ago") |
      | `due_soon` | `PENDING_ACTION_LABELS[act]` (unchanged) | "By 12 Nov 2026, today" / "tomorrow" / "in 2 days" |
      | `confirm_next_date` | by reason: "No clear date in the order", "No next date in the order", "Scanned order, not readable", "Date read was marked wrong" | "Answer by 30 Oct 2026" (the item's `date`, already sent) |
      | `ready_to_close` | "Close this case" | "Disposed by the court on 2 Nov 2026" (unchanged words) |
      | `file_received` | `PENDING_ACTION_LABELS[act]`, including "No action pending" for none (was "Case received") | "From Name, Designation", or "From <office name>" (decision 9) |

    - Dates are written "2 Nov 2026" by one helper. This also fixes today's "02 Nov 2026" from `strftime('%d %b %Y')`.
    - Alternative considered: the portal composes each detail from `kind`, `date` and `overdue_days`. Refused: the
      reason and sender texts are server words, and keeping all of them on the server keeps one place for this text.
25. The badge tones (`LEAD_TONE`) are unchanged; row 229 recolours them.

### G. Report code columns (R2)

26. **Code columns are for Excel only.**
    - `Column` gains `screen: bool = True`. `to_dict` sends it.
    - The code columns get `screen=False`:
      - `group_code` (Department Code or Responsible Unit Code);
      - `court_code`;
      - `holder_department_code`, holder `office_code`, addressed `office_code`;
      - compliance `department_code`;
      - the case list's `holder_office_code`.
    - The on-screen report (`ReportView.tsx`) and the PDF (`report_export`) leave out `screen=False` columns.
    - Excel keeps every column.
    - Each `_totals` label moves to the first column the screen shows, so "Total" never disappears with a hidden code
      column.
27. **The case list names the holder office.** `CASE_COLUMNS` gets `Column("holder_office", "Holder Office")`, the
    holder office's `name`, read in the same query by selecting `holder.name`. The code column becomes
    `Column("holder_office_code", "Holder Office Code", screen=False)`. That fixes the mislabelled column at `:714`.

### H. The small wording findings (P4, S3, A3, L2, C3, P12's case)

28. **P4.** The Latest Order card (`case/Overview.tsx:96`) shows `labelFor(A.orderKinds, o.kind)`: "23 Oct 2026 ·
    Interim Order".
29. **S3.** `T.search.box` (`messages.ts:1758`) becomes "Search by CNR, case number or party name".
30. **A3.** One name, "Next Dates to Enter", for the next-date work:
    - the calendar legend `kinds.confirm` (`messages.ts:3485`) becomes "Next Date to Enter";
    - the count words (`:3488`) become "next date to enter" and "next dates to enter";
    - the My Calendar subtitle (`:3480`) ends "…and next dates waiting for you to enter".
31. **C3.** The claim modal's owner line becomes the label "Owner Department" with `OfficeName` as the value.
    `T.claim.ownedBy` is removed. The tabs become "Parties and Advocates" and "Hearings and Listings"
    (`messages.ts:1661-1664`).
32. **L2.** `T.causelist.versus` (`messages.ts:1903`) becomes "vs", as at `messages.ts:926`.
33. **P12's case.** `T.case.corrects` and `T.case.correctedBy` (`messages.ts:2176-2177`) become "Corrects …" and
    "Corrected by …", matching `messages.ts:3378-3379`. Row 233 replaces the reference number with the note's date and
    link.

### I. One office-name mechanism, aligned with row 228

34. **Row 228's `department_name` on `DashboardOwnCasesOut` stays in the API.**
    - It is built and tested before this row, it is additive, and it is the caller's own membership's department with
      the name at hand.
    - The portal shows it through `<OfficeName code={c.department_code} name={c.department_name} />`, so there is one
      display path, with payload names preferred (decision 5).
    - **The rule from now on:** a new response carries office *codes*, and the portal names them through `OfficeName`.
      A `*_name` field for an office is added only where the server builds a sentence (decision 9).
    - Row 228's `pending_action_label` also stays. It is shown through `serverLabel` (decision 11).

## Data
None. No table, column, reference code, index or `ref_*` row changes. **No migration.** `docs/schema/schema.md` and
`docs/schema/napix_coverage.md` are unchanged. The Details tab labels follow the coverage table, and every NAPIX field
with a home stays visible.

## Services
- **`backend/aslms/services/reference.py`**, new function `offices(session) -> list[dict]`.
  - One `select(Office)` ordered by `path`. `department_code` comes from `path` (second segment when that office is a
    Department-tier kind, the `access.is_department` rule, applied to the loaded rows without a further query).
  - Reads only. No audit row and no event.
- **`backend/aslms/services/dashboard.py`**.
  - D1 constants and detail builders: `ENTER_TITLE` by reason, `READY_TITLE = "Close this case"`, the overdue and
    due-soon details, and the `file_received` title from `PENDING_ACTION_LABELS`.
  - A `_day(d)` helper writes "2 Nov 2026".
  - `_sender_text` takes the office name, read by joining `Office` on the leg's actor office code in the received
    query.
- **`backend/aslms/services/reports.py`**.
  - Title Case titles, sections and labels (decision 13).
  - `Column.screen` (decision 26), the `holder_office` column (decision 27), totals labels on the first shown column.
  - `_generated_by` adds `office_name`.
  - `report_export.py` skips `screen=False` columns in the PDF and prints the generated-by office by name. Excel is
    unchanged, apart from the new labels.
- **`backend/aslms/services/case_detail.py`**. The six list-block tuples (decision 18). The response is unchanged.
- **`backend/aslms/domain/audit_actions.py`** (new). `AUDIT_ACTIONS` (decision 22). No runtime use in production.
- **`backend/tools/export_enum_codes.py`** (new). Writes `frontend/src/lib/enumCodes.json` (decision 15). Run as
  `backend/.venv/Scripts/python backend/tools/export_enum_codes.py`. It needs no database or secret.

## API
1. **New: `GET /reference/offices`.**
   - Gate: `require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL, Permission.USERS_VIEW,
     Permission.AUDIT_VIEW)`. Without one of them: 403. Signed in but still at a first-sign-in step: 403 through
     `current_user`.
   - Response `OfficeNamesOut`:
     ```
     { "items": [ { "code": "SEC-EDU", "name": "Directorate of Secondary Education",
                    "kind": "directorate", "tier": "directorate",
                    "department_code": "EDU", "is_active": true }, … ] }
     ```
     `kind` is `OfficeKind`, `tier` is `Literal["state", "department", "directorate"]`, and `department_code` is
     `str | null`.
   - Header `Cache-Control: private, max-age=300`.
   - Visibility: office names only, the same for every caller who passes the gate (decision 2). No case data.
2. **Changed: `GET /reports/{key}`** (and the Excel and PDF exports).
   - `columns[]` items gain `screen: bool` (`ReportColumnOut`).
   - The pending-actions case list gains the `holder_office` column.
   - `generated_by` gains `office_name: str | null` (`ReportGeneratedByOut`).
   - Titles, section titles and labels are in Title Case.
   - The function gates are unchanged (`reports.department` or `reports.state`).
3. **Changed text only: `GET /dashboard/me`.** `attention[].title` and `detail` follow decision 24. No schema change,
   and the gate is unchanged.
4. `frontend/openapi.json` and `src/lib/api/schema.d.ts` are regenerated (`export_openapi.py`, then `npm run gen:api`).
   No other endpoint changes.

## Jobs
None.

## Tests
**Backend (pytest).**
- `tests/db/test_api_reference.py`:
  - `test_offices_lists_every_office_with_tier_and_department`: active and inactive offices at all three tiers, the
    State root with a null `department_code`, a unit carrying its department's code, ordered by path;
  - `test_offices_gate`: 200 for a department officer (`cases.view_scope`), the Auditor (`audit.view`,
    `cases.view_all`) and a type holding only `users.view`; 403 for a login with no office yet, and 403 while
    `must_change_password` is set;
  - `test_offices_returns_names_only`: the keys of an item are exactly the six fields;
  - `test_offices_cache_header`: `private, max-age=300`;
  - `test_offices_statement_count`: at most 2 statements.
- `tests/db/test_dashboard_headline.py`:
  - `test_attention_badge_words_not_repeated`: per kind, the title and detail of decision 24; "No action pending" for
    a received case with no action; the office name in the sender detail when the move has no person;
  - the existing assertions on "Overdue 3 days", "Next date to enter" and "Case received" are updated.
- `tests/unit/test_reports_unit.py`:
  - `test_report_texts_are_title_case`: every catalogue title, section title, column label and age-band label passes
    `is_title_case`;
  - `test_code_columns_are_not_shown_on_screen`: every column whose key ends in `_code` has `screen=False`, and every
    other column `screen=True`;
  - `test_totals_label_on_first_shown_column`.
- `tests/db/test_reports.py`:
  - `test_pending_actions_case_list_names_holder_office`;
  - `test_generated_by_has_office_name`;
  - `test_pdf_omits_code_columns_excel_keeps_them`.
- `tests/unit/test_enum_codes_snapshot.py`, `test_committed_enum_codes_match_the_backend`: the committed
  `enumCodes.json` equals the tool's output.
- `tests/unit/test_audit_actions_registry.py`:
  - `test_literal_audit_actions_are_registered` (the static scan);
  - `test_registry_has_no_duplicates_and_is_sorted`.
- `tests/db/conftest.py`: the `before_insert` listener (decision 22). The whole database suite is the test that every
  run-time action is registered.
- `tests/db/test_case_detail.py`, `test_overview_list_blocks_use_named_fields`: each list-block dict's keys equal its
  tuple.
- `tests/unit/test_openapi_snapshot.py`: unchanged, regenerated.

**Frontend (vitest).**
- `displayLabels.test.ts`:
  - `labelFor` returns the map's label, Title-Cases an unknown code (`not_found` → "Not Found"), and returns "—" for
    null;
  - `serverLabel` gives "Parawise Comments", "Other - See Remark", "Government Order / Notification", "Next Date
    Reported as Wrong", and leaves a Title Case label unchanged;
  - `labelOf` Title-Cases a server label and falls back through `labelFor`;
  - the source guard against `?? code` fallbacks and `replace(/_/g, " ")`.
- `enumLabels.test.ts` (decision 16): every enum is in exactly one list, every labelled value has a Title Case label,
  and no list or label is stale.
- `serverLabels.test.ts` (decision 12) and `officeNames.test.ts` (decision 7): the source guards.
- `caseFields.test.ts` (decision 18): every exported key is labelled or hidden, every label is Title Case, and no label
  is stale.
- `auditNames.test.ts` (decision 22): every registered action has a Title Case name and every prefix a group.
- `OfficeName.test.tsx`:
  - a payload name wins;
  - the map name is shown with the code as `title`;
  - a code not in the map shows as muted plain text;
  - null shows "—";
  - " · Inactive" appears in the title of an inactive office;
  - with `href` it renders a link;
  - the text is never `mono`.
- `audit.test.ts`: `actionName` returns the name, or the code for an unknown code. The entry page shows name and code.
- Updated screen tests:
  - `Details` shows "Registration Number", not "Reg no";
  - `Overview` shows "Interim Order";
  - `CaseModal` shows "Owner Department" and the "and" tab names;
  - `OwnershipCell` shows the name;
  - department pickers list names;
  - `ReportView` hides `screen: false` columns.
- `labels.test.ts`: still green after the `T` changes, with `audit.actionNames.*` classified as labels.
- `wording.test.ts`: no "CINO", no "versus", no "Next Date to Confirm".

## Verification
1. Backend:
   ```
   cd backend && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m pytest -q
   ```
   Green. Then:
   ```
   .venv/Scripts/python tools/export_openapi.py
   .venv/Scripts/python tools/export_enum_codes.py
   ```
   `git diff --exit-code frontend/openapi.json frontend/src/lib/enumCodes.json` shows no change after the commit.
2. Frontend:
   ```
   cd frontend && npm run gen:api && npm run lint && npx tsc --noEmit && npm test
   ```
   Green.
3. Retired audit codes, read only on the dev database:
   ```
   SELECT DISTINCT action FROM audit_log ORDER BY 1;
   ```
   Every code is in `AUDIT_ACTIONS` and has a name. Report the count.
4. The screen check, on a private network against temporary images (runbook section 16; never on the shared stack):
   all pass. In the screenshots at 1280 and 375:
   - no office code in mono on Case Claim (Pool, Transfers, the modal), the case page's Ownership card, the Custody
     tab, Notes, the Cause List, the Case Inbox's Department tab, Search, the dashboard's Department and State views,
     Tickets or the Audit Log;
   - the Details tab reads "CNR", "Registration Number", "Filing Disposal Date", "Goshwara Number" (or the owner's
     answer to question 2) with aligned label columns;
   - the Audit Log's Action column reads names;
   - report titles are in Title Case.
5. After deployment (no migration), the owner checks the live stack at http://localhost:3000 at 1280 px:
   - **as a department officer:** a case owned by another department shows its name on the owner badge;
   - **Needs Your Attention:** shows "Overdue" with "Parawise Comments" and "Was due …", and no repeated words;
   - **Send Case and Set Stage:** list their options in Title Case;
   - **as the Auditor:** the Audit Log shows "Case Claimed", and the entry page shows "Case Claimed ·
     ownership.claim";
   - **a pending-actions report:** shows Holder Office by name on screen, while its Excel file keeps the code columns.

## Open questions
Each question has a recommended answer. The note is complete with those answers, and the owner may approve "with the
recommended answers".

1. **Inactive offices in `GET /reference/offices`.**
   - **Recommended:** include them, names only, with `is_active: false`. Old custody legs, notes and audit rows keep
     their codes, and without the names those rows would show codes for ever. The `offices.manage` rule on the
     administration list concerns reactivation, not secrecy, and the State auditor already reads these names.
   - Alternative: active offices only. A code of a deactivated office then shows as a muted code.
2. **NAPIX fields whose meaning is not documented for the High Court.** Each label below is the field's own words, not
   a guessed meaning. Every value shown is as the court sent it.
   - `date_filing_disp` and `reason_for_rej`. They have no description in the HC specification (6.1.6) or the eCourts
     specification (5.2.6), and they are empty in every HC sample.
     - **Recommended:** "Filing Disposal Date" and "Reason for Rejection". Revisit when a filled value is seen.
   - `goshwara_no`. The HC specification does not describe it. The eCourts specification (5.2.6) places "Nature of
     disposal is returned: 1 = Contested, 2 = Uncontested" beside it. The HC samples agree: "1" on a disposed case
     whose `disp_nature` reads "Contested - Disposed Of", and "0" on a pending case.
     - **Recommended:** keep the court's term, "Goshwara Number", with the value as sent. The words "Contested" or
       "Uncontested" already show under Nature of Disposal.
     - Alternative: label it "Disposal Nature Code" on the strength of the District Court specification.
   - `document_details.case_state_code` and `case_dist_code` (`filing_state_code`, `filing_district_code`). They are
     not described in either specification (samples: 18 and 117).
     - **Recommended:** "Case State Code" and "Case District Code", the field names written out.
   - `uniform_code`. It is described only in the eCourts specification, as "National Police Station Code". It is null
     in every HC sample.
     - **Recommended:** use that label, since both specifications come from the same e-Committee.
3. **Alert titles and e-mails that name an office by code** ("Transfer requested by EDU: …"). They are written when
   the alert is raised and stored, so this row cannot change them.
   - **Recommended:** a follow-up row in which `alert_rules.py` writes the office name for new alerts and e-mails. The
     raise sites add `*_office_name` to the alert data. Existing alerts keep their stored text.
   - Alternative: fold it into this row, which adds the ownership, workflow and document raise sites and their tests
     (about half a day).
