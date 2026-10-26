# Design: Choose the head of a department from current users, and logins with no office yet

```
slug: office-head-picker
status: awaiting-approval
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

**The owner's answer to the earlier open question** (26 Oct 2026). The question was how to name a head who is not in
ASLMS yet:

> "if there is a department, there will be a head so its always best to create the user first."

This is answer (A), **logins without an office**. Users can create a login that belongs to no office yet, and the New
Office form then picks it as head. The head stays **required** when a department is created or reactivated, as
decision 24 of `user-memberships` says. The "Name the Head Later" tick of the blocked revision is withdrawn, together
with its deviation. Every other decision of the blocked revision is kept. This revision adds the login with no office
(decisions 15-21) and retires `login_no_office` (decision 7).

**What exists (checked 26 Oct 2026 on main at b853a94):**
- **The head fields today.** `OfficeCreateIn.head` and `OfficeReactivateIn.head` are `HeadIn`
  (`backend/aslms/api/schemas.py`). It holds `email`, plus optional `full_name`, `designation`, `designation_id`,
  `mobile` and `password`.
- **How a head is applied.** `services/offices.py::_set_head` needs an e-mail. It calls `tickets.record_direct_set`,
  which calls `memberships.apply_head_change(operation="set")`, which calls
  `memberships._make_incoming(role=DEPT_HEAD)`. `_make_incoming` already takes an existing login by id (`user`) or by
  e-mail, or it makes a new login.
- **What it writes.** An approved `head_change` ticket, with audit `ticket.approved` (`direct: true`),
  `membership.added`, and `office.create` / `office.reactivate` with `after.head`.
- **The head is not the admin.** The head is a `dept_head` membership: at most one active per department
  (`ix_user_memberships_one_dept_head`), at the department office. The department admin (`dept_admin`) is a different
  membership with its own one-per-department index, and picking a head never touches it.
- **Limits already enforced.** `check_type_limits` refuses a second head (`one_dept_head`), a second membership in the
  same department (`one_per_department`) and any other membership for the Super Administrator
  (`super_admin_single`). `_make_incoming` refuses a disabled login (`login_inactive`).
- **One person may already head several departments:** one login, one membership per department (`user-memberships`
  decisions 1-3 and 24).
- **Only the Super Administrator creates or reactivates a Department-tier office.** `assert_can_manage_office` keeps
  everyone else to directorates and units inside their own subtree, and `record_direct_set` answers 403
  `super_admin_only`. The Super Administrator's `GET /admin/users` scope is everyone (`access.user_scope_roots`
  returns None).
- **The head-change request.** `NewTicketForm` (`frontend/src/components/admin/Tickets.tsx`, `POST
  /admin/tickets/head-change`) names the incoming head by a typed exact e-mail. Its payload takes `membership_id` (a
  membership of the department) or `email` (a login with no membership there).
- **A department admin's reach.** Their `users.view` covers only their own department. `GET /admin/users/lookup`
  (exact e-mail, `users.create`) is their only way to reach a person from elsewhere.
- **Designations are one State-wide list** (`designations`, master): 18 seeded, extended by `admin.designations`.
  `GET /admin/designations` (any signed-in user) lists the active ones. A membership keeps `designation` (the text
  shown) and `designation_id`; the service does not fill the text from the id.
- **A login is always created with a membership** today: `POST /admin/users` needs `office_code` and a type.
- **The mirror columns.** `users.office_id` and `users.role` are NOT NULL and mirror the primary membership. Only
  `memberships.write_mirror` writes them.
  - No authority check reads them: `access` computes functions, scope and `is_super_admin` from active memberships
    only.
  - They are read only for display: `auth.user_out`, `users._functions_out`, `users.user_summary` (audit) and
    `cli/cases.py`.
- **A login with no active membership exists today**, after its last exit (`user-memberships` decision 22): "the login
  stays active with no membership — it signs in, sees nothing and holds no function (`/me` shows an empty list) until a
  department admin adds a membership".
- **The portal already handles a login with no office:**
  - the shell's "No Active Office";
  - the Users list's `noMembership`;
  - `NoDashboard` for a login without case functions;
  - the Users filter "Include Logins Without an Active Office" (`include_ended`, State-wide scope only).
- **The kit's `OfficePicker`** (`portal-ui-polish-2`, decisions 28-30) is the pattern for a picker.

**Not covered.** The department admin's Add Admin and Swap dialogs, which name an admin, not a head (follow-up,
decision 13). No change to case visibility, scoring or any NAPIX path.

## Decisions

1. **A user picker replaces the new-login fields; no login is created from the office forms.** The head is chosen from
   people who already have an ASLMS login, including logins with no office yet (decision 15). E-mail, Full Name,
   Temporary Password and Mobile leave the form.
   Alternative: keep the new-login fields beside a picker. Rejected: the owner asked for no user creation here, and
   chose "create the user first".

2. **The picker is a kit component, `UserPicker`** (`frontend/src/components/ui/UserPicker.tsx`, exported from
   `@/components/ui`). It follows `OfficePicker`: an ARIA combobox, one 36 px control with a person icon, a clear button
   and a chevron. The list opens in a portal under the box (above it when there is no room), inside the nearest
   dialog. Keys: Down, Up, Home, End, Enter, Escape keeps the value, Tab closes.
   - **Search:** the server's name or e-mail match after 2 characters, with the 300 ms debounce of `list-search`.
     - Up to 20 options, then "Showing the first 20 — type more to narrow".
     - Empty states: "Type at least 2 letters of a name or e-mail" and "No person matches …".
   - **Each option shows:**
     - the full name, with the match highlighted;
     - the e-mail, greyed;
     - the person's offices, each active membership as "<office code> · <designation> · <type label>": primary first,
       at most 3, then "+ n more";
     - a `Head` badge on each `dept_head` membership;
     - for a login with no office, a badge in place of the offices: `No Office Yet` if it has never held an office
       (decision 15), `No Active Office` if it left its last office.
   - **Options that cannot be chosen** are greyed, carry their reason and are skipped by the keys:
     - "Sign-in Off — turn it on in Users";
     - "Super Administrator — holds no other office";
     - on the ticket form only, "Already in this department as <type>" (decision 9).
     The server checks every rule again; an option is convenience only.
   - **The chosen value** shows the name and e-mail in the box, with the offices line (or the `No Office Yet` badge)
     under it.
   - **Props:** `label`, `hint`, `required`, `value` (`UserChoice | null`), `onChange`, `blocked?(u) → reason | null`,
     `includeWithoutOffice?: boolean` (decision 3).
   - **Where else it fits:**
     - the head-change request (decision 9, in this row);
     - the Swap Admin dialog's existing-login path (follow-up).
     It does not fit the Users "Add to Another Office" lookup, where a department admin may reach a person outside
     their scope only by exact e-mail.
   Alternative: a select of every user. Rejected: thousands of logins, and no search.

3. **No new endpoint: the picker reads `GET /admin/users?q=<text>&limit=20`** (`users.view`, scope unchanged).
   - **The rows** are `UserOut` with every membership. `X-Total-Count` drives the "first 20" line.
   - **Logins with no office.** A State-wide caller's default list includes logins with no office yet (decision 17).
     With `includeWithoutOffice`, the picker also sends `include_ended=true`, which adds logins that left their last
     office. `include_ended` already works only for a State-wide scope.
   - **Scope by caller:**
     - the Super Administrator, the only person who creates or reactivates a department, sees everyone;
     - a department admin on the ticket form sees their own department's people, and the picker does not send
       `include_ended` for them.
   - **Disabled logins** are greyed (decision 2).
   - Nobody gains a wider list than today's functions give.
   Alternatives:
   - a `GET /admin/users/choices` endpoint. Rejected: one more place to keep the scope rule.
   - a `status=on` value. Rejected: off logins are better shown greyed with the reason.

4. **The designation is a dropdown of the State-wide designations, required in the portal.**
   - **The field:** a `SelectField` "Designation in This Department", fed by `GET /admin/designations` (active, in
     `sort_order`), with no free text. The form sends `designation_id` and `designation` (the name).
   - **Why a dropdown:** heads hold Secretariat posts that are in the seeded list (ACS, PS, Commissioner & Secretary,
     Secretary). The Super Administrator holds `admin.designations` and can add a missing post under Administration →
     Designations; a hint says so.
   - **On the server the designation stays optional,** for the CLI and older records. When only `designation_id`
     arrives, `_set_head` fills `designation` from the designation's name. An unknown id answers 400 `bad_field`
     (existing).
   Alternative: free text. Rejected: a typed variant ("Secy.") would be carried into every actor snapshot of the
   membership.

5. **Mobile leaves the form.** It belongs to the login:
   - it can be given when the login is created in Users;
   - the first sign-in's profile confirmation makes it mandatory;
   - the person changes it in My Profile, or an administrator in Users.
   A membership has no mobile.

6. **`HeadIn` takes `user_id`, keeps `email` for the CLI, and retires the new-login fields.**
   - **Shape:** `user_id: UUID | None`, `email: EmailStr | None`, `designation: str | None (≤ 200)`,
     `designation_id: UUID | None`, with `model_config = ConfigDict(extra="forbid")`.
   - **Exactly one of `user_id` or `email`,** otherwise 422.
   - **Retired fields:** `full_name`, `password` and `mobile` answer 422 naming the field.
   - **`email` means an existing login only,** including one with no office. An unknown e-mail answers 400
     `bad_field`: "no login with this e-mail; add the person in Users first".
   - **The portal always sends `user_id`.**
   - **On the server,** `_set_head` resolves the login and passes `{"user": <id>, "designation", "designation_id"}` to
     `record_direct_set`.
   Alternative: retire `email` too. Rejected: `aslms offices create --head-email` names a head from the server, and an
   exact e-mail is unambiguous.

7. **The rules on the chosen person,** checked in `_set_head` before anything is written. All are existing codes;
   none is new.
   - **Refusals:**
     - unknown id: 400 `bad_field` ("no such user");
     - disabled login: 409 `login_inactive`;
     - the Super Administrator: 409 `super_admin_single`;
     - the department already has a head: 409 `head_exists` / `one_dept_head`. This happens only on reactivation,
       while a head membership is still active;
     - one person, one membership per department: 409 `one_per_department`. This cannot happen on creation or
       reactivation, because deactivation needed no active members.
   - **`login_no_office` is retired.** The blocked revision proposed it; it was never built.
     - A login with no office yet, or with no active office after an exit, may be named head.
     - The head membership becomes its first or only membership, and its primary one (decision 18).
     - Reason: the owner's flow creates the person without an office first, and `user-memberships` decision 22 already
       expects a login with no membership to wait for one to be added.
   - **The department admin:** picking a head never creates, changes or counts against the department's admin.
   - **The delegation rule:** creating or reactivating a Department-tier office stays the Super Administrator's alone.
     Nothing in this row changes who may name a head.

8. **The head stays required.** A Department-tier office is created or reactivated only with `head` (400
   `head_required`, unchanged; decision 24 of `user-memberships`). There is no "Name the Head Later" and no
   `head_later` field.
   - **The link.** A plain link "Not in ASLMS Yet? Add a New User in Users" sits under the picker. It opens
     `/admin/users/new?no_office=1&return=/admin/offices/new`.
   - **The half-filled office form is kept.** Before leaving, it is saved in `sessionStorage` (`aslms.officeDraft`:
     code, name, kind, parent, valid from, notes, designation). It holds no secret, since no password field remains. It
     is restored when the form opens again and cleared on Create Office or Cancel.
   - **Coming back.** After creation, `NewUserForm` goes to `return` with `?head=<new user id>`. The office form fetches
     `GET /admin/users/{id}` and puts that person in the picker.
   - **The Reactivate dialog** has the same link, with `return=/admin/offices/<code>?reactivate=1`; the page then
     opens the dialog again.

9. **The head-change request uses the same picker.** In `NewTicketForm`, for `set` and `replace`, the typed "E-mail of
   the Incoming Head" becomes "Incoming Head": a `UserPicker` over the caller's scope, with the Designation dropdown of
   decision 4. `includeWithoutOffice` is on for a State-wide requester.
   - **The body follows the person picked:**
     - with an active membership in the chosen department: `incoming = {membership_id, designation, designation_id}`;
     - otherwise: `incoming = {email: <the picked login's e-mail>, …}`. The e-mail is never typed, and the stored
       ticket payload is unchanged.
   - **`blocked` greys these options:**
     - a membership in the department that is not at the department office ("Works in <office code>; a head sits at
       the department office");
     - a `dept_admin` membership, for a requester who is not the Super Administrator (`not_delegable`);
     - the current head;
     - a disabled login.
   - **"Someone From Another Office":** a small text link that opens an exact-e-mail field checked with
     `GET /admin/users/lookup`. It is shown only to a requester whose scope is not State-wide, so a department admin can
     still propose a person from elsewhere, including a login with no office, as today.
   - **The server keeps `HeadChange.check` unchanged.** The `login_no_office` addition of the blocked revision is
     dropped (decision 7).
   - **The Department field** becomes the `OfficePicker` (purpose `users`, Department-tier offices only). It is filled
     from `?department=`, and fixed to the requester's own department for a department admin.

10. **Reactivation uses the same section.** The Reactivate dialog of a Department-tier office shows the same
    `HeadSection` (picker, designation, the link of decision 8). Its one primary is Reactivate.

11. **Layout: the head section is a heading and a field row, not a bordered fieldset.**
    - **Structure:** inside the New Office card, under the office fields:
      - an `h3` "Head of the Department";
      - one muted line, "Choose a person who already has an ASLMS login. One person may head several departments.";
      - one `.row` with the User Picker (`flex: 2 1 320px`) and the Designation dropdown (`flex: 1 1 220px`);
      - the link of decision 8 on its own line.
    - **Removed:** the `fieldset` and `legend`, and `admin.module.css .fieldset` (used only here).
    - **Labels in Title Case:** "Head of the Department", "Person", "Designation in This Department".
    - **One primary per page:** Create Office on the form, Reactivate in the dialog.
    - **At 375 px** the row stacks, the picker's list takes the box width, and option lines wrap without overflow.
    - **When it shows:** only for a Department-tier kind (`DEPARTMENT_TIER`).

12. **Audit: no new action.**
    - Naming a head writes, as today: `office.create` / `office.reactivate` with `after.head`, `membership.added` with
      `ticket_ref`, and `ticket.approved` with `direct: true`.
    - Creating a login with no office writes the existing `user.create` (decision 20).
    - The picker's reads are not audited.

13. **Follow-up proposed at approval:** the Swap Admin and Add Admin dialogs on `UserPicker` (Add Admin is new-login
    only today). One new row.

14. **One migration** (decision 16). It changes no other table and adds no reference code.

15. **Users can create a login with no office; only the Super Administrator can.**
    - **The tick.** In Users → New User, after the e-mail check finds no login, the Super Administrator sees a
      `CheckField` "No Office Yet" on its own line above the office fields. Its hint: "For a person who will be named
      head of a department being created. They can sign in, but see nothing until they have an office."
    - **When ticked,** the Office, Designation in This Office and User Type fields and the extra functions are hidden.
      The body sends `office_code: null` and `role: null`.
    - **`?no_office=1`** (decision 8) starts the tick on.
    - **A department admin may not create such a login** (403 `super_admin_only`), and the tick is not shown to them.
      Reasons:
      - such a login sits outside every department's scope, so the admin could not see it again in Users;
      - a department admin always has an office of their own to place a new person in;
      - heads of new departments are named only by the Super Administrator.
    Alternatives:
    - also any State-wide `users.create` holder. Rejected: no other type creates departments, so it would only make
      logins nobody can place.
    - a placeholder office (the State office). Rejected: a State-tier membership would let the person see every case.

16. **A login with no office has no mirror values, which needs a migration** (the next free number; 0029 if row 157's
    0028 merges first).
    - **The columns.** `users.office_id` and `users.role` become nullable. A new CHECK `ck_users_placed`
      ((office_id IS NULL) = (role IS NULL)) keeps the pair together.
    - **What NULL means:** "has never held an office". The first membership becomes primary and writes the mirror
      (`insert_membership` → `write_mirror`, unchanged). After a later exit the mirror keeps its last values (decision
      22). So the pair goes from NULL to set once and never back.
    - **API.** `UserOut.office`, `UserOut.role` and `UserFunctionsOut.role` become nullable, null only for a login with
      no office yet. The portal already reads offices from `memberships`; the one fallback, `u.office?.name` in
      `Users.tsx`, is already optional-chained.
    - **The display readers handle NULL:**
      - `auth.user_out`: no office lookup when NULL;
      - `users._functions_out`;
      - `users.user_summary`: `"role": null, "office_id": null`;
      - `cli/cases.py`: "no office".
    - **Downgrade** refuses while any `users` row has a NULL `office_id`, naming the count. No value is invented.
    Alternatives:
    - keep NOT NULL with placeholder values (State office, some type). Rejected: it would record a type and an office
      the person never had, and every display and audit summary would show them.
    - a separate "pending logins" table. Rejected: the person must be able to sign in and confirm the profile as a
      login.

17. **How it shows in Users.**
    - **Default list.** For a State-wide caller with no `office` or `role` filter, the default list also lists logins
      with no office yet, so they do not vanish right after creation. Exited logins stay behind "Include Logins Without
      an Active Office", as today.
    - **A new filter** in More Filters: a `CheckField` "No Office Yet" (`no_office=true`). It lists only logins with
      `users.office_id IS NULL`.
      - With `office` or `role`: 400 `bad_field`.
      - From a scope that is not State-wide: 403 `scope`, as `include_ended` does.
      - `X-Total-Count` counts the same filter.
    - **The row** shows a `No Office Yet` badge in the Offices column (`office === null`), in place of today's muted "No
      Active Office". That text stays for exited logins.
    - **User Details** shows "No Office Yet" as the header's post line. The Offices tab shows an empty state, "No Office
      Yet. Add an office here, or name this person head when you create their department.", with the existing Add
      Office button (`users.create`).
    - **A caller whose scope is not State-wide** never lists such a login, since it has no membership in their scope.
      `GET /admin/users/{id}` answers 404 to them, as for any login outside their scope.

18. **How it gets its first office.** Every path below goes through `memberships.insert_membership`, and the first
    membership is primary and fills the mirror.
    - **Named head** of a department being created or reactivated (decisions 6-8), or through the Super
      Administrator's head-change request. Its first membership is then the `dept_head` one.
    - **Add Office** on User Details (`POST /admin/users/{id}/memberships`, `users.create`: an office in the caller's
      membership's subtree, a delegable type; existing rules). The Super Administrator may add any office.
    - **A department admin** may add it to one of their offices through New User's exact-e-mail check ("Add a
      Membership to This Person"), as for an exited login today. That endpoint checks the target office, not the
      login's scope. The person is then in the admin's scope.

19. **Before it has an office, it signs in, changes its password, confirms its profile, and sees nothing.**
    - **Sign-in works as for a login after its last exit** (decision 22 of `user-memberships`):
      - the e-mailed code at sign-in;
      - the first-sign-in password change (`must_change_password` is set at creation);
      - the profile confirmation with the mandatory mobile.
      Then `/me` shows `memberships: []` and `functions: []`.
    - **It never sees a case.** Every case, inbox, cause-list, alert, calendar, dashboard, report, search, document,
      note, assistant and audit endpoint requires a function. Functions come only from active memberships
      (`access.members`, `access.has`, `visibility`). A function-less login gets 403, or an empty list from the
      endpoints that answer only for one's own work (`/inbox/mine`, `/inbox/mine/counts`, `/me/calendar`).
    - **No notifications.** Recipients are resolved from memberships, so nothing is addressed to it, and the digest
      skips an empty one.
    - **In the portal,** `NoDashboard` shows a card: "No Office Yet: your login is ready. You will see cases once you
      are added to an office or named head of a department.", with a My Profile link. The menu shows only what its
      functions allow: the Dashboard and My Profile.
    - **Why sign-in is allowed:**
      - the person sets their own password and mobile before being named head, so they can work on day one;
      - the state already exists and is tested for exited logins;
      - refusing sign-in would add a second, different rule for the same state.
    Alternative: refuse sign-in until it has an office. Rejected for those reasons.

20. **Audit rows for the login with no office:**
    - **creation:** the existing `user.create`, with `after` = `user_summary` (`role: null`, `office_id: null`) plus
      `no_office: true`; event `user_created` with `role: null, office: null`;
    - **its first office:** the existing `membership.added`, plus the ticket rows when it is named head;
    - **sign-in and profile:** the existing `auth.*` and profile rows. The actor snapshot has `office_code` null, as
      `access.actor_for` already allows.
    No new action name.

21. **CLI.**
    - **`aslms users create --no-office`** creates such a login. `--type` and `--office` become optional; exactly one
      form is required (both of them, or `--no-office`).
    - **`aslms offices create`:**
      - `--head-email` names an existing login, including one with no office;
      - `--head-designation` stays;
      - `--head-name` and the password prompt go;
      - an unknown e-mail exits non-zero with "add the person first with `aslms users create --no-office`";
      - a Department-tier kind still needs `--head-email`.

## Data

**`users`: two columns become nullable, by a migration** (the next free number at build; 0029 if row 157's 0028
merges first). The paragraph for `docs/schema/schema.md` replaces the `users` row:

| `users` (master) | email (unique), mobile, password_hash (argon2), full_name, designation (text as shown), designation_id (→ designations), office_id (→ offices RESTRICT, **NULL only for a login that has never held an office**), role (→ `ref_role`, **NULL with office_id**), is_active, last_login_at, must_confirm_profile, password_changed_at, must_change_password, profile_confirmed_at, created_by, updated_by | **A login** (user-memberships, migration 0008). `office_id`, `role`, `designation`, `designation_id` mirror the primary membership (written only by the membership service, never read for authorisation; kept at the last values when the login has no active membership after an exit). Added by `office-head-picker` (migration 0029 or the next free number): a login created by the Super Administrator with **no office yet** has `office_id` and `role` NULL until its first membership, which becomes primary and writes the mirror; CHECK `ck_users_placed` ((office_id IS NULL) = (role IS NULL)). Such a login signs in, changes its password and confirms its profile, but holds no function and sees nothing. Authority lives in `user_memberships`. *(The rest of today's paragraph, from "`super_admin` (added 1 Oct 2026)" on, is kept as it is.)* |

- **Unchanged:** the table class (master), the keys, the FK behaviour (`office_id` → offices RESTRICT) and the audit
  columns.
- **The migration** changes no data.
  - Upgrade: `ALTER COLUMN office_id DROP NOT NULL`, `ALTER COLUMN role DROP NOT NULL`, `ADD CONSTRAINT
    ck_users_placed CHECK ((office_id IS NULL) = (role IS NULL))`.
  - Downgrade: refuse with the count while any `office_id IS NULL`; otherwise drop the CHECK and restore NOT NULL.
- **ORM:** `User.office_id = uuid_fk("offices.id", nullable=True)`, `User.role = ref_code(Role, "ref_role",
  nullable=True)`, and the CHECK in `__table_args__`.
- **`user_memberships` paragraph:** "A login may have no active membership after an exit" gains "or before its first
  office (office-head-picker)".
- No `ref_*` row. Applied migrations are not edited.

## Services

- **`services/users.py`**
  - `create_user(..., role: Role | None, office: Office | None, ...)`. When both are None it inserts the login with
    `office_id`, `role`, `designation` and `designation_id` NULL and no membership.
  - It writes audit `user.create` with `no_office: true` and event `user_created` (`role` and `office` null).
  - One of the two without the other raises `UserError`.
  - `user_summary` writes NULL as null.
- **`api/routers/users.py`**
  - `POST /admin/users`: both `office_code` and `role` null mean no office.
    - Refused unless the caller is the Super Administrator: 403 `super_admin_only`.
    - `designation`, `designation_id` or `functions` with no office: 400 `bad_field` ("the designation and functions
      belong to an office").
  - `list_users`: the State-wide default adds `| User.office_id.is_(None)` when there is no `office` or `role` filter;
    `no_office` works as decision 17 says.
  - `_functions_out` handles a NULL role.
- **`api/routers/auth.py::user_out`**: `office` is None when `user.office_id` is None.
- **`services/offices.py`**
  - `_set_head(session, actor, actor_user, office, head)`:
    - `head` is `{"user_id"} | {"email"}` plus `designation` / `designation_id`;
    - it resolves the login by id or through `memberships.lookup`: unknown → 400 `bad_field`, disabled → 409
      `login_inactive`;
    - it fills `designation` from `Designation.name` when only the id is given;
    - it calls `tickets.record_direct_set(..., {"user": str(user.id), "designation", "designation_id"})`.
    The new-login branch is no longer reachable from here; `_make_incoming` keeps it for the admin swap.
  - `create_office` and `reactivate_office` change only in the `head` shape; `head_required` stays as today.
- **`services/tickets.py`**: no change.
- **`cli/users.py`, `cli/offices.py`**: as decision 21. `cli/cases.py` prints "no office" for a NULL role.

## API

| Method and path | Function | Change |
|---|---|---|
| `POST /admin/offices` | `offices.manage` (a Department-tier kind: the Super Administrator only, unchanged) | `head: HeadIn` as decision 6. 201 `OfficeDetailOut` (unchanged). Errors: 400 `head_required`, `bad_field`; 403 `super_admin_only`; 409 `login_inactive`, `super_admin_single`, `head_exists`; 422 for a retired field, or for neither or both of `user_id` and `email`. |
| `POST /admin/offices/{code}/reactivate` | `offices.manage` (a Department-tier office: the Super Administrator only, unchanged) | The same `head` change. |
| `POST /admin/users` | `users.create`; with no office, the Super Administrator only | `office_code: str \| None`, `role: Role \| None`; both null mean no office (decision 15). Errors: 403 `super_admin_only`; 400 `bad_field` (only one of the two, or a designation or functions with no office). |
| `GET /admin/users` | `users.view` | The State-wide default also lists logins with no office yet. New `no_office: bool`: State-wide scope only, else 403 `scope`; 400 `bad_field` with `office` or `role`. `UserOut.office` and `UserOut.role` are nullable (decision 16). The picker calls it with `q`, `limit=20` and, for a State-wide caller, `include_ended=true`. |
| `GET /admin/users/{id}`, `GET /me` and every other `UserOut` | unchanged | `office` and `role` are null for a login with no office yet. |
| `GET /admin/users/{id}/permissions` | `users.view` | `UserFunctionsOut.role` is nullable. |
| `GET /admin/designations` | signed in | Unchanged; it feeds the designation dropdown. |
| `POST /admin/tickets/head-change` | `users.propose_head` or `admin.tickets` | Unchanged. |
| `GET /admin/users/lookup` | `users.create` | Unchanged (Someone From Another Office; New User's e-mail check). |

- **Case visibility is unchanged.** A login with no office has no membership, so it has no basis on any case.
- `frontend/openapi.json` and `schema.d.ts` are regenerated.
- `UserChoice` in `lib/api/types.ts` is a `Pick` of `UserOut` (`id`, `email`, `full_name`, `is_active`, `office`,
  `memberships`).

**Portal:**
- **`components/ui/UserPicker.tsx`** (new) and its CSS module, exported from the kit.
- **`components/admin/Offices.tsx`:**
  - `HeadDraft` becomes `{ user: UserChoice | null; designationId: string }`;
  - `headBody` returns `{ user_id, designation_id, designation }`;
  - `HeadFields` becomes `HeadSection` (decision 11), used by `NewOfficeForm` and the Reactivate dialog;
  - the draft and the `?head=` / `?reactivate=` handling of decision 8;
  - Create Office is disabled until a person and a designation are chosen.
- **`components/admin/Tickets.tsx`:** decision 9.
- **`components/admin/Users.tsx`:**
  - `NewUserForm` gets the No Office Yet tick for the Super Administrator, `?no_office=1` and `?return=`;
  - the Users list gets the badge and the More Filters No Office Yet.
- **`components/admin/UserDetails.tsx`:** the No Office Yet header line and empty state.
- **`components/dashboard/Blocks.tsx`:** the `NoDashboard` card for an empty `memberships`.
- **`lib/messages.ts`:**
  - `T.offices.headSection` becomes "Head of the Department"; `headIntro` is rewritten; new `headPerson`,
    `headDesignation`, `headDesignationHint`, `addUserLink`;
  - new `T.userPicker.*`: placeholder, minimum, none, first 20, the reasons, `noOfficeYet`, `noActiveOffice`;
  - `T.tickets.incomingHead` and `otherOffice`;
  - `T.users.noOfficeYet`, `noOfficeYetHint`, `filterNoOffice`;
  - `T.userDetails.noOfficeYetEmpty`;
  - `T.dash.noOfficeTitle` and `noOfficeText`.
  The Title Case guards of both suites cover the new labels.

## Jobs

None.

## Tests

**pytest** (`tests/db/test_offices.py`, `test_api_offices.py`, `test_head_change_tickets.py`, `test_api_users.py`,
`test_api_auth.py`, a migration test):
- `test_create_department_with_picked_head` — `head.user_id` of a login holding an office elsewhere creates:
  - the department;
  - a `dept_head` membership at it with the chosen designation (the text filled from `designation_id`);
  - an approved direct `head_change` ticket, `membership.added`, and `office.create` with `after.head`.
- `test_one_person_heads_two_departments` — the same login, picked for two new departments, ends with two active
  `dept_head` memberships, and its first membership stays primary.
- `test_head_picked_by_email_still_works` — `head.email` (the CLI path) gives the same result.
- `test_head_unknown_email_refused` — 400 `bad_field` with "add the person in Users first"; nothing is written.
- `test_head_new_login_fields_refused` — `password`, `full_name` or `mobile` in `head` → 422. Both `user_id` and
  `email`, or neither → 422.
- `test_head_inactive_login_refused` — 409 `login_inactive`; the office is not created.
- `test_head_super_admin_refused` — 409 `super_admin_single`.
- `test_head_does_not_touch_department_admin` — the `dept_admin` of department X is picked as head of a new department
  Y:
  - X's admin membership is unchanged;
  - Y has a head and no admin;
  - `one_dept_admin` still holds for Y.
- `test_reactivate_with_picked_head` — reactivation with `head.user_id`; a second head while one is active → 409
  `head_exists`.
- `test_department_needs_head` — no `head` on creation or reactivation → 400 `head_required` (unchanged).
- `test_create_department_requires_function` — 403 in each case:
  - `POST /admin/offices` without `offices.manage`;
  - a department admin with `offices.manage` asking for a Department-tier kind;
  - `GET /admin/users?q=` without `users.view`.
- `test_picker_scope_of_department_admin` — `GET /admin/users?q=` for a department admin lists only their department's
  people, and never a login with no office.
- `test_create_login_without_office` — the Super Administrator's `POST /admin/users` with `office_code` and `role` null:
  - answers 201;
  - `users.office_id` and `role` are NULL, and no membership exists;
  - `user.create` has `no_office: true`;
  - `UserOut.office` and `role` are null.
- `test_login_without_office_refusals`:
  - a department admin → 403 `super_admin_only`;
  - only one of `office_code` / `role` → 400;
  - a designation or functions with no office → 400.
- `test_users_placed_check` — a `users` row with `office_id` NULL and a role set fails `ck_users_placed`.
- `test_login_without_office_signs_in_and_sees_nothing`:
  - the code sign-in, password change and profile confirmation succeed;
  - `/me` has no memberships and no functions;
  - these answer 403, or an empty list where documented: `GET /cases/search`, `/cases/{ref}`, `/inbox/mine`,
    `/inbox/mine/counts`, `/dashboard/me`, `/alerts`, `/me/calendar`, `/causelists/*`, `/assistant/*`, `/reports`,
    `/audit`;
  - the alert scan raises nothing for it, and the digest sends it nothing.
- `test_users_list_no_office`:
  - the State-wide default lists the login with `office: null`;
  - `no_office=true` lists only such logins;
  - `no_office` with `office` → 400; from a department admin → 403 `scope`;
  - `X-Total-Count` matches.
- `test_pick_login_without_office_as_head`:
  - its first membership is the `dept_head` one, and it is primary;
  - the mirror is filled (`dept_head`, the department office);
  - the ticket rows are written.
- `test_pick_exited_login_as_head` — a login that left its last office is accepted (`login_no_office` retired).
- `test_add_office_to_login_without_office`:
  - the Super Administrator's Add Office makes the membership primary and fills the mirror;
  - a department admin can add the login to their office through the exact-e-mail path.
- `test_migration_users_placed` — upgrade and downgrade on an empty database; downgrade refuses while a login with no
  office exists.
- `test_cli_users_create_no_office` and `test_cli_offices_create_existing_head_only` — an unknown `--head-email` exits
  non-zero with the `--no-office` hint, and there is no password prompt.

**vitest** (`components/ui/userPicker.test.tsx`, `components/admin/admin.test.tsx`,
`components/dashboard/dashboard.test.tsx`):
- **The picker:**
  - no request under 2 characters;
  - one debounced request with `q` and `limit=20`;
  - `include_ended=true` only with `includeWithoutOffice`;
  - options show the offices with a `Head` badge, or `No Office Yet` / `No Active Office`;
  - greyed options show their reason and are skipped by the arrows;
  - Enter, Escape and clear work as in `OfficePicker`;
  - "Showing the first 20" and "No person matches".
- **`NewOfficeForm`** with a Department-tier kind:
  - no password, full name, e-mail or mobile field;
  - `head` is `{user_id, designation_id, designation}`;
  - Create Office stays disabled until a person and a designation are chosen;
  - the link saves the draft and goes to `/admin/users/new?no_office=1&return=…`;
  - returning with `?head=<id>` restores the draft and picks the person;
  - a directorate kind shows no head section.
- **The Reactivate dialog:** sends the same body.
- **`NewTicketForm`:**
  - `membership_id` for a person in the department, `email` otherwise;
  - "Someone From Another Office" only for a scope that is not State-wide;
  - `?department=&operation=set` fill the form.
- **`NewUserForm`:**
  - No Office Yet is shown only to the Super Administrator;
  - ticked, it hides the office fields and sends `office_code: null, role: null`;
  - `?no_office=1` starts it ticked;
  - after creation it returns to `return` with `?head=`.
- **The Users list:** the `No Office Yet` badge; the filter sends `no_office=true`.
- **User Details:** the header line and the empty state.
- **`NoDashboard`:** the No Office Yet card when `memberships` is empty.

**uicheck** (`frontend/e2e/uicheck.spec.ts`, at 375, 768 and 1280 px):
- `/admin/offices/new (Department, head section)`;
- `/admin/offices/new (User Picker open)`, with an offices line, a `No Office Yet` option and a greyed option;
- `/admin/offices/<code> (Reactivate dialog)`;
- `/admin/tickets/new (Incoming Head)`;
- `/admin/users/new (No Office Yet ticked)`;
- `/admin/users (No Office Yet filter)`.
Each state has no `doubled-heading` or `gutter` finding, the field-row rule holds, and there is one primary per page.

## Verification

1. `pytest -q`, `ruff check`, `npm run lint`, `npm run typecheck` and `npm test` are green.
2. Apply the migration with the `migrate` step after the merge. `alembic heads` shows the new head.
3. `docker compose --profile uicheck run --rm uicheck` finds nothing on the six new states.
4. In the portal at `http://localhost:3000`, as the Super Administrator:
   1. **Create a login with no office.** Users → New User, a new e-mail, tick No Office Yet, Create. The person shows
      in Users with `No Office Yet`, and the No Office Yet filter lists them.
   2. **Sign in as that person** in another browser. The code, the password change and the profile with a mobile all
      work. The dashboard shows the No Office Yet card, with no case, alert or calendar entry.
   3. **Name them head.** Administration → Offices → New Office, Kind Department, code `TESTA`. Type two letters of
      the person's name: the option shows `No Office Yet`. Pick them, choose Secretary, Create Office.
      - The department page shows them as Head.
      - Their User Details lists one `Head` membership, as primary.
   4. **Head a second department.** Create `TESTB` with the same person. Their User Details lists two `Head`
      memberships.
   5. **Keep the draft.** On New Office, fill the code and name, then click "Add a New User in Users". Create a person
      and come back: the form keeps the code and name and has the new person picked.
   6. **Check the audit.**
      - `GET /audit?office=TESTA` shows `office.create`, `membership.added` and `ticket.approved`.
      - The person's `user.create` row has `no_office: true`.
   7. **Clean up.** End the heads with the head-change `end`, then deactivate the test offices.
5. **The CLI path.** `aslms users create --email <new> --name "Test Head" --no-office`, then `aslms offices create
   --code TESTD --kind department --parent GOA --name "Test D" --head-email <that e-mail>`. The department is created.
   With an unknown e-mail the command refuses with the `--no-office` hint.

## Open questions

None. The open question of the blocked revision is answered with (A), logins without an office (owner, 26 Oct 2026).
