# Design: NAPIX Search by Advocate Name and by Filing Number in the court search

```
slug: search-court-advocate-filing
status: approved
author: architect
date: 2026-10-17
approved_by: owner (nayanlhuzuri) on 2026-10-17
```

> **Live probe, 18 Oct 2026 (run by the integrator with the owner's go-ahead; 5 NAPIX calls of the 10 allowed, every attempt in `napix_call_log`; samples `docs/specs/samples/advocate_name_2026-10-18-p1..p4.json`, `filing_2026-10-18-p5.json`). Decision-3 outcomes:**
> - **Advocate name (`hc-advocate-name-api/advocatename`) works.** P1 "MR. P J SAIKIA", 2025, P: 36 rows, keys `cino, pet_name, reg_no, reg_year, res_name, type_name` (every key already has a home; no migration). P2 blank `reg_year`: `606 INVALID_REG_YEAR`, so the year is required (as for party name). P3 "P J SAIKIA" without the honorific: the same 36 rows, so the honorific does not matter. P4 "SAIKIA" alone: 325 rows including all 36, so the court matches **part of a name** — the hint asks users to type the full name for precise results.
> - **Filing number (`hc-filing-api/Filing`) works.** P5 case type 111 (WP(C)), filing 6780/2025: 1 row, keys `cino, type_name, fil_no, fil_year, pet_name, res_name`, CNR GAHC010118832025 = the held case. Every key has a home (`cases.filing_no`, `filing_year`); no migration.
> - P6 (a held case not yet registered) was not run: the dev database holds none. Build both kinds; no amendment is needed.


## Context
Backlog row 21. Plan §3.1 Table 4 lists "Search by Case Number / Filing Number" (finding a specific case not yet
in the database, on user search) and "Search by Party Name / Advocate Name / Act" (finding cases by party, advocate
or Act, on user search). Plan §5.2 says users search by "CINO, case number, party name or advocate name", and lists
the data sources as "NAPIX Search by Case Number, Filing Number, Party Name and Advocate Name; Search by CNR for the
full record". Plan §6.3 and Figure 7 say to search the portal database first and the court only when the case is not
held, and to store what is found. cases-api decision 12 (**deviation, scope**, accepted 4 Oct 2026) deferred the
advocate and filing searches because neither had been called live. They have no sample and their response fields are
not in the repository, and CLAUDE.md forbids guessing NAPIX fields. This item closes that deviation.

What the repository says about the two APIs:
- **Gateway stubs** (`docs/specs/napix/hc/`): `hc-advocate-name-api` with path `/advocatename`, and `hc-filing-api`
  with path `/Filing` (capital F). Both are GET with the usual four query parameters. The stubs carry no response
  fields.
- **HC Open API Specification v1.0** (`docs/specs/pdf/HighCourt_Open_API_Specifications_1.0_NAPIX_07.09.2023…`):
  - §6.8 Search by Advocate Name: input `est_code|pend_disp|advocate_name|reg_year`, all mandatory. `advocate_name`
    is 3 to 99 characters and "may consist of full name of the Advocate or even few characters (minimum 3)". It
    matches the petitioner's, the respondent's or an extra party's advocate. Errors 603, 609, 614
    INVALID_ADVOCATE_NAME, 606, 626, 627, 628, 629, 632.
  - §6.6 Search by Filing Number: input `est_code|case_type|fil_no|fil_year`, all mandatory. `case_type` is the
    case-type master's integer code, `fil_no` is up to 7 digits and `fil_year` 4 digits. Errors 603, 604, 607
    INVALID_FIL_NO, 608 INVALID_FIL_YEAR, 626, 627, 628, 629, 632.
  - The response of both is "As shown in Annexure B" (§12): `establishment_name` and
    `casenos.case{n}.{cino, type_name, reg_no, reg_year, pet_name, res_name}`. This is the shape that Search by Case
    Number and by Party Name were seen to answer live. Those live rows also carried `case_type_id`,
    `police_st_code` and `uniform_code`, which the PDF does not list.
- **Not verified live.** `docs/napix_integration_notes.md` §7 marks both APIs "⚠️ not needed yet". There is no sample in
  `docs/specs/samples/`, no path in `docs/specs/napix_field_inventory.md`, and coverage addendum §E says "when one is
  added, its paths join this file first". The spec PDF has been wrong before: it calls `reg_year` of the party search
  mandatory but did not show that a blank year is refused (606, live 14 Oct). It says a party name may be "few
  characters", yet the court matched the whole phrase (live 14 Oct). The spec also gives no hint of the extra row
  keys. So the PDF is the starting point for these two APIs, not the truth.

In place and reused:
- `NapixHighCourt.search_advocate(name, reg_year, pend_disp)` and `search_filing(case_type, fil_no, fil_year)`
  already exist in `integration/napix/hc.py`. They use the spec's input order and the stub paths, and parse the
  answer with `search_rows`. Neither has ever been called.
- `services/court_search.py` provides `guard` (the switch, the quota floor against the detected window, the per-user
  hourly limit), `search_court` (the kinds `cnr`, `case_number` and `party`, the audit row `case.search_court`, and
  the call log flushed before an error), `store_search_rows` (valid `cino` only, search fields fill only empty
  columns, search vector, scoring, duplicate check), `fetch_dossier`, `fetch_court`, `_resolve_case_type`,
  `_local_by_number`, `PARTY_NAME_RE`.
- `POST /cases/search-court` (`cases.search_court`) with the request union `CourtSearchIn` in `api/schemas.py`, and
  `POST /cases/{ref}/fetch-court`.
- `cases` already holds every filing field from the dossier (`filing_no`, `filing_year`, `filing_no_text`,
  `filing_case_type_text`, `filing_case_type_id`, `filing_date`; coverage §C). The local search already matches
  filing numbers (`filing_no_text`) and advocate names (cases-api decisions 5 and 6).
- `aslms napix-check` (`cli/napix_check.py`) saves decrypted samples. `aslms napix-fields` regenerates the field
  inventory. `tests/unit/test_napix_coverage.py` fails when an inventory path has no home in `napix_coverage.md`.
- The portal Search page (`components/search/CourtSearch.tsx`) searches the court by CNR, number or party, with
  "Fetch details" on rows that have no court details.

Owner decisions that bind this item:
- 14 Oct 2026 (department discovery, decision 2 and the decisions-log entry): **users see no call counts, quota or
  allowance**; counts appear only on the Data collection screens.
- 14 Oct 2026 (correction to "no re-fetch questions"): the Court search tab of Department mapping searches without
  warnings. **The Search page's court search and the Data collection screens keep their already-held behaviour as
  built.** On the Search page, a case already held with its details is answered from the database with no call.
- 14 Oct 2026 live check: the owner approved a budget of 10 NAPIX calls for one probe.

Not covered:
- Search by Act, Advocate Bar Registration Number, Neutral Citation and Caveat. Plan Table 4 groups Act with party
  and advocate, but neither the backlog line nor plan §5.2's feature list asks for it. A separate row can be added if
  the owner wants it.
- Adding the two kinds to the Data collection single-case fetch (decision 10).
- Running department discovery by advocate name. The plan names party names and keywords only.
- Writing `case_advocates` from an advocate hit (decision 6).
- Registration number 0 for cases not yet registered. Search rows and dossiers store it as the court gives it today;
  this item changes neither.

## Decisions
1. **A live probe comes first and gates the build: owner-approved, at most 10 NAPIX calls, every attempt in
   `napix_call_log`.** The integrator runs it with the owner's go-ahead, with `NAPIX_ENABLED=true` set for that run
   only (never in code, tests or `.env.example`). The probe uses real values read from the dev database, never
   invented ones:
   | # | API | Input | What it settles |
   |---|---|---|---|
   | P1 | advocate | `advocate_name` exactly as printed (`case_advocates.name_as_listed`, for example `MR. A I KATHAR`) of a held pending case registered in 2025; `reg_year=2025`; `P` | path, row keys, whether that case is returned, row count |
   | P2 | advocate | the same name, `reg_year` blank | whether the year is mandatory, as it is for party (606) |
   | P3 | advocate | the same name without the honorific (`A I KATHAR`), 2025, `P` | whether the honorific matters |
   | P4 | advocate | the surname only (`KATHAR`, at least 3 characters), 2025, `P` | whole-phrase or part matching |
   | P5 | filing | `case_type` = `case_type_id`, `fil_no`, `fil_year` of a held registered pending case whose `filing_case_type_text` equals its `case_type_text` | path, row keys, whether the row carries `fil_no` / `fil_year`, whether that case is returned |
   | P6 | filing | the filing type, number and year of a held case that is not yet registered (`reg_year` 0 or empty, `filing_no` set), if one is held | whether unregistered cases are found and how their registration fields look |

   That is six planned calls. The other four of the budget cover retries of transient gateway errors (each attempt
   counts) and one fallback call on `/hc-filing-api/filing` if `/Filing` answers the gateway's 404 (as the CNR path
   once did). The integrator checks the running total in `napix_call_log` before each call and stops at 10. Any
   steps not yet run are reported, not run.

   The outputs go to the right places:
   - decrypted samples `docs/specs/samples/advocate_name_<tag>.json` and `filing_<tag>.json` (no credentials);
   - `aslms napix-fields` regenerates the inventory;
   - `docs/napix_integration_notes.md` §7 gets both rows marked ✅ with their input strings and what P2–P4 and P6
     showed, plus a dated paragraph in the style of the 14 Oct party check;
   - `napix_coverage.md` §D gets the new paths (Data).

   Alternatives considered and rejected:
   - build from the PDF and test later: CLAUDE.md, and the two PDF errors seen on the party search;
   - probe through the finished API: the samples and the coverage must exist before the kinds are offered (coverage
     addendum §E).
   **Owner's go-ahead needed (spends up to 10 calls).**
2. **`aslms napix-check` is the probe tool, and from now on it logs every call it makes.** The command gains:
   - Two steps that run only when their inputs are given:
     - `advocate_name`: `--advocate NAME --reg-year YEAR|blank --pend P|D`
     - `filing`: `--filing-type CODE --fil-no N --fil-year YEAR`
   - `--max-calls N`: no new step starts once N attempts have been made in the run.
   - **Call recording**: every attempt of every step goes through a `NapixRecorder` (no user id, no lane) and is
     flushed into `napix_call_log` and `napix_responses` at the end of the run. Recording also happens if the run
     fails part-way (in a `finally`).
   - The command checks the database before the first call and refuses to start if it cannot reach it, so there are
     never unlogged calls.

   This applies the CLAUDE.md rule "every call is logged" to the one command that broke it. Until now napix-check
   only printed its calls, while the 14 Oct check went through the worker and was logged. The probe calls also enter
   the detected quota window like any other call.

   `NapixHighCourt.search_advocate` accepts `reg_year: int | None`; `None` sends an empty value and only the probe
   (P2) uses it. The service always passes a year. `cli/napix_fields.py::KNOWN_APIS` gains `advocate_name` and
   `filing` so the samples are grouped under those names.

   Alternative considered: a separate `napix-probe-search` command. Rejected because the backlog names napix-check,
   and a second tool would need the same sample-saving code.
3. **The design does not depend on what the probe shows. Each outcome has a stated consequence, and anything outside
   the table goes back to the owner.**
   | Probe shows | Consequence |
   |---|---|
   | Rows in the Annexure B shape (`casenos.case{n}` with `cino`, …) | Built as written below. |
   | Extra row keys that already have a home in `cases` (coverage §C: `fil_no`, `fil_year`, `date_of_filing`, `case_type_id`, `police_st_code`, `uniform_code`, `type_name_fil`, …) | Mapped in coverage §D to those columns. `store_search_rows` fills them **only where empty** (a dossier is authoritative), as it does for the existing keys. No migration. |
   | A key with no home anywhere in the schema | **Stop.** The build pauses, and the architect returns an amendment for the owner (a `schema.md` paragraph and migration **0019**). No column is invented ahead of the evidence. |
   | Advocate `reg_year` blank is accepted and returns every year (P2) | Recorded and reported. The year stays required (one call per year, as for party) unless the owner decides otherwise. |
   | Advocate name matched as the whole phrase (P3 / P4) | The form's hint asks for the name as the court prints it. Only the message text changes. |
   | Advocate name matched by part | The hint says "at least 3 characters of the name". Only the message text changes. |
   | `/Filing` and `/filing` both answer the gateway's 404 ("No resources match"), or either API answers as not subscribed | That kind is **not built**. The other kind ships alone, and the owner is asked to request the subscription from e-Committee. The `API` path stays as it is. |
   | Filing search finds a registered case only through its filing type, not its registration type (P5) | The form labels the type "Filing case type". Only the text changes; the master's codes are the same list. |
4. **Two new kinds on the same endpoint and in the same shape as the existing three.** `POST /cases/search-court`
   gains:
   - `{kind: "advocate", name, reg_year, pend_disp: "P"|"D"|"both"}`
   - `{kind: "filing", case_type, fil_no, fil_year}`

   The response, guard, errors, audit and visibility are unchanged (cases-api decisions 9, 13 and 14). Search results
   still carry `visible`, and reading a case still needs visibility.

   Alternative considered: a second endpoint per kind. Rejected because the portal, the guard and the audit already
   switch on `kind`.
5. **Filing number works like the case number: local first, then one search call, then the dossier of the case
   asked for.**
   - **Input check.** `case_type` is a short name or the master's numeric code, resolved through `case_types` by
     `_resolve_case_type`; an unknown type is a 400 and no call is made. `fil_no` is 1 to 9,999,999 (the spec's 7
     digits) and `fil_year` is 1950 to the current year plus one.
   - **Local check (Figure 7, and the Search page as built).** A held, non-merged case with its details is returned
     with `source: local` and no call when all of these hold:
     - it has a dossier (`last_full_refresh_at` set);
     - its `filing_no` and `filing_year` equal the request;
     - its filing type is the requested type: `filing_case_type_id` is that type, or `filing_case_type_text`
       compacts to the type's short name or an alias, or, when the case has no filing type, its `case_type_id` is
       that type.
   - **Court search.** Otherwise Search by Filing Number is called and every returned row is stored by
     `store_search_rows`. The case asked for then gets its dossier at once if it has none (1 + 1 calls). The case
     asked for is:
     - the stored row whose `fil_no` and `fil_year` equal the request, when the rows carry those keys (decision 3);
     - otherwise the single stored row, when the court returned exactly one valid row.

     With several rows and no filing keys, the rows are returned and no dossier is fetched. The user picks one with
     "Fetch details", as for a party hit.
   - A filing number is how a case is found **before it is registered**. Such a row may carry no usable
     registration number; it is stored under its CNR, which is real, and nothing is made up for the missing number.

   Alternative considered: fetching the dossier of every row. Rejected because a filing search asks for one case.
6. **Advocate name works like the party name: no local short cut, every row stored, no dossier fetched.**
   - **Input check.**
     - `name` is 3 to 99 characters (the spec's maximum; the party field's 200 stays as built). It must match
       `PARTY_NAME_RE` (letters, digits, spaces and `. , ' & ( ) / -`), so no typed value can add or change a pair
       in the gateway's `k=v|k=v` input. The schema (422), the service (`CourtSearchError`) and `build_plain` (which
       refuses `|` and `=`) each check this, as cases-api deviation 16 requires.
     - `reg_year` is required, 1950 to the current year plus one.
     - `pend_disp` is `P` (default), `D` or `both`; `both` makes two calls, `P` then `D`, and 628 on one of them is
       not an error.
   - **Court search.** Every returned row with a valid `cino` is stored and scored (origin `search`). Rows without
     one go to `unmatched` and are never stored. **No dossier is fetched.** An advocate who appears for the State
     can be in hundreds of cases a year, and the quota is shared with the daily cycle (the same reasoning as cases-api
     decision 9 for party hits). Each item carries `dossier_status`, and the user fetches the ones they need.
   - **Nothing is written to `case_advocates` from a hit.** The row does not say on which side, or for which party,
     the advocate appears. Recording a guessed advocate–case link would be a fabricated record. The case's advocates
     arrive with its dossier.
   - **Re-searching.** There is no "searched before" question on the Search page: the party kind has none as built,
     and the 14 Oct correction keeps the Search page as built.

   Alternatives considered:
   - Fetching dossiers of all hits: too many calls for one person's search.
   - Queueing them in the `request` lane: the Data collection console already offers that through `fetch-details`
     for users who manage the load.
7. **No new function, no matrix change.** Both kinds need `cases.search_court` (department head, department admin,
   department officer, central operator and the super admin; not the directorate user). Search attempts count
   against `NAPIX_SEARCH_PER_USER_HOUR` through their `case.search_court` audit rows. `both` counts as one search,
   as it does for party. The floor `NAPIX_SEARCH_FLOOR` and the timeout `NAPIX_SEARCH_TIMEOUT_SECONDS` apply
   unchanged.
8. **Audit.** Each attempt that reaches the gateway writes one `case.search_court` row with entity `napix_search`.
   `after` holds:
   - `kind`, `advocate` or `filing`;
   - `request`, the fields as given (an advocate's name is court-public);
   - `calls`, `results`, `created`;
   - `outcome`, one of `ok`, `not_found` or `failed:<code>`.

   Input errors refused before any call write nothing (cases-api deviation 6). New cases emit the existing
   `case_created` event (source `search`) through `get_or_create_case`.
9. **The Search page offers the two kinds and shows no call counts.** The "Search by" choice gains:
   - **"Advocate name"**: name, registration year, pending / disposed / both;
   - **"Filing number"**: case type from the master, filing number, filing year.

   If the local search was run with the advocate field, the court search opens on "Advocate name" with the same
   words. The result line becomes "N case(s) found; M new to the portal." **for every kind**, so the court-call count
   is dropped from the Search page as well. The 14 Oct owner rule says users see no call counts; the Search page
   still showed them because it was built before that rule. The API keeps `calls`, which the Data collection console
   shows. Rows without details keep "Fetch details", and errors keep their current messages.
   **Owner check:** dropping the count for the three existing kinds too.
10. **The Data collection single-case fetch keeps its three kinds.** `POST /admin/data-load/fetch` and its
    already-held / searched-before questions are unchanged. Its request union (`LoadFetchIn`) is separate from
    `CourtSearchIn`, so it is not affected.

    If the owner wants the two kinds there too, it is a small follow-up:
    - filing: `already_held` on the rule of decision 5;
    - advocate: `searched_before` read from the audit rows, as for party.

    Alternative considered: adding them now. Rejected because the backlog line names only `POST
    /cases/search-court`, and the console is for managing the load, where CNR and case number already add a specific
    case. **Owner check.**
11. **Court-search results are built in one query.** `case_search.items_for(session, user, cases, match)` evaluates
    `visible` and the pool flag for all result cases in one `SELECT … WHERE cases.id = ANY(:ids)`, then calls the
    existing `_items`, keeping the court's order. The router uses it for every kind instead of one `item_for` call
    per case. An advocate search can return hundreds of rows; one query per row would hold the request open for
    seconds. `item_for` stays for single cases (`fetch-court`). The result is the same as before.
12. **No migration is expected.** Every field of Annexure B already has a home (coverage §D, the same columns as the
    party and case-number rows), and so does every filing key the dossier carries (§C). Migration 0019 is written
    only in the case decision 3 names (a probe key with no home), and only after the owner approves the amendment.
    The dev database head stays 0018.

## Data
No new table, column or reference code. **No migration** (decision 12; 0019 only after an owner-approved amendment).

`docs/schema/schema.md`: unchanged.

`docs/schema/napix_coverage.md`, written after the probe:
- §D: the search rows' API column reads `case_search, party_name, advocate_name, filing` for the shared paths:
  - `establishment_name` goes to `courts.name` (confirmation only);
  - `casenos[].cino` goes to `cases.cnr`;
  - `pet_name` and `res_name` go to the summaries;
  - `reg_no`, `reg_year`, `type_name` and `case_type_id` go to their usual columns;
  - `police_st_code` and `uniform_code` go to their usual columns.

  Each extra key the probe shows gets a row naming its existing `cases` column, for example
  `| advocate_name, filing | casenos[].fil_no, casenos[].fil_year | cases.filing_no, cases.filing_year |`, written
  only if seen.
- §E: the sentence "Search by Advocate, by Filing number … are not sampled" becomes "Search by Advocate Name and
  by Filing Number sampled on <date> (design `search-court-advocate-filing`); Act, Advocate Bar Reg, Neutral
  Citation and Caveat are not sampled."
- `test_napix_coverage.py` passes with the regenerated inventory.

## Services
`backend/aslms/integration/napix/hc.py`:
- `search_advocate(name, reg_year: int | None, pend_disp="P")`: `None` sends `reg_year=` empty (probe P2 only).
  Input order and path stay as they are: `est_code|pend_disp|advocate_name|reg_year`, `hc-advocate-name-api/advocatename`.
- `search_filing(case_type, fil_no, fil_year)`: unchanged (`est_code|case_type|fil_no|fil_year`,
  `hc-filing-api/Filing`).
- If the probe shows that `/filing` is the working path, `API["filing"]` changes to it, with a fallback like
  `case_by_cnr`'s and the notes updated.

`backend/aslms/services/court_search.py`:
- `MAX_ADVOCATE_NAME = 99`.
- `search_court` dispatches `advocate` to `_search_advocate` and `filing` to `_search_filing`, both inside
  `asyncio.wait_for(…, napix_search_timeout_seconds)`. The error message for an unknown `kind` lists all five kinds.
- `_search_advocate(session, hc, court, request) -> CourtSearchResult` (decision 6). It shares the input checks and
  the `P` / `D` / `both` loop with `_search_party` through a small helper (`_name_search(…, method)`), so the two
  stay identical apart from the field name and maximum length. When no call finds anything it raises `NapixNotFound`
  (`outcome: not_found`).
- `_search_filing(session, hc, court, request, *, force=False, origin) -> CourtSearchResult` (decision 5). Behaviour
  with `force`: it skips the local match and re-fetches the asked case's dossier. Nothing passes `force` today; it
  matches `_search_case_number`'s signature for a later Data collection use.
- `_local_by_filing(session, court, ct, fil_no, fil_year) -> Case | None` applies the matching rule of decision 5 to
  non-merged cases that have a dossier, oldest first.
- `store_search_rows`: gains the extra keys mapped by decision 3, if any, as more `_fill_empty` lines. The rules stay
  as they are: valid `cino` only, fill-empty-only, vector, scoring, duplicate check.
- Audit and call log: unchanged path through `_finish` (decision 8).

`backend/aslms/services/case_search.py`:
- `items_for(session, user, cases, *, match) -> list[dict]` (decision 11).

`backend/aslms/cli/napix_check.py` (decision 2):
- the `advocate_name` and `filing` steps and their options;
- `--max-calls`;
- the recorder flushed in a `finally` through `db.session.session_scope()`;
- the database check before the first call (refuse with a plain message);
- the run summary line also prints how many attempts were recorded in `napix_call_log`.

`backend/aslms/cli/napix_fields.py`:
- `KNOWN_APIS` gains `advocate_name` and `filing`.

## API
`backend/aslms/api/schemas.py`:
- `CourtSearchAdvocateIn {kind: Literal["advocate"], name: str (3–99, pattern ^[A-Za-z0-9 .,'&()/-]+$), reg_year:
  int (1950–2100), pend_disp: Literal["P","D","both"] = "P"}`.
- `CourtSearchFilingIn {kind: Literal["filing"], case_type: str (1–60, short name or master code), fil_no: int
  (1–9,999,999), fil_year: int (1950–2100)}`.
- `CourtSearchIn` = the discriminated union of the five.

| Method, path | Function | Request | Response | Visibility |
|---|---|---|---|---|
| `POST /cases/search-court` | `Permission.CASES_SEARCH_COURT` (`cases.search_court`) | the existing three kinds, plus `{kind: "advocate", name, reg_year, pend_disp}` or `{kind: "filing", case_type, fil_no, fil_year}` | unchanged: 200 `{source: local\|court, calls, created, items: [CaseSearchItemOut], unmatched: [UnmatchedRowOut]}`, with `match` = the kind; 400 `bad_input` (unknown case type, gateway 604 / 607 / 608 / 614 / 606 / 609); 422 schema; 429 `search_limit`; 502 `napix_unavailable`; 503 `napix_off` / `napix_budget`; 504 `napix_timeout` | items carry `visible` (cases-api decision 4); details still need `can_view_case` |
| `POST /cases/{ref}/fetch-court` | `Permission.CASES_SEARCH_COURT` | unchanged | unchanged | unchanged (an advocate hit is fetched here) |

The router's docstring names the five kinds. `frontend/openapi.json` and `src/lib/api/schema.d.ts` are regenerated
(`backend/tools/export_openapi.py`, `npm run gen:api`; `test_openapi_snapshot.py`).

Portal (`frontend/`):
- `components/search/CourtSearch.tsx`: the two kinds and their fields (decision 9). The case-type list reuses
  `useCaseTypes`. The "Advocate name" prefill applies when the Search page's field is `advocate` (the page passes
  `initialField`).
- `lib/messages.ts`:
  - `byAdvocate`, `byFiling`, `advocate`, `advocateHint` (text chosen from the probe, decision 3), `filNo`, `filYear`,
    `filingType`;
  - `courtFound(n, created)` without calls.

## Jobs
None. The order PDFs of a dossier fetched by a filing search are queued by `enqueue_order_pdfs` in the `request`
lane with the caller as `requested_by`, as for the other kinds. Cases found by either kind join the daily Current
Status batches, the weekly dossier sweep and the dirty rescore like every case.

## Tests
Unit:
- `test_napix_hc.py`: `search_advocate("A I KATHAR", 2025)` sends `est_code=GAHC01|pend_disp=P|advocate_name=A I
  KATHAR|reg_year=2025` to `hc-advocate-name-api/advocatename`. `search_advocate(…, None)` sends `reg_year=` empty.
  `search_filing(111, 7451, 2026)` sends `est_code=GAHC01|case_type=111|fil_no=7451|fil_year=2026` to
  `hc-filing-api/Filing`. A name holding `|` or `=` is refused by `build_plain` with no request sent.
- `test_napix_check.py` (new; the unit gateway, no live call):
  - the advocate and filing steps run only with their inputs;
  - `--max-calls 1` starts no second step;
  - every attempt, retries included, reaches the recorder;
  - without a reachable database the command exits before any call.
- `test_napix_fields` (in the existing coverage or fields test): `advocate_name_2026-10-18.json` and
  `filing_2026-10-18.json` map to `advocate_name` and `filing`.
- Schemas (in `test_case_search_parse.py` or a new `test_court_search_schemas.py`):
  - advocate: a 2-character or 100-character name is 422; a name with `|` or `=` is 422; a missing `reg_year` is 422;
  - filing: `fil_no` 0 or 10,000,000 is 422; a missing `case_type` is 422.
- `test_napix_coverage.py` passes with the probe's samples in the inventory.

Database (`tests/db/test_court_search.py` additions). The scripted gateway in `tests/db/conftest.py::router` answers
`hc-advocate-name-api/advocatename` and `hc-filing-api/Filing` from the probe's saved samples (never from invented
fields).
- Advocate:
  - every valid-CNR row is stored with `first_seen_source = search`, summaries, `case_type_id` when given, and a
    score row when a keyword rule matches a sample party;
  - no dossier is fetched, and the verbatim response is in `napix_responses`;
  - `pend_disp: both` makes two calls; 628 on both gives 200 with no items and an audit row `outcome: not_found`;
  - an invalid `cino` goes to `unmatched` and creates no case;
  - **no `case_advocates` row is written** for any hit.
- Filing:
  - a held case with a dossier and that filing type, number and year gives `source: local`, `calls: 0`, and no
    `napix_call_log` row;
  - otherwise one search call and one dossier call for the single returned row, with order PDFs queued in the
    `request` lane;
  - an unknown case type gives 400 and no call;
  - a gateway 607 gives 400 `bad_input`, with the call log row and the audit row `failed:napix_input` committed;
  - with two rows and no filing keys, both are stored and no dossier is fetched;
  - the match falls back to `case_type_id` when the held case has no filing type.
- Both kinds:
  - search fields never overwrite a dossier-filled column;
  - switch off gives 503 `napix_off` with no call log row;
  - the per-user limit counts the new kinds (the 31st search of either kind in an hour gives 429);
  - a directorate user (no `cases.search_court`) gets 403;
  - a gateway 500 on every retry gives 502, and the call log and the audit row with `failed:napix_unavailable` are
    read back in a new session.
- `items_for`: for a mixed list, returns the same `visible`, `in_pool`, `claimable` and `dossier_status` as
  `item_for` per case, in the given order, with one visibility query (statement count asserted with an event
  listener).
- `test_napix_check_records.py`: a napix-check run against the scripted gateway leaves one `napix_call_log` row per
  attempt with `user_id` and `lane` NULL.
- `tests/db/test_pipeline.py`, `test_data_load.py`, `test_api_data_load.py` and `test_discovery_run.py` stay green
  (the shared `store_search_rows` and the unchanged Data collection union).

Portal (`components/search/search.test.tsx`):
- "Advocate name" sends `{kind: "advocate", name, reg_year, pend_disp}`;
- "Filing number" sends `{kind: "filing", case_type, fil_no, fil_year}`;
- the result line reads "1 case(s) found; 1 new to the portal." with no call count, for every kind;
- an advocate field search pre-selects "Advocate name";
- "Fetch details" on an advocate hit calls `fetch-court`.

## Verification
1. `ruff check` clean; `pytest -q` and the portal tests green, with the probe's samples committed.
2. **The probe (decision 1), owner's go-ahead, at most 10 calls.**
   - Read the inputs from the dev database (read-only), for example:
     - `SELECT c.cnr, a.name_as_listed FROM case_advocates a JOIN cases c ON c.id = a.case_id WHERE a.is_current AND
       c.status = 'pending' AND c.reg_year = 2025 LIMIT 5`
     - `SELECT cnr, case_type_id, filing_case_type_text, case_type_text, filing_no, filing_year, reg_year FROM cases
       WHERE filing_no IS NOT NULL AND last_full_refresh_at IS NOT NULL LIMIT 5`
   - Note `SELECT count(*) FROM napix_call_log WHERE api IN ('hc-advocate-name-api/advocatename',
     'hc-filing-api/Filing', 'hc-filing-api/filing')`, which should be 0 before the probe.
   - Run, one call per run with the switch set for that run only:
     `NAPIX_ENABLED=true aslms napix-check --only advocate_name --advocate "<name>" --reg-year 2025 --pend P
     --max-calls 2 --tag <date>-full`. Do the same for P2–P6. Re-read the count before each run and stop at 10.
   - Afterwards: `aslms napix-fields`; update notes §7 and coverage §D / §E; put the call count, row counts and the
     answers to P2–P4 and P6 in the cycle report. If decision 3's "stop" case occurs, the cycle pauses for the
     owner.
3. Compose (`api`, `web` rebuilt; no migration, head stays 0018). With `NAPIX_ENABLED=false` (the default), as the
   `EDU` admin: `POST /cases/search-court {"kind":"filing","case_type":"WP(C)","fil_no":<a held case's
   filing_no>,"fil_year":<its year>}` and `{"kind":"advocate","name":"<a name>","reg_year":2025}` both give 503
   `napix_off`. As built, the router runs the guard before any kind, so the local short cut is only reached with the
   switch on; the database tests prove that short cut with the switch reported as configured
   (`Settings.napix_configured` patched, cases-api deviation 11). `SELECT count(*) FROM napix_call_log WHERE called_at
   > now() - interval '5 minutes' AND user_id = <the admin's id>` gives 0.
4. Only if the owner runs a live check with the switch set for that run (counted with the probe or approved
   separately): one advocate search from the Search page lists cases with "Fetch details" and no call count; one
   filing search for a case not held opens with its details; `SELECT action, after->>'kind', after->>'outcome' FROM
   audit_log WHERE action = 'case.search_court' ORDER BY created_at DESC LIMIT 3`.
5. Portal: the Search page shows the five kinds. The result line has no call count. The Data collection fetch still
   offers three kinds with its already-held questions.

## Open questions
None blocking. The owner should confirm:
- decision 1: the go-ahead for the live probe, at most **10 NAPIX calls** (six planned, four kept for retries and the
  path fallback), with real values read from the dev database. The build of the two kinds waits for it;
- decision 3: the outcomes table, and especially "a key with no home stops the build for an amendment (migration
  0019)" and "an API not subscribed is dropped from this item";
- decision 6: advocate hits are stored without dossiers (fetched on demand or by the weekly sweep), and no
  `case_advocates` row is written from a hit;
- decision 6: the advocate name is limited to 99 characters (the spec), while the party name keeps 200 as built;
- decision 9: the court-call count is removed from the Search page's result line for **all** kinds, to apply the 14
  Oct "no call counts to users" rule;
- decision 10: the Data collection single-case fetch keeps its three kinds for now;
- Not covered: Search by Act (plan Table 4) gets no row unless the owner asks for one.

## Deviations
Written by the developer, 18 Oct 2026.
- **Build split at the probe gate (decision 1).** No decrypted sample of either API exists in `docs/specs/samples/`
  yet, so the first commits build only what does not depend on the probe: the probe tool (decision 2: the
  `advocate_name` and `filing` steps, `--max-calls`, the recorder flushed in a `finally`, the database check, the
  recorded count in the summary line), `search_advocate(reg_year=None)`, `KNOWN_APIS`, and `items_for` used by
  `POST /cases/search-court` (decision 11). The two kinds (schemas, `_search_advocate`, `_search_filing`,
  `_local_by_filing`, the portal, the coverage rows and the database tests that answer from the probe's samples)
  wait for the probe, which only the integrator runs with the owner's go-ahead and the switch set for that run.
- `napix-check --advocate` refuses to start without `--reg-year`: the year is a 4-digit number or the word
  `blank` (probe P2), so an empty year is never sent by accident. `--pend` is `P` or `D`; the filing step needs
  `--filing-type`, `--fil-no` (1 to 9,999,999) and `--fil-year` together. The checks run before any call.
- When the database cannot be reached, napix-check prints a plain message naming only the error class (the URL may
  carry credentials) and exits with code 2.
- `--max-calls` counts attempts, retries included; a step already started finishes its retries, so a run can end
  above N by at most the retries of its last step (the design's "no new step starts").
- `items_for` selects with `cases.id IN (…)` rather than `= ANY(:ids)`; same result, one statement. A case listed
  twice in the court's answer appears twice, as before. The Data collection router keeps `item_for` per case
  (decision 11 names the cases router).

Written by the developer after the probe, 18 Oct 2026 (the two kinds built).
- **Filing rows carry no registration number** (P5: `fil_no`, `fil_year`, no `reg_no` / `reg_year`). A new case
  from such a row has no `case_no_text` until its dossier arrives; nothing is composed for it. `fil_no` and
  `fil_year` fill `cases.filing_no` / `filing_year` only where empty (coverage §D). The row's `type_name` keeps
  its shared home `cases.case_type_text` (fill-empty), as the design's §D lists; `filing_case_type_text` and
  `filing_no_text` stay dossier-only, because P5 could not tell whether a filing row's `type_name` is the filing
  or the registration type (both were WP(C)).
- **The asked row of a filing search** is matched on the row's own `fil_no` / `fil_year` (not the stored columns,
  which a dossier may already hold with other values); the single-valid-row fallback counts distinct CNRs.
- **Unmatched filing rows** list the same five keys as before (`UnmatchedRowOut` unchanged, decision 4), so a
  filing row without a valid `cino` shows no filing number.
- **Gateway error names**: `NAPIX_STATUS` gains 606 `INVALID_REG_YEAR` (seen live), 607 `INVALID_FIL_NO`, 608
  `INVALID_FIL_YEAR` and 614 `INVALID_ADVOCATE_NAME` (spec §6.6, §6.8), so a 400 message names the field. 609 is
  left unnamed: its name is not in the repository.
- **Advocate rows carry no `case_type_id`** (P1, unlike the party rows); the type is resolved from `type_name` by
  the existing path when the master has it.
- **The Search page's advocate field**: the page has no field control, so the court search's "Advocate name"
  pre-selection reads `field=advocate` from the URL; the same `field` (one of `cnr`, `number`, `party`,
  `advocate`, `text`) is now passed to `GET /cases/search`, which already accepted it.
- **Advocate hint** (decision 3, P4 part matching): "At least 3 characters of the name; the court also finds names
  that contain it, so type the full name for precise results."
- **Filing type label**: "Filing case type" (spec §6.6 names the filing's case type; P5 could not tell the two
  apart, decision 3's last row).
- `tests/db/conftest.py::router` answers the two APIs from the P1 and P5 samples; the napix-check recording test
  that relied on the advocate path being unscripted now scripts its 628 explicitly.
