# Report: case-inbox-simplify (row 206), 29–30 Oct 2026

## What changed
- Backend (no migration, no table change; `docs/schema/schema.md` unchanged): `GET /inbox/mine?view=all` (every
  connected case, active first, then disposed) with `all` on `/inbox/mine/counts`; `still_out` and `earlier` on
  `GET /custody/sent`; active-first order with `case_state=all` and the due-date order with `action` on
  `/inbox/claimed`. Files: `services/my_cases.py`, `services/custody.py`, `services/inbox.py`, `api/schemas.py`,
  `api/routers/inbox.py`, `api/routers/workflow.py`; tests `test_my_cases.py`, `test_custody_sent_still_out.py`,
  `test_inbox_claimed.py`.
- Portal: the Case Inbox in four tabs, With Me (`/inbox/with-me`), My Cases (`/inbox/my-cases`), Sent by Me
  (`/inbox/sent`) and Department (`/inbox/department`); `WorkingOn.tsx` removed; 13 old addresses redirect in one
  hop through `OldInboxRedirect`, keeping the query; the kit `Menu` places its list in a portal, fixed from the
  button, flipping above when there is no room, so the case page's More menu and the row menus in scrolling boxes
  are no longer cut off; the tab bar's focus ring is drawn inside the tab; the kit Chip gains `hint`.
- Also: `frontend/openapi.json` and `schema.d.ts`, messages, routes, filters, uicheck spec, checks and fixtures,
  the design note's Deviations section, decisions log, process workflows, backlog, CLAUDE.md.
- Two older date-dependent tests made independent of the run date (commit 76d11eb, no application change):
  `test_field_rules[future]` worked out "tomorrow" at collection, so a run crossing midnight failed;
  `test_my_calendar_lists_department_cases` used the default month grid, which ends Sun 1 Nov 2026 and missed a
  hearing three days ahead.

## Gates
- First merge run (integrator): `pytest -q` 2 failed, 2967 passed, 3 skipped (47 min 18 s); both failures were the
  date-dependent tests above, so the merge stopped. Other gates passed: `ruff check` clean, `docker compose build`
  succeeded, the screen check on a private network against a `web` built from the branch gave 503 passed,
  7 skipped, 0 findings (157 routes and states, 368 screenshots), shared stack untouched; CI on `main` success
  (run 40902361160).
- After the test fix: `ruff check .` clean; `pytest -q`: 2969 passed, 3 skipped (47 min 19 s), every run green.
- Frontend (developer): lint, typecheck and Vitest pass (88 files, 1858 tests); `npm run build` passes.
- `git status` clean on the branch; design note status `approved`; decisions-log entry and backlog row present.

## Review findings and how they were closed
1. Advisory, Clear All on the tracker-only Department list also clears `department` (`filters.ts:123`): follow-up
   row 208 (1).
2. Advisory, the tracker list's Overdue chip is not treated as an active filter, so an empty result shows the
   plain empty state without Clear All (`Held.tsx:130-142`, `198-199`): follow-up row 208 (2).
3. Advisory, old My-Cases-bound addresses carrying `action=overdue` widen to every connected case
   (`routes.ts:494-503`, `MyCases.tsx:68-77`): follow-up row 208 (3).

## Deviations
Those listed in the design note's Deviations section (Chip `hint`, `earlier` kept by Clear All, the tracker list's
Overdue chip only, one `OldInboxRedirect`, Tab in an open menu returning focus to the button, a scroll closing the
menu only when it moves the button).

## Follow-up rows added
Row 208 `case-inbox-simplify-followups` (proposed).

## Load status
`aslms queue-status` after the merge (30 Oct 2026, 06:47 IST): causelist_day 410 done and 259 skipped, dossier 83,154 done and 70 skipped, order_pdf 177,056 done and 212,572 pending (excerpt; the historical load continues in the shared worker).
