# Design: Document OCR — reading scanned orders, filings and images (and showing "scanned, not read" until then)

```
slug: document-ocr
status: approved
author: architect
date: 2026-10-20
approved_by: owner (nayanlhuzuri) on 2026-10-20
```

> **Owner's decision at approval (20 Oct 2026): option C — no OCR in Phase 1.** Build **Part 0 only**: the plain-words text labels ("Scanned, not read" and the others) on the Documents tab, the content-search note that scanned documents, images and old Word files are not searched, the `documents_text` block on `GET /admin/data-health`, and **PyMuPDF pinned below 2** with the test that importing it loads no onnxruntime. Do **not** build the OCR interface, migration 0021, the `ocr` service, Tesseract or the SourceTrace text reader. Option B (SourceTrace returns the text of court orders and filings it holds) is a parked follow-up, waiting for row 36; it is decided again after the pilot.


> **Blocked on one policy question for the owner** (see Open questions). The note is written so that every
> answer leads to a buildable design: Part 0 is built whatever the answer; Part A is built if the answer is
> "a local OCR engine is allowed"; Part B if the answer is "SourceTrace reads scanned court documents"; nothing
> more if the answer is "no OCR in Phase 1". The architect recommends **C now (Part 0 only), Part B once the
> SourceTrace API is documented** (decision 1).

## Context
Backlog row 23: "OCR for scanned PDFs and images (`text_status` `none` today), through a local engine or
SourceTrace if it offers one; until then the Case Assistant cannot read them". The independent audit of
18 Oct 2026 (`docs/audits/2026-10-18-independent-audit.md`, Area 4) lists "no OCR (row 23) — scanned orders show
nothing in the reading column (say 'scanned, not read')", and its owner decision 8 asks: "OCR for scanned orders
and filings: local engine, SourceTrace, or not in Phase 1".

What the plan says (`docs/Legal_Case_Monitoring_Portal_Plan.docx`):
- §5.6 / orders archive: "Text is extracted so orders can be searched by content"; "Court orders, and documents
  uploaded by users (court filings and internal documents), with extracted text and visibility settings". OCR
  and scanned documents are not mentioned anywhere in the plan.
- §3.2: "SourceTrace ... is used for the Case Assistant, all case research, and **reading court orders**". §8
  (data protection): "all AI work, case research and reading orders, is carried out on the in-house SourceTrace
  solution, so no case data is sent to any cloud AI service".
- §5.6 / §5.9: court orders and court filings are ingested into SourceTrace; "Departments' notes and internal
  documents are not sent to SourceTrace".
- Table 9 (phases): Phase 1 has "orders archive; case document upload; alerts for orders with specific dates;
  search"; SourceTrace ingestion is Phase 2, the Case Assistant Phase 3. OCR is in no phase.

What the rules say: CLAUDE.md "All AI goes through SourceTrace ... No cloud LLM, no local model" and "Never send
to SourceTrace: case notes or internal documents". The decisions log (25 Sep, "Superseded decisions") records
"AI: Ollama / local model and the in-portal knowledge repository are REMOVED". That removal was made over a
system that **did OCR with a local model**: the first system's `ocr_engine.py` (read only, in
`ASLMS-legacy/v1-legacy`) sent page images to an Ollama vision model (`qwen3-vl:8b`). Neither the plan nor the
log says whether a classic OCR engine such as Tesseract (whose recogniser since version 4 is a small LSTM neural
network running on the CPU, with no prompt and no generation) counts as a "local model". The plan's "reading
orders ... on SourceTrace" was written about understanding orders (next dates, research), not about turning
pixels into characters. **The plan and the log therefore do not answer the question**; the owner must.

What is in place:
- `services/text_extract.py` (design `documents-uploads`, decision 10): PDFs through `pymupdf`; a PDF averaging
  fewer than 20 non-space characters per page is `text_status = none`; DOCX through `zipfile`; DOC, JPEG and PNG
  are `none` at upload. `document_text` holds `full_text` and the `search_vector`; `GET /documents/search` and the
  case content search use it under the visibility rule.
- `services/next_dates.py` (design `next-date-extraction`): an order whose document is `none` reads `no_text` and
  becomes an *enter* item in the review queue (a person opens the order and enters the date). The owner's
  option B of 17 Oct makes a read date firm only when it equals the court's own date (`date_next_list` or a
  cause-list listing), so a misread date can never be firm on its own.
- The portal (design `portal-next-dates`): the Orders tab's reading column says "Could not be read (scanned
  copy)" for `no_text`, and the enter item says "This order is a scanned copy and could not be read — please open
  it and enter the next date". So the audit's remark is already met **for orders**. It is not met for documents:
  the Documents tab prints the raw value ("Text: none"), and the content search does not say that scanned
  documents are not searched.
- The SourceTrace connector (design `sourcetrace-connector`): the `SourceTraceConnector` protocol has only
  `ingest`; the query side is "added by the items that use it, when their shapes are known"; no real connector
  exists (row 36, waiting for the SourceTrace API documentation); `assert_sendable` lets through only court
  orders and clean, not-private court filings of cases with a CNR.

### The size of the problem, measured on the dev database (20 Oct 2026, read-only SELECTs)

| kind | documents | `extracted` | `pending` | `none` | `failed` |
|---|---:|---:|---:|---:|---:|
| `order` (court order PDFs) | 60,612 | 57,392 | 3,220 | **0** | 0 |
| `upload` (filings and internal documents) | 0 | — | — | — | — |
| `attachment` (note attachments) | 0 | — | — | — | — |
| `admin` (ticket files) | 0 | — | — | — | — |
| `causelist` (cause-list PDFs; read by the cause-list parser, never by text extraction; out of scope) | 7,188 | 0 | 0 | 7,188 | 0 |

- Orders: 301,840 order rows; 75,625 have a stored PDF (60,612 distinct files), 226,212 wait for download
  (the historical load), 3 are not available at the court.
- Characters per page of the 57,392 extracted order PDFs: none below 50; 34 between 50 and 100; 271 between 100
  and 200; 14,171 between 200 and 500; 41,515 between 500 and 1,000; 1,401 above 1,000. **Gauhati High Court
  orders are born-digital (typed, digitally signed).**
- Pages: of 262,196 pages, 24 pages in 8 PDFs carry fewer than 20 characters. 23 of them hold only a page header
  ("Page No.# 231/244") and one image — a scanned annexure page inside a typed order (11 inspected with
  `pymupdf`, all one image each); 1 is a short last line ("...nt Advocates.").
- Next-date readings: 71,878 orders read (40,729 `specific`, 17,738 `period`, 8,692 `unclear`, 4,719 `none`),
  **0 `no_text`**; 229,962 not read yet (no stored PDF or text pending).
- Uploads cannot be measured: no department has uploaded anything on the dev database. Court filings (writ
  petitions with annexures, affidavits) are where scans are expected, and every JPEG / PNG upload is `none` by
  construction. The pilot will give the real number; Part 0 puts it on the data-health screen.

### A finding about the current image (relevant to the same question)
`pyproject.toml` asks for `pymupdf>=1.24` with no upper bound, so the rebuild of 19 Oct installed **PyMuPDF
2.0**, which now requires `onnxruntime` (68 MB), `pymupdf_layout` and `pymupdf4llm`, and ships seven ONNX
neural-network files (layout and table models, about 21 MB) under `pymupdf/layout/resources/onnx/`. Verified in
the `api` container: `import pymupdf` alone opens three `onnxruntime.InferenceSession`s
(`layout_rf2.4.1+imf1.onnx`, `feature_imf1.onnx`, `table_grid_model_v4_ep.onnx`), in every process that imports
it (api, worker, scheduler). Our code uses only `page.get_text("text")` and needs none of it. Whatever the owner
answers about "local model" applies to these files too (decision 2).

Not covered: `.doc` text (an extractor for the old Word format is not OCR; it stays `none`, labelled
separately); handwriting; OCR of image pages inside an otherwise typed PDF (decision 9); sending OCR text to
SourceTrace (never: SourceTrace receives the document bytes as today); the Case Assistant (row 14); the real
SourceTrace connector (row 36); anything in row 94 (`pre-pilot-hardening`).

## Decisions

### Common to every answer

1. **Recommendation: answer C for Phase 1 (Part 0 only), then Part B when SourceTrace is documented.** Reasons:
   (a) the measured problem for orders is nil — 0 scanned among 57,392 order PDFs read, 0 `no_text` among 71,878
   readings — so OCR would not improve the next-date reader or order search today; (b) uploads, where scans are
   likely, are not measurable yet and the pilot will size them through Part 0's counts; (c) OCR is in no phase
   of the plan, and Phase 1 lists search and the orders archive, both working; (d) Part A needs the owner to
   read "no local model" narrowly, a rule written when the owner removed a system that did OCR with a local
   model; (e) Part B stays inside the plan's own words ("reading court orders" on SourceTrace) and, as designed
   here, sends nothing that is not already sent. Alternatives: A now (rejected as a recommendation: it spends
   an image change, a new service and CPU on a problem measured at zero for orders, and depends on a rule
   reading only the owner can give); B now (impossible to finish: no SourceTrace endpoint is known, row 36).
   This is a recommendation; the owner decides (Open questions).
2. **PyMuPDF is pinned below 2 (`pymupdf>=1.24,<2`) in Part 0**, and a test proves `import pymupdf` loads no
   `onnxruntime`. Reasons: the code needs none of the 2.0 layout models; they are an unapproved local neural
   network if the owner reads the rule broadly; they add about 90 MB and model sessions to every process; and an
   unbounded major version changed the dependency tree silently. The developer compares `get_text("text")` of
   1.x and 2.0 on 200 stored orders (same text expected, differences listed in the report). Alternative: keep
   2.0 (only if the owner's answer allows local neural networks and wants 2.0 for another reason). Flagged for
   the owner as part of the question.
3. **"Scanned, not read" is said plainly everywhere a document's text matters (Part 0).** Documents tab: the
   text line becomes a label from `text_status` and `mime` — `pending` "Being read", `extracted` "Searchable",
   `none` on a PDF / JPEG / PNG "Scanned, not read", `none` on a DOC "Old Word format, not read", `failed`
   "Text could not be read". The content search screen says under the box: "Scanned documents, images and old
   Word files are not searched by their content." The Orders tab and the review queue already say "Could not be
   read (scanned copy)" (no change). Under A or B, an OCR'd document reads "Searchable (read from a scan; may
   contain errors)". Alternative: a badge only on scanned rows — rejected, the raw word "none" stays elsewhere.
4. **The data-health screen counts documents without text (Part 0)**, so the owner sees the size during the pilot:
   a `documents_text` block in `GET /admin/data-health` — per kind (`order`, `upload`, `attachment`) the counts of
   `pending`, `extracted`, `failed` and `none`, `none` split into `scanned_pdf`, `image` and `doc` by `mime`.
   Totals only, no case data, so the existing `health_reader` rule suffices. Alternative: a report — rejected,
   the health screen is where the owner looks at data gaps.
5. **The next-date reader needs no change for OCR text.** The owner's two-source rule (17 Oct, option B) makes a
   read date firm only when it equals the court's own date, so an OCR misreading ("16.11" for "15.11") becomes a
   suggestion a person confirms, never an alert on its own. When OCR gives an order text, its orders still at
   `no_text` go back to `pending` (the same put-back as `aslms next-dates read --reread`, per order) and the
   five-minute reader reads them. Alternative: force review for every OCR reading — rejected, it would discard
   the agreement of two sources.

### If the answer is A (a local OCR engine is allowed) or B (SourceTrace reads scanned court documents)

6. **One OCR service, two engines behind one interface.** `backend/aslms/integration/ocr/` holds the `OcrEngine`
   protocol (`name`, `kind` = `local` | `sourcetrace`, `async def read(item) -> OcrResult`), `get_ocr_engine(settings)`
   and `FakeOcrEngine` (tests). Under A the implementation is `TesseractEngine` in the same package; under B it is
   `SourceTraceOcrEngine`, a thin adapter that calls the **SourceTrace connector** (decision 12), so every AI call
   still goes through the SourceTrace connector interface. `services/document_ocr.py` does eligibility, claiming,
   writing and counters for both. `OCR_ENGINE` in `.env` (`none` default, `tesseract`, `sourcetrace`) chooses;
   `none` makes the job a no-op. Alternative: two separate services — rejected, the status, the text write, the
   order put-back and the screens are the same.
7. **OCR text goes where extracted text goes.** A successful read writes `document_text` (`full_text`,
   `page_count`, `search_vector`), sets `text_status = extracted`, `text_source = ocr`, `ocr_status = done`,
   `ocr_engine`, `ocr_done_at`, `ocr_pages`. Nothing else changes: the content search and its snippets are
   restricted by `document_visible_condition` exactly as today, so OCR text of a `private_to_office` document is
   seen only by those who can see the document. A read that yields fewer than 20 non-space characters per page
   is `ocr_status = empty` (text kept in `document_text`, `text_status` stays `none`, the label stays "Scanned,
   not read").
8. **Which documents each engine may touch** (enforced in the claim query and again by `assert_ocr_allowed`
   before the engine is called, and for B by a CHECK):
   - common: `text_status = none`, `ocr_status = pending`, `archived_at IS NULL`, scan `clean` or `skipped`,
     `mime` PDF / JPEG / PNG, `kind` `order` / `upload` / `attachment` (never `causelist`, never `admin`);
   - A (`local`): all of those, internal documents and note attachments included — nothing leaves the server;
   - B (`sourcetrace`): only documents that SourceTrace already holds: `sourcetrace_status = ingested`, so the
     set is exactly what `assert_sendable` allowed (court orders and clean, not-private court filings of cases with
     a CNR), and **no bytes are sent for OCR** — the engine asks SourceTrace for the text of its own reference.
     Internal documents, note attachments, private filings and filings of provisional cases are never read
     under B; they stay "Scanned, not read" and are counted as "not eligible" on the health screen. The CHECK
     `ck_documents_ocr_internal_local` makes a SourceTrace engine name on an internal document impossible.
9. **Whole documents only.** OCR runs on documents whose `text_status` is `none`; image pages inside an
   otherwise typed PDF (23 pages in 8 of 60,612 order PDFs) are not read. Alternative: OCR every page under 20
   characters that holds an image — rejected for now, the cost (rewriting already extracted text, a page-level
   status) outweighs 23 annexure pages; it can be a follow-up if uploads show many mixed PDFs.
10. **Background work with limits and a visible status.** Celery task `aslms.ocr_pending` (beat every 10 minutes),
    a batch of `OCR_BATCH` = 10 documents claimed with `FOR UPDATE SKIP LOCKED`, one savepoint per document, a
    run budget of `OCR_RUN_SECONDS` = 480; at most `OCR_MAX_PAGES` = 300 pages read per document (`ocr_pages`
    records how many; the label adds "first 300 pages read" when the document is longer). A failure increments
    `ocr_attempts`, sets `ocr_next_at` (15 min, 2 h, 12 h) and after `OCR_MAX_ATTEMPTS` = 3 sets `failed` with a
    `source_failures` row (`kind = ocr`, `ref = <document id>`); never lost. Uploads are queued on extraction
    (`text_extract` sets `ocr_status = pending` instead of `not_needed` when the result is `none`, the mime is
    eligible and `OCR_ENGINE` is not `none`); `aslms documents ocr --queue-existing` queues the documents that
    were `none` before. Alternative: OCR in the upload request — rejected, the API must never run a slow parser
    on a hostile file.
11. **Audit.** OCR is system work like text extraction: no `audit_log` row per document; counters in
    `job_runs`. A person's action is audited: `aslms documents ocr --retry-failed | --document REF` writes
    `document.ocr_requeued` (actor `cli`, the count or the document). Changing `OCR_ENGINE` is a deployment
    setting in `.env`, not an application action.

### Only if the answer is A

12. **Tesseract 5 through PyMuPDF, in its own image target and service.** `TesseractEngine.read` renders each page
    and calls `Page.get_textpage_ocr(language=OCR_LANGUAGE, dpi=OCR_DPI, full=True)` then
    `page.get_text(textpage=tp)`; JPEG and PNG are opened with `pymupdf.open(stream=..., filetype=...)` and read
    the same way. PyMuPDF already has this call, so **no new Python dependency**; the engine needs only the
    Debian packages `tesseract-ocr` (5.5 in trixie) and `tesseract-ocr-eng` (Gauhati High Court documents are in
    English; `asm` / `hin` packs exist if the owner ever asks). `OCR_DPI` = 300, `OCR_LANGUAGE` = `eng`,
    `OMP_THREAD_LIMIT=1`, a per-page timeout of `OCR_PAGE_TIMEOUT_SECONDS` = 60 (the page is skipped and
    counted). `ocr_engine` records `tesseract-<version>` read once at start.
    - **Image**: `backend/Dockerfile` becomes three stages — `app` (today's content), `ocr` (`FROM app`, installs
      the two packages as root, back to uid 10001, `TESSDATA_PREFIX` set) and a final unnamed `FROM app`, so every
      existing service builds exactly today's image and only the new service builds `target: ocr`. Expected
      size: about 30–50 MB on top of the 914 MB backend image (estimate; the developer records the measured
      `docker images` difference).
    - **Service**: Compose `ocr`, the same environment as `worker`, store mounted read-only
      (`./data/store:/data/store:ro`), `command: celery -A aslms.jobs.celery_app worker -Q ocr --concurrency 1`,
      `cpus: "1.0"`, `mem_limit: 1g`, the shared hardening and logging blocks. `task_routes` sends
      `aslms.ocr_pending` to the `ocr` queue, so the `scheduler` worker (default queue, concurrency 1, which also
      sends e-mail) is never held up by OCR — the audit's point about a slow extraction batch delaying mail.
      The redis exporter also watches the `ocr` list; `JobLate` gains `ocr-pending`.
    - **CPU**: Tesseract's LSTM recogniser at 300 dpi takes roughly 1–4 seconds per A4 page on one core
      (estimate; verification step A3 measures 20 real pages). One core therefore reads about 1,000–3,000 pages
      a day if kept busy; a 40-page scanned writ petition takes 1–3 minutes. With 0 scanned orders today, the
      load is the pilot's scanned uploads only.
    - **Quality**: good on clean typed scans; weak on phone photographs, skewed or faint copies; handwriting not
      read. The "may contain errors" label and the two-source next-date rule cover this.

### Only if the answer is B

13. **SourceTrace returns the text of a document it holds; the portal never sends anything for OCR.** The connector
    gains an optional capability, `SourceTraceTextReader` (a second `runtime_checkable` protocol beside
    `SourceTraceConnector`): `async def document_text(self, reference: str) -> DocumentTextResult` (`text`,
    `page_count`, `raw`), raising `SourceTraceUnavailable` (retried), `SourceTraceRejected` (failed at once) or
    the new `SourceTraceNoText` (`ocr_status = empty`). `FakeSourceTrace` implements it with scripted texts.
    `SourceTraceOcrEngine` uses it only when `get_connector(settings)` returns an implementation that has it;
    otherwise the job counts the documents as waiting and does nothing. The real call is written by row 36 (or
    a follow-up) **once the SourceTrace documentation shows such an endpoint**; if SourceTrace instead returns
    text in the ingestion answer, the adapter reads `IngestResult.raw` the same way and no second call exists —
    the developer of row 36 records which. If SourceTrace offers neither, answer B cannot be built and the
    owner chooses again between A and C.
    - **Cost**: no image change, no new service; the job runs in the `scheduler` worker (network-bound, small
      batches, the run budget of decision 10); one SourceTrace call per scanned court document already ingested.
    - **Limits**: nothing until a real connector exists (`SOURCETRACE_ENABLED` and row 36); internal documents,
      note attachments and private filings are never read.

## Data

### Part 0
No table, column or reference code. No migration.

### Parts A and B (one migration, `0021_document_ocr.py`, or the next free number when built; applied migrations untouched)
Paragraph for `docs/schema/schema.md`, appended to the `documents` row:

> (document-ocr, migration 0021) `text_source` (native enum `text_source`: `text_layer` / `docx` / `ocr`; NULL
> unless `text_status = 'extracted'`; the way the stored text was obtained), `ocr_status` (native enum
> `ocr_status`: `not_needed` / `pending` / `done` / `empty` / `failed`; NOT NULL default `not_needed`),
> `ocr_engine` (varchar 40 NULL; the engine's `name`, e.g. `tesseract-5.5.0` or the SourceTrace connector's
> name), `ocr_attempts` (smallint NOT NULL default 0), `ocr_next_at` (timestamptz NULL; not claimed before
> this), `ocr_done_at` (timestamptz NULL), `ocr_pages` (integer NULL; pages read). CHECKs
> `ck_documents_text_source` (`(text_status = 'extracted') = (text_source IS NOT NULL)`),
> `ck_documents_ocr_kind` (`ocr_status = 'not_needed' OR kind IN ('order', 'upload', 'attachment')`),
> `ck_documents_ocr_done` (`ocr_status <> 'done' OR (ocr_engine IS NOT NULL AND ocr_done_at IS NOT NULL AND
> text_source = 'ocr')`), `ck_documents_ocr_internal_local` (`doc_group <> 'internal' OR ocr_engine IS NULL OR
> ocr_engine NOT LIKE 'sourcetrace%'`: an internal document is never read by SourceTrace). Partial index
> `ix_documents_ocr_due` (`ocr_next_at`) WHERE `ocr_status = 'pending'`. The `ocr_*` columns and
> `text_source = 'ocr'` are written only by `services/document_ocr.py`; `text_source` `text_layer` / `docx` by
> `services/text_extract.py` (design `document-ocr`).

And to the `document_text` row: "Written only by the text-extraction job and the OCR job (`document-ocr`)."

Migration content: the two native enums; the seven columns; the four CHECKs and the index; backfill in the same
migration — `text_source = 'text_layer'` for `extracted` PDFs, `'docx'` for `extracted` DOCX (57,392 rows on the
dev database), `ocr_status = 'pending'` for `none` documents of an eligible kind and mime (0 on the dev
database). Downgrade drops them. No new table: per-attempt history is `job_runs` counters and `source_failures`
(alternative: a `document_ocr_runs` append-only table — rejected, the document row records the engine and the
result, and failures are already never lost).

No `ref_*` code: the two enums are lifecycle states, like `text_status` (DB_STANDARD: native enums for states the
code branches on).

## Services

### Part 0
- `services/data_health.py`: `documents_text(session) -> dict` (one grouped count over `documents` by `kind`,
  `text_status` and `mime`; kinds `order`, `upload`, `attachment`); `snapshot` adds `"documents_text"`. Under A /
  B it also returns `ocr`: engine, `pending_eligible`, `pending_not_eligible`, `done`, `empty`, `failed`,
  `last_run`.
- `pyproject.toml`: `pymupdf>=1.24,<2` (decision 2).
- Portal (`frontend/`): `lib/messages.ts` gains `textLabels` and the search note; `components/case/Documents.tsx`
  uses `textLabel(doc)` instead of the raw value; `components/search/TextSearch.tsx` shows the note;
  `components/data/Health.tsx` shows the `documents_text` block (and `ocr` under A / B).

### Parts A and B
- `backend/aslms/integration/ocr/__init__.py`, `engine.py`: `OcrItem` (`document_id`, `content` (A) or
  `reference` (B), `mime`, `page_limit`), `OcrResult` (`text`, `pages_read`, `pages_skipped`, `engine`),
  `OcrUnavailable`, `OcrRejected`, `OcrNoText`; the `OcrEngine` protocol; `get_ocr_engine(settings)` (`none` →
  `None`); `fake.py` `FakeOcrEngine` (scripted outcomes `ok`, `empty`, `unavailable`, `rejected`, `timeout`).
  Under A `tesseract.py` `TesseractEngine`; under B `sourcetrace.py` `SourceTraceOcrEngine` (wraps
  `get_connector(settings)`; the only module of the OCR package that touches SourceTrace, and only through the
  connector).
- `services/document_ocr.py`:
  - `eligible_condition(engine_kind)` and `assert_ocr_allowed(doc, engine_kind)` (decision 8; raises
    `NotEligible`);
  - `claim_due(session, *, engine_kind, document_id=None) -> Document | None` (`FOR UPDATE OF documents SKIP
    LOCKED`, oldest first, due by `ocr_next_at`);
  - `apply_result(session, doc, result)` (decision 7: `document_text`, statuses, then `requeue_orders(session,
    doc)` — orders with `document_id = doc.id` and `next_date_status = 'no_text'` back to `pending`,
    `next_date_rules_version` NULL; returns the count);
  - `record_failure(session, doc, exc)` (back-off, `failed` after the limit, `source_failures` `kind = ocr`;
    resolved on a later success);
  - `run(session, store, engine, *, batch, run_seconds) -> dict` counters `claimed`, `done`, `empty`, `failed`,
    `retry_later`, `orders_requeued`, `pages`;
  - `queue_existing(session) -> int`, `requeue(session, actor, *, retry_failed=False, document_id=None) -> int`
    (audited `document.ocr_requeued`).
- `services/text_extract.py`: sets `text_source` on `extracted`; on `none` sets `ocr_status = pending` when the
  kind and mime are eligible and `OCR_ENGINE` is not `none`, else `not_needed`.
- `services/documents.py` and `services/case_detail.py`: document and order items gain `text_source` and
  `ocr_status`.
- `core/config.py`: `ocr_engine` (`none` | `tesseract` | `sourcetrace`, default `none`), `ocr_batch` (10),
  `ocr_run_seconds` (480), `ocr_max_pages` (300), `ocr_max_attempts` (3), `ocr_dpi` (300), `ocr_language`
  (`eng`), `ocr_page_timeout_seconds` (60); listed in `.env.example` (none is a secret).
- CLI: `aslms documents ocr [--queue-existing] [--retry-failed] [--document REF] [--batch N] [--dry-run]`.
- Under B, `integration/sourcetrace/connector.py` gains `DocumentTextResult`, `SourceTraceNoText` and the
  `SourceTraceTextReader` protocol; `fake.py` implements `document_text` with `script_text(...)`.

## API
No new endpoint. All changes are additions to existing responses; the visibility rules do not change.

| Method and path | Function required (`Permission`) | Change | Part |
|---|---|---|---|
| `GET /admin/data-health` | `health_reader`: `REPORTS_STATE` or `ADMIN_NAPIX_REFETCH` or `ADMIN_MASTERS_SYNC` (unchanged) | gains `documents_text: {order|upload|attachment: {pending, extracted, failed, none: {scanned_pdf, image, doc}}}`; under A / B also `ocr: {engine, pending_eligible, pending_not_eligible, done, empty, failed, last_run}`. Totals only. | 0, A, B |
| `GET /cases/{ref}/documents` | `DOCUMENTS_VIEW` and the case and document visibility (unchanged) | items gain `text_source` (`text_layer` / `docx` / `ocr` / null) and `ocr_status` | A, B |
| `GET /cases/{ref}/orders` | the case visible (unchanged) | items gain `text_source` | A, B |
| `GET /documents/search` | unchanged (visibility rule) | none; OCR'd documents become findable | A, B |

`aslms data-health` (CLI) prints the new block with the rest.

## Jobs
- Part 0: none.
- Parts A and B: Celery task `aslms.ocr_pending`, beat `ocr-pending` every 10 minutes (in the `scheduler`
  service's beat); under A routed to queue `ocr` and consumed only by the Compose service `ocr`; under B run on
  the default queue in the `scheduler` worker. One `job_runs` row per run with the counters of decision 10. No
  `fetch_queue` kind, no NAPIX call. The existing `aslms.next_dates_read` (every 5 minutes) reads the orders put
  back to `pending`.

## Tests

### Part 0
- `tests/unit/test_dependencies.py::test_pymupdf_loads_no_neural_runtime` — in a subprocess, `import pymupdf`
  leaves `onnxruntime` out of `sys.modules`, and `pymupdf.VersionBind` starts with `1.`.
- `tests/db/test_data_health.py::test_documents_text_counts` — order, upload and attachment documents in each
  `text_status`, `none` split into scanned PDF, image and DOC; causelist and admin documents not counted; the
  API answers it to a `REPORTS_STATE` holder and 403 to a plain department user.
- Frontend `case.test.tsx`: the Documents tab shows "Scanned, not read" for a `none` PDF and a `none` PNG, "Old
  Word format, not read" for a `none` DOC, "Searchable" for `extracted`, never the raw word `none`.
- Frontend `search.test.tsx`: the content search shows the "not searched by their content" note.
- Frontend `data.test.tsx`: the health screen renders the `documents_text` block.

### Parts A and B
Unit (`tests/unit/test_document_ocr.py`):
- `eligible_condition` / `assert_ocr_allowed`: under `local` an internal upload and a note attachment are allowed;
  under `sourcetrace` an internal document, a private filing, a not-ingested order and a filing of a case without
  a CNR are refused; `causelist` and `admin` kinds are refused under both;
- `FakeOcrEngine` outcomes map to `done`, `empty`, retry with back-off, `failed` after three attempts.
Database (`tests/db/test_document_ocr.py`):
- `run` turns a `none` scanned PDF into `extracted` with `text_source = ocr`, a `document_text` row and a filled
  `search_vector`, and `GET /documents/search` finds it **only** for users who can see the document (a
  `private_to_office` upload is not found by another office);
- an empty read leaves `text_status = none` and `ocr_status = empty`;
- an order at `no_text` goes back to `pending` when its document gets text, and the next-date reader then reads it;
  a read date that differs from `date_next_list` is a `pending` suggestion, not firm (the two-source rule);
- two concurrent runs never claim the same document (`SKIP LOCKED`); a failure writes one `source_failures` row
  and a later success resolves it;
- the CHECKs: `ck_documents_ocr_internal_local` refuses a `sourcetrace…` engine on an internal document;
  `ck_documents_text_source` and `ck_documents_ocr_done` refuse inconsistent rows;
- `requeue` writes `document.ocr_requeued`; `run` writes no audit row;
- `text_extract` sets `ocr_status = pending` for a scanned PDF when `OCR_ENGINE` is set and `not_needed` when it is
  `none`;
- migration 0021 backfill: `text_source` set for every `extracted` row, none left inconsistent.
Under A only: `tests/unit/test_tesseract_engine.py` (skipped when `tesseract` is not installed; runs in the `ocr`
image): a generated image-only PDF with a typed sentence reads back the sentence; a PNG likewise; a page over
the timeout is skipped and counted; `OCR_MAX_PAGES` is respected. `test_compose`: the `ocr` service uses
`target: ocr`, mounts the store read-only, has `cpus` and `mem_limit`; no other service builds the `ocr` target.
Under B only: `tests/unit/test_sourcetrace_text.py` — `FakeSourceTrace.document_text` is called with the stored
`sourcetrace_ref` and receives **no document bytes**; `SourceTraceNoText` → `empty`; `SourceTraceUnavailable` →
retry; with a connector lacking `SourceTraceTextReader` the job counts documents as waiting and calls nothing; a
test proves no OCR item for an internal document or a note attachment ever reaches the connector.

## Verification

### Part 0
1. `docker compose build api worker scheduler` then
   `docker compose exec -T api python -c "import sys, pymupdf; print(pymupdf.VersionBind, 'onnxruntime' in sys.modules)"`
   → `1.x False`; the developer's report lists the 1.x / 2.0 text comparison over 200 orders.
2. `aslms data-health` (or `GET /admin/data-health` as the super admin) → `documents_text.order` matches
   `SELECT text_status, count(*) FROM documents WHERE kind='order' GROUP BY 1` (on 20 Oct: 57,392 extracted,
   3,220 pending, 0 none).
3. Upload a scanned PDF and a PNG to a dev case through the portal: the Documents tab shows "Scanned, not read";
   the health block's `upload.none.scanned_pdf` and `upload.none.image` are 1 each; a content search for a word
   in the scan finds nothing and the note is shown.

### Parts A and B
A1 / B1. `alembic upgrade head`; `SELECT count(*) FROM documents WHERE (text_status='extracted') <> (text_source IS
NOT NULL)` → 0.
A2. Set `OCR_ENGINE=tesseract`, `docker compose up -d ocr`; `docker images` shows the `ocr` image and the size
difference (recorded). Upload a scanned typed filing (a printed page scanned at 300 dpi) and a PNG; within one
beat interval `ocr_status = done`, the Documents tab says "Searchable (read from a scan; may contain errors)",
and a content search for a word on the page finds it — and does not find it as a user of another office when
the upload is `private_to_office`.
A3. CPU: `aslms documents ocr --document <ref>` on a 20-page scanned filing; the report records seconds per page
and the `ocr` container's peak memory (`docker stats`); the `scheduler` keeps sending notifications meanwhile
(`notifications-send` job runs on time).
A4 / B4. The order path (`no_text` → OCR → `pending` → read) is proved by the database test only: the dev
database holds no scanned order (0 measured), and no test order or identifier is made up on it.
B2. With the fake connector only (no real connector exists): the database tests above; on the dev stack
`OCR_ENGINE=sourcetrace` with no real connector → the health block shows the documents as waiting and
`job_runs` shows zero calls.
B3. After row 36 delivers a real connector with a text endpoint: one ingested scanned court filing gets text;
`sourcetrace_ingestions` shows no second send of its bytes.

## Open questions
1. **The OCR policy (owner decision 8 of the audit).** For scanned court orders, scanned court filings and
   uploaded images (today "scanned, not read"; measured: 0 of 57,392 order PDFs are scanned, uploads not yet
   measurable), which do you choose?
   - **A.** A local OCR engine (Tesseract 5, CPU only, its LSTM recogniser is a small neural network, no prompt,
     no generation) is **not** a "local model" under the rule and may read every scanned document on the server,
     internal documents and note attachments included; cost about 30–50 MB of image, one new `ocr` service with
     1 CPU and 1 GB, about 1–4 seconds per page.
   - **B.** Only SourceTrace may read scanned documents: the portal takes back the text of court orders and court
     filings SourceTrace already holds (nothing new is sent; internal documents, note attachments and private
     filings are never read); it can only be finished after the SourceTrace API documentation (row 36) shows a
     way to return a document's text.
   - **C.** No OCR in Phase 1: scanned documents stay "scanned, not read" (clearly labelled, counted on the
     data-health screen, and scanned orders go to the next-date enter queue as today), and the question is
     taken again after the pilot with real upload numbers.

   **Architect's recommendation: C now, B when SourceTrace is documented** (decision 1). Part 0 (labels, counts,
   the PyMuPDF pin) is built under every answer.

   And, under the same rule: **may the backend keep PyMuPDF 2.0, which now loads three bundled neural-network
   layout models (onnxruntime) at import although the portal does not use them, or is it pinned below 2 as this
   note proposes (decision 2)?** The architect recommends the pin whatever the answer to the first part.
