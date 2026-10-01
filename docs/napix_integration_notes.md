# NAPIX High Court API — Integration Notes (verified by live tests)

Last updated: 2026-10-01 (live run of `aslms napix-check`, 14 APIs verified). Source: live calls from Postman and from the backend against the NAPIX gateway, plus the High Court Open API Specification v1.0 (`docs/specs/`). Where this file and the spec PDF disagree, **this file wins**: it records what the live service actually accepted.

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

## 5. Error formats seen live ✅
| What comes back | Meaning |
|---|---|
| PHP `print_r` text: `Array ( [status_code] => 626 [status] => INVALID_TOKEN )` | eCourts backend error (not JSON). Parse `status_code` and `status` from the text. |
| JSON `{"status": "<Base64>"}` | Encrypted error/status message from the backend. Decrypt it like `response_str`. |
| JSON `{"httpCode":"404","httpMessage":"Not Found","moreInformation":"No resources match requested URI"}` | NAPIX gateway: wrong URL path (or API not subscribed). Request never reached eCourts. |
| HTTP 401 | Access token missing or expired. |

eCourts status codes (spec): 600 INVALID_CNR, 601 INVALID_DATE, 602 INVALID_ORDER_NO, 603 INVALID_EST_CODE, 616 INVALID_CAUSELIST_DATE, 626 INVALID_TOKEN, 627 INVALID_DEPT_ID, 628 RECORD_NOT_FOUND (valid call, no data — not an error for the caller), 629 UNEXPECTED_ERROR (retry with backoff), 632 INVALID_VERSION.

## 6. Rate limit ✅
Response headers: `X-RateLimit-Limit: name=default,1000;` and `X-RateLimit-Remaining`. Read them, slow down as remaining approaches zero, and spread scheduled jobs (daily cycle, Current Status batches) accordingly.

**Window measured 1 Oct 2026** (`aslms napix-probe-rate --calls 36 --interval 20`, 13:08–13:20 IST): the counter fell by exactly one per call (984 → 949) and never reset in 12 minutes. The morning live walk (about 50 calls, 12:20–12:35) was no longer counted at 13:07, when 16 calls left the counter at 984. The quota therefore behaves as **1,000 calls per clock hour, reset on the hour**, not a sliding minute. Settings: `NAPIX_RATE_WINDOW_SECONDS=3600`; the load queue keeps `NAPIX_RATE_RESERVE` calls for the daily cycle. Budget at this plan: about 23,000 calls a day, so the dossier load of ~100,000 cases takes four to five days of continuous running. If e-Committee grants a higher plan, only the two settings change.

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
| Current Status | POST `/hc-current-status-api/currentStatus` **with the parameters in the query string** | `cino` (comma-separated, max 500) | ✅ `cases{n}.…` one block per CNR (24 fields) |
| Show Order | GET `/hc-order-api/order` | `cino|order_no|order_date` | ✅ the order PDF as a Base64 JSON string |
| Show Business | GET `/hc-show-business-api/showBusiness` | `cino|business_date` | ✅ `desgname, case_number, business_date, business, short_order_det` |
| Search by Case Number | GET `/hc-case-search-api/casesearch` | `est_code|case_type|reg_no|reg_year` (`case_type` = the master's numeric code, `case_type_id` in a dossier) | ✅ `establishment_name, casenos.case{n}.…` |
| Search by Party Name | GET `/hc-party-name-api/partyname` | `est_code|pend_disp|litigant_name|reg_year` (`pend_disp` must match the case: `P` does not find a disposed case) | ✅ `establishment_name, casenos.case{n}.…` |
| Search by Advocate / Filing / Act, Advocate Bar Reg, Neutral Citation, Caveat | stubs in `docs/specs/napix/hc/` | | ⚠️ not needed yet |

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
- ~~Token lifetime~~ 3600 s (1 Oct). Rate-limit window: `X-RateLimit-Limit: name=default,1000;`, the window length is still unstated (38 calls in 35 minutes consumed 38 of the remaining count, so it is at least that long).
- A dossier for a **pending** case with IAs and objections has not been sampled yet (the sample case `GAHC010277142024` is disposed); needed before the field inventory is called complete.
