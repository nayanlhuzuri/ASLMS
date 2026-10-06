# Report: documents-uploads (2026-10-06)

Merged to main as 1b34182, tag `feature/documents-uploads-done`. Design: docs/design/documents-uploads.md (approved).

## What changed
- Migration 0006 (documents, document text and related columns); schema.md extended first.
- Services: filetypes (type by content), clamd scanner, documents (upload, visibility, archive, search), text_extract; API router documents; Celery extraction jobs; CLI; `clamav` service in Compose.
- Case detail Documents tab and counts use the visibility rule; order PDFs served from the store.
- 38 files, about 3.9k lines added.

## Gates
- ruff: All checks passed
- pytest: 349 passed, 14 warnings (238 s)
- docker compose build: succeeded
- git status clean; design status approved; decisions-log entry and backlog row present

## Review findings (all advisory; none blocked the merge)
1. filetypes: any OLE2 file accepted as .doc, macros unchecked. Open, follow-up.
2. filetypes: `%PDF-` check precedes ZIP check. Open,.
3. text_extract: database errors on writing results escape the savepoint and stall the batch. Open,.
4. celery: no time_limit on extraction tasks in the single-concurrency scheduler worker. Open,.
5. documents: duplicate check race gives 500 instead of 409. Open,.
6. documents: archiving leaves sourcetrace_status pending. Open,.
7. case_detail: counts.timeline counts hidden document_uploaded events. Open,.
8. documents: shared order PDF shown against first case when no case passed. Open,.
9. router: 413 guard relies on Content-Length; chunked bodies unbounded. Open,.

## Deviations
None beyond those in the design note's deviations section.

## Follow-up rows added to backlog
Backlog row 25 documents-hardening covers findings 1-8; finding 9 is row 24 upload-deployment-limits; OCR is row 23.

## Load status (queue-status)
causelist_day: done 5, pending 628, skipped 6; dossier: done 3043, failed 26, pending 109, skipped 3; masters: done 1; order_pdf: pending 23657.
