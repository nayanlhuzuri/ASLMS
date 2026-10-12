# NAPIX integration layer — design (1 Oct 2026)

Scope: `backend/aslms/integration/napix/`, the only place that talks to the NAPIX gateway (CLAUDE.md rule).
Basis: `docs/napix_integration_notes.md` (what the live service accepted; it wins over the spec PDFs), the two
decrypted samples in `docs/specs/samples/` and the Postman collection in `docs/postman/`. The layer already
exists (built 25 Sep against the spec and tested offline); this document fixes its target shape and lists what
changes to match the verified behaviour. No code beyond `.env.example` is written with it.

Verified while writing this: the Authentication Key now in `.env` decrypts both saved samples and their
`response_token` verifies (Overview: the API description; Cause List Bench 2026-09-03: 18 benches, `case1…case18`),
and the notes' empty-input test vector `HMAC("") = 6d1c982a…1fd4` reproduces. The crypto in `crypto.py` is right.

## 1. Modules and classes

```
integration/napix/
  crypto.py     NapixCrypto(auth_key, hash_key)      key normalisation, encrypt / decrypt, HMAC token, self-test
  client.py     NapixClient                           token cache, envelope, errors, retries, rate limit, call hook
                NapixResult                           one HTTP attempt (what napix_call_log stores)
                TokenCache                            process-wide token, shared through Redis when configured
                RateLimiter                           local sliding window + the gateway's X-RateLimit headers
                nested_list()                         {"case1": …} → list
  hc.py         NapixHighCourt(CourtSource)           one typed method per High Court API, maps to dataclasses
                parse_case_record()                   pure mapping of the CNR dossier (tested with recorded samples)
  dc.py         (Phase 3) the same for district courts, behind the same CourtSource protocol
integration/factory.py   napix_source() builds the client from settings; CallRecorder writes napix_call_log
cli/napix_check.py       `aslms napix-check`: walks the APIs live, saves decrypted samples, updates the notes' status
```
Services (`tracking`, `daily_cycle`, `orders`, `search`, `admin.sync_masters`) see only `CourtSource` and typed
dataclasses (`BenchRef`, `CauseListRef`, `CauseListRow`, `CaseRecord`, `StatusRecord`, `OrderRef`); none of them
knows about tokens, encryption or paths.

## 2. Configuration (`.env`, never committed)

| Variable | Value / meaning | Status |
|---|---|---|
| `NAPIX_ENABLED` | master switch, default `false`; nothing calls the gateway until `true` | kept (ground rule) |
| `NAPIX_CLIENT_ID` / `NAPIX_CLIENT_SECRET` | the NAPIX app's Key / Secret; Basic Auth on the token call | notes §1 |
| `NAPIX_DEPT_ID` | subscriber user name, sent as `dept_id` | notes §1 |
| `NAPIX_AUTH_KEY` | Authentication Key from the e-Committee / High Court; AES key and IV | notes §1 |
| `NAPIX_HASH_KEY` | `15081947`, fixed | notes §1 |
| `NAPIX_BASE_URL` | `https://delhigw.napix.gov.in/nic/ecourts` | notes §1 (was `NAPIX_BASE`) |
| `NAPIX_EST_CODE` | `GAHC01` | notes §1 (was `NAPIX_HC_EST_CODE`) |
| `NAPIX_VERSION` | `v1.0` | notes §1 |
| `NAPIX_STATE_CODE` | `6` (Assam), for the State-keyed masters | optional, default 6 |
| `NAPIX_RATE_LIMIT_PER_MIN` | local ceiling, default 60; the gateway's own limit is read from headers | optional |
| `NAPIX_RATE_WINDOW_SECONDS` | the quota window's length, default 3600; the phase is detected (design `napix-window`) | notes §6 |
| `NAPIX_WINDOW_MARGIN_SECONDS` | wait this long after the expected reset, default 60 (0-600) | design `napix-window` |
| `NAPIX_WINDOW_PROBE_SECONDS` | one check call at most this often while a reset is late or the timing unknown, and the limiter's wait at 0 remaining; default 180 (60-300) | design `napix-window` |
| `NAPIX_WINDOW_RESET_JUMP` | a rise of at least this many remaining calls between two readings is a reset, default 50 (10-500) | design `napix-window` |
| `NAPIX_TIMEOUT_SECONDS` | per request, default 40 | optional |
| `NAPIX_TOKEN_TTL_SECONDS` | used only when the token response has no `expires_in`; default 3300 (manual: 1 h) | optional |

Settings keep accepting the old names `NAPIX_BASE` and `NAPIX_HC_EST_CODE` as aliases for one release.
`NAPIX_AUTH_KEY_MODE` (text / hex / base64) is dropped: the live service uses the key as trimmed UTF-8 text.
Secrets are `SecretStr`; logs and `napix-check` show only an 8-character fingerprint of the key.

## 3. Token

- `POST {BASE_URL}//oauth2/token` (the double slash is the Subscriber Manual's form and is what succeeded live),
  Basic Auth Key/Secret, body `grant_type=client_credentials&scope=napix`, `Content-Type:
  application/x-www-form-urlencoded`. Response `access_token`, `expires_in` (1 hour per the manual).
- `TokenCache` holds `(token, expires_at)` once per process (module level, thread-safe) and, when `REDIS_URL` is
  configured, mirrors it under `napix:token` with the remaining TTL so the API, the four workers and the CLI
  share one token instead of each fetching their own. Refresh when fewer than 60 s remain.
- HTTP 401 on a call: drop the cached token (local and Redis), fetch a new one, retry that call once; a second
  401 is `NapixAuthError`.

## 4. Request

`plain = "k1=v1|k2=v2"` in the order the notes' endpoint table gives (it is the HMAC input, so order matters).
`request_str = base64(AES-128-CBC(plain, key = IV = normalised key, PKCS7))`; the key is `trim → UTF-8 → cut or
zero-pad to 16 bytes`. `request_token = hex(HMAC-SHA256(plain, "15081947"))` over the plain text.
APIs with no input encrypt the **empty string** (a blank `request_str` is rejected with 626). GET: the four query
parameters are built by hand with `quote(v, safe="")` so `+ / =` become `%2B %2F %3D`; POST (Current Status)
sends them as a form body. Headers: `Authorization: Bearer <token>` exactly, `Accept: application/json, application/pdf`.
TLS verification stays on (Postman switched it off for the test only).

## 5. Response

1. Ignore `Content-Type` (the backend says `text/html` for JSON). If the body starts with `%PDF` it is a PDF.
2. Parse the text as JSON; if that fails, take the first `{` to the last `}` and parse that; if that fails, look
   for the PHP `print_r` form `[status_code] => NNN` and treat it as an eCourts status; otherwise `NapixProtocolError`.
3. `{"response_str", "response_token", "version"}`: Base64-decode, decrypt, PKCS7-unpad, UTF-8. Compare
   `HMAC(decrypted text)` with `response_token`; on mismatch log a warning and set `token_verified=false`, do not
   fail. Parse the text as JSON; a decrypted PDF (Base64 inside the envelope) is detected by its `%PDF` prefix.
4. `{"status": "<Base64>"}`: decrypt it the same way; the result carries `status` / `status_code` → map as in §6.
5. `{"httpCode", "httpMessage", "moreInformation"}`: a gateway answer, the request never reached eCourts →
   `NapixGatewayError` (wrong path or product not subscribed). `hc-cnr-api/CNR` falls back to `/cnr` once on this.
6. Collections are objects keyed `case1…`, `sr_no1…`; `nested_list()` returns them in numeric order.
Every attempt produces one `NapixResult` (api, params hash, HTTP status, eCourts status, duration, ok, error,
token_verified) handed to the `on_call` hook; the service layer writes it to `napix_call_log` (ground rule 7).

## 6. Errors (all subclass `IntegrationError`; services catch by family, never by code)

| Class | Raised for | Retried |
|---|---|---|
| `NapixNotFound` (→ `SourceNotFound`) | 600 INVALID_CNR, 628 RECORD_NOT_FOUND: valid call, no data | no |
| `NapixUnavailable` (→ `SourceUnavailable`) | 629 UNEXPECTED_ERROR, HTTP 429 / 5xx, time-outs, connection errors | yes |
| `NapixAuthError` | 626 INVALID_TOKEN, 627 INVALID_DEPT_ID, second 401 | no: key or credentials are wrong; alert the operator |
| `NapixGatewayError` | gateway `httpCode` body, 631 API_ACCESS_NOT_ALLOWED, 401 "Cannot find valid subscription" | no: path or subscription |
| `NapixInputError` | 601, 602, 603, 604, 616, 632, 633, 634: our parameters are wrong | no |
| `NapixProtocolError` | undecryptable envelope, `response_token` present but body unreadable, unknown shape | no |

626 is no longer retried (it was treated as transient on 25 Sep; the live tests showed it means the key).
Each failure goes to `source_failures` with the API, the parameter hash and the class, never lost.

## 7. Retries and rate limiting

- `NapixUnavailable` only: 3 attempts, exponential back-off 2 s → 30 s with jitter; a 401 refresh is a separate
  single retry outside this budget.
- `RateLimiter`: a local sliding window (`NAPIX_RATE_LIMIT_PER_MIN`) and the gateway's `X-RateLimit-Limit` /
  `X-RateLimit-Remaining` headers read from every response. When `remaining` falls under 10 % of the limit the
  limiter sleeps proportionally (window ÷ remaining per call); at 0 it waits `NAPIX_WINDOW_PROBE_SECONDS`, never a
  whole window, so a call is not slept through the reset (design `napix-window`, decision 8). Each attempt carries
  its own time (`NapixResult.called_at`, set after the limiter's wait), which the call log stores. The window's
  length is `NAPIX_RATE_WINDOW_SECONDS` (one hour, 1,000 calls); its **phase is detected** by the service layer from
  the call log's `X-RateLimit-Remaining` readings (`services/napix_window.py`; notes §6: the reset is at a fixed minute
  of the hour, not on the clock hour), and the queue worker waits for the expected reset plus
  `NAPIX_WINDOW_MARGIN_SECONDS`. Current Status batches (≤ 500 CNRs per call) and the daily cycle's per-bench calls
  are spread by the scheduler, not fired at once.
- One `httpx.AsyncClient` per `NapixClient` (connection reuse), closed with the job; HTTP/2 off.

## 8. Endpoints (`hc.py`), input order as in the notes

| Method | Path | Input | Returns |
|---|---|---|---|
| `overview()` | `/overview/overview` | empty | dict (connectivity / credential check in data-health) |
| `causelist_benches(d)` | `/hc-causelist-bench-api/causelistbench` | `est_code|causelist_date` | `[BenchRef]` (judges' and registrars' benches) |
| `causelists_for_bench(d, bench)` | `/hc-causelist-details-api/causelistdetails` | `est_code|causelist_date|bench_id` | rows or list metadata — settled by the live test |
| `causelist_pdf(ref)` | `/hc-show-causelist-api/showcauselist` | `est_code|bench_id|causelist_id|causelist_date` | PDF bytes |
| `case_by_cnr(cnr)` | `/hc-cnr-api/CNR` (fallback `/cnr`) | `cino` | `CaseRecord` |
| `current_status(cnrs)` | POST `/hc-current-status-api/currentStatus` | `cino` (comma list, ≤ 500) | `[StatusRecord]` |
| `order_pdf(cnr, ref)` | `/hc-order-api/order` | `cino|order_no|order_date` | PDF bytes |
| `business(cnr, d)` | `/hc-show-business-api/showBusiness` | `cino|business_date` | dict |
| `search_case_number(...)` | `/hc-case-search-api/casesearch` | `est_code|case_type|reg_no|reg_year` | list |
| `search_party(...)` | `/hc-party-name-api/partyname` (path to confirm) | `est_code|pend_disp|litigant_name|reg_year` | list |
| masters | state / district / bench / case type / act | empty or `est_code` / `state_code` | list |

Dates `yyyy-mm-dd`. Verified paths are marked in the notes; `napix-check` writes a decrypted sample for each
newly verified API to `docs/specs/samples/<api>_<date>.json` and the operator updates the notes' status column.

## 9. What changes in the existing code (for the implementation step, after approval)

1. `config.py`: `napix_base_url`, `napix_est_code`, `napix_token_ttl_seconds`; aliases for the old names; drop
   `napix_auth_key_mode` (text only).
2. `crypto.py`: unchanged (key normalisation, AES, HMAC all match the live tests); add the `HMAC("")` vector test.
3. `client.py`: always encrypt (empty string for no-input APIs); token URL with `//oauth2/token`; `TokenCache`
   with Redis mirror; one `AsyncClient` per client; tolerant JSON extraction; gateway `httpCode` body →
   `NapixGatewayError`; the error classes of §6 (626 no longer retried); `X-RateLimit-*` aware limiter;
   `token_verified` kept in `NapixResult`.
4. `hc.py`: `CNR` → `cnr` fallback on a gateway 404; `act_master()` already present.
5. `napix_check.py`: save samples to `docs/specs/samples/` (the notes' location) and print the rate-limit headers.
6. `.env.example`: the variable names of the notes (done with this document).
7. Tests: offline, against a recorded transport: empty-input encryption, the `""` HMAC vector, gateway-404 body,
   print_r body, encrypted status, token refresh on 401, header-driven throttling, Redis-less token cache.

## 10. Open until the next live run (`aslms napix-check`, NAPIX_ENABLED=true)

Cause List Details content (rows or metadata), CNR path casing, Party Name and master paths, token `expires_in`
presence, the rate-limit window, and whether PDF APIs return raw `application/pdf` or Base64 in the envelope.
