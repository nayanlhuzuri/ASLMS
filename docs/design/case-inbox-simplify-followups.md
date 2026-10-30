# Design: Case Inbox follow-ups (the three advisories of the row 206 review)

```
slug: case-inbox-simplify-followups
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 208. The review of row 206 `case-inbox-simplify` (design `docs/design/case-inbox-simplify.md`, report
`docs/reports/2026-10-29-case-inbox-simplify.md`) left three advisory findings. None of them lets anyone see more than
the server allows: the server decides every list. Each one shows the wrong list or the wrong empty state.

1. **Clear All on the tracker's Department list loses the department.** A tracker without whole-department sight
   (decision 11 of row 206) sees `Held tab="pending"` under Department. Its list key is `held_owned`, and
   `LIST_FILTERS.held_owned.fixed` is `[]` (`frontend/src/lib/filters.ts:123`). Clear All (`clearAllUpdates`,
   `components/filters/NoCaseMatches.tsx:22-25`, used by the filter chips' Clear All, `FilterBar.tsx:195`, and by
   `NoCaseMatches`) therefore clears `department`. `DepartmentTab` (`components/inbox/InboxFrame.tsx:117-121`) then
   falls back to the first tracked department, so a tracker of two departments silently lands on the other one.
   Department Cases keeps `department` (`filters.ts:142-147`, `fixed: ["department"]`).
2. **The tracker's Overdue chip is not counted as a filter.** The chip writes `action=overdue`
   (`DepartmentCases.tsx:76-92`, rendered for the tracker at `InboxFrame.tsx:145`), which `Held` reads as `overdue`
   (`Held.tsx:112`). But the empty-state test (`Held.tsx:199`) passes only the own controls' keys, which for this list
   are `holder_department` (`Held.tsx:130-142`). With Overdue on and nothing found, the list says "No case of your
   department is waiting on someone." and offers no Clear All, though cases are waiting that are not overdue.
3. **Old My-Cases-bound addresses lose `action=overdue`.** `/inbox/claimed-by-me` and `/inbox/disposed` go to My Cases
   through `OLD_TAB_REDIRECTS` (`routes.ts:458-463`, the fixed-map line `routes.ts:514-515`), and `ClaimedRedirect`
   sends a non-whole reader to My Cases (`components/inbox/Redirects.tsx:52`, `:54`). My Cases sends no `action`
   (`MyCases.tsx:70-77`; row 206 decision 4: "Action Overdue leaves My Cases, because overdue work is With Me's"). So
   `/inbox/claimed-by-me?action=overdue` widens to every connected case. `/inbox/working` already sends the same query
   to With Me with `overdue=true` (`routes.ts:493-499`).

**What exists.** `clearAllUpdates`, `caseFiltersSet` and `NoCaseMatches` (`NoCaseMatches.tsx`); `oldInboxTarget`,
`without` and `redirectTarget` (`routes.ts:472-516`); the old six-tab `action=overdue` meant "an overdue action on
*my* file" (`services/my_cases.py:155-173`, `holder_user_id=user.id` at `:240`), which is exactly With Me's Overdue
Only (`/custody/held?scope=me&overdue=true`).

**Not covered.** Any other list's Clear All; a removable chip for the Quick Filters; Close Case (row 207); sorting
(row 179).

## Decisions
1. **`held_owned` keeps `department` across Clear All.** `filters.ts:123` becomes
   `held_owned: { fields: [...ALL_CASE, "owner"], fixed: ["department"] }`, with a comment naming this note. Both
   Clear All buttons (the chip row and the no-matches state) read `fixed`, so both keep it.
   - `held` (With Me) is unchanged: it carries no `department`.
   - Alternative: special-case Clear All in `InboxFrame`. Refused: `fixed` is the existing, single place for "kept by
     Clear All" (Department Cases, Sent's `earlier`).
2. **The tracker's Overdue counts as a filter.** `Held.tsx:199` becomes
   `caseFiltersSet(params, listKey, ownKeys) || (scope === "owned" && overdue)`, where `overdue` is the value already
   worked out at `Held.tsx:112` (`action=overdue`, or an old link's `overdue=true`). An empty result then shows
   `NoCaseMatches` ("No cases match these filters." and Clear All), and Clear All drops `action` and `overdue` and keeps
   `department` (decision 1).
   - Only `action === "overdue"` counts: `action=due_week` is not applied by this list (`Held.tsx:112`), so counting any
     `action` would show "no match" for a filter that was never sent.
   - With Me is unchanged: its Overdue Only is an own `check` control and is already counted.
   - Alternative: add `action` as an own control so a chip appears in the filter bar. Refused: the Quick Filters chip is
     the one control for it (row 206 deviation "The tracker's Department list"); a second control for one key is the
     clutter the owner removed.
3. **My-Cases-bound old addresses with an overdue filter land on With Me's overdue list.** A new exported helper in
   `routes.ts`, beside `oldInboxTarget`:
   ```ts
   /** A My-Cases-bound old address: With Me's overdue list for `overdue=true` or `action=overdue` (My Cases has no
    *  overdue filter, case-inbox-simplify decision 4), else My Cases; `overdue` and `action` are dropped either way. */
   export function myCasesTarget(params: Params): string
   ```
   - With an overdue filter: `"/inbox/with-me" + queryString({ ...without(params, ["overdue", "action"]), overdue: "true" })`.
   - Otherwise: `"/inbox/my-cases" + queryString(without(params, ["overdue", "action"]))`.
   - `oldInboxTarget` gains, after the `/inbox/working` branch: `/inbox/claimed-by-me` and `/inbox/disposed` return
     `myCasesTarget(params)`. The `/inbox/working` branch is unchanged (it also reads `held`).
   - `ClaimedRedirect` (`Redirects.tsx:52`, `:54`): the My Cases target becomes `myCasesTarget(params)`. The
     Department target is unchanged, because Department honours `action`.
   - `OLD_TAB_REDIRECTS` keeps its four entries (the documented map and the "every target is final" test); With Me is
     not a redirect source, so every target stays final.
   - Any other value (`action=due_week`) is dropped on the way to My Cases, as `/inbox/working` already does
     (`routes.test.ts:225`).
   - For `ClaimedRedirect` the old `/inbox/claimed?action=overdue` of a non-whole reader meant "overdue on any holder of
     my assigned cases"; With Me's overdue list is narrower but is the only overdue list that reader has, and My Cases
     would show every connected case. Alternative: leave this branch alone. Refused: the same widening the finding names.
4. **No new text, no wording change.** The no-matches sentence and Clear All exist (`T.list.noCaseMatches`,
   `T.filters.clearAll`). The wording guards are untouched.
5. **No plan deviation.** Visibility, recommend-and-claim, the functions and the audit rules are untouched; these are
   screen and address fixes inside row 206's approved decisions 4, 11 and 15.

## Data
None. No table, column, reference code or migration; `alembic heads` is unchanged.

## Services
None. No backend change.

## API
None. The screens call, unchanged: `GET /custody/held` (`scope=owned`: `custody.track`), `GET /inbox/claimed`
(`cases.view_scope`), `GET /inbox/mine` (`cases.view_scope`), `GET /inbox/counts` (`cases.view_scope`). Visibility stays
on the server. `frontend/openapi.json` is not regenerated.

**Portal files:** `lib/filters.ts` (decision 1), `components/files/Held.tsx` (decision 2), `lib/routes.ts` and
`components/inbox/Redirects.tsx` (decision 3).

## Jobs
None.

## Tests
Vitest only.
- **`components/ui/sort.test.tsx`** (beside the `clearAllUpdates` test at line 222): `clearAllUpdates({ department:
  "FIN", action: "overdue", q: "ram", offset: "50" }, "held_owned")` equals `{ action: undefined, q: undefined, offset:
  undefined }`.
- **`components/inbox/inbox.test.tsx`**, the Department tracker block (next to the test at line 583):
  - `Clear All on the tracker's list keeps the department`: `trackerOnly()` with `NOT_WHOLE`, params `{ department:
    "EDU", action: "overdue" }`, `/custody/held` answering no items → "No cases match these filters." is shown (not "No
    case of your department is waiting on someone."); clicking Clear All calls `nav.replace("/inbox/department?department=EDU")`.
  - `an old overdue=true on the tracker's list also counts`: params `{ department: "EDU", overdue: "true" }`, no items →
    the no-matches state.
  - `action=due_week is not a filter on the tracker's list`: params `{ department: "EDU", action: "due_week" }`, no
    items → the plain "No case of your department is waiting on someone.".
- **`components/files/cases-list.test.tsx`**: `Held tab="pending"` with `{ action: "overdue" }` and no items shows the
  no-matches state; With Me's empty state with no filter is unchanged.
- **`lib/routes.test.ts`**, added to the `oldInboxTarget` table (line 219):
  - `/inbox/claimed-by-me` `{ action: "overdue", q: "ram" }` → `/inbox/with-me?q=ram&overdue=true`;
  - `/inbox/disposed` `{ overdue: "true" }` → `/inbox/with-me?overdue=true`;
  - `/inbox/claimed-by-me` `{ action: "due_week", q: "x" }` → `/inbox/my-cases?q=x`;
  - the existing `/inbox/claimed-by-me` `{ q: "x" }` and `/inbox/disposed` `{ case_state: "disposed" }` rows unchanged.
  - `myCasesTarget` directly: `{}` → `/inbox/my-cases`; `{ action: "overdue" }` → `/inbox/with-me?overdue=true`.
  - "no redirect target is itself a redirect source" stays green.
- **`components/inbox/inbox.test.tsx`**, old addresses (line 620 table and the `ClaimedRedirect` tests):
  - `/inbox/claimed-by-me` `{ action: "overdue" }` lands on `/inbox/with-me?overdue=true`;
  - `ClaimedRedirect` for an officer with `{ action: "overdue" }` lands on `/inbox/with-me?overdue=true`;
  - `ClaimedRedirect` for a whole-department reader with `{ department: "EDU", action: "overdue" }` lands on
    `/inbox/department?department=EDU&action=overdue`.
- `lib/wording.test.ts` and `lib/labels.test.ts` stay green (no new text). `npm run typecheck`, `npm run lint` and
  `npm test` pass. No backend test changes; `ruff check` and `pytest -q` are unaffected.

## Verification
1. In `frontend/`: `npm run typecheck`, `npm run lint`, `npm test` green. No migration; `alembic heads` unchanged.
2. `uicheck` on a private network against temporary images (runbook section 16, never on the shared stack) exits 0 with
   no findings; no state's appearance changes.
3. Browser check at http://localhost:3000 (owner or tester, after any live demo):
   - As a login holding `custody.track` by override without `cases.claim` / `cases.allot` in two departments: open
     Department, choose the second department, turn on Overdue so nothing matches → "No cases match these filters." with
     Clear All; Clear All keeps the second department and shows its waiting cases.
   - `/inbox/claimed-by-me?action=overdue` and `/inbox/disposed?overdue=true` open With Me with Overdue Only ticked;
     `/inbox/claimed-by-me?q=ram` opens My Cases with "ram".
4. Scribe: one entry in `docs/claude_ASLMS_design_decisions.md`; row 208 in `docs/backlog.md`; CLAUDE.md's current focus.

## Open questions
None. The three findings are screen behaviour against row 206's approved decisions 4, 11 and 15; no business rule, API
field or SourceTrace endpoint is needed.
