# Design: Portal UI polish 2 — Title Case labels, full user-type names, Edit Name, the expanding side menu, Filter Layout B, the Office Picker, the User Details modal, a simpler Department Mapping and the dashboard greeting

```
slug: portal-ui-polish-2
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25, with the recommended answers to open questions 1-7 (View Cause List modal as designed; Department Mapping a page under Administration; reference values not Title Cased here; overrides shown on Scoring; no Sign Out Everywhere; plan wording for descriptions; three rounds)
```

## Context
The owner approved the mockup `docs/design/ui/aslms-nav-template.html` on 25 Oct 2026. It is the **visual reference**
of this note. Its screens are Dashboard, Case Inbox, Case Page, Assistant, Administration, User Details, Filter
Layouts and Label Style. The owner's choices, fixed and not reopened here:

1. Title Case for every label.
2. Full user-type names.
3. Edit Name for user types.
4. An expanding side menu. **Revised on 25 Oct 2026: one level only** (decision 14).
5. Filter Layout B, "Header Card with Two Zones", plus a "View Cause List" modal.
6. The Office Picker in place of every typed office code.
7. The checkbox alignment rule, and the Users filter as the one-line toolbar.
8. The User Details modal.
9. A simpler Department Mapping.
10. The dashboard greeting and the view switch.

**Where the mockup and this note differ, this note wins.** Specifically:
- **The menu's deeper levels are superseded.** The mockup lists the ten user types under User Types, each with its
  function groups, and the office tree under Offices. The owner's change of 25 Oct 2026 removes them (decision 14).
- **Sample data stays sample.** This covers the mockup's figures, people, offices, "Case Claim" count, type
  descriptions and the scoring signal "Past Ownership". The system's five weights (`counsel_code`, `name_pattern`,
  `watchlist`, `linked_case`, `keyword`) and the plan's Table 1 wording win.
- **The mockup's Users list shows the designation where the name goes.** That is anonymised sample data. The list
  keeps the person's name over their post (row 135).
- **"Sign Out Everywhere" in the user's More menu is not built.** There is no API for it (decision 37).

**What is in place and reused.**
- **Strings.** `frontend/src/lib/messages.ts` (`T`, about 2,900 lines) holds every user-facing string. The wording
  guard `lib/wording.test.ts` (row 135) keeps custody words out.
- **Navigation.** `lib/routes.ts` declares the navigation: `NAV` (groups Work, Oversight and Settings, functions,
  `show`, counts), `ADMIN_TABS`, `MAPPING_TABS`, `DATA_TABS`, `navGroupsFor`.
- **The shell.** `components/shell/PortalShell.tsx` holds the sidebar, the phone drawer below 820 px with its focus
  trap, and the bottom bar.
- **Row 152 (case-inbox-merge, approved, building first).** It removes the "Cases" entry and makes the bottom bar
  Dashboard, Case inbox and Alerts. **This item is built on top of row 152.**
- **Motion.** `components/ui/motion.ts`: `DURATION.med` = 220 ms, tokens at 0 ms under reduced motion,
  `usePrefersReducedMotion`.
- **The kit.** `Modal` (1040 px, full screen on phones), `Dialog`, `ConfirmDialog`, `SidePanel`, `Menu`, `Tabs`,
  `DataTable` (cards on phones), `CheckField`, `Switch`, `SegmentedField`, `Collapsible`, `SettingsLayout`, and
  `useUrlOverlay` (Back closes).
- **User types.** `ref_role` (code PK, label varchar(120), description NULL today, sort_order, is_active). The seed
  inserts `_label(code)`: "Super admin", "State oversight", "Dept head", "Dept admin", "Dept officer",
  "Directorate user", "Referral reviewer", "Standing counsel", "Central operator", "Auditor". `GET /reference/labels`
  returns `user_types[] {code, label, description, assignable}`, and every screen reads labels from it.
- **Function labels.** `PERMISSION_LABELS` in `services/access_seed.py` holds them. The seed upserts them into
  `ref_permission` on every `init`.
- **The access API.**
  - `GET /admin/access/overview`, `/defaults`, `/types`, `/types/{role}`;
  - `PUT /admin/access/types/{role}` (the batch) and `PUT /admin/access/types/{role}/{permission}`, both
    `access.manage_types`, each change audited `access.matrix`.
- **Offices.** `GET /offices` and `GET /offices/tree` need `users.view` and return the caller's scope
  (`_scope_roots`). Mapping writes check `access.in_scope(…, permission=P)`. The reports catalogue `GET /reports`
  already names the departments a reporter may choose.
- **Users and memberships.**
  - `GET /admin/users` (`office` is always a subtree; `include_ended`);
  - `GET/PATCH /admin/users/{id}`, `enable` / `disable`, `password`;
  - `GET /admin/users/{id}/permissions` and `PUT …/permissions/{p}`;
  - `GET/POST /admin/users/{id}/memberships`, `PATCH`, `exit-preview`, `end`, `reactivate`, `primary-membership`;
  - the membership documents;
  - the components `UserDetail.tsx` (`LoginCard`, `MembershipTable`, `ChangeMembership`, `AddMembership`,
    `ExitDialog`, `MembershipFunctionsPanel`, `MembershipDocuments`) and `Users.tsx` (the list, the `?user=` side
    panel, `NewUserForm`).
- **Audit.** `GET /audit?user=<id>` is for State-wide `audit.view` holders only (`readsAudit`).
- **Mapping.** `/admin/counsel-codes` (+ `/unmapped`), `/admin/keywords`, `/admin/name-patterns`,
  `/admin/watchlist`, `/admin/scoring-settings` (+ `/history`):
  - each rule has an optional `weight` override, settable only with `admin.scoring`;
  - counsel codes also have `notes`; on update, `notes` left out means no change and `weight` left out means
    `UNSET`.
- **Cause lists.** `GET /causelists/dates`, `/{date}` (benches and lists), `/{date}/entries?bench_id=…`, and
  `/lists/{id}/file?disposition=inline|attachment` (`documents.view` / `documents.download`).
- **Dashboard.** `components/dashboard/Headline.tsx` (`greeting`, `greetingLine`, `hasPersonalWork`) and
  `Dashboard.tsx` (views from `GET /dashboard`; a State-wide reader without personal work already opens on State).
- **uicheck.** `frontend/e2e/`: Playwright at 375, 768 and 1280 px, every route, fixtures synthesised from OpenAPI
  plus typed overrides, and the geometry checks in `checks.ts`, including the field-row check of 23 Oct 2026, which
  today skips checkboxes.

**The plan.** It fixes the functions, not the screen words. Two items touch wording the plan uses:
- **The user-type names** (Table 1: "State oversight", "Department head", "Department admin", "Department officer",
  "Directorate user", "Standing counsel", "Central operator", "Auditor"). Decision 10 is a **deviation (wording
  only)**.
- **Title Case** is not in the plan. It is a style rule.

No business rule, visibility rule or function changes. The one exception is the new Edit Name write (decision 12),
behind the existing `access.manage_types`.

**Interactions with other rows.**
- **Row 152** builds first. Its new strings ("Sent by me", "Pending action", "With my offices") get Title Case here.
- **Row 154 (partial-code-match)** is being designed separately. If it adds a migration, numbers are coordinated
  (decision 11).
- **Row 150** (user-types page advisories) and **row 151** (uicheck after row 135) touch the same files. Whichever
  merges second rebases. Neither changes a decision here.

**Not covered.**
- **Reference-data values** shown as option names or badges keep their stored text: case stages, note kinds,
  document types, pending actions, alert kinds and ticket kinds (open question 3).
- Excel and PDF export headers, e-mail subjects and bodies, CLI output and OpenAPI summaries.
- The menu entries Case Inbox, Case Claim, Alerts and Assistant do not expand. Their tabs stay on their pages.
- No other menu level, no new function, no new table or column. One reference-data migration only.

## Decisions

### A. Title Case labels (item 1)

1. **The rule.** It is the owner's rule, exactly:
   - **Labels use Title Case.** Labels are navigation entries, tabs, buttons, card titles, column headers, field
     labels, section headings, badges and chips. The mockup's badges are in Title Case: "Sign-in Off", "Changed From
     Default", "Given to This Person".
   - **Short joining words stay lower case unless they come first or last:** a, an, the, and, or, of, by, to, in,
     on, for, at, with. So "Sent by Me", but "Working On".
   - **Every other word is capitalised**, "From" and "Without" included.
   - **Acronyms stay in capitals:** ASLMS, CNR, NAPIX, PDF, API(s), OTP, IST, URL, ID, SMS, CSV, AI, JSON, IP, NJDG.
   - **Sentences keep sentence case:** hints, notices, descriptions, empty states, placeholders, tooltips, error
     messages, confirmations and alert text.
2. **One helper, written twice, with the same examples.**
   - **Frontend:** `frontend/src/lib/titleCase.ts` exports `titleCase(text)`, `isTitleCase(text)` (=
     `titleCase(text) === text`), `SMALL_WORDS` and `ACRONYMS`.
   - **Backend:** `backend/aslms/core/titlecase.py` has the same rule (`title_case`, `is_title_case`). It is used only
     by tests and the seed's own checks. **Nothing typed by a person is ever re-cased by the server.**
   - **The algorithm:**
     1. Split the text into segments at " · ", " / ", " — ", " – " and ": ", keeping the separators. Each segment
        has its own first and last word.
     2. In a segment, split on spaces.
     3. For each word, take the core: the word without leading and trailing punctuation (`( [ " ' “ ‘` and
        `) ] " ' ” ’ , ; . ! ?`).
     4. A core that holds a digit, or a capital after its first character (an acronym, `WP(C)`, `cURL`, `eCourts`),
        is kept as written.
     5. A core whose lower case is in `ACRONYMS` is written in capitals.
     6. A core in `SMALL_WORDS` that is neither the first nor the last word of its segment is written in lower case.
     7. Any other word gets its first letter in capitals and the rest unchanged. So a hyphenated word capitalises
        only its first part: "Sign-in", "E-mail", "Office-only", "Sub-offices", as in the mockup.
   - **Examples pinned in both test suites:**
     - the mockup's Before and After table: "Case inbox" → "Case Inbox", "Sent by me" → "Sent by Me", "Send case" →
       "Send Case", "user types" → "User Types", "Napix call log" → "NAPIX Call Log";
     - "Working on" → "Working On";
     - "Search the court" → "Search the Court";
     - "Include logins without an active office" → "Include Logins Without an Active Office";
     - "Court search / discovery" → "Court Search / Discovery".
3. **Every label in `messages.ts` is rewritten once** (round 1, decision 46). Where needed, the developer runs the
   helper over the label paths (decision 4) and checks each result by eye.
   - **Labels built from parts** are written as Title Case templates, for example `count(label, n)`.
   - **Sentences are left alone.** The only exception is user-type names written in full inside sentences
     (decision 10).
   - **Tests that name an element by its text** (`getByRole("button", { name: "Send case" })`) are updated in the
     same change. This includes the uicheck interaction states ("Send case" → "Send Case", "Remarks and notes" →
     "Remarks and Notes", "Open full page" retired by decision 31).
4. **A vitest keeps it from drifting:** `frontend/src/lib/labels.test.ts`, with its rules in
   `frontend/src/lib/labelRules.ts`.
   - **The walk.** The test walks `T` and collects every string leaf with its dotted path.
   - **Label paths** (`LABEL_PATHS`):
     - `nav.**`, `tabs.**`, `crumbs.**` and `crumbPaths.**`;
     - any path whose last key matches `/^(title|heading|label|button|tab|badge|chip|column|col|field|section)$/` or
       ends in `Title`, `Heading`, `Label`, `Button`, `Tab`, `Badge`, `Chip`, `Col`, `Column`, `Field`, `Section`;
     - any path whose parent key is one of `cols`, `columns`, `fields`, `buttons`, `badges`, `statuses`, `tabs`,
       `headings`, `labels`, `titles`.
     - **Every label path must pass `isTitleCase`.**
   - **Sentence paths** (`SENTENCE_KEY`): a last key matching
     `/(hint|help|placeholder|description|desc|note|notice|empty|body|message|error|confirm|intro|subtitle|tooltip|aria|explain|why|detail)/i`,
     or starting with `no`, `none` or `nothing`. They are not checked.
   - **Everything else is unclassified.** An unclassified string that looks like a label (6 words or fewer, no final
     `. ? ! :`, no `{` or `%`) must pass `isTitleCase`, unless its path is listed in `SENTENCE_EXCEPTIONS` (path →
     one-line reason). That is how a new short string must declare itself.
   - **Functions.** Function values under label paths are called with the sample arguments listed in
     `LABEL_FUNCTIONS` (path → args), and the result is checked. Other functions are skipped.
   - **The test also fails on a stale entry:** an exception or a function path that no longer exists.
   - Alternative: restructure `T` into `labels` and `sentences`. Refused: it would rewrite 2,900 lines and every
     import for no user benefit.
5. **Server-held labels follow the rule too.**
   - **Function labels.** The first element of each `PERMISSION_LABELS` tuple becomes Title Case, for example "Track
     Pending and Overdue Cases" and "Read Office-only Notes", as in the mockup. Descriptions stay sentences. The
     function group labels of `PermissionOut` (row 135) also become Title Case.
     - These need no migration: the seed upserts `ref_permission` on every `init` (DB_STANDARD §0; the row 135
       precedent).
     - A pytest asserts `is_title_case` for every function label and group label.
   - **User-type labels** change by migration (decision 11). A pytest asserts that the seeded labels pass
     `is_title_case`.
   - **Labels an administrator types are not forced.** Edit Name shows the hint "Use Title Case, as the other names
     do." (decision 13) but accepts the text as typed.
6. **Not a uicheck rule.** A browser-side case check would flag case numbers, party names and reference values as
   false positives. The vitest and the pytest are the guard.

### B. Full user-type names (item 2)

7. **Display names, codes unchanged.**

   | Code (never changes) | Seeded label today | New label |
   |---|---|---|
   | `super_admin` | Super admin | Super Administrator |
   | `state_oversight` | State oversight | State Oversight Officer |
   | `dept_head` | Dept head | Head of Department |
   | `dept_admin` | Dept admin | Department Administrator |
   | `dept_officer` | Dept officer | Department Officer |
   | `directorate_user` | Directorate user | Directorate Officer |
   | `referral_reviewer` | Referral reviewer | Referral Reviewer |
   | `standing_counsel` | Standing counsel | Standing Counsel |
   | `central_operator` | Central operator | Central Operator |
   | `auditor` | Auditor | Auditor (unchanged) |

8. **Short descriptions are seeded from the plan's Table 1** (the `access_seed.py` docstring), because
   `ref_role.description` is NULL today and the type cards show it. Each is at most 200 characters, and the owner may
   change any of them with Edit Name:
   - `super_admin`: "Holds every function and manages access for the whole State."
   - `state_oversight`: "Read-only view of all cases, with the State dashboards and reports."
   - `dept_head`: "All cases of the department and its directorates, with approvals and oversight."
   - `dept_admin`: "Manages the department's users, counsel codes and keywords; reviews recommendations and claims
     cases."
   - `dept_officer`: "Works on allotted cases: moves the case, adds notes and documents, and receives alerts."
   - `directorate_user`: "Works on the cases of their own directorate."
   - `referral_reviewer`: "Reviews cases with a department officer's reviewing functions, without ownership or the
     case's movement."
   - `standing_counsel`: "Cases they appear in, with the notes and documents shared with counsel."
   - `central_operator`: "Looks after unclaimed cases and data quality."
   - `auditor`: "Read-only case records and the audit log."

   Alternative: the mockup's descriptions. Refused: they are sample text, and some claim functions the matrix does
   not give (open question 6).
9. **Where the names appear.**
   - Every screen already reads `/reference/labels`, so badges, selects, type cards and the user-type page follow the
     database with no code change.
   - The only work is to drop the stale label cache after Edit Name (decision 13).
10. **Names in sentences.** User-facing sentences that name a type write it in full, as the owner's Label Style
    screen asks ("Department Administrator, not Dept admin"). This applies to:
    - `messages.ts` (for example "Only the super admin may do this." → "Only the Super Administrator may do
      this.");
    - the `PERMISSION_LABELS` descriptions;
    - the API error messages a person can read (the portal falls back to them);
    - e-mail text that names a type.

    These sentences use the default names; they do not follow a later Edit Name. That is acceptable, because the
    owner renames rarely, and the screen labels do follow.
    - Docstrings, comments, log lines and CLI help are not required to change.
    - **Deviation (wording only)** from the plan's Table 1 names, which are the owner's choice. No function changes.
11. **One reference-data migration**, numbered **at build time as the next free number after 0025**. The number is
    **0026** if this item's migration lands first.
    - **Row 154 (partial-code-match)** is being designed now. If it also needs a migration, whichever merges second
      takes the next number and records it. No number is reserved in advance, which is the precedent of rows 122 and
      135.
    - It is written by hand, as 0016 and 0025 were.
    - **Upgrade:**
      1. Each label changes only while it still holds the seeded text in the table above (`WHERE code = :code AND
         label = :old`), so a label an administrator changed is left alone.
      2. Each description is set only `WHERE description IS NULL`.
      3. It creates the unique index `uq_ref_role_label_lower` on `lower(label)`. This comes after the updates, which
         leave the ten labels distinct.
    - **Downgrade:**
      1. Drop the index.
      2. Put each label back where it still holds the new text.
      3. Set each description back to NULL where it still holds the seeded text.
    - **No audit row.** Reference-data migrations of the seed's own labels are not audited (the 0016 and 0025
      precedent).
    - **The seed.** `services/seed.py` inserts the new labels and descriptions for a **fresh** database, through a
      `ROLE_LABELS` / `ROLE_DESCRIPTIONS` entry in `_extra_columns`, used on insert only. It never relabels an
      existing row on `init`, so an administrator's name, or a description they cleared, is never undone.
    - Alternative: relabel on every `init`, like the note kinds. Refused: Edit Name would be undone at the next start.

### C. Edit Name for user types (item 3)

12. **A server-side write behind `access.manage_types`**, the function that already guards the type matrix and that
    only the Super Administrator holds by default. The owner said "super admin only". The function is that rule as
    configured. It is not widened, and a new function is not added.
    - **`PATCH /admin/access/types/{role}/name`**, body `{label, description}`.
    - PATCH is used so it can never collide with `PUT /admin/access/types/{role}/{permission}`.
    - **The rules, in `services/access.py::rename_type(session, actor, actor_user, role, label, description)`:**
      - `require(access.manage_types)`;
      - the role is any of the ten. `super_admin` may be renamed too, because its code and powers never change;
      - **the label** is trimmed, with inner white space collapsed to one space and control characters refused. It
        must be 1 to 80 characters. It must be unique without regard to case against every other `ref_role` row,
        inactive ones included. A clash gives 409 `label_taken`, from the service check and, under a race, from
        `uq_ref_role_label_lower`;
      - **the description** is trimmed and must be at most 200 characters. Empty means NULL;
      - the row is read `FOR UPDATE`;
      - if neither field changes, the answer is 200 with `changed: false` and no audit row.
    - **Audit.** One row: action **`access.type_edited`** (new), `entity_type` `ref_role`, `entity_id` NULL (the key
      is a code). `before` and `after` are `{code, label, description}`.
    - **No event.** No function or visibility changes, so `access_changed` is not raised.
    - **What does not change:** the code, the memberships, the matrix and the history.
    - Alternatives:
      - a free `PATCH /reference/...`: refused, because reference writes belong with the access screens;
      - a new function `access.rename_types`: refused, because the owner gave the permission.
13. **The screen.** The user-type page (`/admin/access/[role]`) gets an **"Edit Name"** secondary button in its
    header, shown with `access.manage_types`.
    - **The header shows** the type's label as the title, the code as a muted code tag (the page is for
      administrators only) and the description.
    - **The button opens a `Dialog` titled "Edit Name"**, subtitle "Internal code: dept_officer". It holds:
      - **Display Name**: required, with an 80-character counter and the hint "Must be different from every other
        user type. Use Title Case, as the other names do.";
      - **Short Description**: a `TextArea` with a 200-character counter;
      - the notice "The internal code (dept_officer) never changes, so users keep their type, functions and history.
        The change is recorded in the audit log.";
      - **Cancel** and **Save**.
    - **Errors.** A duplicate name is warned about in the browser before sending (from `/reference/labels`), and the
      server's 409 is shown on the field: "Another user type already has this name."
    - **On success:**
      - the queries `labels` and `access/overview` are invalidated, so the menu, the cards, the badges and the
        selects show the new name at once;
      - a flash notice reads "Name saved. The change is recorded in the audit log.".
    - **The Audit Log** shows the action under its Access group with the label "User Type Name Changed". The
      before/after page shows both texts.
    - **One primary per page** still holds: the page's primary stays Save Changes in the save bar.

### D. The side menu: one level, animated (item 4, revised by the owner on 25 Oct 2026)

14. **One level below a top entry, never deeper.**

    | Top entry | Expands to (each shown with its own functions, as today) |
    |---|---|
    | **Administration** | Users, User Types, Offices, Designations, Department Mapping, Tickets (`ADMIN_TABS`) |
    | **Data Collection** | Load, Health, Queue, Duplicates, Discovery (`DATA_TABS`) |
    | **Reports** | Pending Cases, Hearings and Disposals, Pending Actions (`reports.department` or `reports.state`); Data Health (`reports.state` only, the rule `GET /reports` applies) |
    | **System Health** | Court APIs (`/system#court`), ASLMS Services (`/system#services`), Access Token (`/system?api=token&tab=<first token tab>`, which opens the existing Access Token modal) |

    - Every other entry is a plain link: Dashboard, Case Inbox, Case Claim, Cause List, My Calendar, Alerts, Search,
      Assistant and Audit Log.
    - **Department Mapping is a leaf under Administration.** Its five tabs stay on its page. Making it expand would be
      a second level (open question 2).
    - **The user types, their function groups and the office tree are not in the menu** (owner, 25 Oct 2026; the
      mockup's deeper levels are superseded):
      - the User Types page shows the type cards;
      - a type's page shows its groups with an in-page **"Jump To"** list of anchor links to each function group,
        sticky beside the list on laptops and a select on phones;
      - the Offices page shows its tree, as today.
15. **The tree is built from routes and functions only, with no API call.**
    - `NavEntry` gains `children?: NavChild[]` (`{ key, label, href, functions, show?, match? }`), declared once in
      `routes.ts` from `ADMIN_TABS`, `DATA_TABS`, `REPORT_TABS` and a new `SYSTEM_SECTIONS`.
    - `navGroupsFor(me)` filters the children with the same `visible()` and `show` rule as the entries. An entry whose
      filtered children are empty is drawn as a plain link to its `href`.
    - `NavChild` has no `children` field, so a deeper level cannot be declared (the type enforces the owner's rule).
    - A child is **active** when the pathname starts with its `href`, or when its `match` says so (for the `/system`
      anchors: the hash, or the `api` key). The parent of the active child is **on the path**.
    - Showing an entry is convenience only. Every page and API keeps its own check.
16. **The behaviour.**
    - **Clicking a closed parent** opens it and goes to its landing page (its `href`), unless the person is already on
      one of its pages.
    - **Clicking an open parent** closes it, without navigating.
    - **One open branch at a time:** opening a parent closes any other open parent.
    - **On every route change**, the parent of the active child opens itself, so the active path is always visible.
    - **The active child** has the accent background and the 3 px accent bar. **The parent on the path** has the
      accent text in semibold. The other states are as in the mockup (`.nrow.active`, `.nrow.onpath`).
    - **The count pills stay** on Case Inbox, Case Claim and Alerts.
17. **The animation** (the mockup's CSS, on the existing tokens):
    - **Children.** The children's wrapper animates `grid-template-rows` from `0fr` to `1fr` over **`--med` (220
      ms)** with `cubic-bezier(.2,.8,.2,1)`. `visibility: hidden` applies once closed, so closed links are neither
      focusable nor read.
    - **Rows.** The child rows fade in and move 4 px, with an 18 ms stagger per row.
    - **The chevron** (16 px) rotates 90° over the same duration.
    - **Reduced motion.** Under `prefers-reduced-motion: reduce` the tokens are 0 ms, so the branch opens at once.
      This is the existing fallback and needs no JavaScript.
    - **No animation library.**
18. **Layout and accessibility.**
    - **Layout:**
      - rows are 36 px high;
      - an 18 px icon column, fixed: children keep an empty icon slot, so the labels line up;
      - children are indented by **16 px** beyond their parent's label start, with a 1 px guide line;
      - the label truncates with an ellipsis.
    - **The tooltip on truncation.** A small hook sets `title` to the full label only when `scrollWidth >
      clientWidth`, measured on pointer enter and focus. The accessible name is always the full label.
    - **The ARIA treeview navigation pattern:**
      - each group (Work, Oversight, Settings) is one `role="tree"`, labelled by its group heading;
      - items are `role="treeitem"` on the links, with `aria-level`, and `aria-expanded` on parents;
      - children sit in `role="group"`;
      - the active page has `aria-current="page"`;
      - one roving `tabindex` spans the whole menu, so Tab enters the menu once and leaves it once.
    - **Keys:**
      - Up and Down move between visible rows, across groups;
      - Home and End go to the first and last row;
      - Right opens a closed parent, or moves to its first child;
      - Left closes an open parent, or moves from a child to its parent;
      - Enter follows the link (on a parent, as a click).
    - Alternative: the disclosure-menu pattern with plain buttons. Refused: the owner asked for full arrow-key
      support, and the mockup uses the tree pattern.
19. **The phone drawer has the same tree.**
    - Choosing a link closes the drawer. Opening or closing a parent does not.
    - The drawer's focus trap, Escape and overlay are unchanged.
    - The bottom bar is row 152's.
20. **The in-page navigation stays:** the Administration sub-menu (`SettingsLayout`, a select on phones), and the
    Data Collection, Reports and Department Mapping tabs. The side menu is a second way in, as in the mockup.

### E. Filter Layout B, "Header Card with Two Zones" (item 5)

21. **A new kit component, `FilterCard`** (`components/ui/layout.tsx`, styles in `layout.module.css`).
    - **The left zone, `hero`.** It holds the page's one leading control, with a large value. It is 280 px wide on
      laptops and sits on top below 768 px.
    - **The right zone.** The other fields in a grid (`repeat(auto-fill, minmax(180px, 1fr))`), labels above the
      boxes, with the actions in the last cell: **Search** (the form's submit) and **More Filters (n)**, where n is
      the number of set fields inside.
    - **More Filters** opens a panel inside the card under the right zone (`Collapsible`, 220 ms, reduced motion
      respected). It is open whenever one of its fields is set.
    - **The summary strip** is a slim line under the card: the count, the quick links the page has, and the applied
      chips with "Clear All".
    - **Rules.** The field-row rule and the checkbox rule (decision 26) apply, and 36 px controls.
    - **Filters stay in the query string**, as today. On phones the card stacks (hero, fields, actions) and More
      Filters opens in place.
22. **`FilterBar` gains `layout="card"` with `hero`** (a shared field key or an own-control key), so the shared
    machinery is reused:
    - `useFilters`, validation, chips and the legacy keys;
    - Search and Department Cases use it.

    The Cause List, Reports, Audit Log and Data Collection Queue forms are their own, so they adopt `FilterCard`
    directly. The other lists keep today's `FilterBar` (decision 23).
23. **The pages.** The owner's list, each with its hero. No filter, key or API changes.

    | Page | Hero (left zone) | Right zone | More Filters | Summary strip |
    |---|---|---|---|---|
    | **Cause List** | The date navigator (decision 24) | Bench, Search Words | List Type, Court | "n entries · x recommended to you · y claimable" (from the API's `counts`), the links setting `only`, and the **Show** select replacing the show-only chips (as in the mockup) |
    | **Search** | **Search For**: the words box (CNR, case number or party name) | Case Type, Year, Department | the rest of the search's shared fields | the total and the chips (only figures the API returns; no invented "yours" or "claimed" counts) |
    | **Case Inbox → Department Cases** | Words | Unit, Officer, Stage, Cause-List Date, Next Hearing, Case Type | Year, Status, Court, Bench, and the rest | the total and the chips |
    | **Reports** | **Period**: From and To, or "As Of" where the report takes no period | Holding Department (Office Picker, decision 28), List the Cases | — | the report's scope line; the downloads stay in the page header |
    | **Data Collection → Queue** | **Reference Starts With** | Kind, Status, Lane | — | the count of rows shown |
    | **Audit Log** | **Period**: From and To, with Today / 7 Days / 30 Days | Person, Name Contains, Case, Office (Office Picker), Action | Unit, About User, Entity Type, Entity ID | "Newest first" and the chips (the API is cursor-paged; no total) |

24. **The Cause List date navigator** is the mockup's Layout B hero.
    - It shows the weekday over the date, large ("Friday" / "23 Oct 2026").
    - **Previous Day** and **Next Day** are icon buttons with accessible names.
    - **Pick Date** opens the native date picker (`showPicker`, with focus as the fallback).
    - The **"Lists Held: n"** badge counts the day's lists from `GET /causelists/{date}`. It reads "No Lists" in amber
      when there are none.
    - **"View Cause List"** (decision 25) sits under the badge.
25. **"View Cause List" opens the chosen bench's list in a large modal over the page.** This is the owner's
    addition, and this note's reading of it (open question 1).
    - **It is a secondary button,** enabled when a bench is chosen. With "All Benches" it is disabled, with the hint
      "Choose a bench to view its list."
    - **It opens the kit `Modal`** (full screen on phones), titled "Cause List: ‹bench label› · ‹date›", with the
      bench's list types as the facts. The address is `?view=<bench_id>&vtab=entries|pdf` through `useUrlOverlay`, so
      Back closes it and a shared link reopens it.
    - **Two tabs:**
      - **Printed Entries.** The bench's entries in court order, from `GET /causelists/{date}/entries?bench_id=…`
        paged by 100, as printed: Court and Item in the lead column, then case number, parties, advocates and
        section. Each row carries the same recommendation or owner badge as the page, and the case number links to
        the case page. Claim stays on the page, not in the modal.
      - **Original PDF.** A list chooser when the bench has more than one list (daily, supplementary) from the day
        data. Then the inline viewer of `GET /causelists/lists/{id}/file?disposition=inline` with `documents.view`,
        and **Download** with `documents.download`. Without either function the tab says the PDF needs the
        documents function. A `no_pdf` or `file_missing` answer shows the API's message.
    - **No new API.** Visibility stays on the server, as on the page.

### F. The checkbox alignment rule and the Users toolbar (item 7)

26. **Checkboxes in a filter row sit level with the boxes, not with the labels.** A `CheckField` placed in a row of
    labelled fields centres its checkbox and text on the **36 px control line**: the line of the inputs, selects and
    the Search button beside it.
    - **How:** `CheckField` gets `inline` (a top margin equal to the label line plus its gap, and `min-height: 36px;
      align-items: center`), used whenever it sits in a field row.
    - **uicheck enforces it.** The field-row check of `checks.ts` gains a checkbox step: in a line of a field row, an
      item whose control is a checkbox (`input[type=checkbox]` with no other box) must have its checkbox's vertical
      centre within 1 px of the line's box centre. Otherwise it reports finding kind `alignment`, detail `field row:
      checkbox centre …`.
    - `uicheck-self.spec.ts` gets a page that breaks the rule and one that keeps it.
27. **The Users filter is the one-line toolbar** (the mockup's "After One-Line Toolbar", the owner's choice):
    - **Name or E-mail**, **User Type**, **Office** (Office Picker with **Include Sub-offices**), **Status**, **More
      Filters (n)** and **Search**, on one line at 1,280 px;
    - labels are visually hidden, and the placeholders show them; the 3-character hint becomes a tooltip;
    - **"Include Logins Without an Active Office"** (`include_ended`, Super Administrator only, as today) sits inside
      More Filters;
    - **Add User** stays the page header's primary;
    - below about 1,280 px the toolbar wraps on the control line; on phones it stacks.

### G. The Office Picker (item 6)

28. **One reusable kit component, `OfficePicker`** (`components/ui/OfficePicker.tsx`), as drawn in the mockup.
    - **It follows the ARIA combobox pattern:** an input with `role="combobox"`, `aria-expanded`, `aria-controls` and
      `aria-activedescendant`, and a `role="listbox"` of options.
    - **The list.**
      - The office tree, indented 16 px per depth, each name with its code greyed on the right.
      - **Typing filters by name or code**, without regard to case. The matches are highlighted and shown with their
        ancestor path under the name.
      - "No office matches" when nothing does.
    - **The box.**
      - An office icon, the chosen name, its code tag, a **clear (×) button** ("Clear office") and a chevron.
      - It is 36 px high.
    - **The foot:** "Only offices you can see or act on."
    - **Optional parts:**
      - **Include Sub-offices**: a checkbox under the box, for filters. It shows "+ sub" beside the code when ticked
        and the office has children;
      - **Inactive offices** marked with an "Inactive" badge, where the purpose allows them.
    - **Keys:**
      - Down opens the list, or moves down it;
      - Up moves up the list;
      - Home and End go to the first and last option;
      - Enter chooses;
      - Escape closes the list, keeping the value;
      - Tab closes the list.
    - **Rendering.** The popover renders in a portal placed under the box, flipping above it when there is no room.
      Modal and side-panel bodies therefore never clip it. Inside an overlay the portal is mounted in the overlay
      root, so the focus trap holds.
    - **The value** is the office code, which every API already takes.
    - **Props:**
      - `purpose`, or `options` (a list given by the page);
      - `value` and `onChange(code | null)`;
      - `label`;
      - `kinds?`;
      - `subtree?: { value, onChange }`;
      - `includeInactive?`.
29. **The data: one new read-only endpoint, `GET /offices/choices?purpose=…`.**
    - The existing `/offices/tree` needs `users.view`, which mapping holders, reporters and the Auditor may not have.
      Widening it would be a visibility change.
    - The new endpoint answers each screen with exactly the offices that screen's write or filter already accepts:

      | `purpose` | Required function (`Permission`) | Offices returned |
      |---|---|---|
      | `users` (Users filter) | `users.view` | the subtrees of `access.user_scope_roots`: everything for the Super Administrator and State-wide readers, as `GET /admin/users` |
      | `membership` (Add User, Add Office) | `users.create` | the subtrees of the caller's memberships holding `users.create` (`access.holders_in`); everything for the Super Administrator; active only |
      | `office_parent` (New Office's parent) | `offices.manage` | the subtrees of the memberships holding `offices.manage`; everything for the Super Administrator; active only |
      | `counsel_codes` / `keywords` / `watchlist` (Department Mapping) | `admin.counsel_codes` / `admin.keywords` / `admin.watchlist` | the subtrees of the memberships holding that function (the rule `matching_rules._scope` enforces); active only. The root office is included only where the caller's scope holds it (a generic code) |
      | `audit` (Audit Log office filter) | `audit.view`, State-wide (the audit search's own scope rule, else 403 `audit_scope`) | every office, inactive ones included and marked |

    - **`include_inactive=true`** is accepted for `users` only with `offices.manage` (today's rule for listing
      inactive offices). `audit` always includes them.
    - **The answer:** `OfficeChoicesOut { purpose, items: [OfficeChoiceOut { code, name, kind, tier, depth,
      parent_code, ancestors: [names, root first], is_active }] }`, in tree order (by `path`). The picker indents by
      `depth` minus the smallest depth returned.
    - **No paging:** offices number in the hundreds.
    - **Reads only, no audit row** (the precedent of `/offices/tree`).
    - **The Reports holding department** needs no call. Its picker gets `options` from `GET /reports`' `departments`,
      which the page already loads and which is that report's own rule.
    - **No visibility change.** Each purpose returns only offices the caller can already see in, or write to, the
      matching screen, and every write still checks again.
30. **Where the picker replaces a typed code.**

    | Screen | Purpose | Notes |
    |---|---|---|
    | Users filter | `users` | with Include Sub-offices. `GET /admin/users` gains **`subtree`** (default `true`, today's behaviour); `false` narrows to that office exactly. This is additive and narrowing only |
    | Add User, and Add Office in User Details | `membership` | |
    | New Office: its Parent | `office_parent` | |
    | Department Mapping (the add rows, Map in Recommended From Cause Lists, Change Office) | `counsel_codes`, `keywords`, `watchlist` | the generic-code rule (`is_generic_state` sent exactly when the root office is chosen) is kept |
    | Reports: Holding Department | `options` from the catalogue | departments only |
    | Audit Log: Office | `audit` | with Include Sub-offices. `GET /audit` gains **`office_subtree`** (default `true`, today's behaviour); additive and narrowing only |

### H. The User Details modal (item 8)

31. **The modal replaces the user's full page and its Offices (memberships) table.**
    - **Its own address is `/admin/users/<id>`** (the existing route), with the tab in `?tab=overview | offices |
      functions | activity`. The route renders the Users list behind, with its filters from the query string, and the
      modal open over it.
    - **Opening from a row** pushes `/admin/users/<id>?<list query>`. **Closing** goes back when the modal was opened
      in the portal (a history-state flag, as in the mockup), else to `/admin/users?<list query>`. Escape, the
      overlay and the Back button close it.
    - **Old addresses redirect** with the query string kept: `/admin/users?user=<id>` (row 135's side panel) goes to
      `/admin/users/<id>`. The new-user flow stays on `?user=new` in the side panel.
    - **On phones** it is a full-screen sheet (the kit `Modal`).
    - Alternative: an intercepting Next.js route. Refused as more machinery than this needs.
32. **The header:**
    - the initials avatar, the full name and "‹primary designation› · ‹primary office›";
    - the facts: e-mail, mobile, the status badge (Active, Not Signed In Yet, Sign-in Off) and "Last Sign-in: …";
    - **Edit Profile** (secondary, `users.edit`). It opens the existing login fields (`LoginCard`: name, e-mail with
      the code check, mobile) in a `Dialog`;
    - **More** (`Menu`):
      - **Reset Password** (`users.reset_password`);
      - **Turn Sign-in Off / On** (`users.enable_disable`). Turning it off still signs the person out everywhere, as
        today.
33. **Overview tab.** Two definition lists, Person and Primary Office:
    - Full Name, E-mail, Mobile, Status and Last Sign-in;
    - Primary Office, Designation, User Type (the label), Offices (n active) and Member Since.
    - Then the sign-in notice: "Sign-in uses a 6-digit code sent to this e-mail address every time. Changing the
      address needs a code sent to the new one."
34. **Offices tab** ("Offices n", the active count). One card per membership: active first, primary first, then the
    ended ones.
    - **Each card shows:**
      - the office name with its code tag, and the ancestor path;
      - the badges Primary, Active or Ended;
      - Designation, User Type, and Since or Period;
      - a footer line: "Shown first wherever this person appears.", "An additional office." or "Kept in the
        history.".
    - **The Actions menu** of an active card:
      - **Change** (the existing `ChangeMembership` in a `Dialog`; `users.edit` or `users.set_type`);
      - **Make Primary** (`users.edit`, not on the primary);
      - **Functions and Overrides** (switches to the Functions tab on this office);
      - **Government Orders** (the existing `MembershipDocuments` in a `Dialog`);
      - a separator, then **End Membership** in red (`users.enable_disable`). It opens the existing **`ExitDialog`**
        (the exit preview with successors). That is the confirm, and its submit is a danger button.
    - **An ended card** has **Reactivate** (`users.enable_disable`).
    - **Add Office** (`users.create`) under the cards opens the existing `AddMembership` with the Office Picker.
35. **Functions tab.**
    - An **Office** select over the active memberships ("‹office› · ‹type label›"), and the line "Holds n functions
      here: those of ‹type›, x given, y taken.".
    - Then **the held functions grouped** by the function groups (`groupFunctions`), one card per group.
    - Overrides are marked **"Given to This Person"** (green) and **"Taken From This Person"** (red, struck through).
    - **Change Exceptions** (`users.grant`) opens the existing `MembershipFunctionsPanel` switches in a `SidePanel`.
    - A login with no active office shows "This login has no active office, so it holds no functions.".
36. **Activity tab.** It shows only with `readsAudit` (the Super Administrator and the Auditor: the audit API's own
    rule).
    - It lists the person's latest 20 audit entries, newest first, from `GET /audit?user=<id>&limit=20`: time,
      action label and the line.
    - **"Open in Audit Log"** goes to `/audit?user=<id>`.
    - Without `readsAudit` the tab is not shown, so no 403 call is made.
37. **"Sign Out Everywhere" is not offered.** There is no API: only `aslms users sign-out` on the server, and Turn
    Sign-in Off already ends every session. Adding an endpoint would be new work outside "reuse the existing APIs"
    (open question 5).
38. **APIs reused unchanged:** the user, membership, exit, override, documents and audit endpoints listed in
    Context. The user detail components are recomposed. Their rules and calls are kept.

### I. Department Mapping simplified (item 9)

39. **Notes and the per-rule weight override leave the forms. The API and the database keep both.**
    - The create and edit forms of codes, keywords, name patterns and the watchlist no longer show Notes or Weight.
      The list columns Notes and Weight go.
    - **The portal never sends `notes` or `weight`.** On update, the server reads a missing `notes` as "no change"
      and a missing `weight` as `UNSET`, so **existing values are untouched**.
    - `CounselCodeIn.notes`, every `weight` field, `weight_override` and `effective_weight` stay in the API. The
      `notes` and `weight` columns stay in the database.
    - **The Scoring tab is the only place for weights** (the owner's words).
    - Alternative: drop the fields from the API and the database. Refused: legal-record caution, a migration for no
      user gain, and the CLI and older clients still send them.
40. **Existing overrides are shown and cleared only on the Scoring tab.** A hidden override still changes scores, so
    hiding it from the forms must not leave it invisible.
    - **The panel.** With `admin.scoring`, the Scoring tab adds **"Rules With Their Own Weight"**: active rules with a
      `weight_override`, read from the existing list endpoints the caller can read. Each shows the rule, its office,
      the own weight and the standard weight.
    - **The action.** **"Use the Standard Weight"** sends `PATCH …/{id}` with `weight: null`. It needs `admin.scoring`
      and the rule's own function, as today, and is audited by the existing rule-change audit.
    - **When empty** the panel reads "No rule has its own weight."
    - **No new override can be set from the portal.** Open question 4.
41. **One toolbar line per tab:**
    - **Search Codes** (and **Search Words** and **Search Watchlist**) uses the list's `q`;
    - the **Include Deactivated** switch uses `include_inactive`;
    - the Keywords tab adds the **All / Keywords / Name Patterns** segmented choice.

    Below it sits **one aligned add row** per tab, on the control line:
    - **Counsel Codes:** Code, Office (picker), **Add Code**.
    - **Keywords and Name Patterns:** Word or Pattern, Kind (Keyword / Exact / Starts With / Pattern, routed to
      `/admin/keywords` or `/admin/name-patterns` as today), Office (picker), the **Search the Court** switch,
      **Add**.
    - **Watchlist:** CNR (16 letters and digits; the existing check), Office (picker), **Add**.

    **Rows.** Each row's kebab menu has **Change Office** (a small `Dialog` with the picker) and **Deactivate** or
    **Reactivate**. A wording change is still a deactivation and a new rule (portal-mapping).
42. **"Recommended From Cause Lists"** is the renamed unmapped-codes panel. It is **always visible**: a right column
    of 360 px beside the codes list on laptops, and below it on phones.
    - **The data.** It comes from `GET /admin/counsel-codes/unmapped?limit=100`. Each code shows its **entries**
      count, **last seen** (`last_listed`) and the example case link.
    - **Inline Map.** Each code has an Office Picker and **Map**, which posts `POST /admin/counsel-codes {code,
      office_code}` directly. The code then leaves the panel, as today.
    - **The notice stays:** "Nothing is mapped automatically." Mapping remains a person's decision.
    - **The header** shows "n to review".
43. **Scoring:**
    - **Each weight row** has its name, a one-line explanation, a **slider** (0.05 to 1, step 0.05) and a **number
      field** (0.01 to 1, step 0.01), kept in sync. The API refuses 0.
    - **The bands** are **Strong Recommendation From** and **Possible Match From**, with the band bar
      (No Recommendation / Possible Match / Strong). The possible band must stay below the strong one.
    - **The save bar** counts unsaved changes, with Discard and **Save Changes**. Saving asks for the **reason** the
      API requires, in a `ConfirmDialog`, and sends the loaded `expected_version`. A 409 reloads the settings and
      keeps the reason, as today.
    - **History** is listed under the form.
    - **Without `admin.scoring`** the sliders and fields are read only, with no save bar and no history (today's
      read rule).
    - **The text "Nothing is ever assigned automatically; a department always claims."** stays under the bands. This
      is the recommend-and-claim rule.

### J. The dashboard greeting and view switch (item 10)

44. **The greeting.** "Good Morning", "Good Afternoon" or "Good Evening", by the IST hour, then ", ‹first name›" when
    the account has a personal name.
    - **An account without a personal name** gets no name. Such an account has a `full_name` that is empty, or that
      equals (trimmed, without regard to case) its primary designation, any user-type label from
      `/reference/labels`, or "Super Administrator".
    - **The line under it**, for every account: "‹designation› · ‹office name›" of the primary membership, for
      example "Super Administrator · Government of Assam" or "Under Secretary · Secondary Education Department".
    - **The date** ("Sunday, 25 October 2026", IST) moves to the right of the view switch.
    - Nothing else is computed in the browser.
45. **The view switch.**
    - **Tooltips.** Each option has a tooltip: "My Work: your own cases.", "Department: your department's cases.",
      "State: every case in the whole State.".
    - **A description line under the switch** repeats the chosen view's sentence, linked by `aria-describedby`.
    - **Department disabled.** For a login that has the State view but no department (the Super Administrator),
      Department shows **disabled**, with the tooltip "Department: not available, because you are not in a
      department".
    - **Other unavailable views stay hidden,** as today.
    - **Opening on State.** When My Work would be empty (`hasPersonalWork` false) and State is available, the
      dashboard opens on State with the notice "Opened on State because you have no cases of your own.". This is
      today's opening rule, now explained.
    - No API change.

### K. Rounds, rules and checks

46. **The build splits into three rounds, in this order.**
    - **Round 1 (row 153, `feature/portal-ui-polish-2`)**: decisions 1-20, 26 and 44-45. It covers Title Case with
      the helper and its tests, the full names and the migration, Edit Name, the one-level side menu, the checkbox
      rule and the uicheck step, and the dashboard greeting and switch. It goes first because:
      - it touches every string, so later rounds write their new strings in the final style;
      - it carries the only migration;
      - it holds the most visible changes.
    - **Round 2 (new row at approval, `portal-ui-polish-2-admin`)**: decisions 27-43. It covers the Office Picker and
      `GET /offices/choices`, the `subtree` and `office_subtree` filters, the Users toolbar, the User Details modal,
      the simpler Department Mapping and the pickers in the Reports and Audit Log forms as they stand. It comes
      before round 3 because Layout B uses the picker.
    - **Round 3 (new row at approval, `portal-ui-polish-2-filters`)**: decisions 21-25. It covers `FilterCard`,
      `FilterBar layout="card"`, the six pages, the date navigator and the View Cause List modal.
    - **Rounds 2 and 3** each get the next free backlog number at approval (row 154 is taken). Each builds from this
      note and has its own report and review.
    - Alternative: one cycle. Refused: about 40 files and every label, which is too much for one review.
47. **The redesign rules hold:**
    - tokens and the kit only. The new kit parts are `FilterCard` and `OfficePicker`, and the nav tree's styles live
      in `shell.module.css`;
    - lead elements in the fixed `Lead` column;
    - the field-row rule plus the checkbox rule;
    - **one primary per page.** The Users page's primary is Add User. The user-type page's is Save Changes. Mapping
      has none outside the add rows' submit buttons, which are secondary. The modals have their own primary;
    - phones at 375 px: lists stack as cards, the modals are full screen and the drawer holds the same tree;
    - motion uses the tokens with the reduced-motion fallback.
48. **The wording guard stays green** (`lib/wording.test.ts` and the backend's `tests/unit/test_wording_guard.py`).
    Its word test ignores case. An allow-list entry that is case-sensitive is made case-insensitive in round 1, so a
    re-cased label such as "Attach New Files" is still allowed. The allowed meanings do not change.
49. **No visibility or permission change.** The only new write is Edit Name, behind `access.manage_types`.
    - `GET /offices/choices` returns per purpose what the matching screen already accepts.
    - `subtree` and `office_subtree` only narrow.
    - Everything else is presentation over the existing APIs.

## Data
**Round 1 only.** One reference-data migration (decision 11), no table and no column. The paragraph for
`docs/schema/schema.md` replaces the `ref_role` part of the row "`ref_role`, `ref_office_kind`, `ref_note_kind`,
`ref_record_type`" with:

> **`ref_role`** (reference). code (PK, never changes), label varchar(120) NOT NULL, description text NULL,
> sort_order, is_active, created_at, updated_at.
> - **Seeded from `Role`** with the full user-type names: Super Administrator, State Oversight Officer, Head of
>   Department, Department Administrator, Department Officer, Directorate Officer, Referral Reviewer, Standing
>   Counsel, Central Operator, Auditor.
> - **Descriptions from the plan's Table 1** (design `portal-ui-polish-2`, decisions 7 and 8). The seed sets labels
>   and descriptions on insert only.
> - **Migration 00NN** (the next free number after 0025):
>   - relabels a row only while its label still holds the old seeded text (`Super admin`, `State oversight`, `Dept
>     head`, `Dept admin`, `Dept officer`, `Directorate user`, `Referral reviewer`, `Standing counsel`, `Central
>     operator`);
>   - sets a description only where it is NULL;
>   - adds the unique index **`uq_ref_role_label_lower`** on `lower(label)`.
> - **Editing.** The label and description are edited only by holders of `access.manage_types` through `PATCH
>   /admin/access/types/{role}/name`:
>   - label 1 to 80 characters, white space collapsed, unique without regard to case;
>   - description up to 200 characters, empty = NULL;
>   - audited `access.type_edited` with before and after `{code, label, description}`.
> - No FK changes. The `aslms_app` UPDATE grant on reference tables is existing (0001), so no new grant is needed.

`RefRole` in `domain/reference.py` declares the index in `__table_args__` (`Index("uq_ref_role_label_lower",
func.lower(label), unique=True)`), so the model and the migrations stay equal for the schema comparison test.

**Rounds 2 and 3: no data change.**

## Services
- **`backend/aslms/core/titlecase.py`** (round 1): `SMALL_WORDS`, `ACRONYMS`, `title_case(text)` and
  `is_title_case(text)`, as decision 2. Pure functions.
- **`services/access.py::rename_type(session, actor, actor_user, role, label, description) -> dict`** (round 1):
  - **checks:** `require(ACCESS_MANAGE_TYPES)`; normalisation and limits; a case-insensitive uniqueness check against
    the other `ref_role` rows; the row read `FOR UPDATE`;
  - **errors:** `TypeLabelTaken` (409 `label_taken`) and `TypeLabelInvalid` (422, code `label_required`,
    `label_too_long`, `label_bad_characters` or `description_too_long`). An `IntegrityError` on the index under a
    race maps to `label_taken`;
  - **audit:** `write_audit(…, "access.type_edited", "ref_role", None, before=…, after=…)`, only when something
    changed;
  - **returns** `{code, label, description, changed}`.
- **`services/seed.py`** (round 1): `ROLE_LABELS` and `ROLE_DESCRIPTIONS`, applied in `_extra_columns` for `RefRole`
  on insert only.
- **`services/access_seed.py`** (round 1):
  - the `PERMISSION_LABELS` labels in Title Case, and their group labels;
  - the descriptions name user types in full (decision 10).
- **`services/offices.py::choices(session, user, purpose, include_inactive) -> list[OfficeChoice]`** (round 2):
  - the rule per purpose from decision 29, reusing `access.user_scope_roots`, `access.holders_in`, `office_tree` and
    `audit_search`'s scope check;
  - `Forbidden` without the function, or (audit) without State-wide reach;
  - ordered by `path`, with `ancestors` built in one pass over the subtree;
  - reads only.
- **`api/routers/users.py::list_users`** and **`services/audit_search.py`** (round 2): the additive `subtree` /
  `office_subtree` parameter. `false` means `office_id = root.id` instead of the subtree.
- No other service changes. The mapping, user, membership and cause-list services are reused unchanged.

## API
| Method and path | Function (`Permission`) | Request | Response | Visibility | Round |
|---|---|---|---|---|---|
| `PATCH /admin/access/types/{role}/name` | `access.manage_types` | `UserTypeNameIn {label: str (1–80 after trim), description: str \| null (≤ 200)}` | `UserTypeNameOut {code, label, description, changed}`; 403, 409 `label_taken`, 422 | reference data, State-wide; no scope | 1 |
| `GET /reference/labels` (unchanged) | signed in | — | `user_types[]` now carry the full names and descriptions | unchanged | 1 |
| `GET /offices/choices?purpose=&include_inactive=` | per purpose (decision 29): `users.view`, `users.create`, `offices.manage`, `admin.counsel_codes`, `admin.keywords`, `admin.watchlist`, or State-wide `audit.view` | `purpose` ∈ `users`, `membership`, `office_parent`, `counsel_codes`, `keywords`, `watchlist`, `audit` | `OfficeChoicesOut {purpose, items: [OfficeChoiceOut {code, name, kind, tier, depth, parent_code, ancestors: [str], is_active}]}`; 403 without the function (`audit_scope` for a non-State-wide auditor); 403 for `include_inactive` without `offices.manage` (except `audit`) | exactly the offices the matching screen accepts | 2 |
| `GET /admin/users?…&subtree=` | `users.view` (unchanged) | `subtree: bool = true` | unchanged | unchanged; `false` narrows | 2 |
| `GET /audit?…&office_subtree=` | `audit.view`, State-wide (unchanged) | `office_subtree: bool = true` | unchanged | unchanged; `false` narrows | 2 |

- **Route order.** The PATCH route cannot collide with `PUT /admin/access/types/{role}/{permission}` (a different
  method). A test pins that `PUT …/name` is still answered 422 (an unknown function), not routed to the rename.
- **The portal's own routes** (no API):
  - `/admin/users/<id>` now renders the list with the User Details modal;
  - `/admin/users?user=<id>` redirects there;
  - `/causelist?view=<bench_id>&vtab=` is the View Cause List overlay.
- **The schema.** `frontend/openapi.json` and `src/lib/api/schema.d.ts` are regenerated in rounds 1 and 2.

## Jobs
None.

## Tests

### Round 1
**Backend (pytest):**
- `tests/unit/test_titlecase.py`:
  - `title_case` and `is_title_case` on the pinned examples (decision 2);
  - small words in the middle, first and last;
  - acronyms;
  - hyphenated words;
  - segments split at " / " and " · ";
  - words with digits or inner capitals left alone.
- `tests/unit/test_access_seed.py::test_permission_labels_are_title_case`: every function label and group label passes
  `is_title_case`; no description is altered by it.
- `tests/unit/test_access_seed.py::test_descriptions_name_types_in_full`: no description contains "super admin", "dept
  admin" or "dept head" (case-insensitive).
- `tests/db/test_seed_and_refno.py::test_fresh_seed_has_full_type_names_and_descriptions`: the ten labels and the ten
  descriptions. `…::test_seed_rerun_keeps_edited_type_name`: an edited label and a cleared description survive a
  second `seed`.
- `tests/db/test_migration_00NN_type_names.py`:
  - upgrade relabels only rows holding the seeded text, leaving a customised label;
  - descriptions are set only where NULL;
  - `uq_ref_role_label_lower` exists and refuses "department officer" beside "Department Officer";
  - downgrade reverses under the mirror conditions.
- `tests/db/test_access_type_name.py`:
  - **a rename:** returns `changed: true`; writes one `access.type_edited` row with before and after; leaves the code,
    the memberships and the matrix untouched;
  - **an unchanged save:** `changed: false` and no audit row;
  - **refusals:**
    - a duplicate without regard to case → 409 `label_taken`;
    - an empty or white-space label → 422 `label_required`;
    - 81 characters → 422;
    - a description of 201 characters → 422;
    - a control character → 422;
  - **an empty description** is stored as NULL;
  - **renamable:** `super_admin` can be renamed;
  - **access:** without `access.manage_types` → 403; an unknown role → 422;
  - **the new name** appears in `GET /reference/labels`;
  - **the race:** two concurrent renames to the same name end with one 409 (two sessions).
- `tests/db/test_api_access.py::test_put_name_is_not_a_function`: `PUT /admin/access/types/dept_officer/name` →
  422.

**Frontend (vitest):**
- `lib/titleCase.test.ts`: the same pinned examples as the pytest, and the mockup's Before and After table.
- `lib/labels.test.ts`:
  - every label path is Title Case;
  - every unclassified short string is Title Case or listed in `SENTENCE_EXCEPTIONS`;
  - the `LABEL_FUNCTIONS` results are Title Case;
  - there are no stale exception or function paths.
- `lib/routes.test.ts`:
  - the four expanding entries' children per function set;
  - Data Health only with `reports.state`;
  - Administration's children follow `ADMIN_TABS`' functions;
  - an entry whose children are all hidden is a plain link;
  - **no child has children** (one level);
  - the `/system` children's `match` (hash and `api`).
- `components/shell/shell.test.tsx`:
  - **opening:** a parent toggles `aria-expanded`; opening one closes the other;
  - **navigation:** clicking a closed parent navigates to its landing page; clicking an open one closes without
    navigating;
  - **the active path:** the active child has `aria-current="page"`, and its parent is on the path and opens on a
    route change;
  - **closed children** are not focusable;
  - **keys:** Up, Down, Home, End, Right, Left and Enter, across groups, with a single tab stop;
  - **truncation:** the title is set only when truncated (mocked widths);
  - **reduced motion:** the open state applies at once;
  - **the drawer:** choosing a child closes it, toggling a parent does not.
- `components/admin/userTypes.test.tsx`:
  - **the button:** Edit Name shows only with `access.manage_types`;
  - **the form:** the counters (80 and 200); the empty-name and duplicate warnings; the 409 shown on the field;
  - **saving:** sends `PATCH …/name` with the trimmed values, then invalidates `labels` and `access/overview`, and the
    page title shows the new name;
  - **the Jump To list:** links to each group anchor.
- `components/dashboard/dashboard.test.tsx`:
  - the greeting with a personal name;
  - without one (full name equals the designation, a type label, or "Super Administrator"): only "Good Afternoon",
    and the line "designation · office";
  - the tooltips and the description line;
  - Department disabled with its reason for a login with no department;
  - opening on State with the notice when there is no personal work.
- **Existing tests** that name elements by text are updated to the Title Case labels.

**Browser check (uicheck):**
- `checks.ts`: the checkbox step (decision 26). `uicheck-self.spec.ts`: a failing and a passing checkbox row.
- **Fixtures:** `/reference/labels` with the ten full names and one 80-character custom name (truncation in badges,
  cards and the page title); `/me` as now (every function).
- **New interaction states:**
  - "/ (side menu: Administration open)" at 1280 px;
  - "/ (phone drawer: Administration open)" at 375 px;
  - `/admin/access/<type> (Edit Name dialog)`.
- **The existing states** are renamed to the new labels.

### Round 2
**Backend:**
- `tests/db/test_office_choices.py`:
  - **per purpose:** the Super Administrator gets every office; a Department Administrator gets their department's
    subtree for `users`, `membership` and the mapping purposes; a mapping holder without `users.view` gets their own
    offices for `keywords`; `office_parent` needs `offices.manage`;
  - **audit:** a State-wide Auditor gets every office including inactive ones, and a department-scoped `audit.view`
    holder gets 403 `audit_scope`;
  - **refusals:** 403 without the function; `include_inactive` refused without `offices.manage`;
  - **the shape:** tree order, `depth`, `ancestors` and `is_active`.
- `tests/db/test_api_users_list.py::test_subtree_false_narrows_to_the_office`.
- `tests/db/test_audit_search.py::test_office_subtree_false`.

**Frontend:**
- `components/ui/officePicker.test.tsx`:
  - the indented tree with greyed codes;
  - filtering by name and by code, with the path under the matches and "No office matches";
  - **keys:** Down, Up, Home, End, Enter, Escape and Tab;
  - **choosing:** the clear button; the Include Sub-offices "+ sub";
  - **the data:** the purpose in the query; `options` used without a call; the Inactive badge;
  - the foot text.
- `components/admin/admin.test.tsx`:
  - **the Users toolbar** is one line, with More Filters holding "Include Logins Without an Active Office" (Super
    Administrator only) and its count;
  - **the requests:** the picker sends `office` and `subtree`;
  - **the other pickers:** Add User and New Office's parent use the picker with their purposes.
- `components/admin/userDetails.test.tsx`:
  - **the address:** `/admin/users/<id>` opens the modal over the list; `?user=<id>` redirects; Escape, the overlay
    and Back close it; the tab lives in `?tab=`;
  - **the header facts and the menus:** each item shows only with its function; there is no Sign Out Everywhere;
  - **the Offices cards:** the order, the badges and the Actions items per function; End Membership is red and opens
    the ExitDialog; Reactivate shows on ended cards;
  - **Functions:** grouped, with the Given and Taken marks, and Change Exceptions only with `users.grant`;
  - **Activity:** only with `readsAudit`, calling `GET /audit?user=<id>&limit=20`.
- `components/admin/mapping.test.tsx`:
  - **the forms:** no Notes or Weight field, even with `admin.scoring`; the POST and PATCH bodies never carry `notes`
    or `weight`;
  - **the toolbar:** Search and Include Deactivated on one line, sending `q` and `include_inactive`;
  - **the add rows:** they use the picker;
  - **Recommended From Cause Lists:** always rendered; Map posts the code and removes it;
  - **Scoring:** the slider and the number field stay in sync; Save needs the reason; "Rules With Their Own Weight"
    lists the overrides and "Use the Standard Weight" sends `weight: null`; read only without `admin.scoring`.
- `components/reports/reports.test.tsx`: the Holding Department picker is fed from the catalogue.
- `components/audit/audit.test.tsx`: the Office picker with `office_subtree`.

**uicheck:**
- **Fixtures:**
  - `/offices/choices` (depth 3, long names, one inactive office);
  - the user with two active and one ended membership plus overrides;
  - `/audit?user=` items;
  - three unmapped codes and one rule with its own weight.
- **New states:**
  - `/admin/users (Office Picker open)`;
  - `/admin/users (More Filters open)`;
  - `/admin/users/<id> (User Details, Offices tab)`;
  - `/admin/users/<id> (Actions menu open)`;
  - `/admin/mapping/codes (Recommended From Cause Lists)`.

### Round 3
**Frontend:**
- `components/ui/ui.test.tsx` (`FilterCard`):
  - the hero and the grid zones;
  - More Filters with its count, open when one of its fields is set;
  - the summary strip;
  - the stacked order on phones (by class).
- `components/filters/filterbar.test.tsx`: `layout="card"` with `hero` keeps the URL keys, chips and validation of the
  bar.
- `components/causelist/causelist.test.tsx`:
  - **the navigator:** the previous and next day; Lists Held n and No Lists;
  - **the Show select** replaces the chips;
  - **View Cause List:** disabled with All Benches; opens `?view=<bench>` with the bench's entries (paged); the PDF
    tab needs `documents.view` and Download needs `documents.download`; `no_pdf` shows its message; Back closes.
- `search.test.tsx`, `inbox.test.tsx` (Department Cases), `reports.test.tsx`, `audit.test.tsx` and `data.test.tsx`
  (Queue): each page renders its hero and its fields in the card, and keeps the same query keys.

**uicheck states:**
- `/causelist (View Cause List modal, Printed Entries)` and the same on the `Original PDF` tab;
- `/causelist (More Filters open)`;
- `/search (Layout B)`;
- `/audit (Layout B with the Office Picker open)`.

## Verification
1. **Each round:** `ruff check` clean, `pytest -q` green, and the frontend `npm run lint`, `npm run typecheck`
   (`tsc`) and `npm test` green.
2. **Round 1, the migration:**
   - `docker compose run --rm migrate` applies 00NN;
   - `docker compose exec postgres psql -U aslms -c "select code,label,description from ref_role order by
     sort_order"` shows the ten full names and descriptions, with "Auditor" unchanged;
   - `\di uq_ref_role_label_lower` exists.
3. **Round 1, Edit Name:** as the Super Administrator at `http://localhost:3000/admin/access/dept_officer`:
   - Edit Name → "Department Officer (Legal)" saves, and the menu, cards and badges show it;
   - `GET /audit?action=access.type_edited` has one row with before and after;
   - renaming another type to "department officer (legal)" is refused with the field message;
   - renaming back restores it.
4. **Round 1, the menu:** at 1280 px, Administration opens with the 220 ms animation and the chevron turns. Opening
   Reports closes Administration. Keyboard only: Tab into the menu, then arrows, Right, Left and Enter. With "reduce
   motion" set in the OS, it opens at once. At 375 px the drawer shows the same tree.
5. **Round 2:**
   - **The picker:** as a Department Administrator, the Users filter's picker lists only their department's subtree;
     the Department Mapping picker lists the same; Audit Log is not in their menu;
   - **The modal:** User Details opens at `/admin/users/<id>`; End Membership opens the exit preview;
   - **Mapping:** adding a counsel code from Recommended From Cause Lists maps it, and the code leaves the panel; a
     rule's existing weight is still shown and clearable on Scoring.
6. **Round 3:**
   - **Cause List:** the day's date shows large with Lists Held; choosing a bench enables View Cause List; the modal
     shows the printed entries and the original PDF; Back closes it;
   - **The other pages:** Search, Department Cases, Reports, Queue and Audit Log show the header card.
7. **The browser check, each round:** `docker compose --profile uicheck run --rm uicheck`. No new finding at 375,
   768 and 1280 px, and the new states pass.
8. **The owner's browser check of the three rounds** against the mockup at 375, 768 and 1280 px. This is a separate
   backlog row at approval.

## Open questions
The owner's approval of this note adopts the recommended answers below. None blocks the design.

1. **"View Cause List".** This note reads it as a button in the Cause List's date zone that opens the **chosen
   bench's** list in a large modal over the page, with two tabs: the printed entries and the original PDF (decision
   25).
   - Other readings: one View button per bench in the day's bench list, or opening the PDF alone in a new tab.
   - **Recommended:** as designed.
2. **Department Mapping in the one-level menu.** The owner's revision of 25 Oct lists Department Mapping both among
   the entries that expand and among Administration's pages. Making it expand under Administration would be a second
   level.
   - **Recommended:** a leaf under Administration, with its five tabs on its page (decision 14).
   - Alternative: move it out of Administration to its own top-level Settings entry that expands to its five tabs.
3. **Reference-data values in Title Case.** These are case stages, note kinds, document types, pending actions,
   alert kinds and ticket kinds, shown as option names and badges. The mockup's sample shows some in Title Case
   ("Parawise Comments", "Prepare Reply").
   - **Recommended:** not in this item. They are values, not labels, and changing them needs another reference-data
     migration. A later row can do it.
4. **Existing per-rule weight overrides.**
   - **Recommended:** show them only on the Scoring tab under "Rules With Their Own Weight", with "Use the Standard
     Weight" to clear one (decision 40). No new override can be set from the portal.
   - Alternatives: clear all overrides once by a migration, or leave them active but invisible (refused: a hidden
     score input).
5. **"Sign Out Everywhere"** in the User Details menu.
   - **Recommended:** leave it out. There is no API, and Turn Sign-in Off already ends every session. If wanted, it
     becomes its own small row (a `POST /admin/users/{id}/sign-out` behind `users.enable_disable`, audited).
6. **The short descriptions** of the user types.
   - **Recommended:** the plan's Table 1 wording in decision 8. The mockup's texts are sample, and some claim
     functions the matrix does not give. The owner can change any of them with Edit Name.
7. **Three rounds.**
   - **Recommended:** split as in decision 46. Row 153 is round 1, and two new rows are added at approval for the
     administration round and the filters round.
