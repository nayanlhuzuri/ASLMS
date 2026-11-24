# Design: Meaning search in the portal (research index, round 2)

```
slug: research-index-portal
status: approved
author: architect
date: 2026-11-24
approved_by: owner on 2026-11-24
```

## Context
Backlog row 275 (owner, 23 Nov 2026), added when row 251 `research-index` was approved. This is round 2 of that row,
as `docs/design/research-index.md` decision 4 sets it out. The owner asked for this design on 24 Nov 2026. In the
build order of 23 Nov 2026 it comes straight after row 251 and before row 274 `home-page`.

**What the row asks for:**
- the Research Index section on Data Collection: coverage, the live model key, and the chunks still waiting or failed;
- the server-side filters of row 251 decision 20 on All Court Orders and My Cases: order forms, substantive only,
  outcomes, Outcome Against the State (Read by Rule), cites, act, and from and to dates;
- the passage view of a cited order, with the exact passage highlighted;
- the "Text Has Changed" note on an old citation;
- the styling of the notes about removed sentences;
- uicheck at 375, 768, 1024 and 1280 px.

The row says frontend only, with no migration.

**What row 251 built and merged** (24 Nov 2026, tag `feature/research-index-done`). Row 251's deviation 12 touched the
frontend only for audit-screen text, and no screen shows any of this yet:
- **`GET /assistant/status`** gains `research: {state: off | building | ready | unavailable, coverage}`. The coverage
  is cached for 60 s and read in under 2 s. When that count runs out of time, the server answers `building` with
  `coverage: null` (row 277, advisory 17).
- **`POST /assistant/ask`** takes `filters: {forms, substantive_only, outcomes, against_state, cites, act, from, to}`
  for `my_cases` and `research` only. The refusals are:
  - 400 `filters_not_allowed` for any other scope;
  - 400 `filters_unavailable` whenever the index will not serve the question (switch off, or preview mode; row 251
    deviation 18);
  - 400 `bad_filter` for an unknown outcome or act key, a citation over 80 characters, or `from` after `to`.

  Filters are stored on the question in `scope_info.filters`, but the thread API does not return them yet.
- **Answers.** `checks` carries `{sentences, kept, removed: {uncited, quote, date, number, case_no, name, outcome},
  withheld}`. `retrieval` carries `{kind: hybrid | words_only | words, reason, …}`. When sentences are removed, the
  answer text ends with the server's line "[Removed by ASLMS: n sentences whose quotes, dates, numbers, case numbers,
  names or outcomes were not found in the records they cite.]". A withheld answer is `NO_ANSWER_TEXT` with outcome
  `no_match`.
- **Court-order citations found through the index** carry `src`, `paragraphs`, `quotes: [{src, page, exact}]`,
  `match`, `same_words_in` and `text_changed`. `text_changed` is computed when the answer is read.
- **`GET /assistant/messages/{id}/sources/{label}/passage`** (`assistant.use`, own answers only, 404 otherwise)
  returns `{order_id, document_id, page, page_count, page_text, highlights: [{start, end, kind: passage | quote,
  exact}], text_changed}`. It gives no offsets when the text has changed.
- **`GET /admin/data-health`** (`reports.state`, `admin.napix_refetch` or `admin.masters_sync`) gains
  `research_index`: `enabled`, `live_model_key`, `readiness` (`off | ready | held | unavailable`), `chunks {order_body,
  case_sheet, total}`, `vectors_live`, `waiting`, `coverage`, `other_keys`, `failures_open`, `last_run`,
  `last_reconcile`, `table_sizes` and `timed_out` (`counts`, `sizes`).
- **System Health** gains the check `research_model` ("Research Index Model"), labelled by the server. The portal
  already draws every check from the server's list.
- `enumLabels.ts` lists the new enums under `NOT_SHOWN`, with "round 2" reasons. `messages.ts` has the audit action
  name "Research Index Rebuilt".

**The screens it extends:**
- the Assistant page `/assistant?tab=my-cases|court-orders` and the case Assistant tab, both in
  `frontend/src/components/assistant/Assistant.tsx` and `lib/assistant.ts`;
- the Source dialog and the Sources dialog;
- the court-record view `/assistant/orders/[orderId]?m=` in `CourtOrderView.tsx`;
- Data Collection's Overview tab in `components/data/Overview.tsx`;
- Problems and Fixes' Recorded Problems, which already reads `/admin/data-health`.

**Not covered** (stated so nobody widens it):
- any change to retrieval, the checks, the job or the CLI (row 251, and its advisories in row 277);
- similar cases, summaries and precedent notes (rows 252 and 253);
- highlighting inside the browser's PDF viewer (row 251 decision 29 states this as a limit);
- filters on This Case or My Work, which the server refuses;
- a button that starts, retries or rebuilds indexing from the portal (the CLI stays the operator's tool);
- the two Word guides (row 276, which runs after deploy);
- any NAPIX call;
- anything sent to a model: these screens only draw what the server returns.

## Decisions

### A. Scope

1. **Round 2 is the portal plus two small read-only API additions. This is a deviation from the row's "frontend
   only".**
   - The screens need two things row 251 did not build:
     - (a) the filters a past question was asked with, so the thread can show them (decision 9);
     - (b) a list to pick an act and a cited judgment from, because the server matches both exactly: an `act_key` is
       a normalised printed name such as `assam land revenue regulation 1886`, and `cites` must equal a stored
       citation (decision 10).
   - Both additions are read-only, additive and court-public. They add no table, no column, no migration, no setting,
     no job and no function.
   - *Alternatives:*
     - no act field, with the act typed into the question (rejected: the owner listed the act filter, and row 251
       decision 20 rejected filters as words in the question);
     - free text only, normalised in the portal (kept only as the fallback in decision 10: a typed act without its
       year matches no key, and the officer would get `bad_filter` with no way to find the right name).

2. **Where each piece lives:**
   - the filters, the research notice and the per-answer hints are on the Assistant page's My Cases and All Court
     Orders tabs;
   - the passage view, the "Text Has Changed" note and the check notes are on every answer that carries them, on the
     page and on the case tab alike;
   - the passage view is also on the court-record view;
   - the Research Index section is on Data Collection → Overview;
   - nothing changes on System Health (decision 20).

### B. The research state on the Assistant

3. **Filters and research notices only when the index serves the question.**
   - They show when all of these hold:
     - `status.mode` is `ollama`;
     - `status.research.state` is not `off`;
     - the tab is My Cases or All Court Orders.
   - **This mirrors the server's own rule (deviation 18):** filters are accepted when the switch is on in ollama mode,
     even when the embedding model is `unavailable`, because the question then runs as words over the index and keeps
     its filters. So `building`, `ready` and `unavailable` all show the filters.
   - **The case tab is unchanged.** It is This Case only, and the server refuses filters there.
   - *Alternative:* showing the filters always and letting the server refuse them (rejected: an officer would fill in
     a panel that can only fail).

4. **The research notice: one sentence, chosen by the state.**
   - It sits under the readiness notice on the two tabs. Its words live in `T.assistant.research`:
     - **`ready`:** no notice. Meaning search is the normal case.
     - **`building` with a coverage:** a hint line (not a banner): "The meaning search is still being built:
       {pct} of court orders are in it so far. Orders not yet in it are found by their words." `pct` is a whole
       percent, or "under 1%".
     - **`building` with `coverage: null`:** this is the count that ran out of time (row 277, advisory 17). The same
       hint style says: "The meaning search is on. How much of it is built could not be read just now; orders not yet
       in it are found by their words."
       - The screen never shows a percent, 0% or "ready" for this state. It never calls the index unavailable.
       - If row 277 later gives this state its own value, the enum-label guard (decision 21) fails until the value is
         mapped to this same sentence.
     - **`unavailable`:** a warning `Notice`: "The meaning search is not available right now, so answers are found by
       their words only. Filters still apply."
   - The state stays `NOT_SHOWN` in the label registry, because it chooses a sentence and is never printed as a word.
   - *Alternative:* a coverage bar for every officer (rejected: progress detail belongs to Data Collection; officers
     only need to know whether the answer may miss recent material).

5. **Per-answer hints:**
   - **`retrieval.kind = words_only`:** under the answer, a hint: "Found by words only this time: the meaning search
     did not answer in time." `hybrid` and `words` add nothing (`words` means the switch is off, as before).
   - **`same_words_in > 0`:** on the source, in the lists and the dialog, a muted line: "The same words are in n other
     orders." (Shared bodies are shown once, under the newest order: row 251 decision 18.)
   - **`match`** (words, meaning or both) is not shown. It is a verification detail, and `aslms research-index search
     --explain` prints it. It stays `NOT_SHOWN`.
   - *Alternative:* a "Matched by Meaning" badge on each source (rejected: it adds a word officers cannot act on).

### C. The filters

6. **A "Search Filters" panel above the question box. It uses Filter Layout B's field grid and summary strip, but not
   the whole `FilterCard`.**
   - **Why not the whole card:** Filter Layout B's left zone is a list page's one leading control, and the Assistant's
     leading control is the question box, which stays where it is under the conversation. Moving it into a 280 px
     zone would break the composer. This is a recorded variation of the pattern, not of a rule.
   - **The row:** above the composer sits one row with the secondary button "Search Filters" (or "Search Filters (n)"
     when n fields are set, `aria-expanded`), and the line "Filters apply to each question you ask on this tab."
   - **The panel** opens under that row, with the kit's 220 ms open, at once under reduced motion.
     - It is a size container with Filter Layout B's grid: `repeat(auto-fill, minmax(180px, 1fr))`, labels above
       the boxes.
     - Its fields mount on first opening and stay mounted, out of the tab order while closed (the `FilterCard` rule).
   - **The applied filters** show under the row as the kit's `FilterChips`, with Clear All, whether the panel is open
     or not. So the officer always sees what will narrow the next question.
   - **There is no Search button.** Ask sends the question with the filters in view. The page keeps its one primary,
     Ask.
   - **On phones** the grid stacks into one column, and the chips wrap.

7. **The fields** (Title Case labels; values worded from `messages.ts`):

   | Field | Control | Sends |
   |---|---|---|
   | Order Form | three check boxes in a group: Judgment, Final Order, Interim Order | `forms` |
   | Substantive Orders Only | one check box; hint "Leaves out adjournments and other procedural orders." | `substantive_only: true` |
   | Outcome | six check boxes in a group: Allowed, Partly Allowed, Dismissed, Disposed Of, Withdrawn, Closed (the labels of What the Order Says); hint "As read from the order's text by rules." | `outcomes` |
   | Outcome Against the State (Read by Rule) | one check box; hint "Allowed or partly allowed with the State as respondent, or dismissed with the State as petitioner. Disposed of, withdrawn and closed count neither way." (the owner's rule of 23 Nov 2026) | `against_state: true` |
   | Cites a Judgment | choice field with suggestions (decision 10), at most 80 characters | `cites` |
   | Act | choice field picked from the list (decision 10) | `act` (the key) |
   | Order Date | `DateRangeField` with the choices Any, A Date and Between Dates; From must not be after To | `from`, `to` |

   - **Checked in the portal before sending,** as the server checks them:
     - From after To shows the field error "From must be on or before To";
     - a citation over 80 characters shows "At most 80 characters";
     - Ask stays disabled while a field is in error.
   - Outcome Against the State combined with Outcome is allowed, as on the server, where the rule applies after the
     outcomes.

8. **The filters live in the address, for that tab only.**
   - The parameters are `forms=judgment,final`, `substantive=1`, `outcomes=dismissed,allowed`, `against_state=1`,
     `cites=…`, `act=…`, `from=YYYY-MM-DD` and `to=YYYY-MM-DD`, beside `tab`. Changes go through `router.replace`, as
     the list filters do.
   - Reloading or sharing the link keeps them.
   - **Changing tab drops them,** because the new tab's address has none. Filters narrow one scope, and carrying All
     Court Orders filters into My Cases would narrow a search the officer did not ask to narrow.
   - **Unknown values in the address** (an outcome not in the list, a bad date) are dropped when read. They are never
     sent.
   - **When the address holds filters but the panel is hidden** (decision 3: the switch was turned off), nothing is
     sent. A warning `Notice` says "The filters in this address are not used: the meaning search is switched off.",
     with Clear Filters.

9. **Each question shows the filters it was asked with. This needs read-only addition (a).**
   - Every question sends exactly the filters in view: `filters` is omitted when none is set, and is never an empty
     object.
   - In the thread, a question's bubble shows its filters as small read-only chips under the question text ("Judgment",
     "Against the State (Read by Rule)", "Cites (2006) 4 SCC 1", "From 1 Jan 2024"). The same chips show for older
     questions after a reload.
   - **The API addition:** `AssistantMessageOut` gains `filters`, the stored `scope_info.filters`, returned on
     question messages only (null otherwise and when none was set). The values are court-public things the asker
     typed, and the conversation is already the asker's own.
   - **An act chip** shows the act's label as picked. On a reload, where only the key is stored, it shows the key
     through the portal's Title Case helper, `lib/titleCase.ts` ("Assam Land Revenue Regulation 1886").
   - **Why this matters:** without the chips, a thread read later could not show that an answer covers only, for
     example, judgments the State lost.
   - *Alternative:* keeping the last filters in browser storage (rejected: it shows nothing for older questions, and
     nothing on another device).

10. **The act and citation fields pick from the server's list. This needs read-only addition (b).**
    - **The endpoint:** `GET /assistant/filter-choices?kind=act|cites&q=&limit=`, for `assistant.use`.
      - It returns `{kind, ready, items: [{value, label, detail, orders}]}`, built from current order readings
        (row 250's `facts.acts` and `facts.judgments`).
      - For an act, `value` is the `act_key` and `label` is its most common printed name.
      - For a cited judgment, `value` and `label` are the citation as stored, and `detail` is its most common printed
        case name ("X v. Y"), when there is one.
      - `orders` is the number of current readings that name the value.
      - The service is in decision "Services".
    - **The control** is a local `ChoiceField` in `components/assistant/ResearchFilters.tsx`. It follows the ARIA 1.2
      combobox pattern the kit's User Picker uses:
      - suggestions after 2 characters, with a 250 ms pause;
      - the arrow keys move, Enter picks, Escape closes;
      - each option reads "label · n orders", with `detail` muted;
      - an error state with Try Again, and Enter retrying only while Try Again is shown (row 186's rule).
    - **Act** must be picked from the list. A typed act that was not picked is sent as the portal's normalisation of
      the words, the same rule as row 250's `_act_key`: lower case, dots removed, every other non-letter or digit a
      space, a leading "the" dropped. If the server answers `bad_filter`, the field says "No order names this act.
      Choose one from the list."
    - **Cites** takes a pick or free text, because the server compares the citation after collapsing spaces. A hint
      says "Choose from the list for an exact match."
    - **When the list is not ready** (`ready: false`, decision "Services"), the field says "The list is being
      prepared; type the name, or try again in a minute." Typing still works as above.
    - **A limit of row 251, stated in the hint:** the server takes one act key. The same act printed two ways (with
      and without its year) has two keys, so the list shows both with their counts and the officer picks one. Row 251
      is unchanged; a several-act filter would be a later change to the request.

11. **Refusals in words** (added to `ASSISTANT_ERRORS`). In each case the question stays in the box:
    - **`filters_unavailable`:** "Filters cannot be used right now: the meaning search is switched off. Clear the
      filters to ask." The status is fetched again, so the panel hides and decision 8's notice offers Clear Filters.
    - **`bad_filter`:** "One of the filters is not recognised. Choose the act from the list and keep From on or before
      To."
    - **`filters_not_allowed`:** the portal never sends filters for This Case or My Work. If it ever comes, it reads
      "Filters are for My Cases and All Court Orders only."

### D. The passage view

12. **The Source dialog shows the cited passage on its page.**
    - **When:** for a court-order source with `src` (found through the index) that is `available`, opening its dialog
      from the marker fetches `GET /assistant/messages/{id}/sources/{label}/passage` once, cached by message and label.
    - **What it shows,** under the source's title and above "Text Given to the Model":
      - the heading "The Cited Passage" and the line "Page {page} of {page_count}, as ASLMS stored the order's text";
      - the page text in the kit's `ScrollBox`, with `white-space: pre-wrap` and no sideways scroll;
      - the highlights drawn as `<mark>`.
    - **The highlights:**
      - `passage` gets the soft emphasis ground of the navy and cream palette;
      - `quote` gets a stronger ground and an underline, so colour is never the only sign;
      - a legend line says "Shaded: the passage the answer cites. Underlined: words the answer quotes.", and shows only
        the parts present.
    - **`exact: false` on a quote:** "The quoted words were not found exactly; the whole passage is marked."
    - **On opening,** the box scrolls to the first highlight, instantly under reduced motion, without moving the
      dialog or the page.
    - **The dialog's primary** stays the existing open link: "Open the Order" (the PDF at `#page=n` in a new tab, or the
      court-record view for a case the reader cannot open).
    - **Other states:**
      - a 404 shows the muted line "The passage cannot be shown for this source.", and the rest of the dialog is
        unchanged;
      - while loading, `Loading` lines;
      - a failure shows `ErrorBanner` with Try Again.
    - **Sources without `src`** (filings, Case Details, internal records, word-search answers, older answers) keep
      today's excerpt and nothing is fetched.
    - **The passage stays out of the lists:** the "Sources (n)" list and an inline list keep today's excerpt, because
      fetching every page for every source would be several calls per answer. Each listed court-order source with
      `src` has the ghost button "Show the Passage", which opens that source's dialog.
    - The text is court-public and open to every assistant user (assistant decision 3). It is not audited, as row
      251's API section says.
    - *Alternatives:*
      - a page of its own (rejected: the dialog already holds the source, and a page would lose the conversation's
        place);
      - highlighting inside the PDF (rejected by row 251 decision 29: the browser's viewer cannot be marked).

13. **The court-record view shows the same passage.**
    - For a cited order of a case the reader cannot open, `sourceLink` adds `&s={label}` to `/assistant/orders/{id}?m=`
      when the citation has `src`.
    - `CourtOrderView` then shows a "The Cited Passage" card, using the same `PassageView` component as decision 12,
      after the Order card. Without `s`, or on a 404, there is no card.
    - The view's primary "Open the Order" is unchanged.

14. **One component.** `components/assistant/PassageView.tsx` renders `{page, page_count, page_text, highlights,
    text_changed}`:
    - overlapping highlights are split into runs, with a quote run inside a passage run getting both styles;
    - offsets are clipped to the page text;
    - it is tested on its own.

### E. Text Has Changed

15. **A citation whose order's text has changed since the answer** (`text_changed: true`):
    - **everywhere the source appears** (the lists, the Source dialog, the marker's accessible name): a warning `Badge`
      "Text Has Changed", and the line "This order's stored text has changed since this answer was written. The cited
      passage can no longer be marked; open the order and check it yourself.";
    - **in the passage view:** that notice only, with no page text and no marks. The server gives no offsets then, and
      showing the new text under an old citation would look like the cited passage;
    - **the open link stays,** so the order itself can still be read;
    - **the answer text is unchanged:** it is the record of what was answered.

### F. The check notes

16. **The removal note becomes a styled block, built from the counts.**
    - **When it applies:** the answer text's last line is exactly the server's form (`[Removed by ASLMS: ` … `]`, as
      `answer_check_rules.REMOVED_NOTE` writes it) and `checks.removed` sums to more than 0.
    - **What changes:** the portal takes that line off the text it runs the `[S#]` markers over, and draws it under the
      answer as a block (`.removed` in `assistant.module.css`: the muted ground, a left rule in the warning tone, an
      info icon):
      - the title is "ASLMS Removed {n} Sentence(s)";
      - the reasons come from the counts in words, for example "Not found in the records they cite: 1 date, 1 name.
        1 stated a fact without a source.";
      - the fixed line is "These checks cannot catch a wrong reading of correctly quoted text: check the sources."
        (owner, row 251).
    - **The reason words** are a sentence map `T.assistant.removedReasons`: uncited "stated a fact without a source",
      quote "quote", date "date", number "number", case_no "case number", name "name", outcome "outcome", with plurals
      through the portal's count helper.
    - **When the line is there but the counts are not:** the block shows the server's line as written.
    - **Copy to Note** keeps the server's line in the text it copies (a note should record that sentences were
      removed). The case tab is the only place Copy to Note appears.

17. **A withheld answer says why.**
    - **When:** `outcome = no_match` with `checks.withheld` set.
    - **What shows:** the text stays the server's `NO_ANSWER_TEXT`, and a hint is added under it:
      - first_sentence: "ASLMS held back the model's answer: its main point was not found in the records it cites.";
      - majority: "ASLMS held back the model's answer: most of its sentences were not found in the records they
        cite.";
      - none_cited: "ASLMS held back the model's answer: no sentence cited a record."
    - `AssistantChecksOut.withheld` moves from `NOT_SHOWN` to `LABELLED`, as a sentence map.
    - The existing badge "Answer Cut Short" and the line "A reference to a source that was not given was removed." are
      unchanged.

### G. Data Collection

18. **A "Research Index" section on the Overview tab, for the readers of data health.**
    - **Where:** after Month by Month, with the anchor `#research-index`.
    - **Who sees it:** logins holding `reports.state`, `admin.napix_refetch` or `admin.masters_sync` (`HEALTH_READERS`,
      the guard of `GET /admin/data-health`). A login with only `admin.data_load` does not see the section, because the
      server would refuse the data.
    - **The data:** the `research_index` block of `GET /admin/data-health`, read with the query key `["data-health"]`
      that Problems and Fixes' Recorded Problems already uses, so the two share one cached snapshot.
    - **Polling:** every 120 s while the tab is visible (`POLL.months`), and again on the tab's Refresh.
    - **When there is no block** (`research_index: null`, because the block failed), the section says "The research
      index status could not be read." with Try Again.
    - *Alternatives:*
      - a new endpoint for the block alone (rejected: the snapshot already carries it and Recorded Problems already
        reads it);
      - Problems and Fixes (rejected: coverage of a backfill is a statistic, and the Overview is where the other
        progress figures are).

19. **What the section shows.** Words are in `T.dc.research`. There is no button: indexing is started, resumed and
    rebuilt only by `aslms research-index`, runbook section 28.
    - **Status line:**
      - "Meaning Search" `Badge`: Off (`enabled` false, neutral) or On (`enabled` true, success).
      - "Model" `Badge` from `readiness`: Ready (success), Held, Not Loaded (info; "It loads at the next question"),
        Not Available (warning), Off (neutral).
      - "Live Model" with `live_model_key` in mono (`embeddinggemma:300m@85462619ee72`), or "Not Known" when null.
    - **When `enabled` is false:** one line, "The meaning search is switched off; the Assistant uses word search. Chunks
      cut so far are shown below.", and only the chunk counts.
    - **Coverage:** the kit `ProgressBar`, with `vectors_live` of `chunks.total` and the text "{pct} embedded · {n}
      waiting". It turns success at 99% or more, the server's `ready` threshold.
    - **Chunks:** a `KvList` with Order Passages (`order_body`), Case Sheets (`case_sheet`) and Waiting (`waiting`).
    - **Not embedded:** "{n} chunks could not be embedded", linking to `/data/problems#failed` when `failures_open > 0`.
      Recorded Problems names the kind `research_embed` "Research Index Embedding" (a new `recordedKinds` entry). When
      the count is 0: "None failed."
    - **Earlier models** (`other_keys`, only when there are any): a small `DataTable` of model key and vectors, under
      the line "Vectors of an earlier model. They are not used for search until the operator retires them."
    - **Runs:**
      - "Last Run": the time, the status in words, and "{embedded} embedded, {cut} chunk sets cut" from the counters;
      - "Last Full Check": the 01:45 reconcile's time and status;
      - "Not Yet" when there is no run.
    - **Space:** the table sizes in MB or GB, through a new `formatBytes` in `lib/format.ts` (KB, MB, GB, one
      decimal). The portal has no GB formatter yet, and `lib/workflow.ts`'s size-limit helper stops at MB.
    - **When counts took too long** (`timed_out` holds `counts`, the same cause as advisory 17):
      - the coverage bar and the chunk figures show "Not Known Right Now", never 0;
      - one muted line says "Some counts took too long to read and are left out; press Refresh to try again." (the
        Order Reading Checks rule of row 264);
      - `sizes` gives the same line for Space.
    - `ResearchIndexStatusOut.readiness` moves to `LABELLED` (badge words). `timed_out` stays `NOT_SHOWN`.

20. **System Health: no change.** The `research_model` check arrives in the server's list with its own label and
    facts, and the screen already draws it. Row 251's Verification 5 records it live.

### H. Labels, checks and documents

21. **Label registry** (`enumLabels.ts`):
    - **moved to `LABELLED`:**
      - `AssistantFiltersIn.forms` (`T.assistant.filters.forms`: Judgment, Final Order, Interim Order);
      - `AssistantChecksOut.withheld` (sentence map, decision 17);
      - `ResearchIndexStatusOut.readiness` (`T.dc.research.readiness`);
    - **kept in `NOT_SHOWN`, with the "round 2" wording replaced by the real reason:**
      - `AssistantResearchStateOut.state` (chooses the notice of decision 4);
      - `AssistantCitationOut.match` (decision 5);
      - `AssistantHighlightOut.kind` (chooses the mark style);
      - `AssistantRetrievalOut.kind` (chooses decision 5's hint);
      - `ResearchIndexStatusOut.timed_out`;
      - `ResearchChunkKind`, `ResearchRetireReason`.
    - **New text** follows Title Case for labels and sentences for lines. The wording guards and the source-scan guard
      run as they are.

22. **uicheck at 375, 768, 1024 and 1280 px.** Nine new routes and states, with fixtures typed against `schema.d.ts`
    in `frontend/e2e/fixtures/`:
    1. `/data/overview (research index building)`: enabled, `held`, 62% coverage, 3 failures, one earlier key;
    2. `/data/overview (research index counts timed out)`: `timed_out: ["counts"]`;
    3. `/assistant?tab=court-orders (search filters open)`: four fields set, with chips and Clear All;
    4. `/assistant?tab=court-orders (act suggestions open)`: the combobox list showing;
    5. `/assistant?tab=court-orders (answer with removed sentences)`: the removal block, a `same_words_in` line, a
       "Text Has Changed" source, the `words_only` hint, and question chips;
    6. `/assistant?tab=court-orders (source dialog with passage)`: the passage view with a passage and a quote, scrolled;
    7. `/assistant?tab=my-cases (withheld answer)`, with the `building` and `coverage: null` notice;
    8. `/assistant?tab=my-cases (meaning search unavailable)`: the warning notice, filters shown;
    9. `/assistant/orders/{id}?m=…&s=S1 (court record with passage)`.

    The existing kinds apply, including `overlap`, `text-overrun`, `tight-gap`, `split-group`, `card-row`,
    `date-wrap` and `primary` (one primary: Ask; the dialog's open link). The passage `ScrollBox` is the kit's vertical
    scroller and wraps its text, so it raises no `inner-scroll` sideways finding.

23. **Documents** (the scribe):
    - **`docs/ASLMS_Process_Workflows.md`**, in the owner's plain words: how an officer narrows a research question,
      reads the cited passage, and what "Text Has Changed" and "ASLMS Removed n Sentences" mean.
    - **The decisions log:** an entry.
    - **The Word guides:** the screens are described in row 276 when it regenerates them after deploy. That row's text
      gains "and the round 2 screens (row 275)".

## Data
No table, column, index, reference code or migration. The schema documents are unchanged.

## Services
- **`services/research_search.py`: `filter_choices(session, kind, q, limit) -> {kind, ready, items}`** (read-only addition
  (b)). It lives in this module, so `test_research_readers_touch_only_court_tables` covers its SQL.
  - **The full list per kind** is one statement over current readings (`order_sections WHERE replaced_at IS NULL`):
    - acts: `jsonb_array_elements(facts -> 'acts')`, grouped by `act_key`, with the label `mode() WITHIN GROUP
      (ORDER BY act)` and `count(*)`;
    - cites: the same over `facts -> 'judgments'` by `citation`, with `detail` from `mode()` of `case_name`.
  - **The time limit:** the statement runs through `reporting_common.isolated` with `CHOICES_SQL_SECONDS = 15`.
  - **The cache:** one copy per process per kind for `CHOICES_CACHE_SECONDS = 21600` (6 hours), built by one request
    at a time (a non-blocking lock).
    - While it is being built, or after a timeout, the answer is `ready: false` with no items, and the next request
      tries again.
    - Acts and citations change slowly. A value that is new within the 6 hours is still accepted by the server; it is
      only missing from the suggestions.
  - **Filtering by `q`** is done in memory, after normalising (lower case, every non-letter or digit a space,
    whitespace collapsed): a substring of the value, the label or the detail. Results are ordered by `orders`
    descending, then by label. `limit` defaults to 20, with a maximum of 50.
  - The two constants live in code, each with a test.
- **`services/assistant.py`, the message output:** each message gains `"filters": (m.scope_info or {}).get("filters")
  if role == "user" else None` (read-only addition (a)). Nothing else changes.
- **No audit:** both additions read court-public data. No event, no alert, no setting.

## API

| Method and path | Function | Change |
|---|---|---|
| `GET /assistant/filter-choices?kind=act\|cites&q=&limit=` | `assistant.use` | **New, read-only.** `kind` required (`act` or `cites`; 422 otherwise); `q` at most 100 characters; `limit` 1 to 50 (default 20). Returns `AssistantFilterChoicesOut {kind, ready: bool, items: [{value: str, label: str, detail: str \| null, orders: int}]}`. Court-public values from current court-order readings only (row 250's facts), the same for every assistant user (assistant decision 3); never notes, remarks, internal documents or drafts. Not audited. |
| `GET /assistant/conversations/{id}` | `assistant.use` (unchanged; own conversations only) | `AssistantMessageOut` gains `filters: AssistantFiltersOut \| null`, with the stored keys `forms`, `substantive_only`, `outcomes`, `against_state`, `cites`, `act`, `from` and `to` (dates as `YYYY-MM-DD`), on question messages only. |
| `POST /assistant/ask` | `assistant.use` (unchanged) | The returned `question` message carries `filters` as above. Request unchanged. |
| `GET /assistant/status`, `GET /assistant/messages/{id}/sources/{label}/passage`, `GET /admin/data-health`, `GET /admin/system-health` | unchanged | Read by the new screens as row 251 built them. |

`frontend/openapi.json` and `src/lib/api/schema.d.ts` are regenerated (`npm run gen:api` leaves no diff).
`lib/api/types.ts` gains the aliases `AssistantFilterChoices`, `AssistantPassage`, `AssistantFilters` and
`ResearchIndexStatus`.

## Jobs
None.

## Tests

**Backend (database, with the scripted gateway; no model, no NAPIX):**
- `test_filter_choices_acts_counts_and_label`: three current readings naming one act printed two ways under one key,
  plus a replaced reading. Expect one item with `orders` 3 (the replaced one is not counted) and the most common
  printed name as its label.
- `test_filter_choices_cites_with_case_name`: `detail` is the most common `case_name`; null when there is none.
- `test_filter_choices_q_and_limit`: a normalised substring on the value, label or detail; the order by count; the
  limit is capped at 50.
- `test_filter_choices_timeout_not_ready`: a forced statement timeout gives `ready: false` and no items; the next call
  builds the list.
- `test_filter_choices_cache_and_single_build`: a second call within the cache time runs no statement.
- `test_filter_choices_guard`: 403 without `assistant.use`; 422 for an unknown `kind`.
- `test_message_filters_on_questions_only`: an ask with filters returns them on the question; the thread read returns
  them; the answer and a question without filters give null.
- The existing `test_research_readers_touch_only_court_tables` passes with the new SQL.

**Frontend (Vitest):**
- `research notice`:
  - no notice for `ready`;
  - the building sentence with a whole percent, and "under 1%";
  - for `building` with null coverage, the "could not be read" sentence, with no percent, no 0% and no "ready";
  - the warning notice for `unavailable`;
  - nothing for `off`, and nothing on the case tab.
- `filters shown only when served`: hidden for `off`, preview and sourcetrace, on My Work and on the case tab; shown
  for `building`, `ready` and `unavailable` on My Cases and All Court Orders.
- `filters round-trip the address`: parameters are read and written; unknown values are dropped; tab change drops
  them; hidden-but-in-address shows the notice with Clear Filters and sends nothing.
- `ask sends exactly the filters in view`: the body's `filters` uses the keys `from` and `to`; it is omitted when none
  is set; the case and My Work tabs never send it.
- `field checks`: From after To, and a citation over 80 characters, show their errors and disable Ask.
- `choice field`:
  - a 250 ms pause and a minimum of 2 characters;
  - arrow keys, Enter and Escape;
  - an option reads "label · n orders";
  - `ready: false` shows its line and still allows typing;
  - the error state with Try Again, and Enter retrying only then;
  - a typed act is normalised by the `_act_key` rule (a table of cases shared with a backend unit test of
    `_act_key`).
- `filter errors in words`: `filters_unavailable` refetches the status and keeps the question; `bad_filter`;
  `filters_not_allowed`.
- `question chips`: the stored filters show under the question after a reload; an act key goes through the Title Case
  helper.
- `passage view`:
  - fetched only for an available court-order source with `src`, once per message and label;
  - passage and quote runs, nested and clipped;
  - the legend only for the parts present;
  - the `exact: false` line;
  - scrolled to the first mark;
  - a 404 line; an error with Try Again.
- `text changed`: the badge and line in the list and the dialog; the marker's accessible name; the passage view shows
  the notice without page text; the open link is kept.
- `show the passage from the lists`: the ghost button opens that source's dialog.
- `court record passage`: `sourceLink` adds `s` only with `src`; the card shows with `s`; no card without it or on a
  404.
- `removal block`:
  - the exact server line is split off and never parsed for markers;
  - the counts are put into words with plurals;
  - the server line is shown as written when the counts are missing;
  - text that only resembles the line is left alone;
  - Copy to Note keeps the line.
- `withheld reason`: one sentence per `withheld` value, and nothing when it is null.
- `retrieval hint and same words`: `words_only` gives its hint, the other kinds none; `same_words_in` gives its line.
- `data collection research section`:
  - hidden without a health-reader function;
  - the switched-off line;
  - readiness badges;
  - the coverage bar turning success at 99%;
  - "Not Known Right Now" and the muted line for `timed_out` counts (never 0);
  - the earlier-models table only when present;
  - the failures link and "None failed.";
  - sizes formatted;
  - one shared `["data-health"]` query with Recorded Problems;
  - the `research_embed` label in Recorded Problems.
- `enumLabels.test.ts` passes with the registry moves of decision 21. The wording guards pass.

**uicheck:** the nine states of decision 22 at four widths, 0 findings.

## Verification
1. **The gates** (definition of done):
   - `ruff check`, `pytest -q` with the database tests, and `npm run lint`, `typecheck`, `test` and `build`;
   - `npm run gen:api` leaves no diff;
   - `docker compose build web` (a build only, never `up` on the shared stack);
   - `backend/tools/portal_smoke.py`.
2. **uicheck** on a private network against temporary images (runbook section 16). It exits 0 with `findings.json`
   empty. The report records the routes and states (195 before, plus the 9), the screenshots and the run time.
3. **The choices query at full size,** read-only on the dev database inside `BEGIN READ ONLY`. `EXPLAIN (ANALYZE,
   BUFFERS)` of both choices statements, recorded with:
   - the number of distinct act keys and citations;
   - the cached list's size in memory.

   If either statement takes more than 10 s, the integrator records it and opens a follow-up row. The portal still
   works by typing (decision 10).
4. **The owner's browser check,** after deploy, with `RESEARCH_INDEX_ENABLED` on and the backfill under way or done,
   at 375 px and 1280 px:
   - a. Data Collection → Overview shows the Research Index section with the live model key and the coverage. A login
     without a health-reader function does not see it.
   - b. On All Court Orders, ask "orders on regularisation of contractual teachers" with Judgment and Outcome Against
     the State (Read by Rule). The question shows its chips, and every source is a judgment.
   - c. Pick an act from the list and ask. Clear All, then ask again unfiltered.
   - d. Open a source from its marker. The passage is shaded on its page, and Open the Order opens the PDF at that
     page.
   - e. A leading question (as in row 251 Verification 8) shows the removal block or the withheld reason.
   - f. With the switch off (on a test stack, not the live one), the filters disappear and an address holding filters
     shows the notice.
5. **"Text Has Changed"** is checked in the test database. Changing a cited order's stored text makes the answer's
   source show the badge, and the passage view show the notice with no text.

## Open questions
None. The business rules come from row 251's approved note and the owner's answers of 23 Nov 2026 (`against_state` by
rule; court information open to every assistant user). Three choices are made here and flagged for the owner's
approval:
- the two read-only API additions (decision 1), a deviation from the row's "frontend only";
- filters dropped when the tab changes (decision 8);
- the Research Index section shown only to the readers of data health (decision 18).

Approved by the owner on 24 Nov 2026 ("approve both designs as recommended"), including the three choices above: the two read-only API additions of decision 1, filters dropped when the tab changes (decision 8), and the Research Index section shown only to the readers of data health (decision 18).

## Deviations
Recorded by the developer on 24 Nov 2026; none changes a business rule or an API field.
1. **The court-record passage card** sits after the facts grid (the Order and Court Record cards), not between the two
   cards, so the page text has the full width. The view's primary is unchanged.
2. **The layout signature** `frontend/src/components/ui/layout-signature.json` is regenerated, as
   `layoutSignature.test.ts` asks of a row that adds layout: new rules in `assistant.module.css` (the filters panel,
   question chips, passage view, removal block) and `data.module.css` (the Research Index status line).
3. **uicheck states choose their answers by a `variant`.** The fixtures answered by API path only, and the nine states
   need different answers on the same paths, so a state may name a `variant`, passed to `answer()`; the research answers
   live in the new `frontend/e2e/fixtures/research.ts` (typed against `schema.d.ts`). Every answer is still a `GET`.
4. **The choice field** reuses the kit pickers' list styles (`officePicker.module.css`) and `PickerRetry`; the active
   option carries `aria-selected`.
5. **Label registry:** besides decision 21's moves, the new response enum `AssistantFiltersOut.forms` is `LABELLED` with
   the same map, and `AssistantFilterChoicesOut.kind` is `NOT_SHOWN` (it names which list was asked for).
6. **"From must be on or before To"** is shown on the To field.
7. **The Model badge** reads "Not Loaded" (info) for `held`, with the note "It loads at the next question"; decision
   19's "Held, Not Loaded" is read as one value.
8. **Space** lists both tables, each "Not Known Right Now" when the sizes timed out, with the muted line under it (the
   empty-state guard refuses a muted paragraph standing in for a list).
9. **The coverage bar:** below 99% the embedded part is the navy "active" segment and the waiting part the striped
   segment; from 99% the embedded part is the success ("done") segment.
10. **Wording guards:** the removal reason words and two field notes are declared in `SENTENCE_EXCEPTIONS`; the
    question chips' list is named "Asked with These Filters".
11. **The hidden-filters notice** (decision 8) also shows when filters are still held in the page after a
    `filters_unavailable` refusal hid the panel, so Clear Filters is offered either way. Ask stays enabled while the
    notice shows and sends no filters.
12. **The choices statement's outer timeout** restored by `isolated` is `REPORT_STATEMENT_TIMEOUT_SECONDS`; the Research
    Index section has its own Refresh button in its head (the tab's toolbar has none).
13. **Verification 3, measured early** (read-only, `BEGIN READ ONLY`, dev database, 24 Nov 2026): the act statement 0.73 s
    over 1,991 act keys, the citation statement 0.33 s over 6,587 citations; both far under the 15 s limit. The
    integrator still records the full `EXPLAIN (ANALYZE, BUFFERS)`.
14. **The filters grid and the checkbox alignment rule** (added 25 Nov 2026, after the integrator's screen check found 4
    `alignment` findings on the grid). The two lone checks (Substantive Orders Only, Outcome Against the State (Read by
    Rule)) are the kit's `CheckField inline`, and each group's first check is one control line high, so every first
    check line sits on the 36 px control line beside the boxes. The kit's `inline` centres a check on its words, which
    puts the checkbox off the line when the words wrap in a narrow column; inside this grid only, a lone check keeps
    its checkbox and its first line on the control line (`align-items: flex-start`, the checkbox's box and the label's
    `::first-line` both `var(--control-h)` high; Chromium paints the square centred in the box), its further lines
    running below. Expressed with the control-height token alone, as `tokens.test.ts` allows no other spacing value.
    The layout signature is regenerated again for these rules. Screen check `20261125-0149`: 204 routes and states,
    0 findings.
15. **Typed filters reach the address after a pause** (review advisory): typing in Cites a Judgment or Act writes the
    address 400 ms after the typing pauses (`FILTER_ADDRESS_DEBOUNCE_MS`), every other filter change at once; a write
    still waiting is dropped when the tab changes or the filters are cleared. The question always sends the filters in
    view, whether or not the address has caught up.
16. **The Cited Passage card** on the court-record view is drawn only when the passage's `order_id` is the page's order
    (review advisory), so an edited `s` never shows another order's passage.
