# Design: Portal — custody (sending the file, recall, tracking), stages, notes and drafts, uploads, alerts and calendar

```
slug: portal-workflow
status: approved
author: architect
date: 2026-10-12
approved_by: owner (nayanlhuzuri) on 2026-10-13
```

> **Owner's decision at approval (13 Oct 2026): the Files and the Alerts & calendar screens are split out** into a new backlog row `portal-files-alerts` (row 55). In this row do **not** build decision 16 (the `/alerts` screen), decision 17 (the hearing calendar `/alerts/calendar`), decision 18 (the `/files/*` screens), the 'Files' and 'Alerts & calendar' navigation entries, the header bell link and the dashboard links of decision 3. Everything on the case page stays here: Send file, Recall, the Custody and stage tab, Set stage, notes, drafts and corrections, uploads and document management, the case Alerts tab (decision 15) and the timeline lines; the seven API additions (decision 20) and the relay header (decision 23) stay too, including `alert_kinds` and `SentItemOut.visible` for row 55 to use. Decision 6 changes until row 55 exists: when the sender no longer sees the case after a move, the portal goes to the dashboard with the same notice instead of `/files/sent`.

## Context
Backlog row 13: "Portal: custody (sending the file, recall, tracking), stages, notes and drafts, uploads, alerts and
calendar". The plan, §5.7 (Custody and Workflow): "Shows, for every case, which office and officer currently hold it
and what action is pending, similar to file movement in eOffice"; the custody card (holder office and officer,
pending action, since when, due date); links to notes trail, alerts, dashboard, reports (pending actions by office).
§5.8 (Case Notes Trail): note kinds, the author's name, designation and office at the time, no edits or deletes,
corrections linked to the original, attachments, visibility per note. §5.6 (Orders and Case Documents): uploads with
type, date, description, uploader and office; PDF, Word and images; court filings and internal documents; visibility
per document; "marked with whether it is available to the Case Assistant". §5.5 (Alerts and Hearing Calendar):
"Calendar of upcoming hearings for the user's cases, with critical (within 48 hours) and this-week highlights";
"alerts go to the current custody holder". §5.12 (Notifications: in-app and e-mail). §5.3: the case page tab
"Custody, and the notes and files trail". §8.1: uploads restricted and scanned before storage. Annexure B: "Case
detail" ("current custody and pending action", a "Hand over" button) and "Case documents and upload" ("with the
upload panel alongside").

**Binding: the owner's rules of 7 Oct 2026** (decisions log, "Custody and file movement — owner's rules", built by
`custody-workflow`): custody is accountability; sending the file to any officer (by membership) with a remark,
pending action and optional due date replaces the plan's "requests between offices" and "hand-over" (an approved
deviation of the plan, recorded in `custody-workflow`); the chain is open as in eOffice; recall by the owning
department (`custody.recall`); tracking (`custody.track`); ownership never moves with custody; no deletion once
claimed except the current holder's draft notes, which become permanent when the file is sent on or recalled.

In place today (used, not rebuilt): every endpoint this item draws over. `custody-workflow`: `GET /workflow/codes`,
`GET /cases/{ref}/custody`, `GET /custody/recipients`, `/custody/summary`, `/custody/held`, `/custody/sent`,
`POST /cases/{ref}/custody/send | recall`, `GET | POST /cases/{ref}/stages`, `GET | POST /cases/{ref}/notes`,
`GET /cases/{ref}/notes/drafts`, `PATCH | DELETE /notes/drafts/{draft}`, `GET /notes/{note}`; the custody card on
`GET /cases/{ref}` with `can_send` and `can_recall`; `counts.notes` and `counts.my_drafts`. `documents-uploads`:
`POST /cases/{ref}/documents` (type by content, ClamAV before storage, 20 MB), `GET /documents/types`,
`PATCH /documents/{doc}` (visibility), `POST /documents/{doc}/archive`, `can_manage` on each document.
`alerts-notifications`: `GET /alerts`, `/alerts/counts`, `/alerts/{alr}`, `POST /alerts/{alr}/acknowledge | done`,
`POST /alerts/read`, `GET /cases/{ref}/alerts`, `GET /calendar`; the preferences are already on My profile
(portal-shell). The portal: the case page and its tabs, `CaseLink`, the department and people hooks, `ConfirmDialog`,
the relay (which streams multipart bodies), `messages.ts`, `routes.ts` with the unbuilt "Alerts & calendar" entry,
the header bell (links to `/#alerts` today). Every rule (functions, the holder, control of an office-held leg,
recall in the owning department, drafts, visibility of notes, documents and alerts, the scan) is already enforced by
the API; this item draws screens over it and adds seven small read-only API changes (decision 20).

Not covered: the Case Assistant and "copy an answer into a note" (row 14); next dates read from orders and their
review queue (rows 26, 37); OCR (row 23); the reports screen including "pending actions by office" (row 39, which
reads the same custody columns); advisory custody findings (row 32); the reverse proxy body limit and a live EICAR
test (row 24); SMS (rows 27, 34). Notification preferences are already on My profile and are not redrawn.

## Decisions
1. **One item, with a split offered.** The row is built as one cycle: the case-page workflow (custody card actions,
   the custody tab, stages, notes and drafts, uploads and document actions, the case alerts tab) and two new screens
   (Files; Alerts and calendar). If the owner prefers a smaller cycle, the two screens (decisions 16-18) can move to
   a new row at approval without changing anything else in this note, as the mapping screens did in row 12.
2. **Routes.** Case tabs `/cases/[ref]/custody` ("Custody and stage") after Overview and `/cases/[ref]/alerts`
   ("Alerts") after Notes; the existing Notes and Documents tabs gain their writing parts. New screens:
   `/files/{mine|offices|department|sent}` (`/files` opens the first tab the login may read) and
   `/alerts` (the list) with `/alerts/calendar`. Filters live in the query string as in row 12. Alternative: dialogs
   only on the Overview (the movement record and the stage history need a page of their own).
3. **Navigation.** "Alerts & calendar" gets `built: true` (shown with `cases.view_scope` or `cases.view_all`, as
   today's entry). A new entry "Files" after Search, shown with `cases.view_scope` (anyone can be sent a file:
   standing counsel included; State-wide types cannot be targets and see empty lists). The header bell links to
   `/alerts` instead of `/#alerts`; the dashboard's "My alerts" heading and the personal "Files" tile link to
   `/alerts` and `/files/mine`. Breadcrumbs for the new segments.
4. **What a page offers comes from the server** (the rule of row 12, decision 8). Buttons show only when the API says
   the caller may act: Send and Recall from the custody card's `can_send` / `can_recall` (built); writing a note, the
   upload panel and Set stage from a new `workflow` block on `GET /cases/{ref}` (decision 20a); Correct from a new
   `can_correct` on each note (20b); Acknowledge / Done from a new `can_act` on each alert (20d); Change visibility
   and Archive from each document's `can_manage` (built). The portal never decides from `/me` functions alone
   whether the caller is the holder, controls an office-held leg, works on the case or may correct a note: those
   rules live once, in Python. The API still decides every call.
5. **Send file** (Annexure B's "Hand over"; the owner replaced hand-over with sending). On the custody card and the
   custody tab, shown when `can_send`. A dialog, in order:
   - department: every active department (`GET /custody/recipients`, the Advocate General's office included);
   - officer: that department's eligible memberships (`?department=`, with the `q` box and paging of 50), each shown
     as name, designation, office code and name, user type — one row per membership, so a person in two offices
     appears twice and the sender picks the office too (owner's rule "picks the person and the membership");
   - pending action: the `sendable` codes of `/workflow/codes` (required, nothing pre-selected);
   - due date: optional, the date input bounded today (IST) to today + 365 days as a hint (the API decides,
     `bad_due_date`);
   - remark: required, 3-2,000 characters with a counter;
   - stage: optional, offered only when `workflow.set_stage` is true (the API refuses a stage without `stages.set`
     before anything is written).
   A summary line before confirming: "Send to <name, designation, office> — <pending action> — due <date>". When
   `counts.my_drafts` > 0 the dialog says "Your n draft notes become permanent notes of the case when you send" (the
   owner's rule; there is no way to keep them as drafts). Sending never claims, allots or changes the owner, and the
   dialog says nothing that suggests it does.
6. **After a move.** The response's `finalised_notes` are listed in the success notice ("Made permanent: NOTE/…").
   When the response's `card` is `null` the sender no longer sees the case (the custody basis left with the file,
   custody-workflow decision 9): the portal goes to `/files/sent` with the notice "File sent to <name>. You no
   longer hold this case." and drops the case's cached queries; it never shows a 404 page for a case the user has
   just sent. Otherwise the case page stays and re-reads (decision 22).
7. **Recall**, shown when `can_recall`: a dialog with the current holder named, a required remark (3-2,000), and
   "The holder's draft notes become permanent notes; the file comes to you with 'Examine' pending." The recaller
   then sends it on with Send file. There is no Recall anywhere else (the function is granted per membership by the
   department admin, and the flag already says whether it applies to this case's owning department).
8. **The custody tab** (`/cases/[ref]/custody`, read with case reading): the custody card with Send and Recall; the
   movement record from `GET /cases/{ref}/custody` (seq no, holder office and officer with designation at the time,
   reason label, pending action, due date, started at, sent by; the remark only when the API returns it — custody-
   workflow decision 11 hides it from readers without a working basis), oldest first, paged by 50; the stage block
   from `GET /cases/{ref}/stages`: the current stage with phase, response mode, office, set by and when, its note;
   the history newest first; the gaps as "Not recorded: …" (guided, not enforced); and Set stage. A case without
   custody (unclaimed) shows "Custody begins when a department claims the case." and no actions.
9. **Set stage**, shown when `workflow.set_stage`: stage (the `/workflow/codes` stages grouped by phase in
   `sort_order`, the current one marked), response mode (pre-filled with the current one, as the API carries it
   forward), optional note (≤ 2,000). 409 `unchanged` shows its message. The Overview's Stage card gains the same
   button and a link to the custody tab.
10. **Writing notes** (Notes tab), shown when `workflow.note_mode` is not `null`; the composer says before writing
    which kind of note it will make, from the server's `note_mode`:
    - `draft` (the caller's membership holds the file): "You hold this file. Your notes are drafts, visible only to
      you, until the file is sent on or recalled; then they become permanent notes of the case." Drafts take links
      to documents of the case only (decision 12);
    - `permanent`: "This note becomes part of the case record at once and cannot be edited or deleted. A mistake is
      corrected by a new note." It may carry up to `limits.attachments_max_files` new files (each with an internal
      document type, default Correspondence, from `/documents/types` where the group is internal) and links.
    Fields: kind (the `selectable` kinds of `/workflow/codes`, required), body (1 to `limits.note_max_chars`, with a
    counter), visibility (required, nothing pre-selected: whole case, shared with counsel, private to the office —
    each with one line saying who sees it), links (a picker over the case's documents the caller can open, not
    archived, from `GET /cases/{ref}/documents`; "A link never widens who can see the document"). The form is sent as
    `multipart/form-data` exactly as the API takes it; the answer's `draft` flag decides where it appears (the trail
    or the drafts panel). A line under the form: "Notes and their attachments are internal and are never sent to the
    Case Assistant."
11. **Corrections.** "Correct" on a note shows when `can_correct`; it opens the composer with "Corrects NOTE/…",
    the kind and visibility of the original shown and fixed (the API keeps both and refuses another visibility).
    409 `already_superseded` (someone corrected it first) shows its message and re-reads the trail. There is no Edit
    or Delete on any permanent note.
12. **Drafts panel** (Notes tab, above the trail, only when `note_mode` is `draft` or `counts.my_drafts` > 0):
    the caller's drafts from `GET /cases/{ref}/notes/drafts` with kind, body, visibility, "corrects NOTE/…", linked
    documents, created and updated times; Edit (the same composer, `PATCH /notes/drafts/{draft}` with only the
    changed fields; links resent as document ids) and Delete (confirmation; "the only delete in a case's records").
    No "make permanent now" button (owner's rule). "Attach a new file" in a draft opens the upload dialog of
    decision 13 for the case, then links the new document to the draft, with the line "The file is uploaded to the
    case now, with its own visibility; the note stays a draft." 409 `draft_finalised` (the file moved meanwhile)
    shows "This draft became a permanent note when the file moved." and re-reads drafts and the trail; 409
    `too_many_drafts` shows its message.
13. **Upload panel** (Documents tab, "alongside" as in Annexure B; shown when `workflow.upload`): file (the input's
    `accept` from `upload.extensions`), document type (the uploadable types of `/documents/types`), group asked only
    when `group_choosable`, document date (required, not in the future, not before 1950-01-01), description (3-500),
    visibility (required, nothing pre-selected). Before sending, the portal checks the extension and the size
    against `upload.extensions` and `upload.max_bytes` and says so at once; the API still decides by content. While
    the request runs the button reads "Uploading and checking for viruses…" (no progress bar: `fetch` gives none,
    and a 20 MB upload with the scan takes seconds). The panel says which uploads reach the Case Assistant: "Court
    filings visible to the whole case or shared with counsel are sent to the Case Assistant. Internal documents and
    files private to your office never are." (documents-uploads decision 9). Answers in words: `type_not_allowed`,
    `too_large`, `infected` ("refused: a virus was found; nothing was stored"), `scanner_unavailable` ("the virus
    scanner is not available; try again in a few minutes"), `duplicate` (with a link to the existing document by its
    `existing_ref_no`), `not_working_on_case`, `bad_field`. Upload is not offered anywhere else (search results,
    inbox).
14. **Document actions** on the Documents tab rows where `can_manage` and not archived: Change visibility (the three
    values, the current one marked; 409 `already_ingested` explains that a document already in the Case Assistant
    cannot be made private) and Archive (required reason 3-500; "Archived documents stay readable under the same
    visibility; there is no unarchive and no delete"). Court records never show them (the API's `can_manage` is false).
15. **Case alerts tab** (`/cases/[ref]/alerts`): `GET /cases/{ref}/alerts` with status filter (open and
    acknowledged by default, or all), severity badge, kind, title, body, due, acknowledged by and when; Acknowledge
    (status open) and Done (open or acknowledged) with an optional note (≤ 500) when `can_act`. For a reader the API
    gives an empty list (not working on the case), the tab says "Alerts of this case are shown to the offices working
    on it." The tab has no count badge (the overview's `counts` has none; no API change for it).
16. **Alerts screen** (`/alerts`): the caller's own alerts (`GET /alerts`), newest first, filters status (open and
    acknowledged / all), kind (labels from 20f), severity, unread only, paged by 50; counts from `/alerts/counts`
    above the list. Each row: severity badge (critical / high / normal from the API), kind label, title, body, due,
    the case as a `CaseLink` (or, for an admin ticket notice, a link to `/admin/tickets/<ref>`; for an ownership
    notice about a case the reader can no longer open, the case number as text), notified and read times,
    acknowledged by. Reading: a row is marked read when the user presses "Mark read", "Mark all read"
    (`{all: true}`), or follows the row's link (marked first, then navigated); opening the list marks nothing, so the
    bell's count does not drop unseen. Acknowledge / Done as in decision 15, by `can_act`. The bell's count and the
    list are re-read after each action.
17. **Hearing calendar** (`/alerts/calendar`, plan §5.5): `GET /calendar`. A month view (a CSS grid of the weeks
    of the chosen month, each day showing its number of hearings and a "critical" mark from the API's flags) and,
    below it, the agenda: hearings grouped by date with case link, court, item, purpose, source ("cause list",
    "court records", "next date") and the API's `critical` ("Within 48 h") and `this_week` badges — never computed
    in the browser. Ranges: "Next 7 days" (default, the API's default), the current month, previous / next month;
    a range longer than 62 days is never requested (a month is at most 31 days). State-wide readers choose a
    department first (the API needs `office`; without it the page says "Choose a department to see its hearings")
    from the active departments. Day cells link to their agenda anchor; the agenda is the accessible version.
    Alternative: a calendar library (a dependency and CSP surface for a grid of at most 42 cells).
18. **Files** (`/files`, the eOffice view of custody-workflow decision 24): tabs
    - "With me" (`/custody/held?scope=me`): the case link, pending action, since, due date with the API's overdue
      badge, sent by, remark; the "Overdue only" filter;
    - "My offices" (`scope=office`): the same with the holder office and officer;
    - "Department files" (`scope=owned`), shown with `custody.track`: the summary of `GET /custody/summary` at the
      top (per tracked department: held, due soon, overdue, then by holder department and by holder office /
      officer, counts only), the list with the holder department filter (`holder_department`) and "Overdue only";
    - "Sent" (`/custody/sent`): the legs the caller wrote (sends and recalls) with the case summary, reason, the
      holder sent to, pending action, due date and the caller's own remark; the case is a link only when the item's new
      `visible` flag is true (decision 20g; a case the sender no longer sees is shown as text, never a link to a 404).
    Lists are ordered as the API orders them (held: due date, then since; sent: newest first) and paged by 50. No action buttons on these
    lists: sending and recalling happen on the case page, where the card's flags are current.
19. **Timeline lines** (`src/lib/timeline.ts`, the payload keys custody-workflow decision 20 names): `custody_moved`
    (reason label, holder office code, holder name and designation, pending action, due date — the payload never
    carries the remark), `stage_set` (stage label, office), `note_added` (kind, `ref_no`, "from a draft" when
    `finalised`), `document_uploaded` (document type, office), `alert_raised` (kind). Unknown types keep the label
    only; payloads are never printed raw.
20. **Seven small API changes, no schema change** (each read-only, each with tests):
    (a) `GET /cases/{ref}` gains `workflow: {note_mode: "draft" | "permanent" | null, upload: bool, set_stage: bool}`
    for the caller, computed by the same checks the writes run (`acting_member_for_case` with the function, the
    claim for notes and stages, the holder test for drafts), without locking or writing.
    (b) `NoteOut` gains `can_correct: bool` (not superseded, the caller may write a note on the case, and
    `_may_correct` passes), computed once per list for the writer and per note for the author rule.
    (c) `DraftDocumentOut` gains `id`, `doc_type`, `mime` (an order PDF linked to a draft has no `ref_no`, so
    the draft could not be edited without losing the link).
    (d) `AlertItemOut` gains `can_act: bool`: on the caller's own list, the status is open or acknowledged and the
    caller holds `alerts.acknowledge` (they are a recipient by construction); on the case tab and `GET /alerts/{alr}`,
    additionally the existing `_may_act_on` rule passes (a State-wide reader sees a case's alerts but may not act on
    them unless notified).
    (e) `GET /workflow/codes` gains `limits: {note_max_chars, attachments_max_files, note_drafts_max}`;
    `GET /documents/types` gains `upload: {max_bytes, extensions}` (from `UPLOAD_MAX_BYTES` and the permitted-type
    table of `services/filetypes.py`), so the portal's pre-checks follow the server's settings instead of copies.
    (f) `GET /reference/labels` gains `alert_kinds: [{code, label}]` (active `ref_alert_kind` rows) for the alert
    filter.
    (g) `SentItemOut` (`GET /custody/sent`) gains `visible: bool`: whether the caller can open the case now (one
    `visible_case_condition` query for the page), since the sender usually loses sight of a case they sent on.
    Alternatives: the portal combining `/me` functions with the card (the holder, office-control, working-basis,
    claim and correction rules would be written twice and drift); hard-coding 20 MB and the extensions (the owner may
    change `UPLOAD_MAX_BYTES`).
21. **Errors in words.** Each code the API gives on these calls has a message in `messages.ts`: custody `not_owned`,
    `unchanged`, `not_in_control`, `bad_target`, `bad_due_date`, `not_owner_department`, `function_missing`;
    notes `drafts_take_links_only`, `not_author`, `already_superseded`, `too_many_drafts`, `draft_finalised`,
    `bad_document_ref`, `not_working_on_case`; uploads and documents as decisions 13-14 plus
    `attachment_follows_note`; alerts `not_open`, `closed`; plain 400 / 403 / 404 messages as given; an unknown code
    falls back to the server's message. 404 on a case page keeps the one neutral message of row 12.
22. **Freshness.** After any write the affected queries are invalidated: the case overview (card, stage, counts),
    custody tab, notes and drafts, documents, timeline, case alerts, `/alerts` and `/alerts/counts`, the Files lists
    and summary, the dashboard blocks. No polling beyond the bell's existing two minutes; refetch on window focus
    stays on.
23. **Uploads through the relay.** The relay already streams request bodies; it gains `content-length` in its
    forwarded request headers so the API's 413 guard (`upload_size_guard`) refuses an oversized body before reading
    it, as it does for direct calls (browsers send the length for `FormData`). A relay test proves the header and the
    multipart boundary pass. If the Node runtime refuses to forward the header with a streamed body, the developer
    records it as a deviation; the API still counts the bytes it reads. The `proxy.ts` gate does not match `/api/*`,
    so Next's proxy body buffering does not apply. The reverse proxy limit stays with row 24.
24. **Nothing on these screens reaches SourceTrace.** Notes, drafts and attachments are internal; the upload panel
    only states the existing rule of documents-uploads decision 9. No screen offers "send to the Case Assistant".
25. **Look, language and checks as before.** CSS Modules and the shell's tokens, the UI kit (extended with
    `FileField`, `CharCounter`, `SeverityBadge`), WCAG 2.1 AA (dialogs trap focus, the month grid is a table with
    headers, the agenda is the accessible list), strings in `messages.ts`, IST dates, monospace references, no new
    npm dependency. Pages are checked in the Compose `web` service (`portal_smoke.py` discovers the nine new pages).

No deviation from the plan beyond the owner's custody rules already approved in `custody-workflow` ("Send file"
replaces the mock-up's "Hand over"). Points for the owner to confirm at approval (decisions taken, reversible): the
split offer (1); the new "Files" entry and its four tabs (3, 18); visibility is never pre-selected on notes or
uploads (10, 13); alerts are marked read only by an explicit action or by following the alert (16); the seven API
additions and the relay header (20, 23).

## Data
No table, column, constraint, reference code, `Permission` or setting is added; no migration. `docs/schema/schema.md`
is unchanged. The values of decision 20 are computed on read from existing rows (`custody`, `case_ownership`,
`user_memberships`, `case_notes`, `alerts`, `notifications`, `ref_alert_kind`) and existing settings
(`UPLOAD_MAX_BYTES`, `ATTACHMENTS_MAX_FILES`, `NOTE_MAX_CHARS`, `NOTE_DRAFTS_MAX`). The portal stores nothing.

## Services
Backend (Python), read-only additions:
- `services/workflow_actions.py` (new): `available(session, user, case) -> {note_mode, upload, set_stage}`.
  `note_mode`: `None` unless the case has an active primary owner and `visibility.acting_member_for_case(…,
  NOTES_ADD)` returns a member; `"draft"` when that member's membership is `custody.holder_membership_id`, else
  `"permanent"` (the same choice `notes.add_note` makes). `upload`: `acting_member_for_case(…, DOCUMENTS_UPLOAD)` is
  not `None` (the rule of `documents.upload`). `set_stage`: owned and `acting_member_for_case(…, STAGES_SET)` is not
  `None`. No lock, no write, no audit (reading).
- `services/case_detail.py`: the overview adds `workflow` from `workflow_actions.available`.
- `services/notes.py`: `note_out(…, writer=…)` adds `can_correct`; `list_for_case` and `get` compute the writer once
  (owned and `acting_member_for_case(NOTES_ADD)`), then per note `superseded_by is None and _may_correct(...)`;
  `draft_out` documents add `id`, `doc_type`, `mime`.
- `services/alerts.py`: `may_act(session, user, alert) -> bool` (`_may_act_on` without raising, the function and the
  status); `list_for_user` items add `can_act` from the function and status; `alerts_for_case` and the detail add it
  from `may_act`.
- `services/workflow_codes.py::codes(session, settings)`: adds `limits`. `services/documents.py::upload_types`
  route adds `upload` (`max_bytes`, the extensions of the permitted `FileType`s). `services/reference.py::labels`:
  adds `alert_kinds`.
- `services/custody.py::sent`: each item adds `visible` (the page's case ids filtered once by
  `visibility.visible_case_condition`).
- `api/schemas.py`: `CaseWorkflowActionsOut`, `CaseDetailOut.workflow`, `NoteOut.can_correct`, `DraftDocumentOut`
  (+ `id`, `doc_type`, `mime`), `AlertItemOut.can_act`, `WorkflowLimitsOut`, `WorkflowCodesOut.limits`,
  `UploadLimitsOut`, `DocumentTypesOut.upload`, `ReferenceLabelsOut.alert_kinds`, `SentItemOut.visible`. `frontend/openapi.json` and
  `schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/server/relay.ts`: `REQUEST_HEADERS` adds `content-length` (decision 23).
- `src/lib/routes.ts` (decisions 2, 3: NAV `alerts` built, `files` entry, `FILES_TABS`, `ALERTS_TABS`, `CASE_TABS`
  + `custody` and `alerts`, `CRUMBS`), `src/lib/timeline.ts` (decision 19), `src/lib/workflow.ts` (new:
  `todayIst()`, `dueDateBounds()`, `checkFile(file, upload)` for the pre-checks, `monthGrid(month)` for the
  calendar), `src/lib/messages.ts` (strings and error codes of decision 21).
- `src/lib/api/hooks.ts`: `useWorkflowCodes()`, `useDocumentTypes()`, `useStages(ref)`, `useCustodyHistory(ref)`,
  `useDrafts(ref, enabled)`, `useAlertCounts()` (shared with the bell).
- `src/components/ui`: `FileField`, `CharCounter`, `SeverityBadge`.
- `src/components/workflow/*`: `SendDialog`, `RecallDialog`, `StageDialog`, `CustodyTab`, `NoteComposer`,
  `DraftsPanel`, `UploadDialog` (panel and dialog share it), `DocumentActions` (visibility, archive), `CaseAlerts`,
  `AlertActions` (acknowledge, done; shared with `/alerts`).
- `src/components/files/*`: `FilesFrame`, `Held` (scope prop), `Sent`, `TrackingSummary`.
- `src/components/alerts/*`: `AlertsFrame`, `AlertList`, `Calendar` (month grid and agenda).
- Changed: `case/Overview.tsx` (Send / Recall on the custody card, Set stage on the stage card, links to the custody
  tab), `case/Notes.tsx` (composer, drafts panel, Correct), `case/Documents.tsx` (upload panel, row actions),
  `case/CaseFrame.tsx` (two tabs), `shell/PortalShell.tsx` (bell → `/alerts`), `dashboard/Dashboard.tsx` (links).
- Pages: `(portal)/cases/[ref]/custody/page.tsx`, `cases/[ref]/alerts/page.tsx`; `(portal)/files/{layout,page}.tsx`,
  `files/mine`, `files/offices`, `files/department`, `files/sent`; `(portal)/alerts/{layout,page}.tsx`,
  `alerts/calendar`.

Audit and events: the portal writes none. Every action it offers is an existing API call that already audits and
emits: `custody.sent`, `custody.recalled`, `stage.set`, `note.added`, `note.finalised`, `note.draft_saved`,
`note.draft_updated`, `note.draft_deleted`, `document.uploaded`, `document.upload_rejected`,
`document.visibility_changed`, `document.archived`, `document.downloaded`, `alert.acknowledged`, `alert.done`
(events `custody_moved`, `stage_set`, `note_added`, `document_uploaded`). The seven API changes are reads and write
nothing.

## API
New or changed (FastAPI):

| Method, path | Function required | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /cases/{ref}` (changed) | `cases.view_scope` or `cases.view_all` (unchanged) | — | + `workflow: {note_mode: "draft" \| "permanent" \| null, upload: bool, set_stage: bool}` | unchanged (404 for an invisible case); flags for the caller only |
| `GET /cases/{ref}/notes`, `GET /notes/{note}`, `POST /cases/{ref}/notes` (permanent answer) (changed) | read (`cases.view_scope` or `cases.view_all`); `notes.add` for the POST (unchanged) | — | each note + `can_correct: bool` | unchanged (`note_visible_condition`) |
| `GET /cases/{ref}/notes/drafts`, `PATCH /notes/drafts/{draft}`, `POST /cases/{ref}/notes` (draft answer) (changed) | `notes.add` (unchanged) | — | `documents[]` + `id`, `doc_type`, `mime` | unchanged (the author only) |
| `GET /alerts`, `GET /cases/{ref}/alerts`, `GET /alerts/{alr}`, `POST /alerts/{alr}/acknowledge \| done` answers (changed) | `cases.view_scope` or `cases.view_all`; `alerts.acknowledge` for the POSTs (unchanged) | — | each item + `can_act: bool` | unchanged |
| `GET /workflow/codes` (changed) | `cases.view_scope` or `cases.view_all` (unchanged) | — | + `limits: {note_max_chars, attachments_max_files, note_drafts_max}` | reference data |
| `GET /documents/types` (changed) | `documents.view` (unchanged) | — | + `upload: {max_bytes, extensions: [str]}` | reference data |
| `GET /reference/labels` (changed) | signed in, first-sign-in steps included (unchanged) | — | + `alert_kinds: [{code, label}]` | reference data |
| `GET /custody/sent` (changed) | `cases.view_scope` or `cases.view_all` (unchanged) | `limit`, `offset` | each item + `visible: bool` | unchanged (the legs the caller wrote); `visible` per the case rule |

Used as they are: `GET /cases/{ref}/custody` (case reading; remark per custody-workflow decision 11);
`GET /custody/recipients` (`cases.view_scope`); `POST /cases/{ref}/custody/send` (`cases.view_scope` gate; the holder,
or `custody.move` with control of an office-held leg); `POST /cases/{ref}/custody/recall` (`custody.recall` in a
membership of the owning department); `GET /custody/summary` (`custody.track`); `GET /custody/held` (case reading;
`scope=owned` needs `custody.track` there); `GET /cases/{ref}/stages` (case
reading); `POST /cases/{ref}/stages` (`stages.set`); `POST /cases/{ref}/notes` (`notes.add`);
`DELETE /notes/drafts/{draft}` (`notes.add`, the author while holding); `GET /cases/{ref}/documents`
(`documents.view`); `POST /cases/{ref}/documents` (`documents.upload`, working basis); `PATCH /documents/{doc}` and
`POST /documents/{doc}/archive` (`documents.upload`, then the uploader / department / super admin rule);
`GET /documents/{doc}/file` (`documents.view` inline, `documents.download` attachment); `POST /alerts/read`
(signed in, own rows); `GET /alerts/counts` (case reading); `GET /calendar` (case reading; `office` needs
`cases.view_all`).

Web server: no new route; the relay header of decision 23.

## Jobs
None. Alerts for files received, recalled and due come from the existing `aslms.alerts_scan_events` (every 5
minutes) and `aslms.alerts_sweep_dates` (hourly); attachment and upload text extraction from the existing
`aslms.extract_document_text` / `aslms.extract_pending_text`.

## Tests
Backend (pytest, `backend/tests/`, the shared world of `tests/db/world.py` with the two-department person, the
scripted scanner and store fakes):
- `db/test_workflow_actions.py` (new): `test_flags_match_outcomes` (for each world user × case state — pool,
  claimed with office-held custody, held personally by the user, held by another department's officer who is the
  user, owned by the user's department with the file elsewhere — `note_mode`, `upload` and `set_stage` equal the
  outcome of `notes.add_note`, `documents.upload` and `stages.set_stage` run in a savepoint that is rolled back:
  draft / permanent / refused); `test_note_mode_draft_for_holder_membership_only` (the two-department person holding
  through one membership gets `draft`); `test_flags_null_on_pool_case`; `test_flags_write_nothing` (no `audit_log`,
  `events`, notes or drafts rows after reading); `test_overview_hidden_case_404`.
- `db/test_notes.py` (added): `test_can_correct_author_and_whole_department`; `test_can_correct_false_when_superseded`;
  `test_can_correct_false_for_reader_without_working_basis`; `test_draft_documents_carry_id_type_mime` (an order PDF
  linked to a draft has `id` and no `ref_no`, and the `PATCH` with that id keeps the link).
- `db/test_api_alerts.py` (added): `test_own_list_can_act_by_function_and_status`;
  `test_case_tab_can_act_false_for_state_reader` (the auditor sees the alert, `can_act` false, acknowledge → 404 as
  before); `test_case_tab_can_act_true_for_working_recipient`; `test_closed_alert_can_act_false`.
- `db/test_api_workflow.py` (added): `test_codes_carry_limits` (from the settings object).
- `db/test_api_documents.py` (added): `test_types_carry_upload_limits` (`max_bytes` from settings; extensions pdf,
  docx, doc, jpg, jpeg, png).
- `db/test_api_reference.py` (added): `test_labels_carry_active_alert_kinds` (retired `request_due` absent).
- `db/test_custody_send.py` (added): `test_sent_item_visible_false_after_sending_on` (the HEALTH officer sends on and
  loses sight: `visible` false; the EDU admin's own send of an owned case: true).
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, the `fakeApi` helper):
- `server/relay.test.ts` (added): `content-length` and the multipart `content-type` with its boundary are forwarded;
  other request headers are still dropped.
- `lib/routes.test.ts` (added): Alerts & calendar shown for case readers; Files shown with `cases.view_scope`; the
  Department files tab only with `custody.track`; case tabs include Custody and stage and Alerts.
- `lib/timeline.test.ts` (added): `custody_moved`, `stage_set`, `note_added`, `document_uploaded`, `alert_raised`
  lines; no remark and no raw JSON.
- `lib/workflow.test.ts` (new): `dueDateBounds` near midnight IST; `checkFile` refuses a wrong extension and an
  oversized file from the given limits; `monthGrid` weeks for a month starting on a Sunday and on a Monday.
- `components/workflow/workflow.test.tsx` (new): Send and Recall appear exactly when `can_send` / `can_recall`;
  the send dialog lists departments, then that department's people with `q`, offers only `sendable` actions, needs a
  remark, offers the stage only with `workflow.set_stage`, warns about drafts when `my_drafts` > 0, and posts
  `{to_membership, pending_action, due_date, remark, stage}`; a `card: null` answer navigates to `/files/sent` with
  the notice; `finalised_notes` are listed; 409 `unchanged` and 403 `not_in_control` show their messages; the recall
  dialog needs a remark; the custody tab lists legs, hides the remark when the API sends none, and shows the stage
  gaps; Set stage only with the flag and 409 `unchanged` in words; the composer says draft or permanent from
  `note_mode`, refuses files in draft mode, sends multipart with `files` and `file_doc_types` in permanent mode,
  requires a visibility with none pre-selected; Correct only with `can_correct`, kind and visibility fixed; drafts
  edit sends only changed fields and ids for links, delete asks for confirmation, `draft_finalised` re-reads; no
  Edit or Delete on permanent notes; the upload panel only with `workflow.upload`, refuses a `.txt` and an oversized
  file before sending, shows `infected`, `scanner_unavailable` and `duplicate` (with the link); Change visibility and
  Archive only on rows with `can_manage`, archive needs a reason, `already_ingested` in words.
- `components/files/files.test.tsx` (new): each tab calls its endpoint and scope; Department files and the summary
  only with `custody.track`; overdue and holder-department filters sent; Sent rows link only visible cases; no action
  buttons on the lists.
- `components/alerts/alerts.test.tsx` (new): filters sent as query parameters; kind labels from `alert_kinds`; Mark
  read and Mark all read post to `/alerts/read`; following a row's link marks it read first; opening the list marks
  nothing; Acknowledge / Done only with `can_act` and by status; an admin ticket notice links to the ticket; the
  calendar requests the month's range (never more than 62 days), shows the API's `critical` / `this_week` flags,
  and for a State-wide reader asks for a department before requesting; the case alerts tab shows the reader message
  on an empty list.
- `components/shell/shell.test.tsx` (changed): the bell links to `/alerts`.
- `components/case/case.test.tsx` (changed): the custody card shows Send / Recall by its flags (replacing the
  read-only assertion of row 12); the Stage card's Set stage by `workflow.set_stage`.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green with the new
   tests; `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the
   commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`, then `docker compose up -d --wait --no-deps api web` (no migration in this item,
   so `init` applies nothing; the worker and scheduler running the historical load are not recreated);
   `python backend/tools/portal_smoke.py` → every page 200 including the nine new ones (`/files`, `/files/mine`,
   `/files/offices`, `/files/department`, `/files/sent`, `/alerts`, `/alerts/calendar`,
   `/cases/smoke-x/custody`, `/cases/smoke-x/alerts`), and no error line in the `web` log.
4. Without a session: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/workflow/codes` →
   401.
5. Signed-in steps (they need the e-mailed sign-in code, so they are run by the owner or the integrator, as in rows
   12 and 50; if not run before merge they are recorded in the cycle report and handed over as in row 53): on a case
   claimed by a department (claim one through the inbox if none), as its department admin: the custody tab shows
   the card and the movement record; Send file to an officer of a second department with `parawise_comments`, a due
   date and a remark → the card shows that officer; `aslms audit search --action custody.sent --limit 1` shows the
   row with the browser's address and no remark text. As that officer: the Notes tab says "drafts"; write a draft;
   upload a small PDF from the Documents tab (201, the document listed; a `.txt` renamed `.pdf` → 415 in words);
   link it to the draft; Send file on to a third officer → the notice lists one finalised `NOTE/…`, the page goes to
   Files → Sent; the department admin's Notes tab shows the note with its attachment link.
6. As the department admin: Recall with a remark → the card shows the admin with "Examine"; Files → Department files
   lists the case and the summary counts it; `docker compose exec api aslms alerts run --events` then the third
   officer's bell count rises and `/alerts` lists the "recalled" notice; Acknowledge it there.
7. Set stage on the case → the stage card and the custody tab show it; the Timeline shows "File sent", "File
   recalled", "Stage set" and "Note added" lines. `/alerts/calendar` shows the department's hearings of the next 7
   days with the critical marks matching `GET /calendar`.
8. In `psql`: `SELECT count(*) FROM case_note_drafts` for the case = 0; no `audit_log.after` of the new rows contains
   the note body or the remark (digests only).

## Open questions
None.
