# Design: The original cause-list PDF without first choosing a bench

```
slug: causelist-pdf-access
status: approved
author: architect
date: 2026-10-30
approved_by: owner on 2026-10-30
```

## Context
Backlog row 196, the owner on 28 Oct 2026: "why is the button disabled. even if my portal shows data in its list i am
not able to view the original cause list"; "shouldnt the user be notified of this step so that the user knows what needs
to be done to view the cause list?".

Today View Cause List on the Cause List page (`DateHero` in `frontend/src/components/causelist/DayBar.tsx`) is enabled
only when a bench is chosen (`CauseList.tsx`: `canView={!!bench && !!viewValue(bench)}`). The default is All Benches,
so a person who opens the page sees the whole day's entries and a disabled button with the small hint "Choose a bench to
view its list." The reason is real: the court publishes one PDF per bench and list (`docs/napix_integration_notes.md` §8:
"Show Cause List is per bench: the PDF for (bench_id, causelist_id, date) contains only that bench's portion"), so there is
no single original for "All Benches". The original PDFs are reachable today only after choosing a bench (the list strip
`ListStrip.tsx`, or the Original PDF tab of the View Cause List modal).

The plan: §3.1 Table 4 (Show Cause List: "official cause list document", feeding the "cause list archive"); design
`portal-causelist` decision 9 (the original PDF of each list through `GET /causelists/lists/{id}/file`, `documents.view`
inline and `documents.download` attachment, court record, not audited) and decision 11 (the screen); design
`portal-ui-polish-2` decision 25 (the View Cause List modal on `?view=<bench_id>&vtab=entries|pdf`).

In place and reused, unchanged:
- `GET /causelists/{list_date}` already returns every bench of the day in court order with its label (the judges), court
  numbers, entry count and lists, each list with `id`, `list_type`, `entries_stored`, `fetch_status`, `has_pdf`,
  `version` (`CauselistDayOut`). This is everything a bench chooser and a per-list PDF link need.
- `GET /causelists/{list_date}/entries` rows carry `causelist_id`, `bench_id`, `bench_label`, `list_type`; `headingsOf`
  (`lib/causelist.ts`) already draws a court, bench, list and section heading row in the entries table, and redraws every
  level for the first row of a page.
- The modal already opens for any bench of the day from `?view=` alone: `benchOfView(benches, value)` looks through all
  the day's benches, not only the chosen one (a court-wide file is named by its list id, `viewValue`).
- `ListStrip.listFileUrl(id, disposition)`, `canViewInline`, `can(me, "documents.view" | "documents.download")`.

Not covered: any change to how lists are fetched, parsed or stored; a single merged day PDF (the court publishes none and
ASLMS does not make one); the Printed Entries tab of the modal; the Problems and Fixes or Data Collection screens.

## Decisions
1. **View Cause List is always enabled when the day holds a list.** Enabled whenever the day's state is `held` and at
   least one bench has a list (`benchesWithLists(benches).length > 0`). With a bench chosen it opens that bench exactly
   as today (`?view=<bench>&vtab=entries`). With All Benches it opens the bench chooser (decision 2), except that when
   only one bench of the day has lists it opens that bench at once (a chooser with one choice is a wasted click). When the
   day holds no list the button stays disabled and its hint says why: "No cause list is held for this day." (the day
   banner below already offers Previous List, Next List and, for `admin.napix_refetch`, the fetch button).
   Alternatives: keep it disabled and only reword the hint (the owner's complaint stands: data on screen, no way to the
   original); open the first bench's list (arbitrary, and wrong for most readers).
2. **The bench chooser.** A kit `Modal` titled "Choose a Bench · ‹date›" with one sentence: "The High Court publishes a
   separate cause list for each bench. Choose the bench whose list you want to see." Then a kit `DataTable` (cards on
   phones) of the day's benches in the API's court order, columns Court (the first printed court number, "—" for none),
   Judges (the bench label; "Bench ‹id›" or "Court-Wide List" as `benchLabel` names them), Lists (the list types, with
   "Corrected" for a version above 1) and Entries (the bench's `entries`), and per row two normal-size secondary buttons:
   **View** (opens the View Cause List modal on that bench, Printed Entries tab, as the button does with a bench chosen)
   and **Original PDF** (the same modal on its Original PDF tab, `vtab=pdf`). A bench with no list is listed with "No List
   Published" and no buttons, so the reader sees it sat but published nothing. Original PDF is shown only when the reader
   holds `documents.view` or `documents.download` and some list of the bench has `has_pdf`; otherwise the cell says "PDF
   Not Available" (or "PDF Not Fetched Yet" when every list without a PDF is `pending`). Choosing closes the chooser and
   opens the modal with `?view=<bench>&vtab=…`; the page keeps All Benches (no `bench_id` is written), so closing the
   modal returns to the page as it was. The chooser is local state, not an address. Alternatives: a bench select inside a
   small dialog (two steps for one choice, and no room for judges and counts); writing `bench_id` on choice (changes the
   reader's filter as a side effect of viewing); an addressable `?choose=1` (Back closing it would be nice, but the
   chooser holds nothing worth sharing and the modal it opens is already addressable).
3. **A plain note while All Benches is chosen.** Above the entries, while the day is `held` and no bench is chosen, a kit
   `Notice` (info tone, not dismissible): "The High Court publishes a separate cause list for each bench, each with its
   own original PDF. To see one, use View PDF beside a list's heading in the table below, or use View Cause List and
   choose the bench." It goes once a bench is chosen (the list strip then shows that bench's PDFs). The disabled-state
   hint of today ("Choose a bench to view its list.") is retired: the button is no longer disabled for that reason.
   Alternatives: a dismissible note (would need a stored preference for a one-line text); the note only in the
   button's tooltip (the owner asked that the user be told, and tooltips are not seen on phones).
4. **View PDF and Download PDF on each list heading of the entries table.** Each list heading row of `EntryTable` ("Daily
   List", "Supplementary List" … under each court and bench heading) carries, after its text, **View PDF** (an anchor to
   `listFileUrl(id, "inline")`, new tab, `rel="noopener noreferrer"`, shown with `documents.view` and when the browser
   can show PDFs inline, as `ListStrip` does) and **Download PDF** (`listFileUrl(id, "attachment")`, `download`, shown
   with `documents.download`). A list without a stored PDF shows the muted "PDF not available from the court" or "PDF Not
   Fetched Yet" text of `ListStrip`. The links sit on the list heading rather than the bench heading because the court's
   PDF is per bench **and list** (a bench with Daily and Supplementary lists has two PDFs); for a bench with one list
   this is the same row. Each link's accessible name names the list and bench ("View the Original PDF of the Daily List,
   Court 6 · HONOURABLE …"), since the same visible text repeats down the page. The links show whether or not a bench is
   chosen (one rule; with a bench chosen the strip above shows the same files). The list facts come from the day already
   loaded (`listsById(day.benches)`: `causelist_id` → `{has_pdf, fetch_status}`); a heading whose list is not in the day
   (an earlier version opened by `list_id`) shows no link, the earlier-version notice already offers its files.
   Alternatives: links on the bench heading with a menu of lists (one more click, and a menu per bench); a PDF column on
   every entry (repeats the same file hundreds of times).
5. **No backend change, no new API, no NAPIX call.** Everything reads `GET /causelists/{date}` and the entries the page
   already loads, and the existing file endpoint. Visibility and gates are unchanged and stay on the server: the file
   endpoint still requires `cases.view_scope` or `cases.view_all` plus `documents.view` (inline) or `documents.download`
   (attachment) and answers `no_pdf` / `file_missing` as today; the portal only hides links the server would refuse.
   Opening or downloading a cause-list PDF stays unaudited (`portal-causelist` decision 9: a court-published record, as
   order PDFs). No `Permission`, setting, table or migration.
6. **Wording.** Labels in Title Case through `T.causelist` (the wording guards of both suites apply): "Choose a Bench",
   "View", "Original PDF", "View PDF", "Download PDF", "No List Published", "PDF Not Available"; sentences in sentence
   case. No new kit component: `Modal`, `DataTable`, `Notice`, `Button`, `buttonClass` for the anchors. One primary per
   page is kept (View Cause List and the chooser's buttons are secondary).

No deviation from the plan. Points for the owner to confirm at approval (decisions taken, reversible): the chooser's
View opens the Printed Entries tab as the button does today, and Original PDF beside it opens the PDF tab (2); a day with
one bench holding lists skips the chooser (1); the note is not dismissible (3); the PDF links sit on each list heading,
also when a bench is chosen (4).

## Data
No table, column, constraint, index, reference code, `Permission` or setting is added; no migration;
`docs/schema/schema.md` is unchanged.

## Services
Backend: none. No file under `backend/` changes; `frontend/openapi.json` and `src/lib/api/schema.d.ts` are unchanged.

Frontend (`frontend/src/`):
- `lib/causelist.ts`: `benchesWithLists(benches)` (benches with at least one list, in the given order);
  `listsById(benches)` (`Record<string, Causelist>` over every list of the day); `benchPdfState(bench)` →
  `"available" | "pending" | "none"` (some list `has_pdf`; else every list without one `pending`; else none).
- `components/causelist/DayBar.tsx`: `DateHero` takes `viewState: "bench" | "choose" | "single" | "none"` in place of
  `canView`; disabled only for `none`, with the `noListHint` description; `onView` unchanged.
- `components/causelist/BenchChooser.tsx` (new): decision 2; props `date`, `benches`, `canPdf` (`documents.view` or
  `documents.download`), `onChoose(bench, tab)`, `onClose`.
- `components/causelist/CauseList.tsx`: computes `viewState` (bench chosen → `bench`; else `benchesWithLists` length 0 →
  `none`, 1 → `single`, more → `choose`); `onView` opens the overlay for the chosen or single bench, or the chooser;
  `onChoose` closes the chooser and calls `overlay.open(viewValue(bench), { vtab: tab })`; renders the All Benches note
  (decision 3) after `DayNotice` and before the entries when `held && !bench`; passes `lists={listsById(benches)}`,
  `canView`, `canDownload` to `EntryTable`.
- `components/causelist/EntryTable.tsx`: the list heading row renders the PDF links of decision 4 (a small
  `ListPdfLinks` part, shared with nothing else); other heading kinds unchanged. Heading rows wrap on phones (no clipped
  or overflowing text: the uicheck `clipped` and `gutter` rules apply).
- `lib/messages.ts` (`T.causelist`): `noListHint`, `chooseBenchTitle(date)`, `chooseBenchIntro`, `chooseCols` (Court,
  Judges, Lists, Entries, Actions), `chooseView`, `choosePdf`, `noListPublishedLabel`, `pdfNotAvailable`,
  `allBenchesNote`, `viewPdf`, `downloadPdf`, `viewPdfOf(list, bench)`, `downloadPdfOf(list, bench)`; `viewListHint`
  removed.
- `components/causelist/causelist.module.css`: the heading-row link group and the chooser's cells, on the shell tokens.

Documents (per cycle, as since row 198): `docs/ASLMS_Process_Workflows.md` (the Cause List section: viewing the
original PDF), `docs/ASLMS_Software_Documentation.docx` (the Cause List screen), and the user guide text if it names
the disabled button.

Audit and events: none (decision 5).

## API
None new or changed. Used as they are:

| Method, path | Function required (`Permission`) | Use here |
|---|---|---|
| `GET /causelists/{list_date}` | `cases.view_scope` or `cases.view_all` | benches, lists, `has_pdf`, `fetch_status` for the chooser and the links |
| `GET /causelists/{list_date}/entries` | `cases.view_scope` or `cases.view_all` | the entries and their list headings (unchanged query) |
| `GET /causelists/lists/{id}/file` | `cases.view_scope` or `cases.view_all`, and `documents.view` (`disposition=inline`) or `documents.download` (`attachment`) | View PDF, Download PDF, the modal's Original PDF tab; not audited |

## Jobs
None.

## Tests
Frontend (Vitest, the `fakeApi` / `browserApi` helpers), `components/causelist/causelist.test.tsx`; the existing test
"is disabled with All Benches, with the hint, and opens ?view=<bench>&vtab=entries once a bench is chosen" is replaced by:
- `View Cause List is enabled with All Benches and opens the bench chooser` (dialog "Choose a Bench · 13 Oct 2026", the
  intro sentence, benches in API order with court, judges, list types and entries).
- `a bench without a list shows No List Published and no buttons in the chooser`.
- `View in the chooser opens ?view=<bench>&vtab=entries and writes no bench_id` (and closing the modal returns to
  `/causelist?date=…` with All Benches).
- `Original PDF in the chooser opens vtab=pdf; hidden without documents.view and documents.download; PDF Not Available
  when no list has a PDF; PDF Not Fetched Yet when the lists are pending`.
- `a court-wide file is offered in the chooser and opens by its list id`.
- `with one bench holding lists View Cause List opens that bench directly`.
- `with a bench chosen View Cause List opens that bench as before, without the chooser`.
- `on a day holding no list View Cause List is disabled with "No cause list is held for this day."`.
- `the All Benches note shows above the entries only while All Benches is chosen on a held day`.
- `each list heading row offers View PDF (inline URL, new tab) with documents.view and Download PDF (attachment URL) with
  documents.download, with accessible names naming the list and bench`.
- `a list heading without a stored PDF shows the not-available or not-fetched text and no link`.
- `no extra request: the chooser and the links make no call beyond GET /causelists/{date} and the entries` (the
  recorded calls).
- `lib/causelist.test.ts`: `benchesWithLists`, `listsById`, `benchPdfState`.
- The wording suites (Title Case, the retired words) stay green with the new strings.
- `e2e/uicheck.spec.ts`: three new cases at 375, 768 and 1280 px: `/causelist?date=<sample>` (All Benches with the note
  and the heading links), the same page after clicking View Cause List (the chooser open), and the chooser's Original PDF
  leading to `&view=<bench>&vtab=pdf`.

Backend: none (no backend file changes; the existing `db/test_api_causelists.py` file tests stay green untouched).

## Verification
1. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
2. The screen check on a private network against temporary images, never through Compose on the shared stack (runbook
   section 16): every case passes, the three new ones included, with no `clipped`, `gutter` or `doubled-heading`
   finding.
3. Deploy the portal only: `docker compose build web`, then bring `web` up with the court-data switch given on the
   command line as the runbook requires for every `up`; `python backend/tools/portal_smoke.py` → every page 200
   (`/causelist` included), no error line in the `web` log. No migration, no backend restart.
4. Signed-in check by the owner (the e-mailed sign-in code), at 375, 768 and 1280 px, on a held date such as the latest
   list date: the page opens on All Benches with the note; View Cause List is enabled; it opens Choose a Bench with the
   day's benches in court order; View opens that bench's Printed Entries, Original PDF opens its PDF in the browser;
   closing returns to All Benches; View PDF beside a list heading opens that bench's PDF in a new tab and Download PDF
   saves it; a date with no list shows the button disabled with "No cause list is held for this day.".
5. In `psql`: no `audit_log`, `events`, `fetch_queue` or `napix_call_log` row written by these steps.

## Open questions
None.
