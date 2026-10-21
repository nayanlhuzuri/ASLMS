# portal-ui-polish (row 115) - integration report

Merged to `main` as 852d60d (squash of `feature/portal-ui-polish`), tag `feature/portal-ui-polish-done`. Design: `docs/design/portal-ui-polish.md`.

## What changed
- Frontend only (100 files): the advisories of rows 106, 107, 108, 111 and 112; every list is a `DataTable` (cards on phones, scrolling inside its own box on wide screens); the server-file guard follows re-exporting barrels; `useUrlOverlay` history-aware close; `transfer_in` sight needs `cases.view_scope`; attention list shows a case once.
- New `uicheck`: Playwright layout check at 375, 768 and 1280 px in the Compose stack with typed fixtures (`frontend/e2e/`), reporting overflow and clipped content.
- No migration, no table, no endpoint change.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 1831 passed, 2 skipped.
- `docker compose build`: succeeded.
- Portal smoke: passed.
- Git status clean on branch; design status approved; decisions-log entry and backlog row 115 present.
- CI on main: status unknown (`gh` is not installed on this machine).

## Review findings and closure
- Blocking, guard blind to the kit barrel: closed in a216b08 (barrel re-exporting a client module counts as client; design decision 8).
- Blocking, `.dataWrap` clipping wide tables: closed in 6c1ed1d (`overflow-x: auto`, cards for many columns; decision 9).
- Blocking, off-screen check missed clipped content: closed in 6c1ed1d (new `clipped` check; run 20261021-2239: 244 passed, findings `[]`).
- Advisory, fixture with one user type: closed (fixtures name the ten types).
- Advisories left open: history mark dropped by a Next router rewrite (graceful fallback to replace); run directory minute precision and result slug collisions; redirect routes drop pre-redirect console and fixture findings; `useLayoutEffect` in `DataTable` measures on every render. Not fixed in this cycle; the owner check is row 124.

## Deviations
None beyond those recorded in the design note.

## Push
See the final return: pushed result is recorded by the integrator after this commit.

## Follow-up rows
125 uicheck-in-ci (first numbered 123; renumbered on main because row 123 is the System health inspector), 124 portal-ui-polish-owner-check (already in the backlog).

## Load status (`aslms queue-status`, tail)
order_pdf done 111035, pending 190953, skipped 4; status_batch done 887, skipped 6; masters done 1; dossier skipped 28.
