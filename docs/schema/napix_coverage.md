# NAPIX coverage addendum to the schema (1 Oct 2026 — for approval before migration 0001)

Rule (owner, 1 Oct): **every piece of information the NAPIX APIs provide is stored.** Two layers guarantee it:

1. **Verbatim.** Every response is kept as the court sent it. The CNR dossier and Current Status go to
   `case_snapshots.payload` (already in `schema.md`); every other JSON response goes to a new derived table
   `napix_responses`; PDFs go to `documents` (content-addressed). Nothing can be missed, even a field nobody
   documented, and a later column can always be back-filled from the stored payloads.
2. **Typed.** Every path in `docs/specs/napix_field_inventory.md` (generated from the live samples by
   `aslms napix-fields`) has a table.column below. A unit test (`test_napix_coverage.py`, written with migration
   0001) reads the inventory and this file's tables and fails on any path without a home.

Inventory as of 1 Oct: 17 samples of 13 APIs, 230 path rows (a disposed and a pending dossier). Paths that the
inventory shows only as empty blocks (`iafiling`, `objections`, `transfer`, `writinfo`) get tables from the
e-Committee specifications (HC Open API v1.0 §6.1.6; eCourts Open API v1.3 §5.2.6 for the two blocks the HC spec
does not describe), marked 📄 = documented, not yet seen with data; the verbatim layer covers them meanwhile.

Conventions as in `DB_STANDARD.md`: UUID v7 keys, `class=` on every table, RESTRICT, court identifiers stored
exactly as issued, NAPIX date strings (`yyyy-mm-dd`, `''` for none) parsed to `date` with the text kept in the
payload.

## A. New and changed tables (relative to `schema.md`)

| Table | Class | Change |
|---|---|---|
| `napix_responses` | derived | **new**: `api`, `params_sha256`, `params` (the plain input string's key=value pairs as jsonb, no secrets), `fetched_at`, `payload_sha256`, `payload jsonb`, `token_verified`, `job_run_id`; unique (api, params_sha256, payload_sha256). One row per distinct response; a repeat with the same payload only bumps `last_seen_at`. |
| `high_courts` | master | **new**: `napix_state_code int UNIQUE` (18), `name` ("Gauhati High Court"); from the state master, which lists High Courts, not States. |
| `courts` | master | + `high_court_id` (→ high_courts), `napix_bench_no` (the bench master's `bench_id` 1–4), `name` = `bench_name` ("Principal Seat at Guwahati"). `state_code` dropped in favour of `high_court_id`. |
| `districts` | master | + `high_court_id`, `ecourts_code` (`dist_code`), `ecourts_name` (`dist_name`, eCourts spelling), `kind` (`district` / `agency` for CBI, NIA, C/O 99 APO — entered by the administrator, not guessed). `name` and `lgd_code` stay the LGD values; the two are linked by the administrator or by exact-name match. |
| `case_types` | master | `type_name` keeps the full master string (`"WA : Writ Appeal"`); + `short_name` ("WA"), `full_name` ("Writ Appeal") split on the first `:`; `aliases` as before. |
| `acts` | master | unchanged (`national_act_code`, `name` = `actname`). |
| `benches` | master | `bench_id` = the cause-list / dossier bench id (2048, 2068…), `judge_names` = `judge_name`; + `bench_name` ("Division Bench"), `bench_type_code` (int) from the dossier; `first_seen`, `last_seen`. |
| `causelist_bench_days` | transaction | **new**: (`court_id`, `list_date`, `bench_id`, `judge_names_as_listed`), unique on the three keys — which benches sat on which day, as Cause List Bench reported it. |
| `causelists` | transaction | `napix_causelist_id` = `causelist_id`; + `list_type_text` (`cause_list_type` trimmed, verbatim), `bench_label` (`bench`); `list_type` enum derived from the text. |
| `cases` | transaction | + `filing_no int`, `filing_year int` (from `fil_no`, `fil_year`; `filing_no_text` kept), `filing_case_type_text` (`type_name_fil`), `date_judgement_pronounced`, `date_judgement_reserved`, `bench_name`, `bench_type_code`, `coram_designation` (`desgname`), `category_code` (the leading number of `category_details.category`), `filing_state_code`, `filing_district_code` (`document_details.*`), `police_st_code`, `goshwara_no`, `main_matter_text`, `court_est_name`; existing columns receive the rest (table C). |
| `case_parties` | transaction | unchanged shape; `pet_name` / `res_name` = party 1, `*_extra_party.party_no{n}` = parties n; `has_legal_heir` from `pet_legal_heir` / `res_legal_heir`. |
| `case_advocates` | transaction | unchanged (`pet_adv`, `res_adv` as listed; counsel codes parsed). |
| `case_acts` | transaction | unchanged (`acts[].actname`, `acts[].section`; `act_id` by name/code). |
| `orders` | transaction | + `order_details` ("ORDER" / "JUDGEMENT"), `order_judge_name`, `date_judgement_pronounced`, `date_judgement_reserved`; `kind` derived (`interimorder[]` → interim, `finalorder[]` → final, `order_details = JUDGEMENT` → judgment). |
| `case_hearings` | transaction | + `hearing_date` (the dossier's `hearing_date`, distinct from `business_date`), `causelist_type`, `judge_designation` (`desgname` from Show Business), `case_number_text`, `short_order_text` (`short_order_det`); `purpose` = `purpose_of_listing`, `bench_text` = `judge_name`, `business_text` = `business`. |
| `case_applications` | transaction | 📄 `iafiling[]` (HC spec §6.1.6, `sr_no{n}`): `ia_number`, `ia_pet_name` → `party_name`, `ia_pend_disp` → `status` (P/D), `date_of_filing` → `filing_date`; unique (case_id, ia_number). Empty in every sample so far. |
| `case_objections` | transaction | 📄 `objections` (HC spec §6.1.6) is **one flat block, not a list**: `objection1`, `objection2`, … plus `scrutiny_date`, `objections_compliance_by_date`, `obj_reciept_date` (sic). One row per `objection{n}`: `seq`, `objection`, `scrutiny_date`, `compliance_by_date`, `receipt_date`; unique (case_id, scrutiny_date, seq). Empty (`[]`) in every sample so far. |
| `case_transfers` | transaction | 📄 **new**: `transfer[]` (`sr_no{n}`; documented only in the eCourts/DC spec §5.2.6, returned empty by the HC backend): `transfer_date`, `from_court_no_desgname` → `from_court_text`, `to_court_no_desgname` → `to_court_text`; unique (case_id, transfer_date, to_court_text). Not to be confused with the portal's own `ownership_transfers`. |
| `case_writ_info` | transaction | 📄 **new**: `writinfo[]` (`sr_no{n}`; DC spec §5.2.6: cases filed in an appellate court): `appellate_case_number`, `appellate_authority`; unique (case_id, appellate_case_number). Returned empty by the HC backend so far. |
| `case_links` | transaction | 📄 `link_cases[]` (HC spec §6.1.6, `sr_no{n}`: `filing_number`, `case_number`) joins the existing table as kind `linked` with `filing_number_text`, `case_number_text` (the CNR of the linked case is not given; resolved by case number when known). `null` in the spec sample; absent from the live samples. |
| `case_lower_courts` | transaction | unchanged (`lower_court_*` → appellate, `trial_lower_court_*` → trial). |
| `case_links` | transaction | unchanged; `main_matter_cino` → kind main_matter (`main_matter` text kept on `cases.main_matter_text`). |
| `case_snapshots` | derived | unchanged: the whole dossier / status block, sha256-deduplicated. |
| `fetch_queue` | derived | **new** (load-and-refresh pipeline, approved 1 Oct): `kind` (`masters` / `causelist_day` / `dossier` / `status_batch` / `order_pdf`), `ref` (date, CNR, order key or batch id), `priority` smallint, `status` (`pending` / `running` / `done` / `failed` / `skipped`), `attempts`, `not_before`, `started_at`, `finished_at`, `last_error`, `job_run_id`; unique (kind, ref). The resumable work list every worker pulls from; `running` rows older than the stale limit are re-queued. Rows are never deleted; `done` rows older than the retention period may be pruned like `napix_call_log`. |
| `cases` (refresh flags) | transaction | + `dossier_stale boolean default false` (set when a Current Status block differs from the stored dossier; cleared by the next dossier apply). `last_full_refresh_at` and `last_status_refresh_at` already exist and serve as `dossier_fetched_at` / `status_checked_at`. `orders.download_status` already carries `pending` / `stored` / `failed` / `not_available`. |

## B. Masters and cause lists — path by path

| API | Path | Table.column |
|---|---|---|
| state_master | `state[].state_code` | `high_courts.napix_state_code` |
| | `state[].state_name` | `high_courts.name` |
| district_master | `[].dist_code` | `districts.ecourts_code` |
| | `[].dist_name` | `districts.ecourts_name` |
| bench_master | `benches[].bench_id` | `courts.napix_bench_no` |
| | `benches[].bench_name` | `courts.name` |
| | `benches[].est_code` | `courts.est_code` |
| case_type_master | `[].case_type` | `case_types.case_type_code` |
| | `[].type_name` | `case_types.type_name` (+ `short_name`, `full_name`) |
| act_master | `[].national_act_code` | `acts.national_act_code` |
| | `[].actname` | `acts.name` |
| causelist_bench | `[].bench_id` | `benches.bench_id`; `causelist_bench_days.bench_id` |
| | `[].judge_name` | `benches.judge_names`; `causelist_bench_days.judge_names_as_listed` |
| causelist_details | `[].bench` | `causelists.bench_label` |
| | `[].bench_id` | `causelists.bench_id` |
| | `[].causelist_id` | `causelists.napix_causelist_id` |
| | `[].cause_list_type` | `causelists.list_type_text` → `list_type` |
| show_causelist | *(PDF)* | `documents` (kind causelist) → `causelists.document_id`; rows → `causelist_entries` (parser) |
| overview | `overview, version, contact, license, uri_scheme, consumes, produces` | `napix_responses.payload` only (service description, used by the data-health check) |

## C. Search by CNR (dossier) and Current Status — path by path

| Path (dossier / status) | Table.column |
|---|---|
| `cino` | `cases.cnr` |
| `est_code`, `court_est_name` | `cases.court_id` (by est_code); `cases.court_est_name` |
| `case_type_id` | `cases.case_type_id` (by `case_types.case_type_code`) |
| `type_name_reg`, status `type_name` | `cases.case_type_text` |
| `type_name_fil` | `cases.filing_case_type_text` (+ `filing_case_type_id` by short name) |
| `fil_no`, `fil_year` | `cases.filing_no`, `cases.filing_year`, `cases.filing_no_text` |
| `reg_no`, `reg_year` | `cases.reg_no`, `cases.reg_year`, `cases.case_no_text` |
| `date_of_filing` | `cases.filing_date` |
| `dt_regis` | `cases.registration_date` |
| `date_first_list` | `cases.date_first_list` |
| `date_last_list` | `cases.last_hearing_date` |
| `date_next_list` | `cases.next_hearing_date`; `next_dates` (source current_status) |
| `purpose_name` | `cases.next_purpose` |
| `pend_disp` | `cases.status` (P → pending, D → disposed) |
| `date_of_decision` | `cases.disposal_date` |
| `disposal_type`, status `disp_nature` | `cases.disposal_type`, `cases.disposal_nature` |
| `date_filing_disp` | `cases.date_filing_disp` |
| `date_judgement_pronounced`, `date_judgement_reserved` | `cases.date_judgement_pronounced`, `cases.date_judgement_reserved` |
| `short_order` | `cases.short_order` |
| `reason_for_rej` | `cases.reason_for_rej` |
| `bench_id` | `cases.bench_id` (→ `benches`) |
| `bench_name`, `bench_type` | `cases.bench_name`, `cases.bench_type_code`; also `benches.bench_name`, `benches.bench_type_code` |
| `coram` | `cases.coram` |
| `desgname` | `cases.coram_designation` |
| `judicial_branch` | `cases.judicial_branch` |
| `category_details.category` | `cases.category` (text), `cases.category_code` (leading number) |
| `document_details.case_state_code`, `document_details.case_dist_code` | `cases.filing_state_code`, `cases.filing_district_code` (→ `districts.ecourts_code`) |
| `state_name`, `dist_name` | `cases.state_id` (→ `states` by name), `cases.district_id` (→ `districts.ecourts_name`) |
| `fir_no`, `fir_year`, `police_station`, `police_st_code` | `cases.fir_no`, `cases.fir_year`, `cases.police_station`, `cases.police_st_code` |
| `uniform_code` | `cases.uniform_code` |
| `goshwara_no` (status) | `cases.goshwara_no` |
| `main_matter`, `main_matter_cino` | `cases.main_matter_text`; `case_links` (kind main_matter, `to_cnr`) |
| `pet_name`, `res_name` | `case_parties` (role, party_no 1); `cases.petitioner_summary`, `cases.respondent_summary` |
| `pet_extra_party.party_no{n}`, `res_extra_party.party_no{n}` | `case_parties` (role, party_no n, name) |
| `pet_legal_heir`, `res_legal_heir` | `case_parties.has_legal_heir` (per side) |
| `pet_adv`, `res_adv` | `case_advocates` (side, name_as_listed, counsel_code); `cases.pet_advocate`, `cases.res_advocate` |
| `acts[].actname`, `acts[].section` | `case_acts.act_name_as_listed`, `case_acts.section` (+ `act_id`) |
| `interimorder[]` / `finalorder[]`: `order_no`, `order_date`, `order_details`, `order_judge_name`, `date_judgement_pronounced`, `date_judgement_reserved` | `orders` (kind, order_no, order_date, order_details, order_judge_name, date_judgement_pronounced, date_judgement_reserved); the PDF from Show Order → `documents` → `orders.document_id` |
| `historyofcasehearing[]`: `business_date`, `hearing_date`, `judge_name`, `purpose_of_listing`, `causelist_type` | `case_hearings` (business_date, hearing_date, bench_text, purpose, causelist_type) |
| `iafiling[]` 📄: `ia_number`, `ia_pet_name`, `ia_pend_disp`, `date_of_filing` | `case_applications` (ia_number, party_name, status, filing_date) |
| `objections` 📄: `objection{n}`, `scrutiny_date`, `objections_compliance_by_date`, `obj_reciept_date` | `case_objections` (seq, objection, scrutiny_date, compliance_by_date, receipt_date) |
| `transfer[]` 📄: `transfer_date`, `from_court_no_desgname`, `to_court_no_desgname` | `case_transfers` (transfer_date, from_court_text, to_court_text) |
| `writinfo[]` 📄: `appellate_case_number`, `appellate_authority` | `case_writ_info` |
| `link_cases[]` 📄: `filing_number`, `case_number` | `case_links` (kind linked, filing_number_text, case_number_text) |
| `category_details.sub_category` 📄 | `cases.sub_category` |
| `historyofcasehearing[].desgname` (DC spec only), `pet_adv_cd`, `res_adv_cd`, `pet_adv_bar_reg`, `res_adv_bar_reg`, `court_no`, `processes[]` (DC spec only) | not returned by the HC backend (absent from the HC spec and from every HC sample); if one ever appears it lands in `case_snapshots.payload` and the coverage test flags it for a column. |
| `lower_court_name`, `lower_court_caseno`, `lower_court_dec_dt` | `case_lower_courts` (level appellate: court_name, case_no_text, decision_date) |
| `trial_lower_court_name`, `trial_lower_court_caseno`, `trial_lower_court_dec_dt` | `case_lower_courts` (level trial) |
| *(whole dossier / status block)* | `case_snapshots.payload` |

## D. Show Business and the searches — path by path

| API | Path | Table.column |
|---|---|---|
| show_business | `case_number` | `case_hearings.case_number_text` |
| | `business_date` | `case_hearings.business_date` (match key with the case) |
| | `business` | `case_hearings.business_text` |
| | `short_order_det` | `case_hearings.short_order_text` |
| | `desgname` | `case_hearings.judge_designation` |
| case_search, party_name | `establishment_name` | `courts.name` (confirmation only) |
| | `casenos[].cino` | `cases.cnr` (the case is created or found; the dossier is fetched on first sight) |
| | `casenos[].pet_name`, `casenos[].res_name` | `cases.petitioner_summary`, `cases.respondent_summary` |
| | `casenos[].reg_no`, `casenos[].reg_year`, `casenos[].type_name`, `casenos[].case_type_id` | `cases.reg_no`, `cases.reg_year`, `cases.case_type_text`, `cases.case_type_id` |
| | `casenos[].police_st_code`, `casenos[].uniform_code` | `cases.police_st_code`, `cases.uniform_code` |
| *(every response)* | | `napix_responses.payload` |

## E. Still open

- **Show Cause List is one PDF per (bench, causelist_id)**, not the court-wide file the website publishes (probe of
  1 Oct: bench 2048's Lawazima for 2025-01-06 is 2 pages; the website Lawazima PDF for the same day is 6 pages and
  covers every registrar bench). `causelists` therefore holds one row per bench list from NAPIX and one row per
  court-wide file from the website; `causelist_entries` dedupe across the two by (list_date, cnr, sr_no) in the
  reconciliation table, and the gateway serves past dates (2025-01-06 and 2025-06-02 both answered), so NAPIX is
  the source for the historical load and the website PDFs are the fallback only.

- The four empty blocks are now typed from the specifications (📄 rows above; HC Open API v1.0 §6.1.6, eCourts
  Open API v1.3 §5.2.6). The coverage test treats an inventory path that is empty in every sample as covered when
  its block has a 📄 table. The three PDFs were reviewed on 1 Oct; copy them to `docs/specs/pdf/` so the repository
  carries them (they are not committed yet).
- The Subscriber Manual v1.5 adds nothing to the schema; it confirms the token URL, the one-hour token and the
  `100 calls per hour` default plan shown on the subscription screen (the live header says 1000: the plan the
  gateway applies is to be read from `X-RateLimit-Limit`, not assumed).
- Search by Advocate, by Filing number, by Act, Advocate Bar Reg, Neutral Citation and the Caveat APIs are not
  sampled (not in the plan's usage map); when one is added, its paths join this file first.
- The rate-limit window: the remaining count was 948 at 12:52 and 994 at 12:56, so the window is short (minutes),
  not daily; `RateLimiter.window_seconds` stays 60 until measured.

Approval of this addendum (sections A–D) is what migration 0001 is written from, together with `schema.md`.
