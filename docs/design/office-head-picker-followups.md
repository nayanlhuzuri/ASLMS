# Design: Office head picker follow-ups (the four advisories of the row 176 review)

```
slug: office-head-picker-followups
status: approved
author: architect
date: 2026-10-27
approved_by: owner on 2026-10-27, as designed
```

## Context

Backlog row 185. The review of row 176 `office-head-picker` (report `docs/reports/2026-10-27-office-head-picker.md`,
merge 938d741) left four advisory findings open. None of them lets anyone do more than the server allows, because the
server checks every rule again. But each one shows the wrong thing on the screen or opens the wrong dialog:

1. **The kept New Office form wins over the address.** `NewOfficeForm` (`frontend/src/components/admin/Offices.tsx`)
   reads `aslms.officeDraft` from `sessionStorage` every time it opens, and `parent: kept?.parent || params.get("parent")`
   lets a stale draft beat an explicit `?parent=` (the "New Office" button on an office page). The draft is written when
   the person follows "Not in ASLMS Yet? Add a New User in Users". It is cleared only by Create Office or Cancel, so if
   they leave New User another way, the old code, name and kind come back the next time New Office opens anywhere in
   that tab.
2. **The ticket form is wider than the server about who sees the whole State.** `stateWideUsers` (`Tickets.tsx`) counts
   any State-office membership holding `users.view` as State-wide. The server's rule (`access.user_scope_roots`) is the
   Super Administrator or a holder of `cases.view_all`, and `GET /admin/users?include_ended=true` answers 403 `scope` to
   anyone else. So a State-office `users.view` holder without `cases.view_all` gets a User Picker that fails on every
   search. They also lose "Someone From Another Office", their only way to reach a login with no office.
3. **The User Picker shows "No person matches …" when the search failed.** `UserPicker.tsx` treats a failed query like
   an empty one (`people.isPending` is false, `shown` is empty, so the note is `noneNote`). The Office Picker
   (`OfficePicker.tsx`) has the same flaw: if `GET /admin/offices/choices` fails, it shows "No office matches".
4. **`?reactivate=1` opens Reactivate without checking anything.** `OfficeDetailView` starts with
   `reactivating = !!reopen`. The dialog then opens with the head section for an active office, a directorate, or a
   caller without `offices.manage`. It also stays armed: if the office is deactivated later on the same page, the dialog
   pops up by itself.

**What exists.**
- The draft helpers: `readDraft`, `writeDraft`, `clearOfficeDraft` and `addUserHref` in `Offices.tsx`.
- `NewUserForm` takes `returnTo` and goes back with `?head=<id>` (`returnWithHead`, guarded by `safeNext`).
- The kit's `Notice` and `ErrorBanner`, and the shared `T.retry` ("Try Again").
- The query client never retries a 4xx and retries other failures twice (`Providers.tsx`).
- `can(me, "cases.view_all")` is already the screen-side "whole State" test in the calendar, inbox and redirects.
- The server tests `test_include_ended_super_admin_sees_logins_without_membership` and
  `test_include_ended_department_admin_403` (`tests/db/test_api_users_list.py`).

**Not covered:**
- the Add Admin and Swap Admin dialogs on the picker (row 184);
- keeping the Reactivate dialog's half-chosen designation across the trip to New User (it was never kept, and nobody
  asked for it);
- the Users page's More Filters, which shows only to the Super Administrator. That is narrower than the server, never
  wider, so it causes no failure.

No business rule, API field, table or migration changes.

## Decisions

1. **The draft is restored only on the way back from New User, and is marked in the address.**
   - **The link** becomes `addUserHref("/admin/offices/new?draft=1")`. New User therefore comes back to
     `/admin/offices/new?draft=1&head=<id>` after creating someone.
   - **When the link is followed,** `keepDraft` writes the draft as today. It also replaces the current history entry
     with `/admin/offices/new?draft=1` (`window.history.replaceState`, which Next 16 keeps in step with
     `useSearchParams`), so the browser's Back button from New User also lands on the marked address and gets the form
     back.
   - **`NewOfficeForm` reads the draft only when the address has `draft=1`.** Without the marker, it clears any stored
     draft as it opens and starts from the address alone (`?parent=`).
   - **When the marker is present but no draft is stored** (another tab, or storage refused), the form starts empty, as
     today.
   - **Create Office and Cancel still clear the draft** (unchanged).
   Alternatives:
   - an expiry time on the draft. Rejected: it still shows a stale draft inside the window and hides a fresh one after
     it.
   - restoring whenever `head` is present. Rejected: it misses Back and Cancel from New User, where there is no `head`.

2. **The address wins over the draft.** `parent` is the only field the address can name. The link never adds `parent`,
   because the draft holds the parent chosen in the picker. If an address carries both `draft=1` and `parent`, the
   address's parent is used. So an explicit `?parent=` is never overridden by stored state, which is the advisory's
   rule.

3. **New User gets a way back when it was opened from an office form.** With `returnTo`, `NewUserForm` shows a secondary
   **Cancel** next to the primary. It goes to `safeNext(returnTo)` with no `head`. From New Office that is
   `/admin/offices/new?draft=1`, so the form comes back intact. From Reactivate it is `/admin/offices/<code>?reactivate=1`,
   so the dialog opens again (decision 7 checks it). Without `returnTo` the form is unchanged. Create stays the one
   primary. If the person leaves by any other path, the draft is discarded the next time New Office opens without the
   marker (decision 1), so nothing stale is ever shown.
   Alternative: clear the draft when New User unmounts. Rejected: a Back press also unmounts it, and that is exactly the
   case where the form should come back.

4. **One screen-side mirror of the server's "whole State" rule for users: `usersStateWide(me)` in `lib/can.ts`.**
   - **The rule:** `isSuperAdmin(me) || can(me, "cases.view_all")`, the same test as `access.user_scope_roots`. A doc
     comment names that function.
   - **Where it is used:** `Tickets.tsx` uses it in place of `stateWideUsers`, which is removed together with its State
     office and `users.view` test.
   - **The effect on the ticket form.** A State-office `users.view` holder without `cases.view_all`:
     - gets a picker that does not send `include_ended`, and lists the people their scope covers;
     - sees "Someone From Another Office", the exact-e-mail path through `GET /admin/users/lookup` (`users.create`), to
       reach a login with no office.
   - **It is display only;** the server still decides.
   Alternatives:
   - a new `/me` field saying whether the user list is State-wide. Rejected: an API change for a rule that is one line
     and already mirrored the same way on four screens.
   - keeping the State-office test and catching the 403. Rejected: the picker would fail first and then hide the
     option.

5. **The User Picker has an error state.** When the search fails (`people.isError`):
   - **The note in the list** says what went wrong instead of "No person matches":
     - for a 403: "You cannot search people from this form." (`T.userPicker.forbiddenNote`; a sentence, like the other
       notes). There is no Try Again, since asking again gives the same answer;
     - for anything else: "The search did not work." (`T.userPicker.errorNote`).
   - **Try Again.** For anything other than a 4xx, a secondary small button "Try Again" (`T.retry`) sits under the list,
     inside the popover and outside the `listbox`. Its mouse-down keeps focus in the box; it calls `people.refetch()`.
     Enter in the box does the same while the error note is shown and there is no option. Typing again starts a new
     search as usual.
   - **The screen reader** gets the error note through a visually hidden `role="status"` span in the picker, so it is
     announced. The note `li` stays `role="presentation"`.
   - **Order of the notes:** fewer than 2 characters → `minimumNote`; waiting or loading → `loadingNote`; error → the
     error note; no rows → `noneNote`; otherwise the options and, past 20, `firstNote`.
   - **The chosen value is kept** when a search fails.
   - The query client's retry rule is unchanged (no retry on 4xx, two on other failures before the error shows).
   Alternative: show the error under the box as a field error. Rejected: the field is not invalid, and the list is
   where the person is looking.

6. **The Office Picker gets the same error state.** If `GET /admin/offices/choices` fails, the list shows "The offices
   could not be loaded." (`T.officePicker.errorNote`) with the same Try Again (`choices.refetch()`) and status span, in
   place of "No office matches". The two kit pickers share their list styles, and the flaw is identical, so fixing one
   and not the other would leave the kit inconsistent.
   Alternative: a separate row. Rejected: it is a few lines in the same pattern, tested the same way.

7. **`?reactivate=1` opens the dialog only when Reactivate is really possible.**
   - **When it opens.** The dialog opens from the address only after the office and `/me` have loaded, and only when
     all of these hold (display only; the server checks again):
     - the office is inactive (`is_active === false`);
     - it is Department-tier (`isDept`: a Department-tier kind at the `department` tier);
     - the caller holds `offices.manage`;
     - the caller is the Super Administrator. Reactivating a Department-tier office is theirs alone: the server answers
       403 `super_admin_only` to anyone else (decision 7 of `office-head-picker`).
   - **When it does not open:**
     - the address is ignored;
     - if the office is already active, a `Notice` says "This office is already active, so there is nothing to
       reactivate." (`T.offices.alreadyActive`);
     - in the other cases nothing is shown.
   - **The state is derived, not armed.** `reactivating` starts false, and the address is consulted once, when the data
     is there. A later deactivation on the same page never opens the dialog by itself.
   - **The address is cleaned.** When the dialog closes (Reactivate done, or closed) or the address is refused, the page
     replaces the address with `/admin/offices/<code>` (`router.replace`, no scroll). A reload or Back then does not
     reopen it. The picked `?head=` person is already in the dialog's state by the time it can close.
   - **The Reactivate button** of a Department-tier office follows the same rule: `offices.manage` and the Super
     Administrator. A directorate or unit keeps today's direct Reactivate for any `offices.manage` holder.
   Alternative: keep opening it and let the server refuse. Rejected: it shows a head picker for an office that cannot
   take one, which is the finding.

8. **Wording.** New texts follow the Title Case rule for labels (none is a label except the existing "Try Again" and
   "Cancel"). The notes are sentences. The wording guards of both suites cover them.

9. **No audit change.** These are screen changes, plus one server test that pins the existing rule. Nothing new is
   written. Reactivation keeps its `office.reactivate`, `membership.added` and `ticket.approved` rows.

10. **No migration, no API change, no new endpoint, no new function.** `frontend/openapi.json` and `schema.d.ts` are not
    regenerated.

## Data

None. No table, column or `ref_*` code changes, and no migration.

## Services

No service change. The server rule the screen now mirrors stays in `access.user_scope_roots` (the Super Administrator
or `cases.view_all` → everyone; otherwise the subtrees of the memberships holding `users.view`), together with the 403
`scope` on `include_ended` and `no_office` in `api/routers/users.py::list_users`.

## API

No endpoint changes. The screens touched call these, unchanged:

| Method and path | Function | Use here |
|---|---|---|
| `GET /admin/users?q=&limit=20[&include_ended=true]` | `users.view` (`include_ended`: Super Administrator or `cases.view_all`, else 403 `scope`) | The User Picker. `include_ended` is sent only when `usersStateWide(me)` holds (decision 4). |
| `GET /admin/users/{id}` | `users.view`, in scope | The picked `?head=` person (unchanged). |
| `GET /admin/users/lookup?email=` | `users.create` | "Someone From Another Office" on the ticket form, shown when `usersStateWide(me)` is false. |
| `GET /admin/offices/choices` | as today (purpose-dependent) | The Office Picker; its error state (decision 6). |
| `GET /admin/offices/{code}` | as today | Whether the office is active and Department-tier (decision 7). |
| `POST /admin/offices/{code}/reactivate` | `offices.manage`; a Department-tier office: the Super Administrator only (403 `super_admin_only`) | Unchanged; the dialog opens only when this can succeed. |
| `POST /admin/tickets/head-change` | `users.propose_head` or `admin.tickets` | Unchanged. |

Visibility is unchanged: every list is still bounded by the caller's scope on the server.

**Portal files:**
- `components/admin/Offices.tsx`:
  - the draft marker and the address rule (decisions 1-2);
  - `keepDraft` replacing the history entry;
  - the derived Reactivate dialog with the address clean-up, and the Department-tier Reactivate button rule
    (decision 7).
- `components/admin/Users.tsx`: `NewUserForm`'s Cancel when `returnTo` is set (decision 3).
- `components/admin/Tickets.tsx`: `usersStateWide` in place of `stateWideUsers` (decision 4).
- `lib/can.ts`: `usersStateWide(me)`.
- `components/ui/UserPicker.tsx` and `components/ui/OfficePicker.tsx`: the error note, Try Again and the status span
  (decisions 5-6). Only styles shared with `officePicker.module.css` are used; no new CSS module.
- `lib/messages.ts`:
  - `T.userPicker.errorNote` and `forbiddenNote`;
  - `T.officePicker.errorNote`;
  - `T.offices.alreadyActive`.
- `frontend/e2e/uicheck.spec.ts`: one state (Tests).

## Jobs

None.

## Tests

**pytest** (`backend/tests/db/test_api_users_list.py`). These pin the server rule that the screen mirrors:
- `test_include_ended_state_office_reader_without_view_all_403`. A login whose only membership is at the State office,
  with `users.view` and without `cases.view_all`:
  - `GET /admin/users?include_ended=true` → 403 `scope`;
  - `no_office=true` → 403 `scope`;
  - the plain `q` search answers 200.
- `test_include_ended_view_all_holder_allowed` — the same login with `cases.view_all` lists a login that left its last
  office.

**vitest:**
- **`components/admin/officeHeadPicker.test.tsx`, the draft:**
  - `a stale draft never beats ?parent=` — with a stored draft, `/admin/offices/new?parent=EDU` shows parent `EDU`,
    empty code and name, and the draft is removed from `sessionStorage`;
  - `the link keeps the draft under ?draft=1` — the link's href is
    `/admin/users/new?no_office=1&return=%2Fadmin%2Foffices%2Fnew%3Fdraft%3D1`; clicking it writes the draft and
    replaces the history entry with `/admin/offices/new?draft=1`;
  - `back from New User restores the draft` — `?draft=1&head=u-9` restores the code, name and designation and picks the
    person (the existing test, re-addressed);
  - `Back or Cancel restores without a person` — `?draft=1` alone restores the fields with the picker empty;
  - `the address parent wins inside a draft` — `?draft=1&parent=EDU` with a draft parent `AGR` shows `EDU`;
  - Create Office and Cancel clear the draft (existing tests, kept).
- **`NewUserForm`:**
  - `Cancel goes back without a person` — with `returnTo`, Cancel goes to the return address with no `head`;
  - without `returnTo`, there is no Cancel.
- **`lib/can.test.ts` (or the admin test file), `usersStateWide`:**
  - the Super Administrator → true;
  - a holder of `cases.view_all` → true;
  - a State-office `users.view` holder without `cases.view_all` → false;
  - a department admin → false.
- **`NewTicketForm`.** For a State-office `users.view` holder without `cases.view_all`:
  - the picker's request has no `include_ended`;
  - "Someone From Another Office" is shown.
  For the Super Administrator, `include_ended=true` is sent and the link is hidden (existing behaviour kept).
- **`components/ui/userPicker.test.tsx`:**
  - `a failed search shows the error note, not "No person matches"` — a 500 shows "The search did not work." and Try
    Again;
  - Try Again refetches, and the options then show;
  - Enter with the error note refetches;
  - `a 403 shows the forbidden note and no Try Again`;
  - the error text is in the `role="status"` span;
  - a chosen value survives a failed search;
  - the order of notes (minimum, loading, error, none) holds.
- **`components/ui/officePicker.test.tsx`:** `a failed choices load shows the error note and Try Again`, not "No office
  matches".
- **`OfficeDetailView` (`officeHeadPicker.test.tsx`), the dialog from the address:**
  - `?reactivate=1` on an active office → no dialog, and the already-active notice shows;
  - on an inactive directorate → no dialog;
  - for a caller without `offices.manage` → no dialog;
  - for a department admin holding `offices.manage` → no dialog;
  - on an inactive Department-tier office as the Super Administrator → the dialog opens, and `?head=` picks the person;
  - closing the dialog calls `router.replace("/admin/offices/<code>")`;
  - a deactivation after a refused `?reactivate=1` never opens the dialog.

**uicheck** (`frontend/e2e/uicheck.spec.ts`, at 375, 768 and 1280 px): `/admin/offices/new (User Picker search failed)`.
The fixture answers the picker's search with a 500. There is no `doubled-heading` or `gutter` finding, the note and
Try Again fit the list width at 375 px, and there is one primary per page.

## Verification

1. `ruff check`, `pytest -q`, `npm run lint`, `npm run typecheck` and `npm test` are green.
2. `docker compose --profile uicheck run --rm uicheck` finds nothing on the new state.
3. `docker compose build`. There is no migration.
4. In the portal at `http://localhost:3000`, as the Super Administrator:
   1. **A stale draft does not come back.** Administration → Offices → New Office. Fill the code and name, choose Kind
      Department, then click "Not in ASLMS Yet? Add a New User in Users". Leave New User through the side menu. Open any
      department's page and click New Office: the parent is that department, and the code and name are empty.
   2. **Back keeps the form.** Repeat up to the link, then press the browser's Back: the code, name, kind and
      designation are back. Repeat, and click Cancel on New User: the same. Repeat, create a person with No Office Yet:
      the form is back with that person picked.
   3. **The picker's error state.** Stop the api (`docker compose stop api`). Type two letters in the User Picker: the
      list says "The search did not work." with Try Again, never "No person matches". Start the api with the court-data
      switch carried as usual, click Try Again, and the options show.
   4. **Reactivate from the address.** Open `/admin/offices/<an active department>?reactivate=1`: no dialog, and the
      notice "This office is already active…" shows. Open it on an active directorate: no dialog. Deactivate a test
      department, then open `/admin/offices/<code>?reactivate=1`: the dialog opens. Close it: the address loses
      `?reactivate=1`.
5. **As a department admin,** open `/admin/offices/<an inactive department>?reactivate=1` (if their scope lets them see
   it): no dialog. On New Head Change the picker searches only their department, and "Someone From Another Office" is
   shown.

## Open questions

None. The four findings are screen behaviour against rules that are already decided (row 176 decisions 3, 7 and 8, and
`access.user_scope_roots`); none needs a new business rule, API field or SourceTrace endpoint.
