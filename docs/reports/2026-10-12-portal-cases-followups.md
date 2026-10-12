# portal-cases-followups (12 Oct 2026)

Merge commit: 5209ee6 on main; tag `feature/portal-cases-followups-done`. Design: docs/design/portal-cases-followups.md (approved by the owner; merge not held for the browser checklist).

## What changed
- No migration, no new table. Three optional fields on existing ownership actions name the acting department; the server computes the possible departments per action.
- Case-page dialogs ask for a department when several apply (none pre-selected); buttons appear only when an action is possible; Allot / Take over show the chosen department's unit and officer.
- Suggest and request-transfer target lists exclude own and holding departments; transfers act for the owning department; super admin can claim for recommended departments from search results.
- Documents tab: paging per group, empty groups hidden; inline view for PDFs and images only (`INLINE_PDF` in `frontend/src/lib/documents.ts`, default true).
- 26 files changed, backend and frontend tests added.

## Gates
- ruff: All checks passed
- pytest: 899 passed (670 s)
- docker compose build: succeeded
- portal_smoke.py: portal smoke: passed
- git status clean; design status approved; decisions-log entry and backlog rows 51, 53 present

## Review findings
- Advisory (dialogs.tsx:368 with ownership.py:517-530): Suggest with empty `suggest_departments` lets the server pick the caller's first department as "from" and still lists it as target (400, audit from_office_code). Not closed; follow-up row added.
- Advisory (Recommended.tsx:150): inbox Suggest excludes only `current_owner_code`, not watcher departments (409 `target_owns`). Not closed; follow-up row added.

## Deviations
None beyond the design note's recorded ones. Browser checklist moved to post-merge row 53 (owner's decision).

## Follow-up rows
- 54 portal-suggest-from-department: both advisory findings above.
- 53 (existing): browser checklist.

## Load status (queue-status)
dossier pending 3114 / failed 296; order_pdf done 19456, pending 165743, failed 5; status_batch done 194; masters done 1.
