# Report: data-collection-redesign-advisories (row 191)

Merged 24 Nov 2026 from `feature/data-collection-redesign-advisories` by squash into `main` (on top of row 251 and
09b4f9c), tag `feature/data-collection-redesign-advisories-done`. No migration.

## What changed
- `backend/aslms/services/data_load.py`, `api/routers/data_load.py`, `api/schemas.py`: Overview and progress reads
  answer 503 `search_timeout` when cancelled; `collection` state shared with Load Control; recheck calls no longer
  overstate calls per cause-list day.
- Frontend: `CollectionStateBadge`, Overview, Automatic Collection, `useCountUp` never restarts through 0 (NaN and
  infinite targets ignored), messages split, generated API types.
- Tests: `backend/tests/db/test_data_collection_overview.py`, `collection.test.tsx`, `motion.test.tsx`.
- Conflicts on merge in CLAUDE.md and the decisions log: both sides kept, row 191 after row 251.

## Gates
- `ruff check .`: all checks passed.
- `pytest -q` on a fresh pgvector container (port 7437, removed afterwards), `ASLMS_TEST_REQUIRE_DB=1`:
  3950 passed, 3 skipped (symlinks, POSIX permissions, hand-saved envelope; none a database test), 1:25:26.
  A first run before 09b4f9c failed the two planner-dependent HNSW plan tests of row 251; fixed on main by 09b4f9c.
- Frontend: lint and typecheck clean; `npm test` 112 files, 2835 tests; `gen:api` no diff. `npm run build` compiles and
  generates all 80 pages but its exit code is intermittently 1 locally: Next 16.4.3's security advisory (row 269)
  raises a SecurityFatalError nudge, even with `CI=1` (exit 0 on one run, 1 on others). `docker compose build`
  (which builds `web`) succeeded.
- Screen check, private network with images from the branch's frontend (unchanged since): run 20261124-0844, 195
  routes and states, 638 screenshots, 0 findings; container, network and images removed.
- CI on main before the merge: success (run 45317401372).
- Design status `approved`; decisions-log entry and backlog row 191 present.

## Review findings
Advisory 1 of the review (`useCountUp` and a NaN target) fixed in fb55a49. One advisory left open: `recheck_calls`
keeps only the last attempt's `result.called`, so a failed recheck's earlier calls stay in the cause-list day's cost
(design decision 6, known limit). Follow-up row 278.

## Deviations
Local `npm run build` exit code affected by the Next advisory (row 269), see Gates.

## Load status
Not taken (the dev database was not used by the gates; no Compose service was touched).
