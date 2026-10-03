# Design: Offices administration — departments, directorates, designations, first department admins

```
slug: offices-admin
status: awaiting-approval
author: architect
date: 2026-10-04
approved_by:
```

## Context
Plan §5.11 (Administration): "Departments, directorates and offices, in the government hierarchy" and
"users and roles". Plan §1.1 Table 1: the **Department admin** is "the nodal officer of a department" who
"manages the department's users, codes and keywords"; a **Directorate user** is "an officer of a directorate
under a department"; access "follows the government hierarchy" (State → Department → Directorate, §8.1).
Backlog row 1: "Offices administration: departments and directorates (create, edit, deactivate, tree),
designations, the super admin's first department admins".

What is in place (migrations 0001–0003, the 3 Oct API slice):
- `offices` (master; `code` unique, `name`, `kind` → `ref_office_kind`, `parent_id`, materialised `path`,
  `notes`, `is_active` / `deactivated_at` / `valid_from` / `valid_to`, `created_by` / `updated_by`) and
  `designations` (master; `code`, `name`, `sort_order`, same lifecycle columns). `aslms seed` creates the
  root office `GOA` ("Government of Assam", kind `state`, path `GOA`) and 18 Secretariat designations.
  **Nothing else is seeded**: department codes are the Secretariat's own and are entered by the super admin
  (CLAUDE.md: no starting data, never fabricate codes).
- `services/access.py`: `require`, `has`, `is_super_admin`, `office_subtree`, `in_scope` (path-prefix
  scope), `assert_can_manage` (the delegation rule: a non-super-admin acts only inside their own office
  subtree and only on the delegable types `dept_officer`, `directorate_user`, `standing_counsel`,
  `referral_reviewer`; `dept_admin` is therefore created only by the super admin).
- `services/users.py::create_user`, `services/audit.py::write_audit`, `Actor`; `EventType.CONFIG_CHANGED`.
- `Permission.OFFICES_MANAGE` (`offices.manage`, "Manage offices") exists in `ref_permission`; the default
  matrix gives it to no type, so today only the super admin holds it.
- API: `GET /admin/offices` (active offices in the caller's scope; `users.view`) lives in
  `api/routers/access.py`; `POST /admin/users` creates a user of any type in any active office, subject to
  the delegation rule; `aslms users …` CLI acts as the `.env` super admin.

Not covered here: counsel codes, keywords, name patterns and watchlist (backlog `recommend-and-claim`);
editing `ref_office_kind` labels; moving an office to another parent (see decision 6); OTP / "set your own
password" on first sign-in (backlog `otp-and-profile`); the portal screens (`portal-shell`).

## Decisions
1. **No schema change, no migration.** `offices` and `designations` already carry every column this item
   needs (DB_STANDARD §0 rule 3 versioning, §5 audit columns). Alternative: add `short_name` / `sort_order`
   to `offices` — not asked for by the plan; deferred until a screen needs it.
2. **One new function, `admin.designations`** ("Designations" — create and edit the designation list), added
   to the `Permission` enum, `PERMISSION_LABELS` and therefore `ref_permission` and the type matrix by the
   idempotent `aslms seed` (the `ref_*` columns are varchar FKs, so no migration). Default matrix: enabled
   for no type (the super admin has it by definition). Alternative: reuse `offices.manage` for designations —
   rejected because designations are State-wide while `offices.manage` can be delegated to a department
   (decision 4), and a department must not edit the State list.
3. **Office kinds and placement.** The parent of a new office must be active and its kind must allow the
   child's kind:

   | child kind | allowed parents | visibility tier |
   |---|---|---|
   | `state` | none (only the seeded root `GOA`; never created through the API) | State |
   | `department`, `central`, `advocate_general` | `state` | Department |
   | `directorate` | `department` | Directorate |
   | `unit` | `department`, `directorate`, `central`, `advocate_general` | tier of its parent's subtree (a unit is a section inside an office, cf. `case_ownership.unit_office_id`) |

   `tier` is reported by the API as `state` for the root, `department` for a direct child of the root,
   `directorate` for anything deeper; scope checks keep using `offices.path` (unchanged). Alternative: free
   placement — rejected because the three tiers of the plan would no longer be derivable from the tree.
4. **Who manages offices.** Writes require `offices.manage`. The super admin may act on any office. Any
   other holder of the function (a department admin granted it by the super admin, the existing override
   mechanism) follows the same shape as the user-delegation rule: only offices **strictly inside their own
   subtree** (not their own office, not another department), and only of the kinds `directorate` and
   `unit`. Departments, central offices and the Advocate General's office are created by the super admin
   only. Alternatives: super-admin-only writes (simpler, but a 30-directorate department would depend on
   the super admin for every section), or unrestricted delegation (would let a department create a
   department). The plan is silent; this mirrors the owner's 1 Oct delegation decision.
5. **Codes are Secretariat codes, immutable.** `code` is normalised to upper case, must match
   `^[A-Z0-9][A-Z0-9-]{1,39}$`, is unique (DB), and **cannot be changed after creation**: it is embedded in
   every `ref_no` allocated for the office (`ASLMS/EDU/REQ/2026/000042`), in `ref_sequences`, and in every
   `actor_office_code` snapshot. A wrongly coded office is deactivated and recreated. The child code is
   free-form (the `EDU-DSE` convention is recommended in the API description, not enforced). Alternative:
   derive child codes from the parent — rejected; the Secretariat's codes are what they are.
6. **Path and no re-parenting.** `path` is the chain of codes from the root inclusive, `GOA/EDU/EDU-DSE`
   (as the seed and the existing tests already build it; `schema.md`'s example `EDU/EDU-DSE` omits the root
   and the scribe corrects it). An office's `parent_id` cannot be changed in this item: a re-parenting
   rewrites the paths of a whole subtree and silently changes who can see every case under it. A
   reorganisation is modelled as deactivate-and-create plus ownership transfers (backlog
   `recommend-and-claim`). If the Secretariat needs true moves, that is a later, audited, two-step feature.
7. **Deactivation is refused while anything active depends on the office.** `deactivate` sets
   `is_active=false`, `deactivated_at=now()`, `valid_to=today` (and never deletes — DB_STANDARD §6). It is
   refused (HTTP 409) when the office has active child offices, active users, active `case_ownership` rows
   (`office_id` or `unit_office_id`, `status='active'`) or `custody` rows (`holder_office_id`); the message
   carries the counts so the admin disables or moves them first (each of those is its own audited action).
   The root `GOA` and the caller's own office can never be deactivated. `reactivate` requires an active
   parent and clears `deactivated_at` / `valid_to`. Alternative: cascade deactivation to the subtree and
   its users — rejected, one request would silently lock out many people without a per-user audit row.
8. **Editable fields.** `name`, `notes`, and `valid_from` (a department established before the portal) on
   offices; `name`, `sort_order` on designations. `kind` is immutable (it fixes the tier); codes are
   immutable (decision 5).
9. **The first department admins.** `POST /admin/offices/{code}/admins` creates a user of type
   `dept_admin` in a Department-tier office (`department`, `central`, `advocate_general`), through the
   existing `services/users.py::create_user` and `access.assert_can_manage(..., target_role=dept_admin)` —
   which admits only the super admin because `dept_admin` is not delegable. It is the same user row
   `POST /admin/users` would create (there is deliberately no second mechanism), with
   `must_confirm_profile=true`; it exists so that setting up a department is two calls on one screen and so
   that `GET /admin/offices/{code}/admins` answers "who runs this department?". A directorate gets
   `directorate_user`s from its department admin through `POST /admin/users`, as today. The password is
   given by the super admin as for every user today; self-set passwords arrive with `otp-and-profile`.
10. **Reads.** `GET /admin/offices` (list), `/tree` and `/{code}` keep the existing rule: `users.view`,
    filtered to the caller's subtree unless they hold `cases.view_all` or are the super admin; inactive
    offices appear only with `include_inactive=true`, which requires `offices.manage`. Designations are read
    by any signed-in user (profile and user-creation pickers); the inactive ones only with
    `include_inactive=true` and `admin.designations`.
11. **Audit and events.** Every write calls `write_audit` with `before` / `after` summaries: `office.create`,
    `office.update`, `office.deactivate`, `office.reactivate`, `office.admin_added` (in addition to the
    `user.create` row written by `create_user`), `designation.create`, `designation.update`,
    `designation.deactivate`, `designation.reactivate`. Office writes also emit one `config_changed` event
    (`visibility=scoped`, payload `{entity, code, action}`, dedupe key `office:<id>:<action>:<iso ts>`), so
    the data-health and audit screens can show organisation changes on the timeline.
12. **CLI** `aslms offices create | list | deactivate` acting as the `.env` super admin (same `_actor`
    pattern as `aslms users`), so a fresh Compose deployment can be bootstrapped without the portal.
    Designations are API-only (the seed already provides the working set).
13. **Router move.** `GET /admin/offices` moves unchanged from `routers/access.py` into the new
    `routers/offices.py` (same path, same behaviour, plus the two query parameters of decision 10).

## Data
No table or column is added or changed. Migration number: **none**.

For `docs/schema/schema.md` (as-built corrections, Group 1, written by the scribe):
- `offices` — `path` is the chain of codes from the root inclusive (`GOA/EDU/EDU-DSE`); `code` and `kind`
  are immutable after insert; `parent_id` is not changed by the application (no re-parenting); allowed
  placements as in decision 3. Deactivation refused while active children, users, ownership or custody
  reference the office.
- `designations` — `code` immutable; `name`, `sort_order` editable; deactivated, never deleted.
- Group 0, `ref_permission` — 43 functions: adds `admin.designations` (module `admin`), seeded by
  `aslms seed` (no migration).

## Services
`backend/aslms/services/offices.py` (new):
- `class OfficeError(ValueError)` — bad input, unknown parent, placement refused, duplicate code, immutable
  field; `class OfficeInUse(OfficeError)` with `.counts: dict[str, int]` for decision 7 (→ HTTP 409).
- `PLACEMENT: dict[OfficeKind, frozenset[OfficeKind]]` (decision 3); `DELEGABLE_KINDS = {directorate, unit}`.
- `normalise_code(code) -> str`; `tier_of(office) -> str`; `child_path(parent, code) -> str` (refuses > 400
  chars).
- `assert_can_manage_office(session, actor_user, *, parent: Office | None, office: Office | None,
  kind: OfficeKind | None)` — `access.require(OFFICES_MANAGE)`; super admin passes; otherwise the target
  (the parent for a create, the office for an update) must satisfy `access.in_scope` **and** not be the
  actor's own office, and `kind in DELEGABLE_KINDS`. Raises `access.Forbidden`.
- `create_office(session, actor, actor_user, *, code, name, kind, parent: Office, notes=None,
  valid_from=None) -> Office` — validation, placement, path, `created_by`, audit `office.create`, event.
- `update_office(session, actor, actor_user, office, *, name=None, notes=None, valid_from=None) -> Office`
  — audit `office.update` with before/after.
- `deactivate_office(session, actor, actor_user, office) -> Office`, `reactivate_office(...)` — decision 7.
- `office_tree(session, roots: list[Office], *, include_inactive=False) -> list[OfficeNode]` — one query
  over the scope's subtree, nested by `parent_id`, each node with `users_active` (count of active users)
  and `children`.
- `dependents(session, office) -> dict[str, int]` — `children`, `users`, `ownership`, `custody` counts.
- `add_department_admin(session, actor, actor_user, office, *, email, password, full_name, designation=None,
  designation_id=None, mobile=None) -> User` — refuses when `tier_of(office) != "department"` or the office is
  inactive; `access.assert_can_manage(session, actor_user, "create", target_office=office,
  target_role=Role.DEPT_ADMIN)`; `create_user(...)`; audit `office.admin_added` (entity `office`, after
  `{user_id, email}`).
- Designations: `create_designation(session, actor, actor_user, *, code, name, sort_order=0)`,
  `update_designation(..., name=None, sort_order=None)`, `set_designation_active(..., enabled: bool)` —
  each `access.require(ADMIN_DESIGNATIONS)` and an audit row. `sort_order` default: 10 past the current max.

`backend/aslms/domain/reference.py`: `Permission.ADMIN_DESIGNATIONS = "admin.designations"`.
`backend/aslms/services/access_seed.py`: its label; no type enabled by default.
`backend/aslms/cli/users.py` or a new `cli/offices.py`: `offices_app` (decision 12), registered in
`cli/main.py` as `offices`.

## API
Router `backend/aslms/api/routers/offices.py` (prefix `/admin`, tag `offices`); schemas in
`api/schemas.py`. `{code}` is the office or designation code (case-insensitive). Errors: 400 `OfficeError`,
403 `Forbidden`, 404 outside scope or unknown (indistinguishable, as `/admin/users` does), 409 `OfficeInUse`
and duplicate code.

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /admin/offices` | `users.view` | `?kind=`, `?include_inactive=` (needs `offices.manage`) | `list[OfficeOut]` ordered by `path` | caller's subtree; all when super admin or `cases.view_all` |
| `GET /admin/offices/tree` | `users.view` | `?include_inactive=` (needs `offices.manage`) | `list[OfficeNodeOut]` (roots of the scope; each `{…OfficeOut, tier, depth, is_active, users_active, children}`) | same |
| `GET /admin/offices/{code}` | `users.view` | | `OfficeDetailOut` = `OfficeOut` + `tier, depth, parent_code, notes, is_active, deactivated_at, valid_from, valid_to, created_at, updated_at, counts {children, users, ownership, custody}` | same |
| `POST /admin/offices` | `offices.manage` | `OfficeCreateIn {code, name, kind, parent_code, notes?, valid_from?}` | 201 `OfficeDetailOut` | decision 4 |
| `PATCH /admin/offices/{code}` | `offices.manage` | `OfficePatchIn {name?, notes?, valid_from?}` | `OfficeDetailOut` | decision 4 |
| `POST /admin/offices/{code}/deactivate` | `offices.manage` | | `OfficeDetailOut`; 409 with `counts` when in use | decision 4 and 7 |
| `POST /admin/offices/{code}/reactivate` | `offices.manage` | | `OfficeDetailOut` | decision 4 and 7 |
| `GET /admin/offices/{code}/admins` | `users.view` | | `list[UserOut]` (users of type `dept_admin` in that office) | caller's subtree |
| `POST /admin/offices/{code}/admins` | `users.create` | `DepartmentAdminIn {email, password, full_name, designation?, designation_id?, mobile?}` | 201 `UserOut` | delegation rule → super admin only (decision 9) |
| `GET /admin/designations` | signed in (`current_user`) | `?include_inactive=` (needs `admin.designations`) | `list[DesignationOut {id, code, name, sort_order, is_active}]` ordered by `sort_order, name` | State-wide list |
| `POST /admin/designations` | `admin.designations` | `DesignationCreateIn {code, name, sort_order?}` | 201 `DesignationOut` | |
| `PATCH /admin/designations/{code}` | `admin.designations` | `DesignationPatchIn {name?, sort_order?}` | `DesignationOut` | |
| `POST /admin/designations/{code}/deactivate`, `…/reactivate` | `admin.designations` | | `DesignationOut` | |

`OfficeOut` gains `is_active` (existing fields `id, code, name, kind, path` unchanged, so `UserOut.office`
and `/me` keep working). `GET /admin/offices` is removed from `routers/access.py`; `main.py` includes the
new router.

## Jobs
None.

## Tests
Unit (`tests/unit/test_offices_rules.py`, no database):
- code normalisation accepts `edu` → `EDU`, `EDU-DSE`; rejects spaces, lower-case after normalisation
  failure, 1-character and 41-character codes;
- placement table: every (child kind, parent kind) pair is allowed exactly as decision 3; `state` is never
  creatable; `tier_of` on a synthetic three-level path.

Database (`tests/db/test_offices.py`, rolled-back `session` fixture, seeded via `clean_db` pattern):
- super admin creates `EDU` under `GOA` → path `GOA/EDU`, `created_by` set, `valid_from` today, one
  `audit_log` row `office.create` and one `config_changed` event;
- `EDU-DSE` (directorate) under `EDU` → path `GOA/EDU/EDU-DSE`; a unit under the directorate; a directorate
  under `GOA` and a department under `EDU` are refused (`OfficeError`); a child under an inactive parent is
  refused;
- a duplicate code (any case) is refused before the database raises; `update_office` cannot change `code`,
  `kind` or parent (no such parameters; the test asserts the audit `after` equals the intended fields only);
- `deactivate_office` is refused with counts while a child, a user, an active `case_ownership` row or a
  `custody` row points at it; succeeds afterwards and sets `is_active=false`, `deactivated_at`, `valid_to`;
  the row still exists; `reactivate_office` fails under an inactive parent and succeeds under an active one;
  `GOA` and the actor's own office cannot be deactivated;
- delegation: an `EDU` dept admin without the function gets `Forbidden`; granted `offices.manage` they
  create `EDU-DSE` and a unit, cannot create a `department`, cannot create under `HEALTH`, cannot edit or
  deactivate `EDU` itself;
- `add_department_admin`: the super admin adds one to `EDU` (type `dept_admin`, `must_confirm_profile`,
  audit `office.admin_added` + `user.create`); refused on `EDU-DSE` (directorate tier) and on an inactive
  office; the `EDU` dept admin gets `Forbidden` (non-delegable type);
- designations: create (`code` upper-cased, `sort_order` defaulted past the max), update, deactivate,
  reactivate, each with its audit row; a duplicate code is refused; a dept admin without
  `admin.designations` gets `Forbidden`; `create_user` with a deactivated `designation_id` still resolves
  (historic rows) — documented behaviour, asserted;
- seed: `seed_all` twice inserts nothing the second time with the 43rd function present;
  `test_seed_builds_the_full_matrix` still passes (rows = types × functions).

API (`tests/db/test_api_offices.py`, `TestClient` as in `test_api_access.py`):
- the super admin's `GET /admin/offices/tree` returns `GOA` with `EDU`, `HEALTH` and `EDU-DSE` nested; the
  `EDU` admin's tree is rooted at `EDU` and never contains `HEALTH`; `GET /admin/offices/HEALTH` as the `EDU`
  admin is 404;
- `include_inactive=true` is 403 without `offices.manage`; deactivated offices are absent from the default
  list and present with the flag;
- `POST /admin/offices` twice with the same code → 201 then 409; a bad `parent_code` → 400; as the `EDU`
  admin without the function → 403;
- `POST /admin/offices/EDU/admins` as the super admin → 201 and the new admin can `POST /auth/login` and
  then `POST /admin/users` a `directorate_user` in `EDU-DSE`; as the `EDU` admin → 403;
- `POST …/deactivate` on an office with users → 409 whose body carries `counts`;
- `GET /admin/designations` works for a `dept_officer`; `POST` by them is 403; by the super admin 201;
- every write above leaves exactly the expected `audit_log` rows (asserted by `action` and `entity_id`).

`tests/unit/test_schema_metadata.py` and `test_database_matches_the_models` are unchanged and must stay
green (no model change beyond the enum).

## Verification
From the repository root, Compose up (`docker compose up -d postgres redis api`), then:
1. `docker compose run --rm api aslms seed` twice → the second run reports 0 rows inserted;
   `SELECT count(*) FROM ref_permission` = 43; `SELECT count(*) FROM role_permissions` = 9 × 43 = 387.
2. Sign in as the `.env` super admin (`POST /auth/login`), then
   `POST /admin/offices {"code":"EDU","name":"Education","kind":"department","parent_code":"GOA"}` → 201,
   `path` = `GOA/EDU`; again → 409.
3. `POST /admin/offices {"code":"EDU-DSE","kind":"directorate","parent_code":"EDU",…}` → 201;
   `POST /admin/offices {"code":"X","kind":"directorate","parent_code":"GOA",…}` → 400.
4. `POST /admin/offices/EDU/admins {…}` → 201; sign in as that user; `GET /me` shows type `dept_admin` and
   the `dept_admin` functions; `GET /admin/offices/tree` as them is rooted at `EDU`;
   `POST /admin/offices` as them → 403.
5. `POST /admin/offices/EDU/deactivate` as the super admin → 409 with `counts.users` = 1; disable the admin
   (`POST /admin/users/{id}/disable`), deactivate `EDU-DSE`, then deactivate `EDU` → 200, `is_active=false`;
   `GET /admin/offices` omits it; `?include_inactive=true` lists it.
6. `POST /admin/designations {"code":"OSD","name":"Officer on Special Duty"}` → 201;
   `GET /admin/designations` as a `dept_officer` lists 19.
7. `SELECT action, count(*) FROM audit_log GROUP BY 1` shows `office.create` 2, `office.deactivate` 2,
   `office.admin_added` 1, `designation.create` 1, `user.create` 1, `user.disable` 1.
8. `aslms offices list` prints the tree with the inactive rows marked; `pytest -q` green; `ruff check`
   clean.

## Open questions
None. Points the owner may wish to overrule at approval: decision 4 (a department admin may be granted
`offices.manage` for its own directorates and units), decision 6 (no re-parenting of offices in this
item), decision 9 (a dedicated `/admins` endpoint rather than only `POST /admin/users`).
