# Design: Case Assistant — the query contract, preview mode, conversations and the portal

```
slug: assistant
status: approved
author: architect
date: 2026-10-23
approved_by: owner on 2026-10-23, with the recommended defaults (court orders open to standing counsel too; preview refused in prod; no user delete of conversations; 30 questions an hour; another department's order opens only from a citation)
```

## Context
Plan §5.9 (Case Assistant and Legal Research), §3.2 (the SourceTrace connector "sends Case Assistant questions,
research and order-reading requests"), Table 9 (Phase 3), Annexure B "Case Assistant" (a chat on the case page;
answers cite their sources, can be copied into a case note; a side panel shows the sources used). What the plan
asks for:
- a chat on every case page. With each question the portal passes the case's context (CNR, case details, orders
  and court filings);
- answers drawn from the case's own orders and court filings, orders and judgments in related past cases, and the
  Acts, rules and policies held in SourceTrace;
- every answer cites its sources, and each source opens in the portal;
- an answer can be copied, with its references, into a new case note;
- each user's conversation is saved and visible only to that user;
- general research across all orders without starting from a case;
- notes and internal documents are never sent to SourceTrace.

Backlog row 14 adds the rules left by `sourcetrace-connector` (decisions 4, 9, 10, 11): pass only references
the asking user may see, never archived ones, and keep related-case retrieval to court orders.

Owner's request (23 Oct 2026): "I will be using an AI assistant later on to work and research on the cases I
have. Make the provision now so I can integrate and test it later, but at least I can check it now."

Owner's decisions given during this design (23 Oct 2026), built in below as decisions 3 and 4:
- **Court-public material is open to every assistant user**, across all cases in ASLMS, whoever owns them. That
  is everything obtained from NAPIX: case details, court orders and judgments, cause-list entries. The reason:
  officers research earlier judgments and similar pending cases, and this material is already public on the High
  Court website.
- **Internal material never crosses the existing visibility.** This covers notes, note attachments, internal and
  admin documents, custody remarks, drafts and department uploads. **Department uploads, uploaded court filings
  included, stay private to the department under the normal document visibility.** They are the department's
  copies: internal material, not court-public research material.

In place today:
- Tables `assistant_conversations` (user_id → users RESTRICT, case_id → cases RESTRICT NULL, scope enum
  `assistant_scope` (`case` / `research`), title ≤ 300, last_message_at, created_at, updated_at) and
  `assistant_messages` (conversation_id → assistant_conversations CASCADE, role enum `message_role`
  (`user` / `assistant` / `system`), content text, citations jsonb, model_info jsonb, created_at). Both were
  created by migration **0001**, are class `transaction` and are empty: nothing writes them. `case_dedupe`
  re-points conversations when cases merge. `aslms_app` may DELETE from `assistant_messages`, which is in
  `CASCADE_TABLES`, and has no DELETE on `assistant_conversations`.
- The function `assistant.use` ("Case Assistant"), module `assistant`. Every type holds it by default except the
  Auditor (removed by row 121, migration 0022); the super admin holds every function.
- `integration/sourcetrace/`: the `SourceTraceConnector` protocol (ingest only; "the query side is added by the
  items that use it"), `connector_state` (`disabled` / `not_implemented`; `ready` is unreachable),
  `get_connector` (always `None`), `FakeSourceTrace` (tests only). `services/sourcetrace_ingest.py` holds the
  sendable rule (`nature_condition`, `assert_sendable`). `documents.sourcetrace_status`, `sourcetrace_ref`, and
  `assistant_available` on the document output.
- Stored text: `document_text.full_text` (PDF pages joined with `"\n\f"`, so a page number can be derived) and
  `search_vector` (GIN). `documents.search` already does `websearch_to_tsquery` + `ts_rank` + `ts_headline` under
  the document visibility rule. No OCR in Phase 1 (row 23, option C), so scanned orders have no text.
- `my_cases.my_cases_condition` (allotted, file with me, claimed by me, standing counsel's codes);
  `visibility.document_visible_condition` and `can_view_case`; `workflow_common.digest` (length + sha256 for
  audit rows); `audit.write_audit`.
- Portal: the round-3 case page with tabs (`CASE_TABS`), "The Case Assistant tab comes with row 14" in
  `CaseFrame.tsx`; `NoteDialog`; the sidebar `NAV` (Work, Oversight, Settings); `INLINE_PDF` with the browser
  viewer honouring `#page=`.

Not covered:
- The real SourceTrace query call. That is row 36 (`sourcetrace-http-connector`), blocked on SourceTrace's API
  documentation. This item defines the contract that connector must implement.
- Acts, rules and policies (they live in SourceTrace, so nothing is held in ASLMS).
- Streaming answers.
- Next-date reading through SourceTrace (the parked `sourcetrace-next-dates`).
- District Court material (Phase 3, NAPIX DC).
- OCR (row 96).

## Decisions

1. **A query contract on the connector, separate from ingestion, provider-neutral.**
   `integration/sourcetrace/connector.py` gains:
   - the value types `AskRequest`, `AskScope`, `CaseContext`, `Turn`, `Answer` and `Citation` (Services);
   - the protocol `AssistantConnector` (`name: str`; `async def ask(self, request: AskRequest) -> Answer`).

   The ingest protocol is unchanged. The future HTTP connector (row 36) implements both protocols, and the
   preview implements only `ask`. Errors reuse the existing `SourceTraceUnavailable` (connection, 5xx,
   throttling) and `SourceTraceRejected` (the question refused), and add `SourceTraceProtocolError` (a malformed
   answer). Timeouts are applied by the service (`asyncio.wait_for`, `ASSISTANT_TIMEOUT_SECONDS` = 45), as
   ingestion does.

   Retries: one, only after `SourceTraceUnavailable`, after 2 s, and only while the time budget allows. No retry
   after a timeout, a refusal or a malformed answer, because a person is waiting.

   No streaming in this item. A later `ask_stream` can be added once SourceTrace's API shows whether it streams.

   Alternatives rejected:
   - adding `ask` to the ingest protocol: the preview would have to fake ingestion;
   - an HTTP-shaped contract (URLs, headers): it would invent SourceTrace's API.

   Every guess about SourceTrace's API is in Open questions (for row 36).

2. **Three modes, one switch: `ASSISTANT_MODE` = `off` (default), `preview` or `sourcetrace`.**
   `services/assistant.py::assistant_state(settings)` answers:
   - `off`;
   - `preview`;
   - `not_implemented`: `sourcetrace` is chosen but `connector_state` is not `ready`, which is always the case
     until row 36;
   - `ready`.

   `assistant_connector(settings, session_factory)` returns the preview connector only in `preview`, the real
   connector only when `ready`, and otherwise `None`. With `None` every question is refused with 503
   `assistant_off` before anything is stored. The fake is never returned (as `sourcetrace-connector` decision 2).
   `sourcetrace` needs `SOURCETRACE_ENABLED=true` as well; the two switches stay independent (ingestion can run
   without the assistant).

3. **Court-public material is open to every assistant user (owner's decision, 23 Oct 2026).**
   - Court orders and judgments of every case in ASLMS, whoever owns the case, may be searched, cited and
     opened through the assistant.
   - For that material the assistant needs `assistant.use` only, not `cases.view_*` and not `documents.view`.
   - The court-public facts of a cited case go with it: CNR, case number, filing number, court and bench, case
     type, year, status, parties and advocates as listed, acts, hearing dates and next date, as already shown by
     local search's court-public summaries.
   - **Deviation (owner's decision, flagged):** documents-uploads decision 7 gives court records to anyone who can
     see the case. This widening is limited to court-record order PDFs, and only through the assistant paths of
     this note. `GET /documents/*`, the case page and `/documents/search` keep their rule unchanged.
   - It holds for every type with `assistant.use`, standing counsel included.

4. **Internal material never crosses the existing visibility (owner's decision, 23 Oct 2026).**
   - Notes, note attachments, internal and admin documents, custody remarks, drafts and cause-list PDFs are never
     in the assistant's corpus in any mode, and never sent to SourceTrace.
   - **Department uploads, uploaded court filings included, stay private to the department under the normal
     document visibility (owner confirmed).** A court filing is in a user's corpus only when
     `document_visible_condition` (function `documents.view`, a visible case, the record rule of the same
     membership) passes for that user.
   - A filing kept `private_to_office` is never in the corpus, even for its own office, because it is never sent
     to SourceTrace (`ck_documents_private_not_sent`). The preview mirrors exactly what SourceTrace could hold.
   - The question text itself is the only user text that leaves ASLMS. The composer says plainly not to type note
     text or internal remarks (decision 12).

5. **Three scopes.**
   - `case`: one case, from the case page. The caller must be able to see the case (`can_view_case`, else 404).
     The corpus is the case's own court orders and its visible court filings. `include_related` (default true)
     adds court orders of other cases, shown apart as "Related orders in other cases". That is the plan's
     "orders and judgments in related past cases", which needs no sight of those cases (decision 3).
   - `my_cases`: the cases from `my_cases_condition`, ANDed with `visible_case_condition`, not merged; at most
     `ASSISTANT_MAX_FOCUS_CASES` (1,000), newest activity first, with `truncated` recorded. The corpus is their
     court orders and visible court filings.
   - `research`: every court order in ASLMS, plus the court filings the caller may see (any case). This is the
     plan's "general research", and it uses the existing enum value `research`.

   New enum value `my_cases` (Data). The CHECK requires `case_id` exactly when the scope is `case`.

6. **The eligibility rule, written once, the same for both modes** (`services/assistant_sources.py`). Two
   corpora, each a SQL condition over `documents`.

   **Court orders (court-public)**:
   ```
   d.kind = 'order' AND d.doc_group = 'court_record' AND d.virus_scan_status = 'skipped'
   AND d.archived_at IS NULL
   AND EXISTS (SELECT 1 FROM orders o JOIN cases c ON c.id = o.case_id
               WHERE o.document_id = d.id AND c.merged_into_case_id IS NULL
                 [AND o.case_id = ANY(:focus_case_ids)])        -- case / my_cases; absent for research
   ```
   No visibility predicate (decision 3). The order part of `sourcetrace_ingest.nature_condition` is reused, so the
   two rules cannot drift.

   **Court filings (department copies)**:
   ```
   d.kind = 'upload' AND d.doc_group = 'court_filing' AND d.virus_scan_status = 'clean'
   AND d.visibility <> 'private_to_office' AND d.archived_at IS NULL
   AND c.cnr IS NOT NULL AND c.cnr <> '' AND c.merged_into_case_id IS NULL   -- c = cases of d.case_id
   AND <document_visible_condition(session, user)>                          -- documents.view, case, record rule
   [AND d.case_id = ANY(:focus_case_ids)]                                   -- case / my_cases
   ```
   The filing part of `nature_condition` and ingestion's CNR rule are reused.

   Per mode:
   - preview adds `document_text.search_vector IS NOT NULL`;
   - sourcetrace adds `d.sourcetrace_status = 'ingested' AND d.sourcetrace_ref IS NOT NULL`.

   The filings are passed as an explicit allow-list of document ids (sourcetrace: their `sourcetrace_ref`), at most
   `ASSISTANT_MAX_FILING_SOURCES` (1,000), newest `doc_date` first, with `truncated` recorded. Court orders are
   passed as a corpus description (`orders = focus | focus_and_related | all` plus the focus CNRs), never as a
   list: there are ~394,000.

   The preview connector applies the nature conditions again in its own SQL (a second check). Kinds `attachment`,
   `admin` and `causelist`, and the group `internal`, can never match either corpus.

7. **Preview mode, so the owner can check the assistant now, without SourceTrace and without any model.**
   `services/assistant_preview.py::PreviewConnector` implements `AssistantConnector`. It answers by PostgreSQL
   full-text search over the stored text of the corpus of decision 6:

   1. **Query.** `q = websearch_to_tsquery('english', :question)`. A question of only stop words (`numnode(q) = 0`)
      gets outcome `no_match` with "Use more specific words".
   2. **Documents.** Rank the matching documents by `ts_rank(search_vector, q)`, then `doc_date` descending. Keep:
      - the top 5 for the focus (case, or my cases);
      - with `include_related`, also the top 3 court orders of other cases, ranked separately;
      - for research, the top 6 overall.
   3. **Fallback.** When the case or my-cases corpus has no match under the all-words query, it retries once with
      any word: `to_tsquery('simple', <the question's lexemes, each quote_literal'd, joined by ' | '>)`. Research
      never falls back, because "any word" over every order is too broad.
   4. **Passages.** For each document, split `left(full_text, 200000)` on `\f` `WITH ORDINALITY`. Keep the pages
      whose `to_tsvector('english', page) @@ q`, at most 300 pages per document. Take the best 2 pages by rank,
      each with
      `ts_headline('english', page, q, 'MaxWords=60, MinWords=25, MaxFragments=1, StartSel=[[, StopSel=]]')`.
      The page number is the ordinal for PDFs and `null` for Word files.
   5. **Limits.** At most `ASSISTANT_PREVIEW_PASSAGES` (8) passages. The whole search runs under
      `SET LOCAL statement_timeout = ASSISTANT_PREVIEW_SQL_MS` (8,000 ms); a timeout gets outcome `failed`, family
      `timeout`, with "The question is too broad for the preview; add more specific words".

   The answer text is fixed, never composed:
   - first line: **"Preview: passages found in the court records, not an AI answer."**;
   - then: "{n} passages from {d} documents matched {all / any} of the words of your question.", or "No passage in
     the court records of this scope matched the words of your question." (outcome `no_match`).

   The excerpts are the citations.

   **Why this does not breach "no cloud LLM, no local model":** the preview uses no AI and no model of any kind.
   There is no neural network, no embedding, no generated text and nothing trained. It is PostgreSQL's built-in
   text search: dictionary stemming, word-frequency ranking and verbatim excerpts. It has been used by document
   search since row 4. Nothing leaves the server, and the only text it adds is a fixed template. It goes through
   the same connector contract, so the SourceTrace path is the same code path apart from the connector.

   **Preview is for dev and test only.** In `APP_ENV=prod`:
   - `aslms ops preflight` reports `ASSISTANT_MODE=preview` as an ERROR, so `init` refuses to start;
   - `assistant_state` answers `off` with one warning log if it is reached anyway.

   Alternative rejected: allowing it in prod as an interim search. Users would read a word search as the Case
   Assistant, and the plan puts all research through SourceTrace.

8. **Conversations: private, append-only, never deleted.**
   - A conversation belongs to one user. Only that user can list or read it: not the super admin, not the Auditor
     (plan: "visible only to that user"). There is no API for anyone else. The audit trail holds digests only.
   - A case-scope conversation is readable only while the user can still see the case (404 otherwise).
   - *Owner, 23 Oct 2026:* the case page's Assistant tab has a scope switch **This case | My cases | All court
     orders**, starting on This case, with a one-line note under the question box naming what is searched. The
     Assistant page in the menu has My cases | All court orders. Switching the scope searches the last question again.
     The visual reference is `docs/design/ui/aslms-final-template.html`.
   - *Owner, 23 Oct 2026:* the conversation does not grow the page. It sits in a box of fixed height
     (`min(60vh, 560px)`) with its own vertical scroll bar. The question box and the Sources panel stay in view.
     A new answer scrolls the box to the newest message; choosing an older answer keeps the position. The box is
     keyboard-focusable and labelled "Conversation", with no smooth scrolling under reduced motion.
   - A user may hold several conversations per case and per scope ("New conversation"). The Assistant tab opens
     the latest. The title is the first 80 characters of the first question.
   - Messages are append-only, enforced by the trigger `aslms_forbid_change` and by removing UPDATE and DELETE
     from `aslms_app`. Conversations are never deleted; `aslms_app` already has no DELETE on them. The only updates
     are `title`, `last_message_at` and the `case_id` re-pointing on a merge.
   - At most `ASSISTANT_MESSAGES_PER_CONVERSATION` (200) messages per conversation (409 `conversation_full`, "start
     a new conversation").
   - Retention: kept with the system's records. The DB_STANDARD §6 retention policy applies when the owner sets
     it. There is no user delete (owner check).
   - **Reading again re-checks filing citations.** Every stored citation of a court filing is checked against the
     caller's current document visibility. If any fails:
     - that citation shows "This source is no longer available to you", with no excerpt;
     - the answer text is hidden ("This answer drew on a document you can no longer see").

     Court-order citations are court-public and stay shown.

9. **One question at a time, rate-limited, three short transactions.**
   - **Transaction A.** Validate, then lock the conversation row (`FOR UPDATE`). Refuse with 409
     `question_in_flight` while that conversation has a question with no answer created within the last
     `ASSISTANT_TIMEOUT_SECONDS + 15` s. Check the hourly limit: `ASSISTANT_QUESTIONS_PER_HOUR` (30) per user,
     counted from `assistant_messages` role `user` in the user's conversations; 429 `assistant_limit` with
     `retry_after`. Insert the question with its `scope_info`, write `assistant.asked`, commit.
   - **The call.** Call the connector outside any transaction.
   - **Transaction B.** Insert the answer, update `last_message_at`, write `assistant.answered`, commit.

   No transaction is held across the call, so this is safe under PgBouncer transaction mode (row 78).
   Questions are 3–2,000 characters (`ASSISTANT_QUESTION_MAX_CHARS`; 422 `bad_question`).

   If the process dies between A and B, the question stays without an answer. It shows as "No answer was
   recorded", and the in-flight window expires.

10. **Every question and every answer is audited, without their text.**
    - `assistant.asked`, entity `assistant_message` (the question), `case_id` for case scope. `after` holds
      `conversation_id`, `new_conversation`, `scope`, `mode`, `question` = `digest()` (length, sha256),
      `include_related`, `focus_cases`, `filings_passed`, `truncated`.
    - `assistant.answered`, entity `assistant_message` (the answer). `after` holds `question_id`, `mode`,
      `connector`, `outcome`, `error_family`, `duration_ms`, `answer` = `digest()`, `citations` = the cited
      document ids and order ids (no text).
    - `assistant.court_order_opened` (decision 11).

    Reading a conversation writes no audit row, as other reads do. The Audit log screen gains the group "Case
    Assistant". Alternative rejected: one row per question written after the answer, because a crash would lose
    the question's row.

11. **Opening a cited court order of a case the caller cannot see: a read-only court-record view.**
    - `GET /assistant/court-orders/{order_id}?message={answer_id}` returns the order (number, date, kind, judge)
      and the case's court-public facts (decision 3).
    - `GET /assistant/court-orders/{order_id}/file?message={answer_id}&disposition=inline|attachment` serves the
      order PDF from the store, with the same headers as the documents file route (`Content-Security-Policy:
      sandbox`, `nosniff`).
    - Both need `assistant.use`. The order's document must satisfy the court-order corpus rule (court record,
      `skipped`, not archived, case not merged). The answer `message` must be one of the caller's own messages,
      and its `citations` must name this order (`citations @> '[{"order_id": "<id>"}]'`). Otherwise 404.

    Requiring a citation keeps this from becoming a bulk downloader outside the hourly question limit. Every
    opening of the facts page or the file writes `assistant.court_order_opened` (entity `order`, `case_id`,
    `after`: `document_id`, `what` = `facts` / `file`, `disposition`, `message_id`, `case_visible` true / false).

    The view never shows the owner department, recommendations, custody, stage, notes, the documents list,
    alerts or `ref_no`. The portal page (`/assistant/orders/[orderId]?m=`) says: "This is the court's public
    record. You cannot open this case in ASLMS."

    When the caller can see the case, the portal opens the ordinary order file route instead. The assistant
    route still works and is still audited.

    Alternative rejected: widening `GET /documents/{doc}/file` for court records. That changes the general
    document rule beyond the assistant.

12. **What is sent to SourceTrace (sourcetrace mode, row 36), fixed now:**
    - the question;
    - the last `ASSISTANT_HISTORY_TURNS` (6) question and answer pairs of the same conversation (only its own
      questions and the connector's own answers; withheld answers are not sent);
    - the scope (decision 6): kind, focus `CaseContext`s (court-public facts only: CNR, case number, court, type,
      year, status, parties and advocates as listed, acts, last and next hearing dates), the order corpus
      (`focus` / `focus_and_related` / `all`, which means `source_kind = court_order`), the filing allow-list of
      `sourcetrace_ref`s, and `truncated`;
    - `request_id` (the question's id, an idempotency key).

    Never sent: notes, drafts, attachments, internal or admin documents, custody remarks, stages, the owner,
    recommendations, the user's name or office.

    Citations come back by reference. The service maps each one to a document by `sourcetrace_ref` (`external_id`
    is the document id, `sourcetrace-connector` decision 4). If any citation is outside the scope sent (a filing
    not in the allow-list, or anything not a court order or court filing), the whole answer is withheld: outcome
    `failed`, family `scope`, with "The answer drew on material outside your reach and was withheld". This is
    stricter than dropping the citation, because the answer text may quote the material.

13. **Copy to note.** On a case-scope answer the portal offers "Copy to note" (secondary). It shows when the case
    workflow block allows a note (`workflow.note_mode`). It opens the existing `NoteDialog` filled with the answer
    text and its references in words ("Order of 12-03-2026, No. 5, page 2"). The person edits and saves an
    ordinary note (source `user`), audited as `note.added` as today. Preview answers can be copied too: their
    excerpts are court-record text. No new note source; nothing flows from notes to the assistant.

14. **Portal (round 1 to 5 design system: tokens, kit, alignment rule, one primary per page, phone layout).**
    - **Case page tab "Assistant"**: `/cases/[ref]/assistant`, in the main tabs after Timeline. It shows when the
      login holds `assistant.use` and `/me.assistant_mode` is not `off`. `CaseFrame.tsx` loses the "comes with
      row 14" line.
    - **Sidebar entry "Assistant"** (Work group, after Search): `/assistant`, same condition. It has two tabs, "My
      cases" and "All court orders" (research). The conversation list is on the left and the thread on the right.
      On phones the list and the thread are separate views, with a back link.
    - **The thread**: chat-style messages. Each answer is a card with its outcome in words, the text, and its
      sources. At 1280 px the sources sit in a side panel "Sources used" (Annexure B); at 375 and 768 px they sit
      under the answer.
      - Each source shows the document (type, date, order number, the case number when it is another case), the
        page and the excerpt, with `[[ ]]` rendered as highlights.
      - A court order of a visible case and a court filing open the ordinary file route in a new tab with
        `#page=N` (PDF, while `INLINE_PDF`; Word files download).
      - A court order of a case the caller cannot see opens `/assistant/orders/[orderId]?m=` (decision 11).
      - Related orders are grouped under "Related orders in other cases".
    - **Suggested questions** (chips, empty thread only).
      - Case: "What did the last order direct?", "When is the next hearing and why?", "What is the petitioner
        asking for?", "Has the court asked the State to file anything?".
      - My cases: "Which of my cases have a direction to file an affidavit?".
      - All court orders: "Orders on regularisation of contractual teachers".
    - **Banners.**
      - Preview: a warning `Notice` on every Assistant screen, "Preview: passages found in the court records, not
        an AI answer. Questions are searched as words; no AI is used." Every preview answer also carries a
        "Preview" badge, kept on old answers after the mode changes (the message's `mode`).
      - Sourcetrace: "Answers come from SourceTrace. Check every source before relying on it. Do not type note text
        or internal remarks into a question."
    - **Composer**: a textarea with a character count and the hourly allowance left. **Ask** is the one primary
      button of the screen; "New conversation" and "Copy to note" are secondary.
    - **States**: "Searching the court records…" while waiting. Every error code and outcome is in words in
      `messages.ts`.
    - `uicheck` fixtures for the three new routes at 375, 768 and 1280 px.

15. **Sizing.**
    - **Buildable now**, in one cycle (backend and portal):
      - the contract;
      - preview mode;
      - the eligibility rule;
      - conversations and limits;
      - audit;
      - the court-record view;
      - API, CLI, migration 0024 and the tests with `FakeSourceTrace`'s new `ask`;
      - the portal.

      This is about the size of row 26 plus row 73 together. The owner may split the portal into a row of its own
      at approval.
    - **Waits for row 36**:
      - `ask` on the real HTTP connector;
      - the mapping of SourceTrace's citations and locators;
      - the allow-list filter (Open questions S2);
      - Acts, rules and policies citations (no ASLMS document to open: shown as text references);
      - switching `ASSISTANT_MODE=sourcetrace` (it becomes `ready`).

## Data
Migration **0024** (`0024_assistant.py`, new; head is 0022 on main and row 122 takes 0023; no applied migration
is edited). The developer renumbers only if the order of merges changes, and records it.

Replace the two rows in `docs/schema/schema.md` ("Phase 2 and 3 tables"):

> | `assistant_conversations` (transaction) | id (uuid v7 PK), user_id (→ users RESTRICT; the owner, the only reader), case_id (→ cases RESTRICT, NULL), scope (`assistant_scope`: `case`, `research`, `my_cases` — `my_cases` added by 0024), title (≤ 300; the first 80 characters of the first question), last_message_at, created_at, updated_at | CHECK `ck_assistant_conversations_case_scope` (`(scope = 'case') = (case_id IS NOT NULL)`). Index `ix_assistant_conversations_user_last` (user_id, last_message_at DESC NULLS LAST) replaces `ix_assistant_conversations_user_id`; `ix_assistant_conversations_case_id` kept. Never deleted (`aslms_app` has no DELETE); updated only for `title`, `last_message_at` and `case_dedupe`'s re-pointing. Private to the user: no API reads another user's conversations (design `assistant`, decision 8). No `created_by` column: `user_id` is the creator and only writer. |
>
> | `assistant_messages` (transaction, append-only) | id (uuid v7 PK), conversation_id (→ assistant_conversations CASCADE, DB_STANDARD §6; cannot fire, conversations are never deleted), role (`message_role`; `system` not written), content (text; a question 3–2,000 characters, an answer ≤ 20,000), reply_to_id (→ assistant_messages RESTRICT, NULL; an answer's question), mode (varchar 20 NULL: `preview` / `sourcetrace`), connector (varchar 40 NULL; the implementation's `name`), outcome (varchar 20 NULL: `answered` / `no_match` / `failed`), error_family (varchar 40 NULL: `unavailable` / `timeout` / `rejected` / `protocol` / `scope` / `error`), duration_ms (integer NULL), scope_info (jsonb NULL; on a question: kind, case_id, include_related, focus_cases, filings_passed, truncated — ids and counts, no text), citations (jsonb NULL; on an answer: a list of `{document_id, order_id?, case_id, source_kind, page?, passage? (≤ 1,000), rank?, related}`), model_info (jsonb NULL; the connector's own engine or model label verbatim; preview `{"engine": "postgresql_full_text", "match": "all" / "any"}`), response (jsonb NULL; SourceTrace's answer verbatim, never shown), created_at | CHECKs: `ck_assistant_messages_role_shape` (`(role = 'user' AND reply_to_id IS NULL AND mode IS NULL AND outcome IS NULL) OR (role = 'assistant' AND reply_to_id IS NOT NULL AND mode IN ('preview', 'sourcetrace') AND outcome IN ('answered', 'no_match', 'failed'))`); `ck_assistant_messages_failure` (`(outcome = 'failed') = (error_family IS NOT NULL)`); `ck_assistant_messages_length` (`role <> 'user' OR char_length(content) BETWEEN 3 AND 2000`). Partial unique `ix_assistant_messages_reply_to` (reply_to_id) WHERE reply_to_id IS NOT NULL (one answer per question). Index `ix_assistant_messages_conversation_created` (conversation_id, created_at) replaces `ix_assistant_messages_conversation_id`. Trigger `aslms_forbid_change` (`assistant_messages_append_only`); `aslms_app` SELECT / INSERT only. Written only by `services/assistant.py`. Never holds note text, internal documents or secrets (design `assistant`). |

No new `ref_*` code set, no new function (`assistant.use` exists; its description becomes "Ask the Case
Assistant about cases and court orders" in `PERMISSION_LABELS`; seed refreshes labels). `assistant_messages`
joins `APPEND_ONLY_TABLES` and stays in `CASCADE_TABLES`.

Migration 0024 steps:
1. Guard: stop if any `assistant_messages` row exists (nothing has ever written one, and the CHECKs assume an empty
   table).
2. `ALTER TYPE assistant_scope ADD VALUE IF NOT EXISTS 'my_cases'`.
3. Add the `assistant_messages` columns, the CHECKs, the partial unique index; swap the indexes; add the trigger;
   `REVOKE UPDATE, DELETE ON assistant_messages FROM aslms_app`.
4. Add `ck_assistant_conversations_case_scope`; swap the user index.

Downgrade: stop if `assistant_messages` has rows or a conversation has scope `my_cases`. Otherwise drop what steps
3 and 4 added and restore the grants and indexes. The enum value `my_cases` stays (Postgres cannot drop it;
recorded).

## Services
`backend/aslms/integration/sourcetrace/connector.py` (additions; frozen dataclasses):
- `CaseContext` (`case_id`, `cnr`, `case_no_text`, `filing_no_text`, `court`, `bench`, `case_type`, `year`,
  `status`, `parties: tuple[str, ...]`, `advocates: tuple[str, ...]`, `acts: tuple[str, ...]`,
  `last_hearing_date`, `next_hearing_date`). Court-public fields only.
- `AskScope` (`kind: Literal["case", "my_cases", "research"]`, `focus: tuple[CaseContext, ...]`,
  `orders: Literal["focus", "focus_and_related", "all"]`, `filings: tuple[FilingRef, ...]`, `truncated: bool`).
  `FilingRef` is (`document_id`, `reference`): the document id in preview, the `sourcetrace_ref` in sourcetrace.
- `Turn` (`question: str`, `answer: str`).
- `AskRequest` (`request_id: uuid.UUID`, `question: str`, `scope: AskScope`, `history: tuple[Turn, ...]`).
- `Citation` (`reference: str`, `document_id: uuid.UUID | None`, `page: int | None`, `passage: str | None`,
  `related: bool`, `locator: dict | None` (SourceTrace's own, verbatim)).
- `Answer` (`text: str`, `citations: tuple[Citation, ...]`, `outcome: Literal["answered", "no_match"]`,
  `info: dict`, `raw: dict | None`).
- `AssistantConnector` protocol; `SourceTraceProtocolError(SourceTraceError)`.
- `__init__.py` exports them. `get_connector` is unchanged. A `get_assistant_connector(settings)` returns `None`
  until row 36.
- `fake.py`: `FakeSourceTrace` gains `ask(request)`. It records `asked`, answers from a scripted list of `Answer`s
  or outcomes (`ok`, `unavailable`, `rejected`, `timeout`, `bad_answer`, `out_of_scope` (a citation to a reference
  not in the scope), `error`), and by default answers citing the first filing or a given reference. Tests only.

`backend/aslms/services/assistant_sources.py` (new; pure SQL builders, no connector import):
- `court_order_condition(*, focus_case_ids=None, exclude_case_ids=None)` and
  `court_filing_condition(session, user, *, focus_case_ids=None)` (decision 6, reusing the parts of
  `sourcetrace_ingest.nature_condition`, which is split into `order_nature()` and `filing_nature()` with no change
  in behaviour).
- `focus_cases(session, user, scope, case)` returns `(case_ids, truncated)` (decision 5).
- `filing_allow_list(session, user, focus_case_ids, mode)` returns `(refs, truncated)`.
- `case_contexts(session, case_ids)` returns `list[CaseContext]` (court-public columns only).
- `assert_citable(session, user, document_id, scope_refs)` re-checks one citation (decisions 8 and 12).

`backend/aslms/services/assistant_preview.py` (new): `PreviewConnector(session_factory, settings)`, name
`preview`, `async ask(request)` (decision 7). It runs its SQL in a session of its own (read-only, `SET LOCAL
statement_timeout`) through `asyncio.to_thread`. It searches only `document_text` of documents that satisfy the
nature conditions again and are in the request's order corpus or filing allow-list. It imports no model library;
a unit test checks its imports.

`backend/aslms/services/assistant.py` (new; with the preview module, the only service importing the connector
apart from `sourcetrace_ingest`):
- `AssistantConfig.from_settings`, `assistant_state(settings)`, `assistant_connector(settings, session_factory)`
  (decision 2).
- `status(session, user, settings)` returns the mode, state, label, limits and `used_last_hour`.
- `async ask(Session, actor, user, *, question, scope, case=None, conversation_id=None, include_related=True,
  connector, config)` (decisions 5, 6, 9, 10, 12). It returns `(conversation, question_msg, answer_msg)`. Refusals
  before storing raise `AssistantOff`, `BadQuestion`, `ConversationFull`, `QuestionInFlight`, `AssistantLimit`
  (with `retry_after`), or `NotVisibleCase` (404). A conversation id of another user is 404. A scope or case
  different from the conversation's is 422 `scope_mismatch`. Connector failures are stored as an answer with
  outcome `failed` and returned, not raised.
- `conversations(session, user, *, scope=None, case=None, limit, offset)` returns `Page` (own only; case scope
  filtered by current sight).
- `conversation(session, user, conversation_id, *, before=None, limit=50)` returns the conversation with its
  messages, filing citations re-checked (decision 8).
- `court_order_view(session, actor, user, order_id, message_id)` and `court_order_file(...)` (decision 11; audit
  `assistant.court_order_opened`).
- `check(session)` returns two counts: stored citations naming a document that is not an order or court filing,
  is a note attachment, internal, admin or cause-list document, or is private; and conversations with a case scope
  but no case. Both must be 0.

`services/sourcetrace_ingest.py`: `nature_condition` split as above (pure refactor, same SQL).
`services/preflight.py`: the `ASSISTANT_MODE` rule (decision 7): ERROR for `preview` in prod; WARNING for
`sourcetrace` while `connector_state` is not `ready`.
`services/access_seed.py`: the `assistant.use` description only.
`core/config.py`: the settings under Jobs.

## API
New router `api/routers/assistant.py`; errors are `{code, message}` as elsewhere; 429 adds `retry_after` and
`Retry-After`. Every endpoint needs **`assistant.use`** (`Permission.ASSISTANT_USE`).

- `GET /assistant/status` returns `{mode: "off" | "preview" | "sourcetrace", state: "off" | "preview" |
  "not_implemented" | "ready", banner: str | null, limits: {questions_per_hour, used_last_hour,
  question_max_chars, messages_per_conversation}, scopes: ["case", "my_cases", "research"]}`.
- `POST /assistant/ask`: body `{question: str, scope: "case" | "my_cases" | "research", case?: id | ref_no | CNR,
  conversation_id?: uuid, include_related?: bool = true}`. 200 with `{conversation: ConversationOut, question:
  MessageOut, answer: MessageOut}`. A connector failure is still 200, with `answer.outcome = "failed"` and
  `answer.error: {family, message}`.
  - Errors: 503 `assistant_off`; 422 `bad_question` / `scope_mismatch`; 404 (case not visible, conversation not
    the caller's); 409 `question_in_flight` / `conversation_full`; 429 `assistant_limit`.
  - Visibility: case scope needs `can_view_case`. Filings follow `document_visible_condition`. Court orders follow
    decision 3.
- `GET /assistant/conversations?scope=&case=&limit=20&offset=0` returns `{total, items: [{id, scope, case:
  {id, ref_no, case_no_text}?, title, last_message_at, created_at, message_count}]}`. The caller's own only. Case
  conversations of cases no longer visible are left out.
- `GET /assistant/conversations/{id}?before=&limit=50` returns `{conversation, messages: [MessageOut], has_more}`.
  - `MessageOut` = `{id, role, created_at, content | null (hidden), hidden_reason?, mode?, outcome?, error?,
    reply_to_id?, citations: [CitationOut]}`.
  - `CitationOut` = `{document_id, order_id?, case: {id?, case_no_text, cnr, visible: bool}, source_kind,
    doc_type_label, doc_date, order_no?, page?, passage | null, related, available: bool, open: {kind: "document"
    | "court_order", href}}`.
  - 404 when the conversation is not the caller's, or is a case conversation whose case they can no longer see.
- `GET /assistant/court-orders/{order_id}?message={answer_id}` returns `{order: {id, order_no, order_date, kind,
  judge}, case: {cnr, case_no_text, filing_no_text, court, bench, case_type, year, status, parties, advocates,
  acts, last_hearing_date, next_hearing_date}, case_visible: bool}`. 404 unless the order is in the court-order
  corpus and cited in the caller's answer `message`. Audited (decision 11).
- `GET /assistant/court-orders/{order_id}/file?message=&disposition=inline|attachment` serves the PDF (as the
  documents file route; `inline` only for PDF). Same rule, audited.
- Changed: `GET /me` adds `assistant_mode: "off" | "preview" | "sourcetrace"` (the state reduced: `off` and
  `not_implemented` become `off`), so the portal shows the tab and the sidebar entry without another call.

CLI `aslms assistant`:
- `status`: the mode, the state and the counts of conversations and questions in the last 24 h.
- `ask --user EMAIL (--case REF | --my-cases | --research) [--no-related] [--conversation ID] [--json] "question"`:
  runs `ask` as that user, with their visibility. The conversation is stored under the user with `model_info.via
  = "cli"`. The audit actor is the system actor `cli` with `after.as_user_id`. Refused in `APP_ENV=prod` (exit 2).
  It prints the answer, the citations with page and excerpt, and the outcome.
- `check`: the two counts of `assistant.check`; exit 1 when either is not 0.

## Jobs
None. Questions are answered in the request, because a person is waiting.

Settings (`core/config.py`, `.env.example`; no secrets):
- `ASSISTANT_MODE=off` (`off` / `preview` / `sourcetrace`);
- `ASSISTANT_QUESTIONS_PER_HOUR=30` (1–500);
- `ASSISTANT_QUESTION_MAX_CHARS=2000` (100–2000);
- `ASSISTANT_MESSAGES_PER_CONVERSATION=200`;
- `ASSISTANT_TIMEOUT_SECONDS=45`;
- `ASSISTANT_HISTORY_TURNS=6`;
- `ASSISTANT_MAX_FOCUS_CASES=1000`;
- `ASSISTANT_MAX_FILING_SOURCES=1000`;
- `ASSISTANT_PREVIEW_PASSAGES=8`;
- `ASSISTANT_PREVIEW_SQL_MS=8000`.

## Tests
Unit (`tests/unit/`):
- `test_assistant_state_by_mode_and_env`:
  - off → None;
  - preview in dev and test → preview;
  - preview in prod → off;
  - sourcetrace → `not_implemented`, None;
  - never the fake.
- `test_preflight_refuses_preview_in_prod` and `test_preflight_warns_sourcetrace_not_ready`.
- `test_preview_imports_no_model_library`: `assistant_preview.py` imports nothing outside the standard library,
  SQLAlchemy and `aslms`.
- `test_only_listed_modules_import_the_connector`: the allow-list gains `services/assistant.py`,
  `services/assistant_preview.py` and `cli/assistant.py` (replaces the ingest-only test).
- `test_preview_answer_text_is_the_fixed_template`.
- `test_fake_ask_records_and_follows_its_script`.
- `test_case_context_has_only_court_public_fields`: no owner, custody, stage, notes or ref_no.
- `test_nature_condition_split_is_unchanged`: the same SQL as before the split.

Database (`tests/db/test_assistant.py`, seeded order text through `document_text`, the `world` fixture):
- `test_preview_case_scope_returns_cited_passages_with_page`: a two-page order with the word on page 2 gives
  page 2, a `[[ ]]` excerpt and `mode` preview.
- `test_preview_falls_back_to_any_word_for_case_scope_only`: research does not fall back.
- `test_preview_stop_word_question_is_no_match`.
- `test_preview_never_reads_notes_attachments_internal_admin_or_causelists`: a note, an attachment, an internal
  upload, an admin document and a cause-list PDF all hold the word; none is cited.
- `test_private_filing_never_in_corpus_even_for_its_office`.
- `test_archived_order_and_filing_never_cited`.
- **`test_other_department_finds_and_opens_court_order_by_research`**: department B's officer asks in research
  scope.
  - Department A's court order is cited.
  - `GET /assistant/court-orders/{id}?message=` returns 200 with the public facts and `case_visible` false.
  - `/file` serves the PDF.
  - Each opening writes `assistant.court_order_opened`.
- **`test_other_department_never_gets_notes_uploads_or_remarks`**: the same officer, with A's case holding a
  matching note, a `case_scope` court filing, an internal upload and a custody remark containing the word.
  - Only the court order is cited.
  - `GET /documents/{filing}` and `/file` are 404.
  - The court-record view carries no owner, custody, stage, notes or documents.
  - `GET /cases/{A's case}` is 404.
- `test_case_scope_related_orders_from_other_cases_marked_related`.
- `test_court_filing_follows_document_visibility`: counsel sees `counsel_shared` and not `case_scope`; another
  department never sees either.
- `test_court_order_view_needs_a_citation_in_own_message`: 404 without `message`, with another user's message, or
  with a message that does not cite the order.
- `test_case_scope_needs_case_sight`: 404 for an invisible case; a `recommended` sight is enough.
- `test_my_cases_scope_covers_allotted_file_and_claimed`.
- `test_question_and_answer_audited_without_text`: `assistant.asked` and `assistant.answered` with digests; the
  question text appears in no `audit_log` row.
- `test_conversation_private_to_its_user`: another user, the super admin and the Auditor get 404 or 403.
- `test_messages_append_only`: UPDATE and DELETE raise; DELETE of a conversation is refused for `aslms_app`.
- `test_rate_limit_429_with_retry_after`, `test_question_in_flight_409`, `test_conversation_full_409`,
  `test_bad_question_length_422`.
- `test_off_mode_refuses_before_storing`.
- `test_reread_hides_answer_when_filing_no_longer_visible`: the filing is narrowed or archived, or the user is
  moved, so the citation shows unavailable and the text is hidden; court-order citations stay.
- `test_case_conversation_unreadable_after_losing_case_sight`.
- `test_sourcetrace_path_with_fake`: a scripted answer maps citations by reference; the scope sent holds only the
  allow-listed filing refs and `orders` as expected; history of 6 turns; no note text anywhere in `fake.asked`.
- `test_sourcetrace_out_of_scope_citation_withholds_answer`: outcome `failed`, family `scope`.
- `test_sourcetrace_unavailable_retried_once_timeout_not`, `test_rejected_and_bad_answer_stored_as_failed`.
- `test_preview_sql_timeout_is_failed_timeout`: a small `ASSISTANT_PREVIEW_SQL_MS` and `pg_sleep` through a hook.
- `test_merge_repoints_conversations` (existing `case_dedupe` behaviour, now with messages).
- `test_migration_0024_guard_up_down`.
- `test_cli_ask_refused_in_prod_and_prints_citations`.
- `test_check_counts_zero`.

API (`tests/db/test_api_assistant.py`):
- `test_endpoints_need_assistant_use`: the Auditor gets 403 on every route.
- `test_status_and_me_assistant_mode`.
- `test_ask_and_read_back_shapes`.

Portal (`frontend/src/components/assistant/*.test.tsx`):
- the tab and the entry show only with `assistant.use` and a mode other than off;
- the preview banner and badge;
- one primary (Ask);
- suggested chips fill the composer;
- citations open the right href (document route with `#page=`, court-order view for an invisible case);
- hidden answers in words;
- Copy to note fills `NoteDialog`;
- error codes in words.

`uicheck` fixtures for `/assistant`, `/cases/[ref]/assistant` and `/assistant/orders/[id]`.

## Verification
1. `ruff check` clean; `pytest -q` green; `npm test`, `npm run lint` and `npm run build` in `frontend/` green.
2. On a scratch database: `alembic upgrade head` (0024), then downgrade and upgrade again. On the dev database,
   the integrator's `migrate` step only, after the merge.
3. With `ASSISTANT_MODE=off`, `aslms assistant status` shows `off`, and `POST /assistant/ask` answers 503
   `assistant_off`.
4. With `ASSISTANT_MODE=preview`, `APP_ENV=dev`, and a dev case with extracted order text:
   - `aslms assistant ask --user <a department officer> --case <CNR> "next date"` prints at least one citation
     with a page and an excerpt, and the fixed preview line;
   - the same with `--research "regularisation"` cites orders of other departments' cases;
   - `SELECT action, count(*) FROM audit_log WHERE action LIKE 'assistant.%' GROUP BY 1` shows `asked` and
     `answered` equal to the questions asked.
5. `aslms assistant check` returns 0 and 0, exit 0.
6. `APP_ENV=prod ASSISTANT_MODE=preview aslms ops preflight` reports the ERROR line and exits non-zero.
7. Owner's browser check at 375, 768 and 1280 px:
   - the case page Assistant tab, with the banner, a suggested question, an answer and a source opening at its
     page;
   - the sidebar Assistant, with an "All court orders" question citing an order of a case the owner's test login
     cannot open, which opens the court-record view;
   - Copy to note.
8. The SourceTrace path is proven by the fake-backed tests until row 36.

## Open questions
None that block this item: every point it builds is decided above.

**Questions for SourceTrace, carried to row 36** (they do not block this item; never answered by invention):
- S1. The query endpoint, authentication, request and response shape, timeouts and rate limits, and whether
  answers can stream.
- S2. Can a query be restricted to (a) every document with `source_kind = court_order` plus (b) an explicit
  allow-list of references (the filings)? If not, the recommendation is that sourcetrace mode sends court orders
  only and leaves filings out, rather than risk another department's filing.
- S3. What a citation carries: the reference or `external_id`, a page number, a passage or offsets. Do Acts, rules
  and policies citations have a stable identifier and section label to show as text?
- S4. Does SourceTrace accept conversation history, or must the portal fold it into the question?
- S5. Does SourceTrace keep the questions it receives, for how long, and can that be switched off? The owner
  should know before going live.

**Owner checks at approval** (decided here, reversible):
- decision 3: court orders of every case open to every assistant user, standing counsel included (owner's
  decision, recorded as a deviation from documents-uploads decision 7, limited to the assistant paths);
- decision 4: department uploads, court filings included, stay under normal document visibility, and private
  filings are never in the corpus (owner confirmed);
- decision 7: preview refused in prod;
- decision 8: no user delete of conversations, and retention follows DB_STANDARD §6;
- decision 9: 30 questions an hour per user;
- decision 11: a court order of a case the user cannot see opens only from a citation in their own answer;
- decision 15: the item may be split into a backend and a portal row.

## Deviations
Recorded by the developer while building (24 Oct 2026); none changes a decision above.
1. **Branch base and migration number.** `feature/assistant` starts at the tip of `feature/court-data-freshness`
   (row 122, `76840ad`), so `0024_assistant.py` revises 0023 as this note says. Row 122's work is untouched. If row
   122 merges after this branch or changes its migration, the integrator rebases and keeps 0024 after 0023.
2. **Autogenerate.** The dev database is at 0022, and autogenerate needs the head, so 0024 was autogenerated against a
   scratch database upgraded to 0023 (created and dropped by the developer), then reviewed: CHECKs, the trigger, the
   grants and the enum value are written by hand. Up, down and up again on the scratch database leave no difference
   from the models.
3. **Step order of 0024.** `ALTER TYPE assistant_scope ADD VALUE 'my_cases'` runs last, in an autocommit block, as
   0017 and 0023 do (the value is not used inside the migration); the guard, the columns, CHECKs, indexes, trigger and
   grant follow the note's steps 1, 3 and 4.
4. **`case_contexts`.** `services/assistant_sources.py` must not import the connector (the import allow-list of the
   tests), so `case_contexts` returns dictionaries with exactly `CaseContext`'s fields and `services/assistant.py`
   builds the `CaseContext`s. A case's `parties` and `advocates` fall back to the printed summaries when the dossier
   rows are absent.
5. **`Citation.rank`.** The connector's `Citation` gains `rank: float | None` (the preview's `ts_rank`), stored as the
   citation's `rank`.
6. **`ask` returns ids.** `services/assistant.ask` returns an `AskResult` (conversation, question and answer ids and
   the stored outcome) instead of ORM objects; the router and the CLI read the messages back through
   `assistant.message`, which applies the reading rules of decision 8.
7. **Merges hold conversations back.** `case_dedupe` does not re-point conversations: a provisional case with a
   conversation is one with a portal record, so it is listed for review and not merged (data-load-console decision
   14, unchanged). The test is `test_merge_holds_back_a_provisional_case_with_conversations`.
8. **Extra ids in records.** `scope_info` also records `orders` (`focus` / `focus_and_related` / `all`); `assistant.asked`
   adds `via` with `as_user_id` for the CLI; `assistant.answered` adds `conversation_id` and `attempts`. No text.
9. **One question of a user at a time.** Transaction A also takes a transaction-scoped advisory lock per user
   (`pg_advisory_xact_lock`, allowed under PgBouncer transaction mode), so two questions in two conversations cannot
   both pass the hourly count.
10. **Failed answers.** A failed answer's `content` (NOT NULL) holds its explanation in words, and `MessageOut.error` is
    `{family, message: content}`; the portal shows its own words per family (`ASSISTANT_FAILURES`). A preview
    question of only stop words answers "Use more specific words: every word of the question is too common to search."
    after the preview line.
11. **`CitationOut`.** `open` is null for an unavailable source. `open.href` is an API path: the file route for kind
    `document` (the portal adds its relay prefix and `#page=N` for a PDF), `/assistant/court-orders/{id}?message=` for
    kind `court_order` (the portal opens `/assistant/orders/[orderId]?m=`). `case.id` is given only when the reader can
    open the case. A court order of a visible case opens the ordinary order file route only when the reader also holds
    `documents.view`; otherwise the court-record view.
12. **Preview passage choice.** Within the 8-passage limit the preview takes the best page of every document first
    (focus, then related), then the second pages, so related orders are not crowded out by the focus documents.
13. **Preflight** reads the assistant's state (`services/assistant.assistant_state`) rather than importing the
    connector, for the same import rule.
14. **Setting bounds** (the note gives defaults only): messages per conversation 2–2,000, timeout up to 300 s, history
    0–50 turns, focus cases and filing sources up to 10,000, preview passages 1–50, preview SQL 100–60,000 ms.
15. **Portal.** Ask is the one primary of the Assistant page; on the case tab it is secondary, because the case
    header holds the case's primary (as the note composer on the case page). Suggested chips fill the question box
    without asking. Switching the scope asks the last question again in that scope's open or latest conversation (a
    new one when there is none). "Copy to note" writes dates as the portal does elsewhere ("Order of 12 Mar 2026, No.
    5, page 2") and `NoteComposer` / `NoteDialog` gain `initialBody`. The conversation box stays mounted while a
    conversation loads.
16. **`uicheck`.** The route list carries no query string, so the court-record view is also checked as an interaction
    state with `?m=`; the fixtures' `/me` has `assistant_mode: "preview"` so the tab and the page render.

**Review fixes (24 Oct 2026).** Recorded by the developer while fixing the reviewer's findings 1 to 8 and 11; each
has its test in `tests/db/test_assistant.py`.

17. **An unavailable source names nothing** (finding 2). A court filing the reader can no longer see comes back with
    `available: false`, the new `unavailable_reason` "This source is no longer available." and every field that
    names it null: no `document_id`, `order_id`, type, date, order number, page, excerpt, case number, CNR or case
    id, `related` false, `open` null. Only `source_kind` stays, so the answer is still hidden by decision 8. The
    portal shows only "This source is no longer available to you" for it.
18. **Court-order citations are re-checked too** (finding 1). On every read a court-order citation is still shown
    only while its document is in the court-order corpus (`assistant_sources.court_order_documents`: the order
    nature, not archived, an order of a case that is not merged), the cited order still points at that document and
    the order's case is not merged. Otherwise it is unavailable as in 17; it does not hide the answer (decision 8
    hides answers only for filings). This refines decision 8's "court-order citations stay shown".
19. **The order link follows the membership** (finding 8). Deviation 11's ordinary order file route is offered only
    when a membership that itself holds `documents.view` sees the order's case (the route's own per-membership
    document rule); otherwise the court-record view. The login's union of functions no longer decides.
20. **One unanswered question per user** (finding 3). Decision 9's in-flight rule now counts every conversation of
    the user, not only the one asked in: while any question of the user has no answer and was created within
    `ASSISTANT_TIMEOUT_SECONDS + 15` s, a question in any conversation, a new one included, is refused with 409
    `question_in_flight` (the existing code). The check runs under the per-user lock of deviation 9.
21. **The case is refused before it is looked up** (finding 6). `POST /assistant/ask` answers 422 `scope_mismatch`
    for a `case` given outside the case scope before any lookup. A case that exists but is not visible answers
    exactly like an unknown one (404 `not_found`, "no such case"), and the service checks the case before it reads
    the question, so a bad question cannot tell them apart either.
22. **Control characters are refused** (finding 11). A question holding NUL or another control character (C0 other
    than tab, line feed and carriage return, DEL, C1) is refused with 422 `bad_question` and `reason`
    `control_characters`, before anything is stored; the portal words it apart from the length rule.
23. **No question text in logs** (finding 7). An unexpected connector failure logs one line with the exception's class,
    the conversation id and the question's digest (sha256 and length), with no message and no traceback.
24. **The preview's time is one budget** (findings 4 and 5). The whole search has `ASSISTANT_TIMEOUT_SECONDS` less a
    margin of 2 s (at most a quarter of the limit); before every statement the budget is checked and
    `statement_timeout` is set to the smaller of `ASSISTANT_PREVIEW_SQL_MS` and what is left. When the service's
    wait gives up, a flag stops the search before its next statement. The related orders of the case scope use the
    all-words query only (never the any-word fallback), run last in a savepoint of their own, and their timeout,
    a spent budget or a database error drops only them: the focus answer stands and `model_info.related` is
    `dropped`.

### Left for later
- **Finding 9, the SourceTrace citation mapping** (`_map_citations` by `sourcetrace_ref`): settled with the real
  connector in row 36, once SourceTrace's citation shape is known (question S3).
- **Finding 10, the CLI `ask --user` check**: the CLI is for development only and refused with `APP_ENV=prod`; the
  check of the named login is left as it is.
