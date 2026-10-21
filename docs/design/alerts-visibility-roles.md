# Design: New-note and listed-for-tomorrow alerts, private records hidden from State oversight, and two role defaults

```
slug: alerts-visibility-roles
status: awaiting-approval
author: architect
date: 2026-10-21
approved_by: (pending)
```

## Context
This is backlog row 121. `docs/ASLMS_Process_Workflows.md` section 6 lists 16 points worth a decision. On 21 Oct 2026
the owner decided four of them. This note designs those four. They are owner decisions and are not reopened here:

- **Item 8, two new alerts.**
  - (a) **New note on your case.** When a permanent note is added, alert the people working on the case who can read
    that note. A private note's existence must never reach someone who cannot read it. Alerts and e-mails never carry
    the note text.
  - (b) **Listed for tomorrow.** After the evening cause-list run (the 18:30 IST job), alert the people working on each
    owned or watched case that is on the next day's lists. The alert gives the court and the item number as printed,
    once per case per date. It complements the 7-day / 48-hour hearing alerts and must not duplicate them.
  - Claiming a case and setting a stage stay quiet (owner's choice).
- **Item 9.** Private-to-office records and custody remarks are hidden from State oversight and the central operator.
  The Auditor and the super admin keep that sight. The owner's words: today the State-wide readers "see every document
  and note including `private_to_office`, and custody remarks"; the Auditor and the super admin "keep that sight".
- **Item 13.** The department head can recall files (`custody.recall`) by default, like the department admin.
- **Item 15.** The Auditor no longer has the Case Assistant (`assistant.use`) by default.

Items 14 (directorates and units are created by the super admin only) and 16 (sign-out token lifetime) stay as they
are.

**The plan.** §5.5 "Alerts and Hearing Calendar" lists listed hearings from Cause List Details and says "alerts go to
the current custody holder". Users and access: State oversight has a "read-only view of all cases across all
departments", and the Auditor has "read-only access to case records and the audit log". Documents and notes carry
"visibility set per note (whole case, shared with counsel, or private to the office)". The plan says nothing on whether
the State tier reads private records. So item 9 does not deviate from the plan. It does replace three earlier logged
decisions: documents-uploads decision 7 ("State-wide readers see all"), custody-workflow decision 11 (the remark is
shown to State-wide readers) and custody-workflow decision 17 (every note for a State-wide reader). The scribe records
that in the decision log.

**What is in place** (code read on 21 Oct 2026):
- **Alerts** (`services/alerts.py`). Alerts come from two generators.
  - `scan_events` runs every 5 minutes over new `events` rows, for owned or watched cases only.
  - `sweep_dates` runs hourly at minute 10. It raises `hearing_due` from `calendar.hearing_rows`, which merges three
    sources: `cases.next_hearing_date`, the cause-list listings and next dates from orders. The listing is preferred
    because it names the court and the item.
  - The key is `hearing_due:<case>:<date>`, `high` inside 7 days and `critical` within 48 hours.
  - `raise_alert` is idempotent on `dedupe_key`. It notifies again only when the severity rises.
- **Recipients** (`services/recipients.py`, `Resolver`). `case_recipients` gives the custody holder, the primary owner
  chain and the watchers. `finalise` then removes inactive users, the actor, standing counsel, anyone who cannot see
  the case and, for `new_document`, anyone who cannot see the document.
- **Reading paths for an alert:**
  - `notification_visible_condition`: the caller's own list, the counts, the bell and the digest.
  - `_may_act_on`: the detail page, acknowledge and done.
  - `alerts_for_case`: the case's Alerts tab.
  - `case_detail._alert_events_rule`: `alert_raised` rows on the timeline.
  - The document rule is applied on all four through `visibility.alert_document_condition` and
    `can_view_alert_document`.
  - The immediate e-mail (`notifications.send_pending`) does not check visibility again.
- **Notes** (`services/notes.py`).
  - `note_added` is emitted for a note added directly (`finalised: false`) and for each holder draft turned permanent
    by `finalise_drafts` when the file moves (`finalised: true`). The event's actor is the note's author.
  - Drafts emit no event.
  - Events and audit rows carry the body's length and SHA-256, never the text.
- **Visibility** (`services/visibility.py`). `state_wide()` is true for a super admin membership or one holding
  `cases.view_all`. Three functions short-circuit to `true()` for such a caller: `record_visibility_condition`,
  `document_visible_condition` (per membership) and `note_visible_condition`. So State oversight, the central operator
  and the Auditor read every `private_to_office` note and document.
- **Custody remarks** (`services/custody.py`). `shows_remark(bases)` shows the remark to a working basis or the
  `state` basis. It is used by `card` and `history`. `sent` shows only the caller's own legs.
- **Cause lists.** `lists-evening` (18:30 IST) only enqueues `causelist_day` for yesterday, today and tomorrow. The
  worker fetches them later in the `daily` lane. `causelists.apply_entries` emits no event.
- **The type matrix** (`services/access_seed.py`). `seed_matrix` only inserts missing (type, function) rows and never
  changes an existing one. `set_matrix` (API and `aslms access set`) writes `updated_by` and an `access.matrix`
  audit row.

**Not covered:** item 7 (alerts on suggestions), claim and stage alerts (kept quiet), any portal screen change
(decision 16), SMS, and the Case Assistant itself (row 14). No NAPIX call is added.

## Decisions

**New-note alert (item 8a)**

1. **One alert per permanent note, from the `note_added` event.**
   - The event scan handles `note_added`. It adds it to `HANDLED_EVENTS` with the existing owned-or-watched filter.
   - It raises `new_note` with key `new_note:<note id>`, addressed to the owning department (`owning_office`).
   - Severity `normal` (from `ref_alert_kind.default_severity`): in-app and the digest; an immediate mail only for
     people who chose "no digest".
   - Only `source = user` notes alert.
   - Alternatives: one alert per case per day, which cannot work, because notes of one case have different audiences
     and one alert row cannot be filtered per note; or a direct call from `notes.py`, which would put alert logic in
     the write path and break the scan's one-pipeline design.
2. **Drafts never alert. A draft alerts when it becomes permanent.**
   - When the file moves, `finalise_drafts` emits `note_added` (`finalised: true`) for each draft. Each becomes its own
     `new_note` alert at the next scan, oldest first.
   - The excluded actor is the draft's author (the event's actor), not the person who moved the file. So a recaller who
     never saw the holder's drafts is told of them.
   - Alternative: one combined "3 notes added" alert per move. Rejected for the same audience reason as decision 1.
     Several notes from one move arrive together and the digest groups them.
3. **Recipients: the people working on the case who can read the note.**
   - The list is `Resolver.case_recipients(case)`, the same as every case alert: custody holder, primary owner chain,
     watchers.
   - `finalise` gains `note_id`. It keeps only users for whom `visibility.can_view_note(session, user, note_id)` holds.
     This is the same membership-aware rule as the Notes tab, including the `notes.view_private_office` and
     `notes.view_counsel_shared` switches and item 9's new rule.
   - The author is excluded and standing counsel are excluded, as for every case alert.
   - A private note of the owner's unit therefore reaches only that office, its department head and admin and its
     author. It never reaches a watcher department or a State-wide reader.
4. **No reading path reveals a note the reader cannot read.** A new SQL condition
   `visibility.alert_note_condition(session, user)` over `alerts` mirrors `alert_document_condition`:
   - Any kind but `new_note` passes.
   - A `new_note` alert passes only when `data.note_id` names a note that passes `note_visible_condition` for the
     caller.
   - A missing or unknown note id hides the alert.
   - `can_view_alert_note` is its one-row twin. Both are applied wherever the document rule is applied today:
     `notification_visible_condition` (list, counts, bell, digest), `_may_act_on` (detail, acknowledge, done),
     `alerts_for_case` (the Alerts tab, including readers who work on the case but were not notified) and
     `case_detail._alert_events_rule` (the timeline's `alert_raised` row, whose payload carries the title).
5. **No note text anywhere.** The title, body, `data`, mail and digest name only these:
   - the note's kind label ("Hearing note");
   - its `ref_no`;
   - the author's name and designation, and the note's office code;
   - `supersedes_ref_no` for a correction;
   - `finalised`.
   - Title: "New hearing note: <case>", or "Note corrected: <case>" when `supersedes_ref_no` is set.
   - Body: "Note ASLMS/EDU/NOTE/2026/000042 (Hearing note) by Under Secretary, EDU. Open the case to read it."
   - `data` also holds `note_id`, `seq_no`, `kind` and `visibility`. The recipient can read the note, so these reveal
     nothing new.
   - A test plants a unique marker in a note body and proves it appears in no alert column, notification, mail or
     digest.
6. **The immediate mail re-checks visibility before sending.**
   - `send_pending` sends a case alert's mail only when `notification_visible_condition` still holds for the recipient
     and that alert, in one query per row.
   - Otherwise the row becomes `failed` with "no longer visible to the recipient" and is not retried.
   - This covers a recipient who lost access between the raise and the send, for every case alert, not only
     `new_note`. The digest already filters by that condition.
   - Alternative: re-check only `new_note` and `new_document`. Rejected: one rule is simpler, and the condition already
     admits the named-recipient notices (`case_taken_over`, `transfer_*`, `file_recalled`).
   - Admin-ticket mails are unchanged.
7. **Life cycle.** `new_note` is informational. It joins `INFO_KINDS` and `CASE_KINDS` and expires `aged` after
   `ALERT_INFO_EXPIRE_DAYS` (14), as `new_document` does. Acknowledge and done work as for any alert.

**Listed for tomorrow (item 8b)**

8. **A pass inside the hourly date sweep, in the evening window.**
   - `alerts.listed_tomorrow(session, now, cfg, *, force=False)` reads the cause-list entries of D = tomorrow (IST
     date + 1). It joins `causelists` on `list_date = D` and keeps live cases (not merged) with an active owner or
     watcher (`calendar.owned_case_condition`).
   - It raises one `listed_tomorrow` alert per case with key `listed_tomorrow:<case id>:<D>`.
   - `sweep_dates` calls it first, before its hearing loop, whenever the IST time is at or after `ALERT_LISTED_FROM`
     (default `18:30`). The sweeps at 19:10, 20:10, 21:10, 22:10 and 23:10 IST run it. A list the worker fetches late in
     the evening is still caught by a later sweep.
   - `aslms alerts run --listed` runs the pass at once whatever the time (`force=True`), for re-runs and verification.
   - Alternatives:
     - A new beat entry every 15 minutes in the evening. This races the hourly sweep: at 19:10 the sweep could raise a
       cause-list `hearing_due` for tomorrow minutes before the listing alert, which is the duplicate the owner ruled
       out.
     - Dispatch from the worker after a `causelist_day` item for tomorrow. This couples the loader to alerts.
     - Events per cause-list entry. This would add millions of rows during the historical load.
   - Lists for tomorrow are published and fetched by the 18:30 run, so in practice the first alert comes at 19:10. A
     list already held earlier in the day is alerted at 18:30 or after, never in the morning, which matches the owner's
     "after the evening cause-list run".
9. **Content: court and item as printed, every listing of the day.**
   - `data.entries` lists each entry of the case on D, ordered by list type, court and position: `list_type`
     (daily / supplementary / …), `court_no`, `item_no` (`printed_sr_no`, else `sr_no`) and `bench_text`. At most 5
     entries, plus `entries_total`. Also `hearing_date`.
   - Title: "Listed tomorrow, 22 Oct 2026, court 3 item 14: WP(C)/123/2026". The first entry is shown; "+1 more" is
     added when there are more.
   - Body: "Listed in the daily cause list of 22 Oct 2026: court 3, item 14; supplementary list: court 5, item 2."
   - No party or advocate text.
   - `due_at` is D at the sitting time, as for hearings.
   - Severity: `rules.severity_for_hearing` gives `critical`, because tomorrow is within 48 hours. That means an
     immediate e-mail to everyone with e-mail on, which is the point of an evening notice. Nothing is raised if the
     sitting time has passed.
10. **Once per case per date.**
    - The key carries the case and the date, so several lists (daily and supplementary), connected entries, re-runs
      and repeated sweeps raise one alert.
    - A supplementary list fetched after the alert was raised does not alert again. The case page and the Cause list
      screen show it.
    - A closed listing alert is never raised again (`raise_alert` returns the existing row).
11. **How duplicates with the hearing alerts are avoided.**
    - (a) When a `listed_tomorrow` alert is newly raised, an open `hearing_due:<case>:<D>` alert is closed `done`
      with `data.closed_reason = "listed_tomorrow"`. This is a system closure, with no audit row, as for the other
      closures. So nobody has two open alerts for one hearing.
    - (b) In the same sweep and every later one, the hearing loop does not raise or upgrade `hearing_due` for a (case,
      date) that has a `listed_tomorrow` alert in any state. The sweep loads those keys once for the look-ahead range.
      This also covers the morning of D, when the 00:10 sweep would otherwise raise a cause-list `hearing_due` for
      "today".
    - (c) The 7-day `high` and the 48-hour `critical` hearing alerts are unchanged before the listing.
    - So a case that the court records give for D gets at most: the `high` alert up to 7 days ahead, the `critical`
      upgrade 48 hours before the sitting (10:30 the day before), and the evening listing alert with court and item.
    - A case that appears only in the list gets only the listing alert.
    - `next_date_changed` is a different event (a change of date) and is untouched.
12. **Recipients and closure.**
    - Recipients are the same as `hearing_due`: `finalise(case_recipients(case), case)`.
    - The alert expires `passed` 12 hours after its due time (`HEARING_GRACE`), in the sweep's hearing closure loop. It
      is not informational and does not join `INFO_KINDS`.
    - A case with a watcher but no primary owner gets no alert and is counted `skipped_unowned`, as in the hearing
      loop.

**Private records and remarks (item 9)**

13. **A function, `cases.view_private_all`, not a user-type test.**
    - Label "View private records State-wide". Description: "With View all cases: also the notes, documents and file
      remarks kept private to an office". Module `cases`.
    - Enabled by default for `auditor` only. The super admin holds every function and cannot be denied, so the super
      admin keeps the sight automatically.
    - `state_oversight` and `central_operator` do not get it.
    - Why a function:
      - It shows in the type matrix and on the person's functions.
      - The super admin can grant it to one named State oversight officer or withdraw it from the Auditor without a
        code change.
      - It follows the "a membership is the unit of authority" rule of `user-memberships`.
      - A test on `Role.AUDITOR` would be invisible and fixed in code.
    - Alternatives: `notes.view_private_all`, rejected because the rule also covers documents and remarks, so a
      `notes.` name would mislead; or reusing `audit.view`, rejected because it mixes two separate authorities.
    - **The function only works with State-wide sight.** It takes effect only in a membership that is State-wide (super
      admin or `cases.view_all`). A department membership granted it gains nothing. Case sight always comes first, and
      a department user's private-record sight stays with `notes.view_private_office` and the office rule.
    - Delegation is unchanged. A department admin can grant only functions they hold, so they can never grant this
      one.
14. **The rule, in `services/visibility.py`, server-side, in SQL.**
    - New `_private_all_member(m) = _state_wide_member(m) and m.holds(Permission.CASES_VIEW_PRIVATE_ALL)` and
      `sees_private_all(session, user)` (any active membership).
    - `record_visibility_condition` and `note_visible_condition` short-circuit to `true()` only when
      `sees_private_all`.
      - Otherwise they OR the per-membership conditions.
      - A State-wide membership without the function now goes through `_record_condition_for` and
        `_member_note_condition`. Its `member_bases` is `[("state", true)]`, so it still sees every case.
      - In those conditions the records pass for court records, `counsel_shared`, `case_scope` and `private_to_office`
        of its own office or its own authorship. It has no department, so there is no department-wide branch. For notes
        the `notes.view_private_office` switch applies as for anyone.
    - `document_visible_condition` returns `_case_of_document(true())` only for a `_private_all_member` holding the
      function asked (`documents.view` / `documents.download`). Other State-wide memberships fall to
      `_member_document_condition`.
    - `state_wide()` keeps its meaning: every case, and alerts addressed to any office. Its docstring loses "private
      ones included".
    - Everything that already reads through these conditions follows with no change of its own:
      - Notes tab, note detail, corrections chain and note counts (`notes.py`, `case_detail.py`).
      - Documents tab, download, content search, note attachments, the data-health failed-documents list and the
        SourceTrace status list (`documents.py`, `notes.py`, `data_health.py`, `sourcetrace_ingest.py`).
      - Timeline `note_added` and `document_uploaded` rows.
      - `new_document` and `new_note` alerts.
15. **Private documents follow the same rule as private notes.** The owner's description of what State oversight
    loses is "every document and note including `private_to_office`". The plan gives notes and documents one
    visibility setting with one meaning ("private to the office"). A private document hidden from the Notes tab but
    open on the Documents tab would be incoherent. Court records (`doc_group = court_record`) stay open to every
    reader of the case. *If the owner meant notes only, striking this decision removes the document branch (decision
    14's `document_visible_condition` change). Nothing else depends on it.*
16. **Custody remarks.** `custody.shows_remark(bases)` becomes `shows_remark(session, user, bases)`:
    - true for a working basis (owner, allotted, custody, counsel);
    - or for the `state` basis when `sees_private_all(session, user)`.
    - `card` (overview, Files lists, Custody tab) and `history` pass the caller.
    - `sent` still shows the caller's own remarks.
    - State oversight and the central operator still see who holds the file, the pending action, the due date and the
      legs, without the remark. The API already returns `remark: null` to readers without a working basis, and the
      portal already renders that. **No portal change.**
    - Remarks never appear in events, audit rows, alerts or reports (custody-workflow decision 21, unchanged).
    - A State-wide membership is never a custody target (`eligible_target` excludes `NOT_OFFICERS`), so it cannot hold
      a file and lose its own remark.

**Role defaults (items 13, 15) and reaching a seeded database**

17. **The defaults in code.** In `DEFAULT_MATRIX`:
    - `dept_head` gains `custody.recall`;
    - `auditor` becomes `(_READ_CASES - {assistant.use}) | {cases.view_all, audit.view, cases.view_private_all}`.
    - `recaller_member` already accepts any membership of the owning department holding `custody.recall`, so the head
      needs no code change. The same goes for the Case Assistant, which is not built yet (row 14).
18. **Migration 0021, a reference-data and access-default migration, applies the two changes exactly once.** It
    changes no table or column. It is modelled on 0016 and 0018: hard-coded rows, no application import, frozen once
    applied.
    - **(a)** `ref_alert_kind` gets `new_note` ("New note", `normal`, sort 130) and `listed_tomorrow` ("Listed for
      tomorrow", `critical`, sort 140), with `ON CONFLICT (code) DO NOTHING`. The seed carries the same labels and
      severities (`ALERT_SEVERITY`, `ALERT_KIND_LABELS`).
    - **(b)** It runs only when `role_permissions` has rows, that is, on an already seeded database. On a fresh database
      the seed that follows `alembic upgrade head` inserts the new defaults directly, so fresh and upgraded databases end
      the same. For each of two (type, function, old → new) changes:
      - `dept_head` / `custody.recall`, `false → true`;
      - `auditor` / `assistant.use`, `true → false`.
      - The row is changed only if all three hold:
        - it still holds the old default;
        - `updated_by IS NULL`;
        - no `access.matrix` audit row exists for that type and function.
      - Each change writes one audit row `access.matrix_default_changed`. Fields: entity `role_permission`, the row id,
        `actor_name` "migration 0021", `before {is_enabled}`, `after {role, permission, is_enabled, migration: "0021",
        design: "alerts-visibility-roles"}`. It also writes one `access_changed` event (scoped, dedupe
        `access_matrix_default:0021:<role>:<permission>`), as `set_matrix` does.
      - A row left alone writes one audit row `access.matrix_default_kept` with `reason: "customised"`, so the owner can
        see why.
    - **(c)** On a seeded database it also writes one audit row `access.rule_changed`. Entity `access_rule`. After:
      `{rule: "private_records_state_wide", function: "cases.view_private_all", default_types: ["auditor"],
      always: ["super_admin"], withdrawn_from: ["state_oversight", "central_operator"], migration: "0021"}`. The audit
      log thus dates the moment State oversight and the central operator stopped reading private records, although that
      change is a rule and not a matrix row.
    - **Why a migration and not a seed step.** Alembic applies a revision once per database by construction, so no
      "applied changes" marker table or audit-row lookup in the seed is needed. The rows are frozen with the history.
      The precedent is 0016 and 0018.
    - **Why the new function needs no migration.** Its `ref_permission` row and its nine matrix rows (enabled for
      `auditor` only) are "missing rows", which the seed already inserts on every database. This is the path
      `admin.service_health` and the other additions took. No access that exists today is widened by them: the Auditor
      keeps sight it already has.
    - **Downgrade.** For each `access.matrix_default_changed` row of 0021 whose matrix row still holds the new value and
      has no later `access.matrix` audit row, the downgrade restores the old value. It writes an audit row with
      `migration: "0021-downgrade"`. It then deletes the two `ref_alert_kind` rows if no alert uses them, as 0018 does.
19. **Counts.** `ref_permission` grows to 53 rows, 51 active. The portal's "50 active functions" wording is the
    scribe's.

## Data
No table or column is added or changed.

Paragraphs for `docs/schema/schema.md`:

> **`ref_permission`** (append to the row's history): `cases.view_private_all` ("View private records State-wide",
> module `cases`; "With View all cases: also the notes, documents and file remarks kept private to an office") added by
> `alerts-visibility-roles` (53 rows, 51 active, seed only). It takes effect only in a State-wide membership (super
> admin or `cases.view_all`). Enabled by default for `auditor`; the super admin holds it always.

> **`role_permissions`** (append): `alerts-visibility-roles` changed two defaults on 21 Oct 2026 (owner's decisions,
> section 6 items 13 and 15): `dept_head` + `custody.recall`, `auditor` − `assistant.use`. Migration 0021 applies them
> to an already seeded database once. It changes a row only while it still holds the old default with
> `updated_by IS NULL` and no `access.matrix` audit row for it. Each change writes an `access.matrix_default_changed`
> audit row and an `access_changed` event; a customised row is kept, with an `access.matrix_default_kept` audit row.
> The seed's `DEFAULT_MATRIX` carries the new defaults for fresh databases.

> **`ref_alert_kind`** (append): `new_note` ("New note", `normal`) and `listed_tomorrow` ("Listed for tomorrow",
> `critical`), from `alerts-visibility-roles`, migration 0021 and the seed.

> **`alerts`** (append to the kind list): `new_note` (key `new_note:<note id>`; `data`: `note_id`, `ref_no`, `seq_no`,
> `kind`, `kind_label`, `visibility`, `office_code`, `author_name`, `author_designation`, `supersedes_ref_no`,
> `finalised`; never the note text; every reading path applies the note rule) and `listed_tomorrow` (key
> `listed_tomorrow:<case id>:<YYYY-MM-DD>`; `data`: `hearing_date`, `entries` [`list_type`, `court_no`, `item_no`,
> `bench_text`] up to 5, `entries_total`; closes an open `hearing_due` of the same case and date as `done` /
> `listed_tomorrow`).

> **Visibility** (the rule paragraph at the top of schema.md, "private_to_office to the office itself …"): replace
> "State-wide readers see all" with "a State-wide reader sees private records only with `cases.view_private_all` (the
> super admin and, by default, the Auditor); State oversight and the central operator do not see `private_to_office`
> notes and documents or custody remarks (alerts-visibility-roles)".

Table classes unchanged: `ref_alert_kind` and `ref_permission` are reference, `role_permissions` is master, and
`audit_log` and `events` are derived. Audit columns are as existing. No foreign key changes.

**Migration:** `0021_alerts_visibility_roles.py` (revises 0020), reference data and access defaults only, as decision
18. `aslms_app` already has SELECT / INSERT / UPDATE on `role_permissions` and `ref_alert_kind` and INSERT on
`audit_log` and `events`, so no grants change.

## Services

**`services/visibility.py`**
- `_private_all_member(member) -> bool` and `sees_private_all(session, user) -> bool` (decision 14).
- `record_visibility_condition`, `note_visible_condition`, `document_visible_condition`: the short-circuit is narrowed
  to `sees_private_all` / `_private_all_member` (decision 14).
- `alert_note_condition(session, user)` over `alerts` and `can_view_alert_note(session, user, alert)` (decision 4).
- Docstrings: the module header and `state_wide` describe the new rule.

**`services/custody.py`**
- `shows_remark(session, user, bases)`. Callers are `card` and `history` (decision 16).

**`services/recipients.py`**
- `Resolver.finalise(..., note_id: uuid.UUID | None = None)` drops users for whom `visibility.can_view_note` is false
  (decision 3).

**`services/alert_rules.py`**
- `INFO_KINDS` + `NEW_NOTE`; `CASE_KINDS` + `NEW_NOTE`, `LISTED_TOMORROW`.
- `render_alert` gets branches for `new_note` (decision 5) and `listed_tomorrow` (decision 9). They read only the
  `data` keys listed above.
- A helper `listing_text(entries)` builds the "court 3, item 14" phrases.

**`services/alerts.py`**
- `HANDLED_EVENTS` + `NOTE_ADDED`. `_handle_event` gets a branch for it that raises `new_note`:
  - It loads `CaseNote` by `payload.note_id`. It skips (`skipped_other`) when the note is missing or is not
    `source = user`.
  - It reads the kind label from `ref_note_kind`.
  - Recipients: `resolver.finalise(resolver.case_recipients(case), case, exclude_user_id=ev.actor_user_id,
    note_id=note.id)`.
  - Office: `owning_office` (else `skipped_unowned`).
- `listed_tomorrow(session, *, now=None, config=None, force=False, counters=None) -> dict` (decisions 8 to 12). It
  returns `{list_date, entries_seen, cases, alerts_new, hearing_closed, skipped_unowned, alerts_without_recipients,
  notifications}`.
  - Outside the window and without `force` it returns `{"skipped": "before_window"}`.
  - One query groups the entries per case, then `raise_alert` runs per case.
  - On a new alert it closes the open `hearing_due:<case>:<D>`.
- `sweep_dates`:
  - Calls `listed_tomorrow` first and merges its counters under `listed_*` keys.
  - Loads the set of `listed_tomorrow` keys for `today .. today + lookahead` and skips those (case, date) pairs in the
    hearing loop. The keys are still added to `current_keys`.
  - Closes `listed_tomorrow` alerts whose due time plus `HEARING_GRACE` has passed (`expired` / `passed`).
- `AlertConfig.listed_from: str = "18:30"`, from `Settings.alert_listed_from` (env `ALERT_LISTED_FROM`, default
  `18:30`). No `.env` change is needed.
- `notification_visible_condition`, `_may_act_on`, `alerts_for_case` AND the note rule (decision 4).

**`services/case_detail.py`**
- `_alert_events_rule` ANDs `alert_note_condition` with `alert_document_condition` (decision 4).

**`services/notifications.py`**
- `send_pending`: before rendering a case alert's mail, it runs one query for the alert joined to its case under
  `notification_visible_condition(session, user)`. If that fails, the row becomes `failed`, error "no longer visible to
  the recipient", `attempts = max_attempts`, counted `skipped` (decision 6).

**`services/access_seed.py`**
- `PERMISSION_LABELS[CASES_VIEW_PRIVATE_ALL]`.
- `DEFAULT_MATRIX` changes (decision 17).

**`services/seed.py`**
- `ALERT_SEVERITY[LISTED_TOMORROW] = "critical"`.
- `ALERT_KIND_LABELS` `new_note` "New note" and `listed_tomorrow` "Listed for tomorrow".

**`domain/reference.py`**
- `AlertKind.NEW_NOTE = "new_note"`, `AlertKind.LISTED_TOMORROW = "listed_tomorrow"`.
- `Permission.CASES_VIEW_PRIVATE_ALL = "cases.view_private_all"`.

**`cli/alerts.py`**
- `aslms alerts run --listed` runs `listed_tomorrow(force=True)` and prints its counters. `--dates` includes the pass
  only inside the window.

**Audit and events**
- No new audit action in the services. Alerts are system rows: raising writes `alert_raised`, and closures sit on the
  row. Acknowledge and done keep their audit rows.
- The access audit rows are written by migration 0021 (decision 18).

## API
No endpoint, path, request shape or required function changes. Existing endpoints change what they return:

| Endpoint | Function required (unchanged) | Change |
|---|---|---|
| `GET /cases/{ref}/notes`, `GET /notes/{note}` | `cases.view_scope` or `cases.view_all` (case sight) | `private_to_office` notes hidden from State-wide readers without `cases.view_private_all` (404 on detail) |
| `GET /cases/{ref}/documents`, document detail and file download, `GET /documents/search` | `documents.view` / `documents.download` | same rule for `private_to_office` documents (404 on detail and download) |
| `GET /cases/{ref}/custody`, the case overview custody card, `GET /custody/held` | case sight | `remark: null` for State-wide readers without `cases.view_private_all` |
| `GET /cases/{ref}/timeline` | case sight | `note_added`, `document_uploaded` and `alert_raised` rows follow the record rules |
| `GET /alerts`, `/alerts/counts`, `/alerts/{ref}`, acknowledge, done, `GET /cases/{ref}/alerts` | own notifications; `alerts.acknowledge` to act | new kinds `new_note`, `listed_tomorrow`; `new_note` filtered by the note rule (404 on detail) |
| `GET /reference/labels` | signed in | `alert_kinds` lists the two new kinds |
| `GET /admin/permissions`, `GET /admin/access/types`, `GET /me` | `users.view` (the matrix) / signed in | the new function appears |

The visibility rule is server-side in SQL on every one of these. Nothing is filtered in the portal.

**Portal.** No change. Alert kind labels come from `GET /reference/labels`. Alerts link to their case as every case
alert does. A null remark already renders as no remark. The matrix screen lists functions from the API.

## Jobs
- **No new beat entry.** The listed-for-tomorrow pass runs inside `alerts-sweep-dates` (hourly at minute 10) from
  `ALERT_LISTED_FROM` (18:30 IST) to midnight. In practice those are the 19:10 to 23:10 sweeps after the 18:30
  `lists-evening` run. The pass writes its counters into the sweep's `job_runs` row (`alerts_dates`) under `listed_*`.
- `alerts-scan-events` (every 5 minutes) now also turns `note_added` events into `new_note` alerts.
- No queue kind, no NAPIX call, no SourceTrace call.

## Tests
Unit (no database):
- `test_alert_rules.py::test_new_note_text_names_kind_ref_and_author_only`: title and body for a note and a correction,
  with no body text.
- `test_alert_rules.py::test_listed_tomorrow_text_lists_court_and_printed_item`: one entry, several entries ("+1
  more", body lists each), a missing `printed_sr_no` falling back to `sr_no`.
- `test_alert_rules.py::test_new_note_is_informational_and_listed_is_not`.
- `test_access_seed.py::test_default_matrix_head_recalls_auditor_has_no_assistant_and_private_sight`: also proves
  State oversight and the central operator lack `cases.view_private_all`.

Database:
- `test_note_visibility.py`:
  - `test_state_oversight_and_central_operator_do_not_read_private_notes`: list, detail 404, count, timeline row.
  - `test_auditor_and_super_admin_read_private_notes`.
  - `test_view_private_all_has_no_effect_without_view_all`.
  - `test_granted_view_private_all_gives_one_oversight_officer_the_sight`.
  - `test_denied_view_private_all_removes_it_from_an_auditor`.
  - `test_oversight_still_reads_case_scope_and_counsel_shared_notes`.
- `test_document_visibility.py`:
  - `test_state_oversight_cannot_list_or_download_private_documents`.
  - `test_state_oversight_still_reads_court_records_and_case_scope_documents`.
  - `test_auditor_downloads_private_documents`.
  - `test_private_document_hidden_from_oversight_content_search`.
- `test_custody_remark_visibility.py` (new):
  - `test_card_and_history_hide_remark_from_oversight_and_operator`.
  - `test_auditor_and_super_admin_see_remark`.
  - `test_working_basis_still_sees_remark`.
  - `test_sent_list_shows_own_remark`.
- `test_alerts_new_note.py` (new):
  - `test_case_scope_note_alerts_holder_owner_and_watchers_not_the_author`.
  - `test_private_note_alerts_only_those_who_can_read_it`: watcher department, other unit and standing counsel get
    nothing.
  - `test_counsel_shared_note_skips_counsel_as_for_every_case_alert`.
  - `test_draft_alerts_nothing_until_the_file_moves`.
  - `test_finalised_drafts_alert_once_each_excluding_their_author_not_the_mover`.
  - `test_correction_alert_says_note_corrected`.
  - `test_note_on_unowned_case_raises_nothing`.
  - `test_rescan_does_not_raise_twice`.
  - `test_note_text_never_in_alert_notification_mail_or_digest`: marker string planted.
- `test_alerts_note_reading_paths.py` (new):
  - `test_private_note_alert_hidden_from_department_reader_who_cannot_read_it`: `alerts_for_case`, detail 404,
    acknowledge 404.
  - `test_private_note_alert_raised_row_hidden_on_timeline`.
  - `test_private_note_alert_hidden_from_state_oversight_alerts_tab`.
  - `test_alert_with_unknown_note_id_is_hidden`.
- `test_alerts_listed_tomorrow.py` (new):
  - `test_owned_and_watched_cases_on_tomorrows_list_alert_once_with_court_and_item`.
  - `test_daily_and_supplementary_listings_make_one_alert_listing_both`.
  - `test_unowned_listed_case_raises_nothing`.
  - `test_before_window_nothing_and_force_runs`.
  - `test_open_hearing_due_closed_done_listed`.
  - `test_sweep_does_not_raise_or_upgrade_hearing_due_after_listing`: same sweep, and the 00:10 sweep of D.
  - `test_hearing_alerts_before_the_listing_unchanged`.
  - `test_late_supplementary_after_alert_does_not_realert`.
  - `test_listed_alert_expires_after_grace`.
  - `test_merged_case_skipped`.
  - `test_severity_critical_sends_immediate_mail`.
- `test_notifications_send.py::test_mail_not_sent_when_recipient_lost_sight` and
  `::test_named_recipient_notice_still_mailed`.
- `test_migration_0021.py` (new, `migration_cycle`):
  - `test_fresh_database_gets_new_defaults_from_seed_and_no_audit`.
  - `test_seeded_database_flips_two_rows_with_audit_and_event`.
  - `test_customised_row_kept_with_kept_audit`: `updated_by` set, and separately an `access.matrix` audit row with the
    value equal to the old default.
  - `test_rule_changed_audit_written_once_on_seeded_database`.
  - `test_alert_kinds_inserted_and_seed_agrees`.
  - `test_downgrade_restores_only_untouched_rows_and_unused_kinds`.
  - `test_database_matches_models_at_head`.
- Existing tests that assert State-wide readers see private notes, documents or remarks are updated for State
  oversight and the central operator and kept for the Auditor and the super admin. Matrix count assertions (53 / 51)
  are updated.

`ruff check` clean, `pytest -q` green, frontend tests unchanged and green.

## Verification
1. `ruff check` and `pytest -q` in `backend/` green. The new test files above pass. `npm test` in `frontend/` is
   green, with no frontend change.
2. On a copy of the dev database (`aslms ops backup` first), run `aslms ops migrate`, which applies 0021 and then the
   seed. Then:
   - `aslms access matrix dept_head` shows `custody.recall` on.
   - `aslms access matrix auditor` shows `assistant.use` off and `cases.view_private_all` on.
   - `aslms access matrix state_oversight` and `… central_operator` show `cases.view_private_all` off.
   - `aslms audit search --action access.matrix_default_changed` shows 2 rows (or fewer plus
     `access.matrix_default_kept` rows where the owner had customised the matrix).
   - `aslms audit search --action access.rule_changed` shows 1 row.
   - A second `aslms seed` inserts nothing.
3. With a test case holding one `private_to_office` note, one private document and a custody remark:
   - A State oversight login gets the note list without the note, 404 on its detail and download, and the custody card
     with `remark: null`.
   - An Auditor login gets all three.
   - A department head of the owning department can now Recall (`can_recall: true` on the card).
4. Add a `case_scope` note as an officer on an owned case and run `aslms alerts run --events`. One `new_note` alert
   appears for the holder and the owner chain, not for the author. Run `aslms alerts status` to see it.
5. After the evening lists are loaded (or with tomorrow's list loaded on the dev database), run
   `aslms alerts run --listed`. The counters give `cases = alerts_new` for the owned or watched cases on tomorrow's
   lists. A second run gives `alerts_new = 0`, and any open `hearing_due` for those cases and that date is closed
   `listed_tomorrow`. Mails appear in Mailtrap with court and item and no note or party text.

## Open questions
None. Every decision above is made from the owner's decisions of 21 Oct 2026 and the code. Three of them are choices
the owner can change at approval without redesign:
- decision 15: private documents follow the notes rule;
- decision 9: `listed_tomorrow` is `critical`, so it sends an immediate e-mail;
- decision 8: the listing pass runs at the hourly sweeps from 18:30 IST, first at 19:10.
