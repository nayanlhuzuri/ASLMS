# Report: sourcetrace-connector (backlog row 8)

Date: 2026-10-08. Design: [docs/design/sourcetrace-connector.md](../design/sourcetrace-connector.md) (approved by the owner on 2026-10-08). Branch `feature/sourcetrace-connector`, squash-merged into `main` (commit `eb2741e`), tag `feature/sourcetrace-connector-done`.

## What changed

**Migration 0011** (`backend/migrations/versions/0011_sourcetrace.py`; `schema.md` updated first)
- `documents` gains `sourcetrace_attempts`, `sourcetrace_next_at`, `sourcetrace_ingested_at`; CHECKs `ck_documents_sourcetrace_kind`, `ck_documents_private_not_sent`, `ck_documents_sourcetrace_ingested`; partial index `ix_documents_sourcetrace_due`.
- `sourcetrace_ingestions` gains `connector`, `error_family`, `duration_ms`, `response`, `metadata_sent` (NOT NULL); CHECK `ck_sourcetrace_ingestions_outcome`; index `ix_sourcetrace_ingestions_document_created`; append-only trigger (`aslms_app` loses UPDATE and DELETE).
- Back-fills archived `pending` / `failed` documents to `not_applicable`. The upgrade stops if any ingestion row exists; the downgrade stops if any ingestion row exists or a document has attempts or an ingested time.
- Seed: function `admin.sourcetrace` (50 rows, 48 active), on by default for `central_operator`.

**Code**
- `backend/aslms/integration/sourcetrace/`: `SourceTraceConnector` protocol (ingest only), `IngestItem`, `IngestResult`, `SourceTraceUnavailable`, `SourceTraceRejected`, `connector_state`, `get_connector` (returns `None`; never the fake), and `FakeSourceTrace` for tests.
- `services/sourcetrace_ingest.py` (new): `build_metadata`, `assert_sendable`, `backoff`, `claim_due`, `ingest_one`, `ingest_pending`, `run`, `status`, `failed`, `retry`, `retry_all_failed`. `services/documents.py`: `lock_document`, `change_visibility`, `archive`, `document_out`.
- API: `GET /admin/sourcetrace/status`, `GET /admin/sourcetrace/failed`, `POST /admin/sourcetrace/documents/{doc}/retry`; `PATCH /documents/{doc}` and `POST /documents/{doc}/archive` may answer 409 `document_busy`; `GET /documents/{doc}` adds `sourcetrace_ingested_at`.
- CLI `aslms sourcetrace` (`status`, `run`, `retry`, `check`); Celery task `aslms.sourcetrace_ingest` with beat entry `sourcetrace-ingest` every 5 minutes (scheduler service).
- `.env.example`: `SOURCETRACE_BATCH`, `SOURCETRACE_RUN_SECONDS`, `SOURCETRACE_TIMEOUT_SECONDS`, `SOURCETRACE_MAX_ATTEMPTS`.
- Tests: `tests/unit/test_sourcetrace.py` (7), `tests/db/test_sourcetrace.py` (23), `tests/db/test_sourcetrace_gaps.py` (8), `tests/db/test_api_sourcetrace.py` (5), helper `tests/db/st_support.py`; existing tests adjusted for 50 functions.

## Gates

| Gate | Result |
|---|---|
| `ruff check .` (backend) | All checks passed! |
| `pytest -q` (backend, Compose postgres up) | 696 passed, 62 warnings in 555.82s |
| `docker compose build` | succeeded (api, worker, scheduler, init built) |
| `git status` on the branch | clean |
| Design note status | `approved` |
| Definition of done | decisions-log entry (section "SourceTrace connector", 8 Oct 2026) and backlog row 8 exist; `CLAUDE.md` current focus updated; `.env.example` carries the new variables |

## Review findings and how they were closed

All five findings are advisory; none blocks the merge. Each is recorded as follow-up backlog row 38 (`sourcetrace-hardening`), and none can affect real data before the real connector (row 36) exists, because `get_connector` returns `None` and every document stays `pending`.

1. Narrowing to `private_to_office` is blocked only for `ingested`; a document whose last attempt was timeout or unavailable may already be held by SourceTrace. Open: row 38 (treat timeout/unavailable as possibly ingested, 409).
2. Archiving or narrowing a `failed` document leaves its `source_failures` row open; `sourcetrace_guard` rows are never resolved. Open: row 38.
3. `retry` takes a blocking `FOR UPDATE` instead of NOWAIT / `document_busy`. Open: row 38.
4. The same `meta` dict goes to the connector and into `metadata_sent`; unexpected connector exception text is stored verbatim. Must be fixed (deep copy, scrubbed or limited error text) before the real connector. Open: row 38; row 36 is blocked on the API documentation anyway.
5. The `failed` list's `max(created_at)` subquery groups the whole `sourcetrace_ingestions` table. Open: row 38 (restrict to failed documents or LATERAL join).

## Deviations

- Written back into the design note by the developer (see the note). No further deviation from the approved design at merge.
- The dev database is not upgraded to 0011 by this merge; upgrade it when the merged images are rebuilt (through the `init` service or `alembic upgrade head`).

## Follow-up backlog rows added

- 36 `sourcetrace-http-connector` (blocked on the SourceTrace API documentation)
- 37 `sourcetrace-next-dates`
- 38 `sourcetrace-hardening` (the five advisories above)

## Load status (`aslms queue-status`)

| kind | status | rows |
|---|---|---|
| causelist_day | done | 27 |
| causelist_day | pending | 593 |
| causelist_day | skipped | 23 |
| dossier | done | 14460 |
| dossier | failed | 135 |
| dossier | pending | 34 |
| dossier | skipped | 18 |
| masters | done | 1 |
| order_pdf | pending | 115643 |
| status_batch | done | 22 |
| status_batch | skipped | 1 |
