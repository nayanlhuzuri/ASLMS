# Design: Choose the head of a department from current users

```
slug: office-head-picker
status: blocked
author: architect
date: 2026-10-26
approved_by: <owner e-mail or name> on YYYY-MM-DD
```

## Context

**The owner's request of 26 Oct 2026** (backlog row 176), on Administration → Offices → New Office → "Head of the
Department (Required for a Department)":

> "while creating a department instead of creating users from here i should have a dropdown of the current users
> because a single user might be head of multiple departments. so since there is already option to create users
> separately, just provide dropdowns here so that the head of the department just can be selected from the current
> available users."

The screenshot shows a `fieldset` with its legend on the border, an explanatory paragraph, E-mail, Full Name,
Temporary Password and Designation on one line, Mobile alone on a second line, and Create Office below. No mockup.

**What exists (checked 26 Oct 2026 on main at c9b9853):**
- `OfficeCreateIn.head` and `OfficeReactivateIn.head` are `HeadIn` (`backend/aslms/api/schemas.py`): `email`, and
  optional `full_name`, `designation`, `designation_id`, `mobile`, `password`. `services/offices.py::_set_head` needs an
  e-mail and calls `tickets.record_direct_set` → `memberships.apply_head_change(operation="set")` →
  `memberships._make_incoming(role=DEPT_HEAD)`. `_make_incoming` already takes an existing login **by id** (`user`), by
  e-mail, or makes a new login (e-mail, password, name). The result is an approved `head_change` ticket, audit
  `ticket.approved` (`direct: true`), `membership.added` and `office.create` / `office.reactivate` with `after.head`.
- The head is a **`dept_head`** membership, not the department admin: one active head per department
  (`ix_user_memberships_one_dept_head`), at the department office. The **department admin** (`dept_admin`) is a
  different membership with its own one-per-department index, named by Add Admin and the swap; picking a head never
  touches it. `check_type_limits` already refuses a second head (`one_dept_head`), a second membership in the same
  department (`one_per_department`) and any membership for the Super Administrator (`super_admin_single`).
  `_make_incoming` refuses a disabled login (`login_inactive`). So **one person heading several departments is already
  allowed** (design `user-memberships`, decisions 1-3 and 24): one login, one membership per department.
- Only the Super Administrator creates or reactivates a Department-tier office: `assert_can_manage_office` keeps
  everyone else to directorates and units inside their own subtree, and `record_direct_set` answers 403
  `super_admin_only`. The Super Administrator's `GET /admin/users` scope is everyone (`access.user_scope_roots` → None).
- The head-change request (`NewTicketForm` in `frontend/src/components/admin/Tickets.tsx`, `POST
  /admin/tickets/head-change`) names the incoming head by a typed exact e-mail. Its payload takes `membership_id` (a
  membership of the department) or `email` (a login with no membership there). A department admin's `users.view`
  covers only their own department, and `GET /admin/users/lookup` (exact e-mail, `users.create`) is the only way they
  reach a person from elsewhere ("No list of other departments' users").
- Designations are **one State-wide list** (`designations`, master; 18 seeded, Chief Secretary to Government Advocate,
  extended under Administration → Designations by `admin.designations`). A new department has the same list.
  `GET /admin/designations` (any signed-in user) lists the active ones. A membership keeps `designation` (the text shown)
  and `designation_id`; the service does not fill the text from the id.
- A login is always created **with a membership** (`POST /admin/users` needs `office_code` and a type; `dept_head` is
  refused there with `use_head_change`). A login may be left with no active membership after an exit (the Users
  toolbar's "Include Logins Without an Active Office").
- The kit's `OfficePicker` (`portal-ui-polish-2`, decisions 28-30) is the pattern for a picker: an ARIA combobox, one
  36 px control, options in a portal, highlighted matches, "No office matches".

**The gap this note cannot close alone (open question 1).** The owner's flow is: create the person in Users, then pick
them here. That works for anyone who already holds an office, such as a Secretary who heads another department. It does
not work for a person who is new to ASLMS and is to head only the department being created. Users cannot create a login
without an office, the right office does not exist yet, and decision 24 requires the head at creation. Placing the
person in some other office first would give them that office's sight. For example, a membership at the State office
would show them every case. The owner must choose how such a person is named. The recommended answer is written into
this note; decisions marked **(Q1)** change with the answer.

**Not covered.** The department admin's Add Admin and Swap dialogs, which name an admin and not a head. The picker fits
the swap's existing-login path (follow-up, decision 13). The Users "Add to Another Office" lookup also stays exact
e-mail (decision 13). No change to visibility, scoring or any NAPIX path.

## Decisions

1. **A user picker replaces the new-login fields; no login is created from the office forms.** The head is chosen from
   people who already have an ASLMS login. E-mail, Full Name, Temporary Password and Mobile leave the form.
   Alternative: keep the new-login fields beside a picker. Rejected: the owner asked for no user creation here.

2. **The picker is a kit component, `UserPicker`** (`frontend/src/components/ui/UserPicker.tsx`, exported from
   `@/components/ui`). It follows the `OfficePicker` closely: an ARIA combobox, one 36 px control with a person icon,
   a clear button and a chevron. The list opens in a portal under the box, or above it when there is no room, inside
   the nearest dialog. The keys are the same: Down, Up, Home, End, Enter, Escape keeps the value, Tab closes.
   - **Search:** the server's name or e-mail match, after 2 characters, with the 300 ms debounce of `list-search`.
     Up to 20 options, then "Showing the first 20 — type more to narrow". The empty states are "Type at least 2
     letters of a name or e-mail" and "No person matches …".
   - **Each option** shows three lines:
     - the full name, with the match highlighted;
     - the e-mail, greyed;
     - the person's current offices: each active membership as "<office code> · <designation> · <type label>",
       primary first, at most 3 and then "+ n more".
     A `Head` badge marks each `dept_head` membership, so the owner sees at a glance that someone already heads
     another department.
   - **Options that cannot be chosen** are shown greyed with the reason and are skipped by the keys. The reasons:
     "Sign-in Off — turn it on in Users"; "Super Administrator — holds no other office"; "Already in this department
     as <type>". The last applies only on the ticket form when that membership cannot become the head (decision 9).
     The server checks every rule again. Showing an option is convenience only.
   - **The chosen value** is shown as the name and e-mail in the box, with that person's offices on a line under it.
   - Props: `label`, `hint`, `required`, `value` (`UserChoice | null`), `onChange`, `blocked?(u) → reason | null`.
   - **Where else it fits:** the head-change request (decision 9, this row), and the Swap Admin dialog's
     existing-login path (follow-up). It does not fit the Users "Add to Another Office" lookup. There a department
     admin may reach a person outside their scope only by an exact e-mail, and a picker over their scope would never
     find that person.
   Alternative: a select of every user. Rejected: thousands of logins, and no search.

3. **No new endpoint: the picker reads `GET /admin/users?q=<text>&limit=20`** (`users.view`, unchanged). The rows
   are already `UserOut` with every membership (office code and name, designation, type). By default the list leaves
   out logins without an active membership. `X-Total-Count` drives the "first 20" line. The caller's scope is
   unchanged:
   - **Super Administrator:** everyone (the only person who creates or reactivates a department);
   - **department admin on the ticket form:** their own department only.
   So nobody gains a wider list than today's functions give. Disabled logins come back with `is_active = false` and
   are greyed (decision 2).
   Alternatives:
   - a `GET /admin/users/choices` modelled on office choices — rejected: the generic list already holds every field
     needed under the right guard, and a second scoped user list would be one more place to keep the scope rule in;
   - a new `status=on` value — rejected as unnecessary: off logins are few and are better shown greyed with the
     reason than hidden.

4. **The designation is a dropdown of the State-wide designations, required in the portal.** It is a `SelectField`
   labelled "Designation in This Department", fed by `GET /admin/designations`: the active designations in
   `sort_order`, with no free text. The form sends both `designation_id` and `designation` (the name).
   - **Why a dropdown:** heads hold Secretariat posts, and every one is in the seeded list (ACS, PS, Commissioner &
     Secretary, Secretary). The only person who uses this form, the Super Administrator, holds `admin.designations`
     and can add a missing post under Administration → Designations. A hint under the field says so.
   - **On the server the designation stays optional,** for the CLI and older records. When only `designation_id`
     arrives, `_set_head` fills `designation` from the designation's name, so the text shown is never empty for an
     id. An unknown id answers 400 `bad_field` (existing).
   - The `DesignationInput` combobox (free text with suggestions) stays where it is used today.
   Alternative: keep free text. Rejected: a head's designation is a post from the list, and a typed variant
   ("Secy.") would be carried into every actor snapshot of that membership.

5. **Mobile leaves the form.** It belongs to the login: `users.mobile` is entered at first sign-in, where the profile
   confirmation makes it mandatory, and changed in My Profile or Users. A membership has no mobile.

6. **`HeadIn` takes `user_id`, keeps `email` for the CLI and older clients, and retires the new-login fields.** The new
   shape is: `user_id: UUID | None`, `email: EmailStr | None`, `designation: str | None (≤ 200)` and
   `designation_id: UUID | None`, with `model_config = ConfigDict(extra="forbid")`.
   - **Exactly one of `user_id` or `email`;** otherwise 422.
   - **The retired fields** `full_name`, `password` and `mobile` answer 422 naming the field. An old client is
     refused loudly, rather than having its password silently ignored.
   - **`email` means an existing login only.** An unknown e-mail answers 400 `bad_field` "no login with this e-mail;
     add the person in Users first".
   - **The portal always sends `user_id`.**
   - **`services/offices.py::_set_head(head)` resolves the login** and passes `{"user": <id>, "designation",
     "designation_id"}` to `record_direct_set`. `_make_incoming` already handles a login given by id.
   Alternative: retire `email` too. Rejected: `aslms offices create --head-email` is how the operator names a head from
   the server, and an exact e-mail is unambiguous.

7. **The rules on the chosen person,** in `_set_head` before anything is written. Except for the new code
   `login_no_office`, these are the existing services and codes.
   - **Unknown id:** 400 `bad_field` "no such user".
   - **Disabled login:** 409 `login_inactive`.
   - **A login with no active membership** (it has left every office): 409 **`login_no_office`**, "this person holds
     no office now; add them to an office in Users first". The picker never offers such a login, because
     `GET /admin/users` leaves them out by default. This rule applies to the office forms and to the ticket's
     `email` path (decision 9). It does not apply to the ticket's `membership_id` path, where an ended membership of
     the department may be reactivated as head (`user-memberships`, decision 15). **(Q1)** If the owner chooses
     answer (A), a new login without an office must be accepted, and this rule is dropped.
   - **Super Administrator:** 409 `super_admin_single`.
   - **The department already has a head:** 409 `head_exists` / `one_dept_head`. This can only happen on
     reactivation, and only when a head membership is still active.
   - **One person, one membership per department:** 409 `one_per_department`. On creation the department is new, so
     this cannot happen. On reactivation it does not happen either, because deactivation needed no active members.
   - **The department admin:** picking a head never creates, changes or counts against the department's admin.
   - **The delegation rule:** creating or reactivating a Department-tier office stays the Super Administrator's alone
     (`assert_can_manage_office`, `record_direct_set`). The Super Administrator is not limited by `not_delegable`.
     Nothing in this row changes who may name a head.

8. **A person new to ASLMS: the department is created without a head and the head is named afterwards (Q1, the
   recommended answer (C)).**
   - **The tick:** on a Department-tier kind, the head section has a `CheckField` "Name the Head Later", off by
     default. Its hint reads: "For a person who is not in ASLMS yet. Create the department, add the person to it in
     Users, then name the head from the department's page."
   - **When ticked,** the picker and the designation are hidden and the body carries `head_later: true` and no
     `head`.
   - **The server's rule:** `OfficeCreateIn` and `OfficeReactivateIn` gain `head_later: bool = false`. A
     Department-tier office needs exactly one of `head` or `head_later`. Neither answers 400 `head_required`
     (unchanged). Both answer 400 `bad_field`. `head_later` on any other kind answers 400 `bad_field`.
   - **Audit:** `office.create` / `office.reactivate` record `after.head = null` and `after.head_later = true`.
   - **The department page,** while the department has no head, shows "No head yet" under Head with two secondary
     links for the Super Administrator:
     - "Add a User to This Department" → `/admin/users/new?office=<code>`; `NewUserForm` reads `office` to fill its
       Office Picker;
     - "Name the Head" → `/admin/tickets/new?department=<code>&operation=set`; `NewTicketForm` reads both.
     The Super Administrator's request is applied at once, as today.
   - **Visibility while headless:** the department shows in `departments_without_head`, so in data-health and
     `aslms offices list --missing-head`, as a department whose head was ended does today. Nothing is assigned
     automatically.
   - **Deviation:** this relaxes the owner's decision 24 of `user-memberships` (7 Oct 2026, "a department is created
     with its head") for the Super Administrator's explicit choice. It is flagged in open question 1.
   - **No "Add a New User in Users" link on the New Office form** under this answer: the new person's office is the
     department not yet created, so the link could only lead to a form that cannot be completed. The office form is
     not kept as a draft.
   Alternatives are in open question 1.

9. **The head-change request uses the same picker.** In `NewTicketForm`, for `set` and `replace`, the typed "E-mail of
   the Incoming Head" becomes:
   - **"Incoming Head":** a `UserPicker` over the caller's `GET /admin/users` scope (decision 3), with the
     Designation dropdown of decision 4. The body follows the picked person:
     - if they have an active membership in the chosen department, the body is
       `incoming = {membership_id, designation, designation_id}`;
     - otherwise the body is `incoming = {email: <the picked login's e-mail>, …}`. The e-mail is never typed, and the
       stored ticket payload is unchanged.
     `blocked` greys these options with their reason:
     - a membership in the department that is not at the department office ("Works in <office code>; a head sits at
       the department office");
     - a `dept_admin` membership, for a requester who is not the Super Administrator (the `not_delegable` rule);
     - the current head;
     - a disabled login.
   - **"Someone From Another Office":** a small text link that opens an exact-e-mail field checked with
     `GET /admin/users/lookup` (`users.create`, unchanged). It is shown only to a requester whose scope is not
     State-wide, so a department admin can still propose a person from elsewhere, as today. They still see no list
     of other departments' people.
   - **The server** keeps its checks (`HeadChange.check`). The only addition is the `login_no_office` refusal on the
     `email` path (decision 7).
   - The Department field becomes the `OfficePicker` (purpose `users`, Department-tier offices only), filled from
     `?department=` and fixed to the requester's own department for a department admin.
   Alternative: leave the ticket form typed. Rejected: the owner wants heads chosen from current users, and the
   ticket is the other place a head is named.

10. **Reactivation uses the same section.** The Reactivate dialog of a Department-tier office shows the same
    `HeadSection`: the picker, the designation and, under answer (C), "Name the Head Later". Its one primary is
    Reactivate.

11. **Layout: the head section is a heading and a field row, not a bordered fieldset.**
    - **Structure:** inside the New Office card, under the office fields, the section is an `h3` "Head of the
      Department", one muted line ("Choose a person who already has an ASLMS login. One person may head several
      departments."), then one `.row` with the User Picker (`flex: 2 1 320px`) and the Designation dropdown
      (`flex: 1 1 220px`), then the "Name the Head Later" tick on its own line. The tick sits outside the field row,
      so the checkbox rule does not apply.
    - **What goes:** the `fieldset` and `legend` and `admin.module.css .fieldset` (used only here) are removed.
    - **Labels** are in Title Case: "Head of the Department", "Person", "Designation in This Department", "Name the
      Head Later".
    - **One primary per page:** Create Office on the form, Reactivate in the dialog.
    - **Small screens:** at 375 px the row stacks, the picker's list takes the box width, and option lines wrap
      without overflow.
    - The section shows only for a Department-tier kind, as today (`DEPARTMENT_TIER`).

12. **Audit: no new action.** The existing rows are written as today:
    - `office.create` / `office.reactivate` with `after.head`: the ticket ref and the incoming membership's summary;
    - `membership.added` with `ticket_ref`;
    - `ticket.approved` with `direct: true`.
    The only change is `after.head_later` under answer (C). The picker's reads are not audited, like every list
    read.

13. **Follow-ups proposed at approval:** the Swap Admin dialog's existing-login path on `UserPicker`, and Add Admin
    for an existing login. Add Admin is new-login only today (`DepartmentAdminIn` requires a password), and the
    owner's reasoning applies to admins too. Both are one new row, not this one.

14. **No migration, no table, no column, no reference code.** `login_no_office` is an error code string, like the
    others.

## Data

No change. No table, column, index or `ref_*` row. The migration head stays where main has it. `schema.md` is
unchanged:
- the `user_memberships` paragraph already states one active head per department at the department office;
- `designations` is already the State-wide list.

## Services

- `services/offices.py`
  - `_set_head(session, actor, actor_user, office, head)`:
    - `head` is `{"user_id"} | {"email"}`, plus `designation` / `designation_id`;
    - it resolves the login, by id or by exact e-mail through `memberships.lookup`, and applies decision 7 in the
      order unknown → `login_inactive` → `login_no_office`;
    - it fills `designation` from `Designation.name` when only the id is given;
    - it calls `tickets.record_direct_set(..., {"user": str(user.id), "designation", "designation_id"})`.
    The new-login branch is no longer reachable from here. `_make_incoming` keeps it for the admin swap.
  - `create_office(..., head=None, head_later=False)` and `reactivate_office(..., head=None, head_later=False)`
    implement the exactly-one rule of decision 8 **(Q1)**. The audit `after` gains `head_later` when true.
  - New exception `LoginNoOffice(OfficeError)` with `code = "login_no_office"`, mapped to 409 in the routers'
    `_http`. Alternatively, `memberships.Conflict("login_no_office", …)` is raised where the ticket path needs it.
- `services/tickets.py::HeadChange.check`: on the `email` path, after `lookup`, a login with no active membership →
  `Conflict("login_no_office", …)`. Nothing else changes.
- `cli/offices.py::create`: `--head-email` (an existing login only) and `--head-designation` stay. `--head-name` and
  the password prompt go, with the message "add the person first with `aslms users create`". Under (C) there is a new
  `--head-later` flag. Exactly one of `--head-email` or `--head-later` is required for a Department-tier kind.

## API

| Method and path | Function | Change |
|---|---|---|
| `POST /admin/offices` | `offices.manage` (a Department-tier kind: the Super Administrator only, unchanged) | `head: HeadIn` as decision 6; **(Q1)** `head_later: bool = false`. 201 `OfficeDetailOut` (unchanged). Errors: 400 `head_required`, `bad_field`; 403 `super_admin_only`; 409 `login_inactive`, `login_no_office`, `super_admin_single`, `head_exists`; 422 for a retired field or neither/both of `user_id` and `email`. |
| `POST /admin/offices/{code}/reactivate` | `offices.manage` (a Department-tier office: the Super Administrator only, unchanged) | Same as above for `head` / `head_later`. |
| `GET /admin/users` | `users.view` | Unchanged. The picker calls it with `q` (2 or more characters) and `limit=20`. The caller's scope (`access.user_scope_roots`) applies. |
| `GET /admin/designations` | signed in | Unchanged. It feeds the designation dropdown. |
| `POST /admin/tickets/head-change` | `users.propose_head` or `admin.tickets` | Unchanged shape. Adds 409 `login_no_office` on the `incoming.email` path. |
| `GET /admin/users/lookup` | `users.create` | Unchanged ("Someone From Another Office"). |

`HeadIn` in `frontend/openapi.json` and `schema.d.ts` is regenerated. `UserChoice` in `lib/api/types.ts` is a
`Pick` of `UserOut` (`id`, `email`, `full_name`, `is_active`, `memberships`).

Portal:
- `components/admin/Offices.tsx`:
  - `HeadDraft` becomes `{ user: UserChoice | null; designationId: string; headLater: boolean }`;
  - `headBody` returns `{ user_id, designation_id, designation }`, or `null` with `head_later: true`;
  - `HeadFields` becomes `HeadSection` (decision 11), used by `NewOfficeForm` and the Reactivate dialog;
  - Create Office is disabled until a person and a designation are chosen, or the tick is on;
  - under (C), `DepartmentPeople` shows "No head yet" and the two links.
- `components/admin/Tickets.tsx` (decision 9) and `components/admin/Users.tsx`: `NewUserForm` reads `?office=`.
- `lib/messages.ts`:
  - `T.offices.headSection` becomes "Head of the Department";
  - `headIntro` is rewritten;
  - new `T.offices.headPerson`, `headDesignation`, `headDesignationHint`, `headLater`, `headLaterHint`, `noHead`,
    `addUserHere`, `nameHead`;
  - `T.userPicker.*` (placeholder, minimum, none, first 20, the reasons);
  - `T.tickets.incomingHead` and `otherOffice`.
  The Title Case guards of both suites cover the new labels.

## Jobs

None.

## Tests

pytest (`tests/db/test_offices.py`, `test_api_offices.py`, `test_head_change_tickets.py`):
- `test_create_department_with_picked_head` — `head.user_id` of a login holding an office elsewhere creates the
  department, a `dept_head` membership at it with the chosen designation (the text filled from `designation_id`), an
  approved direct `head_change` ticket, `membership.added` and `office.create` with `after.head`.
- `test_one_person_heads_two_departments` — the same login is picked for two new departments; it ends with two active
  `dept_head` memberships and its first membership still primary.
- `test_head_picked_by_email_still_works` — `head.email` of an existing login (the CLI path) gives the same result.
- `test_head_unknown_email_refused` — 400 `bad_field` with the "add the person in Users first" message. Nothing is
  written, and no office row exists.
- `test_head_new_login_fields_refused` — `password`, `full_name` or `mobile` in `head` → 422. Both `user_id` and
  `email`, or neither → 422.
- `test_head_inactive_login_refused` — 409 `login_inactive`, and the office is not created (the transaction is rolled
  back).
- `test_head_login_without_office_refused` — an exited login → 409 `login_no_office`, on creation, on reactivation and
  on the ticket's `email` path.
- `test_head_super_admin_refused` — 409 `super_admin_single`.
- `test_head_does_not_touch_department_admin` — a person who is `dept_admin` of department X is picked as head of a new
  department Y. X's admin membership is unchanged. Y has a head and no admin. Adding Y's admin afterwards still obeys
  `one_dept_admin`.
- `test_reactivate_with_picked_head` — reactivation with `head.user_id`. A second head on a department with an active
  head → 409 `head_exists`.
- `test_create_department_requires_function` — `POST /admin/offices` without `offices.manage` → 403. A department admin
  holding `offices.manage` asking for a Department-tier kind → 403. `GET /admin/users?q=` without `users.view` → 403.
- `test_picker_scope_of_department_admin` — `GET /admin/users?q=` for a department admin lists only their
  department's people (scope unchanged).
- **(Q1)** `test_create_department_head_later`:
  - `head_later: true` creates a headless department, audited with `after.head_later`, and it is counted by
    `departments_without_head`;
  - neither `head` nor `head_later` → 400 `head_required`; both → 400 `bad_field`;
  - `head_later` on a directorate → 400 `bad_field`.
- `test_cli_offices_create_existing_head_only` — `--head-email` of an unknown login exits non-zero with the "aslms
  users create" message. There is no password prompt.

vitest (`components/ui/userPicker.test.tsx`, `components/admin/admin.test.tsx`):
- The picker:
  - no request under 2 characters;
  - one debounced request with `q` and `limit=20`;
  - options show name, e-mail and offices, with a `Head` badge;
  - greyed options carry their reason and are skipped by the arrow keys;
  - Enter chooses, Escape keeps the value, the clear button empties it;
  - "Showing the first 20" when `X-Total-Count` is over 20;
  - "No person matches".
- `NewOfficeForm` with a Department-tier kind:
  - no password, full name, e-mail or mobile field;
  - the body's `head` is `{user_id, designation_id, designation}`;
  - Create Office is disabled until a person and a designation are chosen;
  - with "Name the Head Later" the body is `head_later: true` and has no `head`;
  - a directorate kind shows no head section.
- The Reactivate dialog sends the same `head` body.
- `NewTicketForm`:
  - a picked person with a membership in the department sends `membership_id`; one without sends `email`;
  - "Someone From Another Office" appears only for a scope that is not State-wide;
  - `?department=&operation=set` fill the form.
- `NewUserForm` fills its office from `?office=`.

uicheck (`frontend/e2e/uicheck.spec.ts`, at 375, 768 and 1280 px):
- `/admin/offices/new (Department, head section)` — kind set to Department; the field-row rule holds for the
  picker and the designation;
- `/admin/offices/new (User Picker open)` — the list showing options with offices and a greyed option;
- `/admin/offices/<code> (Reactivate dialog)` — an inactive department fixture;
- `/admin/tickets/new (Incoming Head)`.
There is no `doubled-heading` or `gutter` finding, and one primary per page.

## Verification

1. `pytest -q` and `ruff check` are green. `npm run lint`, `npm run typecheck` and `npm test` are green.
2. `docker compose --profile uicheck run --rm uicheck` finds nothing on the four new states.
3. In the portal, at `http://localhost:3000`, signed in as the Super Administrator:
   - Administration → Offices → New Office, Kind Department: the head section shows Person and Designation in This
     Department, with no password field.
   - Type two letters of an existing officer's name: the options show the officer's offices. Pick them, choose
     Secretary and create office `TESTA`. The department page shows them as Head.
   - Create `TESTB` with the same person as head. The person's User Details lists two `Head` memberships.
   - Under (C), create `TESTC` with "Name the Head Later". The department page shows "No head yet" and data-health
     counts one department without a head. Then "Add a User to This Department" adds a person, and "Name the Head"
     makes them head.
   - `GET /audit?office=TESTA` shows `office.create`, `membership.added` and `ticket.approved`.
   - The test offices are deactivated after the check. Their heads are ended first with the head-change `end`.
4. `aslms offices create --code TESTD --kind department --parent GOA --name "Test D" --head-email <existing login>`
   creates the department. With an unknown e-mail it refuses with the `aslms users create` message.

## Open questions

1. **How is the head named when the person is not in ASLMS yet?** Users can create a login only together with an
   office, the new department does not exist yet, and decision 24 (7 Oct 2026) requires the head when a department is
   created. Choose one:
   - **(C) recommended — "Name the Head Later".** The Super Administrator may tick it and create the department
     without a head. The person is then added to the department in Users, and named head from the department's page
     through the head-change request, which for the Super Administrator is applied at once. Headless departments
     already exist after an `end` and are counted on data-health. Nothing new in Users, no migration. Cost: two
     extra steps, and the department is headless for a short while. This relaxes decision 24 for the Super
     Administrator only (decision 8).
   - **(A) Logins without an office.** Users → New User gains "No Office Yet". The login has no membership until it
     is picked as a head here. The New Office form gets the link "Add a New User in Users", and the half-filled form
     is kept as a draft in the browser session. Decision 24 stays as it is, but Users, sign-in and the login-mirror
     columns must handle a brand-new login with no office. The `login_no_office` refusal (decision 7) is then
     dropped. This is larger: Users, `create_user` and the first sign-in.
   - **(F) A secondary "Not in ASLMS Yet" path in this form.** The current new-login fields stay behind a link under
     the picker. It is the smallest change and keeps decision 24, but it keeps the user creation the owner asked to
     remove.
