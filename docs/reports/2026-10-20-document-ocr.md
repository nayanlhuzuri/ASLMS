# document-ocr (backlog row 23), 20 Oct 2026

Owner chose option C: no OCR in Phase 1. Only Part 0 was built. Option B (SourceTrace returns the text it holds) is parked as row 96.

## What changed
- Backend: `services/data_health.py` and `api/schemas.py` add `documents_text` to `GET /admin/data-health` (per origin: pending, extracted, failed, none split into scanned_pdf, image, doc, other; totals only).
- Frontend: plain-words text labels (`lib/documents.ts`, `lib/messages.ts`), Documents tab, content-search note (`TextSearch.tsx`), health panel (`Health.tsx`); `openapi.json` and `schema.d.ts` regenerated.
- `pyproject.toml`: PyMuPDF pinned below 2 (no onnxruntime models under the "no local model" rule).
- Docs: design note, `schema.md` note, decisions log, backlog. No migration, no table change.

## Gates
- ruff: All checks passed.
- pytest: 1515 passed, 2 skipped (24m19s).
- docker compose build: succeeded.
- portal smoke: passed.
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings
1. Design API table omitted `none.other`: fixed on the branch (design note line 325).
2. Backend `_none_bucket` matches mime exactly while the frontend normalises case and `;` parameters: advisory, not triggered today because stored mimes are canonical; left as is.
3. Decisions log not updated: already updated on the branch (entry of 20 Oct 2026 covers the pin, option C and `none.other`).
4. Verification step 3 (browser upload of a scanned PDF and a PNG): not done by the integrator; remains an owner browser check.

## Deviations
None beyond the `none.other` bucket recorded in the design note.

## Follow-ups
Row 96 (ocr-via-sourcetrace, parked).

## Load status (queue-status)
order_pdf: done 80996, pending 220841, skipped 3; status_batch: done 693, skipped 6.
