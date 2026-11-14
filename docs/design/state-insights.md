# Design: State Insights, the cross-filtering analysis page under Oversight

```
slug: state-insights
status: approved
author: architect
date: 2026-11-14
approved_by: owner on 2026-11-14
```

## Context
Backlog row 258. Decisions log entry "State Insights (owner, 13 Nov 2026)". The owner approved a mock built on the dev
data (the "State Overview Dashboard Mock") and answered "go with your defaults" for the eight decisions and the
default export fields. Row 258 comes after rows 250 `order-sections` and 257 `offices-import` (build order of
13 Nov 2026: 257, 189, 250, 258, 251 to 253).

**What the owner asked for.** The page is called **Insights** and sits under **Oversight**, with Reports and Audit Log
unchanged. Today's Dashboard stays the home page. The Dashboard answers "what do I need to do today". Insights
answers "what is the state of our litigation, and where are the problems".
- Every chart, headline figure and the case list re-count on any click. There are no tabs. Filters show as
  removable chips with Clear All, and a Pending / Disposed / All switch sits on top.
- Charts: headline figures; kind of case by age; next hearing bands; age; year filed; by department in three bands
  never added together; posts named; subject groups; counsel codes; registrations against disposals; outcomes.
- An accountability section: action status, compliance with court directions, offices holding overdue files and a
  department scorecard.
- Filters for the next hearing band, and a date filter (Date Of with From and To).
- A case list, 20 a page, with Excel and PDF export of the filtered list.
- State-wide or one department, by function.

**Plan.** The plan has no page by this name. Insights extends plan §5.1 (the State oversight dashboard: "case counts by
department, upcoming hearings across the State, overdue actions and compliance status") and §5.10 (Reports:
"management information for departments and State oversight … exported to Excel and PDF"). The owner approved it on
13 Nov 2026. It is an addition, not a deviation. Decision 8 adds a signal to plan §4.2's recommend-and-claim scoring.
Plan §4.2 lets the super admin change the weights. The rule "never assign a case automatically" is untouched.

**What is in place.**
- Case visibility (`services/visibility.py`: `member_bases`, `visible_case_condition`, `never_owned`, `codes_condition`).
- The shared case filters (`services/case_filters.py`, row 59).
- The dashboard State block (`services/dashboard.py::state_block`: the claimed, recommended, hearing, overdue-file and
  compliance queries, `compliance_flags`, `open_compliance_conditions`, `_overdue_files`).
- The report machinery (`services/reporting_common.py` with `AGE_BANDS`, `with_timeout` and `department_rows`;
  `services/report_export.py`, which writes Excel with XlsxWriter and PDF with PyMuPDF `Story`; the audit action
  `report.exported`).
- The matching engine (`services/matching.py`: signal kinds, noisy-OR, `ENGINE_VERSION = "2"`) and the mapping
  administration (`services/matching_rules.py`: generic `f"{entity}.{action}"` audit).
- The function registry (`domain/reference.py::Permission`, `services/access_seed.py` with `DEFAULT_MATRIX` and
  `PERMISSION_GROUPS`; `RESERVED_FUNCTIONS` in `services/access.py`; the delegation rule in `assert_can_manage`).
- The row 190 hearing bands (`frontend/src/lib/hearingDate.ts::hearingBand`, the kit `HearingDate`).
- The portal kit (`DataTable`, `FilterChips`, `DateRangeField`, tokens of row 229) and the uicheck at 375, 768, 1024
  and 1280 px.

**What the dev data says** (read-only queries, 14 Nov 2026, inside `BEGIN TRANSACTION READ ONLY`):
- 83,941 live cases (not merged), 37,199 of them pending.
- 243 distinct court categories plus 3,264 cases with none. A category is printed as `<5-digit code> - <label> ( <n> )`;
  235 carry a code, and 8 malformed values (`( 20240 )`) carry none.
- 57 case types in use, all covered by the mock's kind-of-case list.
- **Interlocutory applications:** 14,724 cases of types 218, 220 and 221, 5,470 of them pending. 14,695 have a
  `case_links` `main_matter` row and 14,122 of those resolve to a held case. Without IAs, 31,729 cases are pending.
- **Contempt:** 1,582 pending (types 142, 229, 174 and 228). None has a `main_matter` link, so the original writ
  must be read from the order text. 343 latest orders cite a WP(C); the mock counted 1,229 across all orders.
- **State cases by party name and counsel code only:**
  - A State of Assam or Government of Assam party marks 52,729 cases.
  - A government counsel code (GA, PP, AG forms with ASSAM) marks 42,179.
  - Together they mark 53,987, or **18,830 pending without IAs**.
  - These two tests mark only **11 of the 1,582 pending contempt cases**. Contempt respondents are officers named
    personally: 663 carry a service tag (`, IAS`, `, ACS`), and only 76 have any counsel code. 872 latest-order cause
    titles name the Government of Assam or a department. This is why decision 6 adds the service-tag, cause-title and
    original-writ bases.
- **Department named:**
  - NAPIX respondent party names name a department in 3,698 cases.
  - The cause titles of the latest orders name one in 16,091 cases (41,816 cases have order text).
  - Order text is the richer source, and row 250 locates the cause title in it.
- **Ownership:** two Department-tier offices (SEC-EDU, IT); 5 claimed cases; 2,121 open recommendations to SEC-EDU;
  custody for 4 cases. Until row 257 imports the 56 departments, the department charts are thin. Every chart says
  what it covers (decision 4).

**What this does not cover.**
- The court data itself: no NAPIX call and no new collection.
- The AI: Insights uses no model, through any path.
- Directions with time limits read from order text as a compliance source. Compliance here is the existing
  `compliance_due` alerts. Row 250's extracted directions can feed it later, as row 250's own follow-up.
- District Court cases (plan Phase 3). The fact and group tables are keyed by court so they extend later.
- A replacement of the Dashboard or the four Reports. Nothing existing moves.

## Decisions

### A. Shape, rounds and prerequisites

1. **Three rounds, one backlog row each (proposed split).** The whole item is too large for one cycle: a new derived
   table and job, grouping masters, a mapping list, an aggregate service, exports, a new chart library, a page and a
   settings screen, and a change to the matching engine. The split:
   - **Round 1, row 258 `state-insights` (backend):**
     - migration 0039;
     - the per-case fact table and its job;
     - the rule readers (State case, departments, posts, original writ);
     - the subject and kind-of-case groups and the cause-title names, with their administration APIs;
     - the Insights service (scopes, cross-filtered aggregates, case page);
     - the Excel and PDF export;
     - three functions, the CLI `aslms insights`, the data-health block, `schema.md`, the runbook and tests.
   - **Round 2, new row `state-insights-portal` (frontend):** Recharts pinned and wrapped in kit components; the
     `/insights` page with filters in the URL, chips, headline figures, every chart with "View as Table", the
     accountability section and the case list; the export dialog; the Insights Groups settings screen; the Names in
     Cause Titles list on Department Mapping; the uicheck states; the user guide. No migration.
   - **Round 3, new row `cause-title-signal`:** decision 8's recommendation signal in the matching engine. It needs a
     `scoring_settings` column and its own migration, engine version 3, the reason text in Case Claim and a rescore
     (decisions 36 to 40). It touches recommend-and-claim, so it is reviewed on its own.

   Round 2 can be designed and approved with this note: its decisions are written here (section J). Round 3 is
   specified here in full, so its row only needs the owner's go-ahead.
   *Alternatives:* one cycle (rejected: too large to test and review well); backend and frontend together with the
   signal later (rejected: the backend alone is already a full cycle).
2. **Row 250 is a hard prerequisite.**
   - Without row 250, the cause titles cannot be read reliably. The regex over whole order texts took 35 s and misses
     the 7% of orders off the template.
   - The State test then finds 11 of 1,582 pending contempt cases (Context).
   - The department and post readings fall back to NAPIX party names, which name a department in 3,698 cases instead
     of 16,091.

   The owner's order already puts 258 after 250. **What Insights needs from row 250's output** (a contract for row
   250's design, which is not yet written):
   - (a) per order with text: the **cause title span**, as start and end character offsets in
     `document_text.full_text` (the part between the case-number block and `Advocate for …` or `BEFORE`), with the
     PDF fingerprint and parser version row 250 already keeps;
   - (b) the **`Linked Case :` block** entries as printed (case-number texts);
   - (c) the layout flag (template followed or kept whole), so that Insights skips a title it cannot locate rather
     than guess.

   Insights does the reading itself over those spans: the department phrases, the posts, the Government of Assam test
   and the original writ (decisions 7 to 10). Row 250 needs no knowledge of Insights.
   - If row 250's design names the table or columns differently, Insights follows row 250.
   - If row 250 cannot give the span, this note returns to the owner.

   The fact builder also reads NAPIX party names always. So the code and tests work without `order_sections`, and the
   title source is added when present (decision 11). *Alternative:* a soft dependency, building Insights first on
   party names (rejected: contempt, the owner's first concern, would be almost empty).
3. **Row 257 is a soft prerequisite.** The department bands and the automatic matching of cause-title names to
   departments (decision 9) need the departments to exist. Insights works with any set of offices. The dev database
   has two departments today. The row 257 import brings 56, and the next fact refresh picks them up.

### B. Data and what it covers

4. **Every chart says what the data covers.**
   - The response carries `coverage`: the court (Gauhati High Court); `listed_since`, the earliest held cause-list date
     (3 Jan 2025 on dev, the first sitting day after the load's start of 1 Jan 2025; the real date is used rather than
     the load's start date); the facts' freshness; and the selection words.
   - Each chart card prints one line, for example "Cases listed since 3 Jan 2025 · State cases (worked out) ·
     Pending · Interlocutory applications inside their main case".
   - The department charts also say "Only departments in ASLMS appear; N cases name a department not yet in ASLMS".
5. **Interlocutory applications inside their main case (owner's decision 2).**
   - A case whose case type is in the reserved kind-of-case group `ia` (types 218, 220 and 221 in the draft) is an IA.
   - By default IAs are left out of every figure, chart, list and export.
   - The main case's list row and export show "Applications Pending: n", a live count of pending IA cases whose
     resolved `main_matter` link points to it.
   - The headline area prints "n pending interlocutory applications are counted inside their main case (m whose main
     case is not held in ASLMS are left out)".
   - The switch "Include Interlocutory Applications" (`include_ia=true`) counts IAs as cases of their own.
   - Other subordinate types with `main_matter` links (MC, Crl.L.P., CO) stay cases of their own. The owner's decision
     names IAs only.
6. **Which cases are State cases (owner's decision 1).** No court field says so, so the rule works it out and labels it
   "worked out". A case is a State case when it has at least one basis:
   - `party`: a current petitioner or respondent party name matches the State form
     `STATE OF ASSAM|GO?VE?R?N?ME?N?T\.? OF ASSAM` (the mock's pattern, case-insensitive).
   - `officer`: a current respondent name carries a government service tag after a comma or space: `IAS`, `IPS`, `IFS`,
     `ACS`, `APS`, `AFS` or `ACS (…)`, as a whole word. Contempt respondents are named this way.
   - `counsel`: a printed counsel code (current cause lists or current `case_advocates`, normalised by
     `NORMALISED_CODE_SQL`) is one of these:
     - an active generic State code (`counsel_codes.is_generic_state`);
     - a code mapped exactly to a department (active, not generic);
     - a government designation form: first part in `GA`, `SR. GA`, `SR.GA`, `SR. GA ADV.`, `PP`, `ADDL. PP`, `AG`,
       `ADDL. AG`, `ADDL AG`, `SR. AG` (from `matching.GENERIC_PARTS`), with no other part or with the last part
       `ASSAM`.

     An unmapped `SC, <office>` code does not count: standing counsel also appear for Union bodies, universities and
     the High Court.
   - `title`: the cause title (row 250 span) names the Government of Assam, the State of Assam or a department mapped in
     ASLMS (decision 9).
   - `writ`: a contempt case whose original writ (decision 10) is held and is itself a State case.
   - `claimed`: the case has an active primary ownership. A department said it is theirs. This basis is evaluated
     live, not stored.

   The default view is "State Cases Only" (`state_only=true`); the switch shows all cases. The case list and export
   show "State Case: Yes (Parties, Counsel Code)" with the bases in words. Dev numbers with `party` and `counsel` only:
   18,830 pending without IAs. `officer`, `title` and `writ` add to that (Verification).
   *Alternatives:* party names only (rejected: misses contempt); any `SC,` code (rejected: Union and university counsel).

### C. The readings by rule (owner's decision 4: no AI)

7. **One pure rule module, `services/insights_rules.py`, with `READER_VERSION = "1"`.** Every reading is a regular
   expression over upper-cased text with collapsed whitespace and `&` read as `AND`, written once and unit-tested on
   real examples from the dev data. No model, no Ollama, no SourceTrace. The version is stored on every fact row; a
   change of version makes every row dirty (decision 12).
8. **Department phrases.**
   - **What is read:** the respondent side of the cause title (the part of row 250's span after `VERSUS`) and the
     current respondent party names. `DEPTT.`, `DEPTT`, `DEPT.` and `DEPARTMENT` are read alike.
   - **Two forms are read:**
     - `DEPARTMENT OF <X>`, with X stopping at a comma, a full stop, `;`, `(`, `DISPUR`, `GOVERNMENT`, `GOVT`,
       `ASSAM` as a last word, `AND ANR` / `AND ORS` or the end;
     - `<X> DEPARTMENT`, with X after a comma, the start, or `GOVT. OF ASSAM,` / `GOVERNMENT OF ASSAM,`.

     For example, "THE COMMISSIONER AND SECRETARY TO THE GOVT. OF ASSAM, FINANCE DEPARTMENT" gives `FINANCE`.
   - **The phrase's normal form:** a leading `THE` is dropped; single-letter section marks such as `(B)` are dropped
     (`PERSONNEL (B)` → `PERSONNEL`); whitespace is collapsed; length is 3 to 80.
   - **Stop words** never form a phrase: `THE`, `SAID`, `CONCERNED`, `STATE`, `GOVERNMENT`, `SAME`.

   The phrases are stored as read (`title_phrases`); mapping them to departments is decision 9.
9. **Phrases to departments: the new master `office_title_names`, plus an automatic match on the department's own
   name.**
   - **Automatic match:** a phrase that equals the "core" of a Department-tier office's name names that department.
     The core is the name upper-cased, with `DEPARTMENT OF`, `DEPARTMENT`, `DEPTT`, `DEPT` and `THE` removed,
     punctuation dropped and `&` read as `AND`. For example, "Finance Department" → `FINANCE`, and "Department of
     Revenue and Disaster Management" → `REVENUE AND DISASTER MANAGEMENT`.
   - **Explicit mapping:** any other printed form (`SECONDARY EDUCATION`, `PWD`, misspellings such as `PESONNEL`) is
     mapped by a row of `office_title_names` (phrase → office). The row is managed like counsel codes, in the office
     subtree, with the function `admin.keywords` ("Keywords and Name Patterns: words and names that point a case to a
     department").
   - **Attribution:** a phrase mapped to a directorate counts for its Department-tier ancestor (as scoring does).
   - **Unmapped list:** `GET /admin/title-names/unmapped` lists the phrases no mapping and no automatic match names,
     most cases first. This is the counsel-code pattern.
   - **Counsel attribution:** a case is also attributed to a department "by counsel code" when a printed code is
     mapped exactly to it (active, not generic, as `visibility.codes_condition`). Partial code matches are not used:
     they are possible matches, not firm attribution (partial-code-match decision 15).

   *Alternatives:*
   - hard-coded phrase groups as in the mock (rejected: the departments and their codes come from the owner's
     workbook, row 257, and change);
   - reusing `office_name_patterns` (rejected: those feed the name-pattern signal at weight 0.8 and are written for
     party names, not for department phrases);
   - word-level matching (rejected: "EDUCATION" sits in four departments' names).
10. **Posts and the original writ.**
    - **Posts** are read over the same respondent texts as decision 8. A case holds every post found. The fixed list,
      as code, label and rule:
      - `addl_chief_secretary`, Additional Chief Secretary;
      - `principal_secretary`, Principal Secretary;
      - `commissioner_secretary`, Commissioner and Secretary;
      - `secretary`, Other Secretary: a whole-word SECRETARY not part of the three above;
      - `dgp`, Director General of Police;
      - `director`, Director: a whole-word DIRECTOR not followed by GENERAL OF POLICE and not after MANAGING;
      - `deputy_commissioner`, Deputy Commissioner;
      - `superintendent_police`, Superintendent of Police: the full form only, since "SP" is ambiguous;
      - `chief_engineer`, Chief Engineer;
      - `executive_engineer`, Executive Engineer;
      - `inspector_schools`, Inspector of Schools;
      - `deeo`, District Elementary Education Officer (`ELEMENTARY EDUCATION OFFICER` or the whole word `DEEO`);
      - `circle_officer`, Circle Officer;
      - `chief_executive`, Chief Executive or Managing Director.

      The list is code, not a table (the owner asked for posts read by rules, not edited). A new post is a code change
      with a new `READER_VERSION`.
    - **The original writ, for cases in the reserved kind-of-case group `contempt` only.** The sources, in order:
      1. row 250's `Linked Case :` entries that read as a writ number;
      2. the first 3,000 characters of the body of the case's earliest order with text.

      The patterns are `W.P.(C)` / `WP(C)` / `W.P.(Crl.)` / `WA` with an optional `No.`, then the number, then `/` or
      `of`, then a four-digit year from 1950 to the current year. They are written as `WP(C) 4326/2025`.
      - The text is stored as read (`original_writ_text`).
      - `original_writ_case_id` is set only when ASLMS holds that case: same court, case type by the master's short
        name or aliases, `reg_no` and `reg_year`.
      - Nothing is invented: an unresolved writ stays text.
      - The link is not written to `case_links`, which holds court data. A rule's reading stays in the derived table.

      A linked contempt case takes the writ's subject group (decision 15) and, through the `writ` basis, its State
      status.

### D. The fact table and its job

11. **A derived per-case fact table, refreshed by a job; aggregates stay live over `cases` joined to it.** Measured on
    dev (Context's database; 24 cores, `shared_buffers` 1 GB, `work_mem` 16 MB; warm unless stated):

    | Query | Time |
    |---|---|
    | B1: per-case readings from parties, counsel codes, orders and main matter, all 83,941 cases | 2.9 s (7.6 s cold) |
    | B2: cause title by regex over each case's latest order text, 41,816 cases, no row 250 offsets | 35.0 s |
    | B3: one-scan cross-filter, 7 grouping sets, pending (37,199) | 146 to 159 ms (401 ms cold) |
    | B4: the same over all statuses (83,941) | 261 to 342 ms |
    | B6: the same joined to an 84k-row fact-table stand-in | 308 to 340 ms (678 ms cold) |
    | B5: case page, 20 rows with the who-has-it text | 5 to 17 ms; total count 28 ms |
    | B7: registrations against disposals, 12 months | 47 ms |
    | B7: outcomes | 53 ms |
    | B7: counsel codes read live from cause lists | 364 ms (from the fact table instead) |
    | B7: department bands | 3 ms |
    | B9: export query, every pending case (37,199) with the default fields | 655 to 738 ms |

    - **Why the split:** the expensive, slowly changing readings (B1, B2) cannot run per request. The live columns
      (status, dates, next hearing, ownership, recommendations, custody) are cheap and must never be stale.
    - **What is stored:** the fact table holds only the readings. Status, the dates, the next hearing, ownership,
      recommendations, custody and closures are read live at every request.
    - **Estimated cost:** a whole overview response (one grouping-set scan, the multi-valued charts, trend, outcomes
      and accountability) is about 0.6 to 0.9 s warm today.
    - **Targets:** overview p95 ≤ 1.5 s (cold ≤ 3 s); case page ≤ 300 ms; export query ≤ 5 s; Excel file of 100,000
      rows ≤ 60 s.
    - **At three times today's size** (about 250,000 cases), the overview is estimated at about 2 s. When the API's
      request metric (row 77) shows a p95 above 2 s, the follow-up is to copy the live columns into the fact table or
      add a short result cache. Neither is built now.

    *Alternatives:*
    - all live (rejected: 3 to 35 s per request);
    - a materialised view (rejected: `REFRESH` rebuilds everything, and a concurrent refresh needs a unique index and
      locks);
    - a full cube of pre-counted cells as in the mock (rejected: visibility must be applied per viewer, which a
      pre-counted cube cannot do).
12. **When a fact row is rebuilt.**
    - **The job `insights-refresh`, every 10 minutes** (minute 4, 14, …), rebuilds the facts of cases that are:
      - without a row;
      - changed since the row (`cases.updated_at > built_at`);
      - given a new or changed `orders` row, or a new `order_sections` row, since the row;
      - given a new cause-list entry resolved to them since the row;
      - carrying an older `READER_VERSION`.

      At most `INSIGHTS_REFRESH_BATCH` cases (default 5,000) per run, oldest first.
    - **A mapping save** (counsel code, cause-title name) or a new or changed Department-tier office makes the
      department attribution dirty. The job then re-derives `named_title_department_ids` and
      `named_counsel_department_ids` for every row from the stored phrases and codes, in one SQL statement (no text is
      read again). The saves also dispatch the job at once, one run at a time, as mapping saves dispatch
      `rescore-dirty`.
    - **`insights-rebuild` at 04:45 IST** rebuilds every row. B1 takes about 3 s; with row 250's spans, the cause-title
      reading reads only the span of each case's latest titled order. It runs after the 03:00 dedupe sweep and the
      04:15 gap sweep.
    - **CLI:** `aslms insights refresh [--all] [--dry-run]` and `aslms insights status`.

    The job never calls NAPIX and never writes court data. Its counters go to `job_runs`.
13. **Fact rows are updated in place and never deleted.** A merged case keeps its row, and readers join live cases
    only. The department attributions are `uuid[]` columns of Department-tier office ids, not a child table. A child
    table would need DELETE, which `aslms_app` has only on the standard's cascade list.

    **Deviation (DB_STANDARD, keys):** PostgreSQL has no foreign keys on array elements, so these two columns have no
    FK. Offices are never deleted (every FK to `offices` is RESTRICT; offices are deactivated), so no id can dangle.
    The builder writes only ids of Department-tier offices, and a database test checks every stored id against
    `offices`.
    *Alternative:* a child table `insight_case_departments` with DELETE added to the standard's list (rejected: it
    widens the deletion rule for a derived convenience).

### E. Groupings (owner's decision 5)

14. **Two groupings, one master: `insight_groups` with `kind` = `subject` or `family`.** The categories map to subject
    groups (`insight_subject_categories`), and the case types to kinds of case (`insight_case_type_groups`). A
    composite foreign key on (group_id, kind) lets a category point only at a subject group, and a case type only at
    a kind of case.
    - **Reserved codes** cannot be deactivated or recoded; their labels can be edited:
      - in `family`: `contempt` (the contempt figure and the original-writ reading), `ia` (decision 5) and `other`
        (the fallback);
      - in `subject`: `contempt` (contempt cases without an original writ).
    - **Who edits:** the Super Administrator only, through the reserved function `admin.insights_groups` (as
      `admin.tickets`: never granted, held by the super admin alone). The owner said "editable later by the Super
      Administrator".
    - **What they can do:** add a group, rename it, reorder it, deactivate a group that is not reserved, and move
      categories and case types between groups (a batch Save, one audit row per changed line).
    - **When it takes effect:** at once. The mapping is joined at query time, so no rebuild is needed.

    *Alternative:* `ref_*` tables (rejected: `ref_*` sets are seeded code sets; these are edited at run time with audit,
    which is a master).
15. **The draft subject groups are in `docs/design/state-insights-subject-groups.md`** for the owner's review: 15
    groups over the 235 coded categories, with every category, its case count and its pending count. The groups:
    - Service: State Government Employees;
    - Service: Teachers of Provincialised Schools;
    - Service: Local Bodies, Undertakings, Universities and Defence;
    - Education and Academic Matters;
    - Land and Revenue;
    - Foreigners Tribunal and Citizenship;
    - Tax and Duties;
    - Contracts, Settlements and Licences;
    - Panchayat, Municipal, Elections and Co-operatives;
    - Labour and Industrial;
    - Criminal Matters and Bail;
    - Civil Appeals, Revisions and Suits;
    - Rights, Detention and Public Interest;
    - Contempt (Original Subject Not Yet Known);
    - Other Writ and Procedural Matters.

    Merging the three service groups into one would give 13. The owner asked for "about 12"; the draft keeps them apart
    because they answer to different departments.
    - **Cases without a category:** 3,273 cases with no category or a malformed one show as "No Category", never
      guessed.
    - **New categories:** a category the court adds later is inserted by the fact job with no group and shows as "Not
      Grouped" until the Super Administrator places it.
    - **Contempt cases** take the subject of their original writ when it is linked (decision 10), else "Contempt
      (Original Subject Not Yet Known)".
16. **The kinds of case are seeded from the mock's list.** The mock's list covers all 57 case types in use, and every
    other case type starts in "Other". The kinds:
    - Writ Petition;
    - Writ Petition (Criminal) and Habeas Corpus;
    - Public Interest Litigation;
    - Contempt;
    - Writ Appeal;
    - Motor Accident Appeal;
    - Civil Appeal;
    - Criminal Appeal;
    - Bail;
    - Criminal Petition (Section 482);
    - Revision;
    - Review;
    - Transfer;
    - Arbitration;
    - Tax and Customs;
    - Election;
    - Company;
    - Testamentary and Succession;
    - Interlocutory Application (`ia`);
    - Other (`other`).

    The mapping is by court and `case_type_code` in the migration and the seed, and lands on the court's `case_types`
    rows. There is no writ / criminal / civil chart; the kind of case covers it (owner, mock).

### F. Scope, functions and visibility (owner's decision 7)

17. **Three new functions.** No schema change is needed: the seed inserts their `ref_permission` and missing
    `role_permissions` rows at `init`, as close-case did.

    | Code | Name | Description (≤ 120 characters) | Default types |
    |---|---|---|---|
    | `insights.state` | View State Insights | See the Insights page for the whole State: charts, the case list and exports. | State Oversight |
    | `insights.department` | View Department Insights | See the Insights page for your own department and its units. | Department Head, Department Administrator |
    | `admin.insights_groups` | Insights Groups | Group the court's subject categories and case types for Insights. | reserved: Super Administrator only |

    - They join the "reports" group of `PERMISSION_GROUPS` after `dashboard.state`, and are appended to the
      `Permission` enum so earlier sort orders stay.
    - Grants per user type and per user use the existing matrix and overrides, under the delegation rule (a granter
      grants only functions they hold). Every change is audited as today.
    - The Super Administrator holds all three. Nobody else has either Insights function by default.
18. **State scope.** `scope=state` needs a membership that holds `insights.state` **and** is State-wide (the super admin,
    or `cases.view_all`). Otherwise the request answers 403 `state_scope_not_state_wide`. Counting "the whole State"
    through a narrower visibility would mislabel the numbers.
    - The scope's case set is every live case, ANDed with `visible_case_condition` of that membership. That condition
      is `true` for a State-wide membership. The visibility is still applied, as defence in depth.
    - A State-wide holder may also open `scope=department&department=<code>` for any department. This is the
      department view of that department, as the dashboard lets `dashboard.state` holders open any department.
19. **Department scope.** `scope=department` needs a membership in that department holding `insights.department` (or
    the State-wide case of decision 18).
    - **The case set:** the department's three bands (decision 21: claimed, likely or named), ANDed with
      `member_bases` of **that one membership**.
    - **What is left out:** the unclaimed pool a department head can see through the `pool` basis, unless the case is
      in a band. "Department Insights" is about the department's cases, and the visibility rule keeps it to what the
      person may open.
    - **Several departments:** a person with the function in several departments gets a switch. `department=<code>`
      chooses, the primary membership's department is the default, and the response lists the choices (as the
      dashboard's department switch does).
    - **A membership below department level** that has been granted the function sees its department's bands within
      what that membership may open. A dealing officer would see only cases assigned to them or their unit.
    - **The department view** replaces "By Department" with "By Unit" (decision 22) and leaves out the State
      scorecard.
20. **Visibility on every query, on the server.**
    - Every aggregate, the case page and the export AND the scope condition into the SQL.
    - Nothing is filtered in the portal, and nothing after the query.
    - The who-has-it text and the "Recommended to" field name other departments only in the State scope. In a
      department scope they name the viewer's own department or say "Not Claimed". Other departments'
      recommendations stay theirs.
    - Insights never reads a note, a draft, a custody remark, a document or a document description. A static test
      scans the Insights modules for those tables and columns.

### G. Charts, filters and cross-filtering

21. **Three department bands, never added together (owner's decision 3).** For a case C and a department D:
    - **Claimed**: an active primary `case_ownership` of D on C.
    - **Likely (Recommended, Not Claimed)**: an open recommendation of D on C (status `recommended`), and not claimed
      by D.
    - **Named in the Cause Title or by Counsel Code**: D is in `named_title_department_ids` or
      `named_counsel_department_ids`, and C is neither claimed by D nor likely for D.

    The bands of one department are disjoint. They are drawn side by side, never stacked, with no total. The State
    adds no department figures together; "Not Claimed by Any Department" is its own headline figure.

    The label says "Recommended, Not Claimed", never "not assigned": "Assign" means placing a claimed case with a unit
    or officer (row 178). The backlog row's "recommended not assigned" means exactly this band.
22. **The charts and what each counts.** Every chart counts with every filter except its own dimension, inside the
    scope, the status switch, "State Cases Only" and "Include Interlocutory Applications". Bars are clickable and set
    their dimension's filter; clicking the selected bar again removes it.

    | Chart | Dimension and buckets | Notes |
    |---|---|---|
    | Headline figures | Cases; State Cases; Contempt Cases; Over 5 Years; Hearing in Next 7 Days; Not Claimed by Any Department | Counted with **all** filters. A click sets `kind=contempt`, `age=over_5`, `next=within_7`, `action=not_claimed` or `state_only=true`. |
    | What Kind of Cases, and How Old | kind of case × age band, stacked | Top 10 kinds with Show All. Excludes the `kind` filter only, so the age filter narrows the stacks. |
    | Next Hearing | Today, Tomorrow, In 2 to 7 Days, In 8 to 30 Days, Later, Date Passed, No Date Yet (plus Disposed when status is all) | Bands by IST date over `cases.next_hearing_on`, the row 190 rule; colours from the row 190 tokens. |
    | How Long Pending / How Long It Took | the NJDG age bands of `reporting_common.AGE_BANDS` (Up to 1 Year … Over 30 Years, Age Not Known) | Pending: today − registration date (filing date when none). Disposed: disposal − registration. The same bands as the Pending Cases report. |
    | Since When: Year Filed | registration year (filing year when none): the last 8 years and Earlier | |
    | By Department (State) / By Unit (department) | departments × three bands, or units by assigned unit of claimed cases plus the department's three band totals | Top 15 departments by their largest band, with Show All. Unit = the child office of the department holding `case_ownership.unit_office_id`, or "Not Yet Assigned to a Unit". |
    | Against Whom: Post Named | the posts of decision 10, multi-valued | A case naming two posts counts once in each. |
    | Subject of the Case | subject group, No Category, Not Grouped | |
    | Who Appears for the Government | printed counsel codes, multi-valued, top 10 with Show All | "Counsel code printed by the court on cause lists; a court fact, not ownership." |
    | Is the Backlog Growing? | registrations against disposals per IST month, last 12 months | Ignores the status switch and the date filter (its axis is dates). A month click sets Date Of: Registration (or Disposal) to that month. |
    | How Cases End | outcome buckets over disposed cases | Ignores the status switch. Buckets by rule over `disposal_type`, in this order: withdrawal → Withdrawn; infructuous → Infructuous; non-prosecution or default → Dismissed for Default; dismiss → Dismissed; reject → Rejected; allow → Allowed; disposed → Disposed Of; closed → Closed; else Other. It says that most read only "Disposed Of", which does not say who won. |
23. **The accountability section** ("How the Government Is Handling Its Cases"). It reuses the dashboard State block's
    definitions.
    - **Action Status** buckets each case once:
      - Not Claimed (`never_owned`);
      - Closed in ASLMS (an open `case_closures` row);
      - Overdue, Due Soon, Due Later and Action Pending With No Due Date: a pending action other than `none`, banded by
        `custody.due_date`. "Due soon" is the dashboard's `REQUEST_DUE_SOON_DAYS`, so the label reads "Due Soon (2
        Days)" from the setting and the portal has one meaning of "due soon";
      - With an Officer, No Action Pending (custody held by a membership);
      - Claimed, Not Sent to an Officer (custody at an office).
    - **Compliance With Court Directions**, by owning department: open `compliance_due` alerts, overdue and due soon,
      through `compliance_flags` and `open_compliance_conditions`.
    - **Who Is Holding Files**: the 10 offices whose custody holds the most cases with an overdue action, the holder's
      own office named. A click sets `holder=<office>` **and** `action=overdue`, as two chips.
    - **Department Scorecard** (State scope only): per department, Claimed (in the selection), Likely, Named Only,
      Contempt Claimed, Hearing in 7 Days (claimed), Overdue Actions, Compliance Overdue, and Median Days to Claim.
      Median Days to Claim runs over the department's primary claims in the last 365 days, from the first
      recommendation of the case to that department to `claimed_at`, shown only when there are at least 3 such
      claims. There is no column that adds bands together.
24. **The filters and their URL names.** One value per dimension, so a click replaces the value and a second click on
    the same value removes it. Values are validated (400 `bad_filter` naming the parameter).

    | Parameter | Values |
    |---|---|
    | `scope` | `state`, `department` |
    | `department` | department code (the scope's department) |
    | `status` | `pending` (default), `disposed`, `all` |
    | `state_only` | `true` (default), `false` |
    | `include_ia` | `false` (default), `true` |
    | `kind` | an active `family` group code |
    | `age` | an `AGE_KEYS` key, or `over_5` |
    | `next` | `today`, `tomorrow`, `days_2_7`, `days_8_30`, `later`, `passed`, `none`, `within_7` (today to today + 7) |
    | `filed` | a year from 1950 to the current year, or `earlier` |
    | `dept` and `band` | a department code, and `claimed`, `likely` or `named` (`band` only with `dept`; none = any band) |
    | `unit` | an office code in the scope's department subtree (department scope only) |
    | `post` | a post code |
    | `subject` | a `subject` group code, `none` (No Category) or `not_grouped` |
    | `counsel` | a normalised printed code (≤ 120 characters) |
    | `outcome` | an outcome key |
    | `action` | `overdue`, `due_soon`, `due_later`, `no_due_date`, `with_officer`, `not_sent`, `closed`, `not_claimed` |
    | `compliance` | `overdue`, `due_soon` |
    | `holder` | an office code |
    | `date_of`, `from`, `to` | `date_of` is `registration`, `next_hearing`, `latest_order` or `disposal`; `from` and `to` are inclusive IST dates, either may be empty. 400 `bad_dates` when from > to. |

    - The server returns a chip for every applied filter, with its label (for example "Kind: Contempt",
      "School Education · Likely", "Registered: 1 Jan 2026 to 13 Nov 2026"). The portal never builds labels from codes.
    - The quick date choices (Last 30 Days, This Year, Next 7 Days (Hearing), Next 30 Days (Hearing), Clear Dates)
      exist only in the portal and fill `date_of`, `from` and `to`.
25. **One grouping-set scan for the single-valued charts.**
    - Each case row computes a boolean per filter: passes the filter, or the filter is unset.
    - One `GROUP BY GROUPING SETS ((kind, age), (next), (age), (filed), (subject), (action), ())` computes, for each
      set, `count(*) FILTER (WHERE <every filter except that set's dimension>)`. The empty set carries the headline
      figures as FILTER aggregates.
    - The multi-valued charts (departments, posts, counsel), the trend, the outcomes, compliance, holders and the
      scorecard are separate statements in the same transaction, each with the same "all but own dimension"
      condition.
    - Everything runs in one read transaction under `SET LOCAL statement_timeout = INSIGHTS_STATEMENT_TIMEOUT_SECONDS`
      (default 30). Past it, the answer is 503 `insights_timeout`, as reports answer `report_timeout`.
    - No `SET` beyond `SET LOCAL`, so PgBouncer's session-feature scan stays clean (row 78).

    *Alternative:* one statement per chart over the full table (rejected: about 10 scans where one does).

### H. The case list and the export

26. **The case list**: 20 a page, through `GET /insights/cases`, with the same filters.
    - **Columns:** Case (court case number linking to the case page by `ref_no`), Kind, Status, With / Owner, Next
      Hearing, Department Named.
    - **Next Hearing:** the server sends `next_hearing_on`, `next_hearing_basis` and status. The kit `HearingDate`
      draws the row 190 badge, outlined when suggested.
    - **The who-has-it text**, built on the server with structured parts so the portal names offices through
      `OfficeName`:
      1. a membership holds the file: "With <name>, <designation> · <office>";
      2. custody at an office: "With <office> · Not Sent to an Officer";
      3. an open closure: "Claimed by <department> · Closed in ASLMS";
      4. an active primary owner with no custody (should not occur): "Claimed by <department>";
      5. open recommendations: "Not Claimed · Recommended to <department with the highest score>", with "and n more"
         in the State scope (decision 20);
      6. otherwise "Not Claimed by Any Department".
    - **Sorts** (an allow-list; 400 `bad_sort` otherwise):
      - `next` (default): hearings today or later soonest first, then passed dates most recent first, then no date;
        disposed cases by disposal date, newest first;
      - `registered`: oldest first;
      - `latest_order`: newest first.

      Ties are broken by registration date, then id.
27. **Export (Excel and PDF of the filtered list).** `GET /insights/export?format=xlsx|pdf&fields=…` with the same
    filters and sort, built in memory and streamed as reports are.
    - **The field registry** (`insights_export.FIELDS`), with the owner's numbering; ✓ marks a default field:
      - Case identity: ✓1 case number, ✓2 CNR, 3 ASLMS reference number, ✓4 kind of case, 5 court's case type code,
        ✓6 subject (court category), 7 filing date, ✓8 registration date, ✓9 pending for (or time taken).
      - Parties and counsel: ✓10 petitioners, ✓11 respondents, ✓12 State case with its bases, ✓13 department named
        in the cause title (department names, or the phrases as read when unmapped), 14 posts named, 15 petitioner's
        advocate, ✓16 counsel code for the government (the printed codes that pass decision 6's `counsel` test),
        17 acts and sections.
      - Court and hearings: ✓18 status, ✓19 next hearing with its urgency in words ("Today", "In 5 Days", "Date
        Passed", "No Date Yet", "Disposed"), 20 next hearing purpose, 21 bench or judges (`coram`), 22 last hearing
        date, ✓23 latest order date, 24 number of orders, 25 disposal date and outcome, 26 original writ (contempt).
      - Ownership and work in ASLMS: ✓27 owning department, ✓28 with officer (name, designation, office), ✓29
        recommended to (when not claimed; decision 20), ✓30 pending action and due date, 31 case stage, 32 open or
        closed in ASLMS, 33 link to the case page (Excel only: `PORTAL_BASE_URL/cases/<ref_no>`).
      - Plus "Applications Pending" whenever IAs are inside their main case.
    - **Excel** (XlsxWriter in `constant_memory` mode):
      - The first sheet, "About This Export", gives the title, the scope, every filter in words (the chips), who
        exported (name, designation, office name) and when (IST), the coverage line and the row count.
      - The second sheet, "Cases", holds the rows in the list's order.
      - A cell is cut at 32,000 characters with "…".
      - At most `INSIGHTS_XLSX_MAX_ROWS` rows (default 100,000); above it the first sheet says "First N of M".
    - **PDF:**
      - A4 landscape through the `report_export` page frame, with the filters printed at the top.
      - At most `INSIGHTS_PDF_MAX_ROWS` rows (default 2,000, the owner's "about 2,000").
      - When the selection is larger, the first 2,000 rows in list order are printed, with the line "First 2,000 of
        N cases. Export to Excel for every case." The dialog warns before.
    - **What is exported:** only cases of the scope that the viewer may open (decision 20). Never notes, drafts, custody
      remarks, documents or document descriptions.
    - **Audit:** `insights.exported` (entity `insights`, no id) with the scope, department, filters, fields, format,
      rows and truncation, written after the file is built.
    - **Errors:** 400 `bad_field` names an unknown field. The export statement timeout is
      `INSIGHTS_EXPORT_TIMEOUT_SECONDS` (default 90); past it, 503 `insights_timeout`.
28. **Opening Insights is not audited.** The JSON reads write nothing, as reports and dashboards. Exports and every
    group, category, case-type and cause-title-name change are audited.

### I. Data health and operations

29. **The data-health block `insights`**:
    - live cases; fact rows built; cases waiting for their readings, and the oldest waiting since;
    - the `READER_VERSION`;
    - the last `insights-refresh` and `insights-rebuild` runs;
    - categories not grouped; unmapped cause-title names (count of phrases and of cases).

    The Insights response also carries `coverage.facts_waiting`. A case without a fact row is counted with empty
    readings, so it is not a State case unless claimed, and the page says "n cases are waiting for their readings".
30. **Jobs in the scheduler's existing process.** No new service and no new database connection slot. Both jobs go
    into `SCHEDULER_JOBS` (repair at start) and the plain-words schedule list (`services/schedules.py`), as
    `rescore-dirty` does. New settings, none secret, are added to the example environment file:
    - `INSIGHTS_STATEMENT_TIMEOUT_SECONDS` (30);
    - `INSIGHTS_EXPORT_TIMEOUT_SECONDS` (90);
    - `INSIGHTS_XLSX_MAX_ROWS` (100,000);
    - `INSIGHTS_PDF_MAX_ROWS` (2,000);
    - `INSIGHTS_REFRESH_BATCH` (5,000).

### J. The portal (round 2, `state-insights-portal`)

31. **Recharts, pinned and wrapped (owner's decision 6).**
    - **Versions:** `recharts` exactly **3.10.1** (the current release, 3 Nov 2026), and its peer `react-is` exactly at
      the installed React version (19.3.x), both in `package.json` without ranges and locked in `package-lock.json`.
    - **Compatibility:** Recharts 3 declares React 16.8 to 19 as peers and is a client library. Every chart file starts
      `"use client"`, and the page loads the chart kit through `next/dynamic` with `ssr: false`. Next 16.4.3 builds it
      with Turbopack as plain ESM. `npm audit --omit=dev` must stay at 0.
    - **Bundle:** Recharts brings Redux Toolkit, Immer and the d3 parts in `victory-vendor`, estimated at about 100 to
      130 KB gzipped. It is loaded **only** by `/insights`. The build output must show every other route's First Load
      JS unchanged within 1 KB, and `/insights` within 200 KB above the shell (Verification).
    - **Kit components** in `components/ui/insightCharts.tsx`: `ChartCard` (title, coverage line, "View as Table",
      empty state), `HBarChart` (clickable horizontal bars, selected bar marked by colour **and** a tick in its label),
      `StackedBarChart` (kind × age), `GroupedBarChart` (the three bands side by side, never stacked) and `TrendChart`
      (two lines with points).
    - **Colours:** from the row 229 tokens, read once at run time from the CSS custom properties by
      `useChartTokens()`. There are no colour literals in component code, so the colour guards hold. New chart tokens
      `--chart-1` … `--chart-8` go in `globals.css` from the navy and cream palette, with orange for the selected bar.
      The next-hearing chart uses the row 190 band tokens.
    - **Accessibility:**
      - every chart has `role="img"` with an `aria-label` summary, and Recharts' `accessibilityLayer`;
      - "View as Table" shows the same numbers in a `DataTable` whose rows carry the filter buttons, so every click
        has a keyboard path;
      - colour is never the only signal.
    - **Reduced motion:** `isAnimationActive={!reduced}` from `usePrefersReducedMotion`.

    *Alternatives:* hand-drawn SVG as on System Health (rejected by the owner's decision 6); a heavier library
    (ECharts, rejected: about 300 KB, canvas, harder to make accessible).
32. **The page `/insights`.**
    - **Navigation:** the first entry of the Oversight group in `frontend/src/lib/routes.ts` (Insights, Reports, Audit
      Log), shown with `insights.state` or `insights.department`.
    - **Filters:** every filter is held in the URL (`router.replace`, so back and forward work and a link can be
      shared). Another viewer opening the link sees their own scope's numbers.
    - **Requests:** one overview request per change, debounced 300 ms, with the earlier request cancelled
      (`AbortController`). The case list is its own request, so paging does not recount the charts.
    - **Layout, top to bottom:**
      1. scope switch, when there is more than one choice;
      2. status switch;
      3. the two toggles;
      4. the date bar (Date Of, From, To, quick choices, using `DateRangeField`);
      5. chips with Clear All (`FilterChips`);
      6. headline figures;
      7. charts;
      8. the accountability section;
      9. the case list with Export Excel and Export PDF.
    - **Widths:** one column at 375 and 768 px, two at 1024 px, two or three at 1280 px. Tables stack as cards on
      phones (kit `DataTable`).
    - **Empty selection:** "No case matches this selection".
    - **Wording:** Title Case through the label helper; the wording guards hold (no "allot", no internal file-system
      words, no agency names).
    - **Errors:** a 503 `insights_timeout` shows "This selection took too long. Narrow it and try again." with Try
      Again.
33. **The export dialog** lists the 33 fields in the owner's four groups with the defaults ticked, plus Applications
    Pending. Link to the Case Page appears only for Excel. The dialog shows the row count and the PDF limit before the
    download. The choice is kept in the browser for next time (`localStorage`, no server state).
34. **The Insights Groups screen** (`/admin/insights-groups`, Administration, shown only to the Super Administrator)
    follows the Settings template.
    - Two tabs: Subject Groups and Kinds of Case.
    - Groups can be added, renamed, reordered and deactivated (reserved ones marked).
    - The category and case-type tables show code, court's label, cases, pending and a group select, with Search and
      a "Not Grouped" filter.
    - One batch Save with a toast.
35. **Names in Cause Titles** becomes a fourth list on Department Mapping (beside counsel codes, keywords and name
    patterns, watchlist) with the same toolbar, search and sort (row 175). Its "Unmapped Names" panel lists phrases
    found in cause titles that no department matches, with cases and an example case number. Map pre-fills the
    phrase.

### K. "Named in the cause title" as a recommendation signal (owner's decision 8; round 3, `cause-title-signal`)

36. **A new signal kind `named_in_title`.** For each case, the departments in `named_title_department_ids` (decision 9:
    the cause title or respondent party names, explicit or automatic match) each get one signal, carrying the phrase,
    its source (`cause_title` with the order date, or `party`) and a reason sentence. Two examples:
    - "Department named in the cause title of the order of 12 Oct 2026: FINANCE"
    - "Department named among the respondents: REVENUE AND DISASTER MANAGEMENT"

    The engine reads it from `insight_case_facts`. It does not read text itself. Counsel-code attribution is not part
    of this signal; counsel codes already have their own signals.
37. **Default weight 0.600, kept inside the possible band** (as `counsel_code_partial`, partial-code-match decisions 10
    and 12). The service requires `threshold_possible ≤ weight_named_in_title < threshold_strong`.
    - **Alone**, a cause-title naming is a possible match: shown in Case Claim, counted in the digest, no alert.
    - **With a keyword** (0.4) it gives 0.760. **With a partial code** (0.6) it gives 0.840, still possible. **With a
      name pattern** (0.8) or an exact code it reaches the strong band, because independent signals agree.
    - The cause title is evidence the department is a party, not that it is the department that must defend.
      Respondents often list several departments.
38. **Engine version 3 and a new settings version.** A new column `scoring_settings.weight_named_in_title numeric(4,3)`
    (NULL only on older versions; CHECKs as the partial weight's) comes from the round's own migration. That
    migration inserts the next settings version with 0.600, writes one `scoring_settings.update` audit row and event,
    and sets `ENGINE_VERSION = "3"`. The 15-minute `rescore-dirty` job then rescores every case. The Scoring tab gains
    the weight with the band rule.
39. **Never assigns.** The engine still writes only `case_office_scores` and recommendations. Every guard stays: no
    engine recommendation on a case that has ever had a primary owner, none for a department that dismissed or
    claimed it, and a primary claim closes the others' rows as `claimed_elsewhere`. Visibility does not widen beyond
    the existing `recommended` basis.
40. **Why a separate row.** It changes scoring for every case, adds a migration and a settings version, and puts the
    owner's band rule to a new check. The owner will want to see the possible-match count it would add before it goes
    live. The round's Verification prints that number from a dry run (`aslms rescore --all --dry-run` counting new
    `medium` rows by signal kind) before the rescore is applied.

## Data
**Migration 0039** `0039_state_insights.py` (hand-written). It revises the head at build time, and takes the next free
number after that head when the expected predecessors have not landed in the order 257, 189, 250. Applied migrations
are never edited. `docs/schema/schema.md` takes the paragraphs below (section "Phase 2 and 3 tables") before the
migration is written. Round 3 adds its own migration for `scoring_settings` (decision 38).

**New tables** (schema.md):

> **`insight_groups`** (master; design `state-insights`, migration 0039). The subject groups and the kinds of case
> used by Insights.
>
> **Columns:**
> - id (uuid v7 PK);
> - kind (varchar 10 NOT NULL: `subject` / `family`);
> - code (varchar 40 NOT NULL);
> - label (varchar 120 NOT NULL);
> - description (text NULL);
> - sort_order (integer NOT NULL default 0);
> - is_reserved (boolean NOT NULL default false);
> - is_active (boolean NOT NULL default true);
> - deactivated_at (timestamptz NULL);
> - created_at, updated_at;
> - created_by, updated_by (→ users SET NULL).
>
> **Checks and keys:**
> - `ck_insight_groups_kind`: `kind IN ('subject', 'family')`;
> - `ck_insight_groups_code`: `code ~ '^[a-z][a-z0-9_]{1,39}$'`;
> - `ck_insight_groups_active`: `is_active = (deactivated_at IS NULL)`;
> - `ck_insight_groups_reserved`: `NOT is_reserved OR is_active`;
> - unique `uq_insight_groups_kind_code` (kind, code);
> - unique `uq_insight_groups_kind_label` (kind, lower(label));
> - unique `uq_insight_groups_id_kind` (id, kind), the target of the composite FKs below.
>
> **Triggers:** the BEFORE UPDATE trigger `insight_groups_fixed` (function `aslms_insight_group_fixed`) refuses a change
> of `kind`, `code` or `is_reserved`; and `set_updated_at`.
>
> **Reserved rows:** `family`/`contempt`, `family`/`ia`, `family`/`other` and `subject`/`contempt`.
>
> **Lifecycle:** never deleted. Written only by `services/insights_groups.py`, every change audited.

> **`insight_subject_categories`** (master; design `state-insights`, migration 0039). The court's subject categories
> and their group.
>
> **Columns:**
> - id (uuid v7 PK);
> - court_id (→ courts RESTRICT NOT NULL);
> - category_code (integer NOT NULL; the five-digit code the court prints before the label);
> - label (varchar 300 NOT NULL; the court's label as last seen, without the code and the trailing number);
> - group_id (uuid NULL); group_kind (varchar 10 NOT NULL default `subject`); together → insight_groups (id, kind)
>   RESTRICT; NULL = Not Grouped;
> - first_seen_at, last_seen_at (timestamptz NOT NULL default now());
> - created_at, updated_at;
> - created_by, updated_by (→ users SET NULL).
>
> **Checks and keys:**
> - `ck_insight_subject_categories_code`: `category_code BETWEEN 1 AND 99999`;
> - `ck_insight_subject_categories_kind`: `group_kind = 'subject'`;
> - unique (court_id, category_code);
> - index `ix_insight_subject_categories_group_id`.
>
> **Lifecycle:** the migration and the seed insert the 235 categories of the draft
> (`docs/design/state-insights-subject-groups.md`) for the Gauhati High Court. The fact job inserts a category it
> meets for the first time with no group. The label and `last_seen_at` follow the court. Never deleted.

> **`insight_case_type_groups`** (master; design `state-insights`, migration 0039). The kind of case of each case
> type.
>
> **Columns:**
> - id (uuid v7 PK);
> - case_type_id (→ case_types RESTRICT NOT NULL, UNIQUE);
> - group_id (uuid NOT NULL); group_kind (varchar 10 NOT NULL default `family`); together → insight_groups (id, kind)
>   RESTRICT;
> - created_at, updated_at;
> - created_by, updated_by (→ users SET NULL).
>
> **Checks and keys:** CHECK `ck_insight_case_type_groups_kind`: `group_kind = 'family'`; index on group_id.
>
> **Lifecycle:** a case type without a row is of kind `other`. The migration and the seed map the 57 case types of the
> draft (decision 16) by court and `case_type_code`. The court master sync never writes this table. Never deleted.

> **`insight_case_facts`** (derived; design `state-insights`, migration 0039). The per-case readings Insights counts,
> rebuilt by `services/insights_facts.py` (jobs `insights-refresh` and `insights-rebuild`, `aslms insights refresh`);
> re-buildable at any time.
>
> **Columns:**
> - case_id (uuid PK → cases RESTRICT);
> - category_code (integer NULL; parsed from `cases.category`);
> - subject_category_code (integer NULL; the original writ's category for a linked contempt case, else
>   category_code);
> - main_case_id (→ cases RESTRICT NULL; an IA's resolved `main_matter`);
> - state_basis (varchar(10)[] NOT NULL default `{}`);
> - title_phrases (varchar(200)[] NOT NULL default `{}`; the department phrases read, normalised);
> - named_title_department_ids (uuid[] NOT NULL default `{}`) and named_counsel_department_ids (uuid[] NOT NULL
>   default `{}`): Department-tier office ids, without FK (deviation, decision 13);
> - posts (varchar(40)[] NOT NULL default `{}`);
> - counsel_codes (varchar(120)[] NOT NULL default `{}`; every normalised printed code of current lists and current
>   advocates);
> - government_codes (varchar(120)[] NOT NULL default `{}`; those passing decision 6's `counsel` test);
> - original_writ_text (varchar 60 NULL); original_writ_case_id (→ cases RESTRICT NULL);
> - latest_order_on (date NULL); orders_count (integer NOT NULL default 0);
> - title_order_id (→ orders RESTRICT NULL; the order whose cause title was read);
> - reader_version (varchar 20 NOT NULL);
> - built_at (timestamptz NOT NULL);
> - created_at, updated_at.
>
> **Checks:**
> - `ck_insight_case_facts_basis`: `state_basis <@ ARRAY['party','officer','counsel','title','writ']::varchar[]`
>   (`claimed` is evaluated live, never stored);
> - `ck_insight_case_facts_writ`: `original_writ_case_id IS NULL OR original_writ_text IS NOT NULL`;
> - `ck_insight_case_facts_orders`: `orders_count >= 0`.
>
> **Indexes:** `ix_insight_case_facts_built_at` (built_at); partial `ix_insight_case_facts_main_case_id` (main_case_id)
> WHERE main_case_id IS NOT NULL; partial `ix_insight_case_facts_original_writ` (original_writ_case_id) WHERE NOT NULL;
> partial `ix_insight_case_facts_title_order_id`.
>
> **Lifecycle:** one row per case, updated in place, never deleted; a merged case keeps its row and readers join live
> cases only. Post codes are checked by the service (the list is code, decision 10).

> **`office_title_names`** (master; design `state-insights`, migration 0039). Printed department names in cause titles
> and respondent names, mapped to an office.
>
> **Columns:**
> - id (uuid v7 PK);
> - office_id (→ offices RESTRICT NOT NULL);
> - phrase (varchar 200 NOT NULL UNIQUE; the normalised phrase of decision 8);
> - is_active (boolean NOT NULL default true);
> - deactivated_at (timestamptz NULL);
> - created_at, updated_at;
> - created_by, updated_by (→ users SET NULL).
>
> **Checks and keys:** `ck_office_title_names_phrase`: `phrase ~ '^[A-Z0-9][A-Z0-9 ()&.,/-]{2,199}$'`;
> `ck_office_title_names_active`: `is_active = (deactivated_at IS NULL)`; index `ix_office_title_names_office_id`.
>
> **Lifecycle:** managed with `admin.keywords` in the office subtree (super admin everywhere); every create, update,
> deactivate and reactivate is audited (`title_name.*`) with a `config_changed` event. A phrase equal to a
> Department-tier office's name core matches it without a row (decision 9). Never deleted.

**Grants** (all five tables): ALL to `aslms_owner`; SELECT to `aslms_readonly`; SELECT, INSERT and UPDATE to `aslms_app`
(no DELETE). Each table gets a `COMMENT ON TABLE … 'class=…'` and the `set_updated_at` trigger.

**Reference data in the migration.** It is hard-coded with no application import, as 0016, 0018 and 0034 did, with
`ON CONFLICT DO NOTHING`:
- the 20 kinds of case and 15 subject groups;
- the 235 category rows for the court with `ref_code = 'GHC'`;
- the case-type mappings for that court's `case_types` rows by `case_type_code`.

The seed carries the same lists from `services/insights_groups.py` constants, and a unit test holds the two equal. No
`audit_log` row is written (the 0016 precedent for reference data).

**Downgrade.** It refuses (a restore is needed, runbook section 6) while any `office_title_names` row exists or any
`insight_groups`, `insight_subject_categories` or `insight_case_type_groups` row has a non-null `updated_by` or
`created_by`: people's edits would be lost. Otherwise it drops the five tables, their trigger and function. The
function rows stay (the seed owns them).

**schema.md, other paragraphs:**
- The Conventions list of derived tables gains `insight_case_facts`.
- The "No deletion" line records the array-of-ids deviation (decision 13).
- `audit_log` actions gain:
  - `insights.exported`;
  - `insights.group_created`, `insights.group_updated`;
  - `insights.category_grouped`, `insights.case_type_grouped`;
  - `title_name.create`, `title_name.update`, `title_name.deactivate`, `title_name.reactivate`.

  All of them go into `domain/audit_actions.py` and the portal's `AUDIT_ACTIONS` names.
- `job_runs.job` gains `insights-refresh` and `insights-rebuild`.
- `ref_permission` gains `insights.state`, `insights.department` and `admin.insights_groups` (seed).

**DB_STANDARD.md.** One sentence in the keys section records that derived arrays of office ids carry no FK, with the
reason (decision 13), so the deviation is written in the standard, not only here.

## Services
- **`services/insights_rules.py`** (pure, no database):
  - `READER_VERSION`;
  - `STATE_PARTY_RE`, `SERVICE_TAG_RE`, `GOVERNMENT_CODE_FIRST_PARTS` (from `matching.GENERIC_PARTS`), and
    `is_government_code(code, mapped, generic)`;
  - `respondent_side(title_text)`, `department_phrases(text) -> list[str]`, `normalise_phrase`, `office_name_core`;
  - `POSTS` and `posts(text) -> list[str]`;
  - `writ_reference(text) -> str | None`;
  - `parse_category(text) -> (code, label) | None`;
  - `outcome_key(disposal_type)` with `OUTCOMES`;
  - `hearing_band(next_on, status, today)`, the Python twin of `hearingBand` with the 8-to-30 split;
  - `age_key(start, end)` over `reporting_common.AGE_BANDS`.
- **`services/insights_facts.py`:**
  - `dirty_case_ids(session, limit)`;
  - `build(session, case_ids) -> counters`: set-based SQL for the party, officer and counsel bases, the codes, the
    orders, the main matter and the category; the cause-title spans of `order_sections`, read in Python batches of
    500 and passed through `insights_rules`; then the writ resolution and the `writ` basis as a second pass; and
    `INSERT … ON CONFLICT (case_id) DO UPDATE`;
  - `rederive_departments(session)`, one statement from phrases and codes to department ids;
  - `discover_categories(session)`;
  - `refresh(session, *, all_=False, dry_run=False)` and `status(session)`.

  It writes no audit rows (derived data, as the engine) and one `job_runs` row per run, with the counters `checked`,
  `built`, `new_categories`, `rederived`, `unmapped_phrases` and `seconds`.
- **`services/insights_scope.py`:**
  - `available(session, user) -> {state, departments, default}`;
  - `resolve(session, user, scope, department) -> Scope(kind, department, member, condition)`, raising `Forbidden`
    with `state_scope_not_state_wide`, `no_insights_function` or `department_not_yours`;
  - `band_conditions(department)` (claimed, likely and named as SQL over `Case`).

  It uses `visibility.member_bases` / `visible_case_condition` and `access.holders_in`.
- **`services/insights_filters.py`:**
  - the `InsightFilters` dataclass;
  - `parse(**params)`, raising `InsightFilterError(code, param)`;
  - `conditions(session, f, scope) -> dict[dimension, condition]`, `all_but(dim)`;
  - `chips(session, f) -> list[{param, value, label}]`.

  It reuses `case_filters` date validation and `visibility.never_owned`, and the action and compliance predicates
  shared with `dashboard.py`. `compliance_flags`, `open_compliance_conditions` and the custody `HELD` alias are
  imported, never copied.
- **`services/insights.py`:**
  - `overview(session, user, f, scope, *, now, cfg)`: the grouping-set scan, the multi-valued charts, trend, outcomes
    and accountability (decisions 21 to 25), coverage and chips;
  - `case_page(session, user, f, scope, *, page, sort)`, with `who_has_it(...)` (decision 26).

  Everything runs under `with_timeout`; it writes nothing.
- **`services/insights_export.py`:**
  - `FIELDS` (key, number, label, group, default, excel_only) and `parse_fields`;
  - `rows(session, user, f, scope, fields, limit)`, a server-side cursor (`yield_per` 2,000);
  - `to_xlsx` (constant memory) and `to_pdf` (reusing the `report_export` page frame, CSS and footer);
  - `audit_export(session, actor, …)` writing `insights.exported`.
- **`services/insights_groups.py`:**
  - `SEED_GROUPS`, `SEED_CATEGORIES`, `SEED_CASE_TYPES` and `seed(session, report)`;
  - `list_groups`, `create_group`, `update_group` (reserved rules), `set_categories(changes)` and
    `set_case_types(changes)`, each change audited with before and after;
  - `require_groups_admin` (`admin.insights_groups`).
- **`services/matching_rules.py`** gains the entity `title_name`: `create_title_name`, `update_title_name`,
  `set_title_name_active`, `list_title_names` (list-search `q` and allow-listed `sort`) and `unmapped_title_names`.
  The audit is the generic `title_name.<action>` with the `config_changed` event. A save marks the Insights
  attribution dirty and dispatches `insights-refresh`.
- **`services/access_seed.py`:** the three functions with names, descriptions, group placement and defaults;
  `access.RESERVED_FUNCTIONS` gains `admin.insights_groups`.
- **`services/data_health.py`:** the `insights` block (decision 29). **`services/schedules.py`:** the two job rows.
  **`services/job_repair.py`:** `SCHEDULER_JOBS` gains both.
- **CLI `aslms insights`:** `refresh [--all] [--dry-run]`, `status`, and `groups export|check`. `check` lists the
  categories and case types not grouped. Every command prints counts only, never case text.

## API
All under the API's usual authentication. 400 bodies name the parameter. Visibility is applied in SQL on every read
(decision 20).

| Method and path | Function | Request | Response |
|---|---|---|---|
| `GET /insights/scopes` | `insights.state` or `insights.department` | — | `{state: bool, departments: [{code, name}], default: {scope, department}}` |
| `GET /insights` | the same, then the scope rule (decisions 18 and 19) | the filters of decision 24 | `{scope: {kind, department}, generated_at, coverage: {court, listed_since, facts_waiting, facts_built_at}, chips: [{param, value, label}], headline: {cases, state_cases, contempt, over_5_years, hearing_7_days, not_claimed, applications_inside, applications_main_not_held}, kind_by_age: {bands: [{key, label}], rows: [{key, label, total, by_age}]}, next_hearing, age, filed, subjects, posts, counsel, outcomes: [{key, label, count}], departments: [{code, name, claimed, likely, named}] or units: [{code, name, claimed}] with department_bands, unmapped_named: int, trend: [{month, registered, disposed}], accountability: {action, compliance: [{code, name, overdue, due_soon}], holders: [{code, name, overdue}], scorecard: [...] or null}}`. 403 `state_scope_not_state_wide` / `department_not_yours`; 400 `bad_filter` / `bad_dates`; 503 `insights_timeout`. |
| `GET /insights/cases` | as `GET /insights` | the filters plus `page` (from 1) and `sort` (`next`, `registered`, `latest_order`) | `{items: [{case: {id, ref_no, case_no, cnr}, kind: {code, label}, status, who: {kind, text, officer_name, designation, office_code, department_code, recommended_to, more}, next_hearing: {on, basis}, disposal_date, departments_named: [{code, name}], phrases_unmapped, applications_pending, state_case, state_basis}], total, page, page_size: 20, sort}`; 400 `bad_sort` |
| `GET /insights/fields` | as `GET /insights` | — | the export field registry: `[{key, number, label, group, default, excel_only}]` |
| `GET /insights/export` | as `GET /insights` | the filters plus `sort`, `format` (`xlsx` / `pdf`) and `fields` (comma list; default the ✓ set) | the file (`Content-Disposition` attachment; the name `ASLMS_Insights_<scope>_<YYYY-MM-DD_HHMM>.xlsx`); audited `insights.exported`; 400 `bad_field`; 503 `insights_timeout` |
| `GET /admin/insights/groups?kind=` | `admin.insights_groups` (reserved) | — | groups with categories or case types and case counts |
| `POST /admin/insights/groups` | `admin.insights_groups` | `{kind, code, label, sort_order}` | the group; 409 `code_taken` / `label_taken` |
| `PATCH /admin/insights/groups/{id}` | `admin.insights_groups` | `{label?, sort_order?, is_active?}` | the group; 409 `reserved_group` |
| `GET /admin/insights/categories` | `admin.insights_groups` | `q`, `group` (a code or `not_grouped`), `sort` | `[{code, label, group, cases, pending}]` |
| `PUT /admin/insights/categories` | `admin.insights_groups` | `{changes: [{code, group}]}` (`group` null = Not Grouped) | the changed rows; one `insights.category_grouped` audit row per changed line |
| `GET /admin/insights/case-types` | `admin.insights_groups` | `q`, `group`, `sort` | `[{id, code, name, group, cases, pending}]` |
| `PUT /admin/insights/case-types` | `admin.insights_groups` | `{changes: [{case_type_id, group}]}` | the changed rows; one `insights.case_type_grouped` per line |
| `GET /admin/title-names` | `admin.keywords` (office subtree; super admin everywhere) | `office`, `q`, `sort`, `active` | `{items: [{id, phrase, office_code, office_name, department_code, is_active, cases}], total}` |
| `POST /admin/title-names` | `admin.keywords` in the target office's subtree | `{office_code, phrase}` (normalised by the server) | the row, 201; 409 `phrase_taken`; 400 `bad_phrase` |
| `PATCH /admin/title-names/{id}` | `admin.keywords` (both offices in scope) | `{office_code}` | the row |
| `POST /admin/title-names/{id}/deactivate`, `/reactivate` | `admin.keywords` | — | the row |
| `GET /admin/title-names/unmapped` | `admin.keywords` | `q`, `page` | `{items: [{phrase, cases, example_case_no}], total}`; phrases from cases the caller may see only |

`tools/export_enum_codes.py` carries the new function codes, audit actions and filter values to the portal, and
`frontend/openapi.json` is regenerated.

## Jobs
- **`insights-refresh`:** Celery beat, `crontab(minute="4-59/10")`, task `aslms.insights_refresh`. It is also
  dispatched after a counsel-code or cause-title-name save and after an office change, one run at a time (a Redis lock,
  as `rescore-dirty`). It handles at most `INSIGHTS_REFRESH_BATCH` dirty cases, then the department re-derivation when
  a mapping changed. It writes `job_runs` `insights-refresh` with its counters. No NAPIX, no SourceTrace, no Ollama.
- **`insights-rebuild`:** `crontab(hour=4, minute=45)` IST, task `aslms.insights_rebuild`. It rebuilds every fact row
  in batches of 5,000, each batch its own transaction, then discovers categories and writes `job_runs`
  `insights-rebuild`.
- Both run in the existing `scheduler` service, in `SCHEDULER_JOBS` for the start-up repair, and on the plain-words
  schedule list.

## Tests
**Unit** (`backend/tests/unit/test_insights_rules.py`, `test_insights_filters.py`, `test_insights_export_fields.py`,
`test_insights_seed_lists.py`):
- `test_state_party_pattern_forms`: "THE STATE OF ASSAM AND 3 ORS", "GOVT. OF ASSAM" and "GOVERNMENT OF ASSAM" match;
  "ASSAMESE" and "STATE BANK OF INDIA" do not.
- `test_service_tag_whole_word`: ", IAS" and "ACS" match; "BASIS" and "IASI" do not.
- `test_government_code_forms`: `GA, ASSAM`, `PP, ASSAM` and `SR. GA ADV.` pass; `SC, EDU` passes only when mapped;
  `GA, NAGALAND` fails.
- `test_department_phrases_real_titles`: the 15 dev examples (Context) give the expected phrases, including
  `PERSONNEL (B)` → `PERSONNEL` and "DEPTT OF REVENUE AND DISASTER MANAGEMENT".
- `test_office_name_core`: core forms of the State Portal department names.
- `test_posts_each_and_exclusions`: Director against Director General of Police and Managing Director; Other
  Secretary.
- `test_writ_reference_forms`: `W.P.(C) No. 4326 of 2025`, `WP(C) 123/2020`, `WA 45/2019`; CRP refused; a year in the
  future refused.
- `test_parse_category`: a coded value gives (10245, label); `( 20240 )` gives None.
- `test_outcome_buckets_every_dev_value`: the 14 dev `disposal_type` values.
- `test_hearing_band_twin_matches_portal_fixture`: a shared JSON fixture also run by the portal's `hearingDate` test.
- `test_age_keys_reuse_njdg`.
- `test_filters_parse_and_errors`: every parameter; `band` without `dept`; `unit` outside the department; from > to.
- `test_chips_labels`: every filter's chip label.
- `test_export_fields_registry_owner_list`: 33 numbered fields, the ✓ defaults exact, Link Excel only.
- `test_seed_lists_equal_migration_lists`: the groups, categories and case types in the seed equal the lists
  hard-coded in 0039.
- `test_no_internal_records_in_insights_modules`: a static scan; no `case_notes`, `case_note_drafts`,
  `custody_history.remark`, `documents.description` or `document_text` outside the cause-title span reader.
- `test_permissions_seed_defaults`: State Oversight holds `insights.state`; Department Head and Department
  Administrator hold `insights.department`; other types hold neither; `admin.insights_groups` is reserved.

**Database** (`backend/tests/db/`, the scripted gateway never called):
- `test_insights_facts.py`:
  - `test_build_one_row_per_case_never_deletes`;
  - `test_state_bases_party_officer_counsel_title_writ`;
  - `test_claimed_basis_live_not_stored`;
  - `test_title_source_from_order_sections_else_parties`;
  - `test_named_departments_explicit_and_automatic`;
  - `test_deactivated_title_name_rederived`;
  - `test_named_counsel_exact_active_non_generic_only`;
  - `test_department_ids_exist_in_offices` (the deviation's guard);
  - `test_ia_main_case_resolved_and_unresolved`;
  - `test_original_writ_resolved_only_when_held_never_in_case_links`;
  - `test_contempt_subject_from_writ`;
  - `test_new_category_inserted_not_grouped`;
  - `test_dirty_rules_each_trigger`;
  - `test_reader_version_change_marks_all_dirty`;
  - `test_rebuild_idempotent`;
  - `test_job_runs_counters`.
- `test_insights.py`:
  - `test_cross_filter_each_chart_ignores_own_dimension` (a fixture with hand-counted numbers for every chart);
  - `test_headline_counts_all_filters`;
  - `test_state_only_default_and_switch`;
  - `test_ia_out_by_default_inside_main_and_switch`;
  - `test_department_bands_disjoint_never_summed`;
  - `test_department_scope_bands_and_member_visibility` (another department's cases and the plain pool are never
    counted);
  - `test_department_switch_several_memberships`;
  - `test_state_scope_needs_state_wide_membership`;
  - `test_state_wide_may_open_any_department_view`;
  - `test_trend_ignores_status_and_dates`;
  - `test_outcomes_ignore_status`;
  - `test_action_buckets_each_case_once`;
  - `test_compliance_by_department_reuses_dashboard`;
  - `test_holders_click_sets_two_filters`;
  - `test_scorecard_median_days_three_claims_minimum`;
  - `test_case_page_sort_orders`;
  - `test_who_has_it_each_kind`;
  - `test_recommended_to_hidden_from_other_departments`;
  - `test_applications_pending_count`;
  - `test_facts_waiting_counted_empty`;
  - `test_timeout_503`.
- `test_insights_export.py`:
  - `test_xlsx_about_sheet_filters_who_when`;
  - `test_xlsx_fields_in_order_and_link_column`;
  - `test_xlsx_cap_first_n_of_m`;
  - `test_pdf_landscape_capped_with_excel_pointer`;
  - `test_export_only_scope_and_visible_cases`;
  - `test_export_audited_once_after_build`;
  - `test_bad_field_400`;
  - `test_never_exports_internal_records`.
- `test_insights_groups.py`:
  - `test_reserved_function_super_admin_only`;
  - `test_group_create_update_audited`;
  - `test_reserved_group_cannot_deactivate_or_recode` (service and trigger);
  - `test_category_regroup_one_audit_per_change`;
  - `test_composite_fk_refuses_family_group_for_category`;
  - `test_change_takes_effect_without_rebuild`.
- `test_title_names.py`:
  - `test_crud_audited_with_event`;
  - `test_scope_admin_keywords_subtree`;
  - `test_phrase_normalised_and_unique`;
  - `test_unmapped_list_counts_visible_cases_only`;
  - `test_save_dispatches_refresh`.
- `test_insights_api.py`: every endpoint's function (403 without), status codes and shapes, OpenAPI names.
- `test_migration_0039_up_down_up`: the downgrade refuses after a person's edit.
- `test_schema_metadata`, still in step.
- The access matrix suites: the three functions in the type matrix, overrides and the delegation rule.

**Frontend (round 2)** (vitest, plus uicheck states):
- `insights.test.tsx`:
  - the URL to filters and back;
  - a chip's removal;
  - Clear All;
  - a click sets and a second click clears;
  - the headline clicks;
  - the scope switch shown only with choices;
  - a debounced request with the earlier one cancelled;
  - the empty state;
  - the timeout message.
- `insightCharts.test.tsx`:
  - View as Table carries the same numbers and filter buttons;
  - reduced motion gives `isAnimationActive=false`;
  - colours come from tokens (guard);
  - the grouped bars are never stacked;
  - the selected bar has its tick label.
- `exportDialog.test.tsx`: the default fields; Link only for Excel; the PDF warning above 2,000.
- `insightsGroups.test.tsx`: batch Save; reserved rows locked.
- `titleNames.test.tsx`: the list and the unmapped panel.
- `routes.test.ts`: the Insights entry by function.
- The wording, label and colour guard suites extended.
- The layout signature updated.
- uicheck states:
  - `/insights` (State, default);
  - `/insights?kind=contempt&next=within_7`;
  - the department scope;
  - empty;
  - loading;
  - the export dialog;
  - View as Table;
  - `/admin/insights-groups`;
  - the Names in Cause Titles list.

## Verification
1. Migration 0039: upgrade, downgrade and upgrade on a scratch database. On dev, the integrator applies it with the
   `migrate` step, then `init` (seed: the three functions and their type defaults), then `docker compose build`.
   Every Compose `up` carries the court-data switch.
2. `aslms insights refresh --all` on dev. It prints the counts and seconds. The full build should finish in under 2
   minutes; with row 250's spans the cause-title reading reads spans, not whole texts.
3. `aslms insights status`:
   - 83,941 or more live cases, all with fact rows, `waiting` 0;
   - the State bases counted: `party` 52,729 or more, `counsel` 42,179 or more (14 Nov figures);
   - the contempt cases with a State basis well above the 11 of party and counsel alone, from `officer` and `title`;
   - categories not grouped 0 (the draft covers all 235).
4. `GET /insights` as the super admin with the defaults (pending, State cases only, IAs inside): `headline.cases` ≥
   18,830 (the party and counsel figure of 14 Nov; higher with the other bases), `applications_inside` = the pending
   IAs held (5,470 on 14 Nov, less those whose main is not held), the contempt figure, and `not_claimed` =
   `cases` − claimed. Cross-check each figure with a read-only SQL query.
5. Timing: 20 calls of `GET /insights` with varied filters. Record p50 and p95 against the targets (decision 11),
   along with `GET /insights/cases` and an Excel export of every pending case (time and file size). Record the numbers
   in the design note after deploy.
6. A department view as the SEC-EDU head: only claimed, likely and named cases of SEC-EDU, matching an SQL count of
   the three bands ANDed with that membership's visibility; 403 on another department. A State Oversight user: 200 for
   State scope. A Department Officer: 403.
7. Exports: an Excel with the default fields (the first sheet names the filters, the exporter and the time) and a PDF
   of a selection above 2,000 cases (2,000 rows and the Excel pointer); two `insights.exported` audit rows visible on
   Audit Log.
8. Round 2: `next build` route sizes before and after (other routes unchanged within 1 KB; `/insights` within 200
   KB); `npm audit --omit=dev` 0; uicheck on its private network at 375, 768, 1024 and 1280 px with 0 findings
   (runbook section 16); the owner's browser check of the page and the groups screen.
9. Round 3: the dry-run count of new possible matches by signal kind is shown to the owner before
   `aslms rescore --all`; afterwards no `case_ownership` row was written by the engine.
10. Documents updated in the same change:
    - `docs/schema/schema.md` and `docs/DB_STANDARD.md` (Data);
    - `docs/operations.md` (jobs, CLI, settings, the stop lists unchanged);
    - `docs/ASLMS_Process_Workflows.md` (how State cases, bands and readings are worked out, in plain words);
    - the Software Documentation (`docs/software-documentation/build.js`, a section in the reports and dashboards
      chapter) and the user guide for the page (round 2);
    - `.env.example` (the five settings);
    - the decisions log by the scribe.

## Open questions
None that block this item. The owner gave the eight decisions and the export fields on 13 Nov 2026 ("go with your
defaults"). Everything else is decided above, and row 250's contract (decision 2) is a design dependency, not an owner
question.

**Owner checks at approval** (decided here and reversible; say if any should change):
1. **The split into three rows** (decision 1): 258 backend, a new `state-insights-portal` row for the page, and a new
   `cause-title-signal` row for the recommendation signal. Recommended: approve all three now, built in that order
   after row 250.
2. **The subject groups draft** (decision 15, `docs/design/state-insights-subject-groups.md`): 15 groups, with three
   service groups kept apart. Change any line now, or later on the Insights Groups screen.
3. **What makes a State case** (decision 6). Besides State of Assam parties and government counsel codes, three bases
   are added:
   - a respondent named with a service tag (IAS, ACS and the like);
   - the Government of Assam or a department named in the cause title;
   - an original writ that is a State case.

   Without them, contempt shows 11 of 1,582 pending cases. Unmapped `SC, …` codes do not count.
4. **Interlocutory applications** (decision 5): out of every figure by default, shown as "Applications Pending: n" on
   the main case, with a switch to count them as cases. Other subordinate types (MC, Crl.L.P., CO) stay cases of
   their own.
5. **Age bands** follow the Pending Cases report (Up to 1 Year, 1 to 3, 3 to 5, 5 to 10 … Years) rather than the mock's
   1 / 2 / 5 years, so both pages agree. "Over 5 Years" is unchanged.
6. **"Due Soon"** in Action Status uses the dashboard's 2-day setting rather than the mock's 7 days, so the portal has
   one meaning.
7. **Export limits:** PDF 2,000 rows with a pointer to Excel (the owner's figure); Excel up to 100,000 rows.
8. **Decision 8's weight** (round 3): 0.600, a possible match alone and strong only with another signal; the dry-run
   count is shown before it goes live.
9. **Editing the groupings is the Super Administrator's alone** (a reserved function). Cause-title names are mapped
   by department administrators with Keywords and Name Patterns, as counsel codes are.
