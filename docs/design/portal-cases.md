# Design: Portal — case inbox, search, case detail (timeline, orders, parties, notes, documents), claim / dismiss / transfer

```
slug: portal-cases
status: approved
author: architect
date: 2026-10-12
approved_by: owner (nayanlhuzuri) on 2026-10-12
```

> **Owner's decision at approval (12 Oct 2026): the department mapping screens are split out** into a new backlog row `portal-mapping` (row 50). In this row do **not** build decision 12, the `/admin/mapping/*` routes, the "Department mapping" Administration tab (decision 3), `MAPPING_TABS`, the mapping strings, `src/components/admin/mapping/*` or `components/admin/mapping.test.tsx`. Everything else in this note is approved as written. For Verification step 5, map a counsel code through the API or the `aslms` CLI instead of the screen.

## Context
The plan, §5.2 (Search): "Search by CINO, case number, party name or advocate name, with filters for status, year,
case type and department. The portal's own database is searched first; if the case is not found, NAPIX search APIs
are queried live, and the case is fetched and stored. Results respect visibility rules: users see full details only
for cases within their access." Links to the case page and the inbox "to claim a case found through search".
§5.3 (Case detail page): tabs; overview (status, next hearing, court and bench, registration details, owning
department, current custody); parties and advocates; hearings and proceedings timeline; orders with view and
download; linked cases "with a relationship graph of appeals and connected matters"; custody and the notes and files
trail; documents; the Case Assistant. §5.4 (Department case inbox): Recommended "strongest matches first, each with
the signals behind its score, to claim or dismiss"; Claimed; Unclaimed pool "that the department can search and
claim"; Transfers. §4.2 / Table 6: bands, "in every case, the department decides by claiming it", suggest another
department, primary owner and watchers, unclaimed cases visible to the central operator. §5.6: orders and documents
"can be viewed and downloaded from the case page, subject to their visibility"; "text is extracted so orders can be
searched by content". §5.11: "Code-to-department mapping, and keywords and name patterns used for recommendations".
Annexure B: the "Case inbox", "Case detail", "Case documents and upload" and "Department mapping" mock-ups (score
badge with STRONG / POSSIBLE, signal chips, Claim / Dismiss / Suggest department, the notice "No case is assigned
automatically", tabs Recommended / Claimed / Unclaimed pool / Transfers with counts, a cause-list date filter; the
case header with status, type, number, parties, CNR, court and registration date; the overview cards Next hearing,
Parties and advocates, Proceedings, Custody, Latest order, Ownership; the documents tab grouped Court orders / Court
filings / Internal documents with "In Case Assistant" and visibility badges; the mapping table of codes).

Backlog row 12: "Portal: case inbox, search, case detail (timeline, orders, parties, notes, documents),
claim/dismiss/transfer". `portal-shell` (Context) also gave this row "the matching screens (counsel codes, keywords,
patterns, watchlist, scoring settings)", and `recommend-and-claim` left "the portal screens including the
scoring-settings screen (`portal-cases`)". Portal-shell decision 13 promised the header search box with this row and
asked that case references stop being plain text once the case page exists.

In place today (used, not rebuilt): every endpoint this item needs. `cases-api`: `GET /cases` (the visible work
list), `/cases/search` (summaries of any case with `visible`, `owner_office_code`, `in_pool`, `claimable`,
`dossier_status`), `/cases/{ref}` (overview with `custody`, `stage`, `access_basis`, `claimable`, `counts`),
`/parties`, `/hearings`, `/orders`, `/listings`, `/links`, `/links/graph`, `/timeline`; `POST /cases/search-court`
and `/cases/{ref}/fetch-court` (`cases.search_court`, quota guard, audited). `recommend-and-claim`: `/inbox/recommended
| claimed | pool | transfers | counts`, `GET /cases/{ref}/ownership`, `POST /cases/{ref}/claim | dismiss | suggest |
allot | take-over | stop-watching | transfers`, `POST /transfers/{trf}/accept | decline | withdraw`, `/admin/scoring-
settings` (+ history), `/admin/counsel-codes` (+ `/unmapped`), `/admin/keywords`, `/admin/name-patterns`,
`/admin/watchlist`. `documents-uploads`: `GET /cases/{ref}/documents`, `/cases/{ref}/orders/{id}/file`,
`/documents/{doc}/file` (`inline` with `documents.view`, `attachment` with `documents.download`; the API sends
`X-Content-Type-Options: nosniff` and, inline, `Content-Security-Policy: sandbox`), `/documents/search`.
`custody-workflow`: `GET /cases/{ref}/notes` (note visibility applied, drafts never listed), `/custody/recipients`.
The portal shell: the backend-for-frontend relay, TanStack Query, the UI kit, `can()`, `messages.ts`, `format.ts`,
the `built` flags in `routes.ts`. Every rule (functions, scope, visibility, recommend-and-claim, no return to the
pool) is already enforced by the API; this item draws screens over it and adds five small read-only API changes
(decision 14).

Not covered here: sending the file, recall, tracking, stages, writing notes, drafts, uploads, document visibility
changes and archiving, the case alerts tab, the alerts list and the hearing calendar — row 13 `portal-workflow` (this
item shows the custody card, the stage, the notes trail and the documents read-only, and leaves the "Upload
document" and "Hand over" buttons of Annexure B to row 13); the Case Assistant tab and button — row 14; next dates
read from orders on the "Latest order" card — rows 26 and 37; NAPIX search by advocate and filing number — row 21
(searched locally meanwhile); the reviewed merge of provisional cases — row 46; the reports screen — row 39.

## Decisions
1. **Routes.** `/inbox/{recommended|claimed|pool|transfers}` (`/inbox` opens the first tab the login may read),
   `/search`, `/cases/[ref]` with one route per tab (`/cases/[ref]`, `/hearings`, `/orders`, `/parties`,
   `/documents`, `/links`, `/notes`, `/timeline`, `/details`). (`/admin/mapping/{codes|keywords|watchlist|scoring}`
   moved to row 50 `portal-mapping` at approval.)
   `[ref]` is the case's `ref_no` in the dash form (the form the notification mails already use,
   `<PORTAL_BASE_URL>/cases/<ref>`); the API also resolves an id or a CNR, so a pasted CNR URL works. One helper
   `refPath()` (moved from `Tickets.tsx` to `src/lib/refs.ts`) writes every link. Alternatives: tabs in a query
   parameter (not linkable per tab in the browser history), a single page with client tabs (the same). Filters live in
   the query string so a list can be bookmarked and the back button restores it.
2. **Every case reference becomes a link** through one `CaseLink` component (case number, else `ref_no`, monospace,
   CNR as the title): the dashboard's `CaseRef`, the data console's duplicates list, the exit dialog's items, and all
   new screens. A summary with `visible: false` (search results, linked cases) is rendered as text, never as a link,
   because opening it answers 404.
3. **Navigation.** "Case inbox" and "Search" get `built: true`. "Search" shows with `cases.view_scope` or
   `cases.view_all`. "Case inbox" shows with `cases.view_all`, or when `/me.memberships` holds a membership with a
   `department_code` (standing counsel and other logins without a department use Search, whose default list is their
   visible cases). The header search box (Annexure B: "Search by CINO, case number or party name") appears for case
   readers and opens `/search?q=…`. (The "Department mapping" Administration tab and its functions in
   `ADMIN_FUNCTIONS` moved to row 50 `portal-mapping` at approval.)
4. **Inbox department.** The inbox is read for one department at a time (`?department=CODE`, sent to the API as
   `office`). The selector lists the departments of `/inbox/counts` (one block per department the login works in);
   a holder of `cases.view_all` may also pick any active department from `GET /custody/recipients` (no
   `department`), and then reads it as the API allows (read-only lists, no action buttons unless the login also works
   there). With one department the selector is not shown. A tab whose count is `null` in that department's block is
   not shown (the API's rule, not the portal's); the pool tab follows `pool_with_hearing_7d` being non-null. Tab
   badges: Recommended = `recommended_high + recommended_medium`, Claimed = `claimed_active`, Transfers =
   `transfers_in_open`; the pool tab has no badge (the API counts only pool cases with a hearing in 7 days) and shows
   its `total` above the list.
5. **Recommended tab** (Annexure B "Case inbox"). The notice "No case is assigned automatically. A case becomes the
   department's only when claimed." stays at the top. Filters: match strength (All / Strong / Possible → `band`), cause
   list date (Today / Last 7 days / Last 30 days / Any → the new `listed_from` / `listed_to`, decision 14a), words
   (`q`). Each row: the score as stored (three decimals) in a badge whose colour and label (STRONG / POSSIBLE) come
   from the API's `band`, never from the portal comparing numbers (the bands are the super admin's settings); the
   parties; the case number, the latest listing ("Cause list 25 Sep 2026 · Court 3 · Item 41", decision 14b); one
   chip per signal (`Code: SC, EDU`, `Keyword: …`, `Name: …`, `Linked: WP(C)/2417/2026`, `Watchlist`,
   `Suggested unit: …`, from `kind` and `matched`); "Suggested by FIN: reason" for `origin = suggestion`;
   "Owned by FIN" when `current_owner_code` is set. Actions: Claim, Dismiss, Suggest department (decision 7). Order is
   the API's (strong first, score, next hearing).
6. **Claimed, Pool and Transfers tabs.** Claimed: Active / Disposed (`case_state`), role (primary / watcher), unit,
   officer, words; each row shows the unit and officer it is allotted to and an "Allot" action with `cases.allot`.
   Pool: words, listed from / to, status, case type, year, minimum score, "State is a party" (`state_party`); each row
   shows the best score and the department it was for, the departments that dismissed it, the next hearing; actions
   Claim (`cases.claim`) and Suggest department (`cases.suggest_elsewhere`, how the central operator follows up an
   unclaimed case, plan §4.2). Transfers: In / Out, status (requested / accepted / declined / withdrawn); In rows with
   status requested offer Accept / Decline (`cases.transfer_decide`), Out rows offer Withdraw
   (`cases.transfer_request`). Lists page 50 at a time with the API's `total`.
7. **Ownership actions follow the API exactly; the department always decides.** No screen claims, allots or
   transfers anything without the user pressing the button and confirming a dialog; nothing is pre-selected that
   would claim for a department the user did not choose.
   - Claim: a dialog with an optional note (≤ 500) and, with `cases.allot` in that department, an optional unit and
     officer (`unit_code`, `officer_user_id`, chosen from `GET /custody/recipients?department=…`, decision 14d). When
     the case already has a primary owner the dialog says "This case is owned by X; claiming adds your department as
     a watcher" (plan §4.2). From the inbox the request always carries `office_code` = the selected department; from
     the case page the department comes from `actions.claim_departments` (decision 8): one → used, several → chosen in
     the dialog, `null` (the super admin) → chosen from every active department.
   - Dismiss: optional reason (≤ 500). Suggest department: target department (every active department but the
     acting one) and a required reason. Allot: unit and / or officer, with "clear" for each. Take over: confirmation
     naming the current officer, sent with `expected_officer_user_id` so a stale screen gets 409 `stale`. Stop
     watching: required reason, offered only on a watcher row. Request transfer: target department, required reason,
     "stay as a watcher" box. Accept / Decline: optional note. Withdraw: confirmation.
   - There is no "release" or "return to pool" button anywhere (owner's rule: a claimed case never returns to the
     pool; the API has no such endpoint).
   - Every refusal shows the API's code as a message (the `OwnershipConflict` codes `already_claimed`,
     `already_holder`, `not_allotted`, `not_open`, `not_primary`, `primary_cannot_release`, `stale`, `target_owns`,
     `transfer_open`, `concurrent_change`; `office_required`; the plain 400/403/404 strings shown as given; an unknown
     code falls back to the server's message), then the affected lists and the case are re-read. `office_required` (with `candidates`) opens the
     department choice instead of failing.
8. **What the case page offers comes from the server.** `GET /cases/{ref}/ownership` gains an `actions` block
   (decision 14c) saying which ownership actions the caller may take now on this case, computed by the same checks
   the actions run. The portal shows a button only when its flag is true; the API still decides on the call.
   Alternative: the portal combining `/me` functions, memberships and the ownership view (the department, primary,
   watcher, allotted-officer and open-transfer rules would be written a second time in TypeScript and drift). The
   inbox rows, whose state is fixed by the tab (a Recommended row is the department's active recommendation, an In
   transfer is to the department), show actions by the function in the selected department's membership
   (`/me.memberships[].functions`, helper `canIn(me, department, fn)`). This follows the existing `claimable`,
   `can_send`, `can_recall` and `can_manage` flags.
9. **Search** (`/search`). One box, as the API's `parse_query` (CNR, case number such as `WP(C) 4326/2025`, `ref_no`,
   party or advocate words), with filters status, year, case type (from the new `GET /reference/case-types`, decision
   14e), department (`office`), listed from / to, "only cases I can open" (`visible_only`).
   - Without words the page lists the caller's visible cases (`GET /cases`, with Active / Disposed / All and next
     hearing from / to): the work list of officers, directorate users, standing counsel and State-wide readers.
   - With words it calls `/cases/search`. Visible rows link to the case; others show the court-public summary, the
     owning department and "in the unclaimed pool", with Claim when `claimable` (decision 7). A single visible result
     matched by `cnr` or `ref_no` opens the case page directly.
   - "Search the court" (`cases.search_court`): offered under the results, prominently when nothing was found
     locally, as the plan's local-first flow (Figure 7). Three forms as the API: CNR; case type + number + year; party
     name + year + pending / disposed / both. The answer shows the cases found (now stored, so the next local search
     finds them), the NAPIX calls used, the cases created, and unmatched party rows as plain text; a party-search row
     without a dossier offers "Fetch details" (`POST /cases/{ref}/fetch-court`). Errors in words: `napix_off` (court
     search is switched off), `napix_budget` and `search_limit` (with the wait from `retry_after`),
     `napix_unavailable`, `napix_timeout`, `not_found_at_court`, `already_fetched` (link to the case holding that CNR),
     `bad_input`. The button is disabled while a search runs; a court search is never repeated automatically.
   - "Order and document text" tab (`documents.view`): `GET /documents/search` with the API's snippet and the case
     link (plan §5.6 "searched by content"; visibility applied by the API).
10. **Case page** (Annexure B "Case detail"). Header: status badge, case type, case number (serif, large), parties,
    CNR (monospace), court, registration date, owner department; "Provisional — no CNR yet" for a provisional case
    (never a made-up CNR); a merged case (`merged_into_ref_no`) shows a link to the surviving case instead of tabs. A
    case the API answers 404 shows "No such case, or you do not have access to it" (one message for both, so the page
    reveals nothing). When `dossier_status` is not fetched: "Court details not yet fetched" and, with
    `cases.search_court`, "Fetch from the court" (`fetch-court`). Tabs with the API's `counts` as badges:
    - Overview: Next hearing (date, "Within 48 h" / "This week" badge from IST dates, purpose, court and item from the
      latest listing, source); Parties and advocates (first petitioner and respondent with advocates, "+ n more" to the
      Parties tab); Proceedings (the five latest hearings, link to Hearings); Custody (the API's `custody` card: holder
      office and officer, pending action, since, due date with overdue days, sent by, remark when given — read-only
      here, row 13 adds Send and Recall); Stage (label and phase); Latest order (date, kind, View); Ownership
      (`/cases/{ref}/ownership`: primary owner with unit, officer and claimed date, watchers, the department's own
      recommendation with its signals, other departments' recommendations when the API returns them, the open
      transfer, and the action buttons of decision 8); a muted line "You see this case as: …" from `access_basis`.
    - Hearings: hearings (business date, purpose, bench, next date, business text, short order) and, below, cause-list
      appearances (`/listings`: date, list type, bench, court, item, section, connected, counsel codes, remarks).
    - Orders: number, date, kind, judge, `download_status`; View (inline, `documents.view`) and Download
      (`documents.download`) when stored; "not yet published" / "fetch pending" otherwise.
    - Parties: every party and advocate, former ones behind "Show former" (`include_former`), counsel codes shown.
    - Documents: read-only, grouped Court orders / Court filings / Internal documents (`doc_group`), each with type,
      date, description, uploader and office, size and pages, "In Case Assistant" / "Not sent to SourceTrace"
      (`assistant_available`, `sourcetrace_status`), visibility badge, text status; View / Download by function;
      "Show archived". The upload panel of Annexure B comes with row 13.
    - Linked cases: the list (`/links`: direction, kind, number, CNR, link source; visible ones linked) and the graph
      (decision 11).
    - Notes: the trail read-only by `seq_no`: kind, author's name, designation and office at the time, date, body,
      visibility badge, "corrects NOTE/…" and "corrected by NOTE/…" links within the page, attachments with View /
      Download through `/documents/{doc}/file`; "Hide corrected notes" (`include_superseded=false`). Writing notes and
      drafts come with row 13.
    - Timeline: `/timeline` newest first, the API's `label`, time and actor; a short line for the common event types
      (decision 13).
    - Details: every other typed field of the overview response, so each NAPIX field with a home is visible somewhere
      (CLAUDE.md "every NAPIX field is kept"): identity (filing and registration numbers and dates, first listing),
      status block (disposal fields, judgement dates, goshwara), classification (bench, coram, branch, category),
      place (state, district, FIR, police station, main matter), acts and sections, lower courts, applications,
      objections, court transfers, writ information, and the portal block (first seen, last refreshes, tracked).
    The Case Assistant tab and the Upload / Hand over buttons are not shown until rows 14 and 13.
11. **Relationship graph without a new library.** `/links/graph` (depth 2, the API's limit and `truncated`) drawn as a
    small SVG: the case in the centre column, linked cases in columns by distance, edges labelled with the link kind,
    non-visible nodes grey and not clickable. The links table above it is the accessible version. Alternatives: a
    graph library such as Cytoscape or React Flow (a large dependency for at most a few dozen nodes, and more surface
    for the CSP).
12. **[Moved to row 50 `portal-mapping` at approval — not built here]** **Department mapping screens** (Annexure B "Department mapping"), under Administration → Department mapping:
    - Standing counsel codes (`admin.counsel_codes`): the table (code, office, effective weight, generic State,
      status, updated), add / edit / deactivate / reactivate; the form says "Enter the code exactly as it appears in the
      advocate column of the cause list"; the panel "Codes seen in cause lists but not mapped" (`/unmapped`, entries,
      last listed, example case link) with "Map" pre-filling the form.
    - Keywords and name patterns (`admin.keywords`): two tables with the same actions; pattern kind exact / prefix /
      regex.
    - Watchlist (`admin.watchlist`): CNR (16 characters, checked before sending), office, reason; the held case linked;
      "details queued" when the API reports `dossier_queued`.
    - Scoring (`admin.scoring` to edit; readable with `admin.counsel_codes` or `admin.keywords`, as the API): the five
      weights and two thresholds, a required reason, `expected_version` sent (409 → "changed by someone else; reloaded"),
      history of versions with who and why; after a save "applies within 15 minutes".
    Weight fields on rules appear only with `admin.scoring` (the API refuses weights otherwise). Office pickers list
    `/admin/offices` (the caller's scope) when the login holds `users.view`, else a code field the API validates.
    After every rule save the screen repeats the API's "takes effect at the next rescore (within 15 minutes)". The
    mock-up's "Code is shared by more than one department" box is not offered: a code maps to one office
    (`counsel_codes.code` is unique, plan §4.1 "each code is mapped to its department"); a code common to all
    government cases is marked generic State and scores nothing — a difference from the indicative mock-up only.
13. **Timeline lines.** `src/lib/timeline.ts` formats a one-line detail for the common types from known payload keys
    (`next_date_changed` and `listed`: dates; `order_found` / `order_stored`: order date; `status_changed`: from → to;
    `claimed`, `allotted`, `transfer_*`, `suggested_elsewhere`, `dismissed`, `case_taken_over`: department codes and
    names given; `case_merged`: the provisional reference). Any other type shows the API's label only. The payload is
    never printed as raw JSON.
14. **Five small API changes, no schema change** (each read-only, each with tests):
    (a) `GET /inbox/recommended` gains `listed_from` / `listed_to`: recommendations whose case has a cause-list entry
    dated in the range (the mock-up's "Cause list date" filter; the pool already has the same filter).
    (b) `CaseSummaryOut` gains `last_listing: {list_date, list_type, court_no, sr_no} | null`, the latest cause-list
    entry of the case (latest date, then lowest item), computed in `inbox.summaries` in the query that already finds
    `last_listed_on`. Court-public data, the same as the listings tab. Every list using the summary gets it.
    (c) `GET /cases/{ref}/ownership` gains `actions: {claim, claim_departments, dismiss, suggest, allot, take_over,
    stop_watching, request_transfer, withdraw_transfer, decide_transfer}` (booleans; `claim_departments` a list of
    department codes, or `null` for the super admin who may name any).
    (d) `GET /custody/recipients?department=…` items gain `user_id` (allot takes a user, the list gives memberships),
    and the response gains `units: [{code, name}]` — the active offices strictly inside that department — so the claim
    and allot dialogs can offer units. Without `department` the response is unchanged.
    (e) `GET /reference/case-types`: the active case types of the High Court master (`case_type_code`, `short_name`,
    `full_name`, `type_name`), for the search filter and the court search form. Master data, court-public.
    Alternatives: client-side filtering (the inbox pages 50 rows; a date filter must be in SQL), typing case types by
    hand (the court search refuses an unknown type).
15. **Document viewing through the relay is hardened here** (taken from row 44, item 1). Viewing an order or document
    inline is new with this item, and the relay today drops the API's `X-Content-Type-Options` and
    `Content-Security-Policy` (sandbox) headers. The relay's response allowlist gains both, with a relay test. View
    opens `/api/backend/…/file?disposition=inline` in a new tab (the browser's own PDF viewer; images shown by the
    browser); Word files are download only. No PDF.js or in-page viewer. If a browser refuses to render a PDF under
    `sandbox`, the integrator records it and the View button for PDFs falls back to download; the API's sandbox is not
    removed. Row 44 keeps its other two items.
16. **Freshness.** After any write the affected queries are invalidated (inbox lists and counts, the case overview,
    ownership, timeline, the dashboard blocks). Lists are not polled; TanStack's refetch on window focus stays on, so
    a tab left open shows current data when the user returns. Case pages do not cache across sign-out (portal-shell
    decision 11).
17. **Look, language and checks as the shell.** CSS Modules and the shell's tokens, the UI kit (extended with
    `ScoreBadge`, `SignalChip`, `CaseLink`, `DefinitionList`, `ConfirmDialog`), WCAG 2.1 AA, strings in `messages.ts`,
    IST dates, monospace case numbers and CNRs. Constants shared between a server page and a client component live in
    plain modules (the `/admin/tickets` lesson of 11 Oct). Pages are checked in the Compose `web` service, not only by
    unit tests (decisions log, 11 Oct; row 43).

No deviation from the plan. Two points for the owner to confirm at approval: the department mapping screens are built
in this row (portal-shell assigned them here; they can be split into a new row if the owner prefers a smaller cycle),
and the five API changes of decision 14 plus the relay item taken from row 44. The mock-up's "shared code" box is not
built (decision 12).

## Data
No table, column, constraint, reference code or `Permission` is added; no migration. `docs/schema/schema.md` is
unchanged. `last_listing` (decision 14b) and `actions` (14c) are computed on read; `units` and `user_id` (14d) and
the case types (14e) are read from existing tables (`offices`, `user_memberships`, `case_types`). The portal stores
nothing.

## Services
Backend (Python), read-only changes:
- `services/inbox.py`: `summaries()` replaces `_last_listed` with `_last_listings(session, case_ids) -> dict[case_id,
  {list_date, list_type, court_no, sr_no}]` (`DISTINCT ON (case_id)` over `causelist_entries` ⋈ `causelists` ordered by
  `list_date DESC, sr_no`), keeping `last_listed_on`; `recommended_stmt(..., listed_from, listed_to)` adds `EXISTS`
  of an entry of the case with `list_date` in the range; `listed_from > listed_to` → `InboxError` (400).
- `services/ownership.py`: `available_actions(session, user, case) -> dict`. Each action's precondition is factored
  into a check function the action itself calls first (`_check_claim`, `_check_dismiss`, … raising the same
  `Forbidden` / `NotVisible` / `OwnershipConflict` / `OfficeRequired` they raise today); `available_actions` runs every
  check without locking or writing and maps "raises" to `False`, `OfficeRequired` to `True` (the action is possible
  once a department is named). `claim_departments`: the departments of the caller's memberships for which
  `_check_claim` passes; `None` when the caller is the super admin. No behaviour change to the actions; no audit row
  (reading).
- `services/custody.py::recipients`: items gain `user_id`; with `department`, `units` lists the active offices whose
  path is inside the department's (not the department itself), ordered by path.
- `services/reference.py::case_types(session) -> list[dict]`: active `case_types` of the High Court's `courts` row,
  ordered by `short_name`, `case_type_code`.
- `api/schemas.py`: `CaseLastListingOut`, `CaseSummaryOut.last_listing`, `OwnershipActionsOut`,
  `CaseOwnershipViewOut.actions`, `RecipientOut.user_id`, `RecipientListOut.units`, `CaseTypeOut`. `frontend/openapi.json`
  and `schema.d.ts` regenerated.

Frontend (`frontend/`):
- `src/server/relay.ts`: `RESPONSE_HEADERS` adds `x-content-type-options`, `content-security-policy` (decision 15).
- `src/lib/refs.ts` (`refPath`, moved), `src/lib/can.ts` (`canIn(me, departmentCode, fn)`), `src/lib/routes.ts`
  (decision 3; `CRUMBS` for the new segments), `src/lib/timeline.ts` (decision 13),
  `src/lib/signals.ts` (signal chip text), `src/lib/messages.ts` (inbox, search and case strings and the error
  codes of decisions 7 and 9), `src/lib/format.ts` (`hearingBadge(date)` — "Within 48 h" / "This week" from IST dates;
  the dashboard keeps using the API's `critical`).
- `src/lib/api/hooks.ts`: `useDepartments()` (`/custody/recipients`, 10 minutes), `useCaseTypes()`,
  `useInboxCounts()`, `useCase(ref)`, `useOwnership(ref)`.
- `src/components/ui`: `ScoreBadge`, `SignalChip`, `CaseLink`, `DefinitionList`, `ConfirmDialog`.
- `src/components/inbox/*`: `InboxFrame` (department selector, tabs by counts), `Recommended`, `Claimed`, `Pool`,
  `Transfers`, `dialogs.tsx` (Claim, Dismiss, Suggest, Allot, Transfer request, Decide, Withdraw — shared with the case
  page).
- `src/components/search/*`: `Search` (local list and search, filters), `CourtSearch`, `TextSearch`.
- `src/components/case/*`: `CaseFrame` (header, banners, tabs, 404), `Overview`, `OwnershipCard`, `Hearings`, `Orders`,
  `Parties`, `Documents`, `Links`, `LinkGraph`, `Notes`, `Timeline`, `Details`.
- Moved to row 50 `portal-mapping` at approval: `src/components/admin/mapping/*` (`CounselCodes`, `Keywords`,
  `Watchlist`, `Scoring`), `MAPPING_TABS` in `src/lib/routes.ts`, the mapping strings and the `(portal)/admin/mapping/*`
  pages.
- Pages: `(portal)/inbox/{layout,page}.tsx`, `inbox/recommended`, `inbox/claimed`, `inbox/pool`, `inbox/transfers`;
  `(portal)/search/page.tsx`; `(portal)/cases/[ref]/{layout,page}.tsx`, `hearings`, `orders`, `parties`, `documents`,
  `links`, `notes`, `timeline`, `details`. Changed: `PortalShell` (header search box), `Dashboard` (`CaseRef` → `CaseLink`),
  `Duplicates`, `UserDetail` (exit items linked), `Tickets` (imports `refPath`).

Audit and events: the portal writes none. Every action it offers is an existing API call that already audits
(`ownership.claim`, `ownership.allot`, `ownership.take_over`, `ownership.unwatch`, `recommendation.dismiss`,
`recommendation.suggest`, `transfer.request|accept|decline|withdraw`, `case.search_court`, `config_changed` and the
matching rule and scoring rows, `document.downloaded` for uploads). The five API changes are reads and write nothing.

## API
New or changed (FastAPI):

| Method, path | Function required | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /inbox/recommended` (changed) | `cases.claim` in the department, or `cases.view_all` (unchanged) | + `listed_from?`, `listed_to?` (dates) | `RecommendationListOut`; each `case` gains `last_listing` | the department's recommendations only (unchanged); 400 when `listed_from > listed_to` |
| every response with `CaseSummaryOut` (changed) | unchanged per endpoint | — | `case.last_listing: {list_date, list_type, court_no, sr_no} \| null` | court-public cause-list data, as the summary's other fields |
| `GET /cases/{ref}/ownership` (changed) | `cases.view_scope` (unchanged) | — | + `actions: {claim: bool, claim_departments: [code] \| null, dismiss, suggest, allot, take_over, stop_watching, request_transfer, withdraw_transfer, decide_transfer}` | unchanged (404 when the caller may not see the ownership); flags computed for the caller only |
| `GET /custody/recipients` (changed) | `cases.view_scope` (unchanged) | `department?`, `q?`, `limit`, `offset` | items + `user_id`; with `department`: + `units: [{code, name}]` | unchanged (active departments; that department's eligible memberships) |
| `GET /reference/case-types` (new) | `cases.view_scope` or `cases.view_all` (`require_any`) | — | `[{case_type_code, short_name, full_name, type_name}]` | master data, the same for every reader |

Used as they are (function from the existing routers): `GET /cases`, `/cases/search`, `/cases/{ref}` and its tabs
(`cases.view_scope` or `cases.view_all`, then the case visibility rule; 404 otherwise); `POST /cases/search-court`,
`/cases/{ref}/fetch-court` (`cases.search_court`); `/inbox/claimed` (`cases.view_scope`), `/inbox/pool`
(`cases.claim` or `cases.view_all`), `/inbox/transfers` (`cases.transfer_request` or `cases.transfer_decide`, or
`cases.view_all`), `/inbox/counts` (`cases.view_scope`); `POST /cases/{ref}/claim` (`cases.claim`), `/dismiss`
(`cases.dismiss`), `/suggest` (`cases.suggest_elsewhere`), `/allot` (`cases.allot`), `/take-over`
(`cases.take_over`), `/stop-watching` (`cases.release`), `/transfers` (`cases.transfer_request`); `POST
/transfers/{trf}/accept | decline` (`cases.transfer_decide`), `/withdraw` (`cases.transfer_request`); `GET
/cases/{ref}/documents` (`documents.view`), `/cases/{ref}/orders/{id}/file` and `/documents/{doc}/file` (`inline`:
`documents.view`, `attachment`: `documents.download`), `/documents/search` (`documents.view`); `GET
/cases/{ref}/notes` (case reading, note visibility); `/admin/scoring-settings` (read: `admin.scoring`,
`admin.counsel_codes` or `admin.keywords`; `PUT`: `admin.scoring`), `/admin/counsel-codes*` (`admin.counsel_codes`),
`/admin/keywords*` and `/admin/name-patterns*` (`admin.keywords`), `/admin/watchlist*` (`admin.watchlist`),
`/admin/offices` (`users.view`).

Web server: no new route; the relay change of decision 15.

## Jobs
None. (Rule and settings changes are rescored by the existing 15-minute `rescore-dirty` beat; the portal only says
so.)

## Tests
Backend (pytest, `backend/tests/`; the shared world of `tests/db/world.py`):
- `db/test_api_inbox.py` (added): `test_recommended_listed_range_filters`; `test_recommended_listed_range_reversed_400`;
  `test_summary_last_listing_is_latest_entry` (two dates, two items on the latest date → latest date, lowest item);
  `test_summary_last_listing_null_without_entries`; `test_last_listing_in_search_and_pool_items`.
- `db/test_ownership_actions.py` (new): `test_actions_match_outcomes` (for every world user × case state — pool,
  recommended to the user's department, owned by it with an officer, owned by another department with the user's
  department watching, open transfer in each direction — each flag is true exactly when the action, run in a
  savepoint that is rolled back, succeeds or answers only `office_required`); `test_claim_departments_lists_qualifying_memberships`
  (a person in two departments, `cases.claim` in one); `test_claim_departments_null_for_super_admin`;
  `test_officer_without_ownership_functions_has_no_actions`; `test_actions_write_nothing` (no `audit_log`, `events` or
  ownership rows after the read); `test_actions_ignore_hidden_case` (404 as before).
- `db/test_custody_recipients.py` (added, or the existing recipients test file): `test_recipients_carry_user_id`;
  `test_units_are_active_offices_inside_the_department`; `test_no_units_without_department`.
- `db/test_api_reference.py` (added): `test_case_types_active_only_sorted`; `test_case_types_need_case_reading` (a login
  with both case functions denied by override → 403); `test_case_types_signed_out_401`.
- `unit/test_openapi_snapshot.py` (existing) fails until `frontend/openapi.json` is regenerated.

Frontend (Vitest, `frontend/src/**/*.test.ts(x)`, the `fakeApi` helper):
- `server/relay.test.ts` (added): `x-content-type-options` and `content-security-policy` are passed through; other
  headers are still dropped.
- `lib/refs.test.ts`: `/` → `-`, a CNR unchanged. `lib/timeline.test.ts`: known types give their line; an unknown type
  gives no detail; no raw JSON. `lib/signals.test.ts`: each signal kind's chip text. `lib/format.test.ts` (added):
  `hearingBadge` near midnight IST.
- `components/shell/shell.test.tsx` (added): Case inbox shown with a department membership or `cases.view_all`, hidden
  for standing counsel; Search shown for case readers; the header box goes to `/search?q=`. (The Department mapping
  tab test moved to row 50 `portal-mapping`.)
- `components/inbox/inbox.test.tsx`: tabs follow the `null` counts; the selector appears with two departments and
  for a `cases.view_all` reader, who sees no action buttons in a department they do not work in; Recommended shows
  the band label from the API (a 0.849 score with `band: medium` says POSSIBLE), signal chips and the latest listing;
  the cause-list filter sends `listed_from` / `listed_to`; Claim sends `office_code` of the selected department and
  warns about watcher status when `current_owner_code` is set; allot fields only with `cases.allot`; Suggest needs a
  reason and does not offer the selected department; Dismiss reason optional; a 409 `already_claimed` shows its message
  and re-reads the list and counts; Transfers In offers Accept / Decline only with `cases.transfer_decide`, Out offers
  Withdraw; no release button exists on any row.
- `components/search/search.test.tsx`: no words → `GET /cases`; words → `/cases/search` with the filters; non-visible
  rows are not links and show Claim when `claimable`; a single visible CNR match opens the case; the court panel only
  with `cases.search_court`; each court error code shows its message and `retry_after` wait; the button is disabled
  while a search runs; party results offer Fetch details; case types come from `/reference/case-types`; the text tab
  only with `documents.view`.
- `components/case/case.test.tsx`: 404 shows the one neutral message; provisional banner and no CNR; merged case links
  to the survivor; fetch button only when not fetched and with `cases.search_court`; tab badges from `counts`; the
  Ownership card shows exactly the buttons whose `actions` flag is true; claim from the case page with two
  `claim_departments` asks for the department, with `null` lists every department; take over sends
  `expected_officer_user_id`; stop watching requires a reason; transfer request sends `stay_as_watcher`; custody card
  read-only (no Send / Recall buttons); orders View / Download by function and `download_status`; documents grouped by
  `doc_group` with the Case Assistant and visibility badges; notes link corrections both ways and hide corrected notes
  on request; the Details tab renders every block of the overview response; the link graph draws nodes and edges and
  says when `truncated`; non-visible linked cases are not links; no Case Assistant, Upload or Hand over button.
- Moved to row 50 `portal-mapping` at approval, not in this row: `components/admin/mapping.test.tsx`: tabs by function; weight inputs only with `admin.scoring`; the scoring save
  sends `expected_version`, a 409 reloads with the message; history listed; Unmapped "Map" pre-fills the code form; the
  watchlist refuses a CNR that is not 16 characters before sending; the "within 15 minutes" note after a save.
- `components/dashboard/dashboard.test.tsx` (changed): case references are links to `/cases/<dash ref>`.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green with the new tests;
   `python backend/tools/export_openapi.py` then `git diff --exit-code frontend/openapi.json` clean after the commit.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build`; `docker compose build web api`.
3. Precondition for steps 4-9: migrations 0014 and 0015 applied to the dev database by the procedure in the decisions
   log (worker stopped, migration applied, worker restarted), with the owner's go-ahead; starting `api` otherwise
   applies them through `init`. If not done, steps 4-9 are skipped and recorded in the cycle report (as in
   portal-shell).
4. `docker compose up -d`; `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/backend/reference/case-types`
   → 401 without a session. Signed in as the super admin at `http://localhost:3000`: `/search` without words lists
   cases with a total equal to `GET /cases` `total`; a CNR taken from the loaded January 2025 days
   (`aslms cases show <ref>`) typed in the header box opens its case page; the Overview, Hearings, Orders, Parties,
   Linked cases, Timeline and Details tabs load; an order with `download_status = stored` opens with View in a new tab
   (Chrome and Firefox; record whether the sandboxed PDF renders, decision 15) and downloads with Download;
   `curl -sI` of the same relay URL with the session cookie shows `x-content-type-options: nosniff` and
   `content-security-policy: sandbox` for `disposition=inline`.
5. Department admin of a department with mapped codes (if none, map one through `POST /admin/counsel-codes` as the
   super admin; the mapping screen is row 50;
   `aslms rescore --all` or wait 15 minutes): `/inbox/recommended` badge equals `recommended_high + recommended_medium`
   of `GET /inbox/counts`; claim one strong recommendation; `aslms audit search --action ownership.claim --limit 1`
   shows the row with the browser's address; the case's Ownership card shows the department as primary and no claim
   button; the row has left Recommended and appears under Claimed → Active.
6. Allot that case to an officer from the Claimed tab; sign in as a second officer of the same department in a private
   window and take it over from the case page; the first window's take-over attempt then shows `stale`. Audit shows
   `ownership.allot` and `ownership.take_over`.
7. Request a transfer to a second department with "stay as a watcher"; as that department's admin, accept it from
   Transfers → In; the first department's Ownership card shows it as a watcher with Stop watching, and no button
   returns the case to the pool. Audit shows `transfer.request` and `transfer.accept`.
8. From the Unclaimed pool, as the central operator, suggest a department with a reason; that department's
   Recommended tab lists it with "Suggested by". Dismiss another recommendation and confirm it moves to the pool's
   "dismissed by" list.
9. Court search: with `NAPIX_ENABLED=false` (the default) the court panel answers "court search is switched off"
   (503 `napix_off`) and `napix_call_log` gains no row. The live court search (CNR not yet held) is run only in a
   session where the owner sets the switch for that run; the case found opens and a second local search finds it
   without a call.

## Open questions
None.

## Deviations
Recorded by the developer while building (12 Oct 2026). None changes a rule of the plan.
1. **Ownership checks run under the row lock.** Each action now takes the case row lock first and then calls its
   `_check_*` function (before, the acting membership was resolved before the lock and the state checked after it).
   The outcomes, codes and audit rows are unchanged; the whole backend suite is green.
2. **`inbox.Page.extra`.** The recipients list returns `units` through a new `extra` dict on the shared `Page`
   dataclass rather than a second return type.
3. **API paths use the dash form.** The relay refuses an encoded `/`, so every portal call to `/cases/{ref}/…` writes
   the `ref_no` with `-` (`apiCasePath()` in `src/lib/refs.ts`); the query keys of a case use the same form so the
   inbox's re-reads reach an open case page.
4. **Suggest department in the pool shows with `cases.suggest_elsewhere` in any membership**, not only in the
   selected department's, so the central operator (whose membership is not a department) can follow up an
   unclaimed case as decision 6 intends. The API decides the call.
5. **Claim from search results** offers the departments of the login's memberships that hold `cases.claim` (the
   super admin: every department), as the case page does with `claim_departments`.
6. **`/cases`** (the breadcrumb above a case page) is a page that sends the browser to `/search` (a client
   redirect, so the portal smoke check still sees HTTP 200).
7. **Small additions not named in the note:** `useDepartmentPeople()` (recipients of one department for the claim
   and allot fields), `departmentsOf()` in `can.ts`, `src/lib/params.ts` (query-string filters shared by server
   pages and client lists), `SignalChips`; the Claimed tab's officer filter shows only with `cases.allot`; the
   Documents tab reads one page of 200; the Details tab hides internal ids (UUIDs); the test helper `browserApi`
   now awaits an answer that is a promise (used to test the disabled court-search button).
8. **Verification steps 3-9 were not run by the developer.** Migrations 0014 and 0015 are not applied to the dev
   database and starting `api` would apply them through `init` while the historical load runs; that needs the
   owner's go-ahead. `docker compose build web` and `portal_smoke.py` are left to the tester and the integrator.
9. **Web smoke run against the branch's standalone server, not the Compose image** (fix after the tester's report,
   12 Oct 2026). `docker compose build web` cannot run in this session: Docker Hub does not resolve (no network) and
   `node:22-alpine` is not cached, so the running `web` container is still the old image. The same pages were checked
   with the code the image would hold: `npm run build`, the `.next/standalone` server (with `.next/static`) started on
   `127.0.0.1:3100` with the Compose `web` variables (`API_BASE_URL=http://localhost:8000`), then
   `portal_smoke.py --base http://127.0.0.1:3100`: all 41 pages answered 200, including `/cases`, `/cases/smoke-x` and
   its 8 tabs, `/inbox` and its 4 tabs and `/search`; that server's log had no error line. The Compose rebuild
   (`docker compose build web`, `docker compose up -d --wait --no-deps web`, `portal_smoke.py`) remains to be run
   once the registry is reachable, before merge.
10. **Dismiss and Allot name the department on screen** (fix after review, 12 Oct 2026). The inbox is read for one
    department, but `POST /cases/{ref}/dismiss` and `/allot` took no department, so for a login in two departments
    the API acted for the primary membership and could dismiss or allot another department's recommendation or row
    (decisions 4 and 7). `DismissIn` and `AllotIn` gain an optional `office_code`; the inbox's Dismiss sends the
    selected department and Allot (inbox and case page) sends the department of the row it shows. Unlike claim,
    `office_code` here must name one of the caller's own departments (400 otherwise; the super admin gains no new
    power); the named membership must hold the function (403) and that department must have the recommendation or
    row (404). Without `office_code` the API resolves the department as before. The case page's Dismiss still sends
    none (the page has no selected department; `office_required` shows as its message). `frontend/openapi.json` and
    `schema.d.ts` regenerated; tests in `tests/db/test_ownership_office_code.py` and `inbox.test.tsx`.
