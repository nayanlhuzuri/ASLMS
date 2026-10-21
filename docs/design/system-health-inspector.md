# Design: System health request console — editable court API requests, access token, NAPIX documentation

```
slug: system-health-inspector
status: approved
author: architect
date: 2026-10-21
approved_by: owner on 2026-10-21, with the stated defaults (pre-fill only from cases the sender may see; the full decrypted answer for holders who also have cases.view_all); decisions A-E confirmed
```

## Context
Backlog row 123. The owner asked on 21 Oct 2026, about the System health screen of the Assam State Litigation
Management System (ASLMS):

> "In the API health check, I need to know what API URL it is trying to access (the endpoint details). Checks like
> whether the current access token is valid or not should also be available. And I need to know what parameters it is
> passing — kind of like what Postman offers, so that I can verify manually with the API documentation. You can also
> provide a help button to show the API documentation from NAPIX."

**Owner decisions for this item** (21 Oct 2026, relayed by the coordinator while the note was being written; built in
as decisions here and confirmed by the owner's approval of the note):
- **A. A Postman-like request console per court API.** Nothing calls NAPIX automatically. Each API opens a request
  form pre-filled with the sample ASLMS would use (chosen from held data, as today). Any parameter can be edited or
  typed anew, then **Send** makes exactly one live call through the integration layer and shows the full request
  (method, URL, plain parameters, masked envelope) and the response (status, NAPIX code and meaning, timing, rate-limit
  headers, signature check, structure). Validation follows each API's input rules from the specification and the
  integration notes. The safeguards of Test now apply (switch, quota floor, per-API interval, per-person hourly cap,
  an audit row with the parameters sent). Typed values are never stored as case data and a typed CNR never creates a
  case; the call-log rows and the verbatim response are kept as usual; results are shown, not applied. This replaces
  row 109's "no typed input". The per-card history from the call log stays.
- **B. Layout.** The screen keeps its list of court API cards, grouped as today. A card shows only status and history
  from the call log and makes no call. Clicking it opens that API's console in a large modal opened through the
  address (`?api=<key>`, row 115's `useUrlOverlay`, so Back closes it), with the tabs **Request**, **Response**,
  **History** and **Documentation**. The access token gets its own card at the top of the court section, opening the
  same kind of modal.
- **C. The access token may be read automatically** (ASLMS's own backend produces it): its state shows when the screen
  opens (held, issued, expires, minutes left, last renewal and its outcome), with a "Check token" button. The token
  value is never shown.
- **D. Help and the in-app reference** as briefed: the NAPIX documents behind the function, opened at the API's page.
- **E. The full decrypted answer**: the architect's recommendation is asked for (decision 7 gives it).

**Plan.** The plan names "Prometheus and Grafana for system health" (§3, Table 3) and a NAPIX client "that handles
request encryption and tokens" whose failed calls are "retried and logged, never lost". The System health screen (row
109) is already an addition the owner asked for, not in the plan; this item extends it. Nothing here departs from the
plan. Row-109 decisions that change are listed in decision 16.

**What is in place (rows 109 and 110, reused, not rebuilt):**
- `/system` and the function `admin.service_health`; 17 court API cards in four groups; the card's panel at
  `?api=<key>` (row 115, `docs/design/portal-ui-polish.md`, awaiting approval, moves it onto `useUrlOverlay`; this
  item is built after row 115 merges and uses that hook).
- `services/system_health.py` (`CATALOGUE`, `ApiEntry` with key, method, `input_fields`, `invoke`; the call-log
  figures and status rules), `napix_samples.py` (the held sample, `Sample.public_values`, names hidden, case keys
  shown only when the case is visible), `napix_api_check.py` (guard, the two advisory locks, one call on a fresh
  client, `NapixRecorder.flush_apart`, the audit row `napix.api_tested`, the whitelisted summary).
- The integration layer `backend/aslms/integration/napix/`:
  - `client.py`: `TokenCache` (one token mirrored in Redis `napix:token` with its TTL; renewed when under 60 s
    remain); `token()` posts to `{NAPIX_BASE_URL}//oauth2/token` with Basic auth; `_attempt` builds the four query
    parameters `dept_id`, `request_str`, `request_token`, `version`; `NapixResult.rate_limit` holds the
    `X-RateLimit-Limit` and `-Remaining` of each attempt;
  - `crypto.py`: `build_plain` (`k=v|k=v`, refusing `|` and `=`), AES-128-CBC for `request_str`, HMAC-SHA256 with the
    published hash key `15081947` for `request_token`;
  - `hc.py`: `API` (key → path) and one method per API, which fixes each API's parameter names and order.
- `napix_call_log` (one row per API attempt) and `napix_responses` (every decrypted JSON answer verbatim, with its
  plain parameters).
- The NAPIX documentation in the repository: the High Court Open API Specification v1.0 (85 pages), the NAPIX
  Subscriber Manual v1.5 (23 pages) and the eCourts (District Court) Open API Specification v1.3 (152 pages) in
  `docs/specs/pdf/`; the field inventory `docs/specs/napix_field_inventory.md`; the verified live behaviour
  `docs/napix_integration_notes.md` (it overrides the PDFs where they differ); the Postman collection
  `docs/postman/NAPIX eCourt APIs.postman_collection.json`.

**Facts found while designing (they shape the decisions):**
1. **Token requests are not rows in `napix_call_log`.** `NapixClient.token()` is not passed to the `on_call` hook. A
   failed renewal is recorded on the API attempt that needed it (its `error_family`); a successful renewal leaves no
   durable trace. The API builds a new `TokenCache` per client (`from_settings`), so the API always reads the shared
   Redis copy; there is no long-lived per-process token in the API.
2. **Nobody has measured whether a token request counts against the 1,000-call window.** The notes (§2, §6) and the
   three PDFs are silent (searched for "quota", "rate limit", "throttl" and "1000"). The owner-run live check
   measures it (Verification step 5).
3. **The PDFs carry no table-of-contents object**, but their printed contents pages do. In the High Court
   specification the printed page number equals the PDF page index; every heading in decision 12 was found on that PDF
   page by extracting the text with PyMuPDF. The Subscriber Manual's printed numbers are one less than the PDF page
   index ("Page | 1" is PDF page 2); its mapping uses PDF indices.
4. **Confidentiality.** None of the three PDFs carries a "confidential" or copyright marking. The High Court
   specification says "Access to open API is restricted and will be through process prescribed by e-Committee" (PDF
   page 4), and the Subscriber Manual's Annexure B (PDF page 23) prints example subscriber key, secret and dept_id
   values. The documents are therefore served only to holders of `admin.service_health`, through the API, never from a
   public path.
5. **The Postman collection already works from the plain string.** Its collection-level pre-request script reads a
   query parameter `input` (the plain `k=v|k=v` string), encrypts it with the environment's `auth_key`, computes the
   HMAC with `hash_key` and sets `request_str` and `request_token`. Its two saved requests use `{{request_str_enc}}`,
   which that script does not set (it sets `request_str`); the export of decision 9 uses `{{request_str}}` and does not
   depend on those two saved requests.
6. **`request_token` is not secret.** It is HMAC-SHA256 of the plain string under the hash key published in the
   specification (`15081947`, Annexure A). Showing it lets the owner compare Postman's value with ASLMS's and prove
   both built the same plain string. `request_str` is AES under the Authentication Key and is not shown (decision 3).
7. **Court search already audits the query it sends** (`court_search`: `after.request` holds the typed fields, names
   included), the precedent for decision 8's audit row.

**Not covered:**
- The three High Court APIs ASLMS does not use (`advocate_bar_reg`, `act_details`, `neutral_citation`), `cnr_alt`,
  caveat APIs, and the District Court APIs (the eCourts v1.3 PDF is listed as a document but not mapped per API).
- A free URL, path or header: every request comes from the 17-entry `CATALOGUE`. This is not a general HTTP client.
- Durable rows for background token requests (decision 11 proposes a follow-up).
- Mail and SourceTrace (row 109, owner decision 1).

## Decisions

1. **Cards stay; each opens a request console in a large modal (owner decision B).**
   - The four groups and 17 cards stay. A card shows its status badge, last call, 24-hour bars and the 24 h / 7 day
     rates from the call log, as today, and **makes no call**. Its "Test now" button is removed: sending happens in the
     console. Clicking the card body (or Enter on it) opens the console.
   - The console is the kit's large `Modal` (the pattern of row 102's case details modal; full screen on phones),
     opened by `useUrlOverlay` at `?api=<key>&tab=request|response|history|docs`. Back closes it; a shared link opens
     the same tab. Tabs:
     - **Request**: the editable form and the full request (decisions 2, 6, 8, 9);
     - **Response**: the answer of this Send or of the last send (decisions 4, 5, 7);
     - **History**: today's panel content (7 daily buckets as a `DataTable`, the last 10 calls, the sample label);
     - **Documentation**: Help and the in-app reference (decision 12).
   - The Access token card opens the same `Modal` at `?api=token` with the tabs **Token**, **Request** and
     **Documentation** (decision 10). `token` is a reserved key, never a court API.
   - Alternatives: keep the side panel (too narrow for a request form, a URL and a JSON answer side by side); a page
     per API (loses the card list and the overlay pattern).

2. **The Request tab: pre-filled, editable, and the full request built from the code that sends it.** The server
   builds the request with a *preview* in the integration layer (decision 13), which runs the API's own `hc.py`
   method against a capturing client. Method, path, parameter names, order and values therefore come from the code
   that makes the real call, never from a second copy. The tab shows, top to bottom:
   - **Method and URL**: `GET https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR` (the base URL from
     `NAPIX_BASE_URL`, any user-info part removed, plus `hc.API[key]`). Current Status shows `POST` with "the four
     parameters travel in the query string, as for GET (verified live, notes §3)".
   - **Plain parameters**: one form row per parameter in the documented order: the name, an input pre-filled with the
     held sample (decision 6), the source of the current value ("from settings", "from data ASLMS holds", "edited by
     you"), mandatory or optional, the format and the meaning from the High Court specification (decision 12). A
     "Reset to the sample" link restores the held values. APIs with no input read "This API takes no input. The empty
     string is still encrypted and sent (notes §3)".
   - **The plain string** exactly as `build_plain` makes it, e.g. `est_code=GAHC01|causelist_date=2026-10-20`, in a
     `CodeBlock` with a copy button. It is rebuilt by `POST …/preview` (no call) 400 ms after typing stops; field
     errors from the preview show under their inputs before anything can be sent.
   - **Query parameters (the envelope)**, in order:

     | Name | Shown as | Note |
     |---|---|---|
     | `dept_id` | the first 2 characters and `…` | "Department ID from `.env` (NAPIX_DEPT_ID), masked". Fewer than 6 characters in all: fully masked |
     | `request_str` | "encrypted, 44 characters, not shown" | "AES-128-CBC of the plain string with the Authentication Key (`.env`)". The length is computed from the plain string's byte length (PKCS7 to 16-byte blocks, then Base64); no key is used |
     | `request_token` | the 64 hex characters | "HMAC-SHA256 of the plain string with the published hash key 15081947 (spec Annexure A)". Shown only while `NAPIX_HASH_KEY` equals that published value, otherwise "not shown (a different hash key is configured)"; not shown while the plain string holds a placeholder (decision 6) |
     | `version` | `v1.0` | from `NAPIX_VERSION` |

   - **Headers**: `Authorization: Bearer ‹access token, not shown›`, `Accept: application/json, application/pdf`.
   - **Send · 1 court call** (decision 8), then the cURL and Postman templates (decision 9).
   - **"The last send used the same plain string: yes / no"**: SHA-256 of the previewed plain string against the last
     send's `params_sha256` (decision 5).

3. **Secrets are never in any answer, log line or audit row of this item.** Never shown, in full or in part: the
   access token (no fingerprint either: whether the gateway accepts the current token is read from the call log,
   decision 10), the client key and secret, the Authentication Key, `request_str`, the database and Redis passwords.
   `dept_id` is masked as in decision 2. The cURL and Postman templates carry placeholders (decision 9). A database
   test feeds distinctive values into every secret setting and asserts that none of them, nor the scripted access
   token, nor the full `dept_id`, nor any `request_str` ciphertext, appears in any response of the new and changed
   endpoints, in the audit rows they write, in the Redis token metadata or in the captured log records. Alternative:
   show `request_str` masked or with a key fingerprint (no use to the owner, who builds `request_str` in Postman from
   the plain string, decision 9).

4. **Status meanings come from one table**, `napix_reference.STATUS`, from the specification's per-API
   "Errors/Status" tables and Annexure C, corrected by the notes where live behaviour differs. It is shown beside every
   status on the Response tab and listed on the Documentation tab:

   | Code | Name | Plain meaning (ASLMS note where the notes differ) |
   |---|---|---|
   | 600 | INVALID_CNR | The CNR is not in the prescribed format. ASLMS reads it as "answered, nothing found". |
   | 601 | INVALID_DATE | The business or order date is not valid. |
   | 602 | INVALID_ORDER_NO | The order number is not valid. |
   | 603 | INVALID_EST_CODE | The court code is not valid (for example GAHC01). |
   | 604 | INVALID_CASE_TYPE | The case type is not valid. |
   | 605 | INVALID_REG_NO | The registration number is not valid. |
   | 606 | INVALID_REG_YEAR | The registration year is not valid. Also the court's answer to a blank year in the party and advocate searches (notes §7). |
   | 607 | INVALID_FIL_NO | The filing number is not valid. |
   | 608 | INVALID_FIL_YEAR | The filing year is not valid. |
   | 609 | INVALID_PEND_DISP | The pending / disposed value is not P or D. |
   | 610 | INVALID_LITIGANT_NAME | The party name is not valid. |
   | 614 | INVALID_ADVOCATE_NAME | The advocate name is not valid. |
   | 616 | INVALID_CAUSELIST_DATE | The cause-list date is not valid. |
   | 624 | INVALID_STATE_CODE | The state code is not valid. |
   | 626 | INVALID_TOKEN | The request did not decrypt: the Authentication Key in `.env` is not the court's key for this dept_id (notes §3). |
   | 627 | INVALID_DEPT_ID | The Department ID is not valid. |
   | 628 | RECORD_NOT_FOUND | A valid request with no data. Not an error for ASLMS. |
   | 629 | UNEXPECTED_ERROR | The court's service did not respond. |
   | 631 | API_ACCESS_NOT_ALLOWED | The subscription does not include this API. |
   | 632 | INVALID_VERSION | The version is not valid. |
   | 633 | INVALID_BENCH_ID | The bench ID is not valid. |
   | 634 | INVALID_CAUSELIST_ID | The cause-list ID is not valid. |
   | HTTP 401 | — | The access token was missing or expired; ASLMS renewed it and repeated the call once. |
   | HTTP 404 + `httpCode` body | — | The gateway found no such path, or the API is not subscribed; the court was never reached. |
   | HTTP 405 / 414 | — | Wrong method on Current Status / more than about 300 CNRs in one call (notes §7). |
   | HTTP 429, 500, 502, 503, 504 | — | The gateway or court was unavailable. |
   | HTTP 200, empty body | — | The gateway's known intermittent fault (notes §5). |

   `client.NAPIX_STATUS` gains the names of 605, 609, 610 and 624 (names only; their error family is already
   `NapixInputError`, unchanged).

5. **The Response tab: the answer of this Send, or of the last send, in full.** The last send is the latest audit row
   `napix.api_tested` for the API (anyone's; "your send" when it is the caller's). From this item on, every send
   writes into that row's `after`, besides today's keys: `params` (the plain parameters sent, decision 8),
   `params_sha256`, `edited` (true when any value differs from the held sample), `response_id` (the `napix_responses`
   id the recorder returns; NULL for a PDF or a failure), `token_verified`, `rate_limit` {limit, remaining} and
   `structure`. No migration: `after` is JSONB. Rows written before this item read "not recorded for tests before
   this version" for the new facts. Shown:
   - when, by whom ("your send", "a person"), held or edited values, the outcome word ("Answered", "Answered, nothing
     found", "Failed"), attempts;
   - the request as sent: method, URL, the plain string (from `params`), the masked envelope;
   - HTTP status and NAPIX status, each with its meaning (decision 4), the error family and ASLMS's plain reason;
   - duration (summed over attempts, as today);
   - **rate-limit headers**: `X-RateLimit-Limit` and `X-RateLimit-Remaining` of the deciding attempt (from the
     result for this Send, from `after.rate_limit` for a past one), with the window's reset time from
     `data_health.window_block`;
   - **signature check** (`response_token`): "verified", "did not match (expected for PDFs, notes §4)" or "not sent";
   - row 109's summary facts (unchanged);
   - **the structure of the answer**: field paths, types and counts, never values. `napix_inspect.structure(data)`
     walks the decrypted JSON, collapses numbered collections (`case1`…`caseN`, `sr_no1`…, `state1`…) and lists into
     `[]` with the count, as the field inventory writes them (`casenos[].cino`), uses the inventory's type words
     (`str`, `int`, `float`, `bool`, `null`, `dict`, `list`), stops at depth 6 and 200 paths ("… 37 more paths"), and
     keeps paths to 120 characters. A PDF answer reads "PDF, 280 KB, 2 pages" from the summary. Below it,
     **"Paths not in the field inventory"**, against decision 12's inventory for that API: a new path is a field
     without a home in the schema (CLAUDE.md), so it shows as a warning `Notice` with "Not in the field inventory —
     report it"; inventory paths absent from this answer are listed folded, as information;
   - the full decrypted answer (decision 7).

   With no send yet, the tab shows the **latest stored answer**: the newest `ok` call-log row of the API in 7 days
   (served by `ix_napix_call_log_called_at`), its `napix_responses` row by `(api, params_sha256)` (the unique index),
   newest `last_seen_at`; its structure is computed on read and labelled "from the latest answer ASLMS stored, 14:02,
   background work".

6. **The pre-filled values and party or advocate names (change to row-109 decision 5, flagged).** The form is
   pre-filled with the held sample exactly as row 109 chooses it. A name in the held sample of Search by party name or
   Search by advocate name is pre-filled **only when the caller may see the source case** (`visibility.access_basis`,
   the rule of every case query); the case page already shows that name to that caller, so nothing new is revealed.
   Otherwise the field is empty with the hint "Type a name (the held sample belongs to a case you cannot see)", the
   plain string shows `litigant_name=‹type a name›` and Send stays disabled until a valid name is typed. A CNR, case
   number or filing number of a case the caller cannot see is treated the same way (empty field, hint). A discovery
   term is pre-filled, as row 109 already shows it. Every value that is sent was therefore either seen by the sender or
   typed by the sender, which is what makes decision 8's audit row safe to write. The owner may keep row 109's "never
   shown" at approval: names are then never pre-filled.

7. **The full decrypted answer: shown, collapsed, with copy, audited (recommendation on owner point E).** The Response
   tab has a collapsed "Full answer (JSON)" section with a copy button and a download, read from
   `napix_responses.payload` (already stored verbatim; nothing new is kept). Postman shows the decrypted answer, the
   owner expects it from a console, and court records are public; the guards are:
   - **who**: holders of `admin.service_health` who also hold `cases.view_all` (State-wide case visibility). The super
     admin holds both, so the super admin sees it by default. A person granted only `admin.service_health` sees the
     structure and "The full answer is shown only to users who can see every case", because a search answer names
     cases that person might not otherwise see (server-side visibility, CLAUDE.md). The owner may drop the
     `cases.view_all` condition at approval (the coordinator's lean was "the console's holders").
   - **audit**: each opening writes `napix.response_viewed` (`entity_type` `napix`, `after`: `api`, `response_id`,
     `source` `send` or `latest`, `bytes`; never the payload). Expanding the section is the opening; it is fetched
     only then.
   - **size**: answers over `HEALTH_RAW_MAX_BYTES` (2 MB) answer 413 `too_large`; the structure remains.
   - **PDFs** are not shown here; the order or cause-list PDF is opened from the case or Cause list screens as today.
   Alternative: structure only (row 109's "never the payload"; decision 5 already shows every path, type and count).

8. **Send: exactly one live call with the values in the form (owner decision A).**
   - **Who**: every holder of `admin.service_health` (the super admin by default; grantable as today). Alternative:
     the super admin only (narrower, but the function is already an administrator's grant).
   - **What can be edited**: every plain parameter of the API, including `est_code` and `state_code`. The masters and
     the Connection check have nothing to edit (they still have Send).
   - **Validation, before any call** (422 `invalid_input` with a message per field; `build_plain`'s `|` / `=` refusal
     stays as the last guard). Rules from the specification's "Request String" tables and the notes:

     | Parameter | Rule |
     |---|---|
     | `est_code` | one of the `courts.est_code` values held from the bench master (GAHC01 to GAHC04 today): never an invented code |
     | `state_code` | a `high_courts.napix_state_code` held from the state master |
     | `cino` | `CNR_RE` (16 letters and digits), upper-cased; Current Status takes one CNR per send (a list is not a health check) |
     | `causelist_date`, `business_date`, `order_date` | a real date `yyyy-mm-dd` from 1950-01-01 to today (IST) + 60 days |
     | `bench_id`, `causelist_id` | 1 to 6 digits |
     | `order_no` | 1 to 5 digits |
     | `case_type` | an integer that is a `case_types.case_type_code` of the court named by `est_code` (the held master) |
     | `reg_no`, `fil_no` | 1 to 7 digits (spec); `reg_no` is required although the spec makes it optional, so one send never lists a whole case type and year |
     | `reg_year`, `fil_year` | 4 digits, 1950 to the current year |
     | `pend_disp` | `P` or `D` |
     | `litigant_name`, `advocate_name` | `court_search.PARTY_NAME_RE`, 3 to 99 characters (spec), not only `X`; the notes' behaviour (whole phrase for parties, part of a name for advocates) is shown as a hint |

   - **Safeguards**: row 109's guard unchanged, applied to every send (held or edited): 409 `napix_off`, 429
     `test_too_soon` (per-API interval, shared by everyone), 429 `test_limit` (the person's hourly cap, now counting
     sends and token checks together), 429 `napix_budget` (the quota floor), 409 `user_test_running` and
     `test_running` (the advisory locks). `no_sample` remains only for a send with no body when nothing is held.
     One click is one call: fresh client, `max_attempts = 1`, the token renewal after a 401 the only possible second
     attempt, as today.
   - **What is kept**: the call-log rows and the verbatim `napix_responses` row (CLAUDE.md: every call logged, every
     response kept), and one audit row `napix.api_tested` with `params` (the plain parameters sent; names included,
     as court search audits its query, fact 7, and decision 6 ensures the sender saw or typed them).
   - **Nothing is applied**: no case, party, advocate, hearing, order, document, cause list, master or queue row; no
     event or alert. A typed CNR that does not exist only produces a 600 answer and never becomes an identifier in
     ASLMS (CLAUDE.md: never fabricate identifiers); a CNR that does exist is not added either. To add a found case,
     the person uses Search (`cases.search_court`), which has its own storing, dedupe and limits. This keeps "every
     NAPIX field is kept" through the verbatim layer without a second, unguarded way into case data. The Response tab
     says so: "Shown, not saved to cases. Use Search to add a case."

9. **"Copy as cURL" and "Export to Postman" are templates with placeholders, said plainly.** A working command needs
   the access token and `request_str`, which ASLMS never shows. The Request tab offers, for the values in the form:
   - **cURL template**: the plain string as a comment, then
     ```
     curl -G 'https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR' \
       -H 'Authorization: Bearer <ACCESS_TOKEN>' \
       -H 'Accept: application/json, application/pdf' \
       --data-urlencode 'dept_id=<DEPT_ID>' \
       --data-urlencode 'request_str=<REQUEST_STR: the plain string encrypted with your Authentication Key>' \
       --data-urlencode 'request_token=<the 64 hex characters shown above>' \
       --data-urlencode 'version=v1.0'
     ```
     (Current Status adds `-X POST`; `-G` keeps the parameters in the query string.) `request_token` is filled in
     when decision 2 shows it. The token modal's Request tab carries the token template: `curl -X POST
     '<base>//oauth2/token' -u '<CLIENT_KEY>:<CLIENT_SECRET>' -H 'Content-Type: application/x-www-form-urlencoded' -d
     'grant_type=client_credentials&scope=napix'`.
   - **Export to Postman**: a Postman v2.1 collection file for this one API (`POST …/postman` with the form's values,
     downloaded). It holds the token request (as in `docs/postman`), this API's request with `input=<plain string>`,
     `request_str={{request_str}}`, `request_token={{request_token}}`, `dept_id={{dept_id}}`, `version={{version}}`
     and `Authorization: Bearer {{access_token}}`, and the collection-level pre-request and test scripts of
     `docs/postman` (encrypt from `input`, decrypt and verify the answer). Variables `client_key`, `client_secret`,
     `dept_id`, `auth_key`, `access_token` are empty; `hash_key` is `15081947` and `version` `v1.0`.
   - The words on screen: "These do not run as they are. Fill in the placeholders from your NAPIX subscription (the
     same values as your Postman environment). ASLMS never shows them."

   The scripts are a constant in `services/napix_inspect.py`; a test asserts they equal the collection's `event`
   scripts in `docs/postman`, so the two cannot drift. Alternative: a working cURL (would print the token and the
   encrypted envelope; refused by decision 3).

10. **The Access token card and modal: read on open with no call; "Check token" is one audited token request (owner
    decision C).** A full-width card at the top of "Court connections", before the four groups, with its status badge
    in a `Lead` like the API cards and one line ("Held · 42 minutes left"). It opens the token modal.
    - **Recorded from now on, never the token.** The integration layer writes a Redis hash `napix:token:meta` (8-day
      expiry, refreshed on each write) on every token request, background or manual: `requested_at`, `ok`,
      `http_status`, `error_family`, `duration_ms`, `expires_in`, `token_type`, `scope`, and the token endpoint's own
      `X-RateLimit-Limit` / `-Remaining` when sent (fact 2); on success also `obtained_at` and `expires_at`; on
      failure `last_failure_at` and `last_failure_family`. A counter `napix:token:requests:<IST date>` (8-day expiry)
      counts token requests per day. Every token request also writes one structured log line ("napix token
      requested": outcome, HTTP status, duration; never the token or the response body). Redis trouble never fails a
      call (today's rule).
    - **The Token tab, read when the screen and the modal open, on window focus and every 60 s while visible**
      (`GET /admin/system-health/token`; no call, not audited):
      - **Held**: whether `napix:token` exists and its TTL: "Held · valid for 42 more minutes (until 15:16)"; "About to
        be renewed (under 60 s left)"; "No token held — the next court call obtains one (1 token request)". Without
        `REDIS_URL`: "No shared token store — every court call's client obtains its own token" (amber).
      - **Issued at** and **expires at** (from the metadata; "not recorded yet" until the first token request after
        this version), token type and scope ("Bearer", "napix").
      - **Accepted by the court gateway since it was issued**: the latest `napix_call_log` row with `called_at >=
        obtained_at` and an HTTP status other than 401, e.g. "Yes — 14:31:05, Case details by CNR, HTTP 200"; and the
        count of HTTP 401 rows since `obtained_at`. This answers "is the current token valid" without spending a call:
        the gateway accepted it on a real call.
      - **Last renewal**: when, the outcome in plain words ("obtained", "refused: check NAPIX_CLIENT_ID / SECRET" for
        401/403, "the token service did not answer", "no access_token in the answer"), duration, the token endpoint's
        rate headers or "none sent"; the last failure if any; token requests today.
      - Status: `ok` held and accepted since issued (or held and not used yet); `warn` no shared store, or the last
        request failed while a token is still held; `down` the last request failed and none is held, or 401 answers
        since issue with no successful renewal after them; `unknown` switch off and nothing held ("Court calls are
        switched off on this server"). The card is not counted in the page's overall line (row 109 decision 10 is
        unchanged).
    - **Opening the screen never requests a token.** Reading is free; a token request may count against the window
      (fact 2).
    - **"Check token · 1 token request"** (`POST /admin/system-health/token/check`), a secondary button on the Token
      tab: one fresh token request through the new `NapixClient.renew_token()` (no retry). It proves the client key
      and secret work and replaces the shared token for every process (ASLMS does not use the old one again; a process
      still holding it renews once on a 401, which the client already handles). Refusals before any request, writing
      nothing: 409 `napix_off`; 429 `check_too_soon` (a token check by anyone less than
      `HEALTH_TOKEN_CHECK_MIN_SECONDS`, 600 s, ago, counted from audit rows); 429 `test_limit` (the person's hourly
      cap, shared with sends); 429 `napix_budget` (the quota floor, kept while fact 2 is unknown); 409
      `check_running` (advisory lock `napix-token-check`). It writes one audit row `napix.token_checked` (`after`:
      `ok`, `http_status`, `error_family`, `duration_ms`, `expires_in`, `rate_limit` {limit, remaining}; never the
      token), the metadata and the log line, then the tab re-reads. A token-service failure is a 200 with `ok: false`,
      like a failed send.
    - **The Request tab** of the token modal: `POST https://delhigw.napix.gov.in/nic/ecourts//oauth2/token` (the double
      slash is the manual's form, notes §2), body `grant_type=client_credentials&scope=napix`, `Content-Type:
      application/x-www-form-urlencoded`, "Basic authentication with the client key and secret from `.env` (not
      shown)", and the cURL template. **Documentation**: the Subscriber Manual at Token Generation (PDF page 10),
      Token expired (22) and Annexures A and B (23); the High Court specification's Postman page (78).
    - Alternatives: renew on every opening (spends a request for nothing); a check that makes an Overview call (that is
      the Connection check's Send, which stays); a token fingerprint (not needed).

11. **Background token requests stay out of `napix_call_log` in this item (flagged).** Making each token request a
    call-log row is the complete answer to "every call is logged", but every reader that counts calls would change
    (data health, reports, the load report, the ops exporter, the data-load estimate, the per-person search limits),
    and fact 2 is not yet known. This item records every token request in the application log and the Redis metadata,
    the manual check durably in the audit log, and failures on the API attempt rows as today. Recommended follow-up
    (a backlog row the scribe adds after the live check): a durable token-request record, with the decision on
    counting taken from the measurement.

12. **The Documentation tab: the NAPIX documents behind the function, opened at the API's page, plus an in-app
    reference (owner decision D).**
    - **Documents.** `GET /admin/system-health/docs` lists, and `GET /admin/system-health/docs/{doc}` serves inline:

      | `doc` | File | Pages | SHA-256 (pinned) |
      |---|---|---|---|
      | `hc_spec` | `HighCourt_Open_API_Specifications_1.0_NAPIX_07.09.2023-1-1-1.pdf` | 85 | `b84822ab39abe058f2334378a9c6c7f199a8993975a344802dd09e9fd5ec9c1b` |
      | `subscriber_manual` | `NAPIX Subscriber UM V1.5 22.04.2025-4-1-1.pdf` | 23 | `4407afc09c50199f1bd963a774573277536d498a071a18fc09b5fe3ce9065be9` |
      | `ecourts_spec` | `eCourts_Open_API_Specifications_NAPIX_1.3_22.04.2025-1-1-1.pdf` (District Courts; not mapped per API) | 152 | `0943dd47ca83ddfe6eeb5eb0b067cd4204622df139e31973477334bab14141ab` |

      The API reads them from `NAPIX_DOCS_DIR` (default `/app/napix-docs`), a read-only bind mount of `docs/specs/pdf`
      on the `api` service. Served with `Content-Type: application/pdf`, `Content-Disposition: inline`, the documents
      download's `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`, and `Cache-Control: private,
      no-store`. A missing file, or one whose SHA-256 differs from the pin, answers 404 `doc_missing` and the button
      reads "The NAPIX documents are not installed on this server" (the reference still works). Not audited: reading
      the manual is not a significant action. Never under a public path such as the brand assets.
    - **Help button**: a `?` icon button labelled "NAPIX documentation for this API" in the modal header on every tab;
      it opens the specification at the API's page in a new tab with `#page=N` (the browser's viewer honours it). The
      mapping, verified on the PDFs (fact 3), is the constant `napix_reference.DOC_PAGES`:

      | API | `hc_spec` page | Section |
      |---|---|---|
      | `overview` | 10 | 5.1 Overview API |
      | `cnr` | 12 | 6.1 Search by CNR API |
      | `show_business` | 20 | 6.2 Show Business API |
      | `order` | 23 | 6.3 Show Orders API |
      | `current_status` | 24 | 6.4 Search by CNR (Current Case Status) API |
      | `case_search` | 29 | 6.5 Search by Case Number API |
      | `filing` | 31 | 6.6 Search by Filing Number API |
      | `party_name` | 33 | 6.7 Search by Party Name API |
      | `advocate_name` | 35 | 6.8 Search by Advocate Name API |
      | `causelist_bench` | 42 | 7.1 Causelist Bench API |
      | `causelist_details` | 44 | 7.2 Causelist API |
      | `show_causelist` | 46 | 7.3 Show Causelist API |
      | `state` | 56 | 9.1 High Court State Master API |
      | `district` | 58 | 9.2 District Master API |
      | `bench_master` | 60 | 9.3 Bench API |
      | `act` | 63 | 10.1 Acts Master API |
      | `case_type` | 65 | 10.2 Case Type Master API |

      General links on the tab: List of eCourt APIs (`hc_spec` 5), URL structure (8), Service Request API (9), Annexure
      A encryption and hash (68), Annexure B response (71), Postman (78), Annexure C HTTP status codes (85); Subscriber
      Manual: Token Generation (PDF page 10), Test Response (16), Possible errors (20), Token expired (22), Annexures A
      and B (23). A test pins each file's SHA-256 and checks each mapped page holds its heading: a new edition of a PDF
      fails the test, and the page map is verified again before the pin changes.
    - **The in-app reference** (`GET …/reference`), from `services/napix_reference.py`:
      - **Inputs**: per API, the plain parameters in order with mandatory / optional, format and meaning, transcribed
        from the specification's "Request String" tables (the pages above), with ASLMS notes where live behaviour
        differs: `reg_year` mandatory in the party and advocate searches (606 when blank), the party search matching
        the whole phrase and the advocate search part of a name, Current Status at most about 300 CNRs through the
        gateway (the spec says 500), Search by Case Number's `reg_no` optional in the spec (required by ASLMS's
        console), `case_type` being the master's numeric code.
      - **Outputs**: the field inventory's paths and types for the API (no examples column: the inventory's examples
        include party names), with the mapping `state`→`state_master`, `district`→`district_master`,
        `case_type`→`case_type_master`, `act`→`act_master` and the other keys to sections of the same name; the two
        PDF APIs read "a PDF (Base64 inside `response_str`)".
      - **Status codes**: the table of decision 4, the codes the specification lists for that API first.
      - **How a request is built** and **how an answer is read**: notes §3 and §4 in plain words.
      - A test keeps the module honest: the inputs equal the names and order the preview captures from `hc.py`; the
        outputs equal the parse of `docs/specs/napix_field_inventory.md`.

13. **The preview lives in the integration layer and makes no call.** `integration/napix/preview.py`:
    `preview(settings, key, invoke, values) -> RequestPreview` builds `NapixHighCourt` on a `CaptureClient` whose
    `call(api_path, params, method)` records the three and raises an internal `Captured` signal, so the real `hc.py`
    method runs up to its call and no further (`fallback=False` keeps the CNR card to one path). It returns `method`,
    `path`, `url`, `params` (ordered pairs), `plain`, `plain_sha256`, `request_token` (or None, decision 2) and
    `request_str_length`. It needs no Authentication Key and never opens a connection. This keeps "NAPIX only through
    `backend/aslms/integration/napix/`": the request shape is defined there once. `NapixHighCourt` gains an optional
    per-call `est_code` / `state_code` override used only by the console, so an edited court code reaches the same
    method.

14. **The screen, on the redesign's kit.** Tokens, the UI kit, the alignment rule (status badges in a `Lead`), motion
    with the reduced-motion fallback, phone layout and plain words, as row 109.
    - **One primary per page** stays "Check services again". In the console, **Send · 1 court call** is the modal's
      only primary (a modal is its own surface, as the case details modal's footer action); "Check token · 1 token
      request" is the token modal's only primary. Copy, exports, Reset and Help are secondary or ghost.
    - **Request tab** on a phone: the parameter rows become stacked fields (label, input, hint); the URL, plain string
      and templates sit in `CodeBlock`s that scroll inside themselves, never the page. Send sits in the modal footer.
    - **Response tab**: the outcome word large, the facts as a `KvList`, statuses with their meanings, the structure as
      an indented outline, "Paths not in the field inventory" as a `Notice`, the full answer `Collapsible`.
    - **History tab**: row 109's panel content unchanged.
    - **New kit pieces**: `CodeBlock` (monospace, horizontal scroll inside the block, a copy button that announces
      "Copied" to screen readers) and `CopyButton`, in `components/ui/data.tsx`. No JSON tree library: the structure
      is an outline list and the full answer pretty-printed text.
    - Labels in `messages.ts` (`T.system.console`, `T.system.token`, `T.system.docs`).

15. **The friendly-UI rule.** Only holders of `admin.service_health` see this screen; the costs ("1 court call", "1
    token request") and the window's remaining calls are shown, as row 109 decision 14 allows. No other screen
    changes.

16. **Row-109 decisions that change (flagged for the owner):**
    - decision 6 (no typed input) is replaced by decision 8 (owner decision A);
    - decision 15's card ("Test now" on the card, the side panel) is replaced by decision 1 (owner decision B);
    - decision 5 (names never shown) becomes decision 6 (pre-filled only when the case is visible);
    - decision 9 (never the payload) is kept for the summary and relaxed by decision 7.

    The endpoint `POST /napix/{api}/test` stays and becomes Send (with or without a body). Every other row-109 and
    row-110 decision stands.

17. **Settings** (`core/config.py`, `.env.example`, all optional):
    - `NAPIX_DOCS_DIR` = `/app/napix-docs`;
    - `HEALTH_TOKEN_CHECK_MIN_SECONDS` = 600 (60-86400);
    - `HEALTH_RAW_MAX_BYTES` = 2000000 (10000-20000000).

    Compose: the `api` service gains `- ./docs/specs/pdf:/app/napix-docs:ro`. No other service changes.

18. **The owner may change at approval without reopening the design:** the 600 s token-check interval, the 2 MB
    limit, the dept_id mask (2 characters), the `cases.view_all` condition of decision 7, the pre-filling of names in
    decision 6, and the console's audience (every holder of `admin.service_health`, decision 8).

## Data
**No table, no column, no migration** (head stays 0020). Paragraph for `docs/schema/schema.md`, after the System
health paragraphs:

> System health request console (design `system-health-inspector`, no migration, no table or column): the console,
> the token card and the documentation read `napix_call_log` (the latest calls of an API and the calls since the
> current token was issued, served by `ix_napix_call_log_called_at`), `napix_responses` (the stored answer of a send
> by its id, or the latest stored answer by `(api, params_sha256)`, for its structure and, for holders of
> `admin.service_health` and `cases.view_all`, its verbatim payload) and `audit_log` (`napix.api_tested`). A send's
> `audit_log.after` also holds `params` (the plain parameters sent), `params_sha256`, `edited`, `response_id`,
> `token_verified`, `rate_limit` and `structure` (field paths, types and counts, no values). A send is never applied to
> case data. New audit actions: `napix.response_viewed` (`after`: api, response_id, source, bytes; never the payload)
> and `napix.token_checked` (`after`: outcome, HTTP status, error family, duration, expires_in, the token endpoint's
> rate headers; never the token). The per-API interval counts `napix.api_tested`; the per-person hourly cap counts
> `napix.api_tested` and `napix.token_checked`; the token-check interval counts `napix.token_checked`. Outside the
> database, the integration layer keeps non-secret token metadata in Redis (`napix:token:meta`,
> `napix:token:requests:<date>`, 8-day expiry).

- Reference codes: none (no new function; `admin.service_health`, `cases.view_all` and the super admin exist).
- No FK, class or audit-column change.

## Services
- **`integration/napix/preview.py`** (new): `CaptureClient`, `RequestPreview`, `preview(...)` (decision 13);
  `request_str_length(plain) -> int`; `display_url(base_url, path) -> str` (user-info removed).
- **`integration/napix/hc.py`**: the optional per-call `est_code` / `state_code` override (decision 13); defaults
  unchanged for every other caller.
- **`integration/napix/client.py`**:
  - `TokenCache`: an optional `redis_client` seam for tests; `state() -> TokenState(held, ttl_seconds,
    shared_store)` (never the value); `meta() -> dict` (read-only); `note_request(...)` writes the hash and the day
    counter on every token request, success or failure, inside the existing Redis try/except.
  - `NapixClient.token()` calls `note_request` and logs "napix token requested" (outcome, HTTP status, duration),
    recording the token response's rate headers; behaviour otherwise unchanged.
  - `NapixClient.renew_token() -> TokenRenewal(ok, http_status, error_family, duration_ms, expires_in, rate_limit)`:
    one `token(force=True)` with no retry; an `IntegrationError` becomes an outcome; never returns the token.
  - `NAPIX_STATUS` gains 605, 609, 610, 624 (decision 4).
- **`services/napix_reference.py`** (new, pure constants and lookups): `STATUS`, `INPUTS` (per API: name, mandatory,
  format, meaning, ASLMS note, the validation rule of decision 8), `OUTPUTS`, `INVENTORY_SECTION`, `DOCS`,
  `DOC_PAGES`, `GENERAL_LINKS`, `BUILD_STEPS`; `reference(key) -> dict`.
- **`services/napix_inspect.py`** (new):
  - `console(session, settings, user, key, now=None) -> dict`: the pre-filled form (`napix_samples.choose` and
    decision 6's visibility), the preview, the masks, the last send (the latest `napix.api_tested` row for the key),
    the latest stored answer, the doc link. Runs under `with_timeout(session, REPORT_STATEMENT_TIMEOUT_SECONDS)`.
    Never calls NAPIX.
  - `validate(session, settings, key, values) -> Sample`: decision 8's table; maps the NAPIX names to the chooser's
    value keys (`cino`→`cnr`, `causelist_date`→`list_date`, `litigant_name` / `advocate_name`→`name`, others
    unchanged); returns a `Sample` labelled "the values in the form" with `edited` set; raises `InvalidInput(errors)`.
  - `structure(data, max_paths=200, max_depth=6) -> dict` (pure); `inventory_diff(key, paths) -> {new, absent}`.
  - `mask_dept_id(value) -> str`; `curl_template(preview, token_shown) -> str`; `postman_collection(preview, label)
    -> dict` with `POSTMAN_SCRIPTS`.
  - `stored_response(session, user, key, source, response_id=None)` (decision 7: requires `cases.view_all`, raises
    `Forbidden`; 404 `no_response`; 413 `too_large`) and `record_view(...)` writing `napix.response_viewed`.
- **`services/napix_token.py`** (new): `state(session, settings, now=None) -> dict` (decision 10, from
  `TokenCache.state()` / `meta()` and the call log; never calls NAPIX); `check_guard(...)` and `async check(session,
  session_factory, actor, user, settings, client) -> dict` (guard, lock, `client.renew_token()`, audit
  `napix.token_checked` written apart, as a send's audit row is).
- **`services/napix_api_check.py`**: `run` takes `values: dict | None`; with values, `napix_inspect.validate`
  replaces the held sample (422 before the rest of the guard's refusals, after `napix_off`); the audit `after` gains
  decision 5's keys; `structure` is computed for JSON answers; the outcome carries `rate_limit` {limit, remaining}.
- **`services/system_health.py`**: the per-person count `user_tests` counts `napix.api_tested` and
  `napix.token_checked` (`CAP_ACTIONS`); the card's `test` block becomes the console's send state; nothing else.
- **CLI**: `aslms system-health --token` prints the token state (no call, no token value).
- **Audit and events**: `napix.api_tested` (extended), `napix.response_viewed`, `napix.token_checked`. No event, no
  alert, no notification.

## API
All on the existing router `api/routers/system_health.py` (prefix `/admin/system-health`). Every endpoint requires
**`Permission.ADMIN_SERVICE_HEALTH`**; extra checks are named per row. Errors carry `{code, message}`; 429 adds
`retry_after` and `Retry-After`. Times in IST. Schemas in `api/schemas.py`; the frontend's `schema.d.ts` is
regenerated.

| Method and path | Requires | Answer |
|---|---|---|
| `GET /napix/{api}/console` | `ADMIN_SERVICE_HEALTH` | `ConsoleOut`: `{api, label, method, url, fields: [{name, value, prefilled, source, editable, mandatory, format, meaning, hint}], plain, plain_complete, envelope: [{name, shown, note, length?}], headers: [{name, shown}], request_token, sample: {available, label, reason}, send: {available, reason, cost: 1, next_allowed_at}, last_send: {at, by, edited, ok, answered, status, reason, method, url, plain, http_status, http_meaning, napix_status, napix_meaning, error_family, duration_ms, attempts, rate_limit, window_reset_at, token_verified, summary, structure, inventory_diff, response_available, same_plain_as_form} \| null, latest_answer: {at, by, structure, inventory_diff, response_available} \| null, templates: {curl}, doc: {doc, page, section, available}, full_answer_allowed}`. Never calls NAPIX; not audited; 404 `not_found`. |
| `POST /napix/{api}/preview` | `ADMIN_SERVICE_HEALTH` | Body `{values: {name: value}}`. 200 the request part of `ConsoleOut` for those values (with `templates.curl`); 422 `invalid_input` with `errors: {name: message}`. No call; not audited. |
| `POST /napix/{api}/test` (Send) | `ADMIN_SERVICE_HEALTH` | Body optional `{values}`; without it, the held sample (row 109). 422 `invalid_input`, then row 109's refusals (409 `napix_off`, `no_sample` without a body, `user_test_running`, `test_running`; 429 `test_too_soon`, `test_limit`, `napix_budget`). `ApiTestOut` gains `request` {method, url, plain, envelope}, `edited`, `rate_limit`, `structure`, `inventory_diff`, `response_id`, `response_available`. |
| `GET /napix/{api}/response?source=send&response_id=…` or `?source=latest` | `ADMIN_SERVICE_HEALTH` and `CASES_VIEW_ALL` (403 `forbidden`) | 200 `{api, source, response_id, fetched_at, last_seen_at, token_verified, bytes, payload}`; audited `napix.response_viewed`; 404 `no_response`; 413 `too_large`. |
| `GET /napix/{api}/reference` | `ADMIN_SERVICE_HEALTH` | `ReferenceOut`: `{api, inputs, outputs: {kind, paths: [{path, type}]}, statuses, build_steps, doc, general_links}`. Static. |
| `POST /napix/{api}/postman` | `ADMIN_SERVICE_HEALTH` | Body `{values}` (validated as preview). The Postman v2.1 collection file (`application/json`, attachment `aslms-napix-<api>.postman_collection.json`). No secret; no call; not audited. |
| `GET /docs` | `ADMIN_SERVICE_HEALTH` | `[{doc, title, pages, available}]`. |
| `GET /docs/{doc}` | `ADMIN_SERVICE_HEALTH` | The PDF, inline, with decision 12's headers; 404 `not_found` (unknown id), 404 `doc_missing`. |
| `GET /token` | `ADMIN_SERVICE_HEALTH` | `TokenOut`: `{status, napix_enabled, shared_store, held, ttl_seconds, expires_at, obtained_at, token_type, scope, accepted_since: {at, api_label, http_status} \| null, rejected_since, last_request: {at, ok, outcome, http_status, duration_ms, rate_limit} \| null, last_failure: {at, family} \| null, requests_today, endpoint: {method, url, body, content_type, auth_note}, curl_token, check: {allowed, reason, next_allowed_at}}`. No call; not audited. |
| `POST /token/check` | `ADMIN_SERVICE_HEALTH` | 200 `{ok, http_status, outcome, duration_ms, expires_in, rate_limit, token: TokenOut}`; refusals 409 `napix_off`, `check_running`; 429 `check_too_soon`, `test_limit`, `napix_budget`. Audited `napix.token_checked`. |

- The existing `GET ""`, `GET /napix/{api}` and `GET /services` are unchanged (the History tab reads `GET
  /napix/{api}`).
- **Visibility.** Case data appears only as row 109's labels, decision 6's pre-filled values (only for a visible case),
  the values a person types and decision 7's payload (State-wide visibility required). Everything else is
  configuration, call-log figures or static reference. The relay passes the PDF and the Postman file through unchanged
  (the documents download already proves binary passthrough).

## Jobs
None. No scheduled or queued work; sends and the token check run in the request, as row 109 decision 11.

## Tests
No live NAPIX. The switch is never set; tests patch `Settings.napix_configured` as row 109 does. The scripted gateway
(`tests/unit/conftest.Gateway`, `tests/db/conftest.router`) and a dict-backed Redis stub through the new
`redis_client` seam.

**Integration layer (unit):**
- `test_preview_matches_the_real_call`, parametrised over the 17 keys: for the same values, the preview's method,
  path, ordered params and plain string equal what the scripted gateway records for the real call (`gw.seen[0]`), and
  no request reaches the transport.
- `test_preview_with_an_edited_est_code_reaches_the_call`.
- `test_preview_request_token_only_with_the_published_hash_key`; `test_request_str_length_matches_encryption` (against
  `NapixCrypto.encrypt` for plain strings of 0, 15, 16 and 100 bytes).
- `test_token_request_writes_metadata_without_the_token`: success and 401 failure; the hash holds decision 10's
  fields; no field holds the scripted token; the day counter increments; a Redis error never fails the call.
- `test_renew_token_is_one_request_and_returns_no_token`; `test_renew_token_failure_is_an_outcome`.
- `test_token_state_never_exposes_the_value`.
- `test_napix_status_names_cover_the_reference_table`.

**Services (unit):**
- `test_structure_collapses_numbered_collections`, on every JSON sample in `docs/specs/samples/`: paths in the
  inventory's notation, counts right, no value from the sample anywhere in the output.
- `test_structure_limits_paths_and_depth`; `test_inventory_diff_flags_a_new_path`.
- `test_reference_inputs_match_the_captured_params` (all 17) and `test_reference_outputs_match_the_field_inventory`.
- `test_doc_files_match_their_pins` (SHA-256 and page count) and `test_doc_pages_hold_their_headings` (PyMuPDF).
- `test_postman_scripts_equal_the_repository_collection`; `test_postman_export_has_placeholders_only`.
- `test_curl_template_has_placeholders_only`; `test_mask_dept_id`.
- `test_validation_rules`, one valid and one invalid case per row of decision 8's table.

**Database and API** (`tests/db/test_api_system_health_console.py`):
- `test_every_new_endpoint_needs_admin_service_health` (403 for an officer, Central operator, State oversight and an
  auditor by default; 200 for the super admin and for an officer granted the function).
- `test_reading_never_calls_the_gateway`: the card list, console, preview, reference, postman, docs and token;
  `gw.seen` empty and `gw.token_calls` 0.
- `test_console_prefills_the_held_sample_with_masked_dept_id`.
- `test_console_leaves_names_and_case_keys_of_invisible_cases_empty` and `test_console_prefills_names_of_visible_cases`.
- `test_send_with_held_values_is_one_call` and `test_send_with_edited_values_is_one_call_with_those_values` (the
  scripted gateway decrypts the edited plain string).
- `test_send_audit_row_holds_the_parameters_sent_and_the_new_facts`; `test_same_plain_as_form`;
  `test_pre_item_audit_rows_read_not_recorded`.
- `test_send_invalid_input_makes_no_call_and_writes_nothing`; `test_edited_case_type_and_est_code_must_be_held`.
- `test_send_writes_no_case_data` (row counts of row 109's list unchanged, including after a typed CNR that is not
  held; `napix_responses` gains one row).
- `test_edited_and_held_sends_share_the_interval_and_the_hourly_cap`; row 109's guard tests still pass.
- `test_latest_answer_structure_without_a_send`.
- `test_full_answer_needs_view_all_and_is_audited`; `test_full_answer_too_large_is_413`.
- `test_no_secret_in_any_response` (decision 3): distinctive values in every secret setting; every endpoint of the
  table, held and edited sends and a token check; the response bodies, the audit rows written, the Redis stub and
  `caplog` contain none of them, nor the scripted token, nor the full dept_id, nor the `request_str` ciphertext.
- `test_token_card_states`: held and accepted, held unused, no store, last failure with a token held, last failure
  with none held, 401 rows since issue, switch off.
- `test_token_check_refusals_write_nothing` (each refusal); `test_token_check_is_audited_and_counts_in_the_cap`.
- `test_docs_served_inline_with_headers`; `test_docs_missing_or_changed_is_404`.

**CLI:** `test_system_health_token_prints_no_secret_and_never_calls`.

**Frontend** (vitest, `components/system/console.test.tsx`, `components/ui/data.test.tsx`):
- a card makes no request other than the list; it has no "Test now"; clicking it opens the console at
  `?api=cnr&tab=request` and Back closes it;
- the console has Request, Response, History and Documentation tabs; the token card opens `?api=token` with Token,
  Request and Documentation;
- the Request tab renders the URL, the pre-filled fields, the envelope (dept_id masked, request_str "not shown") and
  the plain string; editing calls preview once after 400 ms and updates the plain string; Reset restores the sample;
- an empty name field with its hint keeps Send disabled; a 422 shows the field messages; a 429 shows the wait;
- Send POSTs once (`inFlight`) with the form's values and the Response tab opens with the answer;
- "Paths not in the field inventory" renders as a warning `Notice`;
- the full answer section is fetched only when expanded, and shows the "every case" message without `cases.view_all`;
- the Token tab renders each status with words, reads on open without a POST, and "Check token" shows its cost and the
  wait when refused;
- Help opens `/api/backend/admin/system-health/docs/hc_spec#page=12` in a new tab;
- `CodeBlock` scrolls inside itself and its copy button announces "Copied";
- "Check services again" is still the page's only primary button; Send is the modal's only primary; reduced motion
  renders final states.

## Verification
1. `ruff check` clean; `pytest -q` green; `npm run lint`, `npm test`, `npm run build` green in `frontend/`.
2. Compose up with `NAPIX_ENABLED` false; `/system` as the super admin:
   - opening the screen makes no call and no token request (`napix_call_log` count unchanged; the token day counter
     unchanged);
   - the Access token card shows the shared store and "No token held" or the held token with its minutes left;
   - the Case details by CNR console shows `GET https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR`, the masked
     dept_id, `cino` pre-filled with the reference case's CNR, the plain string and a 64-character `request_token`;
     editing `cino` to a malformed value shows the field error and Send stays disabled; Send is disabled with the
     switched-off reason;
   - Help opens the High Court specification at page 12 (6.1 Search by CNR API); the token modal's Help opens the
     Subscriber Manual at page 10;
   - the Postman export imports into Postman with empty variables;
   - `docker compose exec api ls /app/napix-docs` lists the three PDFs.
3. A login without `admin.service_health` gets 403 on every new endpoint; a holder without `cases.view_all` gets 403
   on `…/response`.
4. Search the API's log for the dev `.env` secret values after the steps above: none found.
5. **Owner-run live check** (the owner's go-ahead and `NAPIX_ENABLED=true` for that run only). Budget: at most 6
   requests (4 API calls and 1 token request, plus at most 1 renewal on a 401).
   1. Send on the Connection check; note the remaining calls R1 on the Response tab.
   2. Check token. Expect one audit row `napix.token_checked`, the card's "issued at" updated, and the token
      endpoint's rate headers recorded (or "none sent").
   3. After the 60 s interval, Send on the Connection check again; note R2. Count N = the `napix_call_log` rows with a
      `rate_limit_remaining` after step 1, up to and including step 3 (the background load keeps running). With no
      window reset between the steps, a token request counts against the window if R1 − R2 − N = 1 and does not if it
      is 0. Record the result in `docs/napix_integration_notes.md` §2 and the decisions log.
   4. Case details by CNR with `cino` edited to another CNR the owner reads from a case page: one call, one audit row
      with `edited: true` and the parameters sent, no case row changed. Open the full answer: one audit row
      `napix.response_viewed`.
   5. Compare the console's plain string and `request_token` with Postman's for the same CNR (the collection's
      pre-request script prints the input string): equal.
6. The scribe updates `docs/schema/schema.md` (the paragraph of "Data"), `docs/claude_ASLMS_design_decisions.md`,
   `docs/operations.md` (the System health section: the console, the token card, the documents mount, the live
   check), `.env.example` (decision 17), and adds the follow-up row of decision 11.

## Open questions
None. The owner's decisions A to E (21 Oct 2026) are built in as decisions 1, 7, 8, 10 and 12; decision 18 lists the
defaults the owner may change at approval without reopening the design.

## Deviations
Recorded by the developer while building (22 Oct 2026); none changes a business rule or a decision's intent.

1. **Schema names.** The token answers are `NapixTokenOut` and `NapixTokenCheckOut`: `TokenOut` is already the
   sign-in token's schema.
2. **The token modal's Documentation tab** reads `GET /admin/system-health/napix/token/reference` (the reserved key
   `token`): no inputs, the token answer's fields (notes §2), the HTTP rows and the Subscriber Manual links of decision
   10. Every other key not in the catalogue is 404, as before.
3. **Token status with nothing to go on.** Switch on, no token held and no token request recorded reads `unknown`
   ("No token held — the next court call obtains one"); decision 10 lists no status for that case.
4. **"Check token · 1 token request" is the token modal's footer primary** (decision 14) rather than a secondary
   button on the Token tab (decision 10); decision 14 sets the one-primary rule for the modal.
5. **The console's `send` block leaves out the held-sample condition** (a send of typed values needs none) and does
   not decide completeness: the form keeps Send disabled until every value is typed ("Type every value first") and
   while the preview reports an error ("Correct the values marked first"). `plain_complete` says whether the pre-filled
   form is complete.
6. **`params` in the audit row is a JSON object**; JSONB does not keep key order, so the plain string of a past send is
   rebuilt in the documented parameter order (`napix_reference.INPUTS`, which a test keeps equal to what `hc.py`
   sends). `params_sha256` is the hash of the string actually sent.
7. **Additive fields** for the screen: `plain_sha256`, `method_note`, `no_input_note`, `templates.note` on the request;
   `not_saved_note`, `full_answer_note` on the console; `recorded`, `params_sha256`, `remaining` on the last send;
   `required` on a field; `http_meaning`, `napix_meaning` on a send's answer; `renewing_soon`, `valid_until` on the
   token; `read_steps` on the reference.
8. **Structure notation.** `structure` collapses numbered keys exactly as `aslms napix-fields` does (only when every
   value is an object), so `pet_extra_party.party_noN` stays keyed as in the inventory and the diff against the
   inventory has no false "new" paths. An empty block above known fields (e.g. `acts` with no rows) is not new.
9. **Validation seam.** The held masters a typed code must be one of are read through `napix_inspect.HeldMasters`
   (one read per check), so the rule table is unit-tested without a database.
10. **Logs.** The production logging setup (`core/logging.py`) already keeps httpx's request-URL lines, which carry
    `request_str`, out of the log; the no-secret test mirrors that setting. Every token request writes the one line
    "napix token requested" (outcome, error family, HTTP status, duration).
11. **Token store seam.** The router reads the shared store from `app.state.napix_token_cache` when a test sets it,
    else `TokenCache(REDIS_URL)`; a send's client also uses it, which is the same Redis copy as before in production.
12. **UI kit.** `Notice` gains `tone="warning"` (amber) for "Not in the field inventory — report it"; the `?` help
    button is a link styled as a ghost button (it opens a new tab); `useUrlOverlay` gains linked parameters
    (`open(value, {tab})`, `close()` drops `tab`), and a tab change rewrites the address with
    `history.replaceState`, keeping the overlay's history mark so Back still closes the modal.
13. **The exported Postman collection** carries the repository collection's scripts unchanged; those read `auth_key`
    and `hash_key` from the Postman environment, so the collection's own variables are defaults the owner's
    environment overrides.
14. **Unrelated test.** `frontend/src/components/calendar/calendar.test.tsx` expected 22 Oct 2026 not to be today; on
    22 Oct 2026 itself the day's name ends in " (Today)". Its two assertions now accept that suffix.
15. **A send with no body never uses a hidden sample (review finding).** `POST …/napix/{api}/test` without a body is
    refused with 409 `sample_hidden` ("The held sample belongs to a case you cannot see; type the values in the
    console's form and send them") when the held sample carries a name, CNR, case or filing number of a case the
    caller cannot see, before any call and writing nothing (after `no_sample`, before the interval checks). Refusing
    rather than masking keeps decision 6 exact: every value sent was seen or typed by the sender, so the answer's
    `request.plain` and the audit row's `params` never carry a value the sender could not see. The portal always
    sends the form's values, so only a direct API call meets this refusal.
16. **The last send masks case values the viewer may not see (review finding).** The console's `last_send.plain`
    shows a name, CNR, case or filing number (`litigant_name`, `advocate_name`, `cino`, `reg_no`, `fil_no`) only when
    the viewer is the sender, holds `cases.view_all`, or the send used the unedited held sample of a case the viewer
    can see (`visibility.access_basis` on the audit row's `sample.case_ref_no`; a held sample with no source case, the
    discovery term, is shown as since row 109). Otherwise each such value reads `‹not shown›` and `params_sha256` is
    `null` (a hash of a name can be checked against guesses); `same_plain_as_form` is still computed on the server.
    Values typed by another person are never shown to a viewer without `cases.view_all`.
