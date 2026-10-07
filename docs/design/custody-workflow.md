# Design: Custody and workflow — custody moves and hand-over, requests and answers, case stages, the notes trail with attachments and per-note visibility

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
since when, due date); "Requests between offices, for example a department asking a directorate for parawise
comments, with stages and due dates"; "Hand-over of a case to another office, recorded with a note"; portal
database only, no court API; links to notes trail, alerts, dashboard, reports (pending actions by office).
Plan §5.8 (Case Notes Trail): an official noting history that belongs to the case and follows it across every
custody move; notes by type "general, instruction, opinion, hearing note, compliance, decision, hand-over"; each
note records the author's name, designation and office at the time; notes cannot be edited or deleted,
corrections are new notes linked to the original; attachments on notes; visibility per note (whole case, shared
with counsel, private to the office). Plan §5.13: notes, custody moves and uploads are audited. Plan §3.2 / §5.9:
notes and internal documents are never sent to SourceTrace. Plan §5.1 (officer: own pending actions; department:
cases with pending action, cases in custody of each office). Backlog row 6.

Earlier decisions in the log that this design follows:
- 25 Sep "CUSTODY" (eOffice-style, derived from requests, stages and assignments; tracking card visible, contents
  scoped) and "CASE NOTES / NOTING TRAIL" (append-only, author snapshot, per-case `seq_no`, custody leg recorded,
  corrections via `supersedes`, attachments are `documents` rows through `case_note_attachments`, reusable across
  notes; three visibility values; State tier sees all; hand-over = hand-over note + custody move in one step;
  event and audit row per note).
- 26 Sep "Custody is derived" (request sent → receiving office with the request's due date; answered or withdrawn
  → back to the requester; hand-over → explicit move with a mandatory note), "Scope widened by workflow"
  (custody and request bases, personal for department-office officers and referral reviewers), "Stages" (the 17
  stages, any stage may be set, skipped main-track stages shown as a gap), "Notes" (attachments are internal
  documents, excluded from SourceTrace), "Request alerts".
- recommend-and-claim decision 11 and its review: custody follows primary ownership (`claimed`, `allotted`,
  `taken_over`, `transferred`); "release → the next primary owner" is superseded (no return to the pool).
- cases-api: one case-visibility rule (`services/visibility.py`), 404 for an invisible case, the custody card
  in the overview, decision 15 ("notes, documents, requests, stages and alerts join the timeline in their own
  items with their own visibility").
- documents-uploads: type by content, ClamAV before storage, `UPLOAD_MAX_BYTES` (20 MB), `record_visibility_
  condition` (reused by notes), `works_on_case` (a working basis), `DOC` numbers on the uploader's office, the
  CHECK `ck_documents_internal_not_sent`; "the Documents tab lists uploads and order PDFs, not note attachments
  (`custody-workflow` owns those)".
- alerts-notifications decision 11 (request due: within 2 days high, overdue critical, done when answered or
  withdrawn; recipients the addressee or the receiving office's `requests.answer` holders — built, waiting for
  requests) and decision 14 (recipients: custody holder, owner, watchers).

What is in place:
- Tables from migration 0001 (Phase 2): `custody` (1:1 with the case), `custody_history` (append-only trigger),
  `requests` (+ `request_status` enum `open` / `answered` / `withdrawn`), `request_messages`, `case_stages`
  (append-only, + `response_mode` enum `department` / `counsel` / `none`), `case_notes` (append-only, `ref_no`,
  `seq_no` unique per case, `visibility` on `doc_visibility`, `custody_leg_id`, `supersedes_id`, `source` enum
  `user` / `system`), `case_note_attachments` (unique `(note_id, document_id)`). Enum `pending_action`
  (`none` / `examine` / `reply` / `file` / `comply` / `review`). All FKs RESTRICT; actor snapshots present.
- Code sets: `ref_case_stage` (17 stages with `phase`), `ref_request_kind` (8), `ref_note_kind` (`general`,
  `decision`, `instruction`, `hearing`, `counsel_advice`, `compliance`, `file_noting`, `correction`).
  `RecordType` `REQ` and `NOTE`. Event types `custody_moved`, `request_sent`, `request_answered`, `stage_set`,
  `note_added`.
- Functions `custody.move`, `requests.send`, `requests.answer`, `stages.set`, `notes.add`,
  `notes.view_counsel_shared`, `notes.view_private_office` (in `_CASE_WORK`: dept head, dept admin, dept
  officer, directorate user; referral reviewer: `notes.add`, `stages.set`, `requests.answer`; standing counsel:
  `notes.add`, `notes.view_counsel_shared`). No new function is needed.
- `services/custody.py::move_custody` (ownership reasons only; it never sets `pending_action`, `due_date` or
  `request_id`, and leaves a stale `custody.request_id` in place). `services/documents.py::upload` already
  accepts `kind=attachment`, but scans, stores and writes the row in one call. `visibility.py` already has the
  `custody` and `request` bases. Nothing writes requests, stages or notes; there are no endpoints.

Not covered: the portal screens (`portal-workflow`); dashboards and the "pending actions by office" report
(`reports-dashboards`, which reads these tables); the Case Assistant's "copy an answer into a note" (`assistant`,
which will write an ordinary note through this item's service); SMS; custody due-date alerts
beyond requests (decision 21).

## Decisions
1. **Custody exists only for a claimed case.** Every write of this item (hand-over, action, request, stage, note)
   requires an active primary owner; on an unclaimed case it answers 409 `not_owned`. Alternative: allow notes on
   pool cases — rejected: the plan places the notes trail with the owning department's handling, and the pool
   has no custody to attach a leg to.

2. **Custody reasons (one CHECK).** `custody_history.reason` ∈ `claimed`, `allotted`, `taken_over`,
   `transferred` (existing), `handed_over`, `request_sent`, `request_assigned`, `request_answered`,
   `request_withdrawn`, `action_set`. `move_custody` gains `pending_action`, `due_date` and `request_id`
   parameters and writes them to both the leg and `custody`; the ownership reasons pass none, so an ownership
   move (allot, take over, transfer) clears `custody.request_id` and pulls the file back (ownership decisions
   win; any open request stays open and can still be answered or withdrawn, its answer simply no longer moves
   custody). Alternative: ownership moves leave custody alone while a request is out — rejected: it contradicts
   recommend-and-claim decision 11 already built and tested.

3. **Who controls custody (`controls_custody`).** The caller is the holder user; or the holder has no user, the
   holder office is not Department-tier, and the caller's office is the holder office; or the caller is a
   whole-department caller (`cases.claim` or `cases.allot`) of the department that contains the holder office
   (for a Department-tier holder with no user, only these nodal officers — the same rule as alerts decision 14).
   Hand-over and action setting need `custody.move` plus control; sending a request with custody needs
   `requests.send` plus control. Alternative: any `custody.move` holder working on the case — rejected: an
   officer could pull a file another office is working on.

4. **Hand-over (plan "recorded with a note") is one step:** move + a `hand_over` note written in the same
   transaction, the note body mandatory, with optional attachments. Target: an active office and optionally an
   active user of that office holding `cases.view_scope`; it must differ from the current holder (409
   `unchanged`). **Scope:** when custody is not under a request, the target lies in the owning department's
   subtree (department, directorates, units); when custody is under a request, the target lies in that
   request's receiving office's subtree and the leg carries the `request_id` forward (the obligation travels
   with the file, and the answer still returns it). Moving a case to another department is an ownership
   transfer (recommend-and-claim), and asking an office outside the department is a request. Pending action
   (default `examine`) and due date (optional) are set on the new leg. Hand-over never changes allotment.
   Alternative: hand-over to any office — rejected: it would give an office outside the department custody
   without ownership or a request, bypassing the transfer decision. **Flagged for the owner** (plan says "another
   office" without limits).

5. **Pending action without a move.** `PUT /cases/{ref}/custody/action` sets `pending_action` and `due_date` for
   the current holder; it appends a leg with reason `action_set` and the same holder (history stays
   append-only). Due date, when given, is today (IST) or later, at most 365 days ahead.

6. **Requests and custody.** A request is sent by a `requests.send` holder working on the case to any active
   office other than the sender's own office (a directorate, another department's office, the Advocate General,
   a counsel office), optionally to a named user inside that office's subtree. `with_custody` (default true)
   decides whether the file goes with it:
   - `with_custody = true` needs `controls_custody`, and is refused (409 `custody_out_on_request`) when custody
     is under an open request that the caller's side did not receive (send it without custody or withdraw the
     first). Custody moves to the receiving office (and the addressee), reason `request_sent`, pending action
     from the request (default per kind: `opinion` → `review`, `compliance` → `comply`, every other kind →
     `reply`), due date = the request's due date, `request_id` = the request. `requests.moves_custody = true`.
   - `with_custody = false` moves nothing (parallel requests: a department asking two directorates at once).
   - **Answer** or **withdraw**: when `custody.request_id` is this request, custody returns to the leg that was
     current just before this request's `request_sent` leg (its holder office and user; a user since deactivated
     is dropped and the office kept), reason `request_answered` (pending action `examine`, the earlier leg's due
     date and `request_id` — so a sub-request inside a directorate returns the file to the directorate still
     owing its own answer; a `request_id` whose request is no longer open is cleared) or `request_withdrawn`
     (the earlier leg's pending action restored). When custody has meanwhile moved for another reason, the
     answer is recorded and custody is not touched (the response says `custody_moved: false`).
   Alternative: one open request per case — rejected: parallel parawise comments from two directorates are the
   plan's own example of normal work. Alternative: every request moves custody — rejected: the second request
   would silently take the file from the first office.

7. **Request life cycle.** `open` → `answered` (by the receiving side, with an answer body, optional
   attachments, sets `answered_at`, `answered_by_user_id`, writes a `request_messages` row with `is_answer =
   true`) or `withdrawn` (by the sending side, reason required, sets `withdrawn_at`, `withdraw_reason`). While
   open: either side adds messages (sending side `requests.send`, receiving side `requests.answer`; messages
   and their attachments append-only); the sending side may change the due date (`PATCH`, audited; custody's due
   date follows when custody is under this request); the receiving side may **assign** an addressee (decision
   8). No reopening; a new request is sent instead. Request "stages" in the plan are this life cycle plus the
   case stages recorded with it (decision 12).

8. **Assign an addressee (eOffice "mark to").** A request addressed to an office reaches its nodal officers
   (the request basis is office-wide only for whole-department callers; department-office officers and referral
   reviewers see personally — cases-api decision 2). So the receiving side's whole-department caller, or the
   current addressee, holding `requests.answer`, may set `to_user_id` to an active user in the receiving
   office's subtree; when custody is under this request it moves to that user (reason `request_assigned`).
   Without this a request to the Law Department could never reach its referral reviewers. Audited.

9. **Who answers.** The addressee; or, with no addressee, a `requests.answer` holder whose office is in the
   receiving office's subtree and who sees it under the request rule (decision 10); or a whole-department caller
   of the receiving office's department. 409 `not_open` on a closed request.

10. **Request visibility (`request_visible_condition`, SQL, over `requests`).** The case must be visible, and:
    State-wide readers see all; the sender (`actor_user_id`) and the addressee; the sending side and the
    receiving side (office in the subtree of `from_office_id` / `to_office_id` of the caller's root — the
    department for whole-department callers, else the caller's own office; personal callers only as sender or
    addressee); the owning department's whole-department callers and the case's allotted officer or unit (they
    handle the case). Everyone else who sees the case sees only the timeline line (kind, offices, dates, no
    subject or body). Standing counsel see a request only when their counsel office is a side.

11. **Request attachments.** A new table `request_attachments` links documents to a request (the request
    itself, `message_id` NULL) or to one message. New files are `documents` rows of kind `attachment`, group
    `internal`, visibility chosen by the sender from `case_scope` (default) or `counsel_shared` —
    `private_to_office` is refused because the other side could not open it. Existing documents of the same
    case visible to the caller may be linked by reference. Alternative: reuse `case_note_attachments` by writing
    each message as a note — rejected: requests are correspondence between offices, not the noting trail.

12. **Case stages.** One stage track per case; the current stage is the latest `case_stages` row; any stage
    may be set (guided, not enforced, 26 Sep), by a `stages.set` holder with a working basis — so the Law
    Department's reviewer answering a request may record `affidavit_vetted`. `office_id` = the setter's office;
    `response_mode` defaults to the previous row's (else `department`); `note` ≤ 2,000 characters; setting the
    current stage and mode again → 409 `unchanged`. The read returns the history and the **gaps**: main-phase
    stages ordered before the current stage (by `sort_order`) never recorded, when the current stage is a main
    one. Sending and answering a request accept an optional `stage` recorded in the same step (for example
    `parawise_comments_sought` / `parawise_comments_received`) — explicit, never automatic. No stage is set by
    the system. Alternative: per-office stage tracks — rejected: the plan's case card shows one stage.

13. **Note kinds (deviation, small).** The plan lists seven: general, instruction, opinion, hearing note,
    compliance, decision, hand-over. The built set lacks `opinion` and `hand_over`; both are added (seed).
    `hearing` is labelled "Hearing note". `hand_over` is written only by the hand-over step (decision 4); a
    plain note with that kind → 400. A correction carries the original note's kind (decision 15), so the
    built code `correction` is retired (`is_active = false`, set by the seed). **Deviation, flagged:** the
    built extras `counsel_advice` and `file_noting` are kept selectable beyond the plan's seven.

14. **Writing a note.** `notes.add` and a working basis (`owner`, `allotted`, `custody`, `request`, `counsel`).
    Body 1–20,000 characters (`NOTE_MAX_CHARS`). Visibility is required (`case_scope`, `counsel_shared`,
    `private_to_office`; no default, as for documents). The note records `office_id` (the author's office),
    `author_role` (the user type), the actor snapshot (name, designation, office code at the time), `seq_no`
    (max + 1 under the case row lock), `custody_leg_id` = `custody.current_leg_id`, `source = user` (no system
    notes are written in this item), `ref_no` `ASLMS/<author office>/NOTE/<yyyy>/<n>`.

15. **Corrections.** `supersedes` names a note of the same case that the caller can see and that is not
    already superseded (409 `already_superseded`; the partial unique index guards the race — correct the latest
    note of the chain). Only the original author or a whole-department caller of the original note's
    department may correct it (403 `not_author`). The correction keeps the original's kind and visibility
    (a different visibility → 400): a correction is never a way to widen or narrow who reads the matter. Both
    notes are kept and listed; the original shows `superseded_by`.

16. **Note visibility (`note_visible_condition`, SQL, over `case_notes`).** A visible case, and
    `record_visibility_condition` (documents decision 7: `counsel_shared` to everyone on the case, `case_scope`
    to everyone but standing counsel unless the author, `private_to_office` to the office, its department-wide
    callers and the author; State-wide readers see all), and the two note functions as switches:
    `private_to_office` needs `notes.view_private_office` (except the author and State-wide readers);
    for standing counsel, `counsel_shared` needs `notes.view_counsel_shared`. Both are on by default for every
    type that can reach such notes, so the defaults equal the document rule; the super admin can switch them off
    per type or user. Alternative: ignore the two seeded functions — rejected: they exist in the matrix and
    would be dead switches.

17. **Note attachments.** Up to `ATTACHMENTS_MAX_FILES` (5) new files per call, each within
    `UPLOAD_MAX_BYTES`, type by content and ClamAV scan exactly as uploads; they become `documents` rows of kind
    `attachment`, group `internal` (so never sent to SourceTrace, enforced by `ck_documents_internal_not_sent`),
    `doc_type` from the internal group (default `correspondence`), `doc_date` today, description "Attachment to
    <note ref_no>", visibility = the note's. Existing documents of the same case that the caller can see (not
    archived) may be linked instead (`document_refs`); a linked document keeps its own visibility, and a reader
    sees an attachment entry only when the document rule lets them see that document (a link never widens).
    **All files are checked and scanned before anything is written**; one refused file refuses the whole call
    (its rejection audit row is committed, as for uploads). An attachment's visibility follows its note, so
    `PATCH /documents/{doc}` (visibility) and archive on a kind-`attachment` document answer 409
    `attachment_follows_note`. Attachments stay out of the Documents tab (documents-uploads deviation) and are
    found by the content search under the document rule.

18. **One multipart form per write that carries files.** `POST` notes, hand-over, requests, request messages and
    answers are `multipart/form-data` (text fields + repeated `files`, `file_doc_types`, `document_refs`), so a
    note and its files are written atomically and no orphan attachment can exist. The upload size guard
    middleware is extended to these paths with the limit `ATTACHMENTS_MAX_FILES × UPLOAD_MAX_BYTES` + overhead;
    each file is still counted against `UPLOAD_MAX_BYTES`. Alternative: upload attachments first, then cite them —
    rejected: orphan rows visible only through search.

19. **Events (payloads never carry note text, request subject or body).** `note_added` (scoped; note id,
    `ref_no`, `seq_no`, kind, visibility, office code, superseded `ref_no`), `custody_moved` (existing; payload
    gains `pending_action`, `due_date`, `request_ref_no`), `request_sent`, `request_answered`, the new
    `request_withdrawn` (request id, `ref_no`, kind, `from_office_code`, `to_office_code`, `due_date`,
    `moves_custody`), `stage_set` (stage, label, phase, response mode, office code). Dedupe keys
    `<type>:<row id>`. Timeline: request and stage events are shown to everyone who sees the case (the file
    movement is the eOffice tracking view; contents stay behind decision 10); `note_added` is shown only when
    the note is visible to the caller (joined through `payload.note_id`, as `document_uploaded` is).

20. **Audit rows** (actor snapshot, IP, user agent): `custody.handed_over`, `custody.action_set`,
    `request.sent`, `request.message_added`, `request.assigned`, `request.due_changed`, `request.answered`,
    `request.withdrawn`, `stage.set`, `note.added`; each attachment file writes the existing `document.uploaded`
    (kind `attachment`). Audit `after` holds references, codes and a body length and SHA-256 — never the note
    or message text (the append-only rows are the record; auditors read them through the normal rule).

21. **Alerts: one new kind `workflow` (seed only), informational.** The event scan raises it for
    `request_sent` (to the addressee, else the receiving office's `requests.answer` holders —
    `Resolver.for_request`), `request_answered` (to the sender if active, else the sending office's
    `requests.send` holders), `request_withdrawn` (as `request_sent`), and `custody_moved` with reason
    `handed_over` or `request_assigned` (to the new holder by the custody-holder rule of alerts decision 14).
    `custody_moved` with `request_sent` raises nothing (the `request_sent` alert covers it). Key
    `workflow:<event_id>`, addressed office = the receiving / returning / new holder office; severity `high` when
    the due date is within `REQUEST_DUE_SOON_DAYS`, else `normal`; expires after `ALERT_INFO_EXPIRE_DAYS`;
    recipients filtered by case visibility, never the actor. Mail and in-app text: kind label, offices, case
    number, due date — never the subject, body or note. Custody due dates of hand-overs raise no alert (the plan's
    alert list has request due only; overdue pending actions appear in the reports item). **Flagged:** like
    `ownership`, `workflow` is a kind beyond the plan's list, added so the plan's "alerts go to the current custody
    holder" reaches a new holder at once.

22. **Case detail.** The overview's custody card gains `request` (`ref_no`, kind, only when the request is
    visible to the caller, else just `under_request: true`), `leg_seq_no`; a `stage` block (code, label, phase,
    response mode, set at, office code). `counts` gains `notes` and `requests` (visible to the caller). The
    tabs are served by the new endpoints below.

23. **Locks.** Every write takes the case row lock (`SELECT … FOR UPDATE`, as ownership does) before computing
    `seq_no`, reading custody or checking control; request answer, withdraw, assign and due change also lock the
    request row. A unique violation on `(case_id, seq_no)` or `ix_case_notes_supersedes` maps to 409.

## Data
Migration **0008_workflow** (new file; 0001–0007 are applied and untouched).

New table, for `schema.md` "Phase 2 and 3 tables":

> | `request_attachments` (transaction, append-only) | id (uuid v7 PK), request_id (→ requests RESTRICT), message_id (→ request_messages RESTRICT, NULL = attached to the request itself), document_id (→ documents RESTRICT), created_at, actor snapshot (`actor_user_id` → users SET NULL, `actor_name`, `actor_designation`, `actor_office_code`) | Unique `uq_request_attachments` (request_id, message_id, document_id) NULLS NOT DISTINCT. Indexes on request_id, message_id, document_id. The message, when set, belongs to the request (checked by the service). New files are `documents` of kind `attachment`, group `internal`, visibility `case_scope` or `counsel_shared`; existing documents of the same case may be linked. Trigger `aslms_forbid_change`; no UPDATE grant for `aslms_app`. Design `custody-workflow` decision 11. |

Changed rows of `schema.md` "Phase 2 and 3 tables" (as built after 0008):

> | `custody` | case_id (PK, → cases RESTRICT), holder_office_id (→ offices RESTRICT), holder_user_id (→ users SET NULL), pending_action (`none` / `examine` / `reply` / `file` / `comply` / `review`), since, due_date, request_id (→ requests RESTRICT; the open request the file is out on), current_leg_id (→ custody_history), created_at, updated_at | Exists only for claimed cases. Written only by `services/custody.py::move_custody`: ownership moves (clear `request_id`), hand-over (carries `request_id`), request sent / assigned / answered / withdrawn, action set (design `custody-workflow`). |
> | `custody_history` (derived, append-only) | id, case_id, seq_no (unique per case), holder_office_id + holder_office_code, holder_user_id + holder_user_name, reason (CHECK `ck_custody_history_reason`: `claimed`, `allotted`, `taken_over`, `transferred`, `handed_over`, `request_sent`, `request_assigned`, `request_answered`, `request_withdrawn`, `action_set`), pending_action, due_date, request_id (→ requests RESTRICT), started_at, actor snapshot, created_at | One row per leg; an answered or withdrawn request returns custody to the leg before its `request_sent` leg. |
> | `requests` (transaction) | ref_no (unique, `ASLMS/<from office>/REQ/<yyyy>/<n>`), case_id (→ cases RESTRICT), kind (→ `ref_request_kind`), from_office_id, to_office_id (→ offices RESTRICT; CHECK `ck_requests_offices`: different), to_user_id (→ users SET NULL; inside the receiving office's subtree), subject (3–300), body, due_date, **moves_custody** boolean NOT NULL default false, status (`open` / `answered` / `withdrawn`), answered_at, answered_by_user_id (→ users SET NULL), withdrawn_at, **withdraw_reason** text, actor snapshot (the sender), created_at, updated_at | CHECKs `ck_requests_answered` ((status = 'answered') = (answered_at IS NOT NULL)), `ck_requests_withdrawn` ((status = 'withdrawn') = (withdrawn_at IS NOT NULL AND withdraw_reason IS NOT NULL)). Partial index `ix_requests_open_due` (due_date) WHERE status = 'open'; index `ix_requests_to_office_status` (to_office_id, status). With `moves_custody` the file goes to the receiving office and comes back on answer or withdrawal. Visible under `request_visible_condition`. |
> | `request_messages` (transaction, append-only) | id, request_id (→ requests RESTRICT), body (1–20,000), is_answer, actor snapshot, created_at | Trigger `aslms_forbid_change` added by 0008; exactly one `is_answer` row for an answered request (service). |
> | `case_stages` (transaction, append-only) | id, case_id, office_id (the setter's office), stage (→ `ref_case_stage`), response_mode (`department` / `counsel` / `none`), note (≤ 2,000), actor snapshot, created_at | Latest row is the current stage; index `ix_case_stages_case_created` (case_id, created_at DESC). Guided, not enforced; gaps are computed on read. |
> | `case_notes` (transaction, append-only) | ref_no (unique, `ASLMS/<author office>/NOTE/<yyyy>/<n>`), case_id, seq_no (unique per case), kind (→ `ref_note_kind`), body (1–20,000), visibility (`case_scope` / `counsel_shared` / `private_to_office`), office_id (the author's office), author_role, custody_leg_id (→ custody_history), supersedes_id (→ case_notes RESTRICT), source (`user`; `system` reserved), actor snapshot, created_at | CHECK `ck_case_notes_not_self` (supersedes_id <> id); partial unique `ix_case_notes_supersedes` (supersedes_id) WHERE supersedes_id IS NOT NULL (a note is corrected once; chains continue from the latest). A correction keeps the original's kind and visibility. Visible under `note_visible_condition`. |
> | `case_note_attachments` (transaction, append-only) | id, note_id (→ case_notes RESTRICT), document_id (→ documents RESTRICT), created_at | Unique (note_id, document_id). Trigger `aslms_forbid_change` added by 0008. New files are internal `attachment` documents with the note's visibility; linked documents keep theirs; never sent to SourceTrace. |

Conventions paragraph: the append-only list becomes `events`, `audit_log`, `case_notes`, `custody_history`,
`case_stages`, `request_messages`, `request_attachments`, `case_note_attachments`; "Notes reuse
`record_visibility_condition`" gains "plus the switches `notes.view_private_office` and (for standing counsel)
`notes.view_counsel_shared`; requests use `request_visible_condition`".

Migration 0008 contents: create `request_attachments`; add `requests.moves_custody`, `requests.withdraw_reason`;
the CHECKs and indexes above; triggers on `request_messages`, `request_attachments`, `case_note_attachments`;
`REVOKE UPDATE … FROM aslms_app` on those three; `COMMENT ON TABLE request_attachments IS 'class=transaction'`.
Downgrade drops exactly these. No data changes in the migration.

Reference codes (seed only, `aslms seed`): `ref_note_kind` + `opinion` ("Opinion"), `hand_over` ("Hand-over");
labels refreshed on every seed run for `hearing` ("Hearing note") and the two new codes (as permission labels
are); `correction` set `is_active = false` by the seed (a retired-codes map). `ref_event_type` + `request_withdrawn`
(timeline label "Request withdrawn"). `ref_alert_kind` + `workflow` ("Workflow", default severity `normal`).
Enums in `domain/reference.py`: `NoteKind.OPINION`, `NoteKind.HAND_OVER`, `EventType.REQUEST_WITHDRAWN`,
`AlertKind.WORKFLOW`. Model: `Request.moves_custody`, `Request.withdraw_reason`, `RequestAttachment` in
`domain/workflow.py`. No new function.

## Services
- `services/documents.py` (refactor, behaviour unchanged for uploads): split `upload` into
  `check_file(data, filename, *, scanner, max_bytes, session, actor, case) -> CheckedFile` (size, type by
  content, scan; writes the rejection audit row and raises `UploadRefused` as today) and
  `create_document(session, actor, user, case, checked, *, kind, doc_type, doc_group, doc_date, description,
  visibility, store) -> Document` (store, row, event, audit). `upload` = both. `change_visibility` and `archive`
  refuse kind `attachment` (`AttachmentFollowsNote`, 409).
- `services/attachments.py` (new): `prepare(session, actor, user, case, files, doc_types, *, max_files) ->
  list[CheckedFile]` (all checks and scans first; doc types from the internal group, default `correspondence`);
  `resolve_links(session, user, case, refs) -> list[Document]` (same case directly or through an order, visible,
  not archived; else 400 `bad_document_ref`); `create_all(...)` (kind `attachment`, group `internal`).
- `services/custody.py` (extended): `REASONS` per decision 2; `move_custody(..., pending_action=NONE,
  due_date=None, request_id=None)`; `controls_custody(session, user, custody) -> bool` (decision 3);
  `hand_over(session, actor, user, case, *, to_office, to_user, pending_action, due_date, note_body,
  note_visibility, files, document_refs, scanner, store)` (decision 4; writes the note through
  `notes.add_note(kind=HAND_OVER)` after the move, so the note's `custody_leg_id` is the new leg);
  `set_action(...)` (decision 5); `return_from_request(session, actor, case, request, reason)` (decision 6);
  `card(session, user, case)` and `history(session, user, case, limit, offset)`; `held(session, user, scope,
  overdue, limit, offset)` (cases held by the caller — holder user, or the caller's office with no user — or,
  with `scope=office`, by any office of the caller's root; filtered by `visible_case_condition`; ordered by due
  date then `since`).
- `services/requests.py` (new): `send`, `add_message`, `answer`, `withdraw`, `assign`, `change_due`, `get`,
  `list_for_case`, `inbox(box=received|sent, status)`, `request_out`. Rules of decisions 6–11; each under the
  locks of decision 23; each writes its audit row and event; `send` and `answer` call `stages.set_stage` when
  `stage` is given (needs `stages.set`, else 403 before anything is written).
- `services/stages.py` (new): `set_stage(session, actor, user, case, *, stage, response_mode, note)`,
  `current(session, case)`, `history_with_gaps(session, user, case)`, `catalogue(session)`.
- `services/notes.py` (new): `add_note(session, actor, user, case, *, kind, body, visibility, supersedes, files,
  doc_types, document_refs, scanner, store, _allow_hand_over=False)`; `list_for_case(session, user, case, kind,
  include_superseded=True, limit, offset)` (ordered by `seq_no`); `get(session, user, ref)`; `note_out`
  (attachments filtered by `document_visible_condition`, `superseded_by`, author snapshot, custody leg
  `seq_no`); `visible_count`.
- `services/visibility.py` (extended): `note_visible_condition(session, user)`, `can_view_note`;
  `request_visible_condition(session, user)`, `can_view_request`. In SQL, as every other rule.
- `services/case_detail.py`: decision 22; `WORKFLOW_EVENTS` (`request_sent`, `request_answered`,
  `request_withdrawn`, `stage_set`) joined to the timeline for everyone who sees the case; `note_added` through
  `note_visible_condition`.
- `services/alerts.py`, `alert_rules.py`, `recipients.py`: decision 21 (`HANDLED_EVENTS` + the four sources;
  `Resolver.for_request_reply(req)`; `render` for `workflow`).
- `services/workflow_codes.py` (or in `stages.py`): `codes(session)` — active note kinds (with
  `selectable`), request kinds with their default pending action, pending actions, stages with phase, response
  modes, custody reasons with labels.
- Settings (`.env.example`): `ATTACHMENTS_MAX_FILES=5`, `NOTE_MAX_CHARS=20000`.

## API
New router `api/routers/workflow.py`. `{ref}` accepts a case id, CNR or dash-form `ref_no`; `{req}` and `{note}`
accept an id or dash-form `ref_no`. Every case-scoped endpoint first applies `require_visible` (404 "no such
case"); `read` = `cases.view_scope` or `cases.view_all`. Errors use the `{code, message}` shape.

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /workflow/codes` | `read` | — | note kinds, request kinds (+ default action), pending actions, stages (+ phase), response modes, custody reasons | Labels from the `ref_*` tables. |
| `GET /cases/{ref}/custody` | `read` | `limit`, `offset` | `{card, legs: [{seq_no, holder_office, holder_user, reason, pending_action, due_date, request_ref_no?, started_at, actor_name}], total}` | Case visible; `request_ref_no` only when the request is visible. |
| `POST /cases/{ref}/custody/hand-over` | `custody.move` | multipart: `to_office` (code), `to_user?` (id), `pending_action?`, `due_date?`, `note_body`, `note_visibility`, `files[]`, `file_doc_types[]`, `document_refs[]` | `{card, leg, note}` 201 | Decisions 3, 4, 17; 409 `not_owned`, `unchanged`; 403 `not_in_control`; 400 `target_out_of_scope`. |
| `PUT /cases/{ref}/custody/action` | `custody.move` | `{pending_action, due_date?}` | `{card, leg}` | Decision 5; 409 `unchanged`. |
| `GET /custody/held` | `read` | `scope=me|office`, `overdue?`, `limit`, `offset` | `{items: [{case summary, card}], total}` | Visible cases only; `scope=office` = the caller's root. |
| `GET /cases/{ref}/requests` | `read` | `status?` | `{items: [request summary], total}` | `request_visible_condition`. |
| `POST /cases/{ref}/requests` | `requests.send` | multipart: `kind`, `to_office`, `to_user?`, `subject`, `body?`, `due_date?`, `with_custody` (default true), `pending_action?`, `stage?`, `attachment_visibility` (`case_scope` default / `counsel_shared`), `files[]`, `file_doc_types[]`, `document_refs[]` | request detail 201 (+ `custody_moved`) | Decisions 6, 11, 12; working basis; 409 `not_owned`, `custody_out_on_request`; 403 `not_in_control` (with custody). |
| `GET /requests` | `requests.answer` (box `received`) or `requests.send` (box `sent`) | `box`, `status?`, `overdue?`, `limit`, `offset` | `{items, total}` | Received: addressed to the caller or (non-personal) the caller's root; sent: sent by the caller or the caller's root. Always ANDed with `request_visible_condition`. |
| `GET /requests/{req}` | `read` | — | detail: header, messages, attachments (visible ones), `can_answer`, `can_withdraw`, `can_assign` | 404 when not visible. |
| `POST /requests/{req}/messages` | `requests.send` or `requests.answer` (by side) | multipart: `body`, files, refs | message 201 | Decision 7; 409 `not_open`. |
| `POST /requests/{req}/answer` | `requests.answer` | multipart: `body`, `stage?`, files, refs | detail (+ `custody_moved`) | Decisions 6, 9; 409 `not_open`. |
| `POST /requests/{req}/withdraw` | `requests.send` | `{reason}` (3–500) | detail (+ `custody_moved`) | Sending side; 409 `not_open`. |
| `POST /requests/{req}/assign` | `requests.answer` | `{to_user}` | detail | Decision 8; 409 `not_open`, 400 `user_out_of_scope`. |
| `PATCH /requests/{req}` | `requests.send` | `{due_date}` | detail | Sending side, open only; audited. |
| `GET /cases/{ref}/stages` | `read` | — | `{current, history: [...], gaps: [codes]}` | Case visible. |
| `POST /cases/{ref}/stages` | `stages.set` | `{stage, response_mode?, note?}` | `{current}` 201 | Decision 12; working basis; 409 `not_owned`, `unchanged`. |
| `GET /cases/{ref}/notes` | `read` | `kind?`, `include_superseded` (default true), `limit` (50, max 200), `offset` | `{items: [note], total}` | `note_visible_condition`; ordered by `seq_no`. |
| `POST /cases/{ref}/notes` | `notes.add` | multipart: `kind`, `body`, `visibility`, `supersedes?` (note ref), `files[]`, `file_doc_types[]`, `document_refs[]` | note 201 | Decisions 13–17; 400 `bad_field` (kind `hand_over`, visibility mismatch on correction); 403 `not_author`; 409 `not_owned`, `already_superseded`; 413/415/422/503 as uploads. |
| `GET /notes/{note}` | `read` | — | note | 404 when not visible. |

Note shape: `{id, ref_no, seq_no, kind, kind_label, body, visibility, author: {name, designation, office_code,
role}, created_at, custody_leg_seq_no, supersedes: {ref_no, seq_no}?, superseded_by: {ref_no, seq_no}?,
attachments: [{ref_no, original_filename, doc_type, mime, size_bytes, linked}]}`.
Changed: `GET /cases/{ref}` (decision 22); `GET /cases/{ref}/timeline` (decision 19); `PATCH /documents/{doc}`
and `POST /documents/{doc}/archive` (409 for attachments); the upload size guard (decision 18).

## Jobs
No new job. The existing `aslms.alerts_scan_events` (every 5 minutes) handles the four new event sources
(decision 21); `aslms.alerts_sweep_dates` already raises `request_due` from open requests. Text extraction of
attachment PDFs/DOCX goes through the existing `aslms.extract_document_text` dispatch after commit.

## Tests
Unit (`tests/unit/`):
- `test_workflow_rules.py`: default pending action per request kind; custody reason set equals the CHECK list;
  stage gaps (main phase only, by sort order; none for appeal/contempt current stage); note kind selectability
  (`hand_over` not selectable, `correction` retired).

Database (`tests/db/`, using `world.py` and the scripted scanner/store fakes of documents-uploads):
- `test_custody_workflow.py`: hand-over within the department writes leg + `hand_over` note in one transaction
  (note's `custody_leg_id` = new leg); hand-over outside the department → `target_out_of_scope`; non-holder
  officer → 403; dept officer in the department office cannot move an unallotted department-held case; action
  set appends `action_set` leg; unclaimed case → `not_owned`; ownership move clears `custody.request_id`.
- `test_requests.py`: send with custody moves it (reason, due date, pending action, `moves_custody`); answer
  returns it to the previous leg with `examine`; withdraw restores the previous pending action; sub-request
  inside a directorate returns the file to the directorate still under the parent request; parallel request
  without custody moves nothing; second request with custody while the first is out → `custody_out_on_request`;
  answer after an ownership move records the answer and leaves custody (`custody_moved: false`); assign moves
  custody to the assignee; due change updates custody due date; answered / withdrawn requests refuse messages,
  answers, withdraw (409); CHECKs reject inconsistent status rows; `request_messages` and
  `request_attachments` refuse UPDATE and DELETE (trigger).
- `test_request_visibility.py`: sender side, receiving side, addressee, owning department nodal officer and
  allotted officer see the request; another directorate of the same department and standing counsel (not a
  side) do not, but see the timeline line without subject; a referral reviewer sees a request only once
  assigned; State-wide reader sees all.
- `test_stages.py`: any stage may be set; `unchanged` 409; response mode carried forward; a referral reviewer
  with a request basis may set a stage; `stage` given with send / answer is recorded in the same transaction
  and refused (nothing written) without `stages.set`.
- `test_notes.py`: seq_no increments per case under concurrency (two sessions); author snapshot frozen
  (renaming the user later leaves the note unchanged); UPDATE/DELETE on `case_notes` and
  `case_note_attachments` refused; correction keeps kind and visibility, a different visibility → 400; second
  correction of the same note → 409 (service and index); only author or department nodal officer may correct;
  plain note with kind `hand_over` → 400; a working basis is required (State-wide reader cannot write).
- `test_note_visibility.py`: the matrix of the three visibilities × dept officer, directorate user of another
  unit, standing counsel, referral reviewer, State oversight, author; switching off `notes.view_private_office`
  for a type hides private notes except the author's own; standing counsel without
  `notes.view_counsel_shared` see no counsel-shared notes; timeline `note_added` follows the same rule.
- `test_note_attachments.py`: files become internal `attachment` documents with the note's visibility and
  `sourcetrace_status = not_applicable`; one infected file among three refuses the note, writes no document
  row, keeps the rejection audit row; more than `ATTACHMENTS_MAX_FILES` → 400; linked document of another case →
  400; a linked private document is listed only to readers who can see it; `PATCH` visibility and archive of an
  attachment → 409; attachments absent from the Documents tab, present in content search under the rule.
- `test_workflow_alerts.py`: `request_sent` raises one `workflow` alert to the addressee (not to the sender);
  `request_answered` alerts the sender; hand-over alerts the new holder; `custody_moved` with `request_sent`
  raises nothing; rendered text contains no subject or note body; existing `request_due` alert closes on answer.
- `test_api_workflow.py`: each endpoint's function check (403), invisible case (404), happy path shapes,
  multipart size guard on the new paths (413), audit rows written with no note or message text in `after`.
- Migration test: 0008 upgrade → downgrade → upgrade; `test_schema_metadata.py` in step with `schema.md`.

## Verification
1. `docker compose run --rm api alembic upgrade head` → head `0008_workflow`; `docker compose run --rm api aslms
   seed` reports `ref_note_kind` +2, `ref_event_type` +1, `ref_alert_kind` +1; `correction` inactive.
2. `ruff check` clean; `pytest -q` green (count reported in the cycle report).
3. With Compose up, on a claimed case of the loaded data (claim one with a dept admin of the `world`-style dev
   accounts if none is claimed): allot to a directorate → custody card shows the directorate; send a
   `parawise_comments` request from the department to that directorate with `stage=parawise_comments_sought`
   and a due date → `GET /cases/{ref}/custody` shows a `request_sent` leg with the due date and pending action
   `reply`; `GET /requests?box=received` as the directorate user lists it; answer with a PDF attachment and
   `stage=parawise_comments_received` → custody back with pending action `examine`; `GET /cases/{ref}/stages`
   shows both stages and the gaps before them.
4. Add a `private_to_office` note as the department officer and a `counsel_shared` note; as standing counsel
   `GET /cases/{ref}/notes` returns only the counsel-shared one; correct the first note → both listed,
   `superseded_by` set; a second correction of the same note → 409.
5. Hand-over to a section officer with a note → `hand_over` note at the next `seq_no`, `workflow` alert for the
   officer after the next `aslms alerts run`.
6. `psql`: `UPDATE case_notes SET body='x'` and `DELETE FROM request_messages` fail with the append-only error;
   `SELECT count(*) FROM documents WHERE kind='attachment' AND doc_group<>'internal'` = 0; `audit_log` rows for
   each action, none containing the note text.

## Open questions
None. Points the owner is asked to check at approval (decisions taken, reversible): hand-over limited to the
owning department's offices, or to the request's receiving office while a request is out (4); `workflow`
alert kind added beyond the plan's list (21); the plan's seven note kinds plus the kept `counsel_advice` and
`file_noting`, `correction` retired (13); request attachments limited to `case_scope` / `counsel_shared` (11);
up to five attachment files per note or message (17).
