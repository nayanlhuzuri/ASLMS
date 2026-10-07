# Design: Custody and workflow — sending the file and recall, case stages, the notes trail with drafts, attachments and per-note visibility

```
slug: custody-workflow
status: approved
author: architect
date: 2026-10-07
approved_by: product owner (nayan.semt@gmail.com) on 2026-10-07
```

## Context
Plan §5.7 (Custody and Workflow): "Shows, for every case, which office and officer currently hold it and what
action is pending, similar to file movement in eOffice"; custody card (holder office and officer, pending action,
since when, due date); "Requests between offices … with stages and due dates"; "Hand-over of a case to another
office, recorded with a note"; portal database only; links to notes trail, alerts, dashboard, reports (pending
actions by office). Plan §5.8 (Case Notes Trail): a noting history that belongs to the case and follows it across
every custody move; note kinds "general, instruction, opinion, hearing note, compliance, decision, hand-over";
author's name, designation and office at the time; no edits or deletes, corrections are new notes linked to the
original; attachments; visibility per note. Plan §5.13: notes, custody moves and uploads are audited. Plan §3.2 /
§5.9: notes and internal documents are never sent to SourceTrace. Backlog row 6.

**Binding: the owner's rules of 7 Oct 2026** (decisions log, "Custody and file movement — owner's rules"):
custody is accountability; sending the file replaces requests; chain as in eOffice; recall by the owning
department at any time; ownership never moves with custody; no deletion once claimed except draft notes, which
become permanent when the case is sent on or recalled; one person, several departments (memberships). They
replace the request-based design.

**Deviation from the plan, set by the owner (flagged):** plan §5.7 "Requests between offices" and the data group
"Custody records, requests between offices, and their stages" are replaced by sending the file (decision 3);
there is no request object. Plan §5.8 "notes cannot be edited or deleted" gains the owner's draft exception
(decision 12).

**What changed from the approved version of 7 Oct (this revision):**
- Requests, request messages, request attachments, `with_custody`, assign, answer, withdraw and the request
  visibility rule are **removed**; the `requests` and `request_messages` tables (migration 0001, empty) are
  dropped by a new migration and `request_attachments` is never created (decision 27).
- **Send** (to any registered officer, by membership, in any department) and **recall** (by the owning
  department) replace hand-over, requests and "pending action without a move" (decisions 3–7).
- The holder is a **membership** (office + officer + designation) — depends on `user-memberships` (row 28).
- **Draft notes** of the current holder, made permanent in the move's transaction (decisions 12–13).
- Alerts: `workflow` kind now covers file received, file recalled and due / overdue; `request_due` retired
  (decision 23).
- (owner review 2026-10-07, from `user-memberships` decisions 21–22) When an officer leaves a department, the
  department admin assigns each file they hold to an officer of the department, one by one (no successor;
  the exit is refused until every file and allotment has a target), and each file gets a leg of the new reason
  **`reassigned_on_exit`** to its own target, with the pending action and due date carried over unless the admin
  changes them; `move_custody` finalises the leaver's drafts as for any holder change (decision 13). Files can
  also be moved before the exit with the ordinary recall and send.
- Migration renumbered **0009_workflow** (0008 is `user-memberships`); the feature branch's `0008_workflow` was
  never applied to `main` and is not used.
- Kept, adapted: stages, note kinds, corrections, note visibility, attachments with type check and ClamAV,
  audit without note text, timeline, case row locks.
- The reviewer's blocking finding is answered in decision 8.

Earlier decisions that still apply: 25 Sep "CASE NOTES / NOTING TRAIL" (append-only, author snapshot, per-case
`seq_no`, custody leg recorded, `supersedes`, attachments as `documents` through `case_note_attachments`, three
visibility values, event and audit row per note); 26 Sep "Stages" (17 stages, any may be set, gaps shown) and
"Notes" (attachments are internal documents, excluded from SourceTrace); recommend-and-claim decision 11 (custody
follows primary ownership moves; no return to the pool); cases-api (one visibility rule, 404 for an invisible
case, custody card in the overview, decision 15); documents-uploads (type by content, ClamAV, 20 MB,
`record_visibility_condition`, `works_on_case`, `ck_documents_internal_not_sent`); alerts-notifications decision
14 (recipients: custody holder, owner, watchers).

What is in place on `main`: tables of migration 0001 — `custody` (1:1), `custody_history` (append-only),
`requests` / `request_messages` (empty, nothing writes them), `case_stages` (append-only), `case_notes`
(append-only, `ref_no`, `seq_no`, `visibility`, `custody_leg_id`, `supersedes_id`, `source`),
`case_note_attachments`; native enum `pending_action` (`none`, `examine`, `reply`, `file`, `comply`, `review`);
`ref_case_stage`, `ref_request_kind`, `ref_note_kind`; functions `custody.move`, `requests.send`,
`requests.answer`, `stages.set`, `notes.add`, `notes.view_counsel_shared`, `notes.view_private_office`;
`services/custody.py::move_custody` (ownership reasons only); `visibility.py` with `custody` and `request` bases;
`alerts.py` sweeping open requests for `request_due` (never fires: no requests exist). The unmerged
`feature/custody-workflow` branch is left as it is; the developer may read and reuse its notes, stages,
attachments and documents-split code where this note keeps the same rule, and discards its requests code and its
`0008_workflow`.

Not covered: portal screens (`portal-workflow`); dashboards and the "pending actions by office" report
(`reports-dashboards`, reading the columns and the `held` query of this item); the Case Assistant's "copy an
answer into a note" (`assistant`, through this item's note service); SMS.

## Decisions
1. **Custody exists only for a claimed case.** Every write of this item (send, recall, stage, note, draft)
   requires an active primary owner; otherwise 409 `not_owned`. Alternative: notes on pool cases — rejected: the
   pool has no custody to attach a leg to.

2. **Custody is accountability: the holder is a membership.** `custody` and every `custody_history` leg name the
   holder office, the holder user and the **holder membership** (the officer's office, designation and type —
   `user-memberships`), with a designation snapshot on the leg. Legs written by ownership moves may name an
   office only (`claimed`, `transferred` → the department; `allotted` to a unit → the unit), as built. Pending
   action, since and due date always describe the current holder, so pending work is measured against that
   officer and office (owner's rule 1).

3. **Sending the file replaces requests and hand-over (deviation, owner's rule).** The sender picks a department
   (any active Department-tier office, the Advocate General's office included), then an officer: an **active
   membership** of an active login at an active office in that department's subtree. Excluded targets: the
   State-wide types (`super_admin`, `state_oversight`, `central_operator`, `auditor` — they hold no department
   work) and the current holder membership (409 `unchanged`). The send carries a **remark** (required, 3–2,000
   characters), a **pending action** (required, not `none`; decision 10) and an optional **due date** (today IST
   to 365 days ahead). It writes one leg, reason `sent`, holder = the target membership. Sending never changes
   ownership or allotment. Alternative: keep requests beside sending — rejected by the owner ("no separate
   request object"). Standing counsel memberships are valid targets (the owner said "any registered user");
   **owner check**.

4. **Who may send.** (a) The holder: the caller whose membership is the holder membership. Holding the case is
   the authority; no function is required, because any registered officer can receive the file and must be able
   to pass it on (a referral reviewer has no `custody.move`). (b) When the leg names an office and no user (after
   claim, allot to a unit, transfer): a holder of `custody.move` who controls the office — a user whose
   membership is at that office when the office is not Department-tier, or a whole-department membership
   (`cases.claim` or `cases.allot`) of the department containing it (the built rule of alerts decision 14). Anyone
   else → 403 `not_in_control`. Alternative: any `custody.move` holder working on the case — rejected: an officer
   could pull a file another officer is accountable for.

5. **Chain, as in eOffice.** Whoever holds the case sends it on to anyone (decision 3); there is no "return
   path", no nesting and no open obligation outside the custody row. Every movement is a leg (from = the previous
   leg, to = the new holder membership, remark, pending action, due date, sender's actor snapshot). The holder
   cannot change their own pending action or due date: a new due date is a new send (by the holder onwards) or a
   recall and resend (by the owning department). Alternative: keep "set pending action without a move" —
   rejected: the holder could extend the due date they are measured against.

6. **Recall is a function the department admin grants (owner review 2026-10-07).** A new function
   **`custody.recall`** (module `custody`). In the default type matrix it is enabled for **`dept_admin`** only
   (and the super admin, who holds every function); it is off for every other type. A department admin gives it
   to the officers they choose with the existing per-user grant (`PUT /admin/users/{id}/permissions/custody.recall`,
   per membership under user-memberships decision 9), within their own department only — the delegation rule
   already limits grants to the admin's subtree and to functions the admin holds. The super admin can grant or
   deny it to anybody, in any department. A membership holding `custody.recall` **in the owning department**
   may call the case back at any time, from wherever it is, with a remark (required, 3–2,000). Holding it in
   another department gives no recall over this case. The leg, reason `recalled`, makes the recalling
   membership the holder, pending action `examine`, no due date; the recaller then sends it on as needed. 409
   `unchanged` when the recaller already holds it; 403 `not_owner_department` / `function_missing` otherwise.
   Every grant, deny and recall is audited. Alternative: recall to the department office with no officer —
   rejected: nobody would be accountable for the file just recalled.

7. **Ownership never moves with custody; ownership moves still move custody.** Send and recall never touch
   `case_ownership`. Claim, allot, take over and transfer (recommend-and-claim, built) keep writing their custody
   legs; when such a leg takes the file from a personal holder it acts as a recall (the holder's drafts are made
   permanent, decision 13; the previous holder is alerted, decision 23). Alternative: ownership moves leave
   custody alone — rejected: it would contradict recommend-and-claim decision 11, built and tested.

8. **The reviewer's blocking finding cannot recur.** The finding: "An answer or withdrawal only returns custody
   when `custody.request_id` is that exact request; if the file is out on a sub-request sent by the receiving
   side, nothing moves, and the receiving department can keep the case indefinitely without ownership or a
   request." It arose because custody could only come back through the request that took it. In this design
   custody is one pointer moved only by explicit legs; there are no requests, so nothing waits on a particular
   request and no leg depends on another; the owning department's recall (decision 6) moves the file from any
   holder, at any depth of the chain, in one step; and an ownership move does the same. A department other than
   the owner holds the file only while an accountable officer of it is the named holder, visible on the card and
   in the owner's `held?scope=owned` list with its due date (decision 24). Test
   `test_recall_from_any_depth` proves it.

9. **The holder's working access (any department), while holding.** The holder membership gets the `custody`
   visibility basis (personal: the holder user; office-wide for callers whose subtree contains the holder office,
   as built), which is a working basis, so it may: read the case and its records under the record rules; write
   notes (as drafts, decision 12) with `notes.add`; upload documents with `documents.upload`; set the case stage
   with `stages.set` (justified: the officer doing the work records `parawise_comments_received` or
   `affidavit_vetted`; the stage row records the setter's office; no ownership effect); send the file on
   (decision 4). Functions still come from the holding membership's type and overrides, so the super admin's
   matrix stays meaningful. The holder may not claim, dismiss, allot, take over, transfer, stop watching or
   recall (all need a membership in the owning department). When the file leaves, the previous holder loses the
   custody basis (other bases, such as ownership, stay); their permanent notes and uploads remain on the case.
   They keep a "sent" list of the legs they wrote (decision 24). Alternative: previous holders keep read access —
   rejected: sight follows the current hold and ownership (least privilege); **owner check**.

10. **Pending actions.** The native enum `pending_action` gains `parawise_comments` ("Parawise comments"),
    `report` ("Report"), `documents` ("Furnish documents"), `opinion` ("Opinion"), `instructions` ("Instructions
    to counsel"), `clarification` ("Clarification"), `other` ("Other — see remark") beside `examine`, `reply`,
    `file` ("File in court"), `comply` ("Comply"), `review` ("Review"), `none` (ownership legs only). Labels come
    from `domain/workflow.py::PENDING_ACTION_LABELS` through `GET /workflow/codes`. Alternative: a `ref_*` table —
    rejected: converting the column of the append-only `custody_history` for a set the design fixes is not worth
    it; the former request kinds are absorbed here.

11. **Remark visibility.** A leg's remark is shown to callers with a working basis on the case and to State-wide
    readers; everyone else who sees the case (recommended, pool) sees the leg without the remark. Events and audit
    never carry the remark text (decision 21).

12. **Draft notes (owner's exception to "no deletion").** A note written by the **current holder** (the caller's
    membership is the holder membership) is a **draft**: stored in `case_note_drafts`, visible only to its author
    (no other reader, State-wide readers included), editable (kind, body, visibility, supersedes, linked
    documents) and deletable by its author while that membership still holds the case. A draft has no `ref_no`
    and no `seq_no` (both are allocated once, at finalisation, and never change). Up to 20 drafts per holder per
    case (`NOTE_DRAFTS_MAX`). A draft carries **links** to documents already on the case (visible to the author,
    not archived), not new files: a new file is uploaded to the case first (`POST /cases/{ref}/documents`,
    permanent, scanned, its own visibility) and then linked, so deleting a draft never deletes a document. When
    custody is office-held with no user, nobody holds personally and notes are permanent at once (decision 14).
    Alternative: drafts as `case_notes` rows with a status — rejected: `case_notes` is append-only by trigger
    and must stay so. Alternative: files on drafts — rejected: deleting the draft would orphan or delete files.
    **Owner check:** the holder cannot "make permanent now"; drafts become permanent only when the file moves.

13. **Drafts become permanent in the move's transaction.** `move_custody`, whenever the new leg's holder
    membership differs from the previous one (send, recall, allot, take over, transfer, and the exit step's
    `reassigned_on_exit` — owner review 2026-10-07, `user-memberships` decision 21), calls
    `notes.finalise_drafts` under the same case row lock and in the same transaction: each draft of the previous
    holder membership on the case, oldest first, becomes a `case_notes` row (next `seq_no`, `ref_no` on the
    membership's office, `custody_leg_id` = the leg during which it was written, `drafted_at` = the draft's
    creation time, the author snapshot of the draft's membership, `source = user`), its links become
    `case_note_attachments` rows, and the draft and link rows are deleted. A draft correcting a note that was
    corrected meanwhile supersedes the latest note of that chain (recorded in the audit `after`). One
    `note_added` event and one `note.finalised` audit row per note. If anything fails, the move fails too; a
    file never moves leaving drafts behind. A deactivated holder's drafts wait for the recall; an ended membership's drafts are finalised by the exit
    step's leg (owner review 2026-10-07).

14. **Notes by others are permanent at once.** A caller who is not the personal holder (the owning department's
    nodal officers, the allotted officer while the file is elsewhere, standing counsel, anyone writing on an
    office-held leg) writes a permanent note: `notes.add` in the acting membership (`user-memberships` decision
    6) and a working basis (`owner`, `allotted`, `custody`, `counsel`). Body 1–20,000 characters
    (`NOTE_MAX_CHARS`); visibility required (`case_scope`, `counsel_shared`, `private_to_office`); `office_id`,
    `author_role`, actor snapshot from the acting membership; `seq_no` max + 1 under the case row lock;
    `custody_leg_id` = `custody.current_leg_id`; `ref_no` `ASLMS/<author office>/NOTE/<yyyy>/<n>`. The response
    says `draft: false`; a holder's write returns the draft with `draft: true`.

15. **Note kinds (deviation, small).** The plan lists seven: general, instruction, opinion, hearing note,
    compliance, decision, hand-over. `opinion` and `hand_over` are added (seed), both selectable (hand-over is
    now an ordinary note kind: the send's remark is on the leg). `hearing` is labelled "Hearing note".
    `correction` is retired (`is_active = false`): a correction carries the original's kind (decision 16).
    **Deviation, flagged:** the built extras `counsel_advice` and `file_noting` stay selectable.

16. **Corrections.** `supersedes` names a permanent note of the same case that the caller can see and that is not
    already superseded (409 `already_superseded`; partial unique index). Only the original author or a
    whole-department membership of the original note's department may correct (403 `not_author`). The correction
    keeps the original's kind and visibility (400 on a different visibility). A correction written by the holder
    is a draft like any other (decision 13 resolves a meanwhile-corrected target). Both notes are listed; the
    original shows `superseded_by`.

17. **Note visibility (`note_visible_condition`, SQL, over `case_notes`).** A visible case and
    `record_visibility_condition` (OR-ed over the caller's memberships, `user-memberships` decision 7), with the
    two note functions as switches: `private_to_office` needs `notes.view_private_office` (except the author and
    State-wide readers); for standing counsel `counsel_shared` needs `notes.view_counsel_shared`. Drafts are never
    in this rule; they are read only by their author through the drafts endpoints.

18. **Attachments on permanent notes.** As approved before: up to `ATTACHMENTS_MAX_FILES` (5) new files per
    call, each within `UPLOAD_MAX_BYTES`, type by content and ClamAV scan as uploads, all checked before anything
    is written (one refused file refuses the call; its rejection audit row is committed); they become `documents`
    of kind `attachment`, group `internal` (never sent to SourceTrace, `ck_documents_internal_not_sent`), default
    `doc_type` `correspondence`, visibility = the note's; existing case documents may be linked
    (`document_refs`), keeping their own visibility (a link never widens). `PATCH /documents/{doc}` visibility
    and archive on a kind-`attachment` document → 409 `attachment_follows_note`. Attachments stay out of the
    Documents tab and are found by content search under the document rule. `POST` notes is
    `multipart/form-data`; the upload size guard covers it with `ATTACHMENTS_MAX_FILES × UPLOAD_MAX_BYTES` +
    overhead.

19. **Case stages.** One track per case; the latest `case_stages` row is current; any stage may be set (guided,
    not enforced) by a `stages.set` holder with a working basis (the personal holder included, decision 9);
    `office_id` = the acting membership's office; `response_mode` carried from the previous row (else
    `department`); note ≤ 2,000; the same stage and mode again → 409 `unchanged`. The read returns history and
    the **gaps** (main-phase stages before the current one, by `sort_order`, never recorded). A send accepts an
    optional `stage` recorded in the same step (e.g. `parawise_comments_sought`), needing `stages.set` (403 before
    anything is written). No stage is set by the system.

20. **Events.** `custody_moved` (existing; payload: reason, holder office code, holder user name, holder
    designation, membership id, pending action, due date, seq no, previous holder user id — never the remark),
    `note_added` (note id, `ref_no`, `seq_no`, kind, visibility, office code, superseded `ref_no`, `finalised`
    true when it came from a draft), `stage_set`. Dedupe `<type>:<row id>` (`custody_moved:<case>:<seq>` as
    built). Timeline: `custody_moved` and `stage_set` for everyone who sees the case (the eOffice tracking view);
    `note_added` only when the note is visible to the caller. Drafts write no event.

21. **Audit rows** (actor snapshot of the acting membership, IP, user agent): `custody.sent`, `custody.recalled`,
    `stage.set`, `note.added`, `note.finalised`, `note.draft_saved`, `note.draft_updated`, `note.draft_deleted`;
    each new file writes the existing `document.uploaded`. `after` holds references, codes, lengths and SHA-256
    of note bodies and remarks — never the text.

22. **Retired request codes and functions.** New functions `custody.recall` and `custody.track` are added by the seed (decisions 6 and 24a, owner review 2026-10-07; enabled for `dept_admin` in the default matrix, granted to officers by their department admin or by the super admin). Seed: `ref_permission` `requests.send` and `requests.answer` set
    `is_active = false` (and their matrix rows `is_enabled = false`); `access` ignores inactive functions (47 after
    `user-memberships` adds `users.propose_head` and `admin.tickets`, 49 with the two custody functions → 47
    active; owner review 2026-10-07). `ref_event_type` `request_sent`, `request_answered` and `ref_alert_kind` `request_due` retired;
    `ref_record_type` `REQ` retired. The Python members stay, marked retired, so old rows still load.

23. **Alerts: kind `workflow` (seed), three sources.** (a) **File received**: `custody_moved` with reason
    `sent` or `reassigned_on_exit` (owner review 2026-10-07) → the new holder user. (b) **File recalled**: `custody_moved` with reason `recalled`, `allotted`,
    `taken_over` or `transferred` that took the file from a personal holder → that previous holder (if active and
    not the actor). (c) **Due / overdue**: the date sweep raises one alert per current leg with a due date within
    `REQUEST_DUE_SOON_DAYS` (the existing setting, now also used here) — severity `high` when due soon,
    `critical` when overdue — to the holder (custody-holder rule of alerts decision 14) and, when overdue, also to
    the owning department's users holding **`custody.track`** (owner review 2026-10-07, see decision 24a); key
    `workflow_due:<leg id>`, closed
    `done` when the case's current leg changes. (a) and (b) are informational (expire after
    `ALERT_INFO_EXPIRE_DAYS`; severity `high` when the due date is within the window, else `normal`). Addressed
    office = the holder office (a, c) or the previous holder office (b). Text: kind label, offices, officer
    designation, case number, pending action, due date — never the remark or a note. The `request_due` sweep and
    `Resolver.for_request` are removed. **Flagged:** `workflow` is a kind beyond the plan's list, so that "alerts
    go to the current custody holder" reaches a new holder at once.

24. **Accountability views.** `GET /custody/held`: `scope=me` (cases whose holder user is the caller, any
    membership), `scope=office` (holder office in the subtree of any of the caller's memberships' roots — the
    department for whole-department memberships, else the own office), `scope=owned` (cases owned by a department
    where the caller has a whole-department membership, wherever they are held, showing holder office, officer,
    pending action, since, due date, overdue days); filter `overdue`, `holder_department`; ordered by due date then
    since; always ANDed with `visible_case_condition`. `GET /custody/sent`: the legs the caller wrote (sends and
    recalls) with the case summary (searchable facts only) and the leg; detail still needs visibility. The
    dashboards and the "pending actions by office" report (`reports-dashboards`) read the same columns.

24a. **Tracking pending and overdue files is a function the department admin grants (owner review 2026-10-07).**
    A new function **`custody.track`** (module `custody`). In the default type matrix it is enabled for
    **`dept_head`** (the seniormost officer) and **`dept_admin`**; off for every other type. A department admin
    gives it to any other officer of their department with the existing per-user grant (per membership); the
    super admin can grant or deny it to anybody. A membership holding `custody.track` in a department:
    (i) receives the overdue (`critical`) and due-soon (`high`) `workflow` alerts for every case that department
    owns, wherever the file is held, alongside the holder; (ii) may use `GET /custody/held?scope=owned` and
    `GET /custody/summary` for that department. `GET /custody/summary` (new) returns, per owned department the
    caller tracks: files held, due within the window, overdue, and the same counts by holder department and by
    holder office/officer (counts only, no case text). Tracking gives sight of the owned department's files and
    their custody cards but no recall, no send and no ownership action. It replaces "overdue alerts to the
    `cases.allot` / `custody.recall` holders". Every grant and deny is audited by the existing override service.

25. **Case detail.** The custody card: holder office, holder officer (name, designation), pending action (code,
    label), since, due date, `overdue`, sent by (actor name, designation, office code), remark (decision 11),
    `leg_seq_no`, `can_send`, `can_recall`; a `stage` block; `counts` gains `notes` (visible permanent notes) and
    `my_drafts`. `requests` disappears from counts and tabs.

26. **Locks.** Send, recall, ownership moves, every note write, draft save, update and delete take the case row
    lock (`SELECT … FOR UPDATE`) before reading custody, computing `seq_no` or checking the holder. A draft edit
    racing a send waits, then finds the draft finalised → 409 `draft_finalised`. Unique violations on
    `(case_id, seq_no)` or `ix_case_notes_supersedes` map to 409.

27. **The request tables are dropped, by a new migration.** `requests`, `request_messages`, `ref_request_kind`,
    the `request_status` enum and the `request_id` columns of `custody` and `custody_history` were created by the
    applied 0001 and have never held a row (nothing writes them). Migration 0009 drops them after checking they
    are empty (it stops otherwise: no legal record is dropped); 0001 is not edited. The `request` visibility basis
    goes. Alternative: leave them unused — rejected: dead tables and columns in an approved schema invite misuse
    and keep `custody.request_id` pointing at a concept the owner removed.

## Data
Migration **0009_workflow** (new file; depends on `0008_memberships`; 0001–0007 applied and untouched).

New tables, for `schema.md` "Phase 2 and 3 tables":

> | `case_note_drafts` (transaction, **mutable and deletable**) | id (uuid v7 PK), case_id (→ cases RESTRICT), membership_id (→ user_memberships RESTRICT; the holder membership that wrote it), author_user_id (→ users RESTRICT), custody_leg_id (→ custody_history RESTRICT; the leg during which written), kind (→ `ref_note_kind`), body (1–20,000), visibility (`doc_visibility`), supersedes_id (→ case_notes RESTRICT, NULL), created_at, updated_at, actor snapshot | Index `ix_case_note_drafts_case_membership` (case_id, membership_id). Visible only to `author_user_id`. Exists only while `membership_id` holds the case; turned into `case_notes` rows and deleted in the transaction that moves custody away (design `custody-workflow` decisions 12–13). `aslms_app` has DELETE on this table. |
> | `case_note_draft_documents` (transaction, deletable with its draft) | id, draft_id (→ case_note_drafts RESTRICT), document_id (→ documents RESTRICT), created_at | Unique (draft_id, document_id). The document belongs to the draft's case. Rows deleted by the service before their draft; become `case_note_attachments` on finalisation. `aslms_app` has DELETE. |

Changed rows of `schema.md` "Phase 2 and 3 tables" (as built after 0009):

> | `custody` | case_id (PK, → cases RESTRICT), holder_office_id (→ offices RESTRICT), holder_user_id (→ users SET NULL), **holder_membership_id (→ user_memberships RESTRICT, NULL for an office-held leg)**, pending_action, since, due_date, current_leg_id (→ custody_history) | Exists only for claimed cases. Written only by `services/custody.py::move_custody`: ownership moves, `sent`, `recalled`. Partial index `ix_custody_due` (due_date) WHERE due_date IS NOT NULL; index `ix_custody_holder_user` (holder_user_id). `request_id` dropped by 0009. |
> | `custody_history` (derived, append-only) | id, case_id, seq_no (unique per case), holder_office_id + holder_office_code, holder_user_id + holder_user_name, **holder_membership_id (→ user_memberships RESTRICT) + holder_designation (snapshot, ≤ 200)**, reason (CHECK `ck_custody_history_reason`: `claimed`, `allotted`, `taken_over`, `transferred`, `sent`, `recalled`, **`reassigned_on_exit`** (owner review 2026-10-07: the exit step of `user-memberships` decision 21; remark required as for `sent`; legs written before 0009 by the exit step already carry the remark, so the CHECK validates)), pending_action, due_date, **remark (≤ 2,000; CHECK `ck_custody_history_remark`: reason NOT IN ('sent','recalled','reassigned_on_exit') OR remark IS NOT NULL)**, started_at, actor snapshot (the sender or recaller), created_at | One row per movement; the chain is the file's movement record. `request_id` dropped by 0009. |
> | `case_notes` (transaction, append-only) | … as built, + **drafted_at** timestamptz NULL (set when the note came from a draft) | CHECK `ck_case_notes_not_self`; partial unique `ix_case_notes_supersedes`. A note is permanent from insert; drafts live in `case_note_drafts`. |
> | `case_note_attachments` (transaction, append-only) | as built | Trigger `aslms_forbid_change` added by 0009; no UPDATE for `aslms_app`. |
> | `case_stages` | as built | Index `ix_case_stages_case_created` (case_id, created_at DESC). |

Removed rows: `requests`, `request_messages`, `ref_request_kind` (dropped by 0009). Conventions: code sets become
eight `ref_*` tables plus `ref_record_type` (nine after `user-memberships` adds `ref_ticket_kind`, minus
`ref_request_kind`; owner review 2026-10-07); the append-only list adds `case_note_attachments`; the "No deletion"
paragraph gains: "**Deviation from DB_STANDARD §6 / §9 (owner's rule of 7 Oct 2026):** `aslms_app` may DELETE
from `case_note_drafts` and `case_note_draft_documents`, which hold unfinished drafts, not legal records";
`withdrawn_at` on requests is removed from the lifecycle list; the visibility basis list loses `request`.

Migration 0009 contents: guard (stop unless `requests` and `request_messages` are empty and no `custody` /
`custody_history` row has `request_id`); drop the `request_id` FKs, indexes and columns, `request_messages`,
`requests`, `ref_request_kind`, enum `request_status`; `ALTER TYPE pending_action ADD VALUE` × 7 (decision 10);
add `custody.holder_membership_id`, `custody_history.holder_membership_id`, `holder_designation`, `remark`,
`case_notes.drafted_at`; the CHECKs and indexes above; create the two draft tables (`class=transaction`
comments, grants SELECT/INSERT/UPDATE/DELETE for `aslms_app`, `set_updated_at` on `case_note_drafts`); trigger and
`REVOKE UPDATE` on `case_note_attachments`. Downgrade: stops while drafts exist or any leg uses the new reasons;
recreates the dropped tables and columns empty (0001 shapes); leaves the added enum values (PostgreSQL cannot drop
them; harmless).

Reference codes (seed only): `ref_note_kind` + `opinion` ("Opinion"), `hand_over` ("Hand-over"); `hearing`
relabelled "Hearing note"; `correction` retired. `ref_alert_kind` + `workflow` ("Workflow", default `normal`);
retired per decision 22. Enums: `NoteKind.OPINION`, `NoteKind.HAND_OVER`, `AlertKind.WORKFLOW`, the seven
`PendingAction` members; models `CaseNoteDraft`, `CaseNoteDraftDocument` in `domain/workflow.py`; `Request`,
`RequestMessage`, `RefRequestKind`, `RequestKind` removed. No new function.

## Services
- `services/documents.py` (refactor, uploads unchanged): split `upload` into `check_file` and
  `create_document`; `change_visibility` and `archive` refuse kind `attachment`.
- `services/attachments.py` (new): `prepare` (check and scan every file first), `resolve_links` (same case, visible,
  not archived; else 400 `bad_document_ref`), `create_all` (kind `attachment`, group `internal`).
- `services/custody.py` (extended): `REASONS` (decision 2/27; `reassigned_on_exit` already added by
  `user-memberships`); `move_custody(session, actor, case, *, office,
  user=None, membership=None, reason, pending_action=NONE, due_date=None, remark=None)` — writes leg and row,
  calls `notes.finalise_drafts` when the holder membership changes (decision 13), emits `custody_moved`;
  `controls_custody(session, user, custody)` (decision 4); `send(session, actor, user, case, *, to_membership,
  pending_action, due_date, remark, stage)` (decisions 3, 4, 19); `recall(session, actor, user, case, *, remark)`
  (decision 6); `recipients(session, user, department, q, limit, offset)` (decision 3 targets); `card`,
  `history` (remark per decision 11), `held(session, user, scope, overdue, holder_department, limit, offset)`,
  `sent(session, user, limit, offset)` (decision 24). Every write re-snapshots the actor with the acting
  membership (`user-memberships` decision 10) and writes its audit row.
- `services/notes.py` (new): `add_note(...)` (draft for the personal holder, permanent otherwise — decisions
  12, 14; files only for permanent notes); `update_draft`, `delete_draft`, `list_drafts` (author only, holder
  check under the case lock); `finalise_drafts(session, actor, case, membership_id)` (decision 13);
  `list_for_case`, `get`, `note_out`, `visible_count`.
- `services/stages.py` (new): `set_stage`, `current`, `history_with_gaps`, `catalogue`.
- `services/visibility.py`: `request` basis removed; `note_visible_condition`, `can_view_note`; custody basis
  per membership (`user-memberships` decision 7); `WORKING_BASES` without `request`.
- `services/ownership.py`: its `move_custody` calls pass the officer's membership in the department.
- `services/case_detail.py`: decision 25; timeline per decision 20.
- `services/alerts.py`, `alert_rules.py`, `recipients.py`: decision 23 (`for_request` and the request sweep
  removed; `render` for `workflow`; `Resolver.previous_holder(payload)`).
- `services/workflow_codes.py`: note kinds (with `selectable`), pending actions with labels, stages with phase,
  response modes, custody reasons with labels.
- Settings (`.env.example`): `ATTACHMENTS_MAX_FILES=5`, `NOTE_MAX_CHARS=20000`, `NOTE_DRAFTS_MAX=20`.

## API
New router `api/routers/workflow.py`. `{ref}` = case id, CNR or dash-form `ref_no`; `{note}` = id or dash-form
`ref_no`; `{draft}` = id. Every case-scoped endpoint first applies `require_visible` (404 "no such case");
`read` = `cases.view_scope` or `cases.view_all`. Errors `{code, message}`.

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /workflow/codes` | `read` | — | note kinds, pending actions, stages, response modes, custody reasons | Labels. |
| `GET /cases/{ref}/custody` | `read` | `limit`, `offset` | `{card, legs: [{seq_no, holder_office, holder_user, holder_designation, reason, pending_action, due_date, remark?, started_at, actor_name, actor_designation, actor_office_code}], total}` | Remark per decision 11. |
| `GET /custody/recipients` | `cases.view_scope` | `department?`, `q?`, `limit`, `offset` | without `department`: `[{code, name}]` departments; with it: `[{membership_id, full_name, designation, office_code, office_name, role_label}]` | Decision 3 targets only. |
| `POST /cases/{ref}/custody/send` | `cases.view_scope` (gate); the holder, or `custody.move` + control for an office-held leg | `{to_membership, pending_action, due_date?, remark, stage?}` | `{card, leg, finalised_notes: [ref_no]}` 201 | Decisions 3, 4, 13, 19; 409 `not_owned`, `unchanged`; 403 `not_in_control`; 400 `bad_target`, `bad_due_date`. |
| `POST /cases/{ref}/custody/recall` | `custody.recall` (in a membership of the owning department) | `{remark}` | `{card, leg, finalised_notes}` 201 | Decision 6; 403 `not_owner_department`; 409 `unchanged`. |
| `GET /custody/summary` | `custody.track` (in the owned department) | `department?` | `{departments: [{code, held, due_soon, overdue, by_holder_department, by_holder}]}` | Decision 24a; counts only. |
| `GET /custody/held` | `read` (`scope=owned` needs `custody.track` in that department) | `scope=me|office|owned`, `overdue?`, `holder_department?`, `limit`, `offset` | `{items: [{case summary, card}], total}` | Decision 24; visible cases only; `owned` needs a whole-department membership (else 403). |
| `GET /custody/sent` | `read` | `limit`, `offset` | `{items: [{case summary, leg}], total}` | Legs the caller wrote. |
| `GET /cases/{ref}/stages` | `read` | — | `{current, history, gaps}` | Case visible. |
| `POST /cases/{ref}/stages` | `stages.set` | `{stage, response_mode?, note?}` | `{current}` 201 | Decision 19; working basis; 409 `not_owned`, `unchanged`. |
| `GET /cases/{ref}/notes` | `read` | `kind?`, `include_superseded` (true), `limit` (50, max 200), `offset` | `{items: [note], total}` | `note_visible_condition`; by `seq_no`; drafts never listed. |
| `POST /cases/{ref}/notes` | `notes.add` | multipart: `kind`, `body`, `visibility`, `supersedes?`, `document_refs[]`, and (permanent notes only) `files[]`, `file_doc_types[]` | note (`draft: false`) or draft (`draft: true`) 201 | Decisions 12–18; files sent by the holder → 400 `drafts_take_links_only`; 400 `bad_field`; 403 `not_author`; 409 `not_owned`, `already_superseded`, `too_many_drafts`; 413/415/422/503 as uploads. |
| `GET /cases/{ref}/notes/drafts` | `notes.add` | — | `{items: [draft]}` | The caller's own drafts on the case. |
| `PATCH /notes/drafts/{draft}` | `notes.add` | `{kind?, body?, visibility?, supersedes?, document_refs?}` | draft | Author, still holding; 404 for anyone else; 409 `draft_finalised`. |
| `DELETE /notes/drafts/{draft}` | `notes.add` | — | 204 | Author, still holding; the only delete in the case's records (owner's rule). |
| `GET /notes/{note}` | `read` | — | note | 404 when not visible. |

Note shape: `{id, ref_no, seq_no, kind, kind_label, body, visibility, author: {name, designation, office_code,
role}, created_at, drafted_at?, custody_leg_seq_no, supersedes?, superseded_by?, attachments: [{ref_no,
original_filename, doc_type, mime, size_bytes, linked}]}`. Draft shape: `{id, kind, body, visibility,
supersedes?, documents: [{ref_no, original_filename}], created_at, updated_at, draft: true}`.
Changed: `GET /cases/{ref}` (decision 25), `GET /cases/{ref}/timeline` (decision 20), `PATCH /documents/{doc}`
and `POST /documents/{doc}/archive` (409 for attachments), the upload size guard (notes path).

## Jobs
No new job. `aslms.alerts_scan_events` handles `custody_moved` for decision 23 (a, b); `aslms.alerts_sweep_dates`
replaces its request block with the custody due block (c). Attachment text extraction goes through the existing
`aslms.extract_document_text` after commit.

## Tests
Unit: `test_workflow_rules.py` — reasons equal the CHECK list (including `reassigned_on_exit`, owner review
2026-10-07); pending-action labels cover every enum member;
stage gaps; note kind selectability (`hand_over` and `opinion` selectable, `correction` retired); retired
functions excluded from effective functions.

Database (`tests/db/`, `world.py` with the two-department person of `user-memberships` and the scripted
scanner/store fakes):
- `test_custody_send.py`: the holder sends to an officer of another department (leg `sent`, membership,
  designation snapshot, remark, pending action, due date; ownership unchanged); a referral reviewer holding the
  file sends it on without `custody.move`; a non-holder → 403; office-held leg sent by a nodal officer and by a
  unit user with `custody.move`; State-wide target, inactive membership, same holder → 400/409; due date in the
  past → 400; `stage` with send recorded or refused without `stages.set` (nothing written).
- `test_custody_recall.py`: **`test_recall_from_any_depth`** (EDU → HEALTH officer → HEALTH directorate officer →
  FIN officer; the EDU admin recalls in one step; the card shows the admin; every holder's drafts permanent);
  recall by an EDU officer without `custody.recall` → 403, then the EDU admin grants it and the same officer
  recalls → 201; the super admin grants it to a HEALTH officer → recall of an EDU case still 403
  (`not_owner_department`); a HEALTH nodal officer → 403; recall when already holding → 409; an
  ownership move (allot) while the file is out acts as recall and alerts the previous holder.
- `test_holder_access.py`: the holder from another department sees the case, uploads, sets a stage, writes
  drafts, cannot allot, claim, transfer or recall; after sending on they lose sight (404) unless another basis;
  `GET /custody/sent` still lists the leg.
- `test_note_drafts.py`: holder's note is a draft (no `ref_no`, invisible to State-wide reader and owner);
  author edits and deletes; others get 404; links only (files → 400); send finalises all drafts in order with
  consecutive `seq_no`, `drafted_at`, `custody_leg_id` = the holder's leg, attachments from links, draft rows
  gone, one `note_added` event each — all in the send's transaction (a forced failure after finalisation rolls
  back both); a draft correction whose target was corrected meanwhile supersedes the latest; edit racing a send →
  409 `draft_finalised` (two sessions); `too_many_drafts`.
- `test_notes.py`: non-holder notes permanent; `seq_no` under concurrency; author snapshot frozen and taken from
  the acting membership; UPDATE/DELETE on `case_notes` and `case_note_attachments` refused; correction rules.
- `test_note_visibility.py`: the three visibilities × types, the two switches, a two-membership reader sees
  private notes of both offices; timeline follows the rule.
- `test_note_attachments.py`: as approved before (internal `attachment`, scan refusal writes nothing, limits,
  link never widens, `attachment_follows_note`, absent from Documents tab).
- `test_stages.py`: as before, plus the personal holder from another department may set a stage.
- `test_workflow_alerts.py`: send → `workflow` alert to the new holder only; recall → previous holder; due soon
  `high`, overdue `critical` with the owning department's `cases.allot` holders added; closed when the leg
  changes; text has no remark or note body; no `request_due` alert is raised.
- `test_api_workflow.py`: each endpoint's function check (403), invisible case (404), shapes, remark hidden from a
  recommended-department reader, size guard (413), audit rows with no note or remark text.
- Migration test: 0009 upgrade → downgrade → upgrade on an empty database; the guard stops on a seeded request
  row; `test_schema_metadata.py` in step with `schema.md`; `DELETE` on `case_note_drafts` allowed for
  `aslms_app`, on `case_notes` refused.

## Verification
1. `alembic upgrade head` → `0009_workflow` (after `0008_memberships`); `aslms seed` reports `ref_note_kind` +2,
   `ref_alert_kind` +1 and the retired codes; `\dt requests` → no relation.
2. `ruff check` clean; `pytest -q` green (count in the cycle report).
3. With Compose up, on a claimed EDU case: as the EDU admin `GET /custody/recipients?department=HEALTH`, then
   `POST /cases/{ref}/custody/send` to a HEALTH officer with `pending_action=parawise_comments`, a due date and a
   remark → the card shows the HEALTH officer, designation and due date; as that officer `POST
   /cases/{ref}/notes` → `draft: true`; send on to a HEALTH directorate officer → `finalised_notes` lists one
   `ref_no`; `GET /cases/{ref}/notes` as the EDU admin shows it.
4. As the EDU admin `POST /cases/{ref}/custody/recall` with a remark → card shows the admin; `GET
   /custody/held?scope=owned` lists the case with no due date; after `aslms alerts run` the directorate officer
   has a `workflow` "recalled" alert.
5. `psql`: `UPDATE case_notes SET body='x'` fails; `SELECT count(*) FROM case_note_drafts` = 0 for the case;
   `audit_log` rows for `custody.sent`, `custody.recalled`, `note.finalised`, none containing note or remark text.

## Open questions
None. Points the owner is asked to check at approval (decisions taken, reversible):
- standing counsel are valid targets of a send; State-wide types are not (3);
- the holder may send on without `custody.move`; holding is the authority (4);
- recall is the `custody.recall` function: on for department admins by default, granted to chosen officers by
  their department admin, and to anybody by the super admin; it works only in the owning department (6);
- previous holders lose sight of the case once it moves on, keeping only their "sent" list (9);
- the holder may set the case stage while holding (9, 19);
- drafts become permanent only when the file moves; there is no "make permanent now"; drafts link existing
  documents rather than carry new files (12);
- the holder cannot change their own pending action or due date (5);
- overdue files alert the owning department's nodal officers as well as the holder (23);
- the request tables are dropped by migration 0009 rather than left unused (27);
- the DB_STANDARD deviation: DELETE allowed on the two draft tables (Data);
- the plan's seven note kinds plus `counsel_advice` and `file_noting`, `correction` retired (15).
