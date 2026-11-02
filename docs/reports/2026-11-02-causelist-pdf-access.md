# Report: Cause list PDF access (row 196, `causelist-pdf-access`)

Merged 2 Nov 2026 as squash commit 45edb4c on `main`, tag `feature/causelist-pdf-access-done`.

## What changed
- Frontend only: `components/causelist/BenchChooser.tsx` (new), `CauseList.tsx`, `DayBar.tsx`, `EntryTable.tsx`, `causelist.module.css`, `lib/causelist.ts`, `lib/messages.ts`.
- View Cause List is always enabled. With All Benches it opens a bench chooser (bench, judges, number of lists); with a bench chosen it opens that bench. A plain note explains the per-bench PDFs. View and Download PDF links on each bench heading.
- Tests: `causelist.test.tsx`, `lib/causelist.test.ts`, uicheck fixtures and spec.
- Docs: design note, decisions log, software documentation build script (version 1.7), backlog.
- No tables, endpoints or migration. No NAPIX call (stored PDFs only).

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3099 passed, 3 skipped (36 min), every run green.
- `docker compose build`: succeeded (no `up`; the shared stack was not touched).
- Screen check on a private network (temporary `web` and uicheck images from the branch, then removed): 173 routes and states, 416 screenshots, 0 findings; 551 passed, 7 skipped.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (41419243244).

## Review findings
- Advisory, `CauseList.tsx:285`: the All Benches note is gated on the raw URL `bench_id` while the strip and view state use the resolved bench; a shared link to a bench that did not sit that day shows no note. Not fixed in this cycle; the fix is to gate the note on `!bench && !earlier`. Left open (see follow-ups).
- Advisory, `build.js:249`: `TOC_PAGES` not checked against a rendered copy after 4.10 grew. Already row 216.

## Deviations
- None beyond those in the design note (deviations 1 to 6).

## Follow-ups
- Row 216 (existing): check `TOC_PAGES` at the next regeneration.
- Row 217: gate the All Benches note on the resolved bench (`CauseList.tsx`).

## Load status
`aslms queue-status` did not answer within 2 minutes (the historical load is running); not recorded.

## Deployed
Deployed 2 Nov 2026 at 18:33 IST, after CI on `main` passed (run 41445135208: policy, backend, frontend, compose). No
migration. Images built from the clean `main` checkout at 4572d0b; `docker compose --profile monitoring up -d --wait`
with the court-data switch on recreated the app services, then `api`, `worker`, `scheduler` and `web` once more with
`--no-deps --force-recreate`; court data on in `api` and `worker`; the running `web` has the image's build ID;
`portal_smoke.py` passed. The second review advisory was checked on a rendered copy of
`docs/ASLMS_Software_Documentation.docx` (version 1.7): 38 pages, and all 17 contents entries match their headings'
pages, so `TOC_PAGES` needs no change.
