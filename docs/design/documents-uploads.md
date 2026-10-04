# Design: Documents and uploads — upload with virus scan, per-document visibility, downloads, order PDFs, text extraction

```
slug: documents-uploads
status: awaiting-approval
author: architect
date: 2026-10-04
approved_by: <owner e-mail or name> on YYYY-MM-DD
```

## Context
Plan §5.6 (Orders and Case Documents), §8.1 ("Uploads: only permitted file types (PDF, Word, images) accepted,
with a size limit, and every upload scanned for viruses before it is stored"), §5.3 (the Documents tab of the
case detail page), §1.1 Table 1 (standing counsel see "cases they appear in, and notes and files shared with
counsel"), §5.13 (file uploads are audited), §7 Table 8 ("Documents: court orders, and documents uploaded by
users (court filings and internal documents), with extracted text and visibility settings"; "search index for
text search across cases and orders"). CLAUDE.md: uploads restricted and virus-scanned; visibility on the server
for every query; audit every upload; never send internal documents to SourceTrace. Backlog row 4.

The plan's rules, in substance:
- Every document of a case in one place: the court orders collected automatically and the documents users
  upload (writ petition, affidavit-in-opposition, reply, rejoinder, interlocutory applications, annexures,
  compliance reports, parawise comments, instructions to counsel).
- Each upload records the document type, date, a short description, and who uploaded it from which office.
  PDF, Word and image files are accepted.
- Types are grouped as court filings (filed in or received from the court) and internal documents (parawise
  comments, instructions to counsel). Court filings are ingested into SourceTrace like orders; internal
  documents never are.
- Visibility per document, as for notes: the whole case, shared with counsel, or private to the office. All
  documents can be viewed and downloaded from the case page, subject to their visibility.
- Order text is extracted so orders can be searched by content.

Earlier decisions in the log that this design follows:
- 25 Sep "CASE DOCUMENTS" (two groups, three visibility values, PDF / Word / images, size limit, scan before
  storage); 25 Sep "CASE NOTES" (State tier sees all notes; attachments are documents rows through
  `case_note_attachments`); 26 Sep "Standing counsel scope" (counsel see documents shared with counsel and court
  records); 26 Sep "SourceTrace" (court orders and **virus-clean** court filings only).
- DB_STANDARD §3: `DOC` reference numbers for documents whose `doc_group` is `court_filing` or `internal`,
  allocated on the **uploader's office**; §6: no deletion, `documents.archived_at` is the retirement column.
- cases-api decisions 1, 4, 14, 15: one case-visibility rule (`services/visibility.py`); a case that is not
  visible answers 404; reading is not audited; document events join the timeline allow-list "in their own
  items, with per-document visibility".

What is in place:
- `documents` (all columns of schema.md Group 6, plus `page_count`), `document_text`, `orders`; enums
  `doc_kind` (`causelist` / `order` / `upload` / `attachment`), `doc_group`, `doc_visibility`, `scan_status`,
  `text_status` (`pending` / `extracted` / `failed` / `none`), `sourcetrace_status`.
- `services/storage.py::LocalStore` (content-addressed `<sha[:2]>/<sha>.<ext>` under `STORAGE_DIR`, atomic
  write); `services/orders.py::fetch_order_pdf` writes order PDFs (`kind order`, `court_record`, scan `skipped`,
  text `pending`, SourceTrace `pending`) and `services/causelists.py::store_pdf` cause-list PDFs (text `none`).
- **Defects this item must fix:** `documents.sha256` is **UNIQUE** (`uq_documents_sha256`), so the same file
  cannot be uploaded to two cases or by two offices, and an upload whose bytes equal an order PDF would make
  `fetch_order_pdf` (which looks up by `sha256` only) attach a user's — possibly private, internal — document
  to an order. `document_text.search_vector` has **no index** although schema.md says "GIN". Nothing extracts
  text yet: the stored January 2025 orders all sit at `text_status = pending`.
- Functions `documents.upload` (dept head, dept admin, dept officer, directorate user, standing counsel),
  `documents.view` and `documents.download` (every case-reading type). `EventType.DOCUMENT_UPLOADED`,
  `RecordType.DOC` exist. `ref_doc_type` (+ `doc_group`) holds 13 codes.
- `pymupdf` and `python-multipart` are already dependencies. Compose has no virus scanner; the `scheduler`
  service (Celery worker with beat) does not mount `./data`.

Not covered: note attachments and their per-note visibility (`custody-workflow`, which reuses the upload
service and the visibility rule written here); ingestion into SourceTrace (`sourcetrace-connector`; this item
only sets `sourcetrace_status`); next-date extraction from orders (SourceTrace, plan §3.2); OCR of scanned
PDFs and images; serving cause-list PDFs; re-fetch buttons for missing order PDFs (`audit-screens`); the portal
screens (`portal-cases`, `portal-workflow`); request attachments (`custody-workflow`).

## Decisions
1. **The scan happens before anything is stored, synchronously, and fails closed.** The upload request reads
   the file (size limit enforced while reading), checks its type, sends the bytes to ClamAV (`clamd`
   `INSTREAM` over TCP), and only on `OK` writes the file to the store and inserts the `documents` row with
   `virus_scan_status = clean`, `scanned_at`. `FOUND` → 422 `infected`, nothing written to disk or to
   `documents`, an audit row (decision 12). Scanner unreachable, timed out or answering an error → 503
   `scanner_unavailable`, nothing stored. So uploaded rows are always `clean`; a CHECK enforces it (Data). There
   is no "scan disabled" setting. Alternatives: store into a quarantine area and scan asynchronously (the
   `pending` / `infected` states) — rejected, the plan says "before it is stored" and a user waits a few seconds
   at most for a 20 MB file; scanning on download — rejected, same reason. Court PDFs fetched by the system
   (orders, cause lists) stay `skipped` (they are not uploads; plan §8.1 speaks of uploads).
2. **The scanner is an interface.** `services/scanner.py`: `Scanner` protocol `scan(data: bytes) ->
   ScanResult(clean: bool, signature: str | None)`; `ClamdScanner(host, port, timeout)` speaks the `zINSTREAM`
   protocol with the standard library `socket` (4-byte big-endian chunk lengths, zero-length terminator; reply
   `stream: OK` / `stream: <name> FOUND` / `... ERROR`) — no new dependency; `FakeScanner` for tests (flags the
   EICAR test string, can be told to fail). The API takes the scanner from a dependency (`get_scanner`) so tests
   override it. Compose gains a `clamav` service (official `clamav/clamav:stable` image, signatures updated by
   its own `freshclam`, port 3310 on the Compose network only, a named volume for the signature database, a
   healthcheck). The `api` does not wait for it (signature download can take minutes); until `clamd` answers,
   uploads get 503. Alternative: the `clamd` Python package (unmaintained; the protocol is twelve lines).
3. **Permitted types, decided by content, not by the name or the browser.** The first bytes decide the type;
   the file name's extension must agree; the declared `Content-Type` is ignored:

   | Type | Signature | Extensions | Stored mime |
   |---|---|---|---|
   | PDF | `%PDF-` within the first 1,024 bytes | `.pdf` | `application/pdf` |
   | Word (OOXML) | ZIP (`PK\x03\x04`) containing `word/document.xml` and `[Content_Types].xml`, **no** `word/vbaProject.bin` | `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
   | Word 97–2003 | OLE2 (`D0 CF 11 E0 A1 B1 1A E1`) | `.doc` | `application/msword` |
   | JPEG | `FF D8 FF` | `.jpg`, `.jpeg` | `image/jpeg` |
   | PNG | `89 50 4E 47 0D 0A 1A 0A` | `.png` | `image/png` |

   Anything else, a mismatch (a PDF named `.docx`), or a macro-enabled Word file (`.docm`, or a `.docx` carrying
   `vbaProject.bin`) → 415 `type_not_allowed`. Empty files → 400. Alternatives: trust the extension or the
   `Content-Type` (spoofable); add TIFF, ODT, Excel (the plan names PDF, Word and images; TIFF and others can be
   added to the table on the owner's word).
4. **Size limit `UPLOAD_MAX_BYTES`, default 20 MB (20,971,520 bytes)** in `.env` / `core/config.py`, below
   ClamAV's default `StreamMaxLength` (25 MB) so `clamd` needs no configuration change. A `Content-Length` above
   the limit plus 64 KB of multipart overhead is refused with 413 `too_large` before the body is read; the
   service counts the bytes it reads from the spooled part and refuses at the limit too (a client may omit or
   lie in the header). The number is the architect's proposal for the owner to confirm (the plan says "a size
   limit" without a number). The reverse proxy limit (`client_max_body_size`) is set to match in
   `deployment-checklist`.
5. **Upload rules** (`POST /cases/{ref}/documents`, multipart):
   - Fields: `file`; `doc_type` (a code of `ref_doc_type` usable for uploads, decision 6); `doc_date` (required,
     not in the future, not before 1950-01-01); `description` (required, 3–500 characters, trimmed);
     `visibility` (**required**: `case_scope`, `counsel_shared` or `private_to_office` — no default, the user
     decides, the portal may pre-select); `doc_group` only for `doc_type = other` (`court_filing` or
     `internal`, required there, refused elsewhere).
   - Who: holders of `documents.upload` who **work on the case**: the case is visible to them through the
     `owner`, `allotted`, `custody`, `request` or `counsel` basis (`visibility.access_basis`). A case visible only
     through `state`, `recommended` or `pool` → 403 `not_working_on_case` (a department uploads to a case once it
     has claimed it, holds it or was asked about it). Not visible at all → 404. Alternative: any user who can see
     the case — rejected: a department could attach files to a case another department owns, or to a pool case
     it has not claimed.
   - The row: `kind = upload`, `doc_group` from `ref_doc_type.doc_group` (or the field for `other`),
     `case_id`, `office_id` = the uploader's office, the actor snapshot (name, designation, office code),
     `original_filename` (path stripped, control characters removed, at most 200 characters), `mime` and
     `size_bytes` from decision 3, `sha256`, `storage_key`, `ref_no = ASLMS/<uploader's office code>/DOC/<yyyy>/<n>`
     (DB_STANDARD §3), `text_status = pending` for PDF and DOCX, `none` for DOC and images (decision 10),
     `sourcetrace_status` per decision 9.
   - Duplicate: the same bytes already uploaded to the same case by the same office and not archived → 409
     `duplicate` with the existing document's `ref_no` (that office can see it). The same bytes by another office
     or on another case are a separate row (the store keeps one file; decision 8).
   - Ordering: validate fields → read and size-check → detect type → scan → `store.put` → insert row, event,
     audit → commit. A file written to the store whose transaction then rolls back is an unreferenced
     content-addressed file (harmless; a later identical upload reuses it).
6. **Document types.** Uploads may use every active `ref_doc_type` code except the system types `causelist`,
   `order`, `judgment` (`court_record`, written by the pipeline). A user's copy of an order is uploaded as
   `other` with group `court_filing` ("received from the court"). Four codes from the plan's list are added to
   `DocType` and seeded (seed only, no migration): `reply` (court_filing), `interlocutory_application`
   (court_filing), `annexure` (court_filing), `instructions_to_counsel` (internal). The plan's
   "affidavit-in-opposition" is the existing `counter_affidavit`; its label is set to "Affidavit-in-opposition
   (counter affidavit)" for new databases (the seed inserts missing codes only; existing labels are an
   administrator's edit). `compliance_report`, `legal_opinion`, `correspondence` and `parawise_comments` stay
   `internal` as seeded today; `other` asks the uploader (25 Sep log). `GET /documents/types` lists the
   uploadable types with `doc_group` and `group_choosable`.
7. **Per-document visibility — one rule, written once, in SQL**, beside the case rule. A document is visible
   to a caller when all three hold:
   - **(a) function**: `documents.view` (listing, metadata, inline view) or `documents.download` (attachment
     download);
   - **(b) case**: a case the document belongs to is visible (`visible_case_condition`): `documents.case_id`,
     or any `orders.case_id` whose `orders.document_id` is this document (one order PDF may serve connected
     cases, decision 8);
   - **(c) the document's own setting** (`record_visibility_condition`, generic over a visibility column, an
     office column and an author column so `custody-workflow` applies the same rule to notes, "as for notes"):

     | Document | Visible to (among those who pass (a) and (b)) |
     |---|---|
     | `doc_group = court_record` (orders, judgments) | everyone, standing counsel included (26 Sep: counsel see court records) |
     | `case_scope` | everyone except users of type `standing_counsel` (Table 1: counsel see what is *shared with counsel*); the uploader always |
     | `counsel_shared` | everyone, standing counsel included |
     | `private_to_office` | users whose `office_id` **equals** the document's `office_id`; department-wide callers (`visibility.whole_department`: holders of `cases.claim` / `cases.allot`) of the department containing that office; the uploader; State-wide readers |

     State-wide readers (super admin, holders of `cases.view_all`: State oversight, central operator, auditor)
     pass (c) for every document (25 Sep: "State tier sees all"). "Private to the office" means the office
     itself, not its subtree: a document private to `EDU` is not visible to `EDU-DSE` users; one private to
     `EDU-DSE` is visible to the `EDU` head and admin (the tier rule) but not to `EDU-DHE`. A department that
     loses sight of a case (transfer without watcher, cases-api decision 3) loses sight of its documents on that
     case too; they stay in the database and visible to State-wide readers.
   - `services/visibility.py` gains `record_visibility_condition(session, user, *, visibility, office_id,
     author_user_id)` and `document_visible_condition(session, user)` (a, b, c over `documents`, correlated
     `EXISTS`, parameters bound); `can_view_document`, `require_visible_document` (→ 404). Lists, the timeline,
     metadata, file serving and content search all use the same condition; nothing is filtered after the query.
     Alternatives: reuse `notes.view_counsel_shared` / `notes.view_private_office` for documents — rejected,
     their labels and matrix rows are about notes, and the document functions already exist; private to the
     office's subtree — rejected, a directorate's private file would be visible to sibling directorates through
     the department path.
8. **One stored file may back several `documents` rows; system PDFs stay deduplicated per kind.** Migration
   0006 drops `uq_documents_sha256`, adds a plain index on `sha256`, a partial unique index on `(kind, sha256)`
   for `kind IN ('causelist', 'order')` (the pipeline's dedupe, unchanged in effect) and a partial unique index on
   `(case_id, office_id, sha256)` for non-archived uploads (decision 5's duplicate rule). `fetch_order_pdf` and
   `causelists.store_pdf` look up an existing document by `sha256` **and** their own `kind`, so an order never
   points at an uploaded document. The store is content-addressed, so the bytes are kept once. Alternative: a
   separate `stored_files` table referenced by `documents` — cleaner, but a new table and a rewrite of every
   writer for no behaviour the index change does not already give.
9. **SourceTrace status at upload.** `internal` → `not_applicable` (a CHECK makes any other value impossible
   for internal documents — Data). `court_filing` with visibility `case_scope` or `counsel_shared` → `pending`
   (the `sourcetrace-connector` item ingests clean pending court records and filings). A `court_filing` marked
   `private_to_office` → `not_applicable` until its visibility is widened (then `pending`): the Case Assistant
   answers every user who can see the case, so a file one office keeps private must not be in its sources.
   Narrowing an already `ingested` court filing to `private_to_office` → 409 `already_ingested` (removal from
   SourceTrace is not defined; its endpoints are unknown). The document list shows `assistant_available`
   (`sourcetrace_status = ingested`), as the plan's figure "marked with whether it is available to the Case
   Assistant" asks. This is the architect's reading of "court filings are ingested" together with per-document
   visibility; flagged for the owner.
10. **Text extraction is background work with a visible status.** Pending documents (uploads, attachments and
    orders; `text_status = pending`, scan `clean` or `skipped`) are processed by the Celery task
    `aslms.extract_pending_text` (beat every 5 minutes, batch of `TEXT_EXTRACT_BATCH` = 50, rows claimed with
    `FOR UPDATE SKIP LOCKED`, one savepoint per document); the upload endpoint also dispatches
    `aslms.extract_document_text(document_id)` after commit (best effort; when Redis is down the sweep catches
    it). Per type:
    - PDF: `pymupdf`, text of each page (at most 2,000 pages), `page_count`; when the text averages fewer than 20
      non-space characters per page (a scan without a text layer) → `none`, the page count and any text kept;
      else `extracted`.
    - DOCX: `zipfile` + `xml.etree` over `word/document.xml` (paragraph texts joined by new lines), refused above
      50 MB uncompressed (zip bomb guard) → `failed`; `page_count` NULL.
    - DOC and images: `none` at upload (no extractor without a new dependency; no OCR — the plan does not ask
      for OCR and the stack has no OCR service).

    Result: one `document_text` row (`full_text`, `page_count`, `search_vector = to_tsvector('english',
    left(full_text, 500000))` — prose, stemming helps; the cut keeps under the 1 MB `tsvector` limit),
    `documents.text_status`, `text_extracted_at`, `page_count`. A failure → `failed` and a `source_failures` row
    (`kind = text_extraction`, `ref = <document id>`, the error); never lost. `aslms documents extract
    [--retry-failed] [--document REF]` reruns it. Extraction runs in the worker, never in the API request, so a
    hostile file cannot stall the API. Alternative: a `fetch_queue` kind — rejected, `fetch_queue.kind` is a
    native enum (a migration), and the runner's quota logic is NAPIX-specific.
11. **Order PDFs are served from the store** — `GET /cases/{ref}/orders/{order_id}/file` (the case visible, the
    order belongs to it, `orders.document_id` set, else 404 `not_stored` carrying `download_status`), and the
    same document through `GET /documents/{id}/file`. Missing PDFs are not fetched on demand here (the queue and
    the weekly sweep do it; a re-fetch button is `audit-screens`). `OrderOut` gains `text_status` and
    `page_count`.
12. **Audit and events.**
    - `document.uploaded` (entity `document`, `case_id`, `after` = ref_no, doc_type, doc_group, visibility,
      original_filename, mime, size_bytes, sha256, sourcetrace_status) + event `document_uploaded` (scoped;
      payload `document_id`, `ref_no`, `doc_type`, `doc_group`, `visibility`, `office_code`).
    - `document.upload_rejected` for `infected` (signature name) and `type_not_allowed` (detected type,
      extension), `entity_id` NULL, `case_id`, `after` = reason, original_filename, size_bytes, sha256: security
      events worth keeping. Field-validation errors, 413 and 503 write no row (nothing reached the store or the
      scanner's verdict). The router commits the audit row **before** raising the HTTP error (the pattern of
      recommend-and-claim deviation 2).
    - `document.visibility_changed` (before / after visibility and sourcetrace_status), `document.archived`
      (reason).
    - `document.downloaded` for every file served of an **uploaded** document (inline or attachment):
      internal files leaving the server are accountable. Order and court-record files are court-public and not
      audited, as case reads are not (cases-api decision 14). Listing and metadata are not audited.
    - Timeline: `document_uploaded` joins the allow-list of cases-api decision 15, shown only when the document
      is visible to the caller (an `EXISTS` on `documents` with `document_visible_condition`, keyed by the
      payload's `document_id`); `order_stored` already shows.
13. **Changing a document after upload: visibility and archive only.** No content replacement, no type change,
    no delete. `PATCH /documents/{doc}` `{visibility}` and `POST /documents/{doc}/archive` `{reason}` (3–500
    characters) are allowed to the uploader, to department-wide callers of the uploading office's department,
    and to the super admin; never on `court_record` documents (400). An archived document disappears from the
    Documents tab unless `include_archived=true`, stays readable and downloadable under the same visibility,
    its partial-unique duplicate slot is freed, and it is not unarchived (a mistaken archive is fixed by
    uploading again). Alternative: an edit endpoint for description and date — the plan does not ask for it and
    every edit of a legal record needs a history; a wrong upload is archived and uploaded again.
14. **Serving files.** `GET /documents/{doc}/file?disposition=inline|attachment` (default `attachment`):
    `inline` needs `documents.view` and is offered for PDF, JPEG and PNG only (Word → 400 `inline_not_supported`);
    `attachment` needs `documents.download`. Response: the stored mime, `Content-Disposition` with the
    sanitised original name (RFC 6266 `filename*=UTF-8''…`; orders get `<case no>_<order no>_<date>.pdf`),
    `Content-Length`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, and for `inline`
    `Content-Security-Policy: sandbox`. Streamed from `LocalStore.path(key)` (`FileResponse`). A stored file
    missing from disk → 500 and a `source_failures` row (`kind = document_missing`), never a silent 404.
15. **Content search** — `GET /documents/search?q=` (`documents.view`): word search over
    `document_text.search_vector` (`websearch_to_tsquery('english', :q)`, bound parameter), restricted by
    `document_visible_condition`, optional `case` (a case ref), `group`, `doc_type`, `date_from` / `date_to`;
    ranked by `ts_rank`, then `doc_date` descending; `limit` ≤ 50; each item is the document summary, its case
    summary and a `ts_headline` snippet computed for the returned page only. This is plan §5.6 "orders can be
    searched by content"; the GIN index is added in 0006.
16. **Permissions.** `documents.view`, `documents.download`, `documents.upload` as above; no new function, no
    matrix change. Every case-scoped endpoint resolves the case with `resolve_case_ref` and applies the case rule
    first (404). `{doc}` = document id or `ref_no` (slash or dash form, via `ref_no_from_url`).

## Data
Migration **0006_documents** (new; 0001–0005 are applied and not edited). Written by hand like 0005 and checked
with `compare_metadata` (the model `Document` declares the same indexes and checks):
- `ALTER TABLE documents DROP CONSTRAINT uq_documents_sha256`; `CREATE INDEX ix_documents_sha256 ON documents
  (sha256)`.
- `CREATE UNIQUE INDEX ix_documents_system_sha ON documents (kind, sha256) WHERE kind IN ('causelist',
  'order')`.
- `CREATE UNIQUE INDEX ix_documents_upload_dedupe ON documents (case_id, office_id, sha256) WHERE kind =
  'upload' AND archived_at IS NULL`.
- `ALTER TABLE documents ADD COLUMN archive_reason text`.
- CHECK `ck_documents_internal_not_sent`: `doc_group <> 'internal' OR sourcetrace_status = 'not_applicable'`.
- CHECK `ck_documents_user_file`: `kind NOT IN ('upload', 'attachment') OR (ref_no IS NOT NULL AND office_id IS
  NOT NULL AND doc_date IS NOT NULL AND virus_scan_status = 'clean' AND doc_group <> 'court_record')`.
- CHECK `ck_documents_upload_case`: `kind <> 'upload' OR case_id IS NOT NULL`.
- CHECK `ck_documents_archive_reason`: `archived_at IS NULL OR archive_reason IS NOT NULL`.
- `CREATE INDEX ix_document_text_search_vector_gin ON document_text USING gin (search_vector)`.
- `CREATE INDEX ix_documents_case_kind ON documents (case_id, kind) WHERE archived_at IS NULL` (the tab).
- Downgrade reverses each step; it re-adds `uq_documents_sha256` only when no duplicate `sha256` exists (else it
  stops with a message — no data is deleted).

All existing rows (cause-list and order documents) satisfy the checks. No enum change. Seed (no migration):
`DocType` + `reply`, `interlocutory_application`, `annexure`, `instructions_to_counsel` with their groups in
`seed.DOC_GROUP` (decision 6); `ref_event_type.document_uploaded` already exists (not a tracking-card event).

Paragraph for `docs/schema/schema.md`, Group 6, replacing the `documents` and `document_text` rows:

> | `documents` (transaction) | ref_no (unique; allocated for `upload` and `attachment` rows on the uploader's office, `ASLMS/<office>/DOC/<yyyy>/<n>`), sha256 (indexed, **not** unique), storage_key, mime, size_bytes, original_filename, kind (`causelist` / `order` / `upload` / `attachment`), doc_type (→ `ref_doc_type`), doc_group (`court_record` / `court_filing` / `internal`), case_id (→ cases RESTRICT), doc_date, description, visibility (`case_scope` / `counsel_shared` / `private_to_office`), office_id (→ offices RESTRICT; the uploader's office), virus_scan_status, scanned_at, text_status (`pending` / `extracted` / `failed` / `none`), text_extracted_at, page_count, sourcetrace_status, sourcetrace_ref, archived_at, archive_reason, actor snapshot, created_at, updated_at | Partial unique `ix_documents_system_sha` (kind, sha256) WHERE kind IN ('causelist','order'); partial unique `ix_documents_upload_dedupe` (case_id, office_id, sha256) WHERE kind = 'upload' AND archived_at IS NULL; one stored file may back several rows (the store is content-addressed). CHECKs: `ck_documents_internal_not_sent` (internal → `sourcetrace_status = not_applicable`), `ck_documents_user_file` (uploads and attachments carry ref_no, office_id, doc_date, scan `clean`, never `court_record`), `ck_documents_upload_case`, `ck_documents_archive_reason`. Uploads are stored only after a clean virus scan (design `documents-uploads`); system PDFs are `skipped`. Only `court_record` and `court_filing` may ever be sent to SourceTrace, and a `private_to_office` filing is not sent. Retired with `archived_at` + `archive_reason`, never deleted; visibility may change (audited), content never. |
> | `document_text` (transaction) | document_id (PK, CASCADE), page_count, full_text, search_vector (tsvector, `to_tsvector('english', left(full_text, 500000))`, GIN `ix_document_text_search_vector_gin`), created_at, updated_at | Written only by the text-extraction job. |

And under "Conventions", after the case-visibility paragraph:

> Document visibility is one rule (`services/visibility.py::document_visible_condition`, design
> `documents-uploads`): the document function, a visible case the document belongs to (directly or through an
> order), and the document's own setting (`record_visibility_condition`: court records and `counsel_shared` to
> everyone on the case, `case_scope` to everyone but standing counsel, `private_to_office` to the office itself,
> its department-wide callers and the uploader; State-wide readers see all). Notes reuse
> `record_visibility_condition`.

`.env.example` (no secrets): `UPLOAD_MAX_BYTES=20971520`, `CLAMAV_HOST=localhost` (Compose sets `clamav`),
`CLAMAV_PORT=3310`, `CLAMAV_TIMEOUT_SECONDS=30`, `TEXT_EXTRACT_BATCH=50`.

Compose: service `clamav` (image `clamav/clamav:stable`, volume `clamdb_v3:/var/lib/clamav`, healthcheck
`clamdscan --ping 1` or the image's own check, no host port); `api` gains `CLAMAV_HOST: clamav`; `scheduler`
gains `STORAGE_DIR: /data/store` and the `./data:/data` volume (it runs the extraction task).

## Services
`backend/aslms/services/scanner.py` (new): `ScanResult`, `Scanner` (protocol), `ClamdScanner`, `FakeScanner`,
`ScannerUnavailable`; `get_scanner(settings)`.

`backend/aslms/services/filetypes.py` (new, pure): `detect(data: bytes, filename: str) -> FileType(mime, ext,
extractable)`; raises `TypeNotAllowed(reason, detected)`; `safe_filename(name) -> str`.

`backend/aslms/services/storage.py`: `EXT_FOR_MIME` gains `doc`, `docx` (the OOXML and `msword` mimes) and
keeps `pdf`, `png`, `jpg`; no other change.

`backend/aslms/services/visibility.py` (extended): `state_wide(session, user) -> bool` (the existing super-admin-or-`cases.view_all` test, named);
`record_visibility_condition(session, user, *, visibility, office_id, author_user_id, group=None)`;
`document_case_condition(session, user)` (b of decision 7); `document_visible_condition(session, user)`;
`can_view_document`, `require_visible_document` (raises `NotVisibleDocument` → 404); `working_bases = {"owner",
"allotted", "custody", "request", "counsel"}` and `works_on_case(session, user, case) -> bool`.

`backend/aslms/services/documents.py` (new):
- `upload(session, actor, user, case, *, data: bytes, filename, doc_type, doc_group, doc_date, description,
  visibility, scanner, store, kind=DocKind.UPLOAD) -> Document` — decisions 3–6, 9, 12; raises
  `UploadRefused(code, http_status, audit: bool)` with codes `bad_field`, `not_working_on_case`, `too_large`,
  `type_not_allowed`, `infected`, `scanner_unavailable`, `duplicate`. `kind=attachment` is the entry point
  `custody-workflow` will call for note attachments (no case-level row rule beyond the CHECK).
- `list_for_case(session, user, case, *, group, doc_type, include_archived, limit, offset) -> Page` — uploads of
  the case and the order documents of the case's orders (with `order {id, order_no, order_date, kind}`), filtered
  by `document_visible_condition`, newest `doc_date` first.
- `get(session, user, ref) -> Document` (id or ref_no; 404 when unknown or not visible).
- `open_file(session, actor, user, doc, *, disposition) -> ServedFile(path, mime, filename, size)` — decision 14;
  writes `document.downloaded` for uploads and attachments.
- `order_file(session, actor, user, case, order_id, *, disposition)`.
- `change_visibility(session, actor, user, doc, visibility)` and `archive(session, actor, user, doc, reason)` —
  decision 13; audit rows; `sourcetrace_status` recomputed by decision 9.
- `upload_types(session) -> list[dict]`.
- `search(session, user, *, q, case, group, doc_type, date_from, date_to, limit, offset)` — decision 15.

`backend/aslms/services/text_extract.py` (new): `extract(data, mime) -> Extracted(text, page_count, status)` —
pure over bytes, unit-tested; `extract_document(session, store, doc)` (writes `document_text`, the document's
status columns, a `source_failures` row on failure); `extract_pending(session, store, *, batch, retry_failed=False)
-> dict` counters (`extracted`, `none`, `failed`).

`services/orders.py::fetch_order_pdf` and `services/causelists.py::store_pdf`: look up by `sha256` and `kind`
(decision 8). `services/case_detail.py`: `orders` items gain `text_status`, `page_count`; `_counts` gains
`documents` (visible, non-archived); `_timeline_stmt` adds `document_uploaded` filtered by
`document_visible_condition`.

CLI: `aslms documents extract [--retry-failed] [--document REF] [--batch N]`, `aslms documents scan-check` (sends
the EICAR string built at run time and a clean string to the configured `clamd`; prints the verdicts — the
integrator's probe), both wrapping tested services.

## API
New router `backend/aslms/api/routers/documents.py` (tag `documents`), mounted in `api/main.py`. `{ref}` = case
id, `ref_no` or CNR; `{doc}` = document id or `ref_no` (slash or dash form). Unknown or not visible → 404 `no such
case` / `no such document`. Errors carry `{code, message}`. Lists return `{items, total}`, `limit` ≤ 200 (≤ 50 on
search), default 50, `offset`. `/documents/types` and `/documents/search` are declared before `/documents/{doc}`.

`DocumentOut` = `{id, ref_no?, kind, doc_type, doc_type_label, doc_group, doc_date?, description?,
original_filename?, mime, size_bytes, visibility, office {code, name}?, uploaded_by {name, designation?,
office_code?}?, uploaded_at, virus_scan_status, text_status, page_count?, text_extracted_at?, sourcetrace_status,
assistant_available, archived_at?, archive_reason?, order {id, order_no, order_date, kind}?, case {id, ref_no,
cnr?, case_no_text?}, can_manage}` (`can_manage` = the caller may change visibility or archive).

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /cases/{ref}/documents` | `documents.view` | `?group=court_record\|court_filing\|internal`, `doc_type`, `include_archived=false`, `limit`, `offset` | `{items: [DocumentOut], total}` | case visible, then each document by decision 7 |
| `POST /cases/{ref}/documents` | `documents.upload` | multipart: `file`, `doc_type`, `doc_date` (YYYY-MM-DD), `description`, `visibility`, `doc_group` (only for `other`) | 201 `DocumentOut`; 400 `bad_field`; 403 `not_working_on_case`; 404; 409 `duplicate` (`existing_ref_no`); 413 `too_large`; 415 `type_not_allowed`; 422 `infected`; 503 `scanner_unavailable` | case visible through a working basis (decision 5) |
| `GET /documents/types` | `documents.view` | | `{items: [{code, label, doc_group, group_choosable}]}` | none (reference data) |
| `GET /documents/search` | `documents.view` | `?q=` (required, ≥ 3), `case`, `group`, `doc_type`, `date_from`, `date_to`, `limit` (≤ 50), `offset` | `{items: [{document: DocumentOut, case: CaseSummaryOut, snippet, rank}], total}` | `document_visible_condition` |
| `GET /documents/{doc}` | `documents.view` | | `DocumentOut` | decision 7 |
| `GET /documents/{doc}/file` | `documents.view` for `disposition=inline`, `documents.download` for `attachment` (default) | `?disposition=` | the file (decision 14); 400 `inline_not_supported`; 404 | decision 7 |
| `GET /cases/{ref}/orders/{order_id}/file` | as above | `?disposition=` | the order PDF; 404 `not_stored` `{download_status}` | case visible; order belongs to the case |
| `PATCH /documents/{doc}` | `documents.upload` | `{visibility}` | `DocumentOut`; 400 on a court record; 403 not the uploader / department / super admin; 409 `already_ingested` | decision 7, then decision 13 |
| `POST /documents/{doc}/archive` | `documents.upload` | `{reason}` | `DocumentOut`; 400 court record or already archived; 403 as above | same |

Changed: `GET /cases/{ref}/orders` items gain `text_status`, `page_count`; `GET /cases/{ref}` `counts` gains
`documents`; `GET /cases/{ref}/timeline` shows `document_uploaded` per decision 12.

## Jobs
- Celery task `aslms.extract_pending_text` (beat `extract-text`, every 5 minutes, the `scheduler` service): batch
  of `TEXT_EXTRACT_BATCH` pending documents, `FOR UPDATE SKIP LOCKED`, a `job_runs` row with the counters.
- Celery task `aslms.extract_document_text(document_id)`, dispatched after an upload commits (best effort).
- No `fetch_queue` kind, no NAPIX call. The first sweep after deployment extracts the order PDFs already stored
  (January 2025 week: a few hundred), 50 per run.

## Tests
Unit (`tests/unit/test_filetypes.py`):
- PDF, DOCX, DOC, JPEG, PNG detected from bytes with the matching extension; extension case-insensitive;
- a PDF named `.docx`, an HTML file named `.pdf`, a ZIP that is not Word, a `.docx` carrying
  `word/vbaProject.bin`, a `.docm`, an `.exe` → `TypeNotAllowed`; an empty file refused;
- `safe_filename` strips directories (`..\..\x.pdf`, `/etc/x.pdf`), control characters, and cuts at 200.

Unit (`tests/unit/test_scanner.py`): `ClamdScanner` against an in-process fake `clamd` (a thread with
`socketserver`) — `OK` → clean, `Eicar-Signature FOUND` → infected with the name, `ERROR` and a closed socket and
a time-out → `ScannerUnavailable`; the chunks are length-prefixed and zero-terminated. The EICAR string is built
at run time from two halves (desktop antivirus would otherwise quarantine the test file).

Unit (`tests/unit/test_text_extract.py`): a generated text PDF → `extracted` with pages; a generated image-only PDF
→ `none`; a generated DOCX → its paragraphs; a DOCX whose `document.xml` declares more than 50 MB → `failed`;
images and DOC → `none`; a corrupt PDF → `failed`.

Database (`tests/db/test_documents_upload.py`, the shared world, `FakeScanner`, a temporary `STORAGE_DIR`):
- the `EDU` admin uploads a PDF to a case `EDU` owns → 201, `ref_no` `ASLMS/EDU/DOC/<yyyy>/000001`, scan
  `clean`, text `pending`, the file in the store under its sha, an audit row `document.uploaded` and a
  `document_uploaded` event; `dse_user` (allotted unit) uploads → `ASLMS/EDU-DSE/DOC/…`;
- a court filing `case_scope` → SourceTrace `pending`; internal → `not_applicable`; a court filing
  `private_to_office` → `not_applicable`, widened later → `pending`; inserting an internal row with `pending`
  directly violates `ck_documents_internal_not_sent`;
- infected → 422, nothing in the store, no `documents` row, a committed `document.upload_rejected` row (read in
  a new session); scanner down → 503, nothing stored, no audit row;
- 21 MB → 413 (also with a lying `Content-Length`); a PDF named `.docx` → 415 and an audit row;
- the `EDU` admin on a pool case and on a case only recommended → 403 `not_working_on_case`; the auditor (no
  `documents.upload`) → 403; a `HEALTH` officer on an `EDU` case → 404; a standing counsel on a case carrying
  `SC, EDU` → 201;
- the same file twice by `EDU` on the same case → 409 with `existing_ref_no`; by `EDU-DSE` on the same case, or
  by `EDU` on another case → 201 (two rows, one stored file); after archiving the first, `EDU` may upload it again;
- `doc_type = order` → 400; `other` without `doc_group` → 400; `doc_group` on `petition` → 400; a future
  `doc_date` → 400;
- an uploaded file whose bytes equal a later order PDF: `fetch_order_pdf` creates its own `kind order` row and
  the order points at it, never at the upload.

Database (`tests/db/test_document_visibility.py`):
- `case_scope`: visible to the `EDU` admin, head, allotted officer and `dse_user` (allotted), not to the
  standing counsel unless they uploaded it; `counsel_shared` visible to the counsel; an order PDF (court
  record) visible to the counsel;
- `private_to_office` uploaded by `dse_user`: visible to `dse_user`'s colleagues at `EDU-DSE`, the `EDU` admin and
  head; not to `EDU` officers, not to a `EDU-DHE` user with custody of the case; uploaded by an `EDU` officer:
  not visible to `dse_user`; visible to the auditor and the super admin;
- after an accepted transfer `EDU` → `HEALTH` without watcher, `EDU` users no longer see `EDU`'s documents on the
  case; `HEALTH` sees `case_scope` ones, not `EDU`'s private ones;
- an order PDF shared by two connected cases (one document, two orders) is visible to a user who sees only the
  second case;
- **one rule**: for every world user and a fixed set of documents, `GET /cases/{ref}/documents`, `GET
  /documents/{doc}`, `/file`, the timeline's `document_uploaded` rows and `/documents/search` agree exactly with
  `can_view_document`;
- `inline` with only `documents.view` (download denied by override) → 200 for a PDF, `attachment` → 403; Word
  inline → 400; served headers carry `nosniff`, `no-store`, `Content-Disposition` with the encoded name; a
  download of an upload writes `document.downloaded`, of an order does not;
- `/cases/{ref}/orders/{id}/file` → the PDF; an order without a document → 404 `not_stored` with
  `download_status`; an order of another case → 404.

Database (`tests/db/test_documents_manage.py`):
- the uploader and the `EDU` admin change visibility (audit before / after); an `EDU` officer who is not the
  uploader → 403; the super admin may; a court record → 400; narrowing an `ingested` court filing to private →
  409 `already_ingested`;
- archive with a reason → hidden from the tab, listed with `include_archived=true`, still downloadable,
  `document.archived` audited; archive again → 400; without a reason → 422;
- no endpoint deletes; `DELETE /documents/{doc}` → 405.

Database (`tests/db/test_text_extract.py`):
- `extract_pending` turns pending PDFs and DOCX into `extracted` with a `document_text` row and a filled
  `search_vector`, images into nothing new (`none` at upload), a corrupt PDF into `failed` with a
  `source_failures` row; a second run does nothing; `--retry-failed` retries;
- two concurrent runs never extract the same document (`SKIP LOCKED`);
- `/documents/search?q=<a word of the generated order text>` finds the order with a snippet for a user who sees
  the case and not for one who does not.

Database (`tests/db/test_migrations.py`): 0006 upgrade → downgrade → upgrade on a database holding order and
cause-list documents; `test_database_matches_the_models` stays green; `tests/db/test_pipeline.py` stays green.

## Verification
With Compose up (`docker compose up -d`, now including `clamav`; wait for its healthcheck), migrations at head
`0006`, `aslms seed`, the January 2025 week loaded and the recommend-and-claim verification world in place
(`EDU`, `EDU-DSE`, `HEALTH`, their admins and officers, a standing counsel at `EDU-SC`):
1. `aslms documents scan-check` → `eicar: infected (Eicar-Signature)`, `clean: ok`.
2. `SELECT count(*) FILTER (WHERE text_status='pending') FROM documents WHERE kind='order'` before; wait one
   beat interval (or `aslms documents extract --batch 500`); after: pending 0 (or fewer by 50 per run),
   `SELECT text_status, count(*) FROM documents WHERE kind='order' GROUP BY 1` shows `extracted` (and `none` for
   scanned orders); `\di ix_document_text_search_vector_gin` exists.
3. As the `EDU` admin, on a case `EDU` claimed: `curl -F file=@petition.pdf -F doc_type=petition -F
   doc_date=2025-01-03 -F "description=Writ petition" -F visibility=case_scope …/cases/<ref>/documents` → 201,
   `ref_no` `ASLMS/EDU/DOC/2026/…`; the file exists under `data/store/<sha[:2]>/`; an EICAR file (built locally)
   → 422 and `SELECT action, after->>'reason' FROM audit_log ORDER BY created_at DESC LIMIT 1` →
   `document.upload_rejected | infected`; a renamed `.exe` → 415; a 25 MB PDF → 413.
4. Upload an internal `parawise_comments` as `private_to_office`; as an `EDU` officer and as the standing counsel
   `GET /cases/<ref>/documents` → it is absent; as the `EDU` head and the auditor → present. Upload an
   `instructions_to_counsel` as `counsel_shared` → the counsel sees it and downloads it; `document.downloaded`
   is audited.
5. `GET /cases/<ref>/orders` → items with `text_status`; `GET /cases/<ref>/orders/<id>/file` → `%PDF`;
   `GET /documents/search?q=<a word from that order>` → the order with a snippet; the same as the `HEALTH`
   officer → no result.
6. `SELECT count(*) FROM documents WHERE doc_group='internal' AND sourcetrace_status <> 'not_applicable'` → 0.
7. Stop `clamav` (`docker compose stop clamav`); an upload → 503 `scanner_unavailable`, nothing new in the store;
   start it again.
8. `pytest -q` green, `ruff check` clean.

## Open questions
None. Points the owner may wish to overrule at approval:
- decision 4, the size limit: 20 MB per file (`UPLOAD_MAX_BYTES`), the architect's proposal — the plan gives no
  number;
- decision 3, the accepted formats: PDF, DOCX, DOC, JPEG, PNG; TIFF, ODT and macro-enabled Word are refused;
- decision 5, uploading needs a working relation to the case (owner, allotted, custody, request, counsel), not
  only sight of it (pool, recommended, State-wide); `visibility` must be chosen on every upload (no default);
- decision 7, `case_scope` documents are not shown to standing counsel (Table 1: they see what is shared with
  counsel), "private to the office" is the office itself plus its department's head and admin, and State-wide
  readers (oversight, central operator, auditor) see every document, private ones included;
- decision 9, a court filing kept `private_to_office` is not sent to SourceTrace until its visibility is widened;
- decision 10, no OCR: scanned PDFs, images and `.doc` files are stored with `text_status = none` and are not
  searchable by content;
- decision 12, downloads of uploaded documents are audited; order downloads and listings are not;
- decision 13, only visibility and archive can change after upload; no unarchive.
