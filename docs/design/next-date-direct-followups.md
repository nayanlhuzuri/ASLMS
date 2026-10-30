# Design: Next hearing follow-ups (row 199 review advisories)

```
slug: next-date-direct-followups
status: awaiting-approval
author: architect
date: 2026-10-30
approved_by: —
```

## Context
Backlog row 203. The row 199 review (`docs/reports/2026-10-28-next-date-direct.md`, "Review findings") closed its two
blocking findings in f69fcb0 and left seven advisories on the approved design `docs/design/next-date-direct.md`
(decisions 4, 6, 7, 13, 17, 18; deviations 5, 8, 10, 15). Each was checked against `main` (eeb3424) on 30 Oct 2026;
none is fixed yet and none is dropped. Items 2 to 4 are one change to `next_hearing.compute`; they are designed
together.

1. **Every manual date with an order reads as a correction.** `basisLine`
   (`frontend/src/lib/hearingDate.ts:89-107`, lines 100-102) shows "Corrected by hand: the date read from the order of
   … was wrong" whenever a `manual` value carries an order. A date entered from Next Dates to Enter is linked to the
   order it answers (`next_dates.enter` with `order_id`, `services/next_dates.py:1182-1214`), so a plain entry for an
   unclear or dateless order is called a correction. The server sends no field that tells the two apart.
2. **A corrected date is superseded at once.** `correct` (`next_dates.py:1633-1712`) rejects the reading, writes a
   `manual` row linked to the same order (`_insert_corrected`, 1715-1752) and refreshes. `compute`
   (`services/next_hearing.py:149-238`) then ranks that row at step 4 (a date entered by hand), below:
   - step 3's passed court date: a NAPIX date or listing after the order but already passed (`_merge`, lines
     262-264) wins, the value is court-given, and `_supersede_manual` (392-444) closes the correction with an audit
     row, in the same transaction;
   - a second open reading at step 2: the readings query takes the latest open reading of **any** order (190-210), so
     another open reading (an older order's, or a second reading of the same order left by a `--reread`) wins the same
     way.
   Owner answer 5 (design Context) makes correcting "the only path that changes a court-given date read from an
   order"; a correction erased by the very rule it corrects defeats it.
3. **Step 3 prefers a passed court date over a passed reading of the latest order.** `_merge` returns `max(passed)`
   of the court's dates (262-264) before it looks at the reading (265-266). Decision 4 step 3 keeps "the latest
   court-given date (the court's record, or a dated reading of the latest order)", so the later of the two must win.
4. **Step 2 uses an older order's reading.** The reading of step 2 is the latest open reading of the case, whatever its
   order (190-210, 254, 260-261), although decision 4 says "the latest order's reading". It happens when the latest
   order is not read yet: an order without its PDF or text is never a candidate of the reader
   (`next_dates.candidates`, 662-670, joins `documents` and needs readable text), so `supersede_older` never runs for
   it and the older reading stays open. The case then shows the older order's date as court-given, `enter` answers
   409 `court_date_fixed` (decision 6) and the order is not an enter item.
5. **`correctors` loops over every membership under the case lock.** `next_dates.correctors` (1508-1525), called by
   `report_wrong` while it holds the case lock, reads every active membership of every active login and builds each
   one's functions (`access.member_of`) before checking `next_dates.correct` and visibility.
6. **The two repair commands lock every live case in one transaction.** `next_hearing.refresh_all` (576-602) refreshes
   page after page in one session; each page's `FOR UPDATE` locks are kept until the command's single commit
   (`cli/next_dates.py:124-139` and 143-165 use one `session_scope`). On 29 Oct the integrator stopped the worker and
   scheduler for `direct --apply` (report, "Deploying"). `direct_apply` also counts `enter_items_added` (1933-1938)
   for every enter item even when its `next_date_extracted` event already exists, because `emit_event`
   (`services/cases.py:162-186`) returns nothing when its dedupe key is taken; the dry run counts the same way.
7. **The model's Case Details blanks only `manual`.** `assistant_sources.case_details` (349-354) drops a `manual`
   next hearing but keeps `confirmed`, also for cases the asker cannot open: the court-passage cases of the All court
   orders scope get the compact Case Details (`assistant_ollama.py` `_gather_in`, 707-742), and S1 is re-rendered at
   read time for any reader (`assistant.py:1650-1687`). Deviation 15 treats `confirmed` as a department's record on a
   row the caller cannot open (`next_hearing.court_public`, 791-801), as the court-record view already does
   (`assistant.py:1993-1995`).

Not covered: the Overview card's "Next Date From Orders" (`next_dates.effective_for_case`, 1307-1324) keeps listing the
latest open reading of any order, as information; the portal screens of row 73; rows 200 and 74.

## Decisions
1. **The server says when a manual date is a correction: `NextHearingOut.corrected`.**
   - A `manual` value is a correction when its row is linked to an order **and** that order has a `rejected`
     order reading (`order_specific` / `order_period`). That is the state both `correct` (decision 18) and the earlier
     "Not correct" with a replacement leave behind, and also an entry made later for an order whose reading was marked
     wrong: in every case "the date read from that order was wrong" is true. A plain entry for an unclear, dateless or
     unreadable order (no rejected reading) is not a correction.
   - `next_hearing.outs` adds `corrected: bool` to each item (false for every other basis): one query for the page,
     `select distinct order_id from next_dates where order_id in (…manual rows' orders) and source in ORDER_SOURCES
     and review_status = 'rejected'`. `NextHearingOut` gains `corrected: bool = False`; `openapi.json` and
     `schema.d.ts` are regenerated. `court_public` still blanks every `manual` value.
   - `basisLine`: `manual` → `next.corrected && od ? T.hearing.basis.corrected(od) : T.hearing.basis.manual`.
   - The same flag gives the same words in `next_hearing.words` ("<date> (corrected by hand; the order of <date> was
     misread)") and the quick fact's line (`assistant_facts._next_lines`, "(corrected by hand: the date read from the
     order of <date> was wrong)"), so the alert texts and the Case Assistant match the badge.
   - Alternative (the review's): read the `next_date_reviewed` event's action. Refused: events are the timeline, not
     the state; the rejected reading is the state the event records, readable in one set query for a page of rows.
2. **The latest order's step: a reading or a correction of an order dated O, the newest first** (items 2 and 4;
   decision 4 step 2 as written, decision 18 as owner answer 5 intends).
   - O is the latest `order_date` among the case's orders, as today (all orders, with or without a PDF).
   - The candidates of step 2 are the open order readings (`not_needed`, `pending`, `confirmed`) of orders dated O,
     and the open `manual` rows linked to an order dated O that are corrections (decision 1). The candidate is the
     newest by (`created_at`, `id`).
   - Step 2: the candidate when its date ≥ T. A reading keeps its basis (`order`, `around`, `confirmed`); a correction
     has basis `manual` with `corrected` true.
   - So a correction stands where the reading it corrects stood: above step 3 (a passed court date) and above any
     older reading. Only step 1 outranks it, a court date ahead after O, and decision 7 then supersedes it with its
     audit row, which is decision 18's "decision 7 replaces it when the court gives a date". A newer order replaces it
     through `supersede_older` (deviation 5), audited.
   - A reading of an older order is never step 2 or step 3 any more. When the latest order has no reading yet, the
     case shows no date from orders: a court date (steps 1 and 3), else an entered date (step 4), else none. Entering
     is then allowed (decision 6: the court has given no date the system can read) and is superseded when the order is
     read with a date (decision 7). The integrator measures how many cases this moves (Verification 3).
   - The discrepancy flag (decision 5) looks at the candidate only when it is an exact reading (`order`,
     `confirmed`), as today; a correction never raises it.
   - `reportable_row` (`next_dates.py:1460-1476`, decision 17's row) follows step 2: the candidate when it is a reading
     dated today or later, else None. The candidate query is one builder in `next_hearing` used by both `compute`
     (set-based) and `reportable_row` (one case).
   - **Change to approved decision 18, flagged:** decision 18 said the correct date "is a manual date: decision 4 ranks
     it below any court record". It now ranks below a court date ahead only. Alternatives: keep the ranking and
     refuse a correction with 409 when a passed court date or another reading would outrank it (refused: the
     corrector could then never fix a misread order once a listing date has passed, which is the common case); a new
     basis `corrected` (refused: an enum value and a migration for what one boolean says).
3. **Step 3 takes the later of the court's passed date and the latest order's passed reading** (item 3).
   Candidates: the court's dates after O and before T (`cases.next_hearing_date`, current listings; basis `court`)
   and the step-2 candidate when it is a reading dated before T (its own basis). The value is the latest date; on a
   tie, `court`. A passed correction is not a step-3 candidate (it is an entered date; when it passes, the case falls
   to step 4 or none, and entering is allowed as for any passed manual date).
4. **`correctors` reads the holders in SQL first** (item 5).
   - A new `access.memberships_holding(session, permission) -> list[tuple[UserMembership, User]]`: active memberships
     of active logins where the membership is the super admin's, or an active in-date `grant` override of the
     function exists, or the type matrix enables it (`role_permissions.is_enabled`) and no active in-date `deny`
     override exists. "Active in-date" is `is_active` and `valid_from ≤ today ≤ valid_to` (or no `valid_to`), the rule
     of `access.membership_overrides`. A reserved or retired function returns only super admins, as
     `membership_functions` does.
   - `correctors` builds `member_of` only for those rows, keeps `holds(NEXT_DATES_CORRECT)` as a check, and calls
     `visibility.can_view_case` once per person. The result and its order (by e-mail) are unchanged.
5. **The repair commands commit per page; the events are counted when written** (item 6).
   - `refresh_all(session, …, page=…, commit=None)` calls `commit()` after each page when given. `hearing_refresh`
     and `direct_apply` take `commit` and pass it on; `direct_apply` also commits after step 1 (the old pending
     readings shown directly). The CLI passes `s.commit` for `--apply` and for `hearing-refresh --all`, with pages of
     1,000 cases (`next_hearing.CLI_PAGE = 1000`); `refresh_due` keeps its 5,000 and its single transaction.
   - Each page holds its case locks for that page only. A stop or failure keeps the pages already written; running the
     command again finishes the rest (both are idempotent: a refreshed case refreshes to the same value, and a second
     `--apply` finds nothing). The closing audit row (`next_dates.direct_apply`, `next_dates.hearing_refresh`) is
     written at the end, as today; each superseded manual row already has its own audit row in its page.
   - `emit_event` returns `True` when it writes the event and `False` when the dedupe key exists (existing callers
     ignore the value). `_extracted_event` returns it; `direct_apply` counts `enter_items_added` only for `True`. The
     dry run counts an enter item only when its `next_date_extracted:<order id>:<rules version>` key does not exist,
     so the dry run and `--apply` agree.
   - Runbook `docs/operations.md` section 21: run `direct --apply` and `hearing-refresh --all` in a quiet window with
     the worker and scheduler stopped (`docker compose stop worker scheduler`, then start them again with the
     court-data switch), as on 29 Oct; each page of 1,000 cases is committed on its own; a second run completes an
     interrupted one.
6. **The Case Details given to the model shows the `confirmed` tier only for the case the asker may open** (item 7).
   - `assistant_sources.case_details(…, open_ids=())`: for a case in `open_ids` the next hearing is the value with
     `manual` blanked (today); for any other case it is `next_hearing.court_public(value)` (`manual` and `confirmed`
     blanked, `differs` dropped).
   - `_gather_in` passes `{focus_ids[0]}` when it builds the full form for the focus case (a case of the asker's own
     scope); every compact case from court passages gets the court-public value.
   - `_details_out` passes `{case.id}` only when the citation is the full form (`compact` false) and the reader may
     see the case now (`case.id in visible`), so the re-rendered S1 never shows more than the model was given and
     never more than the reader may see.
   - **Overlap with row 202** (one `next_hearing.outs` call in `case_details`, a read cache in `messages_out`):
     whichever row is built second keeps both; `open_ids` applies to the batched values.

## Data
No table, no column, no index, no reference code, no migration. `NextHearingOut.corrected` is computed, not stored.
`schema.md` is unchanged: the six `cases.next_hearing_*` columns keep their meaning; the developer appends to
`next-date-direct.md` a "Follow-ups (row 203)" section restating steps 2 and 3 and the changed sentence of decision 18,
and the scribe logs it.

## Services
- `services/next_hearing.py`:
  - the step-2 candidate builder (readings and corrections of orders dated O, newest first) used by `compute` and
    `reportable_row`; `_merge` for decisions 2 and 3; `_Reading` gains `created_at` and `corrected`;
  - `outs`: `corrected` per item (decision 1); `words` with the corrected wording;
  - `refresh_all(..., commit=None)`, `CLI_PAGE = 1000` (decision 5).
- `services/next_dates.py`: `reportable_row` through the builder; `correctors` through
  `access.memberships_holding`; `direct_apply(..., commit=None)` and `hearing_refresh(..., commit=None)`; the dry run's
  dedupe check; `_extracted_event` returns the `emit_event` result.
- `services/access.py`: `memberships_holding(session, permission)`.
- `services/cases.py`: `emit_event` returns `bool`.
- `services/assistant_sources.py`: `case_details(..., open_ids=())`; `services/assistant_ollama.py` `_gather_in` and
  `services/assistant.py` `_details_out` pass it (decision 6).
- `services/assistant_facts.py`: `NextHearing.corrected` and the corrected line (decision 1).
- Audit: unchanged rows and actions (`next_date.superseded_by_court` keeps being written by decision 7 and by
  `supersede_older`; `next_dates.direct_apply`, `next_dates.hearing_refresh`). No new action.

## API
| Method and path | Function (`Permission`) | Change |
|---|---|---|
| Every response carrying `NextHearingOut` / `NextHearingDetailOut` (`GET /cases/{ref}`, the case lists, inbox, calendar, dashboard, `POST /next-dates/{id}/correct`, …) | unchanged per endpoint | adds `corrected: bool` (false except a correction); a row the caller cannot open still gets `court_public` (no manual value at all) |
| `POST /next-dates/{id}/report` (`next_dates.report_wrong`), `POST /next-dates/{id}/correct` and `/keep` (`next_dates.correct`) | unchanged | the reportable row follows decision 2 (409 `not_reportable` / `not_order_reading` for an older order's reading) |
| `POST /cases/{ref}/next-dates` (`next_dates.review`) | unchanged | 409 `court_date_fixed` no longer raised by an older order's reading (decision 2) |

## Jobs
No new job. The 5-minute `aslms.next_dates_read` job (`refresh_due`) uses the new `compute`; on the first runs after
deploy only rollovers change. The CLI commands commit per page (decision 5).

## Tests
pytest, `tests/db/test_next_hearing.py`:
- `test_a_correction_stands_where_the_reading_stood`: order O with a reading 15 days ahead and a NAPIX date after O
  already passed; correct to 20 days ahead → value `manual`, `corrected` true, the manual row open, no
  `next_date.superseded_by_court` row; then a NAPIX date ahead → `court`, the correction superseded with its audit
  row.
- `test_a_correction_beats_a_second_open_reading`: two open readings of order O (a reread left both); correct the
  newer → the correction is the value, the other reading is not.
- `test_an_older_orders_reading_is_not_the_latest_orders`: an older order read with a date ahead, a newer order with
  no PDF → value none (no court date), `court_given` false, `reportable_row` None, `enter` allowed; once the newer order
  is read with a date, that date is the value and the manual date is superseded.
- `test_step_3_takes_the_later_passed_date`: passed court date 10 days ago vs a passed reading of O 5 days ago → the
  reading (`order`); court 3 days ago vs reading 5 days ago → `court`; equal → `court`.
- The existing tests pass, including `test_a_court_given_date_that_passed_stays_as_an_ultimatum` and
  `tests/db/test_next_date_correction.py::test_correct_on_a_case_the_court_has_listed_changes_only_the_order_tier`
  (a court date ahead still supersedes the correction at once).

pytest, other files:
- `tests/db/test_next_date_correction.py::test_corrected_flag_only_for_corrections`: `correct` with a date →
  `corrected` true; an entry from Next Dates to Enter for an unclear order → false; marked wrong without a date, then
  entered → true.
- `tests/db/test_access.py::test_memberships_holding_matches_member_of`: logins with the function by type, by grant,
  removed by deny, an expired and a future override, an inactive membership, an inactive login and a super admin:
  the set equals the memberships whose `member_of(...).holds(...)` is true.
- `tests/db/test_next_date_correction.py::test_report_tells_the_correctors_who_may_see_the_case` passes unchanged.
- `tests/db/test_next_hearing.py::test_refresh_all_commits_each_page`: with `page=2` and a `commit` counter over
  five cases → three commits; a failure injected on the third page leaves the first two pages written.
- `tests/db/test_next_dates_review.py::test_direct_counts_only_events_written`: a second `--apply` reports
  `enter_items_added` 0 and the dry run before it the same number as the first `--apply`.
- `tests/db/test_next_dates_review.py::test_emit_event_returns_whether_it_wrote` (a new event `True`, the same
  dedupe key again `False`, one row).
- `tests/db/test_assistant_facts.py::test_confirmed_only_for_the_case_the_asker_may_open`: a court-passage case the
  asker cannot open with a `confirmed` value → its compact Case Details sent to the model says "No next hearing
  known"; the focus case's confirmed date is given; S1 of the first, re-read, does not show it.
- `tests/unit/test_next_hearing_words.py`: the corrected wording.

vitest, `frontend/src/lib/hearingDate.test.ts` "gives one basis line for each basis": `manual` with an order and
`corrected: false` → "Entered by hand; the court has given no date"; with `corrected: true` → "Corrected by hand: the
date read from the order of 12 Oct 2026 was wrong".

## Verification
1. `ruff check` clean; `pytest -q` green; frontend `tsc`, `eslint`, vitest green; `gen:api` shows only `corrected`.
2. No migration: `alembic heads` unchanged.
3. Before `up`, with the newly built image (a one-off `docker compose run --rm --no-deps api aslms next-dates
   hearing-refresh --all --dry-run`; a dry run writes nothing and calls no court service): `would_change` and the
   counts by basis show how many cases lose an older order's date (decision 2) or change at step 3; the integrator
   records the numbers in the report. After deploy, in a quiet window
   with the worker and scheduler stopped (runbook section 21), `hearing-refresh --all` commits page by page;
   `aslms next-dates status` before and after.
4. Owner's browser check at http://localhost:3000: on a case corrected through Correct Misread Next Date, the header
   keeps the corrected date with "Corrected by hand…"; on a case answered from Next Dates to Enter, the line reads
   "Entered by hand; the court has given no date".

## Open questions
None. Decision 2 changes one sentence of approved decision 18 and is flagged for the owner's approval of this note.
