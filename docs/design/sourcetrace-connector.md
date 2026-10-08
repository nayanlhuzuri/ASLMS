# Design: SourceTrace connector — the interface, the fake, ingestion of court records and court filings

```
slug: sourcetrace-connector
status: approved
author: architect
date: 2026-10-08
approved_by: owner (nayanlhuzuri) on 2026-10-08
```

## Context
Plan §3.2 (Table 5, Figure 2): every court order, and every court filing uploaded by users, is added to
SourceTrace through its ingestion API "with its case details (CNR, case number, court, document date)"; an
ingestion job is placed in the background queue when a new order is stored or a filing is uploaded; the portal
records the ingestion status (pending, ingested, failed) and the reference SourceTrace returns; failures are
retried automatically and those that still fail are listed on an administration screen; batches must not
overload either system. Plan §5.6 / §5.9: internal documents and notes are never sent. Plan §5.10: the data
collection health report shows failed SourceTrace ingestions. CLAUDE.md: all AI goes through the SourceTrace
connector interface; the SourceTrace endpoints are not known yet, so code against the interface and use a fake
in tests; never send case notes or internal documents. Backlog row 8.

In place today:
- `core/config.py`: `SOURCETRACE_ENABLED` (default `false`), `SOURCETRACE_BASE_URL`, `SOURCETRACE_API_KEY`
  (a `SecretStr`); nothing reads them.
- `documents.sourcetrace_status` (`not_applicable` / `pending` / `ingested` / `failed`) and `sourcetrace_ref`;
  CHECK `ck_documents_internal_not_sent`. Writers: `orders.fetch_order_pdf` (order PDFs: `court_record`,
  scan `skipped`, `pending`), `causelists.store_pdf` (`not_applicable`), `documents.upload` and
  `change_visibility` (documents-uploads decision 9: internal never; a court filing kept `private_to_office` is
  `not_applicable` until widened; an `ingested` filing cannot be narrowed, 409 `already_ingested`), note
  attachments and admin documents (`internal`, so `not_applicable` by the CHECK). The document detail shows
  `assistant_available` (= `ingested`).
- Table `sourcetrace_ingestions` (migration 0001, derived, FK to `documents` CASCADE per DB_STANDARD §6):
  `id`, `document_id`, `attempt`, `ok`, `reference`, `error`, `metadata_sent`, `created_at`; empty; no writer.
- `source_failures` and `matching.record_failure` (used by text extraction); `job_runs`; the Celery
  `scheduler` service (`worker -B --concurrency 1`) that runs the 5-minute text and alert jobs.
- Documents waiting: every order PDF stored by the historical load since 2025-01-01 is `pending`, plus the
  eligible uploads.
- Lessons from the 26–29 Sep build (read only, nothing copied): a `KnowledgeService` protocol with a stub that
  refused ingestion, so nothing could be tested end to end; the stub mixed ingestion, next-date reading and chat
  in one protocol before any shape was known.

Not covered: the real HTTP connector (the SourceTrace API is not documented; a follow-up row is proposed under
"Left for later"); the query API, the Case Assistant and its conversations (`assistant`, row 14); SourceTrace
reading of next-date directions (follows `next-date-extraction`, row 26, once the query API is known); removal
of a document from SourceTrace (no endpoint known); OCR (row 23); the portal screen for failures
(`portal-*` rows) and the data-health page (`audit-screens`, row 10), which read the API written here.

## Decisions
1. **One connector interface in the integration layer, ingestion only for now.**
   `backend/aslms/integration/sourcetrace/` holds the `SourceTraceConnector` protocol, its value types and
   errors, `get_connector(settings)` and the fake. The protocol has `name` and one async method,
   `ingest(item) -> IngestResult`. The query side (`ask`, `read_order`) is added by the items that use it,
   when their shapes are known. Alternative: one protocol with ingest, next-date and chat now (as in the
   September build) — rejected: it would fix three unknown API shapes at once. Alternative: synchronous
   protocol — rejected: `CourtSource` is async and the Case Assistant will be called from FastAPI.
2. **No real implementation in this item; the fake is for tests only.** `get_connector(settings)` returns
   `None` and `connector_state(settings)` answers `disabled` when `SOURCETRACE_ENABLED` is false, and
   `not_implemented` when it is true (no HTTP connector exists yet). It never returns the fake, whatever the
   settings: a fake reference written to the real database would be a fabricated identifier. The fake
   (`integration/sourcetrace/fake.py`, `FakeSourceTrace`) records every item it receives, returns the reference
   `fake-<sha256 of content, first 24 hex>` and can be scripted to answer `unavailable`, `rejected`, a timeout
   or a malformed reference for the next n calls. Tests pass it to the service directly. Alternative: a
   selectable `SOURCETRACE_CONNECTOR=fake` for demos — rejected for the same reason (fake references would mark
   documents "available to the Case Assistant").
3. **Only court orders and court filings, decided by the document's own nature, checked three times.**
   A document is sendable only when all hold: (a) `kind = order`, `doc_group = court_record`, scan `skipped`,
   and an `orders` row points at it; or `kind = upload`, `doc_group = court_filing`, scan `clean`;
   (b) `visibility <> private_to_office`; (c) not archived; (d) its case has a CNR (decision 8). Never sendable:
   cause-list PDFs, note attachments (`kind attachment`, always internal), admin documents, internal uploads,
   note text of any kind. The rule is enforced by (i) the claim query, (ii) `assert_sendable(doc, case, order)`
   called again under the row lock just before the bytes leave (a failure raises `NotSendable`, sends nothing,
   writes a `source_failures` row of kind `sourcetrace_guard` and leaves the status alone), and (iii) database
   CHECKs (Data): `ck_documents_internal_not_sent` (exists), new `ck_documents_sourcetrace_kind` (only `order`
   and `upload` may be other than `not_applicable`) and `ck_documents_private_not_sent`. A court filing that a
   note links to (custody-workflow decision 18, "existing case documents may be linked, keeping their own
   visibility") remains a court filing and is sent; the note, its text and its own attachments are not.
   **Owner check:** the architect's reading of the approved rules.
4. **The metadata sent is fixed and court-public.** Exactly: `external_id` (the document id, also the
   idempotency key), `source_kind` (`court_order` / `court_filing`), `doc_type` and its label, `document_date`
   (`doc_date`; the order date for orders), `cnr`, `case_number` (`case_no_text`), `court` (`est_code`,
   `name`), and for orders `order_no`, `order_kind` (`interim` / `final` / `judgment`) and
   `order_judge_name`; plus `filename` (synthetic: `<CNR>_<order_no>_<date>.pdf` for orders,
   `<ref_no with dashes>.<ext>` for uploads), `mime`, `size_bytes`, `sha256`. Never sent: the uploader's
   `description` and `original_filename` (user text that may carry internal remarks), the uploader, office and
   visibility, any note, custody or ownership data. The content is the stored file's bytes as stored. The
   metadata is built by one pure function and stored verbatim in `sourcetrace_ingestions.metadata_sent`.
   **Deviation (minor, flagged):** the plan names four case details; the document identity, type, order number
   and kind are added because citations must open the document in the portal (§5.9) and the Case Assistant
   must be able to keep "related past cases" to orders and judgments (§5.9: "orders and judgments in related
   past cases") rather than other cases' filings.
5. **The pending status is the queue; one document per transaction.** No `fetch_queue` kind: that queue is
   NAPIX work under the NAPIX quota and its worker; SourceTrace work must not compete with it. The ingestion
   job claims one due document at a time (`FOR UPDATE OF documents SKIP LOCKED`), sends it, records the outcome
   and commits, so two runs never send the same document and a crash loses at most one attempt. Order of
   work: uploads before orders (a user is waiting), then `doc_date` newest first, then `created_at`, so the
   historical backlog drains behind new material. Alternative: batch in one transaction with savepoints (as
   text extraction) — rejected: it would hold every claimed row locked across many network calls.
6. **Changes to a document wait for or refuse an in-flight send.** The send holds the document row lock (at
   most `SOURCETRACE_TIMEOUT_SECONDS`). `documents.change_visibility` and `documents.archive` now lock the row
   first with `FOR UPDATE NOWAIT`; a row being sent answers 409 `document_busy` ("being sent to SourceTrace; try
   again in a minute"). Without this, a visibility change read before the send commits could overwrite
   `ingested` with `not_applicable` while the file is in SourceTrace. Alternative: wait for the lock — rejected:
   an API request could hang for the connector timeout.
7. **Retries.** `SourceTraceUnavailable` (connection, 5xx, throttling), a timeout, or any unexpected connector
   exception: attempt recorded, `sourcetrace_attempts + 1`, back to `pending` with `sourcetrace_next_at` =
   now + 10 min × 2^(attempts − 1) (10, 20, 40, 80 minutes); at `SOURCETRACE_MAX_ATTEMPTS` (5) the document is
   `failed`. The run stops claiming after the first unavailable / timeout outcome (SourceTrace is down; the
   next run tries again). `SourceTraceRejected` (the document refused, e.g. type or size) and a malformed
   answer (empty reference or longer than 200 characters, family `protocol`) fail at once, no retry. A file
   missing from the store fails at once (family `store`). Every `failed` writes or refreshes a
   `source_failures` row (kind `sourcetrace_ingestion`, ref the document id); a later success resolves it.
8. **A court filing on a provisional case waits for the CNR.** It stays `pending` but is not claimed until the
   case has a CNR (counted as `waiting_cnr` in the status). SourceTrace keys the case's material by CNR, and a
   provisional case may later be merged; sending it with no CNR would file it under no case. Orders always have
   a CNR. **Deviation (minor, flagged):** plan §3.2 sends a filing "when uploaded".
9. **Archiving stops sending.** `documents.archive` sets a `pending` or `failed` document to `not_applicable`
   (before / after in the existing `document.archived` audit row); an `ingested` one stays `ingested` with its
   reference (removal from SourceTrace has no known endpoint), and the Case Assistant (row 14) must not pass
   archived documents as context. Migration 0011 back-fills archived `pending` / `failed` rows. This takes
   over "archive stops SourceTrace queueing" from `documents-hardening` (row 25).
10. **Widening a private filing re-queues it cleanly.** `change_visibility` from `private_to_office` to a wider
    visibility sets `pending` with `sourcetrace_attempts = 0` and `sourcetrace_next_at = NULL`; narrowing a
    `pending` / `failed` filing sets `not_applicable` (as today); narrowing an `ingested` one stays 409
    `already_ingested`. A change between `case_scope` and `counsel_shared` touches nothing: visibility is not
    sent (decision 4); the Case Assistant filters the references it passes by the asking user's document
    visibility (a rule for row 14, recorded here).
11. **Shared order PDFs are sent once.** An order PDF is one `documents` row even when several cases' orders
    point at it (`ix_documents_system_sha`); it is sent once, with the case of `documents.case_id`. The portal,
    not SourceTrace, knows which cases use it: the Case Assistant passes the `sourcetrace_ref` of every order of
    the case as context, shared or not. No re-send when another case starts using an ingested PDF.
12. **Records and audit.** `sourcetrace_ingestions` is the record of every attempt (append-only; metadata sent,
    reference, outcome family, duration, SourceTrace's response body verbatim). System sends write no
    `audit_log` row (hundreds of thousands of order sends would bury the trail; the ingestion record is
    append-only and queryable). Human actions are audited: `sourcetrace.retry_requested` (one document, API or
    CLI) and `sourcetrace.retry_all_failed` (CLI, with the count). **Owner check.**
13. **A new function `admin.sourcetrace`** ("SourceTrace ingestion": see the ingestion status and the failed
    documents, retry them). Enabled by default for `central_operator` (who runs data collection) and held by
    the super admin; seed only (50 rows, 48 active). The failure list applies the document visibility rule, so
    a holder without State-wide sight sees only the documents of cases they can see. Alternative: reuse
    `admin.napix_refetch` — rejected: a different system. **Owner check:** the default holder.
14. **Batches that cannot overload either system.** Beat every 5 minutes; each run sends at most
    `SOURCETRACE_BATCH` (20) documents and stops claiming after `SOURCETRACE_RUN_SECONDS` (240), so the
    single-concurrency `scheduler` worker is never held past its next 5-minute jobs; ceiling 5,760 documents a
    day, adjustable in `.env`. No per-document dispatch after an upload or a download: the 5-minute beat is the
    "job placed in the background queue" of Figure 2 (latency ≤ 5 minutes).
15. **Nothing runs until a real connector exists.** With the state `disabled` or `not_implemented` the job
    returns at once with `{"state": …}`, sends nothing and writes no `job_runs` row; `not_implemented` logs one
    warning per run. Documents keep accumulating as `pending`, so the backlog is sent in batches once the
    connector arrives (the plan's batch mechanism, decision 14). Secrets: `SOURCETRACE_API_KEY` comes from
    `.env` only; the connector's `repr` and every log line omit it; `metadata_sent` and `response` never hold it.

## Data
Migration **0011** (`0011_sourcetrace.py`, new; no applied migration is edited).

Replace the `documents` row's notes in `docs/schema/schema.md` (Group 6) by adding:

> (sourcetrace-connector, migration 0011) `sourcetrace_attempts` (integer NOT NULL default 0; attempts since the
> document last became `pending`), `sourcetrace_next_at` (timestamptz NULL; not claimed before this),
> `sourcetrace_ingested_at` (timestamptz NULL). CHECKs `ck_documents_sourcetrace_kind` (`sourcetrace_status =
> 'not_applicable' OR kind IN ('order', 'upload')`), `ck_documents_private_not_sent` (`visibility <>
> 'private_to_office' OR sourcetrace_status = 'not_applicable'`), `ck_documents_sourcetrace_ingested`
> (`sourcetrace_status <> 'ingested' OR (sourcetrace_ref IS NOT NULL AND sourcetrace_ingested_at IS NOT
> NULL)`). Partial index `ix_documents_sourcetrace_due` (`sourcetrace_next_at`) WHERE `sourcetrace_status =
> 'pending'`. `sourcetrace_status`, `sourcetrace_ref`, `sourcetrace_attempts`, `sourcetrace_next_at` and
> `sourcetrace_ingested_at` are written only by `services/sourcetrace_ingest.py`, except the transitions of
> `services/documents.py` (upload, visibility change, archive: design `sourcetrace-connector` decisions 9–10).
> `sourcetrace_ref` is SourceTrace's reference stored verbatim (≤ 200).

Replace the `sourcetrace_ingestions` row (Phase 2 and 3 tables):

> | `sourcetrace_ingestions` (derived, append-only) | id (uuid v7 PK), document_id (→ documents CASCADE, DB_STANDARD §6), attempt (integer NOT NULL; the document's `sourcetrace_attempts` after this attempt), ok (boolean NOT NULL), connector (varchar 40 NOT NULL; the implementation's `name`), reference (≤ 200, NULL), error (text ≤ 2,000, NULL), error_family (varchar 40 NULL: `unavailable` / `timeout` / `rejected` / `protocol` / `store` / `error`), duration_ms (integer NOT NULL default 0), metadata_sent (jsonb NOT NULL; exactly what was sent besides the bytes), response (jsonb NULL; SourceTrace's answer verbatim), created_at | CHECK `ck_sourcetrace_ingestions_outcome` (`(ok AND reference IS NOT NULL AND error_family IS NULL) OR (NOT ok AND error IS NOT NULL AND error_family IS NOT NULL)`). Index `ix_sourcetrace_ingestions_document_created` (document_id, created_at) replaces `ix_sourcetrace_ingestions_document_id`. Trigger `aslms_forbid_change` (`sourcetrace_ingestions_append_only`); `aslms_app` SELECT / INSERT only. One row per attempt, written only by `services/sourcetrace_ingest.py` in the transaction that records the outcome on the document. Never holds secrets, note text or internal documents (design `sourcetrace-connector`). |

`ref_permission`: + `admin.sourcetrace` (module `admin`, "SourceTrace ingestion"; seed only; 50 rows, 48
active); `role_permissions` row enabled for `central_operator`, disabled for the other types (seed inserts only
missing rows). No new `ref_*` code set; no new enum.

Migration 0011 steps:
1. Guard: stop if any `sourcetrace_ingestions` row exists (none was ever written; the new NOT NULL columns
   assume an empty table).
2. Back-fill: `UPDATE documents SET sourcetrace_status = 'not_applicable' WHERE archived_at IS NOT NULL AND
   sourcetrace_status IN ('pending', 'failed')` (decision 9). Then verify no row breaks the new CHECKs (stop
   with the counts if one does).
3. Add the three `documents` columns, the three CHECKs and the partial index.
4. Add `connector`, `error_family`, `duration_ms`, `response` to `sourcetrace_ingestions`; `metadata_sent` NOT
   NULL; the CHECK; swap the index; the append-only trigger; `REVOKE UPDATE, DELETE ON sourcetrace_ingestions
   FROM aslms_app`.
Downgrade: stop if `sourcetrace_ingestions` has rows or a document has `sourcetrace_attempts > 0` or
`sourcetrace_ingested_at` set; otherwise drop what step 3–4 added and restore the grant and index. The
back-filled statuses stay `not_applicable` (consistent with the 0006 rules).

## Services
`backend/aslms/integration/sourcetrace/` (new package; the only place a SourceTrace implementation may live):
- `connector.py`: `IngestItem` (frozen: `document_id: uuid.UUID`, `content: bytes`, `mime: str`,
  `filename: str`, `metadata: dict[str, Any]`), `IngestResult` (`reference: str`, `raw: dict | None`),
  `SourceTraceConnector` protocol (`name: str`; `async def ingest(self, item: IngestItem) -> IngestResult`),
  errors `SourceTraceError(IntegrationError)`, `SourceTraceUnavailable`, `SourceTraceRejected`.
- `__init__.py`: `connector_state(settings) -> Literal["disabled", "not_implemented", "ready"]` and
  `get_connector(settings) -> SourceTraceConnector | None` (decision 2; `ready` is unreachable until a real
  connector is added).
- `fake.py`: `FakeSourceTrace` (decision 2): `received: list[IngestItem]`, `script(*outcomes)` with outcomes
  `ok`, `unavailable`, `rejected`, `timeout` (sleeps past the timeout), `bad_reference`.

`backend/aslms/services/sourcetrace_ingest.py` (new; the only service that imports the connector until row 14):
- `IngestConfig` (`batch`, `run_seconds`, `timeout_seconds`, `max_attempts`; `from_settings`).
- `build_metadata(doc, case, court, order) -> dict` — pure, decision 4; `filename_for(doc, case, order)`.
- `assert_sendable(doc, case, order) -> None` — decision 3 (raises `NotSendable`).
- `backoff(attempts) -> timedelta` — decision 7.
- `claim_due(session, *, document_id=None) -> Document | None` — the claim query of decisions 3, 5, 8.
- `async ingest_one(session, connector, store, doc, config) -> Outcome` — decisions 3, 4, 7: guard, read the
  file, send with `asyncio.wait_for`, write the `sourcetrace_ingestions` row and the document columns, write
  or resolve `source_failures`.
- `async ingest_pending(Session, connector, store, config, *, document_id=None) -> dict` — the loop of decisions
  5 and 14 (one session per document, committed each time; stops on batch, run time, or the first
  unavailable / timeout). Counters: `claimed`, `ingested`, `retrying`, `failed`, `guarded`, `stopped`
  (`unavailable` / `batch` / `time` / `empty`).
- `run(Session, connector, store, config) -> dict` — sync wrapper (`asyncio.run`) for Celery and the CLI; writes
  the `job_runs` row (`job = sourcetrace_ingest`, status `partial` when anything failed or retried).
- `status(session, settings) -> dict` — state, connector name, counts by status for kinds `order` and `upload`,
  `waiting_cnr`, `due_now`, oldest pending `created_at`, the last `sourcetrace_ingest` run.
- `failed(session, user, *, limit, offset) -> (rows, total)` — failed documents filtered by the document
  visibility rule (`services/visibility.py`), with the latest attempt's error, family and time.
- `retry(session, actor, user | None, doc) -> Document` — `failed` (or `pending` waiting on back-off) →
  `pending`, attempts 0, `next_at` NULL; 409 `not_retryable` for `ingested` / `not_applicable`; audit
  `sourcetrace.retry_requested` (entity `document`, `case_id`, before / after status and attempts).
- `retry_all_failed(session, actor) -> int` — CLI; one audit row `sourcetrace.retry_all_failed` with the count.

`backend/aslms/services/documents.py` (changes):
- `change_visibility` and `archive` load the document `FOR UPDATE NOWAIT`; a lock failure raises
  `DocumentBusy` (409 `document_busy`) — decision 6.
- `change_visibility`: widening resets `sourcetrace_attempts` / `sourcetrace_next_at` (decision 10).
- `archive`: `pending` / `failed` → `not_applicable`, recorded in the audit row's before / after (decision 9).

## API
New router `api/routers/sourcetrace.py`; errors `{code, message}` as elsewhere; `{doc}` a document id or
`ref_no` (slash or dash form), as in the documents API.

- `GET /admin/sourcetrace/status` — `admin.sourcetrace`. Response `{state: "disabled" | "not_implemented" |
  "ready", connector: str | null, counts: {pending, ingested, failed, not_applicable}, waiting_cnr, due_now,
  oldest_pending_at: datetime | null, last_run: {started_at, finished_at, status, counters} | null}`. Counts
  are totals (no case data), so no visibility filter.
- `GET /admin/sourcetrace/failed?limit=50&offset=0` — `admin.sourcetrace`. Response `{total, items: [{document_id,
  ref_no?, kind, doc_type, doc_date, case: {id, ref_no, cnr?, case_no_text?}, attempts, last_error,
  error_family, last_attempt_at}]}`; only documents the caller may see (document visibility rule); `limit`
  1–200.
- `POST /admin/sourcetrace/documents/{doc}/retry` — `admin.sourcetrace` and sight of the document (404
  otherwise). 200 with the document's `{document_id, sourcetrace_status, sourcetrace_attempts}`; 409
  `not_retryable`; audited (decision 12).
- Changed: `PATCH /documents/{doc}` and `POST /documents/{doc}/archive` may answer 409 `document_busy`.
  `GET /documents/{doc}` adds `sourcetrace_ingested_at` (null unless ingested).

CLI (`aslms sourcetrace`): `status`; `run [--batch N] [--document ID]` (refuses unless the state is `ready`);
`retry --document ID` / `retry --all-failed` (system actor `cli`, audited); `check` (prints the count of
documents that break decision 3's rule while not `not_applicable`, and of ingestion rows on documents that
are not sendable now; both must be 0; exit code 1 otherwise).

## Jobs
- Celery task `aslms.sourcetrace_ingest`, beat entry `sourcetrace-ingest` every 5 minutes
  (`crontab(minute="*/5")`) in the `scheduler` service: `connector_state` first (decision 15), then
  `sourcetrace_ingest.run`; a `job_runs` row (`job = sourcetrace_ingest`) only when the state is `ready`.
- The queue is `documents.sourcetrace_status = 'pending'` with `sourcetrace_next_at` (decision 5); no
  `fetch_queue` kind, no `ref` format.
- Settings in `.env.example` (no secrets): `SOURCETRACE_ENABLED=false`, `SOURCETRACE_BASE_URL=`,
  `SOURCETRACE_API_KEY=`, `SOURCETRACE_BATCH=20`, `SOURCETRACE_RUN_SECONDS=240`,
  `SOURCETRACE_TIMEOUT_SECONDS=60`, `SOURCETRACE_MAX_ATTEMPTS=5`.

## Tests
Unit (`tests/unit/`):
- `test_metadata_has_exactly_the_allowed_keys` — order and upload; no description, original filename,
  uploader, office, visibility; synthetic filenames.
- `test_assert_sendable_refuses_each_forbidden_case` — internal upload, attachment, admin, cause list,
  private filing, archived, provisional case, order kind without an order row, unscanned upload.
- `test_backoff_schedule` — 10, 20, 40, 80 minutes.
- `test_get_connector_states` — disabled → None; enabled → `not_implemented`, None; never the fake.
- `test_only_ingest_service_imports_the_connector` — scans `aslms/` for imports of
  `aslms.integration.sourcetrace` outside the package, `services/sourcetrace_ingest.py`, `jobs/celery_app.py`
  and `cli/sourcetrace.py` (the API router reaches it only through the service).
- `test_fake_records_and_follows_its_script`.
- `test_connector_repr_and_logs_hide_the_api_key` — settings with a dummy key; `repr`, log capture.

Database (`tests/db/test_sourcetrace.py`, with `FakeSourceTrace` and the `world` fixture):
- `test_order_pdf_ingested_with_reference_attempt_and_metadata` — status, ref, `ingested_at`, one ok row,
  `metadata_sent` equal to what the fake received.
- `test_court_filing_case_scope_and_counsel_shared_ingested`.
- `test_internal_uploads_attachments_admin_and_causelists_never_sent` — fake receives nothing.
- `test_linked_court_filing_still_sent_and_note_never` — a filing linked to a note is sent; nothing of the
  note reaches the fake.
- `test_private_filing_waits_until_widened` — widened → pending with attempts 0 → ingested.
- `test_archive_stops_sending` and `test_archived_ingested_keeps_reference`.
- `test_provisional_case_filing_waits_for_cnr`.
- `test_unavailable_backs_off_then_fails_after_max_attempts` — `source_failures` row; the run stops after the
  first unavailable.
- `test_timeout_counts_as_unavailable`; `test_rejected_and_bad_reference_fail_at_once`;
  `test_missing_file_fails_with_store_family`.
- `test_success_resolves_the_source_failure`.
- `test_two_runs_never_send_the_same_document` — two sessions in parallel, each document sent once.
- `test_visibility_change_during_send_answers_document_busy`.
- `test_batch_and_run_time_limits`; `test_uploads_before_orders_newest_first`.
- `test_disabled_job_sends_nothing_and_writes_no_run`.
- `test_shared_order_pdf_sent_once`.
- `test_checks_refuse_private_pending_causelist_pending_and_ingested_without_ref`.
- `test_ingestion_rows_are_append_only` — UPDATE and DELETE raise.
- `test_migration_0011_back_fills_archived_and_down_up` — and the downgrade guard with rows present.

API (`tests/db/test_api_sourcetrace.py`):
- `test_status_requires_admin_sourcetrace` — 403 without, central operator and super admin 200; counts.
- `test_failed_list_respects_document_visibility` — a granted department admin sees only their cases.
- `test_retry_requeues_audits_and_refuses_ingested` — 409 `not_retryable`, 404 for an invisible document.
- `test_document_detail_shows_ingested_at`.
- `test_seed_adds_admin_sourcetrace` — 50 rows, 48 active; enabled for `central_operator` only.

## Verification
1. `ruff check` clean; `pytest -q` green (the new tests run against the migrated test database).
2. `alembic upgrade head` on the dev database (0011), then `aslms seed`.
3. `aslms sourcetrace status` → state `disabled`; `pending` = number of order PDFs stored plus eligible
   uploads; `SELECT count(*) FROM sourcetrace_ingestions` → 0.
4. `aslms sourcetrace check` → both counts 0, exit 0. Also `SELECT count(*) FROM documents WHERE
   sourcetrace_status <> 'not_applicable' AND (doc_group = 'internal' OR kind NOT IN ('order', 'upload') OR
   visibility = 'private_to_office' OR (archived_at IS NOT NULL AND sourcetrace_status <> 'ingested'))` → 0.
5. `aslms sourcetrace run` → refused (state `disabled`), nothing written.
6. `GET /admin/sourcetrace/status` as the super admin → 200 with the same counts; as a department officer → 403.
7. Real sending cannot be verified until the HTTP connector exists (follow-up row); the fake-backed tests are
   the proof for this item.

## Open questions
None. Points for the owner to check at approval (decided here, reversible): decision 3 (a court filing linked
to a note is still sent), decision 4 (metadata beyond the plan's four case details), decision 8 (filings of
provisional cases wait for the CNR), decision 12 (no audit row per system send), decision 13 (`admin.sourcetrace`
enabled for the central operator by default).

## Left for later
- New backlog row `sourcetrace-http-connector`: the real connector against the SourceTrace ingestion API
  (endpoint, authentication, size and type limits, use of `external_id` for idempotency, error mapping to
  `unavailable` / `rejected`), blocked until the SourceTrace API documentation is provided.
- New backlog row `sourcetrace-next-dates`: SourceTrace reading of next-date directions in ingested orders
  (plan §3.2 Figure 2, §5.5), after `next-date-extraction` (row 26) and the query API.
- Removal from SourceTrace of archived ingested documents, if SourceTrace offers it.
- Row 25 (`documents-hardening`) loses "archive stops SourceTrace queueing" (decision 9 does it).
- Row 14 (`assistant`): pass only references of documents the asking user may see, never archived ones, and
  keep related-case retrieval to `source_kind = court_order` (decisions 4, 9, 10, 11).

## Deviations
Written by the developer while building (2026-10-08); each is the smallest option where the design was silent
or the platform did not allow the letter of it.
1. **Migration 0011: autogenerated, then written as a new file.** The repository guard treats every file under
   the migration versions directory as applied, so the autogenerated scaffold (columns and indexes only) was
   removed and the reviewed revision written fresh from "Data", with the three `documents` CHECKs, the outcome
   CHECK, the append-only trigger and the grant change added by hand. `compare_metadata` is empty;
   `sourcetrace_ingestions` joins `APPEND_ONLY_TABLES` in `db/base.py`.
2. **`build_metadata(doc, case, court, order, *, doc_type_label=None)`.** The label lives in `ref_doc_type`,
   which a pure function cannot read; `ingest_one` passes it.
3. **`FakeSourceTrace` has two extras for the tests:** an `error` outcome (an unexpected exception, decision 7's
   "any unexpected connector exception", retried like `unavailable` but not stopping the run) and an
   `on_ingest(item)` hook called while the document row is locked (the `document_busy` and two-runs tests);
   `timeout_sleep` sets how long `timeout` sleeps.
4. **`claim_due` takes `exclude`** (documents already claimed in this run), so a document refused by the guard
   is not claimed again until the next run; and an explicit `document_id` (`aslms sourcetrace run --document`)
   is claimed without waiting for its back-off.
5. **A guard refusal** writes `source_failures` (kind `sourcetrace_guard`, family `guard`), is counted as
   `guarded`, and makes the run `partial` like a failure or a retry.
6. **`retry` of a `pending` document** is accepted only while it waits on back-off (`sourcetrace_attempts > 0` or
   `sourcetrace_next_at` set); a fresh `pending` answers 409 `not_retryable`.
7. **Widening an archived private filing does not queue it** (decisions 9 and 10 together): only a non-archived
   filing goes from `private_to_office` to `pending`. Archiving also clears `sourcetrace_next_at`.
8. **`aslms sourcetrace check`:** the first count is documents not `not_applicable` whose nature breaks decision 3
   (a) / (b), or archived while not `ingested`; filings waiting for a CNR (decision 8) are not counted. The second
   is ingestion rows of documents whose nature (a) / (b) is not sendable; an archived ingested document
   (decision 9) is not counted.
9. **`GET /admin/sourcetrace/status`: `connector` is `null`** while no real connector is ready; the counts cover
   kinds `order` and `upload`.
10. **Settings bounds:** `SOURCETRACE_BATCH` 1–1000, `SOURCETRACE_MAX_ATTEMPTS` 1–20, run and timeout seconds > 0.
