# ASLMS v2 — Phase 1 database schema (approved 25 Sep 2026)

Source: `docs/Legal_Case_Monitoring_Portal_Plan.docx` section 7 (data groups) and the decisions log.
The database starts empty; there is no migration of earlier data. Phase 2 and 3 tables are listed at the end
so that Phase 1 columns leave the right hooks. Implemented by Alembic migration `0001_phase1_core` in `backend/`
(39 tables; the model modules under `backend/aslms/domain/` are the executable form of this document).

## Conventions
- UUID primary keys (`gen_random_uuid()`); `created_at` / `updated_at` as `timestamptz`; the application works in IST.
- Enumerations are Postgres enums, named `<table>_<column>`.
- Wherever accountability matters, the actor is stored twice: the user id **and** a frozen snapshot
  (`actor_name`, `actor_designation`, `actor_office_code`) taken at write time.
- Data received from NAPIX is kept verbatim in a `raw jsonb` column beside the parsed columns.
- Append-only tables (`events`, `audit_log`) never receive UPDATE or DELETE; enforced by database grants.
- Scope checks use `offices.path` prefix matching, in SQL only.

## Group 1 — Organisation and authentication
| Table | Columns (key ones) | Notes |
|---|---|---|
| `offices` | code (unique, e.g. `EDU`, `EDU-DSE`), name, kind (`department` / `directorate` / `section` / `state_office` / `counsel_office` / `central_cell`), parent_id (self FK), path (materialised, e.g. `EDU/EDU-DSE`, indexed), is_active | Departments and directorates are rows of one table; the visibility tier is derived from kind and path depth. |
| `users` | email (unique), mobile, password_hash (argon2), full_name, designation, office_id, role (`state_oversight` / `dept_admin` / `dept_officer` / `dept_head` / `directorate_user` / `referral_reviewer` / `standing_counsel` / `central_operator` / `auditor`), is_active, last_login_at, must_confirm_profile | One role per user. |
| `otp_codes` | user_id, purpose (`login` / `password_reset` / `new_device`), code_hash, expires_at (10 min), attempts (max 5), consumed_at | |
| `refresh_tokens` | user_id, token_hash, expires_at, revoked_at, device_label | Rotating refresh tokens; access tokens are 15-minute JWTs. |
| `user_notification_preferences` | user_id, channel (`in_app` / `email` / `sms`), digest (`none` / `daily`), critical_only | |

## Group 2 — Reference data (NAPIX masters and court)
| Table | Columns | Notes |
|---|---|---|
| `courts` | est_code (unique, e.g. `GAHC01`), name, state_code, bench_location, court_level (`hc` / `dc`), is_active | District courts are Phase 3 rows. |
| `benches` | court_id, bench_id (NAPIX), judge_names, bench_type, first_seen, last_seen | Bench ids change daily; keep every id as seen. |
| `case_types` | court_id, case_type_code (NAPIX numeric), type_name (e.g. `WP(C)`), aliases text[] | Aliases hold the spellings printed in cause lists. |
| `master_sync_runs` | master (`state` / `district` / `bench` / `case_type`), fetched_at, row_count, sha256 | |

## Group 3 — Cases
| Table | Columns | Notes |
|---|---|---|
| `cases` | cnr (unique; null only when `is_provisional`), court_id, case_type_id, reg_no, reg_year, case_no_text, filing_no_text, filing_date, registration_date, status (`pending` / `disposed` / `unknown`), disposal_date, disposal_nature, next_hearing_date, next_purpose, last_hearing_date, bench_id, coram, category, judicial_branch, petitioner_summary, respondent_summary, pet_advocate, res_advocate, is_provisional, is_tracked, first_seen_source (`causelist` / `search` / `discovery` / `link`), last_full_refresh_at, last_status_refresh_at, merged_into_case_id, search_vector (tsvector, GIN), raw | Never fabricate a CNR: a row without one is provisional. |
| `case_parties` | case_id, role (`petitioner` / `respondent` / `extra`), party_no, name, name_normalised, address | Unique (case_id, role, party_no). |
| `case_advocates` | case_id, side, name, bar_reg_no, counsel_code | `counsel_code` holds the standing-counsel token (e.g. `SC, EDU`) when present. |
| `case_hearings` | case_id, business_date, purpose, bench_text, next_date, business_text, source | Unique (case_id, business_date, purpose). `business_text` comes from Show Business. |
| `case_acts` | case_id, act_name, national_act_code, section | |
| `case_links` | from_case_id, to_case_id (nullable), to_case_no_text, kind (`main_matter` / `connected` / `ia_in` / `appeal_of` / `contempt_of` / `with`), source | Unique (from, to, kind). `to_case_no_text` is used until the target case exists. |
| `case_snapshots` | case_id, source, fetched_at, payload_sha256, payload jsonb | Unique (case_id, payload_sha256). Diffing successive snapshots produces status and next-date change events. |

## Group 4 — Cause lists
| Table | Columns | Notes |
|---|---|---|
| `causelists` | court_id, list_date, bench_id (NAPIX), napix_causelist_id, list_type (`daily` / `supplementary` / `lawazima` / `vacation` / `other`), label, source (`napix` / `ghc_website` / `local_dir`), document_id (stored PDF), fetch_status, parse_status, entry_count, fetched_at | Unique (court_id, list_date, bench_id, causelist_id, source). |
| `causelist_entries` | causelist_id, sr_no, court_no, cnr (nullable), case_id (nullable until resolved), case_no_text, petitioner_text, respondent_text, pet_advocate_text, res_advocate_text, counsel_codes text[], with_text, remarks, source (`napix_details` / `pdf_parse`), resolution_status (`resolved` / `provisional` / `unresolved`), raw | Unique (causelist_id, source, sr_no). Two sources are kept until the live test shows whether Cause List Details returns rows. |
| `causelist_reconciliations` | causelist_id, cnr, in_napix, in_pdf, mismatch_fields jsonb | Feeds the data-collection-health report. |

## Group 5 — Ownership and matching (recommend and claim)
| Table | Columns | Notes |
|---|---|---|
| `counsel_codes` | code (unique, as printed, e.g. `SC, EDU`), office_id, weight (default 0.95), is_generic_state, notes, is_active | Managed in Administration. `is_generic_state` marks codes such as `PP, ASSAM` that identify the State but not a department. |
| `office_name_patterns` | office_id, pattern, kind (`exact` / `prefix` / `regex`), weight, is_active | |
| `office_keywords` | office_id, keyword, weight, is_active | |
| `office_watchlist` | office_id, cnr or case_id, reason, added_by, is_active | |
| `case_office_scores` | case_id, office_id, score numeric(4,3), signals jsonb, computed_at, engine_version | Unique (case_id, office_id). `signals` is a list of `{kind, value, weight, matched_text}`. Recomputed on every listing and refresh. |
| `recommendations` | case_id, office_id, score, band (`high` ≥ 0.85 / `medium` 0.50–0.85), status (`recommended` / `claimed` / `dismissed` / `suggested_elsewhere` / `expired`), origin (`cause_list` / `discovery` / `suggestion` / `link_history` / `search`), suggested_office_id, acted_by_user_id (+snapshot), acted_at, reason | One active row per (case, office). Cases below 0.50 get no row: the unclaimed pool is "cases with no active ownership". |
| `case_ownership` | case_id, office_id, role (`primary` / `watcher`), officer_user_id, claimed_by_user_id (+snapshot), claimed_at, status (`active` / `transferred` / `released`), released_at | Partial unique index: one active primary owner per case. Nothing is written here except by an explicit claim. |
| `ownership_transfers` | case_id, from_office_id, to_office_id, requested_by, status (`requested` / `accepted` / `declined`), reason, decided_by, decided_at | The inbox "Transfers" tab. |

## Group 6 — Documents and orders
| Table | Columns | Notes |
|---|---|---|
| `documents` | sha256 (unique), storage_key, mime, size_bytes, original_filename, kind (`court_order` / `causelist` / `court_filing` / `internal` / `other`), doc_type (`writ_petition` / `affidavit_in_opposition` / `reply` / `rejoinder` / `ia` / `annexure` / `compliance_report` / `parawise_comments` / `instructions_to_counsel` / `order` / `judgment` / `causelist_pdf` / `other`), doc_group (`court_record` / `court_filing` / `internal`), case_id (nullable), doc_date, description, visibility (`case_scope` / `counsel_shared` / `private_to_office`), uploaded_by_user_id (+snapshot), office_id, virus_scan_status (`pending` / `clean` / `infected` / `failed`), scanned_at, text_status (`pending` / `done` / `failed` / `not_applicable`), text_extracted_at, sourcetrace_status (`not_applicable` / `pending` / `ingested` / `failed`), sourcetrace_ref | Only `court_record` and `court_filing` may ever be sent to SourceTrace; `internal` never. `sourcetrace_*` stay `not_applicable` in Phase 1. |
| `document_text` | document_id (PK), page_count, full_text, search_vector (tsvector, GIN) | Kept separate so `documents` stays narrow. |
| `orders` | case_id, order_no (NAPIX), order_date, kind (`interim` / `final` / `judgment`), is_reportable, document_id (nullable), download_status (`pending` / `downloaded` / `not_available` / `failed`), download_attempts, raw | Unique (case_id, order_no, order_date). |

## Group 7 — Next dates, alerts and notifications
| Table | Columns | Notes |
|---|---|---|
| `next_dates` | case_id, next_date, source (`causelist` / `current_status` / `order_specific` / `order_period` / `manual`), order_id (nullable), confidence, needs_review, review_status (`none` / `pending` / `confirmed` / `rejected`), reviewed_by, created_at | Phase 1 writes the first three sources; `order_period` arrives with SourceTrace in Phase 2. |
| `alerts` | case_id, kind (`hearing` / `next_date` / `compliance` / `order_received` / `unclaimed_followup` / `data_health`), due_at, severity (`critical` within 48 h / `high` this week / `normal`), status (`open` / `acknowledged` / `done` / `expired`), title, body, source_event_id, dedupe_key (unique) | |
| `notifications` | alert_id (nullable), user_id, channel (`in_app` / `email` / `sms`), status (`queued` / `sent` / `failed` / `read`), sent_at, read_at, error, dedupe_key (unique) | SMS is a stub until Phase 2. |
| `digests` | user_id, digest_date, sent_at, alert_ids uuid[] | Daily 08:00 digest. |

## Group 8 — Events and audit (append-only)
| Table | Columns | Notes |
|---|---|---|
| `events` | case_id (nullable), type (enum: `listed`, `listed_supplementary`, `hearing_date_changed`, `status_changed`, `order_received`, `case_created`, `case_merged`, `recommendation_made`, `recommendation_dismissed`, `case_claimed`, `ownership_transferred`, `watcher_added`, `document_uploaded`, `next_date_extracted`, `alert_raised`, `source_failed`, …), occurred_at, actor_user_id (nullable), payload jsonb, dedupe_key (unique), visibility (`tracking_card` / `scoped`) | Every state change emits one event; timelines, alerts and dashboards read from here. |
| `audit_log` | actor_user_id (+snapshot), action, entity_type, entity_id, case_id (nullable), ip, user_agent, before jsonb, after jsonb, created_at | Searchable by user, case and date; read-only for auditors. |

## Group 9 — Integration and operations (data-collection health)
| Table | Columns | Notes |
|---|---|---|
| `job_runs` | job (`daily_cycle` / `status_refresh` / `full_refresh` / `order_download` / `discovery` / `master_sync`), run_date, started_at, finished_at, status, counters jsonb, error | |
| `napix_call_log` | api, params_sha256, http_status, napix_status (6xx), duration_ms, ok, error, called_at, job_run_id | Indexed on called_at; pruned after a retention period. |
| `source_failures` | kind (`napix` / `ghc_pdf` / `order_download` / `antivirus`), ref, error, first_seen, last_seen, attempts, resolved_at | Read by the administration "needs attention" screen. |

## Deferred by design
- **Phase 2:** `custody`, `custody_history`, `requests`, `request_messages`, `case_stages`, `case_notes`, `case_note_attachments`, `sourcetrace_ingestions`, `decisions`, `deadlines`; `next_dates.source = order_period`.
- **Phase 3:** `assistant_conversations`, `assistant_messages`, `assistant_citations`; district-court rows in `courts` and the NAPIX DC integration.

## Not carried over from the prototype's 56 tables
AI and knowledge-base tables (ai_jobs, research_*, document_chunks, chunk_embeddings, order_analyses, order_directions, order_citations, issues, case_briefs, judgments_external, legal_instruments and versions/sections), `assignments` (replaced by `recommendations` + `case_ownership`), `match_feedback`, `court_outcomes`, `listing_reconciliations` (renamed), and the pgvector extension.
