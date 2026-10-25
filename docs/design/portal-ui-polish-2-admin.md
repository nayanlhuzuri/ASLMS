# Design: Portal UI polish 2, round 2 — Office Picker, Users toolbar, User Details modal, Department Mapping

```
slug: portal-ui-polish-2-admin
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25, as round 2 of docs/design/portal-ui-polish-2.md (approved with three rounds, decision 46)
```

This is a pointer note. The whole design is **[portal-ui-polish-2.md](portal-ui-polish-2.md)**, approved by the owner on
25 Oct 2026. This cycle (row 162, branch `feature/portal-ui-polish-2-admin`) builds **decisions 27-43** of that note, and only those, under
its rules (decision 47), tests and verification. Round 1 (row 153) is merged; its deviations are recorded in that note.

- Build from that note's decisions 27-43, its API, tests and Verification sections for these decisions.
- Record any deviation of this round in a "Deviations, round 2" section of **this** note.
- Strings follow the round 1 Title Case rule and the `labels.test.ts` guard.

## Deviations, round 2
Recorded by the developer while building round 2 (26 Oct 2026); none changes a rule, a function or what a caller may see.
1. **Address of the offices list.** The endpoint is `GET /admin/offices/choices`: the offices router carries the `/admin`
   prefix, and the note's `/offices` and `/offices/tree` name the existing `/admin/offices` routes. It is declared before
   `/admin/offices/{code}`.
2. **`include_inactive`.** It needs `offices.manage` for every purpose but `audit` (403 otherwise) and widens only
   `users`; the active-only purposes (`membership`, `office_parent`, the three mapping purposes) accept it and stay active
   only. `audit` always lists inactive offices and needs no `offices.manage`.
3. **Ancestors.** Each office's `ancestors` names every office above it, root first, also those outside the caller's
   subtree (one more query for the names of the path's codes), so a department's picker shows "Government of Assam ›
   Education" under a match.
4. **Include Sub-offices** is a checkbox under the picker's box (decision 28), not in the list's foot as in the mockup, so
   it is reached by Tab (Tab closes the list). The picker's input is itself the 36 px control, with the icon, the code tag,
   "+ sub", the clear button and the chevron drawn over it, so its box lines up with the other boxes of a field row. The
   kit's `OfficePicker` also takes `hideLabel`, `placeholder`, `hint`, `error`, `required` and `onChoose` (the whole
   office, read by the generic-code rule).
5. **Users toolbar.** Name or E-mail keeps the server's 2-character minimum (the note's "3-character hint" is that hint),
   shown as the field's tooltip. More Filters shows only to the Super Administrator, the only one with a field inside
   it. The list's filters (`q`, `role`, `office`, `subtree`, `status`, `include_ended`, `offset`) now live in the query
   string, so the list behind the User Details modal keeps them. The status "Off" reads "Sign-in Off" everywhere (the
   badge of decision 32), and the type filter's empty choice reads "All User Types".
6. **User Details.** A tab change replaces the address (`history.replaceState`), so Back still closes the modal; the
   "opened in the portal" mark is set through a module-level flag, because the route's page remounts on navigation.
   The earlier page's "Entries About This User" link is kept beside "Open in Audit Log" on the Activity tab. Edit Profile
   and Reset Password are confirm dialogs over the earlier fields; a login created from `?user=new` opens its modal by
   replacing the address, so Back returns to the list. The Functions tab lists what the membership holds and, struck
   through, what was taken from it. The kit gained `hideLabel` on fields, `onSelect` on `Tabs` and `danger` and
   `separator` on `Menu` items; `SaveBar` is exported from `UserTypes.tsx` for the Scoring tab.
7. **Change Office only on counsel codes.** The API takes an office change only on `PATCH /admin/counsel-codes/{id}`
   (`office_code`); keyword, name-pattern and watchlist rows offer Deactivate or Reactivate only. Adding office changes to
   those three would be an API change outside this round; a later row can add it.
8. **Search on the Keywords and Watchlist tabs** filters the list in the browser: `GET /admin/keywords`,
   `/admin/name-patterns` and `/admin/watchlist` have no `q` and answer their whole (unpaged) list. Search Codes sends the
   list's `q`, 300 ms after typing stops.
9. **Keywords and name patterns are one list** with a Kind column (Keyword, Exact, Starts With, Pattern), narrowed by the
   All / Keywords / Name Patterns choice.
10. **Watchlist.** The add row drops the Reason field, as the forms drop notes; existing reasons stay visible, read only,
    in the list. A watch's office stays optional (empty = the caller's department), with the existing hint.
11. **Recommended From Cause Lists** now loads with the Counsel Codes tab (always visible, decision 42); the earlier rule
    of reading it only when its panel was opened is dropped.
12. **Scoring.** The panel title is "Rules with Their Own Weight" ("with" is a joining word under the Title Case rule).
    The reason is asked in the confirm dialog that Save Changes opens. Save Changes in the save bar is the tab's one
    primary; without `admin.scoring` there is none.
13. **Reports, Holding Department.** The picker's options are the departments the page already loads for this field
    (`GET /custody/recipients`, every active department), not the catalogue's `departments`: a case may be with any
    department (portal-reports, decision 5; the server accepts any department), while the catalogue lists only the
    departments the reporter may scope a report to. No extra call is made.
14. **Audit Log.** The Unit select stays (shown when the chosen office is a department), and `office_subtree` is one of
    the screen's URL parameters.
15. **Messages and uicheck.** "Open Full Page" and the strings of the removed weight and notes fields are gone, with their
    two `SENTENCE_EXCEPTIONS`; "+ sub" is a new exception (a marker beside a code). The uicheck state
    "/admin/users?user=<id> (side panel)" is replaced by the five states of the Tests section; the old address redirects.
