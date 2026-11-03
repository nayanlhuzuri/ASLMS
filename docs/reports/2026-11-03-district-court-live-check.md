# Report: District Court live check (row 222, `district-court-live-check`)

Run on 3 Nov 2026, 16:02 to 16:05 IST, on branch `check/district-court-live`. This was a live test, not a build cycle: there is no schema change and no change to application code. The probe is `backend/tools/dc_probe.py`. It ran in one-off containers of the api image, with the court-data switch on for each run only, and recreated no stack service. The behaviour found is recorded in `docs/napix_integration_notes.md` §10. The decrypted samples are in `docs/specs/samples/dc/`.

## Calls made
- **17 District Court calls** (the budget was 20), one at a time, and no token request. The access token the High Court worker already held was accepted. No Overview call was made.
- `napix_call_log` holds 17 rows with an api of `dc-*`: 14 ok, 1 HTTP 500 and 2 HTTP 400. All 17 have `rate_limit_remaining` NULL. `napix_responses` holds 13 rows, one per JSON answer; the order PDF is not stored there, as for the High Court.
- Per API: state 1, district 1, court complex 3, court list 1, cause list 3 (civil, then criminal, which failed with HTTP 500, then criminal again, which worked), CNR 2, current status 1, show business 1, order 1, advocate cause list 1, caveat by name 2.
- Each attempt with its real rate headers is in `docs/specs/samples/dc/dc_probe_calls_2026-11-03.json`.

## What worked
- **Access works.** The subscription covers the `dc-*` APIs. The same token, `dept_id`, encryption and signing work as for the High Court.
- **Assam is state code 18** in the District Court state master.
- **34 districts.** Court complexes were read for three districts: Kamrup Metro (9 complexes, 12 establishments), Nagaon (2 and 7) and Majuli (1 and 5).
- **Court rooms of `ASKM01`.** The District and Sessions Judge establishment in Kamrup Metro has 9 court rooms, numbered 1, 2, 4, 19, 21, 22, 23, 24 and 25.
- **Cause lists of 3 Nov 2026, court 1 of `ASKM01`.** The civil list has 17 cases and the criminal list 11. Every row carries the case's **CNR (`cino`)** and `est_code`. Criminal rows also carry the police station name, FIR number and year, and `uniform_code`.
- **One case followed through.** For the listed case `ASKM010024792023` (L A Reference Case 49/2023, against the Deputy Commissioner, Kamrup Metro), the full record, current status and show business all answered. Order 6 of a second listed case, `ASKM010028022019`, came back as a 2-page PDF.
- **Advocate cause list.** For bar number `AS-270-2014`, taken from the first record, it answered with 4 cases, all on the civil list.
- **Caveat search by name.** For `ASKM01` it answered "no record" (628), delivered as HTTP 400 with an encrypted status body.

## The safety check and the deviation
- **Why the safety check failed before any call.** `napix_window.readings` (`backend/aslms/services/napix_window.py:233-244`) reads every `napix_call_log` row that has `rate_limit_remaining`, whatever the API. A District Court count would therefore have been taken as a High Court reading. `detect` and `assess` (lines 154-227) would have produced a false reset and a wrong remaining count, and the runner seeds and re-reads its budget from that count (`backend/aslms/services/runner.py:204-213` and `:259-267`). So would the court-search guard (`backend/aslms/services/court_search.py:204`).
- **The deviation (owner-approved, one-off, 3 Nov 2026).** The probe wrote the District Court rows with `rate_limit_remaining` NULL. The reason is that the window code does not yet separate the two allowances. The fix is a separate backlog row, which the main session is adding. The real header values were kept in the probe's own output.
- **The column nulled.** `napix_call_log.rate_limit_remaining` is the only rate figure the recorder stores (`backend/aslms/services/napix_store.py:139-160`; the model is `backend/aslms/domain/ops.py:108`). The table has no column for the rate limit itself.
- **Readers checked, all left harmless by the workaround:**
  - `napix_window.readings` (`napix_window.py:238-240`) filters on `rate_limit_remaining IS NOT NULL`, so it ignores the rows.
  - `data_load.hourly_limit` (`backend/aslms/services/data_load.py:1216-1224`) takes `max(rate_limit_remaining)` over non-NULL values only. It is a display and plan figure, read at `data_load.py:1332`, `data_load.py:1498` and `backend/aslms/services/collect.py:164-176`, and none of those steers the worker or the guard.
  - `calls_since` (`napix_window.py:260-280`) counts every row, so the 17 calls show in the "outside the queue" totals on the console and health screens (`backend/aslms/services/data_health.py:93`, `data_load.py:1062`, `data_load.py:1463`). Display only.
  - The one steering reader of `calls_since` is the discovery share (`backend/aslms/services/discovery.py:817-824`, read by the runner at `runner.py:195-199`). It takes only the `discovery` lane, and the probe's rows have no lane.
  - `by_user` (`napix_window.py:283-300`, `data_health.py:181-182`) counts only rows with a user, and the probe's rows have none.
  - The runner's own `recorder.last_remaining` comes only from its own calls (`napix_store.py:84-85`).
- **After the run.** A read-only query found 0 District Court rows with a remaining count, and the High Court window still reported `current` with remaining 90.

## Is the allowance separate?
**Yes.** Both headers use the same policy name (`X-RateLimit-Limit: name=default,1000;`), but the counts are separate. The District Court remaining count fell one per call, from 998 to 982. Over the same minutes the latest High Court reading in `napix_call_log` stayed at 90 (`hc-caveat-name-api/caveatname` at 16:00:41 IST, read at 16:02:13, 16:04:06 and 16:04:45 IST). With a shared allowance, the District Court count could not have been above 90. No other rate header was seen. Failed calls count too.

## Main differences from the specification
- **District codes** are 3 digits (300–739); the spec says 2.
- **Cause-list rows** carry `cino` and `est_code`, and criminal rows carry `uniform_code`, `police_st_name`, `fir_no` and `fir_year`. None of these is in the spec. The spec's `time_slot` and `ias` did not appear.
- **Wrapper keys:** Court List answers are wrapped in `court`, and Current Status uses `cases1` where the spec has `case1`.
- **The advocate cause list** does not return the spec's `court_no`, `jo_code`, `judge_name`, `desgname` or `desg_code`. It accepted the bar number in the court record's form, `AS-270-2014`.
- **The CNR record** has 11 keys the spec does not list, among them `ci_cri`, `case_type_id`, `state_code`, `district_code`, the three `hide_*` flags and `order_judge_name`.
- **`response_token`** did not match on any of the 14 answers. High Court JSON answers do verify.
- **"No record" (628)** came as HTTP 400 with an encrypted status body. Today's client treats any non-200 as a protocol error before reading the body.

## Field coverage needed later (first pass; the architect owns the full coverage table)
The High Court schema (`docs/schema/schema.md`) has no home for:
- **Court room number:** `court_no`, on the case, the listing and the court list.
- **Civil or criminal flag:** `ci_cri`.
- **The district-court hierarchy:** District Court districts (their own numbering), court complexes, establishments (`est_code`, about 250 of them) and their court rooms (`court_no`, `desgname`, `judge_name`). `courts` and `benches` model the High Court only.
- **Criminal-case keys:** `police_st_code` and `police_st_name`, and `uniform_code`. `cases` already has `fir_no`, `fir_year` and a `police_station` text.
- **Cause-list rows as JSON**, replacing the PDF the High Court sends: `sr_no`, `case_number`, `cause_title`, `main_advocate_names`, `purpose_name`, `urgent`, `time_slot`, `ias`.
- **Advocate codes and bar numbers:** `pet_adv_cd`, `res_adv_cd`, `pet_adv_bar_reg`, `res_adv_bar_reg`.
- **Masking flags:** `hide_pet_name`, `hide_res_name`, `hide_partyname_est`.
- **Process details:** `processes.process_id`, `process_date`, `process_title`.
- **Order judge:** `order_judge_name` on orders.
- **Other record fields:** `objections`, `pet_legal_heir` and `res_legal_heir`, `goshwara_no`, `main_matter_cino`, the lower-court fields.
- **Caveat fields** (not yet seen live).

## Estimate of daily calls for every Assam cause list, civil and criminal
This is an estimate, not a count.
- **Establishments:** about 250, from 8 per district on average across the three districts sampled.
- **Court rooms:** 9 in the one establishment listed. If establishments average 2 to 4 rooms, Assam has **about 500 to 1,000 court rooms**.
- **Daily cause-list calls:** one civil and one criminal call per room per working day is **about 1,000 to 2,000 calls a day**, or 1 to 2 hours of the separate 1,000-an-hour allowance. An empty list (a criminal call to a civil-only court, for example) is expected to answer 628 and still counts.
- **Court lists:** keeping court rooms current takes one court-list call per establishment (about 250) whenever lists are refreshed. One court-complex call per district (34) would replace the estimate with exact counts.
- **CNRs come with the list.** The cause list gives each case's CNR, so no case-number search or PDF parsing is needed. Full records would be fetched only for cases that match a department.
- **Cheaper alternative:** the advocate cause list costs one call per government advocate per establishment per day. It needs the owner's list of government advocates and their bar numbers (row 222 already notes this need).

## Open questions for the owner
1. **Overview's allowance.** Overview has the same path for both courts and is the High Court window's probe. It was not called. Which allowance it counts against is open; the separate backlog row that splits the window should settle it.
2. **The District Court reset.** The reset minute was not observed. The first call already read 998, not 999. Does anything outside ASLMS use the subscription for District Court calls?
3. **Scope of establishments.** Should the plan cover all of about 250, or only some? The lists include tribunals and special courts: MACT, Family Court, Industrial Tribunal, Labour Court, the Railway Magistrate and the CBI court.
4. **Government advocates' bar numbers per district.** The advocate cause list works with the court's bar-number form, so this list would make it the cheapest daily route.
5. **Later client work, before any build (design decisions).** Decrypt the status of HTTP 400 answers (628 arrives that way), and decide how to treat the `response_token` mismatch on every District Court answer.
6. **A data quirk.** Majuli's court complex lists its CJM as `ASJR06`, with Jorhat's prefix. Establishments may sit under another district's code.

## Deviations
- The owner-approved NULL `rate_limit_remaining` on the District Court rows, described above.
- The samples are in `docs/specs/samples/dc/`, a subfolder, rather than directly in `docs/specs/samples/`. Two High Court tests take every `*.json` directly in that folder and would fail on District Court files: `tests/unit/test_napix_inspect.py:62` and `tests/unit/test_system_health.py:130-149`. With the subfolder, both pass: 114 passed, 1 skipped.
