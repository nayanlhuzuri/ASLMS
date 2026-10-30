# Design: Close Case — a department's case is Open or Closed

```
slug: close-case
status: awaiting-approval
author: architect
date: 2026-10-30
approved_by: <owner> on <date>
```

## Context
Backlog row 207. The owner decided on 29 Oct 2026 that the department's own view of a case is **Open** or **Closed**, and
that this is separate from the court's status:
- "close case can be added as functionality. and can be closed by The officer the file is with, and the department
  head." Close Case is a grantable function, given by default to department heads and department officers.
- "how can a case be closed if there is no file? someone has to claim the file right?" Only a claimed case can be closed.
- "a case can only be closed if the dispose flag is given by the court." Close Case works only when the court's status
  is disposed.
- Closing needs a remark saying why. The remark is kept as an append-only case note, so anyone who can open the case
  can later read why it was closed. Closing also writes an audit row and a timeline event.
- Reopening: "only when the court's status changes". A closed case reopens by itself when the court's status changes
  from disposed (restored or revived), with an alert to the department.
- "lets remove the disposed by court option ... its the responsibility of the user to close it ... so we can remove this
  head". There is no Disposed tab or heading. Row 206, live since 30 Oct 2026, built the Case Inbox as four tabs and
  left Open / Closed to this row (`docs/design/case-inbox-simplify.md`: the row 207 block and decisions 4, 5 and 9).

**The owner's answers to the first draft (30 Oct 2026).** They are marked "(owner, 30 Oct 2026)" where they apply.
1. Who may close: "only officers of the owning department". A holder from another department may not close. The
   owning department's head may still close wherever the case is.
2. Manual reopen: "Manual reopen keep it as a functionality and by default the superadmin and the department head and
   the department admin can reopen with a reason." The automatic reopen stays as well.
3. "Superadmin can do it." The Super Administrator may close any case, on the same conditions.
4. Confirmed: a case cannot be closed while a transfer is waiting for a decision.
5. Confirmed: the existing "Closed" stage is retired from Set Stage.

**The plan.** The plan (`docs/Legal_Case_Monitoring_Portal_Plan.docx`) does not mention closing or reopening a case. The
nearest sections are §5.7 (custody and workflow) and §5.3 (the case page: "Overview: status, ... owning department and
current custody"). This row adds to them and changes nothing they say. **No deviation from the plan.**

**What is in place (read for this note).**
- **The court's status.** `cases.status` (`pending` / `disposed` / `unknown`) is written only by
  `services/cases.py::apply_core_fields`, from `pend_disp`. Two functions call it:
  - `apply_dossier`, for the full record: court search, refreshes, and the monthly refresh of disposed cases (row 122);
  - `apply_status`, for the Current Status batch, which `services/tracking.py` runs over non-disposed cases and follows
    with `record_status_change`.
- **`cases.closed_at`** already exists. As built it is the **court disposal mark**: set when a record first shows the case
  disposed, and cleared on restoration (`apply_dossier`, design `court-data-freshness`, decision 4).
  `services/tracking.py` reads it as a fallback disposal date. DB_STANDARD §6 describes it as "set on disposal + owner
  closure" (see decision 1).
- **A restoration** (`disposed` → `pending` in `apply_dossier`) already emits `status_changed`. The alert scan then
  raises one `status_changed` alert per restoration to the case's recipients (`services/alerts.py`).
- **Custody** (`services/custody.py`):
  - `move_custody` is the only writer of `custody` and `custody_history`. When the holder membership changes, it makes
    the previous holder's drafts permanent.
  - The other functions are `held(scope=me|office|owned)`, `sent`, `summary_for` and `card` (`can_send`, `can_recall`).
  - `custody_history.reason` has a CHECK listing seven reasons.
- **Notes** (`services/notes.py`):
  - `_insert_note` writes a permanent note with the `note_added` event and the `note.added` audit row.
  - A `source = user` note raises the `new_note` alert (row 121).
  - Corrections supersede.
- **Stages.** The code set `ref_case_stage` already has a stage `closed` ("Closed"), which any `stages.set` holder may
  choose today.
- **The inbox (row 206):**
  - With Me = `GET /custody/held?scope=me|office`;
  - My Cases = `GET /inbox/mine?view=all`;
  - Sent by Me = `GET /custody/sent?still_out=true`;
  - Department = `GET /inbox/claimed?case_state=all`, or `held?scope=owned` for a tracker without whole-department
    sight.

  Disposed rows carry `HearingDate`'s "Disposed" badge.
- **Offices and roles.**
  - The department head is the single active `dept_head` membership of a department (`memberships.head_of`). The
    department admin is its single active `dept_admin` membership (`memberships.admin_of`).
  - A membership's `department_id` is the department that contains its office, so it covers the department's units and
    directorates.
  - The super admin holds every function by design: `DEFAULT_MATRIX` has no row for `super_admin`
    (`services/access_seed.py`).

**Not covered.**
- Closing an unclaimed or watched-only case (owner rule 2).
- Changes to court data, recommendations, the Case Assistant, SourceTrace or NAPIX.
- Archiving or retention after closure. DB_STANDARD §6's 10-year proposal stays with the policy owner.
- A State-wide count of closed cases on the State dashboard or in the four reports (decision 24).

## Decisions

### A. Closing

1. **Open / Closed is a record of its own, `case_closures`, not a column on `cases`.**
   - A case is **Closed** while it has a closure row with `reopened_at IS NULL`. Otherwise it is **Open**, whatever the
     court's status.
   - **Why a table.** A closure has an author, a standing (decision 3), a remark note, a custody leg and a reopening,
     which is automatic or manual and has its own author and reason. A case may be closed, reopened and closed again, and
     every round must stay on record. Lifecycle is state, never deletion (DB_STANDARD §6).
   - `cases.closed_at` keeps its as-built meaning: the court disposal mark. `tracking.py` and the reports read it that
     way, and reusing it would give it two meanings.
   - **Deviation from the wording of DB_STANDARD §6** ("`closed_at` to `cases` (set on disposal + owner closure)"),
     flagged for the owner. The owner closure is recorded in `case_closures`, and closing does not set `cases.closed_at`.
     The scribe records this in `schema.md` and in the decisions log. The plan is unchanged.
   - Alternative: `closed_at` / `closed_by` on `case_ownership`. Refused, because a closure belongs to the case, not to
     one ownership row: a watching department sees the case as Closed too.
   - Alternative: reuse `cases.closed_at`. Refused, for the reasons above.
2. **Two new functions, both in the group "Case Work"** (after "Track Pending Cases"). Each description is within the
   120-character rule.

   | Code | Label | Description | Default types |
   |---|---|---|---|
   | `cases.close` | Close Cases | "Close a disposed case of your department with the reason why. Only the officer who has it or the head can close it." | Department Head, Department Officer (owner, 29 Oct 2026). The Super Administrator (owner, 30 Oct 2026) holds it as it holds every function. |
   | `cases.reopen` | Reopen Cases | "Reopen a closed case of your department, with the reason why. The Super Administrator can reopen any case." | Department Head, Department Admin (owner, 30 Oct 2026). The Super Administrator holds it, as above. |

   - Each function is added to its types directly in `DEFAULT_MATRIX`, not to the shared `_CASE_WORK` set. The other
     types do not get either function by default: Directorate User, Referral Reviewer, Standing Counsel, Central
     Operator, State Oversight and Auditor. Department Admin does not get `cases.close`, and Department Officer does not
     get `cases.reopen`.
   - The super admin's "default" needs no matrix row. `super_admin` always has every function, and the seed writes no
     `role_permissions` rows for it. Decisions 3 and 18 give the super admin the standing the owner asked for.
   - The super admin may switch either function on for other types or for one person, under the delegation rule.
     Holding a function is necessary but not enough: decisions 3 and 18 decide on which cases it works.
   - The owner said "(Close Case)". The function list uses plural verbs ("Claim Cases", "Assign Cases", "Recall
     Cases"), so the functions read "Close Cases" and "Reopen Cases". The buttons and dialogs read "Close Case" and
     "Reopen Case".
3. **Who may close (owner, 29 and 30 Oct 2026).** The service checks this membership by membership. The acting
   membership must hold `cases.close` and stand in one of three ways, tried in this order:

   | # | Standing | The rule |
   |---|---|---|
   | 1 | **Holder** | The caller's membership holds the case (`custody.holder_membership_id`), **and** that membership belongs to the owning department: its `department_id` is the active primary owner's office. That includes the department's own office and its units and directorates (owner, 30 Oct 2026: "only officers of the owning department"). |
   | 2 | **Head** | The caller's membership is the active `dept_head` membership of the owning department. The head may close **wherever the case is**: with an officer, with the department office or one of its units with no named officer, or with an officer of another department. |
   | 3 | **Super Administrator** | The caller's `super_admin` membership. It may close **any** case (owner, 30 Oct 2026: "Superadmin can do it."), on the same conditions as everyone else (decision 4). |

   - The closure records the standing as `closed_as`: `holder`, `head` or `super_admin`.
   - Nobody else may close: not a holder from another department, not the Department Admin (unless they hold the case
     as an officer of the department and have the function), not a recaller, and not a State-wide reader.
   - A holder from another department, typically an officer sent the case for an opinion, sends it back. The department
     then closes it.
4. **Which cases can be closed.** Every condition below must hold. The service checks them under the case row lock, in
   this order, and the portal shows each refusal in plain words:

   | # | Condition | Refusal |
   |---|---|---|
   | 1 | The caller can open the case (the super admin can open every case) | 404 |
   | 2 | The remark is 3 to 2,000 characters | 400 `bad_field` |
   | 3 | The caller has `cases.close` in some membership | 403 `function_missing` |
   | 4 | The case has an active primary owner and a custody row | 409 `not_owned` |
   | 5 | The case has no open closure | 409 `already_closed` |
   | 6 | `cases.status = disposed` | 409 `not_disposed` |
   | 7 | No transfer is waiting for a decision (`ownership_transfers.status = requested`; owner, 30 Oct 2026, confirmed) | 409 `transfer_open` |
   | 8 | The caller may close as holder, head or super admin (decision 3) | 403 `not_closer` |

   - The remark limits are the existing custody remark limits (`REMARK_MIN`, `REMARK_MAX`), so a remark means the same
     everywhere.
   - A case reopened by hand may be closed again later, on the same conditions. Its court status must still be
     disposed (owner, 30 Oct 2026).
5. **The closing remark is a permanent case note of a new kind, `closing`** ("Closing remark", shown as "Closing
   Remark").
   - It is written through `notes._insert_note`, so it gets a `ref_no`, a `note_added` event and a `note.added` audit
     row, like any note.
   - Its visibility is fixed at `case_scope`: everyone who can open the case can read it (owner rule 4). The user does
     not choose the visibility.
   - Its office is the closer's acting membership office. Its `custody_leg_id` is the `closed` leg.
   - The kind cannot be chosen in Add Note: it is not `selectable` in `/workflow/codes`, and `check_kind` refuses it.
   - It is corrected only by a superseding note, under the existing correction rule (its author, or a whole-department
     membership of its office's department). The correction keeps the kind and the visibility. `case_closures.note_id`
     keeps pointing at the original, and the notes trail shows the chain.
   - The closing note raises the existing `new_note` alert to the people working on the case who can read it, author
     excluded. That is how the department hears of a closure. **There is no separate "case closed" alert.**
6. **Closing ends the case's movement.** In one transaction:
   1. `move_custody(reason="closed")` writes a leg to the **owning department's office**, with no officer, no membership,
      `pending_action = none` and no due date. The previous holder's drafts become permanent here, as on every move, so
      they come before the closing note in the trail.
   2. The closing note is written (decision 5).
   3. The `case_closures` row is written.
   4. The event and the audit row are written (decision 7).

   - **The leg carries no remark.** The note is the single record of why, and `case_closures` links the leg to the
     note. `closed` is not added to `REMARK_REASONS`.
   - **The case leaves With Me**, because no person holds it. It also leaves "With My Offices" and every custody count
     (decision 15).
   - **Resting the case at the department office widens no one's sight.** A department-office member without
     whole-department sight sees custody only personally, and a unit member's office-wide custody basis covers only the
     unit's subtree (`visibility`; `custody-workflow`, decision 9).
   - **A closer may lose sight of the case.** A department-office officer who saw the case only because they held it
     loses sight on closing, as on a send. The response then says `visible: false`.
   - Alternative: leave the holder in place and only clear the pending action. Refused. The officer would still seem to
     hold a closed case, the exit step would move it when they leave, and every list would need a special rule.
7. **Audit and timeline for closing.**
   - **Audit row `case.closed`:**
     - target `case_closure`, with `case_id`;
     - `before`: the custody summary (`card_summary`);
     - `after`: `closed_as`, the owning office code, the leg's `seq_no`, the note's `ref_no`, the remark's length and
       SHA-256 (`digest`, never the text), the drafts made permanent, and `disposal_date`.
   - **Event `case_closed`:**
     - payload: `closure_id`, `office_code` (the owner), `closed_as`, `note_ref_no`, `seq_no`;
     - dedupe key `case_closed:<closure id>`;
     - on the tracking card and in `case_detail.OWNERSHIP_EVENTS`, so everyone who can open the case sees "Case closed"
       on the timeline;
     - never the remark.
   - The `closed` leg emits its `custody_moved` event as every move does. `closed` and `reopened` are in neither
     `RECEIVED_REASONS` nor `TAKEN_REASONS`, so they raise no "received" or "recalled" alert.
8. **A closed case does not move and does not change hands. Its record stays open to additions.**
   - **Refused with 409 `case_closed`** ("This case is closed. It opens again when the court's status changes or when
     it is reopened."):
     - `custody.send` and `custody.recall`;
     - `ownership.allot` (Assign), `take_over` and `request_transfer`.

     `available_actions` and the custody card (`can_send`, `can_recall`) read false for a closed case, so the portal
     offers none of them.
   - **Still allowed:**
     - Add Note (always permanent, because nobody holds the case);
     - Upload;
     - Set Stage;
     - acknowledging alerts;
     - Stop Watching;
     - the Case Assistant;
     - Reopen Case (decision 18).

     Papers and notes may still arrive after closure, such as a certified copy or a compliance note.
   - **The court refresh keeps running** for a closed case exactly as for any disposed case: the monthly slice for a
     year after disposal (row 122), searches and the data load. That is how a restoration is found.
9. **The stage "Closed" is retired from Set Stage** (owner, 30 Oct 2026, confirmed).
   - The migration and the seed set `ref_case_stage.closed` `is_active = false`. `/workflow/codes` and `check_stage` then
     no longer offer or accept it.
   - Past `case_stages` rows keep the stage, and its label reads from the full catalogue as today (`stage_out`,
     `_stage_briefs`).
   - Close Case does not write a stage. Stages stay the officers' guided marks, and "No stage is set by the system"
     (custody-workflow, decision 19) still holds.

### B. Reopening

10. **Two ways to reopen, both with the same effects** (decision 12):
    - **Automatic.** When the court's status changes (owner, 29 Oct 2026).
    - **Manual.** A person reopens the case with a reason (owner, 30 Oct 2026, decision 18).

    One closure is reopened once. A reopened case may be closed again, which starts a new closure row.
11. **The automatic reopen: the court's status reads `pending` while a closure is open.**
    - It runs in either writer: `apply_dossier`, or `apply_status` followed by `record_status_change`. It runs whatever
      the status was just before, so `disposed` → `pending` and `unknown` → `pending` both reopen.
    - `unknown` does **not** reopen. It means a `pend_disp` value the portal cannot read, which is the portal failing to
      read the court, not the court changing its status.
    - Alternative: reopen on any move away from `disposed`. Refused, because a garbled answer would reopen a case the
      department closed.
12. **What any reopen writes.** One transaction, under the case row lock:
    - **On the closure row** (a trigger lets these be set only once, from NULL):
      - `reopened_at`;
      - `reopen_kind` (`automatic` / `manual`);
      - `reopen_leg_id`;
      - `reopened_status`: the court status at the reopening; always `pending` for an automatic one, usually `disposed`
        for a manual one;
      - for a manual reopen, also `reopen_note_id` and the reopener's snapshot (`reopened_by_user_id`,
        `reopened_by_name`, `reopened_by_designation`, `reopened_by_office_code`).
    - **A custody leg.** `move_custody(reason="reopened")` writes a leg to the **owning department's office**, with no
      officer, `pending_action = examine` and no due date. The leg's actor is the system actor "court status"
      (automatic) or the reopener's acting membership (manual).
      - The case then shows under "With My Offices" for the head, in the department's Pending Actions and in the
        Tracking Summary.
      - The head, or a `custody.move` holder who controls the office, sends it on, as for any case resting with an
        office.
      - A manually reopened case that is still disposed also shows "Ready to Close" (decision 15).
    - **Event `case_reopened`:**
      - payload: `closure_id`, `office_code`, `reopen_kind`, `status` [court status before, court status now],
        `closed_at`, and `note_ref_no` for a manual reopen;
      - dedupe key `case_reopened:<closure id>`;
      - on the tracking card and in `OWNERSHIP_EVENTS`;
      - never the reason text.
    - **Audit row `case.reopened`:**
      - target `case_closure`, with `case_id`;
      - the actor: the reopener's acting membership (manual), or the system actor (automatic);
      - `after`: `reopen_kind`, `closed_at`, the court status, the leg's `seq_no`, and for a manual reopen the note's
        `ref_no` and the reason's digest (never the text).
    - **One alert to the department** (decision 13).
    - Alternative: return the case to the membership that closed it. Refused. The owner said "with an alert to the
      department", and that membership may have ended. The head decides who works on the case next.
13. **One department alert per reopen.** The alert scan reads `case_reopened`. In both cases the recipients are the
    existing `case_recipients`:
    - the custody holders, which are now the department office's `cases.allot` holders, normally the head and the
      department admin;
    - the assigned officer or unit;
    - watchers.

    The reopener is excluded from a manual reopen's alert.

    | | Automatic | Manual |
    |---|---|---|
    | Kind | the existing `status_changed`, so everyone's notification preferences for status changes keep working | the existing `workflow` (the case's own movement), with `data.event = "reopened"` |
    | Key | `status_changed:<case id>:reopened:<event id>` | `workflow:reopened:<event id>` |
    | Severity | `high` | `high` |
    | Title | "Case reopened: <case>" | "Case reopened: <case>" |
    | Body | "The court records show the case as pending again. It had been closed on <date> and is open again, with the department for action." | "Reopened by <name>, <designation>, with a reason in note <ref>. It is open again, with the department for action." |

    - **No double alerts.**
      - The restoration `status_changed` event carries `reopened: true` when the same apply reopened the case, and the
        scan skips it (counter `skipped_reopened`). A restoration of a closed case therefore raises one alert, not two.
      - A reopening note raises no `new_note` alert (the scan skips kind `reopening`), because the reopen alert already
        names the note.
    - Alternative: a new alert kind `case_reopened`. Refused, because it needs a new reference row and a new preference
      for the same message.
14. **A closed case found on a new cause list is refreshed from the court.**
    - The cause-list apply (`services/causelists.py`) queues one `dossier` fetch for an entry matched to an existing
      case with an open closure. It uses `queue.enqueue` with the lane and priority of the cause list's origin and
      `requeue=False`, so at most one fetch waits per case.
    - A restored case is usually listed before anything else shows it. Without this, a closed case more than a year
      after disposal, outside row 122's monthly slice, would never be seen as reopened.
    - Only closed cases are covered, so the extra court calls are few. The quota guard and the request slots apply as
      for every fetch.

### C. The Case Inbox (row 206's four tabs)

15. **With Me loses closed cases by itself, and a disposed case that is still open carries a nudge.**
    - A closed case has no personal holder, so `held(scope=me)` and the With Me count (`/inbox/mine/counts.files`)
      leave it out. The dashboard's "Cases with Me" figure and the sidebar pill follow.
    - `held` also leaves closed cases out for `scope=office` and `scope=owned`, through
      `NOT case_closure.closed_condition(...)`.
    - `summary_for` (the Tracking Summary, the department dashboard's Pending Actions and the Pending Actions report)
      leaves closed cases out of `held` and of every figure.
    - A disposed case with me is Open. Its row shows a **"Ready to Close"** badge (warning tone) beside `HearingDate`'s
      "Disposed".
    - A new quick chip, **"Ready to Close"**, sets the existing shared filter `case_status=disposed`. No new API filter.
    - The order is unchanged: due date first.
16. **My Cases gains an Open / Closed switch** (the kit `SegmentedSwitch`). Open is the default and has no URL key.
    Closed is `closure=closed`, a fixed key that Clear All keeps.
    - **Open** is row 206's list without closed cases, in row 206's order: active cases first, then disposed. A disposed
      open row carries "Ready to Close".
    - **Closed** lists the closed cases the caller is connected to, newest closure first, each with a neutral
      **"Closed"** badge. Connected means "assigned to me or my unit" or "claimed by me": the With Me reason ends at
      closing, because nobody holds a closed case.
    - The count line "n of m" takes m from `/inbox/mine/counts`: `all_open` or `all_closed`.
    - An incoming `case_state` is still ignored (row 206).
17. **Department gains the same switch.**
    - **Open** lists the department's active and disposed cases without the closed ones, with row 206's order, chips
      and filters.
    - **Closed** lists the closed cases, newest closure first. The quick chips Overdue and With Another Office are
      hidden and their keys dropped, because a closed case does not move. Unit, Officer, Stage, Next Hearing and the
      More Filters stay.
    - m is `claimed_open` or `claimed_closed` of the selected `/inbox/counts` block.
    - The tracker fallback list (`held?scope=owned`, row 206 decision 11) has no switch: it lists pending work, and
      closed cases never appear in it.
    - **Sent by Me is unchanged.** A send overtaken by a closure is no longer the current leg, so it leaves the "still
      out" list and stays under Show Earlier, muted.
    - **Every case summary carries `closed: bool | null`** (`CaseSummaryOut`). It is filled in one batched query in
      `inbox.summaries`, and is `null` for a case in `hidden`. The Closed and Ready to Close badges are drawn on the
      four inbox tabs and on Search results.

### D. Manual reopen (owner, 30 Oct 2026)

18. **Who may reopen, and on what.** The acting membership must hold `cases.reopen` and be one of:
    - **a membership of the owning department**: its `department_id` is the active primary owner's office. By default
      that means the Department Head and the Department Admin, for their own department's cases only. A department
      member whose type or override was given the function may reopen the same way;
    - **the `super_admin` membership**, for any case.

    The checks run in this order, under the case row lock:

    | # | Condition | Refusal |
    |---|---|---|
    | 1 | The caller can open the case | 404 |
    | 2 | The reason is 3 to 2,000 characters | 400 `bad_field` |
    | 3 | The caller has `cases.reopen` in some membership | 403 `function_missing` |
    | 4 | The case has an open closure | 409 `not_closed` |
    | 5 | The caller stands as a member of the owning department, or as super admin | 403 `not_reopener` |

    - There is no court-status condition: a disposed case may be reopened (owner, 30 Oct 2026). It may then be closed
      again under decision 4.
    - The reason is a permanent case note of the new kind `reopening` ("Reopening remark", shown as "Reopening
      Remark"), on the same rules as the closing remark (decision 5):
      - visibility fixed at `case_scope`;
      - not selectable in Add Note;
      - corrected only by a superseding note;
      - office: the reopener's acting membership office;
      - `custody_leg_id`: the `reopened` leg.

      Its `ref_no` is in `case_closures.reopen_note_id`.
    - Effects, event, audit and alert: decisions 12 and 13. The leg comes first, then the note, then the closure row
      update, the event and the audit row.
    - Alternative: let only the head and the super admin reopen. Refused, because the owner named the Department Admin.

### E. The case page

19. **The header, the action rail and the two dialogs.**
    - **Header** (`CaseFrame.tsx`):
      - a closed case shows a neutral "Closed" badge after the court status;
      - beside it, the line "Closed on <date> by <name>, <designation>", with **"Read the Closing Remark"** opening the
        Notes tab at that note;
      - a reopened case whose current leg is still the `reopened` leg shows either "Reopened on <date>: the court's
        status changed." or "Reopened on <date> by <name>, <designation>", the second with **"Read the Reopening
        Remark"**. The line goes once the case moves on;
      - each remark link is drawn only when the API gives the note's `ref_no`, which it does only when the caller can
        read the note.
    - **Your Task card** (`Rail.tsx`):
      - **When `workflow.close` is true**, the card shows a notice, **"Ready to Close"**: "The court has disposed of this
        case. Close it when the department's work on it is done." It has a primary **"Close Case"** button.
      - **When the caller would be a closer but `workflow.close_blocked` is set**, the notice says why. For
        `transfer_open`: "A transfer of this case is waiting for a decision. Decide or withdraw it first." Nothing is
        shown for `not_disposed`.
      - **For a closed case**, the card shows the closure line in place of the task, and Send and Recall are absent
        (`can_send` and `can_recall` are false).
      - **When `workflow.reopen` is true**, the card adds a secondary **"Reopen Case"** button.
      - **When `workflow.reopen_blocked` is `not_own_department`**, the card says "Only the owning department or the
        Super Administrator can reopen this case."
    - **Close dialog** (`components/workflow/CloseCaseDialog.tsx`, on the Action dialog template):
      - title: "Close This Case";
      - body: "Closing ends this case's movement and clears its pending action. It leaves With Me and moves to Closed in
        My Cases and Department. It opens again by itself if the court's status changes, or when someone allowed to
        reopen cases reopens it with a reason.";
      - with drafts on the case: "Your drafts on this case become permanent notes.";
      - field: **"Why Is This Case Being Closed?"** (required, 3 to 2,000 characters, with a counter), hint "Saved as a
        note that everyone who can open this case can read. A note is never edited; a correction is a new note.";
      - buttons: "Close Case" (primary) and "Cancel".
    - **Reopen dialog** (`components/workflow/ReopenCaseDialog.tsx`, the same template):
      - title: "Reopen This Case";
      - body: "Reopening makes the case open again and puts it with the department, with 'Examine' pending. The
        department is alerted.";
      - field: **"Why Is This Case Being Reopened?"** (required, 3 to 2,000 characters), with the same hint;
      - buttons: "Reopen Case" (primary) and "Cancel".
    - **After closing:**
      - with `visible: true`, the case reloads with the flash "Case closed. The closing remark is note <ref>.";
      - with `visible: false`, the portal goes to `/inbox/with-me` with "Case closed. You can no longer open it: it was
        with you only to work on.".
    - **After reopening:** the case reloads with "Case reopened. The reopening remark is note <ref>.".
    - Refusals show their plain words (decision 25).
    - The existing texts that say when drafts become permanent ("... when the case is sent on or recalled") add "or
      closed".
20. **The server says what the page may offer.**
    - `workflow_actions.available` gains:
      - `close: bool`: every write check of decision 4 passes for the caller, without locking or writing;
      - `close_as: "holder" | "head" | "super_admin" | null`;
      - `close_blocked: "not_disposed" | "transfer_open" | null`. It is set only when the caller holds `cases.close`
        and would be a closer, but condition 6 or 7 fails;
      - `reopen: bool`: every check of decision 18 passes;
      - `reopen_blocked: "not_own_department" | null`. It is set only when the case is closed and the caller holds
        `cases.reopen`, but not in the owning department's membership or as super admin.
    - `GET /cases/{ref}` gains `closure`: the latest closure of the case (open or reopened), or null.
    - The custody card gains `closed: bool`. `can_send` and `can_recall` are false while the case is closed.
    - The custody reasons `closed` ("Closed") and `reopened` ("Reopened") join `/workflow/codes`, so the journey and the
      remarks page can label the legs.

### F. Dashboard and reports

21. **Personal dashboard** (`GET /dashboard/me`): a new attention kind, `ready_to_close`.
    - It lists the disposed cases held by the caller through a membership that holds `cases.close` and belongs to the
      owning department, visible and not merged.
    - Each item has the title "Ready to Close" and the detail "Disposed by the court on <date>", and links to the case
      page.
    - It comes after `due_soon` and before `file_received`, and leaves out cases already listed, as the other kinds do
      (portal-ui-polish, decision 13).
    - The five headline figures are unchanged.
22. **Department dashboard** (`GET /dashboard/department`):
    - `cases` gains `to_close` (primary-owned, disposed, open) and `closed` (primary-owned, closed);
    - `attention` gains `to_close`;
    - the Attention card shows "Ready to Close (n)", linking to
      `/inbox/department?department=<code>&case_status=disposed` (Open is the default);
    - the "Cases Claimed and Active" figure and its "n disposed" line are unchanged.
23. **The audit log.** `case.closed` and `case.reopened` appear in the Audit Log's action list under the `case` group, as
    every code does. A manual `case.reopened` row names the reopener. An automatic one names the system actor "court
    status".
24. **The State dashboard and the four reports are unchanged.**
    - They count the court's figures (pending cases, hearings and disposals) and pending actions. Closing changes no
      court figure, and pending actions already leave closed cases out (decision 15).
    - A State-wide count of closed cases was not asked for.

### G. Wording, plan and earlier decisions

25. **New and changed user text.** All of it is in Title Case under the existing helper, and passes both wording guards
    (`lib/wording.test.ts`, `lib/labels.test.ts`) and the backend guard. It has no custody-sense "file", no "allot" and no
    eOffice words.
    - **Actions and titles:** "Close Case", "Close This Case", "Reopen Case", "Reopen This Case", "Read the Closing
      Remark", "Read the Reopening Remark".
    - **Switch, badges and chip:** "Open", "Closed", "Ready to Close".
    - **Fields:** "Why Is This Case Being Closed?", "Why Is This Case Being Reopened?".
    - **Lines and dialog texts:** the header lines, the rail notices, the two dialog bodies and hints, and the three
      flashes of decision 19.
    - **Empty states:**
      - My Cases, Closed: "Closed cases you are connected to appear here.";
      - Department, Closed: "The department's closed cases appear here.".
    - **Refusals:**

      | Code | Text |
      |---|---|
      | `case_closed` | decision 8's text |
      | `not_disposed` | "The court has not disposed of this case, so it cannot be closed." |
      | `already_closed` | "This case is already closed." |
      | `not_closer` | "Only an officer of the owning department who has the case, the Head of Department or the Super Administrator can close it." |
      | `transfer_open` | decision 19's text |
      | `not_closed` | "This case is not closed." |
      | `not_reopener` | "Only the owning department or the Super Administrator can reopen this case." |

    - **Labels:**
      - "Close Cases" and "Reopen Cases", with their descriptions;
      - the note kinds "Closing Remark" and "Reopening Remark";
      - the custody reasons "Closed" and "Reopened";
      - the timeline entries "Case Closed" and "Case Reopened";
      - the dashboard's "Ready to Close" and "Disposed by the court on <date>".
    - **Server alert texts:** decision 13.
26. **Earlier decisions this note changes, all for the owner's approval:**
    - case-inbox-simplify, decisions 4 and 9: My Cases and Department gain the Open / Closed switch that row 206
      reserved. Decision 5 of the same note is kept: a disposed case stays in With Me until it is closed;
    - custody-workflow, decisions 2 and 27: two custody reasons are added;
    - custody-workflow, decision 19: the stage `closed` is retired (decision 9; owner, 30 Oct 2026);
    - row 207's first wording ("No manual reopen"): replaced by the owner's answer of 30 Oct 2026 (decision 18);
    - DB_STANDARD §6: the owner closure is recorded outside `cases.closed_at` (decision 1, flagged).

    Recommend-and-claim, visibility, the notes rule, NAPIX and the Case Assistant are untouched.

## Data
**Migration.** **0035** (`0035_close_case.py`, revises 0034). If another row merges a 0035 first, the build takes **the
next free number after the head at that time**. Applied migrations are never edited. `schema.md` takes the paragraphs
below before the migration is written.

**New table** (schema.md, "Phase 2 and 3 tables"):

> **`case_closures`** (transaction; design `close-case`, migration 0035).
>
> **Columns:**
> - id (uuid v7 PK);
> - case_id (→ cases RESTRICT, NOT NULL);
> - office_id (→ offices RESTRICT, NOT NULL: the owning department at closing);
> - ownership_id (→ case_ownership RESTRICT, NOT NULL: the active primary row at closing);
> - closed_as (varchar 12 NOT NULL: `holder` / `head` / `super_admin`);
> - note_id (→ case_notes RESTRICT, NOT NULL, UNIQUE: the closing remark, kind `closing`);
> - close_leg_id (→ custody_history RESTRICT, NOT NULL, UNIQUE: the `closed` leg);
> - disposal_date (date NULL: the court's `cases.disposal_date` at closing, a snapshot);
> - closed_at (timestamptz NOT NULL default now());
> - reopened_at (timestamptz NULL);
> - reopen_kind (varchar 10 NULL: `automatic` / `manual`);
> - reopen_leg_id (→ custody_history RESTRICT, NULL, UNIQUE: the `reopened` leg);
> - reopened_status (`case_status` NULL: the court status at the reopening);
> - reopen_note_id (→ case_notes RESTRICT, NULL, UNIQUE: the reopening remark, kind `reopening`; manual only);
> - reopened_by_user_id (→ users SET NULL, NULL), reopened_by_name (≤ 200), reopened_by_designation (≤ 200),
>   reopened_by_office_code (≤ 40): the reopener's snapshot, manual only;
> - the actor snapshot (the closer, through the acting membership: `actor_user_id` → users SET NULL, `actor_name`,
>   `actor_designation`, `actor_office_code`);
> - created_at, updated_at.
>
> **Checks:**
> - `ck_case_closures_closed_as`: `closed_as IN ('holder', 'head', 'super_admin')`;
> - `ck_case_closures_reopen_kind`: `reopen_kind IS NULL OR reopen_kind IN ('automatic', 'manual')`;
> - `ck_case_closures_reopened`:
>   `(reopened_at IS NULL) = (reopen_leg_id IS NULL) AND (reopened_at IS NULL) = (reopened_status IS NULL) AND
>   (reopened_at IS NULL) = (reopen_kind IS NULL)`;
> - `ck_case_closures_reopen_manual`:
>   `(reopen_kind = 'manual') = (reopen_note_id IS NOT NULL) AND (reopen_kind = 'manual') = (reopened_by_name IS NOT
>   NULL) AND (reopen_kind IS DISTINCT FROM 'automatic' OR reopened_status = 'pending')`.
>
> **Indexes:**
> - partial unique `ix_case_closures_open` (case_id) WHERE `reopened_at IS NULL`: at most one open closure per case;
> - `ix_case_closures_case_closed` (case_id, closed_at DESC).
>
> **Triggers:**
> - `case_closures_reopen_once` (BEFORE UPDATE, function `aslms_case_closure_reopen_once`) refuses any change except
>   `updated_at` and the reopening columns (`reopened_at`, `reopen_kind`, `reopen_leg_id`, `reopened_status`,
>   `reopen_note_id`, `reopened_by_*`). It allows those only from NULL, and once: a closure is reopened once;
> - `set_updated_at`.
>
> **Class and grants:**
> - `COMMENT ON TABLE` `class=transaction`.
> - In `MUTABLE_TABLES`. Not in `APPEND_ONLY_TABLES` (it has one update, the reopening), and not in `CASCADE_TABLES`.
> - `aslms_owner` ALL; `aslms_readonly` SELECT; `aslms_app` SELECT, INSERT and UPDATE. No DELETE: a closure is a legal
>   record.
>
> **Rules:**
> - Written only by `services/case_closure.py`: `close` inserts; `reopen_on_court_status` and `reopen` update.
> - A case is **Closed** while a row with `reopened_at IS NULL` exists, and **Open** otherwise.
> - No `created_by` / `updated_by`: the two snapshots are the audit columns (DB_STANDARD §5).
> - Never deleted.

**Changed rows of schema.md:**
- **`custody_history`.** `reason` gains two values:
  - `closed`: a Close Case leg to the owning department's office, with no officer, `pending_action = none`, no due date
    and no remark;
  - `reopened`: a reopen leg, automatic or manual, to the owning department's office, with no officer,
    `pending_action = examine`, no due date and no remark. Its actor is "court status" or the reopener.

  CHECK `ck_custody_history_reason` is dropped and added again with nine reasons. `ck_custody_history_remark` is
  unchanged.
- **`custody`.** "Written only by `services/custody.py::move_custody`" gains `closed` and `reopened`. A closed case's row
  rests at the owning department's office. `held`, `summary_for` and every custody count leave closed cases out.
- **`case_notes`.** Two new kinds:
  - `closing`: the closing remark, written only by Close Case;
  - `reopening`: the reopening remark, written only by Reopen Case.

  Both are fixed to `case_scope` and never selectable.
- **`cases`.** No change. `closed_at` stays the court disposal mark: set on disposal, cleared on restoration. The
  department's Open / Closed is in `case_closures` (decision 1).

**Reference rows.** They are hard-coded in the migration with `ON CONFLICT (code) DO NOTHING` and no application
import, as 0016, 0018, 0022 and 0034 do. The seed carries the same rows.

| Code set | Code | Row |
|---|---|---|
| `ref_event_type` | `case_closed` | label "Case closed", timeline label "Case closed", on the tracking card, sort 400 |
| `ref_event_type` | `case_reopened` | label "Case reopened", timeline label "Case reopened", on the tracking card, sort 410 |
| `ref_note_kind` | `closing` | label "Closing remark", sorted after `hand_over` |
| `ref_note_kind` | `reopening` | label "Reopening remark", sorted after `closing` |
| `ref_case_stage` | `closed` | `is_active` set to false, only while it is true; the downgrade restores it under the mirror condition |

- No new `ref_alert_kind`: decision 13 reuses `status_changed` and `workflow`.
- **The two functions need no schema change**, because `permission` is a varchar code. The seed (`init`, after
  `migrate`) inserts their `ref_permission` rows and the missing `role_permissions` rows:
  - `cases.close` enabled for `dept_head` and `dept_officer`;
  - `cases.reopen` enabled for `dept_head` and `dept_admin`;
  - both disabled for the other types;
  - `super_admin` has no rows, because it holds every function.
- **Model changes:**
  - `Permission.CASES_CLOSE` and `CASES_REOPEN`;
  - `EventType.CASE_CLOSED` and `CASE_REOPENED`;
  - `NoteKind.CLOSING` and `REOPENING`;
  - `CUSTODY_REASONS` and `CUSTODY_REASON_LABELS` gain `closed` ("Closed") and `reopened` ("Reopened").

**Downgrade.** It refuses (a restore is needed, runbook section 6) while any of these exist:
- a `case_closures` row;
- a `custody_history` row with reason `closed` or `reopened`;
- a `case_notes` row of kind `closing` or `reopening`.

Otherwise it:
1. drops the table, its trigger and its function;
2. restores the seven-reason CHECK;
3. deletes the four reference rows if unused;
4. reactivates the stage.

The function rows stay, because the seed owns them.

## Services

**`backend/aslms/services/case_closure.py` (new).** The only writer of `case_closures`.
- `closed_condition(case_id_col) -> ColumnElement[bool]`: an `EXISTS` over `case_closures` with `reopened_at IS NULL`,
  correlated on the given column. It is read by `held`, `summary_for`, `my_cases`, `inbox` and `dashboard`.
- `open_closure(session, case) -> CaseClosure | None`.
- `closer_member(session, user, case, custody) -> tuple[Member, "holder" | "head" | "super_admin"] | None` (decision 3).
  Every candidate membership must hold `cases.close`. The candidates, in order:
  1. the holder membership (`custody.holder_member`) when its `department` is the primary owner's office;
  2. the caller's membership whose `membership_id` is `memberships.head_of(owner office).id`;
  3. `access.super_admin_member`.
- `reopener_member(session, user, case) -> Member | None` (decision 18): the first caller membership holding
  `cases.reopen` whose `department` is the primary owner's office; else the super admin membership.
- `check_close(...)` and `check_reopen(...)`: the checks of decisions 4 and 18, without locking or writing. They feed
  `workflow_actions.available`.
- `close(session, actor, user, case, *, remark) -> CloseResult`:
  - checks in the order of decision 4, taking `lock_case` before condition 4;
  - `actor = access.actor_as(actor, member)`;
  - writes the `closed` leg (`move_custody` to the primary owner's office), the closing note (`notes.add_system_kind_note`
    with kind `closing`), the closure row, the `case_closed` event and the `case.closed` audit row;
  - returns the closure, the note, the drafts made permanent and the leg.
- `reopen(session, actor, user, case, *, reason) -> ReopenResult` (decision 18):
  - checks in order, with the lock;
  - `actor = access.actor_as(actor, member)`;
  - then `_apply_reopen(kind="manual", actor, note_body=reason)`.
- `reopen_on_court_status(session, case) -> CaseClosure | None` (decision 11):
  - does nothing unless `case.status == pending` and an open closure exists (read `FOR UPDATE` after `lock_case`);
  - otherwise calls `_apply_reopen(kind="automatic", Actor.system("court status"))`;
  - idempotent: a second call finds no open closure.
- `_apply_reopen` (decision 12):
  - writes the `reopened` leg (office = the primary owner's office, or `closure.office_id` if somehow none);
  - for a manual reopen, the `reopening` note;
  - the closure row's reopening columns, the `case_reopened` event and the `case.reopened` audit row.
- `refuse_if_closed(session, case, error)`: raises the calling module's conflict with code `case_closed`.
- `brief(session, user, closure) -> dict`: the `CaseClosureOut` shape. `note_ref_no` and `reopen_note_ref_no` are
  given only when `visibility.can_view_note` passes for the caller.

**`services/notes.py`.**
- `SYSTEM_KINDS = frozenset({NoteKind.CLOSING, NoteKind.REOPENING})`. `check_kind` refuses them ("note kind ... cannot
  be chosen"), and `kinds()` lists them with `selectable: false`.
- New `add_system_kind_note(session, actor, member, case, custody, *, kind, body) -> CaseNote`: `_insert_note` with a
  kind from `SYSTEM_KINDS`, visibility `case_scope`, no files and no links.
- Corrections are unchanged. A correction of either kind keeps the kind and the visibility.

**`services/custody.py`.**
- `send` and `recall` call `case_closure.refuse_if_closed` right after `require_owned` (409 `case_closed`).
- `held` adds `~case_closure.closed_condition(HELD.case_id)` for every scope. `summary_for` adds it on `Custody.case_id`.
- `card` returns `closed`, and forces `can_send` and `can_recall` to false while the case is closed.
- `move_custody` is unchanged: the new reasons come from `CUSTODY_REASONS`.

**`services/ownership.py`.**
- `_check_allot`, `_check_take_over` and `_check_request_transfer` refuse a closed case (`OwnershipError`, code
  `case_closed`), so `available_actions` reads false and the writes refuse.
- `_check_decide_transfer` needs no rule: no transfer can be open on a closed case (condition 7, and requests are
  refused).

**`services/cases.py`.**
- In `apply_dossier`, after the record is applied and before the status events:
  `reopened = case_closure.reopen_on_court_status(session, case)`.
- The restoration `status_changed` payload gains `reopened: true` when `reopened` is not None.
- `apply_core_fields` is unchanged and stays the only writer of `status`.

**`services/tracking.py`.** In `record_status_change`, when `status` changed and the case is now `pending`, it calls
`reopen_on_court_status` before emitting, and adds `reopened: true` to the payload when the case was reopened.

**`services/causelists.py`.** For an entry matched to an existing case with an open closure, it calls
`queue.enqueue(FetchKind.DOSSIER, cnr or court ref, origin.dossier_priority(), lane=origin.lane, ...)` once
(decision 14).

**`services/alerts.py` and `alert_rules.py`.**
- `EventType.CASE_REOPENED` joins the scanned types. Its handler raises the alert of decision 13 through `raise_alert`
  with `case_recipients()`: kind `status_changed` for `reopen_kind = automatic`, and kind `workflow` with
  `event = "reopened"` for `manual`, excluding the actor.
- The `status_changed` handler skips a payload with `reopened: true` (counter `skipped_reopened`).
- The `new_note` handler skips notes of kind `reopening` (counter `skipped_reopening_note`).
- `alert_rules.text` gives the two titles and bodies of decision 13.
- `case_closed` raises nothing: the closing note's `new_note` alert covers it.

**`services/my_cases.py`.**
- `mine` and `mine_stmt` take `closure: "open" | "closed" | "all" = "all"`, applied through `closed_condition(Case.id)`
  or its negation. Any other value is 400.
- With `closed`, the order is the open closure's `closed_at` descending, then the case number and id. Otherwise the order
  is unchanged.
- `mine_counts` adds `all_open` and `all_closed`, which split the `all` view.

**`services/inbox.py`.**
- `claimed_stmt` and `claimed` take `closure` the same way.
- `claimed_order` puts `closed_at` descending first when `closure=closed`.
- `_counts_for` adds `claimed_open` and `claimed_closed`, so `claimed_open + claimed_closed = claimed_active +
  claimed_disposed`.
- `summaries` fills `closed`, which is null for hidden cases.

**`services/workflow_actions.py`.** `available` adds `close`, `close_as`, `close_blocked`, `reopen` and `reopen_blocked`.

**`services/case_detail.py`.**
- The overview adds `closure` (`case_closure.brief` of the latest closure, or null).
- `OWNERSHIP_EVENTS` gains `CASE_CLOSED` and `CASE_REOPENED`.

**`services/dashboard.py`.**
- `personal_headline` adds the `ready_to_close` attention rows (decision 21).
- `department_block` adds `cases.to_close`, `cases.closed` and `attention.to_close`.

**`services/access_seed.py`.**
- `PERMISSION_LABELS` gains `P.CASES_CLOSE` and `P.CASES_REOPEN`.
- `PERMISSION_GROUPS` "case_work" gains them after `CUSTODY_TRACK`.
- `DEFAULT_MATRIX` adds `CASES_CLOSE` to `DEPT_HEAD` and `DEPT_OFFICER`, and `CASES_REOPEN` to `DEPT_HEAD` and
  `DEPT_ADMIN`.

**`services/seed.py`.**
- The reference rows of "Data".
- `NOTE_KIND_LABELS` for the two kinds.
- `TRACKING_CARD_EVENTS` gains both events.
- The `closed` stage is seeded inactive, and switched off on an existing database while it is still active.

No other service writes `case_closures`. Reading paths write nothing.

## API

| Method and path | Permission | Change |
|---|---|---|
| `POST /cases/{ref}/close` (new, `routers/workflow.py`) | `cases.close` on the route. The service checks holder, head or super admin in the acting membership (decision 3). | Body `CaseCloseIn {remark: str (3–2,000)}`. Returns 201 `CaseCloseOut {closure: CaseClosureOut, note_ref_no: str, finalised_notes: [str], card: CustodyCardOut \| null, visible: bool}`. Errors: 404; 400 `bad_field`; 403 `function_missing`, `not_closer`; 409 `not_owned`, `already_closed`, `not_disposed`, `transfer_open`, `concurrent_change`. |
| `POST /cases/{ref}/reopen` (new, `routers/workflow.py`) | `cases.reopen` on the route. The service checks the owning department's membership or super admin (decision 18). | Body `CaseReopenIn {reason: str (3–2,000)}`. Returns 201 `CaseReopenOut {closure: CaseClosureOut, note_ref_no: str, card: CustodyCardOut \| null, visible: bool}`. Errors: 404; 400 `bad_field`; 403 `function_missing`, `not_reopener`; 409 `not_closed`, `concurrent_change`. |
| `GET /cases/{ref}` | `cases.view_scope` or `cases.view_all` (unchanged) | Adds `closure: CaseClosureOut \| null`. `workflow` adds `close`, `close_as`, `close_blocked`, `reopen` and `reopen_blocked`. The custody card adds `closed`. |
| `GET /cases/{ref}/custody` | unchanged | The card adds `closed`. Legs may carry `closed` and `reopened`. |
| `GET /workflow/codes` | unchanged | `note_kinds` lists `closing` and `reopening` with `selectable: false`. `custody_reasons` adds `closed` and `reopened`. `stages` no longer lists `closed`. |
| `POST /cases/{ref}/custody/send`, `/custody/recall` | unchanged | 409 `case_closed` on a closed case. |
| `POST` assign, take over and request transfer (`routers/ownership.py`) | unchanged | 409 `case_closed` on a closed case. |
| `GET /inbox/mine` | `cases.view_scope` (unchanged) | New `closure=open\|closed\|all`, default `all`, so other callers are unchanged. With `closed`, the newest closure comes first. |
| `GET /inbox/mine/counts` | `cases.view_scope` | Adds `all_open` and `all_closed`. |
| `GET /inbox/claimed` | unchanged | New `closure` parameter, as above. |
| `GET /inbox/counts` | `cases.view_scope` | Each department block adds `claimed_open` and `claimed_closed`. |
| `GET /custody/held` (`me`, `office`, `owned`), `GET /custody/summary` | unchanged | Closed cases are left out. No new parameter. |
| Every list returning `CaseSummaryOut` | unchanged | Adds `closed: bool \| null`. |
| `GET /dashboard/me` | unchanged | Attention kind `ready_to_close`. |
| `GET /dashboard/department` | unchanged | `cases.to_close`, `cases.closed` and `attention.to_close`. |

`CaseClosureOut` has these fields:
- `closed_at`, `closed_as`;
- `closed_by: {name, designation, office_code}`;
- `office_code`, `note_ref_no: str | null`, `disposal_date`;
- `reopened_at`, `reopen_kind`, `reopened_status`;
- `reopened_by: {name, designation, office_code} | null`;
- `reopen_note_ref_no: str | null`.

**Visibility.** Every path applies the existing server-side case visibility. The note references follow the note rule,
and `closed` is withheld for hidden cases. The developer regenerates `frontend/openapi.json` and the generated client
during the build.

## Jobs
- No new job and no new schedule.
- The cause-list apply queues one `dossier` fetch for a closed case it finds listed (decision 14). The fetch uses kind
  `dossier`, the case's CNR (or the court reference), and the origin's lane and dossier priority. The queue removes
  duplicates.
- The automatic reopen runs inside whichever job applies the court's answer.
- The 5-minute alert scan picks up `case_reopened`.

## Tests

**Backend, database** (`backend/tests/db/`, with the scripted fixtures of `tests/db/conftest.py`; no NAPIX call, and
`NAPIX_ENABLED` is never set):
- **`test_case_close.py` (new):**
  - `test_holder_of_owning_department_closes`: a department officer, and a directorate user of the department whose
    type was given the function, each holding a disposed claimed case, close it. The test checks:
    - one closure row with `closed_as = "holder"`;
    - a `closed` leg to the owner's office, with no officer, pending `none` and no due date;
    - one `closing` note with `case_scope` visibility and the leg as its `custody_leg_id`;
    - one `case_closed` event without the remark;
    - one `case.closed` audit row with the digest and no text.
  - `test_holder_from_other_department_refused`: an officer of another department holding the case, with the function,
    gets `not_closer`. Nothing is written.
  - `test_head_closes_wherever_the_case_is`: held by a department officer, by a unit with no officer, and by an officer of
    another department. `closed_as = "head"`.
  - `test_super_admin_closes_any_case`: `closed_as = "super_admin"`, on the same conditions. A pending case is still
    refused with `not_disposed`.
  - `test_refusals_in_order`:
    - unclaimed → `not_owned`;
    - pending or unknown → `not_disposed`;
    - already closed → `already_closed`;
    - open transfer → `transfer_open`;
    - a department officer not holding the case, the department admin and a State-wide reader → `not_closer`;
    - no function → `function_missing`;
    - a short remark → 400.

    No refusal writes anything.
  - `test_holder_without_function_refused`.
  - `test_drafts_finalised_before_closing_note`.
  - `test_system_kinds_not_selectable`: Add Note with `closing` or `reopening` is 400, and `/workflow/codes` lists both as
    not selectable.
  - `test_closing_note_correction`: a superseding note keeps the kind and visibility, and `note_id` is unchanged.
  - `test_closed_case_does_not_move`:
    - send, recall, assign, take over and request transfer are 409 `case_closed`;
    - `available_actions` and the card read false;
    - add note (permanent), upload and set stage still work.
  - `test_closer_loses_sight_visible_false`.
  - `test_one_open_closure_per_case`, `test_closure_row_update_guard`. A change of `note_id`, `closed_at` or `closed_as`,
    or a second change of any reopening column, is refused. `aslms_app` cannot DELETE.
- **`test_case_reopen.py` (new):**
  - **Automatic reopen:**
    - `test_dossier_restoration_reopens`: `apply_dossier` with a sample record showing `pend_disp = P` on a closed case
      sets `reopen_kind = automatic` and `reopened_status = pending`. It writes a `reopened` leg to the owner office
      with `examine`, one `case_reopened` event and one `case.reopened` audit row with the system actor. The restoration
      `status_changed` payload carries `reopened: true`.
    - `test_status_batch_reopens`.
    - `test_unknown_does_not_reopen`: an unknown status does not reopen; a later `P` does.
    - `test_reopen_idempotent`.
    - `test_automatic_alert_once`: one `status_changed` alert with `data.reopened`, sent to the department office's
      `cases.allot` holders and the assigned officer; the restoration event is counted `skipped_reopened`. A
      restoration of an open case still raises its usual alert.
  - **Manual reopen:**
    - `test_manual_reopen_by_head_and_admin`: the head and the department admin of the owning department each reopen a
      closed, still-disposed case (two cases). The test checks:
      - `reopen_kind = manual`, `reopened_status = disposed`, the reopener's snapshot and `reopen_note_id`;
      - a `reopening` note with `case_scope` visibility linked to the `reopened` leg;
      - the leg's actor is the reopener;
      - one `case_reopened` event and one `case.reopened` audit row naming the reopener, with the reason's digest.
    - `test_manual_reopen_super_admin_any_case`.
    - `test_manual_reopen_refusals`:
      - an open case → `not_closed`;
      - the head of another department, and a department officer of the owning department without the function →
        `not_reopener` and `function_missing` respectively;
      - a short reason → 400.
    - `test_manual_reopen_alert`: one `workflow` alert with `event = reopened` to the department recipients, excluding
      the reopener. No `new_note` alert for the reopening note.
    - `test_close_again_after_manual_reopen`: the case is closed again while still disposed. That makes a second
      closure row, and both rows stay.
  - `test_closed_case_listed_queues_refresh`.
- **Additions to `test_custody_held.py`, `test_custody_sent_still_out.py` and `test_dashboard*.py`:**
  - `test_closed_leaves_held_every_scope`, plus `summary_for` totals;
  - `test_files_count_excludes_closed`;
  - `test_send_overtaken_by_closure_not_still_out`;
  - `test_ready_to_close_attention`, including a holder without the function, or from another department, who gets no
    item;
  - `test_department_block_to_close_and_closed`;
  - a reopened case appears under the head's `scope=office` with `examine`.
- **Additions to `test_my_cases.py` and `test_inbox_claimed.py`:**
  - `test_closure_filter_open_closed_all`;
  - `test_closed_order_newest_first`;
  - `test_counts_split`;
  - `test_summary_closed_null_when_hidden`.
- **`test_workflow_actions.py`:** the five flags agree with what the writes would do. The cases covered:
  - the holder of the owning department;
  - a holder from another department (`close` false, `close_blocked` null);
  - the head;
  - the super admin;
  - a pending case (`not_disposed`);
  - an open transfer;
  - a closed case for its head (`reopen` true);
  - a closed case for another department's head holding `cases.reopen` (`reopen_blocked = "not_own_department"`).
- **`test_stages.py`:** the stage `closed` cannot be set, and past `closed` rows still read their label.
- **`test_migration_0035.py` (new):**
  - the upgrade creates the table, checks, indexes, triggers, grants and comment;
  - the reason CHECK accepts the two new reasons;
  - the four reference rows are added and the stage is inactive;
  - the downgrade refuses while a closure exists, succeeds on an empty table, and restores the stage and the CHECK.
- **`test_app_role.py` and `tests/unit/test_schema_metadata.py`:** `case_closures` is a transaction table, is in
  `MUTABLE_TABLES`, has RESTRICT foreign keys (the snapshot user foreign keys are SET NULL), and `aslms_app` cannot
  DELETE from it.
- **`tests/unit/test_permission_groups.py`:**
  - both functions are in exactly one group;
  - the matrix gives `cases.close` to `dept_head` and `dept_officer` only, and `cases.reopen` to `dept_head` and
    `dept_admin` only;
  - labels and descriptions are within the length rules.
- **`tests/unit/test_wording_guard.py`:** both alert texts and every refusal message pass.
- The existing suites stay green. `ruff check` and `pytest -q` pass.

**Frontend** (vitest):
- **`components/workflow/workflow.test.tsx`:**
  - `CloseCaseDialog`: the remark is required and counted, the drafts line shows only when there are drafts, it posts
    `/cases/{ref}/close`, and `visible: false` goes to `/inbox/with-me`.
  - `ReopenCaseDialog`: the reason is required, it posts `/cases/{ref}/reopen`, and the flash shows the note.
  - Every refusal code shows its text.
- **`components/case/rail.test.tsx` and `case.test.tsx`:**
  - Ready to Close appears only with `workflow.close`;
  - the `transfer_open` text;
  - Reopen Case appears only with `workflow.reopen`;
  - the `not_own_department` text;
  - a closed case shows the badge, the closure line and the remark link (only when it has a `ref_no`), and no Send or
    Recall;
  - the reopened lines for automatic and manual reopens;
  - the journey labels Closed and Reopened.
- **`components/inbox/inbox.test.tsx`:**
  - the switch on My Cases and Department;
  - `closure=open` and `closure=closed` are sent, and Clear All keeps the switch;
  - m comes from the split counts;
  - under Closed, the Department chips are hidden;
  - the tracker fallback has no switch;
  - the Ready to Close and Closed badges.
- **`components/files/cases-list.test.tsx`:** With Me's Ready to Close chip and badge.
- **`components/dashboard/dashboard.test.tsx`:** the `ready_to_close` item, and the department "Ready to Close (n)" link.
- **`lib/filters.test.ts`:** `closure` is a fixed key of `mine` and `department`.
- **`lib/wording.test.ts` and `lib/labels.test.ts`** stay green.
- `npm run typecheck`, `npm run lint` and `npm test` pass.

**uicheck** (`frontend/e2e`), at 375, 768 and 1280 px:
- **States:**
  - `/cases/<sample> (Ready to Close)`;
  - `/cases/<sample> (Close dialog open)`;
  - `/cases/<sample> (closed, Reopen Case)`;
  - `/cases/<sample> (Reopen dialog open)`;
  - `/inbox/my-cases?closure=closed`;
  - `/inbox/department?closure=closed`;
  - `/inbox/with-me (Ready to Close chip)`.
- **Fixtures:**
  - the case detail gains `closure` and the five flags;
  - the `/inbox/mine` and `/inbox/claimed` matchers read `closure`;
  - the counts gain the split figures.
- The generic checks, including `menu-clipped`, pass.

## Verification
1. **Static checks.** `ruff check`, `pytest -q`, and in `frontend/` `npm run typecheck`, `npm run lint` and `npm test`,
   all green.
2. **Migration.**
   - `alembic heads` shows 0035 (or the build's number) as the one head.
   - The `migrate` step applies it. Then `init` (seed) adds the two functions, the reference rows and the
     `role_permissions` rows.
   - `cases.close` is enabled for `dept_head` and `dept_officer`, and `cases.reopen` for `dept_head` and `dept_admin`.
     Both are disabled for the other types.
   - The stage `closed` is inactive.
3. **API checks on the dev proxy.** They need four users and two cases:
   - users: a department officer holding a claimed, court-disposed case of the department; that department's head; its
     department admin; and the super admin;
   - a second disposed case, held by a unit with no officer.

   The checks, in order:
   - `GET /cases/{ref}` as the officer: `workflow.close = true` and `close_as = "holder"`. For a pending case:
     `close = false` and `close_blocked = "not_disposed"`.
   - `POST /cases/{ref}/close` with a remark returns 201, `visible: true`, a `note_ref_no`, and a card with no officer
     holding the case and `closed: true`.
   - The closing note is readable by the officer, the head and an Auditor. `GET /audit?action=case.closed` has one row,
     with the digest and no text.
   - The With Me count (`/inbox/mine/counts.files`) drops by one and equals the dashboard's "Cases with Me".
     `all_open + all_closed = all`.
   - `GET /inbox/claimed?office=<dept>&case_state=all&closure=closed` lists the case first.
     `claimed_open + claimed_closed = claimed_active + claimed_disposed`.
   - Send on the closed case returns 409 `case_closed`. Closing it again returns 409 `already_closed`.
   - As the department admin, `GET /cases/{ref}` shows `workflow.reopen = true`.
     `POST /cases/{ref}/reopen` with a reason returns 201.
     - The case now shows under the head's With Me "With My Offices" with "Examine" pending.
     - One `workflow` alert, `event = reopened`, reaches the head.
     - `GET /audit?action=case.reopened` names the admin.
     - The case is still disposed, so `workflow.close` is true again for the head.
   - The super admin closes the unit-held case (`closed_as = "super_admin"`), then reopens it.
4. **The automatic reopen** is proven by the database tests (decision 11). It cannot be shown live without the court
   restoring a case, and `NAPIX_ENABLED` is never turned on for it.
5. **Browser checks** at http://localhost:3000, by the owner and the tester, at 1280, 768 and 375 px:
   - the officer sees Ready to Close, closes the case with a remark, and sees the flash, the header line and the note;
   - the case leaves With Me and appears under Closed in My Cases and Department;
   - Send and Recall are gone;
   - the department admin sees Reopen Case, reopens the case with a reason, and sees the reopened line and the note;
   - the head is alerted, and Ready to Close (n) appears on the department dashboard;
   - both functions appear under Case Work on the user-type pages.
6. **uicheck** runs on a private network against temporary images (runbook section 16, never on the shared stack). It
   exits 0 with `findings.json` empty, and the run directory is recorded in the cycle report.
7. **The scribe records the change in:**
   - `docs/schema/schema.md` (first);
   - `docs/claude_ASLMS_design_decisions.md`: the rules, including the owner's answers of 30 Oct 2026, and the
     DB_STANDARD §6 note;
   - `docs/ASLMS_Process_Workflows.md`: closing, the automatic and manual reopen, and the Open / Closed switch;
   - CLAUDE.md's current focus: "after row 207 merges: apply 0035 with the `migrate` step, then `init` (seed);
     `docker compose build`". Row 207's backlog text "No manual reopen" is replaced by the manual reopen rule.

## Open questions
None. The owner gave the rules on 29 Oct 2026 and answered the first draft's points on 30 Oct 2026. Where the answers
leave a detail open, the note makes the narrowest choice and names it:
- decision 3: a department admin closes only as a holder of the department;
- decision 13: a manual reopen's alert is of kind `workflow`;
- decision 14: a closed case found on a cause list is refreshed;
- decision 18: anyone in the owning department given `cases.reopen` may reopen.
