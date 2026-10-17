# Design: Next dates from orders — read by rule, the review queue and manual next dates

```
slug: next-date-extraction
status: approved
author: architect
date: 2026-10-16
approved_by: owner (nayanlhuzuri) on 2026-10-17
```

> **Owner's decision of 17 Oct 2026 (second), after the review stopped the cycle again — option B, which takes precedence over the first decision block and the note where they differ:**
> 1. **Firm only when two sources agree.** A date read from an order is `not_needed` (feeds the calendar and alerts) **only when it equals the court's own date for the case**: the case's `cases.next_hearing_date` (NAPIX `date_next_list`) or a cause-list listing of the case (`causelist_entries` joined to `causelists.list_date`) on that date. Every other reading — a plain listing date that does not match, a date after `after / on or after / from / onwards / not before / commencing / or any date thereafter / or on any subsequent date`, a returnable date, a period — is a suggestion that a person confirms (`pending`). The text rules decide only which date to suggest and whether the reading is unclear; they no longer make anything firm on their own.
> 2. **A suggestion becomes firm automatically when a matching court date arrives later**: when the dossier or Current Status sets `cases.next_hearing_date`, or a cause-list entry for the case is stored, equal to a pending suggestion's date, that row is closed as matched (system closure, `not_needed`-equivalent effect on the calendar, its review alert closed done) — no person needed. A match is checked when the reading is made and whenever the court's date for the case changes.
> 3. **Periods** stay counted from the order date and confirmed by a person, unless point 2 matches them. Add the period wordings found in the review: "adjourned by N weeks/days", numbers in words up to at least thirty with bracketed digits ("after 30 (thirty) days", "after 3 (three weeks)"), "on the expiry of N weeks", "on completion of N weeks from today", "list the matter N weeks".
> 4. Small points: confirm refuses a pending row whose date has already passed (409); unit tests for every example in the two reviews (including "is slated / likely to be listed on", "the connected case stands fixed on", negations, a counsel's prayer, the split after "No."); with point 1 these may read as suggestions rather than firm, which is acceptable.


> **Owner's decision of 17 Oct 2026, after the review stopped the cycle (two blocking findings), replacing the note where it differs:**
> 1. **Periods stay as designed:** "list the matter after two weeks" (and every other period) is counted from the order date and always goes to the user for confirmation (`order_period`, pending); it never drives the calendar or alerts until confirmed.
> 2. **A date after `after`, `on or after`, `from`, `onwards`, `not before`, `week commencing` / `commencing`** (e.g. "List the matter after 15.12.2026", "List on or after 20.11.2026", "from 20.11.2026 onwards", "in the week commencing 16.11.2026", "after the vacation, i.e. after 02.01.2027") is **not** a listing date: it is read as a suggested date that **needs confirmation** (`order_specific`, confidence 0.800, review pending), like the returnable date, never `not_needed`.
> 3. **Another matter's date, or two different dates, in the same direction** (e.g. "... since the connected appeal before the Division Bench is fixed on 20.11.2026", "as the writ appeal against the same order is fixed on 20.11.2026") reads **unclear** (enter item), whichever verb is nearest; the reported-date exclusion applies to the whole sentence, not only the verb next to the date. A period in the same sentence still wins over a reported date ("List after 3 weeks since ... fixed on 20.11.2026" is period +21 days, pending).
> 4. **Only plain directions are firm** (`list_on_date`, 1.000, not_needed): a listing verb followed by `on`/`for` and one date with no qualifier from point 2 and no other date in the sentence ("List on 15.11.2026", "List the matter on 15.11.2026 for hearing", "Fix 20.11.2026 for hearing", "Put up on 20.11.2026", "Next date: 20.11.2026"). A clear direction the patterns miss reads `unclear` (an enter item), never `none`.
> 5. Unit tests for every example above. Fix also the review's easy advisories in the same round: configured NEXT_DATE_UNCLEAR_DAYS everywhere (no default config); an enter item counts as answered by a manual row with `order_id` = that order even after a reread; visibility before the date and order checks (404 before 400). The remaining advisories (two orders sharing the latest order_date, a newer order without a stored document, case locks held for the whole batch) go to a follow-up row.


## Context
Backlog row 26, split out of `alerts-notifications` by its decision 3: "Next dates read from stored order text by
rule (specific dates as `order_specific`; period phrases counted from the order date and flagged for review), the
review queue (`next_dates.review`: confirm / reject), manual next dates (`NXT`); completes plan Phase 1 'alerts for
orders with specific dates'."

The plan:
- §5.3 and §5.7: "Next dates from orders: specific dates are read directly; periods such as 'list after two weeks'
  are identified by SourceTrace and counted from the order date; unclear directions are flagged for manual review
  (Figure 6)." The case overview shows "the latest order with the next date read".
- §6.2 / Figure 6: "When a new order appears for a tracked case, it is downloaded, its text is extracted, and the
  next-date direction is identified. The resulting date feeds the alerts calendar."
- §5.1: the department dashboard shows "items needing attention, including next dates read from new orders".
- §8 phases: Phase 1 "alerts for orders with specific dates"; Phase 2 "SourceTrace-based alerts for orders that
  state a period".
- §7 Table 8: "next dates (with source: specific date / period via SourceTrace / manual review)".
- Decisions log, 26 Sep 2026: "A specific date in the latest order is read by rule; a period ('after two weeks')
  produces a counted hint flagged for manual review and an alert; SourceTrace replaces the hint in Phase 2."
- DB_STANDARD §3: `NXT` reference numbers for `next_dates` where `source = manual`, allocated on the reviewer's
  office.

In place and reused:
- `next_dates` (migration 0001, as built in `domain/alerts.py::NextDate`): `ref_no` (optional), `case_id`,
  `next_date`, `source` (`causelist` / `current_status` / `order_specific` / `order_period` / `manual`), `order_id`
  (→ orders), `confidence` numeric(4,3), `needs_review`, `review_status` (`not_needed` / `pending` / `confirmed` /
  `rejected`), `reviewed_by_user_id` (SET NULL), `reviewed_at`, `note`, `created_by`, `updated_by`, unique
  (case_id, next_date, source, order_id) with nulls not distinct. Only `services/tracking.py` writes it today
  (source `current_status`, 3,347 rows in the dev database).
- `Permission.NEXT_DATES_REVIEW` (`next_dates.review`, "Review next dates"), enabled by default for the department
  head, department admin, department officer and directorate user (`_CASE_WORK`).
- `EventType.NEXT_DATE_EXTRACTED` (a court event on the timeline, `case_detail.COURT_EVENTS`), never written yet.
- `RecordType.NXT`, `services/refno.py::allocate_ref_no`.
- `services/calendar.py::hearing_rows`, shared by the hourly date sweep (`alerts.sweep_dates`, hearing alerts within
  7 days, critical at 48 hours) and `GET /calendar`: it already reads the case's latest `next_dates` row of source
  `manual` / `order_specific` / `order_period` whose review status is `not_needed` or `confirmed`.
- `services/dashboard.py`: the department block's `next_dates_to_review` count (pending rows of the department's
  cases, shown only to holders of `next_dates.review`) and `recent_order_next_dates`; the portal dashboard already
  renders both (empty today).
- The event scan (`alerts.scan_events`, `_handle_event`), `raise_alert`, `close_alert`, the `Resolver` recipients,
  `alert_rules.render_alert`, decision 4's 14-day age rule.
- `services/text_extract.py`: order PDFs get `document_text.full_text` (pymupdf), `documents.text_status`.
- The write pattern of `services/stages.py`: `require_function`, `require_visible_basis`, `lock_case`,
  `require_owned`, `acting_member` (`services/workflow_common.py`), `audit.write_audit`, `cases.emit_event`.
- The shared case filters (`api/filters.py::case_filter_query`, `services/case_filters.py::conditions`).

What the stored orders say (dev database, read-only queries of 16 Oct 2026): 253,901 order rows, 28,265 PDFs
stored, 22,206 order documents with text (27,477 order rows point to them: connected matters share one PDF).
Read over the last 1,500 characters of each text, a listing direction with a written date ("List this matter on
14.10.2026", "listed again on 10.09.2026", "adjourned to 06.04.2026", "re-notify on 12.11.2025", "come up … on
04.08.2026", "fixing the matter on 30.09.2026", "list all these matters on 24th September, 2026") appears in about
58%; a period ("List this matter after four weeks", "after two (2) weeks", "after 4(four) weeks", "after a week",
"adjourned for further 3 (three) weeks") in about 19%; "after the returnable date" with "returnable within four
weeks" in 0.4%; the rest have no listing direction (bail decided, notice issued and service steps only, "passed over
for the day", final orders) or a direction without a countable date ("after winter vacation", "after the ensuing
vacation", "in the 3rd week of August, 2026, on a date to be fixed by the Registry", "in due course", "sine die",
"before any other bench"). 4,705 cases have a current order (their latest order date) with text, 4,197 of them dated
in the last 120 days. No case is claimed in the dev database yet (0 active ownerships).

Not covered: SourceTrace reading of directions (row 37 `sourcetrace-next-dates`, after the SourceTrace query API;
it will write `order_period` rows with rule `sourcetrace` under this design without a schema change); compliance
directions in orders ("file affidavit within four weeks", row 27); OCR of scanned orders (no text → `no_text`,
decision 7); the portal screens (decision 1).

## Decisions
1. **Backend, API and CLI here; the portal screens are a new row.** This item builds the reader, the review queue,
   manual next dates, the API, the job and `aslms next-dates`. The screens — the review queue page, the case page's
   next-date block with "Enter next date", the reading column of the Orders tab, the dashboard count linking to the
   queue — go to a new backlog row `portal-next-dates` (after this one), added when this note is approved.
   Alternative: both in one item (doubles it; the API must settle first, as for rows 12/13 after rows 3/6).
   **Scope, flagged for the owner.**
2. **Periods are counted by rule in Phase 1 and always reviewed — deviation (recorded 26 Sep 2026).** The plan has
   SourceTrace identify periods (Phase 2). As recorded in the decisions log of 26 Sep, Phase 1 counts a period found
   by rule from the order date and stores it as an `order_period` hint that needs review; it never drives a hearing
   alert until a person confirms it. Row 37 later adds SourceTrace's reading as another `order_period` reading
   (rule `sourcetrace`). No AI is used here and nothing is sent anywhere: the reader works only on the stored text
   of court orders. **Deviation, flagged for the owner** (already in the log; restated because the plan wording
   differs).
3. **The rules (pure, versioned, in `services/next_date_rules.py`, `RULES_VERSION = 1`).** The text is normalised
   (whitespace collapsed, lower case, the spaced separators seen in the samples such as `31.08 .2026` joined), capped
   at 500,000 characters, and split into sentences.
   - *Listing sentence*: contains a listing verb — `list` / `listed` / `listing`, `re-notify` / `renotify`,
     `adjourned to`, `stand(s) over to`, `fix` / `fixed` / `fixing` (`on` / `for`), `come up`, `posted on|to`,
     `deferred to be listed`, `taken up on`, `placed on`.
   - *Date forms*: `dd.mm.yyyy`, `dd-mm-yyyy`, `dd/mm/yyyy`, two-digit years as 20yy, day-month order only (Indian
     form); written months (`24th september, 2026`, `25th of september, 2026`, `september 24, 2026`).
   - *Specific*: every date that follows a listing verb in a listing sentence (no other date in between, within 80
     characters) and lies in (order date, order date + `NEXT_DATE_MAX_AHEAD_DAYS` (548)] is a candidate. Exactly one
     distinct candidate date → `specific`, rule `list_on_date`. Two or more distinct candidates → `unclear`, rule
     `conflicting_dates` (common orders of connected matters can give each case a different date; the reader cannot
     tell which is this case's).
   - *Returnable date*: no listing candidate, but `returnable on|by <date>` within the window → `specific`, rule
     `returnable_date`, needs review (the matter is usually listed on the returnable date, but the order does not
     say so).
   - *Period*: a listing verb (or `adjourned for|by`) followed within the sentence by `after|for (further)? N
     day(s)|week(s)|fortnight|month(s)`, N in digits, words (`a`, `one` … `twelve`) or both (`2 (two)`, `4(four)`,
     `2 [two]`) → `period`, rule `list_after_period`; "after the returnable date" with `returnable within N weeks` in
     the same order → `period`, rule `after_returnable_period`; with `returnable on <date>` → `specific`, rule
     `returnable_date`. No listing direction but `returnable within N weeks|days` → `period`, rule
     `returnable_period`. Counting: days and weeks added to the order date; months as calendar months, clamped to the
     month's last day; a fortnight is 14 days. No weekend or holiday adjustment: the system has no court calendar,
     and every counted date is reviewed. The counted date must also fall inside the window.
   - *Unclear*: a listing sentence remains but yields no date (`vacation`, `nth week of <month>`, `first week of`,
     `after service`, `after the reply`, a written date outside the window) → `unclear`, rule `no_countable_date`.
   - *None*: no listing direction, or one that sets no date by design (`sine die`, `in due course`, `before any other
     bench`, `before appropriate bench`) → `none`.
   Precedence when several rules match one order: `list_on_date` (the court's own written date), then
   `list_after_period` and the two "after the returnable date" readings, then `returnable_date`, then
   `returnable_period`; `conflicting_dates` stops the reading as `unclear` whatever else matches.
   Alternatives: only the last listing sentence (missed "fixing the matter on" in mid-text orders and connected-case
   dates); a learned model (not allowed: AI only through SourceTrace).
4. **The reading is recorded on the order.** `orders` gains `next_date_status`, `next_date_found`, `next_date_rule`,
   `next_date_phrase` (the sentence, ≤ 400 characters, court text), `next_date_rules_version`, `next_date_read_at`
   (Data). Every order with a stored document is read once; `aslms next-dates read --reread` re-reads orders of an
   older rules version. Alternatives: a separate `order_readings` table (one more join for the Orders tab, no gain:
   one reading per order); deriving "read" from `next_dates` (orders with no direction would be re-read forever).
5. **Only an actionable reading becomes a `next_dates` row.** A row is written when (a) the order is the case's
   current order (no order of the case has a later `order_date`), (b) the reading is `specific` or `period`, and
   (c) the date is today or later (IST) at reading time. Other readings stay on the order only (the Orders tab and
   the measurement show them). This keeps the first run over 27,477 old order rows from filling the calendar and
   the review queue with dates long past, which Current Status has already superseded. Alternative: a row for every
   reading (≈ 21,000 rows, thousands of past "pending" hints).
6. **Review flags.** `list_on_date` → `order_specific`, confidence 1.000, `needs_review = false`,
   `review_status = not_needed`: it feeds the calendar and hearing alerts at once (plan Phase 1). `returnable_date` →
   `order_specific`, confidence 0.800, `needs_review = true`, `pending`. Every period rule → `order_period`,
   confidence 0.600, `needs_review = true`, `pending`. `needs_review` stays true after the review (it records that
   a person had to look). A pending row never drives a hearing alert or the calendar.
7. **The review queue holds two kinds of item, only for claimed cases.**
   - *confirm*: a `pending` row of a claimed case (an active primary owner).
   - *enter*: the current order of a claimed case read as `unclear` or `no_text` (a scanned order with no text
     layer), dated within `NEXT_DATE_UNCLEAR_DAYS` (30) of today, with no `manual` row of the case created since the
     order was read. The reviewer enters the date by hand (decision 10); there is no "dismiss": the item leaves the
     queue when a date is entered, a newer order of the case is read, or the 30 days pass.
   Unclaimed cases have no reviewer (alerts-notifications decision 5); their pending rows simply expire. The queue
   is sorted by `act_by` (the counted date for *confirm*, order date + 30 days for *enter*), then case.
8. **Two new review statuses close pending rows that nobody needs to review.** `superseded`: a newer order of the
   case was read and gave a row, or a manual date was entered for the case. `expired`: the date passed while
   pending (checked by every reader run). Both are system closures (`reviewed_by_user_id` stays NULL, `reviewed_at`
   NULL). Alternative: leave them pending (the queue would fill with moot items) or reuse `rejected` (it would
   claim a person decided).
9. **The effective next date from orders.** `calendar.hearing_rows` takes the case's latest row (by `created_at`,
   then `id`) of source `manual` / `order_specific` / `order_period` among `not_needed`, `pending` and `confirmed`,
   and uses it only when it is not `pending`. So a newer order whose hint awaits review stops an older order's date
   from raising hearing alerts, while a rejected or closed row falls back to the earlier one. The union with
   `cases.next_hearing_date` and the cause lists is unchanged. The same selection is the case overview's "next date
   from orders". Alternative: keep today's query, which skips pending rows (the older, probably stale date keeps
   alerting while the department reviews the new one).
10. **Who reviews and enters: `next_dates.review` with a working basis on a claimed case** — the rule of `stages.set`
    (custody-workflow decision 9; user-memberships decision 6): the function, a visible case, a working basis
    (owner, allotted, custody, counsel) in the same membership, the case claimed; the acting membership is
    `acting_member(..., NEXT_DATES_REVIEW)`. Manual entry uses the same function (no new function); its label stays
    "Review next dates" and its description becomes "Confirm or reject next dates read from orders, and enter next
    dates by hand" (seed refresh). The queue lists items of cases on which one of the caller's memberships holding
    the function has a working basis. Alternative: a separate `next_dates.enter` function (one more matrix row for
    the same people).
11. **Manual next dates (`NXT`).** `POST /cases/{ref}/next-dates` with `next_date` (today … today + 548 days),
    optional `note` (≤ 300 characters) and optional `order` (an order of the case the date answers, e.g. an *enter*
    item). Row: `source = manual`, `ref_no` = `ASLMS/<acting office code>/NXT/<yyyy>/<n>`, confidence 1.000,
    `not_needed`, `created_by` = the user, `order_id` = the order or NULL. It supersedes the case's pending rows and
    closes their review alerts. The note is shown to every reader of the case's next dates (the form says so: no
    internal remarks; it is not a case note and has no per-note visibility). The same date entered twice for the
    same order link answers 409 `already_entered`.
12. **Confirm and reject.** `confirm`: the row must be `pending` (409 `not_pending`); → `confirmed`,
    `reviewed_by_user_id`, `reviewed_at`, `updated_by`. `reject`: → `rejected` with optional `note` (≤ 300) and an
    optional replacement `next_date`, which writes the manual row of decision 11 in the same transaction linked to
    the same order (so "the counted date is wrong, it is 12 Nov" is one step). Both close the item's review alert
    (`done`, reason `confirmed` / `rejected`).
13. **One new alert kind, from the event scan.** `next_date_review` (`ref_alert_kind`, default severity `normal`):
    raised by the event scan from `next_date_extracted` events whose payload says `review` (a *confirm* or *enter*
    item), for claimed cases only, when the order date is within `ALERT_EVENT_MAX_AGE_DAYS` (14) of today
    (alerts-notifications decision 4: the first run over old orders raises nothing). Key
    `next_date_review:<order_id>`; `high` when the counted date is within `ALERT_HEARING_LOOKAHEAD_DAYS` (7); office
    = the owning department; recipients = the case recipients, as for `new_order`; `data`: `order_id`,
    `document_id`, `next_date_id`, `hearing_date` (counted date or null), `source`. Closed `done` by the review
    actions and `expired` by the hourly date sweep once the order has no queue item. A `list_on_date` reading raises
    no alert of its own: the date sweep turns it into the `hearing_due` alert when it comes within 7 days (Figure
    6: "the resulting date feeds the alerts calendar"). Alternative: raise from the reader directly (rejected by
    alerts-notifications decision 1: alerting must not roll back the court data).
14. **Events.** The reader emits `next_date_extracted` (court event, tracking card, on the timeline) for every row
    it writes and for every *enter* item it creates: payload `order_id`, `order_no`, `order_date`, `status`, `rule`,
    `next_date`, `next_date_id`, `review` (bool); dedupe `next_date_extracted:<order_id>:<rules_version>`. Two new
    event types (tracking card, shown to every reader of the case, like `stage_set`): `next_date_reviewed` (payload
    `next_date_id`, `action` confirm / reject, `next_date`, `office_code`) and `next_date_entered` (payload
    `next_date_id`, `ref_no`, `next_date`, `order_id`, `office_code`). No payload carries the note text.
15. **Audit.** People's actions: `next_date.confirm`, `next_date.reject`, `next_date.enter` (entity `next_date`,
    the case id, before/after with dates, statuses and the note's length and hash, never its text, as `stage.set`
    does). The system reading is not audited (system work, recorded in `job_runs` and the events, like the daily
    cycle; department-discovery decision 11). `aslms next-dates read --reread` is audited `next_dates.reread`
    (system actor `cli`, the counts).
16. **Locking: case, then order.** The reader selects candidate order ids without locks, then per order (one
    savepoint each) takes the case row lock (`lock_case`), re-reads the order `FOR UPDATE`, skips it if no longer
    `pending`, reads, writes. The review actions take the same case lock before touching the case's rows. One lock
    order everywhere; two reader runs never read one order twice.
17. **Visibility.** `next_dates` rows, readings and phrases are court data: readable by everyone who may see the
    case (`require_visible`). The queue and every write additionally need decision 10's working basis. A manual
    row's note follows the case. No query relies on the frontend to hide anything.
18. **Dashboard and case page data.** The department block's `next_dates_to_review` counts both kinds of queue item
    for the department (`next_dates.review_condition`); `recent_order_next_dates` leaves out `rejected`,
    `superseded` and `expired` rows. The case overview gains `next_date_from_orders` (decision 9's row, with its
    order and phrase) and `next_dates_to_review` (the case's queue items the caller may act on, 0 otherwise); the
    Orders tab items gain the reading fields.
19. **Dedupe.** `case_dedupe.portal_records` counts `next_dates` rows that are `manual` **or reviewed by a person**
    (`reviewed_by_user_id` not null), so a provisional case with a review is not merged silently.
20. **Settings** (`core/config.py`, `.env.example`, validated at start): `NEXT_DATE_BATCH` (orders per run, 1–5,000,
    default 500), `NEXT_DATE_UNCLEAR_DAYS` (7–120, default 30), `NEXT_DATE_MAX_AHEAD_DAYS` (90–1,095, default 548).
    No secret, no NAPIX call, no SourceTrace call.
21. **Migration 0018** (Data). Enum values cannot be dropped; the downgrade drops the columns, indexes, checks and
    the new type and leaves the two review-status values in place (harmless).

## Data
Migration **0018** (`0018_next_date_extraction.py`, new; no applied migration is edited).

In an `autocommit_block` (as 0014 and 0017 did): `ALTER TYPE review_status ADD VALUE IF NOT EXISTS 'superseded'`;
`ALTER TYPE review_status ADD VALUE IF NOT EXISTS 'expired'`. Then: `CREATE TYPE order_next_date_status AS ENUM
('pending', 'specific', 'period', 'unclear', 'none', 'no_text')`; the `orders` columns, checks and index below; the
`next_dates` checks and index below; reference rows inserted with `ON CONFLICT (code) DO NOTHING` (hard-coded, no
application import, as 0016): `ref_alert_kind` (`next_date_review`, "Next date to review", default_severity
`normal`), `ref_event_type` (`next_date_reviewed`, "Next date reviewed", is_tracking_card true;
`next_date_entered`, "Next date entered", is_tracking_card true). `aslms seed` carries the same rows and the new
`next_dates.review` description. Python: `ReviewStatus.SUPERSEDED`, `ReviewStatus.EXPIRED`, `OrderNextDateStatus`,
`AlertKind.NEXT_DATE_REVIEW`, `EventType.NEXT_DATE_REVIEWED`, `EventType.NEXT_DATE_ENTERED`. Existing orders get
`pending` from the column default; the job reads them in batches. No grant change (`aslms_app` already has SELECT /
INSERT / UPDATE on both tables). Downgrade: refuses while any `next_dates` row of source `order_specific`,
`order_period` or `manual` exists (legal-record history); otherwise drops what it added except the enum values and
deletes the three reference rows if unused.

Paragraphs for `docs/schema/schema.md`:

Group 6, the `orders` row gains (as-built note):
> (next-date-extraction, migration 0018) `next_date_status` (`order_next_date_status`: `pending` / `specific` /
> `period` / `unclear` / `none` / `no_text`; NOT NULL default `pending`), `next_date_found` (date NULL: the written
> or counted date), `next_date_rule` (varchar(40) NULL: `list_on_date`, `returnable_date`, `list_after_period`,
> `after_returnable_period`, `returnable_period`, `conflicting_dates`, `no_countable_date`), `next_date_phrase`
> (varchar(400) NULL: the court's sentence the reading rests on), `next_date_rules_version` (smallint NULL),
> `next_date_read_at` (timestamptz NULL). CHECKs `ck_orders_next_date_found` (`(next_date_status IN ('specific',
> 'period')) = (next_date_found IS NOT NULL)`) and `ck_orders_next_date_read` (`(next_date_status = 'pending') =
> (next_date_read_at IS NULL)`). Partial index `ix_orders_next_date_pending` (`created_at`) WHERE
> `next_date_status = 'pending'`. Written only by `services/next_dates.py` (the reader), from the stored text of the
> order's document; an order without a stored document stays `pending`; a document with `text_status = none` gives
> `no_text`. Court text only; nothing is sent to SourceTrace or any AI service. FKs unchanged.

Group 7, the `next_dates` row becomes:
> `next_dates` (transaction) | ref_no (unique; `ASLMS/<office>/NXT/<yyyy>/<n>` on the acting office, `manual` rows
> only), case_id (→ cases RESTRICT), next_date, source (`causelist` / `current_status` / `order_specific` /
> `order_period` / `manual`), order_id (→ orders RESTRICT; the order read, or the order a manual date answers),
> confidence numeric(4,3) (1.000 written date, 0.800 returnable date, 0.600 counted period), needs_review,
> review_status (`not_needed` / `pending` / `confirmed` / `rejected` / `superseded` / `expired`), reviewed_by_user_id
> (→ users SET NULL), reviewed_at, note (≤ 300, manual and rejected rows; shown to every reader of the case),
> created_by, updated_by (→ users SET NULL), created_at, updated_at | Unique (case_id, next_date, source, order_id)
> NULLS NOT DISTINCT. CHECKs `ck_next_dates_manual_ref` (`(source = 'manual') = (ref_no IS NOT NULL)`),
> `ck_next_dates_pending_review` (`review_status <> 'pending' OR needs_review`), `ck_next_dates_reviewed`
> (`review_status NOT IN ('confirmed', 'rejected') OR reviewed_at IS NOT NULL`). Partial index
> `ix_next_dates_pending` (`case_id`, `next_date`) WHERE `review_status = 'pending'`. Written by
> `services/tracking.py` (`current_status`) and `services/next_dates.py` (order readings, reviews, manual dates;
> design `next-date-extraction`). A reading becomes a row only for the case's current order with a date today or
> later; `superseded` and `expired` are system closures of pending rows. The effective next date from orders is the
> latest `manual` / `order_*` row among `not_needed`, `pending`, `confirmed`, used only when not `pending`. Never
> deleted; changed only by review.

Group 0 (reference data), notes added:
> `ref_alert_kind` gains `next_date_review` (default severity `normal`); `ref_event_type` gains
> `next_date_reviewed` and `next_date_entered` (tracking card); next-date-extraction, migration 0018 and the seed.
> `ref_permission`: `next_dates.review` described as "Confirm or reject next dates read from orders, and enter next
> dates by hand" (seed only).

## Services
- **`services/next_date_rules.py`** (new, pure, no database): `RULES_VERSION = 1`; `Reading` (frozen dataclass:
  `status`, `date`, `rule`, `phrase`, `needs_review`, `confidence`); `read_order_text(text: str | None, order_date:
  date, *, max_ahead_days: int = 548) -> Reading` (decision 3; `None` or blank text → `no_text`); `parse_dates(sentence)
  -> list[date]`; `count_period(order_date, n, unit) -> date`; `WORD_NUMBERS`; the verb and phrase patterns as
  compiled module constants. Never raises on hostile text (bounded patterns, no nested quantifiers).
- **`services/next_dates.py`** (new):
  - `is_current(session, order) -> bool`: no order of the case has a later `order_date`.
  - `read_order(session, order, *, today, cfg) -> str` (decision 5, 6, 8, 14): text from `document_text` (or
    `no_text` when the document's `text_status` is `none`); writes the reading columns; when actionable inserts the
    `next_dates` row (`ON CONFLICT DO NOTHING` on the unique key), marks the case's other `pending` rows
    `superseded`, emits `next_date_extracted`; for an *enter* item emits `next_date_extracted` with `review = true`
    and no row. Returns the outcome for the counters.
  - `read_pending(session, *, batch, now=None, order_id=None, cfg) -> dict` (decision 16): candidates are `pending`
    orders with a document whose `text_status` is `extracted` or `none`, oldest first; one savepoint per order;
    then `expire_stale(session, today)`. Counters: `claimed`, `specific`, `period`, `unclear`, `none`, `no_text`,
    `rows_written`, `review_items`, `superseded`, `expired`.
  - `expire_stale(session, today) -> int`: `pending` rows with `next_date < today` → `expired`.
  - `reread(session, actor, *, all_versions=False) -> int`: orders read under an older `RULES_VERSION` (or all)
    back to `pending`; audited `next_dates.reread`.
  - `review_condition(session, user_or_department)` and `review_items(session, user, *, kind=None, filters=None,
    limit, offset) -> Page` (decisions 7, 10, 17): the union of *confirm* rows and *enter* orders, restricted by
    `visibility.working_condition_for(session, user, Permission.NEXT_DATES_REVIEW)` and the case filters; each item
    names the departments the caller may act for.
  - `confirm(session, actor, user, next_date_id) -> NextDate`; `reject(session, actor, user, next_date_id, *,
    note=None, replacement=None) -> tuple[NextDate, NextDate | None]`; `enter(session, actor, user, case, *,
    next_date, note=None, order_id=None, member=None) -> NextDate` (decisions 10–12): `require_function`,
    `require_visible_basis`, `lock_case`, `require_owned`, `acting_member(..., NEXT_DATES_REVIEW)`; write; supersede;
    close the review alert with `alerts.close_alert(..., DONE, reason)`; emit `next_date_reviewed` /
    `next_date_entered`; `write_audit`. Errors use the workflow error types (400 `bad_field`, 403 `forbidden` /
    `not_working_on_case`, 404, 409 `not_owned` / `not_pending` / `already_entered`).
  - `effective_for_case(session, case) -> NextDate | None` (decision 9) and `case_next_dates(session, user, case, *,
    limit, offset) -> Page` (all sources, newest first, `effective` flagged).
  - `next_date_out(session, row) -> dict` (id, ref_no, next_date, source, confidence, needs_review, review_status,
    order {id, order_no, order_date, document_id, phrase, rule}, note, reviewed_by {name} and reviewed_at, created_by
    {name}, created_at).
- **`services/visibility.py`**: `working_condition_for(session, user, permission) -> ColumnElement[bool]` — the OR of
  the working-basis conditions (`WORKING_BASES`) of the memberships that hold the permission; `false()` when none.
- **`services/calendar.py`**: `hearing_rows` selection per decision 9 (`NEXT_DATE_OPEN = (not_needed, pending,
  confirmed)`; the outer filter drops `pending`); the module docstring updated.
- **`services/alerts.py`**: `_handle_event` branch for `next_date_extracted` with `review = true` (decision 13);
  `sweep_dates` closes open `next_date_review` alerts whose order has no queue item (`closed_next_date` counter).
  **`services/alert_rules.py`**: `render_alert` text for `next_date_review` ("Next date to confirm: <date> counted
  from the order of <date>" / "Enter the next date: the order of <date> gives no date that could be read").
- **`services/dashboard.py`**: decision 18. **`services/case_detail.py`**: overview `next_date_from_orders` and
  `next_dates_to_review`; Orders items gain `next_date_status`, `next_date_found`, `next_date_rule`,
  `next_date_phrase`; `OWNERSHIP_EVENTS` (shown to every reader) gains `next_date_reviewed`, `next_date_entered`.
- **`services/case_dedupe.py`**: decision 19. **`services/access_seed.py`**: the new description.
  **`services/seed.py`**: the three reference rows.
- **`cli/next_dates.py`** (new group `aslms next-dates`): `read [--batch N] [--all] [--order ID] [--reread
  [--all-versions]] [--dry-run]` (`--all` loops until no candidate is left; `--dry-run` reads and prints counts
  without writing); `status` (orders by `next_date_status` and rule, rows written by source and review status, queue
  size by kind); `sample --status S [--rule R] [--n 20] [--seed K]` (order date, CNR, reading, date and phrase, for
  the hand check). Registered in `cli/main.py` and its docstring.

## API
All responses in IST dates; errors as the workflow routers map them.

| Method and path | Function (`Permission`) | Request | Response | Rule |
|---|---|---|---|---|
| `GET /next-dates/review` | `next_dates.review` | `kind` (`confirm` / `enter`, optional), the shared case filters (`case_filter_query`), `limit`, `offset` | `{items: [{kind, id (next_date id for confirm, order id for enter), case: CaseRef, order: {id, order_no, order_date, document_id}, phrase, rule, next_date (null for enter), act_by, alert_ref_no, departments: [office code]}], total}` | Decisions 7, 10, 17: only cases on which a membership holding the function has a working basis; claimed cases only. |
| `POST /next-dates/{id}/confirm` | `next_dates.review` | `{}` | `NextDateOut` | Decisions 10, 12. 404 unknown or not visible; 403 `not_working_on_case` / `forbidden`; 409 `not_owned` / `not_pending`. |
| `POST /next-dates/{id}/reject` | `next_dates.review` | `{note?: str ≤ 300, next_date?: date}` | `{rejected: NextDateOut, entered: NextDateOut \| null}` | Decisions 11, 12; same errors; 400 for a replacement date outside today … today + 548. |
| `POST /cases/{ref}/next-dates` | `next_dates.review` | `{next_date: date, note?: str ≤ 300, order?: uuid}` | `NextDateOut` (201) | Decisions 10, 11. 400 date outside the range or an order of another case; 409 `already_entered` / `not_owned`. |
| `GET /cases/{ref}/next-dates` | `cases.view_scope` or `cases.view_all` | `limit`, `offset` | `{items: [NextDateOut + effective: bool], total}` | `require_visible`; every source. |
| `GET /cases/{ref}` (changed) | unchanged | — | gains `next_date_from_orders: NextDateOut \| null`, `next_dates_to_review: int` | Decision 18. |
| `GET /cases/{ref}/orders` (changed) | unchanged | — | items gain `next_date_status`, `next_date_found`, `next_date_rule`, `next_date_phrase` | Court text, case readers. |
| `GET /dashboard` (changed) | unchanged | — | `attention.next_dates_to_review` counts both kinds | Decision 18. |

`NextDateOut`: `id`, `ref_no`, `next_date`, `source`, `confidence`, `needs_review`, `review_status`, `order` (`id`,
`order_no`, `order_date`, `document_id`, `phrase`, `rule`, or null), `note`, `reviewed_by` (`name`, or null),
`reviewed_at`, `created_by` (`name`, or null), `created_at`. `{id}` accepts the row's uuid or its `ref_no`. The
router is `api/routers/next_dates.py`; `schemas.py` gains the models; `frontend/src/lib/api/schema.d.ts` is
regenerated (no screen change in this item).

## Jobs
- **`aslms.next_dates_read`** (Celery beat `next-dates-read`, `crontab(minute="2-59/5")`, two minutes after
  `extract-text`): `next_dates.read_pending(batch=NEXT_DATE_BATCH)` in one `job_runs` row (job `next_dates_read`,
  counters, `partial` when an order failed — the failure recorded in `source_failures` kind `next_date_read`, ref
  the order id, resolved on a later success). No queue row, no NAPIX call. At 500 orders a run the first pass over
  the dev database's ~27,500 order rows takes about 4.5 hours; `aslms next-dates read --all` does it at once.
- The hourly date sweep (existing) closes `next_date_review` alerts (decision 13) and, through
  `calendar.hearing_rows`, raises `hearing_due` alerts for order dates within 7 days.
- The 5-minute event scan (existing) raises `next_date_review` alerts.

## Tests
Unit (`tests/unit/test_next_date_rules.py`, short excerpts of public court orders like those in Context):
- each listing form gives `specific` with the right date: "List this matter on 14.10.2026", "listed again on
  10.09.2026", "adjourned to 06.04.2026", "re-notify on 12.11.2025", "come up for consideration … on 04.08.2026",
  "fixing the matter on 30.09.2026", "list all these matters on 24th september, 2026", "25th of september, 2026",
  "16-07-2025" and "08/04/2026" forms, "31.08 .2026" spacing, a two-digit year;
- dates outside the window are ignored ("order dated 25.05.2026", "affidavit dated 17.10.2025", a listing date
  before the order date, one more than 548 days ahead);
- two different listing dates → `unclear` `conflicting_dates`; the same date twice → `specific`;
- "Notice is returnable by 25.3.2015" alone → `specific` `returnable_date`, needs review;
- periods: "after four weeks" (+28), "after two (2) weeks", "after 4(four) weeks", "after 2 [two] weeks", "after a
  week", "after 10 days", "after a fortnight", "adjourned for further 3 (three) weeks", "after two months" from 31
  Dec → 28/29 Feb (clamped), "list after the returnable date" with "returnable within four weeks";
- the specific rule wins over a period in the same order;
- "after winter vacation", "3rd week of august, 2026", "after service of notice" → `unclear`; "sine die", "in due
  course", "before any other bench", a bail order with no listing → `none`; empty text → `no_text`;
- a 500,000-character hostile text reads in under a second (no catastrophic backtracking).

Database (`tests/db/test_next_dates_read.py`, `test_next_dates_review.py`, `test_api_next_dates.py`, with a
`next_dates_support.py` building cases, orders, documents and text):
- the reader writes a not-needed `order_specific` row for the current order with a future date and emits
  `next_date_extracted`; an older order of the case, a past date, a `none` reading write no row but record the
  reading on the order;
- a period reading writes a pending `order_period` row (confidence 0.600) and supersedes the case's earlier pending
  row; `expire_stale` expires a pending row whose date passed;
- an `unclear` current order of a claimed case is an *enter* item; it leaves the queue after a manual date, a newer
  read order, or 30 days; an unclaimed case gives no queue item;
- a document with `text_status = none` gives `no_text`; an order without a document stays `pending`; a second run
  reads nothing (idempotent); `--reread` resets only older-version orders and is audited;
- the CHECK constraints reject a found date without status and a pending row without `needs_review`;
- calendar: a pending newer row hides an older not-needed row's date; a rejected newer row restores it; a confirmed
  row drives a `hearing_due` alert in the sweep;
- confirm: needs the function, visibility and a working basis (403 `not_working_on_case` for a State reader with
  the function granted, 404 for an invisible case), 409 on a non-pending row and on an unclaimed case; writes
  `confirmed`, the reviewer, the event, the audit row (no note text), closes the review alert;
- reject with a replacement date writes the `NXT` manual row on the acting office (ref format), links the order,
  supersedes nothing else wrongly, two audit rows;
- enter: ref_no allocation per office and year, range checks, 409 `already_entered`, an order of another case → 400,
  supersedes pending rows and closes their alerts, `next_date_entered` on the timeline for every case reader;
- event scan: a review event for a claimed case with a recent order raises one `next_date_review` alert (high within
  7 days), none for an old order or an unclaimed case, dedupe on a re-scan; the sweep expires it when the item
  leaves the queue;
- queue API: lists only items the caller may act on (two memberships, one without the function), the shared
  filters narrow it, `kind` filters, paging and totals; a directorate user sees items of cases allotted to the unit;
- dashboard count equals the queue size for the department; `recent_order_next_dates` omits closed rows; the
  overview's `next_date_from_orders` follows decision 9; Orders items carry the reading fields;
- `portal_records` counts a reviewed row; nothing in the reader or the review path calls the SourceTrace connector
  or the NAPIX client (the fake connector records no call; the scripted gateway records none);
- migration: upgrade from 0017 on a database with orders and `current_status` rows; downgrade refused with an
  `order_specific` row present.

## Verification
1. `ruff check` clean; `pytest -q` green.
2. Dev database: `alembic upgrade head` (0018), `aslms seed`; `aslms next-dates read --dry-run --all` then `aslms
   next-dates read --all`; `aslms next-dates status`. Expected on today's data (±5 points): of the orders with text,
   about 55–60% `specific`, 17–21% `period`, the rest `unclear` / `none` (a few `no_text`); rows written only for
   current orders with dates from today on (at most ~4,700 cases; none past).
3. Hand check against the PDFs (`aslms next-dates sample --status specific --n 20`, then `--status period --n 20`,
   then `--status unclear --n 10`), opening each order: **no wrong date among the 20 specific readings**; every
   counted period date equals the order date plus the period in the phrase; unclear ones genuinely give no countable
   date. Results recorded in the build report and the decisions log.
4. Claim two dev cases through the API as a department admin (the dev database has none claimed): one whose current
   order has a written date within 7 days, one with a counted period. Next hourly sweep (or `aslms alerts run`): a
   `hearing_due` alert for the first; the event scan raises a `next_date_review` alert for the second only if its
   order is within 14 days (otherwise check the queue). `GET /next-dates/review` lists the second; confirm it; the
   calendar (`GET /calendar`) shows its date; enter a manual date on the first; `GET /cases/{ref}/next-dates` shows
   the `NXT` ref; `GET /audit?case=…` shows `next_date.confirm` and `next_date.enter`.
5. `docker compose up` (worker and scheduler): the `next-dates-read` beat appears and a `job_runs` row
   `next_dates_read` is written every five minutes with zero claims once the backlog is read.

## Open questions
None. Owner checks at approval: decision 1 (portal screens as a new row `portal-next-dates`), decision 2 (rule-counted
period hints, always reviewed, as recorded on 26 Sep), decision 5 (no rows for old orders or past dates), decision 7
(the 30-day window for *enter* items).

## Deviations
Recorded by the developer while building (smallest reasonable choices where the note was silent):
1. **The 500,000-character cap keeps the end of the text.** Decision 3 caps the text but does not say which part.
   Combined PDFs in the dev database run past 500,000 characters (one of 663 pages) and their direction closes the
   text; reading the first 500,000 lost it. The reader keeps the last 500,000 characters.
2. **Listing verbs and directions, small additions found on the dev orders.** `re-post on|to` counts like `posted
   on|to` ("Re-post on 15.07.2026"); "list accordingly" is a direction (an `unclear` item when no date follows). A
   list / fix / post verb that reports a date rather than directs one is not a candidate: after `is`, `are`, `was`,
   `were`, `been`, `already`, `now`, `scheduled`, `tentatively`, `presently`, `currently` (up to two words between:
   "which is fixed on", "has been listed on", "is scheduled to be listed on", "is now posted on"), and a gerund
   after "of" ("the next date of listing … is on"); "this Court is fixing the matter on" still directs. A `;`
   between the verb and the date separates clauses ("list after 2 weeks; file the affidavit by <date>"). `returnable
   in N weeks` is read like `returnable within N weeks`, and "after a period of N weeks" like "after N weeks". On
   6,000 dev orders with text: 64.8% `specific`, 18.9% `period`, 9.8% `unclear`, 6.5% `none` (design expected
   55–60% ± 5 and 17–21%).
3. **Several period sentences in one order:** the last one in the text is used (the direction closes an order);
   always reviewed anyway.
4. **`next_date_read_at` is the database clock** (`now()`), the same clock as `created_at` of a manual row that the
   *enter* rule compares it with.
5. **A *confirm* item also needs its date to be today or later** (a pending row whose date passed is expired by the
   next reader run in any case); the queue, the dashboard count, the case count and the alert closure use the one
   queue query.
6. **Reject's note stays on the rejected row;** the replacement manual row carries no note.
7. **Alert closures:** the review actions close the case's `next_date_review` alerts whose order has no queue item
   left, `done` with reason `confirmed`, `rejected` or `entered`; the hourly sweep closes the rest `expired` with
   reason `no_review_item`. The alert `data` also carries `order_no` and `order_date` (for the title and body).
   `AlertConfig` gains `next_date_unclear_days` (from `NEXT_DATE_UNCLEAR_DAYS`).
8. **`aslms next-dates read --dry-run`** reads pending orders only (it cannot be combined with `--reread`) and prints
   counts by status and rule plus how many rows it would write and items it would raise.
9. **Two existing test fixtures** wrote `next_dates` rows the new CHECKs refuse (a manual row without its `NXT` ref,
   a confirmed row without `reviewed_at`); they now write valid rows. `test_migration_0017` expects the head
   revision after its refused downgrade (it now passes through 0018).
10. **Not every list / fix / come-up word before a date is a listing direction** (review finding). Decision 3
    promises that `list_on_date` is the court's own written date, but "file a list of documents by <date>", "the
    time fixed for filing … ends on <date>" and "come up with a fresh representation by <date>" read as
    `list_on_date` and outranked the real direction. A listing verb and its date are no candidate when: the word
    is the noun "list" (followed by "of", or after `a`, `an`, `the`, a possessive, `such`, `any`, `said`, `same`,
    `cause`, `daily`, `weekly`, `supplementary`, `additional`, `fresh`, `revised`, `separate`, `detailed`,
    `complete`, `full`; "this list matter" still directs); it is "come up with" (not a direction either); the
    date follows `by`, `within`, `till`, `until` or `before` (a deadline, "on or before" included), or `ends`,
    `expires`, `expiry` or `lapses` stands between; or a `fix` verb follows `time`, `period`, `deadline`, `limit`
    or `limitation` (up to two words between) or is "fixed for filing / submitting / submission / depositing /
    deposit / paying / payment / complying / compliance / furnishing". "cause list on" is no direction. On all
    31,172 dev orders with text 7 readings change and no other: 4 wrong `list_on_date` dates from "shall fix a
    date for giving a personal hearing … on or before <date>" now read the order's returnable date (reviewed),
    "the next date fixed for filing the amended plaint is <date>" becomes `unclear` (its "List accordingly"), and
    2 "come up with" sentences go from `unclear` to `none`. `RULES_VERSION` stays 1: no reading has been stored
    yet (no order in the dev database carries a rules version).
11. **A newer order without a usable date closes the dates of older orders** (review finding). Decision 8 supersedes
    only when the newer order gives a row, so a disposal ("the writ petition is disposed of", read `none`), an
    `unclear` or `no_text` order, or a date already past left an older order's date driving the calendar and
    `hearing_due` alerts, and an older pending row confirmable (the plan's "alerts generated from the most recent
    order"; the approved "items leave the list when a newer order arrives"). When the case's current order is read
    without a usable date, `supersede_older` marks `superseded` every open (`not_needed`, `pending`, `confirmed`)
    order or manual row linked to an order with an earlier `order_date`, and every manual row without an order
    created before this order's date (00:00 IST). A confirmed row keeps its reviewer and review time (the
    confirmation stays on the timeline and in the audit log). Rows of orders of the same date and manual answers to
    this order stay; Current Status and the cause lists still feed the calendar; the hourly sweep closes the
    `hearing_due` alerts (`date_changed`) and the review alerts (`no_review_item`) that lose their date. When the
    newer order does give a row, decision 9's fallback after a rejection is unchanged. `superseded` is therefore no
    longer only a closure of pending rows (`schema.md`, Group 7, updated).
12. **The owner's decision of 17 Oct 2026, as built** (smallest choices where it was silent):
    - *Rule name.* A date after `after`, `on or after`, `from`, `not before`, `commencing` (or followed by `onwards`,
      `or thereafter`) is rule `qualified_date` (`specific`, `order_specific`, 0.800, pending); `orders.next_date_rule`
      is a varchar, so no migration (`schema.md` Group 6 and 7 updated).
    - *What is plain.* A date is firm only when the words just before it are `on`, `on the`, `for`, `to`, `on
      <weekday>, i.e.`, only the matter listed ("list this matter again 13.02.2026"), or nothing ("Fix 20.11.2026 for
      hearing", "adjourned to 06.04.2026", "Next date: 20.11.2026"). Any other word before the date ("tomorrow, i.e.",
      "on Monday," with `or thereafter`, "in the week commencing") makes it `qualified_date`, so the list of
      qualifiers is open, not closed. `put up` and `next date:` are listing verbs; `fix <date>` and `put up` are
      directions, so a "Put up after the vacation" reads `unclear`, not `none`.
    - *Each date belongs to the nearest listing verb before it* (point 3, "whichever verb is nearest"); a date the
      sentence reports for another matter — after `is` / `are` / `been` / ... as before, or a participle right after
      another proceeding ("the connected appeal fixed on", "the writ petition listed on"; not after "matter" or
      "case", and never "listed again") — makes every date of that sentence unusable. With a period in the sentence
      the period is read (pending); with a direction of its own the sentence reads `unclear` `conflicting_dates`;
      when the only direction is the reporting verb itself ("This matter is to be listed on <date>") it reads
      `unclear` `no_countable_date`, never `none`. "shall now be listed on" is not a report.
    - *"No other date in the sentence"* (point 4) counts only dates after the order date: the order's own date in its
      heading, an affidavit or an earlier hearing date do not make a listing date unclear; a later deadline ("file by
      20.10.2026 and list on 30.10.2026") does (`conflicting_dates`, as the owner wrote).
    - *Page headers* of the court's PDFs ("Page No.# 2/2") are removed before reading: they fell between "on" and
      the date.
    - *Measured* on the 25,300 distinct order texts of the dev database against the rules before this round: 58.6% →
      59.0% `list_on_date`; 66 readings (0.3%) move from `list_on_date` to `qualified_date` (every one "after
      <date>", "week commencing", "tomorrow, i.e." or similar), 57 to `conflicting_dates` (another matter's date, or
      a deadline in the sentence), 3 to `no_countable_date` ("in the cause list on", "1st week of December"); 40
      directions move from `none` to `unclear` ("List next week", "Put up before the Bench ..."); 24 "Put up on
      <date>" and 16 page-header cases gain their written date. `RULES_VERSION` stays 1: no reading is stored yet
      (all 280,089 dev orders are `pending`).
13. **The review's easy advisories:** `NextDateConfig` has no defaults any more; every caller passes the configured
    one or takes `NextDateConfig.from_settings()` (the API passes it to confirm, reject and enter and to their alert
    closures; the case overview's count and the alert sweep read the settings). An *enter* item counts as answered by
    a manual row linked to the order (`order_id`) whatever its time, so a `--reread` does not ask again, and the
    reader raises no review item for such an order. Confirm, reject and enter check the function and the case's
    visibility (404) before any field (400). The rest (two orders of one `order_date`, a newer order without a stored
    document, case locks held for the whole batch) are for a follow-up row.
14. **The second review of 17 Oct 2026 (three blocking findings), as built.** The user's instruction for this round:
    "if something is mentioned like list the matter after two weeks, you calculate it based on the order date and
    ask the user for a confirmation".
    - *The words between the verb and the date count.* A date is firm only when, between its listing verb and the
      date, stand only the matter listed and how: a closed word list (`this`, `the`, `matter(s)`, `case(s)`,
      `again`, `before the Division Bench`, `Lawazima Court`, `for hearing / admission / motion / consideration /
      orders / final disposal`, `in the admission column`, `along with`, `under the same heading`, `positively`, ...)
      and case numbers ("along with WP(C) 1234/2026", "AB/1353/2026"), then `on`, `on the`, `for`, `on <weekday>,
      i.e.` or nothing. Any other word makes it a date to confirm (`qualified_date`, pending). Another act or actor
      between them (`liberty`, `leave`, a modal, `to <verb>` other than `to be`, a party, `counsel`, `interim`,
      `stay`, `extended`, `file`, `appear`, `mention`, `submit`, `comply`, `deposit`, `pay`) makes the date no
      candidate at all; so does a period that the date does not spell out ("list after 2 weeks, and the respondents
      to file their reply on <date>" is the period, +14 days, pending). A period spelled out by the date ("after 2
      weeks, i.e. on <date>", "after 2 weeks, on <date>", "after 3 weeks fixing <date>") gives the written date as
      a date to confirm; "after" anything else ("after receipt of the records on <date>") also gives a date to
      confirm.
    - *A period anywhere in the order means no firm date.* When an order also lists after a period in another
      sentence ("List after 2 weeks. Let the connected case also be listed on <date>"), the written date is still the
      one suggested (the design's "the specific rule wins over a period"), but as `qualified_date`, pending, even
      when it equals the counted date. This replaces the checklist's firm reading of that case.
    - *`to` is not plain.* "to" is gone from the plain words before a date (the verbs that take it, `adjourned to`,
      `stands over to`, `posted to`, end with it); `up to`, `upto` and `prior to` join the deadline words (no
      candidate); `subsequent to` is a date to confirm.
    - *More reported forms (point 3).* A participle (`listed`, `fixed`, `posted`) right after a case number ("WA
      5/2026 listed for", "WP(C) 1234/2026 listed on", "5 of 2026 fixed on") or after `connected / other / another /
      analogous / tagged / companion / related / leading / main case(s) / matter(s)` reports another matter's date;
      so do `stands` / `stood` right before it (not after "matter" or "case": "the matter stands posted on" still
      directs) and `which` up to two words before it ("which stands fixed on"). `come up`, `adjourned`, `stand(s)
      over`, `taken up`, `placed` and `re-notify` report after `has / have / had (been)`, `was / were` or `which ...`
      ("which will come up on", "has been adjourned to"); "this case is adjourned to <date>" still directs.
    - *Measured* on the 25,343 distinct order texts of the dev database against the rules of deviation 12: 14,645
      `list_on_date` (57.8%, was 59.0%); 293 move from `list_on_date` to `qualified_date` (99 because the order also
      lists after a period elsewhere, often an earlier order in the same PDF or the counsel's prayer; the rest
      "tomorrow, i.e.", "next Monday i.e.", "before the Lok Adalat", "as prayed for", "after 2 weeks, i.e. on" and
      similar), 4 to `no_countable_date` ("the affidavit filed by the petitioner on <date>", "as prayed for by the
      parties on <date>"), 1 to `none` ("fixing the date of appearance on"); 5 move from `qualified_date` to
      `list_on_date` ("listed again 21st of May, 2026"), 1 conflict becomes `list_on_date` (a superannuation date
      no longer counted) and 1 becomes `no_countable_date`. `RULES_VERSION` stays 1: no reading is stored yet.
15. **The third review of 17 Oct 2026 (one blocking finding), as built.** The `stands` / `stood` form of deviation 14
    was not built: the pattern held a literal backspace character where a word boundary was meant, so "The connected
    appeal stands fixed on <date>" read as a firm date of this case. The character is now the word boundary, and a
    unit test fails on any control character in the rules source. As built, with tests: "The connected appeal stands
    fixed on <date>", "WA 5/2026 stands fixed on <date>" and "The connected writ appeal stood fixed on <date>" read
    `none` (a report of another matter with no direction for this case, as "The connected appeal is fixed on <date>"
    already did; nothing reaches the calendar); "List this matter along with WA 5/2026 that stands fixed on <date>"
    reads `unclear` (`conflicting_dates`, an enter item); "The matter stands posted on <date>" and "This case stands
    fixed on <date>" still direct. The owner's reminder for this round is unchanged and already built (decision
    point 1, tests in `test_periods_are_counted_from_the_order_date`, now also "List the matter after two weeks."):
    a period is counted from the order date and always goes to a person to confirm, never to alerts first.
    - *Measured* on the 25,391 distinct order texts of the dev database against the rules of deviation 14: exactly
      one reading moves, `list_on_date` to `no_countable_date` ("the matter hesitantly stands posted to <date>": an
      adverb between "matter" and "stands" hides the exception, so this case's own date goes to a person to enter;
      the cautious side, left as is). `list_on_date` stays 14,650 (57.7%). `RULES_VERSION` stays 1: no order has
      been read yet (all 284,629 orders are `pending`).
16. **The owner's second decision of 17 Oct 2026 (option B), as built** (smallest choices where it was silent):
    - *Who decides firm.* The rules no longer make anything firm: every dated `Reading` has `needs_review = true`
      (`list_on_date` still names a plain direction, confidence 1.000). `next_dates.read_order` writes the row
      `not_needed` (with `needs_review = false`) only when the date equals `cases.next_hearing_date` or the case has a
      `causelist_entries` row on a list of that `list_date`; otherwise `pending`. This holds for every reading with a
      date (plain, qualified, returnable, period): a period counted to the court's own date needs no click either.
    - *A later match* (point 2) is a system closure to `not_needed` with `needs_review` left true, no reviewer and no
      review time — no new enum value and no migration, and `needs_review = true` with `reviewed_at` NULL on a
      `not_needed` order row is how "made firm by the court's date" is told apart. Only order rows dated today or
      later are matched (a past pending row still expires). No event is written for the match (the court's own
      `next_date_changed` / listing is on the timeline already); the review alert of the order is closed `done`,
      reason `matched`, when its order has no queue item left, and the hourly sweep closes such an alert `done` /
      `matched` too (instead of `expired` / `no_review_item`) when it finds it first.
    - *When the match is checked.* At reading time; at the start of every reader run (`read_pending`, every five
      minutes, all cases, before the batch takes any case lock; counter `matched`); and inline, inside a savepoint,
      after `cases.apply_dossier`, after `cases.apply_status` when `next_hearing_date` changed, and after
      `causelists.apply_entries` for the cases the list touched (`next_dates.match_after_court_change`). A failure
      there is recorded in `source_failures` (kind `next_date_match`) and never fails the court data; the next
      reader run matches again. The inline match takes no case lock of its own (the dossier and status paths
      already hold the case row; the update re-checks `pending` under READ COMMITTED, so a review in between wins).
      Cases merged by the dedupe sweep are matched by the next reader run.
    - *Period wordings* (point 3): `adjourned by N ...`, `on / upon / after (the) expiry / completion / lapse of N
      ...`, the bare "list the matter N weeks (hence)", numbers in words up to ninety-nine ("twenty one",
      "thirty-five") alone or with digits in brackets either way round ("30 (thirty) days", "fourteen (14) days"),
      and the unit inside the bracket ("3 (three weeks)"). The two spellings must still agree.
    - *Small points* (point 4): confirm answers 409 `date_passed` for a pending row whose date is before today (reject
      is still allowed); "or any (other / subsequent / later) date (thereafter)" and "or on any subsequent date" count
      as "on or after" (`qualified_date`). The review examples now read: "is slated / likely / expected / due to be
      listed on" and "likely to come up on" report another matter's date (with no direction of this case → `unclear`
      `no_countable_date`, an enter item; inside a direction → `conflicting_dates`); "the connected / other ...
      case(s) / matter(s) stands / stood fixed on" reports too (`none` alone); a negation up to two words before the
      verb ("shall not be listed on", "need not be listed on") is no listing date; a prayer verb before the verb in
      the same sentence ("prays", "seeks", "requests", "submits that", "urges that", "contends that"; not "as prayed
      for", not the noun "at the request of") with no grant word ("allowed", "granted", "accepted", "considered",
      "accordingly") between them reports the counsel's date; the sentence no longer splits after "No." / "Nos."
      ("along with WP(C) No. 1234/2026 on <date>" keeps its date). `RULES_VERSION` stays 1: no order of the dev
      database has been read yet (all 294,224 orders are `pending`).
    - *Dry run.* `aslms next-dates read --dry-run` also prints `would_be_firm` (rows it would write that the court's
      date already confirms).
    - *Measured* (read-only dry run on the dev database, 17 Oct 2026, 32,091 pending order rows with text): 18,759
      `list_on_date` (58.5%), 709 `qualified_date`, 954 `returnable_date`, 6,318 `period` (19.7%; 6,008
      `list_after_period`), 3,260 `unclear` (85 `conflicting_dates`), 2,091 `none`. Of the 2,778 rows a first run
      would write (current orders, dates from today on), 2,089 (75%) equal the court's own date and are firm at once;
      689 go to a person to confirm (before the claim filter of the queue), and 504 orders would ask for a date.
    - *Not changed:* the confirm endpoint's OpenAPI description (so `schema.d.ts` needs no regeneration); a 409
      `date_passed` is a new error code of the existing 409 response.
