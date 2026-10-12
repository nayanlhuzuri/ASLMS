# ASLMS v2 — database schema (as built; DB_STANDARD v1.2, migration `0001_core`, 29 Sep 2026)

Source: `docs/Legal_Case_Monitoring_Portal_Plan.docx` section 7 (data groups), the decisions log and
`docs/DB_STANDARD.md` (the binding standard; where the two disagree, the standard wins and this file is updated in
the same commit). The database starts empty; there is no migration of earlier data. Implemented by the single
Alembic migration `0001_core` in `backend/` (67 tables; the model modules under `backend/aslms/domain/` are the
executable form of this document, and `tests/unit/test_schema_metadata.py` keeps the two in step).

**Addendum (approved 1 Oct 2026): `docs/schema/napix_coverage.md`** maps every field the NAPIX APIs
return (docs/specs/napix_field_inventory.md) to a table and column, and adds `napix_responses`, `high_courts`,
`causelist_bench_days`, `case_transfers`, `case_writ_info` and the columns listed there. Migration 0001 is
written from this document plus the approved addendum. **As built (1 Oct 2026):** migration `0001_core`, 73 tables
(the 67 here plus the addendum's six); the decisions log entry "Migration 0001 and seed" records how.

## Conventions (DB_STANDARD §0–§9)
- **Keys.** `id uuid PRIMARY KEY DEFAULT uuid_generate_v7()` (RFC 9562, time-ordered); `uuid6.uuid7()` in Python
  when the id is needed before flush. Business identifiers (CNR, `est_code`, `code`, e-mail) are UNIQUE columns.
  `custody.case_id` and `document_text.document_id` are 1:1 primary keys; `ref_*` tables are keyed by `code`.
- **Table classes.** Every table is `reference` (`ref_*`), `master`, `transaction` or `derived`, declared as
  `__table_class__` on the model and written as `COMMENT ON TABLE … 'class=…'` (`\dt+` shows it).
- **Reference numbers.** Records people quote carry `ref_no varchar(40) NOT NULL UNIQUE`:
  `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>` (`ASLMS/GOA/CASE/2026/001842`, `ASLMS/EDU/NOTE/2026/000042`); `GOA` when
  the system creates the record before a department owns it. One counter per (office, type, year) in
  `ref_sequences`; allocated once at insert, never changed. Types: `CASE` cases, `REQ` requests (retired
  by `custody-workflow`, never allocated), `NOTE` case notes (allocated at finalisation for a draft), `DOC` uploaded court filings and internal documents, `TRF` ownership transfers, `NXT` manual next dates,
  `ALR` alerts, `TKT` admin tickets (allocated on the target department's code; design `user-memberships`). The API accepts a `ref_no` (also as `ASLMS-GOA-CASE-2026-001842` in a URL) wherever a case id is.
- **Code sets.** Eight enumerations users see as labels are `ref_*` tables (`code` PK, `label`, `description`,
  `sort_order`, `is_active`): `ref_role`, `ref_office_kind`, `ref_case_stage` (+ `phase`),
  `ref_note_kind`, `ref_doc_type` (+ `doc_group`), `ref_alert_kind` (+ `default_severity`), `ref_event_type`
  (+ `timeline_label`, `icon_key`, `is_tracking_card`), plus `ref_record_type`; `ref_ticket_kind` added by
  `user-memberships` (migration 0008); `ref_request_kind` dropped by `custody-workflow` (migration 0009), so
  eight `ref_*` tables plus `ref_record_type` and `ref_ticket_kind`. Retired codes stay as rows with
  `is_active = false` (the Python members stay, so old rows still load). The business columns are
  `varchar(40) REFERENCES ref_*(code)`; the Python enums stay the ORM type (their values are the codes) and the seed
  upserts one row per member. The other 48 enumerations (statuses, sources, channels, scan states…) stay native
  Postgres enum types.
- **Timestamps.** `timestamptz` in UTC, IST in the API; court dates as `date`. `created_at` everywhere, `updated_at`
  on the mutable tables (`case_note_drafts` added by `custody-workflow`), maintained by the `set_updated_at()` trigger.
- **Audit columns.** `ActorSnapshotMixin` (`actor_user_id`, `actor_name`, `actor_designation`, `actor_office_code`)
  where accountability matters; `created_by` / `updated_by` (FK `users`, SET NULL, NULL for system writes) on
  masters and on transactions users write that carry no snapshot.
  Report exports write one `audit_log` row (`report.exported`) (design `reports-dashboards`).
- **No deletion.** Every foreign key to a legal-record table is `ON DELETE RESTRICT`. CASCADE remains only on
  `otp_codes`, `refresh_tokens`, `user_notification_preferences`, `notifications`, `digests`, `case_office_scores`,
  `causelist_reconciliations`, `document_text`, `sourcetrace_ingestions`, `assistant_messages`,
  `napix_call_log`. Lifecycle is state: `cases.closed_at`, `documents.archived_at`, `withdrawn_at` on
  transfers, `is_current` on parties and advocates. Masters are deactivated (`is_active`, `deactivated_at`),
  organisation masters versioned (`valid_from`, `valid_to`).
  **Deviation from DB_STANDARD §6 / §9 (owner's rule of 7 Oct 2026):** `aslms_app` may DELETE from
  `case_note_drafts` and `case_note_draft_documents`, which hold unfinished drafts, not legal records (design
  `custody-workflow`, decisions 12–13).
- **Append-only** (trigger `aslms_forbid_change`): `events`, `audit_log`, `case_notes`, `custody_history`,
  `case_stages`, `admin_ticket_documents`, `membership_documents` (the last two added by `user-memberships`),
  `case_note_attachments` (added by `custody-workflow`, migration 0009).
- **Roles.** `aslms_owner` (migrations), `aslms_app` (API, workers, CLI: SELECT/INSERT/UPDATE; INSERT only on the
  append-only tables; DELETE only on the cascade list; no DDL), `aslms_readonly` (SELECT).
- Data received from NAPIX is kept verbatim in a `raw jsonb` column beside the parsed columns; scope checks use
  `offices.path` prefix matching, in SQL only.
- Case visibility is one rule (`services/visibility.py::visibility_bases`, design `cases-api`): the bases
  `state`, `owner`, `recommended`, `pool`, `allotted`, `custody`, `counsel` (`request` removed by
  `custody-workflow`; the custody basis follows the holder membership), OR-ed in SQL for every
  list and evaluated for one case on every detail; summaries of any case are searchable, details only within
  the rule. (user-memberships, migration 0008) The rule is evaluated per active membership and OR-ed;
  functions are per membership (type matrix + the membership's overrides); the union is only a gate.
- Document visibility is one rule (`services/visibility.py::document_visible_condition`, design
  `documents-uploads`): the document function, a visible case the document belongs to (directly or through an
  order), and the document's own setting (`record_visibility_condition`: court records and `counsel_shared` to
  everyone on the case, `case_scope` to everyone but standing counsel, `private_to_office` to the office itself,
  its department-wide callers and the uploader; State-wide readers see all). Notes reuse
  `record_visibility_condition`.

## Group 0 — Code sets and sequences (reference)
| Table | Columns | Notes |
|---|---|---|
| `ref_role`, `ref_office_kind`, `ref_note_kind`, `ref_record_type` | code (PK), label, description, sort_order, is_active | Seeded from `Role`, `OfficeKind`, `NoteKind`, `RecordType`. (custody-workflow) `ref_note_kind` + `opinion`, `hand_over`; `hearing` labelled "Hearing note"; `correction` retired; `ref_record_type` `REQ` retired. `ref_request_kind` dropped by migration 0009. |
| `ref_case_stage` | + phase (`main` / `appeal` / `contempt` / `counsel`) | The 17 lifecycle stages in order. |
| `ref_doc_type` | + doc_group (`court_record` / `court_filing` / `internal`) | The filing vocabulary. |
| `ref_alert_kind` | + default_severity | (custody-workflow) + `workflow` ("Workflow", `normal`); `request_due` retired. |
| `ref_event_type` | + timeline_label, icon_key, is_tracking_card | Timeline labels live in data. `case_taken_over` (tracking card) added by recommend-and-claim (seed only). (custody-workflow) `request_sent`, `request_answered` retired. (data-load-console) `case_merged` ("Case merged", not on the tracking card), seed only. |
| `ref_permission` | + module (`users`, `access`, `admin`, `cases`, `custody`, `requests`, `stages`, `notes`, `documents`, `alerts`, `next_dates`, `reports`, `dashboard`, `assistant`, `audit`) | The functions of the application, seeded from `Permission` (added 1 Oct 2026, migration 0003); `admin.designations` added 4 Oct 2026 (43 functions, seed only, no migration); `admin.scoring` and `cases.take_over` added by recommend-and-claim (45 functions, seed only), `cases.release` relabelled "Stop watching"; `users.propose_head` and `admin.tickets` (reserved: enabled for no type, never overridden) added by `user-memberships` (47 functions, seed only); `custody.recall` and `custody.track` added and `requests.send`, `requests.answer` retired (`is_active = false`, matrix rows disabled, ignored by access) by `custody-workflow` (49 rows, 47 active, seed only); `admin.sourcetrace` ("SourceTrace ingestion", enabled by default for `central_operator`) added by `sourcetrace-connector` (50 rows, 48 active, seed only); `admin.data_load` ("Manage the data load", module `admin`, enabled for no type by default) added by `data-load-console` (51 rows, 49 active, seed only); `seed` refreshes labels and descriptions from `PERMISSION_LABELS`. |
| `ref_ticket_kind` | code (PK), label, description, sort_order, is_active | Seeded from `TicketKind`: `head_change` ("Head of department change"). Added by `user-memberships` (migration 0008). |
| `ref_sequences` | office_code, record_type (FK ref_record_type), year, last_value; PK (office_code, record_type, year) | Locked row by row by `allocate_ref_no`. |

## Group 1 — Organisation and authentication
| Table | Columns (key ones) | Notes |
|---|---|---|
| `offices` (master) | code (unique, e.g. `EDU`, `EDU-DSE`), name, kind (→ `ref_office_kind`), parent_id (self FK), path (materialised, e.g. `GOA/EDU/EDU-DSE`, indexed), is_active, deactivated_at, valid_from, valid_to, created_by, updated_by | Departments and directorates are rows of one table; the visibility tier is derived from kind and path depth. As built (offices-admin, 4 Oct 2026, no migration): `path` is the chain of codes from the root inclusive; `code` and `kind` are immutable after insert; `parent_id` is never changed by the application (no re-parenting); placement: department, central, advocate_general under state, directorate under department, unit under department, directorate, central or advocate_general; deactivation refused while active children, users, ownership or custody reference the office. |
| `designations` (master) | code (unique), name, sort_order, is_active, deactivated_at, valid_from, valid_to, created_by, updated_by | Secretariat designations; seeded with 18, extended under Administration. As built (offices-admin, no migration): `code` immutable (letters, digits, `-`, `_`); `name` and `sort_order` editable; deactivated, never deleted; edited by the new function `admin.designations`. |
| `users` (master) | email (unique), mobile, password_hash (argon2), full_name, designation (text as shown), designation_id (→ designations), office_id, role (→ `ref_role`), is_active, last_login_at, must_confirm_profile, password_changed_at (timestamptz NULL), must_change_password (boolean NOT NULL default false), profile_confirmed_at (timestamptz NULL), created_by, updated_by | **A login** (user-memberships, migration 0008). `office_id`, `role`, `designation`, `designation_id` mirror the primary membership (written only by the membership service, never read for authorisation; kept at the last values when the login has no active membership). Authority lives in `user_memberships`. `super_admin` (added 1 Oct 2026) holds every function and cannot be denied; an inactive login has none. Added by `otp-and-profile` (migration 0010): `password_changed_at` is set by every password set and by an e-mail change, and access tokens issued before it (whole seconds) are refused; `must_change_password` is set when anyone other than the person sets the password (creation, administrator reset, CLI) and cleared by the person's own change or reset; `profile_confirmed_at` is the first profile confirmation (`must_confirm_profile` false afterwards). Back-fill `must_change_password = must_confirm_profile`. While either flag is set the API admits only the first-sign-in endpoints. |
| `user_memberships` (master, versioned) | id (uuid v7 PK), user_id (→ users RESTRICT), office_id (→ offices RESTRICT), department_id (→ offices RESTRICT; the Department-tier ancestor of office_id, NULL for a State-tier office; derived at insert, immutable), role (→ `ref_role`), designation (text as shown, ≤ 200), designation_id (→ designations RESTRICT, NULL allowed), is_primary boolean NOT NULL default false, is_active, deactivated_at, valid_from, valid_to, end_reason (text ≤ 500, NULL; set when ended), created_at, updated_at, created_by, updated_by (→ users SET NULL) | One row per office a person serves in, with that office's designation and user type. Partial unique `ix_user_memberships_one_per_department` (user_id, department_id) NULLS NOT DISTINCT WHERE is_active; partial unique `ix_user_memberships_primary` (user_id) WHERE is_primary AND is_active; partial unique `ix_user_memberships_one_super_admin` (role) WHERE role = 'super_admin' AND is_active; partial unique `ix_user_memberships_one_dept_admin` (department_id) WHERE role = 'dept_admin' AND is_active; partial unique `ix_user_memberships_one_dept_head` (department_id) WHERE role = 'dept_head' AND is_active; index `ix_user_memberships_office_active` (office_id) WHERE is_active. CHECKs `ck_user_memberships_active` (is_active = (deactivated_at IS NULL)), `ck_user_memberships_primary_active` (NOT is_primary OR is_active). A `super_admin` membership is the login's only membership and is written only by the CLI; `dept_admin` and `dept_head` sit at the department office (service). A login may have no active membership after an exit. Ended, never deleted. Functions per membership = type matrix + the membership's overrides; visibility = the union over active memberships (design `user-memberships`, migration 0008). |
| `role_permissions` (master) | role (→ `ref_role`), permission (→ `ref_permission`), is_enabled, created_by, updated_by; unique (role, permission) | The type matrix: one row per type and function, seeded from the plan's Table 1; only `access.manage_types` (the super admin) switches `is_enabled`. Added 1 Oct 2026 (migration 0003). |
| `user_permissions` (master) | user_id, membership_id (→ user_memberships RESTRICT, NOT NULL), permission (→ `ref_permission`), effect (`grant` / `deny`), granted_by_user_id, reason, is_active, deactivated_at, valid_from, valid_to, actor snapshot; unique (membership_id, permission) | Overrides per membership (user-memberships, migration 0008; `user_id` equals the membership's user); never deleted, ended with `valid_to` / `is_active`. A non-super-admin may grant only functions they hold in the acting membership, to memberships in their own office subtree, of the types `dept_officer`, `directorate_user`, `standing_counsel`, `referral_reviewer`. `admin.tickets` is never overridden. Added 1 Oct 2026 (migration 0003). |
| `admin_tickets` (transaction) | id (uuid v7 PK), ref_no (unique, `ASLMS/<department code>/TKT/<yyyy>/<n>`), kind (→ `ref_ticket_kind`), status (`ticket_status`: `open` / `approved` / `rejected` / `withdrawn`), department_id (→ offices RESTRICT, NULL for a kind with no department), target_user_id (→ users RESTRICT, NULL), target_membership_id (→ user_memberships RESTRICT, NULL; for `add` filled on approval), requested_by_user_id (→ users RESTRICT), requested_by_membership_id (→ user_memberships RESTRICT), actor snapshot (actor_user_id, actor_name, actor_designation, actor_office_code — the requesting membership), payload jsonb NOT NULL (the proposed change, per kind), request_remark (≤ 2,000, NULL), result jsonb NULL (what approval applied), decision_remark (≤ 2,000, NULL), decided_by_user_id (→ users SET NULL), decided_by_name, decided_by_designation, decided_by_office_code (snapshot), decided_at, created_at, updated_at | CHECKs `ck_admin_tickets_decided` ((status = 'open') = (decided_at IS NULL)), `ck_admin_tickets_reject_remark` (status <> 'rejected' OR decision_remark IS NOT NULL), `ck_admin_tickets_head_change` (kind <> 'head_change' OR department_id IS NOT NULL). Partial unique `ix_admin_tickets_one_open_head_change` (department_id) WHERE kind = 'head_change' AND status = 'open'; indexes `ix_admin_tickets_status_created` (status, created_at), `ix_admin_tickets_department_status` (department_id, status). Trigger `admin_tickets_closed_frozen` refuses UPDATE of a row whose old status is not `open`. Never deleted. Written only by `services/tickets.py` (design `user-memberships` decisions 15–19, migration 0008). |
| `admin_ticket_documents` (transaction, append-only) | id (uuid v7 PK), ticket_id (→ admin_tickets RESTRICT), document_id (→ documents RESTRICT), actor snapshot, created_at | Unique (ticket_id, document_id). The document is kind `admin`. No UPDATE or DELETE for `aslms_app`. |
| `membership_documents` (transaction, append-only) | id (uuid v7 PK), membership_id (→ user_memberships RESTRICT), document_id (→ documents RESTRICT), ticket_id (→ admin_tickets RESTRICT, NULL), actor snapshot, created_at | Unique (membership_id, document_id). The order that authorised the membership's change, findable after the ticket. No UPDATE or DELETE for `aslms_app`. |
| `otp_codes` (derived) | user_id (CASCADE), purpose (`login` / `password_reset` / `new_device`), code_hash, expires_at (10 min), attempts (max 5), consumed_at | The `id` is the challenge id. `code_hash` is HMAC-SHA256 of the 6-digit code keyed with `ASLMS_JWT_SECRET`. `consumed_at` is set on success, on the last failed attempt, and when a newer code of the same purpose is issued. Index `ix_otp_codes_user_purpose_created` (user_id, purpose, created_at) for the resend wait and the hourly cap (`otp-and-profile`, migration 0010). |
| `refresh_tokens` (derived) | user_id (CASCADE), token_hash, expires_at, revoked_at, device_label, device_id (→ user_devices RESTRICT, NULL for tokens issued before 0010; index `ix_refresh_tokens_device_id`) | Rotating refresh tokens; access tokens are 30-minute JWTs. Presenting a rotated token again revokes every refresh token of the login (`otp-and-profile`, decision 10). |
| `user_devices` (derived) | id (uuid v7 PK), user_id (→ users RESTRICT; logins are never deleted), token_hash (char 64, unique; SHA-256 of the device token), label (text ≤ 200, the client's name for itself, NULL), user_agent (≤ 400), first_ip, last_ip (inet as text ≤ 64, valid addresses only), first_seen_at, last_seen_at, verified_at (last successful code from this device), revoked_at (NULL), created_at, updated_at | Index `ix_user_devices_user_id`. CHECK `ck_user_devices_seen` (last_seen_at >= first_seen_at). The client holds a random 32-byte device token issued after its first successful code; each sign-in names its device and refresh tokens are tied to it; a code is still asked at every sign-in (no device trust). Written only by `services/auth.py`; never deleted (`aslms_app` SELECT / INSERT / UPDATE); a revoked device stays as a record. `updated_at` trigger. Design `otp-and-profile` decision 6, migration 0010. |
| `user_notification_preferences` (master) | user_id (CASCADE), channel (`in_app` / `email` / `sms`), enabled, digest (`none` / `daily`), critical_only | |

## Group 2 — Court masters (NAPIX) and places
| Table | Columns | Notes |
|---|---|---|
| `courts` | est_code (unique, e.g. `GAHC01`), name, state_code, bench_location, court_level (`hc` / `dc`), is_active, deactivated_at | District courts are Phase 3 rows. |
| `benches` | court_id, bench_id (NAPIX), judge_names, bench_type, first_seen, last_seen, is_active, deactivated_at | Bench ids change daily; keep every id as seen. |
| `case_types` | court_id, case_type_code (NAPIX numeric), type_name (e.g. `WP(C)`), full_name, aliases text[], is_active, deactivated_at | Aliases hold the spellings printed in cause lists. |
| `states` | lgd_code (unique, nullable until entered), ecourts_code (unique), name (unique), is_active, deactivated_at | Seeded with Assam (LGD 18); `master_sync` fills `ecourts_code`. |
| `districts` | state_id, lgd_code (unique, nullable), ecourts_code, name; unique (state_id, name) | Seeded with the 35 Assam districts by name; LGD codes are entered, never guessed. |
| `acts` | national_act_code (unique, nullable), name (unique), is_active, deactivated_at | From the NAPIX act master. |
| `advocates` | bar_reg_no (unique, nullable), name, name_normalised (indexed), is_active, deactivated_at | Linked from `case_advocates.advocate_id` when the dossier identifies the advocate. |
| `master_sync_runs` (derived) | master (`state` / `district` / `bench` / `case_type` / `act`), fetched_at, row_count, sha256 | |

## Group 3 — Cases
| Table | Columns | Notes |
|---|---|---|
| `cases` | ref_no (unique), cnr (unique; null only when `is_provisional`), court_id, case_type_id, case_type_text, reg_no, reg_year, case_no_text, filing_case_type_id, filing_no_text, filing_date, registration_date, date_first_list, status (`pending` / `disposed` / `unknown`), disposal_date, disposal_nature, disposal_type, short_order, date_filing_disp, reason_for_rej, next_hearing_date, next_purpose, last_hearing_date, bench_id, coram, category, sub_category, judicial_branch, state_id, district_id, fir_no, fir_year, police_station, petitioner_summary, respondent_summary, pet_advocate, res_advocate, is_provisional, is_tracked, first_seen_source (`causelist` / `search` / `discovery` / `link`), last_full_refresh_at, last_status_refresh_at, merged_into_case_id, closed_at, search_vector (tsvector, derived — see below), raw | Never fabricate a CNR: a row without one is provisional. `closed_at` is set on disposal. `merged_into_case_id` is set only by `services/case_dedupe.py::merge_provisional` (a provisional row without portal records merged into the row holding its CNR); merged rows keep their `ref_no` and events and leave every list (data-load-console, migration 0014). |
| `case_parties` | case_id, role (`petitioner` / `respondent` / `extra`), party_no, name, name_normalised, address, has_legal_heir, is_current | Unique (case_id, role, party_no). A dossier upsert never deletes: parties that disappear get `is_current = false`. |
| `case_advocates` | case_id, side, name_as_listed, advocate_id (→ advocates), bar_reg_no, counsel_code, is_current | `counsel_code` holds the standing-counsel token (e.g. `SC, EDU`) when present. |
| `case_hearings` | case_id, business_date, purpose, bench_text, next_date, business_text, source | Unique (case_id, business_date, purpose). |
| `case_acts` | case_id, act_name_as_listed, act_id (→ acts), national_act_code, section | Unique (case_id, act_name_as_listed, section). |
| `case_applications` | case_id, ia_number, party_name, status, filing_date, raw | `iafiling{}`; unique (case_id, ia_number). |
| `case_lower_courts` | case_id, level (`appellate` / `trial`), court_name, case_no_text, decision_date, raw | `lower_court_*` / `trial_lower_court_*`; unique (case_id, level). |
| `case_objections` | case_id, objection, scrutiny_date, compliance_by_date, receipt_date, raw | `objections{}`; unique (case_id, scrutiny_date). |
| `case_links` | from_case_id, to_case_id (nullable), to_case_no_text, to_cnr, kind (`main_matter` / `connected` / `ia_in` / `appeal_of` / `contempt_of` / `with`), source | Unique (from, to_case_no_text, kind). (data-load-console, migration 0014) `link_kind` + `court_duplicate` (two CNRs the court issued for one case number or filing number; one row from the newer case to the older, never merged); `link_source` + `dedupe`. |
| `case_snapshots` (derived) | case_id, source, fetched_at, payload_sha256, payload jsonb | Unique (case_id, payload_sha256). Diffing successive snapshots produces status and next-date change events. |

> `cases.search_vector` (tsvector) is derived. As built, migration 0005 (adds only this function and two indexes, no table or column): `aslms_case_search_vector(case_id)` (SQL
> function, config `simple`) builds it from the current party names, the party summaries and the cause-list
> party texts (weight A), the current advocates, counsel codes and cause-list advocate texts (weight B) and the
> CNR, case number, filing number and `ref_no` (weight C). It is refreshed by
> `services/cases.py::refresh_search_vector` after every dossier apply, cause-list apply and court-search store;
> never written by hand. GIN index `ix_cases_search_vector_gin`; expression index `ix_cases_case_no_compact` on
> the upper-cased case number without white space.

> Reporting indexes (reports-dashboards, migration 0012, no table or column): partial index
> `ix_cases_disposal_date` (disposal_date) WHERE disposal_date IS NOT NULL; index
> `ix_case_hearings_business_date` (business_date). Dashboards and reports (`services/dashboard.py`,
> `services/reports.py`) only read; they store nothing. Export files are streamed, never kept in `documents`.

## Group 4 — Cause lists
| Table | Columns | Notes |
|---|---|---|
| `causelists` | court_id, list_date, bench_id (NAPIX), napix_causelist_id, list_type (`daily` / `supplementary` / `lawazima` / `vacation` / `other`), label, source (`napix` / `ghc_website` / `local_dir`), document_id (stored PDF), fetch_status, parse_status, entry_count, fetched_at, error, raw | Unique (court_id, list_date, bench_id, napix_causelist_id, source). |
| `causelist_entries` | causelist_id, sr_no, court_no, cnr (nullable), case_id (nullable until resolved), case_no_text, petitioner_text, respondent_text, pet_advocate_text, res_advocate_text, counsel_codes text[], with_text, remarks, source (`napix_details` / `pdf_parse`), resolution_status, raw | Unique (causelist_id, source, sr_no). Immutable once written, except `case_id`, which is filled on resolution and re-pointed when a provisional case is merged into the row holding its CNR (design `data-load-console`, decision 14). |
| `causelist_reconciliations` (derived) | causelist_id (CASCADE), cnr, in_napix, in_pdf, mismatch_fields jsonb | Feeds the data-collection-health report. |

## Group 5 — Ownership and matching (recommend and claim)
As built by `recommend-and-claim` (migration 0004). Index names carry the `ix_` prefix with an explicit suffix
because the convention's generated name (`ix_<table>_<column>`) is already used by the plain indexes.

| Table | Columns | Notes |
|---|---|---|
| `scoring_settings` (master, versioned) | id, version integer (unique), weight_counsel_code, weight_name_pattern, weight_watchlist, weight_linked_case, weight_keyword numeric(4,3) (each > 0 and ≤ 1, CHECK `ck_scoring_settings_weights`), threshold_strong, threshold_possible numeric(4,3) (CHECK `ck_scoring_settings_thresholds`: 0 < possible < strong ≤ 1), reason text, is_current boolean default false, valid_from timestamptz default now(), valid_to timestamptz (CHECK `ck_scoring_settings_current`: is_current = (valid_to IS NULL)), created_at, updated_at, created_by, updated_by (→ users SET NULL) | Partial unique `ix_scoring_settings_current` (is_current) WHERE is_current. A save inserts a new version and closes the previous one; never updated in place for values, never deleted. Version 1 (0.950, 0.800, 0.750, 0.700, 0.400; 0.850, 0.500; "Plan §4.2 defaults") is inserted by `aslms seed`; an empty table means the same defaults as version 0. |
| `counsel_codes` (master) | code (unique, stored normalised, e.g. `SC, EDU`), office_id (→ offices RESTRICT, any office; its Department-tier ancestor receives the score), weight numeric(4,3) NULL (NULL = the kind's setting; a value is an override set by `admin.scoring` holders; CHECK `ck_counsel_codes_weight`), is_generic_state (mapped to `GOA`, scores nothing), notes, is_active, deactivated_at, created_by, updated_by | Deactivated, never deleted; its scores stay until the next rescore. |
| `office_name_patterns` (master) | office_id, pattern (exact/prefix stored normalised; regex validated by the service), kind (`exact` / `prefix` / `regex`), weight NULL (same meaning, CHECK `ck_office_name_patterns_weight`), is_active, deactivated_at, created_by, updated_by | Unique (office_id, pattern, kind). |
| `office_keywords` (master) | office_id, keyword (stored normalised: upper case, dots as spaces, whitespace collapsed), weight NULL (same meaning, CHECK `ck_office_keywords_weight`), is_active, deactivated_at, created_by, updated_by | Unique (office_id, keyword). |
| `office_watchlist` (master) | office_id, cnr (16-character CNR checked by the service), case_id (→ cases RESTRICT, filled when the case is held), reason, weight NULL (same meaning, CHECK `ck_office_watchlist_weight`), is_active, deactivated_at, actor snapshot | Unique (office_id, cnr). |
| `case_office_scores` (derived) | case_id (CASCADE; recomputed), office_id (a Department-tier office), score numeric(4,3), signals jsonb, computed_at, engine_version (`"<engine>.<scoring_settings version>"`, `1.1` at the defaults) | Unique (case_id, office_id). Only rows with score > 0; rows that drop to 0 are deleted. `signals` is an array of `{kind, rule_id, rule_office_code, weight, matched, where, ref}` (kind ∈ `counsel_code`, `keyword`, `name_pattern`, `linked_case`, `watchlist`; `where` ∈ `causelist_entry`, `case_advocates`, `case_parties`, `case_summary`, `case_links`, `watchlist`), plus `{kind: "suggested_unit", office_code}` when the strongest rule sat below the department. |
| `recommendations` | case_id, office_id (always a Department-tier office), score (CHECK `ck_recommendations_score_range`: 0..1), band (`high` / `medium`), status (`recommended` / `claimed` / `dismissed` / `suggested_elsewhere` / `expired`), origin, suggested_office_id, acted_at, reason, actor snapshot | Partial unique `ix_recommendations_active` (case_id, office_id) WHERE status = 'recommended'. Engine rows carry the system actor (`actor_name = 'matching'`), suggestion rows the suggesting user. `expired` is set by the engine when an engine score drops below the current `threshold_possible` or the case is merged. The unclaimed pool is "cases that have never had a primary owner". |
| `case_ownership` | case_id, office_id (a Department-tier office), role (`primary` / `watcher`), officer_user_id, unit_office_id (an office strictly inside office_id), allotted_at, allotted_by_user_id (→ users SET NULL), claimed_at, status (`active` / `transferred` / `released`), released_at, release_reason, actor snapshot | Partial unique `ix_case_ownership_active_primary` (case_id) WHERE status = 'active' AND role = 'primary'; `ix_case_ownership_active_office` (case_id, office_id) WHERE status = 'active'. CHECK `ck_case_ownership_release_watcher` (status <> 'released' OR role = 'watcher'): a primary row is never released; a claimed case never returns to the pool and leaves a department only by an accepted transfer. Written only by an explicit claim, transfer or take-over. |
| `ownership_transfers` | ref_no (unique, `ASLMS/<from office>/TRF/<yyyy>/<n>`), case_id, from_office_id, to_office_id, status (`requested` / `accepted` / `declined` / `withdrawn`), reason, stay_as_watcher boolean default false, decision_note, decided_by_user_id, decided_at, withdrawn_at, actor snapshot | Partial unique `ix_ownership_transfers_open` (case_id) WHERE status = 'requested'. The inbox "Transfers" tab. |

`custody` / `custody_history` (Phase 2 tables) are first written by `recommend-and-claim`, for primary-ownership
moves only; `custody_history.reason` codes `claimed`, `allotted`, `taken_over`, `transferred`; `custody-workflow`
adds `sent`, `recalled` and (with `user-memberships`) `reassigned_on_exit`.

## Group 6 — Documents and orders
| Table | Columns | Notes |
|---|---|---|
| `documents` (transaction) | ref_no (unique; allocated for `upload` and `attachment` rows on the uploader's office, `ASLMS/<office>/DOC/<yyyy>/<n>`), sha256 (indexed, **not** unique), storage_key, mime, size_bytes, original_filename, kind (`causelist` / `order` / `upload` / `attachment` / `admin`), doc_type (→ `ref_doc_type`), doc_group (`court_record` / `court_filing` / `internal`), case_id (→ cases RESTRICT), doc_date, description, visibility (`case_scope` / `counsel_shared` / `private_to_office`), office_id (→ offices RESTRICT; the uploader's office), virus_scan_status, scanned_at, text_status (`pending` / `extracted` / `failed` / `none`), text_extracted_at, page_count, sourcetrace_status, sourcetrace_ref, archived_at, archive_reason, actor snapshot, created_at, updated_at | Partial unique `ix_documents_system_sha` (kind, sha256) WHERE kind IN ('causelist','order'); partial unique `ix_documents_upload_dedupe` (case_id, office_id, sha256) WHERE kind = 'upload' AND archived_at IS NULL; one stored file may back several rows (the store is content-addressed). CHECKs: `ck_documents_internal_not_sent` (internal → `sourcetrace_status = not_applicable`), `ck_documents_user_file` (uploads and attachments carry ref_no, office_id, doc_date, scan `clean`, never `court_record`), `ck_documents_upload_case`, `ck_documents_archive_reason`; (user-memberships, migration 0008) `ck_documents_user_file` covers `upload`, `attachment`, `admin`, and `ck_documents_admin_file` (kind <> 'admin' OR (case_id IS NULL AND doc_group = 'internal' AND visibility = 'private_to_office')): an `admin` document belongs to an admin ticket or membership (link tables), never to a case. Uploads are stored only after a clean virus scan (design `documents-uploads`); system PDFs are `skipped`. Only `court_record` and `court_filing` may ever be sent to SourceTrace, and a `private_to_office` filing is not sent. Retired with `archived_at` + `archive_reason`, never deleted; visibility may change (audited), content never. (sourcetrace-connector, migration 0011) `sourcetrace_attempts` (integer NOT NULL default 0; attempts since the document last became `pending`), `sourcetrace_next_at` (timestamptz NULL; not claimed before this), `sourcetrace_ingested_at` (timestamptz NULL). CHECKs `ck_documents_sourcetrace_kind` (`sourcetrace_status = 'not_applicable' OR kind IN ('order', 'upload')`), `ck_documents_private_not_sent` (`visibility <> 'private_to_office' OR sourcetrace_status = 'not_applicable'`), `ck_documents_sourcetrace_ingested` (`sourcetrace_status <> 'ingested' OR (sourcetrace_ref IS NOT NULL AND sourcetrace_ingested_at IS NOT NULL)`). Partial index `ix_documents_sourcetrace_due` (`sourcetrace_next_at`) WHERE `sourcetrace_status = 'pending'`. `sourcetrace_status`, `sourcetrace_ref`, `sourcetrace_attempts`, `sourcetrace_next_at` and `sourcetrace_ingested_at` are written only by `services/sourcetrace_ingest.py`, except the transitions of `services/documents.py` (upload, visibility change, archive: design `sourcetrace-connector` decisions 9–10). `sourcetrace_ref` is SourceTrace's reference stored verbatim (≤ 200). |
| `document_text` (transaction) | document_id (PK, CASCADE), page_count, full_text, search_vector (tsvector, `to_tsvector('english', left(full_text, 500000))`, GIN `ix_document_text_search_vector_gin`), created_at, updated_at | Written only by the text-extraction job. |
| `orders` | case_id, order_no (NAPIX), order_date, kind (`interim` / `final` / `judgment`), is_reportable, document_id, download_status, download_attempts, last_error, raw | Unique (case_id, order_no, order_date). |

## Group 7 — Next dates, alerts and notifications
As built by `alerts-notifications` (migration 0007, 6 Oct 2026): `alerts` gains `office_id`, `data`, `closed_at`, `closed_by_user_id` (indexed), CHECKs and indexes; `notifications` gains `severity`, `attempts`, `next_attempt_at` and the outbox index; `digests` gains its sending state. `ref_alert_kind` gains `ownership` and `new_document` (seed only). The rows below are the as-built columns.
| Table | Columns | Notes |
|---|---|---|
| `next_dates` | ref_no (unique, manual entries only), case_id, next_date, source (`causelist` / `current_status` / `order_specific` / `order_period` / `manual`), order_id, confidence, needs_review, review_status, reviewed_by_user_id, reviewed_at, note, created_by, updated_by | Unique (case_id, next_date, source, order_id). |
| `alerts` (transaction) | ref_no (unique, `ASLMS/GOA/ALR/<yyyy>/<n>`, allocated only for a new dedupe key), case_id (→ cases RESTRICT, NULL only for `admin_ticket`), kind (→ `ref_alert_kind`: `hearing_due`, `next_date_changed`, `new_order`, `status_changed`, `compliance_due`, `request_due` (retired), `recommendation`, `ownership`, `new_document`, `admin_ticket`, `workflow` (custody-workflow: file received, file recalled, due / overdue; key `workflow_due:<leg id>` for the date alert)), office_id (→ offices RESTRICT; the office addressed), due_at, severity (`critical` / `high` / `normal`; may only rise), status (`open` / `acknowledged` / `done` / `expired`), title, body, data jsonb (links and dates: `order_id`, `document_id`, `recommendation_id`, `request_id`, `transfer_id`, `hearing_date`, `previous_date`, `source`, `closed_reason`), source_event_id (→ events), dedupe_key (unique, `<kind>:<subject>`), acknowledged_by_user_id, acknowledged_at, closed_at, closed_by_user_id (→ users SET NULL), created_at, updated_at | CHECKs `ck_alerts_closed` (done/expired ⇔ closed_at), `ck_alerts_acknowledged`, `ck_alerts_case` ((case_id IS NULL) = (kind = 'admin_ticket'); user-memberships, migration 0008: a case-less alert is visible only to its notified recipients). Indexes `ix_alerts_case_status`, partial `ix_alerts_open_kind`, `ix_alerts_office_id`. Written by the event scan and the date sweep (design `alerts-notifications`); raised only for cases with an active owner or watcher, except `recommendation`. Never deleted; closed by state. |
| `notifications` (derived) | alert_id (CASCADE), user_id (CASCADE), channel (`in_app` / `email`; `sms` reserved), status (`queued` / `sent` / `failed` / `read`), severity (the level notified), title, body, attempts, next_attempt_at, sent_at, read_at, error, dedupe_key (unique, `n:<alert>:<user>:<channel>:<severity>`), created_at | CHECK `ck_notifications_read` (`read` only for in-app, with read_at). Indexes `ix_notifications_user_inbox`, partial `ix_notifications_outbox`. In-app rows are `sent` on insert; e-mail rows are sent by the sender job, retried up to 3 times. |
| `digests` (derived) | user_id (CASCADE), digest_date (unique per user), status (`queued` / `sent` / `failed`), item_count, alert_ids uuid[], body, attempts, next_attempt_at, sent_at, error, created_at | Daily 08:00 IST digest; no row when there is nothing to send. |

## Group 8 — Events and audit (append-only)
| Table | Columns | Notes |
|---|---|---|
| `events` | case_id, type (→ `ref_event_type`), occurred_at, actor_user_id, payload jsonb, dedupe_key (unique), visibility (`tracking_card` / `scoped`) | Every state change emits one event; timelines, alerts and dashboards read from here. |
| `audit_log` | action, entity_type, entity_id, case_id, ip, user_agent, before jsonb, after jsonb, actor snapshot | Searchable by user, case and date; read-only for auditors. |

> Audit search indexes (audit-screens, migration 0013, no table or column): `ix_audit_log_created_at`
> (created_at) and `ix_audit_log_actor_created` (actor_user_id, created_at). The log is read by
> `services/audit_search.py` only (`GET /audit`, keyset on `(created_at, id)`, IST date bounds), by holders of
> `audit.view` in a State-wide membership; reading writes nothing. `audit_log` stays append-only (`aslms_app`
> SELECT / INSERT), class `derived`, FKs unchanged (`case_id` → cases RESTRICT, `actor_user_id` → users SET NULL).

## Group 9 — Integration and operations (data-collection health)
| Table | Columns | Notes |
|---|---|---|
| `job_runs` (derived) | job, run_date, started_at, finished_at, status, counters jsonb, error | |
| `napix_call_log` (derived) | api, params_sha256, http_status, napix_status (6xx), duration_ms, ok, error, called_at, job_run_id (CASCADE) | Indexed on called_at; pruned after a retention period (the one allowed deletion). |
| `source_failures` (derived) | kind, ref, error, first_seen, last_seen, attempts, resolved_at | Read by the administration "needs attention" screen. |
| `data_load_settings` (master, versioned) | id (uuid v7 PK), version integer NOT NULL UNIQUE, paused boolean NOT NULL default false, load_order (`load_order` enum: `cases_first` / `lists_first` / `cases_with_orders`) NOT NULL default `cases_first`, first_from date NULL, first_to date NULL, reason text NOT NULL, is_current boolean NOT NULL default false, valid_from timestamptz NOT NULL default now(), valid_to timestamptz NULL, created_at, updated_at, created_by, updated_by (→ users SET NULL) | CHECKs `ck_data_load_settings_current` (is_current = (valid_to IS NULL)), `ck_data_load_settings_first` ((first_from IS NULL) = (first_to IS NULL) AND (first_from IS NULL OR first_from <= first_to)). Partial unique `ix_data_load_settings_current` (is_current) WHERE is_current. A pause, resume or order change inserts a new version and closes the previous one; values never updated in place, rows never deleted. Empty table = running, `cases_first`, nothing brought forward. Read by `queue.claim` (pause) and by the load priority policy; written only by `services/data_load.py` (design `data-load-console`, migration 0014). |

> `fetch_queue` (napix_coverage §A) gains `lane` (`fetch_lane` enum: `request` / `daily` / `load`, NOT NULL default
> `daily`; precedence in that order, a row asked by two lanes keeps the higher one) and `list_date` (date NULL: the
> cause-list date whose loading queued the row; inherited by the dossiers and order PDFs it spawns). Indexes
> `ix_fetch_queue_claim` (priority, created_at) WHERE status = 'pending', and `ix_fetch_queue_lane_list_date` (lane,
> list_date). `queue.claim` skips `lane = 'load'` while the current `data_load_settings` row is paused, and the
> runner claims `load` rows only above `NAPIX_RATE_RESERVE` and other lanes only above `NAPIX_LIVE_RESERVE`.
> Priorities: masters 10, the daily list days 20, status batches and a person's requests 30, today's new dossiers and
> live-case order PDFs 40, the load 41–48 (design `data-load-console`, decision 3), the weekly sweep 50,
> disposed-case order PDFs 80. `napix_call_log` gains `lane` (`fetch_lane` NULL: the lane of the queue item that
> made the call; NULL for calls made by the API). `napix_call_log`, `fetch_queue` and `source_failures` are read
> live by `services/data_health.py` and `services/data_load.py` (`/admin/data-health`, `/admin/napix/*`,
> `/admin/data-load*`); buttons write `fetch_queue` rows only through `queue.enqueue`. `source_failures` kind
> `case_duplicate` (ref `<provisional id>|<holder id>`) lists provisional rows that could not be merged.

> `napix_call_log` gains `user_id` (uuid NULL, → users **RESTRICT**; users are never deleted): the person whose
> action caused the call — a court search or fetch, the connectivity check, or a `request`-lane queue row they
> asked for. NULL for daily and load lane work, window probes, CLI checks and rows written before 0015. Partial
> index `ix_napix_call_log_user_called` (user_id, called_at) WHERE user_id IS NOT NULL. `called_at` is the
> attempt's own time (`NapixResult.called_at`), not the flushing transaction's. `fetch_queue` gains
> `requested_by` (uuid NULL, → users **RESTRICT**): the person who asked for the row's pending run; set on insert,
> revive or requeue from the caller, kept (`COALESCE`) while pending; CHECK `ck_fetch_queue_requested_by`
> (`requested_by IS NULL OR lane = 'request'`); copied by the runner to the calls the row makes and inherited by
> the rows it spawns. The quota window is derived, not stored: `services/napix_window.py` reads the call-log
> readings (`rate_limit_remaining` NOT NULL) of the last 6 hours; a reset is a rise of at least
> `NAPIX_WINDOW_RESET_JUMP`, precise when the previous reading is at most 300 s older; the phase comes from the
> latest precise reset (design `napix-window`, migration 0015). Both tables stay class `derived`; `aslms_app`
> grants unchanged (INSERT / SELECT on `napix_call_log`; SELECT / INSERT / UPDATE on `fetch_queue`).

## Phase 2 and 3 tables
| Table | Columns (key ones) | Notes |
|---|---|---|
| `custody` | case_id (PK, → cases RESTRICT), holder_office_id (→ offices RESTRICT), holder_user_id (→ users SET NULL), holder_membership_id (→ user_memberships RESTRICT, NULL for an office-held leg), pending_action, since, due_date, current_leg_id (→ custody_history) | Exists only for claimed cases. Written only by `services/custody.py::move_custody`: ownership moves, `sent`, `recalled`, `reassigned_on_exit`. Partial index `ix_custody_due` (due_date) WHERE due_date IS NOT NULL; index `ix_custody_holder_user_id` (holder_user_id). `request_id` dropped by 0009. |
| `custody_history` (derived, append-only) | id, case_id, seq_no (unique per case), holder_office_id + holder_office_code, holder_user_id + holder_user_name, holder_membership_id (→ user_memberships RESTRICT) + holder_designation (snapshot, ≤ 200), reason (CHECK `ck_custody_history_reason`: `claimed`, `allotted`, `taken_over`, `transferred`, `sent`, `recalled`, `reassigned_on_exit`), pending_action, due_date, remark (≤ 2,000; CHECK `ck_custody_history_remark`: reason NOT IN ('sent','recalled','reassigned_on_exit') OR remark IS NOT NULL), started_at, actor snapshot (the sender or recaller), created_at | One row per movement; the chain is the file's movement record. `request_id` dropped by 0009; exit-step legs written before 0009 get their remark back-filled from their `custody_moved` event. |
| `case_stages` (append-only) | case_id, office_id, stage (→ `ref_case_stage`), response_mode, note, actor snapshot | Latest row is the current stage. Guided, not enforced. Index `ix_case_stages_case_created` (case_id, created_at DESC). |
| `case_notes` (transaction, append-only) | ref_no (unique), case_id, seq_no (unique per case), kind (→ `ref_note_kind`), body, visibility, office_id, author_role, custody_leg_id, supersedes_id, source, drafted_at timestamptz NULL (set when the note came from a draft), actor snapshot | The noting trail; corrections supersede, both kept. CHECK `ck_case_notes_not_self`; partial unique `ix_case_notes_supersedes` (supersedes_id) WHERE supersedes_id IS NOT NULL. A note is permanent from insert; drafts live in `case_note_drafts`. |
| `case_note_attachments` (transaction, append-only) | note_id, document_id | Internal documents; never sent to SourceTrace. Trigger `aslms_forbid_change` added by 0009; no UPDATE for `aslms_app`. |
| `case_note_drafts` (transaction, **mutable and deletable**) | id (uuid v7 PK), case_id (→ cases RESTRICT), membership_id (→ user_memberships RESTRICT; the holder membership that wrote it), author_user_id (→ users RESTRICT), custody_leg_id (→ custody_history RESTRICT; the leg during which written), kind (→ `ref_note_kind`), body (1–20,000), visibility (`doc_visibility`), supersedes_id (→ case_notes RESTRICT, NULL), created_at, updated_at, actor snapshot | Index `ix_case_note_drafts_case_membership` (case_id, membership_id). Visible only to `author_user_id`. Exists only while `membership_id` holds the case; turned into `case_notes` rows and deleted in the transaction that moves custody away (design `custody-workflow` decisions 12–13). `aslms_app` has DELETE on this table. |
| `case_note_draft_documents` (transaction, deletable with its draft) | id, draft_id (→ case_note_drafts RESTRICT), document_id (→ documents RESTRICT), created_at | Unique (draft_id, document_id). The document belongs to the draft's case. Rows deleted by the service before their draft; become `case_note_attachments` on finalisation. `aslms_app` has DELETE. |
| `sourcetrace_ingestions` (derived, append-only) | id (uuid v7 PK), document_id (→ documents CASCADE, DB_STANDARD §6), attempt (integer NOT NULL; the document's `sourcetrace_attempts` after this attempt), ok (boolean NOT NULL), connector (varchar 40 NOT NULL; the implementation's `name`), reference (≤ 200, NULL), error (text ≤ 2,000, NULL), error_family (varchar 40 NULL: `unavailable` / `timeout` / `rejected` / `protocol` / `store` / `error`), duration_ms (integer NOT NULL default 0), metadata_sent (jsonb NOT NULL; exactly what was sent besides the bytes), response (jsonb NULL; SourceTrace's answer verbatim), created_at | CHECK `ck_sourcetrace_ingestions_outcome` (`(ok AND reference IS NOT NULL AND error_family IS NULL) OR (NOT ok AND error IS NOT NULL AND error_family IS NOT NULL)`). Index `ix_sourcetrace_ingestions_document_created` (document_id, created_at) replaces `ix_sourcetrace_ingestions_document_id`. Trigger `aslms_forbid_change` (`sourcetrace_ingestions_append_only`); `aslms_app` SELECT / INSERT only. One row per attempt, written only by `services/sourcetrace_ingest.py` in the transaction that records the outcome on the document. Never holds secrets, note text or internal documents (design `sourcetrace-connector`). |
| `assistant_conversations` | user_id, case_id, scope, title, last_message_at | Private to the user. |
| `assistant_messages` | conversation_id (CASCADE), role, content, citations jsonb, model_info jsonb | |

Still deferred: district-court rows in `courts` and the NAPIX DC integration (Phase 3; no DC API specification in
the repository yet); PostgreSQL schemas per bounded context (DB_STANDARD §9, revisited with Phase 3).

Removed by `custody-workflow` (migration 0009, after checking they are empty): `requests`, `request_messages`,
`ref_request_kind`, the `request_status` enum and the `request_id` columns of `custody` and `custody_history`
(sending the file replaces requests, owner's rule of 7 Oct 2026).

## Not carried over from the prototype's 56 tables
AI and knowledge-base tables (ai_jobs, research_*, document_chunks, chunk_embeddings, order_analyses,
order_directions, order_citations, issues, case_briefs, judgments_external, legal_instruments and
versions/sections), `assignments` (replaced by `recommendations` + `case_ownership`), `match_feedback`,
`court_outcomes`, `listing_reconciliations` (renamed), and the pgvector extension.
