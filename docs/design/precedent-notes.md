# Design: Precedent notes (case research, step 4)

```
slug: precedent-notes
status: blocked
author: architect
date: 2026-11-25
approved_by: (awaiting the owner's answers to the open questions, then approval)
```

## Context
Backlog row 253 (owner, 12 Nov 2026). Decisions log entry "Case research plan (owner, 12 Nov 2026)". It is the last of
the four research rows: 250 `order-sections` (live since 17 Nov 2026), 251 `research-index` (live since 24 Nov 2026),
275 `research-index-portal` (its round 2, live since 25 Nov 2026), 252 `similar-and-summaries` (being designed at the
same time, built first) and this row. In the build order of 23 Nov 2026 it comes after rows 274 and 252.

**What the owner asked for (row 253).**
- A Precedent Note action in the sidebar Assistant's All Court Orders tab.
- The officer states an issue (for example "regularisation of contractual teachers").
- ASLMS finds the relevant judgments and substantive orders by the hybrid search of row 251 and groups them by year
  and outcome.
- The local model writes a chronological note (holding, reasoning in brief, directions to the State). Every point is
  cited to case, order, date and page.
- The note is saved privately for the officer, and can be copied into a case note through the existing Copy to Note.
- Court information only. A cap on cases per note and a timeout, both settings.
- Every point passes the sentence checks of row 251, and records the orders and PDF fingerprints used.
- **Documentation:** chapter 6 and Annexure E gain how a precedent note is put together (search, grouping by year and
  outcome, the checks), with one worked note.
- **Rules kept:** local only (Ollama, never inside the backend; `no_local_model` stays fatal); court information
  only (orders, permitted court filings, NAPIX case details; never notes, file remarks, internal documents or
  drafts; visibility as `services/assistant_sources.py`); every AI text labelled, cited and checked on the server;
  derived tables re-buildable; AI outputs versioned and never deleted; court work keeps its priority.

**The allowance.** The owner's rule of 27 Oct 2026 (the local model for Case Assistant questions only) was extended
on 12 Nov 2026 to embeddings, case summaries **and precedent notes**: local only, court information only (decisions
log, "Case research plan", "Allowance extended").

**Plan.** The plan holds all research in SourceTrace (§3.2, §5.9: "All case research is carried out through
SourceTrace"). Writing precedent notes locally is a **deviation** from the plan. The owner approved it in direction on
12 Nov 2026 ("local first, then SourceTrace"), and it is flagged again in decision 1.

**What is in place (read in the code, 25 Nov 2026).**
- **Hybrid search** (`services/research_search.py`): `ranked_words` (full text over `research_chunks.search_vector`,
  `websearch_to_tsquery`), `ranked_meaning` (pgvector, HNSW or an exact scan up to `RESEARCH_EXACT_MAX`), `fuse`
  (RRF, k = 60), `holders` (the current readings and orders holding a chunk), the weights (procedural × 0.5,
  judgment or final × 1.2), shared bodies kept once with `same_words_in`, `small_to_big`, `full_context_line`, the
  `Filters` of decision 20 (`forms`, `substantive_only`, `outcomes`, `against_state`, `cites`, `act`, `from`, `to`)
  and `embed_question` (the query vector, else words only). `passages(...)` returns at most
  `ASSISTANT_OLLAMA_SOURCES` passages for one question; it is built for an Assistant answer, not for a list of
  orders.
- **Answer checks** (`services/answer_checks.py`, `answer_check_rules.py`): `check(answer, sources, *,
  rule_outcomes)` is pure (no database, no network) and returns `Checked(text, removed, withheld, quotes, counts)`.
  It removes a sentence whose quotes, dates, numbers, case numbers, names or outcomes are not in the text it cites,
  removes an uncited factual sentence, and withholds the whole text when the first sentence fails, when more than
  half fail or when nothing cited remains (row 251 decisions 23 to 29).
- **Order readings** (`order_sections`, row 250): per current reading `form` (judgment, final, interim),
  `procedural`, `outcome` (rule-read), the parts (`opening`, `facts`, `petitioner_submissions`,
  `respondent_submissions`, `issues`, `reasoning`, `conclusion`, or one `body`), the paragraphs with page and
  offsets, and the facts (`outcome`, `directions` with addressee, period and due date, `acts`, `judgments`).
  `order_sections.text_matches` refuses a reading whose stored text has changed.
- **The local model** (`services/assistant_ollama.py`, `OllamaConnector`): `ASSISTANT_OLLAMA_MODEL=qwen3.5:4b`,
  `num_ctx` 16,384, `num_predict` 800, `think: false`, `temperature` 0, a model share of 30 s
  (`ASSISTANT_OLLAMA_TIMEOUT_SECONDS`), one slot per api process (`ASSISTANT_OLLAMA_SLOTS` = 1, an in-process
  `threading.BoundedSemaphore`), a slot wait of 20 s. `OllamaClient.chat(body, timeout)` takes the request body
  as given, so a `format` field can be passed without a client change.
- **The connector interface** (`integration/sourcetrace/connector.py`): `AssistantConnector.ask(AskRequest) ->
  Answer`; the Ollama connector and the test fake implement it. Only `assistant_ollama.py`, `service_checks.py`,
  `cli/assistant.py`, `research_embed.py`, `research_search.py` and `cli/research.py` may import the Ollama client
  (`tests/unit/test_assistant_ollama.py`).
- **The court-record view of a cited order** (`assistant.court_order_view`, `court_order_file`, audited as
  `assistant.court_order_opened`) and the **passage view** (`assistant.passage_for`) are tied to an answer
  (`message_id`) of the caller's own conversation.
- **Copy to Note** (assistant decision 13; `frontend/src/lib/assistant.ts`, `NoteDialog` with `initialBody`): offered
  on a case-tab answer when the case's workflow block allows a note (`workflow.note_mode`); the person edits and saves
  an ordinary note (source `user`), audited as `note.added`. Nothing flows from notes to the Assistant. A note body is
  at most 20,000 characters (`notes.DEFAULT_NOTE_MAX`).
- **Visibility.** Every assistant user may search, cite and open the court orders of every case (assistant decision
  3, owner 23 Oct 2026). Conversations are readable only by their owner.

**What the dev data says** (read-only, 25 Nov 2026, inside `BEGIN READ ONLY`, through `docker compose exec -T postgres
psql`):
- **Current readings, substantive only:** 3,975 judgments (3,578 with a rule-read outcome; 3,026 distinct bodies),
  26,147 final orders (19,709 with an outcome; 23,584 distinct bodies), 82,799 interim orders.
- **Outcomes read by rule** (judgments / final orders): allowed 402 / 1,621; partly allowed 188 / 196; dismissed
  1,287 / 4,246; disposed of 1,575 / 10,334; withdrawn 10 / 591; closed 116 / 2,761; none read 398 / 6,438.
- **Judgment part sizes** (characters, median / p90): conclusion 598 / 5,026; reasoning 5,231 / 21,841; facts 4,288 /
  19,441; petitioner submissions 3,860 / 17,123; respondent submissions 4,409 / 23,626; one-part `body` 9,682 /
  31,655. Final orders: conclusion 245 / 1,122; reasoning 1,016 / 5,025; body 727 / 3,398.
- **Directions read by rule:** 5,743 of the 30,141 substantive judgments and final orders carry at least one; the
  commonest addressees are "the respondent authorities", "the respondents", "State", "Department" and "the State
  Government".
- **Common judgments:** 312 judgment bodies and 1,290 final-order bodies are held by more than one order (at most 83
  orders share one judgment).
- **Years:** judgments by order year: 2025 2,622; 2026 1,276; 2015 to 2024 together 78 (the load runs from
  1 Jan 2025). Year groups will mostly be 2025 and 2026 until older orders are collected.
- **An example issue.** The word query `(regularisation | regularization) & (contractual | contract)` matches the
  chunks of 242 substantive judgments and final orders (165 judgments, 77 final orders, 2020 to 2026, every outcome
  present), in 25 ms. `plainto_tsquery('regularisation contractual teacher')` matches 8. So a common issue finds far
  more orders than a note can carry: the cap matters, and the meaning list carries the search (row 251's model test
  found the same).
- **The chat model's speed on the owner's machine** (22 local answers, 28 Oct to 13 Nov 2026, from
  `assistant_messages.model_info`): writing 64 to 77 tokens a second (median about 68), reading the prompt about
  2,000 to 3,600 tokens a second (median about 2,850), prompts of 1,000 to 4,500 tokens, answers in 1.3 to 7.4 s when
  the model is loaded and 8 to 17 s when it first loads. A hybrid search took 2.6 s (decisions log, 24 Nov 2026).

**Not covered** (stated so nobody widens it):
- a model-written passage across several orders (open question 3);
- an alert or e-mail when a note is ready (the portal shows the state; a notice would be a new alert kind);
- sharing a note with another officer other than by copying it into a case note;
- editing a note, or deleting a note or a version;
- court filings, Acts, rules and policies in a note (the All Court Orders scope holds court orders only);
- notes in the preview mode (no model) or the sourcetrace mode (row 36's design decides);
- an entry point on the case page;
- OCR; any NAPIX call: this row reads stored data only;
- the portal screens, which are round 2 (decision 4).

## Decisions

### A. Scope and boundary

1. **Precedent notes are written locally: a deviation the owner approved in direction.**
   - The plan puts all research in SourceTrace. Writing notes inside ASLMS with the local model follows the owner's
     case research plan of 12 Nov 2026 ("local first, then SourceTrace") and the allowance extended to precedent
     notes the same day.
   - When SourceTrace's API arrives (row 36), its design decides whether notes move there. The writing call is a
     capability of the connector interface (decision 12), so a SourceTrace connector can take it over.
   - This amends `docs/design/assistant-ollama.md`, "Not covered" ("any other use of the model: … summaries …").
     The scribe adds an "Amended by `precedent-notes`" line, beside the one row 252 adds for summaries.
   - *Alternative:* waiting for SourceTrace (rejected: row 36 is blocked on its documentation).

2. **Court information only.**
   - The model is given, for each order, paragraphs of that order's current reading (`order_sections.body_text`) and
     a context line built from court-public case fields (case number, case type, category, judge, date, form, part,
     pages). Nothing else.
   - The precedent modules read only `order_sections`, `orders`, `documents` (hash and nature columns),
     `document_text` (the hash, and the page text of a cited passage), `cases`, `case_parties`, `case_acts`,
     `courts`, `research_chunks`, `research_embeddings` and their own three tables. A unit test scans their SQL and
     imports and refuses notes, custody, file movements, internal documents, drafts and `assistant_internal`, as row
     251's reader test does.
   - Court filings are not used: the All Court Orders scope holds court orders only (row 251 decision 3).
   - The officer's issue text is sent to the local model, as an Assistant question is. It is not written to the audit
     log or to any log line.

3. **Who may write a note, and what they see.**
   - Writing and reading notes needs `assistant.use` (open question 2 asks whether a separate function is wanted).
   - A note is the officer's own: every read, Write Again, passage and court-order route answers 404 for anyone else,
     the Super Administrator included, as conversations do today. The audit log shows that a note was written, with
     counts only (decision 26).
   - The orders a note cites are open to every assistant user (assistant decision 3), so a note never shows something
     its reader may not see. Orders of a case merged into another (`merged_into_case_id`) are left out, as the
     court-record view does.

4. **Two rounds.** Round 1 is this row: the backend. Round 2 is a new row, `precedent-notes-portal`, added on
   approval, as rows 251/275 and 258/259 were split.
   - **Round 1:** the migration, the search for a note, the writer and its checks, the runner, the API (decision 27),
     the status fields, the data-health block, the CLI, the tests.
   - **Round 2 (portal):**
     - the Write a Precedent Note action in the All Court Orders tab, with the issue, the Search Filters panel of row
       275 and Cases At Most;
     - the Precedent Notes list in that tab beside the conversations, with each note's state;
     - the note view: progress while writing ("Reading 4 of 12 Orders"), the groups by year and outcome, the
       entries, the citations with the passage view and the court-record view, the "Text Has Changed" note, the
       removed-sentence notes, Write Again and the version history;
     - Copy to Note with a case choice (decision 24);
     - uicheck at 375, 768, 1024 and 1280 px.
   - *Alternative:* one row (rejected: a migration, a background runner and a new model pipeline to review, plus a
     portal of four states).

### B. Finding the orders

5. **Which orders: judgments and final orders, substantive only (open question 1).**
   - The row says "judgments and substantive orders". The recommendation reads it as substantive judgments and
     substantive final orders by default, with substantive interim orders added only when the officer ticks Interim
     in the filters' order forms.
   - Why: a note is built from holding, reasoning and directions, which a disposing order has and an interim order
     (97% of orders, median body 787 characters when substantive) mostly has not; 82,799 substantive interim orders
     would otherwise fill most slots of a 12-case note.
   - `substantive_only` is always true for a note: the officer cannot switch it off.

6. **The search: row 251's hybrid search, ranked by order and then by case.**
   - **The issue's vector** by `research_search.embed_question` (the profile's query prefix), within
     `RESEARCH_QUERY_EMBED_SECONDS`. On failure, words only (`retrieval.kind = words_only` with the reason), as a
     question.
   - **Two lists** over the current chunks of the research scope with the note's filters: words (`ranked_words`) and
     meaning (`ranked_meaning`, HNSW, or an exact scan when the filtered set has at most `RESEARCH_EXACT_MAX`
     chunks), each up to `RESEARCH_CANDIDATES` (100). Case sheets take part; a sheet hit counts for its case only
     through that case's qualifying orders.
   - **Fusion and weights** as row 251 (RRF k = 60; judgment or final × 1.2). Shared bodies give one item (the newest
     order holding the body), with `same_words_in` and the other orders' case numbers kept for the entry (decision
     19).
   - **One order per case:** the case's best-ranked qualifying order. The cases are taken in fused order up to the
     note's cap (decision 7).
   - **Orders not yet indexed** (minutes old, or text not read yet) are not searched: a note uses indexed orders
     only, and says how many orders of the scope wait for the index (`unindexed`), from the research status.
   - **Stale texts:** an order whose current reading no longer matches its stored text (`text_matches`) is dropped
     and counted (`stale_dropped`), as row 251 does.
   - **New function** `research_search.ranked_orders(session, budget, issue, *, query, filters, limit_cases,
     candidates, exact_max, ef_search) -> OrderRanking`, built from the existing `ranked_words`, `ranked_meaning`,
     `fuse`, `holders` and `weight`. It returns, per chosen order: the holder (order, reading, case), score, rank,
     `match` (`words`, `meaning`, `both`), the matched chunk ids, `same_words_in` and the other holders. It also
     returns every candidate considered (up to 100) for the version's record. `passages(...)` is unchanged.
   - It runs in one read-only transaction with `ASSISTANT_PREVIEW_SQL_MS` per statement, as a question's search.
   - *Alternative:* calling `passages(...)` with a large limit (rejected: it reads small-to-big text for every
     passage and caps at the Assistant's source count; a note needs a ranked list of orders, then its own reading of
     each).

7. **The cap and the time limit are settings.**
   - `PRECEDENT_NOTE_CASES` (default 12, bounds 3 to 25): the most cases a note may carry. The officer may ask for
     fewer (`cases`, 1 to the setting).
   - `PRECEDENT_NOTE_SECONDS` (default 300, bounds 60 to 1,800): the note's own working time (search and model calls).
     Waiting for people's questions (decision 15) does not count; a wall-clock ceiling of 3 × the setting does.
   - **Why 12 and 300 s, from the measurements:** an entry's prompt is at most about 4,000 tokens (decision 9),
     read in about 1.5 s; an entry of 250 to 400 tokens is written in 4 to 6 s at 68 tokens a second; so about 6 to
     8 s per order, about 1.5 minutes for 12 orders plus 3 s of search, and about 2 minutes 10 s in the worst case
     (every entry at the 600-token limit). 300 s leaves room for loading and for waits. On a CPU-only machine a note
     will usually stop at the limit with fewer entries (decision 17).

### C. Writing the note

8. **One model call per order, never one call for the whole note.**
   - Each chosen order gets its own call, given only that order's paragraphs. The model writes that order's entry.
     ASLMS puts the entries together (decision 18).
   - **Why:**
     - a holding can never be attributed to the wrong case, because the model sees one order at a time;
     - 12 orders × 12,000 characters (about 34,000 tokens) would not fit `num_ctx` 16,384, and a 4-billion-parameter
       model reads a long context less reliably;
     - a person's question waits for one short call at most, not for the whole note (decision 15);
     - a note stopped by the time limit or a restart keeps the entries already written.
   - **No call ever changes `num_ctx`,** so the chat model is never reloaded for a note: the options are the
     Assistant's (`think: false`, `temperature` 0, `num_ctx` = `ASSISTANT_OLLAMA_NUM_CTX`, `keep_alive` as set), with
     only `num_predict` = `PRECEDENT_ENTRY_TOKENS` (600).
   - *Alternative:* one call over all orders (rejected, above); a map step then a model-written merge (rejected for
     this row: open question 3).

9. **What the model is given for one order: numbered sources from that order, best parts first.**
   - Each source is a run of whole paragraphs of one part of the current reading, never repeated in two sources.
     Its header is row 251's full context line (`research_search.full_context_line`) plus the part and paragraphs,
     for example `Judgment dated 12.03.2025 · WP(C)/7013/2024 · Service: Regularisation · Hon'ble Mr Justice A ·
     Conclusion · paragraphs 31 to 33 · pages 14 to 15`.
   - **The order of filling,** until `PRECEDENT_ORDER_CHARS` (default 12,000, bounds 4,000 to 30,000):
     1. **Outcome:** the `conclusion` part (its last paragraphs up to 5,000 characters when longer); for a one-part
        `body` reading, its last paragraphs up to 3,000 characters plus the paragraph holding the rule-read outcome;
     2. **Directions:** the paragraphs holding row 250's `facts.directions`, not already given (up to 3,000);
     3. **Matched passages:** the order's matched chunks from the search, read small-to-big inside their part
        (`small_to_big`, at most 2 passages of `ASSISTANT_OLLAMA_SOURCE_CHARS`);
     4. **Reasoning:** the last paragraphs of `reasoning` not already given;
     5. **Background:** the first paragraphs of `facts`, at most 2,000.
   - **Sources are numbered S1 to Sn** within the call, as Assistant sources are. There is no Case Details source:
     the case's court facts are in each header, so every cited point is cited to the order itself.
   - **The text given** comes from the current reading's `body_text`, the cleaned text the chunks were cut from.
     Each source stores its part, paragraphs, pages, `src` and `txt` offsets and the SHA-256 of the exact text given
     (`given_sha256`), not the text: the reading is never deleted, so the text can be rebuilt and proved equal.
   - **The prompt fits:** at the code's conservative 3 characters a token, 12,000 characters are 4,000 tokens; with
     the instructions (about 700) and the reply (600) a call needs about 5,300 of the 16,384 tokens. Preflight
     refuses a setting where `PRECEDENT_ORDER_CHARS / 3 + 1,000 + PRECEDENT_ENTRY_TOKENS` passes
     `ASSISTANT_OLLAMA_NUM_CTX`.
   - The sizes above cover a judgment's conclusion at p90 (5,026) and a final order's whole reasoning at p90 (5,025)
     with room for the matched passages.

10. **The entry the model writes: four fields in JSON, by Ollama's structured output.**
    - The request carries `format`, a JSON schema: `{relevant: boolean, holding: string, reasoning: string,
      directions: string}`, all required.
    - **The precedent prompt, version 1** (`PRECEDENT_PROMPT_VERSION = 1`), the rules in plain words:
      1. Use only the numbered sources; they all come from one court order.
      2. Set `relevant` to false when the order does not decide or discuss the issue, and leave the other fields
         empty.
      3. `holding`: at most 3 sentences on what the court decided on the issue; the first sentence is the direct
         holding.
      4. `reasoning`: at most 4 sentences on why.
      5. `directions`: at most 3 sentences on what the court directed the State or its officers to do, with any time
         given; an empty string when there is none.
      6. End every sentence with the markers of the sources it uses, such as [S2].
      7. When you quote, copy the words exactly and put them in double quotes.
      8. No fact from outside the sources; no advice and no opinion.
    - The issue is given as "The officer's issue:" before the sources. It is the officer's own words and is never
      read as an instruction to change the rules (the system prompt says so).
    - **Sentences beyond the limits** (3, 4, 3) are dropped by ASLMS before the checks and counted (`over_limit`).
    - **A reply that is not valid JSON of the schema** is asked again once with the same input; a second failure
      makes the entry `failed` with `format`. Ollama 0.40.11's acceptance of `format` with `qwen3.5:4b` and `think:
      false` is checked in Verification 2. If the model ignores `format`, the parser still reads a JSON object from
      the reply text, and the retry rule stays.
    - *Alternative:* plain text with headings (rejected: headings are fragile to parse, and a heading missed would
      merge two fields).

11. **Every field passes row 251's checks; the holding decides the entry.**
    - For each field, in order: `check_citations` (markers out of range removed, assistant-ollama decision 8), then
      `answer_checks.check(field, sources, rule_outcomes)` with `sources` = {n: header + text given} and
      `rule_outcomes` = {n: the reading's rule-read outcome} for every source (all from the same order). The module
      is unchanged; `CHECKS_VERSION` is stored on the version.
    - **The holding is withheld** (first sentence removed, more than half removed, or nothing cited): the entry is
      `withheld`. It shows the order's facts read by rule (decision 19) and the line "No statement supported by the
      order was written. Open the order to read it." The order stays cited by its facts, never by AI text.
    - **Reasoning or directions withheld:** that field is left out, with "Left out by ASLMS: not supported by the
      order's text."
    - **Removed sentences** in a kept field get row 251's line at the end of that field ("[Removed by ASLMS: n
      sentences …]").
    - **`relevant` false:** the entry is `not_relevant`. It is listed under "Read and Left Out" with its order and
      the words "The order was read and found not to decide this issue (the model's reading)". The fields are not
      stored. This reading cannot be checked by rules; listing the order lets the officer open it.
    - **Directions with nothing written:** when `directions` is empty but row 250 read directions in the order, the
      entry says "The model wrote no directions; the directions read by rule are listed below."
    - The checks cannot catch a wrong reading of correctly quoted text, so the note stays labelled as AI text and
      every citation opens the order at its page (decision 21).

12. **The writing call goes through the connector interface.**
    - `integration/sourcetrace/connector.py` gains a second, optional protocol beside `AssistantConnector`:
      `CitedWriter.write_cited(WriteRequest) -> WriteAnswer`, where `WriteRequest` holds `request_id`, `task`
      (`precedent_entry`), the instruction text (the issue), the numbered sources (`n`, header, text), the JSON
      schema, the token limit and the timeout, and `WriteAnswer` holds the parsed fields or `None`, the raw reply,
      the engine facts (model, digest, `eval_count`, `prompt_eval_count`, milliseconds) and an error family.
    - `OllamaConnector` implements it in `services/assistant_ollama.py` (already allowed to import the client), with
      `PRECEDENT_SYSTEM_PROMPT` beside its other prompts. The test fake implements it. The preview connector does not,
      so notes are off in the preview mode.
    - `services/precedent_notes.py` never imports the Ollama client; it calls the connector. The import guard of
      `test_assistant_ollama.py` is unchanged.
    - **Shared with row 252.** Row 252 writes judgment and case summaries by the same pattern (the local chat model
      writing cited text checked sentence by sentence). **Row 252 provides a writing capability on the connector
      interface for its summaries; if it takes numbered sources and a JSON schema and returns fields, this row uses
      it with the task `precedent_entry`, adding only its prompt. If it does not, this row adds `CitedWriter` as
      above,** and row 252's capability stays as built.
    - *Alternative:* calling the Ollama client from the precedent service (rejected: CLAUDE.md, "All AI goes through
      the Case Assistant connector interface").

13. **A note is not built from row 252's judgment summaries.** Row 252 writes a general summary of each judgment and
    final order for the Orders tab. A precedent entry is written for the officer's issue (what the court decided on
    it, and what it directed the State to do), so it is written afresh from the order's text. Two different readings
    of one order may therefore exist, each labelled and cited. *Alternative:* reusing the summary (rejected: it is
    not about the issue, and a summary written before the issue was known cannot answer it).

### D. Running the work

14. **Notes are written in the background, one at a time, by a runner in the api process.**
    - `POST /assistant/precedent-notes` stores the note and its first version in state `queued` and answers 202 at
      once. The portal polls `GET /assistant/precedent-notes/{id}` while the note is open.
    - **The runner** (`services/precedent_runner.py`) is an asyncio task started in the api's lifespan when notes are
      on (decision 22). It claims the oldest `queued` version (`FOR UPDATE SKIP LOCKED`), sets it `searching`, then
      `writing`, writes one entry per order and finishes it (decision 17). Every state change, every entry and the
      heartbeat are committed in short transactions of their own; no transaction stays open across a model call, as
      the Assistant's transactions A and B.
    - **Why the api process:** the one slot that guards the chat model (`ASSISTANT_OLLAMA_SLOTS`) and the knowledge of
      which questions are waiting live there (decision 15). The scheduler runs one Celery task at a time
      (`--concurrency 1`), so a two-minute note there would hold up the 18:30 cause-list check and every other job.
    - **A restart** (deploy or crash) leaves a version `searching` or `writing` with an old `heartbeat_at`. At start and
      every 60 s the runner ends any such version whose heartbeat is older than `PRECEDENT_CALL_SECONDS` + 60 s:
      `written` with `cut_short` and `stop_reason = interrupted` when it holds a written entry, else `failed`
      (`interrupted`). It never resumes on its own; the officer uses Write Again.
    - **Shared with row 252.** If row 252 adds a shared runner for local-model writing with person-requested work
      ahead of background work, the precedent note is that runner's person-requested work and this row adds no runner
      of its own; the developer records it as a deviation. Otherwise this row's runner is built as above.
    - *Alternatives:* the scheduler (rejected, above); a new Compose service (rejected for now: one more service to
      run and monitor, and the person-first rule would rest on a Redis flag rather than on the slot itself).

15. **People's questions first, then notes, then background summaries.**
    - Before each entry call the runner asks the connector for a background slot
      (`OllamaConnector.admission_background()`): it is granted only when no question is waiting for the slot and the
      slot is free; otherwise the runner waits in 1 s steps and asks again. The connector counts questions waiting in
      `admission()`. The slot is released after every entry call.
    - So a question waits at most for one entry call: about 6 to 8 s on the owner's GPU, at most about 11 s at the
      600-token limit, inside the slot wait of 20 s. Verification 4 measures it.
    - While a note is writing, the runner sets the Redis key `aslms:research:person_writing` (60 s expiry, renewed).
      **Row 252's background summaries pause on it, as the embedding job pauses on the asking flag; if row 252 defines
      its own priority signal, this row sets that one instead.** The embedding job does not pause for a note (a
      different model, decision 22 of row 251); the issue's own embedding sets the asking flag for its few seconds,
      as a question does.
    - The court work is untouched: no `fetch_queue` row, no NAPIX call, no scheduler slot.

16. **Limits per officer and for the queue.**
    - One note `queued`, `searching` or `writing` per officer at a time: a second request answers 409
      `precedent_in_progress`.
    - `PRECEDENT_NOTES_PER_DAY` (default 10, bounds 1 to 100) versions requested per officer per IST date: beyond it
      429 `precedent_limit` with the time the count resets. Notes do not count against the hourly question limit.
    - `PRECEDENT_QUEUE_MAX` (default 5, bounds 1 to 50) versions waiting in all: beyond it 503 `precedent_busy`
      ("Many notes are being written; try again in a few minutes").
    - The queue position is shown while a version waits.

17. **How a version ends.**
    - `written`: at least one entry `written`.
    - `no_match`: nothing to write (no qualifying order found, or every entry `not_relevant`, `withheld` or
      `stale`). The note says "No precedent supported by the records was found for this issue." and lists what was
      read and why it was left out.
    - `failed`: stopped before any entry, with an error family: `model_unavailable` (the chat model not ready within
      120 s, one background load started as for a question), `search` (the search failed or timed out),
      `interrupted`, `internal`.
    - **`cut_short`** (with `written` or `no_match`) when the time limit (`time_limit`), the wall-clock ceiling
      (`wall_limit`), a restart (`interrupted`) or the model going away mid-note (`model_unavailable`) stopped it
      before every chosen order was read. The note says "Stopped after n of m orders: <reason>."
    - An entry call that fails on its own (timeout of `PRECEDENT_CALL_SECONDS`, 60 by default, or an error) makes that
      entry `failed` with its family and the runner goes on to the next order. Failures are stored on the entry, never
      lost.

### E. The note

18. **ASLMS puts the note together from the entries, by fixed rules; the model writes only the entries.**
    - The note is assembled when it is read (`precedent_render.render`, pure), from the version's stored entries, so
      a note stopped early is simply shorter. The entries are never changed after they are written.
    - **Heading:** "AI Precedent Note: check against the orders", the issue, the filters in words, "Written by the
      local model <model> on <date>", and a count line written by ASLMS, for example "12 orders read: 9 written up,
      2 found not to decide this issue, 1 withheld by the checks. Found by meaning and word search."
    - **Grouping, the owner's "by year and outcome":** year groups in ascending order of the order date's year;
      inside a year, outcome groups in the fixed order Allowed, Partly Allowed, Dismissed, Disposed Of, Withdrawn,
      Closed, Outcome Not Read (row 250's rule-read outcome, labelled "Read by Rule"); inside an outcome group, by
      order date then case number. So the note reads in time order.
    - **Label:** every entry and the heading carry the AI label; the copy text starts with it (decision 24).
    - The style of the label follows row 252's "AI Summary: check against the orders". **If row 252 fixes a shared
      label component or wording rule, this row uses it.**

19. **One entry.**
    - **Its heading, written by ASLMS from held data (never by the model):** case number, case type, Judgment or
      Final Order of <date>, the judge (`orders.order_judge_name`, else the case's coram), "Outcome: <label> (Read by
      Rule)", and "Against the State (Read by Rule)" when row 251's `against_state` rule says so (the order's
      outcome with the State among the current respondents or petitioners; no other reading of the State's result is
      made).
    - **A common judgment:** "The same order was passed in n other cases" with up to 10 of their case numbers.
    - **Holding, Reasoning in Brief, Directions to the State:** the checked fields, each sentence with its citation
      numbers.
    - **From the order, read by rule:** the outcome text and the directions of row 250's facts, each at most 300
      characters as printed, with its page. This model-free part is shown for every written or withheld entry.

20. **Citations: case, order, date and page, and the exact passage.**
    - Each `[Sn]` of an entry becomes a note-wide number `[k]` in reading order. Citation k names the order (case
      number, Judgment or Final Order, date), the page (the first page of the cited source's paragraphs) and, as row
      251 decision 13, the `src` span of those paragraphs, and any matched quotes (`quotes: [{src, page, exact}]`,
      found as `assistant._locate_quote` finds them).
    - Each entry records the chain: order, document, reading, `pdf_sha256`, `text_sha256`, `parser_version`, the
      matched chunk ids, `chunker_version` and the embedding `model_key` of the search (row 251 decision 13), and
      per source its paragraphs, pages, offsets and `given_sha256`.
    - **Text changed:** when a note is read, a citation whose order now has another text hash
      (`assistant.current_text_hashes`) is flagged `text_changed`; the note then says "Some orders have changed since
      this note was written" and offers Write Again. The note stays readable.

21. **Opening a cited order.**
    - **Passage view:** `GET /assistant/precedent-notes/{id}/versions/{n}/citations/{k}/passage` returns the stored
      text of the cited page with the passage and quotes highlighted, as row 251's passage endpoint.
    - **Court-record view and PDF:** the existing `GET /assistant/court-orders/{order_id}` and `/file` accept
      `precedent_version_id` in place of `message_id`. The check is the same (the version is the caller's own and an
      entry of it cites the order; the document is a court order; the case is not merged). Audited as today
      (`assistant.court_order_opened`) with `precedent_version_id` in `after`.
    - **Shared with row 252.** `assistant.passage_for` and `_cited_order` work on a citation stored on an answer.
      **Row 252 may generalise them to a citation stored elsewhere (its summaries); if it does, this row uses that; if
      not, this row factors the page-and-highlight part of `passage_for` into a helper that both call,** and adds the
      `precedent_version_id` path to `_cited_order`.

22. **When notes are on.** All of: `PRECEDENT_NOTES_ENABLED` true (default `false`; the owner switches it on after
    the live check, as `RESEARCH_INDEX_ENABLED`), `ASSISTANT_MODE=ollama`, `RESEARCH_INDEX_ENABLED` true, and the
    caller holds `assistant.use`.
    - Otherwise `GET /assistant/status` reports `precedent.state = off` and a request answers 503 `precedent_off`.
      Saved notes stay readable whatever the switches.
    - With the embedding model not ready, a note is still written from the words list (`words_only`), and says so.
    - In the preview and sourcetrace modes notes are off (no writer). Preflight warns when the switch is on in another
      mode.

23. **Versions: Write Again, never edit, never delete.**
    - A note keeps its issue, filters and cap. Write Again (`POST …/versions`) queues version n + 1 with the same
      issue and filters, the current settings, model and prompt. A different issue or filter is a new note.
    - Every version and every entry is kept. A note shows its latest finished version by default and lists the others
      (number, state, date).

24. **Copy to Note: the existing note dialog, with a choice of case.**
    - The note is not tied to a case, so Copy to Note (round 2) first asks for the case: a search over the cases the
      officer can open (`GET /cases?q=`, visibility on the server), then the case's workflow block (`GET
      /cases/{ref}`, `workflow.note_mode`). When the officer may not write a note on that case, the dialog says so.
      Then the existing `NoteDialog` opens with the copy text; the officer edits and saves an ordinary note, audited
      as `note.added`. No new note source and no link back from the note.
    - **The copy text is built by the server** (`copy_text` on the note's API) so that one rendering is tested: the AI
      label, the issue, the date and model, the groups and entries with `[k]` markers, then the references in words
      ("[3] WP(C)/7013/2024, Judgment of 12 Mar 2025, page 14"), as the Assistant's Copy to Note writes them.
    - **Length:** a note body is at most 20,000 characters. When `copy_text` is longer, the server also gives
      `copy_text_brief` (headings, holdings and directions, no reasoning), and the portal uses it and says so. A 12-
      entry note runs to about 15,000 to 21,000 characters at the sentence limits of decision 10.
    - Nothing flows from a case note to the Assistant or to a precedent note.

25. **Status everywhere.**
    - **`GET /assistant/status`** gains `precedent: {state: "off" | "ready" | "unavailable", cases_max, queue,
      mine: {in_progress, left_today}}`.
    - **The data-health block `precedent_notes`** (in `GET /admin/data-health`, counts only, read in isolated parts
      with a timeout as row 264 does): enabled, queued, writing, the last 7 days' versions by state, `cut_short` by
      reason, median duration and median entries, entries by state.
    - **`aslms precedent-notes status`** prints the same.

26. **Audit and logging.**
    - `precedent_note.requested` (entity `precedent_note`, the note's id; on the first version and on Write Again):
      `after` `{version, cases, filters, issue_chars}`. The issue text is not written, as `assistant.asked` writes no
      question text.
    - `precedent_note.written` (same entity, when a version ends in any state): `after` `{version, state, cut_short,
      stop_reason, error_family, orders_planned, entries: {written, withheld, not_relevant, failed, stale}, checks:
      {sentences, kept, removed by reason, over_limit}, retrieval: {kind, words, meaning, fused, stale_dropped},
      model, prompt_version, checks_version, duration_ms}`. Written in the runner's transaction with the requesting
      officer as actor and `via: "precedent_runner"`, as the Assistant writes `assistant.answered`.
    - Both actions join `domain/audit_actions.py`; the portal's `AUDIT_ACTIONS` registry gets their names in round 2.
    - **Log lines:** one INFO line per entry (version id, order id, state, milliseconds, tokens) and per version (state,
      counts). Never the issue, a source text or a field.

## Data

**Migration.** A new migration: **0044 if row 252 adds 0043**, otherwise the next free number. Migrations 0001 to
0042 are applied and untouched; no applied migration is edited. It does the following:
1. Creates the enum types `precedent_version_state` (`queued`, `searching`, `writing`, `written`, `no_match`,
   `failed`) and `precedent_entry_state` (`written`, `withheld`, `not_relevant`, `failed`, `stale`).
2. Creates `precedent_notes`, `precedent_note_versions` and `precedent_note_entries` (below), with their indexes,
   CHECKs, triggers (functions `aslms_precedent_note_touch` and `aslms_precedent_version_freeze`; the existing
   `aslms_forbid_change` and `set_updated_at`), grants and comments.
3. Downgrade: drops the three tables, the two functions and the two types. The runbook warns that a downgrade loses
   the officers' saved notes, so it is for a test database only.

No reference data: no new function (unless open question 2 is answered with one; then this migration also adds it to
`ref_permission` and the role defaults through `aslms/db/migration_audit.py`, and the seed gains it).

**`docs/DB_STANDARD.md`:** §0, the Transaction row gains `precedent_notes`, `precedent_note_versions`,
`precedent_note_entries` (no version change, as row 250 added its table).

**`docs/schema/schema.md`:** the Conventions' audit paragraph gains `precedent_note.requested` and
`precedent_note.written`; Group 6 (Case Assistant) gains three rows:

| `precedent_notes` (transaction) | id (uuid v7 PK), user_id (→ users RESTRICT, NOT NULL; the officer who asked, the only reader), issue (varchar 300 NOT NULL; the officer's words, whitespace collapsed), filters (jsonb NOT NULL default `{}`; row 251's filter shape `{forms, outcomes, against_state, cites, act, from, to}` as stored by `Filters.stored()`; `substantive_only` is implied and not stored), cases (smallint NOT NULL; the cap asked for), last_version (smallint NOT NULL default 1), last_activity_at (timestamptz NOT NULL default now()), created_at, updated_at | CHECKs `ck_precedent_notes_issue` (`char_length(issue) BETWEEN 3 AND 300`), `ck_precedent_notes_cases` (`cases BETWEEN 1 AND 50`; the setting's bound is enforced by the service), `ck_precedent_notes_version` (`last_version >= 1`). Index `ix_precedent_notes_user_activity` (user_id, last_activity_at DESC). Trigger `precedent_notes_touch` (function `aslms_precedent_note_touch`): only `last_version`, `last_activity_at` and `updated_at` may change, `last_version` only upward; DELETE refused; plus `set_updated_at`. Grants: ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT / UPDATE to `aslms_app` (no DELETE; not on the §6 cascade list). Comment `class=transaction`. No `ref_no` (private, never quoted, like `assistant_conversations`); `user_id` is the creator, so no `created_by`. Written only by `services/precedent_notes.py` (design `precedent-notes`). Never holds notes, remarks, internal documents or drafts. |
| `precedent_note_versions` (transaction) | id (uuid v7 PK), note_id (→ precedent_notes RESTRICT, NOT NULL), version (smallint NOT NULL), state (`precedent_version_state` NOT NULL default `queued`), cases (smallint NOT NULL; the cap used), mode (varchar 20 NOT NULL; `ollama`), model (varchar 160 NULL; Ollama's full name, set when writing starts), model_digest (varchar 80 NULL), prompt_version (smallint NULL), checks_version (smallint NULL), embed_model_key (varchar 180 NULL; the search's live key, NULL for words only), retrieval (jsonb NULL; `{kind: hybrid / words_only, reason?, words, meaning, fused, stale_dropped, unindexed}`, counts only), candidates (jsonb NULL; up to 100 `{order_id, case_id, rank, score, match, chosen}`, ids and numbers only), orders_planned (smallint NULL), orders_done (smallint NOT NULL default 0), cut_short (boolean NOT NULL default false), stop_reason (varchar 30 NULL; `time_limit`, `wall_limit`, `interrupted`, `model_unavailable`), error_family (varchar 40 NULL), checks (jsonb NULL; the version's summed counts), queued_at (timestamptz NOT NULL default now()), started_at, heartbeat_at, finished_at (timestamptz NULL), work_ms (integer NULL; the time counted against the limit), duration_ms (integer NULL), created_at, updated_at | Unique `uq_precedent_note_versions_note_version` (note_id, version). CHECKs `ck_precedent_note_versions_failed` (`(state = 'failed') = (error_family IS NOT NULL)`), `ck_precedent_note_versions_cut` (`cut_short = (stop_reason IS NOT NULL)` and `NOT cut_short OR state IN ('written', 'no_match')`), `ck_precedent_note_versions_finished` (`(state IN ('written', 'no_match', 'failed')) = (finished_at IS NOT NULL)`). Indexes: partial `ix_precedent_note_versions_queue` (queued_at) WHERE state = 'queued'; partial `ix_precedent_note_versions_active` (heartbeat_at) WHERE state IN ('searching', 'writing'); `ix_precedent_note_versions_created` (created_at) for the daily count and data-health. Trigger `precedent_note_versions_freeze` (function `aslms_precedent_version_freeze`): `id`, `note_id`, `version`, `cases`, `mode` and `queued_at` never change; once `state` is `written`, `no_match` or `failed` no column changes; DELETE refused; plus `set_updated_at`. Grants as `precedent_notes`. Comment `class=transaction`. Written only by `services/precedent_notes.py` and `services/precedent_runner.py`. Holds no text written by the model or the officer: the fields are on the entries, the issue on the note. |
| `precedent_note_entries` (transaction, append-only) | id (uuid v7 PK), version_id (→ precedent_note_versions RESTRICT, NOT NULL), seq (smallint NOT NULL; the order's rank in the version, 1-based), state (`precedent_entry_state` NOT NULL), order_id (→ orders RESTRICT, NOT NULL), case_id (→ cases RESTRICT, NOT NULL), reading_id (→ order_sections RESTRICT, NOT NULL; the current reading used), document_id (→ documents RESTRICT, NOT NULL), pdf_sha256 (varchar 64 NOT NULL), text_sha256 (varchar 64 NOT NULL), parser_version (smallint NOT NULL), chunker_version (smallint NULL), chunk_ids (uuid[] NOT NULL default `{}`; the matched chunks, without FK: derived ids kept for the chain, as citations keep them), order_date (date NULL), form (`order_kind` NOT NULL), outcome (`order_outcome` NULL; the reading's rule-read outcome), against_state (boolean NOT NULL default false; row 251's rule), score (real NOT NULL), match (varchar 10 NOT NULL), same_order_cases (uuid[] NOT NULL default `{}`; the other cases holding the same body, at most 10, without FK, checked against `cases` by a database test), same_words_in (integer NOT NULL default 0), sources (jsonb NOT NULL; `[{n, kind (outcome / directions / matched / reasoning / background), part, para_first, para_last, page, page_to, src: [s, e], txt: [s, e], chars, given_sha256}]`), holding, reasoning, directions (text NULL; the checked text with its `[Sn]` markers and any removal line; NULL when not written or left out), fields_withheld (varchar(12)[] NOT NULL default `{}`), quotes (jsonb NULL; `{n: [[s, e], …]}` offsets in the given text), checks (jsonb NULL; per field `answer_checks` counts plus `over_limit`), response (jsonb NULL; the model's own reply, never shown, as `assistant_messages.response`), engine (jsonb NULL; model, `eval_count`, `prompt_eval_count`, milliseconds, retried), error_family (varchar 40 NULL), duration_ms (integer NULL), created_at | Unique `uq_precedent_note_entries_version_seq` (version_id, seq). CHECKs `ck_precedent_note_entries_failed` (`(state = 'failed') = (error_family IS NOT NULL)`), `ck_precedent_note_entries_written` (`state <> 'written' OR holding IS NOT NULL`), `ck_precedent_note_entries_silent` (`state = 'written' OR (holding IS NULL AND reasoning IS NULL AND directions IS NULL)`), `ck_precedent_note_entries_match` (`match IN ('words', 'meaning', 'both')`). Indexes `ix_precedent_note_entries_order_id`, `ix_precedent_note_entries_case_id`, `ix_precedent_note_entries_reading_id`, `ix_precedent_note_entries_document_id`. Trigger `precedent_note_entries_append_only` (`aslms_forbid_change`). Grants: ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT to `aslms_app`. Comment `class=transaction`. Written only by `services/precedent_runner.py`, once per order read. Every source is a run of paragraphs of the current reading of a court order; the text given is not stored and is rebuilt from `order_sections.body_text` and proved by `given_sha256`. Never holds notes, remarks, internal documents or drafts. Size: about 5 to 8 KB per entry. |

Estimated size: about 70 KB per 12-order version; at 50 notes a day about 1.3 GB a year. A database test checks every
`same_order_cases` element against `cases`.

## Services

- **`integration/sourcetrace/connector.py`**: `WriteSource`, `WriteRequest`, `WriteAnswer` and the protocol
  `CitedWriter` (decision 12), unless row 252 has provided an equivalent capability.
- **`services/assistant_ollama.py`**:
  - `OllamaConnector.write_cited(request)`: one `/api/chat` call through the client with `format`, the Assistant's
    options and `num_predict` from the request; parses the JSON (decision 10); returns `WriteAnswer`. Never retries
    itself (the service decides).
  - `PRECEDENT_SYSTEM_PROMPT`, `PRECEDENT_PROMPT_VERSION = 1`.
  - `admission_background()` and the waiting count in `admission()` (decision 15), unless row 252 provides them.
- **`services/research_search.py`**: `ranked_orders(...)` and `OrderRanking` (decision 6).
- **`services/precedent_sources.py`** (database, read-only): `order_sources(session, reading_id, matched_chunks, *,
  budget_chars, passage_chars) -> list[GivenSource]` (decision 9); `given_text(reading, source)` rebuilds the text and
  its hash. **Row 252 may provide the same reading of an order's best parts for its judgment summaries; if it does,
  this row uses it with the matched passages added; if not, this row adds this module.**
- **`services/precedent_notes.py`**:
  - `request(session, actor, user, *, issue, filters, cases, cfg) -> (note, version)`: the switches (decision 22),
    the limits (decision 16), the filters through `research_search.parse_filters` with `substantive_only` forced and
    the default forms (decision 5); writes `precedent_note.requested`.
  - `write_again(session, actor, user, note_id, cfg)`.
  - `notes(session, user, *, cursor, limit)`, `note(session, user, note_id, *, version)`: own only
    (`PrecedentNoteNotFound` otherwise), with `render` and the `text_changed` flags.
  - `passage(session, user, note_id, version, k)`; `cited_order(session, user, order_id, version_id)` for the
    court-record view.
  - `status(session, cfg, user)` for `GET /assistant/status`; `health(session, *, timeout_s)` for data-health.
- **`services/precedent_runner.py`**:
  - `run_forever(app_state)`: the lifespan task; `claim_next`, `sweep_stale`;
  - `write_version(session_factory, connector, version_id, cfg)`: search (`ranked_orders` in a read-only
    transaction), then per order: `text_matches`, `order_sources`, `admission_background`, `write_cited`, the retry
    on format, `check_citations` and `answer_checks.check` per field, the sentence limits, the entry insert, the
    heartbeat; the end state; `precedent_note.written`;
  - the priority key `aslms:research:person_writing` (decision 15).
- **`services/precedent_render.py`** (pure): `render(note, version, entries, orders) -> NoteView` (decisions 18 to
  20), `copy_text(view, *, brief)`.
- **`services/assistant.py`**: `_cited_order` accepts `precedent_version_id`; the page-and-highlight helper factored
  out of `passage_for` (decision 21), unless row 252 has done it.
- **`services/data_health.py`**: the `precedent_notes` block.
- **`services/preflight.py`**: the context-fit check (decision 9) as an error; a warning `precedent_notes_mode` when
  `PRECEDENT_NOTES_ENABLED` is true while `ASSISTANT_MODE` is not `ollama` or `RESEARCH_INDEX_ENABLED` is false.
  `no_local_model` and `no_cloud_model` unchanged.
- **`domain/precedent.py`**: `PrecedentNote`, `PrecedentNoteVersion`, `PrecedentNoteEntry` and the two enums.
- **`domain/audit_actions.py`**: the two actions.
- **`api/main.py`**: the runner started in the lifespan when notes are on, and stopped at shutdown.
- **`cli/precedent.py`**: `aslms precedent-notes`:
  - `status`;
  - `search "issue" [--cases N] [--forms …] [--explain]`: read-only, prints the ranked orders (case numbers, dates,
    forms, outcomes, scores, match) and the sources each would be given (parts, paragraphs, pages, characters),
    sends nothing to the chat model;
  - `check`: entries whose document is no longer a court order, `same_order_cases` ids that do not exist, versions
    stuck past the sweep.
- **Settings** (`core/config.py`, `.env.example`; no secret): `PRECEDENT_NOTES_ENABLED` (false),
  `PRECEDENT_NOTE_CASES` (12, 3 to 25), `PRECEDENT_NOTE_SECONDS` (300, 60 to 1,800), `PRECEDENT_CALL_SECONDS` (60, 10
  to 280), `PRECEDENT_ENTRY_TOKENS` (600, 200 to 1,500), `PRECEDENT_ORDER_CHARS` (12,000, 4,000 to 30,000),
  `PRECEDENT_NOTES_PER_DAY` (10, 1 to 100), `PRECEDENT_QUEUE_MAX` (5, 1 to 50). Constants in code with a test: the
  sentence limits (3, 4, 3), the part budgets of decision 9, the outcome order of decision 18, 10 common-judgment case
  numbers, 300 characters per rule-read direction.

## API

Every route needs `assistant.use` (open question 2) and serves only the caller's own notes (404 otherwise).

| Method and path | Function | Request and response |
|---|---|---|
| `POST /assistant/precedent-notes` | `assistant.use` | **New.** `{issue (3 to 300 characters), filters? {forms?, outcomes?, against_state?, cites?, act?, from?, to?}, cases? (1 to PRECEDENT_NOTE_CASES)}`. 202 `{note: PrecedentNoteOut, version: {version, state: "queued", position}}`. Errors: 400 `bad_issue`, 400 `bad_filter`; 409 `precedent_in_progress`; 429 `precedent_limit` (with `resets_at`); 503 `precedent_off`; 503 `precedent_busy`. Writes `precedent_note.requested`. |
| `GET /assistant/precedent-notes` | `assistant.use` | **New.** `?cursor&limit` (as `GET /assistant/conversations`). `{items: [{id, issue, filters, cases, last_version, state, cut_short, entries_written, written_at, last_activity_at}], next_cursor}`, newest activity first. |
| `GET /assistant/precedent-notes/{id}` | `assistant.use` | **New.** `?version=n` (default: the latest finished, else the latest). `{note, version: {version, state, position?, progress: {done, planned}, cut_short, stop_reason, error_family, model, prompt_version, checks_version, retrieval, checks, queued_at, started_at, finished_at}, label, heading_lines, groups: [{year, outcomes: [{outcome, label, entries: [{seq, state, case: {id, ref_no, case_no, case_type}, order: {id, date, form, judge, outcome, outcome_label, against_state}, same_order: {count, case_nos}, holding, reasoning, directions, fields_withheld, rule_facts: {outcome_text, directions: [{text, page}]}}]}]}], left_out: [{seq, state, case_no, order_date, form, reason}], citations: [{k, seq, n, order_id, document_id, case_no, order_date, form, page, page_to, src, quotes, text_changed}], text_changed, versions: [{version, state, finished_at}], copy_text, copy_text_brief}`. Court-public text and the officer's own AI note; not audited (as reading a conversation). |
| `POST /assistant/precedent-notes/{id}/versions` | `assistant.use` | **New.** Write Again: 202 as the first request, same errors. Writes `precedent_note.requested`. |
| `GET /assistant/precedent-notes/{id}/versions/{version}/citations/{k}/passage` | `assistant.use` | **New.** As row 251's passage endpoint: `{order_id, document_id, page, page_count, page_text, highlights: [{start, end, kind: "passage" or "quote", exact}], text_changed}`. Not audited. |
| `GET /assistant/court-orders/{order_id}` and `/file` | `assistant.use` (unchanged) | Accept `precedent_version_id` in place of `message_id` (exactly one of them, 400 otherwise). Same checks and audit, with `precedent_version_id` in `after`. |
| `GET /assistant/status` | `assistant.use` (unchanged) | Gains `precedent: {state, cases_max, queue, mine: {in_progress, left_today}}`. |
| `GET /admin/data-health` | `reports.state`, `admin.napix_refetch` or `admin.masters_sync` (unchanged) | Gains the `precedent_notes` block (counts only). |

`frontend/src/lib/api/schema.d.ts` is regenerated in round 1 (the OpenAPI snapshot); no screen uses it until round 2.

## Jobs

| Kind | Where | When | What | Writes |
|---|---|---|---|---|
| precedent runner | api process, asyncio task from the lifespan | continuously while notes are on; the stale sweep at start and every 60 s | claims queued versions one at a time; search, then one model call per order, people's questions first | `precedent_note_versions`, `precedent_note_entries`, `audit_log` `precedent_note.written` |

No Celery task, no `job_runs` row (the version is the record), no `fetch_queue` row and no NAPIX call.

## Tests

**Unit (no database, no model):**
- `test_render_groups_year_then_outcome_then_date`: years ascending; the fixed outcome order; Outcome Not Read last.
- `test_render_citation_numbers_in_reading_order`: `[S2]` of entry 3 becomes the right `[k]`; references in words.
- `test_copy_text_label_first_and_brief_when_long`: the AI label starts the text; `copy_text_brief` drops reasoning;
  both under 20,000 characters for a 12-entry fixture.
- `test_entry_heading_from_held_data_only`: the case number, date, judge, outcome and Against the State come from
  the rows, never from the model's fields.
- `test_sentence_limits_trim_and_count`: a fourth holding sentence is dropped and counted `over_limit`.
- `test_holding_withheld_makes_entry_withheld`; `test_reasoning_withheld_left_out_with_line`;
  `test_not_relevant_listed_left_out`.
- `test_write_cited_sends_format_and_same_num_ctx` (`httpx.MockTransport`): `format` schema present, `num_ctx`
  equal to the Assistant's, `num_predict` = `PRECEDENT_ENTRY_TOKENS`, `think: false`.
- `test_write_cited_parses_json_and_reads_object_in_text`; `test_invalid_json_retried_once_then_failed`.
- `test_order_sources_fill_order_and_budget`: outcome, directions, matched, reasoning, background; no paragraph twice;
  never past `PRECEDENT_ORDER_CHARS`; a one-part body gets its last paragraphs.
- `test_given_sha256_rebuilds`.
- `test_context_fit_preflight`: a setting past `num_ctx` is refused.
- `test_precedent_readers_touch_only_court_tables`: the SQL table scan of decision 2 over `precedent_*.py`.
- `test_precedent_service_does_not_import_ollama_client`: the import guard's list unchanged.
- `test_prompt_rules_version_1`.

**Database (scripted connector or `httpx.MockTransport`; never a real model):**
- `test_migration_up_down_up`: types, tables, triggers, grants; `aslms_app` cannot DELETE from any of the three.
- `test_entries_append_only`; `test_version_frozen_when_finished`; `test_note_touch_only_listed_columns`.
- `test_request_switches_and_mode`: off unless enabled, ollama mode and the index on; 503 `precedent_off`.
- `test_one_in_progress_per_officer`: 409; `test_daily_limit_ist`: 429 with `resets_at`; `test_queue_max`: 503.
- `test_default_forms_and_substantive_forced`: interim orders only when asked; procedural never.
- `test_ranked_orders_one_per_case_and_cap`: two orders of one case give one entry; the cap holds.
- `test_shared_body_one_entry_with_same_order_cases`.
- `test_words_only_when_query_embed_fails`: the note is written, `retrieval.kind = words_only`.
- `test_stale_text_dropped_never_cited`.
- `test_runner_end_states`: written, no_match, failed with `model_unavailable` and `search`.
- `test_time_limit_cut_short_keeps_entries`; `test_entry_timeout_failed_and_continues`.
- `test_stale_sweep_interrupted`: a version with an old heartbeat becomes `written` + `cut_short` or `failed`.
- `test_question_goes_before_next_entry`: with a question waiting, the runner does not take the slot.
- `test_runner_never_touches_fetch_queue_or_napix`.
- `test_own_notes_only`: list, read, Write Again, passage and court-order routes answer 404 to another officer and to
  the Super Administrator.
- `test_write_again_new_version_old_kept`.
- `test_text_changed_flag_on_read`.
- `test_passage_page_relative_highlights`.
- `test_court_order_view_by_precedent_version_audited`: `assistant.court_order_opened` with
  `precedent_version_id`; an order the version does not cite answers 404.
- `test_audit_rows_counts_no_text`: `precedent_note.requested` and `.written` carry no issue and no field text.
- `test_entries_record_the_chain`: order, document, reading, both hashes, parser and chunker versions, chunk ids,
  model key, `given_sha256` per source.
- `test_data_health_precedent_block_timeout_parts`; `test_assistant_status_precedent`.
- `test_same_order_cases_exist`.
- `test_preview_mode_no_notes`.

## Verification

1. **Migration.** `pre-migrate` backup, then the `migrate` step. `\d+` shows the three tables and triggers;
   `aslms_app` cannot DELETE from them.
2. **Ollama's structured output.** On the owner's machine (Ollama 0.40.11, `qwen3.5:4b`, `think: false`), one
   `write_cited` call on a masked fixture order records whether `format` is honoured (`message.content` parses as the
   schema) and the token counts. If not honoured, record the reply's form; the parser and retry rule stand.
3. **Search check.** `aslms precedent-notes search "regularisation of contractual teachers" --explain` and four other
   issues chosen by the owner (for example pension of provincialised teachers, recovery from salary, compassionate
   appointment, contempt for non-compliance). Record for each: the 12 orders chosen, one per case, the forms and years,
   the sources' sizes, the time (expected under 5 s).
4. **Five live notes** with `PRECEDENT_NOTES_ENABLED=true` on the owner's machine. Record per note: the time
   (expected about 1.5 to 2.5 minutes for 12 orders), the entries by state, the checks' counts, `cut_short`. While one
   note writes, ask an All Court Orders question: it must answer within its usual time plus at most one entry call
   (record the wait). Open every citation of one note: each opens the order's page with the passage highlighted.
5. **Restart drill.** Recreate `api` (with the court-data switch, `--no-deps --force-recreate`) while a note writes.
   Within 2 minutes of start the version is `written` with `cut_short` and `interrupted`, or `failed` (`interrupted`);
   Write Again writes a new version.
6. **Copy to Note** (after round 2; listed here so the note is complete): copy a note into a test case's note;
   the note is saved as an ordinary note with `note.added`.
7. **Worked note for Annexure E.** One note written in a test database over the masked fixtures (`judgment_parts.txt`,
   `final_directions.txt` and one more masked judgment if the fixtures need it), with the real local model: the
   ranked orders, the sources of one entry with their pages and offsets, the model's fields, the checked entry with
   one removed sentence if one occurs, and the assembled note. Saved for the scribe; never from an unmasked order.
8. **Documentation** (scribe): Software Documentation section 6.5 gains "Precedent notes" (the search, one call per
   order, the grouping by year and outcome, the checks, the limits and the queue) and Annexure E the worked note;
   section 13.2 the variation (decision 1); `docs/ASLMS_Process_Workflows.md` the owner's plain-words explanation; the
   runbook a section (the next free number, 30 if row 252 takes 29): the switch, the settings, the restart behaviour,
   reading the data-health block; the decisions log an entry; `docs/design/assistant-ollama.md` "Not covered" the
   amendment line.

## Open questions

1. **Which orders does a note use by default?** The row says "judgments and substantive orders".
   - (a) **Recommended:** substantive judgments and substantive final orders by default; substantive interim orders
     only when the officer ticks Interim in the order forms (decision 5).
   - (b) Every substantive order, interim included, ranked together (judgments and final orders weighted × 1.2): about
     83,000 substantive interim orders would compete with about 30,000 judgments and final orders for the slots.
2. **Which function allows writing a note?**
   - (a) **Recommended:** `assistant.use`, as the row places the action inside the Assistant; the load is held by the
     per-officer and queue limits of decision 16.
   - (b) A new function "Write Precedent Notes" (`assistant.precedent_notes`), granted by default to every user type
     that holds `assistant.use` by default, so the Super Administrator can switch it off for a type or a person
     without removing the Assistant. This adds a reference-data step to the migration.
3. **Should the model also write an opening passage across the cases** ("Across these orders the court has …")?
   - (a) **Recommended: no, not in this row.** The note opens with ASLMS's count line and the grouping, and each
     entry is written from one order only. A sentence that generalises across orders can pass every word check (each
     word is in some cited order) and still be a wrong generalisation, which the checks cannot catch.
   - (b) Yes: one more call after the entries, given only the checked entries, at most 4 sentences, each citing the
     entries' sources and checked against them, labelled as AI text. Adds about 10 s per note.
