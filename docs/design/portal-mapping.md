# Design: Portal — department mapping screens (counsel codes and unmapped codes, keywords and name patterns, watchlist, scoring settings)

```
slug: portal-mapping
status: approved
author: architect
date: 2026-10-12
approved_by: owner (nayanlhuzuri) on 2026-10-12
```

## Context
The plan, §4.1 (Codes and signals): "Gauhati High Court cause lists show who appears for the government, usually as a
standing counsel code in the advocate column (for example, 'SC, EDU' or 'PP, ASSAM'). Each code is mapped to its
department in the administration module", with keywords and name patterns ("department names and designations
appearing in the party names"), linked-case history and the watchlist ("specific cases a department has asked to
follow") as the other signals. §4.2 / Table 6: the bands (≥ 0.85 strong, 0.50–0.85 possible, < 0.50 unclaimed pool),
"in every case, the department decides by claiming it". §5.11 (Administration): "Code-to-department mapping, and
keywords and name patterns used for recommendations". §1.1 Table 1: the department admin "manages the department's
users, codes and keywords". Annexure B: the "Department mapping" mock-up ("The administration screen where standing
counsel codes, as they appear in the cause list, are mapped to departments (Sections 4.1 and 5.11)"). CLAUDE.md:
recommend-and-claim; "the super admin can change the weights and bands from the application".

Backlog row 50: the department mapping screens split out of row 12 at approval (owner, 12 Oct 2026): counsel codes
with the unmapped-codes panel, keywords and name patterns, the watchlist, and the scoring settings (weights and bands,
editable by the super admin, with `expected_version` and history); weight fields only with `admin.scoring`; designed
as decision 12 of `docs/design/portal-cases.md`. It carries from row 12: the `/admin/mapping/{codes,keywords,
watchlist,scoring}` routes, the "Department mapping" Administration tab and its functions in `ADMIN_FUNCTIONS`,
`MAPPING_TABS`, the mapping strings, `src/components/admin/mapping/*`, and the tests
`components/admin/mapping.test.tsx` and the shell test that the Department mapping tab shows by its functions.

In place today (used, not rebuilt; `recommend-and-claim` decisions 13, 14, 19, 21, router
`backend/aslms/api/routers/matching.py`): `GET | PUT /admin/scoring-settings` and `GET …/history`;
`/admin/counsel-codes` (list with `office`, `q`, `include_inactive`; create; `PATCH` office, notes, weight;
deactivate / reactivate) and `GET /admin/counsel-codes/unmapped`; `/admin/keywords` and `/admin/name-patterns` (list
with `office`, `include_inactive`; create; `PATCH` weight only; deactivate / reactivate); `/admin/watchlist` (list;
add with optional office, reason and weight, answering `dossier_queued`; `PATCH` reason and weight; deactivate /
reactivate). The services enforce every rule: the function, the caller's office subtree (generic State codes readable
by every holder of `admin.counsel_codes`, writable only where the root office is in scope), `admin.scoring` for any
weight, regex safety, duplicates, the root office only for generic codes, a watchlist entry below the root, the
scoring-settings ranges, the required reason and the stale `expected_version` (409); each write writes its audit
row (`counsel_code.*`, `keyword.*`, `name_pattern.*`, `watchlist.*`, `scoring_settings.update`) and a
`config_changed` event. Rule changes are picked up by the 15-minute `rescore-dirty` beat; a scoring-settings save
also dispatches the rescore at once; a watchlist change rescores its held case inline. The portal shell and row 12
give the relay, TanStack Query, the UI kit (`Table`, `Tabs`, `Dialog`, `ConfirmDialog`, `TextField`, `SelectField`,
`CheckField`, `Badge`, `Notice`, `ErrorBanner`), `can()`, `isSuperAdmin()`, `messages.ts`, `format.ts`, `useAction`,
`AdminFrame` with `adminTabsFor`, and `CaseLink`.

This item draws screens over those endpoints. It changes no API, no table and no function.

Not covered: the "Codes shared by more than one department" box of the mock-up (decision 10); paging and a server-side
text filter on the rule lists and the regex complexity guard (row 20 `recommend-and-claim-hardening`); department
discovery by party name (row 19); the per-case score breakdown `GET /admin/matching/cases/{ref}/scores` on the case
page (not asked for; may be proposed later).

## Decisions
Decision 12 of `portal-cases` (approved by the owner on 12 Oct 2026 and moved here) is kept in substance; the points
below restate it and settle what it left open. Nothing deviates from the plan.

1. **Routes.** `/admin/mapping` (opens the first mapping tab the login may read, as `/admin` does),
   `/admin/mapping/codes`, `/admin/mapping/keywords` (keywords and name patterns on one page, both under
   `admin.keywords`), `/admin/mapping/watchlist`, `/admin/mapping/scoring`. One route per tab so each is linkable and
   the back button works (portal-cases decision 1). `CRUMBS` gains `mapping` "Department mapping", `codes` "Counsel
   codes", `keywords` "Keywords and name patterns", `watchlist` "Watchlist", `scoring` "Scoring". Alternative: tabs
   in a query parameter (not linkable per tab).
2. **Navigation and tab functions.** `src/lib/routes.ts` gains `MAPPING_FUNCTIONS = ["admin.counsel_codes",
   "admin.keywords", "admin.watchlist", "admin.scoring"]` and
   `MAPPING_TABS` (in a plain module, so a server page may import it — the `/admin/tickets` lesson of 11 Oct):
   | Tab | Path | Shows with |
   |---|---|---|
   | Counsel codes | `/admin/mapping/codes` | `admin.counsel_codes` |
   | Keywords and name patterns | `/admin/mapping/keywords` | `admin.keywords` |
   | Watchlist | `/admin/mapping/watchlist` | `admin.watchlist` |
   | Scoring | `/admin/mapping/scoring` | `admin.scoring`, `admin.counsel_codes` or `admin.keywords` (the API's read rule) |

   `ADMIN_TABS` gains `{key: "mapping", label: "Department mapping", href: "/admin/mapping", functions:
   MAPPING_FUNCTIONS}` after Designations. `ADMIN_FUNCTIONS` (the Administration entry of the sidebar) becomes the six
   functions it lists today plus `MAPPING_FUNCTIONS`, so a login holding only a mapping function (for example the
   central operator's `admin.watchlist`, if `users.view` were removed by override) still reaches Administration. The
   Designations tab, which uses `ADMIN_FUNCTIONS` today, keeps exactly its present six functions through a new named
   constant `PEOPLE_ADMIN_FUNCTIONS`, so the change does not widen it. Helper `mappingTabsFor(me)` as `adminTabsFor`.
   Showing a tab is convenience only; the API decides every read and write (403 shows the API's message).
3. **Weights appear only with `admin.scoring`** (owner's rule). On every rule screen the table shows the effective
   weight read-only for everyone (the API's `effective_weight`, three decimals, marked "setting" when
   `weight_override` is null and "override" otherwise). The override input ("Weight override — leave blank to use
   the setting for this kind") and the "Clear override" action exist in the create and edit forms only when
   `can(me, "admin.scoring")`. A request carries `weight` only when that input was changed: a number to set, `null` to
   clear; otherwise the key is left out (the API reads a missing key as "no change" and refuses any `weight` key,
   even `null`, without `admin.scoring`). The portal never sends `weight` for a login without the function.
4. **Office pickers.** A login holding `users.view` picks the office from `GET /admin/offices` (the active offices of
   its scope, by path, shown as "name (code)", indented by depth). A login without `users.view` types the office
   code; the API validates it (400 "no such office"). The office list is the `users.view` scope, which can differ from
   the mapping function's scope; an office outside the latter is refused by the API (403 "the office is outside your
   offices"), shown as given. The rule lists have an office filter (sent as `office`, which the API applies to the
   office and its sub-offices) when the picker has more than one department, and an "Include deactivated" box
   (`include_inactive`).
5. **Counsel codes tab** (`admin.counsel_codes`; Annexure B "Department mapping").
   - Table: code (monospace), office, effective weight, generic State, status, notes, updated. Default order the
     API's (by code). Filter by code (`q`, server-side, normalised by the API) and office.
   - Add form: code, office, notes (≤ 4000), weight override (decision 3). Hint: "Enter the code exactly as it appears
     in the advocate column of the cause list (for example SC, EDU). It is stored normalised." The API stores the
     normalised code and answers 409 when the code is already mapped (the message names the office).
   - **Generic State codes follow from the office.** The API requires the root office exactly for generic codes and
     refuses either without the other. The form therefore sends `is_generic_state: true` exactly when the chosen
     office is the root office (the one whose `path` has no `/`), and shows under the picker "A code mapped to the
     State is generic: it is recognised but recommends no department." The root appears in the picker only for a
     login whose scope holds it (the super admin, a State-tier login). Alternative: a separate checkbox (two inputs
     that must agree, and the API refuses every disagreement).
   - Edit (dialog): office, notes, weight override. `is_generic_state` is not editable (the API has no such field; a
     generic code is changed by deactivating it and adding a new mapping). Deactivate / Reactivate with a
     confirmation: "The code stops (or starts) counting at the next rescore, within 15 minutes. Cases already claimed
     stay with their department." Rows of generic codes are read-only (no actions) unless the root office is in the
     login's picker; the API decides in any case.
   - **Unmapped codes panel** ("Codes seen in cause lists but not mapped", `GET /admin/counsel-codes/unmapped?
     limit=100`): collapsed under the table and read when first opened, not on every page load (the query scans every
     cause-list entry; see Verification step 6). Columns: code, entries (cause-list entries plus current dossier
     advocate rows, as the API counts), last listed, an example case. "Map" fills the add form's code and moves focus
     to its office picker; nothing is mapped until the user saves. The notice "Nothing is mapped automatically" heads
     the panel. A timeout or 5xx shows the API's message with a Retry button.
6. **Keywords and name patterns tab** (`admin.keywords`). Two tables on one page, each with its own add form.
   - Keywords: keyword, office, effective weight, status, updated. Add: keyword (≤ 200), office, weight override. Hint:
     "Words found in party names, such as a department or designation (for example DIRECTOR OF SECONDARY EDUCATION).
     Stored in upper case."
   - Name patterns: pattern, kind, office, effective weight, status, updated. Add: pattern (≤ 300), kind (Exact — the
     whole party name; Prefix — the start of the party name; Regular expression — checked by the server), office,
     weight override. A refused regex shows the API's reason (400).
   - Edit is the weight override only (the API's `PATCH` takes nothing else), so the Edit action shows only with
     `admin.scoring`. A wording change is made by deactivating the rule and adding a new one; adding a rule that
     exists deactivated reactivates it (the API's behaviour, audited as `reactivate`), and the screen says so when the
     answer's row was already known. Deactivate / Reactivate with the confirmation of decision 5.
7. **Watchlist tab** (`admin.watchlist`).
   - Table: CNR (monospace), case, office, reason, effective weight, status, updated.
   - Add: CNR, office, reason (≤ 2000), weight override. The CNR is trimmed and upper-cased and checked against
     `^[A-Z]{4}\d{12}$` (the API's `CNR_RE`: four letters and twelve digits) before sending; a malformed CNR never
     reaches the API. The office is optional: left blank, the API uses the login's only department and answers 400
     `office_code is required: …` when the login has none or several, shown as given with the picker highlighted.
     The root office is not offered (the API refuses it).
   - After a save: `dossier_queued: true` → "This case is not held yet: its court details are queued and it will be
     scored when they arrive"; otherwise "The case was scored again now". Watchlist changes rescore the held case at
     once (unlike rules, which wait for the beat), so the "within 15 minutes" line is not shown here.
   - Edit: reason and weight override. Deactivate / Reactivate with a confirmation.
   - **Case references link through search, not to the case page.** The watchlist's `case_ref` and the unmapped
     panel's `example_case_ref` carry no visibility flag, and a department often watches a case it cannot open yet
     (in the pool or owned elsewhere). Each is rendered as a link to `/search?q=<ref_no>`: search opens the case page
     directly when the case is visible (portal-cases decision 9) and otherwise shows the court-public summary with
     Claim when `claimable`. This keeps portal-cases decision 2 (a link never leads to a 404). Alternative: an API
     change adding `case_visible` to both answers (more surface for the same result).
8. **Scoring tab** (Annexure B; CLAUDE.md: "the super admin can change the weights and bands from the application").
   - Read (`admin.scoring`, `admin.counsel_codes` or `admin.keywords`): the current version, valid from, by whom and
     why, the engine version; the five weights (counsel code, name pattern, watchlist, linked case, keyword) and the
     two thresholds (strong, possible) as stored, three decimals. A short fixed explanation: "Within a kind the
     strongest signal counts; across kinds the signals combine, so two weaker signals together can reach a stronger
     band. A score at or above Strong is a strong recommendation, at or above Possible a possible match, below it the
     case stays in the unclaimed pool. No case is assigned automatically." Version 0 (no saved row; the API's built-in
     defaults) is shown as "Built-in defaults, never saved".
   - Edit (`admin.scoring` only; without it the values are read-only and no form or history is shown): seven number
     inputs (step 0.001), a required reason (≤ 2000), Save. The browser checks each weight in (0, 1] and
     `0 < possible < strong ≤ 1` for convenience; the API checks again and its 400 message is shown as given. The
     request is `PUT /admin/scoring-settings {weights {all five}, thresholds {strong, possible}, reason,
     expected_version}` with `expected_version` = the version the form was loaded from. A confirmation dialog repeats
     the old and new values side by side before sending.
   - Answers: `changed: false` → "Nothing changed; no new version was saved." `changed: true` → "Saved as version N.
     Recommendations are rescored within 15 minutes" (and "rescoring has started" when `rescore_dispatched`). 409 →
     "The settings were changed by someone else and have been reloaded; review them and save again": the current
     settings and the history are re-read, the inputs take the new values, and the typed reason is kept.
   - History (`admin.scoring`): `GET /admin/scoring-settings/history`, newest first, 50 a page with the API's `total`:
     version, valid from and to, by, reason, the seven values, each value that differs from the next older version
     marked. The portal never computes a band of a stored score (portal-cases decision 5); this tab shows only the
     settings themselves. Alternative considered and left out: an "alone gives" preview per weight (a second copy of
     the band rule in TypeScript).
9. **Saving and freshness.** After every rule write the screen shows "Takes effect at the next rescore, within 15
   minutes" (the API's `applies_within_minutes`) and invalidates the list it changed; a scoring save invalidates the
   settings, the history and every rule list (effective weights follow the settings), plus the inbox counts and lists
   (portal-cases decision 16). Every write runs through `useAction` (button busy, the API's message in the banner);
   409 on a rule ("already mapped", "already exists", "another change happened at the same time") shows the message
   and re-reads the list. No write is repeated automatically.
10. **The mock-up's "Code is shared by more than one department" box is not built** (as portal-cases decision 12): a
    code maps to one office (`counsel_codes.code` is unique; plan §4.1 "each code is mapped to its department"); a
    code common to all government cases is mapped to the State as generic and scores nothing. A difference from the
    indicative mock-up only.
11. **Look, language and checks as the shell.** CSS Modules and the shell's tokens, the UI kit, WCAG 2.1 AA (each
    table with a caption, each input labelled, the confirmation dialogs focus-trapped as `Dialog` already is), strings
    in `messages.ts` under `T.mapping`, IST dates through `format.ts`, monospace codes and CNRs. Pages are checked in
    the Compose `web` service, not only by unit tests (decisions log 11 Oct; row 43).

## Data
No table, column, constraint, reference code or `Permission` is added; no migration. `docs/schema/schema.md` and
`docs/schema/napix_coverage.md` are unchanged. The portal stores nothing; every value is read from and written to
the existing tables (`counsel_codes`, `office_keywords`, `office_name_patterns`, `office_watchlist`,
`scoring_settings`) through the existing API.

## Services
Backend: no change. The screens call the router `api/routers/matching.py` over `services/matching_rules.py`,
`services/scoring_settings.py` and `services/matching.py::unmapped_codes`, and `api/routers/offices.py::list_offices`.

Frontend (`frontend/`):
- `src/lib/routes.ts`: `PEOPLE_ADMIN_FUNCTIONS` (the six functions of today's `ADMIN_FUNCTIONS`),
  `MAPPING_FUNCTIONS`, `ADMIN_FUNCTIONS = [...PEOPLE_ADMIN_FUNCTIONS, ...MAPPING_FUNCTIONS]`, the `mapping` entry of
  `ADMIN_TABS`, Designations on `PEOPLE_ADMIN_FUNCTIONS`, `MAPPING_TABS`, `mappingTabsFor(me)`, the five `CRUMBS`
  (decisions 1, 2).
- `src/lib/mapping.ts` (plain module): `CNR_PATTERN` and `isCnr(value)`; `weightBody(changed, value)` returning `{}`
  or `{weight: number | null}` (decision 3); `isRootOffice(office)` (path without `/`); `scoringErrors(values)` for
  the browser-side checks of decision 8; `changedFields(version, older)` for the history marks.
- `src/lib/messages.ts`: `T.mapping` (tab names, column heads, hints, confirmations, the after-save lines, the 409
  reload line, the dossier-queued lines, the generic-code line, the scoring explanation).
- `src/lib/api/hooks.ts`: `useScopedOffices(enabled)` (`GET /admin/offices`, only with `users.view`, 10 minutes),
  `useScoringSettings()`.
- `src/components/admin/mapping/`: `MappingFrame` (sub-tabs by `mappingTabsFor`, `MappingIndex` redirect),
  `OfficePicker` (decision 4), `WeightField` and `WeightCell` (decision 3), `RuleStatusActions` (deactivate /
  reactivate with `ConfirmDialog`), `CounselCodes` with `UnmappedCodes`, `Keywords` (both tables), `Watchlist`,
  `Scoring` with `ScoringHistory`; `mapping.module.css` if the kit's classes do not suffice.
- Pages: `src/app/(portal)/admin/mapping/layout.tsx` (`MappingFrame`), `page.tsx` (`MappingIndex`),
  `codes/page.tsx`, `keywords/page.tsx`, `watchlist/page.tsx`, `scoring/page.tsx` (each a server page rendering its
  client component; constants imported only from plain modules).
- `src/components/admin/AdminFrame.tsx`: no logic change (the new tab arrives through `ADMIN_TABS`).

Audit and events: the portal writes none. Every action it offers is an existing API call that already audits and
emits `config_changed`: `counsel_code.create|update|deactivate|reactivate`, `keyword.*`, `name_pattern.*`,
`watchlist.*`, `scoring_settings.update`. Reads write nothing.

## API
No new or changed endpoint. Used as they are:

| Method, path | Function required (`Permission`) | Used by | Visibility (server) |
|---|---|---|---|
| `GET /admin/counsel-codes` | `admin.counsel_codes` | codes table (`office`, `q`, `include_inactive`) | rules in the caller's subtree plus generic codes; all for the super admin |
| `POST /admin/counsel-codes` | `admin.counsel_codes` (+ `admin.scoring` when `weight` sent) | add form | office in scope; root office only for generic codes |
| `PATCH /admin/counsel-codes/{id}` | `admin.counsel_codes` (+ `admin.scoring` when `weight` sent) | edit dialog (`office_code`, `notes`, `weight`) | old and new office in scope; unknown or out of scope → 404 |
| `POST /admin/counsel-codes/{id}/deactivate`, `…/reactivate` | `admin.counsel_codes` | status actions | in scope |
| `GET /admin/counsel-codes/unmapped` | `admin.counsel_codes` | unmapped panel (`limit=100`) | court text only |
| `GET`, `POST /admin/keywords`; `PATCH /admin/keywords/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` (+ `admin.scoring` when `weight` sent) | keywords table and form | caller's subtree |
| `GET`, `POST /admin/name-patterns`; `PATCH /admin/name-patterns/{id}`; `…/deactivate`, `…/reactivate` | `admin.keywords` (+ `admin.scoring` when `weight` sent) | patterns table and form | caller's subtree |
| `GET`, `POST /admin/watchlist`; `PATCH /admin/watchlist/{id}`; `…/deactivate`, `…/reactivate` | `admin.watchlist` (+ `admin.scoring` when `weight` sent) | watchlist table and form | caller's subtree; root office refused |
| `GET /admin/scoring-settings` | `admin.scoring`, `admin.counsel_codes` or `admin.keywords` | scoring tab (read) | State-wide values |
| `PUT /admin/scoring-settings` | `admin.scoring` | scoring form | super admin by default; 409 on a stale `expected_version` |
| `GET /admin/scoring-settings/history` | `admin.scoring` | history table (`limit=50`, `offset`) | |
| `GET /admin/offices` | `users.view` | office pickers | the caller's scope |
| `GET /cases/search` (through `/search?q=`) | `cases.view_scope` or `cases.view_all` | watchlist and unmapped case links (decision 7) | portal-cases rules |

Web server: no new route; the relay passes these paths as it does every API path.

## Jobs
None. Rule changes are rescored by the existing 15-minute `rescore-dirty` beat; a scoring save dispatches
`aslms.rescore_if_dirty` through the API; watchlist changes rescore inline. The screens only say so.

## Tests
Backend: none new (no backend change). `unit/test_openapi_snapshot.py` stays green and `npm run gen:api` gives no diff.

Frontend (Vitest, the `fakeApi` / `browserApi` helpers):
- `components/shell/shell.test.tsx` (added cases): a department admin (`admin.counsel_codes`, `admin.keywords`,
  `admin.watchlist`) sees the "Department mapping" tab; a department officer does not; a login holding only
  `admin.watchlist` sees Administration with the Department mapping tab and without Designations; the super admin
  sees it; the mapping sub-tabs follow the functions (Watchlist only for `admin.watchlist`; Scoring for
  `admin.keywords` without `admin.scoring`).
- `lib/routes.test.ts` (new or added): `ADMIN_FUNCTIONS` contains the four mapping functions; Designations'
  functions equal `PEOPLE_ADMIN_FUNCTIONS`; `mappingTabsFor` for each function alone.
- `lib/mapping.test.ts` (new): `isCnr` accepts four letters and twelve digits after trim and upper case and refuses
  15 or 17 characters, digits in the first four places and letters in the last twelve; `weightBody` omits the key
  when unchanged, sends `null` on clear and a number on set; `isRootOffice`; `scoringErrors` (weight 0 and 1.001
  refused, 1 accepted, possible equal to strong refused, strong 1 accepted); `changedFields` marks only differing
  values.
- `components/admin/mapping.test.tsx` (new):
  - weight inputs and Clear override shown only with `admin.scoring`; without it a create request carries no
    `weight` key and an edit request of a counsel code carries no `weight` key; with it an unchanged override is
    not sent and a cleared one sends `null`;
  - keywords and patterns offer no Edit without `admin.scoring`; Deactivate asks for confirmation and posts to
    `…/deactivate`; the "within 15 minutes" line follows a rule save; a 409 shows the API's message and re-reads the
    list;
  - choosing the root office in the code form sends `is_generic_state: true` and shows the generic line; any other
    office sends `false`; generic rows show no actions when the root is not in the picker;
  - the office picker lists `/admin/offices` with `users.view` and is a text field without it;
  - the unmapped panel is not requested until opened; "Map" fills the code and sends nothing; its example case and the
    watchlist's case link to `/search?q=<ref>`;
  - the watchlist refuses a CNR that is not four letters and twelve digits without calling the API; `dossier_queued`
    true and false show their lines; a 400 `office_code is required` shows the message; the root office is not offered;
  - scoring: read-only values for `admin.keywords` without `admin.scoring` (no inputs, no history request); with
    `admin.scoring` the save sends all five weights, both thresholds, the reason and `expected_version` equal to the
    loaded version; the reason is required; the browser refuses possible ≥ strong without calling the API;
    `changed: false` shows "Nothing changed"; a 409 re-reads settings and history, shows the reload message, keeps the
    reason; history lists versions with `total` and marks changed values; version 0 shows "Built-in defaults".

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green (unchanged
   backend); `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`. `docker compose build web` when the registry is reachable (row 51); otherwise the branch's
   standalone server as in portal-cases deviation 9, recorded in the cycle report.
3. `portal_smoke.py` (against the Compose `web` service, or `--base` the standalone server): every page answers 200,
   including the five new ones (`/admin/mapping`, `/admin/mapping/codes`, `…/keywords`, `…/watchlist`, `…/scoring`),
   and the server log has no error line.
4. Signed in as a department admin (for example of `EDU`): Administration shows Department mapping; Counsel codes,
   Keywords and name patterns, Watchlist and Scoring tabs show; Scoring is read-only, with no history; no weight input
   appears anywhere. Add the counsel code `SC, EDU` (or one taken from the unmapped panel) to the department;
   `aslms audit search --action counsel_code.create --limit 1` shows the row with the browser's address. Add a
   keyword and a prefix name pattern; deactivate and reactivate the keyword (audit rows `keyword.deactivate`,
   `keyword.reactivate`). After `aslms rescore` (or 15 minutes) the department's Recommended badge reflects the
   mapping (cases listed with that code appear with the `Code: SC, EDU` chip).
5. Signed in as the super admin: weight inputs appear; set and then clear an override on the code (two
   `counsel_code.update` rows, the effective weight returning to the setting). On Scoring, change the keyword weight
   with a reason: version N+1, history lists both versions with the change marked, `scoring_settings.update` in the
   audit. In a second window still showing version N, save again: the 409 reload message appears and nothing is
   saved. Restore the old value (version N+2).
6. Open the unmapped panel on the dev database holding the historical load and record in the cycle report how long
   `GET /admin/counsel-codes/unmapped?limit=100` takes (browser network panel or `curl -w "%{time_total}"` through
   the relay). If it exceeds the API's statement timeout or 10 seconds, record it for row 20 (a summary table or an
   index for the unmapped report); the panel's error and Retry handling must show cleanly either way.
7. Watchlist: as the department admin, add a CNR of a held case (from `aslms cases show`): "scored again now" and
   the case appears in the department's Recommended tab with the `Watchlist` chip when its score reaches Possible.
   Adding a CNR not yet held queues a dossier (`dossier_queued`); with `NAPIX_ENABLED=false` (the default) no
   `napix_call_log` row is written by the save itself.

## Open questions
None.
