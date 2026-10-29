# Design: Data Collection redesign, round 2 — Problems and Fixes, the System Health Court Calls section, the old tabs retired

```
slug: data-collection-redesign-tabs
status: approved
author: architect
date: 2026-10-26
approved_by: owner on 2026-10-26, as round 2 of the revised data-collection-redesign
```

This is a pointer note. The whole design is **[data-collection-redesign.md](data-collection-redesign.md)**. The owner
reopened it on 26 Oct 2026 for four tabs (its history section); round 2 is re-approved with it. This cycle (row 173,
branch `feature/data-collection-redesign-tabs`) builds **decisions 2 (the remaining redirects), 3, 4 and 42-46** of
that note, and only those, under its rules, API, tests and verification. It builds after round 1 (row 172) has merged.

- Build from those decisions and the API, Services, Tests and Verification lines marked for round 2.
- Record any deviation of this round in a "Deviations, round 2" section of **this** note.
- The first version of this round (Health rebuilt as cards, Queue and Calls with a switch) is superseded: Health and
  Queue and Calls are removed, their pieces placed as decision 3 lists.

## Deviations, round 2

**Round 2 (row 173, developer, 29 Oct 2026).** Where the note was silent, the smallest reasonable choice:

1. **`DataGapsOut` carries `counts`** (the total split by state: `being_fetched`, `not_found`, `failed`, `not_queued` for
   cases; `not_available`, `failed` for orders) beside `kind`, `total`, `items` and `documents_text`, because decision 45
   shows "a count with its split" and a page of 50 cannot give it. Additive. Cases are the held cases without details,
   not merged, newest first; each case's state is that of its `dossier` row in any lane (by CNR or
   `<est_code>|<case number>`, a waiting row first; a `done` row or none reads Not Yet Queued). Orders are those with no
   stored PDF marked `not_available` or `failed`, latest order date first, merged cases included so the count equals the
   Overview's `orders_not_available + orders_failed`. `limit` 1-200 (default 50); a slow query answers 503
   `search_timeout`.
2. **Collect These** sends the listed cases of the page that are not being fetched (at most 50) to the existing
   `POST /admin/data-load/fetch-details` (request lane, priority 30, audit `data_load.details_requested`), because the
   Several Cases request `POST /admin/data-load/collect {kind: "list"}` arrives in round 3 (row 174), which repoints the
   button.
3. **Readers who hold only `admin.data_load`** cannot read `/admin/napix/*` (the API's `health_reader`): their Court
   Connection line says the last court call from the pulse, and Failed Fetches shows them the summary by kind with a note
   instead of the failed items. No guard is widened.
4. **Failed Fetches' summary by kind** comes from the Overview's `waiting_work` (every lane), each kind with Retry All
   (no lane) by its function (`admin.masters_sync` for the reference lists, else `admin.napix_refetch`). The failed items
   are `GET /admin/napix/queue?status=failed` in a `ScrollBox`, paged by 50; What is worded from the reference (a day's
   cause lists, an order by number, date and CNR, a provisional case by its printed number), the reference in a tooltip.
5. **Possible Duplicates** keeps today's endpoints and kinds; "Needs Review" reads **To Confirm** (decision 44's "possible
   duplicates to confirm"), with a one-line explanation per kind; the heading's count is the Overview's
   `duplicates_review`.
6. **Problems links.** The Problems line's four parts and Automatic Collection's failed count lead to
   `/data/problems#failed`, `#duplicates` and `#gaps`; the tab scrolls to the anchor once its sections are drawn. The
   query string of an old `/data/queue?status=failed` link is kept by the redirect and not read.
7. **The data-health report's link** to the live screen pointed at `/data/health`; it now opens `/data/overview` and reads
   "Data Collection Overview".
8. **Court Calls** follows ASLMS Services on `/system` (menu child order Court APIs, ASLMS Services, Court Calls, Access
   Token). Recent Resets and E-mail sit side by side from 900 px, the call log below in a `ScrollBox` with More. The
   e-mail figures read `GET /admin/data-health` (no API change). A call's Result is Answered or "Failed: ‹the error family
   in words›"; Kind of Work uses the lane words of decision 47; the three court services without a System Health card
   (advocate registration, act details, neutral citation) have plain names too.
9. **Strings left in `T.data`.** The keys only the removed Health, Queue and Calls and Duplicates tabs read stay in
   `messages.ts` (no screen reads them); pruning them, with the round 1 leftovers, is left to a cleanup.

## Verification, round 2

**Browser screen check (row 173, developer, 29 Oct 2026).** Run as `docs/operations.md` section 16 says, never through
Compose on the shared stack: `frontend/` built from this branch as `tmp173-web`, `frontend/e2e/Dockerfile`
(`PLAYWRIGHT_VERSION=1.64.1`) as `tmp173-uicheck`, both on the private network `tmp173-net` (web with the alias `web`,
`API_BASE_URL=http://api:8000`, `PORTAL_BASE_URL=http://web:3000`, `COOKIE_SECURE=false`, answers from the fixtures).
Result `20261029-0847`: 147 routes and states, 350 screenshots at 375, 768 and 1280 px, **0 findings**; 467 passed,
7 skipped (the drawer and rail states that apply only at other widths). Covered for this round: `/data/problems` and
its all-sections state (`data-problems-all-sections`), `/data/overview`, the redirects `/data/health` →
`/data/overview` and `/data/queue`, `/data/duplicates` → `/data/problems`, and `/system` with the Court Calls section
(`system-court-calls`). The container, the network and both images were removed afterwards; the shared stack was not
touched.
