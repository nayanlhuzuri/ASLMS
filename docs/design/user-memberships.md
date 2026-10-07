# Design: User memberships — one login, several offices, each with its own designation and user type

```
slug: user-memberships
status: awaiting-approval
author: architect
date: 2026-10-07 (revised the same day with the owner's review: head changes with a second-level check,
      the admin ticket queue, the government order, one super admin and one department admin, the exit step)
approved_by: — (awaiting the product owner)
```

## Context
The owner's rules of 7 Oct 2026 (decisions log, "Custody and file movement — owner's rules", last bullet): "A
user can hold designations in more than one department: one login with several memberships (department,
designation and user type each). They see and act on the cases of all their departments with the rights of
their type in each. When sending a file, the sender picks the person and the membership." The revised
`custody-workflow` (sending the file to "an officer — a membership") is built on this item, so this item comes
first (backlog row 28, placed above row 6).

**Owner's review of 7 Oct 2026 (folded into this revision, each change marked "(owner review 2026-10-07)"):**
1. A department admin may assign the head (`dept_head`, exactly one per department, and a department always
   has one — owner's answers) of their own department, subject to the super admin's
   approval; until approved, nothing changes.
2. Such proposals reach the super admin as tickets in a panel; the mechanism is generic (`head_change` is the
   first kind).
3. An optional supporting document (the government order) is uploaded with the head-change request, or later
   while the ticket is open (not after the decision — owner's answer), and stays findable on the membership it
   authorised.
4. Exactly one super admin in the system and exactly one department admin per department ("creating too many
   admins loses the purpose of admin roles"), enforced in the database and the services.
5. When an officer is transferred out of a department, the department admin reassigns each of their allotted
   cases and held files to an officer of the department (no successor; revised the same day), after a preview;
   the exit completes in one step once every item has a target.

**Deviation from the plan, set by the owner (flagged):** the plan's Table 1 and §5.1 give each user one type and
one office; schema.md `users` says "One type (role) per user". This item replaces that with memberships. **Further
deviations (owner review 2026-10-07, flagged):** the plan has no approval queue, no "one admin" rule and no
off-boarding step; all three are the owner's rules of 7 Oct 2026.

What is in place (built and merged):
- `users` (master): `office_id` (NOT NULL), `role` (→ `ref_role`), `designation` (text), `designation_id`,
  one row per login (e-mail unique, password, OTP, refresh tokens, notification preferences).
- `services/access.py`: effective functions = the type's enabled matrix rows + `user_permissions` grants −
  denies, per **user**; delegation (`assert_can_manage`, `in_scope`) on `users.office_id`'s subtree, delegable
  types `dept_officer`, `directorate_user`, `standing_counsel`, `referral_reviewer`, grant only what you hold.
- `services/visibility.py`: `visibility_bases(session, user)` from `user.office_id` / `user.role`
  (`whole_department`, personal custody and request bases, counsel codes of the department);
  `record_visibility_condition` (`private_to_office` = `user.office_id`, department-wide callers);
  `alert_office_condition` / `addressed_to_department` (`user_department`); `document_case_condition` (a
  document is visible only through a visible case — a document with no case is never returned by it).
- `services/ownership.py`: `acting_department` (the actor's department from `office_id`; `office_code` only for
  the super admin), `eligible_officer`, `allot`, `take_over` (actor's office as the new unit), `suggest`,
  `case_ownership_view`. `services/inbox.py::target_department`, `transfers`, `counts`.
- `services/custody.py::move_custody` (ownership reasons; `custody_history.reason` is `varchar(60)`, no CHECK
  until `custody-workflow`'s 0009).
- `services/recipients.py::Resolver.office_users` (users whose `office_id` is the office),
  `department_holders`. `api/deps.py::actor_of` (snapshot from `users.office_id`).
- `services/offices.py`: deactivation refused while active users reference the office; `department_admins`,
  `add_department_admin` ("the first department admin", super admin only; nothing stops a second one today).
- `services/access_seed.py`: the seed creates the `.env` super admin when that e-mail is unknown (a second super
  admin if another one exists); CLI `aslms users create-super-admin` creates one more each time.
- `services/documents.py::upload` (kinds `upload` / `attachment`; type check by content, ClamAV, size limit,
  `DOC` number) and the alert tables of 0007 (`alerts.case_id` NOT NULL; notifications hang off an alert).
- Roughly 85 reads of `user.office_id` / `user.role` across services and routers (counted 7 Oct); most are
  authorisation or scope reads, a few are display.

Not covered: the portal screens for memberships, the ticket panel and the exit dialog (`portal-shell`); OTP and
profile confirmation per login (`otp-and-profile`, unchanged: one login, one profile); SSO; ticket kinds beyond
`head_change` (later items add them through decision 17's registry).

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
   "acting as" choice and allotments would need a membership column. **Owner check.** (owner review
   2026-10-07) The type-specific limits of decisions 13 and 14 sit beside this one (one `super_admin` in the
   system, one `dept_admin` per department).

3. **`users.office_id`, `users.role`, `users.designation`, `users.designation_id` are kept as the mirror of the
   primary membership.** Exactly one active membership per login is `is_primary` (owner review 2026-10-07: or
   none, while a transferred officer waits for their next department — decision 22); the membership service
   writes the four mirror columns in the same transaction whenever the primary membership is created, changed or
   replaced, and nothing else writes them (with no primary left they keep the last values). They are **never
   read for authorisation or visibility** (decision 11 lists every read that moves). Why keep rather than drop:
   `users.office_id` is a NOT NULL FK used for the home office shown in lists and the sign-in response, the
   default office of records that are not case-scoped, the offices deactivation check's history, the CLI and the
   seed; dropping them is a wide, risky change with no gain once no authorisation code reads them. Alternative:
   migrate fully and drop the columns — rejected for this cycle; a later migration can drop them once the mirror
   has no reader left.

4. **Super admin.** The super admin type exists only as the primary membership at the State root; a login with
   a `super_admin` membership cannot hold another membership, and no second membership may be of type
   `super_admin` (409 `super_admin_single`). It already holds every function everywhere. (owner review
   2026-10-07) There is exactly one in the whole system and it is created and replaced only from the server's
   command line — decision 13. **General rule (owner review 2026-10-07: "the super admin can do anything"):**
   the super admin is never subject to an approval step or to the delegation limits — no ticket waits for
   anyone when the super admin acts, no scope or delegable-type check applies, and grants are not limited to
   functions held. What still binds the super admin: the database invariants (one super admin, one department
   admin per department, one head per department and a department always has a head — decisions 13, 14, 15,
   24; one membership per person per department — decision 2), the no-deletion rules (memberships ended,
   documents archived, tickets closed, never deleted), the paths that keep records complete (head changes
   through the head-change endpoint so the change and its order are recorded; the super admin's own
   replacement only from the CLI), and the audit of every action.

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
     basis (counsel, allotted). Ties cannot occur (decision 2);
   - (owner review 2026-10-07) an action on an admin ticket → the caller's membership in the ticket's
     department holding `users.propose_head` (proposer side) or the super admin membership (decider side).
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
   (owner review 2026-10-07) Case-less records added by this revision (tickets, their documents, `admin_ticket`
   alerts) have their own rules in decisions 18–20, also in SQL.

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
   - (owner review 2026-10-07) **`dept_head` changes only through the head-change request** (decision 15):
     the membership endpoints refuse any add or reactivation that makes a `dept_head` (409
     `use_head_change`) and any end, type change or exit of the current head's membership (409
     `head_required`, decision 24), for every caller including the super admin; a department admin's request opens a ticket, the
     super admin's is applied at once and recorded. `dept_admin` stays outside every department admin's reach
     (decision 14); `super_admin` is outside the API (decision 13).
   - **End / reactivate a membership** (`users.enable_disable`): scope as above; never deleted (`is_active`,
     `deactivated_at`, `valid_to`). ~~Ending is refused while the membership holds custody personally (409
     `holds_custody`) or is the allotted officer of an active ownership row (409 `has_allotments`); the primary
     membership cannot be ended (409 `primary_membership`).~~ (owner review 2026-10-07) **Replaced by the exit
     step (decisions 21–22):** ending a membership that holds files or allotments needs a target officer for
     each of them, chosen by the admin and applied in the same transaction (no successor); ending the primary membership passes
     the primary flag to another active membership, or leaves the login without one. Ending or reactivating a `dept_head`
     membership goes through the head-change request (decision 15); a `dept_admin` membership only through the super admin's swap
     (decision 14); a `super_admin` membership never through the API (decision 13).
   - **Make another membership primary** (`users.edit`): the super admin, or an actor whose scope contains both
     the old and the new primary office.
   - **Login-level actions** (name, e-mail, mobile, password reset, enable or disable the login): the super
     admin or an actor whose scope contains the **primary** membership's office. A department admin who added a
     membership to a HEALTH officer cannot reset that officer's password or disable the login. (owner review
     2026-10-07) A login with no active membership (decision 22): the super admin only. The super admin's own
     login cannot be disabled through the API (403 `super_admin_cli_only`). Disabling the login of a person
     who is a department's head is refused (409 `head_required`; replace the head first, decision 24).
   - **Grants and denies** (`users.grant`): per membership, only within the actor's scope over that membership,
     only functions the actor holds **in the acting membership** (decision 6), never on a super admin's
     membership. (owner review 2026-10-07) `admin.tickets` is never granted (decision 18).
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
    adds `holder_membership_id` to custody, where the membership is the subject, not the actor. (owner review
    2026-10-07) `admin_tickets` keeps `requested_by_membership_id` beside the snapshot, because the ticket is
    acted on later by the proposer's membership (withdraw) and its department is checked against it.

11. **Code already built that changes (no behaviour change for one-membership users).**
    - `services/access.py`: `members(session, user) -> list[Member]` (active memberships, functions cached per
      request); `effective_permissions(session, user)` = union (gate and `/me`); `member_functions`;
      `has(session, user_or_member, perm)` accepts either; `in_scope(session, member, office)`;
      `assert_can_manage(session, member, ...)` and `acting_member_for_office(session, user, office)`;
      `set_type`, `set_enabled` (login), `set_override` (membership), `actor_as`. (owner review 2026-10-07)
      `RESERVED_FUNCTIONS = {admin.tickets}` refused by `set_override` and by the matrix editor (400
      `reserved_function`); `set_enabled` refuses the super admin's login.
    - `services/memberships.py` (new): `add`, `update`, `end`, `reactivate`, `make_primary`, `lookup`,
      `membership_out`, mirror write (decision 3), the department derivation; (owner review 2026-10-07) the
      admin-type limits (decisions 13–14), the head-change routing (decision 15), `exit_preview` and the exit
      step (decisions 21–22), `replace_department_admin` (decision 14), `replace_super_admin` (CLI only,
      decision 13).
    - `services/users.py::create_user` writes the login and its primary membership in one step;
      `user_summary` adds memberships.
    - `services/visibility.py`: decision 7; `whole_department(session, member)`, `user_department` replaced by
      `departments(session, user)`; `claimed_conditions` and `owned_case_filter` take a `Member`.
    - `services/ownership.py`: `acting_department` → `acting_member(session, user, office_code, permission)`
      (decision 6; `office_code` honoured for any caller with a membership there); `eligible_officer` (an active
      membership of a non-State type in the department's subtree); `take_over` uses the acting membership's
      office as the new unit; `suggest`, `case_ownership_view` per membership; custody legs written by
      ownership moves name the officer's membership in that department. (owner review 2026-10-07)
      `reallot_on_exit(session, actor, case, *, from_user, to_member)` (decision 21).
    - `services/custody.py` (owner review 2026-10-07): reason `reassigned_on_exit` added to `REASONS`
      (decision 21; `custody-workflow` puts it in its CHECK).
    - `services/inbox.py`: `target_department` per decision 6; `counts` returns one block per department the
      caller works in (a list; one element for a one-membership user, shape change flagged in API).
    - `services/recipients.py`: `office_users(office, perm)` = users with an **active membership at that office**
      whose membership holds the function (not `users.office_id`); `department_holders` likewise;
      `finalise` unchanged (visibility is already the union).
    - `services/documents.py`, `case_detail.py`, `case_search.py`, `calendar.py`, `notifications.py`,
      `matching_rules.py`: their `user.office_id` reads go through `Member` (uploads: the `DOC` number and
      `documents.office_id` come from the acting membership's office). (owner review 2026-10-07)
      `documents.py`: the upload path accepts kind `admin` (decision 20) — no case, no working-relation check,
      types limited to the ticket kind's `doc_types` (decision 20), group `internal`, no `document_uploaded` event (that event is a case
      timeline entry); case uploads refuse `government_order` (400 `bad_field`); `upload_types()` leaves it out.
    - `services/alerts.py`, `notifications.py`, `mailer` message builder (owner review 2026-10-07): case-less
      `admin_ticket` alerts (decision 19) — the in-app list, counts, detail, acknowledge / done and the
      single-alert e-mail and digest take an outer join to `cases` and a case-less branch.
    - `services/offices.py`: deactivation refused while active **memberships** reference the office (replaces the
      users check; the mirror makes the old check a subset). (owner review 2026-10-07)
      `add_department_admin` refuses when the department has an active admin (409 `admin_exists`; use the swap,
      decision 14); `department_admins` reads memberships (at most one row).
    - `services/access_seed.py` (owner review 2026-10-07): the `.env` super admin is created only when no active
      `super_admin` membership exists; otherwise the seed reports `super admin exists (<e-mail>); .env not used`
      and changes nothing.
    - `api/deps.py`: `current_user` unchanged (a login); `require` = union gate; `actor_of` per decision 10.
    - CLI `aslms users`: `memberships add|end|list` subcommands (super admin path, like `create-super-admin`).
      (owner review 2026-10-07) `create-super-admin` refuses when one exists; new `replace-super-admin`
      (decision 13); the CLI's acting identity (`_actor`) becomes "the single active super admin" instead of the
      `.env` e-mail lookup.
    A unit test (`test_no_authority_reads_of_user_office.py`) scans `services/` and `api/` for `.office_id` /
    `.role` read off a `User` outside an allow-list (`users.py`, `memberships.py`, display helpers) so the mirror
    never becomes authority again.

12. **Events and audit.** Audit actions `membership.added`, `membership.updated`, `membership.ended`,
    `membership.reactivated`, `membership.primary_changed` (before/after: office code, designation, type,
    is_primary); `access.override` gains `membership_id` in `after`. Events: the existing `user_updated` (payload
    `user_id`, `membership_id`, `office_code`, change) and `access_changed`. ~~No new event or alert kind;~~ no
    e-mail is sent for membership changes (the owner may ask for one later). (owner review 2026-10-07) Added
    audit actions: `ticket.opened`, `ticket.approved`, `ticket.rejected`, `ticket.withdrawn`,
    `ticket.approve_refused` (stale proposal, decision 17), `ticket.document_attached`,
    `ticket.document_archived`, `membership.exit` (decision 21, every item with its target, and the counts),
    `ownership.reallotted_on_exit` (one per case), `office.admin_replaced` (decision 14),
    `membership.super_admin_replaced` (decision 13); `membership.added` / `membership.updated` carry `ticket_ref`
    in `after` when a ticket authorised them. One new alert kind, `admin_ticket` (decision 19). No new event
    type: approvals emit `user_updated` per membership changed; the exit emits the existing `allotted` and
    `custody_moved` per case (payload `on_exit: true`).

13. **Exactly one super admin, replaced only from the server's command line (owner review 2026-10-07).** A
    partial unique index `ix_user_memberships_one_super_admin` (role) WHERE role = 'super_admin' AND is_active
    allows one active `super_admin` membership in the database. The API never creates, changes, ends or
    reactivates a `super_admin` membership and never disables the super admin's login (403
    `super_admin_cli_only`). Bootstrap: `aslms seed` creates the `.env` super admin only on a system with none
    (decision 11). Replacement: `aslms users replace-super-admin --email <e> [--name] [--designation]` (password
    prompted, never echoed or logged), in one transaction: lock the current super admin membership; end it
    (`valid_to`, reason `replaced`), disable that login and revoke its refresh tokens (the login holds no other
    membership, decision 4); create the new login, or take an existing login that has **no** active membership
    (a login with memberships → refused: the super admin holds nothing else); insert the new `super_admin`
    primary membership at the State root; audit `membership.super_admin_replaced` (before/after: user ids and
    e-mails). The index rejects any racing second insert; the end-then-insert order inside one transaction
    means the system is never without one or with two. `create-super-admin` refuses when one exists ("use
    replace-super-admin"). Alternative: replacement through the API with a second confirmation — rejected by
    the owner ("never through the API"). Alternative: keep the old login active with no membership — rejected:
    a dormant former super admin login is an unnecessary risk; the CLI can re-enable it if ever needed.

14. **Exactly one department admin per department, changed only by the super admin as a swap (owner review
    2026-10-07).** A `dept_admin` membership sits at the Department-tier office itself (`office_id =
    department_id`; service rule, 400 `admin_at_department` otherwise — directorates are run by the department's
    admin), and a partial unique index `ix_user_memberships_one_dept_admin` (department_id) WHERE role =
    'dept_admin' AND is_active allows one per department. No department admin ever creates, changes, ends or
    reactivates a `dept_admin` membership (as today: not delegable). The super admin:
    - sets the first admin through `POST /admin/offices/{code}/admins` (as built; 409 `admin_exists` when one
      is active) or by adding / changing a membership (409 `one_dept_admin` when one is active);
    - replaces the admin only through **`PUT /admin/offices/{code}/admin`** — one transaction: lock the current
      admin membership; apply the outgoing choice first — `dept_officer` (default; the person stays in the
      department, keeping custody and allotments) or `end` (the per-item exit of decision 21, done by the super admin with
      an assignment for every item to existing memberships of the department; to give items to a brand-new
      incoming admin, the super admin first swaps with `dept_officer` and then exits the old admin);
      then make the incoming admin: an existing membership of the department changed to
      `dept_admin` (its office must be the department office — else it is ended and re-added there in the same
      step), or a new membership for an existing login found by exact e-mail, or a new login with its first
      membership (the `add_department_admin` fields); audit `office.admin_replaced` (before/after: user ids,
      membership ids, outgoing choice, the exit's items and targets) plus the membership audits; `user_updated` events.
    A department may be left without an admin only by ending the admin with no replacement, which only the
    super admin can do (decision 8). Alternative: allow several admins and let the super admin decide —
    rejected by the owner. Alternative: let the outgoing admin hand over — rejected: the owner said only the
    super admin changes department admins.

15. **Head changes: exactly one head per department; a department admin requests and the super admin
    approves; the super admin changes it directly (owner review 2026-10-07; revised with the owner's answers:
    one head, always a head, no approval for the super admin).** A partial unique index
    `ix_user_memberships_one_dept_head` (department_id) WHERE role = 'dept_head' AND is_active allows at most one
    active head per department, at the department office (400 `head_at_department` elsewhere); the services
    answer 409 `one_dept_head` and the index refuses a racing insert. Every head change goes through **`POST
    /admin/tickets/head-change`** (multipart: the request plus optional documents, decision 20); the membership
    endpoints refuse to make a head (409 `use_head_change`) or to remove one (409 `head_required`, decision 24).
    Operations (the ticket's `payload.operation`):
    - **`set`** — only for a department with no head (a department created before this change, decision 24;
      409 `head_exists` otherwise): the incoming head is an existing membership of the department of a
      delegable type (changed to `dept_head`; an ended membership of the department is reactivated as head) or a
      new membership at the department office for a person found by exact e-mail who has no active membership
      there;
    - **`replace`** — the department has a head (409 `no_head` otherwise): the incoming head as for `set`,
      plus the outgoing head's fate (decision 16), applied together;
    - ~~**`end`**~~ — removed (owner review 2026-10-07): a department always has a head, so a head leaves only by
      `replace`.
    **Department admin:** the request comes from a membership holding **`users.propose_head`** (decision 18) in
    that department and opens a ticket. Rules checked at request and again at approval: the requester never
    touches a `dept_admin` or `super_admin` membership (403 `not_delegable` — so a department admin cannot
    request themselves); the logins involved are active (409 `login_inactive`); one open `head_change` ticket per
    department (409 `ticket_open`, partial unique index). **Until approval nothing changes**: the incoming
    person keeps their previous type (or has no membership), the current head stays head.
    **Super admin: no approval, no waiting** (decision 4's general rule). The super admin's request through the
    same endpoint is applied at once, in its own transaction. It is also written as a ticket already `approved`
    (`requested_by` = `decided_by` = the super admin, `decided_at` = now) for one reason only: the audit trail
    and a place where the order stays attached (decision 20) — that record is not an approval step and nothing
    waits on it. The super admin is not limited by `not_delegable` (may make a `dept_admin`'s membership the
    head, subject to decision 14's one-admin rule) nor by an open ticket of the department: a direct change
    while a department admin's ticket is open closes that ticket as `rejected` with the remark "superseded by
    the super admin's change <TKT ref>".
    Either way the outgoing change is applied first and then the incoming one, in one transaction (so the
    one-head index holds at every statement and the department is never left without a head).
    ~~Heads are not limited in number~~ (the flag is withdrawn: the owner set one head per department).
    Alternative: proposals through the membership endpoints with 202 (an earlier revision) — replaced: the
    request must carry its documents (multipart) and names two memberships (incoming and outgoing), which a
    single-membership endpoint expresses badly.

16. **The outgoing head's fate is part of the replacement (owner review 2026-10-07; revised with the owner's
    answers).** A `replace` request states, in `payload.outgoing`, one of:
    - (a) **`retype`** — the outgoing head's membership changes from `dept_head` to `dept_officer` (default) or
      another delegable type (`role_to`; never `dept_admin`). The person stays in the department and keeps their
      allotments and files (their membership is still active and an eligible officer); nothing moves
      automatically; their per-membership overrides stay;
    - (b) **`exit`** — the outgoing head is transferred out through the per-item exit (decision 21): the request
      carries the full `assignments` list, the `items_fingerprint` from the exit preview and the exit `reason`;
      at approval a changed item set refuses with 409 `ticket_stale` (the admin withdraws and requests again
      with a fresh preview; for the super admin's direct change the same check answers 409 `stale_exit`).
    The outgoing change and the incoming change are applied atomically (by the approval, or at once for the
    super admin). The ticket detail shows the approver the outgoing membership's active overrides, its counts of
    files held and allotments and, for `exit`, every item with its target. Alternative: hand the outgoing head's
    cases to the new head automatically — rejected: a move must be a decision (option (b) makes it item by item).

17. **A generic admin ticket mechanism (owner review 2026-10-07).** `admin_tickets` (Data) holds one request
    needing the super admin's decision: `ref_no` `ASLMS/<department>/TKT/<yyyy>/<n>` (`GOA` for a case with no
    department), `kind` (→ `ref_ticket_kind`; `head_change` first), `status` `open` → `approved` | `rejected` |
    `withdrawn` (final; a closed ticket never changes — trigger), the requester (user, acting membership,
    actor snapshot), the target department, person and membership, `payload` (the proposed change, validated by
    the kind's schema), `request_remark` (optional), `decision_remark` (required to reject), `decided_by` /
    `decided_at` (also for a withdrawal), `result` (what approval applied: membership ids, before / after).
    Each kind is a handler in `services/tickets.py::KINDS` with `validate(payload)`, `check(session, ticket)`
    (re-run at approval), `apply(session, actor, ticket)` and `describe(ticket)`; adding a kind later is a
    `ref_ticket_kind` row, a handler and its tests — no table change. Approval locks the ticket and every
    membership it names, re-runs `check` against the current state; if the world has moved (the membership was
    ended or changed, the person got a membership meanwhile, the outgoing head is no longer head, a head was set
    meanwhile, the exit items changed) it refuses
    with 409 `ticket_stale` and the reason, audited as `ticket.approve_refused`, and the ticket stays open for a
    reject. Withdraw: the proposer (same user, while their proposing membership is active) while open. No expiry
    and no job: the panel shows each ticket's age. Alternative: approval rows on `user_memberships` (a pending
    state) — rejected: a pending membership would have to be excluded from every authority read, and later
    kinds are not memberships. Alternative: a free-text request — rejected: approval must apply exactly what was
    proposed.

18. **Who sees and decides tickets (owner review 2026-10-07).** Two new functions (seed): **`users.propose_head`**
    (module `users`; default matrix: `dept_admin` only) — open `head_change` tickets in the departments where
    the acting membership holds it, list and read that department's tickets, attach documents to them while
    open, and withdraw one's own; and **`admin.tickets`** (module `admin`) — the panel over every ticket, held only by the
    super admin: enabled for no type and **reserved** (the matrix editor and the override service refuse it,
    400 `reserved_function`), so the second-level check stays with the one super admin (decision 13). Approve
    and reject also require the caller's membership to be the super admin's. Visibility in SQL
    (`tickets.visible_condition(session, user)`): `admin.tickets` → all; otherwise tickets whose
    `department_id` is the department of an active membership of the caller holding `users.propose_head`.
    Others get 404. The target person does not see the ticket (they see the result on `/me`). Alternative:
    let `dept_head` see their department's tickets — not asked for; the function can be granted by the
    department admin if wanted.

19. **Ticket alerts reuse the alert machinery with a new kind (owner review 2026-10-07).** New `ref_alert_kind`
    **`admin_ticket`** ("Admin ticket", default `normal`). `alerts.case_id` becomes nullable, only for this kind
    (CHECK `ck_alerts_case`: (case_id IS NULL) = (kind = 'admin_ticket')). The ticket service raises the
    alerts directly in its transaction (no event scan: the scan reads case events only):
    - **opened** → one alert addressed to the State root, severity **`normal`** (owner's answer: all tickets
      are equally important; ~~`critical`~~), recipients every active super admin (one, decision 13), key
      `admin_ticket:<ticket id>:opened`, `data` {ticket_id, ticket_ref, kind, department_code}; e-mail follows
      the super admin's own preferences (the daily digest by default, immediate if they choose); the panel's
      counts are the working queue; closed `done` when the ticket is decided or withdrawn;
    - **decided** (approved / rejected) → one alert addressed to the department office, severity `normal`,
      recipient the proposer, key `admin_ticket:<ticket id>:<status>`, body naming the decision and the remark;
      the proposer acknowledges or marks it done as any alert.
    A case-less alert is visible and actionable only to its notified recipients (the State-wide branch does
    not widen it); the in-app list and counts outer-join `cases`; the e-mail names the ticket ref, kind,
    department and the panel link, never the payload. Alternative: no alert, only the panel — rejected: the
    owner asked for a notification both ways. Alternative: reuse `ownership` — rejected: it is case-scoped and
    its recipients and wording are ownership's. (The `critical` owner check of the previous revision is
    settled: `normal`, the kind's default severity in `ref_alert_kind`.)

20. **The supporting document belongs to the request (owner review 2026-10-07; revised with the owner's
    answers).** The government order is uploaded **with** the head-change request (the multipart parts of
    `POST /admin/tickets/head-change`), so the super admin sees it while evaluating. It stays optional (the order
    often comes later): it may be attached while the ticket is **open** (`POST /admin/tickets/{ref}/documents`),
    never after the decision (409 `ticket_closed` for `approved`, `rejected`, `withdrawn`; ~~attach after
    approval~~). Supporting uploads are defined **per ticket kind**: each handler in `KINDS` declares
    `doc_types` — `head_change`: {`government_order`}; a kind with none refuses uploads (409
    `uploads_not_allowed`); later kinds decide their own. Every file is checked and scanned before the ticket
    row is written: one refused file refuses the whole request (nothing stored, the refusal audited as today).
    Stored through the documents service (type check by content, ClamAV scan before storage, `UPLOAD_MAX_BYTES`
    per file, at most 5 files per request, `DOC` number on the uploader's acting membership's office) as:
    - a new `doc_kind` value **`admin`** — a document of an administrative record, never of a case: CHECK
      `ck_documents_admin_file` (kind <> 'admin' OR (case_id IS NULL AND doc_group = 'internal' AND visibility =
      'private_to_office')), and the existing `ck_documents_user_file` extended to `admin` (ref_no, office,
      doc_date, clean scan);
    - a new `ref_doc_type` **`government_order`** ("Government order / notification", group `internal`); case
      uploads refuse it and `upload_types()` leaves it out;
    - group `internal`, so `sourcetrace_status = not_applicable` by the existing CHECK — never sent to
      SourceTrace; text is extracted by the existing job (searchable later in the panel) but the case documents
      search never returns it (`document_case_condition` needs a case);
    - linked by `admin_ticket_documents` (ticket ↔ document) and, on approval, by `membership_documents`
      (membership ↔ document, with the ticket) for every membership the ticket changed (the incoming head's
      and, for `replace`, the outgoing head's), so the order stays on the membership after the ticket is
      history; a super admin's direct change links at once;
    - visible (SQL, `tickets.admin_document_condition`) to `admin.tickets` holders and to callers holding
      `users.propose_head` in the department of a ticket or membership it is linked to — the super admin and
      the department's admin; downloads audited as today (`document.downloaded`); never deleted — while the
      ticket is open, archived by its uploader or the super admin with a reason (`ticket.document_archived`),
      still listed as archived.
    Duplicates: the same file twice on one ticket → 409 `duplicate`. A government order that arrives after the
    decision is not attached to the closed ticket; recording it would be a later ticket kind or item (not asked
    for). Alternative: `documents.case_id` with a placeholder case — rejected (fabricated record). Alternative: a
    `ticket_id` column on `documents` — rejected: one order may authorise several memberships and later kinds;
    link tables keep `documents` generic.

21. **The exit step: the department admin reassigns every item, one by one (owner review 2026-10-07,
    revised the same day: no successor).** Ending a membership (`users.enable_disable`, scope as decision 8; a
    `dept_head` only as the outgoing side of a `replace`, decisions 15–16 and 24; a `dept_admin` through the super admin's swap, decision 14) is
    possible only when every **item** of the leaving membership has a target. Items, computed by
    `memberships.exit_items` (the same function serves the preview and the end call):
    - an **allotment** item per active ownership row of that department whose `officer_user_id` is the leaving
      person (key: ownership row id);
    - a **file** item per custody row whose holder is the leaving membership (before `custody-workflow`'s 0009:
      `holder_user_id` = the person and `holder_office_id` in the department's subtree; after it:
      `holder_membership_id`; key: case id + current leg id). This includes files of other departments' cases
      sent to the leaver: they stay with the leaver's department, as the sender chose it. A case allotted to and
      held by the leaver gives two items, which may go to different officers.
    The admin submits an **assignment for each item**: target = an active membership of an active login in the
    **same department**, not the leaving one, of an officer type (`eligible_officer`); one target per item;
    different items may go to different officers; for a file item, `pending_action` and `due_date` carry over
    unless the assignment changes them (same validation as a send: not `none`, today IST to 365 days ahead),
    with an optional per-item remark. There is **no default and no successor**: the admin decides each case.
    The end call carries the full list and the preview's `items_fingerprint` (SHA-256 of the sorted item keys).
    Under the membership row lock it recomputes the items and refuses, before anything is written, with
    **409 `stale_exit`** (the current items in the body) when the fingerprint differs or an assignment names an
    item that is no longer there; with **409 `unassigned_items`** (listing them) when any allotted case or held
    file has no assignment; with 400 `bad_target` / `duplicate_item` (per item) for a wrong target or a doubled
    item. Then, in one transaction, taking each case row lock in case-id order:
    - **allotment items** — re-allotted to their targets (`ownership.reallot_on_exit`; the officer field only, no
      `allotted` custody leg); event `allotted` (`on_exit: true`), audit `ownership.reallotted_on_exit` per case;
    - **file items** — one leg each, reason **`reassigned_on_exit`**, holder = the item's target membership,
      pending action and due date as carried or changed, remark "Reassigned on the transfer of <name,
      designation> out of <department>: <item remark, else the exit reason>";
    - **drafts** — the leaver's draft notes on those cases become permanent in that move (`custody-workflow`
      decision 13, called by `move_custody` whenever the holder membership changes — nothing extra here);
    - **open alerts** — open or acknowledged alerts on those cases addressed to an office of the department
      for which the leaver was notified: each target of an item on that case is notified
      (`notifications.notify` at the alert's severity); an alert the leaver had acknowledged goes back to
      `open`; the leaver's notification rows stay as the record;
    - the membership is ended (`valid_to`, `end_reason`) and, if primary, decision 22 applies; one
      `membership.exit` audit row lists every item with its target (item kind, case id, target membership id;
      for files the pending action and due date before / after) and the counts (allotments, files, notes
      finalised, alerts).
    **Reassigning ahead:** the admin may move items before the exit with the ordinary actions — allot
    (`cases.allot`) for allotments; recall (`custody.recall`) and send for files — so fewer items remain at
    exit; a membership with no items is ended with an empty list. The person's login and their memberships in
    other departments are untouched; the new department's admin adds their new membership (decision 8). If any
    step fails, nothing changes. Alternative: one successor for everything (the previous revision) — rejected
    by the owner: the admin decides which case goes to which officer. Alternative: refuse the exit until every
    item was moved by hand — rejected: once each item has a target, the admin finishes in one step.

22. **Exit preview, the primary flag and the login after an exit (owner review 2026-10-07, revised: no
    successor).** `GET /users/{id}/memberships/{mid}/exit-preview` (same function and scope as ending) returns
    every item — allotments (case, ownership role) and held files (case, pending action, due date, since, leg
    seq no) — with its key, the counts, the drafts count (after `custody-workflow`), the open alerts per case,
    the `items_fingerprint`, and the eligible target memberships of the department (name, designation, office,
    type) for the picker. Cases not otherwise visible to the admin (files of other departments' cases) are
    listed with searchable facts only (case number, CNR, court, owning department), as `custody/sent` does. The
    preview writes nothing; the end call recomputes under the locks (decision 21). When the ended membership is
    the primary one, the oldest other active membership becomes primary (mirror rewritten,
    `membership.primary_changed`); when it was the last, the login stays active with no membership — it signs
    in, sees nothing and holds no function (`/me` shows an empty list) until a department admin adds a
    membership, which becomes primary. Alternative: disable the login on its last exit — rejected: a transfer
    between departments would lock the officer out while the receiving admin acts.

23. **Already-built code and tests that change for the admin limits (owner review 2026-10-07).**
    - `services/offices.py::add_department_admin` and `POST /admin/offices/{code}/admins`: 409 `admin_exists`
      when the department has an active admin; `GET /admin/offices/{code}/admins` returns zero or one.
    - `services/access_seed.py`, CLI `create-super-admin` / `_actor`: decision 13.
    - The migration's guard (Data) stops if the existing data already has two active super admins or two
      active `dept_admin` users in one department, listing them; nothing is fixed silently.
    - Tests: `tests/db/test_offices.py` creates a second super admin (`root2@example.org`, deactivation test) —
      rewritten with another State-wide type; `test_add_department_admin` adds a second EDU admin beside the
      world's — moved to a department without one, plus a new 409 case; `tests/db/test_api_offices.py` FIN
      admin — the repeat call now expects 409 `admin_exists` (before the duplicate e-mail check);
      `tests/db/test_seed_and_refno.py` and every fixture that seeds the `.env` super admin beside a world super
      admin — the seed now skips; the developer greps `role=Role.SUPER_ADMIN` / `Role.DEPT_ADMIN` across
      `tests/` and fixes any other second admin. `world.py` (one admin per department) stays valid.
    - (owner review 2026-10-07, decision 24) `services/offices.py::create_office` and `reactivate_office`,
      `POST /admin/offices`, `POST /admin/offices/{code}/reactivate`, CLI `aslms offices create` (new options
      `--head-email`, `--head-name`, `--head-designation`, password prompted for a new login): a Department-tier
      office needs a head; `deactivate_office` ends the head membership as described in decision 24;
      `aslms offices list --missing-head`. Tests that create Department-tier offices through the service or the
      API (`tests/db/test_offices.py`, `tests/db/test_api_offices.py`, `tests/db/test_api_access.py`) pass a
      head; `world.py` builds offices directly (no service), so its departments start without a head —
      `world.py` gives each department a head membership so the data-health count is 0 in tests, and one test
      builds a headless department on purpose for the count and for `set`.

24. **A department always has a head (owner review 2026-10-07).** Every active Department-tier office
    (`department`, `central`, `advocate_general` kinds) has exactly one active `dept_head` membership;
    directorates and units have none (decision 15 keeps heads at the department office).
    - **Creation:** the super admin's department creation (`POST /admin/offices` with a Department-tier kind;
      `aslms offices create`) must name the head — an existing login by exact e-mail (with designation) or a new
      login (e-mail, name, designation, mobile?, password; `must_confirm_profile`) — and the office and the head
      membership are created in one transaction (400 `head_required` when missing; a login that already has an
      active membership elsewhere is fine — it gains this one). Audit `office.created` gains the head;
      `membership.added` and the opened-and-approved `head_change` ticket record it like any direct super admin
      change (decision 15), so an order can be attached at creation. Reactivating a Department-tier office
      names a head the same way. Directorates and units: unchanged, no head.
    - **No removal by another path:** ending, retyping or exiting the current head's membership through the
      membership endpoints, the compatibility type endpoint or the CLI is refused (409 `head_required`), also for
      the super admin; disabling the head's login likewise (decision 8). A head leaves only by `replace`
      (decisions 15–16). The super admin's department-admin swap (decision 14) cannot touch a head.
    - **Deactivating a department** keeps its rule (no active members left, offices-admin): the head's
      membership is not counted as blocking; when it is the last active membership of the department's subtree
      and holds no items (decision 21), the deactivation ends it in the same transaction (`end_reason`
      "department deactivated"), the only way a department loses its head; if it holds items → the existing
      409 `office_in_use` with the counts.
    - **Departments created before this change** (dev data only; the database starts empty in production):
      migration 0008 does not invent heads (no fabricated data); it prints the departments without an active
      head (`NOTICE`) and does not stop. They are fixed with the head-change `set` (decision 15) by the super
      admin directly or by the department admin with approval, or from the CLI (`aslms users memberships add
      --type dept_head`, which goes through the same service).
    - **Data health:** `GET /admin/tickets/counts` returns `departments_without_head` to `admin.tickets` holders
      and `GET /admin/offices?missing_head=true` (`offices.manage`) lists them; the count is expected to be 0
      once the dev data is fixed, and the integrator records it in the cycle report.
    The rule is enforced by the services (a "one row exists" rule across rows cannot be a CHECK); the partial
    unique index of decision 15 enforces "at most one". Alternative: allow a headless department for a while
    after a head leaves — rejected by the owner ("a department must always have a head").


## Data
Migration **0008_memberships** (new file; 0001–0007 are applied and untouched; the feature branch's
`0008_workflow` was never applied to `main` and is superseded — `custody-workflow` becomes 0009).

New table, for `schema.md` "Group 1 — organisation and access":

> | `user_memberships` (master, versioned) | id (uuid v7 PK), user_id (→ users RESTRICT), office_id (→ offices RESTRICT), department_id (→ offices RESTRICT; the Department-tier ancestor of office_id, NULL for a State-tier office; derived at insert, immutable), role (→ `ref_role`), designation (text as shown, ≤ 200), designation_id (→ designations RESTRICT, NULL allowed), is_primary boolean NOT NULL default false, is_active, deactivated_at, valid_from, valid_to, **end_reason (text ≤ 500, NULL; set when ended)**, created_at, updated_at, created_by, updated_by (→ users SET NULL) | One row per office a person serves in, with that office's designation and user type. Partial unique `ix_user_memberships_one_per_department` (user_id, department_id) NULLS NOT DISTINCT WHERE is_active; partial unique `ix_user_memberships_primary` (user_id) WHERE is_primary AND is_active; **partial unique `ix_user_memberships_one_super_admin` (role) WHERE role = 'super_admin' AND is_active; partial unique `ix_user_memberships_one_dept_admin` (department_id) WHERE role = 'dept_admin' AND is_active; partial unique `ix_user_memberships_one_dept_head` (department_id) WHERE role = 'dept_head' AND is_active** (owner review 2026-10-07); index `ix_user_memberships_office_active` (office_id) WHERE is_active. CHECKs `ck_user_memberships_active` (is_active = (deactivated_at IS NULL)), `ck_user_memberships_primary_active` (NOT is_primary OR is_active). A `super_admin` membership is the login's only membership and is written only by the CLI; `dept_admin` and `dept_head` sit at the department office (service). A login may have no active membership after an exit. Ended, never deleted. Functions per membership = type matrix + the membership's overrides; visibility = the union over active memberships (design `user-memberships`). |

New tables (owner review 2026-10-07), for `schema.md` "Group 1 — organisation and access":

> | `admin_tickets` (transaction) | id (uuid v7 PK), ref_no (unique, `ASLMS/<department code>/TKT/<yyyy>/<n>`), kind (→ `ref_ticket_kind`), status (`ticket_status`: `open` / `approved` / `rejected` / `withdrawn`), department_id (→ offices RESTRICT, NULL for a kind with no department), target_user_id (→ users RESTRICT, NULL), target_membership_id (→ user_memberships RESTRICT, NULL; for `add` filled on approval), requested_by_user_id (→ users RESTRICT), requested_by_membership_id (→ user_memberships RESTRICT), actor snapshot (actor_user_id, actor_name, actor_designation, actor_office_code — the requesting membership), payload jsonb NOT NULL (the proposed change, per kind), request_remark (≤ 2,000, NULL), result jsonb NULL (what approval applied), decision_remark (≤ 2,000, NULL), decided_by_user_id (→ users SET NULL), decided_by_name, decided_by_designation, decided_by_office_code (snapshot), decided_at, created_at, updated_at | CHECKs `ck_admin_tickets_decided` ((status = 'open') = (decided_at IS NULL)), `ck_admin_tickets_reject_remark` (status <> 'rejected' OR decision_remark IS NOT NULL), `ck_admin_tickets_head_change` (kind <> 'head_change' OR department_id IS NOT NULL). Partial unique `ix_admin_tickets_one_open_head_change` (department_id) WHERE kind = 'head_change' AND status = 'open'; indexes `ix_admin_tickets_status_created` (status, created_at), `ix_admin_tickets_department_status` (department_id, status). Trigger `admin_tickets_closed_frozen` refuses UPDATE of a row whose old status is not `open`. Never deleted. Written only by `services/tickets.py` (design `user-memberships` decisions 15–19). |
> | `admin_ticket_documents` (transaction, append-only) | id (uuid v7 PK), ticket_id (→ admin_tickets RESTRICT), document_id (→ documents RESTRICT), actor snapshot, created_at | Unique (ticket_id, document_id). The document is kind `admin`. No UPDATE or DELETE for `aslms_app`. |
> | `membership_documents` (transaction, append-only) | id (uuid v7 PK), membership_id (→ user_memberships RESTRICT), document_id (→ documents RESTRICT), ticket_id (→ admin_tickets RESTRICT, NULL), actor snapshot, created_at | Unique (membership_id, document_id). The order that authorised the membership's change, findable after the ticket. No UPDATE or DELETE for `aslms_app`. |

Group 0 row added (owner review 2026-10-07):

> | `ref_ticket_kind` | code (PK), label, description, sort_order, is_active | Seeded from `TicketKind`: `head_change` ("Head of department change"). |

Changed rows of `schema.md` group 1:

> | `users` (master) | … (unchanged columns) | **A login.** `office_id`, `role`, `designation`, `designation_id` mirror the primary membership (written only by the membership service, never read for authorisation; kept at the last values when the login has no active membership). Authority lives in `user_memberships`. |
> | `user_permissions` (master) | user_id, **membership_id (→ user_memberships RESTRICT, NOT NULL)**, permission, effect, granted_by_user_id, reason, is_active, deactivated_at, valid_from, valid_to, actor snapshot; **unique (membership_id, permission)** | Overrides per membership; `user_id` equals the membership's user. `admin.tickets` is never overridden. |

Changed rows of other groups (owner review 2026-10-07):

> | `documents` | … `kind` (`causelist` / `order` / `upload` / `attachment` / **`admin`**) … | CHECK **`ck_documents_admin_file`** (kind <> 'admin' OR (case_id IS NULL AND doc_group = 'internal' AND visibility = 'private_to_office')); `ck_documents_user_file` covers `upload`, `attachment`, `admin`. An `admin` document belongs to an admin ticket or membership (link tables), never to a case. |
> | `alerts` | case_id (→ cases RESTRICT, **NULL only for `admin_ticket`**), kind (… + **`admin_ticket`**) … | CHECK **`ck_alerts_case`** ((case_id IS NULL) = (kind = 'admin_ticket')). A case-less alert is visible only to its notified recipients. |

Conventions paragraph: "Case visibility is one rule … evaluated per active membership and OR-ed; functions are
per membership (type matrix + the membership's overrides); the union is only a gate." (owner review 2026-10-07)
"Code sets": nine `ref_*` tables after 0008 (`ref_ticket_kind` added; eight again after `custody-workflow` drops
`ref_request_kind`); record types gain `TKT` (admin tickets, allocated on the target department's code).

Reference codes (seed, owner review 2026-10-07): `ref_record_type` + `TKT`; `ref_ticket_kind` + `head_change`;
`ref_doc_type` + `government_order` (group `internal`); `ref_alert_kind` + `admin_ticket` (default `normal`);
`ref_permission` + `users.propose_head` (module `users`), `admin.tickets` (module `admin`) — 45 → 47 functions;
`role_permissions`: `users.propose_head` enabled for `dept_admin`, `admin.tickets` for no type. Enums:
`RecordType.TKT`, `TicketKind.HEAD_CHANGE`, `DocType.GOVERNMENT_ORDER`, `AlertKind.ADMIN_TICKET`,
`DocKind.ADMIN`, `TicketStatus`, two `Permission` members; `CustodyReason`/`REASONS` + `reassigned_on_exit`
(the column is `varchar(60)`; `custody-workflow`'s CHECK lists it).

Migration 0008 contents:
1. **Guard** (owner review 2026-10-07): stop, listing the rows, if more than one active user has role
   `super_admin`, or more than one active user of one department has role `dept_admin`, or (owner's answer)
   role `dept_head`.
2. Create `user_memberships` with the indexes and CHECKs, grants (SELECT/INSERT/UPDATE for `aslms_app`),
   `COMMENT ON TABLE … 'class=master'`, the `set_updated_at` trigger; back-fill one primary membership per
   existing user (`office_id`, `role`, `designation`, `designation_id`, `is_active` from `users`;
   `department_id` from the office path's second segment when that office is Department-tier).
3. Add `user_permissions.membership_id` nullable, back-fill to the primary membership, set NOT NULL, add the FK
   (RESTRICT), drop `uq_user_permissions_user_id` (the built name, checked against 0003 by the developer), add
   `uq_user_permissions_membership_id`.
4. (owner review 2026-10-07) Create `ref_ticket_kind` (`class=reference`), enum `ticket_status`,
   `admin_tickets` (CHECKs, indexes, the freeze trigger, `set_updated_at`), `admin_ticket_documents`,
   `membership_documents` (`class=transaction`; SELECT/INSERT for `aslms_app` on the two link tables,
   SELECT/INSERT/UPDATE on `admin_tickets`).
5. (owner review 2026-10-07) `ALTER TYPE doc_kind ADD VALUE 'admin'` in an autocommit block, then drop and
   re-add `ck_documents_user_file` with `admin`, add `ck_documents_admin_file`.
6. (owner review 2026-10-07) `alerts.case_id` DROP NOT NULL; add `ck_alerts_case` (the table holds no
   case-less row, so it validates).
7. (owner review 2026-10-07, decision 24) `NOTICE` listing every active Department-tier office without an
   active `dept_head` after the back-fill; nothing is created and the migration does not stop.
Downgrade: stops while any login has more than one membership, any non-primary membership exists, any
`admin_tickets` row, `kind = 'admin'` document or case-less alert exists; otherwise drops exactly these,
restores `alerts.case_id` NOT NULL and recreates `doc_kind` without `admin` (rename, create, cast, drop).

## Services
- `services/memberships.py` (new): `add(session, actor, member, user, *, office, role, designation,
  designation_id)`, `update(..., designation?, designation_id?, role?)`, `end(..., reason, assignments, items_fingerprint)`,
  `reactivate`, `make_primary`, `lookup(session, email)`, `membership_out`; each checks decision 8 with the
  acting member, writes the mirror (decision 3), audit (decision 12) and the `user_updated` event. (owner
  review 2026-10-07) `add` / `update` / `end` / `reactivate` refuse to make a head (409 `use_head_change`) or remove one (409 `head_required`,
  decision 15) and offer `apply_head_change(..., via_ticket)` to the ticket handler; enforce decisions 13–15
  (409 `super_admin_single`, `one_dept_admin`, `one_dept_head`, 403 `super_admin_cli_only`, `not_delegable`); `exit_items`, `exit_preview(session,
  member, membership)` and the per-item exit inside `end` (decisions 21–22, membership lock then case locks in id
  order); `replace_department_admin(session, actor, member, department, *, incoming, outgoing, reason,
  assignments?, items_fingerprint?)` (decision 14); `replace_super_admin(session, *, email, name, designation, password)` (CLI only,
  decision 13). Unique violations on the new indexes map to 409 with the same codes.
- `services/tickets.py` (new, owner review 2026-10-07): `KINDS` registry (decision 17) with `HeadChange`
  (`validate` → a pydantic `HeadChangePayload`: operation `set` / `replace` (`end` removed), department_code,
  incoming {membership_id | email, designation, designation_id; role_from}, outgoing {membership_id, mode
  `retype` (role_to) | `exit` (assignments, items_fingerprint, reason)}; `doc_types = {government_order}`;
  `check`; `apply` through `memberships` with `via_ticket`, outgoing first; `describe`);
  `request_head_change(session, actor, member, payload, request_remark, files)` (files checked and scanned
  first; allocates `TKT`; for a department admin raises the "opened" alert and audits `ticket.opened`; for the
  super admin applies at once, records the ticket approved and closes a superseded open ticket, decision 15);
  `departments_without_head(session)` (decision 24); `approve(session,
  actor, member, ticket, remark?)`; `reject(..., remark)`; `withdraw(session, actor, member, ticket, remark?)`;
  `list_tickets(session, user, *, status='open', kind, department, mine, limit, offset)` (oldest first),
  `counts(session, user)` (open total, open by kind, by department, oldest open `created_at`), `get`,
  `ticket_out` (payload described with names, the outgoing membership's overrides and held counts for the
  super admin, documents); `visible_condition`, `admin_document_condition` (decisions 18, 20);
  `attach_document(session, actor, member, ticket, *, data, filename, doc_type, doc_date, description,
  scanner, store, max_bytes)` (documents service, kind `admin`; open tickets only;
  the kind's `doc_types`; links per decision 20); `archive_document` (open tickets only), `open_document` (download, audited). Every step writes its audit row with the actor
  snapshot of the acting membership; decisions close the "opened" alert and raise the "decided" one.
- `services/alerts.py`, `notifications.py` (owner review 2026-10-07): `raise_alert` accepts `case=None` for
  `admin_ticket`; `notification_visible_condition` gains the case-less branch (notified recipient only);
  `list_for_user`, `counts_for_user`, `detail_item`, `_may_act_on`, the single-alert e-mail and the digest
  outer-join `cases`.
- `services/documents.py` (owner review 2026-10-07): kind `admin` in the upload path (decision 11); the
  allowed types come from the ticket kind; case upload refuses `government_order`.
- `services/ownership.py` (owner review 2026-10-07): `reallot_on_exit`; `services/custody.py`: reason
  `reassigned_on_exit`.
- `services/access.py`, `visibility.py`, `ownership.py`, `inbox.py`, `recipients.py`, `documents.py`,
  `case_detail.py`, `case_search.py`, `calendar.py`, `notifications.py`, `matching_rules.py`, `offices.py`,
  `access_seed.py`, `users.py`: decision 11 (and 23).
- `api/deps.py`: decision 10; a helper `member_for(request, session, user, *, department=None, office=None,
  case=None, permission)` that routers call to resolve decision 6 and map failures to 403 / 400.
- CLI (owner review 2026-10-07): `aslms users replace-super-admin`; `create-super-admin` refuses when one
  exists; `aslms users memberships end --assignments <json file>` runs the per-item exit.

## API
Existing endpoints keep their paths; the changes:

| Method and path | Function | Request | Response | Rule |
|---|---|---|---|---|
| `GET /me` | signed in | — | `{user, memberships: [{id, office: {code, name, kind}, department_code, designation, role, is_primary, functions: [...]}], functions: [...] (union)}` | The caller's own. Empty `memberships` for a login after its last exit (decision 22). |
| `POST /auth/login`, `/auth/refresh` | — | unchanged | `user` gains `memberships` (as above, without functions) | — |
| `GET /users` | `users.view` | unchanged filters + `office?` | each user with `memberships` | Logins with an active membership in the actor's scope (decision 8). |
| `GET /users/lookup` | `users.create` | `email` (exact) | `{id, full_name, memberships: [{office_code, designation, role}]}` or 404 | For adding a membership to a person outside the actor's scope. |
| `POST /users/{id}/memberships` | `users.create` | `{office, role, designation?, designation_id?}` | membership 201 | Decision 8; 409 `one_per_department`, `super_admin_single`, `one_dept_admin`, (owner review 2026-10-07) `use_head_change` for role `dept_head`; 403 out of scope / non-delegable type / `super_admin_cli_only`. |
| `PATCH /users/{id}/memberships/{mid}` | `users.edit` (designation) / `users.set_type` (role) | `{designation?, designation_id?, role?}` | membership | Scope over that membership's office; decision 14; (owner review 2026-10-07) 409 `use_head_change` for a type change to `dept_head`, 409 `head_required` for a type change of the current head (designation edits of a head stay here). |
| `GET /users/{id}/memberships/{mid}/exit-preview` | `users.enable_disable` | — | `{items: [{key, kind: allotment \| file, case: {ref_no, case_no, cnr, court, owning_department, visible}, ownership_role?, pending_action?, due_date?, since?, leg_seq_no?, open_alerts}], counts: {allotments, files, drafts, open_alerts}, items_fingerprint, targets: [{membership, name, designation, office_code, role}], primary_after: membership \| null}` | (owner review 2026-10-07, revised: no successor) Decision 22; scope as ending; writes nothing. |
| `POST /users/{id}/memberships/{mid}/end` | `users.enable_disable` | `{reason (3–500), items_fingerprint, assignments: [{key, to_membership, pending_action?, due_date?, remark? (≤ 2,000)}]}` (empty list when nothing is held) | `{membership, reassigned: [{key, kind, case_ref, to_membership}], counts: {allotments, files, notes_finalised, alerts}}` | (owner review 2026-10-07, revised: no successor) Decision 21; 409 `unassigned_items` (listing them), `stale_exit` (current items); 400 `bad_target`, `duplicate_item`; 403 `dept_admin` / `super_admin` memberships; 409 `head_required` for the current head's membership, also for the super admin (owner review 2026-10-07, decision 24). ~~409 `holds_custody`, `has_allotments`, `primary_membership`.~~ |
| `POST /users/{id}/memberships/{mid}/reactivate` | `users.enable_disable` | — | membership | 409 `one_per_department` when another active one exists in that department; `one_dept_admin`; `use_head_change` for a `dept_head` membership. |
| `PUT /users/{id}/primary-membership` | `users.edit` | `{membership}` | user | Decision 8. |
| `GET /users/{id}/memberships/{mid}/permissions` | `users.view` | — | `{type_functions, overrides, effective}` | Scope over the membership. |
| `PUT /users/{id}/memberships/{mid}/permissions/{permission}` | `users.grant` | `{effect: grant|deny|null, reason?}` | as above | Decision 8 (grant only what the acting membership holds); 400 `reserved_function` for `admin.tickets`. |
| `GET /users/{id}/memberships/{mid}/documents` | `users.propose_head` or `admin.tickets` | — | `[{ref_no, doc_type, doc_date, description, ticket_ref, archived, attached_by, attached_at}]` | (owner review 2026-10-07) Decision 20 visibility; 404 otherwise. |
| `PUT /users/{id}/type`, `GET/PUT /users/{id}/permissions…` | as today | unchanged | unchanged | Kept for compatibility: act on the **primary** membership (same limits; `use_head_change`, `head_required`). |
| `PATCH /users/{id}`, `POST /users/{id}/enable|disable`, `POST /users/{id}/password` | as today | unchanged | unchanged | Scope over the **primary** membership's office (login-level); super admin only for a login with no membership; disabling the super admin → 403 `super_admin_cli_only`; (owner review 2026-10-07) disabling a head's login → 409 `head_required`. |
| `POST /admin/offices/{code}/admins` | `users.create` (super admin) | as built | user 201 | (owner review 2026-10-07) 409 `admin_exists` when the department has an active admin. |
| `PUT /admin/offices/{code}/admin` | `users.create` + super admin membership | `{incoming: {membership} \| {user, designation?, designation_id?} \| {email, password, full_name, designation?, designation_id?, mobile?}, outgoing: "dept_officer" \| "end", reason (3–500), items_fingerprint? and assignments? (required with `outgoing: "end"`, as the end call)}` | `{admin, outgoing: {membership, reassigned?}}` | (owner review 2026-10-07) Decision 14; 403 for anyone else; with `end`: 409 `unassigned_items`, `stale_exit` as the end call (targets are existing memberships). |
| `POST /admin/tickets/head-change` | `users.propose_head` (in the department) or the super admin | multipart: `request` (JSON: `{department, operation: set \| replace, incoming?: {membership} \| {email, designation?, designation_id?}, outgoing?: {mode: retype, role_to?} \| {mode: exit, reason, items_fingerprint, assignments}, request_remark?}`), `files[]` optional (≤ 5; each with `doc_type` = `government_order`, `doc_date?`, `description?`) | ticket 202 (department admin) / ticket 201 already `approved` with the applied result (super admin: applied at once, no approval) | (owner review 2026-10-07) Decisions 15, 16, 20, 24; 409 `head_exists`, `no_head`, `one_dept_head`, `ticket_open`, `login_inactive`, `unassigned_items`, `stale_exit`; 403 `not_delegable`, out of scope; 413 / 415 / 422 as uploads (whole request refused). |
| `GET /admin/tickets` | `admin.tickets` or `users.propose_head` (`require_any`) | `status?` (default `open`; `all`), `kind?`, `department?`, `mine?`, `limit`, `offset` | `{items: [{ref_no, kind, status, department_code, target: {user_name, designation, role_from, role_to}, requested_by: {name, designation, office_code}, created_at, age_days, documents_count, decided_at?}], total, counts: {open, open_by_kind, oldest_open_at}}` | (owner review 2026-10-07) Oldest first; decision 18 visibility. |
| `GET /admin/tickets/counts` | `admin.tickets` or `users.propose_head` | — | `{open, open_by_kind: {...}, open_by_department: {...}, oldest_open_at, departments_without_head?}` | For the dashboard panel; same visibility; `departments_without_head` only for `admin.tickets` holders (decision 24). |
| `POST /admin/offices` | `offices.manage` (as built) | as built + `head` (required for a Department-tier kind): `{email, designation?, designation_id?}` for an existing login or `{email, full_name, designation?, designation_id?, mobile?, password}` for a new one, `documents?` none (attach on the recorded ticket) | office detail with `head` 201 | (owner review 2026-10-07) Decision 24; 400 `head_required`; office and head membership in one transaction. |
| `POST /admin/offices/{code}/reactivate` | as built | + `head` for a Department-tier office | office detail | (owner review 2026-10-07) Decision 24. |
| `POST /admin/offices/{code}/deactivate` | as built | as built | office detail | (owner review 2026-10-07) Ends the head membership in the same transaction when it is the last and holds no items (decision 24). |
| `GET /admin/offices` | as built | + `missing_head=true` | as built | (owner review 2026-10-07) Departments without an active head (decision 24). |
| `GET /admin/tickets/{ref}` | as list | — | ticket detail: payload described, request and decision remarks, result, documents, for the super admin the outgoing membership's overrides and held counts, `can_approve`, `can_withdraw`, `can_attach` | 404 when not visible. |
| `POST /admin/tickets/{ref}/approve` | `admin.tickets` + super admin membership | `{remark?}` (≤ 2,000) | ticket | 409 `ticket_closed`, `ticket_stale` (with reason). |
| `POST /admin/tickets/{ref}/reject` | `admin.tickets` + super admin membership | `{remark}` (3–2,000) | ticket | 409 `ticket_closed`. |
| `POST /admin/tickets/{ref}/withdraw` | `users.propose_head` | `{remark?}` | ticket | The proposer only; 409 `ticket_closed`; 403 otherwise. |
| `POST /admin/tickets/{ref}/documents` | `users.propose_head` (in the ticket's department) or `admin.tickets` | multipart `file`, `doc_type` (from the kind's `doc_types`; `government_order` for `head_change`), `doc_date?`, `description?` | document 201 | (owner review 2026-10-07) Decision 20; open tickets only — 409 `ticket_closed` after any decision; 409 `uploads_not_allowed` for a kind without uploads, `duplicate`; 413 / 415 / 422 as uploads (`too_large`, `type_not_allowed`, `infected`, `scanner_unavailable`). |
| `GET /admin/tickets/{ref}/documents/{doc}/file` | as attach | `disposition?` | the file | Audited download. |
| `POST /admin/tickets/{ref}/documents/{doc}/archive` | the uploader or the super admin | `{reason}` | document | Open tickets only (409 `ticket_closed`); never deleted. |
| `GET /inbox/counts` | as today | `office?` | **`{departments: [{office_code, …counts}]}`** | Shape change: one block per department the caller works in (flagged; no portal consumes it yet). |
| Ownership and inbox endpoints with `office_code` / `office` | unchanged | the parameter is honoured for any caller with a membership in that department | unchanged | Decision 6; 400 `office_required` with candidates when ambiguous. |
| `GET /alerts`, `/alerts/counts`, `/alerts/{ref}` and actions | as today | unchanged | items may have `case: null` and `ticket_ref` (kind `admin_ticket`) | (owner review 2026-10-07) Decision 19. |

## Jobs
None new. (owner review 2026-10-07) Text of `admin` documents is extracted by the existing
`aslms.extract_document_text` after commit; ticket alerts are raised in the ticket transaction and their e-mails
go out through the existing sender job.

## Tests
Unit (`tests/unit/`):
- `test_no_authority_reads_of_user_office.py` (decision 11's scan).
- `test_membership_rules.py`: department derivation from a path; acting-membership preference order for case
  writes; union gate vs per-membership check.
- (owner review 2026-10-07) `test_ticket_kinds.py`: every `TicketKind` member has a handler and a
  `ref_ticket_kind` seed row; `HeadChangePayload` refuses unknown operations (including the removed `end`), `set`
  with an outgoing part, `replace` without one, `dept_admin` / `super_admin` as `role_to`, `exit` without a complete
  assignment list; `RESERVED_FUNCTIONS` contains `admin.tickets`; every kind's `doc_types` are group `internal`;
  `head_change.doc_types == {government_order}`.

Database (`tests/db/`; `world.py` gains a two-department person: `dept_admin` in EDU, `dept_officer` in HEALTH):
- `test_memberships.py`: migration back-fill gives every user exactly one primary membership equal to the mirror
  and moves overrides; add a membership in own department (allowed) and in another department (403); one active
  membership per department (409, and the index refuses a racing insert); `super_admin` cannot get a second
  membership; make-primary rewrites the mirror; ended membership has no functions; lookup by exact e-mail only;
  audit rows for each change.
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
- (owner review 2026-10-07) `test_admin_limits.py`: a second active `super_admin` membership refused by the
  service (409) and by the index (direct insert); the API cannot create, change, end or disable the super
  admin (403 `super_admin_cli_only`); `replace_super_admin` ends the old, disables its login, revokes tokens,
  creates the new — exactly one active afterwards; refused for a login holding memberships; seed with an
  existing super admin of another e-mail creates nothing; a second `dept_admin` in a department refused (409
  `one_dept_admin`, `admin_exists` on the first-admin endpoint, index on a racing insert); `dept_admin` at a
  directorate refused; the swap with `outgoing=dept_officer` (old admin keeps custody and allotments) and with
  `outgoing=end` (per-item exit to existing memberships; refused while any item is unassigned) leaves exactly one admin, audited `office.admin_replaced`; a
  department admin cannot call the swap (403); the migration guard stops on two seeded super admins.
- (owner review 2026-10-07; revised with the owner's answers) `test_head_change_tickets.py`: the EDU admin
  requests `set` for a person from HEALTH by e-mail with a government order → 202 ticket with one document, no
  membership yet, the person's `/me` unchanged; the super admin approves → the membership exists as
  `dept_head`, `target_membership_id` and `result` set, `membership.added` carries `ticket_ref`, the order is
  linked to the membership; `set` with an existing EDU officer membership; `set` when a head exists → 409
  `head_exists`; a second active head refused by the service (409 `one_dept_head`) and by the index (racing
  insert); `replace` with `retype` → in one transaction the old head becomes `dept_officer` (keeping custody and
  allotments) and the new head is set; `replace` with `exit` → the old head's items go to their targets and the
  membership ends, the new head is set; `exit` with items changed since the preview → 409 `ticket_stale` at
  approval, ticket still open; `replace` with no head → 409 `no_head`; an `end` operation → 400; the
  membership endpoints refuse to make a head (409 `use_head_change`) and to end, retype or exit the current head
  (409 `head_required`), also for the super admin; disabling the head's login → 409 `head_required`; the super
  admin's direct `replace` is applied at once with no approval step (an `approved` ticket recorded, no
  "opened" alert) and closes an open department-admin ticket of the same department as `rejected`
  (superseded); reject needs a remark and changes nothing; withdraw by the proposer only, while open;
  second open ticket in the same department → 409 `ticket_open` (and the index under a race); a closed ticket
  cannot be updated (trigger); a department admin cannot request on a `dept_admin` (themselves) or in another
  department (403); the super admin's request is applied at once and recorded as an approved ticket with its
  documents linked; audit rows for every step; a HEALTH admin sees EDU tickets → 404.
- (owner review 2026-10-07) `test_department_head_required.py`: creating a Department-tier office without a
  head → 400 `head_required`; with an existing login (who keeps their other memberships) and with a new login →
  the office and the head membership exist together (a forced failure creating the membership leaves no office);
  a directorate and a unit need no head; reactivating a department needs a head; deactivating a department whose
  only remaining member is the head ends the head membership in the same transaction, and refuses (409
  `office_in_use`) while the head holds items; a headless department built on purpose is counted in
  `departments_without_head` and listed by `GET /admin/offices?missing_head=true`, and `set` fixes it; the
  migration on a database with a headless department prints the notice and completes without creating rows;
  the super admin is not stopped by `not_delegable` (makes the department admin's membership the head, the
  one-admin rule still holding) but is stopped by the one-head index and `head_required`.
- (owner review 2026-10-07; revised with the owner's answers) `test_ticket_alerts.py`: opening raises one
  `admin_ticket` alert (case NULL, severity `normal`) to the super admin — an in-app notification, and under
  the default preferences no immediate e-mail (it goes to the digest); with `digest = none` an immediate e-mail;
  approval closes it `done` and raises a `normal` alert to the proposer only; other users never see either
  (list, counts, detail 404); the digest and the single-alert e-mail name the ticket ref and no payload;
  `ck_alerts_case` refuses a case-less alert of another kind.
- (owner review 2026-10-07; revised with the owner's answers) `test_ticket_documents.py`: documents uploaded
  with the request are on the ticket when the super admin opens it; a request without documents is accepted and
  one is attached later while open; attaching after approval, reject or withdrawal → 409 `ticket_closed`; a
  type other than `government_order` → 400; one infected file in a request refuses the whole request (no ticket,
  nothing stored, audit row); type check and size limit as uploads; `sourcetrace_status = not_applicable`; the
  document is invisible through `GET /documents/{ref}`, the case documents search and every case tab; readable
  by the super admin and the EDU admin, 404 for an EDU officer and the HEALTH admin;
  `GET /users/{id}/memberships/{mid}/documents` lists it after approval (incoming and outgoing memberships); a
  case upload with `government_order` → 400; duplicate on one ticket → 409; archive while open keeps the link.
- (owner review 2026-10-07, revised: no successor) `test_membership_exit.py`: the preview lists every
  allotment and every held file as items (a HEALTH-held file of an EDU case with facts only; a case both allotted
  to and held by the leaver as two items), the eligible targets and a fingerprint; the end call with every item
  assigned to different officers re-allots each allotment to its own target (officer field; no `allotted`
  leg), writes one `reassigned_on_exit` leg per file to its target with pending action and due date carried, or
  changed where the assignment says, and the remark, notifies each item's target of the case's open alerts and
  reopens alerts the leaver had acknowledged, writes one `membership.exit` row listing every item and its target
  — all in one transaction (a forced failure on the last item leaves everything unchanged); a missing item → 409
  `unassigned_items` naming it, nothing written; an item allotted elsewhere by the admin after the preview → 409
  `stale_exit` with the current items; a target in another department, ended, State-wide or the leaver → 400
  `bad_target`; the same item twice → 400 `duplicate_item`; items reassigned ahead with allot and recall + send
  disappear from the preview; nothing held → ended with an empty list; ending the primary passes the flag to the
  oldest other membership (mirror rewritten); ending the last membership leaves an active login with no
  functions, and a department admin can then add a membership that becomes primary; the person's HEALTH
  membership untouched by an EDU exit; the super admin's swap with `outgoing=end` requires the same full list.
  After `custody-workflow` lands, its suite adds: the leaver's
  drafts on those cases become permanent in the exit.
- `test_api_memberships.py`: each endpoint's function check (403), scope errors, shapes; `/me` lists memberships
  with per-membership functions and the union; `inbox/counts` returns a block per department; ownership
  endpoint with `office_code` of a second department; (owner review 2026-10-07) the head-change multipart request (202 / 201 shapes),
  `use_head_change` on the membership endpoints,
  exit-preview and end shapes, `/admin/tickets` list (oldest first, filters, counts), detail, approve, reject,
  withdraw, attach, download, `reserved_function` on granting `admin.tickets`.
- Existing suites stay green (`test_access.py`, `test_ownership.py`, `test_case_visibility.py`,
  `test_alert_recipients.py`, `test_api_*`), with the changes of decision 23 (`test_offices.py`,
  `test_api_offices.py`, seed tests); `test_migrations.py` covers 0008 upgrade → downgrade → upgrade (the
  downgrade guard stops on a ticket row); `test_schema_metadata.py` in step with `schema.md`.

## Verification
1. `docker compose run --rm api alembic current` → `0007`; if the dev database carries the feature branch's
   `0008_workflow`, the integrator first downgrades it to `0007` from that branch's checkout. (owner review
   2026-10-07) Before upgrading, `psql`: `SELECT count(*) FROM users WHERE role='super_admin' AND is_active` ≤ 1
   and no department with two active `dept_admin` users (else the guard stops and the integrator asks the owner
   which to keep). Then `alembic upgrade head` → `0008_memberships`; `psql`: `SELECT count(*) FROM users` =
   `SELECT count(*) FROM user_memberships WHERE is_primary`; `SELECT count(*) FROM user_permissions WHERE
   membership_id IS NULL` = 0; `aslms seed` reports `ref_ticket_kind` +1, `ref_record_type` +1, `ref_doc_type`
   +1, `ref_alert_kind` +1, `ref_permission` +2.
2. `ruff check` clean; `pytest -q` green (count in the cycle report). (owner review 2026-10-07) The migration
   output lists departments without a head; after fixing them with `POST /admin/tickets/head-change`
   (`operation=set`, as the super admin — applied at once), `GET /admin/tickets/counts` →
   `departments_without_head: 0` (recorded in the cycle report).
3. With Compose up: as the super admin create a person in EDU (`dept_officer`); as the HEALTH department admin
   `GET /users/lookup?email=…` and `POST /users/{id}/memberships` with `office=HEALTH`, `role=dept_officer`;
   sign in as the person: `GET /me` shows two memberships; `GET /inbox/counts` shows EDU and HEALTH blocks;
   `POST /cases/{ref}/allot` on a HEALTH-owned case → 403.
4. As the HEALTH admin `POST /users/{id}/password` → 403; `POST /users/{id}/memberships/{mid}/end` (nothing
   held: empty assignment list) → 200; the person's `/me` lists one membership.
5. (owner review 2026-10-07; revised with the owner's answers) As the EDU admin `POST
   /admin/tickets/head-change` (multipart: `operation=set`, `incoming.membership` = an EDU officer, one PDF
   government order) → 202 with `ASLMS/EDU/TKT/2026/000001` and one document; the officer's `/me` still says
   `dept_officer`; `PATCH /users/{id}/memberships/{mid}` with `role=dept_head` → 409 `use_head_change`; as the
   super admin `GET /admin/tickets/counts` → `open: 1`, the in-app `admin_ticket` alert is listed with severity
   `normal`; `GET /admin/tickets/{ref}` shows the order; `POST /admin/tickets/{ref}/approve` → the officer's
   `/me` says `dept_head`; the EDU admin has a "decided" alert; `POST /admin/tickets/{ref}/documents` → 409
   `ticket_closed`; `GET /users/{id}/memberships/{mid}/documents` lists the order; a second `set` for EDU → 409
   `head_exists`; a second `POST /admin/offices/EDU/admins` → 409 `admin_exists`; `PUT /admin/offices/EDU/admin`
   with a new person and `outgoing=dept_officer` → one EDU admin; `docker compose run --rm api aslms users
   create-super-admin …` → refused. As the super admin `POST /admin/offices` for a new department `TST` without
   `head` → 400 `head_required`, with `head` → 201 and the head's `/me` lists the `TST` membership; `POST
   /users/{id}/memberships/{mid}/end` on that head → 409 `head_required`.
6. (owner review 2026-10-07, revised: no successor) With two claimed EDU cases allotted to an EDU officer who
   holds both files: as the EDU admin `GET /users/{id}/memberships/{mid}/exit-preview` → 4 items and a
   fingerprint; `POST …/end` with three assignments → 409 `unassigned_items` naming the fourth; with all four
   (case A to officer X, case B to officer Y, B's file with a new due date) → 200; the custody cards show X and
   Y with the carried or changed pending action and due date, `custody_history` has two `reassigned_on_exit`
   legs, `audit_log` has one `membership.exit` row listing the four items and their targets.

## Open questions
None. Settled by the owner's answers (owner review 2026-10-07): one head per department and always a head,
named when the department is created (15, 24); the super admin changes the head at once, with no approval, and
is never subject to approval or delegation limits (4, 15); the outgoing head's fate stated in the replacement,
retype or per-item exit (16); `normal` severity for new tickets (19); the
order uploaded with the request, attachable only while open (20). Points the owner is asked to check at
approval (decisions taken, reversible):
- one active membership per person per department (2) — two posts in one department become one membership;
- the `users` office, type and designation columns kept as a mirror of the primary membership (3), dropped in a
  later migration;
- the acting membership is resolved by the server, with no "acting as" switch (6);
- a department admin may add a membership for their department to a person from any department, found by exact
  e-mail; login-level actions (password, disable) stay with the primary office's admins (8);
- `GET /inbox/counts` changes shape to one block per department (API table);
- (owner review 2026-10-07) up to 5 files per head-change request, `government_order` only (20);
- (owner review 2026-10-07) deactivating a department ends its head membership when it is the last member and
  holds no items (24); a super admin's direct head change closes an open department-admin ticket as superseded
  (15);
- (owner review 2026-10-07) the replaced super admin's login is disabled (13);
- (owner review 2026-10-07, revised) no successor: every allotted case and held file gets a target chosen by
  the admin, one by one; the exit is refused until all have one (21);
- (owner review 2026-10-07) a login whose last membership ends stays active with no functions until its next
  department adds it (22).
