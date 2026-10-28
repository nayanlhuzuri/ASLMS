# Cycle report: uicheck repair (row 197), 28 Oct 2026

## Why
The merge of row 190 stopped at the Compose screen check: 39 failed on the merged tree and the same 39 on clean
main `04a5529`. Cause: since row 154 (26 Oct) the uicheck image could not be built (`npx tsc --noEmit` in
`frontend/e2e/Dockerfile` failed on the missing `partial_matches` fixture field), so every `docker compose run`
quietly reused the 25 Oct image with its old spec, fixtures and `openapi.json`.

## What changed (frontend and docs only; no backend, no migration)
- uicheck image builds again (fixture `partial_matches`, a pair the engine can return).
- Real portal defects fixed: the Scoring phone card ran 15 px past a 375 px screen (label "Actions"); the
  breadcrumb linked to `/assistant/orders`, which has no page, and stalled the court-record view (crumbs with no
  page are plain text, `CRUMBS_WITHOUT_PAGE` with a test against `src/app`); the Keywords table caption doubled
  its heading (visually hidden, still the accessible name); two lone `sm` phone buttons raised to normal size;
  the sign-in frame's brand panel moved outside `main#main` (a test pins one `main`).
- Check fixes: checkbox self-tests measured at 1280 px; No Office Yet clicks More Filters only while closed;
  citation fixtures carry S1..Sn labels.
- Owner decisions (28 Oct 2026, "approve"): `CodeBlock` scrolls sideways as a third `data-scroll-x` place
  (amends portal-ui-polish decision 21); text inputs and textareas are exempt from the "clipped" rule, with
  self-tests that a clipped div or button still fails; Try Again and Start a Court-Only Conversation stay at
  normal size (supersedes office-head-picker-followups decision 5 on size). Row 151 closed by this row.

## Tests
- `npm run lint`, `npm run typecheck`, `npx tsc --noEmit` in `frontend/e2e`: clean. `npx vitest run`: 79 files,
  1611 passed. `npm run gen:api`: no diff. uicheck self-tests: 33 passed.
- Full uicheck against a `web` built from the branch on a private network: 0 failed, 7 skipped, 413 passed.
  The official run against the running stack passes only after `web` is rebuilt from this commit.

## Review
No blocking findings. Advisories: the `partial_matches` fixture pair (fixed, `356cde5`); no test pinning the
sign-in landmarks (fixed, `d5a201c`).

## Incident during the cycle
A uicheck run against the shared stack (row 190's integrator, 03:21 IST) recreated the api through
`depends_on` without the court-data switch: court searches were off from 03:21 to 07:19 IST (collection
continued in the worker). Restored with the switch and checked; later runs used a private network.
