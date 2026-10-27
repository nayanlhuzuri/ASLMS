# Design: Assign, Responsible Unit and Dealing Officer in place of "Allot"

```
slug: claim-assign-wording
status: approved
author: architect
date: 2026-10-26
approved_by: owner on 2026-10-26, as designed (Assign wording everywhere users read, the reference-data migration)
```

## Context

**The owner's question of 26 Oct 2026** (backlog row 178) was asked on the claim screen. The screen shows "Allot Now
(Optional)" with "Unit" (No unit) and "Officer" (No officer), and the owner asked what these are.

They are the department's allotment. The service is `ownership.allot`, and the row is `case_ownership.unit_office_id`
and `officer_user_id`:
- the **unit** is an office under the department that is responsible for the case, and sees it through the
  `allotted` basis;
- the **officer** is the dealing officer, who finds the case in Case Inbox → Working On.

This is not Send Case, which moves the case's current holder and carries a remark, a pending action and a due date.

The owner chose **"Keep it, make it clear"**:
- rename the section to "Assign Now (Optional)";
- label the fields "Responsible Unit" and "Dealing Officer";
- add one explanatory line under the heading;
- show the empty choices as "Whole Department" and "No Dealing Officer Yet";
- replace the bordered fieldset with the field-row layout (`portal-ui-polish-2`), with both pickers on one row at
  desktop width;
- use the same words everywhere allotment appears.

**Where allotment shows today** (checked on main at b853a94):
- **Portal dialogs:**
  - the claim step of the case claim modal: `components/claim/ModalActions.tsx`, a `fieldset` with legend
    `T.own.allotOptional`;
  - the inbox Claim dialog: `components/inbox/dialogs.tsx::ClaimDialog`, the same fieldset;
  - the Allot dialog on the case page and in the inbox: `AllotDialog`, titled `T.own.allotTitle`, with the button
    `T.own.allot` and the choices Keep As Is / Clear;
  - the Take Over text (`T.own.takeOverText`).
- **Case page:** the ownership card line (`case/OwnershipCard.tsx`) shows the unit code and officer name with no
  label.
- **Department Cases:**
  - the column "Unit · Officer" (`T.inbox.unitOfficer`) and "Not Allotted";
  - the Unit and Officer filters, including the officer filter's "Not Allotted" option (chip "Officer: Not Allotted").
- **Dashboard:** "Allotted, Active" (`T.dash.allotted`).
- **Inbox and access texts:** the Case Inbox subtitle and the empty Working On text, and the access basis "allotted to
  you or your office" (`T.case.bases.allotted`).
- **The membership exit dialog:** "Every allotted case …", "Allotted Case" and "allotment(s)".
- **Error texts:** `not_allotted` and `stale`.
- **Server texts:**
  - the in-app and e-mail alert for an allotment (`alert_rules.py`: "Case allotted: …", "Allotted to … by …", "The
    case allotted to you was taken over by …");
  - the custody reason label "Allotted" (`domain/workflow.py::CUSTODY_REASON_LABELS`), shown in the journey and the
    "case moved" alert;
  - the function label "Allot Cases" (`access_seed.PERMISSION_LABELS`);
  - the report grouping "Unit code" / "Unit" and "Department office / not allotted" (`reports.py`);
  - error messages in `ownership.py` and `memberships.py`;
  - two seeded labels stored in the database: the timeline label of event type `allotted` ("Allotted", in
    `ref_event_type`), and the description of the user type `dept_officer` ("Works on allotted cases: …", in
    `ref_role`).
- **The audit log** shows action codes as they are (`ownership.allot`, `ownership.reallotted_on_exit`). It has no
  label for them, so nothing there is reworded.

**The plan** (§ user types) says officers work on "Cases allotted to them within the department". This note changes the
word the portal shows, not the rule: **deviation (wording only)**, chosen by the owner. The plan's rule "no case is
assigned automatically" concerns a case reaching a department. It is unchanged and stays true: assigning within a
department is always a person's action.

**Not covered:** any rule. No change to who may assign, what a unit or officer sees, the API paths or fields
(`/cases/{ref}/allot`, `unit_code`, `officer_user_id`), the codes (`ownership.allot`, `allotted`,
`reallotted_on_exit`, `cases.allot`) or the custody workflow.

## Decisions

1. **The portal's word is "Assign"; the codes keep "allot".** "Allot" in what users read becomes "Assign".
   "Allotted to" becomes "Assigned to" when it names the person, and "the responsible unit" when it names the unit.
   Codes, API paths, field names, event types and audit actions do not change.
   Alternative: rename the codes too. Rejected: a rename of the API, the audit actions and the custody reason CHECK
   for a wording change, and old audit rows would still carry the old code.

2. **The claim dialogs' section** (the case claim modal's claim step and the inbox Claim dialog):
   - **Heading:** an `h4` "Assign Now (Optional)", not a `legend`.
   - **One muted line under it:** "Choose who in the department handles this case. They will see it in their inbox.
     To pass the case on for an action, use Send Case on the case page." The owner's example said "hand over the
     file" and "Send File". The portal's button is **Send Case** (`T.wf.send`), and the wording guards of
     `case-workspace-admin` (decision 6) refuse "file" in the custody sense, so the line uses the portal's words.
   - **Fields:** "Responsible Unit" (empty choice "Whole Department") and "Dealing Officer" (empty choice "No Dealing
     Officer Yet").
   - **Hints:** "An office under the department that is responsible for the case. It will see the case." and "The
     officer who deals with the case day to day."
   - **Layout:** both fields in one `.row` (`flex: 1 1 220px` each). They sit side by side where the dialog body is at
     least about 460 px wide (expected in the claim modal at 768 px and above; uicheck confirms it), and stack below that. The fieldset and its border
     go.
   - The section shows only when the user may assign (`canAllot`, unchanged).

3. **The Assign dialog** (`AllotDialog`, from the case page's ownership card and rail, and from the inbox):
   - **Title:** "Assign This Case". The confirm button and the ownership card's button both read "Assign".
   - **The explanation line** of decision 2 sits under the department choice.
   - **Fields:** "Responsible Unit" and "Dealing Officer", in one `.row`.
   - **Choices:**
     - "Keep As Is (<current>)";
     - then "Whole Department" (clears the unit) or "No Dealing Officer" (clears the officer), each in place of the
       shared "Clear";
     - then the lists.
   - The confirm stays disabled while both fields are Keep As Is (unchanged).

4. **The ownership card line** labels its parts: "<department> · Responsible unit <code> · Dealing officer <name> ·
   claimed on …". A part that is empty is left out, as today.

5. **Department Cases:**
   - the column "Responsible Unit · Dealing Officer";
   - a row with neither shows "Not Assigned";
   - the filters "Responsible Unit" (placeholder "Any Unit") and "Dealing Officer" (placeholder "Anyone");
   - the officer filter's option for rows with no officer (`unallotted=true`) reads "Not Assigned Yet", so the chip
     reads "Dealing Officer: Not Assigned Yet".
   The unused keys `T.inbox.unit` ("Unit (Code)") and `T.inbox.allottedTo` are removed.

6. **The other portal texts:**

   | Key | Today | New |
   |---|---|---|
   | `T.dash.allotted` | Allotted, Active | Assigned, Active |
   | `T.inbox.mySubtitle` | cases allotted to you | cases assigned to you |
   | `T.inbox.emptyViews.working` | Cases allotted to you, and cases sent to you, appear here. | Cases assigned to you, and cases sent to you, appear here. |
   | `T.case.bases.allotted` | allotted to you or your office | assigned to you or your unit |
   | `T.exit.intro` | Every allotted case and case with this membership needs another officer before it ends. | Every case assigned to this membership, and every case with them, needs another officer before it ends. |
   | `T.exit.allotment` | Allotted Case | Assigned Case |
   | `T.exit.counts` | `n allotment(s)` | `n assigned case(s)` |
   | `T.errors.not_allotted` | The case is not allotted to an officer; allot it instead. | The case has no dealing officer; assign it instead. |
   | `T.errors.stale` | The case was allotted to someone else meanwhile. … | The case was assigned to someone else meanwhile. … |
   | `T.own.takeOverText` | The case is allotted to ${name}. Take it over? … | ${name} is the dealing officer. Take the case over? … |

7. **The server's texts:**
   - **`alert_rules.py`, the in-app and e-mail alert:**
     - title "Case assigned: <case>";
     - body "Assigned to <officer, else the unit code, else your unit> by <actor>.";
     - take-over body "The case assigned to you was taken over by <name>."
   - **`CUSTODY_REASON_LABELS["allotted"]`:** "Assigned". The journey, the custody codes API and the "case moved"
     alert's reason read it.
   - **`PERMISSION_LABELS[cases.allot]`:** "Assign Cases" — "Choose the responsible unit and the dealing officer for a
     case of the department." `aslms seed` (in `init`) already refreshes permission labels.
   - **`reports.py`:**
     - the department-scope grouping columns read "Responsible unit code" and "Responsible unit";
     - `NOT_ALLOTTED`'s label reads "Whole department (no responsible unit)". The code `DEPT` stays.
   - **Error messages:** `ownership.py` "the case was assigned to someone else meanwhile" and "the case is no longer
     assigned to the leaving officer"; `memberships.py` "every assigned case and case with them needs a target".
   - **What is not rewritten:** alerts and audit rows written before the change keep their stored text. They are
     records.

8. **One reference-data migration for the two labels stored in the database** (the next free number at build). It
   follows the 0025 precedent:
   - `ref_event_type` code `allotted`: `label` and `timeline_label` "Allotted" → "Assigned";
   - `ref_role` code `dept_officer`: `description` "Works on allotted cases: moves the case, adds notes and documents,
     and receives alerts." → "Works on cases assigned to them: moves the case, adds notes and documents, and receives
     alerts.".

   **How it behaves:**
   - each change applies only while the column still holds the seeded text, so a description the Super Administrator
     edited through Edit Name is kept;
   - the downgrade reverses each change under the same condition;
   - no `audit_log` row (the 0016 and 0025 precedent);
   - `seed.py` carries the new texts for fresh databases: `EVENT_TIMELINE_LABELS["allotted"]`, the
     `ref_event_type` label and `ROLE_DESCRIPTIONS`.

   **Why a migration is needed:** `aslms seed` does not refresh these two tables' existing rows. Without it the
   journey would still say "Allotted" beside "Assigned" everywhere else.

   **This answers the brief's "no migration":** the brief asked for frontend wording only and no migration. All
   other changes are code only; these two labels cannot be.

9. **The guards stop "allot" coming back:**
   - **Frontend** (`src/lib/wording.test.ts`): a second rule, `\ballot(s|ted|ting|ment|ments)?\b` (any case), fails
     in any `messages.ts` value or component JSX text. There is no allow-list.
   - **Backend** (`tests/unit/test_wording_guard.py`): the same rule over the module list, plus
     `aslms/services/ownership.py`. Code-like strings (`^[a-z0-9_.:{}]+$`, such as `allotted` and `ownership.allot`)
     and docstrings are skipped, as today.
   - **Title Case:** the new labels follow the Title Case rule, and the `labelRules.ts` guards of both suites cover
     them. "Assign Now (Optional)", "Responsible Unit", "Dealing Officer", "Whole Department", "No Dealing Officer
     Yet" and "Not Assigned Yet" are Title Case. The explanation line and hints are sentences, as hints are.

10. **No rule, visibility or API change.** The OpenAPI descriptions of `/cases/{ref}/allot` (developer text) keep
    "allot". There is no migration beyond decision 8.

## Data

No table or column. One reference-data migration (decision 8), hand-written like 0016 and 0025, with no schema change.
The next free number at build: row 176 `office-head-picker` and row 157 `case-ref-court-prefix` also add migrations.

`schema.md` is unchanged: the seeded labels are reference data, not structure.

## Services

- `services/alert_rules.py`: the texts of decision 7.
- `domain/workflow.py`: `CUSTODY_REASON_LABELS["allotted"] = "Assigned"`.
- `services/access_seed.py`: the `cases.allot` label and description.
- `services/seed.py`: `EVENT_TIMELINE_LABELS["allotted"]`, the `ref_event_type` label for `allotted`, and
  `ROLE_DESCRIPTIONS[DEPT_OFFICER]`.
- `services/reports.py`: the grouping column labels and `NOT_ALLOTTED`'s label.
- `services/ownership.py`, `services/memberships.py`: the error messages of decision 7.

## API

No endpoint, field or function change. These responses carry the new texts:
- alert `title` and `body` (new alerts only);
- custody `reason_label` (`GET /workflow/codes`, the journey);
- `GET /reference/labels` (permission and user-type descriptions);
- report column labels;
- the case timeline labels.
`POST /cases/{ref}/allot` still needs `cases.allot`.

Portal: `lib/messages.ts` (decisions 2-6), `components/claim/ModalActions.tsx`, `components/inbox/dialogs.tsx`
(`ClaimDialog`, `AllotDialog`), `components/case/OwnershipCard.tsx`, `components/inbox/DepartmentCases.tsx`.

## Jobs

None.

## Tests

**vitest:**
- `claim modal: Assign Now section` (`components/claim/*.test.tsx`):
  - the claim step shows the heading "Assign Now (Optional)", the explanation line, and "Responsible Unit" and
    "Dealing Officer" with the empty choices "Whole Department" and "No Dealing Officer Yet";
  - there is no `fieldset` or `legend`;
  - the body still sends `unit_code` / `officer_user_id`.
- `inbox ClaimDialog: Assign Now section` — the same checks.
- `AllotDialog wording`:
  - the title is "Assign This Case" and the confirm button reads "Assign";
  - the choices are Keep As Is (current), "Whole Department" (sends `unit_code: null`) and "No Dealing Officer"
    (sends `officer_user_id: null`).
- `OwnershipCard labels` — "Responsible unit DSE" and "Dealing officer <name>"; an empty part is omitted.
- `DepartmentCases wording`:
  - the column "Responsible Unit · Dealing Officer";
  - "Not Assigned" for a row with neither;
  - the chip "Dealing Officer: Not Assigned Yet", replacing the existing "Officer: Not Allotted" assertion in
    `inbox.test.tsx`.
- `wording guard: no "allot"` (`lib/wording.test.ts`) — the new rule passes on the tree, and a sample string fails.
- The Title Case guard covers the new labels.

**pytest:**
- `test_alerts_generate` — the allotment alert's title starts with "Case assigned"; the existing assertion on "Case
  allotted" changes.
- `test_custody_reason_label_assigned` — `GET /workflow/codes` gives "Assigned" for `allotted`.
- `test_seed_relabels_assign_permission` — after `seed`, `ref_permission` `cases.allot` reads "Assign Cases".
- `test_migration_assign_labels`:
  - the upgrade relabels the `allotted` event type and the `dept_officer` description when they hold the seeded text;
  - it leaves an edited description alone;
  - the downgrade restores them.
- `test_reports_unit_grouping_labels` — the department-scope report columns and the `DEPT` row label.
- `test_wording_guard` — the "allot" rule over the module list plus `ownership.py`.

**uicheck** (at 375, 768 and 1280 px):
- `/claim/recommended (case claim modal, Assign Now)` — the existing modal state, with Claim pressed so the claim step
  and its Assign Now row show.
- `/cases/<ref> (Assign dialog)` — the dialog open from the ownership card.

Both states must give no `doubled-heading`, `gutter` or field-row finding. The two fields sit on one line at 1280 px
and stack at 375 px.

## Verification

1. `pytest -q`, `ruff check`, `npm run lint`, `npm run typecheck` and `npm test` are green.
2. Apply the migration with the `migrate` step, then `init` (seed). Rebuild with `docker compose build`.
3. `docker compose --profile uicheck run --rm uicheck` finds nothing on the two states.
4. At `http://localhost:3000`:
   - **Claim:** Recommended → open a case → Claim. "Assign Now (Optional)" shows the line and the two fields on one row,
     with "Whole Department" and "No Dealing Officer Yet".
   - **Assign:** claim with a dealing officer, then open the case page. The ownership card reads "Dealing officer
     <name>". Its Assign button opens "Assign This Case".
   - **Inbox and alerts:** Department Cases shows "Responsible Unit · Dealing Officer". The officer's Alerts show
     "Case assigned: …".
   - **Journey and audit:** the journey shows "Assigned". The audit log still lists `ownership.allot`.
5. Administration → User Types → Department Officer shows the new description, unless it was edited before.

## Open questions

None.

## Deviations
Recorded by the developer while building (27 Oct 2026); none changes a decision above.
1. **Migration number.** 0029 went to `office-head-picker`, so the reference-data migration is
   `0030_claim_assign_wording.py` (revises 0029); the test file is `test_migration_0030_assign_labels.py`, which also
   holds `test_seed_relabels_assign_permission`. The seed gains `EVENT_TYPE_LABELS` (the `ref_event_type` label of
   `allotted` for fresh databases) beside `EVENT_TIMELINE_LABELS`.
2. **Two more function descriptions.** The guard of decision 9 covers `access_seed.py`, so the descriptions of
   `cases.view_scope` ("Cases owned by, assigned to, or sent to the offices you belong to.") and `cases.take_over`
   ("Take over a case assigned to a colleague in the same department.") say "assigned" too; `aslms seed` refreshes
   them with the other permission labels. The help line of `aslms users memberships end` and the report docstring
   read "assigned" as well.
3. **Function codes inside a sentence.** `ownership.py` refuses with "cases.allot is not enabled for you in <dept>",
   which names the function code. The backend guard strips dotted function codes (`cases.allot`) before applying the
   "allot" rule, as it already skips bare code strings; no other exception and no allow-list.
4. **Hints in the Assign dialog.** The Assign dialog's two fields carry the same hints as the claim dialogs, so the
   fields read the same wherever they appear. The shared pieces are `AssignSection` and `ClaimAssignNow` in
   `components/inbox/dialogs.tsx`; the row's `flex: 1 1 220px` is `.assignRow` in `inbox.module.css`.
5. **Ownership card labels.** "Responsible unit" and "Dealing officer" are parts of the card line in sentence case, as
   decision 4 writes them, so they are listed in `SENTENCE_EXCEPTIONS` of `labelRules.ts` with that reason.
6. **uicheck states.** The Assign dialog state opens the dialog from the header's More Actions menu (the same
   `AllotDialog`), which is present at 375, 768 and 1280 px; the ownership card sits in a collapsed section on
   phones. Both states choose a department when the dialog asks, so the field row shows. `e2e/checks.ts` has no
   `doubled-heading` or `gutter` finding kind; the states are checked by the existing kinds, including the field-row
   alignment. The e2e fixture's custody leg label for `allotted` reads "Assigned".
