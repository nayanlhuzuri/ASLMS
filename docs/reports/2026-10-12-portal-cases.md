# Report: portal-cases (backlog row 12)

Merged 2026-10-12 as squash commit fff6ffe on main, tag `feature/portal-cases-done`.

## What changed
- 92 files, about 7800 lines. Frontend: case inbox (recommended, claimed, transfers), search (local and court), case page (timeline, orders, parties, notes, documents, ownership card), CaseLink, header search box, relay header fix (row 44 item 1), tests.
- Backend (9 files): five read-only API additions in `api/routers/{inbox,ownership,reference,workflow}.py`, `api/schemas.py`, `services/{custody,inbox,ownership,reference}.py`. Dismiss and Allot accept the department on screen (`office_code`).
- Tables: none. Migration: none. Department mapping screens split out to row 50.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 888 passed, 71 warnings (864 s).
- `docker compose build`: all five images built.
- `docker compose up -d --wait --no-deps web` healthy; `portal_smoke.py`: portal smoke: passed.
- git status clean; design note status approved; decisions-log entry (2026-10-12) and backlog row present.

## Review findings and closure
- Blocking (Dismiss/Allot sent no department): closed in ce53f1f ("Dismiss and Allot act for the department on screen"); gates green after it.
- Advisory, left open and carried to row 51: case-page Dismiss without department choice or `office_required` handling; Suggest and Request-transfer dialogs offering the caller's own department on the case page (API refuses with 400); portal-side choice of Allot / Take over row can differ from the API's department; super-admin Claim lists every department; Word note attachments offer View; Documents tab reads one page of 200 with no paging notice.
- Advisory, Compose verification: image build and web smoke now done and passing. Browser checks of steps 3-9 (live claim, allot, take over, transfer, sandboxed inline PDF in Chrome and Firefox) were not run; they remain in row 51.

## Deviations
Mapping screens excluded by the owner at approval (row 50). Live browser verification steps not run (see above).

## Follow-up rows
Row 51 (portal-cases-followups) already holds the follow-ups; the advisory items above are appended to it.

## Load status (`aslms queue-status`)
causelist_day done 63 / pending 540 / skipped 44; dossier done 22481 / failed 294 / pending 3014 / skipped 22; masters done 1; order_pdf done 15525 / failed 3 / pending 167016; status_batch done 145 / failed 1 / skipped 3.
