# Design: User Picker, Enter retries only while Try Again is shown

```
slug: user-picker-enter-retry
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 186, the one advisory of the row 185 review (`docs/reports/2026-10-27-office-head-picker-followups.md`,
"Review findings"). Design `docs/design/office-head-picker-followups.md`, decision 5, says Enter repeats the search
"while the error note is shown and there is no option".

`frontend/src/components/ui/UserPicker.tsx:282` repeats it on a wider condition:
```ts
if (failed && canRetry) void people.refetch();
```
`failed` (`:302`) is `people.isError && !people.isFetching` for the *settled* query, so it stays true while the note is
not the error note:
- the person has typed more and the 300 ms debounce has not settled yet (`settled !== typed`, `:307`: the note is
  "Searching…");
- the person has deleted back below 2 letters (`:306`: the note is the minimum note) and the debounce still holds the
  old text.

In those windows Enter sends the failed search again. One wasted request; nothing wrong is shown or chosen (the
following `choose` is skipped, and `shown` is empty anyway). Try Again itself is already gated correctly
(`:357`, `errorNote && canRetry`).

The Office Picker was checked and needs no change: its Enter (`OfficePicker.tsx:263-264`) chooses an option first and
retries only when no option is shown and `canRetry`, which is exactly when its error note and Try Again show
(`:285-287`, `:317`).

**Not covered.** The query client's retry rule (unchanged); any other picker behaviour.

## Decisions
1. **One condition for Try Again and Enter.** After the notes are worked out (`UserPicker.tsx:304-312`), add
   `const retryShown = errorNote !== null && canRetry;`. Line 282 becomes
   `if (retryShown) void people.refetch(); else choose(active);` and line 357 becomes
   `{retryShown ? <PickerRetry … /> : null}`. The two can no longer drift apart. `failed` and `canRetry` stay as they
   are (`canRetry` still feeds `retryShown`).
   - `onKey` already reads `failed` and `canRetry`, declared later in the render body; `retryShown` follows the same
     pattern, so lint is unaffected.
   - Alternative: inline `errorNote && canRetry` at line 282 as the row words it. Equivalent; the named constant is
     preferred so the button and the key share one test.
2. **Outside the error note, Enter behaves as with any other note:** it calls `choose(active)`, which does nothing when
   no option is shown. A new search starts only from typing, as decision 5 of row 185 says.
3. **No text, style, API, data or audit change.** The doc comment at `UserPicker.tsx:16-18` gains "Enter only while Try
   Again is shown (design user-picker-enter-retry)".

## Data
None. No table, column, reference code or migration.

## Services
None.

## API
None. The picker still calls `GET /admin/users?q=&limit=20[&include_ended=true]` (`users.view`; `include_ended`: the
Super Administrator or `cases.view_all`). Visibility stays on the server.

## Jobs
None.

## Tests
Vitest, `frontend/src/components/ui/userPicker.test.tsx`, in the "a failed search" block (helper `failing`, line 174):
- `Enter while a new search waits does not repeat the failed one`: `failing(500)`; type "ra"; the error note shows;
  type "m" and press Enter at once (inside the 300 ms debounce). After the options show, the searches are exactly
  `["/admin/users?q=ra&limit=20", "/admin/users?q=ram&limit=20"]` (no second `q=ra`), and no person is chosen.
- `Enter below 2 letters does not repeat the failed search`: `failing(500)`; type "ra"; the error note shows;
  `{Backspace}` then Enter at once; wait past the debounce: one search only, and the minimum note shows.
- `Enter with the forbidden note asks nothing`: `failing(403)`; type "ra"; the forbidden note shows; Enter; wait past
  the debounce: one search only.
- Kept green: "Enter with the error note refetches" (line 210), "Try Again refetches, and the options then show"
  (line 198), "the order of the notes holds" (line 256), and the Office Picker tests unchanged.
- `npm run typecheck`, `npm run lint` and `npm test` pass. No backend change.

## Verification
1. In `frontend/`: `npm run typecheck`, `npm run lint`, `npm test` green. No migration.
2. `uicheck` on a private network against temporary images (runbook section 16, never on the shared stack) exits 0;
   the state `/admin/offices/new (User Picker search failed)` is unchanged.
3. No browser step is needed beyond the tests: the change removes a request and alters nothing on the screen.
4. Scribe: one entry in `docs/claude_ASLMS_design_decisions.md`; row 186 in `docs/backlog.md`.

## Open questions
None. The rule is row 185's approved decision 5; no business rule, API field or SourceTrace endpoint is involved.
