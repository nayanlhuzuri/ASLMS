# Report: portal-workflow (backlog row 13)

Date: 2026-10-13. Branch feature/portal-workflow, squash-merged to main (tag feature/portal-workflow-done). Design: docs/design/portal-workflow.md (approved by the owner, "approve, split").

## What changed
- Frontend (Next.js portal): case-page workflow. Send, recall and take back the file; custody and stage tab (holder, movement history, set stage); notes with drafts, permanent notes, corrections via supersedes and visibility chosen every time; uploads with pre-checks and explained refusals, document visibility and archiving (no delete, no unarchive); case Alerts tab with acknowledge and done. New components under `frontend/src/components/workflow/`, pages `cases/[ref]/custody` and `cases/[ref]/alerts`, `lib/workflow.ts`, `lib/flash.ts`, routes, messages and hooks.
- Backend: seven read-only API additions (routers `workflow.py`, `documents.py`; services `workflow_actions.py`, `workflow_codes.py`, `custody.py`, `notes.py`, `alerts.py`, `case_detail.py`, `reference.py`, `filetypes.py`). No new tables, no migration.
- Portal relay: forwards content-length so an oversized upload is refused early.
- Tests: new db tests (api_alerts, api_workflow, custody_send, notes, workflow_actions, extended documents and reference) and frontend tests (workflow, relay, routes, timeline, case).
- Nothing on these screens is sent to SourceTrace; notes, drafts and attachments are labelled internal.
- 58 files changed.

## Gates
- ruff check: All checks passed.
- pytest -q: 917 passed, 71 warnings (919 s).
- docker compose build: succeeded (all images built).
- Portal smoke (web rebuilt and healthy): portal smoke: passed.
- git status clean on branch; design status approved; decisions-log entry (13 Oct 2026) and backlog row present.

## Review findings
- Advisory (CustodyDialogs.tsx:136-146): when the send answer has `card: null`, the case queries are removed right after `router.push("/")` while the case page still observes them, which can trigger GET /cases/{ref} returning 404 and a brief not-found message. Not fixed in this cycle (advisory); recorded as follow-up row 57.

## Deviations
- Files and Alerts & calendar screens split into row 55 at approval (owner's choice).
- Compose signed-in verification steps are not run here: row 56.

## Follow-up rows
- 56 portal-workflow-verification (existing), 57 portal-send-away-race (new), 55 portal-files-alerts (split).

## Load status (queue-status)
order_pdf: done 22133, failed 5, pending 167652, skipped 47; status_batch: done 194, failed 1, skipped 3.
