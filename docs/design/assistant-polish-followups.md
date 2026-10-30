# Design: Case Assistant polish follow-ups (row 198 review advisories)

```
slug: assistant-polish-followups
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 202. The row 198 review (`docs/reports/2026-10-28-assistant-polish.md`, "Review findings") left four
advisories on the approved design `docs/design/assistant-polish.md` (decisions 7, 12 to 16, deviation 5). Each was
checked against `main` (eeb3424) on 30 Oct 2026; none is fixed yet.

1. **The "nothing found" line points below.** `NO_ANSWER_TEXT` (`backend/aslms/services/assistant_ollama.py:88`,
   used at line 634 when the model cites nothing) reads "…The sources searched are listed below; check them
   yourself." Since decision 16 a local-model answer lists no sources under it; they open from the "Sources (n)" button
   in the answer's footer (`frontend/src/components/assistant/Assistant.tsx:391-396`, shown because a `no_match` answer
   still carries labelled citations, deviation 5).
2. **A quick fact's source dialog says "Text Given to the Model".** `TextGiven` (`Assistant.tsx:148-157`) is drawn
   for every labelled citation, in the single-source dialog (`SourceDialog`, line 558) and in each item of "Sources of
   This Answer" (`SourceItem`, line 226). For a quick fact (`engine.kind = "case_record"`, decision 15) no model was
   called.
3. **S1 of a quick fact does not back every value the answer states.** The quick fact is built from
   `assistant_facts.facts_of` and `assistant_facts.next_hearing` (`services/assistant_facts.py:216-236, 288-339`);
   S1 is re-read at read time by `_details_out` (`services/assistant.py:1650-1687`) through
   `assistant_sources.case_details` and rendered with the model's `details_text`
   (`assistant_ollama.py:188-258`). Checked value by value, S1 lacks:
   - a date entered by hand: `case_details` blanks a `manual` next hearing (`assistant_sources.py:353-354`), which is
     right for the model (decision 6) but leaves the quick fact's "entered by hand" date without a source;
   - the party counts by side and the summaries when party rows exist (`case_contexts` puts the party names or, only
     when there are none, the summaries in one list, `assistant_sources.py:238-251`);
   - the printed advocate fields when advocate rows exist (same rule, line 252), which the answer prefers;
   - the disposal date and nature (`case_contexts` has only `status`);
   - the last order's date and number (not in `case_details` at all);
   - the bench fallback from the latest hearing (`bench_text`): the stored quick-fact citation asks for 0 hearings
     (`assistant_facts.citation`, lines 412-422);
   - the differing order date of a `court` next hearing ("The order of … gives …", `assistant_facts.py:271-275`).
4. **Case Details is re-read once per citation on every conversation read.** `messages_out` calls `_details_out` for
   each `case_details` citation of each message (`assistant.py:1749-1752`), and each call runs `case_details` for one
   case: four `case_contexts` queries, the hearings and listings queries, and `next_hearing.describe_case`
   (`assistant_sources.py:349-354`), whose detail form adds three more (the `next_dates` rows, their orders and the open
   report alerts, `services/next_hearing.py:668-751`). A conversation of ten answers on one case re-reads the same Case
   Details ten times. The review's other option, skipping the next hearing for the short form, is refused: the short
   (compact) form given to the model also carries the "Next hearing:" line (`details_text`, line 224), so S1 would no
   longer show what the model read.

Not covered: the wording of stored answers (append-only `assistant_messages`; old `no_match` answers keep their text);
the `confirmed` tier on rows the caller cannot open (row 203, item 7, which also edits `case_details`); My Work (row
189).

## Decisions
1. **New wording of the line:** `NO_ANSWER_TEXT = "No answer supported by the records was found. Open Sources to see
   the records searched and check them yourself."` "Sources" matches the button's label ("Sources (n)"). Only new
   answers carry it; stored answers are never rewritten. Alternative: hide the button and list the sources under a
   `no_match` answer (refused: it brings back the inline list decision 16 removed, for one outcome only).
2. **For a quick fact the block is renamed, not hidden: "Facts From the Case Record", shown open.**
   - `TextGiven` takes the message's kind: for `isCaseRecord(m)` its summary reads `A.factsUsed` = "Facts From the Case
     Record" and the `<details>` is `open`; for a model answer it stays "Text Given to the Model", collapsed.
     `SourceItem` gets a `record` flag from its message for the "Sources of This Answer" list.
   - **Deviation from the review's advisory, flagged:** the review asks to hide the block. Hiding it would leave the
     quick fact's S1 dialog with only "Case Details" and a link, so the reader could not check the stated values in the
     dialog; decision 3 makes that text exactly the evidence. Renaming removes the wrong statement (no model) and keeps
     the evidence. If the owner prefers hiding, the change is one condition and decision 3 still applies to "Open Case
     Details".
   - `labels.test.ts` covers the new key (Title Case).
3. **S1 of a quick fact is the facts form of the case record: every value the six facts can state.**
   - A new pure `assistant_facts.source_text(values, nh) -> str` (no connector import), from the same `facts_of`
     values and the same `NextHearing` the answer is built from:
     - `Case number: …; CNR: …; Court: …` (as the first line of `details_text`);
     - `Petitioners (as printed): <petitioner_summary or "not recorded">`; `Respondents (as printed): …`;
     - `Parties tab: <p> petitioners, <r> respondents; first petitioner: <name>; first respondent: <name>` (counts
       from the current `case_parties` by role, `party_no` order, the same rows the answer counts);
     - `Advocates for the petitioners (as printed): …; listed: <names joined by "; ">`, and the same for the
       respondents;
     - `Status: Pending` or `Status: Disposed of on <date>, <nature>` or `Status: not given`;
     - `Last order: <date> (No. <no>)` or `Last order: none held`;
     - `Bench: <coram> (<bench_name>)`, and `Latest hearing's bench: <bench_text>` when held;
     - `Next hearing: <the quick fact's own next-hearing words>` (all bases, the date entered by hand included),
       `Court's own record: <date>, for <purpose>` when held, and `Order of <order date> gives <date>` when a `court`
       value carries a differing order date.
     Dates in the portal's form (05 Nov 2026), names exactly as printed. Values not held are said in words.
   - `_details_out` takes `facts_form: bool` (`m.connector == assistant_facts.CONNECTOR`, as `messages_out` already
     computes at line 1823). For a quick fact it renders `source_text` in place of `details_text`; everything else of
     the citation (availability, open link, merged case unavailable) is unchanged.
   - **Visibility:** the facts form is re-read under the reader's sight, as decision 14 says. When the reader can no
     longer open the case (`case.id not in visible`), the next hearing goes through `next_hearing.court_public`, so a
     date entered by hand or a confirmed reading is not shown (next-date-direct deviation 15).
   - **The model's Case Details is unchanged:** `details_text` still leaves out a date entered by hand (decision 6).
   - Alternative: add the missing fields to `case_details` for everyone (refused: they would also go to the model,
     including the manual date it must not read, and would lengthen every prompt).
4. **Case Details is read once per conversation read, and its next hearing in one query batch.**
   - `messages_out` keeps a dictionary for the call, keyed by `(case_id, compact, hearings, listings, facts_form)`;
     `_details_out` reads it before running `case_details` / `source_text`. Each distinct key is read once per
     `messages_out` call (a conversation read, or the one new answer). The visibility set is the call's own, so the
     cache never crosses readers or requests.
   - `assistant_sources.case_details` replaces its per-case loop (lines 344-354) with one
     `next_hearing.outs(session, rows, detail=False)` for all the cases it was given (the stored columns, one query
     for the rows and one for the orders), and `case.coram` from the `Case` rows `case_contexts` already loaded. The
     list form is enough: `details_text` and `next_hearing.words` use the date, basis, around words, order and
     `differs`, never `phrase`, `court_date` or `reported_at`; this drops the report-alert query.
   - `assistant_facts.next_hearing` keeps `describe_case` (one quick fact, one call).
   - Measured in a test by counting calls, not queries (decision tests). Alternative: store the rendered Case
     Details on the message (refused: decision 14 re-reads under the reader's current sight).
   - **Overlap with row 203:** row 203 item 7 adds an `open_ids` argument to `case_details` (the `confirmed` tier only
     for cases the caller may open). Whichever row is built second keeps both changes; neither changes the other's
     rule.

## Data
No table, no column, no migration. Stored answers and citations are unchanged (`assistant_messages` is append-only;
the facts form is rendered at read time).

## Services
- `services/assistant_ollama.py`: `NO_ANSWER_TEXT` (decision 1).
- `services/assistant_facts.py`: `source_text(values, nh) -> str` (decision 3), pure.
- `services/assistant.py`: `_details_out(session, user, c, visible, *, facts_form, cache)`; `messages_out` passes
  `facts_form` per message and one `cache` dict per call (decisions 3 and 4). No audit change: reading a conversation
  is not audited today and stays so.
- `services/assistant_sources.py` `case_details`: one `next_hearing.outs(..., detail=False)` for all cases
  (decision 4); a `manual` value is still blanked for the model.

## API
No endpoint, request or response shape changes. `GET /assistant/conversations/{id}` (and the answer returned by a
question) carries a different `citations[].context` text for quick-fact answers (decision 3). Functions unchanged:
`assistant.use` for reading one's own conversations; visibility as decision 14 of `assistant-polish`.

## Jobs
None.

## Tests
pytest:
- `tests/unit/test_assistant_facts.py::test_source_text_lists_every_value`: from a `facts_of`-shaped dict and a
  `NextHearing` per basis (court with a differing order, order, around, confirmed, manual, none, disposed), every value
  each `*_lines` function would state appears in `source_text`.
- `tests/db/test_assistant_facts.py::test_quick_fact_source_backs_every_value`: a case with both summaries, 4
  petitioner and 5 respondent rows, printed advocate fields and advocate rows, a disposal date and nature, two orders,
  no coram but a hearing with `bench_text`, and a manual next date: ask each of the six facts; for each answer, every
  date, count, number and name in `content` is found in `citations[0].context`.
- `tests/db/test_assistant_facts.py::test_quick_fact_source_hides_a_manual_date_from_a_reader_who_lost_the_case`:
  after the asker loses sight of the case, S1's context no longer carries the manual date.
- The existing `test_quick_fact_rereads_under_reader` and
  `test_the_one_next_hearing_given_to_the_model_never_manual` pass (the model's text is unchanged).
- `tests/db/test_assistant_ollama.py`: the existing `no_match` test asserts the new `NO_ANSWER_TEXT`; a unit
  assertion that it contains "Sources" and not "below".
- `tests/db/test_assistant.py::test_case_details_read_once_per_conversation_read`: a conversation of five answers
  each citing the same case's Case Details; `messages_out` calls `assistant_sources.case_details` once (monkeypatched
  counter); a second `messages_out` call reads again (no cache across calls).
- `tests/db/test_assistant.py::test_case_details_reads_next_hearings_once`: `case_details` for three cases calls
  `next_hearing.outs` once with `detail=False` (counter), and the rendered text equals today's for each case.

vitest (`frontend/src/components/assistant/assistant.test.tsx`):
- a quick-fact answer's S1 dialog shows "Facts From the Case Record", open, and no "Text Given to the Model";
- a local-model answer's dialog still shows "Text Given to the Model", collapsed;
- "Sources of This Answer" of a quick fact uses the same label.

## Verification
1. `ruff check` clean; `pytest -q` green; frontend `tsc`, `eslint`, vitest green; `gen:api` no diff.
2. No migration: `alembic heads` unchanged.
3. Screen check on a private network (runbook section 16) passes with no finding.
4. Owner's browser check at http://localhost:3000 on a case's Assistant tab:
   - "who are the parties", "when is the next hearing", "which bench": open S1; each value of the answer is in "Facts
     From the Case Record";
   - a question the records do not answer: the line says "Open Sources…", and Sources (n) lists what was searched.

## Open questions
None. Decision 2 departs from the review's wording (rename, not hide) and is flagged for the owner's approval of this
note.
