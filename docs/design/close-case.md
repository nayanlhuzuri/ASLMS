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
  head." A grantable function, Close Case, given by default to department heads and department officers.
- "how can a case be closed if there is no file? someone has to claim the file right?" Only a claimed case can be closed.
- "a case can only be closed if the dispose flag is given by the court." Close Case works only when the court's status
  is disposed.
- Closing needs a remark saying why. The remark is kept as an append-only case note, so anyone who can open the case
  can later read why it was closed, with an audit row and a timeline event.
- Reopening: "only when the court's status changes". A closed case reopens by itself when the court's status changes
  from disposed (restored or revived), with an alert to the department. There is no manual reopen.
- "lets remove the disposed by court option ... its the responsibility of the user to close it ... so we can remove this
  head". There is no Disposed tab or heading. Row 206 (live since 30 Oct 2026) built the Case Inbox as four tabs and
  left Open / Closed to this row (`docs/design/case-inbox-simplify.md`, the row 207 block and decisions 4, 5 and 9).

**The plan.** The plan (`docs/Legal_Case_Monitoring_Portal_Plan.docx`) does not mention closing or reopening a case. §5.7
(custody and workflow) and §5.3 (case page: "Overview: status, ... owning department and current custody") are the
nearest sections. This row adds to them and changes nothing they say. **No deviation from the plan.**

**What is in place (read for this note).**
- `cases.status` (`pending` / `disposed` / `unknown`) is the court's status, written only by
  `services/cases.py::apply_core_fields` from `pend_disp`. It is called by `apply_dossier` (the full record: court
  search, refreshes, the monthly disposed refresh of row 122) and by `apply_status` (the Current Status batch, which
  `services/tracking.py` runs over non-disposed cases and follows with `record_status_change`).
- `cases.closed_at` already exists. As built it is the **court disposal mark**: set when a record first shows the case
  disposed and cleared on restoration (`apply_dossier`, design `court-data-freshness`, decision 4). `services/tracking.py`
  reads it as a fallback disposal date. DB_STANDARD §6 described it as "set on disposal + owner closure" (decision 1).
- A restoration (`disposed` → `pending` in `apply_dossier`) already emits `status_changed`. The alert scan then raises
  one `status_changed` alert per restoration to the case's recipients (`services/alerts.py`).
- Custody (`services/custody.py`): `move_custody` is the only writer of `custody` / `custody_history`. When the holder
  membership changes, it makes the previous holder's drafts permanent. `held(scope=me|office|owned)`, `sent`,
  `summary_for`, `card` (`can_send`, `can_recall`). `custody_history.reason` has a CHECK listing seven reasons.
- Notes (`services/notes.py`): `_insert_note` writes a permanent note with `note_added` and the `note.added` audit row.
  A `source = user` note raises the `new_note` alert (row 121). Corrections supersede.
- The ref code set `ref_case_stage` already has a stage `closed` ("Closed") that any `stages.set` holder may choose today.
- The inbox (row 206): With Me = `GET /custody/held?scope=me|office`; My Cases = `GET /inbox/mine?view=all`; Sent by Me =
  `GET /custody/sent?still_out=true`; Department = `GET /inbox/claimed?case_state=all`. A tracker without
  whole-department sight gets `held?scope=owned` instead. Disposed rows carry `HearingDate`'s "Disposed" badge.
- The department head is the single active `dept_head` membership of a department (`memberships.head_of`).

**Not covered.**
- Closing an unclaimed or watched-only case: owner rule 2.
- Any manual reopen: owner rule 5.
- Changes to the court data, recommendations, the Case Assistant, SourceTrace or NAPIX.
- Archiving or retention after closure (DB_STANDARD §6's 10-year proposal stays with the policy owner).
- A State-wide count of closed cases on the State dashboard or in the four reports (decision 22).

**Points the owner should look at when approving.** Decisions 3 (an officer of another department holding the case
may close it, as the owner's words say), 9 (a reopen needs the court's status to read **pending**), 10 (on reopen the
case goes to the department, not back to the person who closed it), 12 (a closed case found on a cause list is
refreshed) and 13 (the stage "Closed" is retired). Each one is the literal reading of the owner's rule, or the smallest
safe choice where the rule says nothing.

## Decisions

### A. The rule

1. **Open / Closed is a record of its own, `case_closures`, not a column on `cases`.** A case is **Closed** while it has a
   closure row with `reopened_at IS NULL`. Otherwise it is **Open**, whatever the court's status.
   - Why a table: a closure has an author, a standing (holder or head), a remark note, a custody leg and a reopening.
     A case may be closed, reopened and closed again, and each round must stay on record. Lifecycle is state, never
     deletion (DB_STANDARD §6).
   - `cases.closed_at` keeps its as-built meaning, the court disposal mark. `tracking.py` and the reports read it that
     way, and reusing it would make it mean two things.
   - **Deviation from the DB_STANDARD §6 wording** ("`closed_at` to `cases` (set on disposal + owner closure)"), flagged
     for the owner. The "owner closure" is recorded in `case_closures`, and `cases.closed_at` is not set by it. The
     scribe records this in `schema.md` and in the decisions log. No change to the plan.
   - Alternative: `closed_at` / `closed_by` columns on `case_ownership`. Refused, because closure is about the case, not
     one ownership row: a watching department sees the case as Closed too.
   - Alternative: reuse `cases.closed_at`. Refused for the reasons above.
2. **A new function, `cases.close`, labelled "Close Cases".**
   - Description (at most 120 characters): "Close a disposed case with the reason why. Only the officer the case is with or
     the Head of Department can close it."
   - Group "Case Work", after "Track Pending Cases".
   - **Default: Department Head and Department Officer only** (owner, 29 Oct 2026). It is added to those two types
     directly, not to the shared `_CASE_WORK` set, so Department Administrator, Directorate User, Referral Reviewer,
     Standing Counsel, Central Operator, State Oversight and Auditor do not get it.
   - The super admin may switch it on for other types or for one person, under the delegation rule.
   - Holding the function is necessary but not enough. Decision 3 decides who may close.
   - The owner said "(Close Case)". The function list names its functions as plural verbs ("Claim Cases", "Assign
     Cases", "Recall Cases"), so the function reads "Close Cases". The button and the dialog read "Close Case".
3. **Who may close.** The service checks this, membership by membership. The caller may close in one of two ways:
   - **As holder.** The caller's membership holds the case (`custody.holder_membership_id`), and that membership has
     `cases.close`. This is "the officer the file is with", **whatever department that membership belongs to**: the
     owner named the holder without a limit.
   - **As head.** The caller's membership is the active `dept_head` membership of the department that owns the case (the
     active primary owner), and that membership has `cases.close`. The head may close **wherever the case is**:
     - with an officer;
     - with the department office or one of its units with no named officer (the owner's "the head also closes ...");
     - with an officer of another department.

   No one else may close: not the Department Administrator, not a recaller, not the super admin (who holds every
   function but is neither holder nor head), and not a State-wide reader.
   - When the caller is both holder and head, the closure records "holder".
   - Alternative: let a holder close only through a membership inside the owning department. Refused, because it
     narrows the owner's words. If the owner wants that limit, it is one condition in `closer_member`.
   - **The owner should know:** with no manual reopen, a closure made in error stays until the court's status changes.
     The closer can still correct the closing remark with a superseding note.
4. **Which cases may be closed.** Every condition below must hold. Each is checked under the case row lock, in this
   order, and refusals are written in plain words in the portal:

   | # | Condition | Refusal |
   |---|---|---|
   | 1 | The caller can open the case | 404 |
   | 2 | A remark of 3 to 2,000 characters | 400 `bad_field` |
   | 3 | The caller has `cases.close` in some membership | 403 `function_missing` |
   | 4 | The case has an active primary owner and a custody row | 409 `not_owned` |
   | 5 | No open closure | 409 `already_closed` |
   | 6 | `cases.status = disposed` | 409 `not_disposed` |
   | 7 | No transfer waiting for a decision (`ownership_transfers.status = requested`) | 409 `transfer_open` |
   | 8 | The caller may close as holder or head (decision 3) | 403 `not_closer` |

   - The remark limits are the existing custody remark limits (`REMARK_MIN`, `REMARK_MAX`), so a remark means the same
     everywhere.
   - Condition 7 exists because a transfer accepted after closing would move a closed case. The owner's rules do not
     cover that, so the case is closed only once the transfer is decided or withdrawn.
5. **The remark is a permanent case note of a new kind, `closing` ("Closing remark", shown "Closing Remark").**
   - The service writes it through `notes._insert_note`, so it gets a `ref_no`, the `note_added` event and the
     `note.added` audit row, like any note.
   - Its visibility is fixed at `case_scope`, so everyone who can open the case can read it (owner rule 4). The user does
     not choose the visibility.
   - Its office is the closer's acting membership office. Its `custody_leg_id` is the `closed` leg.
   - The kind cannot be chosen in Add Note: it is not `selectable` in `/workflow/codes`, and `check_kind` refuses it.
   - It may be corrected like any note, by a superseding note from its author or a whole-department membership. The
     correction keeps the kind and the visibility. `case_closures.note_id` keeps pointing at the original, and the
     notes trail shows the chain.
   - The closing note raises the existing `new_note` alert to the people working on the case who can read it (author
     excluded). That is how the department hears of a closure; **no separate "case closed" alert**.
   - Alternative: an existing kind such as `decision`. Refused, because the closing remark should be easy to find and to
     tell apart.
6. **Closing ends the case's movement.** In one transaction:
   1. `move_custody(reason="closed")` writes a leg to the **owning department's office**, with no officer and no
      membership, `pending_action = none` and no due date. The previous holder's drafts become permanent here, as on
      every move, so they come before the closing note in the trail.
   2. The closing note is written (decision 5).
   3. The `case_closures` row is written.
   4. The `case_closed` event and the `case.closed` audit row are written (decision 7).

   - The leg carries no remark. The note is the one record of why, and `case_closures` links the leg to the note.
     `closed` is not added to `REMARK_REASONS`.
   - The case leaves With Me: no person holds it. It also leaves "With My Offices" and every custody count (decision 14).
   - Resting the case at the department office widens no one's sight. A department-office member without
     whole-department sight sees custody only personally, and a unit member's office-wide custody basis covers only
     the unit's subtree (`visibility`, decision 9 of `custody-workflow`).
   - An officer who could open the case only because it was with them loses sight on closing, as on a send. The response
     says `visible: false`.
   - Alternative: leave the holder in place and only clear the pending action. Refused. The officer would still seem to
     hold a closed case, the exit step would move it when they leave, and every list would need a special rule.
7. **Audit and timeline.**
   - Audit `case.closed`:
     - target `case_closure`, with `case_id`;
     - `before`: the custody summary (`card_summary`);
     - `after`: `closed_as`, the owning office code, the leg's `seq_no`, the note's `ref_no`, the remark's length and
       SHA-256 (`digest`, never the text), the drafts made permanent, and `disposal_date`.
   - Event `case_closed`:
     - payload: `closure_id`, `office_code` (owner), `closed_as`, `note_ref_no`, `seq_no`;
     - dedupe key `case_closed:<closure id>`;
     - on the tracking card, and in `case_detail.OWNERSHIP_EVENTS`, so everyone who can open the case sees "Case closed"
       on the timeline;
     - never the remark.
   - The `custody_moved` event of the `closed` leg is emitted as for every move. `closed` is in neither
     `RECEIVED_REASONS` nor `TAKEN_REASONS`, so it raises no "received" or "recalled" alert.
8. **A closed case does not move and does not change hands. Its record stays open to additions.**
   - Refused with 409 `case_closed` ("This case is closed. It opens again only if the court's status changes."):
     - `custody.send` and `custody.recall`;
     - `ownership.allot` (Assign), `take_over` and `request_transfer`.

     `available_actions` and the custody card (`can_send`, `can_recall`) read false for a closed case, so the portal
     offers none of them.
   - Still allowed:
     - Add Note (always permanent: nobody holds the case);
     - Upload;
     - Set Stage;
     - acknowledging alerts;
     - Stop Watching;
     - the Case Assistant.

     Papers and notes may still arrive after closure (a certified copy, a compliance note).
   - The court refresh keeps running for a closed case exactly as for any disposed case: the monthly slice for a year
     after disposal (row 122), searches and the data load. That refresh is how a restoration is found.
   - Alternative: freeze notes and uploads too. Refused, because the owner made only the movement end, and freezing
     records helps no one.
9. **Reopen is automatic only. It happens when the court's status reads `pending` while a closure is open.**
   - The trigger is the court's status becoming `pending` in either writer: `apply_dossier`, or `apply_status` followed
     by `record_status_change`. It does not matter what the status was just before, so `disposed` → `pending` and
     `unknown` → `pending` both reopen.
   - `unknown` (a `pend_disp` value the portal cannot read) does **not** reopen. It is the portal failing to read the
     court, not the court changing its status.
   - No endpoint, no CLI and no screen reopens a case (owner rule 5).
   - Alternative: reopen on any move away from `disposed`. Refused, because a garbled answer would reopen a case the
     department closed.
10. **What a reopen writes.** One transaction, by the system actor "court status", under the case row lock:
    - On the closure row: `reopened_at`, `reopen_leg_id` and `reopened_status = pending`. A trigger allows only these
      columns to be set, and only once.
    - `move_custody(reason="reopened")` writes a leg to the **owning department's office** with no officer,
      `pending_action = examine` and no due date. The case shows under "With My Offices" for the head, in the
      department's Pending Actions and in the tracking summary. The head or a `custody.move` holder who controls the
      office sends it on, as for any case resting with an office.
    - Event `case_reopened`: payload `closure_id`, `office_code`, `status` [previous, `pending`], `closed_at`; dedupe
      `case_reopened:<closure id>`; on the tracking card and in `OWNERSHIP_EVENTS`.
    - Audit `case.reopened`, system actor, target `case_closure`: `closed_at`, the previous and new status, and the
      leg's `seq_no`.
    - Alternative: return the case to the membership that closed it. Refused, because the owner said "with an alert to
      the department", and that membership may have ended. The head decides who works on it next.
11. **One alert on reopen, of the existing kind `status_changed`.**
    - The alert scan reads `case_reopened` and raises one `status_changed` alert:
      - key `status_changed:<case id>:reopened:<event id>`;
      - severity `high`;
      - addressed to the owning department's office;
      - data `{status: "pending", previous_status, reopened: true, closed_at}`;
      - title "Case reopened: <case>";
      - body "The court records show the case as pending again. It had been closed on <date> and is open again, with
        the department for action."
    - Recipients are the existing `case_recipients`: the custody holders (now the department office's `cases.allot`
      holders, normally the head and the department administrator), the assigned officer or unit, and watchers.
    - The restoration `status_changed` event carries `reopened: true` when the same apply reopened the case. The scan
      then skips it (counter `skipped_reopened`), so a restoration of a closed case raises one alert, not two.
    - Using the existing kind keeps every user's notification preferences for status changes working.
    - Alternative: a new alert kind `case_reopened`. Refused: it would need a new reference row and a new preference,
      and say the same thing.
12. **A closed case found on a new cause list is refreshed from the court.**
    - The cause-list apply (`services/causelists.py`) queues one `dossier` fetch:
      - for an entry matched to an existing case with an open closure;
      - through `queue.enqueue`, lane and priority of the cause list's origin, `requeue=False`, so at most one waiting
        fetch per case.
    - A restored case is usually listed before anything else shows it. Without this, a closed case more than a year
      after disposal (outside row 122's monthly slice) would never be seen as reopened.
    - Only closed cases are covered, so the extra court calls are few. The quota guard and the request slots apply as
      for every fetch.
    - Alternative: leave detection to row 122. Refused, because owner rule 5 depends on seeing the change.
13. **The stage "Closed" is retired from Set Stage.**
    - The migration and the seed set `ref_case_stage.closed` `is_active = false`. `/workflow/codes` and `check_stage`
      then no longer offer or accept it.
    - Past `case_stages` rows keep it, and its label reads from the full catalogue as today (`stage_out`,
      `_stage_briefs`).
    - Close Case does not write a stage. Stages stay the officers' guided marks, and "No stage is set by the system"
      (custody-workflow, decision 19) still holds.
    - Alternative: keep the stage. Refused, because a case at the stage "Closed" that is still Open, and still in
      someone's With Me, would be two meanings of one word.

### B. The Case Inbox (row 206's four tabs)

14. **With Me loses closed cases on its own. Disposed cases that are still open carry a nudge.**
    - A closed case has no person holding it, so `held(scope=me)` and the With Me count (`/inbox/mine/counts.files`) leave
      it out. The dashboard's "Cases with Me" and the sidebar pill follow.
    - `held` also leaves out closed cases for `scope=office` and `scope=owned`, through
      `NOT case_closure.closed_condition(...)`. The department office "holds" a closed case only as its resting place.
    - `summary_for` (tracking summary, department dashboard Pending Actions, Pending Actions report) leaves closed cases
      out of `held` and every figure. A closed case has no pending action anyway.
    - A disposed case with me is still Open. Its row shows a **"Ready to Close"** badge (warning tone) beside
      `HearingDate`'s "Disposed".
    - A new quick chip, **"Ready to Close"**, sets the existing shared filter `case_status=disposed`. No new API filter.
    - The order is unchanged (due date first).
15. **My Cases gains an Open / Closed switch** (the kit `SegmentedSwitch`). Open is the default and needs no URL key;
    Closed is `closure=closed`, a fixed key kept by Clear All.
    - **Open:** row 206's list without closed cases, in row 206's order: active first, then disposed. A disposed open row
      carries "Ready to Close".
    - **Closed:** the closed cases the caller is connected to, newest closure first, each with a neutral **"Closed"**
      badge. The connection is "assigned to me or my unit" or "claimed by me": the With Me reason ends at closing,
      because no one holds a closed case. The Your Action column is empty, because no
      one holds a closed case.
    - The count line "n of m" takes m from `/inbox/mine/counts`: `all_open` or `all_closed`.
    - An incoming `case_state` is still ignored (row 206).
16. **Department gains the same switch.**
    - **Open:** the department's active and disposed cases without closed ones; row 206's order, chips and filters.
    - **Closed:** the closed cases, newest closure first. The quick chips Overdue and With Another Office are hidden and
      their keys dropped, because a closed case does not move. Unit, Officer, Stage, Next Hearing and the More Filters
      stay.
    - m is `claimed_open` or `claimed_closed` of the selected `/inbox/counts` block.
    - The tracker fallback list (`held?scope=owned`, row 206 decision 11) has no switch: it is a list of pending cases,
      and closed cases never appear in it.
17. **Sent by Me is unchanged.** A send overtaken by a closure is no longer the current leg, so it leaves the "still
    out" list and stays under Show Earlier, muted.
18. **Every case summary carries `closed`.**
    - `CaseSummaryOut` gains `closed: bool | null`. It is filled in one batched query in `inbox.summaries` over the cases
      on the page.
    - It is `null` for a case in `hidden` (the caller cannot open it), because Open / Closed is the department's own fact.
    - The Closed and Ready to Close badges are drawn on the four inbox tabs and on Search results. Other screens read the
      field and draw nothing new.

### C. The case page

19. **The header, the action rail and the dialog.**
    - **Header** (`CaseFrame.tsx`):
      - a closed case shows a neutral "Closed" badge after the court status, and a line "Closed on <date> by <name>,
        <designation>" with **"Read the Closing Remark"**, which opens the Notes tab at that note;
      - the link is drawn only when the API gives `closure.note_ref_no`, which it does only when the caller can read the
        note;
      - a reopened case whose current leg is still the `reopened` leg shows "Reopened on <date>: the court's status
        changed." The line goes once the case moves on.
    - **Your Task card** (`Rail.tsx`):
      - when `workflow.close` is true, a notice **"Ready to Close"** reads "The court has disposed of this case. Close it
        when the department's work on it is done." It has a primary **"Close Case"** button;
      - when the caller would be a closer but `workflow.close_blocked` is set, the notice explains why. `transfer_open`
        reads "A transfer of this case is waiting for a decision. Decide or withdraw it first." Nothing is shown for
        `not_disposed`;
      - for a closed case the card shows the closure line in place of the task. Send and Recall are absent, because the
        card says `can_send` and `can_recall` are false.
    - **The dialog** `components/workflow/CloseCaseDialog.tsx`, on the Action dialog template:
      - title "Close This Case";
      - body: "Closing ends this case's movement and clears its pending action. It leaves With Me and moves to Closed in
        My Cases and Department. A closed case cannot be reopened by hand: it opens again by itself if the court's
        status changes.";
      - when the caller has drafts on the case: "Your drafts on this case become permanent notes.";
      - field **"Why Is This Case Being Closed?"** (required, 3 to 2,000 characters, with a counter), hint "Saved as a
        note that everyone who can open this case can read. A note is never edited; a correction is a new note.";
      - buttons "Close Case" (primary) and "Cancel".
    - **After closing:**
      - with `visible: true`, the page reloads the case with the flash "Case closed. The closing remark is note <ref>.";
      - with `visible: false`, it goes to `/inbox/with-me` with "Case closed. You can no longer open it: it was with you
        only to work on.";
      - refusals show their plain words (decision 4).
    - The existing texts that list when drafts become permanent ("... when the case is sent on or recalled") add "or
      closed".
20. **The server says what the page may offer.**
    - `workflow_actions.available` gains:
      - `close: bool`: every write check of decision 4 passes for the caller, without locking or writing;
      - `close_as: "holder" | "head" | null`;
      - `close_blocked: "not_disposed" | "transfer_open" | null`, set only when the caller would be a closer as holder
        or head and holds `cases.close`, but condition 6 or 7 fails.
    - `GET /cases/{ref}` gains `closure`, the latest closure of the case (open or reopened) or null.
    - The custody card gains `closed: bool`. `can_send` and `can_recall` are false while the case is closed.
    - The custody reasons `closed` ("Closed") and `reopened` ("Reopened") join `/workflow/codes`, so the journey and the
      remarks page label the legs.

### D. Dashboard and reports

21. **Personal and department dashboards.**
    - **Personal** (`GET /dashboard/me`): a new attention kind, `ready_to_close`.
      - It lists disposed cases held by the caller, through a membership holding `cases.close`, visible and not merged.
      - Title "Ready to Close", detail "Disposed by the court on <date>", linking to the case page.
      - It comes after `due_soon` and before `file_received`, and leaves out cases already listed, as the other kinds
        do (portal-ui-polish, decision 13).
      - The five headline figures are unchanged.
    - **Department** (`GET /dashboard/department`):
      - `cases` gains `to_close` (primary-owned, disposed, open) and `closed` (primary-owned, closed);
      - `attention` gains `to_close`;
      - the Attention card shows "Ready to Close (n)", linking to `/inbox/department?department=<code>&case_status=disposed`
        (Open is the default);
      - the "Cases Claimed and Active" figure and its "n disposed" line are unchanged.
22. **State dashboard and the four reports are unchanged.**
    - They count the court's figures (pending cases, hearings and disposals) and the pending actions. Closing changes no
      court figure.
    - Pending actions already leave closed cases out (decision 14).
    - A State-wide count of closed cases is not asked for. A later row may add it.

### E. Wording, plan and earlier decisions

23. **New and changed user text.** All of it is Title Case under the existing helper, passes both wording guards
    (`lib/wording.test.ts`, `lib/labels.test.ts`) and the backend guard, uses no custody-sense "file", no "allot" and no
    eOffice words:
    - **Actions and titles:** "Close Case", "Close This Case", "Read the Closing Remark".
    - **Switch, badges and chip:** "Open", "Closed", "Ready to Close".
    - **Field:** "Why Is This Case Being Closed?".
    - **Lines:**
      - "Closed on <date> by <name>, <designation>";
      - "Reopened on <date>: the court's status changed.";
      - the rail notice, the dialog body and the hint of decision 19;
      - the two flashes of decision 19.
    - **Empty states:**
      - My Cases, Closed: "Closed cases you are connected to appear here.";
      - Department, Closed: "The department's closed cases appear here.".
    - **Refusals:**
      - `case_closed`: "This case is closed. It opens again only if the court's status changes.";
      - `not_disposed`: "The court has not disposed of this case, so it cannot be closed.";
      - `already_closed`: "This case is already closed.";
      - `not_closer`: "Only the officer the case is with or the Head of Department can close it.";
      - `transfer_open`: decision 19's text.
    - **Labels:**
      - function "Close Cases" and its description (decision 2);
      - note kind "Closing Remark";
      - custody reasons "Closed" and "Reopened";
      - timeline "Case Closed" and "Case Reopened";
      - dashboard "Ready to Close" and "Disposed by the court on <date>".
    - **Server alert text** (decision 11): "Case reopened: <case>" and its body.
24. **Earlier decisions this note changes, all for the owner's approval:**
    - case-inbox-simplify, decisions 4 and 9: My Cases and Department gain the Open / Closed switch that row 206
      reserved;
    - decision 5 of the same note is honoured: a disposed case stays in With Me until it is closed;
    - custody-workflow, decisions 2 and 27: two custody reasons are added;
    - custody-workflow, decision 19: the stage `closed` is retired (decision 13);
    - DB_STANDARD §6: owner closure is recorded outside `cases.closed_at` (decision 1, flagged).

    Recommend-and-claim, visibility, the notes rule, NAPIX and the Case Assistant are untouched.

## Data
Migration **0035** (`0035_close_case.py`, revises 0034). Built on **the next free number after the head at build time**
if another row merges a 0035 first. Applied migrations are never edited. `schema.md` takes the paragraphs below before
the migration is written.

**New table (schema.md, Phase 2 and 3 tables):**

> **`case_closures`** (transaction; design `close-case`, migration 0035).
>
> **Columns:**
> - id (uuid v7 PK);
> - case_id (→ cases RESTRICT, NOT NULL);
> - office_id (→ offices RESTRICT, NOT NULL: the owning department at closing);
> - ownership_id (→ case_ownership RESTRICT, NOT NULL: the active primary row at closing);
> - closed_as (varchar 10 NOT NULL: `holder` / `head`);
> - note_id (→ case_notes RESTRICT, NOT NULL, UNIQUE: the closing remark, kind `closing`);
> - close_leg_id (→ custody_history RESTRICT, NOT NULL, UNIQUE: the `closed` leg);
> - disposal_date (date NULL: the court's `cases.disposal_date` at closing, a snapshot);
> - closed_at (timestamptz NOT NULL default now());
> - reopened_at (timestamptz NULL);
> - reopen_leg_id (→ custody_history RESTRICT, NULL, UNIQUE: the `reopened` leg);
> - reopened_status (`case_status` NULL: the court status that reopened it, always `pending` as built);
> - actor snapshot (the closer, through the acting membership: `actor_user_id` → users SET NULL, `actor_name`,
>   `actor_designation`, `actor_office_code`);
> - created_at, updated_at.
>
> **Constraints and indexes:**
> - CHECK `ck_case_closures_closed_as` (`closed_as IN ('holder', 'head')`);
> - CHECK `ck_case_closures_reopened` (`(reopened_at IS NULL) = (reopen_leg_id IS NULL) AND (reopened_at IS NULL) =
>   (reopened_status IS NULL)`);
> - partial unique index `ix_case_closures_open` (case_id) WHERE `reopened_at IS NULL`: at most one open closure per
>   case;
> - index `ix_case_closures_case_closed` (case_id, closed_at DESC).
>
> **Triggers:**
> - `case_closures_reopen_once` (BEFORE UPDATE, function `aslms_case_closure_reopen_once`) refuses any change except
>   setting `reopened_at`, `reopen_leg_id` and `reopened_status` from NULL (once) and `updated_at`;
> - `set_updated_at`.
>
> **Writers and grants:** `COMMENT ON TABLE` `class=transaction`. In `MUTABLE_TABLES`; not in `APPEND_ONLY_TABLES` (one
> update, the reopening) nor in `CASCADE_TABLES`. Grants: `aslms_owner` ALL, `aslms_readonly` SELECT, `aslms_app` SELECT,
> INSERT, UPDATE (no DELETE: a closure is a legal record). Written only by `services/case_closure.py`: `close` inserts,
> `reopen_on_court_status` updates. A case is **Closed** while a row with `reopened_at IS NULL` exists; otherwise
> **Open**. No `created_by` / `updated_by`, because the actor snapshot is the audit column (DB_STANDARD §5), and the
> reopening is a system write. Never deleted.

**Changed rows of schema.md:**
- **`custody_history`.** `reason` gains `closed` (a Close Case leg: the owning department's office, no officer,
  `pending_action = none`, no due date, no remark) and `reopened` (the system's leg on reopening: the owning department's
  office, no officer, `pending_action = examine`, no due date, no remark). CHECK `ck_custody_history_reason` is dropped and
  added again with nine reasons. `ck_custody_history_remark` is unchanged: neither new reason carries a remark.
- **`custody`.** "Written only by `services/custody.py::move_custody`" gains `closed` and `reopened`. A closed case's row
  rests at the owning department's office. `held`, `summary_for` and every custody count leave closed cases out.
- **`case_notes`.** The kind `closing` (the closing remark, written only by Close Case, visibility `case_scope`, never
  selectable).
- **`cases`.** No change. `closed_at` stays the court disposal mark (set on disposal, cleared on restoration). The
  department's Open / Closed is in `case_closures` (decision 1).

**Reference rows** (hard-coded in the migration, `ON CONFLICT (code) DO NOTHING`, with no application import, as 0016,
0018, 0022 and 0034 do; the seed carries the same rows):

| Code set | Code | Row |
|---|---|---|
| `ref_event_type` | `case_closed` | label "Case closed", timeline label "Case closed", on the tracking card, sort 400 |
| `ref_event_type` | `case_reopened` | label "Case reopened", timeline label "Case reopened (court status changed)", on the tracking card, sort 410 |
| `ref_note_kind` | `closing` | label "Closing remark", sort after `hand_over` |
| `ref_case_stage` | `closed` | `is_active` set to false, only while it is true; the downgrade restores it under the mirror condition |

- No new `ref_alert_kind`: decision 11 reuses `status_changed`.
- The function `cases.close` needs no schema change, because `permission` is a varchar code. The seed (`init`, after
  `migrate`) inserts its `ref_permission` row and the missing `role_permissions` rows, enabled for `dept_head` and
  `dept_officer` only.
- Model changes: `Permission.CASES_CLOSE`, `EventType.CASE_CLOSED` and `CASE_REOPENED`, `NoteKind.CLOSING`, and
  `CUSTODY_REASONS` / `CUSTODY_REASON_LABELS` gaining `closed` ("Closed") and `reopened` ("Reopened").

**Downgrade.** It refuses (a restore is needed, runbook section 6) while any of these exist: a `case_closures` row, a
`custody_history` row with reason `closed` or `reopened`, or a `case_notes` row of kind `closing`. Otherwise it:
1. drops the table, its trigger and its function;
2. restores the seven-reason CHECK;
3. deletes the three reference rows if unused;
4. reactivates the stage.

The function rows stay, because the seed owns them.

## Services

**`backend/aslms/services/case_closure.py` (new).** The only writer of `case_closures`.
- `closed_condition(case_id_col) -> ColumnElement[bool]`: an `EXISTS` over `case_closures` with `reopened_at IS NULL`,
  correlated on the given column. It is read by `held`, `summary_for`, `my_cases`, `inbox` and `dashboard`.
- `open_closure(session, case) -> CaseClosure | None`.
- `closer_member(session, user, case, custody) -> tuple[Member, "holder" | "head"] | None`, decision 3:
  - first the holder membership (`custody.holder_member`), if it has `cases.close`;
  - else the caller's membership whose `membership_id` is `memberships.head_of(owner office).id`, if it has
    `cases.close`.
- `check_close(session, user, case) -> CloseCheck`: conditions 3 to 8 of decision 4 without locking or writing. It
  feeds `workflow_actions.available` (`close`, `close_as`, `close_blocked`).
- `close(session, actor, user, case, *, remark) -> CloseResult`:
  - checks in the order of decision 4, taking `lock_case` before condition 4;
  - `actor = access.actor_as(actor, member)`;
  - `before = custody.card_summary(row)`;
  - writes the `closed` leg (`move_custody`, office = the primary owner's office), the closing note
    (`notes.add_closing_note`), the closure row, the `case_closed` event and the `case.closed` audit row (decisions 5
    to 7);
  - returns the closure, the note, the drafts made permanent and the leg.
- `reopen_on_court_status(session, case) -> CaseClosure | None`, decisions 9 and 10:
  - nothing unless `case.status == pending` and an open closure exists (read `FOR UPDATE` after `lock_case`);
  - otherwise sets the reopening columns, writes the `reopened` leg with `Actor.system("court status")`, emits
    `case_reopened` and writes the `case.reopened` audit row;
  - if the case somehow has no active primary owner, the leg goes to `closure.office_id`;
  - idempotent: a second call finds no open closure.
- `refuse_if_closed(session, case, error)`: raises the caller module's conflict with code `case_closed`.
- `brief(session, user, closure) -> dict`: the `CaseClosureOut` shape. `note_ref_no` is given only when
  `visibility.can_view_note` passes for the caller.

**`services/notes.py`.**
- `SYSTEM_KINDS = frozenset({NoteKind.CLOSING})`. `check_kind` refuses it ("note kind closing cannot be chosen").
  `kinds()` lists it with `selectable: false`.
- New `add_closing_note(session, actor, member, case, custody, body) -> CaseNote`: `_insert_note` with kind `closing`,
  visibility `case_scope`, no files and no links.
- Corrections are unchanged.

**`services/custody.py`.**
- `send` and `recall` call `case_closure.refuse_if_closed` right after `require_owned` (409 `case_closed`).
- `held` adds `~case_closure.closed_condition(HELD.case_id)` for every scope. `summary_for` adds it on `Custody.case_id`.
- `card` returns `closed` and forces `can_send` and `can_recall` to false while closed.
- `move_custody` is unchanged: the new reasons come from `CUSTODY_REASONS`.

**`services/ownership.py`.** `_check_allot`, `_check_take_over` and `_check_request_transfer` refuse a closed case
(`OwnershipError`, code `case_closed`), so `available_actions` reads false and the writes refuse. `_check_decide_transfer`
needs no rule: no transfer can be open on a closed case (condition 7, and requests are refused).

**`services/cases.py`.** In `apply_dossier`, after the record is applied and before the status events:
`reopened = case_closure.reopen_on_court_status(session, case)`. The restoration `status_changed` payload gains
`reopened: true` when `reopened` is not None. `apply_core_fields` is unchanged and stays the only writer of `status`.

**`services/tracking.py`.** In `record_status_change`, when `status` changed and the case is now `pending`, it calls
`reopen_on_court_status` before emitting, and adds `reopened: true` to the payload when it reopened.

**`services/causelists.py`.** For an entry matched to an existing case with an open closure, it calls `queue.enqueue(
FetchKind.DOSSIER, cnr or court ref, origin.dossier_priority(), lane=origin.lane, ...)` once (decision 12).

**`services/alerts.py` / `alert_rules.py`.**
- `EventType.CASE_REOPENED` joins the scanned types. Its handler raises the `status_changed` alert of decision 11
  through `raise_alert` with `case_recipients()`.
- The `status_changed` handler skips a payload with `reopened: true` (counter `skipped_reopened`).
- `alert_rules.text` gives the reopened title and body when `data.reopened`.
- `case_closed` raises nothing: the closing note's `new_note` alert covers it.

**`services/my_cases.py`.**
- `mine` and `mine_stmt` take `closure: "open" | "closed" | "all" = "all"`, through `closed_condition(Case.id)` or its
  negation; any other value is 400.
- With `closed`, the order is the open closure's `closed_at` descending, then case number and id. Otherwise the order
  is unchanged.
- `mine_counts` adds `all_open` and `all_closed` (the `all` view split).

**`services/inbox.py`.**
- `claimed_stmt` and `claimed` take `closure` the same way.
- `claimed_order` puts `closed_at` descending first when `closure=closed`.
- `_counts_for` adds `claimed_open` and `claimed_closed` (primary and watcher rows, any status, so `claimed_open +
  claimed_closed = claimed_active + claimed_disposed`).
- `summaries` fills `closed`, `null` for hidden cases.

**`services/workflow_actions.py`.** `available` adds `close`, `close_as` and `close_blocked` from
`case_closure.check_close`.

**`services/case_detail.py`.**
- The overview adds `closure` (`case_closure.brief` of the latest closure, or null).
- `OWNERSHIP_EVENTS` gains `CASE_CLOSED` and `CASE_REOPENED`.

**`services/dashboard.py`.**
- `personal_headline` adds the `ready_to_close` attention rows (decision 21). The cases held by the caller, `Case.status
  = disposed`, `held.holder_membership_id` in the caller's memberships that hold `cases.close`, limited by the room
  left, excluding listed cases.
- `department_block` adds `cases.to_close`, `cases.closed` and `attention.to_close`.

**`services/access_seed.py`.**
- `PERMISSION_LABELS[P.CASES_CLOSE]`.
- `PERMISSION_GROUPS` "case_work" gains it after `CUSTODY_TRACK`.
- `DEFAULT_MATRIX` adds it to `DEPT_HEAD` and `DEPT_OFFICER` only.

**`services/seed.py`.**
- The `ref_event_type`, `ref_note_kind` and `ref_case_stage` rows of "Data", with `NOTE_KIND_LABELS[CLOSING] = "Closing
  remark"`.
- `TRACKING_CARD_EVENTS` gains both events.
- The `closed` stage is seeded inactive and switched off on an existing database while still active.

No other service writes `case_closures`. Reading paths write nothing.

## API

| Method and path | Permission | Change |
|---|---|---|
| `POST /cases/{ref}/close` (new, `routers/workflow.py`) | `cases.close` (route); the service checks holder or head in the acting membership (decision 3) | Body `CaseCloseIn {remark: str (3–2,000)}`. 201 `CaseCloseOut {closure: CaseClosureOut, note_ref_no: str, finalised_notes: [str], card: CustodyCardOut \| null, visible: bool}`. Errors: 404 not visible; 400 `bad_field`; 403 `function_missing`, `not_closer`; 409 `not_owned`, `already_closed`, `not_disposed`, `transfer_open`, `concurrent_change`. |
| `GET /cases/{ref}` | `cases.view_scope` or `cases.view_all` (unchanged) | Adds `closure: CaseClosureOut \| null`. `workflow` adds `close`, `close_as` and `close_blocked`. `custody` (the card) adds `closed`. |
| `GET /cases/{ref}/custody` | unchanged | The card adds `closed`. The legs may carry the reasons `closed` and `reopened`. |
| `GET /workflow/codes` | unchanged | `note_kinds` lists `closing` (`selectable: false`). `custody_reasons` adds `closed` and `reopened`. `stages` no longer lists `closed`. |
| `POST /cases/{ref}/custody/send`, `/custody/recall` | unchanged | 409 `case_closed` on a closed case. |
| `POST` assign, take over and request transfer (`routers/ownership.py`) | unchanged | 409 `case_closed` on a closed case. |
| `GET /inbox/mine` | `cases.view_scope` (unchanged) | New `closure=open\|closed\|all` (default `all`, so other callers are unchanged). With `closed`, the newest closure comes first. |
| `GET /inbox/mine/counts` | `cases.view_scope` | Adds `all_open` and `all_closed`. |
| `GET /inbox/claimed` | unchanged | New `closure=open\|closed\|all` (default `all`). With `closed`, the newest closure comes first. |
| `GET /inbox/counts` | `cases.view_scope` | Each department block adds `claimed_open` and `claimed_closed`. |
| `GET /custody/held` (`me`, `office`, `owned`), `GET /custody/summary` | unchanged | Closed cases are left out. No new parameter. |
| Every list returning `CaseSummaryOut` | unchanged | Adds `closed: bool \| null` (null when the caller cannot open the case). |
| `GET /dashboard/me` | unchanged | Attention kind `ready_to_close`. |
| `GET /dashboard/department` | unchanged | `cases.to_close`, `cases.closed`, `attention.to_close`. |

- `CaseClosureOut`: `{closed_at, closed_as, closed_by: {name, designation, office_code}, office_code, note_ref_no: str |
  null, disposal_date, reopened_at, reopened_status}`.
- Visibility: every path above applies the existing server-side case visibility. `note_ref_no` follows the note rule.
  `closed` is withheld for hidden cases.
- `frontend/openapi.json` and the generated client are regenerated by the developer in the build.

## Jobs
- No new job and no new schedule.
- The cause-list apply queues a `dossier` fetch for a closed case it finds listed (decision 12): kind `dossier`, the
  case's CNR (or the court reference for a provisional case), the origin's lane and dossier priority, deduplicated by
  the queue.
- Reopening runs inside whichever job applies the court's answer: the dossier fetch, the status batch, the monthly
  disposed refresh or a court search.
- The 5-minute alert scan picks up `case_reopened`.

## Tests

**Backend, database** (`backend/tests/db/`, the scripted fixtures of `tests/db/conftest.py`; no NAPIX call, and
`NAPIX_ENABLED` is never set):
- `test_case_close.py` (new):
  - `test_holder_closes_disposed_claimed_case`: one closure row, a `closed` leg to the owner's office with no officer,
    pending `none` and no due date; one `closing` note with visibility `case_scope` and `custody_leg_id` set to the leg;
    one `case_closed` event without the remark; one `case.closed` audit row with the remark's digest and no text.
  - `test_head_closes_wherever_the_case_is`: the head closes a case held by an officer of the department, one held by a
    unit with no officer, and one held by an officer of another department. `closed_as == "head"`.
  - `test_outside_holder_may_close_and_loses_sight`: an officer of another department holding the case closes it.
    `visible` is false and the case is no longer visible to them.
  - `test_refusals_in_order`: unclaimed → `not_owned`; pending or unknown → `not_disposed`; already closed →
    `already_closed`; open transfer → `transfer_open`; a department officer who does not hold the case, the department
    administrator, the super admin and a State-wide reader → `not_closer`; no function → `function_missing`; a short
    remark → 400. Nothing is written by any refusal.
  - `test_holder_without_function_refused`: the holder whose membership lacks `cases.close` gets `not_closer`, even
    when another of their memberships holds it.
  - `test_drafts_finalised_before_closing_note`: the holder's two drafts become notes with lower `seq_no` than the
    closing note, and the drafts are gone.
  - `test_closing_note_kind_not_selectable`: Add Note with kind `closing` is 400. `/workflow/codes` lists it as not
    selectable.
  - `test_closing_note_correction`: the author's correction supersedes it, keeps the kind and visibility, and
    `case_closures.note_id` is unchanged.
  - `test_closed_case_does_not_move`: send, recall, assign, take over and request transfer are 409 `case_closed`.
    `available_actions` and the card read false. Add note (permanent), upload and set stage still work.
  - `test_one_open_closure_per_case`: a second insert while open fails on `ix_case_closures_open`.
  - `test_closure_row_update_guard`: an UPDATE of `note_id`, `closed_at` or a second change of `reopened_at` is refused
    by the trigger. `aslms_app` cannot DELETE.
- `test_case_reopen.py` (new):
  - `test_dossier_restoration_reopens`: `apply_dossier` with a sample record showing `pend_disp = P` on a closed case
    sets `reopened_at` and `reopened_status = pending`, writes a `reopened` leg to the owner office with `examine`, one
    `case_reopened` event and one `case.reopened` audit row with a system actor, and the restoration `status_changed`
    payload carries `reopened: true`.
  - `test_status_batch_reopens`: `apply_status` plus `record_status_change` to `pending` reopens the same way.
  - `test_unknown_does_not_reopen`: an unreadable `pend_disp` leaves the closure open. A later `P` reopens it.
  - `test_reopen_idempotent`: applying the same record twice writes one leg, one event and one audit row.
  - `test_close_again_after_reopen`: a second disposal and closing make a second row; the history keeps both.
  - `test_reopen_alert_once`: the alert scan over the events of one restoration raises one `status_changed` alert with
    `data.reopened`, to the department office's `cases.allot` holders and the assigned officer. The `status_changed`
    event with `reopened` is counted `skipped_reopened`. A restoration of an open case still raises its usual alert.
  - `test_closed_case_listed_queues_refresh`: a cause-list apply with an entry for a closed case queues one `dossier`
    fetch; a second apply queues none while it waits; an open case queues nothing new.
- `test_custody_held.py`, `test_custody_sent_still_out.py`, `test_dashboard*.py` additions:
  - `test_closed_leaves_held_every_scope`: a closed case is absent from `scope=me`, `office` (for the head) and `owned`,
    and from `summary_for` totals and by-holder figures.
  - `test_files_count_excludes_closed`: `mine_counts()["files"]` equals `held(scope="me").total` equals the headline
    "Cases with Me", before and after a closing.
  - `test_send_overtaken_by_closure_not_still_out`.
  - `test_ready_to_close_attention`: a disposed case held by me through a membership with `cases.close` is listed once as
    `ready_to_close`. Without the function, nothing is listed. A closed case is not listed.
  - `test_department_block_to_close_and_closed`.
- `test_my_cases.py` and `test_inbox_claimed.py` additions:
  - `test_closure_filter_open_closed_all`: the three values give complementary sets. `all` equals the list without
    the parameter. A bad value is 400.
  - `test_closed_order_newest_first`.
  - `test_counts_split`: `all_open + all_closed == all`, and `claimed_open + claimed_closed == claimed_active +
    claimed_disposed`.
  - `test_summary_closed_null_when_hidden`.
- `test_workflow_actions.py` addition: `close`, `close_as` and `close_blocked` agree with what `close` would do, for the
  holder, the head, an officer who does not hold the case, a pending case (`close_blocked == "not_disposed"` for a
  would-be closer) and an open transfer.
- `test_stages.py` addition: the stage `closed` cannot be set. Past `closed` rows still read their label.
- `test_migration_0035.py` (new):
  - upgrade from 0034 creates the table, constraints, indexes, triggers, grants and comment;
  - the reason CHECK accepts `closed` and `reopened`;
  - the reference rows are present and the stage is inactive;
  - the downgrade refuses with a closure present and succeeds on an empty one, restoring the stage and the CHECK.
- `test_app_role.py`, `tests/unit/test_schema_metadata.py`: `case_closures` is a transaction table, in
  `MUTABLE_TABLES`, with RESTRICT foreign keys and no DELETE for `aslms_app`.
- `tests/unit/test_permission_groups.py`: `cases.close` is in exactly one group. The matrix gives it to `dept_head` and
  `dept_officer` only. The label and description are within the length rules.
- `tests/unit/test_wording_guard.py`: the reopened alert text and the refusal messages pass.
- The existing suites stay green: visibility, row 206's counts and orders, custody, notes, alerts and the dashboard.
  `ruff check` and `pytest -q` pass.

**Frontend** (vitest):
- `components/workflow/workflow.test.tsx`, for `CloseCaseDialog`:
  - the remark is required and counted;
  - the drafts line appears only with drafts;
  - submit posts `/cases/{ref}/close`;
  - `visible: false` routes to `/inbox/with-me` with its flash;
  - each refusal code shows its text.
- `components/case/rail.test.tsx` and `case.test.tsx`:
  - the Ready to Close notice and button only with `workflow.close`;
  - the `transfer_open` explanation;
  - a closed case shows the header badge, the closure line and the remark link only with `note_ref_no`, and no Send or
    Recall;
  - the reopened line only while the current leg is `reopened`;
  - the journey labels Closed and Reopened.
- `components/inbox/inbox.test.tsx`:
  - My Cases and Department draw the Open / Closed switch;
  - Open sends `closure=open`, Closed sends `closure=closed` and is kept by Clear All;
  - m comes from `all_open` / `all_closed` and `claimed_open` / `claimed_closed`;
  - Department under Closed hides the Overdue and With Another Office chips and drops their keys;
  - the tracker fallback has no switch;
  - disposed open rows show Ready to Close and closed rows show Closed.
- `components/files/cases-list.test.tsx`: With Me's Ready to Close chip sets `case_status=disposed`; the badge shows on
  disposed rows.
- `components/dashboard/dashboard.test.tsx`:
  - the `ready_to_close` attention item and its link;
  - the department "Ready to Close (n)" line linking to `/inbox/department?department=<code>&case_status=disposed`.
- `lib/filters.test.ts`: `closure` is a fixed key of `mine` and `department`.
- `lib/wording.test.ts` and `lib/labels.test.ts` stay green with every new string.
- `npm run typecheck`, `npm run lint` and `npm test` pass.

**uicheck** (`frontend/e2e`), at 375, 768 and 1280 px:
- **States:**
  - `/cases/<sample> (Ready to Close)`: the rail notice;
  - `/cases/<sample> (Close dialog open)`;
  - `/cases/<sample> (closed)`;
  - `/inbox/my-cases?closure=closed`;
  - `/inbox/department?closure=closed`;
  - `/inbox/with-me (Ready to Close chip)`.
- **Fixtures:**
  - the case detail fixture gains `closure` and the `workflow.close*` flags;
  - the `/inbox/mine` and `/inbox/claimed` matchers read `closure`;
  - the counts fixtures gain the split figures.
- The generic checks, including `menu-clipped`, pass.

## Verification
1. **Static checks:** `ruff check`, `pytest -q`, and in `frontend/` `npm run typecheck`, `npm run lint` and `npm test`,
   all green.
2. **Migration:** `alembic heads` shows 0035 (or the build's number) as the one head. The `migrate` step applies it,
   then `init` (seed) adds the function, the reference rows and the two `role_permissions` rows. In `role_permissions`,
   `cases.close` is enabled for `dept_head` and `dept_officer` and disabled for the other eight types. The stage
   `closed` is inactive.
3. **API checks on the dev proxy.** Use a department officer holding a claimed, court-disposed case; the head of that
   department; and a second disposed case resting with a unit with no officer.
   - `GET /cases/{ref}` for the officer: `workflow.close = true`, `close_as = "holder"`. For a pending case:
     `close = false`, `close_blocked = "not_disposed"`.
   - `POST /cases/{ref}/close` with a remark returns 201, `visible: true`, a `note_ref_no`, and a card with no holder
     officer and `closed: true`.
   - `GET /cases/{ref}/notes` shows the closing note to the officer, the head and an Auditor. The audit search (`GET
     /audit?action=case.closed`) has one row with the digest and no text.
   - The With Me count (`/inbox/mine/counts.files`) drops by one and equals the dashboard's "Cases with Me".
     `all_open + all_closed = all`.
   - `GET /inbox/claimed?office=<dept>&case_state=all&closure=closed` lists the case first. `claimed_open +
     claimed_closed = claimed_active + claimed_disposed` in `/inbox/counts`.
   - `POST .../custody/send` on it returns 409 `case_closed`.
   - The head closes the unit-held case: 201, `closed_as = "head"`.
   - Repeating either close returns 409 `already_closed`.
4. **Reopen** is proven by the database tests (decision 9). It cannot be shown live without the court restoring a case,
   and `NAPIX_ENABLED` is never turned on for it.
5. **Browser checks** at http://localhost:3000 by the owner and the tester, at 1280, 768 and 375 px:
   - the officer sees Ready to Close on the case page and in With Me, closes with a remark, and sees the flash, the
     header badge and line, and the note in the Notes tab;
   - the case is gone from With Me and appears under Closed in My Cases and Department, newest first;
   - Send and Recall are gone; Add Note and Upload remain;
   - the head's dashboard shows "Ready to Close (n)" and the link opens Department filtered to disposed open cases;
   - the Close Case function appears under Case Work on the user-type pages.
6. **uicheck** runs on a private network against temporary images (runbook section 16, never on the shared stack) and
   exits 0 with `findings.json` empty. The run directory is recorded in the cycle report.
7. **Scribe** records the change in:
   - `docs/schema/schema.md` (the paragraphs of "Data", first);
   - `docs/claude_ASLMS_design_decisions.md`: the rule, decisions 1, 3, 9 to 13, and the DB_STANDARD §6 note;
   - `docs/ASLMS_Process_Workflows.md`: the closing and reopening steps and the Open / Closed switch;
   - CLAUDE.md's current focus, with "after row 207 merges: apply 0035 with the `migrate` step, then `init` (seed);
     `docker compose build`".

## Open questions
None. The owner gave the rules on 29 Oct 2026. Where they were silent, this note takes the narrowest choice and names it
for approval: decisions 3, 4 (condition 7), 8, 9, 10, 12 and 13.
