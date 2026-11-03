# NAPIX High Court API — Integration Notes (verified by live tests)

Last updated: 2026-11-03 (the two caveat APIs verified live, row 223; the District Court APIs added in §10, 11 `dc-*` APIs called live, row 222); 2026-10-01 (live run of `aslms napix-check`, 14 APIs verified). Source: live calls from Postman and from the backend against the NAPIX gateway, plus the High Court Open API Specification v1.0 (`docs/specs/`). Where this file and the spec PDF disagree, **this file wins**: it records what the live service actually accepted.

Status legend: ✅ verified live · ⚠️ from the spec, not yet verified live

## 1. Credentials (all from `.env`, never committed)

| Variable | Meaning |
|---|---|
| `NAPIX_CLIENT_ID` | NAPIX subscriber application client ID (Basic Auth username for the token call) |
| `NAPIX_CLIENT_SECRET` | NAPIX subscriber application client secret (Basic Auth password) |
| `NAPIX_DEPT_ID` | Department ID = subscriber user name, sent as `dept_id` |
| `NAPIX_AUTH_KEY` | Authentication key from the e-Committee / High Court, used for AES (key and IV) |
| `NAPIX_HASH_KEY` | `15081947` (fixed, published in the spec) |
| `NAPIX_BASE_URL` | `https://delhigw.napix.gov.in/nic/ecourts` |
| `NAPIX_EST_CODE` | `GAHC01` (Gauhati High Court, Principal Seat) ✅; the bench master also lists `GAHC02` Kohima, `GAHC03` Aizawl, `GAHC04` Itanagar |
| `NAPIX_STATE_CODE` | `18` = Gauhati High Court in the NAPIX state master ✅ (`6` is Chhattisgarh: the bench and district masters return the wrong court with it) |
| `NAPIX_VERSION` | `v1.0` |
| `NAPIX_ENABLED` | master switch, `false` by default; set only for a live run |

## 2. Access token ✅
- `POST {BASE_URL}/oauth2/token`
- Basic Auth: client ID / client secret.
- Body `application/x-www-form-urlencoded`: `grant_type=client_credentials`, `scope=napix`.
- Response JSON has `access_token`, `token_type` (`Bearer`), `scope`, `consented_on` and `expires_in` = 3600 ✅. Send it on every API call as `Authorization: Bearer <token>`.
- The token lasts an hour; on HTTP 401 fetch a new one and retry once. Cache it and reuse it until it expires (the backend keeps one per process and mirrors it in Redis).

## 3. Building a request ✅
1. **Input string**: `key=value` pairs joined with `|`, in the exact order the spec lists for that API. No spaces. Example: `est_code=GAHC01|causelist_date=2026-09-24`.
2. **Key normalisation (critical)**: take the auth key (trimmed), encode UTF-8, then **cut to exactly 16 bytes, or pad with zero bytes to 16**. AES-128 requires 16 bytes and the server does this; without it, some libraries switch to AES-192/256 and every call fails with 626 INVALID_TOKEN.
3. **request_str**: AES-128-CBC, key = normalised key, **IV = the same 16 bytes**, PKCS7 padding, output Base64.
   - GET: URL-encode the Base64 value (`+` → `%2B`, `/` → `%2F`, `=` → `%3D`).
   - POST (Current Status) ✅: the four parameters go in the **query string exactly as for GET**. A form body or a JSON body is answered by the gateway with 400 "One or more required API parameters are missing"; GET on the POST path gives 405.
   - **APIs with no input (Overview, masters)**: encrypt the empty string and send that. A blank `request_str` was rejected with 626.
4. **request_token**: HMAC-SHA256 of the **plain input string** (not the encrypted one), key `15081947`, lowercase hex.
   - Test vector: input `""` → `6d1c982a5a21d89d2556c5e5ffb7c9e661a7c549512b1dfd6f055d8d78161fd4` ✅
5. Query parameters on every call: `dept_id`, `request_str`, `request_token`, `version`.

## 4. Reading a response ✅
- The server returns `Content-Type: text/html` even for JSON. Parse the body text as JSON yourself; be tolerant of extra text around the JSON (take the first `{` to the last `}`).
- Success: `{"response_str": "...", "response_token": "...", "version": "v1.0"}`.
  - Decrypt `response_str`: Base64-decode, AES-128-CBC with the same normalised key and IV, PKCS7, then UTF-8 → JSON.
  - Treat the Base64 strictly as raw ciphertext (no OpenSSL "Salted__" handling).
  - Integrity: HMAC-SHA256 of the decrypted JSON text with `15081947` should equal `response_token`. Log a warning on mismatch; do not crash.
- Collections in responses are objects keyed `case1`, `case2`, … (or `sr_no1`, `casetype1`, `district1`, `state1`, `act1`, `cases1`), **not arrays**. Convert to lists in order; the keys are not always in order (`state14` before `state2`), so sort by the number.
- PDFs (Show Cause List ✅, Show Order ✅) arrive as a **JSON string of Base64 inside `response_str`** (`"JVBERi0…"`), not as `application/pdf`: decrypt, JSON-parse the string, Base64-decode, check the `%PDF` prefix. Show Order's `response_token` did not match the decrypted text once (logged, not fatal).
- The gateway can answer HTTP 500 "URL Open error" for a correct call (Search by CNR, three times in a row, fine a minute later): transient, retry with back-off.

- **PDF responses fail the `response_token` check** (observed on every Show Cause List call of the 1 Oct load run):
  the HMAC the gateway sends does not match the decrypted JSON string, presumably because it is computed over
  the raw Base64 rather than the quoted string. The client logs the mismatch and keeps the PDF
  (`token_verified = false` in `napix_call_log`); JSON responses verify as before.
  - 21 Oct 2026: in 24 hours of the load, all 20,287 Show Order answers failed the check and every JSON API verified
    (about 900 calls). The client now also accepts a signature over the unquoted Base64 or over the encrypted
    `response_str`. The worker log will show whether either form matches: `token_verified` turns true for Show Order
    if so. A mismatch is still recorded on every call, but warned at most once per API every 10 minutes, with the
    count since the last warning.

## 5. Error formats seen live ✅
| What comes back | Meaning |
|---|---|
| PHP `print_r` text: `Array ( [status_code] => 626 [status] => INVALID_TOKEN )` | eCourts backend error (not JSON). Parse `status_code` and `status` from the text. |
| JSON `{"status": "<Base64>"}` | Encrypted error/status message from the backend. Decrypt it like `response_str`. |
| JSON `{"httpCode":"404","httpMessage":"Not Found","moreInformation":"No resources match requested URI"}` | NAPIX gateway: wrong URL path (or API not subscribed). Request never reached eCourts. |
| HTTP 401 | Access token missing or expired. |
| HTTP 200 with an empty body (hc-cnr-api, in runs of minutes to hours; 9,668 times between 18 Sep and 18 Oct 2026; the next call fails too in 89 % of cases, a median 0.57 s later) | Gateway fault. Treat as unavailable (`NapixEmptyResponse`), do not retry immediately, back off at the queue (retry ladder 10 min, 1 h, 6 h, 24 h, 72 h; the worker pauses after a run of such failures). Evidence: `napix_call_log` (design `safety-fixes`). |

eCourts status codes (spec): 600 INVALID_CNR, 601 INVALID_DATE, 602 INVALID_ORDER_NO, 603 INVALID_EST_CODE, 616 INVALID_CAUSELIST_DATE, 619 INVALID_CAVEAT_PARTY_NAME, 620 INVALID_SEARCH_TYPE (✅ live 3 Nov 2026, an encrypted `{"status_code": "620", "status": "INVALID_SEARCH_TYPE"}`), 623 INVALID_CAVEAT_CODE, 626 INVALID_TOKEN, 627 INVALID_DEPT_ID, 628 RECORD_NOT_FOUND (valid call, no data — not an error for the caller), 629 UNEXPECTED_ERROR (retry with backoff), 632 INVALID_VERSION. The client's `NAPIX_STATUS` names do not yet include 619, 620 and 623 (it logs them as `UNKNOWN`, with the number and the decrypted body).

## 6. Rate limit ✅
Response headers: `X-RateLimit-Limit: name=default,1000;` and `X-RateLimit-Remaining`. Read them, slow down as remaining approaches zero, and spread scheduled jobs (daily cycle, Current Status batches) accordingly.

**1,000 calls per one-hour window; the reset is at a fixed minute of the hour, not on the clock hour** (corrected
12 Oct 2026, design `napix-window`). The call log of 1-11 Oct (48,830 rows) shows `X-RateLimit-Remaining` jumping
back to 999 once an hour, always between **HH:33 and HH:35 IST** wherever calls were made just before and just after
the reset (11 Oct: 00:34:28, 02:34:53, 04:34:30, 10:33:30, 12:34:30, 14:33:27, 16:34:53, 18:33:28). That is neither
the IST clock hour nor the UTC clock hour (HH:30 IST). The window is therefore **detected from
`X-RateLimit-Remaining`, never assumed**: a rise of at least `NAPIX_WINDOW_RESET_JUMP` (50) between two readings is a
reset, precise when the previous reading is at most 300 s older; the phase comes from the latest precise reset
(`services/napix_window.py`). The worker sleeps until the expected reset plus `NAPIX_WINDOW_MARGIN_SECONDS` (60 s) and
makes one check call (Overview) at most every `NAPIX_WINDOW_PROBE_SECONDS` (180 s) while a reset is late or the timing
is unknown. Inside a window the count sometimes rises by 1-2 (concurrent calls, and before 0015 one timestamp per
queue item); only a large jump is a reset.

The 1 Oct measurement (`aslms napix-probe-rate --calls 36 --interval 20`, 13:08-13:20 IST) saw no reset in 12 minutes
and concluded "reset on the hour"; the reset came at about 13:34, after the probe had ended. Sleeping to the next clock
hour lost every second window (about 240 calls instead of about 850). `NAPIX_RATE_WINDOW_SECONDS=3600` stays the
window *length*; the load queue keeps `NAPIX_RATE_RESERVE` calls for the daily cycle. If e-Committee grants a higher
plan, only the settings change.

Evidence query (the resets of a day, IST):

```sql
SELECT called_at AT TIME ZONE 'Asia/Kolkata' AS at, prev, rate_limit_remaining
FROM (SELECT called_at, rate_limit_remaining,
             lag(rate_limit_remaining) OVER (ORDER BY called_at, id) AS prev
      FROM napix_call_log
      WHERE rate_limit_remaining IS NOT NULL
        AND called_at >= '2026-10-11 00:00+05:30' AND called_at < '2026-10-12 00:00+05:30') t
WHERE rate_limit_remaining - prev >= 50
ORDER BY called_at;
```

## 7. Endpoints
**URL pattern ✅**: service names use hyphens as in the spec's API list (`hc-…-api`). The detailed spec sections drop hyphens at line breaks — ignore those spellings. Paths are case-sensitive.

| API | Method + path (after BASE_URL) | Input string (exact order) | Status |
|---|---|---|---|
| Overview | GET `/overview/overview` | *(empty, encrypted)* | ✅ |
| State master | GET `/hc-state-api/state` | *(empty)* | ✅ `state{n}.state_code, state_name` (High Courts; 18 = Gauhati) |
| District master | GET `/hc-district-api/district` | `state_code` | ✅ `district{n}.dist_code, dist_name` (40 rows for 18, in eCourts spellings: `Kamrup(M)`, `Sibsagar`, `Karimganj`; plus `CBI`, `NIA`, `C/O 99 APO`) |
| Bench master | GET `/hc-bench-master-api/bench` | `state_code` | ✅ `benches.sr_no{n}.bench_id, bench_name, est_code` (4 benches) |
| Case Type master | GET `/hc-case-type-master-api/casetypemaster` | `est_code` | ✅ `casetype{n}.case_type, type_name` (222 rows, `"WA : Writ Appeal"` form) |
| Act master | GET `/hc-act-master-api/actMaster` | *(empty)* | ✅ `act{n}.national_act_code, actname` (4,677 rows) |
| Cause List Bench | GET `/hc-causelist-bench-api/causelistbench` | `est_code|causelist_date` | ✅ `case{n}.bench_id, judge_name` |
| Cause List Details | GET `/hc-causelist-details-api/causelistdetails` | `est_code|causelist_date|bench_id` | ✅ **list metadata, not case rows**: `case{n}.bench, bench_id, causelist_id, cause_list_type` (one row per list the bench published; `cause_list_type` is space-padded) |
| Show Cause List | GET `/hc-show-causelist-api/showcauselist` | `est_code|bench_id|causelist_id|causelist_date` | ✅ the list PDF as a Base64 JSON string (280 KB for a Lawazima list) |
| Search by CNR | GET `/hc-cnr-api/CNR` | `cino` | ✅ the full dossier (70 field paths; `/hc-cnr-api/cnr` is a gateway 404) |
| Current Status | POST `/hc-current-status-api/currentStatus` **with the parameters in the query string** | `cino` (comma-separated; the spec says max 500 but **the gateway refuses more than ~300**: live probe 7 Oct 2026, 300 ok, 350 → HTTP 414 URI too long, 400–500 → HTTP 405; `NAPIX_STATUS_BATCH=250`) | ✅ `cases{n}.…` one block per CNR (24 fields) |
| Show Order | GET `/hc-order-api/order` | `cino|order_no|order_date` | ✅ the order PDF as a Base64 JSON string |
| Show Business | GET `/hc-show-business-api/showBusiness` | `cino|business_date` | ✅ `desgname, case_number, business_date, business, short_order_det` |
| Search by Case Number | GET `/hc-case-search-api/casesearch` | `est_code|case_type|reg_no|reg_year` (`case_type` = the master's numeric code, `case_type_id` in a dossier) | ✅ `establishment_name, casenos.case{n}.…` |
| Search by Party Name | GET `/hc-party-name-api/partyname` | `est_code|pend_disp|litigant_name|reg_year` (`pend_disp` must match the case: `P` does not find a disposed case; **`reg_year` is mandatory**: blank gives `606 INVALID_REG_YEAR`, so a name is searched one registration year per call; `litigant_name` is matched as the **whole phrase** in the petitioner or respondent name, live 14 Oct 2026) | ✅ `establishment_name, casenos.case{n}.…` |
| Search by Advocate Name | GET `/hc-advocate-name-api/advocatename` | `est_code|pend_disp|advocate_name|reg_year` (**`reg_year` is mandatory**: blank gives `606 INVALID_REG_YEAR`; the honorific does not matter (`MR. P J SAIKIA` and `P J SAIKIA` give the same rows); the court matches **part of a name** (`SAIKIA` alone gives 325 CNRs including all 36), live 18 Oct 2026) | ✅ `establishment_name, casenos.case{n}.cino, type_name, reg_no, reg_year, pet_name, res_name` (a row may repeat a CNR; masked names `XXXXXXX` in matrimonial cases) |
| Search by Filing Number | GET `/hc-filing-api/Filing` | `est_code|case_type|fil_no|fil_year` (`case_type` = the master's numeric code) | ✅ `establishment_name, casenos.case{n}.cino, type_name, fil_no, fil_year, pet_name, res_name` (no `reg_no` / `reg_year`, live 18 Oct 2026) |
| Caveat Search by Name | GET `/hc-caveat-name-api/caveatname` | `est_code|caveat_party_name|search_type` (no year; the spec's request string prints the last item as a bare `search_type`, the server takes `search_type=A` or `S`; left out → `620 INVALID_SEARCH_TYPE`; **only the caveator's name is searched** (a word found only in the caveatee gives 628) and a multi-word phrase matches inside it; `A` and `S` gave the same 32 rows for `ASSAM`, every match having the text at the start of a word; the answers held only caveats filed in the last ~11 weeks, live 3 Nov 2026) | ✅ `caveat.caveat{n}.caveat_no, caveat_year, matched_case_no, caveat_filing_date, caveator_caveatee_details, caveat_code` (`matched_case_no` is `""` until the anticipated case is filed, then the case number, e.g. `WP(C)/4688/2026`; `caveator_caveatee_details` is one text `CAVEATOR VS CAVEATEE`; `caveat_code` 15 digits, no masking seen) |
| Caveat Details (spec: Caveat History) | GET `/hc-caveat-details-api/caveatdetails` | `est_code|caveat_code` (the code from a Caveat Search answer) | ✅ `caveat_details.caveat_no` (7-digit zero-padded), `caveat_year`, `cnr_no` (**the caveat's own filing reference** `GAHC01-C00936-2026`, not the matched case's CNR as the spec says), `subject` (the impugned order and the lower case, free text), `caveat_filing_date`, `time_of_filing`, `matched_case_no` (**key absent** when there is no match, unlike the search's `""`); `caveator_details.caveator_name, caveator_add`; `caveatee_details.caveatee_name, caveatee_add` (addresses empty in both samples); `extra_party_caveator` / `extra_party_caveatee` blocks of the spec absent when there are none (not seen live) |
| Search by Act, Advocate Bar Reg, Neutral Citation | stubs in `docs/specs/napix/hc/` | | ⚠️ not needed yet |

Dates are `yyyy-mm-dd`. Update the Status column (and this file) whenever an endpoint is verified live, and save a decrypted sample to `docs/specs/samples/<api>_<date>.json` (no credentials in samples).

## 8. Observed data notes
- Cause List Bench returns judges' benches **and** registrars' benches (Joint Registrar, Deputy Registrar, Officer on Special Duty). `bench_id` is an integer; `judge_name` may list two judges for a division bench.
- **Past dates are served** ✅ (1 Oct): Cause List Bench, Details and Show Cause List answered for 2025-01-06 (22 benches)
  and 2025-06-02 (24 benches), so the historical load from January 2025 can run through NAPIX.
- **Show Cause List is per bench**: the PDF for (bench_id, causelist_id, date) contains only that bench's portion
  (bench 2048's Lawazima for 2025-01-06: 2 pages, 1 court; the website's Lawazima PDF for the day: 6 pages, all
  registrar benches). Two benches may report the same `causelist_id` (1008 = Lawazima); the key is (bench_id, causelist_id).
- Bench list has no `causelist_id`; it comes from Cause List Details, which also gives `cause_list_type` (`LAWAZIMA`, …). Cause List Details does **not** return case entries, so the cause-list PDF (Show Cause List) remains the source of entries and the parser stays primary.
- The full field list of every verified response is in `docs/specs/napix_field_inventory.md` (generated by `aslms napix-fields` from `docs/specs/samples/`).

## 9. Open questions
- ~~Does Cause List Details return complete entries?~~ No (1 Oct): list metadata only; the PDF parser is primary.
- ~~Exact CNR path casing; Party Name and master endpoint paths.~~ Settled (1 Oct): `/CNR`, `/partyname`, masters as in §7.
- ~~Token lifetime~~ 3600 s (1 Oct). ~~Rate-limit window length~~ Settled (12 Oct, design `napix-window`): one hour,
  1,000 calls, reset at a fixed minute of the hour (HH:33-HH:35 IST from 1 to 11 Oct), detected from
  `X-RateLimit-Remaining` (§6).
- A dossier for a **pending** case with IAs and objections has not been sampled yet (the sample case `GAHC010277142024` is disposed); needed before the field inventory is called complete.


**Search by Party Name, live check of 14 Oct 2026** (department-discovery, owner-approved budget of 10 calls, 4 used, all in `napix_call_log`): `litigant_name=NARAYAN KONWAR`, `pend_disp=P`. Blank `reg_year` → `NapixInputError 606 INVALID_REG_YEAR` (the year cannot be left out). `reg_year=2025` → 52 rows, `reg_year=2026` → 103 rows; every 2025 row holds the full phrase "NARAYAN KONWAR" in `pet_name`/`res_name` (typically `res_name` "NARAYAN KONWAR, IAS AND 2 ORS."), all of type `Cont.Cas(C)` or `I.A.(Civil)`; 16 of the 52 CNRs were already held. Row keys: `case_type_id, cino, pet_name, police_st_code, reg_no, reg_year, res_name, type_name, uniform_code`; every row's `reg_year` equals the year asked for.

**Search by Advocate Name and by Filing Number, live probe of 18 Oct 2026** (design `search-court-advocate-filing`, owner-approved budget of 10 calls, 5 used, all in `napix_call_log`; samples `advocate_name_2026-10-18-p1..p4.json`, `filing_2026-10-18-p5.json`). Advocate: `advocate_name=MR. P J SAIKIA`, `reg_year=2025`, `pend_disp=P` → 36 rows (P1); blank `reg_year` → `606 INVALID_REG_YEAR` (P2, the year cannot be left out); `P J SAIKIA` without the honorific → the same 36 rows (P3); `SAIKIA` alone → 331 rows, 325 distinct CNRs including all 36 (P4: part of a name matches, unlike the party search). Row keys `cino, pet_name, reg_no, reg_year, res_name, type_name` (no `case_type_id`, `police_st_code` or `uniform_code`, unlike the party rows). Filing: `case_type=111` (WP(C)), `fil_no=6780`, `fil_year=2025` → 1 row, `GAHC010118832025`, the held case (P5); row keys `cino, type_name, fil_no, fil_year, pet_name, res_name`. A held case not yet registered (P6) was not probed: the dev database holds none.

**Caveat Search by Name and Caveat Details, live check of 3 Nov 2026** (backlog row 223 `caveat-live-check`, owner-approved budget of 10 calls, 9 used, all in `napix_call_log` between 10:28:21 and 10:30:41 UTC; `X-RateLimit-Limit` 1000, `X-RateLimit-Remaining` falling one per call from 98 to 90; no token renewal recorded; probe `backend/tools/caveat_probe.py` with automatic retries off; samples in `docs/specs/samples/caveat/`, kept out of the top folder because `aslms napix-fields` and two unit tests read every top-level sample and caveat fields have no schema home yet; report `docs/reports/2026-11-03-caveat-live-check.md`). At `GAHC01`: `STATE OF ASSAM` (A) → 628; `ASSAM` (A) → 32 caveats filed 19 Aug to 15 Oct 2026, 6 with a `matched_case_no` (sample `caveat_name_2026-11-03.json`); `ASSAM` (S) → the same 32 rows; `EDIFICE` (a word only in a caveatee) → 628; `COMMISSIONER AND SECRETARY` (A) → 11 caveats filed 1 to 9 Oct 2026 with the Government as caveator (`caveat_name_2026-11-03-b.json`); `DEPUTY COMMISSIONER` (A) → 628; `search_type` left out → 620. Caveat Details for `117800009342026` (matched to `WA/326/2026`; `caveat_details_2026-11-03.json`) and `117800010932026` (the State as caveatee, no match; `caveat_details_2026-11-03-b.json`). Not settled: whether the court serves only live caveats (a caveat lapses after 90 days; every answer fell inside the last 11 weeks while caveat numbers 1 to 903 of 2026 never appeared), and whether `S` differs from `A` for text found in the middle of a word.

## 10. District Court APIs (`dc-*`), live check of 3 Nov 2026

Backlog row 222 `district-court-live-check`. Run with `backend/tools/dc_probe.py`, 17 calls between 16:02:13 and 16:04:45 IST, one at a time, all through `NapixClient.call` and all in `napix_call_log` (17 rows, 14 ok) with each JSON answer in `napix_responses` (13 rows). Decrypted samples: `docs/specs/samples/dc/` (a subfolder, so that the High Court sample tests, which take every `*.json` directly in `docs/specs/samples/`, are not affected). Each attempt with its rate headers: `docs/specs/samples/dc/dc_probe_calls_2026-11-03.json`. Report: `docs/reports/2026-11-03-district-court-live-check.md`. Specification: `docs/specs/pdf/eCourts_Open_API_Specifications_NAPIX_1.3_22.04.2025-1-1-1.pdf`; gateway stubs: `docs/specs/napix/dc/`.

**Owner-approved, one-off deviation:** the 17 District Court rows have `rate_limit_remaining` NULL. The quota-window code (`services/napix_window.py`, `readings`) does not yet tell the two allowances apart and would have read a District Court count as a High Court reading. The real header values are in the probe's output file. A separate backlog row separates the allowances.

### 10.1 Access, sign-in and encryption ✅
- The subscription covers the `dc-*` APIs. The same base URL, `dept_id`, access token, AES-128-CBC envelope, HMAC request token and `version=v1.0` work as for the High Court. No token request was needed: the token the High Court worker already held (shared through Redis) was accepted.
- Paths are the stubs' `basePath` plus path, case-sensitive: CNR is **`/dc-cnr-api/cnr`** (lower case, unlike the High Court's `/CNR`). The order API's path really is spelt **`dc-oreder-api/order`**.
- Current Status is a POST with the four parameters in the query string, as for the High Court (§3).
- **`response_token` never matched** (14 of 14 answers, JSON and PDF alike; High Court JSON answers verify). The client logs it and keeps the answer (`token_verified = false`).

### 10.2 Rate limit ✅ (separate from the High Court's)
- Headers on every answer, failures included: `X-RateLimit-Limit: name=default,1000;` and `X-RateLimit-Remaining: name=default,<n>;`. This is the same policy name (`default`) and format as the High Court, but **a separate count**. Across the 17 calls the District Court count went down one per call, 998 → 982. Over the same minutes the High Court's latest reading in `napix_call_log` stayed at 90 (`hc-caveat-name-api/caveatname` at 16:00:41 IST, read at 16:02:13 and again at 16:04:06 and 16:04:45 IST).
- Every attempt counts, including an HTTP 500 and an HTTP 400. No `Retry-After` or other rate header was seen.
- The first call already read 998, not 999. Either one District Court call outside ASLMS (none is in our log) came earlier in that window, or the count does not start at 999. The window's reset minute was not observed (all calls fell inside 2.5 minutes).
- Overview (`/overview/overview`, the same path in the District Court spec) was **not** called. Its path is shared with the High Court window probe, so it is not known which allowance it counts against.

### 10.3 Endpoints

| API | Method + path | Input string (exact order) | Status and fields returned |
|---|---|---|---|
| State master | GET `/dc-state-api/state` | *(empty)* | ✅ `state.state{n}.state_code` (int), `state_name`; 36 rows; **Assam = 18** (the High Court master's 18 is the Gauhati High Court; Haryana is 6 here) |
| District master | GET `/dc-district-api/district` | `state_code` | ✅ `district.district{n}.dist_code` (int, **3 digits**, 300–739; the spec says 2 digits), `dist_name`; **34 districts for Assam**. Spellings and numbering differ from the High Court district master: `Kamrup Metro` 322, `Sribhumi` 317, `Sivasagar` 311, `Bajali` 739. No `Tamulpur` row. |
| Court Complex | GET `/dc-court-complex-api/courtComplex` | `state_code\|dist_code` | ✅ flat `complex{n}.court_complex_name`, `complex{n}.establishment{n}.est_code`, `court_est_name` (no wrapper key) |
| Court List | GET `/dc-court-list-api/courtList` | `est_code` | ✅ `court.court{n}.court_no` (string), `desgname`, `judge_name`. Wrapped in `court`, where the spec's sample shows `court`, `court1`, … unwrapped. Court numbers are not contiguous (ASKM01: 1, 2, 4, 19, 21, 22, 23, 24, 25), one judge holds two courts, and names have runs of spaces. |
| Cause List | GET `/dc-causelist-api/causelist` | `est_code\|court_no\|causelist_date\|ci_cri` (`ci_cri` 2 = civil, 3 = criminal) | ✅ top-level `desgname`, `cases.case{n}`. Civil row keys: `sr_no` (int), `case_number`, `cause_title`, `main_advocate_names`, `purpose_name`, `urgent` (`N`), **`cino`, `est_code`** (not in the spec). Criminal rows add **`uniform_code`** (int), **`police_st_name`**, **`fir_no`**, **`fir_year`** (int) when the case has an FIR (10 of 11 rows); `urgent` is `""`. `time_slot` and `ias` (in the spec) did not appear. The criminal call first answered HTTP 500 in 57 ms; the same call about 1 minute later answered normally. |
| Advocate-wise Cause List | GET `/dc-advocate-causelist-api/advocateCauselist` | `est_code\|advocate_bar_regn_no\|causelist_date` | ✅ `establishment_name`, `casenos.case{n}.cino, type_name, reg_no, reg_year, pet_name, res_name` (4 rows). The spec's `court_no`, `jo_code`, `judge_name`, `desgname` and `desg_code` are **not returned**. The bar number in the form the court record gives, `AS-270-2014`, was accepted (the spec describes `MAH-NNNNNN-YYYY`). |
| Search by CNR | GET `/dc-cnr-api/cnr` | `cino` | ✅ the full record: 85 key paths over two records. Keys not in the spec: `state_code`, `district_code`, `case_type_id`, `ci_cri`, `establishment_name`, `hide_pet_name`, `hide_res_name`, `hide_partyname_est`, `pet_extra_adv`, `res_extra_adv`, `interimorder.sr_no{n}.order_judge_name`. `court_no` is an int here and a string elsewhere; `main_matter_cino` is 16 spaces when empty. Nested: `acts.act{n}`, `historyofcasehearing.sr_no{n}`, `interimorder` / `finalorder.sr_no{n}`, `processes.sr_no{n}`, `pet_extra_party.party_no{n}`, `objections`. The day's business (3 Nov) was already in the history at 16:03 IST. |
| Current Status | POST `/dc-current-status-api/currentStatus` (parameters in the query string) | `cino` (comma-separated per the spec; only one CNR tried) | ✅ `cases1.…` (wrapper key **`cases1`**, the spec says `case1`): 21 fields, the spec's 20 plus `case_type_id`, which was `null` although the record gives 44 |
| Show Business | GET `/dc-show-business-api/showBusiness` | `cino\|business_date` | ✅ `desgname, case_number, business_date, business, short_order_det`. `case_number` is zero-padded (`L A Reference Case/0000049/2023`; the cause list gives `/49/2023`); `business` was `""` for the same day's date |
| Show Order | GET `/dc-oreder-api/order` | `cino\|order_no\|order_date` | ✅ PDF, 103,442 bytes, 2 pages, with a text layer |
| Caveat by name | GET `/dc-caveat-name-api/caveatName` | `est_code\|caveat_party_name\|search_type` | ⚠️ path and input accepted, but only "no record" seen. `STATE OF ASSAM` and `ASSAM` (type `A`) at ASKM01 both answered **HTTP 400 with an encrypted `{"status": …}` body** that decrypts to `{"status_code":"628","status":"RECORD_NOT_FOUND"}`. The client raises `NapixProtocolError` for any non-200 before reading the body, so a District Court client must decrypt the status of an HTTP 400. No caveat fields seen. |
| Case Type master, Police Station master, Act, Search by Case Number / Filing Number / Party / Advocate / FIR, Filing and Registration date lists, Caveat number / details | stubs in `docs/specs/napix/dc/` | | not tried |
| Overview | GET `/overview/overview` | | not tried (shared path, §10.2) |

### 10.4 Assam counts seen
- **34 districts** (`dc-district-api`).
- Court complexes and establishments in three districts:
  - Kamrup Metro: 9 complexes, 12 establishments (`ASKM01`–`ASKM05`, `ASKM07`, `ASKM08`, `ASKM12`, and `AS0106`, `AS0109`, `AS0110`, `AS0111` for the CJM, Railway, Industrial Tribunal and Labour Court).
  - Nagaon: 2 complexes, 7 establishments.
  - Majuli: 1 complex, 5 establishments. Its CJM establishment is coded `ASJR06`, with Jorhat's prefix.
- Estimate (not counted): about **8 establishments per district on average in these three** (Kamrup Metro is the largest), so **roughly 200 to 280 establishments in Assam, about 250**. One `dc-court-complex-api` call per district (34 calls) would give the exact number.
- Court rooms: **9 in ASKM01** (District and Sessions Judge with the Additional District and Sessions Judges, the POCSO court, the Exclusive Fast Track Sessions Court and the NDPS court). Other establishments were not listed.
