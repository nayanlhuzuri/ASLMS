# Design: Next hearing shown directly from the latest court order, one next-hearing value everywhere

```
slug: next-date-direct
status: approved
author: architect
date: 2026-10-28
approved_by: —
```

## Context

Backlog row 199. **Owner's request, 28 Oct 2026:** "since the next hearing has been decided by the court for the case
via the court orders, it must be visible directly. yes for cases when the next hearing is not mentioned then you can
ask the user for a confirmation but for other cases like specific dates, to be listed after 3 weeks, those things must
be displayed directly capturing from the latest court order."

**Owner's answers, 28 Oct 2026 (recorded as given):**
1. A period ("list after 3 weeks") shows the counted date marked approximate, e.g. "Around 11 Mar 2026 (after 3
   weeks, order of 18 Feb 2026)". It is shown directly with no confirmation, and is replaced automatically when the
   court's own date or a cause list appears.
2. When the latest order's reading and the court's own record (NAPIX next date `cases.next_hearing_date` /
   `date_next_list`, or a cause-list listing) give different dates: "the court record wins but if there is
   discrepancies, it must be flagged."
3. Dates read from orders (specific dates and counted periods) drive My Calendar and the hearing alerts without anyone
   confirming; a period's alert says "around"; the court's date replaces it when it arrives.
4. "if a date has been given by the court, user will not be allowed to edit it. even for dates like 'two be listed in
   two weeks', the user wont be allowed to edit."
5. On a misread order: "keep this editing date as a functionality so that the report wrong date can be provided to
   user types." — two grantable functions: report a wrong reading, and correct a misread reading (Super Administrator
   by default). This is the only path that changes a court-given date read from an order; the court's own record
   stays locked for everyone (decisions 17 to 19).

**Owner-reported defect, 28 Oct 2026:** "when i confirm the order, the hearing date doesnt get updated? what is the
issue?" Cause, checked on `main` (5861406): the case header, the rail and every list show the court's NAPIX value
`cases.next_hearing_date` (set only from `date_next_list`, `services/cases.py:289`; portal `CaseFrame.tsx`,
`Rail.tsx`; `CaseSummaryOut.next_hearing_date`, `api/schemas.py:623`, used by every list). A confirmed reading or a
manual `NXT` date lives only in `next_dates` and feeds the calendar, the alerts and the case page's "Next Date From
Orders" card, never the header, rail or lists. Row 190 named this gap in its owner check 7 ("a case whose court date
is empty but whose firm order date is known reads No Date Yet in the header"). This item closes it: one server-made
next-hearing value that every screen and API reads.

**The plan.** The next-date rule is in §5.5 Alerts and Hearing Calendar, key features: "Next dates from orders:
specific dates are read directly; periods such as 'list after two weeks' are identified by SourceTrace and counted
from the order date; unclear directions are flagged for manual review (Figure 6)." Data and APIs of §5.5: "Cause List
Details (listed hearings); Current Status (next date); Show Order and SourceTrace (next dates from orders)." §6.2 /
Figure 6: "When a new order appears for a tracked case, it is downloaded, its text is extracted, and the next-date
direction is identified. The resulting date feeds the alerts calendar." The screens table (the case overview, Sections
5.3 and 5.7): "next hearing, ... the latest order with the next date read by SourceTrace". §5.3: the overview leads
with "next hearing". §8: Phase 1 "alerts for orders with specific dates"; Phase 2 "SourceTrace-based alerts for orders
that state a period".

**How the new rule fits the plan (for the scribe):**
- *Specific dates are read directly* — this item returns to the plan's own words. The owner's second decision of 17
  Oct 2026 (option B: "firm only when two sources agree") had made every written date a suggestion unless the
  court's record agreed; that was stricter than the plan. Now a written date in the latest order is the next hearing
  at once.
- *Periods counted from the order date* — kept, and now shown directly as approximate. The plan has SourceTrace
  identify periods (Phase 2); counting them by rule in Phase 1 stays the deviation recorded on 26 Sep 2026
  (next-date-extraction decision 2). What changes is the review: the 26 Sep entry ("a counted hint flagged for manual
  review") and next-date-extraction decision 2 ("always reviewed") are superseded by the owner's answer 1. The plan
  itself does not ask for a review of periods, so this is closer to the plan than before. When row 37 adds
  SourceTrace's reading, it writes `order_period` rows under the same rule (shown directly, around).
- *Unclear directions flagged for manual review* — kept: the enter queue. It now also holds orders that give no next
  date at all ("not mentioned", the owner's words), for pending cases where the court's record gives no date either.
- *The court's record wins and differences are flagged* — the plan is silent on a conflict between sources; this is
  the owner's rule (answer 2).
- *No user may edit a court-given date* — the plan is silent; this is the owner's rule (answer 4). It replaces the
  approved confirm / "Not correct" / "Enter next date at any time" actions for dates the court gave. A misread
  reading is corrected only through the two new functions of answer 5 (report, then correct), audited.

**Earlier owner decisions and approved designs this supersedes** (the scribe logs each):
- Decisions log, 26 Sep 2026: "a period ('after two weeks') produces a counted hint flagged for manual review and an
  alert" — periods are shown directly, marked approximate; no review.
- `next-date-extraction`: the owner's decision of 17 Oct 2026 (first), points 1 (periods always confirmed), 2 ("after
  / on or after / from / not before / commencing" dates need confirmation) and 4 (only plain directions firm); the
  owner's decision of 17 Oct 2026 (second, option B), points 1, 2 and 3 (firm only when the court agrees; a later
  matching court date makes a suggestion firm; periods confirmed); decisions 2 (always reviewed), 6 (review flags), 7
  (queue kinds), 9 (the effective next date), 11 (manual dates at any time), 12 (confirm and reject); Deviations 14,
  15 (the reminder "a period ... always goes to a person") and 16.
- `portal-next-dates`: decisions 1 (tab name "Next dates to confirm"), 4 to 7 (Confirm, Not correct, the Show control),
  8 (the court's "Next hearing" card unchanged beside a separate order card), 12 (status words), 13 and 14 (labels
  and the "Answer it" link wording).
- `next-hearing-highlight`: decision 5 ("Suggested" as the only non-firm kind; in practice unreachable after this
  item), the last "Not covered" bullet and owner check 7 (the header shows only the court's date) — resolved here;
  decision 11's places keep their component but read the new value.
- `alerts-notifications` decision 6 (the calendar's union of three sources) — the order source is now the case's one
  next-hearing value, so a court date replaces an order date instead of standing beside it.

**What exists and is reused.** The reader and rules (`services/next_date_rules.py`, `RULES_VERSION = 1`;
`services/next_dates.py`: `read_order`, `supersede`, `supersede_older`, `expire_stale`, `match_court_dates`,
`queue_subquery`, `confirm`, `reject`, `enter`, `effective_for_case`, `next_date_out`), the 5-minute job
`aslms.next_dates_read`, the reading columns on `orders`, `next_dates` with its six review statuses,
`services/calendar.py::hearing_rows` and `my_calendar`, the hourly date sweep with `hearing_due` and
`listed_tomorrow` (`services/alerts.py`), `alert_rules.render_alert`, `inbox.summaries` (the one builder of
`CaseSummaryOut`, also used by the Cause list rows), the shared case filters (`case_filters.py`, `next_from` /
`next_to`), `workflow_actions.available` (`workflow.next_dates`), the kit `HearingDate` and `lib/hearingDate.ts` of
row 190, `cases.search_vector` as the precedent for a derived column on `cases`.

**NAPIX fields.** None new. The court's record is `cases.next_hearing_date` (NAPIX `date_next_list`, from the dossier
and Current Status, kept verbatim and never overwritten here) and the cause-list listings (`causelist_entries` on
`causelists.list_date`, current versions only). No other NAPIX field is read or invented.

**Not covered.** The rules themselves (no new wording, `RULES_VERSION` stays 1, no reread); SourceTrace's reading of
periods (row 37); any change to the court's own record (NAPIX next date, cause lists: no endpoint changes them); the
weekday or holiday adjustment of counted dates (none, as before); the `next_date_changed` alert from Current Status
(unchanged).

## Decisions

1. **What the latest order's reading becomes.** A reading of the case's current order with a date today or later
   (IST) is written `not_needed` with `needs_review = false` and is the court-given date from orders, with no person
   involved:
   | Rule (`orders.next_date_rule`) | Example | Shown as |
   |---|---|---|
   | `list_on_date` | "List on 15.11.2026" | exact: "15 Nov 2026" |
   | `list_after_period`, `after_returnable_period`, `returnable_period` | "List after 3 weeks" | **around**: "Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)" |
   | `qualified_date` | "List after 15.12.2026", "on or after", "not before", "commencing", "or any date thereafter", "tomorrow, i.e. ..." | **around**: "Around 15 Dec 2026 (after 15.12.2026, order of ...)" |
   | `returnable_date` | "Notice returnable on 25.11.2026" with no listing direction | **around**: "Around 25 Nov 2026 (returnable date of the notice, order of ...)" |
   - `qualified_date` is around because the court fixed the earliest day, not the day. Some of its readings are in
     fact exact ("tomorrow, i.e. 29.10.2026", "after 2 weeks, i.e. on <date>"); marking them around is the cautious
     side and needs no rule change. Owner check A.
   - `returnable_date` is around because the matter is usually listed on the returnable date but the order does not
     say so. Owner check B (the alternative is to send it to the enter queue as "not mentioned").
   - Alternatives: keep periods and qualified dates as suggestions (refused by the owner's request and answers 1 and
     3); mark only periods around (shows "after 15.12.2026" as if the court fixed 15 Dec).
2. **What still goes to a person: only orders where the court gave no next date.** An *enter* item is the current
   order of a claimed case, dated within `NEXT_DATE_UNCLEAR_DAYS` (30), with no manual date answering it, whose case
   is not disposed (`cases.status <> 'disposed'`) and has no next hearing from the court (decision 4's value is empty:
   no court record after the order and no usable reading), read as:
   - `unclear`, rule `conflicting_dates` (two different dates, or another matter's date inside the direction: the
     reader cannot tell which date is this case's, so showing one would be a guess);
   - `unclear`, rule `no_countable_date` ("after vacation", "3rd week of August", "after service");
   - `none` — **new**: the order gives no next date ("not mentioned", the owner's words; e.g. notice issued and
     service steps only, "passed over for the day", "in due course", "sine die");
   - `no_text` (a scanned order with no text layer);
   - a reading marked wrong through `next_dates.correct` with no correct date given (decision 18; reason
     `marked_wrong`).
   *Confirm* items no longer exist (decision 9). The queue condition gains `not disposed` and `no next hearing` so a
   final order or a case the court has already listed asks nobody. Alternatives: leave `none` out (contradicts "when
   the next hearing is not mentioned then you can ask the user"); count "after vacation" (the system has no court
   calendar). Owner check C (including `none`).
3. **Pending suggestions are retired.** `next_dates.read_order` no longer calls `court_date_matches`: every dated
   reading of the current order is `not_needed`. `match_court_dates` stays for any row left `pending` and is called
   as today; after decision 13's command it finds nothing. `review_status = pending` can still be read from old rows
   and through the API, but no code path writes it any more. No enum value is removed (enum values cannot be dropped).
4. **One next-hearing value per case, computed in one server function, stored on the case.**
   `services/next_hearing.py::compute(session, case_ids, today)` gives, for each live case (T = today in IST, O = the
   latest `order_date` among the case's orders, or none):
   1. **The court's record** — the earliest date d with d ≥ T and d > O among `cases.next_hearing_date` and the
      case's current cause-list listings. Basis `court`, exact. (d > O, strictly: on the day an order is passed, NAPIX
      and that day's list still show that very day, which is the hearing just held, not the next one.)
   2. else **the latest order's reading** — the latest (`created_at`, then `id`) `order_specific` / `order_period`
      row of the case among `not_needed`, `pending` and `confirmed`, used only when its date is ≥ T. Basis `order`
      (exact: `list_on_date`), `around` (decision 1) or `confirmed` (a row a person confirmed before this item; exact).
   3. else **the court's last given date, passed** (owner, 28 Oct 2026: "court dates should be treated as
      ultimatums") — when the latest court-given date (the court's record, or a dated reading of the latest order)
      is before T and nothing newer has come from the court, it stays the value: same basis (`court`, `order`,
      `around`, `confirmed`), shown as Date Passed by the `HearingDate` badge, and no manual date may replace it.
   4. else **a date entered by hand** — the latest open `manual` row with date ≥ T. Basis `manual`. Under decision 6
      it exists only where the court gave no date at all, and decision 7 closes it when the court gives one.
   5. else none.
   This order settles the precedence question: a manual entry never outranks a court-given date (owner, answer 4); it
   applies only when there is none, and a later court date or order reading replaces it. The value is stored in six
   derived columns on `cases` (Data) by `next_hearing.refresh(session, case_ids, today)`, so lists can sort and filter
   on it in SQL and every API reads the same thing. Alternatives: compute on read in every list (a correlated query
   per row in seven list APIs, no index for sorting or the `next` filter); overwrite `cases.next_hearing_date`
   (breaks "every NAPIX field is kept"); a side table (a join in every list, the standard prefers no new table).
5. **The discrepancy flag.** Set when the value's basis is `court` and the latest order's reading (step 2 of decision
   4, date ≥ T) is **exact** (`order` or `confirmed`) and gives a different date. Stored as `next_hearing_differs_on`
   (the order's date) and `next_hearing_differs_id` (its row).
   - An *around* reading never raises the flag: the owner's answer 1 says the court's date simply replaces it, and a
     court date a few days off a counted period is expected. Owner check D (the alternative is to flag an around
     reading when the court's date is before the earliest day the order allows).
   - Where it shows: the case header and rail ("Order Differs" beside the date, with the sentence "The order of 12 Oct
     2026 gives 20 Nov 2026; the court's record gives 25 Nov 2026. The court's record is used."), the case details
     modal, the Overview card, every Next Hearing list cell (the "Order Differs" chip, the sentence as its title), a
     shared case filter "Next date differs" (`next_differs=true`) on every list, and a count "Next dates that differ
     from the court" in the department dashboard's Items Needing Attention, linking to Department Cases with the
     filter.
   - It alerts nobody and sends no e-mail: the court's date is already the one used for the calendar and alerts.
     Owner check E.
   - Timeline: one court event `next_date_differs` when the flag appears (dedupe on case, court date and order date).
   - It clears by itself on the next refresh: the court's record changes to agree, its date passes, a newer order is
     read, or the reading is closed. There is no "acknowledge" action (a person cannot edit a court-given date,
     decision 6).
6. **No user may edit a court-given date (owner, answer 4), enforced on the server.** A case "has a court-given next
   date" when decision 4 gives basis `court`, `order`, `around` or `confirmed`. Then, for every user and every type,
   the super admin included:
   - `POST /cases/{ref}/next-dates` (enter) answers **409 `court_date_fixed`**;
   - `POST /next-dates/{id}/confirm` and `POST /next-dates/{id}/reject` (with or without a replacement) answer **409
     `court_date_fixed`** (the reading itself is a court-given date);
   - `workflow.next_dates` is false and the new `workflow.next_dates_blocked` says `court_date_fixed`; the portal
     shows no Enter Next Date, Confirm or Not Correct control and says in plain words "The court has given the next
     date, so it cannot be changed here."
   The check runs inside the case lock, after the function, visibility and working-basis checks (403 / 404 first, as
   today), by recomputing the value for that case (not trusting the stored column). A user may enter a date only when
   the court has given none: the latest order gave no direction, an unclear one or no text, or the case has no order
   and no court date. **A court date that has passed is not a gap to fill** (owner, 28 Oct 2026: "dont give the
   provision for entering a date if a date has passed because that would defeat the purpose of alerts. court dates
   should be trated as ultimatums"): it stays the value as Date Passed (decision 4, step 3) and enter answers 409
   `court_date_fixed` until the court's record or a newer order gives a date. Refused attempts write no audit row (owner,
   coordinator note). Alternatives: hide the controls only (forbidden: visibility and rules are server-side); allow
   the super admin (refused by the owner's "user will not be allowed").
   - The one exception is a reading marked wrong through `next_dates.correct` (decision 18). It works only on a date
     read from an order, never on the court's own record. Holding that function does not lift the 409 on enter,
     confirm or reject: correcting is its own action with its own reason and audit.
7. **System replacements of a person's record are audited.** When `refresh` finds a court-given date (basis `court`,
   `order`, `around`, `confirmed`) and the case has an open `manual` row, that row becomes `superseded` (system
   closure, `updated_by` NULL) and one `audit_log` row is written per row: action `next_date.superseded_by_court`,
   entity `next_date`, the case id, actor `Actor.system("next_hearing")`, before / after with the dates, statuses,
   the basis that replaced it and the court date or order reference (never the note text). The same audit row is
   written when `supersede_older` closes a `manual` or `confirmed` row because a newer order was read. Rows the system
   wrote itself (readings) closing other readings stay unaudited system work (next-date-extraction decision 15:
   `job_runs` and events). Changes of the court's own next date are court data, on the timeline, not audited.
8. **"Around" through the API and the badge.** `NextHearingOut` (API) carries `basis` (`court` / `order` / `around` /
   `confirmed` / `manual`), `approximate` (true exactly when `basis = around`), `basis_words` and the order. The
   words are made on the server from the stored court sentence by a pure helper
   `next_date_rules.describe(rule, phrase, order_date, found)`: "after 3 weeks", "after 15.12.2026" (as written),
   "returnable date of the notice"; when it cannot find the words, a fixed fallback per rule ("counted from the
   order", "not before this date"). No column, no reread. The kit `HearingDate` gains `kind="around"`:
   - the word **Around** first, then the band word and the date ("Around · In 3 Days · Wed, 11 Mar 2026" in `md`,
     "Around · 11 Mar 2026" in `sm`), in the band's normal fill (it is shown directly, unlike the outlined
     "Suggested");
   - the `title`, and in `md` a muted line under it: "Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)", the
     owner's form;
   - `data-kind="around"`; the "Order Differs" chip has `data-differs="true"`. Colour is never the only signal.
   Every `md` place also shows one muted basis line: `court` "From the court's records" (or the existing court and
   item line when listed that day), `order` "Given in the order of 12 Oct 2026", `confirmed` "From the order of 12 Oct
   2026", `manual` "Entered by hand; the court has given no date".
9. **The review queue is enter-only.** `queue_subquery(kind="confirm")` returns nothing (pending rows of a case with a
   court-given date cannot be confirmed, decision 6); `kind` stays accepted for compatibility. The portal tab becomes
   **"Next Dates to Enter"** at the same address `/alerts/next-dates`; the Show control, Confirm and Not Correct
   dialogs and the "Waiting for You" confirm rows are removed; each row says why: "The order gives no clear date"
   (`unclear`), "The order gives no next date" (`none`), "This order is a scanned copy and could not be read"
   (`no_text`), "The date read from this order was marked wrong" (`marked_wrong`), with Enter Date. The `next_date_review` alert texts follow ("Enter the next date: the order of <date>
   gives no next date"). The dashboard line "Next dates to confirm" becomes "Next dates to enter".
10. **The calendar and the alerts read the one value.** `calendar.hearing_rows` keeps the court's next date and the
    cause-list listings as today and replaces its third part (the latest `next_dates` row) with the case's stored
    value where its basis is `order`, `around`, `confirmed` or `manual`. So a court date replaces an order date (it no
    longer stands beside it), and a period drives My Calendar, `GET /calendar`, the dashboard Upcoming Hearings and
    the hourly `hearing_due` alerts at once. Rows from the value carry `basis`, `approximate`, `order_date` and
    `basis_words`.
    - `hearing_due` text (`alert_rules.render_alert`, also the e-mail and the digest, which use the alert's title and
      body): around: title "Hearing around 11 Mar 2026: <case>", body "Counted from the order of 18 Feb 2026 (after 3
      weeks). The court's own date will replace it when it is known."; exact order: "Hearing on 20 Nov 2026: <case>",
      "Date given in the order of 12 Oct 2026."; confirmed: "Date from the order of 12 Oct 2026."; manual: "Date
      entered by hand; the court has given no date." Court texts unchanged. Severity follows the date as today (48
      hours critical), around or not.
    - `listed_tomorrow` stays a cause-list alert: it names the court and item as printed, which an order date does not
      have. A hearing tomorrow from an order raises the critical `hearing_due` "Hearing tomorrow" alert (around when a
      period). Owner check F (the owner named "listed for tomorrow" as an example of the hearing alerts).
    - When the court's date replaces an order date, the old `hearing_due` alert closes `expired` / `date_changed` and
      the court date raises its own (existing sweep behaviour, dedupe on case and date).
    - The `confirm` kind of `GET /me/calendar` stays in the API and is always empty.
11. **Every API and screen that switches to the one value.** `CaseSummaryOut.next_hearing_date` is **removed** and
    replaced by `next_hearing: NextHearingOut | null`, so the portal's type check fails at every old use and none is
    missed. The court's verbatim value stays in the case detail's `status.next_hearing_date` (the Court record and the
    discrepancy sentence). Switching:
    | API | Change |
    |---|---|
    | `GET /cases/{ref}` | top-level `next_hearing` (with `phrase` and the differs detail); `workflow.next_dates_blocked`; `status.next_hearing_date` unchanged (court) |
    | every list returning `CaseSummaryOut` (built by `inbox.summaries`): `GET /inbox/mine`, `/inbox/claimed`, `/inbox/recommended`, `/inbox/pool`, `/inbox/department`, transfers, `GET /cases`, `GET /cases/search`, `POST /cases/search-court`, `GET /causelists/*` entry rows, recommendations | `next_hearing` in place of `next_hearing_date` |
    | sorting by next hearing (`inbox.py`, `my_cases.py`, `case_search.py`, `assistant_sources.py`) | `cases.next_hearing_on` |
    | shared filters `next_from` / `next_to` | `cases.next_hearing_on`; new `next_differs` |
    | Pool "with a hearing in 7 days" count (`inbox.counts`) | `cases.next_hearing_on` |
    | `GET /calendar`, `GET /me/calendar`, `GET /dashboard/me` upcoming, department / State hearing lists | through `hearing_rows` (decision 10); items gain `basis`, `approximate`, `basis_words`, `order_date` |
    | `GET /dashboard/department` | `attention.next_dates_differ` (count, decision 5) |
    | `GET /assistant/court-orders/{id}` view (`AssistantCourtCaseOut`) | gains `next_hearing` beside the court's `next_hearing_date` |
    | the Case Assistant's local model context (`assistant_ollama.py`) | the line "Next date (court)" becomes "Next hearing: <words>" from `next_hearing.words()`, plus "Court's own record: <date>" when it differs |
    | row 198's quick fact "next hearing" (designed in parallel) | must answer from `next_hearing.describe_case()` / `words()`, never from `cases.next_hearing_date` |
    Not switched: `load_report.py` (the data-load coverage report counts NAPIX fields), the SourceTrace connector's
    case facts (court record field), the Reports (none shows a next hearing), the Cause list date navigator
    (`next_date` there is the next list date).
    Screens: the case header (`CaseFrame.tsx`), the rail (`Rail.tsx`), the case details modal (`CaseModal.tsx`), every
    Next Hearing column (`WorkingOn`, `MyCases`, `DepartmentCases`, `Recommended`, `Pool`, Search `CaseResults` and side
    panel), the Overview card, the dashboard, My Calendar and the hearing calendar (an "Around" word on around items),
    the Assistant's court-record view (`CourtOrderView.tsx`).
12. **A confirmation or entry changes the header at once.** `confirm`, `reject`, `enter` and `read_order` call
    `next_hearing.refresh` for their case inside the same transaction, after their write and under the case lock they
    already hold, so the response and the next read of the case and of any list carry the new value with no court
    refresh. The portal's existing `useWorkflowRefresh` invalidates the case, the lists and the dashboard. (With
    decision 6, entering is possible only where the court gave no date; confirm survives only for completeness.)
13. **On deploy, one command re-evaluates the old suggestions: `aslms next-dates direct`** (dry run by default; writes
    only with `--apply`):
    1. every `pending` `order_specific` / `order_period` row of a case's current order with a date ≥ today becomes
       `not_needed`, `needs_review = false`, `updated_by` NULL; its `next_date_review` alert closes `done`, reason
       `shown_directly`;
    2. `pending` rows of older orders or with past dates are left to the existing `supersede` / `expire_stale`
       (counted only);
    3. current `none` orders that are now *enter* items (decision 2) get their `next_date_extracted` event with
       `review = true` (the existing dedupe key), so the event scan raises a review alert when the order is within
       its 14-day age rule;
    4. `next_hearing.refresh` for every live case (this supersedes and audits open manual rows that a court-given date
       now outranks, decision 7);
    5. it reports, by case, the rows that conflict: manual rows superseded; confirmed rows whose date differs from the
       court's (now flagged); and `rejected` readings of current orders dated today or later (a person's rejection
       under the old rules, left standing, owner check G);
    6. one `audit_log` row `next_dates.direct_apply` (actor `cli`, the counts and the conflict list size). The dry run
       prints the same counts and writes nothing.
    A second `--apply` finds nothing. The migration itself changes no data (the derived columns start empty); until
    the command runs, the 5-minute job backfills them in batches (Jobs).
14. **Visibility.** The next hearing, its basis words, the court sentence and the flag are court information,
    readable by everyone who may see the case; lists stay filtered by the existing visibility rules. A manual row's
    note is not part of `NextHearingOut` (it stays on the Hearings tab's Next Dates section, as today). No query relies
    on the frontend.
15. **Nothing reaches SourceTrace or any AI.** The reader and `describe` work on stored court text by rule; no NAPIX
    call is added (the court's record is read from held data). The local model receives the same next-hearing words
    any case reader sees (court information).
16. **Migration 0034** (the next free number at build time if another row takes 0034 first). One new enum, six
    derived columns on `cases`, their checks and indexes, one `ref_event_type` row and one `ref_alert_kind` row. The
    two new functions (decision 19) need no schema change: `permission` is a varchar code and the seed inserts the
    `ref_permission` rows and the missing matrix rows, as for `cases.view_private_all` (0022 (c)). No table, no
    setting.
17. **Report a wrong reading: function `next_dates.report_wrong`, "Report Wrong Next Date"** (owner, answer 5).
    - Who: a holder of the function who may see the case (`require_visible`, 404 otherwise; 403 without the
      function). No working basis is needed: reporting changes nothing.
    - What: the case's latest order reading (decision 4, step 2: an open `order_specific` / `order_period` row dated
      today or later), whether or not it is the shown value (a reading that differs from the court's record can be
      reported too). Anything else answers 409 `not_reportable` (the court's record, a manual date, an old reading).
    - With: a required reason, 10 to 300 characters (the form says it is shown to the people who can correct it).
    - Effect: no date changes. One alert of the new kind `next_date_reported` (severity `normal`, key
      `next_date_reported:<next_date id>`, office the owning department or, for an unclaimed case, the reporter's
      acting office) to every active holder of `next_dates.correct` who may see the case (the Super Administrator
      always); `data`: next date id, order id, order date, the date read, the rule, the reporter's name and office, the
      reason. While that alert is open a second report answers 409 `already_reported`. Audit `next_date.report_wrong`
      (entity `next_date`, the case id, the reason's length and hash; the text lives in the alert). The case page
      shows every case reader "Reported as possibly wrong on <date>; waiting for correction" (no reporter name, no
      reason) while the alert is open.
    - The alert closes `done` with reason `corrected` or `kept` (decision 18), or `expired` / `no_longer_used` in the
      hourly sweep when the row stops being the latest reading (a newer order, the court's record replacing it, its
      date passing).
18. **Correct a misread reading: function `next_dates.correct`, "Correct Misread Next Date"** (owner, answer 5).
    - Who: a holder who may see the case (404 / 403 as above); no working basis needed (an oversight function).
    - What: the same row as decision 17 (409 `not_order_reading` for anything else). The court's own record has no
      correct action at all.
    - **Correct** (`POST /next-dates/{id}/correct`): a required reason (10 to 300 characters) and an optional correct
      date (today to today + `NEXT_DATE_MAX_AHEAD_DAYS`). Under the case lock: the row becomes `rejected` with
      `reviewed_by_user_id`, `reviewed_at` and `note` = the reason; the order's reading columns
      (`next_date_found`, `next_date_rule`, `next_date_phrase`) are never changed, so the court's sentence stays
      beside the correction. With a date, a `manual` row (`NXT` reference on the corrector's office: the membership
      holding the function, or for the Super Administrator their own office) linked to the same order is written in
      the same transaction, so the case shows it at once (basis `manual`, line "Corrected by hand: the date read from
      the order of <date> was wrong"). Without a date, the order joins Next Dates to Enter (reason `marked_wrong`,
      decision 2's other conditions applying). Open `next_date_reported` alerts of the row close `done` /
      `corrected`; the `next_date_reviewed` event (action `corrected`) goes on the timeline; one audit row
      `next_date.correct` with before / after (the dates, statuses, the order id and the court's sentence, the
      reason's length and hash, the manual row's reference); then `next_hearing.refresh`. Choice flagged (owner check
      I): the date in the same step, optional, rather than always falling back to "enter".
    - **Reading Is Right** (`POST /next-dates/{id}/keep`): closes the open report alerts `done` / `kept` with an
      optional note (≤ 300), audit `next_date.report_kept`; the reading stays.
    - The correct date is a `manual` date: decision 4 ranks it below any court record and decision 7 replaces it when
      the court gives a date. Because the case then has no court-given date, a holder of `next_dates.review` with a
      working basis may enter a different date, as for any manual date (owner check J).
    - Holding `next_dates.correct` never permits enter, confirm or reject on a court-given date (decision 6) and never
      touches `cases.next_hearing_date` or a cause list.
19. **The two functions in the matrix.** `Permission.NEXT_DATES_REPORT_WRONG = "next_dates.report_wrong"` and
    `Permission.NEXT_DATES_CORRECT = "next_dates.correct"`, in the "Alerts" group of `PERMISSION_GROUPS` after
    `next_dates.review`, labelled in Title Case:
    - "Report Wrong Next Date" — "Tell the people who correct dates that a next date read from an order looks wrong,
      with your reason.";
    - "Correct Misread Next Date" — "Mark a next date read from an order as wrong and, if the order shows it, enter the
      right date. The court's own records cannot be changed.";
    - `next_dates.review` is relabelled "Enter Next Dates" — "Enter the next date when the court's order gives none."
      (seed upsert on code; no migration).
    Defaults (`DEFAULT_MATRIX`): `next_dates.report_wrong` for the department head, department admin, department
    officer and directorate user (the case-work types, `_CASE_WORK`); `next_dates.correct` for no type, so only the
    Super Administrator holds it (the super admin always has every function). Both appear on the Administration
    user-type pages and in per-user overrides like any function; the delegation rule applies unchanged (a grantor can
    give only functions they hold). Owner check K (the report defaults). The portal shows Report and Correct only by
    the server flags `workflow.next_date_report` and `workflow.next_date_correct` on `GET /cases/{ref}` (true when the
    caller holds the function, may see the case and a reportable row exists), and the "Correct It" link on a
    `next_date_reported` alert.

No deviation from the plan beyond the existing one (periods counted by rule in Phase 1, 26 Sep 2026). The changes to
approved owner decisions are listed in Context for the scribe.

## Data

Migration **0034** (`0034_next_date_direct.py`, new; no applied migration is edited).

- `CREATE TYPE next_hearing_basis AS ENUM ('court', 'order', 'around', 'confirmed', 'manual')`.
- `cases` gains six nullable columns, the checks and indexes below. No default data: the command or the job fills
  them.
- Reference rows (hard-coded, `ON CONFLICT (code) DO NOTHING`, as 0016, 0018 and 0022): `ref_event_type`
  `next_date_differs`, "Next date differs from the court", `is_tracking_card` false (a court event);
  `ref_alert_kind` `next_date_reported`, "Next date reported as wrong", default severity `normal`. `aslms seed`
  carries the same rows.
- Functions (seed only, as `cases.view_private_all` in 0022 (c)): `ref_permission` rows `next_dates.report_wrong` and
  `next_dates.correct` with decision 19's labels; the relabelled `next_dates.review`; the missing `role_permissions`
  rows from `DEFAULT_MATRIX` (`report_wrong` enabled for `dept_head`, `dept_admin`, `dept_officer`,
  `directorate_user`; disabled for the other types; `correct` disabled for every type). `permission` is a varchar
  code (`native_enum=False`), so no type change. Deploy order: `migrate`, then `init` (seed).
- Python: `NextHearingBasis` (`domain/cases.py`), `EventType.NEXT_DATE_DIFFERS`, `AlertKind.NEXT_DATE_REPORTED`,
  `Permission.NEXT_DATES_REPORT_WRONG`, `Permission.NEXT_DATES_CORRECT`.
- No grant change (`aslms_app` already updates `cases` and writes `alerts`, `role_permissions`, `audit_log`).
  Downgrade drops the columns, checks, indexes and the type and deletes the two reference rows if unused; it refuses
  while a `next_date_reported` alert exists (legal-record history). The function rows stay (the seed owns them).

Paragraph for `docs/schema/schema.md`, Group 2, the `cases` row (as-built note; `cases` stays class transaction, these
columns are derived like `search_vector`):
> (next-date-direct, migration 0034) The case's one next hearing, derived and regenerable, written only by
> `services/next_hearing.py::refresh`: `next_hearing_on` (date NULL), `next_hearing_basis` (`next_hearing_basis`:
> `court` / `order` / `around` / `confirmed` / `manual`, NULL), `next_hearing_next_date_id` (uuid NULL → next_dates
> RESTRICT: the reading or manual row the date comes from), `next_hearing_differs_on` (date NULL: an exact reading of
> the latest order that differs from the court's record), `next_hearing_differs_id` (uuid NULL → next_dates RESTRICT),
> `next_hearing_set_at` (timestamptz NULL: when last computed). Rule (design `next-date-direct`, decision 4): the
> court's record — the earliest of `next_hearing_date` and the current cause-list listings that is today or later and
> after the latest `order_date` — else the latest open order reading dated today or later, else the court's last
> given date when it has passed and nothing newer came from the court (shown as Date Passed; owner, 28 Oct 2026:
> court dates are ultimatums), else the latest open manual row dated today or later. `next_hearing_date` itself stays the court's verbatim `date_next_list`. CHECKs
> `ck_cases_next_hearing_basis` (`(next_hearing_on IS NULL) = (next_hearing_basis IS NULL)`),
> `ck_cases_next_hearing_row` (`(COALESCE(next_hearing_basis::text, '') IN ('order', 'around', 'confirmed',
> 'manual')) = (next_hearing_next_date_id IS NOT NULL)`), `ck_cases_next_hearing_differs` (`(next_hearing_differs_on
> IS NULL) = (next_hearing_differs_id IS NULL) AND (next_hearing_differs_on IS NULL OR next_hearing_basis =
> 'court')`). Index `ix_cases_next_hearing_on` (`next_hearing_on`); partial indexes `ix_cases_next_hearing_differs`
> (`id`) WHERE `next_hearing_differs_on IS NOT NULL` and `ix_cases_next_hearing_unset` (`id`) WHERE
> `next_hearing_set_at IS NULL`. The refresh writes only these six columns (not `updated_by`). The FKs to
> `next_dates` are RESTRICT (`next_dates` rows are never deleted).

Group 7, the `next_dates` paragraph, the sentence from "A reading becomes a row only ..." to "... used only when not
`pending`." becomes:
> A reading becomes a row only for the case's current order with a date today or later, and is `not_needed` (needs
> review false): it is the court-given date from orders, shown directly, around for periods, qualified and returnable
> dates (design `next-date-direct`, owner 28 Oct 2026). `pending` remains only on rows written before migration 0034
> and is retired by `aslms next-dates direct --apply`; no code path writes it. A user may enter a `manual` row only
> when the case has no court-given date (409 `court_date_fixed` otherwise); an open `manual` row is `superseded` by a
> system closure, audited `next_date.superseded_by_court`, as soon as the court's record or an order reading gives a
> date. A reading of the latest order is changed only by `next_dates.correct` (`rejected`, the reason in `note`,
> reviewer and time set; an optional correct date as a `manual` row linked to the same order); the order's reading
> columns are never changed. `superseded` and `expired` are system closures; `superseded` also closes the open rows of older orders, and
> manual rows without an order entered before its date, when the case's current order is read without a usable date.
> The case's one next hearing is kept on `cases.next_hearing_*`.

Group 0 (reference data), note added:
> `ref_event_type` gains `next_date_differs` (court event); `ref_alert_kind` gains `next_date_reported` (default
> severity `normal`); next-date-direct, migration 0034 and the seed. `ref_permission` (seed only):
> `next_dates.report_wrong` "Report Wrong Next Date" and `next_dates.correct` "Correct Misread Next Date"; 
> `next_dates.review` relabelled "Enter Next Dates".

Group 1, the `role_permissions` row, note added:
> Defaults of next-date-direct (seed): `next_dates.report_wrong` for the department head, department admin,
> department officer and directorate user; `next_dates.correct` for no type (the Super Administrator only, who holds
> every function).

## Services

- **`services/next_hearing.py`** (new):
  - `NextHearing` (frozen dataclass: `date`, `basis`, `next_date_id`, `differs_on`, `differs_id`).
  - `compute(session, case_ids, *, today) -> dict[uuid, NextHearing | None]`: decision 4 and 5 in set-based SQL (the
    court tier from `cases.next_hearing_date` and `causelist_entries` / `causelists` with `CURRENT_LIST`; O from
    `orders`; the order tier with `distinct_on` as `hearing_rows` does; the manual tier), merged in Python.
  - `refresh(session, case_ids, *, today=None, actor=None) -> RefreshResult`: locks the cases in id order (`SELECT ...
    ORDER BY id FOR UPDATE`; a caller already holding one case's lock is unaffected), computes, writes the six columns
    where they changed and `next_hearing_set_at`; supersedes and audits open manual rows (decision 7); emits
    `next_date_differs` when the flag appears. Counters `changed`, `differs_set`, `differs_cleared`,
    `manual_superseded`.
  - `refresh_after_court_change(session, case_ids)`: inside a savepoint; a failure is recorded in `source_failures`
    (kind `next_hearing_refresh`, ref the case id) and never fails the court data. Called where
    `match_after_court_change` is called today: `cases.apply_dossier`, `cases.apply_status` (when
    `next_hearing_date` changed), `causelists.apply_entries` and the corrected-list path
    (`causelists.py` lines 309 and 848), and `case_dedupe.merge_provisional` (the surviving case).
  - `refresh_due(session, *, today, batch) -> dict`: cases whose `next_hearing_on < today`, cases with an unresolved
    `next_hearing_refresh` failure, then up to `batch` (5,000) cases with `next_hearing_set_at IS NULL` (backfill).
  - `court_given(session, case, *, today) -> bool` (decision 6: recomputed for the one case, basis in `court`,
    `order`, `around`, `confirmed`).
  - `describe_case(session, case) -> dict | None` and `next_hearing_out(session, case, *, detail)`: the API shape,
    batch form `outs(session, cases, *, detail=False)` for lists (one query for the rows and orders of a page).
  - `words(out) -> str`: one plain line for the Assistant and alert text ("Around 11 Mar 2026 (after 3 weeks, order of
    18 Feb 2026)", "25 Nov 2026 (court's records)", "20 Nov 2026 (order of 12 Oct 2026)", "No next hearing known").
- **`services/next_date_rules.py`**: `describe(rule, phrase, order_date, found) -> str | None` (pure, bounded
  patterns over the ≤ 400-character sentence; decision 8). `RULES_VERSION` unchanged.
- **`services/next_dates.py`**:
  - `read_order`: every dated reading of the current order is `not_needed`, `needs_review = false` (decision 3); a
    `none` reading of the current order emits the review event when decision 2 makes it an enter item; then
    `next_hearing.refresh(case)`.
  - `queue_subquery`: *enter* adds `OrderNextDateStatus.NONE` to `ENTER_STATUSES`, `Case.status <> disposed` and
    `Case.next_hearing_basis IS NULL OR = 'manual'` with no manual row answering the order; *confirm* returns no row.
  - `confirm`, `reject`, `enter`: after the existing checks and the case lock, `next_hearing.court_given` → 409
    `court_date_fixed` (`conflict("court_date_fixed", ...)`); then the write and `next_hearing.refresh`.
  - `supersede_older`: audits `next_date.superseded_by_court` for each `manual` / `confirmed` row it closes
    (decision 7).
  - `read_pending` (the 5-minute job): after the batch, `next_hearing.refresh_due` (counters `hearing_refreshed`,
    `hearing_backfilled`).
  - `direct_apply(session, *, apply: bool, today) -> dict` (decision 13) and its audit.
  - `effective_for_case` keeps its meaning for the "Next Date From Orders" card (the order-side row), now with the
    manual row ranked below an order reading as in decision 4.
  - `reportable_row(session, case, *, today) -> NextDate | None` (decision 17's row); `report_wrong(session, actor,
    user, next_date_id, *, reason)`, `correct(session, actor, user, next_date_id, *, reason, next_date=None)` and
    `keep(session, actor, user, next_date_id, *, note=None)` (decisions 17 and 18): `require_function`,
    `require_visible`, `lock_case`, the row check, the write, the alert raise / close (`alerts.raise_alert` with
    explicit recipients: the active holders of `next_dates.correct` who may see the case, through
    `access.holders_of` and `visibility`), the event, `write_audit`, `next_hearing.refresh`. Errors: 400 `bad_field`
    (reason length, date range), 403 `forbidden`, 404, 409 `not_reportable` / `not_order_reading` /
    `already_reported` / `not_reported` (keep with no open report).
  - `queue_subquery` *enter*: also the current order whose reading row is `rejected` by a correction with no manual
    row answering it (reason `marked_wrong`).
- **`services/alerts.py`**: the hourly sweep closes open `next_date_reported` alerts whose row is no longer
  `reportable_row` (`expired` / `no_longer_used`, counter `closed_next_date_report`). **`services/alert_rules.py`**:
  `next_date_reported` text ("Next date reported as wrong: <date> read from the order of <date>"; body: the reporter's
  name and office and the reason, shown only to the alert's recipients).
- **`services/access_seed.py`**: the two labels, the relabel, the group places, `_CASE_WORK` gains
  `NEXT_DATES_REPORT_WRONG`; `domain/reference.py`: the two `Permission` members.
- **`services/calendar.py`**: `hearing_rows` third part from `cases.next_hearing_on` / `next_hearing_basis`
  (decision 10); rows carry `basis`, `approximate`, `order_date`, `basis_words`.
- **`services/alerts.py`** / **`services/alert_rules.py`**: `hearing_due` data gains `basis`, `approximate`,
  `order_date`, `order_no`, `basis_words`; `render_alert` texts of decision 10; `next_date_review` texts of decision 9.
- **`services/inbox.py`**: `summaries` returns `next_hearing` (via `next_hearing.outs`) and no `next_hearing_date`;
  sorts and the pool count on `next_hearing_on`. **`services/my_cases.py`**, **`services/case_search.py`**,
  **`services/assistant_sources.py`**: order by `next_hearing_on`.
- **`services/case_filters.py`**: `next_from` / `next_to` on `next_hearing_on`; `next_differs` (bool).
- **`services/case_detail.py`**: overview `next_hearing` (detail form, with `reported_at` while a report is open).
  **`services/workflow_actions.py`**: `next_dates` false and `next_dates_blocked = "court_date_fixed"` when
  `court_given`; `next_date_report` and `next_date_correct` (decision 19).
- **`services/dashboard.py`**: department `attention.next_dates_differ` (count of the department's claimed cases with
  `next_hearing_differs_on` set); "next dates to enter" label in the payload unchanged in shape.
- **`services/assistant_ollama.py`**: the case facts line from `next_hearing.words` (decision 11).
- **`services/seed.py`**: the `next_date_differs` event type.
- **`cli/next_dates.py`**: `direct [--apply]` and `hearing-refresh [--all | --case REF] [--dry-run]` (repair and
  backfill at once; audited `next_dates.hearing_refresh` with counts when it writes); `status` adds the next-hearing
  counts by basis and the number flagged.

Frontend (`frontend/`):
- `lib/hearingDate.ts`: `HearingKind` gains `around`; `hearingWords` puts "Around" first; `nextHearingProps(next)` maps
  `NextHearingOut` to the component's props; `basisLine(next)` and `differsSentence(next, courtDate)`.
- `components/ui/HearingDate.tsx`: prop `next?: NextHearingOut` beside `date`; `kind="around"`; the "Order Differs"
  chip; the `md` basis line; `data-kind`, `data-differs`.
- Changed screens: decision 11's list; `nextdates/*`: the review list without Show, Confirm and Not Correct (decision
  9), `NextDateBlock` without the confirm rows and with the blocked reason, the Enter Next Date button only with
  `workflow.next_dates`; new dialogs `ReportWrongNextDate` (reason with `CharCounter`, the court's sentence and the
  order link shown) and `CorrectNextDate` (the sentence, the date read, required reason, optional correct date,
  "Reading Is Right" as a second button), shown only by `workflow.next_date_report` / `next_date_correct`; the
  "Reported as possibly wrong" line; the "Correct It" link on `next_date_reported` alerts; `lib/filters.ts`: `next_differs` on the case lists; `lib/messages.ts`: `T.hearing.badges.around`
  "Around", `T.hearing.badges.differs` "Order Differs", the basis lines, the blocked reason, the new queue texts;
  `lib/labelRules.ts` as needed for the Title Case guard.
- `frontend/openapi.json` and `src/lib/api/schema.d.ts` regenerated.

Audit and events: `next_date.superseded_by_court` (system, decision 7), `next_date.report_wrong`,
`next_date.correct`, `next_date.report_kept` (people, decisions 17 and 18), `next_dates.direct_apply` and
`next_dates.hearing_refresh` (CLI, counts); events `next_date_differs` and `next_date_reviewed` (action `corrected`).
Refused attempts are not audited.

## API

| Method, path | Function (`Permission`) | Change | Visibility |
|---|---|---|---|
| `GET /cases/{ref}` | `cases.view_scope` or `cases.view_all` (unchanged) | gains `next_hearing: NextHearingOut \| null` (detail form) and `workflow.next_dates_blocked: "court_date_fixed" \| null`, `workflow.next_date_report: bool`, `workflow.next_date_correct: bool`; `workflow.next_dates` false when blocked | `require_visible` (404) |
| `POST /next-dates/{id}/report` (new) | `next_dates.report_wrong` | `{reason: str 10–300}` → `{reported: true, alert_ref_no}` (201) | `require_visible` (404); 403 without the function; 409 `not_reportable` / `already_reported`; 400 `bad_field` |
| `POST /next-dates/{id}/correct` (new) | `next_dates.correct` | `{reason: str 10–300, next_date?: date}` → `{rejected: NextDateOut, entered: NextDateOut \| null, next_hearing: NextHearingOut \| null}` | `require_visible` (404); 403; 409 `not_order_reading`; 400 `bad_field` |
| `POST /next-dates/{id}/keep` (new) | `next_dates.correct` | `{note?: str ≤ 300}` → `{kept: true}` | `require_visible` (404); 403; 409 `not_reported` |
| List APIs returning `CaseSummaryOut` (decision 11's table) | unchanged per endpoint (`cases.view_scope` / `cases.view_all` / `cases.claim` / `causelists.view` as today) | `next_hearing_date` removed, `next_hearing: NextHearingOut \| null` added (list form); filters `next_from` / `next_to` on the one value, new `next_differs: bool` | unchanged server filters |
| `GET /calendar`, `GET /me/calendar`, `GET /dashboard/me` | unchanged | items gain `basis`, `approximate`, `basis_words`, `order_date` | unchanged |
| `GET /dashboard/department` | unchanged | `attention.next_dates_differ: int \| null` (null without the block) | unchanged |
| `GET /next-dates/review` | `next_dates.review` | enter items only; `reason` (`unclear` / `none` / `no_text`) on each item | working basis on a claimed case (unchanged) |
| `POST /cases/{ref}/next-dates` | `next_dates.review` | 409 `court_date_fixed` when the case has a court-given date | unchanged checks first (404, 403) |
| `POST /next-dates/{id}/confirm`, `POST /next-dates/{id}/reject` | `next_dates.review` | 409 `court_date_fixed` | unchanged checks first |
| `GET /assistant/court-orders/{id}` | `assistant.use` (unchanged) | `case.next_hearing` added | unchanged |

`NextHearingOut`: `date` (date), `basis` (`court` / `order` / `around` / `confirmed` / `manual`), `approximate`
(bool), `basis_words` (str or null), `order` (`{id, order_no, order_date, document_id}` or null), `rule` (str or
null), `differs` (`{date, order: {id, order_no, order_date, document_id}}` or null); detail form adds `phrase` (the
court's sentence, ≤ 400), `court_date` (`cases.next_hearing_date`, for the sentence) and `reported_at` (while a
report is open). Error texts: `court_date_fixed` "The court has given the next date for this case, so it cannot be
changed."; `already_reported` "This date has already been reported and is waiting for correction.";
`not_reportable` / `not_order_reading` "Only a next date read from the latest order can be reported or corrected.";
`not_reported` "There is no open report on this date." `GET /admin/access/*` and `GET /reference/labels` list the two
functions from the seed with no code change.

## Jobs

- **`aslms.next_dates_read`** (existing, every 5 minutes): after the batch, `next_hearing.refresh_due` — rollovers
  (`next_hearing_on` before today), failed refreshes, and the backfill of up to 5,000 cases a run with
  `next_hearing_set_at IS NULL` (the dev database's ~55,000 cases in about an hour; `aslms next-dates hearing-refresh
  --all` does it at once). Counters in the same `job_runs` row. No NAPIX call, no queue row.
- The hourly date sweep and the 5-minute event scan: unchanged schedules, new texts (decisions 9 and 10).
- One-off on deploy: `aslms next-dates direct` then `--apply` (decision 13).

## Tests

Unit (`tests/unit/`):
- `test_next_date_rules.py`: `describe` gives "after 3 weeks", "after 30 days", "after 2 months", "after a fortnight",
  "after 15.12.2026", "on or after 20.11.2026", "returnable date of the notice"; None on a phrase it cannot read; no
  control character in the source (existing guard).
- `test_next_hearing_words.py`: `words()` for each basis, around in the owner's form, none.
- `test_alert_rules.py`: `hearing_due` titles and bodies for `around`, `order`, `confirmed`, `manual`, court and
  cause list; "around" in the around title.

Database (`tests/db/`):
- `test_next_hearing.py`:
  - the court tier wins over an exact reading and over an around reading; the earliest of NAPIX date and listing;
    a court date equal to the latest order date is ignored (the hearing just held) and the reading is used;
  - the order tier: a period gives `around` with the counted date; `qualified_date` and `returnable_date` give
    `around`; `list_on_date` gives `order`; a past reading gives nothing; an older order's row after a newer `none`
    order gives nothing;
  - manual only with no court-given date; a later court date or reading supersedes it and writes
    `next_date.superseded_by_court` (actor system, no note text);
  - discrepancy: set for an exact reading that differs, not for an around one, cleared when the court agrees, when
    its date passes, and when a newer order is read; one `next_date_differs` event, not repeated on a second refresh;
  - `refresh_due` rolls over a passed date to the next tier and backfills unset cases in batches; a failure in the
    court path is recorded and does not roll back the dossier;
  - the migration's checks refuse a basis without a date, an order basis without its row, and a differs date on a
    non-court basis.
- `test_next_dates_read.py` (changed): every dated reading of the current order is `not_needed`, `needs_review`
  false, with no court match needed; a `none` current order of a claimed pending case with no court date is an enter
  item, not for a disposed case and not when the court gives a later date.
- **The owner's scenario** (`test_next_date_direct_owner.py`):
  - `test_order_date_shows_in_header_and_inbox_without_confirm`: a claimed case with no NAPIX next date and an order
    "List after 3 weeks" → after the reader run, `GET /cases/{ref}` `next_hearing` is the counted date, `around`, and
    `GET /inbox/mine` shows the same `next_hearing` for the case, with no confirm call.
  - `test_legacy_pending_row_shown_and_retired`: a `pending` row written as before 0034 → the case detail and inbox
    already show it (decision 4 counts pending); `aslms next-dates direct --apply` makes it `not_needed`, closes its
    review alert `shown_directly`, writes one `next_dates.direct_apply` audit row; a second run changes nothing.
  - `test_enter_where_court_gave_none_updates_header_at_once`: an `unclear` current order → `POST
    /cases/{ref}/next-dates` → the response, `GET /cases/{ref}` and `GET /inbox/mine` show the date, basis `manual`,
    with no court refresh.
  (The coordinator's first form of this test, "pending → confirm → header", is replaced by these three: under owner
  answer 4 a confirm of a court-given reading is refused.)
- `test_court_date_fixed.py`: with a court record, with an exact reading and with an around reading, `POST
  /cases/{ref}/next-dates`, `confirm` and `reject` (with and without a replacement) answer 409 `court_date_fixed` for
  a department officer, a department admin, a department head and the super admin; 404 / 403 still come first for an
  invisible case or no working basis; no audit row is written for a refusal; `workflow.next_dates` is false with
  `next_dates_blocked = "court_date_fixed"`.
- `test_next_date_correction.py` (decisions 17 to 19):
  - report: with the function on a visible case → one `next_date_reported` alert to the holders of
    `next_dates.correct` who may see the case (the super admin always; a holder who cannot see the case gets none),
    one audit row without the reason text, the "reported" line on the case detail; without the function 403 (a
    department officer whose override denies it, the Auditor, State oversight by default); invisible case 404; a
    second report 409 `already_reported`; the court's record or a manual date 409 `not_reportable`; the date never
    changes;
  - correct: without the function 403 for every default type (department head, admin, officer, directorate user,
    State oversight, central operator, Auditor, standing counsel, referral reviewer); the super admin and a type
    granted the function by the matrix succeed; with a date → the reading `rejected` with reason and reviewer, the
    order's reading columns unchanged, a `manual` `NXT` row linked to the order, `GET /cases/{ref}` and `GET
    /inbox/mine` show the corrected date at once, the report alert closed `done` / `corrected`, one audit row with
    before / after and the court's sentence; without a date → the order is an enter item `marked_wrong` and the case
    has no next hearing from orders; on a case whose court record gives the date, correct changes only the order tier
    (the flag clears, the shown date stays the court's);
  - keep: closes the report `kept` with an audit row; 409 `not_reported` with none open;
  - holding `next_dates.correct` still gets 409 `court_date_fixed` on enter, confirm and reject;
  - no endpoint changes `cases.next_hearing_date` or a cause list (asserted after every action);
  - the sweep closes a report alert `no_longer_used` after a newer order is read;
  - seed: both functions in `ref_permission` with their labels, the defaults of decision 19 in `role_permissions`,
    `next_dates.review` relabelled; a second seed changes nothing; a user-type change and a per-user override grant
    and deny them like any function (the delegation rule refuses a grantor who lacks the function).
- `test_calendar.py` (changed): a period drives `GET /me/calendar` and a `hearing_due` alert "Hearing around ..."; the
  court's date arriving closes that alert `date_changed` and raises the court one; the court's date and a different
  exact order date give one calendar row (the court's), not two.
- `test_case_filters.py` (changed): `next_from` / `next_to` match `next_hearing_on`; `next_differs` narrows.
- `test_api_next_dates.py` (changed): the queue has no confirm item; `reason` on enter items.
- `test_dashboard.py` (changed): `next_dates_differ` counts the department's flagged cases.
- `unit/test_openapi_snapshot.py` fails until `frontend/openapi.json` is regenerated.
- Nothing in these paths calls the NAPIX client or the SourceTrace connector (the scripted gateway and the fake
  connector record no call).

Frontend (Vitest):
- `lib/hearingDate.test.ts`: `around` words first in `sm` and `md`; the owner's title sentence; `basisLine` for each
  basis; `differsSentence`.
- `components/ui/hearingDate.test.tsx`: `data-kind="around"`, the "Order Differs" chip with `data-differs`, no
  `aria-label` replacing the text.
- Screens: every list, the header, the rail and the modal read `next_hearing` (a case with no court date and an order
  date shows the order date, the owner's defect); the review list shows enter rows only with their reason and no
  Confirm or Not Correct; Enter Next Date absent and the plain reason shown when `next_dates_blocked`; the Overview
  card without the confirm rows; the dashboard differs line links with `next_differs=true`; Report Wrong Next Date
  only with `workflow.next_date_report` and Correct / Reading Is Right only with `workflow.next_date_correct` (both
  absent otherwise); the report dialog requires a reason of 10 characters; the correct dialog posts the date only
  when filled; the "Correct It" link on a `next_date_reported` alert; the Administration user-type page lists the
  two functions in the Alerts group.
- `lib/labels.test.ts` and `lib/wording.test.ts` pass ("Around", "Order Differs", "Next Dates to Enter").
- uicheck (`docker compose --profile uicheck run --rm uicheck`, 375, 768 and 1280 px): the row 190 states gain an
  around row and a differs row; no new finding.

## Verification

1. `ruff check backend` clean; `pytest -q` green; `python backend/tools/export_openapi.py` then `git diff
   --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`; a
   search finds no `next_hearing_date` read outside the Court record and the discrepancy sentence.
3. Dev database: `migrate` (0034), `init` (seed: the two functions and their matrix rows); `aslms next-dates direct` (dry run: counts of pending rows to show
   directly, enter items added by `none`, manual rows to supersede, conflicts), then `aslms next-dates direct
   --apply`; `aslms next-dates hearing-refresh --all`; `aslms next-dates status` shows the next hearing by basis and
   the flagged count. Expected: no `pending` row dated today or later remains; every live case has
   `next_hearing_set_at`; `audit_log` has one `next_dates.direct_apply` row.
4. `docker compose build`, `up` (with the court-data switch as for every `up`); the `job_runs` row of
   `next_dates_read` shows `hearing_refreshed` and, after midnight IST, rollovers.
5. **The owner's checks at http://localhost:3000** (signed in, phone and desktop widths):
   1. A claimed case whose latest order says "List after 3 weeks" and whose court record has no later date: the
      header, rail, Case Inbox row and case details modal all show "Around · ... · <date>" with "Around <date> (after 3
      weeks, order of <date>)"; My Calendar lists it; no Enter Next Date button; the reason line says the court has
      given the date.
   2. A case whose latest order gives a written date: the date shows directly, no "Suggested", no Confirm.
   3. A case whose court record gives a later date different from an exact order date: the court's date shows with
      "Order Differs" and the sentence; the Department Cases filter "Next date differs" lists it; the dashboard line
      counts it.
   4. A case whose latest order is unclear or gives no date: it appears under Alerts & Calendar → Next Dates to
      Enter; Enter Date → the header and the inbox show the date at once, "Entered by hand; the court has given no
      date".
   5. As a department officer on a case whose date was read from an order: Report Wrong Next Date with a reason →
      the case shows "Reported as possibly wrong"; the date is unchanged. As the Super Administrator: the bell shows
      the report; Correct It → Correct with a reason and the right date → the header and the Case Inbox show the new
      date at once with "Corrected by hand"; the court's sentence still shows on the Orders tab. Repeat without a
      date → the case appears under Next Dates to Enter. As a department admin (no `next_dates.correct`): no Correct
      control. Administration → User Types shows "Report Wrong Next Date" and "Correct Misread Next Date" under
      Alerts, with the defaults of decision 19.
   6. In `psql`: a refused enter writes no audit row; a manual row replaced by a later court date has a
      `next_date.superseded_by_court` row; `next_date.report_wrong` and `next_date.correct` rows exist for step 5;
      `cases.next_hearing_date` of the corrected case is unchanged.

## Open questions

None. The misread-order path, first recorded here as an open question, was decided by the owner on 28 Oct 2026
(answer 5) and is designed in decisions 17 to 19.

Owner checks at approval (decisions taken, reversible):
- A. `qualified_date` readings ("after / on or after / not before <date>", "tomorrow, i.e.") shown as around (decision 1).
- B. `returnable_date` shown as around, rather than sent to Next Dates to Enter (decision 1).
- C. Orders that give no next date (`none`) join Next Dates to Enter, for pending cases with no court date (decision 2).
- D. An around reading never raises the discrepancy flag; only an exact one does (decision 5).
- E. The flag alerts nobody and sends no e-mail; it shows on screens, a filter and a dashboard count (decision 5).
- F. "Listed for tomorrow" stays a cause-list alert; an order date tomorrow raises the critical "Hearing tomorrow" /
  "Hearing around" alert instead (decision 10).
- G. Readings a person rejected under the old rules stay rejected (their replacement date stays, until the court gives
  a date); the command lists them (decision 13).
- H. Decided by the owner (28 Oct 2026): entering a date is **not** allowed when the court's last date has passed —
  court dates are ultimatums; a passed court-given date stays the value as Date Passed (decisions 4 and 6). Entering
  is allowed only where the court gave no date at all (no direction, unclear, no text, or no order and no court
  date).
- I. Correcting takes the right date in the same step, optional; without it the order goes to Next Dates to Enter
  (decision 18).
- J. A corrected date is a manual date: a holder of `next_dates.review` with a working basis may later enter a
  different one, until the court gives a date (decision 18).
- K. Defaults: Report Wrong Next Date for the department head, department admin, department officer and directorate
  user; Correct Misread Next Date for the Super Administrator only (decision 19).

## Deviations

Recorded by the developer while building (28 Oct 2026); the smallest reasonable choice where the design was silent.

1. **The super admin meets the 403 first.** A Super Administrator holds no other membership and cannot hold a file, so
   never has a working basis on a department's case: enter, confirm and reject answer 403 `not_working_on_case` before
   the 409 `court_date_fixed` of decision 6 (the order of checks the decision keeps). The outcome the owner asked for
   holds: nobody edits a court-given date. `test_court_date_fixed.py` asserts 409 for the department officer, admin
   and head and 403 for the super admin; `workflow.next_dates_blocked` says `court_date_fixed` for every reader.
2. **The `next_dates.correct` description is shortened** to the 120-character rule of the user-type pages
   (`test_permission_groups.py`): "Mark a next date read from an order as wrong and enter the right date if the order
   shows it. Court records never change."
3. **`next_hearing_set_at` is written on every computation** (the rollover rule needs to know when a value was made),
   so the `set_updated_at` trigger also moves `cases.updated_at` when a refresh runs.
4. **Rollovers** (Jobs): `refresh_due` takes the cases whose stored date has passed since it was computed (a value that
   was already passed when computed cannot change with time alone, so the ultimatum dates of decision 4 step 3 are not
   recomputed every five minutes) and the cases whose differing order date has passed; at most `batch` a run, the
   case locks taken with `SKIP LOCKED`, written 500 at a time.
5. **A dated reading also closes older dates.** `read_order` runs `supersede_older` for a dated reading of the current
   order too (it already did for a reading without a usable date), so the open readings of older orders and older
   manual rows close when a newer order gives a date, and a later correction of the newer reading never falls back to
   an older order's date. A manual or confirmed row closed this way is audited `next_date.superseded_by_court` with
   `replaced_by.basis = "newer_order"` (decision 7's second sentence).
6. **A `none` reading raises its review event only on a claimed case.** An unclear or scanned order keeps the old
   behaviour (the event, then the scan checks the owner); an order with no next date at all on an unclaimed case raises
   no event, so the pool's many final and procedural orders do not fill the events table.
7. **The personal dashboard's `confirm_next_date` item now lists enter items** (title "Next date to enter", the date to
   answer by, the reason in words, `next_date_id` null), since confirm items no longer exist; the API kind keeps its
   name and the headline figure `next_dates_to_confirm` counts the enter items ("Next Dates to Enter").
8. **The local model is not given a manual date.** The Case Details source says "Next hearing: <words>" from the one
   value as decision 11 asks, except when the value is a date entered by hand: assistant-polish decision 6 (an
   officer's entry is never put to the model) is kept, and the line then reads "No next hearing known". The quick
   fact (answered without a model) states every basis.
9. **A case never computed is computed on the spot when read.** `next_hearing.outs` computes the value without writing
   for a case whose `next_hearing_set_at` is null, so lists and pages are right before the backfill reaches it; the
   filters and sorts read the stored column (empty until then), as decision 13 expects.
10. **Report and Correct act on the Overview card's reading row** (`next_date_from_orders.id`, the latest open order
    reading), because `NextHearingOut` carries no row id; the server checks that it is decision 17's row. The "Correct
    It" link of a `next_date_reported` alert opens the case page with `?nd=correct`, which opens the dialog when
    `workflow.next_date_correct` allows it. "Reading Is Right" is the dialog's left footer button, shown while a report
    is open.
11. **The `next_differs` filter** is one more shared field, a check under More Filters, on every case list (not on the
    Claimed › Disposed list, which has no next-hearing filter either).
12. **A passed listing is the court's last given date** (decision 4 step 3 counts the listings), so a disposed case keeps
    its last listing date as its stored value; the badge reads Disposed, and a next-hearing range over past days can
    match it.
13. **The rail's Enter Next Date link** stays where it was (only when the case has no next hearing at all); a case
    whose only date was entered by hand enters a new one from the Overview card, by `workflow.next_dates`.
14. **The migration test** writes the refusing `next_date_reported` alert with `session_replication_role = replica`,
    since a wiped database has no case or office rows to point at.
15. **A row the caller cannot open shows only the court's tiers of the next hearing** (review finding). `CaseSummaryOut`
    is court-public and is returned for cases the caller cannot open (`GET /cases/search`, the court search, cause-list
    rows, the case's links, discovery term cases, the Assistant's court-record view). On those rows
    `next_hearing.court_public` blanks a `manual` or `confirmed` value (a department's own record) and drops `differs`
    and `reported_at`; the `court`, `order` and `around` tiers, read from the court's record and order text, stay.
    `inbox.summaries` takes `hidden` (the ids the caller cannot open) for this; the Assistant view applies the same
    helper when `case_visible` is false.
16. **A report after a closed one takes a numbered key** (review finding). `alerts.dedupe_key` is unique across every
    status, so decision 17's key `next_date_reported:<next_date id>` is used for the first report of a reading and
    `next_date_reported:<next_date id>:<n>` (n = 2, 3, ...) for a later report made after the earlier ones were closed
    (kept, corrected or expired). Every lookup of the open report (the 409 `already_reported` check, Correct, Reading Is
    Right, the case page's `reported_at`) matches the reading id in the key's second part, whatever the number.
