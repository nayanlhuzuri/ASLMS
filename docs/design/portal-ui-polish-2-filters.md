# Design: Portal UI polish 2, round 3 — Filter Layout B and the View Cause List modal

```
slug: portal-ui-polish-2-filters
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25, as round 3 of docs/design/portal-ui-polish-2.md (approved with three rounds, decision 46)
```

This is a pointer note. The whole design is **[portal-ui-polish-2.md](portal-ui-polish-2.md)**, approved by the owner on
25 Oct 2026. This cycle (row 163, branch `feature/portal-ui-polish-2-filters`) builds **decisions 21-25** of that note, and only those, under
its rules (decision 47), tests and verification. Round 1 (row 153) is merged; its deviations are recorded in that note.

- Build from that note's decisions 21-25, its API, tests and Verification sections for these decisions.
- Record any deviation of this round in a "Deviations, round 3" section of **this** note.
- Strings follow the round 1 Title Case rule and the `labels.test.ts` guard.

## Deviations, round 3
Recorded by the developer while building round 3 (26 Oct 2026); none changes a rule, a function, an API or what a caller
may see.
1. **The kit's `FilterCard`** (`components/ui/layout.tsx`) is always one `<form>` (role `search` when the page gives a
   submit, `group` otherwise), so the hero is not remounted when the page's data adds the right zone; the More Filters
   fields mount on first opening and stay mounted, out of the tab order while closed; the zones carry `data-zone`
   (`hero`, `fields`, `actions`, `more`, `summary`) for the tests. Its grid is `repeat(auto-fill, minmax(min(180px,
   100%), 1fr))`, so a phone never scrolls sideways.
2. **`FilterBar layout="card"`** takes `hero`, `more` (the page's own choice of the shared fields under More Filters),
   `wordsHint` and `countLine` (a page's own count at the head of the strip). In the card the submit reads "Search"; the
   bar keeps "Apply".
3. **Search.** The hero is "Search For" with "CNR, case number or party name." as its hint. "Only Cases I Can Open"
   (an own control, shown with words) stays in the right zone. The strip carries "n cases match" and the chips; the
   results heading keeps its own count.
4. **Department Cases.** Only the fields the list takes today are drawn: Cause-List Date, Status and Bench of the
   note's table are not in this list's filters (no filter, key or API change), and Active / Disposed stays the Status
   switch above the card. The hero reads "Words" with the long wording as its hint; the "n of m cases" line moved into
   the strip.
5. **Cause List.** Previous Day and Next Day step one calendar day. "Previous List" and "Next List" (to the nearest
   dates with lists, design portal-causelist, decision 4) moved into the notice of a day without lists, beside "Fetch
   This Day From the Court". Lists Held counts `totals.lists` of `GET /causelists/{date}`. Bench applies at once and
   Search Words on Search (secondary, as before). The strip shows "n entries", the two links and the Show select (the
   claimed figure is in the select); the applied Search Words, List Type and Court are chips with Clear All. The bench's
   lists (View, Download, corrected-list badges) stay under the card.
6. **View Cause List.** A court-wide file, which has no bench id, is named by its list id in `view`. Opening writes
   `vtab=entries`; a tab change replaces the address, so Back still closes the modal. The printed entries are a
   `DataTable` (cards on phones) without row clicks. The Original PDF tab first asks for the file through a new
   `probeFile` in `lib/api/client.ts` (the answer's head only, then the read is aborted), so a `no_pdf` or
   `file_missing` answer shows the API's message before the browser's viewer opens the address; a holder of
   `documents.download` alone gets Download without the viewer; a list without a stored PDF says so from the day's data
   without a request.
7. **Reports.** A report with a period keeps its Period quick-choice select in the hero, with From and To for "Choose
   Dates"; a report without one shows "As Of" today with a one-line note. The Scope (or Department) choice stays, first
   in the right zone. Show Report is the submit and Refresh sits beside it. The scope line in the strip repeats the
   report header's.
8. **Audit Log.** The hero shows From and To always, with Today, 7 Days and 30 Days (and "Any Time" once a date is
   set); the Period select is gone and the API's period refusal shows under To. Unit moved under More Filters, as the
   note's table says. The chips are built from the address; removing one searches again; Clear All is Clear.
9. **Queue.** Its filters stay in the component's state as before (they were never in the address). Kind, Status and
   Lane still apply at once; Reference Starts With now applies on Search instead of on each keystroke. The strip reads
   "x of y rows shown".
10. **Office Picker.** Its list is now kept inside the viewport when the box sits near the right edge (the Audit Log's
    right zone at 768 px, found by the browser check).
11. **Messages.** New strings in Title Case; the unused `causelist.counts`, `causelist.states`, `causelist.words` and
    `causelist.clear` are removed; `kit.moreButton` joins `LABEL_FUNCTIONS`.
12. **uicheck.** The fixtures answer `GET /causelists/{date}` with a held day (a bench of two lists, the longest label,
    a court-wide file) and the list file with a stand-in; `SAMPLE` gains `causelistDate`, `benchId` and `causelistId`;
    the five states of the Tests section are added. The affected routes and states were run locally with Chromium
    against `next dev` (69 passed); the Compose run is the integrator's.
