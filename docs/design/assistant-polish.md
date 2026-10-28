# Design: Case Assistant polish (Enter sends, fewer repeated answers, quick facts from the case record, sources on click)

```
slug: assistant-polish
status: approved
author: architect
date: 2026-10-28
approved_by: (pending)
```

## Context
Backlog row 198. The owner tried the Case Assistant on the local model (`ASSISTANT_MODE=ollama`, `qwen3.5:4b`, design
`assistant-ollama`, row 188) and asked on 28 Oct 2026 for four changes:

1. "after me typing something in the chat box, if i press enter the query should go". Today the composer sends only
   on Ctrl+Enter or Cmd+Enter (`frontend/src/components/assistant/Assistant.tsx`, the `Composer`'s `onKeyDown`).
2. "i am getting a lot of repeated answers".
3. "for specific questions like when is the next date, who are the parties, it should provide me crisp answers".
4. (sent the same day, through the coordinator) "instead of displaying the sources like the current one, you can keep
   it hidden and only when i click on the reference, it may be displayed via a modal."

**What the stored conversations show** (read-only SELECTs on `assistant_messages`, 28 Oct 2026; six ollama answers in
two case-tab conversations, both court-only, the owner's own):

- **The repetition is real and measurable.** In conversation `01a180fa…` (WP(C)/2615/2026) the owner asked "What did
  the last order direct?" and then "so me as the head of the department, what do i need to do?". The second answer is
  the first answer again, word for word apart from the `[S#]` markers. Word 4-gram containment of each answer in the
  earlier answers of its conversation (the measure of decision 9):

  | Conversation | Answer | Overlap with earlier answers | Words |
  |---|---|---|---|
  | WP(C)/39/2024 | 1, 2 | 0.00, 0.04 | 107, 50 |
  | WP(C)/2615/2026 | 1 "What did the last order direct?" | 0.00 | 131 |
  | | 2 "…what do i need to do?" | **0.90** | 127 |
  | | 3 "when is the next hearing date as per the latest court order?" | 0.21 | 147 |
  | | 4 "summarize the whole case." | 0.04 | 169 |

- **Why it happens** (`services/assistant_ollama.py`, `build_messages`):
  - the last `ASSISTANT_OLLAMA_HISTORY_TURNS` (2) questions **and full answers** (markers stripped) go to the model as
    chat turns, and the rule "7. Earlier questions and answers are context only." is weak for a 4B model;
  - temperature is 0, so the same input gives the same output;
  - retrieval searches the new question only. A follow-up with few distinctive words ("what do i need to do") falls
    back to the any-word search (`match: any` on all six answers) and gets the same six orders and the same Case
    Details as the question before. The model sees the same sources plus its own earlier answer about them, and copies
    it;
  - `no_match` answers (the fixed line "No answer supported by the records was found…") are also fed back as history
    (`ANSWERED_OUTCOMES` includes `no_match` in `services/assistant.py`, `_history`), which pushes the model towards
    repeating a refusal.
- **The next-date answer was wrong, not only long.** For WP(C)/2615/2026 the model said "no specific next date was fixed
  in that order". The court's own record (`cases.next_hearing_date`) still says 15 Oct 2026, which has passed. The order
  of 15 Oct 2026 says "let all these matters be listed on 05.11.2026", and that reading is held as the case's next date
  from orders (`next_dates`, `order_specific`, `confirmed`). The "Case Details (Court Record)" source gives the model only
  "Next date (court): 15 Oct 2026" and nothing of the order's reading. A quick fact read straight from the record
  (decision 11) answers "05 Nov 2026" in one line.
- **The parties and advocates are held in the shape a crisp answer needs.** `cases.petitioner_summary` /
  `respondent_summary` hold "DINAR AHMED AND 3 ORS" / "THE STATE OF ASSAM AND 4 ORS". `cases.pet_advocate` /
  `res_advocate` hold "MR. S BANIK, SR. ADV." / "SC, SEC. EDU.". The `case_advocates` rows split the first into "MR. S
  BANIK" and "SR. ADV.", so the printed fields are better for a one-line answer.

**What is in place:**
- row 14 `assistant` (migration 0024): the service's transactions A and B, the audit rows, private conversations;
- row 188 `assistant-ollama` (migration 0032): the Ollama connector, the citation check, the Case Details source, the
  internal-records switch, the source list grouped Court Record / Internal Records with "Text Given to the Model";
- the case page's two next-date values: the header's court date (`status.next_hearing_date`, design
  `next-hearing-highlight`) and the Overview card "Next date from orders" (`next_date_from_orders`, from
  `next_dates.effective_for_case`, design `next-date-extraction` decision 9).

**Rows this interacts with:**
- **Row 199 `next-date-direct`**, designed in parallel. It changes how the next hearing is decided: the court's record
  wins, the latest order's reading is shown directly, a counted period is marked "around", and differences are flagged.
  Decision 13 says how the quick-fact next date follows it.
- **Row 189 `assistant-ollama-work`** (approved, not built): My Work uses the same composer and source rendering.
  Whichever of rows 189 and 198 is built second keeps both working (decisions 1 and 15).
- **Row 195 `assistant-ollama-live-check`**: the owner's live check on the pilot machine. The repeat check of decision
  9 is run there too (Verification 5).
- **Row 188 review advisory 1** (Copy to note numbers versus `[S#]` labels) is fixed here (decision 17).

**Not covered:**
- other languages for quick facts (English only; anything else goes to the model);
- quick facts in My cases, All court orders or My Work;
- any change to retrieval ranking, the internal-records switch, SourceTrace's boundary, the citation check or what is
  stored per citation;
- streaming;
- a model-written query of any kind.

## Decisions

**Item 1: Enter sends**

1. **Enter sends; Shift+Enter inserts a new line; Ctrl+Enter and Cmd+Enter still send.**
   - The rule is in the shared `Composer` of `Assistant.tsx`, so it holds on the case Assistant tab and on the Assistant
     page alike (and on My Work when row 189 is built, since it uses the same composer).
   - The key handler sends only when all of these hold:
     - the key is Enter;
     - Shift is not held;
     - no input-method composition is in progress: `e.nativeEvent.isComposing` is false and `e.keyCode` is not 229
       (the browser's composition code, which older Safari sends instead of `isComposing`).
   - Enter while a question is being answered, or while the text is under 3 characters or over the limit, does
     nothing: no send and no new line (`preventDefault`). This is the same condition that disables the Ask button. It
     covers a double press too, because `ask` already ignores a call while `pending` is set.
   - The textarea gets `enterKeyHint="send"`, so a phone keyboard shows a Send key. The rule is the same on phones, by
     the owner's words; this is owner check 9.
   - **A visible hint** goes in the TextArea's `hint`, which is linked by `aria-describedby`: "Press Enter to send,
     Shift+Enter for a new line." It is shown on every screen width.
   - Alternatives rejected:
     - a setting per user: it adds a preference for one key;
     - Enter sends only on wide screens: the owner asked for it plainly, and the hint says how to add a line.

**Item 2: fewer repeated answers**

2. **Earlier answers are no longer sent to the model; earlier questions are sent as a short context list.**
   - By default the model gets the last `ASSISTANT_OLLAMA_HISTORY_TURNS` (2) earlier questions of the same
     conversation, **not their answers**. They are not sent as chat turns. They go as a block at the top of the last user
     message:

     > Earlier questions in this conversation (context only; they have been answered already):
     > - What did the last order direct?
     > - …
     >
     > Sources:
     > [S1] …
     >
     > Question: so me as the head of the department, what do i need to do?

     The messages become exactly two: the system message, then that one user message.
   - New setting **`ASSISTANT_OLLAMA_HISTORY_ANSWERS`** = `none` (default) | `short` | `full`:
     - `none`: questions only, as above;
     - `short`: each earlier answer goes under its question, cut to its first sentence and at most 160 characters,
       markers stripped;
     - `full`: today's behaviour, chat turns with whole answers, markers stripped. It is kept so the owner's check
       (decision 9) can compare before and after on the same build. It is not a recommended setting.
   - Turns whose answer was `no_match`, `failed`, or hidden from the asker now (as today, decision 10 of
     `assistant-ollama`) are left out in every setting. Their question is not listed either, because the earlier list
     exists to make a follow-up understandable, and a question that got no answer adds nothing to that.
   - The service's `_history` keeps reading `ASSISTANT_HISTORY_TURNS` (6) for the provider-neutral contract (`Turn` is
     unchanged, and SourceTrace and the preview are unchanged). The Ollama connector alone decides what it sends. A
     `Turn` does not say whether its answer was `no_match`, so the exclusion is made in the service: `_history` gains a
     keyword `outcomes`, which the service sets to `("answered",)` for an ollama connector, while the other connectors
     keep `ANSWERED_OUTCOMES`. `Turn` gains no field.
   - Why: the stored conversation shows the copy comes from the earlier answer, not from the sources. Follow-ups such as
     "what do I need to do?" still need to know what was asked before; the question list keeps that. A 4B model cannot
     reliably be told not to copy text that sits in front of it.
   - Alternatives rejected:
     - keeping full answers with a stronger instruction only: the instruction is already there (rule 7) and was ignored;
     - dropping history altogether: follow-up questions lose their meaning;
     - summarising earlier answers with a second model call: it doubles the time, and the summary can repeat just as
       well.

3. **The prompt, version 2 (`PROMPT_VERSION = 2`, stored in `model_info` as now).** Rules 1 to 6 stay word for word.
   Rules 7 and 8 become:
   > 7. Answer only the question after "Question:". The earlier questions are listed only so you understand what the
   > officer means; do not answer them again and do not repeat an earlier answer.
   >
   > 8. When the question asks for one fact (a date, a name, a number or a status), answer in one sentence. Otherwise
   > answer in as few sentences as the question needs, in plain text without headings or tables, and never in more
   > than 200 words.

   Rule 8 is the owner's "crisp answers" rule for everything that is not a quick fact (decision 10).

4. **No repeat penalty.** Ollama's `repeat_penalty`, `presence_penalty` and `frequency_penalty` stay unset.
   - Reason: a penalty works on recently generated tokens. It does not stop copying a whole earlier answer, and it does
     harm answers that must quote names, dates and `[S#]` markers exactly. Repeating "[S2]" or a party's name is
     correct here.
   - Temperature stays 0, so the same question on the same sources still gives the same answer (useful for checking).
   - Alternatives rejected:
     - a mild `repeat_penalty` (1.1): it distorts quoting and does not reach the cause;
     - a temperature above 0: answers vary, and the cause stays.

5. **Retrieval is unchanged, and history never feeds it.**
   - The court search still uses the new question's words only. Earlier questions are not searched, and the list of
     earlier questions is not a source.
   - That the same case gives nearly the same orders is correct: they are that case's orders. With the earlier answer
     no longer in front of the model, the same sources lead to an answer to the new question.
   - Alternative rejected: adding the previous question's words to the search. It would make the sources even more
     alike, and it mixes two questions in one search.

6. **The Case Details source gains the next date from orders and the coram** (court-derived facts only).
   - `assistant_ollama.details_text` adds, in the full form only:
     - "Coram: …" from `cases.coram`, when held;
     - "Next date from the order of <order date>: <date>", when the case's effective next date
       (`next_dates.effective_for_case`) is read from an order (`order_specific` or `order_period`).
   - A `manual` next date is not given to the model. It is an officer's entry, not court information, and the model
     reads court information only by default (`assistant-ollama` decision 3).
   - `assistant_sources.case_details` returns the two values (`coram`, and `order_next_date` holding
     `{next_date, order_date}` or null). It reads them through the same next-date reader as the quick fact (decision
     13), so both follow row 199 together.
   - This fixes the wrong answer above: the model is no longer told only the stale court date.
   - It is a small addition inside court information; owner check 4.

7. **Fixed lines stay out of the model's sight, and the model is not called for them.** This is unchanged: stop
   words and no passage give the fixed line with no model call. The change is only that such turns are no longer fed
   back (decision 2).

8. **Each ollama answer records how much it repeats the previous answer.**
   - `model_info.overlap_prev` is the word 4-gram containment (decision 9) of the new answer in the latest earlier
     answered turn of the conversation, which the connector already has in `request.history`. It is rounded to 2
     places, and null when there is no earlier turn.
   - `model_info.history_answers` records the setting used (`none` / `short` / `full`).
   - Both are numbers and labels only. The `assistant.answered` audit row carries `overlap_prev` beside the counts it
     already holds (`_ollama_audit`).
   - It measures; it never changes or withholds an answer.
   - Alternative rejected: asking again automatically when the overlap is high. That doubles the wait, and at
     temperature 0 the same input gives the same output.

9. **A check the owner can run: `aslms assistant repeat-check`.**
   - **The measure** is `overlap(earlier, later)`, a pure function in `assistant_ollama.py`:
     - lower-case both texts, remove `[S#]` markers, and keep runs of letters and digits as words;
     - take the sets of 4-word sequences;
     - the result is |later ∩ earlier| / |later|, or 0 when the later answer has fewer than 4 words.
     - An answer's **repeat score** is its highest overlap with any earlier model answer of its conversation.
   - **Mode A, stored conversations, no model call:** `aslms assistant repeat-check --user <e-mail> --conversation
     <id> [--conversation <id> …]`.
     - The conversations must be that user's own (`own_conversation`).
     - It prints, per answer: number, outcome, connector, word count and repeat score.
     - It never prints a question or an answer, so nothing private reaches the terminal.
   - **Mode B, a fixed question set, live:** `aslms assistant repeat-check --user <e-mail> --case <ref> [--questions
     <file>]`.
     - It starts a new case conversation as that user and asks the questions in order through the normal service
       (`svc.ask`, `via="cli"`). So the questions are stored, audited, visibility-checked and counted against that
       user's hourly limit like any other question (8 of 30).
     - Then it prints the same table, marking quick-fact answers `case_record` and leaving them out of the scores.
     - The default set is fixed in code: a follow-up chain on one case.
       1. What did the court direct in the most recent order?
       2. So what needs to be done next?
       3. Summarise the order before that in two sentences.
       4. Who are the parties?
       5. When is the next hearing?
       6. What reason was given for the last adjournment?
       7. Is there any direction to file an affidavit?
       8. Summarise the whole case.
     - `--questions` reads one question per line, at most 20.
   - **The pass rule:** no model answer has a repeat score of 0.50 or more.
     - On the stored conversation above, today's build scores 0.90 and fails.
     - The command exits 0 on pass and 1 on fail, and prints the median and maximum score.
     - The threshold is owner check 5.
   - Both modes are refused with `APP_ENV=prod` (exit 2), like `aslms assistant ask`.
   - Alternatives rejected:
     - a similarity model or embeddings: no model library may enter the backend (`no_local_model`);
     - judging by eye only: it gives the owner no number to compare.

**Item 3: quick facts from the case record**

10. **Six quick facts are answered from the case's court record without any model, on the case tab's This case
    scope.** The facts are:
    - next hearing;
    - parties;
    - advocates;
    - status;
    - last order date;
    - bench.

    **Where it applies:**
    - Scope `case` (the case tab's This case), in every mode where the assistant is on: `ollama`, `preview` and
      `sourcetrace`. The answer needs no model and sends nothing anywhere.
    - The asker must hold the case page's read guard (`cases.view_scope` or `cases.view_all`, which
      `internal_records.read_guard` checks), as for Case Details today (`assistant-ollama` deviation 5). An asker
      without it gets today's path: court orders and filings, through the connector.
    - **My cases and All court orders:** no quick facts. There is no single case to answer for, and a case number in
      the question is not resolved. The question goes to the connector as today, where rule 8 asks for one sentence
      when one fact is asked. The asker's own hearings across cases belong to My Work (row 189).

    - **Deviation from the plan, flagged for the owner.** Plan §5.9 describes the Case Assistant as "an AI chat window
      … powered by SourceTrace" that answers "with references". Quick-fact answers are written by fixed code from the
      same court record the case page shows, not by an AI. They keep the plan's references (a cited Case Details
      source). This is owner check 8, and a variation row for the software documentation (decision 18).
    - Alternatives rejected:
      - letting the model answer with a stricter prompt: the stored next-date answer shows that even with the sources
        in front of it a 4B model can get a fact wrong;
      - asking the model to pick a fact through tool calling: it takes a model call and a cold start for a fact the
        server already holds.

11. **How a question is recognised: whole-question patterns in English. Anything else goes to the model.**
    `services/assistant_facts.py`, `recognise(question) -> tuple[str, ...] | None`, is pure and imports no connector.
    1. **Normalise:**
       - lower-case;
       - expand "who's", "what's", "when's" and "where's" to "who is" and so on;
       - drop "'s";
       - turn every character other than letters, digits and spaces into a space, and collapse the spaces.
    2. **Strip fixed fillers.** At the start: "please", "kindly", "can you tell me", "could you tell me", "tell me",
       "let me know", "i want to know", "may i know". At the end: "please", and "of / in / for" followed by "this
       case", "the case", "this matter" or "the matter".
    3. **Match.** The remainder must match **one whole frame** of the table below (anchored at both ends), or **two
       frames joined by "and"**. Three or more facts, or any word left over, means no quick fact.
    4. **Ambiguity rule.** When the question does not match completely, it goes to the model, never to a guess:
       - "What did the last order direct?" goes to the model, because "direct" is not in any frame;
       - "Who are the parties and what did they argue?" goes to the model, because of the words left over;
       - "so me as the head of the department, what do i need to do?" goes to the model.

    | Fact | Frames (after normalising; `( )?` optional, `a|b` either) |
    |---|---|
    | `next_hearing` | `(when is\|what is) (the )?(next )?(hearing\|hearing date\|date of hearing\|next date\|listing\|listing date)`; `(when is\|when will) (the case\|this case\|the matter\|this matter\|it) (be )?(next )?(listed\|heard\|taken up\|coming up\|come up)( next)?`; `(the )?next (hearing\|date\|listing)( date)?`; `(the )?next date of hearing`. Each may end with `(as per\|according to\|in\|from\|by) (the )?(latest\|last\|most recent\|recent) (court )?order` |
    | `parties` | `(who are\|who is\|who were) (the )?(parties\|petitioners?\|respondents?)`; `(name\|names\|list)( of)? (the )?(parties\|petitioners?\|respondents?)`; `(the )?(parties\|petitioners?\|respondents?)( names)?`; `who (filed\|has filed\|brought) (the case\|this case\|the petition\|it)`; `(who is\|who are) (the case\|this case\|it) (against\|filed against)` |
    | `advocates` | `(who are\|who is\|who were) (the )?(advocates?\|lawyers?\|counsels?)( for (the )?(petitioners?\|respondents?\|state\|government))?`; `(who appears?\|who is appearing) for (the )?(petitioners?\|respondents?\|state\|government)`; `(name\|names\|list)( of)? (the )?(advocates?\|lawyers?\|counsels?)`; `(the )?(advocates?\|lawyers?\|counsel)( names)?` |
    | `status` | `(what is )?(the )?(current )?(case )?status`; `is (it\|the case\|this case\|the matter) (still )?(pending\|disposed\|closed\|decided\|over)`; `(has\|was) (it\|the case\|this case\|the matter) (been )?(disposed\|decided\|closed)( of)?`; `(is it )?(pending or disposed\|disposed or pending)` |
    | `last_order` | `(when was\|what is the date of\|date of) (the )?(last\|latest\|most recent\|previous) order( passed\| issued\| made)?`; `(the )?(last\|latest\|most recent) order date`; `when did the court (last )?pass (an \|the )?(last \|latest )?order` |
    | `bench` | `(which\|what) (bench\|judge\|court)( is (it\|the case\|this case\|the matter) (before\|in\|listed before))?`; `before (which\|whom\|what) (bench\|judge)( is (it\|the case\|this case\|the matter)( listed\| pending)?)?`; `(who is\|who are) the (judge\|judges\|bench)`; `(the )?(bench\|coram\|judge)` |

    - The table is fixed in code. A change is a code change with its tests, not a setting; editing it from the
      application is rejected for the same reason as the prompt (`assistant-ollama` decision 7).
    - The owner's own examples match: "when is the next date", "who are the parties", and "when is the next hearing date
      as per the latest court order?" (the last frame with the order tail).

12. **The answer: one or two lines per fact, each ending with `[S1]`, the case's Case Details.**
    - Facts are answered in the order asked, one paragraph each.
    - All values come from the court record the case page shows. A value that is not held is said in words, never
      guessed. Dates use the portal's form (05 Nov 2026) with the weekday. "(today)" or "(tomorrow)" is added from
      `core.clock.today_ist()`, the same IST day as the `HearingDate` badge. Names are given exactly as the court
      printed them.

    | Fact | Wording (values from) |
    |---|---|
    | `next_hearing` | Decision 13 |
    | `parties` | "<petitioner_summary> versus <respondent_summary> [S1]." then "<p> petitioner(s) and <r> respondent(s) are listed on the Parties tab [S1]." Counts are from the current `case_parties` rows by `role`. When a summary is missing, the first current party of that side (`party_no` order) is used, with "and N others". When there are no parties: "No parties are recorded in the court record for this case [S1]." |
    | `advocates` | "For the petitioners: <pet_advocate>. For the respondents: <res_advocate> [S1]." When a printed field is missing, the current `case_advocates` names of that side are joined with "; ". When a side has none: "none recorded". |
    | `status` | "Pending [S1]." or "Disposed of on <disposal_date>[, <disposal_nature>] [S1]." or "The court record does not give the status yet [S1]." (`cases.status`, `disposal_date`, `disposal_nature`) |
    | `last_order` | "The last order is dated <order_date> (No. <order_no>) [S1]." It is the first row of the case's Orders tab order (`orders` of the case by `order_date` desc, `order_no` desc), or "No court order is held for this case yet [S1]." |
    | `bench` | "Before <coram> (<bench_name>) [S1]." (`cases.coram`, `cases.bench_name`). When there is no coram, the latest hearing's `bench_text` is used; when there is neither: "The court record does not name the bench yet [S1]." |

    - Not answered as quick facts, because they are not court record: the owner department, stage, custody, notes,
      recommendations and `ref_no`. A question about them does not match a frame, so it goes to the model, which does
      not hold them either unless internal records are switched on.

13. **Next hearing: the same source as the case page, before and after row 199.**
    - `assistant_facts.next_hearing(session, case)` is the **only** reader of the next hearing for the assistant. It is
      used by the quick fact and by the Case Details line of decision 6.
    - **Until row 199 is built**, it states exactly the two values the case page shows today, without choosing between
      them. The values are:
      - the court's date, `cases.next_hearing_date` with `next_purpose` (the header);
      - the next date from orders, `next_dates.effective_for_case` (the Overview card: order-read or manual, never a
        pending suggestion).

      The wording, from the IST date:

      | Situation | Answer |
      |---|---|
      | Disposed | "The case was disposed of on <disposal_date>; no further hearing is listed [S1]." |
      | Both held, the same date | "Next hearing: <date> [S1]." |
      | Court date today or later, no order date or the same | "Next hearing: <date>, for <purpose> (the court's record) [S1]." |
      | Order date held, court date missing or passed | "Next date from the order of <order date>: <date> [S1]." then, when a court date is held, "The court's own record still shows <court date>, which has passed [S1]." |
      | Both today or later and different | "The court's record shows <court date>. The next date read from the order of <order date> is <date> [S1]." |
      | A manual date | Its line says "entered in ASLMS on <created date>" in place of "from the order of …" |
      | Only a court date, passed | "The last date the court fixed was <date>, which has passed; no later date is held yet [S1]." |
      | Nothing held | "No next hearing date is held for this case yet [S1]." |

      The manual date is shown because the case page shows it to the same person; it never reaches a model (decision 6).
      Owner check 3.
    - **When row 199 is built**, `next_hearing` calls row 199's shared next-hearing reader, the one that row 199's case
      header, calendar and alerts use. The answer then states that reader's result in one line, with row 199's own
      words for "around" (a counted period), the order it was read from, and the flagged difference with the court's
      record.
      - Row 199's developer makes that switch and updates this function's tests. Row 199's design note should name its
        reader for that purpose.
      - The test "the quick fact equals the case page" (Tests) is the guard: it compares the quick fact with the
        overview's values for the same case, so it fails if the two ever diverge.
    - The parties, advocates, status, last order and bench facts are not affected by row 199.

14. **Stored, audited and seen exactly like other answers; no model, no slot, no migration.**
    - **Flow in `services/assistant.ask`:**
      - when the scope is `case` and `recognise` returns facts, the service first checks the read guard in a short
        read;
      - if the guard holds, it **skips the model admission** (no readiness check, no slot, so no 503 `assistant_loading`
        or `assistant_busy`);
      - it runs transaction A unchanged: case visibility (404), the question rules, the in-flight rule, the hourly limit
        (a quick fact counts like any question; owner check 2), the stored question and `assistant.asked`;
      - then `assistant_facts.answer(session, case_id, facts)` builds the answer in a read-only session;
      - transaction B stores it.
    - **The stored answer:**
      - `mode` is the mode in force (`ollama` / `preview` / `sourcetrace`, so the existing CHECK holds);
      - `connector` is `facts`;
      - `outcome` is `answered`;
      - `citations` is one item `{source_kind: "case_details", label: "S1", cited: true, case_id, hearings: 0,
        listings: 0, compact: false}`;
      - `model_info` is `{"engine": "case_record", "facts": [...], "facts_version": 1}`;
      - `response` is null.
    - **The citation check:** `_map_citations` accepts a `case_details` citation for a quick-fact answer in every mode,
      only for the conversation's own case. Anything else raises `NotCitable`, as now.
    - **Audit:**
      - `assistant.asked` gains `quick_fact: [...]`, the fact names;
      - `assistant.answered` carries `connector: "facts"`, `facts`, the outcome, the answer digest and an empty court
        citation list. It holds no text, as now.
    - **History:** a quick-fact turn is not sent to the model, because `_history` reads only the connector's own answers
      (`connector = 'ollama'`).
    - **No suggestion:** `suggest_internal` is not computed for a quick fact.
    - **Visibility is the asker's own:**
      - the case must be visible (transaction A);
      - the read guard is required;
      - every value is what the asker's case page shows;
      - reading the answer later re-reads Case Details under the reader's sight (`_details_out`, unchanged);
      - the conversation stays private to the asker.
    - **No new table or column.** `connector` is free text (varchar 40). The `schema.md` paragraph names the new value
      (Data).
    - Alternative rejected: a new `mode` value `facts`. It needs a migration of the CHECK, and the mode records the
      assistant's setting, not who wrote one answer.

15. **How a quick-fact answer looks.**
    - `MessageOut.engine` is `{kind: "case_record", model: null}` (`AssistantEngineOut.kind` and
      `AssistantEngineBriefOut.kind` widen to `"ollama" | "case_record"`).
    - The answer card shows the badge **"From the Case Record"**, in place of "Local Model" and its line. The line under
      the answer is "Taken from the court record held for this case, as shown on the case page." `answerBy.case_record`
      is "Assistant (Case Record)".
    - The `[S1]` marker opens the Case Details source (decision 16).
    - Copy to note works as for any case-scope answer.
    - The portal never decides that an answer is a quick fact. It reads `engine.kind`.

**Item 4: sources hidden, opened from the reference**

16. **Sources are no longer listed under an answer or in the side panel. Each `[S#]` marker is a button that opens
    that one source in a dialog.**
    - **Removed:** the inline source list under each answer (`inlineSources`), the 1280 px "Sources Used" side panel
      (`SidePanel`), and the "Sources of answer n" chooser. The Assistant page becomes the conversation list and the
      thread; the case tab becomes the thread at full width.
    - **The marker:**
      - In an answer with labelled citations (ollama answers and quick facts), every `[Sn]` whose label is among the
        answer's citations is a real `<button type="button">`, reachable with Tab. A marker without a matching citation
        stays plain text, as today.
      - It shows "S1" as a small pill.
      - Its accessible name is "Source S1: <what>", where <what> is `sourceWords` with "(Internal)" for internal kinds.
        For example: "Source S1: Order of 18 Feb 2026, No. 7, page 2", "Source S1: Case Details", or "Source S3: Note 4,
        Hearing Note (Internal)". A source that is no longer available reads "Source S2: No Longer Available".
    - **The dialog** is the kit's `Dialog` (the Action dialog template: 560 px, full screen on phones). The kit already
      traps focus, closes on Escape, locks the page scroll and **returns the focus to the marker** on close.
      - Title: "Source S1". Subtitle: the case number when the source is of another case, or for Case Details.
      - Body, top to bottom:
        - the kind line ("Court Order", "Court Filing", "Case Details", "Note", "File Movement", "Department
          Document", "Note Attachment") with the "Internal" badge for internal kinds;
        - the title (`sourceWords`);
        - the excerpt with its highlights, for court kinds;
        - "Text Given to the Model", collapsed, for ollama answers. For Case Details it is the re-read facts, which for a
          quick fact are the facts it used;
        - "This source is no longer available." when it is unavailable.
      - Footer: Close, and the existing open link where one exists today (`sourceLink`). The link reads "Open the
        Order", "Open the Filing", "Open Case Details", "Open the Document" or "Open the Court Record" (the court-record
        view), and keeps today's new-tab rule.
      - The dialog renders only what the API returned for the message. The server's re-checks (`messages_out`) are
        unchanged, so an internal source the reader can no longer see still hides the answer and names nothing.
    - **"Sources (n)" stays, collapsed** (recommended; owner check 1).
      - Each answer with citations has a small secondary button "Sources (n)" in its footer, beside Copy to Note.
      - It opens a `Dialog` titled "Sources of This Answer" with today's grouped list: Court Record, Internal Records,
        and "Other Sources Given (Not Cited)" collapsed, with each source's open link.
      - It lets an officer check an answer in full, and it is the only way to reach the sources of an answer whose
        text has no markers.
    - **Answers without markers** (preview, whose passages are the answer, and SourceTrace until its contract is known)
      keep their source list under the answer, as on phones today. Their text has nothing to click, and hiding the
      preview's passages would leave an empty card. Owner check 7.
    - **No server change.** The citation checks, what is stored and `MessageOut` are unchanged, apart from
      `engine.kind` (decision 15).
    - Alternatives rejected:
      - a hover popover: it cannot be reached on a phone, and it is fragile with a keyboard;
      - the side panel kept and the inline list removed: the owner asked for the sources to be hidden until clicked.

17. **Copy to Note keeps its references in step with the markers** (row 188 review advisory 1).
    - `lib/assistant.ts` `noteText` keeps the answer's text with its markers unchanged. The reference list under "From
      the court records:" then names each **cited** source by its **own label**: "[S2] Order of 18 Feb 2026, No. 7, page
      2 (WP(C)/2615/2026): "…excerpt…"". So every marker in the note has a matching line, and no line lacks one.
    - A cited source that is no longer available gets "[S3] No longer available", so the marker still resolves.
    - Answers without labels (preview) keep the numbers 1..n in citation order, as today.
    - Uncited sources are not listed.

**Common**

18. **Documents updated in this item.** The developer does these; the scribe writes the log entry.
    - `docs/schema/schema.md`: the `assistant_messages` paragraph (Data).
    - `.env.example`: `ASSISTANT_OLLAMA_HISTORY_ANSWERS=none`, with its line.
    - `docs/operations.md`, the Ollama section: `aslms assistant repeat-check`, and what `history_answers` means.
    - `docs/ASLMS_Software_Documentation.docx`, regenerated through `docs/software-documentation/build.js`:
      - the Case Assistant section: quick facts, Enter to send, and sources opened from the reference;
      - 13.2 Variations, one row. Plan: "Case Assistant answers by the AI". As built: "Six quick facts on a case (next
        hearing, parties, advocates, status, last order date, bench) are answered from the court record held for the
        case, without the AI, with the same reference". Reason: "owner, 28 Oct 2026: crisp answers to specific
        questions".
    - `docs/claude_ASLMS_design_decisions.md`: a dated entry, "2026-10-28 — Owner: Case Assistant polish (row 198)".
    - CLAUDE.md is unchanged. No rule changes: quick facts use no AI, and nothing new reaches the model except decision
      6's court-derived next date and coram.

## Data
**No migration. No new table, column, index, `ref_*` code set or function.**

Replacement text for the `assistant_messages` paragraph in `docs/schema/schema.md`. Only the named parts change.

- **connector:** "connector (varchar 40 NULL; the implementation's name: `preview`, `ollama`, `facts` — a quick fact
  answered from the case's court record without a model, design `assistant-polish` — or SourceTrace's)".
- **citations:** add after the source-kind sentence: "a `facts` answer has exactly one citation, `case_details` of the
  conversation's own case, label `S1`".
- **model_info:**
  - add "`facts`: `{"engine": "case_record", "facts": [names], "facts_version": 1}`";
  - in the ollama shape, add `history_answers` (`none` / `short` / `full`) and `overlap_prev` (0–1 or null; the word
    4-gram containment of the answer in the previous answered turn);
  - `prompt_version` 2 from row 198.
- **closing sentence:** add "A `facts` answer draws on no model and no internal record; its mode is the assistant's
  mode at the time."

New setting (`core/config.py`): `assistant_ollama_history_answers: Literal["none", "short", "full"] = "none"`.
`ASSISTANT_OLLAMA_HISTORY_TURNS` (2) now counts earlier questions, and earlier answers too when the new setting is not
`none`.

## Services
- **`services/assistant_facts.py`** (new; imports no connector and no write service). Its functions:
  - `FACTS` (the six names) and `FACTS_VERSION = 1`;
  - `normalise(question) -> str` and `recognise(question) -> tuple[str, ...] | None`, pure (decision 11);
  - `next_hearing(session, case, *, today) -> NextHearing`, the assistant's one next-hearing reader (decision 13).
    `NextHearing` holds the court date and purpose, the order date and its source row (`source`, `order_date`,
    `created_at`), the disposal date, and the line or lines in words;
  - `facts_of(session, case) -> dict`: the values of decision 12, read from `cases`, current `case_parties` /
    `case_advocates` counts and names, the latest `orders` row and the latest `case_hearings.bench_text`;
  - `answer(session, case_id, facts, *, today) -> Answer`: the text (decision 12), the one `case_details` citation, and
    `info`. It raises nothing for missing values; they are worded.
- **`services/assistant.py`:**
  - `ask`: recognises quick facts for scope `case`, checks the read guard, skips `_admit`, runs `_prepare` (which adds
    `quick_fact` to the `assistant.asked` audit), calls `assistant_facts.answer` in a read-only session, and stores it
    through `_record` with a connector stand-in named `facts` (decision 14);
  - `_map_citations` accepts the quick fact's `case_details` citation;
  - `_history(…, outcomes=…)`;
  - `_ollama_audit` adds `overlap_prev`;
  - `messages_out` maps `engine` `{kind: "case_record"}` for `connector == "facts"`.
- **`services/assistant_ollama.py`:**
  - `PROMPT_VERSION = 2` and the new rules 7 and 8 (decision 3);
  - `build_messages` builds the earlier-questions block, plus `short` or `full` answers by setting (decision 2);
  - `overlap(earlier, later)`, pure, and `model_info.overlap_prev` / `history_answers` (decision 8);
  - `details_text` adds the coram and the next date from orders (decision 6).
- **`services/assistant_sources.case_details`** adds `coram` and `order_next_date`, read through
  `assistant_facts.next_hearing`. A manual date is never put into `order_next_date`.
- **`cli/assistant.py`:** `repeat-check` (decision 9). It is refused in prod and prints numbers only in mode A.
- **The portal:**
  - `components/assistant/Assistant.tsx`: the composer keys and hint (decision 1); marker buttons, the source dialog,
    "Sources (n)", the side panel and inline list removed for answers with markers (decision 16); the quick-fact badge
    (decision 15);
  - `lib/assistant.ts`: `noteText` (decision 17) and `markerName(c)`;
  - `assistant.module.css`: the grid without the side column, and the marker pill;
  - `lib/messages.ts`: the new words in Title Case where they are labels: "Sources (n)", "Sources of This Answer",
    "Source S1", "From the Case Record", "Open the Order", "Open Case Details". "Press Enter to send, Shift+Enter for a
    new line." is a sentence hint.
- No new audit action. No event, alert or job.

## API
No new endpoint and no new function. Existing routes and their guards:

| Method and path | Function | Change |
|---|---|---|
| `POST /assistant/ask` | `assistant.use` | Request unchanged. A quick-fact question is answered without the model (no 503 `assistant_loading` or `assistant_busy` for it); the response's `answer.engine` may be `{kind: "case_record", model: null}`. Visibility: case visibility (404) and, for a quick fact, the case page's read guard (otherwise the ordinary path). |
| `GET /assistant/conversations/{id}` | `assistant.use` | `MessageOut.engine.kind` may be `case_record`. Re-checks unchanged. |
| `GET /assistant/conversations` | `assistant.use` | Unchanged. |
| `GET /assistant/status` | `assistant.use` | Unchanged. |

The OpenAPI types are regenerated (`frontend/src/lib/api/schema.d.ts`).

## Jobs
None.

## Tests
**Backend, unit** (`tests/unit/test_assistant_facts.py`, new; `tests/unit/test_assistant_ollama.py`):
- `test_recognise_owner_questions`: "when is the next date", "who are the parties", "when is the next hearing date as
  per the latest court order?", "Who's the judge?" and "parties and advocates" are recognised as the right facts.
- `test_recognise_each_frame`: a table of positives for every frame of the six facts, with fillers and punctuation.
- `test_recognise_refuses_partial_and_content_questions`: "What did the last order direct?", "so me as the head of the
  department, what do i need to do?", "summarize the whole case.", "who are the parties and what did they argue",
  "next date and parties and status" (three facts) and an Assamese question all give None.
- `test_next_hearing_wording_before_row_199`: one case per row of the decision 13 table (disposed, same date, court
  only in the future, order date with the court date passed, both in the future and different, manual, only a court
  date passed, nothing), with a fixed `today`, including "(today)" and "(tomorrow)".
- `test_fact_wordings`: parties from the summaries, the fallback to the first party with "and N others", counts by role;
  advocates from the printed fields and the `case_advocates` fallback; status for pending, disposed and unknown; last
  order and none; bench from coram, from `bench_text`, and neither. Every line ends with `[S1]`.
- `test_prompt_v2_rules`: the system message has rules 1 to 6 unchanged and the new 7 and 8; `PROMPT_VERSION == 2`.
- `test_history_questions_only_by_default`: with two earlier turns, `build_messages` gives exactly
  `[system, user]`; the user message starts with the earlier-questions block, and neither earlier answer's text is
  present.
- `test_history_short_and_full`: `short` gives the first sentence of at most 160 characters with markers stripped;
  `full` gives today's chat turns.
- `test_overlap_measure`: identical texts give 1.0, unrelated texts 0.0, markers are ignored, and an answer under 4
  words gives 0. The stored-conversation pair of this note (synthetic text of the same shape) scores at least 0.85.
- `test_details_text_adds_coram_and_order_date`: the coram line, and "Next date from the order of …" only for order
  sources, never for a manual date.

**Backend, with FakeOllama** (`tests/db/test_assistant_ollama.py` and `tests/db/test_assistant_facts.py`, new):
- `test_copycat_model_repeats_only_with_full_history`: a FakeOllama callable that echoes the last assistant message it
  is sent (or a fixed line citing `[S1]` when there is none). With `full`, the second answer has `overlap_prev` ≥ 0.9;
  with `none`, the earlier answer is absent from `sent_text()` and `overlap_prev` < 0.5.
- `test_no_match_turns_not_fed_back`: an earlier `no_match` answer and its question are absent from the request.
- `test_overlap_prev_recorded_and_audited`: `model_info.overlap_prev` and `history_answers` are stored, and
  `assistant.answered` carries `overlap_prev` and no text.
- `test_quick_fact_answered_without_model`: FakeOllama with `loaded=False` (it would refuse with
  `assistant_loading`). A quick-fact question on the case tab is answered: no `/api/chat` and no `/api/generate`
  request; connector `facts`, mode `ollama`, outcome `answered`, one `case_details` citation `S1` of the case; engine
  `case_record`.
- `test_quick_fact_in_preview_and_sourcetrace_modes`: the same answer is stored with the mode in force.
- `test_quick_fact_audit`: `assistant.asked` has `quick_fact`, and `assistant.answered` has connector `facts`; neither
  holds the question or answer text.
- `test_quick_fact_needs_read_guard`: an assistant user without `cases.view_scope` or `cases.view_all` gets the
  ordinary connector path for the same question.
- `test_quick_fact_case_scope_only`: the same question in `my_cases` and `research` goes to the connector.
- `test_quick_fact_case_not_visible`: 404, as today, and nothing is stored.
- `test_quick_fact_counts_and_in_flight`: it counts against the hourly limit, and the in-flight rule applies.
- `test_quick_fact_equals_case_page`: for several cases (court date only, order date, manual, both, disposed), the
  dates in the quick fact equal `case_detail.overview`'s `status.next_hearing_date` and
  `next_date_from_orders.next_date` for the same asker. Row 199 updates this test to its shared reader.
- `test_quick_fact_not_in_history`: a later model question does not get the quick-fact turn.
- `test_quick_fact_rereads_under_reader`: the stored answer's Case Details source is re-read at read time
  (`_details_out`).
- `test_repeat_check_cli`: refused with `APP_ENV=prod` (exit 2); mode A prints scores and never the question or answer
  text (planted words are absent from the output) and refuses another user's conversation; mode B with FakeOllama
  asks the 8 questions in one new conversation, marks quick facts `case_record`, and exits 1 on a copycat model with
  `full` and 0 with `none`.
- The existing guards stay green: `test_assistant_modules_import_no_write_service` (now including
  `assistant_facts`), `test_only_listed_modules_import_the_ollama_client` (`assistant_facts` does not import it), and
  `test_contract_has_no_internal_field`.

**Portal, vitest** (`components/assistant/assistant.test.tsx`, `lib/assistant.test.ts`):
- `enter sends and shift+enter adds a line`: on both the case tab and the page, Enter calls the ask API once and
  Shift+Enter inserts a new line without a call.
- `ctrl or cmd+enter still sends`.
- `no send while composing`: `isComposing` true, or `keyCode` 229, makes no call.
- `enter does nothing while busy or too short`: no call and no new line.
- `the hint is shown and described`: the hint text is present and in the textarea's `aria-describedby`;
  `enterKeyHint` is "send".
- `markers are buttons with names`: each valid marker is a button named "Source S1: …"; a marker without a citation
  is plain text.
- `marker opens the source dialog`: the dialog is labelled "Source S1" and shows the kind, title, excerpt and open
  link. Escape closes it, and the focus returns to the same marker.
- `internal source in the dialog`: the "Internal" badge, and "(Internal)" in the marker's name.
- `no inline list or side panel for marked answers`: none in the DOM for an ollama answer; a preview answer keeps its
  list under the answer.
- `sources (n) opens the full list`: the grouped list, with uncited sources collapsed.
- `quick fact badge`: "From the Case Record", with no Local Model badge or line.
- `noteText labels match markers`: the copied text holds `[S2]` and `[S5]`, and the references are exactly `[S2]` and
  `[S5]` (none for uncited sources); an unavailable cited source gives "No longer available"; a preview answer keeps
  1..n.
- The wording guards in both suites (Title Case labels, no eOffice words, no "allot") pass with the new strings.

**uicheck** (`frontend/e2e/uicheck.spec.ts`, fixtures in the ollama state), at 375, 768 and 1280 px:
- `/cases/[ref]/assistant` with an answer holding markers (the inline list and side panel gone);
- the same with the source dialog open, reached by clicking "Source S1";
- the same with "Sources (n)" open;
- `/assistant` with a quick-fact answer;
- the existing rules (`gutter`, `doubled-heading`, one primary) hold.

## Verification
1. **Suites:** `ruff check` clean; `pytest -q` green; `npm run test` (vitest) green; `npm run typecheck` and lint clean;
   the regenerated OpenAPI types committed.
2. **No migration:** `alembic heads` is unchanged by this row.
3. **The integrator's uicheck:** `docker compose --profile uicheck run --rm uicheck` passes, including the new states
   at 375, 768 and 1280 px.
4. **The CLI without a model** (dev database, any mode with the assistant on):
   `aslms assistant ask "when is the next date" --user <your e-mail> --case "WP(C)/2615/2026"` answers in one or two
   lines, ending `[S1]`, with connector `facts`. For this case today it says "Next date from the order of 15 Oct 2026:
   Thursday 05 Nov 2026 [S1]." and "The court's own record still shows 15 Oct 2026, which has passed [S1].", matching
   the case page's Overview card and header. "who are the parties" gives "DINAR AHMED AND 3 ORS versus THE STATE OF
   ASSAM AND 4 ORS [S1]." and the counts line.
5. **The owner's repeat check** (on the machine running Ollama; also part of row 195's live check):
   - The baseline, on the merged build, from what is already stored (no model call):
     `aslms assistant repeat-check --user <your e-mail> --conversation 01a180fa-efbf-719f-a2b7-b1eafd9465e6` prints a
     maximum of about 0.90 and FAIL. Those answers were written by the old prompt and history.
   - Then live, with the new build: `aslms assistant repeat-check --user <your e-mail> --case "WP(C)/2615/2026"` asks the 8
     questions (it uses 8 of your 30 questions this hour) and prints PASS: no model answer at 0.50 or more. Questions 4
     and 5 show `case_record`.
   - For comparison, the same run with `ASSISTANT_OLLAMA_HISTORY_ANSWERS=full` set for that run only shows the old
     behaviour.
6. **The owner's browser check** at http://localhost:3000, on a case's Assistant tab and on the Assistant page:
   - typing a question and pressing Enter sends it; Shift+Enter starts a new line; the hint is under the box;
   - an answer shows no source list; clicking `S1` in the text opens the source in a dialog, and the open link works;
     Escape returns to the same `S1`; "Sources (n)" opens the full list;
   - "when is the next date" and "who are the parties" give one- or two-line answers marked "From the Case Record",
     instantly, even right after the model was restarted;
   - asking two different follow-up questions gives two different answers;
   - Copy to Note fills a note whose `[S#]` markers match its reference lines;
   - on a phone width (375 px) the source dialog is full screen.

## Open questions
None of these blocks the design. Each has a stated default that the build follows; the owner confirms or changes them
at approval, as with row 188's owner checks.

1. **"Sources (n)" button.** The default keeps a small "Sources (n)" button on each answer, opening the full list in a
   dialog, beside the clickable references (decision 16). Remove it if you want the references to be the only way in.
2. **Quick facts and the hourly limit.** By default a quick fact counts as one of the 30 questions an hour, like any
   question (decision 14). They use no model, so they could be left uncounted.
3. **Next dates entered in ASLMS.** Until row 199, the quick-fact next date also states a date an officer entered on
   the case page ("entered in ASLMS on …"), because the case page shows it to the same person. It is never given to
   the model (decisions 6 and 13).
4. **The model's Case Details.** The default adds two court-derived lines to what the model reads: the coram, and the
   next date read from the latest order. Neither is an officer's entry (decision 6).
5. **The repeat threshold.** The check passes when no model answer repeats 50 % or more of an earlier answer's
   4-word sequences. Your stored conversation scores 90 % on the copied answer (decision 9).
6. **Earlier answers.** By default the model sees your earlier questions but not its earlier answers. If a follow-up
   such as "and why?" is understood less well in the live check, `ASSISTANT_OLLAMA_HISTORY_ANSWERS=short` adds each
   earlier answer's first sentence (decision 2).
7. **Preview answers.** Preview answers (development only) keep their passages under the answer, because their text
   has no references to click (decision 16).
8. **Quick facts are not written by the AI** (deviation from plan §5.9). Six facts are stated from the court record
   with a reference, without the AI (decision 10).
9. **Enter on phones.** Enter sends on phones too, and the phone keyboard shows a Send key; Shift+Enter is not
   available on most phone keyboards, so a new line there means sending and asking again (decision 1).

## Deviations
(Filled by the developer when the build differs from this note.)
