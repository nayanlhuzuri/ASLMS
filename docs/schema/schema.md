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
  `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>` (`ASLMS/GOA/CASE/2026/001842`, `ASLMS/EDU/REQ/2026/000042`); `GOA` when
  the system creates the record before a department owns it. One counter per (office, type, year) in
  `ref_sequences`; allocated once at insert, never changed. Types: `CASE` cases, `REQ` requests, `NOTE` case
  notes, `DOC` uploaded court filings and internal documents, `TRF` ownership transfers, `NXT` manual next dates,
  `ALR` alerts. The API accepts a `ref_no` (also as `ASLMS-GOA-CASE-2026-001842` in a URL) wherever a case id is.
- **Code sets.** Eight enumerations users see as labels are `ref_*` tables (`code` PK, `label`, `description`,
  `sort_order`, `is_active`): `ref_role`, `ref_office_kind`, `ref_case_stage` (+ `phase`), `ref_request_kind`,
  `ref_note_kind`, `ref_doc_type` (+ `doc_group`), `ref_alert_kind` (+ `default_severity`), `ref_event_type`
  (+ `timeline_label`, `icon_key`, `is_tracking_card`), plus `ref_record_type`. The business columns are
  `varchar(40) REFERENCES ref_*(code)`; the Python enums stay the ORM type (their values are the codes) and the seed
  upserts one row per member. The other 48 enumerations (statuses, sources, channels, scan states…) stay native
  Postgres enum types.
- **Timestamps.** `timestamptz` in UTC, IST in the API; court dates as `date`. `created_at` everywhere, `updated_at`
  on the 39 mutable tables, maintained by the `set_updated_at()` trigger.
- **Audit columns.** `ActorSnapshotMixin` (`actor_user_id`, `actor_name`, `actor_designation`, `actor_office_code`)
  where accountability matters; `created_by` / `updated_by` (FK `users`, SET NULL, NULL for system writes) on
  masters and on transactions users write that carry no snapshot.
- **No deletion.** Every foreign key to a legal-record table is `ON DELETE RESTRICT`. CASCADE remains only on
  `otp_codes`, `refresh_tokens`, `user_notification_preferences`, `notifications`, `digests`, `case_office_scores`,
  `causelist_reconciliations`, `document_text`, `sourcetrace_ingestions`, `assistant_messages`,
  `napix_call_log`. Lifecycle is state: `cases.closed_at`, `documents.archived_at`, `withdrawn_at` on requests and
  transfers, `is_current` on parties and advocates. Masters are deactivated (`is_active`, `deactivated_at`),
  organisation masters versioned (`valid_from`, `valid_to`).
- **Append-only** (trigger `aslms_forbid_change`): `events`, `audit_log`, `case_notes`, `custody_history`,
  `case_stages`.
- **Roles.** `aslms_owner` (migrations), `aslms_app` (API, workers, CLI: SELECT/INSERT/UPDATE; INSERT only on the
  append-only tables; DELETE only on the cascade list; no DDL), `aslms_readonly` (SELECT).
- Data received from NAPIX is kept verbatim in a `raw jsonb` column beside the parsed columns; scope checks use
  `offices.path` prefix matching, in SQL only.

## Group 0 — Code sets and sequences (reference)
| Table | Columns | Notes |
|---|---|---|
| `ref_role`, `ref_office_kind`, `ref_request_kind`, `ref_note_kind`, `ref_record_type` | code (PK), label, description, sort_order, is_active | Seeded from `Role`, `OfficeKind`, `RequestKind`, `NoteKind`, `RecordType`. |
| `ref_case_stage` | + phase (`main` / `appeal` / `contempt` / `counsel`) | The 17 lifecycle stages in order. |
| `ref_doc_type` | + doc_group (`court_record` / `court_filing` / `internal`) | The filing vocabulary. |
| `ref_alert_kind` | + default_severity | |
| `ref_event_type` | + timeline_label, icon_key, is_tracking_card | Timeline labels live in data. |
| `ref_sequences` | office_code, record_type (FK ref_record_type), year, last_value; PK (office_code, record_type, year) | Locked row by row by `allocate_ref_no`. |

## Group 1 — Organisation and authentication
| Table | Columns (key ones) | Notes |
|---|---|---|
| `offices` (master) | code (unique, e.g. `EDU`, `EDU-DSE`), name, kind (→ `ref_office_kind`), parent_id (self FK), path (materialised, e.g. `EDU/EDU-DSE`, indexed), is_active, deactivated_at, valid_from, valid_to, created_by, updated_by | Departments and directorates are rows of one table; the visibility tier is derived from kind and path depth. |
| `designations` (master) | code (unique), name, sort_order, is_active, deactivated_at, valid_from, valid_to, created_by, updated_by | Secretariat designations; seeded with 18, extended under Administration. |
| `users` (master) | email (unique), mobile, password_hash (argon2), full_name, designation (text as shown), designation_id (→ designations), office_id, role (→ `ref_role`), is_active, last_login_at, must_confirm_profile, created_by, updated_by | One role per user. |
| `otp_codes` (derived) | user_id (CASCADE), purpose (`login` / `password_reset` / `new_device`), code_hash, expires_at (10 min), attempts (max 5), consumed_at | |
| `refresh_tokens` (derived) | user_id (CASCADE), token_hash, expires_at, revoked_at, device_label | Rotating refresh tokens; access tokens are 15-minute JWTs. |
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
| `cases` | ref_no (unique), cnr (unique; null only when `is_provisional`), court_id, case_type_id, case_type_text, reg_no, reg_year, case_no_text, filing_case_type_id, filing_no_text, filing_date, registration_date, date_first_list, status (`pending` / `disposed` / `unknown`), disposal_date, disposal_nature, disposal_type, short_order, date_filing_disp, reason_for_rej, next_hearing_date, next_purpose, last_hearing_date, bench_id, coram, category, sub_category, judicial_branch, state_id, district_id, fir_no, fir_year, police_station, petitioner_summary, respondent_summary, pet_advocate, res_advocate, is_provisional, is_tracked, first_seen_source (`causelist` / `search` / `discovery` / `link`), last_full_refresh_at, last_status_refresh_at, merged_into_case_id, closed_at, search_vector (tsvector, GIN), raw | Never fabricate a CNR: a row without one is provisional. `closed_at` is set on disposal. |
| `case_parties` | case_id, role (`petitioner` / `respondent` / `extra`), party_no, name, name_normalised, address, has_legal_heir, is_current | Unique (case_id, role, party_no). A dossier upsert never deletes: parties that disappear get `is_current = false`. |
| `case_advocates` | case_id, side, name_as_listed, advocate_id (→ advocates), bar_reg_no, counsel_code, is_current | `counsel_code` holds the standing-counsel token (e.g. `SC, EDU`) when present. |
| `case_hearings` | case_id, business_date, purpose, bench_text, next_date, business_text, source | Unique (case_id, business_date, purpose). |
| `case_acts` | case_id, act_name_as_listed, act_id (→ acts), national_act_code, section | Unique (case_id, act_name_as_listed, section). |
| `case_applications` | case_id, ia_number, party_name, status, filing_date, raw | `iafiling{}`; unique (case_id, ia_number). |
| `case_lower_courts` | case_id, level (`appellate` / `trial`), court_name, case_no_text, decision_date, raw | `lower_court_*` / `trial_lower_court_*`; unique (case_id, level). |
| `case_objections` | case_id, objection, scrutiny_date, compliance_by_date, receipt_date, raw | `objections{}`; unique (case_id, scrutiny_date). |
| `case_links` | from_case_id, to_case_id (nullable), to_case_no_text, to_cnr, kind (`main_matter` / `connected` / `ia_in` / `appeal_of` / `contempt_of` / `with`), source | Unique (from, to_case_no_text, kind). |
| `case_snapshots` (derived) | case_id, source, fetched_at, payload_sha256, payload jsonb | Unique (case_id, payload_sha256). Diffing successive snapshots produces status and next-date change events. |

## Group 4 — Cause lists
| Table | Columns | Notes |
|---|---|---|
| `causelists` | court_id, list_date, bench_id (NAPIX), napix_causelist_id, list_type (`daily` / `supplementary` / `lawazima` / `vacation` / `other`), label, source (`napix` / `ghc_website` / `local_dir`), document_id (stored PDF), fetch_status, parse_status, entry_count, fetched_at, error, raw | Unique (court_id, list_date, bench_id, napix_causelist_id, source). |
| `causelist_entries` | causelist_id, sr_no, court_no, cnr (nullable), case_id (nullable until resolved), case_no_text, petitioner_text, respondent_text, pet_advocate_text, res_advocate_text, counsel_codes text[], with_text, remarks, source (`napix_details` / `pdf_parse`), resolution_status, raw | Unique (causelist_id, source, sr_no). Immutable once written. |
| `causelist_reconciliations` (derived) | causelist_id (CASCADE), cnr, in_napix, in_pdf, mismatch_fields jsonb | Feeds the data-collection-health report. |

## Group 5 — Ownership and matching (recommend and claim)
| Table | Columns | Notes |
|---|---|---|
| `counsel_codes` (master) | code (unique, as printed, e.g. `SC, EDU`), office_id, weight (default 0.95), is_generic_state, notes, is_active, deactivated_at, created_by, updated_by | Deactivated, never deleted; its scores stay. |
| `office_name_patterns` (master) | office_id, pattern, kind (`exact` / `prefix` / `regex`), weight, is_active, deactivated_at, created_by, updated_by | |
| `office_keywords` (master) | office_id, keyword, weight, is_active, deactivated_at, created_by, updated_by | |
| `office_watchlist` (master) | office_id, cnr, case_id, reason, weight, is_active, deactivated_at, actor snapshot | |
| `case_office_scores` (derived) | case_id (CASCADE; recomputed), office_id, score numeric(4,3), signals jsonb, computed_at, engine_version | Unique (case_id, office_id). |
| `recommendations` | case_id, office_id, score, band (`high` / `medium`), status (`recommended` / `claimed` / `dismissed` / `suggested_elsewhere` / `expired`), origin, suggested_office_id, acted_at, reason, actor snapshot | One active row per (case, office). Cases below 0.50 get no row: the unclaimed pool is "cases with no active ownership". |
| `case_ownership` | case_id, office_id, role (`primary` / `watcher`), officer_user_id, unit_office_id, claimed_at, status (`active` / `transferred` / `released`), released_at, actor snapshot | One active primary owner per case. Written only by an explicit claim. |
| `ownership_transfers` | ref_no (unique), case_id, from_office_id, to_office_id, status (`requested` / `accepted` / `declined` / `withdrawn`), reason, decided_by_user_id, decided_at, withdrawn_at, actor snapshot | The inbox "Transfers" tab. |

## Group 6 — Documents and orders
| Table | Columns | Notes |
|---|---|---|
| `documents` | ref_no (unique, uploads only), sha256 (unique), storage_key, mime, size_bytes, original_filename, kind, doc_type (→ `ref_doc_type`), doc_group (`court_record` / `court_filing` / `internal`), case_id, doc_date, description, visibility (`case_scope` / `counsel_shared` / `private_to_office`), office_id, virus_scan_status, scanned_at, text_status, text_extracted_at, sourcetrace_status, sourcetrace_ref, archived_at, actor snapshot | Only `court_record` and `court_filing` may ever be sent to SourceTrace; `internal` never. Retired with `archived_at`, never deleted. |
| `document_text` | document_id (PK, CASCADE), page_count, full_text, search_vector (tsvector, GIN) | |
| `orders` | case_id, order_no (NAPIX), order_date, kind (`interim` / `final` / `judgment`), is_reportable, document_id, download_status, download_attempts, last_error, raw | Unique (case_id, order_no, order_date). |

## Group 7 — Next dates, alerts and notifications
| Table | Columns | Notes |
|---|---|---|
| `next_dates` | ref_no (unique, manual entries only), case_id, next_date, source (`causelist` / `current_status` / `order_specific` / `order_period` / `manual`), order_id, confidence, needs_review, review_status, reviewed_by_user_id, reviewed_at, note, created_by, updated_by | Unique (case_id, next_date, source, order_id). |
| `alerts` | ref_no (unique), case_id, kind (→ `ref_alert_kind`), due_at, severity (`critical` / `high` / `normal`), status (`open` / `acknowledged` / `done` / `expired`), title, body, source_event_id, dedupe_key (unique), acknowledged_by_user_id, acknowledged_at | |
| `notifications` (derived) | alert_id (CASCADE), user_id (CASCADE), channel, status (`queued` / `sent` / `failed` / `read`), title, body, sent_at, read_at, error, dedupe_key (unique) | |
| `digests` (derived) | user_id (CASCADE), digest_date, sent_at, alert_ids uuid[] | Daily 08:00 digest. |

## Group 8 — Events and audit (append-only)
| Table | Columns | Notes |
|---|---|---|
| `events` | case_id, type (→ `ref_event_type`), occurred_at, actor_user_id, payload jsonb, dedupe_key (unique), visibility (`tracking_card` / `scoped`) | Every state change emits one event; timelines, alerts and dashboards read from here. |
| `audit_log` | action, entity_type, entity_id, case_id, ip, user_agent, before jsonb, after jsonb, actor snapshot | Searchable by user, case and date; read-only for auditors. |

## Group 9 — Integration and operations (data-collection health)
| Table | Columns | Notes |
|---|---|---|
| `job_runs` (derived) | job, run_date, started_at, finished_at, status, counters jsonb, error | |
| `napix_call_log` (derived) | api, params_sha256, http_status, napix_status (6xx), duration_ms, ok, error, called_at, job_run_id (CASCADE) | Indexed on called_at; pruned after a retention period (the one allowed deletion). |
| `source_failures` (derived) | kind, ref, error, first_seen, last_seen, attempts, resolved_at | Read by the administration "needs attention" screen. |

## Phase 2 and 3 tables
| Table | Columns (key ones) | Notes |
|---|---|---|
| `custody` | case_id (PK), holder_office_id, holder_user_id, pending_action, since, due_date, request_id, current_leg_id | Where the case is now; derived from claims, allotments, transfers, requests and hand-overs. |
| `custody_history` (derived, append-only) | case_id, seq_no, holder_office_id + code snapshot, holder_user_id + name snapshot, reason, pending_action, due_date, request_id, started_at, actor snapshot | One row per leg. |
| `requests` | ref_no (unique), case_id, kind (→ `ref_request_kind`), from_office_id, to_office_id, to_user_id, subject, body, due_date, status (`open` / `answered` / `withdrawn`), answered_at, answered_by_user_id, withdrawn_at, actor snapshot | Sending moves custody to the receiving office; answering or withdrawing brings it back. |
| `request_messages` | request_id, body, is_answer, actor snapshot | |
| `case_stages` (append-only) | case_id, office_id, stage (→ `ref_case_stage`), response_mode, note, actor snapshot | Latest row is the current stage. Guided, not enforced. |
| `case_notes` (append-only) | ref_no (unique), case_id, seq_no (unique per case), kind (→ `ref_note_kind`), body, visibility, office_id, author_role, custody_leg_id, supersedes_id, source, actor snapshot | The noting trail; corrections supersede, both kept. |
| `case_note_attachments` | note_id, document_id | Internal documents; never sent to SourceTrace. |
| `sourcetrace_ingestions` (derived) | document_id (CASCADE), attempt, ok, reference, error, metadata_sent | |
| `assistant_conversations` | user_id, case_id, scope, title, last_message_at | Private to the user. |
| `assistant_messages` | conversation_id (CASCADE), role, content, citations jsonb, model_info jsonb | |

Still deferred: district-court rows in `courts` and the NAPIX DC integration (Phase 3; no DC API specification in
the repository yet); PostgreSQL schemas per bounded context (DB_STANDARD §9, revisited with Phase 3).

## Not carried over from the prototype's 56 tables
AI and knowledge-base tables (ai_jobs, research_*, document_chunks, chunk_embeddings, order_analyses,
order_directions, order_citations, issues, case_briefs, judgments_external, legal_instruments and
versions/sections), `assignments` (replaced by `recommendations` + `case_ownership`), `match_feedback`,
`court_outcomes`, `listing_reconciliations` (renamed), and the pgvector extension.
