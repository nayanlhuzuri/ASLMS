# Design: Portal case screens — follow-ups (department on every case-page action, document paging, inline viewing, the browser verification)

```
slug: portal-cases-followups
status: approved
author: architect
date: 2026-10-12
approved_by: owner (nayanlhuzuri) on 2026-10-12
```

> **Owner's decision at approval (12 Oct 2026), replacing decisions 10 and 11 where they differ:** the merge does **not** wait for the owner's browser checklist. The integrator merges after the automated gates (ruff, pytest, frontend checks, Compose build and `portal_smoke.py`). `INLINE_PDF` defaults to `true` (PDFs and images viewable inline; Word download-only). The signed-in browser checklist (steps 4-9, including whether the sandboxed PDF renders in Chrome and Firefox) is handed to the owner after merge as a follow-up; if either browser fails to render the sandboxed PDF, a follow-up sets `INLINE_PDF` to `false`. The API sandbox header is never relaxed. The live court search in the checklist runs only if the owner sets NAPIX_ENABLED for that run.

## Context
Backlog row 51, the follow-ups of row 12 `portal-cases` (design `docs/design/portal-cases.md`, report
`docs/reports/2026-10-12-portal-cases.md`). The plan sections are those of the parent note: §4.2 / Table 6
(recommend-and-claim: "in every case, the department decides by claiming it", suggest another department, primary
owner and watchers, transfers), §5.3 (case detail page), §5.4 (case inbox), §5.6 (orders and documents "can be viewed
and downloaded from the case page, subject to their visibility"). Nothing in this item changes a rule of the plan.

What the row holds, and where each item stands today (12 Oct 2026):
1. **Compose verification.** Done in the row-12 cycle after the registry came back: `docker compose build` (all
   images), `docker compose up -d --wait --no-deps web` healthy, `portal_smoke.py` passed (report, "Gates"). It is run
   again here only as this cycle's own gate (the API and web images change).
2. **Signed-in verification steps 3-9 of `portal-cases`.** Step 3's precondition is met: migrations through 0015 are
   applied to the dev database (CLAUDE.md, 12 Oct 2026), so starting `api` applies nothing. Steps 4-9 need a browser
   session, which needs the e-mailed sign-in code (otp-and-profile); no agent can read that mail or `.env`. They were
   never run (rows 12 and 50 both left them to the owner).
3. **Sandboxed inline PDF.** `portal-cases` decision 15: View opens the API's file through the relay with
   `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`; whether Chrome's and Firefox's own PDF
   viewers render under `sandbox` was to be recorded, with "View for PDFs falls back to download" if one refuses.
   Not yet recorded.
4. **The case page names no department for most actions.** `services/ownership.py` resolves the acting department
   with `acting_member` (primary membership if it qualifies, else the single qualifying one, else 400
   `office_required` with candidates). Deviation 10 of `portal-cases` added `office_code` to dismiss and allot and the
   inbox sends it; the case page does not:
   - Dismiss sends nothing; a login in two recommended departments whose primary membership is neither gets
     `office_required`, which the dialog shows as an error with no way to answer it.
   - Suggest and Request transfer list every active department, including the caller's own (the API refuses with
     400) and departments already holding the case (409 `target_owns`).
   - Allot and Take over act on the row the portal picks (`OwnershipCard`: the first of primary, watchers whose
     department is one of the login's), while the API picks its own: allot sends the portal's department (correct
     since deviation 10, but the button can show for a department whose membership lacks `cases.allot`), take over
     sends none and the API takes the first membership holding `cases.take_over` with an active row, so the dialog can
     name officer A of department X while the API takes over department Y's row (or answers `stale`).
   - Stop watching sends nothing; a login watching from two departments gets `office_required` that it cannot answer
     (the endpoint takes no department). Request transfer resolves by "any active row", so a login in the primary
     department and a watcher department whose primary membership is the watcher one gets `not_primary`.
   - Suggest from the inbox's Recommended tab sends no originating department: for a login in two departments both
     recommended, the API may mark the other department's recommendation as suggested elsewhere — the same defect
     deviation 10 closed for dismiss.
   - The super admin's Claim lists every active department (`claim_departments: null`), but once a case has been
     claimed only a department with an active recommendation that does not hold the case can claim; every other choice
     answers 404. Search results (deviation 5) do the same for the super admin.
5. **Documents tab** reads one page of 200 (`limit: 200`, the API's `MAX_LIMIT`) and says nothing when a case has
   more.
6. **Word note attachments** offer View (`Notes.tsx` shows View for every attachment; the Documents tab already
   hides it for Word).

Not covered: the mapping screens' follow-ups and their signed-in steps (row 52); custody screens (row 13); paging of
the rule lists (row 20); the relay's other two hardening items (row 44).

## Decisions
1. **The server names, per action, the departments the caller may act for.** `GET /cases/{ref}/ownership` `actions`
   gains department lists computed by running each action's own check with each of the caller's departments
   (`dismiss_departments`, `suggest_departments`, `allot_departments`, `take_over_departments`,
   `stop_watching_departments`) and `transfer_from` (the one department a transfer request would come from). The
   existing booleans stay; for dismiss, allot, take over and stop watching the boolean becomes exactly "the list is not
   empty", so a flag is never true only because `office_required` was raised with no way to answer it. Alternative:
   the portal computing departments from `/me` memberships and the ownership rows (the rule written twice, the
   drift that caused item 4). This extends `portal-cases` decision 8 (the case page offers what the server says).
2. **Every action that resolves the caller's department accepts it.** As deviation 10 did for dismiss and allot:
   `POST /cases/{ref}/suggest` gains `from_office_code`, `/take-over` and `/stop-watching` gain `office_code`. Each is
   optional and must name one of the caller's own departments (400 otherwise; the super admin gains no new power),
   whose membership holds the function (403) and which has the recommendation or row the action needs (404). Without
   it the API resolves the department as today. Claim (already has `office_code`), withdraw and decide (tied to the
   transfer's from / to office, never ambiguous) are unchanged. Alternative: portal-only exclusions (leaves the API
   choosing a different department than the screen shows, the blocking review finding of row 12).
3. **Request transfer resolves to the primary owner's department.** `_check_request_transfer` first looks for the
   caller's membership in the department holding the primary row; if there is one it acts for it (403 without
   `cases.transfer_request` there); otherwise the current resolution runs unchanged (a watcher-only caller still gets
   409 `not_primary`, an unrelated caller 404). Only one primary row exists, so no `office_code` is needed. Behaviour
   change for one case only: a login in both the primary and a watcher department no longer gets `not_primary` or
   an unanswerable `office_required`.
4. **One rule for the department choice in every dialog.** A shared `DepartmentChoice` field: one department in the
   list → shown as text ("For: FIN") and sent; several → a required select with no pre-selection (`portal-cases`
   decision 7: nothing is pre-selected that the user did not choose); an `office_required` answer with `candidates`
   (from any action) opens the same select instead of failing, as Claim does today. Applied on the case page to Claim,
   Dismiss, Suggest ("Suggest from", only when `suggest_departments` has more than one; empty → sent without, the
   central operator's case), Allot, Take over and Stop watching.
5. **Allot and Take over show the chosen department's row.** The dialog first fixes the department (decision 4), then
   shows that department's row from the ownership view: current unit and officer for Allot; the current officer for
   Take over, sent as `expected_officer_user_id` with `office_code`. The buttons show when the list is non-empty (the
   API's take-over check already requires an allotted officer). `myRow` in `OwnershipCard` is removed.
6. **Suggest and Request-transfer targets exclude what the API refuses.** Suggest's target list excludes the chosen
   "from" department and every department holding an active row (primary or watcher, from the ownership view:
   `target_owns`). Request transfer excludes `transfer_from`. The inbox's Recommended tab sends `from_office_code` =
   the selected department; the Pool tab sends none (a pool case has no active recommendation to suggest from; the
   central operator follows up without a department, `portal-cases` deviation 4).
7. **The super admin's Claim lists only departments that can claim.** `claim_departments` stays `null` ("any active
   department") only when the case is in the pool (never had a primary owner); otherwise it lists the departments
   with an active recommendation that do not hold the case (possibly empty, then `claim` is false). For non-super-admin
   logins it is unchanged. Search results' Claim no longer computes departments in the portal (deviation 5 of
   `portal-cases` is withdrawn): opening the dialog reads `GET /cases/{ref}/ownership` and uses its
   `claim_departments` (a 404 shows the API's message). Alternative: keeping `null` for the super admin (every wrong
   choice answers 404).
8. **Documents tab pages per group.** Three sections (Court orders, Court filings, Internal documents), each its own
   query `GET /cases/{ref}/documents?group=<g>&limit=50&offset=…` with the shared `Pagination` and the API's `total`;
   an empty group is not shown; "No documents" when all three totals are 0; "Show archived" applies to all three.
   Alternative: one list paged 50 with groups inside a page (a group splits across pages and a reader cannot tell how
   many internal documents exist). No API change: `group`, `limit`, `offset` exist.
9. **View only for types a browser shows itself.** One helper `canViewInline(mime)` in `src/lib/documents.ts`: true for
   `application/pdf` (subject to decision 10) and `image/*`, false for everything else (Word); an allowlist, so a
   future type is download-only until named. Used by Orders, Documents and Notes attachments
   (`NoteAttachmentOut.mime` already exists). The API's `inline` disposition and its headers are unchanged.
10. **The sandboxed-PDF result is recorded first and decides one constant.** The owner opens a stored order with View
    in Chrome and in Firefox on the running Compose `web` (the View link exists on main) and records, per browser and
    version, "renders" or what is seen (blank, blocked, download). `INLINE_PDF` in `src/lib/documents.ts` is `true` if
    both render; `false` if either does not, and then PDFs offer Download only (with the hint "Opens as a download")
    while images keep View. The API's `Content-Security-Policy: sandbox` is never relaxed (`portal-cases` decision 15;
    a relaxed policy would need the owner's separate decision). The developer asks for the result at the start of the
    build; the tests cover both values. No browser sniffing (a per-browser switch would hide the result behind the
    user agent string).
11. **The signed-in browser checklist is run by the owner and gates the row.** Running steps 4-9 of `portal-cases` is
    the purpose of this row, so the integrator merges only when the owner's results for the checklist in
    Verification are written into the cycle report (pass, or the observed failure, which becomes a fix in this cycle
    or a new row). The live court search (portal-cases step 9, second half) is run only if the owner sets
    `NAPIX_ENABLED` for that run himself; if the owner declines, the report says "not run, by the owner's choice" and
    the row may still close. Agents never set the switch or read the sign-in mail. **Owner to confirm at approval**
    (alternative: merge the code after the automated gates and leave the checklist outstanding, as rows 12 and 50
    did, which is how it stayed unrun).

No deviation from the plan. Two points for the owner at approval: the three API additions of decision 2 and the
resolution change of decision 3 (small, read-or-name only, same audit rows), and decision 11 (the owner runs the
browser checklist and the row waits for it).

## Data
No table, column, constraint, reference code or `Permission` is added; no migration. `docs/schema/schema.md` is
unchanged. The new `actions` fields are computed on read; the new request fields name a department that the
existing audit rows already record (`recommendation.suggest` `after.from_office_code`, `ownership.take_over` and
`ownership.unwatch` `office_code`). The portal stores nothing.

## Services
Backend (Python):
- `services/ownership.py`
  - `_check_suggest(session, actor_user, case, target, *, from_office_code=None)`: with `from_office_code`, the member
    is the caller's membership in that department (`_own_department` rule: 400 when not the caller's), which must
    hold `cases.suggest_elsewhere` (403) and have an active recommendation or row for the case (404 "no
    recommendation or ownership of <code> for this case"); without it, today's selection. `suggest(...,
    from_office_code=None)` passes it through; the audit row and event already carry `from_office_code`.
  - `_check_take_over(..., office_code=None)`: with `office_code` (`_own_department` rule), only that department's
    membership is considered (403 without `cases.take_over`, 404 when it is not eligible or the department has no
    active row); then today's `not_allotted` / `already_holder` / `stale` checks. `take_over(..., office_code=None)`.
  - `_check_stop_watching(..., office_code=None)`: passes `_own_department(...)` to `acting_member` as dismiss does.
    `stop_watching(..., office_code=None)`.
  - `_check_request_transfer`: decision 3 — the primary row's department is tried first through
    `access.member_in_department`; else the current `acting_member` call.
  - `available_actions`: adds `dismiss_departments`, `suggest_departments`, `allot_departments`,
    `take_over_departments`, `stop_watching_departments` (for each distinct department of the caller's memberships,
    in membership order, the department is listed when the check with that department passes; `OfficeRequired`
    cannot occur with a department named) and `transfer_from` (the department returned by
    `_check_request_transfer(..., None)` when it passes, else null). `dismiss`, `allot`, `take_over`,
    `stop_watching` = list non-empty. `suggest` unchanged (it may pass without a department). For the super admin,
    `claim_departments` per decision 7 through `_super_admin_claim_departments(session, actor_user, case) -> list[str]
    | None` (replacing `_super_admin_can_claim`; `claim` = `None` or non-empty list, and `cases.claim` held, case not
    merged). No lock, no write, no audit (reading).
- `api/routers/ownership.py`: passes the new body fields to the services.
- `api/schemas.py`: `OwnershipActionsOut` + `dismiss_departments: list[str]`, `suggest_departments: list[str]`,
  `allot_departments: list[str]`, `take_over_departments: list[str]`, `stop_watching_departments: list[str]`,
  `transfer_from: str | None`; `SuggestIn.from_office_code`, `TakeOverIn.office_code`, `StopWatchingIn.office_code`
  (each `str | None`, 1-40 characters, described as on `DismissIn`). `frontend/openapi.json` and `schema.d.ts`
  regenerated.

Frontend (`frontend/src`):
- `lib/documents.ts` (new): `INLINE_PDF` (decision 10), `canViewInline(mime)`; `isWord` in `Documents.tsx` removed.
- `components/inbox/dialogs.tsx`: `DepartmentChoice` and a `useOfficeRequired()` helper (reads `candidates` from an
  `office_required` `ApiError`); `DismissDialog`, `SuggestDialog`, `AllotDialog`, `TakeOverDialog`,
  `StopWatchingDialog` accept `departments?: string[]` (the case page) or a fixed `department` (the inbox) and send
  `office_code` / `from_office_code`; `SuggestDialog` and `TransferDialog` take an `exclude: string[]`; `AllotDialog`
  and `TakeOverDialog` take `rows: Ownership[]` and show the chosen department's row; `ClaimDialog` without
  `departments` and without `department` reads `useOwnership(caseRef)` for `claim_departments`. `DialogKind` updated.
- `components/case/OwnershipCard.tsx`: buttons from the flags and lists (decisions 1, 5, 6); `myRow` removed.
- `components/inbox/Recommended.tsx` (Suggest sends the selected department), `Pool.tsx` (sends none).
- `components/search/CaseResults.tsx`: Claim opens `ClaimDialog` without departments (decision 7).
- `components/case/Documents.tsx` (decision 8, `canViewInline`), `Notes.tsx` and `Orders.tsx` (`canViewInline`).
- `lib/messages.ts`: "For", "Suggest from", "Opens as a download", the paging and empty strings.
- `lib/api/types.ts` follows the regenerated schema.

Audit and events: no new kind. The portal writes none; every action is an existing audited API call
(`recommendation.dismiss`, `recommendation.suggest`, `ownership.allot`, `ownership.take_over`, `ownership.unwatch`,
`transfer.request`, `ownership.claim`). The audit row names the department that acted, now the one the user chose.

## API
| Method, path | Function required | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /cases/{ref}/ownership` (changed) | `cases.view_scope` (unchanged) | — | `actions` + `dismiss_departments`, `suggest_departments`, `allot_departments`, `take_over_departments`, `stop_watching_departments` (lists of department codes), `transfer_from` (code or null); `claim_departments` is `null` for the super admin only for a pool case | unchanged (404 when the caller may not see the ownership); computed for the caller only |
| `POST /cases/{ref}/suggest` (changed) | `cases.suggest_elsewhere` (unchanged) | + `from_office_code?` | unchanged | 400 not the caller's department; 403 function not held there; 404 no recommendation or row of that department |
| `POST /cases/{ref}/take-over` (changed) | `cases.take_over` (unchanged) | + `office_code?` | unchanged (`TakeOverOut`) | 400 / 403 / 404 as above; then `not_allotted`, `already_holder`, `stale` as today |
| `POST /cases/{ref}/stop-watching` (changed) | `cases.release` (unchanged) | + `office_code?` | unchanged | 400 / 403 / 404 as above; `primary_cannot_release` as today |
| `POST /cases/{ref}/transfers` (behaviour) | `cases.transfer_request` (unchanged) | unchanged | unchanged | acts for the primary owner's department when the caller has a membership there (decision 3) |

Used as they are: `GET /cases/{ref}/documents` (`documents.view`; `group`, `limit`, `offset`, `include_archived`),
`/documents/{doc}/file` and `/cases/{ref}/orders/{id}/file` (`inline`: `documents.view`; `attachment`:
`documents.download`), `/custody/recipients` (`cases.view_scope`), `POST /cases/{ref}/claim` (`cases.claim`),
`/dismiss` (`cases.dismiss`), `/allot` (`cases.allot`). Web server: no new route.

## Jobs
None.

## Tests
Backend (pytest, `backend/tests/db/`, the shared world and the `dual` fixture of `test_ownership_office_code.py`):
- `test_ownership_actions.py` (changed and added): `test_actions_match_outcomes` updated — for dismiss, allot, take
  over and stop watching the flag is true exactly when the action succeeds for some department (run in a rolled-back
  savepoint); `test_department_lists_match_outcomes` (for each world user and case state, every listed department
  succeeds with that `office_code` and every other own department is refused); `test_transfer_from_is_primary_department`;
  `test_super_admin_claim_departments_null_for_pool_case`; `test_super_admin_claim_departments_lists_recommended_not_holding`
  (a claimed case with one other department recommended → that one code; none → `claim` false);
  `test_actions_write_nothing` still green with the new fields.
- `test_ownership_office_code.py` (added): `test_suggest_from_named_department` (the named department's
  recommendation becomes `suggested_elsewhere`, the other's stays; audit `after.from_office_code`);
  `test_suggest_from_must_be_own_related_department` (400 / 403 / 404); `test_take_over_acts_for_named_department`
  (the named department's row changes, the other's does not); `test_take_over_office_code_refusals`;
  `test_stop_watching_two_watcher_rows` (without `office_code` → 400 `office_required` with both candidates; with it →
  only that row released, `ownership.unwatch` audited); `test_request_transfer_from_primary_and_watcher_member`
  (primary membership in the watcher department → the transfer is requested from the primary department);
  `test_api_suggest_takeover_stopwatching_take_office_code` (HTTP shapes and codes).
- `unit/test_openapi_snapshot.py` (existing) passes after `frontend/openapi.json` is regenerated.

Frontend (Vitest, the `fakeApi` helper):
- `lib/documents.test.ts` (new): `canViewInline` true for PDF and images, false for Word and an unknown type; false for
  PDF when `INLINE_PDF` is false (mocked module value).
- `components/case/case.test.tsx` (added): Dismiss with one `dismiss_departments` sends it without asking, with two
  asks (no pre-selection) and sends the chosen one; an `office_required` answer opens the choice; Suggest excludes the
  from department and departments holding rows, sends `from_office_code`; Request transfer excludes `transfer_from`;
  Allot with two `allot_departments` shows the chosen department's current unit and officer and sends its
  `office_code`; Take over sends `office_code` and that row's officer as `expected_officer_user_id`; Stop watching with
  two departments asks; super-admin Claim with a list offers only those codes, with `null` every active department;
  Documents tab issues three `group=` queries, a group with 51 items shows a pager and the next page asks `offset=50`,
  empty groups are hidden; a Word note attachment shows Download only, a PDF and an image show View; with
  `INLINE_PDF` false the Orders, Documents and Notes tabs offer no View for PDFs and show the hint.
- `components/inbox/inbox.test.tsx` (added): Recommended's Suggest sends `from_office_code` = the selected department;
  Pool's Suggest sends none.
- `components/search/search.test.tsx` (changed): Claim on a result reads `/cases/{ref}/ownership` and lists its
  `claim_departments`; a 404 there shows the API's message.

## Verification
Automated (developer, tester, integrator):
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`.
3. `docker compose build api web`; `docker compose up -d --wait --no-deps api web` (migrations through 0015 are already
   applied, so `init` applies nothing; check `docker compose logs init` shows no upgrade step); `python
   backend/tools/portal_smoke.py` passes; the `web` log has no error line.

Owner's browser checklist (decision 11; results written into the cycle report by the integrator). At
`http://localhost:3000`, signed in with the e-mailed code:
4. Super admin: `/search` without words shows a total equal to `GET /cases` `total` (the page's count); a CNR from the
   loaded January 2025 days typed in the header box opens its case page; Overview, Hearings, Orders, Parties, Linked
   cases, Timeline and Details load. On an order with `download_status = stored`: View in Chrome and in Firefox —
   record per browser and version whether the PDF renders (decision 10); in the browser's developer tools the
   response headers show `x-content-type-options: nosniff` and `content-security-policy: sandbox`; Download saves the
   file. Documents tab of a case with documents shows the groups and, past 50 in a group, the pager.
5. Department admin of a department with mapped codes (map one with the mapping screen of row 50 if none; `aslms
   rescore --all` or wait 15 minutes): the Recommended badge equals `recommended_high + recommended_medium` of
   `/inbox/counts`; claim one strong recommendation; `aslms audit search --action ownership.claim --limit 1` shows the
   row; the case's Ownership card shows the department as primary and no Claim button; the row is under Claimed →
   Active.
6. Allot that case to an officer from the Claimed tab; as a second officer of the department in a private window,
   take it over from the case page; the first window's take-over then shows `stale`. Audit shows `ownership.allot` and
   `ownership.take_over` with the department chosen.
7. Request a transfer to a second department with "stay as a watcher" (the target list does not offer the own
   department); as that department's admin, accept from Transfers → In; the first department's card shows it as a
   watcher with Stop watching and no button returns the case to the pool. Audit: `transfer.request`, `transfer.accept`.
8. Central operator, Unclaimed pool: suggest a department with a reason; that department's Recommended tab lists it
   with "Suggested by". Dismiss another recommendation from the case page; it moves to the pool's "dismissed by" list.
   If a login with memberships in two departments exists (or one is given a second membership through user
   administration), its case-page Dismiss asks which department and the audit row names the one chosen.
9. Court search: with `NAPIX_ENABLED=false` (the default) the court panel says court search is switched off (503
   `napix_off`) and `napix_call_log` gains no row (`aslms data-health` call count unchanged). The live court search
   (a CNR not yet held) only if the owner sets the switch for that run; the case opens and a second local search finds
   it without a call. Otherwise recorded as "not run, by the owner's choice".

Expected: every step passes; the report records the two browser results and the `INLINE_PDF` value they led to.

## Open questions
None.

## Deviations
Recorded by the developer during the build (12 Oct 2026); none changes a rule of the plan or an API field beyond
the design.
1. **`request_transfer` is exactly "`transfer_from` is set".** Decision 1 kept the boolean as it was (true on an
   `office_required` answer). After decision 3 an `office_required` from the fallback resolution can only come from a
   caller with no membership in the primary department, whose request always ends in `not_primary`; the flag would
   show a button the API always refuses. `test_actions_match_outcomes` checks the strict outcome.
2. **Super admin's claim list: active departments only.** `_super_admin_claim_departments` lists the recommended
   departments that do not hold the case and are active departments, because claim's own check refuses any other.
3. **Frontend helpers.** `useOfficeRequired(departments, fixed)` holds the whole department choice (the codes, the
   chosen one, `check()` and `onError()`), `officeRequiredCandidates(error)` reads the candidates, and
   `DepartmentChoice` renders it. `src/lib/documents.ts` also exports `pdfDownloadOnly(mime)` (the hint);
   `canViewInline` and `pdfDownloadOnly` take an optional `inlinePdf` argument defaulting to `INLINE_PDF`, so the
   unit tests cover both values directly; the component tests with `INLINE_PDF` false mock the module in their own
   file (`components/case/inlinePdf.test.tsx`).
4. **Suggest with one "from" department** shows it as text ("Suggest from: EDU", decision 4's one-department rule);
   the select appears only with more than one. The inbox's Recommended tab also leaves the case's current owner
   (`current_owner_code`) out of the targets (`target_owns`).
5. **Claim from search results.** While `GET /cases/{ref}/ownership` loads or after it fails, Claim is disabled; a 404
   shows the API's message; an empty `claim_departments` shows "None of the departments you may act for can claim
   this case now." and Claim stays disabled.
6. **Documents tab.** Each group shows its total ("51 in this group") above its table, and keeps the current page on
   screen while the next one loads; "Show archived" returns every group to its first page.
