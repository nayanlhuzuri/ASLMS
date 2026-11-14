# Design: Offices from the Assam State Portal list, new office types and the workbook import

```
slug: offices-import
status: approved
author: architect
date: 2026-11-14
approved_by: owner on 2026-11-14
```

## Context

**The owner's decisions of 13 Nov 2026** (decisions log, "Departments follow the Assam State Portal"; backlog row 257):
- The portal's departments follow https://assam.gov.in/departments-list: 56 departments, and about 160 offices under
  them.
- Six office types are approved: Board / Corporation, Statutory Authority / Commission, Society / Mission / Project,
  Institution, Local Body and Autonomous Council. Directorate becomes Directorate / Commissionerate. Unit stays.
- The owner fills a workbook with the departments, offices, codes, types, department heads, first department
  administrators and optional office heads. Claude checks it and lists the problems. Then one audited run of
  `aslms offices import` creates everything. Passwords are never collected; a new login gets an e-mail to set its own
  password.
- The existing `SEC-EDU` "Department of School Education" follows the State Portal naming (proposed code `SCH-EDU`).
  Office codes are immutable, so this design checks the impact and proposes a fix.

The plan names "departments, directorates and offices, in the government hierarchy", with visibility at three tiers:
State, department, directorate. The new types are offices in that hierarchy. This design does not deviate from the
plan. It deviates once from an earlier owner decision (decision 9, flagged).

**The workbook** is built by the scratchpad script `build_offices_xlsx_v2.py`. The filled copy is
`Claude outputs/ASLMS_Offices_From_State_Portal.xlsx`. It is outside git (`.git/info/exclude`) because it holds
officers' names, e-mails and mobile numbers. Its sheets:
- **Read Me**: instructions and a summary written as formulas. The import does not read it.
- **Departments**: header on row 4, data from row 5. 56 rows from the site, then 10 empty rows. Columns:
  No. · Department Name (as on the site) · Website · Code · Code Check · Include? (Yes / No / To Decide) ·
  Head: Full Name / Designation / Login E-mail / Mobile (10 digits) / Head Already Has an ASLMS Login? ·
  Admin: the same five · People Check · In ASLMS Now · Note From the Check · Your Remarks.
- **Offices Under Departments**: header on row 4, data from row 5. 163 rows (160 from the site and 3 suggested
  Autonomous Councils), then 60 empty rows. Columns: No. · Parent Department (a department *name*, from a dropdown) ·
  Office Name · Website · Office Type · Code · Code Check · Include? · Office Head: Full Name / Designation /
  Login E-mail / Mobile (10 digits) / User Type (Directorate User / Department Officer) · Already Has an ASLMS Login? ·
  People Check · Source (Site / Suggested / Added) · In ASLMS Now · Note From the Check · Your Remarks.
- **Lists**: the dropdown sources (office types with "What It Covers", Include?, designation names, office user
  types).

The proposed codes are at most 15 characters (departments at most 10). The types break down as: 73 Directorate /
Commissionerate, 30 Board / Corporation, 19 Society / Mission / Project, 18 Statutory Authority / Commission,
16 Institution, 3 Autonomous Council, 3 Unit and 1 Local Body. The Read Me makes the owner three promises that bind
this design: "A designation not in the list can be typed; ASLMS will add it", "If the person already has an ASLMS login
... the same login is used, no second one is made", and "Each new login receives an e-mail to set their own password".

**What exists (checked 14 Nov 2026 on `main` at 3e19b17):**
- **Office types.** `offices.kind` is a `ref_office_kind` code (a varchar foreign key, not a Postgres enum). It is
  seeded from `OfficeKind` (`state`, `central`, `department`, `directorate`, `advocate_general`, `unit`; labels
  "State", "Central", "Department", "Directorate", "Advocate general", "Unit"; sort 10 to 60). Adding a type is a
  reference-data insert.
- **Placement.** `services/offices.py::PLACEMENT` says which parent kinds each kind accepts. `DELEGABLE_KINDS`
  (`directorate`, `unit`) are the kinds a department administrator may create inside their own subtree.
  `DEPARTMENT_TIER_KINDS` (`department`, `central`, `advocate_general`) is defined three times, in `services/access.py`,
  `services/matching.py` and `services/offices.py`. It is used by `is_department`, `department_of`, the matching engine's
  department list, custody, ownership, reporting and the head and admin rules.
- **Tiers.** `tier_of` takes the tier from the depth of `offices.path`: depth 0 is State, 1 is department, 2 or more
  is directorate. Visibility is a prefix of `path`. An office of any kind placed under a department is at the
  directorate tier and inside its department's visibility, with no code change.
- **Where the frontend uses kinds.** `components/admin/Offices.tsx` (`DEPARTMENT_TIER`, the Kind dropdown from
  `GET /reference/labels` `office_kinds`, labels through `labelOf`), `components/admin/Tickets.tsx` (department kinds
  only) and `components/admin/mapping/Watchlist.tsx`. The watchlist has a hard-coded
  `WATCH_KINDS = ["department", "central", "advocate_general", "directorate", "unit"]`, which would hide the new
  types from the Watchlist office picker. `test/render.tsx` has the label fixture.
- **Codes.** `OFFICE_CODE_RE = ^[A-Z0-9][A-Z0-9-]{1,39}$` allows 2 to 40 characters. A code is immutable. It is
  embedded in `offices.path`, in every actor snapshot (`actor_office_code`, 15 tables) and in every `ref_no` the office
  allocates (`ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>`).
- **Gap found: long codes break numbering.** `ref_no` is `varchar(40)` and `ref_sequences.office_code` is
  `varchar(20)`. The fixed parts of a number are 23 characters (`ASLMS/`, `/NOTE/`, `2026/`, six digits). So an office
  code longer than 17 characters makes the first note, document, transfer, ticket or manual next date from that office
  fail with "value too long". No office has such a code today (the longest is 13).
- **Gap found: hyphens in `REF_NO_RE`.** `services/refno.py::REF_NO_RE` accepts `[A-Z0-9_]{2,20}` for the code part,
  so it cannot parse a number from a hyphenated office such as `ASLMS/SEC-EDU/TKT/2026/000001`. Its only caller today,
  `current_case_ref_no`, handles `CASE` numbers only, so nothing is broken yet.
- **The head.** `create_office` raises `HeadRequired` (`head_required`) for a Department-tier office without `head`.
  `head` is `{user_id | email, designation?, designation_id?}` of an *existing* login (design `office-head-picker`).
  `_set_head` records it as an approved `head_change` ticket through `tickets.record_direct_set`. The owner's answer of
  26 Oct 2026 withdrew "Name the Head Later" ("if there is a department, there will be a head so its always best to
  create the user first").
- **Departments can already lack a head.** A head-change ticket can end a head. `offices.departments_without_head`
  lists such departments. The super admin's dashboard counts them (`departments_without_head`).
  `GET /admin/offices?missing_head=true` and `aslms offices list --missing-head` list them. A head-change request with
  `operation=set` fills the gap.
- **The admin.** `add_department_admin` always creates a *new* login through `create_user` and requires a password.
  `memberships.add` gives an existing login a membership. The super admin may add any type except `super_admin` and
  `dept_head`.
- **Membership rules.** `check_type_limits` allows one active membership per person per department
  (`one_per_department`), one head and one admin per department, and no other membership for the Super Administrator.
  So **the same person cannot be both head and admin of one department**. The workbook's Read Me says the admin "can
  be the same person as the head" (decision 12).
- **Logins.** `create_user(..., role=None, office=None)` makes a login with no office yet, which the head picker
  accepts. `password` is required and hashed. `must_change_password=True` and `must_confirm_profile=True` are set.
- **Setting a password.** There is no set-password link or welcome e-mail today. The reset flow is: Forgot password?
  (`/forgot`), then a 6-digit code mailed to the address, then a new password (`auth.request_reset` /
  `auth.confirm_reset`). It sets the person's own password and clears `must_change_password`. The first sign-in then
  asks the person to confirm their profile with a mandatory mobile number. Every sign-in needs a code by e-mail
  (`otp.ensure_mail_ready` refuses without a mail service). Development mail goes to Mailpit.
- **Validators.** E-mail: `users.EMAIL_RE`. Mobile: `profile.normalise_mobile` (`+91`, `91…` and `0…` forms accepted,
  then `^[6-9][0-9]{9}$`; otherwise `invalid_mobile`). Name: `profile._name` (2 to 200 characters).
- **Designations.** 19 rows are in the dev database (the seed's 18 plus `ADDL_SECY` "Additional Secretary"), with the
  codes renamed on 12 Nov 2026. The workbook's Lists sheet names them by *name*.
- **Dependencies.** `openpyxl` is not a dependency. `xlsxwriter` writes only. `defusedxml` is not in the lock either.
- **The dev offices.** `GOA`, `IT` (Information Technology Department) with `IT-DITEC` (directorate) and one unit, and
  `SEC-EDU` (Department of School Education). There are 8 logins.

**Out of scope:** a portal screen for the import (the command line only, like `aslms offices create`), the State
Insights page (row 258), District Court offices, and changing an existing department's head or admin. Head changes
go through the head-change request, and the admin through the swap.

## Decisions

### Office types

1. **Six new `ref_office_kind` codes, and the Directorate label widened.** The codes, with the workbook's "What It
   Covers" text as their description and their sort order:

   | code | label | sort |
   |---|---|---|
   | `directorate` (exists) | Directorate / Commissionerate (was "Directorate") | 40 |
   | `board_corporation` | Board / Corporation | 41 |
   | `statutory_authority` | Statutory Authority / Commission | 42 |
   | `society_mission` | Society / Mission / Project | 43 |
   | `institution` | Institution | 44 |
   | `local_body` | Local Body | 45 |
   | `autonomous_council` | Autonomous Council | 46 |

   The sort orders keep the new types between Directorate and Advocate general, so every dropdown lists the types
   under a department together. `OfficeKind` gains the six members in that order. The Directorate label changes only
   while it still reads "Directorate", so a label an administrator has edited is kept (the precedent of
   `_relabel_note_kinds`). Codes are short and stable; the labels carry the "/" wording.
   *Alternatives:* one code per word pair, such as `board` and `corporation` (12 codes, and the owner approved six
   types); a free-text "type" column on `offices` (no code set, against DB_STANDARD §7).

2. **Placement: every new type sits under a department, as a directorate does.** `PLACEMENT` adds
   `{K.DEPARTMENT}` for each of the six. A Unit may also sit inside any of the six, matching the workbook's "a section,
   cell, wing or district office inside any office above". So `K.UNIT` accepts department, directorate, the six new
   types, central and advocate_general. The Autonomous Councils (Bodoland Territorial Council, Karbi Anglong, Dima
   Hasao) sit under their administering department, as the workbook places them (Welfare of Bodoland, Hill Areas). No
   new type is accepted under the State root, under `central` or under `advocate_general`, because no row needs it.
   *Alternative:* allowing the new types under `central` and `advocate_general` too (no row needs it; easy to add
   later).

3. **Tiers and visibility do not change.** The new types are not Department-tier: `DEPARTMENT_TIER_KINDS` stays the
   same in all three modules. They sit at depth 2, which is the directorate tier. So the department's head, admin and
   officers see their cases through the existing `path` prefix rule. Cases are recommended and claimed at the
   department, as today, and a counsel code or keyword mapped to such an office scores for its department as it does
   for a directorate. The `tier` value in the API stays `directorate`; it names a tier, not a kind.
   *Alternative:* making Boards and Autonomous Councils Department-tier so they claim cases in their own name (a change
   to the plan's three tiers, the matching engine and recommend-and-claim; not asked for).

4. **The new types are delegable.** `DELEGABLE_KINDS` adds the six. A department administrator may create a Board or an
   Institution inside their own department, just as they may create a directorate. Only the Super Administrator
   creates Department-tier offices (unchanged).

5. **The frontend reads the types from the server.** `GET /reference/labels` `office_kinds` items gain two additive
   fields: `description` (the "What It Covers" text) and `parents` (the kinds a parent may have, from `PLACEMENT`).
   Three frontend changes follow:
   - The New Office form offers only the kinds the chosen parent accepts, and shows the chosen kind's description as
     the field hint.
   - `Watchlist.tsx` drops `WATCH_KINDS` and uses every kind except `state` from the labels.
   - The `test/render.tsx` fixture lists the new kinds.

   *Alternative:* a hard-coded list in the frontend (it would drift again; the watchlist list is the proof).

6. **Office codes are at most 17 characters from now on.** `OFFICE_CODE_RE` becomes `^[A-Z0-9][A-Z0-9-]{1,16}$`, and
   `OfficeCreateIn.code` takes `max_length=17`. This holds for the portal, `aslms offices create` and the import, and
   it fixes the numbering gap described in Context. No existing office is affected (the longest code is 13, and the
   proposed workbook codes are at most 15). The message names the reason ("a code is 2 to 17 characters …, because it
   is part of every reference number the office issues"). `REF_NO_RE` accepts hyphens and codes up to 20 characters
   (`[A-Z0-9_-]{2,20}`), matching `ref_sequences.office_code`. *Alternatives:* widening `ref_no` to 60 characters (a
   migration on seven tables and the DB_STANDARD §3 limit, for codes nobody needs); leaving it (a latent failure on
   the first note from such an office).

### The import

7. **`aslms offices import FILE [--apply --expect FINGERPRINT] [--no-welcome]`.** The default is a dry run that
   writes nothing.
   - `FILE` is a path, or `-` to read the workbook from standard input. The runbook uses
     `docker compose exec -T api aslms offices import - < "Claude outputs/ASLMS_Offices_From_State_Portal.xlsx"`, so
     the file is never copied into a container or the repository.
   - The command acts as the single active Super Administrator, like `aslms offices create`. The services check
     `offices.manage`, `users.create` and `admin.designations` as they do for the portal.
   - The dry run prints every problem, a plan of what `--apply` would do, and a **plan fingerprint**: 12 hex
     characters of the sha256 of the file's bytes and the plan.
   - `--apply` needs `--expect` with that fingerprint. If the file or the database changed since the dry run the owner
     approved, the fingerprint differs and the command refuses (exit 3). This is the shape of the exit step's
     fingerprint (`memberships.exit_preview`).

   *Alternative:* `--apply` without a fingerprint (the owner approves one listing, and a different one could run).

8. **Reading the workbook.**
   - The command reads with `openpyxl.load_workbook(..., read_only=True, data_only=True)`. It refuses a file over
     5 MB, or one that does not start with the zip signature, with exit 2. `defusedxml` is installed so openpyxl
     parses the XML defensively.
   - Sheets are found by name ("Departments" and "Offices Under Departments"). Columns are found by their header text
     in the row that starts with "No." within the first 10 rows, not by letter, so an added column does not shift
     them. A missing required header refuses the file and names the header.
   - The formula columns (Code Check, People Check) and In ASLMS Now, Note From the Check, Your Remarks and Source
     are ignored. The import makes its own checks and never trusts cached formula values.
   - Cells are trimmed, non-breaking spaces become spaces, and runs of spaces are collapsed. Yes / No / To Decide are
     read without regard to case. A mobile typed as a number (`9864012345` or `9864012345.0`) is read as its digits.
   - A row with no name and no code is empty and is skipped silently.

9. **A department with no head yet: allowed only through the import, with a "No Head Yet" badge (deviation from
   `office-head-picker`, the owner's answer of 26 Oct 2026; for the owner to confirm).**
   - When a department row's five Head cells are *all* empty, `--apply` creates the department without a head.
     `create_office` gains a keyword `allow_no_head: bool = False`, which only `offices_import` passes. The portal
     form, `POST /admin/offices` and `aslms offices create` keep `head_required`.
   - The audit row `office.create` carries `head: null` and `no_head_yet: true`.
   - A partly filled head (some cells empty) is an error, not a headless department.
   - The office tree and the office page show a **No Head Yet** badge (decision 23).
   - The super admin's dashboard figure "departments without a head" already counts these departments. The head is
     named later through the head-change request (`operation=set`), or by running the import again with the head
     filled in (decision 15).
   - *Why:* a department must exist before counsel codes, keywords and the watchlist can map cases to it, and before
     recommendations can reach it. Its administrator can claim cases without a head. The headless state already
     exists after a head is ended.
   - *Default if the owner keeps the 26 Oct rule instead:* a headless department is reported as an error, it and its
     offices wait, and a later run creates them once the head is filled in. The import is built so that only
     `allow_no_head` changes.

10. **Matching what already exists, and never duplicating it.**
    - **Offices by code.** An existing code must have the same kind and the same parent; a different kind or parent
      is an error, because both are immutable. A different name is renamed to the workbook's name through
      `update_office` (audited `office.update`), so the State Portal names win (for example "Information Technology
      Department" becomes "Information Technology"). An inactive office matched by code is an error ("reactivate it in
      Administration first", because reactivation needs its head).
    - **Possible duplicates.** A new code whose normalised name equals an existing active office's normalised name
      under the same parent is an error naming that office. This is what stops `SCH-EDU` being created next to
      `SEC-EDU` (decision 24). Normalising: lower case, `&` read as "and", punctuation dropped, and a leading
      "department of" or trailing "department" dropped.
    - **Logins by e-mail** (exact, lower case). An existing login is used as it is: the import never changes its name,
      mobile, designation or password. "Already Has an ASLMS Login?" is cross-checked. "Yes" with no such login is an
      error. "No" when the login exists is a notice, and the existing login is used, as the Read Me promises.
    - **Memberships by (login, office, type).** An identical active membership is matched. Another active membership
      of that login in the same department is an error (`one_per_department`, decision 12).
    - **An existing department's head or admin is never replaced.** If the workbook names someone else, that is a
      notice ("the head differs: change it through Head Change"). The same person is matched.

11. **People: what each row needs.**
    - **A new login** needs Full Name (2 to 200 characters), Login E-mail (`EMAIL_RE`) and Designation. Mobile is
      optional because the first sign-in asks for it. A mobile that is given must pass `normalise_mobile` and is
      stored normalised.
    - **An existing login** needs only the e-mail and the designation for the new membership.
    - **Placeholders** from the Read Me example ("[name]@…", "[Head's Full Name]", "9XXXXXXXXX") are errors.
    - **One e-mail on several rows** (for example one officer heading two departments) is one person. If the rows give
      different names or mobiles for that e-mail, that is an error, so the wrong details are never stored.
    - **The Super Administrator's e-mail** is an error (`super_admin_single`).
    - **The office head's User Type** is required when an office head is given. It must be Department Officer
      (`dept_officer`) or Directorate User (`directorate_user`), matched by the type code, by its current `ref_role`
      label, or by the workbook's words "Directorate User". The current label of `directorate_user` is "Directorate
      Officer". Other types are an error.
    - **Designations** are matched by code or by name, without regard to case or spacing. A name not in the list is
      added, as the Read Me promises. `--apply` creates it with `offices.create_designation` (audited
      `designation.create`). The code is made from the name: upper case, `&` becomes `AND`, other non-alphanumerics
      become `_`, cut to 40 characters, with `_2`, `_3` added on a clash. The dry run lists each new designation and
      its code. A designation code is an ASLMS internal code, not an external identifier.

12. **The head and the admin cannot be the same person in one department (the existing rule; the workbook's Read Me
    is corrected).** The dry run reports it as an error: "a person holds one membership per department; name another
    administrator, or leave the Admin cells empty". If the owner wants the head to manage users too, the Super
    Administrator can later grant those functions to the head's membership as per-user overrides in Administration.
    The import does not do it, because a silent grant of user management is a decision for the owner each time.
    *Alternative:* the import grants the head membership the `_DEPT_ADMIN` functions automatically (it hides an access
    decision inside a data load).

13. **What counts as an error, a notice or a skip.**
    - **Errors** block `--apply` for the whole file. The run is all or nothing, in one transaction, so the database is
      never half imported.
    - **Notices** do not block. Examples: no administrator; the head or admin differs on an existing department; a
      "No" in Already Has a Login when the login exists; a missing mobile; a new designation; a name that will be
      renamed; a department created with No Head Yet.
    - **Skips:** Include? = No means left out. To Decide, or a blank Include? on a filled row, waits for the owner.
    - **Offices under a parent that is not being created:** an office whose parent department is "No" while the
      office says "Yes" is an error. An office whose parent waits (To Decide) waits too. The parent is named by the
      department name, as the dropdown gives it (matched after normalising spaces and case), or by its code. It is
      looked up among the Departments sheet's rows and the existing departments.
    - **The checks on every included row:**
      - the code against the new `OFFICE_CODE_RE` (decision 6);
      - the code unique across both sheets;
      - the code not a court's `ref_code`;
      - the type known, and the placement allowed for the parent's kind;
      - the path no longer than 400 characters;
      - the people (decision 11);
      - the membership rules (decision 12, `one_per_department`, one head and one admin per department);
      - duplicates in the file and against the database (decision 10).

14. **The order of `--apply`, inside one transaction.** The transaction takes
    `pg_advisory_xact_lock(hashtext('aslms_offices_import'))`, a transaction-level lock that is safe behind PgBouncer.
    It runs every check again inside the transaction and compares the fingerprint. Then:
    1. new designations;
    2. new logins, each as a login with no office yet (`create_user(role=None, office=None, password=None)`,
       decision 16);
    3. departments: `create_office` with `head={email, designation, designation_id}`, or with `allow_no_head`. A
       matched department is renamed if its name differs. A matched department with no head and a head in the row
       gets it through `offices.set_missing_head` (decision 15);
    4. first department admins: `add_department_admin`, extended to take an existing login (decision 17);
    5. offices under departments, in sheet order, through `create_office`;
    6. office heads, through `memberships.add` with the row's type and designation;
    7. one summary audit row (decision 19);
    8. commit, then the welcome e-mails (decision 18).

    The first membership a login receives becomes its primary (`insert_membership`). New offices get `notes` =
    "From the Assam State Portal department list. Website: <url>" (the website only when given). Your Remarks and the
    check columns are never stored.

15. **Running again does only what is missing.** A second `--apply` with the same workbook matches everything,
    writes nothing, prints "nothing to change" and writes no summary row. A filled-in head for a No Head Yet
    department, a newly included office or a new admin is applied by a later run. `offices.set_missing_head(session,
    actor, actor_user, office, head)` is `resolve_head` followed by `_set_head`. It answers `one_dept_head` when the
    department already has a head, so it never replaces one.

16. **New logins get no usable password.** `create_user` takes `password: str | None`. With None, it stores the
    argon2id hash of a random 48-byte secret from `secrets` that is never shown, logged or kept. The audit row
    `user.create` carries `password: "unset"`. Nobody can sign in with that login until the person sets a password
    through Forgot password?. `must_change_password` stays true until then, and the reset clears it (`by_self`). The
    portal and API forms keep requiring a password (unchanged). *Alternatives:* a sentinel hash that can never verify
    (a special case in `verify_password`); a new set-password link with its own token table (a second reset
    mechanism beside the code flow already built).

17. **`add_department_admin` takes an existing login.** It gains `user: User | None = None` and makes `password`
    optional.
    - With `user`, it adds the `dept_admin` membership through `memberships.insert_membership`, after the same checks
      as today (Department-tier office, active, no admin yet) and `access.assert_can_manage`.
    - Without `user`, the import first creates the login with no office (step 2 of decision 14), so in practice the
      import always passes `user`.
    - Either way it writes `office.admin_added` as today.
    - `POST /admin/offices/{code}/admins` is unchanged: it still creates a new login with the given password.

18. **The welcome e-mail is sent after the commit, one per new login, and audited.**
    - It is sent only after the transaction commits, so a rolled-back run never e-mails anyone.
    - New function `users.send_welcome(session_factory, mailer, settings, user)`. Subject "Your ASLMS Sign-In Is
      Ready". The body names the offices and user types the login now holds (office names, not codes) and gives the
      steps: open `<PORTAL_BASE_URL>/forgot`, enter this e-mail, enter the 6-digit code that arrives and choose a
      password; at the first sign-in confirm the profile and mobile number; every sign-in needs the password and a
      code sent to this e-mail.
    - The mail holds no password, no code and no link token.
    - Each attempt writes `user.welcome_sent` in a session of its own (`write_audit_apart`) with
      `{sent, reason}`. The reason is the exception class only; the mailer already scrubs secrets.
    - Before any write, `--apply` refuses (exit 4) when mail is not ready (`otp.ensure_mail_ready`), because the new
      logins could not sign in anyway. `--no-welcome` skips the mails for a run on purpose.
    - `aslms users welcome (--email ADDRESS | --pending)` sends again. `--pending` covers every login whose
      `user.create` row says `password: "unset"`, whose `password_changed_at` is still empty and that has no
      `user.welcome_sent` row with `sent: true`. Each send is audited the same way.
    - Existing logins that only gain a membership get no welcome mail; the membership is audited as today.

    *Alternatives:* the alerts outbox (the `alerts` CHECK allows a case-less alert only for `admin_ticket`, so it
    would need a new alert kind, a CHECK change and a sender branch, all for a one-off mail); sending inside the
    transaction (mails for logins a failed run never created).

19. **One audited run.**
    - Every audit row the run writes carries the same `user_agent`, `aslms offices import <run id>`. The run id is a
      UUID v7 made at the start, and `Actor` keeps `user_agent` through `actor_as`. The rows are `office.create`,
      `office.update`, `designation.create`, `user.create`, `ticket.approved` / `membership.added` for heads,
      `office.admin_added`, `membership.added` and `user.welcome_sent`. One filter on the audit log finds the whole
      run.
    - The summary row is `office_import.applied`, `entity_type` `office_import`, with `entity_id` and `row_id` set to
      the run id. Its `after` holds the file's sha256, the fingerprint, the counts (departments created / matched /
      renamed / no head yet, offices created / matched / renamed, logins created / matched, heads, admins, office
      heads, designations created, rows skipped by reason), the codes created and the ids of the logins created.
      E-mails, names and mobiles are left out of the summary; they appear only in the per-login `user.create` rows, as
      they do for every login today.
    - A dry run writes no audit row: it changes nothing.
    - `AUDIT_ACTIONS` in the frontend registry gains `office_import.applied` ("Offices Imported") and
      `user.welcome_sent` ("Welcome E-Mail Sent"). The no-head creation stays `office.create`.

20. **Personal details stay out of the output and the logs.**
    - The command prints problems as `Departments row 17, Head: Login E-mail: …` or `Offices row 88 (HFW-DME): …`.
      They give the sheet, the row, the column, the office code and the problem.
    - An e-mail is printed only masked (`mailer.mask_address`, for example `n***@assam.gov.in`), and only where the
      operator needs it to find the row. Names and mobiles are never printed.
    - Nothing from a row goes to the application log.
    - The workbook is read into memory and never written anywhere.
    - Tests build their workbooks in memory with made-up people (`@example.gov.in`, invalid-range mobiles in negative
      tests) and commit no spreadsheet.
    - `backend/tools/repo_policy.py::check_path` gains the rule `spreadsheet` for any `.xlsx`, `.xlsm` or `.xls`
      path, and `.gitignore` gains `*.xlsx`, `*.xlsm` and `*.xls`.

21. **New dependencies `openpyxl` and `defusedxml`**, as runtime requirements in `backend/pyproject.toml`
    (`"openpyxl>=3.1,<4"` and `"defusedxml>=0.7"`). The import runs in the `api` container, so the image needs them.
    They are added only with `python tools/deps.py lock` (runbook section 23), then `python tools/deps.py sync`,
    committing `uv.lock`, `requirements/image.txt` and `requirements/dev.txt`. The CI import smoke gains `openpyxl`.
    *Alternative:* parsing the xlsx XML by hand (fragile, more code to review).

22. **Exit codes:** 0 when done (or a dry run with no errors); 1 when the dry run found errors; 2 for a bad file;
    3 when the fingerprint does not match; 4 when mail is not ready; 5 when there is no super admin.

### Portal

23. **The No Head Yet badge.**
    - `OfficeNodeOut` and `OfficeDetailOut` gain `no_head: bool`. It is true only for an active Department-tier office
      at the department tier with no active `dept_head` membership. `office_tree` computes it with one extra query
      (the `departments_without_head` condition).
    - `Offices.tsx` shows the kit `Badge` (notice tone) "No Head Yet" beside the name in the tree and on the office
      page. The office page adds one line: "Name the head through a Head Change request", linking to the new-ticket
      form with the department chosen.
    - This is read-only, the visibility rules are unchanged, and no new endpoint is added.

### SEC-EDU

24. **SEC-EDU: keep the code and rename the office to "School Education" (recommended; option A). The owner may
    choose option B, a one-time audited code change to `SCH-EDU`, at approval.**

    **Impact, checked on the dev database on 14 Nov 2026** (read-only transaction; office id `01a177be-…47e2`, created
    26 Oct 2026). All 23 foreign-key columns that point at `offices` use the office's **id**, not its code. So a code
    change touches none of these rows:

    | Referencing rows (by id) | count |
    |---|---|
    | `user_memberships` (office and department; 1 head, 1 admin, 1 officer, all active) and `users.office_id` | 3 |
    | `case_ownership` (claimed, active) | 5 |
    | `recommendations` (2,121 recommended, 5 claimed) and `case_office_scores` | 2,126 each |
    | `custody` / `custody_history` | 5 / 10 |
    | `alerts.office_id` | 953 |
    | `counsel_codes` / `office_name_patterns` | 2 / 1 |
    | `admin_tickets.department_id` | 1 |
    | children, keywords, watchlist, case stages, notes, documents, transfers, closures | 0 |

    The code itself is stored as **text** in history that is never rewritten:

    | Text that holds `SEC-EDU` | count |
    |---|---|
    | `audit_log.actor_office_code` (18 actions: sign-ins, claims, assigns, assistant, counsel codes …) | 146 |
    | `audit_log` before / after JSON | 17 |
    | actor snapshots in the other 14 tables | 15 |
    | issued `ref_no` `ASLMS/SEC-EDU/TKT/2026/000001` and its `ref_sequences` row | 1 + 1 |
    | `events.payload` | 3,102 |
    | `alerts` title / body, `notifications` title / body | 944 / 1,099 |
    | `offices.path` (`GOA/SEC-EDU`; no descendants) | 1 |

    `SCH-EDU` is free (no office, no court code). In code, `SEC-EDU` appears only in frontend test fixtures
    (`e2e/fixtures/index.ts`, `OfficeName.test.tsx`), which do not depend on the database.

    - **Option A (recommended): keep `SEC-EDU`, rename to "School Education".** One `update_office` (audited
      `office.update`), done by the import when the Departments row says code `SEC-EDU` and name "School Education".
      The owner changes that row's Code cell from `SCH-EDU` to `SEC-EDU`. The duplicate check (decision 10) refuses
      `SCH-EDU` beside it if the cell is left as it is.
      - Since row 232 the portal shows office **names** in place of codes on every screen, so users see "School
        Education" everywhere.
      - Nothing is rewritten, nothing is lost from history, and no schema or code is added.
      - The only trace of the old wording is the code, seen by administrators and in reference numbers.
    - **Option B: a one-time audited code change.** `aslms offices rename-code SEC-EDU SCH-EDU [--apply]`, for the
      Super Administrator, dry run by default.
      - The command runs in one transaction under the office row lock. It checks the new code (decision 6 pattern,
        free among offices, courts and former codes). It sets `offices.code` and rewrites `offices.path` for the
        office and every descendant (prefix replace).
      - It adds a row to a new log table, `office_code_history` (Data). It writes audit `office.code_renamed` with
        before and after, and emits `config_changed`.
      - It never rewrites issued `ref_no`s, `ref_sequences`, actor snapshots, audit rows, event payloads, or alert and
        notification texts: those are records of what was true when they were written. The old ticket number keeps
        resolving because tickets are found by their exact `ref_no`, and new numbers start at
        `ASLMS/SCH-EDU/…/000001`.
      - To keep the 146 + 15 history rows findable and named, `GET /reference/offices` also returns each former code,
        mapped to its office (so `OfficeName` shows "School Education" for an old `SEC-EDU` snapshot), and the Audit
        Log office filter adds the former codes of the chosen offices to `actor_office_code IN (…)`.
      - `find_office` stays exact. A former code never names a new office: `create_office` refuses a former code.
      - **Costs of B:** one table, three services, one API field and a portal mapping, all for one office.
        `offices.code` stops being immutable (it is so only by service rule, and DB_STANDARD §0 rule 5 keeps the
        Secretariat code as the master's identifier). Every later "rename my code" request would have a precedent.
      - If B is chosen, it is built in this cycle and run once before the import.

    *Why A:* the visible goal, the State Portal's name, is met in full. The code is an internal identifier that people
    no longer read since row 232, and changing it touches identifiers already issued.

## Data

**Reference data: `ref_office_kind`.** The `schema.md` row "`ref_office_kind`, `ref_note_kind`, `ref_record_type`"
gains:

> (offices-import, migration 0036) `ref_office_kind` + `board_corporation` "Board / Corporation" (41),
> `statutory_authority` "Statutory Authority / Commission" (42), `society_mission` "Society / Mission / Project" (43),
> `institution` "Institution" (44), `local_body` "Local Body" (45), `autonomous_council` "Autonomous Council" (46),
> each with its description; `directorate` relabelled "Directorate / Commissionerate" (while unedited) with its
> description. All six sit under a department only, at the directorate tier; none is Department-tier.

**`offices`.** The `schema.md` row for `offices` gains, after "placement: …":

> (offices-import, migration 0036, no column change) placement adds `board_corporation`, `statutory_authority`,
> `society_mission`, `institution`, `local_body` and `autonomous_council` under department; unit also under each of
> them; codes created from 14 Nov 2026 are 2 to 17 characters (`^[A-Z0-9][A-Z0-9-]{1,16}$`) so every `ref_no` the
> office allocates fits `varchar(40)` and `ref_sequences.office_code varchar(20)`. A Department-tier office may exist
> without an active head (after a head is ended, or when created by `aslms offices import` with No Head Yet);
> `departments_without_head` lists them.

**Option B only: `office_code_history` (derived / log).** Written into `schema.md` Group 1 only if the owner chooses
option B:

> | `office_code_history` (derived / log) | id (uuid v7 PK), office_id (→ offices RESTRICT), old_code varchar(40) NOT NULL,
> new_code varchar(40) NOT NULL, reason text NOT NULL (≤ 500), renamed_at timestamptz NOT NULL default now(),
> actor_user_id (→ users SET NULL), actor_name, actor_designation, actor_office_code (the ActorSnapshotMixin),
> created_at | One row per code change of an office (design `offices-import`, option B; the one-time `SEC-EDU` →
> `SCH-EDU`). INSERT-only (trigger `aslms_forbid_change`). Unique `old_code` (a former code is never reused);
> index `ix_office_code_history_office_id`. CHECK `ck_office_code_history_differs` (old_code <> new_code). Grants:
> ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT to `aslms_app`. Read by `GET /reference/offices`
> and the audit office filter so old snapshots keep their office's name. |

`old_code` is `varchar(40)` because existing codes may be up to 40 characters under the old rule.

**Migration `0036_office_kinds.py`**, a new reference-data migration. It takes the next free number at build time:
0036 if this cycle merges before rows 189 and 209, which have reserved "the next free number". Applied migrations are
never edited. It is hand-written, with rows hard-coded and no application import (the precedent of 0016, 0030
and 0034):
1. Insert the six `ref_office_kind` rows with label, description and sort order, `ON CONFLICT (code) DO NOTHING`.
2. `UPDATE ref_office_kind SET label = 'Directorate / Commissionerate', description = … WHERE code = 'directorate' AND
   label = 'Directorate'`.
3. Option B only: create `office_code_history` with its comment `class=derived`, index, CHECK, unique, the
   `aslms_forbid_change` trigger and the grants.

There is no `audit_log` row (the 0016 precedent). **Downgrade** refuses while any `offices` row uses a new kind
(restore needed, runbook section 6), and with option B while `office_code_history` has a row. Otherwise it deletes the
six rows, restores the "Directorate" label if it is still the new one, and drops the table under option B.

**Seed** (`services/seed.py`): `OFFICE_KIND_COLUMNS` (label, description, sort order) for all eight non-State kinds,
used by `_extra_columns` for `RefOfficeKind`. The same unedited-label relabel of `directorate` (`_relabel_office_kinds`,
the shape of `_relabel_note_kinds`). The seed's `DESIGNATIONS` list is unchanged; designations the import adds live
in the database like those added in Administration.

No other table or column changes. The welcome mail, the run correlation and the badge need no schema.

## Services

- **`domain/reference.py`**: `OfficeKind` + `BOARD_CORPORATION`, `STATUTORY_AUTHORITY`, `SOCIETY_MISSION`,
  `INSTITUTION`, `LOCAL_BODY`, `AUTONOMOUS_COUNCIL` (in that order, after `DIRECTORATE`).
- **`services/offices.py`**:
  - `PLACEMENT`, `DELEGABLE_KINDS` and `OFFICE_CODE_RE` as decisions 2, 4 and 6;
  - `NEW_KIND_PARENTS` exported for the labels API (`parents`);
  - `create_office(..., allow_no_head=False)`, decision 9;
  - `set_missing_head`, decision 15;
  - `add_department_admin(..., user=None, password=None)`, decision 17;
  - `office_tree` and `OfficeNode` carry `no_head`, decision 23;
  - `normalised_name(name)` for the duplicate check, decision 10;
  - `designation_code_from_name(name, taken)`, decision 11.
- **`services/users.py`**: `create_user(..., password: str | None)`, decision 16; `send_welcome(...)` and
  `welcome_pending(session)`, decision 18.
- **`services/refno.py`**: `REF_NO_RE` as decision 6.
- **`services/reference.py`**: `office_kinds` items with `description` and `parents`.
- **New `services/offices_import.py`**:
  - `read_workbook(data: bytes) -> Workbook`: the two sheets as typed rows with their sheet and row numbers
    (decision 8). It raises `ImportFileError` for a bad file.
  - `check(session, wb) -> ImportPlan`: every problem (`Problem(sheet, row, column, code, severity, message)`, with
    severity `error`, `notice` or `skip`), the planned actions, and the counts. Problem codes: `bad_code`,
    `code_too_long`, `duplicate_code_in_file`, `code_taken`, `court_code`, `possible_duplicate`, `kind_unknown`,
    `placement`, `kind_mismatch`, `parent_mismatch`, `office_inactive`, `parent_left_out`, `parent_waiting`,
    `head_partial`, `person_incomplete`, `bad_email`, `bad_mobile`, `bad_name`, `placeholder`, `person_conflict`,
    `login_missing`, `login_exists`, `login_inactive`, `super_admin_single`, `same_person_head_admin`,
    `one_per_department`, `type_unknown`, `type_not_allowed`, `designation_new`, `head_differs`, `admin_differs`,
    `no_admin`, `no_head_yet`, `rename`, `no_mobile`, `include_no`, `include_wait`. The checks are read-only queries.
  - `fingerprint(data, plan) -> str` (12 hex characters).
  - `apply(session, actor, actor_user, wb, *, expect, run_id) -> ImportResult`, in the order of decision 14, entirely
    through `offices`, `memberships`, `users` and `tickets`, with no SQL of its own except the advisory lock. It
    raises `PlanChanged` on a fingerprint mismatch, and `ImportErrors` if errors appear on the re-check. It writes the
    summary audit row (decision 19).
  - Rules enforced: decisions 9 to 17. Audit and events: those of the services it calls, plus
    `office_import.applied`. Office writes emit `config_changed` as today.
- **Option B only, `services/offices.py::rename_code(session, actor, actor_user, office, new_code, reason)`** and
  `former_codes(session) -> dict[str, Office]`; `services/reference.py` and `services/audit_search.py` read the former
  codes as decision 24 describes.
- **CLI**:
  - `cli/offices.py` `import` (decisions 7, 20 and 22; prints with `rich`, with masked e-mails);
  - `cli/users.py` `welcome` (decision 18);
  - option B: `cli/offices.py` `rename-code`.
- **Frontend**:
  - `components/admin/Offices.tsx`: kinds filtered by parent, the kind description hint, the No Head Yet badge and
    line;
  - `components/admin/mapping/Watchlist.tsx`: kinds from the labels;
  - `lib/api/schema.d.ts` regenerated;
  - the `AUDIT_ACTIONS` entries (decision 19);
  - `test/render.tsx` labels.
- **Docs**:
  - `docs/operations.md`: a new section "Importing offices from the workbook", covering the stdin command, dry run,
    fingerprint, backup first (`aslms ops backup`), `--apply`, Mailpit in development, `aslms users welcome
    --pending`, and keeping the workbook out of the repository;
  - `schema.md` as Data;
  - the decisions log (the scribe);
  - the workbook builder's Read Me lines about codes ("2 to 17 characters") and about head and admin ("must be two
    different people") are corrected in the scratchpad script for the owner's next copy. The script is not in the
    repository.

## API

No new endpoint. The changes are additive and read-only:

| Method and path | Function (`Permission`) | Change | Visibility |
|---|---|---|---|
| `GET /reference/labels` | signed in (unchanged) | `office_kinds[]` gains `description: str \| null` and `parents: list[str]` | reference data, as today |
| `GET /admin/offices/tree` | `users.view` (unchanged) | each node gains `no_head: bool` | the caller's scope, as today |
| `GET /admin/offices/{code}` | `users.view` (unchanged) | gains `no_head: bool` | the caller's scope, as today |
| `POST /admin/offices` | `offices.manage` (unchanged) | `code` at most 17 characters (`max_length=17`); `kind` accepts the six new codes | unchanged |
| `GET /reference/offices` (option B only) | signed in (unchanged) | items gain `former_codes: list[str]` | as today |

`head_required` stays for `POST /admin/offices` and `POST /admin/offices/{code}/reactivate`.
`POST /admin/offices/{code}/admins` is unchanged (it still takes a password).

The import and the welcome command are command-line only. They act as the Super Administrator and need
`offices.manage`, `users.create` and `admin.designations` through the services.

## Jobs

None. The import is an operator command. The welcome mails are sent by the command after its commit, not by a
queued job.

## Tests

Unit (`backend/tests/`):
- `test_offices_import_read.py`
  - `test_reads_sheets_by_header_text_not_letter`: an extra column inserted before Code still reads.
  - `test_missing_header_refuses_file`.
  - `test_refuses_non_zip_and_oversize`.
  - `test_formula_columns_ignored`.
  - `test_mobile_number_cell_read_as_digits`.
  - `test_cells_trimmed_and_nbsp_collapsed`.
  - `test_empty_rows_skipped`.
- `test_offices_import_rules.py` (pure checks against a faked lookup):
  - `test_code_pattern_and_17_char_limit`;
  - `test_duplicate_code_across_sheets`;
  - `test_placeholder_values_refused`;
  - `test_same_email_different_name_is_error`;
  - `test_partial_head_is_error`;
  - `test_include_no_and_to_decide_skip`;
  - `test_office_under_left_out_department_is_error`;
  - `test_user_type_aliases`;
  - `test_designation_code_from_name`;
  - `test_normalised_name`.
- `test_refno.py`: `test_parse_ref_no_accepts_hyphenated_office`.
- `test_users.py`: `test_welcome_mail_has_no_password_code_or_token`.

Database (`backend/tests/db/`, the scripted gateway is not needed):
- `test_office_kinds.py`
  - `test_new_kinds_placed_under_department_only`;
  - `test_unit_under_each_new_kind`;
  - `test_new_kinds_are_directorate_tier_and_inside_department_visibility`: a department officer sees a case owned at
    the department and an office under a Board (path rule);
  - `test_department_admin_may_create_new_kinds_in_own_subtree`;
  - `test_new_kinds_never_department_tier` (`is_department`, `department_of`, matching's department list);
  - `test_office_code_over_17_refused_portal_and_cli`.
- `test_offices_import.py`
  - `test_dry_run_writes_nothing`: row counts of `offices`, `users`, `user_memberships`, `designations` and
    `audit_log` are unchanged.
  - `test_apply_creates_departments_heads_admins_offices_and_office_heads`: one transaction. Audit rows share the run's
    `user_agent`, and one `office_import.applied` row is written.
  - `test_apply_refuses_without_matching_fingerprint`.
  - `test_apply_refuses_when_any_error`: nothing is written.
  - `test_second_apply_changes_nothing`: no new rows and no summary row.
  - `test_existing_login_reused_never_duplicated`, and the "Already Has Login" cross-checks.
  - `test_existing_office_matched_and_renamed_kind_or_parent_mismatch_refused`.
  - `test_possible_duplicate_by_name_refused` (the `SEC-EDU` / `SCH-EDU` case).
  - `test_head_and_admin_same_person_refused`.
  - `test_office_head_in_department_where_person_already_member_refused`.
  - `test_existing_department_head_never_replaced`.
  - `test_no_head_yet_department_created_only_by_import`: `POST /admin/offices` still answers 400 `head_required`.
  - `test_no_head_yet_then_head_filled_by_second_run` (`set_missing_head`).
  - `test_new_designation_created_and_audited`.
  - `test_new_login_has_unusable_password_and_must_change`: the login cannot sign in, and reset then sign-in works.
  - `test_welcome_sent_after_commit_only`: a forced failure mid-apply sends no mail (`RecordingMailer` is empty).
  - `test_welcome_failure_audited_and_resent_by_pending`.
  - `test_apply_refuses_when_mail_not_ready_unless_no_welcome`.
  - `test_output_has_no_names_or_mobiles`: captured stdout holds no name and no mobile from the workbook, and only
    masked e-mails.
- `test_api_offices.py`: `test_tree_and_detail_no_head_flag`; `test_labels_office_kinds_description_and_parents`.
- `test_migration_0036.py`: up inserts six kinds and relabels an unedited directorate; an edited label is kept; down
  refuses while an office uses a new kind; up, down, up on an empty table.
- `test_seed_and_refno.py`: the seed and the migration agree on labels, descriptions and sort orders.
- Option B only, `test_office_code_rename.py`:
  - `test_rename_rewrites_code_and_descendant_paths_only`: ids, `ref_no`s, snapshots and audit rows are unchanged;
  - `test_former_code_resolves_in_reference_offices_and_audit_filter`;
  - `test_former_code_never_reused`;
  - `test_rename_audited`.
- `backend/tools` policy tests: `test_spreadsheet_paths_refused`.

Frontend (`vitest`):
- `Offices.test`: the kind options follow the parent; the description hint; the No Head Yet badge and line.
- `mapping.test`: the Watchlist picker offers a Board office.
- `audit` registry: the two new action names.

## Verification

The integrator, on the branch, then on `main` after the merge:
1. `python tools/deps.py check` is clean. `ruff check` is clean. `pytest -q` is green. The frontend `vitest`, `tsc`
   and `lint` pass. `docker compose build` passes with the import smoke (`import openpyxl, defusedxml`).
2. `aslms ops backup` of the dev database, then `migrate` to 0036. Run read-only:
   `SELECT code, label, sort_order FROM ref_office_kind ORDER BY sort_order` gives 12 rows, with the six new codes at
   41 to 46 and `directorate` labelled "Directorate / Commissionerate".
3. **Dry run on the owner's workbook:**
   `docker compose exec -T api aslms offices import - < "Claude outputs/ASLMS_Offices_From_State_Portal.xlsx"`.
   - It exits 0 or 1 and prints problems by sheet, row and column with masked e-mails only, then the plan and the
     fingerprint.
   - Before and after counts of `offices`, `users`, `user_memberships` and `audit_log` are equal (5, 8, 8 and
     unchanged).
   - The dry-run output goes to the owner. **No `--apply` without the owner's approval of that listing.**
4. After the owner's approval: `… import - --apply --expect <fingerprint>`.
   - `offices` grows by the planned departments and offices.
   - Each new login has one Mailpit message "Your ASLMS Sign-In Is Ready" and a `user.welcome_sent` row with
     `sent: true`.
   - The Audit Log filtered on the run's user agent shows the run, with one `office_import.applied` row.
5. Running the same command again with the new dry-run fingerprint answers "nothing to change". No rows are added.
6. One new login (a test address in Mailpit) uses Forgot password?, receives the code, sets a password, signs in with
   the e-mailed code, confirms the profile, and sees its department's cases.
7. In the portal at http://localhost:3000:
   - Administration → Offices shows the new types and labels.
   - Under a department, the New Office form offers the six new types and Unit, but not Department.
   - A No Head Yet department shows its badge, and the Head Change request named on its page clears the badge.
   - The Watchlist picker offers an office of a new type.
8. SEC-EDU, option A: the office page shows "School Education" with code `SEC-EDU`, and the 5 claimed cases, 2,126
   recommendations and 3 memberships are unchanged.
   Option B: `aslms offices rename-code SEC-EDU SCH-EDU` dry run, then `--apply`. The path is `GOA/SCH-EDU`. An
   Audit Log filter on School Education still lists the 146 older rows, and the ticket
   `ASLMS/SEC-EDU/TKT/2026/000001` still opens.

## Open questions

None block the build. Three decisions carry a default the owner confirms or changes at approval:
- **Decision 9, a department with no head yet** (a deviation from the owner's answer of 26 Oct 2026). Default:
  allowed only through the import, with a No Head Yet badge, named later by Head Change or a second run. Alternative:
  keep `head_required` everywhere; such departments and their offices wait.
- **Decision 24, SEC-EDU.** Default: option A, keep `SEC-EDU` and rename the office to "School Education" (the
  workbook's Code cell becomes `SEC-EDU`). Alternative: option B, the one-time audited code change to `SCH-EDU` with
  `office_code_history`, built in this cycle.
- **Decision 12, head and admin the same person.** Default: refused, as the one-membership-per-department rule
  already says. The owner names a different administrator or leaves Admin empty, and may grant the head the admin
  functions per user afterwards.

## Deviations

Written by the developer during the build (14 Nov 2026). None changes a rule of the design; each is the smallest
choice where the design was silent.

1. **Problem code `parent_unknown`** (decision 13). An office whose Parent Department is neither a Departments-sheet
   row nor an existing department is an error with this code; the design's list had no code for it.
2. **"Partly filled" person** (decisions 9 and 11). A person whose cells are partly filled is an error only when a cell
   the person needs is empty: the e-mail and the designation always, the full name for a new login. Mobile and
   "Already Has an ASLMS Login?" may be blank, since decision 11 makes the mobile optional (a `no_mobile` notice). The
   code is `head_partial` for a department head and `person_incomplete` for an administrator or office head.
3. **Include? values.** Anything other than Yes or No (To Decide, blank, or an unknown word) makes the row wait
   (`include_wait`).
4. **Placeholders** (decision 11) are recognised as a cell holding both `[` and `]`, four or more X's in a row, or `…`.
5. **Kind descriptions.** Only the seven kinds the design gives text for (the six new ones and `directorate`) carry a
   description, in the migration and the seed alike; `department`, `central`, `advocate_general` and `unit` keep none,
   so a fresh seed and a migrated database stay identical. The New Office form falls back to its general hint.
6. **`POST /admin/offices` with a code over 17 characters** answers 422 from `max_length=17` (decision 6), before the
   service's message; `aslms offices create`, the import and the service give the message "2 to 17 characters …".
7. **`users.send_welcome(..., *, actor=None)`** takes the acting Super Administrator so the `user.welcome_sent` rows
   carry the run's user agent (decision 19). The commit-then-mail order lives in a service function
   `offices_import.run_apply(session_factory, wb, *, expect, run_id, mailer, settings)` used by the command and the
   tests; `import_actor` gives the Super Administrator with the run's user agent.
8. **The dry run also needs the Super Administrator** (exit 5), as `--apply` does, since the command acts as them.
9. **The Watchlist picker's kinds** come from the labels (decision 5); until they have loaded, from the generated
   `enumCodes.json` list of `OfficeKind`, so the State root is never offered.
10. **The No Head Yet badge** uses the kit's `warning` tone (the kit's tones are danger, warning, success and info).
11. **A kind the new parent does not accept** is cleared from the New Office form when the parent changes.
12. **Test files.** The seed-and-migration agreement is `test_seed_and_migration_agree` in `test_migration_0036.py`
    (beside the other 0036 cases) rather than in `test_seed_and_refno.py`; the Offices tests are in
    `frontend/src/components/admin/officeKinds.test.tsx`; the workbooks are built in memory by
    `backend/tests/offices_workbook.py`. Two existing tests follow the new rules: `test_offices_rules.py` (17-character
    codes, the placement table and the delegable kinds) and `test_migration_0033.py` (0036 is the single head); the
    admin test choosing a Directorate under a directorate now chooses a Unit, the only kind offered there.
