# Cycle report: list search and sort, round 1 (row 175), 28 Oct 2026

Design `docs/design/list-search.md` (approved). Built, tested and reviewed on `feature/list-search`;
squash-merged on 28 Oct 2026. Round 1 of 4; rounds 2 to 4 are rows 179, 180 and 181.

## What changed
- Backend: the shared list `q` (`services/list_search.py`) and allow-listed sort (`services/list_sort.py`) with
  400 `bad_q`, `bad_sort` (naming the allowed keys) and `bad_cursor`; `GET /admin/counsel-codes/unmapped/page`
  with keyset paging that carries the sort; `total_all` on `GET /admin/counsel-codes`; `q`, `sort` and `dir` on
  `GET /admin/discovery/terms` and a term's cases; every mapping save commits, then starts one rescore (one at a
  time, exactly one follow-up after a change during a run), answering `rescore_dispatched`.
- Portal: the kit's `ListToolbar`, `ListSearch`, `ListCount`, `NoMatches`, `ListSort`, `OrderLine` and sortable
  `DataTable` headers; Recommended From Cause Lists reads every unmapped code in pages of 100; search and sort on
  the Department Mapping lists; Search Words on Working On, Claimed by Me and Disposed; "No cases match these
  filters." with Clear All.
- No migration, no new table or column, no change to `schema.md`. Eleven deviations in the design note.

## Merge
The integrator's squash merge stopped on conflicts: `main` had moved on after the branch point (5861406) with
documents only (rows 198 to 200 and their designs). Resolved by hand: `docs/backlog.md` (row 175 from the branch,
rows 198 and 199 from `main`) and the decisions log (both entries kept). The code is the branch's, unchanged.

## Gates
- On the branch: `ruff check` clean; full `pytest -q` 2769 passed, 3 skipped. Frontend `tsc`, `eslint`, vitest
  88 files / 1808 passed, `npm run build`, e2e `tsc`, `gen:api` no diff. `main`'s extra commits are documents
  only, so the results hold for the merged tree. CI runs the full suite on `main`.
- Tester: round 1 backend files 96 passed; round 1 vitest files 35 passed; `portal_smoke.py` passed.
- Screen check on a private network against a `web` built from the merged tree. First run: 6 failed, all on
  `/admin/mapping/codes` at 375 px: "Show 100 More" and the kit's "Clear Search" were `sm` buttons outside a row on
  a phone, and once a sort was chosen the search box ran 13 px past the card (the phone toolbar is a wrapping
  column, so each line took the sort row's 331 px minimum). Fixed at merge: both buttons at the normal size, the
  phone toolbar `flex-wrap: nowrap`. Final run: 446 passed, 7 skipped, 0 findings (140 routes and states). The
  shared stack was not touched. After the fixes: frontend `tsc`, `eslint`, vitest 88 files / 1808 passed.

## Review
Mergeable, no blocking findings. Three advisories, left open as follow-ups (row 201):
1. `matching.py` `claim_rescore` / `rescore_if_dirty` compare rule timestamps with `now()` (transaction start),
   so a save whose transaction began before a rescore claimed and committed after it loaded the rules can wait
   for the next unrelated change. Fix: take the cut-off with `clock_timestamp()` before `RuleSet.load`.
2. `GET /admin/counsel-codes` still accepts any `q` without `list_search.parse` (decision 6).
3. `CounselCodes.tsx` `saved()` never invalidates the unmapped-codes query (10-minute `staleTime`), so a mapping
   deactivated from the row menu shows in Recommended From Cause Lists only after a reload.

## Deploying
No migration: `docker compose build`, then `up` with the court-data switch; check the switch in api and worker;
`portal_smoke.py`.
