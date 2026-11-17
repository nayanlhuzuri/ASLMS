# Design: Order sections — every court order read into its parts by rules, with no AI

```
slug: order-sections
status: approved
author: architect
date: 2026-11-15
approved_by: owner on 2026-11-15
```

## Context
Backlog row 250 (owner, 12 Nov 2026; decisions log "Case research plan (owner, 12 Nov 2026)"). It is the first of the
four case-research rows: 250 `order-sections` (this note, rules only, no AI), 251 `research-index` (embeddings and
hybrid search), 252 `similar-and-summaries`, 253 `precedent-notes`. Each has its own design. The build order of
13 Nov 2026 puts it after row 189 (done 14 Nov 2026) and before row 258 `state-insights`. Row 258 is approved and
treats this row as a hard prerequisite. Its decision 2 asks this row for three outputs:
- (a) the cause-title span as character offsets into `document_text.full_text`;
- (b) the `Linked Case :` entries as printed;
- (c) the layout flag.

**What the owner asked for (backlog row 250, abridged).**
- A rule-based parser `services/order_parse.py` over `document_text.full_text`. It finds the header (CNR, case
  number, cause title, advocates, linked cases), the coram, the heading, the date and author, the body paragraphs
  with page numbers, and the sign-off.
- It strips the page markers, the stray `undefined` and the `Comparing Assistant` trailer, and rejoins lines broken
  across pages.
- It cross-checks the CNR, case number and order date against `orders` and `cases`. A mismatch is a data-quality flag
  on data-health and never overwrites anything.
- It tags each order judgment / final / interim, registrar (Lawazima), and procedural or substantive.
- A derived table `order_sections`: one row per order, re-buildable, never deleted.
- A 5-minute job and `aslms orders parse --backfill`.
- The roughly 7% of orders off the template are kept whole as body with a flag.
- Parties, advocates and coram already held from NAPIX are not stored again.
- **Structure, not token size.**
  - An interim order's body stays one unit.
  - A judgment's or final order's numbered paragraphs are grouped into parts (facts, the petitioner's submissions,
    the State's submissions, issues, reasoning, conclusion and directions). A part never cuts a paragraph.
  - Rule-extracted facts: the outcome, the directions to the State with any time limit, the acts and sections cited
    and the earlier judgments cited, each with its page.
  - Identical bodies are recognised by a hash.
  - Procedural orders rank low in research but count fully in each case's history.
- **"What the Order Says"** on the Orders tab:
  - the cleaned body without the cause title and addresses, with Procedural / Registrar Order labels and the
    next-date sentence still marked;
  - for a judgment or final order, also the outcome, the directions with time limits, the acts and judgments cited,
    and links to its parts that open the PDF at that page.
  - Read-only API additions only.
- **Traceability** ("I don't want you to cite wrong answers at all").
  - Every section and paragraph keeps its page, its start and end offsets in `full_text`, the PDF's SHA-256 and the
    parser version.
  - A changed PDF is re-parsed and the old sections are marked replaced, never deleted.
  - The chain chunk → section → order → stored PDF → verbatim NAPIX answer → case (CNR) is kept by keys.
- **Documentation.**
  - In the Software Documentation, chapter 6 gains the section "Case research: how orders and case details are used".
  - A new "Annexure E. Worked example: one order from text to answer" is built on one real order with names and
    addresses masked.
  - `docs/ASLMS_Process_Workflows.md` gains the owner's plain-words explanation.

**The plan.** Plan §3.2 and §5.9 give SourceTrace the reading of court orders and the research index ("the research
index itself is held in SourceTrace"). This row reads orders locally, by rules, with no AI and no external call. See
decision 1, marked **deviation**. The owner approved this direction in the case research plan of 12 Nov 2026 (local
first, then SourceTrace through the existing connector; row 36 decides whether parsed sections go there too).

**What is in place (read for this note).**
- `services/text_extract.py` writes `document_text.full_text`. A PDF's pages are joined by `"\n\f"` and the whole is
  `.strip()`-ed, so page boundaries are form feeds. A leading blank page is lost by the strip (decision 9).
  `documents` content never changes. An order PDF is a `documents` row of kind `order`, deduplicated by
  (kind, sha256).
- `services/orders.py` sets `orders.document_id` once and never changes it.
- `services/next_dates.py` and `next_date_rules.py` are the pattern for a pure rule module plus a 5-minute
  `job_runs` job. They store `orders.next_date_phrase` (the court's sentence, whitespace collapsed, at most 400
  characters). The Orders tab shows that sentence today under "What the order says" (`Orders.tsx` `OrderReading`).
- `GET /cases/{ref}/orders` (`case_detail.orders`, gated by `cases.view_scope` / `cases.view_all` and
  `require_visible`). The PDF route `GET /cases/{ref}/orders/{order_id}/file` adds `documents.view` or
  `documents.download` and the document rule (`visibility.document_visible_condition`).
- The Problems and Fixes tab's Data Gaps (`GET /admin/data-load/gaps`, `data_load.READERS`) and
  `GET /admin/data-health` (`health_reader`) carry the `documents_text` block.
- Migration 0035 has the "set once" trigger pattern (`aslms_case_closure_reopen_once`). Migrations through 0037 are
  applied to dev. 0039 is reserved by row 258, so this row takes **0038**.

**Measured on the dev database (15 Nov 2026, read-only queries).**
- 395,568 orders, 259,475 with a stored PDF. Of those, 259,432 have extracted text and 43 failed.
- The 259,475 orders point at 212,958 distinct PDFs. 21,043 PDFs back more than one order (67,560 orders in all).
  20,613 of these are common orders shared across different cases, up to 64 cases on one PDF.
- In a common order, line 2 prints the CNR of one case only. The other cases appear as `Linked Case :` entries, each
  followed by its own cause title (decision 13).
- The order PDFs hold 667 MB of text.
- Variants seen beside the owner's list:
  - `:::BEFORE:::`;
  - `HON'BLE` in place of `HONOURABLE`;
  - `JUDGMENT&ORDER (CAV)`;
  - the judgment block `Date on which judgment is reserved : …` / `Date of pronouncement of judgment : …`;
  - a neutral citation such as `2026:GAU-AS:7666` on line 3 of judgments, in the place of `undefined`;
  - an order date broken across lines (`29.07.` / `2026`);
  - `Date : 29.07.2026` in registrar orders;
  - `Advocate for the petitioner` in lower case.

**Not covered here.**
- Chunks, embeddings, pgvector, hybrid search and the answer checks: row 251. Summaries: row 252. Precedent notes:
  row 253.
- The Case Assistant keeps reading `document_text` as today. Row 251 moves it to the bodies.
- The next-date reader keeps reading the whole text. Moving it to the body is a possible follow-up, not this row.
- No OCR: orders without a text layer get no sections (`document-ocr`, option C).
- No reading of court filings (uploads): they do not follow the court's template.
- Nothing is sent to SourceTrace or any model, and no NAPIX call is made.
- Insights' own readings of the cause title (departments, posts, the State test) belong to row 258.
- Feeding directions into compliance alerts is a later follow-up (state-insights decision 2).

## Decisions

### A. Scope and where the reading happens

1. **Rules in the backend, no AI, no network.** **Deviation** from plan §3.2 and §5.9, which give the reading of
   orders to SourceTrace. This is approved in direction by the owner on 12 Nov 2026 ("Case research plan": local
   first, then SourceTrace). It is flagged here for the owner's confirmation.
   - `services/order_parse.py` and `services/order_parse_rules.py` are pure Python (`re`, no model, no model library,
     no database). This mirrors `next_date_rules.py`. The `no_local_model` guard is untouched.
   - *Alternatives:* the local Ollama model reading each order (rejected: the owner asked for no AI here, and a model
     cannot promise exact offsets); waiting for SourceTrace (rejected: row 36 is blocked).
2. **Court orders only.** These are `orders` rows whose document is kind `order`, group `court_record`, with
   `text_status = extracted`. Uploads, attachments, internal documents and cause lists are never read.
   - *Alternative:* uploaded court filings too (rejected: they do not follow the court's template, and the owner
     asked for orders).
3. **One current row per order, parsed once per PDF text.** `order_sections` has one current row per `orders` row,
   as the owner wrote, because the cross-checks, the common-order test and row 251's chain are per order.
   - Orders that share a PDF get identical parse results. One batch parses each (document, text) once and writes one
     row per order.
   - The duplicate bodies (about 46,500 extra rows, mostly short interim orders) cost a few tens of MB and are
     recognised by `body_sha256` (decision 16).
   - *Alternative:* one row per document with a per-order link (rejected: two tables to keep in step, and the owner's
     chain names the order).
4. **Rows never change, except to be marked replaced.**
   - A row is immutable once written. The only update allowed is setting `replaced_at`, `replaced_by_id` and
     `replace_reason`, once, from NULL. A trigger in the 0035 pattern enforces this, and `aslms_app` has no DELETE.
   - A new reading is a new row in the same transaction that marks the old one replaced. The reason is one of
     `parser_version`, `text_reextracted`, `document_changed`, `text_gone` (decision 18).
   - So row 251's chunks and anything citing a section always point at the exact text they were made from.
   - *Alternative:* update in place (rejected: a citation could silently move to different text, against the owner's
     "never cite wrong answers").
5. **Cross-checks are computed live, never stored.**
   - Stored with the row are only the facts read from the text: the printed CNR, case number and dates, and the flags
     about the text itself (decision 15).
   - A mismatch against `orders` and `cases` is computed in SQL whenever it is read: data-health, Data Gaps and the
     CLI, one definition in `services/order_sections.py`. A case later corrected, merged or refreshed then never
     leaves a stale flag, and the row stays immutable.
   - Nothing in `orders` or `cases` is ever overwritten from the text.
   - *Alternative:* stored check flags re-run on every case change (rejected: needs a mutable column and a re-check
     job for each nightly refresh of thousands of cases).
6. **Parties, advocates and coram are not stored again.**
   - The row keeps only the spans (offsets) of the cause title, the advocates block and the coram, the `Linked Case :`
     entries as printed (case-number text and the span of each block, the contract of row 258), and short printed
     identifiers needed for the checks: CNR, case number, dates, neutral citation, heading and author.
   - No party, advocate or address is copied into a column. Readers that need the words read `full_text` through the
     span.

### B. The parser

7. **The template, in order.** The parser walks the text top-down:
   - (1) page markers `Page No.# n/N`;
   - (2) the CNR line (16 characters, `[A-Z]{4}\d{12}`), then a stray `undefined` or a neutral citation
     (`\d{4}:GAU-[A-Z]{2,3}:\d+`);
   - (3) the court header (`THE GAUHATI HIGH COURT` and the bracketed line);
   - (4) `Case No. :`;
   - (5) the cause title, up to the first of `Advocate for`, `Linked Case :`, or the coram marker;
   - (6) `Advocate for the Petitioner / Respondent :`, any case;
   - (7) zero or more `Linked Case :` blocks, each with its own title and advocates;
   - (8) the coram marker: `BEFORE`, `:::BEFORE:::`, `B E F O R E`, `CORAM`, `PRESENT`, then the judges'
     (`HONOURABLE` / `HON'BLE` … `JUSTICE`) or `DEPUTY REGISTRAR (BENCH)` / `REGISTRAR` lines;
   - (9) the judgment date block (`Date on which judgment is reserved`, `Date of pronouncement of judgment`, and the
     operative-part and full-pronouncement lines), if present;
   - (10) the heading: `ORDER`, `JUDGMENT`, `JUDGMENT & ORDER` / `JUDGMENT&ORDER`, `JUDGEMENT`, `COMMON ORDER`, with
     `[ORAL]` / `(ORAL)` and `(CAV)`;
   - (11) the order date: `dd.mm.yyyy` even when broken across lines, or `Date : dd.mm.yyyy`. It is read at the
     heading or, for judgments, also from the pronouncement line and a closing `Date:`;
   - (12) the author, when printed (`(… J)`, `Per …`, `JUDGMENT (… J.)`, at most 200 characters);
   - (13) the body;
   - (14) the sign-off (`JUDGE`, `JUDGE  JUDGE`, `CHIEF JUSTICE`, `DEPUTY REGISTRAR`), then `Comparing Assistant`.

   Every match is case-insensitive and tolerant of extra spaces. Each pattern lives in `order_parse_rules.py` with
   the measured variant it covers.
   - *Alternative:* a general layout model (rejected: no AI, and the template is fixed).
8. **Two layouts.**
   - `template`: a coram marker and a heading were found, so the body is the text from after the heading (and date or
     author) to the sign-off.
   - `whole`: either is missing.
   - A `whole` order keeps the whole cleaned text as its body and gets the flag `off_template`. The CNR, case number
     and date are still searched at the top. The cause title, advocates and coram spans are absent (row 258 skips
     such a title rather than guess).
   - Paragraphs, parts and facts are still read from the whole body, because an off-template judgment is still worth
     its outcome and citations. The Orders tab says the order "does not follow the usual layout; shown as printed".
9. **Pages.**
   - A position's page is the PDF page it falls on (1-based), the number `#page=N` opens.
   - The page is the printed `n` of the nearest `Page No.# n/N` before the position when the markers are present (97%
     of orders), else the count of form feeds before it plus 1.
   - When the printed markers and the form feeds disagree (a blank first page lost by extraction's strip, or missing
     markers), the printed marker wins and the row gets the flag `page_marks_differ`.
10. **Clean-up, with offsets kept.**
    - The parser never edits `full_text`. It builds `body_text` from the body region by:
      - dropping page-marker lines, the CNR / `undefined` / citation lines, the court header (when repeated), the
        sign-off and the trailer;
      - rejoining a paragraph broken across a page or a line (a line not ending a sentence, followed by a line
        continuing it, is joined with one space; a word hyphenated at a line end keeps the hyphen, because a rule
        cannot tell `ex-` from a broken word);
      - collapsing runs of spaces;
      - separating paragraphs by a blank line (`"\n\n"`).
    - The parser keeps a map from every `body_text` position to its `full_text` position. So each paragraph and fact
      records both its source span `src` (in `full_text`) and its display span `txt` (in `body_text`).
    - **Offsets are 0-based code-point offsets, end exclusive.** Python string indexes and PostgreSQL `substr` on
      UTF-8 both count characters, so `substr(full_text, start + 1, end - start)` returns the span.
11. **Paragraphs.**
    - A new paragraph starts at a printed number (`2.`, `2)`, `(2)`, `2.1`, `[2]`) at the line start, at a sub-list
      item (`i)`, `(a)`) only when it follows a line ending in `:` or `;`, or at a blank line.
    - In an unnumbered body, a new paragraph also starts after a line ending in `.`, `:` or `?` that is clearly
      shorter than the body's typical line (under 70% of the median line length).
    - Each paragraph records:
      - `i`: its index;
      - `label`: the printed number, or null;
      - `page` and `page_to`;
      - `src` and `txt`;
      - `part`.
    - A paragraph is never split.
12. **Parts (owner: structure, not token size).**
    - An interim order's body is one part, `body`, never split.
    - A judgment's or final order's paragraphs are grouped, in order, into the parts `opening` (the "Heard …" and
      appearance paragraphs), `facts`, `petitioner_submissions`, `respondent_submissions`, `issues`, `reasoning`,
      `conclusion` (conclusion and directions).
    - A paragraph opens a new part when it starts with a heading (`FACTS`, `SUBMISSIONS`, `ISSUES`, `POINTS FOR
      DETERMINATION`, `DISCUSSION`, `ANALYSIS`, `CONCLUSION`, `ORDER`, `DIRECTIONS`, and their variants) or with one of
      the court's standard phrases:
      - "the facts of the case", "the case of the petitioner";
      - "learned counsel for the petitioner submits / contends";
      - "learned Standing Counsel / Government Advocate / Additional Advocate General / counsel for the respondents
        submits";
      - "the issue / question that arises for consideration";
      - "I have heard / considered", "having heard";
      - "in view of the above", "for the reasons", "accordingly", "in the result".
    - Otherwise a paragraph inherits the previous paragraph's part. The phrase table is in `order_parse_rules.py`.
    - When no marker is found, the whole body is one `body` part, and the Orders tab shows no part links.
    - **Small deviation in wording:** the owner wrote "State's submissions". The part is `respondent_submissions`,
      labelled "Respondents' Submissions", because the respondents are not always the State. In a State case they are
      the State.
    - *Alternative:* fixed-size chunks (rejected by the owner).

### C. Tags and extracted facts

13. **Checks of identity, and the common order.** The live checks (decision 5) compare the printed values with the
    order's own records:
    - `cnr_differs`: the printed CNR is not the order's case's `cnr`;
    - `case_no_differs`: the printed case number, compacted as `ix_cases_case_no_compact` does (upper case, no
      spaces), is not the case's `case_no_text` compacted;
    - `date_differs`: the printed order date is neither `orders.order_date` nor, for a judgment,
      `date_judgement_pronounced`;
    - `reserved_date_differs` / `pronounced_date_differs`: against `orders.date_judgement_reserved` /
      `date_judgement_pronounced`, when both sides are present;
    - `form_differs`: the parser's form (decision 14) is not `orders.kind`.

    **A common order is not a mismatch.** When the printed CNR or case number belongs to another case, and either
    that case also has an order on the same PDF or the order's own case number is among the printed `Linked Case :`
    entries, the check reports `common_order` (information, shown as "Common order issued under WP(C)/7013/2024")
    and not `cnr_differs` / `case_no_differs`. On the dev data this covers the 20,613 shared PDFs, which would
    otherwise flood the list.
14. **Form: judgment / final / interim.**
    - `judgment` when the heading contains JUDGMENT / JUDGEMENT or NAPIX's `orders.kind` is `judgment`.
    - Else `final` when NAPIX says `final` or an outcome of the main matter is read (decision 17).
    - Else `interim`.
    - The reading never changes `orders.kind`. A difference is the live check `form_differs`.
    - The column reuses the existing `order_kind` type.
15. **Registrar and procedural.**
    - `registrar`: the coram is a Deputy Registrar or Registrar (the Lawazima court).
    - `procedural`: the order is `registrar`, or it is `interim` and all of the following hold:
      - no outcome;
      - no compliance direction (decision 17);
      - no act or judgment cited;
      - no substantive phrase from the rule table (interim relief or stay, "status quo", "shall not", "bail",
        "suspended", "set aside", "quashed", "interim order … extended / vacated", "is directed to" followed by
        anything other than filing or producing);
      - a body of at most `PROCEDURAL_MAX_CHARS` = 1,500 characters.
    - Everything else is substantive. Judgments and final orders are always substantive unless the coram is a
      registrar: a Lawazima dismissal for default is `final` with an outcome, but still `registrar` and `procedural`
      (`ck_order_sections_registrar`).
    - The tag only ranks research (row 251). Procedural orders stay in every case's history, count, and show as
      usual.
    - Intrinsic flags stored with the row (native enum `order_section_flag`):
      - `off_template`;
      - `no_cnr_line`;
      - `no_case_no`;
      - `no_date`;
      - `page_marks_differ`;
      - `empty_body` (nothing left after clean-up);
      - `capped` (text over `MAX_PARSE_CHARS` = 2,000,000 characters; the rest is not read).
16. **Identical bodies.** `body_sha256` is the SHA-256 of `body_text` with whitespace runs collapsed to one space and
    trimmed. Case and punctuation are kept, so two orders with the same hash have the same words character for
    character, and a quote from one is a quote from the other.
    - Indexed on current rows, so row 251 embeds a routine "List after four weeks." once.
    - `status` reports the distinct count.
17. **Facts read by rules (owner's point 3).** Every item keeps its `page`, `src` and `txt`. All live in the `facts`
    jsonb.
    - **Outcome** of the main matter:
      - Values `allowed`, `partly_allowed`, `dismissed`, `disposed_of`, `withdrawn`, `closed`. The owner's four are
        allowed, dismissed, disposed of and withdrawn. `partly_allowed` ("allowed in part", "partly allowed",
        "allowed to the extent") is added because it is common and the State's outcome differs. `closed` is added for
        "the contempt proceeding is closed / dropped".
      - It is read from the sentence whose subject is the main matter ("the writ petition / appeal / petition /
        revision / review / case / contempt / matter / application under …"), never an interlocutory application, a
        Misc. Case or an I.A.
      - "Dismissed as withdrawn" and "permitted to withdraw" are `withdrawn`.
      - The last such sentence in the body wins.
      - The value is copied to the `outcome` column for filtering, and its sentence is kept as evidence.
    - **Directions** (`facts.directions`): sentences directing a respondent, the State or an authority ("is / are
      directed to", "shall", "to consider and dispose of", "to pass a reasoned order", "do the needful", "is required
      to"). Each records:
      - `text`: the sentence verbatim from `body_text`, at most 1,000 characters;
      - `addressee`: the phrase naming the respondent or authority, verbatim;
      - `kind`: `compliance`, or `procedural` when the act is filing, producing records or obtaining instructions;
      - `period`: `{n, unit (days / weeks / months), from (order_date / receipt_of_copy / other / none), phrase}`, from
        "within (a period of) N … from …";
      - `due_on`: the order date plus the period, only when `from` is `order_date` ("from today", "from the date of
        this order"). Otherwise null, because receipt of a certified copy is not known.
    - **Acts and provisions cited** (`facts.acts`):
      - "Section(s) N (and M) of the X Act, YYYY", "Article N of the Constitution (of India)", "Rule N of the X
        Rules, YYYY", "Order N Rule M CPC", and the common short forms (IPC, CrPC, CPC, BNS, BNSS, NDPS Act).
      - Each records `act` verbatim, `act_key` (lower case, whitespace and punctuation collapsed), `provisions` as
        printed, `kind` (section / article / rule / order) and its first occurrence plus a `count`.
      - The acts are not matched to the `acts` master here: that is a follow-up once row 251 shows the need.
    - **Judgments cited** (`facts.judgments`):
      - Reporter patterns: `(YYYY) V SCC P`, `YYYY SCC OnLine <Court> N`, `AIR YYYY <Court> P`, `(YYYY) V SCR P`,
        `YYYY (V) GLT P`, `(YYYY) V GLR P`, `YYYY (V) GauLT P`, `(YYYY) V LLJ P`, and neutral citations
        `YYYY:<COURT>:N` / `YYYY INSC N`.
      - Each records `citation` verbatim, `reporter`, `year`, the printed `case_name` when an "X v. Y" / "X vs. Y" /
        "X versus Y" stands immediately before it (at most 200 characters, else null), the first occurrence and a
        `count`.
      - The developer records in the build report how many citations each pattern found on the dev orders, and adds
        a pattern only for a form seen in the data.
    - The neutral citation of the order itself, printed on line 3 of judgments, is kept in `neutral_citation`. It is
      the court's own printed identifier, never derived or made up.

    *Alternative:* the model extracting facts (rejected: no AI in this row; row 252 adds an AI summary under these
    facts).

### D. Showing it ("What the Order Says")

18. **When an order is read again.** The job takes, in this order:
    - (1) orders with stored extracted text and no current row;
    - (2) current rows whose `document_id` or `pdf_sha256` no longer equals the order's document (`document_changed`;
      cannot happen today, since `orders.document_id` is set once, but it is guarded);
    - (3) current rows older than their `document_text.updated_at` (`text_reextracted`; the text was extracted again,
      for example after a PyMuPDF upgrade; a new row even if the text is the same, since this is rare);
    - (4) current rows with `parser_version` below `PARSER_VERSION` (`parser_version`);
    - (5) current rows whose document no longer has extracted text, which are marked `text_gone` with no successor.

    A parser version bump re-reads every order gradually, about 144,000 a day at the default batch, or at once with
    `--backfill`. The old rows stay, for about 0.4 to 0.6 GB per version (estimate). A move to an archive schema
    under DB_STANDARD §6 can follow if versions pile up. Nothing is deleted.
19. **"What the Order Says" on the Orders tab** replaces today's disclosure, which shows only the next-date sentence.
    Expanded, it loads `GET /cases/{ref}/orders/{order_id}/sections` and shows, in Title Case per the portal rules:
    - badges `Procedural`, `Registrar Order`, `Judgment` or `Final Order`, and `Common Order` with the printed case
      number;
    - the cleaned body without the cause title, addresses or advocates, paragraphs as printed. The next-date sentence
      of `orders.next_date_phrase` is marked (`<mark>`) where found;
    - for a judgment or final order, above the body:
      - Outcome;
      - Directions to the State, compliance kind only, each with its time limit in words and Due By when `due_on`
        is set;
      - Acts and Provisions Cited;
      - Judgments Cited;
      - Parts (Facts, Submissions, Issues, Reasoning, Conclusion, those found). Each part link opens the stored PDF
        inline at the part's first page (`…/file?disposition=inline#page=N`), only for a caller who may view the PDF
        inline (the same rule as today's View);
    - each listed fact also carries its page as a link to the PDF at that page;
    - an off-template order: the one-line notice of decision 8;
    - not read yet: "Not Read Yet"; no text layer: "Scanned, Not Read" (the `document-ocr` wording). Either way it
      falls back to today's next-date sentence;
    - long bodies (judgments) in the kit `ScrollBox`.

    The next-date sentence is found by a whitespace- and punctuation-tolerant match of the stored phrase's words in
    `body_text`, so the reader's joined dates and stripped page headers still match. When it is not found, the
    sentence is shown under the body as today. The Case Claim modal's order rows are unchanged in this row.
20. **Who sees it.**
    - The body is document content, so the API gives the reading only to a caller who may open the case
      (`require_visible`), holds `documents.view` in a membership, and passes `visibility.can_view_document` for the
      order's PDF. Court records are `case_scope`, so in practice this is everyone on the case with the document
      function.
    - Without that, the list's `reading` is null and the sections route answers 404.
    - Reading the sections writes no audit row, as viewing a court record writes none today.
    - Data-health and Data Gaps show counts and, in the check list, the case reference, CNR, case number, order
      number and date, and the printed values. They never show body or title text.
21. **Data-quality flags on data-health (owner).**
    - A block `order_sections` in `GET /admin/data-health` and in `GET /admin/data-load/gaps`, beside
      `documents_text`.
    - A paged list `GET /admin/data-load/gaps?kind=order_checks` of current rows with a live mismatch or an intrinsic
      flag.
    - The portal shows them in Problems and Fixes → Data Gaps as "Order Reading Checks". Nothing is fixed from there:
      a mismatch is for a person to look at.
22. **No events, no alerts, no audit.** Parsing is system work on derived data, like the next-date reader and the
    scoring engine. Each run writes one `job_runs` row (`order_sections`). A failure goes to `source_failures` (kind
    `order_parse`, ref the order id) and is resolved when the order is read.
23. **Court work keeps its priority.**
    - The job runs in the `scheduler` process every 5 minutes at minutes 3, 8, …, between `next-dates-read` (2) and
      the insights refresh (4), with `ORDER_SECTIONS_BATCH` (default 500).
    - It never touches `fetch_queue` or NAPIX.
    - The backfill is a CLI run outside the app services (`docker compose run --rm api aslms orders parse --backfill`).
      It commits every batch, can be stopped and resumed, and pauses `--pause-ms` (default 200) between batches.
    - Concurrency needs no locks on `orders`. The insert relies on the partial unique index on current rows, and a
      replacement is an `UPDATE … WHERE replaced_at IS NULL` that must touch one row. A loser of either race rolls
      back its savepoint and counts `skipped`. This is safe under PgBouncer transaction mode (no session features).

### E. Documentation and fixtures

24. **Fixtures hold no unmasked personal data.**
    - Parser tests use masked copies of real orders: names, addresses, the CNR and case-number digits replaced
      (`GAHC01XXXXXX2025`, `WP(C)/XXXX/2025`).
    - Fixtures cover each variant of decision 7, plus:
      - an interim order;
      - a registrar order;
      - a final order with directions;
      - a judgment with parts and citations;
      - a common order with linked cases;
      - an off-template order;
      - a leading blank page;
      - a `capped` text (generated).
    - Fixtures live under `backend/tests/fixtures/orders/`.
25. **The documentation part of this row (owner).** The scribe writes it from the developer's output (definition of
    done).
    - In `docs/software-documentation/build.js`, chapter 6 "Case Assistant and SourceTrace" gains the section "Case
      research: how orders and case details are used". This row writes its first part:
      - the order template;
      - the clean-up;
      - the cross-checks and the common order;
      - the tags;
      - the extracted facts;
      - "What the Order Says";
      - the traceability chain;
      - order sections → `orders` (with its verbatim dossier entry `orders.raw`) → the stored PDF by SHA-256 (the
        verbatim Show Order answer) → `cases.cnr` → `napix_responses`.
    - It adds "Annexure E. Worked example: one order from text to answer" after Annexure D, with an entry in
      `TOC_PAGES`. It is built on one real final order of 2 to 4 pages with at least one direction to the State and
      one act cited, chosen by the developer and named in the build report.
    - **Masking:** every personal name (parties, advocates, judges, officers), every address, and the digits of the
      CNR and case number are masked and marked as masked. The court, case type, year, dates, acts and cited judgments
      are kept.
    - It shows the order's parts marked (header, cause title, advocates, coram, heading, body paragraphs, sign-off),
      its clean body, its tags and facts each with page and offsets, and its PDF fingerprint (shortened).
    - The document is regenerated to `docs/ASLMS_Software_Documentation.docx` with the version raised.
    - `docs/ASLMS_Process_Workflows.md` gains in section 4.9 a plain-words subsection "How ASLMS reads an order". Its
      contents page numbers are checked on a rendered copy when one is available; row 255 notes that none was
      available on 13 Nov 2026.
    - Rows 251 to 253 extend the same section and annexure.

## Data

**Migration 0038 `order_sections`** (down_revision 0037). New native enum types: `order_layout` (`template`, `whole`),
`order_outcome` (`allowed`, `partly_allowed`, `dismissed`, `disposed_of`, `withdrawn`, `closed`),
`order_section_flag` (`off_template`, `no_cnr_line`, `no_case_no`, `no_date`, `page_marks_differ`, `empty_body`,
`capped`), `order_section_replace_reason` (`parser_version`, `text_reextracted`, `document_changed`, `text_gone`). The
existing `order_kind` is reused, not created again. No `ref_*` code set: these are system states, not labels an
administrator edits (DB_STANDARD §7). The portal labels them. No new function and no seed change.

The paragraph for `docs/schema/schema.md`, Group 6 (after `orders`):

> | `order_sections` (derived) | id (uuid v7 PK), order_id (→ orders RESTRICT, NOT NULL), document_id (→ documents RESTRICT, NOT NULL; the order's PDF at parse), pdf_sha256 (varchar 64 NOT NULL; `documents.sha256` at parse), text_sha256 (varchar 64 NOT NULL; SHA-256 of the exact `document_text.full_text` read), text_chars (integer NOT NULL), parser_version (smallint NOT NULL), layout (`order_layout` NOT NULL), form (`order_kind` NOT NULL; the parser's reading, never written to `orders.kind`), heading (varchar 80 NULL; as printed, whitespace collapsed), oral (boolean NOT NULL default false), cav (boolean NOT NULL default false), printed_cnr (varchar 16 NULL), printed_case_no (varchar 80 NULL), printed_date (date NULL), printed_reserved_on (date NULL), printed_pronounced_on (date NULL), neutral_citation (varchar 40 NULL; as printed), author (varchar 200 NULL; as printed), registrar (boolean NOT NULL), procedural (boolean NOT NULL), outcome (`order_outcome` NULL), spans (jsonb NOT NULL; `{name: [start, end]}` for `header`, `cnr`, `case_no`, `cause_title`, `advocates`, `coram`, `judgment_dates`, `heading`, `date`, `author`, `body`, `signoff`, each present only when found), linked_cases (jsonb NOT NULL default `[]`; `[{case_no (as printed, ≤ 80), src: [start, end] of the block, title: [start, end] or null}]`), body_text (text NOT NULL; the cleaned body, paragraphs separated by a blank line, may be empty only with `empty_body`), body_sha256 (varchar 64 NOT NULL; of `body_text` with whitespace collapsed and trimmed), paragraphs (jsonb NOT NULL; `[{i, label, page, page_to, src: [s, e], txt: [s, e], part}]`), parts (jsonb NOT NULL; `[{part, first, last, page, src: [s, e], txt: [s, e]}]`, part ∈ `body`, `opening`, `facts`, `petitioner_submissions`, `respondent_submissions`, `issues`, `reasoning`, `conclusion`), facts (jsonb NOT NULL; `{outcome: {value, text, page, src, txt} or null, directions: [{kind, text, addressee, period, due_on, page, src, txt}], acts: [{act, act_key, provisions, kind, count, page, src, txt}], judgments: [{citation, reporter, year, case_name, count, page, src, txt}]}`), flags (`order_section_flag[]` NOT NULL default `{}`), replaced_at (timestamptz NULL), replaced_by_id (→ order_sections RESTRICT, NULL), replace_reason (`order_section_replace_reason` NULL), created_at, updated_at | One current row per order: partial unique `ix_order_sections_current` (order_id) WHERE replaced_at IS NULL. Indexes `ix_order_sections_order_created` (order_id, created_at) for the history, `ix_order_sections_document_id`, `ix_order_sections_replaced_by_id`, partial `ix_order_sections_body_sha256` (body_sha256) WHERE replaced_at IS NULL. CHECKs: `ck_order_sections_replaced` (`(replaced_at IS NULL) = (replace_reason IS NULL)`); `ck_order_sections_successor` (`(replaced_by_id IS NULL OR replaced_at IS NOT NULL) AND (replace_reason IS NULL OR replace_reason = 'text_gone' OR replaced_by_id IS NOT NULL)`); `ck_order_sections_whole` (`layout = 'template' OR 'off_template' = ANY(flags)`); `ck_order_sections_registrar` (`NOT registrar OR procedural`); `ck_order_sections_outcome` (`outcome IS NULL OR form <> 'interim'`). Trigger `order_sections_replace_once` (function `aslms_order_section_replace_once`, the 0035 pattern): every column except `replaced_at`, `replaced_by_id`, `replace_reason` and `updated_at` is fixed, and those three change once, from NULL; plus `set_updated_at`. Grants: ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT / UPDATE to `aslms_app` (no DELETE; not on the §6 cascade list). Comment `class=derived`. Written only by `services/order_sections.py`, from the stored text of court orders, by the rules of `services/order_parse.py` (no AI, no network). All offsets are 0-based code-point offsets into `document_text.full_text` (`src`) or `body_text` (`txt`), end exclusive: `substr(full_text, s + 1, e - s)`. Pages are PDF pages (1-based). Mismatches with `orders` and `cases` are not stored: they are computed when read (design `order-sections`, decision 5). Parties, advocates and coram are not copied: only their spans. Re-buildable and never deleted; a new reading replaces the old row, which stays (design `order-sections`, decisions 4 and 18). Size on the dev data: about 0.4 to 0.6 GB per parser version (estimate; the build report gives the measured size). |

Also in `schema.md`:
- The "Not carried over from the prototype" paragraph gains: "`order_sections` (design `order-sections`, owner's case
  research plan of 12 Nov 2026) is a new derived table, not the prototype's `order_analyses` / `order_directions` /
  `order_citations`. Rules only, one row per order with the facts in jsonb."
- The DB_STANDARD §0 "Derived / log" list gains `order_sections`, as a DB_STANDARD text edit by the scribe with no
  version change. The standard is not otherwise changed.

The downgrade drops the table, its trigger, function, indexes and the four types. It is derived and re-buildable, so it
needs no refusal. The `order_kind` type stays.

`job_runs.job` gains the value `order_sections`; `source_failures.kind` gains `order_parse` (both free text today).

## Services

**`backend/aslms/services/order_parse_rules.py`** (pure). The patterns and phrase tables of decisions 7, 11, 12, 15 and
17, each with a one-line comment naming the variant it covers and its measured share:
- `PARSER_VERSION = 1`, `PROCEDURAL_MAX_CHARS = 1500`, `MAX_PARSE_CHARS = 2_000_000`;
- `PAGE_MARK`, `CNR_LINE`, `NEUTRAL_CITATION`, `COURT_HEADER`, `CASE_NO`, `ADVOCATES`, `LINKED_CASE`, `CORAM_MARK`,
  `REGISTRAR_CORAM`, `JUDGMENT_DATES`, `HEADING`, `ORDER_DATE`, `AUTHOR`, `SIGNOFF`, `TRAILER`;
- `PARA_START`, `PART_HEADINGS`, `PART_PHRASES`, `SUBSTANTIVE_PHRASES`, `OUTCOME_PATTERNS`, `MAIN_MATTER_SUBJECTS`,
  `DIRECTION_VERBS`, `ADDRESSEES`, `PROCEDURAL_DIRECTION_ACTS`, `PERIOD`, `ACT_PATTERNS`, `REPORTER_PATTERNS`.

**`backend/aslms/services/order_parse.py`** (pure; no database, no network, no model):
- `parse(full_text: str, *, order_date: date | None, napix_kind: str | None) -> Parsed`. It never raises on court text:
  an unexpected exception is a bug, recorded by the caller.
- `Parsed` holds every column of `order_sections` except the keys and hashes of the source. Its helpers:
  - `pages(text) -> PageMap` (decision 9);
  - `locate(text, pages) -> Spans`, which also returns the layout (decisions 7 and 8);
  - `clean(text, spans) -> (body_text, offset_map)` (decision 10);
  - `paragraphs(...)` (decision 11);
  - `parts(paragraphs, form)` (decision 12);
  - `outcome(...)`, `directions(...)`, `acts(...)` and `judgments(...)` (decision 17);
  - `form(...)`, `procedural(...)` and `flags(...)` (decisions 14 and 15);
  - `body_hash(body_text)` (decision 16).
- `next_date_span(body_text: str, phrase: str | None) -> tuple[int, int] | None` for the API (decision 19).
- Invariants, asserted in tests:
  - every `src` span lies inside `spans.body` (facts and paragraphs) or the header;
  - every `txt` span lies inside `body_text`;
  - `body_text[txt]` equals the cleaned form of `full_text[src]`;
  - paragraphs are in order, do not overlap, and cover the body;
  - parts never cut a paragraph;
  - pages never decrease.

**`backend/aslms/services/order_sections.py`** (database):
- `candidates(session, *, batch, order_id=None) -> list[Candidate]`: the five sets of decision 18, in that order,
  oldest first. They are read without locks, joined to `documents` and `document_text`. Only court orders are read:
  `documents.kind = 'order'`, `doc_group = 'court_record'`.
- `read_batch(session, *, batch, order_id=None) -> counters`:
  - groups the candidates by (document, text) and parses each text once;
  - per order, one savepoint inserts the new row and marks the old one replaced (decisions 4 and 23);
  - counters `claimed`, `parsed`, `template`, `whole`, `replaced` (by reason), `text_gone`, `skipped`, `failed`;
  - a failure goes to `source_failures` (`order_parse`) with the exception class and message, and an open failure of
    the order is resolved when it is read.
- `run_job(session, *, cfg) -> counters`: one `job_runs` row (`order_sections`), `partial` when an order failed, as
  `next_dates.run_job`.
- `backfill(session_factory, *, batch, pause_ms, limit=None, dry_run=False, echo)`: batches until no candidate is
  left. It commits each batch. With `dry_run` it parses and counts but writes nothing.
- `check_columns()` returns the SQL expressions of decision 13 over `order_sections` (current), `orders`, `cases` and
  the common-order test. These are `cnr_differs`, `case_no_differs`, `date_differs`, `reserved_date_differs`,
  `pronounced_date_differs`, `form_differs` and `common_order`. It is one definition used by `status`, `check_rows`
  and the CLI.
- `status(session) -> dict`: the data-health block (one snapshot, under the report statement timeout):
  - `parser_version`;
  - `orders_with_text` (orders whose PDF has extracted text);
  - `read` (with a current row at the current version);
  - `waiting` (candidates of sets 1 to 4);
  - `failed` (open `order_parse` failures);
  - `by_layout`, `by_form`, `procedural`, `registrar`, `with_outcome`, `with_directions`;
  - `distinct_bodies`;
  - `flags` (`{flag: n}`, intrinsic);
  - `checks` (`{check: n}`, live, `common_order` included);
  - `last_run` (time and counters of the latest `order_sections` run).
- `check_rows(session, *, check=None, limit, offset) -> (total, items)`: current rows with any live mismatch or
  intrinsic flag (optionally one), newest order first. Each item has the case brief (`id`, `ref_no`, `cnr`,
  `case_no_text`), `order_id`, `order_no`, `order_date`, `kind`, `checks`, `flags`, and the printed and held CNR, case
  number and dates. It carries no body or title text.
- `brief(session, user, order_ids) -> dict[order_id, dict | None]` for the orders list (decision 20). It is built in
  one query: the current row's `layout`, `form`, `procedural`, `registrar`, `outcome`, `body_chars`, the part names,
  `has_compliance_directions`, `common_order` and `printed_case_no` (only when `common_order`). The gate is one
  document-visibility condition for the page.
- `sections_out(session, user, case, order_id) -> dict`:
  - It calls `require_visible`, checks the order belongs to the case, and requires `documents.view` and
    `can_view_document`.
  - It returns `layout`, `form`, `heading`, `oral`, `cav`, `printed_date`, `author`, `neutral_citation`, `registrar`,
    `procedural`, `outcome` (value, sentence, page), `body_text`, `paragraphs` (`label`, `page`, `part`, `txt`; no
    `src`), `parts` (`part`, `page`, `txt`), `directions`, `acts` and `judgments` (each with `page` and `txt`),
    `next_date` (the `txt` span from `next_date_span`, or null plus the stored phrase) and `common_order`.
  - `made_from` gives `{document_id, pdf_sha256, parser_version, parsed_at}`.
  - Raises `CaseNotFound` (404) when the order is not the case's or the reading is not allowed, and `NoReading`
    (404 `no_reading`, with `text_status`) when no current row exists.
- Writes no audit row and no event (decision 22).

**`services/data_health.py`**: `snapshot` gains `"order_sections": order_sections.status(session)`.
**`services/data_load.py`**: `GAP_KINDS` gains `order_checks`, read through `order_sections.check_rows`. `gaps` adds the
`order_sections` block beside `documents_text`.
**`services/case_detail.orders`**: each item gains `reading` from `order_sections.brief`.
**`services/job_repair.py`**: `SCHEDULER_JOBS` gains `order_sections`.
**`core/config.py`**: `order_sections_batch: int = Field(500, ge=1, le=5000)` (`ORDER_SECTIONS_BATCH`), with a line in
the example environment file. No secret.

**CLI** `backend/aslms/cli/orders.py`, registered as `aslms orders`:
- `parse [--backfill] [--order <uuid>] [--limit N] [--batch N] [--pause-ms N] [--dry-run]`: without `--backfill`, one
  batch, as the job does;
- `status`, which prints the data-health block;
- `show <order uuid | CNR|order_no|YYYY-MM-DD> [--text]`, which prints the layout, spans with pages, paragraphs with
  part and page, facts, flags and live checks. `--text` also prints the body. It is used for verification and for
  Annexure E;
- `checks [--check <name>] [--limit N]`, which prints the check list.

The CLI makes no NAPIX call and writes no audit row (system work, as `aslms next-dates read`).

**Portal** (`frontend/`):
- `components/case/Orders.tsx`: the "What the Order Says" disclosure of decision 19 as a new `OrderSays` component
  (`components/case/OrderSays.tsx`). It is loaded on expand (`useQuery`, key `[...caseKey, "orders", id, "sections"]`)
  and uses the kit's `Badge`, `ScrollBox`, `EmptyState` and `ErrorBanner`. Part and page links go through the existing
  `fileUrl(caseRef, orderId, "inline")` with `#page=N`, shown only where View is shown today. Texts go in
  `lib/messages.ts` in Title Case. Part, outcome and flag labels go through the label helper.
- `components/data/ProblemsAndFixes.tsx`: Data Gaps gains an "Order Reading Checks" subsection. It has the counts from
  the `order_sections` block and a paged `DataTable` of `kind=order_checks` (Case, Order, What Differs, Printed, Held)
  with a case link. It is read only.
- `lib/api/schema.d.ts` and `openapi.json` are regenerated.

## API

All additions are read-only.

- **`GET /cases/{ref}/orders`** (unchanged gate: `Permission.CASES_VIEW_SCOPE` or `Permission.CASES_VIEW_ALL`; case
  visibility by `require_visible`). Each `OrderOut` gains `reading: OrderReadingBrief | null`:
  `{layout, form, procedural, registrar, outcome, body_chars, parts: [part], has_compliance_directions, common_order,
  printed_case_no}`. It is null when the order has no current row, or the caller lacks `Permission.DOCUMENTS_VIEW`, or
  the order's PDF fails the document rule.
- **`GET /cases/{ref}/orders/{order_id}/sections`** (new; `Permission.CASES_VIEW_SCOPE` or
  `Permission.CASES_VIEW_ALL` at the route, then `Permission.DOCUMENTS_VIEW` and `can_view_document` in the service).
  - 200 `OrderSectionsOut`, shaped as `sections_out` above.
  - 404 `not_found` when the case or order is not visible or not the case's, or the caller may not open the PDF.
  - 404 `no_reading` (`{text_status}`) when the order is not read yet or has no text.
  - Not audited. Never calls NAPIX.
- **`GET /admin/data-health`** (unchanged gate `health_reader`: `Permission.REPORTS_STATE`,
  `Permission.ADMIN_NAPIX_REFETCH`, `Permission.ADMIN_MASTERS_SYNC`): `DataHealthOut` gains `order_sections` (the
  `status` block). Counts only.
- **`GET /admin/data-load/gaps`** (unchanged gate `data_load.READERS`: `Permission.ADMIN_DATA_LOAD`,
  `Permission.REPORTS_STATE`, `Permission.ADMIN_NAPIX_REFETCH`, `Permission.ADMIN_MASTERS_SYNC`).
  - `kind` accepts `cases|orders|order_checks`, with an optional `check` (one of the live check or flag names, else
    400 `bad_input`).
  - `DataGapsOut` gains `order_sections`. For `kind=order_checks`, `items` are the `check_rows` items and `counts` the
    totals by check.
  - References, CNRs, case numbers, order numbers, dates and printed identifiers only. 503 `search_timeout` as today.

## Jobs

- **`order-sections`** (beat, `crontab(minute="3-59/5")`, task `aslms.order_sections_read`, in the `scheduler`
  process):
  - `order_sections.run_job` with `ORDER_SECTIONS_BATCH` (500);
  - one `job_runs` row (`job = order_sections`) with the counters of `read_batch`;
  - repaired at scheduler start with the other scheduler jobs (`SCHEDULER_JOBS`).
  - No `fetch_queue` row, no NAPIX call, no priority over court work.
- **Backfill** (owner-run, once after deploy): `docker compose run --rm api aslms orders parse --backfill`. It is
  resumable, commits per batch and pauses between batches. The developer measures its time on the dev data (estimate:
  one to two hours for 259,432 orders).

## Tests

Unit (`backend/tests/unit/test_order_parse.py`, `test_order_parse_rules.py`), on the masked fixtures of decision 24:
- `test_template_interim_header_spans_and_body`: CNR, case number, cause title, advocates, coram, heading, date and
  body located. The body excludes the title, the addresses and the sign-off.
- `test_page_markers_undefined_and_trailer_removed_and_lines_rejoined_across_pages`
- `test_order_date_broken_across_lines_and_registrar_date_form`
- `test_judgment_dates_block_neutral_citation_and_author`
- `test_variants_before_hon_ble_lowercase_advocates_judgment_and_order_cav`
- `test_linked_case_entries_as_printed_with_their_spans` (the row 258 contract b)
- `test_cause_title_span_ends_at_advocates_linked_case_or_coram` (contract a)
- `test_off_template_kept_whole_with_flag_and_no_title_span` (contract c)
- `test_pages_from_printed_markers_and_form_feeds_and_leading_blank_page_flag`
- `test_offsets_round_trip_src_and_txt_for_every_paragraph_and_fact` (the invariants of `order_parse`)
- `test_paragraphs_numbered_sublists_and_unnumbered_bodies`
- `test_interim_body_is_one_part_never_split`
- `test_judgment_parts_from_headings_and_phrases_never_cut_a_paragraph`
- `test_outcome_main_matter_only_not_ia_and_last_sentence_wins` (with `withdrawn`, `partly_allowed`, `closed`)
- `test_directions_compliance_vs_procedural_period_and_due_on_only_from_order_date`
- `test_acts_and_provisions_with_counts`
- `test_judgments_cited_reporters_and_case_name`
- `test_form_judgment_final_interim_and_registrar_procedural_rules`
- `test_body_hash_ignores_whitespace_only`
- `test_capped_and_empty_body_flags`
- `test_next_date_span_tolerant_match_and_not_found`
- `test_parse_never_raises_on_garbage_text` (random and binary-looking text)
- `test_no_model_or_network_import` (the module imports neither `integration` nor any HTTP or model library)

Database (`backend/tests/db/test_order_sections.py`):
- `test_job_reads_new_orders_once_and_writes_job_run`
- `test_shared_pdf_parsed_once_one_row_per_order`
- `test_only_court_orders_with_extracted_text_are_read` (uploads, attachments and `none` text are never read)
- `test_reextracted_text_replaces_row_and_keeps_old` (`text_reextracted`; the old row is unchanged)
- `test_parser_version_bump_replaces_gradually`
- `test_text_gone_marks_replaced_without_successor`
- `test_document_changed_guard`
- `test_trigger_forbids_changing_fixed_columns_and_second_replacement`
- `test_app_role_cannot_delete_order_sections`
- `test_partial_unique_one_current_row_and_race_counts_skipped`
- `test_failure_recorded_in_source_failures_and_resolved_on_success`
- `test_live_checks_cnr_case_no_date_form_and_common_order_suppresses_mismatch`
- `test_checks_follow_a_corrected_case_without_rewriting_rows`
- `test_orders_and_cases_never_written_by_the_reader`
- `test_status_block_counts`, `test_check_rows_paging_and_check_filter`
- `test_backfill_commits_per_batch_resumes_and_dry_run_writes_nothing`

API (`backend/tests/db/test_api_order_sections.py`; see Deviation 11):
- `test_orders_list_reading_brief_with_documents_view`
- `test_orders_list_reading_null_without_documents_view`
- `test_sections_route_returns_body_parts_facts_and_next_date_span`
- `test_sections_route_404_for_invisible_case_other_case_order_or_no_document_rule`
- `test_sections_route_404_no_reading_with_text_status`
- `test_sections_route_writes_no_audit_row`
- `test_data_health_has_order_sections_block`
- `test_gaps_order_checks_kind_and_bad_check_400`
- `test_responses_carry_no_title_or_body_text_in_admin_blocks`

Migration and policy:
- `0038` passes the migration audit: class comment, grants, no CASCADE, and the trigger present;
- upgrade and downgrade on an empty and a filled table;
- `order_sections` is in the derived-class registry and not in `CASCADE_TABLES`;
- the CLI help lists `orders`.

Frontend (`components/case/case.test.tsx`, `components/data/data.test.tsx`):
- "What the Order Says" for an interim order: body with the next-date sentence marked, the Procedural badge;
- a judgment: Outcome, Directions with time limit and Due By, Acts, Judgments Cited, Part links with `#page=`;
- off-template notice; Not Read Yet and Scanned, Not Read with the old sentence fallback;
- no part links without the view right;
- the Order Reading Checks table and paging;
- Title Case and label guards;
- uicheck states for the expanded judgment and interim readings at 375, 768, 1024 and 1280 px.

`ruff check` clean, `pytest -q` green, frontend `npm test` and lint green.

## Verification

1. `docker compose run --rm migrate` applies 0038 (the `migrate` step with the court-data switch as the runbook says).
   `\d+ order_sections` shows `class=derived`, the partial unique index and the trigger.
   `aslms ops preflight` passes.
2. `aslms orders parse --dry-run --limit 3000` on the dev database prints the counts by layout and form, the flags and
   the citations per reporter pattern. **Expected:**
   - `template` in at least 92% of orders with text (the owner measured about 93% on the template);
   - `whole` in about 7%;
   - `procedural` in most interim orders;
   - no failure.

   The developer records the numbers and the parse time per 1,000 orders in the build report.
3. `docker compose run --rm api aslms orders parse --backfill`. Then `aslms orders status`:
   - `read` equals `orders_with_text` (259,432 on 15 Nov 2026, plus new texts);
   - `waiting` 0 and `failed` 0, or each failure listed in `source_failures` with its cause;
   - `distinct_bodies` well below `read`;
   - `checks.common_order` in the order of the 46,500 orders on shared PDFs;
   - `cnr_differs` and `case_no_differs` a small number, which the developer samples and explains in the report.

   The table size is given by `pg_total_relation_size`.
4. Within 10 minutes of a new order's text being extracted, `job_runs` shows an `order_sections` run that read it.
   `aslms orders show <that order>` prints its spans, paragraphs with pages and facts.
5. Traceability spot check, by SQL in the report, for 20 random current rows:
   - `substr(full_text, s + 1, e - s)` of `spans.cause_title`, of each fact's `src` and of three paragraphs equals what
     the parser reported;
   - `pdf_sha256` equals `documents.sha256`;
   - `#page=N` of a part opens the PDF on the page where that paragraph starts.
6. Portal, at `http://localhost:3000`, on the case page Orders tab:
   - an interim order shows the cleaned body without the cause title, with the next-date sentence marked;
   - a Lawazima order shows Registrar Order and Procedural;
   - a judgment shows Outcome, Directions with time limit, Acts, Judgments Cited, and part links opening the PDF at
     the right page;
   - an off-template order shows the notice;
   - a common order shows Common Order with the printed case number;
   - an officer without `documents.view` sees no reading.
7. Problems and Fixes → Data Gaps shows Order Reading Checks with counts and the list, with no body or title text.
8. **The owner's sample of 20** (5 interim, 5 final, 5 judgments, 5 registrar or off-template, chosen by the developer
   across years): each "What the Order Says" is compared with the PDF by the owner in the browser. A wrong outcome, a
   wrong direction or a misplaced part is a defect for the follow-up row, not a data change.
9. The documentation (decision 25):
   - `node docs/software-documentation/build.js` regenerates the Software Documentation with the new chapter 6
     section and Annexure E;
   - the worked example shows no unmasked name, address, CNR or case-number digits;
   - `docs/ASLMS_Process_Workflows.md` has "How ASLMS reads an order".
10. No NAPIX call during the backfill: the `napix_call_log` count for the backfill window is unchanged by it.
    `sourcetrace_ingestions` is unchanged.

## Open questions
None. Every rule needed is in the owner's row text or decided above. The owner confirms or changes these with the
approval:
- decision 1, the marked deviation from plan §3.2 / §5.9 (rules locally in place of SourceTrace for reading orders;
  already the owner's direction of 12 Nov 2026);
- decision 12, the part named "Respondents' Submissions" in place of "State's Submissions";
- decision 17, the two outcome values added (`partly_allowed`, `closed`);
- decision 25, masking judges' names as well as parties, advocates and addresses in the worked example.

## Deviations
Recorded by the developer while building (15 Nov 2026). None changes a business rule; each is the smallest reading of a
point the note leaves open, or a variant measured in the data.
1. **Coram then date, no heading, is the template.** Decision 8 makes an order `whole` when the heading is missing.
   On 3,000 random dev orders that literal rule gave 87% `template`; most of the rest were older and division-bench
   orders printed as coram → date → body with no `ORDER` line. A coram followed within four lines by the order date
   now counts as `template` (heading null). With it, 98.0% of the sample is `template` (the note expects at least
   92%), and those orders keep their cause title and addresses out of the body.
2. **More measured variants in `order_parse_rules.py`.** Page markers `Page n of N` (judgments typed outside the
   template); a heading indented, spaced out (`O R D E R`), printed one letter per line, or with the date before it on
   the same line; `Date :  --19.03.2025`; an author in square brackets (`[A. B., J]`); the `Date of Hearing` /
   `Date of Judgment` lines in the judgment block; a digital-signature block after `Comparing Assistant` (the trailer
   is looked for in the last 15 lines). The heading is looked for within 40 non-blank lines of the coram, because
   judgments put the advocates and the judgment dates between them.
3. **Blank lines.** A blank line starts a paragraph only after a line that ends a sentence, and blank lines next to a
   page break are ignored. Extraction leaves a blank line at every page join, and some judgments have a blank line
   between single words.
4. **Hyphen at a line end.** The two lines are joined with no space, keeping the hyphen (`P.O.-` / `UDAYAN` reads
   `P.O.-UDAYAN`).
5. **Parts.** The opening is only the "Heard" and appearance paragraphs among the first three; an unmarked paragraph
   after it starts the facts, and a first paragraph without the formula is the facts. A conclusion phrase
   ("accordingly", "in view of the above", …) counts only in the second half of the body, because these phrases open
   many paragraphs mid-judgment.
6. **One parse per (document, order date, NAPIX kind).** The form uses `orders.kind` and `due_on` uses the order date,
   so orders on one PDF with a different kind or date are parsed separately. Orders sharing a PDF normally share both,
   so a common order is still parsed once.
7. **Outcome and directions wording.** "Bail application" is a main-matter subject (the main matter of a bail case);
   `closed` also covers "these writ petitions stand closed". Appellants are an addressee only as "State appellants";
   titles (Commissioner, Secretary, Director, …) match only with their capital letter; "Government Advocate",
   "Government Pleader" and "State counsel" are never addressees.
8. **Deferred self-reference.** `fk_order_sections_replaced_by_id_order_sections` is `DEFERRABLE INITIALLY DEFERRED`.
   The old row must name its successor in the update that frees the one-current-row slot, before the successor is
   inserted in the same savepoint (`ck_order_sections_successor` and the trigger allow no second update).
9. **API shapes.** `OrderSectionsOut` also carries `order_id` and `flags`; `common_order` is `{printed_case_no}` or
   null; `parts` leaves out a single `body` part, and the list's `reading.parts` is empty when the body is one part.
   `GapOrderCheckOut` carries `form` beside `kind`, and `printed` / `held` as `{cnr, case_no, date, reserved_on,
   pronounced_on}`. The `kind=order_checks` list leaves out readings whose only check is `common_order` unless
   `check=common_order` is asked; `counts` gives every check and flag. `DataGapsOut.order_sections` is filled for
   `kind=order_checks` only (null for `cases` and `orders`): Data Gaps asks for its three lists at once, and the block
   counts every current reading with its live checks, so it is computed once per page; `GET /admin/data-health`
   always carries it.
10. **Job counters.** Flat keys: `replaced_parser_version`, `replaced_text_reextracted`, `replaced_document_changed`
    beside `claimed`, `parsed`, `template`, `whole`, `text_gone`, `skipped`, `failed` and `retried` (deviation 14).
11. **Test files.** The API tests are `backend/tests/db/test_api_order_sections.py` (this repository keeps its API
    tests under `tests/db`). The fixtures put a synthetic CNR (`GAHC01000001…`) in place of the mask at load time,
    so the masked files never hold a CNR.
12. **Portal.** "What the Order Says" is a native disclosure under each order row: an order with a reading loads it on
    first opening; a stored order not read yet, or scanned, shows that state with the court's sentence; a caller
    without `documents.view` sees the court's sentence alone, as before. The new CSS classes change the layout
    signature, so `layout-signature.json` is regenerated (additions only). The uicheck fixtures answer the orders list
    and the readings, and two states open the interim and the judgment readings.
13. **Dry run on the dev database.** `aslms orders parse --dry-run` reads `order_sections` (it skips orders already
    read), so it runs only once 0038 is applied. The numbers in the build report were measured read-only with the
    same parser on 3,000 random dev orders: 98.0% `template`, 2.0% `whole`, 76% of interim orders procedural, no
    failure, about 3.2 s of parsing per 1,000 orders.
14. **Orders that keep failing come last** (review finding, 15 Nov 2026). Decision 18's five sets are first taken
    without the orders that have an open `order_parse` failure; those orders are then taken by the same five sets as
    a retry pass, so they fill only the room left in a batch and never keep newer orders or replacements out of the
    5-minute job. `retried` counts the orders claimed in that pass. The backfill stops when a batch claims nothing, or
    reads nothing and holds only retries (a batch of first failures goes on, and the next batch passes them by), so
    `aslms orders parse --backfill` ends when only failing orders are left, each listed in `source_failures`.
    `status().waiting` leaves those orders out too, so `waiting` and `failed` never count the same order and
    Verification 3's "waiting 0, each failure listed" can be reached.

## Measurements

Appended 16 Nov 2026 by the developer of row 264 (design `order-sections-review-advisories`, decision 17). Every
figure was taken read-only on the dev database; nothing was written to it. The dev database is at migration 0037
(this row's 0038 is not applied there yet), so the figures that need the `order_sections` table are taken at the
deploy and added here then.

**Citations per reporter pattern** (parser version 2 over every readable court order on the dev data: 266,824
orders, one per order as the current readings will be; no reader failure). Citations are the sum of `count`, orders
the orders citing the reporter at least once. Every pattern of decision 17 found citations, so none is kept "for
nothing"; none is added.

| Reporter | Citations | Orders |
|---|---:|---:|
| SCC | 15,721 | 2,994 |
| SCC OnLine | 2,650 | 918 |
| AIR | 2,343 | 786 |
| GLT | 818 | 630 |
| GLR | 364 | 234 |
| INSC | 331 | 249 |
| SCR | 308 | 169 |
| neutral | 82 | 70 |
| GauLT | 10 | 10 |
| LLJ | 5 | 3 |

The same pass: 260,177 `template` and 6,647 `whole` readings; 5.2 s of parsing per 1,000 orders (1,389 s in all).

**Table size.** Not measurable on dev yet (no `order_sections` table). At the deploy the integrator records
`pg_total_relation_size`, `pg_relation_size`, the TOAST and index sizes of `order_sections` and the row count by
`parser_version` and current or replaced, after the version 2 backfill, and `schema.md`'s estimate ("about 0.4 to 0.6
GB per parser version") is replaced by the measured figure.

*Measured at the deploy, 17 Nov 2026, after the version 2 backfill:* 269,999 rows, all `parser_version` 2 and
current, none replaced (rows 250 and 264 deployed together, so no version 1 row was ever written). Total 672 MB: heap
470 MB, TOAST 136 MB, indexes 66 MB.

**The order used for Annexure E**: the masked fixture `backend/tests/fixtures/orders/final_directions.txt`, a final
order of 3 pages with one direction to the State and one act cited, read by the real parser. The unmasked source
order is not named by its CNR or case number anywhere in the repository: naming it would undo the masking (owner's
confirmation (a) of 16 Nov 2026, a change to decision 25). It reads the same under parser version 2 (no linked case,
and it starts with a printed marker).

**Linked-case blocks (row 264, decision 3).** Of 219,018 readable order texts, 31,347 carry a `Linked Case :` line.
Among the template readings, the last linked block bounded by its coram has at most 6,971 non-blank lines after its
`Linked Case :` line (a cause title listing every petitioner; median 35, p99 747, p99.9 2,467), so
`LINKED_BLOCK_MAX_LINES` is 6,980. 48 texts read `whole` with linked cases: in 35 the reader still found a coram, which
bounds the block as in version 1 (10 of them reach the body's last 10%, because the heading is printed before the coram
or the body is a few lines); in 13 no coram was found, and version 1 ran each last block to the end of the order,
while version 2 ends all 13 at their advocates run (2 still reach the body's last 10%, both orders of a few lines).
With a cap of 40 lines, 9 of the 13 would have been cut to their own line for a long cause title.

**Pages before the first marker (row 264, decision 4).** On 3,000 random dev orders: 2,914 carry printed markers;
none has a form feed before its first marker (so version 2 changes no page of these), 3 carry `Page n of N` markers
and none of those is printed at the foot of a page. No follow-up row is needed.

**The full check's hashing (row 264, decision 8).** Hashing every readable order text in SQL
(`encode(sha256(convert_to(full_text, 'UTF8')), 'hex')`, 219,018 texts, `document_text` 1,127 MB with its indexes)
took 0.7 s with the texts in cache. The full check's time with the join to the current readings, and the times of
decision 14 (the two `counts` statements, the `checks` statement, one `order_checks` page, each light set, the full
check) with `EXPLAIN (ANALYZE, BUFFERS)`, are recorded at the deploy, after the backfill.

*Measured at the deploy, 17 Nov 2026* (269,999 current readings, read-only, each part timed by wall clock through its
service function in the `api` container with the Compose workers running; not `EXPLAIN`):

| Part | Time | Budget |
|---|---|---|
| `counts` part (both statements) | 1.73 s | 10 s |
| `checks` pass | 2.08 s | 10 s |
| one `order_checks` page (50 rows) | 3.97 s | 10 s |
| whole status block (data-health) | 3.84 s | 10 s |
| light run, set 1 with the version gate on | 0.66 s | 1 s |
| light run, sets 1 and 4 | 0.66 s | 1 s |
| full check, sets 1, 4, 2, 3, 5 | 8.72 s | 10 s |
| full check with the retry pass (no open failure) | 8.51 s | 10 s |
| set 3's hash walk alone | 5.95 s | (inside the full check) |

Every part is inside its budget, so decision 14 needs no follow-up. The full check is the closest (8.7 s of 10 s);
with an open failure its retry pass hashes again (row 266, point 2), which would take it over. The first light run
after the deploy (23:53 IST) ran the day's full check in 9 s and found nothing.

**Backfill at the deploy, 17 Nov 2026.** `aslms orders parse --backfill` read 269,999 orders at version 2 from 23:30 to
23:53 IST (23 minutes), none failed; 500 were skipped because the 5-minute job had claimed them first (the partial
unique index, as designed). Template 263,282, whole 6,717; interim 254,402, final 13,178, judgment 2,419; procedural
185,844; registrar 5,909; with an outcome 12,472; with directions 23,231; distinct bodies 212,635. Live checks: CNR
differs 11,685, case number differs 16,685, date differs 640, common order 50,957. Flags: no CNR line 6,513, no case
number 9,780, no date 9,595, empty body 6, capped 0. No court call came from the backfill: the 904 calls in the window
were the queue's own `hc-cnr-api/CNR` fetches (daily lane, 23:31 to 23:39) after the workers restarted.

**Linked cases after the backfill (row 264, Verification 4).** 78,713 current readings carry a linked case; 146 of
them read `whole`, and in 34 of those the last linked block's `src` reaches the body's last 10%. Four of the 34 were
read by hand: each block ends at its last advocates line or at the `ORDER Date :` line printed before the coram, and
reaches the last 10% only because the order after it is a line or two. In three of the four the block's `src` takes
in the `ORDER Date :` heading line printed before the coram; that is noted for row 266. The owner's ten-order check
(row 265) is still to come.
