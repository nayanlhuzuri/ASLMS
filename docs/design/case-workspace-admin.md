# Design: Case workspace and Administration hub — plain case vocabulary, the case page with an action rail, the full remarks history, the Cases list and the user-type pages

```
slug: case-workspace-admin
status: awaiting-approval
author: architect
date: 2026-10-23
approved_by: <owner> on <date>
```

## Context
The owner made these decisions between 21 and 23 Oct 2026. They are fixed and are not reopened here:
1. **No eOffice vocabulary** in the portal, alerts, e-mails or user documents. The case itself moves between officers.
2. **Case page.** It follows template A, "Workspace with action rail".
3. **Remarks.** Every past remark and comment can be reached from the case page.
4. **Cases list.** It replaces Files.
5. **Administration.** It follows template A, "Settings hub", with user types as cards that open pages of plain-language switches.
6. **Redesign rules.** The rules of the UI redesign apply.

The visual reference is `docs/design/ui/aslms-final-template.html`, the mockup the owner approves together with this note. It holds only these screens:
- case-page template A, with the "See all remarks (n)" panel;
- the Cases list;
- Administration template A.

Where the mockup's sample data or function names differ from the system (for example, its function list and its "Release ownership" wording), this note and the code win.

The plan (`docs/Legal_Case_Monitoring_Portal_Plan.docx`, §5.7) describes custody as "similar to file movement in eOffice". That is an analogy. It does not fix screen words, so dropping the eOffice words changes no plan function. It is still flagged here (decision 1) because the plan's own wording is the analogy being removed.

What is in place and reused:
- **The round-3 case page** (row 103, `frontend/src/components/case/*`):
  - the summary header in `CaseFrame.tsx`, whose primary follows a fixed order: Send, else Claim, else Accept transfer;
  - the tabs as routes (`CASE_TABS`);
  - the dialogs in `components/workflow/*`: Send as 3 steps, Recall, Note, Stage and Upload.
- **The custody APIs** (`backend/aslms/api/routers/workflow.py`, `services/custody.py`):
  - `GET /cases/{ref}/custody`: the card plus the legs, oldest first, paged by 50. The remark is shown only when `shows_remark` allows it.
  - `GET /custody/held?scope=me|office|owned`: ordered by due date. `owned` needs `custody.track`.
  - `GET /custody/sent`: the caller's sends and recalls, newest first, with `visible`.
  - `GET /custody/summary`.
- **The notes API.** `GET /cases/{ref}/notes` returns the trail by `seq_no`. It takes `kind` and `include_superseded`, and gives each note `supersedes` / `superseded_by`. Every note passes the note visibility rule, and drafts are never listed.
- **The Files screen** (`components/files/*`):
  - `Held` and `Sent` on the shared `FilterBar` (design `portal-filters`);
  - `TrackingSummary`;
  - the side panel `FilePanel`.
- **The Administration frame.** `AdminFrame` on `SettingsLayout` already has the left sub-menu: Users, User types, Offices, Designations, Department mapping and Tickets.
- **Users and Access screens.** The Users list and full page (`Users.tsx`, `UserDetail.tsx`) and the old matrix table (`Access.tsx`).
- **The access APIs:**
  - `GET /admin/permissions`: code, module, label, description, is_active;
  - `GET /admin/access/types`;
  - `GET /admin/access/types/{role}`;
  - `PUT /admin/access/types/{role}/{permission}`: `access.manage_types`; one `access.matrix` audit row and one `access_changed` event per change; `admin.tickets` reserved; retired functions refused.
- **`aslms access matrix|set`.**
- **Function labels.** `PERMISSION_LABELS` in `services/access_seed.py`. The seed upserts them into `ref_permission` on every `init`.
- **`DEFAULT_MATRIX`.** The seed defaults per type, in the same file.
- **The kit.** `DataTable` (cards on phones), `SidePanel`, `Collapsible`, `Tabs`, `Lead`, `DateChip`, `Badge`, `useUrlOverlay` (row 115) and the motion helpers with their reduced-motion fallback.
- **`uicheck`.** Playwright at 375, 768 and 1280 px, with the field-row check of 23 Oct 2026.

Interactions with other rows:
- **Row 14 (Case Assistant, awaiting approval).** It adds an "Assistant" tab after Timeline and gives `assistant.use` the description used below.
- **Row 122.** Its migration may land before this one, so this item's reference-data migration takes the **next free number** at build time (0023, 0024 or 0025).
- **Row 134, finding 1.** `shows_remark` is given the bases merged across memberships. This item uses `shows_remark` as it stands and does not fix it. Row 134 does.
- **`docs/ASLMS_Process_Workflows.md`.** It uses the old words throughout and is listed for the **scribe** (decision 7). This item does not edit it.

Not covered:
- **Office statistics.** Out of scope: a separate MIS screen (owner, 23 Oct).
- **Template C's policies view and its full-matrix toggle.** Not built.
- **Template B (role builder).** Not built.
- **Internal code names.** They are not renamed (decision 2).
- **No new function, no new table, no new column.**

## Decisions

### A. Plain case vocabulary (owner decision 1)

1. **What users read is renamed. Code names stay.** Every user-facing "file" in the custody sense goes:

   | Old | New |
   |---|---|
   | Files (menu, page title, routes) | Cases |
   | Send file / Send the file | Send case / Send the case |
   | Recall / Recall the file / Recall files | Recall case / Recall the case / Recall cases |
   | File is with / Held by / file holder / who holds the file | With (the value is the designation, decision 13) |
   | Files with me | Cases with me |
   | Sent / Files I sent or recalled | Sent by me / Cases I sent or recalled |
   | Department files / Files of my department | Pending action / Cases of my department waiting on someone |
   | File received / File taken back / File overdue / File due (alerts, e-mails, dashboard) | Case received / Case recalled / Case overdue / Case due |
   | file remark | remark |
   | "You hold this file" (notes, drafts) | "This case is with you" |
   | "when the file is sent on or recalled / when the file moved" | "when the case is sent on or recalled / when the case moved" |
   | Files by office, Files I hold, Pending files, Overdue files (dashboard) | Cases by office, Cases with me, Pending cases, Overdue cases |
   | Files with a pending action (pending-actions report, screen and Excel/PDF headers) | Cases with a pending action |
   | List the files / with the file list (Reports form) | List the cases / with the case list |
   | Held file / file(s) (the exit step of a membership) | Case with them / case(s) |
   | No file record yet | No movement recorded yet |
   | Order column "File" | "PDF" |

   **Deviation (wording only)** from the plan's analogy, §5.7 "similar to file movement in eOffice". No function changes. Alternatives considered:
   - keep "file" where it reads naturally: refused, because the owner's rule is absolute;
   - also rename code names: refused, because the owner said users' words only.

2. **Code names, API paths and JSON stay unchanged.** All of these keep their names:
   - tables, enums, functions (`custody.move`, `custody.recall`, `custody.track`) and services;
   - API paths `/custody/*` and `/cases/{ref}/custody`;
   - every JSON field and code value: `holder_office`, `holder_user`, the `files` view and count of `/inbox/mine`, the attention kind `file_received`, the alert payload events `file_received` / `file_recalled`, the exit item kind `file` and its key prefix, the pending action `file`.

   **Recommendation adopted: the API's JSON field names stay.** Renaming them would break the generated types, the stored alert payloads and audit rows that name them, for no user benefit. API error `message` texts are read by people when the portal falls back to them, so their wording changes (decision 5). Internal TypeScript names (`components/files/*`, `FilesFrame`, `filesTabsFor`, the nav key `files`, query keys) may stay. Renaming them is allowed but not required. OpenAPI summaries are developer-facing and not required to change.

3. **Routes.** The Cases list lives under `/cases`, beside the case page:

   | Route | Shows |
   |---|---|
   | `/cases/with-me` | Cases with me |
   | `/cases/sent` | Sent by me |
   | `/cases/pending` | Pending action |
   | `/cases` | Redirects to the first tab the login may open; with no tab, to `/search` (which `/cases` showed until now) |
   | `/cases/[ref]` | The case page, unchanged |

   - The three list routes sit in a route group, `app/(portal)/cases/(list)/`, with their own layout.
   - Static segments win over `[ref]`. No case reference (a dash-form `ref_no`, a UUID or a CNR) can equal `with-me`, `sent` or `pending`. A test pins this.
   - The case breadcrumb "Cases" now leads to the Cases list.

   The old URLs redirect, keeping the query string. This uses a map like `OLD_INBOX_REDIRECTS`, called `OLD_FILES_REDIRECTS`:

   | Old URL | Redirects to |
   |---|---|
   | `/files` | `/cases` |
   | `/files/mine` | `/cases/with-me` |
   | `/files/offices` | `/cases/with-me?held=offices` |
   | `/files/department` | `/cases/pending` |
   | `/files/sent` | `/cases/sent` |
   | `/inbox/files` | `/cases/with-me` (decision 18; open question 2) |

   E-mails link to case pages, never to `/files`, so no e-mail link changes. Alternative: keep `/files/*` with new labels. Refused, because the owner listed routes in the rename.

4. **Reference labels that say "file".**
   - **`ref_note_kind`.** `file_noting` is labelled "File noting". It appears in the note composer, in note badges and in "New file noting" alert titles. It becomes **"Office note"** (open question 1).
   - **`ref_event_type`.** `custody_moved` has the timeline label "Custody moved". It becomes **"Case moved"** (open question 3).
   - **How they change.** A **reference-data migration** (the next free number) changes both rows. It changes a row only while it still holds the seeded label, so a label an administrator changed is left alone. The seed's dictionaries change too, so a fresh database matches.
   - **`ref_permission`.** Its labels and descriptions already follow `PERMISSION_LABELS` through the seed's upsert on every `init` (DB_STANDARD §0; the way row 14 also changes a description). They change there (decision 21) and need no migration.
   - Alternative: let the seed relabel everything. Refused for the note kind and the event type, because the owner asked for a migration and the seed refreshes only `ref_permission`.

5. **Backend texts users read** change wording only:
   - `services/alert_rules.py`, `render_workflow`, which feeds the in-app alert, the immediate e-mail and the daily digest:
     - "Case received from <office>: <case>"
     - "Case recalled by <office>: <case>"
     - "Case overdue since <date>: <case>" / "Case due <date>: <case>"
     - the body "The case you had is now with <designation, office> (<reason>)."
   - `services/dashboard.py`: `RECEIVED_TITLE` becomes "Case received".
   - `services/reports.py`: the pending-actions column and section labels.
   - `services/access_seed.py`: `PERMISSION_LABELS` (decision 21).
   - The API messages in `custody.py`, `notes.py`, `workflow_common.py` and `memberships.py` (the exit step). For example, "the case is already with that officer" and "only the officer the case is with (or, for a case with an office, its controller) may send it".
   - CLI help and output: `aslms reports --include-cases` ("one row per case"), the `aslms reports` summary line ("overdue cases"), `aslms users` exit help ("every allotted case and case with them needs a target").
   - `notifications.py` builds no wording of its own (it sends what `alert_rules` renders), but it is in the guard (decision 6).

   **Alerts already stored keep the title they were raised with.** That is the text that was shown and e-mailed, and rewriting it would falsify the record. New alerts use the new words (open question 5).

6. **A wording guard, in both test suites. It fails when "file" reaches user-facing text in the custody sense.**
   - **What it scans.** Every string constant and template piece:
     - Frontend: `frontend/src/lib/messages.ts` and the JSX text of `frontend/src/components/**`, through the TypeScript compiler API. Object keys are skipped.
     - Backend: `alert_rules.py`, `notifications.py`, `dashboard.py`, `reports.py`, `access_seed.py`, `seed.py`, `domain/workflow.py`, `custody.py`, `notes.py`, `workflow_common.py`, `memberships.py`, `cli/reports.py` and `cli/users.py`, through `ast`. Docstrings are skipped, and so are bare code constants matching `^[a-z0-9_.:{}]+$` (for example `"file"` and `"files"`).
     - The rendered title and body of every workflow alert event, from sample payloads.
   - **The rule.** A text containing `\bfiles?\b` (any case) fails unless it matches an entry of an **allow-list**.
   - **The allow-list** is data in each test, one regex and one reason per entry. It covers only the uploaded-computer-file sense and the legal verb:
     - "file type";
     - "PDF file" / "Word file(s)" / "Excel file";
     - "the file is larger" / "is empty" / "failed the virus scan" / "is already on the case" / "is uploaded";
     - "Attach (a) new file(s)" / "Up to n file(s)" / "At most n file(s)";
     - "No text in the file";
     - "File (PDF, Word or image)";
     - "Old Word files";
     - "File in court" (the pending action, a legal verb).
   - **The deny-list.** Phrases that fail even when an allow entry matches: `file (is )?with`, `hold(s|ing)? (this |the )?file`, `send (the )?file`, `recall(ing)? (the )?files?`, `files? (received|recalled|holder|remark|moved|movement|due|overdue)`, `files with`, `department files`.

   Alternatives:
   - a deny-list only: misses new phrasings;
   - rename every "file", the upload sense included: "the document is larger than the limit" reads oddly where the user picked a file from disk, and the owner's rule targets eOffice words.

   The reviewer checks that every allow entry is the upload sense.

7. **`docs/ASLMS_Process_Workflows.md`, the README's user sections and the runbook's user-facing lines** are for the **scribe** in this cycle's documentation step. This note only lists them. The developer does not edit them.

### B. The case page: template A, "Workspace with action rail" (owner decision 2)

8. **Layout.**
   - **Header.** The summary header stays on top, full width.
   - **Below it, two columns.**
     - Left: the tabs card, the existing routes and components unchanged, with row 14's Assistant tab when it lands.
     - Right: a **rail** 320 px wide (`--rail-w`, a new token), `position: sticky` under the shell's top bar. It is beside the tabs from 1100 px.
     - The main column has a minimum width of 640 px. The Overview's own two columns stack by **container width** (a container query on the tabs card), not by viewport, so they stack when the rail is present.
   - **Below 1100 px (768 and 375 px).** The rail's cards move **under the header, above the tabs**, as `Collapsible` cards:
     - "Your task" is open;
     - "Next hearing", "Quick actions" and "Journey" are closed, and each title line shows its key fact (the date, or "3 actions", or the latest move).

     The open or closed state lives in the component and is not stored.

   Alternative: the rail below the tabs on phones, as the mockup shows. Refused by the owner, because the task would be low on the page.

9. **The header.** It keeps:
   - the case number (`cno`);
   - the status badge;
   - the owner badge ("Your department" or the owner's code);
   - the parties line.

   One badge is added: **"Action due <date>"** (warning tone; danger and "Overdue since <date>" when overdue). It shows when the case is with the caller and has a due date. Five facts: Next hearing, **With**, Stage, **Owner department** and **Status**. The status label sits in the Status fact as well as the badge. On phones the badge stays and the Status fact is hidden.

   **Actions.** At most one primary, in the fixed order of row 103: **Send case** (`custody.can_send`), else Claim, else Accept transfer. A "More actions" menu holds Recall case, Enter next date, the ownership actions and Audit trail, each by its existing flag.

   Add note, Upload and Set stage **leave the header and the menu**. They live only in the rail's Quick actions (decision 12), so no action shows twice. On phones the rail cards sit under the header, so these actions stay one tap away.

10. **The "Your task" card**, from the overview's `custody` card (no new call). Four states:
    - **The case is with the caller** (`custody.holder_user.id` is the caller). The card shows:
      - the eyebrow "Your task";
      - the action needed (`pending_action_label`) in large type;
      - "From" with the sender's designation and office (`sent_by`);
      - "Due by" with the date and "n days left", or a danger "Overdue by n days";
      - the latest remark, quoted and clamped to 6 lines with "Show all";
      - the button **"See all remarks (n)"** (decision 14);
      - the hint "Done? Use Send case above to pass it on with your remark."
    - **The case is with someone else.** The eyebrow is "With <designation, office>", followed by the action, the due date and the latest remark, but only when the API returned it. The remark is left out when hidden, with no placeholder. "See all remarks (n)" or "See the journey (n)" follows (decision 14). When `can_recall` is true, **Recall case** shows as a secondary danger button. It is never primary (one primary per page).
    - **A case with an office and no officer.** "With <office name>" replaces the designation.
    - **No custody** (an unclaimed case). One muted line: "The case moves between officers once a department claims it." No buttons.

11. **The "Next hearing" card.**
    - **Content.** The weekday and date, the court number and the item (as printed, else the serial) when the latest listing is that day (the header's rule), and a countdown.
    - **The countdown is in whole IST days:** "Today", "Tomorrow" or "In n days". There are no hours or minutes. ASLMS does not hold the hearing time, and a guessed 10:30 would be a made-up fact.
    - *Owner, 23 Oct 2026:* the date is always shown with the countdown, in the header fact and in the rail card (for example "Wed, 28 Oct 2026 · in 5 days").
    - **Badges.** The 48 h and "this week" badges of the header rule stay.
    - **No next date.** "No next hearing date yet". When `workflow.next_dates` is set, an "Enter next date" link opens the existing dialog.

    **Deviation** from the mockup, which shows days, hours and minutes.

12. **The "Quick actions" card.** Add note (`workflow.note_mode`), Upload (`workflow.upload`) and Set stage (`workflow.set_stage`) as secondary buttons. They open the existing `NoteDialog`, `UploadDialog` and `StageDialog`, unchanged: visibility chosen every time, pre-checks, virus scan, drafts for the person the case is with. A flag that is off hides its button. With none on, the card is not shown.

13. **"With" shows the designation.** The text is "<designation>, <office name>", with "(you)" for the caller. The person's full name appears only when the membership has no designation, and as the title attribute. The text is built once, in `lib/cases.ts` `withText`, and used by:
    - the header fact;
    - the rail;
    - the Cases list;
    - the side panel;
    - the remarks history.

14. **The "Journey of this case" card** is a short trail: the **latest 4 movements**, newest first, from `GET /cases/{ref}/custody?order=desc&limit=4` (decision 23). Each row has:
    - the date and time;
    - who it went to ("With …"), with "(you)";
    - the reason when it is not a send (Claimed, Allotted, Recalled, Taken over, Transferred, Reassigned on an officer's exit);
    - the remark clamped to 2 lines, only when the API returned it.

    The newest row has the "now" marker.

    **"See all remarks (n)":**
    - It sits in the Your task card.
    - **n** is the response's `total`: every movement, each a remark entry, including any without a remark.
    - When the response's new `remarks_shown` is false for this caller, the label reads **"See the journey (n)"**, and the panel says once that remarks are shown only to the people working on the case.
    - The Journey card has no second button. Its footer link "Journey and stage" opens the existing tab (open question 3).

### C. All past remarks and comments (owner decision 3)

15. **The remarks history** is a wide `SidePanel` titled "Remarks and notes" on the URL overlay `?remarks=all` (`useUrlOverlay`): Back closes it and the link can be shared. Two tabs inside:
    - **"Remarks (n)".** Every movement, **newest first**, from `GET /cases/{ref}/custody?order=desc`, 50 at a time with "Show more". Each entry has:
      - the date and time in the `DateChip` lead;
      - a heading: "Sent by <actor designation, office> to <holder designation, office>", "Recalled by …", or "Claimed by <department> — with …";
      - "Action asked: <label>";
      - "Due by: <date>", or "No due date";
      - the **full remark** (pre-wrapped, never clamped), or nothing when the API returned none.
    - **"Notes (m)".** The notes trail **in order** (by `seq_no`, oldest first, as the Notes tab), from `GET /cases/{ref}/notes?include_superseded=true`, 50 at a time:
      - **Filter.** A **kind** filter (a select of the selectable note kinds from `GET /workflow/codes`; "All kinds" by default), passed to the API's `kind`.
      - **Each note:** kind badge, author designation and office at the time, date and time, visibility badge, the full body, and attachments as on the Notes tab.
      - **A correction** shows "Corrects NOTE/…" with the note it supersedes **inline under it**: muted, labelled "Corrected note", and folded behind "Show the corrected note". It is taken from the loaded page, else from `GET /notes/{note}`.
      - **A superseded note** in its own place shows "Corrected by NOTE/…" and links to the correction.
      - **Notes the caller cannot read are never listed** (the API's note rule).
      - No drafts.

    Nothing in the panel writes. Alternatives:
    - a new combined endpoint: refused, because both APIs already return everything needed and the change is two read-only fields and a sort parameter (decision 23);
    - a page instead of a panel: refused, because the owner asked for a button that opens the history from the rail.

16. **Visibility stays on the server.**
    - **The legs.** They are listed to anyone who can see the case (`require_visible`).
    - **The remark.** It comes only from `shows_remark`: a working basis, or a State-wide reader holding `cases.view_private_all` (row 121).
    - **Notes.** Each note passes the note rule (per-note visibility, `notes.view_private_office`, `notes.view_counsel_shared`, `cases.view_private_all`).
    - **The frontend never infers a hidden remark.** It only reads `remarks_shown`.

### D. The Cases list (owner decision 4)

17. **Tabs** (`CASES_TABS` in `routes.ts`, each its own route):

    | Tab | Shows when | API |
    |---|---|---|
    | **Cases with me** | `cases.view_scope` or `cases.view_all` | `GET /custody/held?scope=me` |
    | **Sent by me** | the same functions | `GET /custody/sent` |
    | **Pending action** | a department membership holding `custody.track` (`tracksDepartment`, the API's rule) | `GET /custody/held?scope=owned`, with `TrackingSummary` above |

    Each list keeps:
    - its shared `FilterBar` and its list key (`held`, `held_owned`, `sent`);
    - "Overdue only";
    - on Pending action, the holder department, relabelled "Department it is with";
    - paging by 50.

    **"My offices"** is no longer a tab. Cases with me gains a **"Held by" segmented control, "Me" / "My offices"**, in the filter bar's own controls, as `?held=offices`. It maps to `scope=office`, so nothing is lost and the owner's three tabs hold.

    Pending action for a login without `custody.track` is open question 4. The recommendation is hidden, as Department files is today.

    Alternative: a fourth tab. Refused, because the owner named three tabs.

18. **The Case inbox's "Files with me" tab** (`/inbox/files`) shows the same list as Cases with me. It is **removed**, and `/inbox/files` redirects to `/cases/with-me` (open question 2). The `files` view of `/inbox/mine` stays, because it feeds the navigation count.

19. **Rows** use the Work list template, a `DataTable` that becomes cards on phones and when it cannot fit:
    1. **The lead badge**, a fixed `Lead` column of 96 px;
    2. **Case and parties**: the number (`cno`) over "petitioner vs respondent";
    3. **Action needed**;
    4. **Due by**: danger text when overdue;
    5. **From** on Cases with me (the sender, `withText` of `sent_by`), **With** on Pending action (the holder), **Sent to** on Sent by me (the leg's holder; decision 20);
    6. the chevron, hidden on phones.

    Since and Sent by move to the side panel. A recall row on Sent by me shows "Recalled" as a small label under the case number.

    The lead badge comes from one pure function, `leadBadge(row, tab)` in `lib/cases.ts`, first match wins:

    | Tab | Rule | Badge |
    |---|---|---|
    | Cases with me / Pending action | `card.overdue` | **Overdue** (danger) |
    | Cases with me / Pending action | `card.due_soon` (new server field, decision 23) | **Due soon** (warning) |
    | Cases with me | `card.since` within the last 48 h | **New** (info) |
    | Pending action | anything else | **Waiting** (neutral) |
    | Cases with me | anything else | no badge; the column keeps its width |
    | Sent by me | `current` and overdue | **Overdue** |
    | Sent by me | `current` and due soon | **Due soon** |
    | Sent by me | `current` | **Waiting** |
    | Sent by me | not current, or not known | no badge |

    "Due soon" uses the server's `request_due_soon_days`, the same window as `GET /custody/summary`, so screens and counts agree.

20. **The side panel** (`FilePanel`, titled "Case details") keeps:
    - the row's facts: With, Action needed, Since, Due by, From;
    - the **full remark** (the API's rule; on Sent by me it is the caller's own);
    - **"Open case page"** when the case can be opened.

    It never acts. Sending and recalling stay on the case page.

    On Sent by me:
    - the "Sent to" header names the leg's holder;
    - when `current` is false the row is muted;
    - for a case the caller can no longer open, `current` is null and the row says nothing about where the case went (decision 23).

21. **Navigation and other screens:**
    - **Navigation.**
      - The sidebar entry "Cases" (key `files` may stay) points to `/cases`.
      - Its pill counts cases with me, from `/inbox/mine/counts`, unchanged.
      - The phone bottom bar shows "Cases".
      - Crumbs: "Cases", "Cases with me", "Sent by me", "Pending action".
    - **Dashboard.**
      - The KPI is "Cases with me", linked to `/cases/with-me`.
      - The attention line for `file_received` reads "Case received".
      - "Department files" links go to `/cases/pending`.
    - **Reports.** The Reports form's link to the live list reads "The live list of your department's pending cases, with remarks, is under Cases:" and points to `/cases/pending`.

### E. Administration: template A, "Settings hub" (owner decision 5)

22. **The hub.**
    - **Sub-menu.** `AdminFrame`'s left sub-menu (a select on phones) stays as built, with Users, User types, Offices, Designations, Department mapping and Tickets, each by its existing functions. The sub-menu shows no counts (office and people statistics belong to the MIS screen, out of scope).
    - **Offices, Designations, Department mapping and Tickets** keep their screens. They are checked against the kit and the field-row rule by `uicheck` and by nothing else.

23. **Users** (`/admin/users`):
    - **The list.** A searchable, filterable `DataTable`:
      - **Search** by name or e-mail: `q`, 2 or more characters, as today.
      - **Filters:** User type (`role`), Office (the code, subtree, as today), and a new **Status** filter:
        - "Active": a login that is on and has signed in;
        - "Not signed in yet": on, never signed in;
        - "Off": sign-in turned off.
      - The super admin's "Include logins without an office" stays.
    - **Columns:**
      - the avatar initials in a fixed lead;
      - name over designation and office (the primary membership);
      - user-type badges (one per active membership, at most 2 and "+n");
      - status badge;
      - chevron.
    - **The side panel.** A row opens a wide `SidePanel` on the URL overlay `?user=<id>`. It holds the existing `UserDetail` sections, unchanged in behaviour:
      - the login card (name, designation, mobile, e-mail correction, sign-in on or off, password reset, sign out everywhere);
      - memberships with their type, designation and functions panel (overrides with the delegation rule);
      - the exit step;
      - documents.

      Its footer has "Open full page" to `/admin/users/[id]`, which stays for deep links and audit-trail links.
    - **"Add user"** is the page's one primary. It opens the existing new-user flow (e-mail lookup first) in the same panel, `?user=new`.
    - **Server rules unchanged.** Every rule stays on the server: scope, delegable types, granting only functions held, the head through tickets, the audit rows.

24. **User types index** (`/admin/access`). One **card per type**, in `ref_role` order. Each card shows:
    - the label and description (`GET /reference/labels`);
    - **users**: logins with an active membership of that type in the caller's scope;
    - **"n of N functions on"**;
    - an amber **"n changed from default"** when not zero.

    The counts come from a new read-only endpoint (decision 27). A card opens `/admin/access/[role]`. Readable with `users.view`; changing needs `access.manage_types`.

25. **The user-type page** (`/admin/access/[role]`):
    - **Header.**
      - Back link "All user types".
      - The type's name and description.
      - "n users · n of N functions on".
    - **Toolbar** (one field row, by the field-row rule):
      - a search over label and description ("Find a function, e.g. recall");
      - an "Only changed from default" chip;
      - **"Reset to default"**, secondary. It sets the draft to the defaults and saves nothing.
    - **Groups.** One card per plain-language group (decision 26), titled with "n of m on". Each function is a row with:
      - a `switch` (`role="switch"`);
      - the label and a one-line description;
      - an amber "Changed from default" badge, measured against the defaults (decision 27), when the draft differs from the default.
    - **The sticky Save bar** at the bottom:
      - "No unsaved changes" or "n unsaved changes", counted against the saved state;
      - Discard (ghost);
      - **Save changes**, the page's one primary, disabled at 0.

      The bar's count change uses the motion helper and falls back to no animation under reduced motion.
    - **Leaving with unsaved changes** asks first. This covers in-app links (a confirm dialog) and closing the tab (`beforeunload`).
    - **Locked rows:**
      - The **super admin** type shows every switch on and disabled, with one line: "The super admin always holds every function."
      - **`admin.tickets`** is shown disabled with "Reserved to the super admin".
      - Retired functions are not shown.
    - **Read-only view.** Without `access.manage_types` every switch is disabled, and the bar is replaced by "Only the super admin changes user types."
    - **Save sends one batch** (decision 27). On success the saved state refreshes and a notice says "Saved. The change is in the audit log." On refusal nothing is saved, and the error names the function.

    The old `AccessMatrix` table is removed. `aslms access matrix` stays the full-matrix view for audits.

26. **Plain-language groups are data, on the server.**
    - **Where.** `PERMISSION_GROUPS` in `services/access_seed.py`, next to `PERMISSION_LABELS`: an ordered list of (code, label, functions in order). Every **active** function is in exactly one group, which a pytest proves.
    - **What the API returns.** `GET /admin/permissions` adds `group`, `group_label` and `sort_in_group`. The page renders in that order, so the frontend holds no copy of the mapping. A vitest proves that the page puts every function it is given under its group's heading.
    - **The groups** (51 active functions):

      | Group | Functions |
      |---|---|
      | **People and access** (11) | users.view, users.create, users.edit, users.set_type, users.enable_disable, users.grant, users.reset_password, users.propose_head, access.manage_types, offices.manage, admin.designations |
      | **Cases and ownership** (12) | cases.view_scope, cases.view_all, cases.view_private_all, cases.search_court, cases.claim, cases.dismiss, cases.suggest_elsewhere, cases.transfer_request, cases.transfer_decide, cases.allot, cases.release, cases.take_over |
      | **Case work** (8) | custody.move, custody.recall, custody.track, stages.set, notes.add, notes.view_counsel_shared, notes.view_private_office, assistant.use |
      | **Documents** (3) | documents.view, documents.upload, documents.download |
      | **Alerts** (2) | alerts.acknowledge, next_dates.review |
      | **Reports** (4) | reports.department, reports.state, dashboard.state, audit.view |
      | **Administration** (11) | admin.counsel_codes, admin.keywords, admin.watchlist, admin.scoring, admin.masters_sync, admin.napix_refetch, admin.config, admin.sourcetrace, admin.data_load, admin.service_health, admin.tickets |

    Alternative: the mapping in the frontend. Refused, because one source beside the labels and a server test is simpler to keep true.

27. **New access reads and one batch write.** The API had neither defaults nor user counts.
    - **`GET /admin/access/defaults`** (`users.view`): `DEFAULT_MATRIX` over the active functions, in the matrix's shape. The super admin's row is all on.
    - **`GET /admin/access/overview`** (`users.view`): per type, the users in the caller's scope (the State for the super admin and State-wide readers; the caller's office subtrees otherwise, as `GET /admin/users`), plus functions on, functions total and changed from default.
    - **`PUT /admin/access/types/{role}`** (`access.manage_types`): `{changes: [{permission, enabled}]}`, at most 60. It runs in **one transaction**:
      - each change goes through the existing `access.set_matrix`, so each changed function writes its own `access.matrix` audit row and `access_changed` event, as the one-cell PUT does;
      - entries equal to the current value are skipped (no audit);
      - any refusal (the super admin type, `admin.tickets`, a retired or unknown function) rejects the whole batch.

    The one-cell PUT and `aslms access set` stay unchanged.

    Alternative: the page sends one PUT per change. Refused, because a failure halfway would leave a type half-saved, with no way for the Save bar to say what happened.

### F. Redesign rules and checks (owner decision 6)

28. **Redesign rules.** Every new or changed screen uses the tokens and the kit. New tokens: `--rail-w` 320 px and `--savebar-h`.
    - **The alignment rule.**
      - The Cases list's lead badge sits in a 96 px `Lead`.
      - The remarks history's dates sit in a `DateChip`.
      - The Users list's avatar sits in a fixed lead.
    - **The field-row rule of 23 Oct.** It applies to the Cases filter bar, the remarks Notes kind filter, the Users filters and the user-type toolbar: label tops and box tops on one line within 1 px, and a bare button dropped by `--label-offset`.
    - **One primary per page:**

      | Page | Primary |
      |---|---|
      | Case page | Send case, Claim or Accept transfer |
      | Cases list | none |
      | Users | Add user |
      | User types index | none |
      | User-type page | Save changes |

    - **Motion.** The rail cards, the panel and the Save bar use the motion helpers, with the reduced-motion fallback.
    - **Phones at 375 px.**
      - The rail becomes collapsible cards under the header.
      - Lists become cards.
      - The Save bar spans the width above the bottom bar.
      - Switch rows stack the description under the label.

29. **`uicheck`** gains:
    - **Fixtures** in `frontend/e2e/fixtures/synth.ts`:
      - custody history with `order=desc` and `remarks_shown`;
      - held items with `due_soon`;
      - sent items with `current`;
      - notes with a correction and its superseded note;
      - `/admin/permissions` with groups;
      - `/admin/access/defaults`;
      - `/admin/access/overview`;
      - `/admin/users` with each status.
    - **Routes:** `/cases/with-me`, `/cases/sent`, `/cases/pending`, `/admin/access/<type>`. The `/files/*` routes are checked as redirects.
    - **States** at all three widths unless stated:
      - `/cases/with-me (side panel)`, replacing `/files/mine (side panel)`;
      - `/cases/<ref> (send case, step 1)`, with the button name "Send case";
      - `/cases/<ref>?remarks=all (remarks panel)`;
      - `/cases/<ref> (rail cards open)` at 375 and 768;
      - `/admin/users?user=<id> (side panel)`;
      - `/admin/access/<type> (two switches changed, Save bar)`.

## Data
**No new table, no new column, no change to `docs/schema/schema.md`'s tables.**

One **reference-data migration**, numbered as the **next free number** at build time (0023 after row 14 or row 122, else later). It changes two seeded labels, and only where they still hold the seeded text:
- `UPDATE ref_note_kind SET label = 'Office note' WHERE code = 'file_noting' AND label = 'File noting'`;
- `UPDATE ref_event_type SET timeline_label = 'Case moved' WHERE code = 'custody_moved' AND timeline_label = 'Custody moved'`.

The downgrade reverses each change under the mirror condition. The migration writes no `audit_log` row: reference-data migrations of the seed's own labels have never been audited (migration 0016 precedent), and the seed's `ref_permission` relabelling is reported by `aslms seed` in the same way.

The seed matches for fresh databases:
- `NOTE_KIND_LABELS[NoteKind.FILE_NOTING] = "Office note"`;
- a new `EVENT_TIMELINE_LABELS = {EventType.CUSTODY_MOVED: "Case moved"}`, read by `_extra_columns`.

The existing `_relabel_note_kinds` already relabels a row still holding the default label, so the seed and the migration agree.

`ref_permission` labels, descriptions and the new group fields: labels and descriptions follow `PERMISSION_LABELS` through the seed's upsert (no migration). The groups are not stored. They are data in code, returned by the API (decision 26).

## Services
- **`services/custody.py`:**
  - **`history(..., order="asc")`.** `order` is `"asc" | "desc"` on `seq_no`. The result adds `remarks_shown` (the `shows_remark` value already computed). Any other `order` value is refused with 422 at the router.
  - **`card()`.** It adds `due_soon`: not overdue, and `due_date <= today + request_due_soon_days`, read from settings as in `summary`.
  - **`sent()`.** Each item adds `current`: true when the leg is the case's current leg (`custody.current_leg_id == leg.id`), false otherwise. It is **null when the caller cannot open the case** (`visible` false), so the sender learns nothing about a case they can no longer see.
  - **Message texts reworded** (decision 5).
  - No new audit. These are reads.
- **`services/access.py`:**
  - **`defaults()`.** `DEFAULT_MATRIX` over `ACTIVE_FUNCTIONS`, plus the super admin all on.
  - **`overview(session, user)`.** Per `Role`:
    - `users` is the count of distinct logins with an active membership of that role. It is scoped with the same roots `GET /admin/users` uses: all for the super admin and State-wide readers, else the caller's membership subtrees.
    - `functions_on`, `functions_total` (active functions) and `changed_from_default` (against `defaults()`).
    - Reads only.
  - **`set_matrix_batch(session, actor, user, role, changes)`.** It checks every change first (the same refusals as `set_matrix`), then calls `set_matrix` for each change that differs from the current value. It returns the role's row. One transaction, from the router's session. Audit and events come from `set_matrix`, one per changed function.
- **`services/access_seed.py`:**
  - `PERMISSION_LABELS` rewritten in plain language (the table below).
  - New `PERMISSION_GROUPS` (decision 26).
  - The module docstring says "notes and documents" for "notes, files".
- **`services/users.py` or the users router's query.** The `status` filter (`active` / `not_signed_in` / `off`) on `is_active` and `last_login_at`, counted in `X-Total-Count`.
- **`services/alert_rules.py`, `dashboard.py`, `reports.py`, `notes.py`, `workflow_common.py`, `memberships.py`, `cli/reports.py`, `cli/users.py`:** wording only (decision 5).
- **`services/seed.py`:** the two label dictionaries (Data).

New `PERMISSION_LABELS`. The description is one line, shown under the switch. Row 14's `assistant.use` description is kept as row 14 sets it.

| Function | Label | Description |
|---|---|---|
| users.view | See users | See the people of the offices you look after. |
| users.create | Add users | Create a sign-in for a new officer, with a user type, in an office you look after. |
| users.edit | Edit user details | Change a person's name, designation and contact details. |
| users.set_type | Change a user's type | Move a person to another user type. |
| users.enable_disable | Turn sign-in on or off | Stop or restore a person's access; nothing they did is deleted. |
| users.grant | Give or take single functions | Switch one function on or off for one person, within your own functions. |
| users.reset_password | Reset passwords | Set a new password for a person. |
| users.propose_head | Propose a new head | Ask the super admin to change the head of a department, and follow the ticket. |
| access.manage_types | Change user types | Switch functions on or off for a whole user type. |
| offices.manage | Manage offices | Add, rename, move and close departments and directorates. |
| admin.designations | Manage designations | Keep the State-wide list of posts up to date. |
| cases.view_scope | See the office's cases | Cases owned by, allotted to, or sent to the offices you belong to. |
| cases.view_all | See all cases | Every case in the State, in every department. |
| cases.view_private_all | See private records too | With See all cases: notes, documents and remarks kept private to an office. |
| cases.search_court | Search the High Court | Look up a case at the court by CNR, number, party, advocate or filing number. |
| cases.claim | Claim cases | Take a recommended or unclaimed case for the department. |
| cases.dismiss | Dismiss recommendations | Say a recommended case is not the department's. |
| cases.suggest_elsewhere | Suggest another department | Point a recommended case to the department it belongs to. |
| cases.transfer_request | Ask for a transfer | Ask another department to take over a claimed case. |
| cases.transfer_decide | Decide transfers | Accept or refuse a transfer asked of the department. |
| cases.allot | Allot cases | Give a case of the department to an officer to work on. |
| cases.release | Stop watching | End the department's watching role on a case. |
| cases.take_over | Take over a case | Take over a case allotted to a colleague in the same department. |
| custody.move | Send cases held by an office | Send on a case that is with an office rather than an officer; whoever has a case can always send it. |
| custody.recall | Recall cases | Call a case of the department back from whoever has it. |
| custody.track | Track pending cases | See every case of the department that is waiting on someone, with due and overdue alerts. |
| stages.set | Set the stage | Record where the department's work on a case stands. |
| notes.add | Add notes | Write notes on a case; a note is never edited, a correction is a new note. |
| notes.view_counsel_shared | Read notes shared with counsel | See notes and documents marked for the Standing Counsel. |
| notes.view_private_office | Read office-only notes | See notes kept private to your own office. |
| assistant.use | Use the Case Assistant | Ask the Case Assistant about cases and court orders. |
| documents.view | See documents | Open documents you are allowed to see. |
| documents.upload | Upload documents | Add court papers and internal documents (PDF, Word, images) to a case. |
| documents.download | Download documents | Save a copy of a document you are allowed to see. |
| alerts.acknowledge | Acknowledge alerts | Mark an alert as seen and dealt with. |
| next_dates.review | Confirm next dates | Confirm, reject or enter the next date read from an order. |
| reports.department | Department reports | Run and download the department's reports. |
| reports.state | State reports | Run and download reports across all departments. |
| dashboard.state | State dashboard | See the State-wide dashboard. |
| audit.view | Read the audit log | Search who did what, and when. |
| admin.counsel_codes | Counsel codes | Link standing-counsel codes to departments. |
| admin.keywords | Keywords and name patterns | Words and names that point a case to a department. |
| admin.watchlist | Watchlist | Cases a department always wants to follow. |
| admin.scoring | Scoring weights and bands | How strongly each signal counts, and the strong and possible bands. |
| admin.masters_sync | Refresh court masters | Reload case types and benches from the court, and run the connection check. |
| admin.napix_refetch | Fetch court data again | Fetch a cause list, a case or an order again from the court, and retry failed fetches. |
| admin.config | System settings | Change system settings. |
| admin.sourcetrace | Case Assistant intake | See which court orders and filings went to the Case Assistant, and retry failures. |
| admin.data_load | Data collection | Start, pause and order the historical load, fetch single cases and check duplicates. |
| admin.service_health | System health | See whether the court APIs and ASLMS services work, and test a court API with one call. |
| admin.tickets | Decide admin tickets | Decide the requests that need the super admin (reserved to the super admin). |

The retired `requests.send` / `requests.answer` keep their labels. They are never shown.

## API
All changes are additive and read-only, except the one batch write. JSON names are unchanged (decision 2). OpenAPI and `frontend/src/lib/api/schema.d.ts` are regenerated.

| Method and path | Function (`Permission`) | Change |
|---|---|---|
| GET `/cases/{ref}/custody` | case visibility (`read`: `cases.view_scope` or `cases.view_all`, then `require_visible`) | New query `order=asc\|desc` (default `asc`, so existing callers are unchanged). `CustodyHistoryOut` adds `remarks_shown: bool`. The remark per leg is still from `shows_remark`. |
| GET `/custody/held` | `read`; `scope=owned` needs `custody.track` | `CustodyCardOut` adds `due_soon: bool`. The card is shared, so the overview's `custody` and the move responses carry it too. |
| GET `/custody/sent` | `read` | `SentItemOut` adds `current: bool \| null` (null when `visible` is false). |
| GET `/cases/{ref}/notes` | `read`, each note through the note rule | Unchanged. Already has `kind` and `include_superseded`. |
| GET `/notes/{note}` | `read`, note rule | Unchanged. Used for a superseded note outside the loaded page. |
| GET `/admin/permissions` | signed in (unchanged) | `PermissionOut` adds `group: str \| null`, `group_label: str \| null` and `sort_in_group: int \| null` (null for retired functions). |
| GET `/admin/access/defaults` | **`users.view`** | **New.** `dict[str, dict[str, bool]]`: role → active function → default. |
| GET `/admin/access/overview` | **`users.view`** | **New.** `list[UserTypeCardOut]`: `{code, users, functions_on, functions_total, changed_from_default}`. Users are counted in the caller's scope. Labels come from `/reference/labels`. |
| PUT `/admin/access/types/{role}` | **`access.manage_types`** | **New.** Body `MatrixBatchIn {changes: list[{permission: Permission, enabled: bool}]}` (1 to 60, no duplicate permission, else 422). Response `dict[str, bool]` (the role's row, as the one-cell PUT). 403 for `super_admin`. 400 `{code: "reserved" \| "retired", message}` for `admin.tickets` or a retired function, and nothing is saved. Audit `access.matrix` per changed function. |
| GET `/admin/users` | `users.view` (unchanged) | New query `status=active\|not_signed_in\|off`, counted in `X-Total-Count`. |

Route order: `PUT /admin/access/types/{role}` sits beside the existing `PUT /admin/access/types/{role}/{permission}`, with no path clash. `GET /admin/access/defaults` and `/overview` are declared before any `{role}` path.

No endpoint is added for the Cases list, the rail or the remarks history beyond the fields above.

## Jobs
None. No schedule or queue change.

## Tests
Backend (`pytest -q`, database tests on the scripted world of `tests/db/conftest.py`):
- **`tests/db/test_custody_history_order.py`:**
  - `order=desc` returns the legs newest first and pages from the newest;
  - `order=asc` and no `order` are unchanged;
  - `remarks_shown` is true for a working basis, true for a State-wide reader with `cases.view_private_all`, and false for State oversight and the central operator, whose legs carry no remark;
  - a caller who cannot see the case gets 404.
- **`tests/db/test_custody_card_due_soon.py`.** `due_soon` follows `request_due_soon_days`: false when overdue, false with no due date, true on the window's last day.
- **`tests/db/test_custody_sent_current.py`:**
  - `current` is true for the case's current leg;
  - it is false after the case moved on or was recalled;
  - it is **null** when the sender can no longer open the case;
  - `visible` is unchanged.
- **`tests/db/test_access_defaults_overview.py`:**
  - the defaults equal `DEFAULT_MATRIX` over active functions, with the super admin all on;
  - `users` counts distinct logins in the caller's scope: a department admin sees only their subtree's logins and the super admin sees all;
  - `changed_from_default` counts after one matrix change;
  - `users.view` is required (403 without).
- **`tests/db/test_access_matrix_batch.py`:**
  - a batch of 3 changes writes 3 `access.matrix` audit rows and 3 `access_changed` events;
  - an unchanged entry writes none;
  - a batch with `admin.tickets` or a retired function is refused with 400, and **none** of its changes is saved;
  - the `super_admin` type gets 403;
  - without `access.manage_types` the answer is 403 (a department admin);
  - duplicates or more than 60 changes get 422;
  - the one-cell PUT still works.
- **`tests/unit/test_permission_groups.py`:**
  - every active `Permission` is in **exactly one** group of `PERMISSION_GROUPS`;
  - no retired function and no unknown code is in any group;
  - groups and their order match the API's `group` and `sort_in_group`;
  - every active function has a label and a one-line description (no newline, at most 120 characters).
- **`tests/db/test_users_status_filter.py`.** `status=active`, `not_signed_in` and `off` each return the right logins with the right `X-Total-Count`. Scope is unchanged.
- **`tests/db/test_migration_<n>_reference_labels.py`:**
  - the upgrade relabels `file_noting` and `custody_moved` when they hold the seeded text;
  - it leaves an administrator-changed label alone;
  - the downgrade restores;
  - the seed on a fresh database gives the same labels.
- **`tests/unit/test_wording_guard.py`.** The backend guard of decision 6:
  - the `ast` scan of the listed modules;
  - the rendered workflow alert titles and bodies for `file_received`, `file_recalled`, due and overdue;
  - the allow-list and deny-list as data with reasons;
  - a self-test that "Send file" and "the file is with" fail and "The file is larger than the limit" passes.
- **Existing tests updated, rules unchanged.** The alert, dashboard, report and custody tests that assert the old wording. Their assertions about **who** gets what (`test_custody_remark_visibility.py`, `test_alerts_*`, `test_visibility_*`, the delegation tests in the access suite) must pass **unchanged**.

Frontend (`vitest`):
- **`src/lib/wording.test.ts`.** The frontend guard of decision 6, over `messages.ts` and component JSX text, with the same allow-list and deny-list idea and a self-test.
- **`src/lib/cases.test.ts`:**
  - `leadBadge` for every row of decision 19's table, the 48 h edge included;
  - `withText`: designation and office, "(you)", an office with no officer, and the name only when there is no designation;
  - the hearing countdown: "Today", "Tomorrow", "In n days", computed in IST across midnight.
- **`src/components/case/rail.test.tsx`:**
  - the four Your task states;
  - Recall case shows only with `can_recall` and is never primary;
  - the remark is absent when the API omits it;
  - "See all remarks (n)" against "See the journey (n)" by `remarks_shown`;
  - Quick actions follow the three workflow flags and the card hides with none;
  - Add note, Upload and Set stage are not in the header menu;
  - the journey shows 4 rows newest first;
  - below 1100 px the cards render as collapsibles with Your task open.
- **`src/components/case/remarks.test.tsx`:**
  - Remarks newest first, with who, to whom, when, action, due and the full remark;
  - "Show more" pages;
  - the Notes tab is in `seq_no` order;
  - the kind filter passes `kind`;
  - a correction shows its superseded note folded under it;
  - a superseded note links to its correction;
  - `?remarks=all` opens and Back closes the panel.
- **`src/components/files/files.test.tsx`** (or a renamed `cases-list.test.tsx`):
  - three tabs, with Pending action only with `custody.track`;
  - "Held by: My offices" sends `scope=office`;
  - the columns per tab;
  - the side panel shows the full remark;
  - `/files/*` and `/inbox/files` redirect with the query string kept;
  - `/cases` goes to the first tab, else `/search`.
- **`src/components/admin/userTypes.test.tsx`:**
  - the cards show users, "n of N on" and "n changed";
  - the type page groups follow the API's groups;
  - search filters;
  - "Only changed from default" filters;
  - "Changed from default" badges are correct;
  - "Reset to default" changes the draft only;
  - the Save bar counts and Discard clears;
  - Save sends **one** `PUT /admin/access/types/{role}` with only the changed entries;
  - a 400 shows the named function and keeps the draft;
  - super admin switches and `admin.tickets` are disabled;
  - the page is read-only without `access.manage_types`;
  - leaving with changes asks first.
- **`src/components/admin/admin.test.tsx`.** The Users status filter, and the side panel at `?user=<id>` with "Open full page".
- **`src/app/pages.test.tsx`.** The one-primary test covers the new routes. `/cases/with-me` cannot be read as a case reference.
- **`uicheck`.** The fixtures, routes and states of decision 29. It exits 0 with `findings.json` empty at 375, 768 and 1280 px.

## Verification
1. **Static checks.**
   - `ruff check` clean, `ruff format` applied, `pytest -q` green.
   - In `frontend/`: `npm run lint`, `npm run typecheck` and `npx vitest run` green.
   - OpenAPI and `schema.d.ts` regenerated, with no diff left.
2. **Migration.** The integrator applies the reference-data migration with the `migrate` step (`docker compose --profile ops run --rm migrate`), then `init` (seed).
   - `select label from ref_note_kind where code='file_noting'` gives `Office note`.
   - `select timeline_label from ref_event_type where code='custody_moved'` gives `Case moved`.
   - `select count(*) from ref_permission where label ilike '%file%'` gives `0`.
3. **Wording on the running stack.**
   - `grep -niE "\bfiles?\b" frontend/src/lib/messages.ts` lists only allow-listed upload-sense lines.
   - Both wording guards pass.
   - On the dev stack, send a case to a test officer. The new alert title starts "Case received from". The Mailtrap e-mail subject and body use "case", and the digest line too.
   - Older alerts keep their old titles.
4. **API checks** (a super admin session, `curl` through the dev proxy):
   - `GET /admin/access/defaults` has 10 types × 51 active functions.
   - `GET /admin/access/overview` has 10 entries, and the users counts add up to the active memberships by type.
   - `PUT /admin/access/types/dept_officer` with two changes gives 200 and two new `access.matrix` rows in `GET /audit?action=access.matrix`. Reverse them the same way.
   - The same PUT including `admin.tickets` gives 400, and the audit count is unchanged.
   - `GET /cases/{ref}/custody?order=desc&limit=4` gives the newest leg first and `remarks_shown`.
5. **Browser checks** (owner and tester at 1280, 768 and 375 px, signed in on the dev stack):
   - **Case page.** The header has one primary, "Send case". The rail shows Your task with the action, due date, sender and latest remark. "See all remarks (n)" opens the panel: remarks newest first with full text; notes in order, filtered by kind; a correction shows the corrected note. At 375 px the rail cards sit under the header and fold.
   - **Cases list.** It has three tabs with lead badges in one column. "Held by: My offices" works. `/files/mine` lands on `/cases/with-me`.
   - **Administration.** Users: search, filter by status and open the side panel. User types: cards with counts. Department officer: flip two switches, the Save bar says "2 unsaved changes", Save, and the audit log shows two entries.
   - **Department admin view.** Signed in as a department admin, User types is read-only, and Users shows only their department's people.
6. **`uicheck`.** `docker compose --profile uicheck run --rm uicheck` exits 0 with `findings.json` empty. The run directory under `./data/uicheck/` is recorded in the cycle report.

## Open questions
The status is `awaiting-approval` because each point below has a recommended answer that this note already uses. When the owner approves the note and the mockup together, the recommendations are accepted unless the owner says otherwise.

1. **New label for the note kind "File noting".**
   - **Recommended:** "Office note".
   - Other options: "Noting" (still eOffice usage) or "Internal note" (confusable with internal documents).
2. **The Case inbox's "Files with me" tab** repeats Cases with me.
   - **Recommended:** remove it and redirect `/inbox/files` to `/cases/with-me` (decision 18).
   - Other option: keep it, relabelled "Cases with me", at `/inbox/with-me`.
3. **"Custody" in what users read.** This covers the "Custody and stage" tab, the Case-page "Custody" fields and the "Custody" timeline label. It is not eOffice vocabulary, but the rail calls the same record "the case's journey".
   - **Recommended:** rename the tab to "Journey and stage", "Custody" in user text to "Journey", and the timeline label to "Case moved" (in the migration).
   - Other option: keep "Custody". The migration then changes only the note kind.
4. **"Pending action" for a login without `custody.track`.**
   - **Recommended:** hidden, so the tab means "the department's cases waiting on someone" (today's Department files). It is shown to department heads and admins by default.
   - Other option: give every login a personal Pending action (cases with them that have an action, plus cases they sent that are still waiting). That needs a new list query, so it would be a further item.
5. **Alerts already stored with "File received" titles.**
   - **Recommended:** leave them as they were shown and e-mailed.
   - Other option: a one-off command to rewrite stored titles. Not recommended, because it changes the record of what was sent.
