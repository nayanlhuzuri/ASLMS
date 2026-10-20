# Report: portal-ui-case-calendar (backlog row 103)

Date: 2026-10-20. Branch `feature/portal-ui-case-calendar`, squash-merged into `main` (commit 449f5e0), tag `feature/portal-ui-case-calendar-done`.

## What changed
Portal UI redesign round 3 of 5 (design `docs/design/portal-ui-redesign.md`, status approved). 58 files.
- Backend: `GET /me/calendar` (hearings of my cases, my action due dates, next dates to confirm); tests for 403 and merged cases.
- Frontend: the case page (summary header with next hearing, holder, stage, owner and one primary action; tabs Overview, Hearings, Orders, Documents, Notes, Timeline, More); Send file as a 3-step dialog and the other workflow dialogs on the Action dialog template; My calendar (month grid, legend filter, day agenda); Alerts as its own menu entry.
- No migration and no table change; `docs/schema/schema.md` has an as-built note.
- Documentation: decisions log entry, backlog row 103, current focus.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1692 passed, 2 skipped (20 min 16 s).
- `docker compose build`: succeeded.
- Portal smoke (`portal_smoke.py` after `docker compose up -d --wait --no-deps web`): passed.
- Design note status `approved`; decisions-log entry and backlog row present.
- `git status` clean on the branch.
- Gates ran on the branch before the merge. `main` had moved on (commit da1e068, rename of the application and the show-password button), so the squash merge conflicted in `docs/claude_ASLMS_design_decisions.md` (both sides appended an entry). Resolved by keeping both entries unchanged (20 insertions, no deletions). The merged frontend was built with `docker build ./frontend` (succeeded). The backend and frontend test suites were not re-run on the merged tree; main's changes were limited to names, e-mail footers and a password control.

## Push and CI
No remote (`git remote get-url origin` fails; `gh` is not installed). Not pushed. CI status unknown.

## Review findings
1. Advisory: Send file on the custody card (`CustodyDialogs.tsx:448`, `CustodyTab.tsx:84`) is still a primary button, so the Custody and stage tab shows two primary buttons. Not fixed in this cycle; follow-up below.
2. Advisory: the header's next-hearing fact (`CaseFrame.tsx:82`) shows `sr_no` and ignores `printed_sr`, so it can differ from My calendar (which shows the printed number). Not fixed in this cycle; follow-up below.

## Deviations
Merge conflict resolution as above. `aslms queue-status` did not return within the time limit, so the load status is not recorded.

## Follow-ups
Backlog row 108 added for the two advisory findings.
