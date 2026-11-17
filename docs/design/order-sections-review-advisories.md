# Design: Order sections, review advisories (linked-case spans, pages, the job's scans, isolation, reading states)

```
slug: order-sections-review-advisories
status: approved
author: architect
date: 2026-11-16
approved_by: owner on 2026-11-16
```

## Context
Backlog row 264 (integrator, 16 Nov 2026). These are the review advisories of row 250 `order-sections` (design
`docs/design/order-sections.md`, approved 15 Nov 2026, merged 16 Nov 2026) that were left open at the merge. The two
blocking findings were closed before the merge, in fccfff5 (orders that keep failing come last) and 10cd322 (a `whole`
reading keeps no cause title, advocates or coram span).

The owner's decisions of 16 Nov 2026 (decisions log, "Owner decisions (16 Nov 2026)") put this row **before row 258
`state-insights`**, with **point 6 built first**. The reason: Insights reads the `Linked Case :` entries, and in a
`whole` reading those spans run into the body. The fix raises the parser version, so every order is read again (about
one to two hours, no court call).

**The eight points of the row.**
1. `order_sections.status()` runs inside every `GET /admin/data-health`, and the live checks run inside
   `kind=order_checks`. A statement timeout there must not turn the whole response into a 500. Measure on dev after
   the backfill.
2. Sets 2 to 5 of the 5-minute job scan every current reading even when nothing changed.
3. A re-extracted text is detected by `created_at` against `document_text.updated_at`, not by `text_sha256`.
4. The Orders list shows "Not Read Yet" for an order whose text extraction failed, or whose reading is withheld from
   the caller.
5. The design note does not record the citation counts per reporter, the measured table size, or the order chosen for
   Annexure E.
6. `Linked Case :` spans in a `whole` reading run to the end of the order. `PageMap.page` ignores the form-feed count
   for a position before the first printed marker. Both need a `PARSER_VERSION` bump.
7. No test denies `can_view_document` on the sections route or on the list.
8. An order whose reading keeps failing logs a traceback every 5 minutes. An open `order_parse` failure for an order
   whose text has gone is never resolved.

**What is in place (read for this note).**
- `services/order_parse.py`:
  - `locate` ends the last `Linked Case :` block at `title_end_i`. That is the coram line, or the end of the text
    when no coram was found.
  - `PageMap.page` returns the first marker's printed number for any position before the first marker
    (`marks[max(i, 0)]`).
  - `PARSER_VERSION = 1` (`order_parse_rules.py`).
- `services/order_sections.py`:
  - `candidates` runs the five sets of decision 18, then the same five sets again as a retry pass for orders with an
    open failure. That is up to ten queries every 5 minutes. Sets 2 to 5 join every current reading to `orders`,
    `documents` and `document_text`. Set 3 is `s.created_at < DocumentText.updated_at`.
  - `read_batch` calls `log.exception` on every failure, retries included.
  - `status` runs about ten statements: the live checks over every current reading, the union of sets 1 to 4 for
    `waiting`, and grouped counts. `data_health.snapshot` calls it under the 30 s report statement timeout with no
    guard, so one cancelled statement gives a 500.
  - `data_load.gaps` wraps its calls in `_timed`, which turns a cancelled statement into a 503 `search_timeout`. For
    `kind=order_checks` it computes the checks three times over every current reading: `check_rows` total,
    `check_rows` counts and `status().checks`.
- `services/text_extract.py` never re-extracts a text that is already `extracted`. Today a re-extraction happens only
  when someone sets `text_status` back to `pending` by hand, or through a later feature (OCR, row 96).
- `case_detail.orders` gives `reading` from `order_sections.brief`, or null. The portal's `OrderReading` shows
  "Not Read Yet" whenever `reading` is null and the order has a stored PDF and the caller holds `documents.view`.
  This includes `text_status = failed` and a document the caller fails the document rule for.
- `visibility.can_view_document` fails for a court record only when no single membership both sees the case and holds
  `documents.view` (court records pass part (c) for every membership).
- Annexure E (`docs/software-documentation/build.js`, version 1.9) is built on the masked fixture
  `backend/tests/fixtures/orders/final_directions.txt` and states "version 1 here".
- Row 250 is merged but not yet deployed. Its deploy (migration 0038, then the backfill) is held for a late-night
  window.

**Not covered here.**
- No change to what a reading contains beyond point 6: the template, parts, facts, tags and checks are unchanged.
- No new table, column, index or migration (decision 2).
- Moving the next-date reader to the cleaned body: row 263 (3), after the owner's sample of 20.
- Markers printed at the foot of a page (`Page n of N`, judgments typed outside the template): counted only
  (decision 4).

## Decisions

### A. Build order and version

1. **Point 6 first, then the job, then the reads.** The owner asked for point 6 first. The build goes in this order:
   - point 6: the parser fixes, `PARSER_VERSION = 2`;
   - points 3, 2 and 8: the job;
   - point 1: the status block and the gaps route;
   - points 4 and 7: the reading state, the portal and the tests;
   - point 5: the measurements and documentation.

   One branch and one merge. The re-read happens once, at the deploy of this row.
   - *Alternative:* point 6 alone as a first merge (rejected: a second deploy for no gain, because the re-read is
     the same).
2. **No migration.** Every point is met without a new table, column or index:
   - the job's gates live in the counters of its own `job_runs` rows (decision 7);
   - re-extraction is found by hash in a daily check (decision 8).

   The reasons:
   - migration 0039 stays reserved by row 258 as approved;
   - the deploy needs no `migrate` step and no pre-migrate backup (about an hour of portal downtime).
   - *Alternative:* a partial index `(parser_version) WHERE replaced_at IS NULL` and a `document_text.text_sha256`
     column (rejected: it renumbers row 258's migration, and back-filling a hash on every `document_text` row would
     rewrite about 265,000 rows and their GIN index entries for a check that finds nothing on most days).

### B. The parser (point 6), version 2

3. **A linked-case block ends where the block ends.** The last `Linked Case :` block of a reading, when no coram line
   bounds it (today this happens only when no coram was found, so the reading is `whole`), ends at the first of these:
   - (a) a heading line (`R.HEADING` or a vertical heading), a judgment-date line (`R.JUDGMENT_DATE_LINE`) or a coram
     marker (`R.CORAM_MARK`);
   - (b) the end of the block's advocates run. The run starts at the block's first `Advocate for` line
     (`R.ADVOCATES`). It continues over further `Advocate for` lines, rule lines (`R.RULE_LINE`), and continuation
     lines. A continuation line is a non-blank line that directly follows a line of the run with no blank line
     between, and is not a paragraph start (`R.PARA_START`), a heading or a date line. Blank lines next to a page
     break do not end the run (the rule of deviation 3 of row 250).
   - (c) If neither (a) nor (b) occurs within `LINKED_BLOCK_MAX_LINES` non-blank lines (default 40), the entry's `src`
     is cut to its own `Linked Case :` line and its `title` is null. The case number as printed is kept: it is row
     258's contract (b), and a title the reader cannot bound is not guessed (the reasoning of 10cd322).

   The developer measures the longest linked block bounded by a coram among the template readings on the dev data,
   and records it. `LINKED_BLOCK_MAX_LINES` is set at or above that length, rounded up to a multiple of 10.
   - A block followed by another `Linked Case :` line, or by the coram, ends as today. So **template readings keep
     the same linked spans**, and a test holds them equal to version 1 on every fixture.
   - The `title` of a bounded block is unchanged: from the line after `Linked Case :` up to the first advocates, rule
     or judgment-date line.
   - *Alternatives:* drop the spans of linked entries in every `whole` reading (rejected: the owner asked that the
     span "stop where the linked block ends", and the case number alone loses the block); end the block at the first
     blank line (rejected: extraction puts a blank line at every page join, inside titles).
4. **A page before the first printed marker counts back by form feeds.** When the text has printed markers and a
   position falls before the first one, its page is the first marker's printed number minus the number of form feeds
   between the position and that marker, and never below 1.
   - Example: a first page printed without a marker, then `Page No.# 2/3` after one form feed. Text on the first page
     is page 1, not page 2.
   - With no marker before the first form feed this gives what the form feeds alone give. After the first marker the
     rule of decision 9 of row 250 is unchanged.
   - The `page_marks_differ` flag is computed as before.
   - The developer also counts, on 3,000 random dev orders, the texts whose markers are `Page n of N` printed at the
     foot of a page (a marker followed by a form feed within two lines), and records the count. A fix for those is
     a follow-up row only if they are seen. It is not part of version 2.
   - *Alternative:* form feeds alone before the first marker (rejected: that is wrong when a leading blank page was
     lost by extraction's strip, the case `page_marks_differ` exists for).
5. **`PARSER_VERSION = 2`.**
   - Every current reading is replaced with reason `parser_version`. The version 1 rows stay, as decision 4 of row
     250 requires.
   - Annexure E's example reads the same under version 2: the fixture has no linked case and starts with a marker.
     Its "version 1 here" becomes "version 2 here" (decision 15).

### C. The 5-minute job (points 2, 3 and 8)

6. **Light runs and one daily full check.**
   - **Every run** (each 5 minutes) takes:
     - set 1, new orders with extracted text and no current reading;
     - set 4, readings below `PARSER_VERSION`, behind the gate of decision 7.
   - **The full check** takes sets 2 (document changed), 3 (text changed, decision 8) and 5 (text gone), and the
     retry pass (decision 9). It also resolves stale failures (decision 10).
   - The full check runs in the first run at or after **01:30 IST** each day (`FULL_CHECK_IST`, a constant). It runs
     before the 02:30 disposed-case slice and the 03:00 dedupe sweep, and well after the 22:00 nightly refresh has
     queued its work.
   - A full check whose candidates filled the batch leaves the check due, so the next run repeats it from the start.
     The readings it found are no longer candidates by then, so it moves on.
   - `aslms orders parse --full` runs a full check at once (the runbook's step after any manual re-extraction).
     `--order <id>` always checks every set for that one order.
   - "Stop at the first empty set" (the row's wording) is met three ways:
     - the retry pass runs only when one indexed probe finds an open `order_parse` failure;
     - set 4 is skipped while the gate says it is empty;
     - the sets of the full check run only when it is due.
   - *Why a day is acceptable:*
     - sets 2 and 5 cannot happen in today's code (`orders.document_id` is set once; an extracted text is never taken
       back);
     - set 3 happens only by hand;
     - every reader of `src` spans checks the text's hash first (decision 11), so a stale reading is never used to
       cite text that changed.
   - *Alternative:* the full sets every run behind an "anything changed" watermark on `updated_at` (rejected: the
     columns are not indexed, and a watermark misses a transaction that commits after the run started; that is the
     race of point 3).
7. **The gates are carried in `job_runs.counters`.** Each `order_sections` run reads the counters of the latest run of
   the same job (one indexed row), and writes two integers forward:
   - `version_clear` = `PARSER_VERSION` when set 4 is known empty. Either the run's set 4 query returned fewer rows
     than it asked for, or the previous run's `version_clear` already equalled `PARSER_VERSION` and no full check
     found otherwise.
   - `full_check_on` = the IST date of the last completed full check, as `YYYYMMDD`. The counters stay `dict[str, int]`
     as the API schema requires.

   Set 4 runs when the previous `version_clear` is not `PARSER_VERSION`, which is the case after every deploy that
   raises it. The full check also runs set 4 without the gate, so a reading written by an older process during a
   deploy is caught the next night.

   A run that failed (no counters) makes the next run start with no gates. That is safe: it only costs one full scan.

   Further counters: `full_check` (1 when this run did one), `full_check_found` (candidates of sets 2, 3 and 5),
   `failures_resolved`.
8. **A text change is found by its hash (point 3).**
   - In the full check, set 3 is the current readings whose `text_sha256` differs from
     `encode(sha256(convert_to(document_text.full_text, 'UTF8')), 'hex')`, computed in SQL. The database encoding is
     UTF-8, so this equals the Python `sha256(full_text.encode("utf-8"))` the reader stores (a test holds them equal
     on Assamese text and form feeds).
   - It is walked in keyset pages of 20,000 readings by `order_sections.id`, one statement per page, so no statement
     reads all 667 MB at once.
   - `document_text.updated_at` is no longer read.
   - The results:
     - a text extracted again with the same characters is not read again (no new row);
     - a change that committed after the reading's own `created_at` (the race of point 3) is still found.
   - The developer measures the full check's time on dev (expected well under 2 minutes) and records it.
   - *Alternative:* keep the timestamp and add a margin (rejected: it still misses a long extraction transaction, and
     re-reads unchanged texts).
9. **An order that keeps failing is retried once a day, and logged once (point 8).**
   - The retry pass (orders with an open `order_parse` failure, deviation 14 of row 250) moves from every run into
     the full check, the backfill and `--order`. The reader is deterministic, so a text that failed fails again until
     the text or the parser changes. A version bump's backfill retries them all.
   - **Logging.**
     - The first failure of an order (no open failure before) is logged with its traceback, as today.
     - A failure on a retry is one warning line with no traceback: the order id, the attempt count from
       `source_failures.attempts`, and the exception class.
     - So an order that keeps failing writes one line a day.
   - `source_failures.record` is unchanged: it bumps `attempts` and `last_seen`.
   - `status().failed` and the list in `source_failures` stay the place to look.
10. **A failure whose text has gone is resolved (point 8).**
    - The full check resolves every open `order_parse` failure whose order no longer has a readable text. Readable is
      decision 2 of row 250: a court order's PDF with `text_status = extracted` and `full_text` present.
    - It uses `UPDATE source_failures SET resolved_at = now() … WHERE NOT EXISTS (…)`, counted in
      `failures_resolved`.
    - Such an order has no reading to replace and is no candidate, so nothing else would ever close it.
    - If the text comes back, the order is a set 1 candidate again. A new failure opens a new attempt on the same row
      (`record` clears `resolved_at`).
11. **Readers of `src` spans check the text first.**
    - A reading's `src` offsets point into the exact text it was made from. New helper
      `order_sections.src_text(reading, full_text, span) -> str | None` returns `full_text[s:e]` only when
      `sha256(full_text)` equals the reading's `text_sha256`, else None.
    - `aslms orders show` uses it: on a mismatch it prints "text changed since this reading; run `aslms orders parse
      --full`" in place of the page numbers.
    - Row 258 reads the cause-title span the same way. Its design already reads `full_text` in Python batches, so the
      hash costs nothing extra.
    - The rule is written into the `schema.md` paragraph (Data).
    - `body_text`, the paragraphs' `txt` spans and the facts are stored in the row itself. The Orders tab and row 251
      never depend on the current `full_text`.

### D. The data-health block and the gaps route (point 1)

12. **The block is built in three parts, each isolated.**
    - **Always**, from small indexed reads:
      - `parser_version`;
      - `failed` (open `order_parse` failures);
      - `last_run`;
      - `full_check`: `{last_on: date | null, found: int | null}`, from the counters of decision 7;
      - `timed_out`: the list of parts not computed.
    - **`counts`**, two statements:
      - one over `orders` → `documents` → `document_text`, giving `orders_with_text` and the set 1 count;
      - one pass over the current readings with `FILTER` aggregates, giving `read`, the set 4 count, `by_layout`,
        `by_form`, `procedural`, `registrar`, `with_outcome`, `with_directions`, `distinct_bodies` and `flags`.
      - `waiting` = set 1 + set 4, failing orders left out as today. It no longer counts sets 2 and 3: the full check
        reports those as `full_check.found`.
    - **`checks`**, one statement: the live checks of decision 13 of row 250 over the current readings joined to
      `orders` and `cases`. The raw CNR and case-number mismatches and the common-order test are computed once per
      row in a `LATERAL` sub-select, not three times as the `check_columns` expressions are referenced today. It
      returns the count by check and by flag, and `any` (a mismatch other than `common_order`, or any flag).
    - **Isolation.** Each part runs inside a savepoint (`session.begin_nested()`) with `SET LOCAL statement_timeout`
      set to `ORDER_SECTIONS_STATUS_TIMEOUT_SECONDS` (new setting, default 10, 1 to 60). The outer timeout is set
      back after the savepoint is released.
      - A cancelled statement (`57014`) rolls back to the savepoint, which also undoes its `SET LOCAL`. The part's
        fields are null and its name goes into `timed_out`.
      - Any other error is raised as before.
      - Savepoints and `SET LOCAL` are safe under PgBouncer transaction mode, and pass the session-feature scan.
    - The helper `reporting_common.isolated(session, seconds, restore_seconds, fn)` is written once and used by both
      callers.
    - `GET /admin/data-health` therefore always answers 200, with the order block partial when a part ran out of time.
    - *Alternative:* a stored summary refreshed by the job (rejected for now: the live figures are wanted, and the
      measurement of decision 14 decides whether that is ever needed).
13. **`kind=order_checks` computes the checks once.**
    - The gaps route runs the `checks` part once.
    - `total` is `any`, or the count of the asked `check`. `counts` are its counts by check and flag.
    - The page of items is one statement, as today.
    - The `order_sections` block in the same answer reuses that `checks` result and runs only its `counts` part,
      isolated.
    - The list's own figures (the `checks` part and the page) stay under `_timed`: a cancelled statement is a 503
      `search_timeout` ("try again"), never a 500.
    - A timeout in the block's `counts` part only nulls those fields; the list stands.
    - `check_rows` keeps its signature for the CLI, built on the same single pass.
14. **Measured, not assumed.** After the backfill (row 250's version 1 readings, if they exist on dev when this row is
    built, else at this row's deploy), the developer or integrator records the time of each part with
    `EXPLAIN (ANALYZE, BUFFERS)` on the dev database. That is: the two `counts` statements, the `checks` statement,
    one `order_checks` page, each light set, and the full check.
    - Expected: each part under 10 s at about 260,000 readings, and the light run's sets under 1 s.
    - A part above its budget is recorded with its plan. The follow-up (a stored summary or an index) is a new row for
      the owner. It is not built here.

### E. The Orders list (points 4 and 7)

15. **The server names the reading's state.**
    - Each `OrderOut` gains `reading_state`, one of:
      - `read`: a current reading exists and the caller may open the PDF;
      - `not_read_yet`: text pending, or extracted and not read yet;
      - `scanned`: `text_status = none`;
      - `text_failed`: `text_status = failed`;
      - `reading_failed`: an open `order_parse` failure and no current reading;
      - `withheld`: the caller lacks `documents.view` in every membership, or fails `visibility.can_view_document`
        for the order's PDF;
      - null when the order has no stored PDF.
    - `withheld` is decided first, so a caller who may not open the PDF learns nothing about its text.
    - It is computed in `order_sections.brief` in the same single query: the document rule as one condition for the
      page, the open-failure probe by the unique `(kind, ref)` index.
    - The 404 `no_reading` of the sections route also carries `reading_state`.
    - **The portal** (`Orders.tsx`, `OrderSays.tsx`) uses `reading_state` in place of its own `documents.view` test:
      - `read`: "What the Order Says" as today;
      - `not_read_yet`: "Not Read Yet";
      - `scanned`: "Scanned, Not Read";
      - `text_failed`: "Text Could Not Be Read", the Documents tab's wording, with the note "The text of this order
        could not be taken from its PDF.";
      - `reading_failed`: "Not Read Into Parts", with the note "This order's text could not be read into its parts;
        it is listed for the administrators.";
      - `withheld`: the court's next-date sentence alone, as for a caller without `documents.view` today.
      - Every state still shows the next-date sentence. Texts go in `lib/messages.ts` in Title Case.
    - *Alternative:* keep the client-side test and add `text_failed` only (rejected: the client cannot know the
      document rule, and visibility is the server's job).
16. **Tests deny the document rule for real (point 7).** One login holds two memberships:
    - membership A sees the case and does not hold `documents.view` (its user type or the membership's functions
      without it, by whichever per-membership means the test helpers offer);
    - membership B holds `documents.view` in an office that does not see the case.

    `access.has` passes and `can_view_document` fails. The list gives `reading` null with `reading_state` `withheld`,
    and the sections route answers 404 `not_found`.
    - *Alternative:* monkeypatching `can_view_document` (rejected: the list uses `document_visible_condition` in SQL,
      not the function, so a patch would test neither).

### F. Measurements and documentation (point 5)

17. **The design note of row 250 gains a "Measurements" section**, appended by the developer as its Deviations were,
    with the date:
    - **Citations per reporter pattern**: citations (sum of `count`) and orders, over the current readings, by
      `facts.judgments[].reporter`.
      - A pattern with no citation is listed and kept: it reads nothing wrongly, and decision 17 of row 250 limits
        adding patterns, not keeping them.
    - **Table size**: `pg_total_relation_size`, `pg_relation_size`, the TOAST and index sizes of `order_sections`,
      the row count by `parser_version` and current or replaced. Recorded after the version 1 backfill if it ran, and
      again after this row's version 2 backfill.
    - The `schema.md` sentence "about 0.4 to 0.6 GB per parser version (estimate …)" is replaced by the measured
      figure.
    - **The order used for Annexure E**: the masked fixture `backend/tests/fixtures/orders/final_directions.txt`, a
      final order of 3 pages with one direction to the State and one act cited, read by the real parser.
      - **Change to decision 25 of row 250, for the owner's confirmation:** the unmasked source order is not named
        by its CNR or case number anywhere in the repository. Naming it would undo the masking the owner asked for
        (every personal name, address and the CNR and case-number digits). The fixture is the reproducible source.
    - The measurements of decisions 3, 4, 8 and 14.
18. **Documentation by the scribe.**
    - The decisions log gets an entry.
    - Runbook section 25:
      - the deploy has no migration, then the version 2 backfill;
      - the daily full check at 01:30 IST;
      - `aslms orders parse --full` after any manual re-extraction;
      - the reading states;
      - `ORDER_SECTIONS_STATUS_TIMEOUT_SECONDS`.
    - In `docs/software-documentation/build.js`, Annexure E's "version 1 here" becomes "version 2 here". Section 6.5
      gains one sentence on the daily check of changed texts. The version goes to 1.10 with a line in the version
      table, and the document is regenerated.
    - `.env.example` gains the new setting.

## Data
**No migration, no new table, column, index or reference code.**

`schema.md`, the `order_sections` paragraph (Group 6), changes in text only (scribe, no migration):
- "Size on the dev data: about 0.4 to 0.6 GB per parser version (estimate; the build report gives the measured size)"
  becomes the measured figure of decision 17.
- Add after "All offsets are 0-based code-point offsets …": "A reader of `src` spans first checks that the SHA-256 of
  the `document_text.full_text` it reads equals the row's `text_sha256` and treats a mismatch as no reading
  (`order_sections.src_text`; design `order-sections-review-advisories`, decision 11). A changed text is found by that
  hash in the job's daily full check, not by timestamps (decision 8)."

`job_runs` rows of job `order_sections` gain the integer counters `version_clear`, `full_check_on` (`YYYYMMDD`),
`full_check`, `full_check_found` and `failures_resolved` (jsonb, free keys today). `source_failures` kind `order_parse`
is unchanged.

## Services

**`services/order_parse_rules.py`:**
- `PARSER_VERSION = 2`;
- `LINKED_BLOCK_MAX_LINES = 40`, or the measured value of decision 3, with its one-line comment naming the measured
  longest block.

**`services/order_parse.py`:**
- `locate`: the bounded end of the last linked block (decision 3), applied only when neither another `Linked Case :`
  line nor the coram bounds it.
- `PageMap.page`: the count-back before the first marker (decision 4).
- The invariants of row 250 still hold and are asserted again. Linked `src` spans now also lie before the body's
  first paragraph in a `whole` reading.

**`services/order_sections.py`:**
- `FULL_CHECK_IST = time(1, 30)`.
- `candidates(session, *, batch, order_id=None, full=False, retry=False)`:
  - light sets 1 and 4 always (set 4 behind the gate unless `full`);
  - with `full`: sets 2, 3 (hash, keyset pages of 20,000) and 5;
  - with `retry`, and only when the open-failure probe finds a row: the same sets again for orders with an open
    `order_parse` failure;
  - with `order_id`, every set and the retry pass for that order.
- `read_batch(session, *, batch=None, order_id=None, dry_run=False, full=False, retry=False, gates=None)`:
  - as today, plus the logging of decision 9 (first failure with traceback, retries one warning line);
  - with `full`, `resolve_stale_failures` (decision 10);
  - returns the counters including the gate counters of decision 7.
- `run_job`: reads the previous run's counters, decides the gates and whether the full check is due, calls
  `read_batch`, and writes the counters forward.
- `backfill`:
  - light batches until a light batch claims nothing;
  - then full batches with the retry pass until a batch claims nothing, or reads nothing and holds only retries (the
    stop rule of deviation 14);
  - one commit per batch as today. The full sets' scan is paid only while they find work, normally once at the end.
- `resolve_stale_failures(session) -> int` (decision 10).
- `src_text(reading, full_text, span) -> str | None` (decision 11).
- `status(session, *, timeout_s, restore_s, checks=None) -> dict`: the three parts of decision 12. `checks` passes a
  result already computed by the gaps route.
- `checks_pass(session) -> dict`: the one `checks` statement (decision 12).
- `check_rows(session, *, check, limit, offset, pass_=None)`: total and counts from `checks_pass`, items from the page
  statement (decision 13).
- `brief(...)` also returns `reading_state` for every order id asked, including those with no reading (decision 15).
- `sections_out`: the 404 `NoReading` carries `reading_state`.
- No audit row and no event, as decision 22 of row 250. No NAPIX, SourceTrace or model call.

**`services/reporting_common.py`:**
- `isolated(session, seconds, restore_seconds, fn, *, part) -> (value | None, timed_out: bool)` (decision 12).

**`services/data_health.py`:**
- `snapshot` calls `order_sections.status(session, timeout_s=settings.order_sections_status_timeout_seconds,
  restore_s=settings.report_statement_timeout_seconds)`.

**`services/data_load.py`:**
- `gaps` for `kind=order_checks` runs `checks_pass` once under `_timed`, the page under `_timed`, and the block's
  `counts` part isolated (decision 13).

**`services/case_detail.orders`:**
- each item gains `reading_state` from `brief`.

**`core/config.py`:**
- `order_sections_status_timeout_seconds: int = Field(10, ge=1, le=60)` (`ORDER_SECTIONS_STATUS_TIMEOUT_SECONDS`),
  with a line in `.env.example`. No secret.

**CLI `aslms orders`:**
- `parse --full` (one batch with the full check and retries now);
- `status` prints the new block, `timed_out` included;
- `show` uses `src_text` (decision 11).

**Portal (`frontend/`):**
- `components/case/Orders.tsx` and `OrderSays.tsx`: the states of decision 15, and the client-side `documents.view`
  test removed.
- `components/data/ProblemsAndFixes.tsx`:
  - the "n orders read, n waiting" line is shown only when `read` and `waiting` are present;
  - when `timed_out` is not empty, one muted line: "Some counts took too long and are not shown. Try again in a
    moment.";
  - Data Gaps keeps its table and paging.
- `lib/messages.ts`: the new texts in Title Case. `lib/api/schema.d.ts` and `openapi.json` are regenerated.

## API
All changes are read-only. No new route and no new function.

- **`GET /cases/{ref}/orders`** (unchanged gate: `Permission.CASES_VIEW_SCOPE` or `Permission.CASES_VIEW_ALL`;
  `require_visible`).
  - Each `OrderOut` gains `reading_state: Literal["read", "not_read_yet", "scanned", "text_failed",
    "reading_failed", "withheld"] | None` (decision 15).
  - `reading` stays as today: null unless `reading_state` is `read`.
- **`GET /cases/{ref}/orders/{order_id}/sections`** (unchanged gates: `Permission.CASES_VIEW_SCOPE` or
  `Permission.CASES_VIEW_ALL` at the route, then `Permission.DOCUMENTS_VIEW` and `can_view_document` in the service).
  - The 404 `no_reading` detail gains `reading_state` beside `text_status`.
  - The 404 `not_found` for a failed document rule is unchanged, and now tested (decision 16).
- **`GET /admin/data-health`** (unchanged gate `health_reader`: `Permission.REPORTS_STATE`,
  `Permission.ADMIN_NAPIX_REFETCH`, `Permission.ADMIN_MASTERS_SYNC`).
  - `OrderSectionsStatusOut` changes:
    - `orders_with_text`, `read`, `waiting`, `by_layout`, `by_form`, `procedural`, `registrar`, `with_outcome`,
      `with_directions`, `distinct_bodies`, `flags` and `checks` become nullable;
    - new `timed_out: list[Literal["counts", "checks"]]` (default `[]`);
    - new `full_check: {last_on: date | None, found: int | None}`;
    - `waiting` now counts sets 1 and 4 only.
  - Always 200 when the order block runs out of time; counts only, as before.
- **`GET /admin/data-load/gaps`** (unchanged gate `data_load.READERS`: `Permission.ADMIN_DATA_LOAD`,
  `Permission.REPORTS_STATE`, `Permission.ADMIN_NAPIX_REFETCH`, `Permission.ADMIN_MASTERS_SYNC`).
  - For `kind=order_checks`, `total` and `counts` come from the one checks pass.
  - `order_sections` is the block of decision 13, possibly partial.
  - 503 `search_timeout` when the list's own figures run out of time, as today; never a 500.

## Jobs
- **`order-sections`** (unchanged beat: `crontab(minute="3-59/5")`, task `aslms.order_sections_read`, scheduler
  process, `ORDER_SECTIONS_BATCH`).
  - Light every run: set 1, and set 4 behind its gate.
  - The full check in the first run at or after 01:30 IST each day, repeated while it fills the batch: sets 2, 3 by
    hash and 5, the retry pass, and the stale failures resolved.
  - One `job_runs` row per run, with the counters of decision 7.
  - No `fetch_queue` row, no NAPIX call.
- **Backfill** after the deploy (owner-run): `docker compose exec api aslms orders parse --backfill`. It re-reads every
  order at version 2: about one to two hours, resumable, one commit per batch.

## Tests

Unit (`backend/tests/unit/test_order_parse.py`, `test_order_parse_rules.py`). Two new masked fixtures, under the rules
of decision 24 of row 250:
- `off_template_linked.txt`: a `whole` order with two `Linked Case :` blocks and no coram;
- `first_page_unmarked.txt`: the first page printed without a marker, then `Page No.# 2/3`.

The tests:
- `test_linked_block_in_whole_reading_ends_after_its_advocates_run`: the last block's `src` ends at its last advocates
  line, and no body paragraph lies inside it.
- `test_linked_block_ends_at_heading_or_judgment_date_line`
- `test_linked_block_without_advocates_cut_to_its_line_with_null_title` (the `LINKED_BLOCK_MAX_LINES` cap)
- `test_template_readings_keep_version_1_linked_spans` (every fixture: `linked_cases` equal to the version 1 output)
- `test_page_before_first_marker_counts_back_by_form_feeds_never_below_1`
- `test_pages_without_markers_and_after_first_marker_unchanged`
- `test_parser_version_is_2`
- The invariants test of row 250 runs over the new fixtures.

Database (`backend/tests/db/test_order_sections.py`):
- `test_light_run_queries_only_sets_1_and_4` (statement count by a SQLAlchemy event: no set 2, 3, 5 or retry query)
- `test_set_4_gate_skipped_after_a_clear_run_and_reopened_by_a_version_bump`
- `test_full_check_once_a_day_after_0130_ist_repeated_while_batch_full`
- `test_full_check_runs_set_4_without_the_gate`
- `test_same_text_reextracted_writes_no_new_row` (newer `updated_at`, same characters)
- `test_changed_text_committed_after_the_reading_is_found_by_hash` (the race: an older `updated_at`, different text →
  replaced `text_reextracted`)
- `test_sql_text_hash_equals_python_hash_on_assamese_text_and_form_feeds`
- `test_failing_order_retried_only_in_full_check_backfill_and_order_option`
- `test_first_failure_logs_traceback_retries_log_one_line` (`caplog`)
- `test_open_failure_resolved_when_the_text_is_gone` (`failures_resolved`)
- `test_backfill_light_then_full_and_ends_with_only_failing_orders`
- `test_src_text_returns_none_when_text_hash_differs`
- `test_status_part_timeout_gives_partial_block_and_outer_timeout_restored` (a `checks` statement made slow with
  `pg_sleep` under a 1 s budget; the next statement of the transaction runs under the report timeout)
- `test_status_counts_and_checks_equal_the_version_1_definitions` (on the fixtures, the single pass gives the same
  numbers as `check_columns`)

API (`backend/tests/db/test_api_order_sections.py`):
- `test_orders_list_reading_state_for_each_state` (`read`, `not_read_yet` for pending and extracted, `scanned`,
  `text_failed`, `reading_failed`, `withheld`, null without a PDF)
- `test_withheld_decided_before_text_states` (a caller without `documents.view` on a failed text gets `withheld`)
- `test_document_rule_denied_hides_reading_on_list_and_404_on_sections` (the two-membership login of decision 16)
- `test_no_reading_404_carries_reading_state`
- `test_data_health_answers_200_when_order_checks_time_out` (`timed_out == ["checks"]`, every other block present)
- `test_gaps_order_checks_total_and_counts_from_one_pass`
- `test_gaps_list_stands_when_block_counts_time_out`
- `test_gaps_list_timeout_is_503_search_timeout_not_500`

Frontend (`components/case/case.test.tsx`, `components/data/data.test.tsx`):
- each `reading_state` shows its title and note, with the next-date sentence;
- `withheld` shows the sentence alone;
- no client-side `documents.view` decision is left in `OrderReading`;
- Order Reading Checks with `timed_out` shows the muted line and hides the missing counts;
- Title Case and label guards;
- the uicheck states of row 250 still pass, plus one state for `text_failed`.

Policy: the session-feature scan passes (savepoints and `SET LOCAL` only). `ruff check` clean, `pytest -q` green,
frontend `npm test` and lint green.

## Verification
1. **Before the deploy, on dev, read-only** (if row 250's backfill has run). The integrator records the times of
   decision 14 and the measurements of decision 17. `aslms orders status` answers, and `timed_out` is empty or names
   the slow part.
2. **Deploy** (no migration):
   - `docker compose build` from a clean worktree of `main`;
   - recreate the app services with `--no-deps --force-recreate api worker worker2 scheduler web`, the court-data
     switch carried on the `up`;
   - `aslms ops preflight` passes.
   - **Owner's choice of timing:** if row 250 has not been deployed by then, the two deploy together. Migration 0038
     goes first with the `migrate` step, and one backfill reads every order at version 2 directly. That saves one
     re-read and one copy of about 260,000 rows.
3. `docker compose exec api aslms orders parse --backfill`. Then `aslms orders status`:
   - `parser_version` 2;
   - `read` equals `orders_with_text`;
   - `waiting` 0;
   - `failed` 0, or each failure listed in `source_failures`.

   `SELECT count(*) FROM order_sections WHERE parser_version = 1 AND replaced_at IS NULL` gives 0. No court call:
   the `napix_call_log` count does not change during the backfill.
4. **Linked cases.** Ten `whole` readings with linked cases, chosen by SQL. For each, `aslms orders show <order>` shows
   every linked `src` ending at the block's last advocates line, or cut to the `Linked Case :` line. Count, by SQL,
   the version 2 `whole` readings whose last linked `src` reaches the body's last 10% (expected 0), against the
   version 1 count.
5. **Pages.** For five orders whose first page has no marker, a paragraph on the first page reports page 1 and its
   `#page=1` link opens the PDF there.
6. **Job.**
   - The next light runs' `job_runs` counters show `version_clear: 2`.
   - The run at 01:33 IST shows `full_check: 1` and a `full_check_found` figure.
   - Later runs that day issue no set 2, 3 or 5 query (statement log, or the run time).
   - A failing order (if any) writes one log line a day.
   - An open failure whose order's text is gone is resolved.
7. **Data health.** `GET /admin/data-health` answers 200 and carries the order block. With
   `ORDER_SECTIONS_STATUS_TIMEOUT_SECONDS=1` set for one check run, it still answers 200 with `timed_out` listing the
   slow part (then the setting is put back).
8. **Portal** at `http://localhost:3000`:
   - an order whose text failed shows "Text Could Not Be Read";
   - an order not yet read shows "Not Read Yet";
   - a read order shows "What the Order Says";
   - an officer without `documents.view` sees only the court's sentence;
   - Problems and Fixes, Data Gaps, Order Reading Checks loads.
9. **Documentation.**
   - `docs/design/order-sections.md` has the Measurements section (citations per reporter, table size, Annexure E's
     source, the measurements of decisions 3, 4, 8 and 14);
   - `schema.md` has the measured size and the `src` rule;
   - `node docs/software-documentation/build.js` regenerates version 1.10 with "version 2 here".

## Open questions
None. Every point has a decision above. The owner confirms or changes these with the approval:
- **decision 17**, a change to decision 25 of row 250: the unmasked source of Annexure E is not named by CNR or case
  number in the repository, because that would undo the masking. The masked fixture is the named source.
- **decision 6**: texts that change (rare, by hand today) are re-read within a day by the 01:30 IST full check, not
  within 5 minutes. Every reader of `src` spans checks the text's hash first, so nothing is cited from a changed text
  meanwhile.
- **decision 15**: the two new plain-words states on the Orders tab, "Text Could Not Be Read" and "Not Read Into
  Parts".
- **Verification 2**: whether to deploy row 250 together with this row (one backfill) or separately (two re-reads).

## Deviations
Written by the developer, 16 Nov 2026.

1. **`LINKED_BLOCK_MAX_LINES` is 6,980.** Decision 3's rule (at or above the longest coram-bounded block, rounded up
   to a multiple of 10) on the dev data gives 6,980: the longest last linked block of a template reading has 6,971
   non-blank lines (median 35, p99 747). The cap therefore only stops a block that never ends; a cap of 40 would have
   cut 9 of the 13 affected orders for a long cause title. The measurements are in row 250's note, "Measurements".
2. **The check sub-select is fenced, not `LATERAL`.** The raw CNR and case-number mismatches and the common-order test
   are computed once per row in a sub-select over the current readings with `OFFSET 0` (which the planner never
   inlines), and the counts and the page read its columns. SQLAlchemy cannot compile a `LATERAL` select without a
   `FROM` of its own, and the fence gives the same "once per row".
3. **The full check is complete unless non-retry candidates filled the batch.** "A full check whose candidates filled
   the batch leaves the check due" counts the claimed orders less the retries, so a batch of failing orders alone does
   not keep the full check (and its scans) running every 5 minutes; the failing orders left over are retried the next
   day.
4. **Gates from the latest finished run.** `run_job` reads the counters of the latest run of the job that is not
   `running`: a run still going has no counters yet, and reading it would make an overlapping run start a second full
   check. A failed run still leaves no counters, so the next run starts with no gates, as decision 7 says.
5. **`full_check_found` is carried forward.** A light run writes the last full check's figure forward under the same
   key, so `status().full_check.found` reads the latest row only (one indexed row).
6. **`candidates` keywords.** Beside `full` and `retry`, `candidates` takes `version_gate` (set 4 skipped) and `info`
   (it fills `set4_short` and `full_found`), which `read_batch` turns into the counters of decision 7.
7. **Set 3's pages.** Each keyset page is two statements: the page's last reading id (an index walk), then the one
   hashing statement for the readings up to it, so each statement hashes at most 20,000 texts.
8. **`waiting`'s set 4 count.** The one pass over the current readings counts set 4 as the readings below
   `PARSER_VERSION` whose order's document is a court order with `text_status = extracted` and no open failure; it
   joins `orders` and `documents` but not `document_text`, so the pass reads no text.
9. **Logging.** A part of the status block left out by its timeout logs one warning line. When several orders share a
   text that fails, the first order's first failure logs the traceback and the others one line each.
10. **`aslms orders parse --full` writes no `job_runs` row**, as `parse` without `--backfill` writes none, so it does
    not move the next 01:30 check.
11. **Page links in "What the Order Says"** no longer test `documents.view` in the portal either: a reading is served
    only to a caller who may open the PDF.
12. **Measurements left to the deploy.** The dev database is at 0037 (row 250's 0038 is not applied there), so the
    table size, the times of decision 14 and the full check's time with the join to the readings are recorded by the
    integrator after the backfill (row 250's note, "Measurements"); `schema.md` keeps its size estimate until then.
13. **Documentation left to the scribe** (decision 18): the decisions log, runbook section 25 and the Software
    Documentation (Annexure E's "version 2 here", section 6.5, version 1.10).
