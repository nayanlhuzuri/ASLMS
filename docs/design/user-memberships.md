# Design: User memberships — one login, several offices, each with its own designation and user type

```
slug: user-memberships
status: awaiting-approval
author: architect
date: 2026-10-07
approved_by: — (awaiting the product owner)
```

## Context
The owner's rules of 7 Oct 2026 (decisions log, "Custody and file movement — owner's rules", last bullet): "A
user can hold designations in more than one department: one login with several memberships (department,
designation and user type each). They see and act on the cases of all their departments with the rights of
their type in each. When sending a file, the sender picks the person and the membership." The revised
`custody-workflow` (sending the file to "an officer — a membership") is built on this item, so this item comes
first (backlog row 28, placed above row 6).

**Deviation from the plan, set by the owner (flagged):** the plan's Table 1 and §5.1 give each user one type and
one office; schema.md `users` says "One type (role) per user". This item replaces that with memberships.

What is in place (built and merged):
- `users` (master): `office_id` (NOT NULL), `role` (→ `ref_role`), `designation` (text), `designation_id`,
  one row per login (e-mail unique, password, OTP, refresh tokens, notification preferences).
- `services/access.py`: effective functions = the type's enabled matrix rows + `user_permissions` grants −
  denies, per **user**; delegation (`assert_can_manage`, `in_scope`) on `users.office_id`'s subtree, delegable
  types `dept_officer`, `directorate_user`, `standing_counsel`, `referral_reviewer`, grant only what you hold.
- `services/visibility.py`: `visibility_bases(session, user)` from `user.office_id` / `user.role`
  (`whole_department`, personal custody and request bases, counsel codes of the department);
  `record_visibility_condition` (`private_to_office` = `user.office_id`, department-wide callers);
  `alert_office_condition` / `addressed_to_department` (`user_department`).
- `services/ownership.py`: `acting_department` (the actor's department from `office_id`; `office_code` only for
  the super admin), `eligible_officer`, `take_over` (actor's office as the new unit), `suggest`,
  `case_ownership_view`. `services/inbox.py::target_department`, `transfers`, `counts`.
- `services/recipients.py::Resolver.office_users` (users whose `office_id` is the office),
  `department_holders`. `api/deps.py::actor_of` (snapshot from `users.office_id`).
- `services/offices.py`: deactivation refused while active users reference the office.
- Roughly 85 reads of `user.office_id` / `user.role` across services and routers (counted 7 Oct); most are
  authorisation or scope reads, a few are display.

Not covered: the portal screens for memberships (`portal-shell`); OTP and profile confirmation per login
(`otp-and-profile`, unchanged: one login, one profile); SSO.

## Decisions
1. **A membership is the unit of authority.** `user_memberships` (decision 2) holds office + designation +
   user type for one person. Every function check, scope check, visibility basis and actor snapshot is computed
   from a membership, never from the login. The login (`users`) keeps what belongs to the person: e-mail,
   mobile, password, name, OTP and tokens, notification preferences, active flag. Alternative: one login per
   department (several e-mails) — rejected by the owner ("one login").

2. **At most one active membership per person per department.** The membership stores its `department_id`
   (the Department-tier ancestor of its office, derived at insert, immutable because offices are never
   re-parented — offices-admin decision) and a partial unique index allows one active row per (user,
   department); State-tier memberships (office at the State root, `department_id` NULL) count as one
   "department". So "the person's membership in department D" is always unique, which makes every
   case-scoped action unambiguous (decision 6) and keeps `case_ownership.officer_user_id` meaningful without a
   new column. A person holding two posts in one department gets one membership with the stronger type.
   Alternative: any number of memberships per department — rejected: every action would need an explicit
   "acting as" choice and allotments would need a membership column. **Owner check.**

3. **`users.office_id`, `users.role`, `users.designation`, `users.designation_id` are kept as the mirror of the
   primary membership.** Exactly one active membership per login is `is_primary`; the membership service writes
   the four mirror columns in the same transaction whenever the primary membership is created, changed or
   replaced, and nothing else writes them. They are **never read for authorisation or visibility** (decision
   11 lists every read that moves). Why keep rather than drop: `users.office_id` is a NOT NULL FK used for the
   home office shown in lists and the sign-in response, the default office of records that are not
   case-scoped, the offices deactivation check's history, the CLI and the seed; dropping them is a wide,
   risky change with no gain once no authorisation code reads them. Alternative: migrate fully and drop the
   columns — rejected for this cycle; a later migration can drop them once the mirror has no reader left.

4. **Super admin.** The super admin type exists only as the primary membership at the State root; a login with
   a `super_admin` membership cannot hold another membership, and no second membership may be of type
   `super_admin` (409 `super_admin_single`). It already holds every function everywhere.

5. **Effective functions per membership.** `functions(membership)` = the membership type's enabled matrix rows
   + the membership's active grants − its active denies (`user_permissions` gains `membership_id`; overrides
   become per membership, decision 9). An inactive login has none in every membership; an ended membership has
   none. The **union** over active memberships is used only as a gate ("holds the function somewhere", e.g. the
   `require(...)` dependency) and for `/me`; every service then checks the function **in the membership that
   acts** (decision 6). So a `dept_admin` in EDU who is a `dept_officer` in HEALTH passes the gate for
   `cases.allot`, and the allot service refuses a HEALTH case because the HEALTH membership lacks it.
   Alternative: union for everything — rejected: admin rights would leak into every department of the person.

6. **The acting membership.** `access.Member` (a frozen view: user, membership, office, department, role,
   functions) is what services receive for an action. It is resolved, never chosen freely by the client:
   - an action on a department (claim, dismiss, suggest, allot, take over, transfer, inbox tabs, matching
     rules, department settings) → the caller's membership in that department (decision 2), which must hold the
     function; the existing `office_code` parameter of ownership and inbox endpoints names the department when
     the caller has several (today only the super admin may give it); without it: the primary membership's
     department when it qualifies, else the single qualifying membership, else 400 `office_required` listing the
     candidate department codes;
   - an action on a user or membership (decision 8) → the caller's membership whose subtree contains the target
     office (the super admin's always does);
   - a write on a case (notes, uploads, stages; custody actions in `custody-workflow`) → the caller's
     membership that has a **working basis** on that case and holds the function, in this order: the membership
     that holds custody personally, the membership in the owning department, then any other with a working
     basis (counsel, allotted). Ties cannot occur (decision 2).
   Alternative: an "acting as" switch in the portal sent as a header on every call — rejected: the server would
   trust a client choice, and a person with two departments would see only one at a time, contrary to "see and
   act on the cases of all their departments".

7. **Visibility is the union of the memberships' bases.** `visibility_bases(session, user)` = OR over active
   memberships of today's per-office computation (`_bases_for(member)`, unchanged logic: `owner`,
   `recommended`, `pool`, `allotted`, `custody`, `counsel` — the `request` basis is removed by
   `custody-workflow`); `[("state", true)]` when any membership is State-wide (`cases.view_all` or super
   admin). `access_basis` returns the names plus, internally, which membership produced each (used by
   decision 6). `record_visibility_condition` is OR-ed over memberships the same way (`private_to_office` = any
   membership's office, department-wide memberships' departments; the counsel rule per membership). Alerts:
   `alert_office_condition` passes alerts addressed to any membership's department. Everything stays in SQL.

8. **User administration and delegation (per membership).**
   - **Create a login** (`users.create`): as today — the first membership is the primary; scope and delegable
     types checked with the actor's membership whose subtree contains the office.
   - **Add a membership** to an existing login (`users.create`): the actor's membership's subtree must contain
     the new membership's office and the type must be delegable (super admin: any type but `super_admin`).
     So a department admin adds memberships for their own department (and its directorates and units) only,
     to anyone, including a person whose primary membership is elsewhere. The person is found by exact e-mail
     (`GET /users/lookup`), which returns the id, name and the person's memberships (office code, designation,
     type) — no list of other departments' users.
   - **Change a membership's designation** (`users.edit`) or **type** (`users.set_type`): actor's scope must
     contain that membership's office; type changes only between delegable types (as today).
   - **End / reactivate a membership** (`users.enable_disable`): scope as above; never deleted (`is_active`,
     `deactivated_at`, `valid_to`); ending is refused while the membership holds custody personally (409
     `holds_custody`; the owning department recalls first) or is the allotted officer of an active ownership row
     in that department (409 `has_allotments`); the primary membership cannot be ended (409 `primary_membership`;
     make another primary first).
   - **Make another membership primary** (`users.edit`): the super admin, or an actor whose scope contains both
     the old and the new primary office.
   - **Login-level actions** (name, e-mail, mobile, password reset, enable or disable the login): the super
     admin or an actor whose scope contains the **primary** membership's office. A department admin who added a
     membership to a HEALTH officer cannot reset that officer's password or disable the login.
   - **Grants and denies** (`users.grant`): per membership, only within the actor's scope over that membership,
     only functions the actor holds **in the acting membership** (decision 6), never on a super admin's
     membership.
   - `GET /users` (`users.view`): the logins with an active membership in the actor's scope, each listing all of
     its memberships (designations are public facts of government officers; the picker of `custody-workflow`
     shows them anyway).
   Every change writes an audit row and a `user_updated` / `access_changed` event (existing types).

9. **Overrides move to the membership.** `user_permissions` gains `membership_id` (NOT NULL after the
   back-fill to each login's primary membership); the unique key changes from (user_id, permission) to
   (membership_id, permission); `user_id` stays (equal to the membership's user, checked by the service) for
   lookups. Existing override rows keep their meaning (they applied to the only office the user had).

10. **The actor snapshot names the acting membership.** `Actor` gains `membership_id`; `access.actor_as(actor,
    member)` returns the snapshot with that membership's designation and office code. `deps.actor_of` builds the
    snapshot from the primary membership (sign-in, profile, non-case actions); services re-snapshot with the
    acting membership before writing any row or audit entry. No new snapshot column: `actor_designation` and
    `actor_office_code` already identify the membership (unique per department, decision 2). `custody-workflow`
    adds `holder_membership_id` to custody, where the membership is the subject, not the actor.

11. **Code already built that changes (no behaviour change for one-membership users).**
    - `services/access.py`: `members(session, user) -> list[Member]` (active memberships, functions cached per
      request); `effective_permissions(session, user)` = union (gate and `/me`); `member_functions`;
      `has(session, user_or_member, perm)` accepts either; `in_scope(session, member, office)`;
      `assert_can_manage(session, member, ...)` and `acting_member_for_office(session, user, office)`;
      `set_type`, `set_enabled` (login), `set_override` (membership), `actor_as`.
    - `services/memberships.py` (new): `add`, `update`, `end`, `reactivate`, `make_primary`, `lookup`,
      `membership_out`, mirror write (decision 3), the department derivation.
    - `services/users.py::create_user` writes the login and its primary membership in one step;
      `user_summary` adds memberships.
    - `services/visibility.py`: decision 7; `whole_department(session, member)`, `user_department` replaced by
      `departments(session, user)`; `claimed_conditions` and `owned_case_filter` take a `Member`.
    - `services/ownership.py`: `acting_department` → `acting_member(session, user, office_code, permission)`
      (decision 6; `office_code` honoured for any caller with a membership there); `eligible_officer` (an active
      membership of a non-State type in the department's subtree); `take_over` uses the acting membership's
      office as the new unit; `suggest`, `case_ownership_view` per membership; custody legs written by
      ownership moves name the officer's membership in that department.
    - `services/inbox.py`: `target_department` per decision 6; `counts` returns one block per department the
      caller works in (a list; one element for a one-membership user, shape change flagged in API).
    - `services/recipients.py`: `office_users(office, perm)` = users with an **active membership at that office**
      whose membership holds the function (not `users.office_id`); `department_holders` likewise;
      `finalise` unchanged (visibility is already the union).
    - `services/documents.py`, `case_detail.py`, `case_search.py`, `calendar.py`, `notifications.py`,
      `matching_rules.py`: their `user.office_id` reads go through `Member` (uploads: the `DOC` number and
      `documents.office_id` come from the acting membership's office).
    - `services/offices.py`: deactivation refused while active **memberships** reference the office (replaces the
      users check; the mirror makes the old check a subset).
    - `api/deps.py`: `current_user` unchanged (a login); `require` = union gate; `actor_of` per decision 10.
    - CLI `aslms users`: `memberships add|end|list` subcommands (super admin path, like `create-super-admin`).
    A unit test (`test_no_authority_reads_of_user_office.py`) scans `services/` and `api/` for `.office_id` /
    `.role` read off a `User` outside an allow-list (`users.py`, `memberships.py`, display helpers) so the mirror
    never becomes authority again.

12. **Events and audit.** Audit actions `membership.added`, `membership.updated`, `membership.ended`,
    `membership.reactivated`, `membership.primary_changed` (before/after: office code, designation, type,
    is_primary); `access.override` gains `membership_id` in `after`. Events: the existing `user_updated` (payload
    `user_id`, `membership_id`, `office_code`, change) and `access_changed`. No new event or alert kind; no
    e-mail is sent (the owner may ask for one later).

## Data
Migration **0008_memberships** (new file; 0001–0007 are applied and untouched; the feature branch's
`0008_workflow` was never applied to `main` and is superseded — `custody-workflow` becomes 0009).

New table, for `schema.md` "Group 1 — organisation and access":

> | `user_memberships` (master, versioned) | id (uuid v7 PK), user_id (→ users RESTRICT), office_id (→ offices RESTRICT), department_id (→ offices RESTRICT; the Department-tier ancestor of office_id, NULL for a State-tier office; derived at insert, immutable), role (→ `ref_role`), designation (text as shown, ≤ 200), designation_id (→ designations RESTRICT, NULL allowed), is_primary boolean NOT NULL default false, is_active, deactivated_at, valid_from, valid_to, created_at, updated_at, created_by, updated_by (→ users SET NULL) | One row per office a person serves in, with that office's designation and user type. Partial unique `ix_user_memberships_one_per_department` (user_id, department_id) NULLS NOT DISTINCT WHERE is_active; partial unique `ix_user_memberships_primary` (user_id) WHERE is_primary AND is_active; index `ix_user_memberships_office_active` (office_id) WHERE is_active. CHECKs `ck_user_memberships_active` (is_active = (deactivated_at IS NULL)), `ck_user_memberships_primary_active` (NOT is_primary OR is_active). A `super_admin` membership is the login's only membership (service). Ended, never deleted. Functions per membership = type matrix + the membership's overrides; visibility = the union over active memberships (design `user-memberships`). |

Changed rows of `schema.md` group 1:

> | `users` (master) | … (unchanged columns) | **A login.** `office_id`, `role`, `designation`, `designation_id` mirror the primary membership (written only by the membership service, never read for authorisation). Authority lives in `user_memberships`. |
> | `user_permissions` (master) | user_id, **membership_id (→ user_memberships RESTRICT, NOT NULL)**, permission, effect, granted_by_user_id, reason, is_active, deactivated_at, valid_from, valid_to, actor snapshot; **unique (membership_id, permission)** | Overrides per membership; `user_id` equals the membership's user. |

Conventions paragraph: "Case visibility is one rule … evaluated per active membership and OR-ed; functions are
per membership (type matrix + the membership's overrides); the union is only a gate."

Migration 0008 contents: create `user_memberships` with the indexes and CHECKs, grants (SELECT/INSERT/UPDATE
for `aslms_app`), `COMMENT ON TABLE … 'class=master'`, the `set_updated_at` trigger; back-fill one primary
membership per existing user (`office_id`, `role`, `designation`, `designation_id`, `is_active` from `users`;
`department_id` from the office path's second segment when that office is Department-tier); add
`user_permissions.membership_id` nullable, back-fill to the primary membership, set NOT NULL, add the FK
(RESTRICT), drop `uq_user_permissions_user_id` (the built name, checked against 0003 by the developer), add
`uq_user_permissions_membership_id`. Downgrade: stops while any login has more than one membership or any
non-primary membership exists; otherwise drops exactly these. No reference codes change; no new function.

## Services
- `services/memberships.py` (new): `add(session, actor, member, user, *, office, role, designation,
  designation_id)`, `update(..., designation?, designation_id?, role?)`, `end(..., reason)`, `reactivate`,
  `make_primary`, `lookup(session, email)`, `membership_out`; each checks decision 8 with the acting member,
  writes the mirror (decision 3), audit (decision 12) and the `user_updated` event. `end` checks custody and
  allotments under a row lock on the membership.
- `services/access.py`, `visibility.py`, `ownership.py`, `inbox.py`, `recipients.py`, `documents.py`,
  `case_detail.py`, `case_search.py`, `calendar.py`, `notifications.py`, `matching_rules.py`, `offices.py`,
  `users.py`: decision 11.
- `api/deps.py`: decision 10; a helper `member_for(request, session, user, *, department=None, office=None,
  case=None, permission)` that routers call to resolve decision 6 and map failures to 403 / 400.

## API
Existing endpoints keep their paths; the changes:

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /me` | signed in | — | `{user, memberships: [{id, office: {code, name, kind}, department_code, designation, role, is_primary, functions: [...]}], functions: [...] (union)}` | The caller's own. |
| `POST /auth/login`, `/auth/refresh` | — | unchanged | `user` gains `memberships` (as above, without functions) | — |
| `GET /users` | `users.view` | unchanged filters + `office?` | each user with `memberships` | Logins with an active membership in the actor's scope (decision 8). |
| `GET /users/lookup` | `users.create` | `email` (exact) | `{id, full_name, memberships: [{office_code, designation, role}]}` or 404 | For adding a membership to a person outside the actor's scope. |
| `POST /users/{id}/memberships` | `users.create` | `{office, role, designation?, designation_id?}` | membership 201 | Decision 8; 409 `one_per_department`, `super_admin_single`; 403 out of scope / non-delegable type. |
| `PATCH /users/{id}/memberships/{mid}` | `users.edit` (designation) / `users.set_type` (role) | `{designation?, designation_id?, role?}` | membership | Scope over that membership's office. |
| `POST /users/{id}/memberships/{mid}/end` | `users.enable_disable` | `{reason}` (3–500) | membership | 409 `holds_custody`, `has_allotments`, `primary_membership`. |
| `POST /users/{id}/memberships/{mid}/reactivate` | `users.enable_disable` | — | membership | 409 `one_per_department` when another active one exists in that department. |
| `PUT /users/{id}/primary-membership` | `users.edit` | `{membership}` | user | Decision 8. |
| `GET /users/{id}/memberships/{mid}/permissions` | `users.view` | — | `{type_functions, overrides, effective}` | Scope over the membership. |
| `PUT /users/{id}/memberships/{mid}/permissions/{permission}` | `users.grant` | `{effect: grant|deny|null, reason?}` | as above | Decision 8 (grant only what the acting membership holds). |
| `PUT /users/{id}/type`, `GET/PUT /users/{id}/permissions…` | as today | unchanged | unchanged | Kept for compatibility: act on the **primary** membership. |
| `PATCH /users/{id}`, `POST /users/{id}/enable|disable`, `POST /users/{id}/password` | as today | unchanged | unchanged | Scope over the **primary** membership's office (login-level). |
| `GET /inbox/counts` | as today | `office?` | **`{departments: [{office_code, …counts}]}`** | Shape change: one block per department the caller works in (flagged; no portal consumes it yet). |
| Ownership and inbox endpoints with `office_code` / `office` | unchanged | the parameter is honoured for any caller with a membership in that department | unchanged | Decision 6; 400 `office_required` with candidates when ambiguous. |

## Jobs
None.

## Tests
Unit (`tests/unit/`):
- `test_no_authority_reads_of_user_office.py` (decision 11's scan).
- `test_membership_rules.py`: department derivation from a path; acting-membership preference order for case
  writes; union gate vs per-membership check.

Database (`tests/db/`; `world.py` gains a two-department person: `dept_admin` in EDU, `dept_officer` in HEALTH):
- `test_memberships.py`: migration back-fill gives every user exactly one primary membership equal to the mirror
  and moves overrides; add a membership in own department (allowed) and in another department (403); one active
  membership per department (409, and the index refuses a racing insert); `super_admin` cannot get a second
  membership; ending refused while holding custody / allotted / primary; make-primary rewrites the mirror; ended
  membership has no functions; lookup by exact e-mail only; audit rows for each change.
- `test_membership_access.py`: the EDU-admin/HEALTH-officer person can allot an EDU case and cannot allot,
  claim or take over a HEALTH case; can grant EDU users only functions held as EDU admin; cannot manage HEALTH
  users; a HEALTH admin cannot reset the person's password (primary in EDU) but can end their HEALTH
  membership; overrides on one membership do not apply to the other.
- `test_membership_visibility.py`: the person sees EDU-owned cases (whole department) and HEALTH cases only on
  personal bases (allotted, custody); `access_basis` names both; private-to-office notes and documents of
  either office visible; alerts addressed to either department visible; a one-membership user's visible set is
  unchanged (regression over the existing `test_case_visibility.py` matrix).
- `test_membership_recipients.py`: `office_users` finds a person through a non-primary membership at that office
  and only when that membership holds the function; no duplicate notification for a person with two matching
  memberships.
- `test_api_memberships.py`: each endpoint's function check (403), scope errors, shapes; `/me` lists memberships
  with per-membership functions and the union; `inbox/counts` returns a block per department; ownership
  endpoint with `office_code` of a second department.
- Existing suites stay green (`test_access.py`, `test_ownership.py`, `test_case_visibility.py`,
  `test_alert_recipients.py`, `test_api_*`); `test_migrations.py` covers 0008 upgrade → downgrade → upgrade;
  `test_schema_metadata.py` in step with `schema.md`.

## Verification
1. `docker compose run --rm api alembic current` → `0007`; if the dev database carries the feature branch's
   `0008_workflow`, the integrator first downgrades it to `0007` from that branch's checkout. Then `alembic
   upgrade head` → `0008_memberships`; `psql`: `SELECT count(*) FROM users` = `SELECT count(*) FROM
   user_memberships WHERE is_primary`; `SELECT count(*) FROM user_permissions WHERE membership_id IS NULL` = 0.
2. `ruff check` clean; `pytest -q` green (count in the cycle report).
3. With Compose up: as the super admin create a person in EDU (`dept_admin`); as the HEALTH department admin
   `GET /users/lookup?email=…` and `POST /users/{id}/memberships` with `office=HEALTH`, `role=dept_officer`;
   sign in as the person: `GET /me` shows two memberships; `GET /inbox/counts` shows EDU and HEALTH blocks;
   `POST /cases/{ref}/allot` on a HEALTH-owned case → 403; on an EDU-owned case → 200 with the audit row's
   `actor_office_code = EDU`.
4. As the HEALTH admin `POST /users/{id}/password` → 403; `POST /users/{id}/memberships/{mid}/end` → 200; the
   person's `/me` lists one membership.

## Open questions
None. Points the owner is asked to check at approval (decisions taken, reversible):
- one active membership per person per department (2) — two posts in one department become one membership;
- the `users` office, type and designation columns kept as a mirror of the primary membership (3), dropped in a
  later migration;
- the acting membership is resolved by the server, with no "acting as" switch (6);
- a department admin may add a membership for their department to a person from any department, found by exact
  e-mail; login-level actions (password, disable) stay with the primary office's admins (8);
- ending a membership is refused while it holds custody or allotments (8);
- `GET /inbox/counts` changes shape to one block per department (API table).
