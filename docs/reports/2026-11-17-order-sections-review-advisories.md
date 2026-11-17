# Order sections review advisories (row 264), integrator report

Merged 17 Nov 2026 as one squash commit on `main`, tag `feature/order-sections-review-advisories-done`. Design: `docs/design/order-sections-review-advisories.md` (approved 16 Nov 2026). No migration (row 250 carries 0038).

## What changed
- `backend/aslms/services/order_parse.py`: parser version 2; `Linked Case :` blocks of a `whole` reading end where they end; `PageMap.page` before the first printed marker counts the form feeds.
- `backend/aslms/services/order_sections.py`: light runs of the 5-minute job and a daily 01:30 IST full check; isolated status parts; re-extraction found by `created_at` against `document_text.updated_at`; reading states; open `order_parse` failures resolved when the text goes and no traceback every 5 minutes.
- Frontend: Orders tab by the server's reading state ("Text Could Not Be Read", "Not Read Into Parts"), partial order checks on Data Collection, labels, generated API types.
- Docs: design note and row 250 measurements, decisions log, backlog, runbook, process workflows, Word guides. New test fixtures under `backend/tests/fixtures/orders/`.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3638 passed, 3 skipped (44 min 34 s); no failure in the run.
- `docker compose build`: succeeded (build only, no `up`).
- Screen check (private network, `web` and `uicheck` images built from the branch, runbook section 16): 184 routes and states, 594 screenshots, 0 findings; 866 passed, 14 skipped; temporary containers, network and images removed.
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: last run success (run 43828899715). `origin/main` equalled local `main` before the merge.

## Review findings
All three reviewer findings were advisories, left open and recorded as row 266: (1) the last linked block with no coram and no `Advocate for` line takes in body text, and `assert_invariants` does not check the invariant; (2) the full check's retry pass hashes every reading twice while a failure is open; (3) Deviation 4's wording is wrong, an overlapping run also runs the full check (data correct, scan cost doubled). Finding 1 needs a further PARSER_VERSION bump if fixed after the backfill.

## Deviations
None beyond those in the design note (Deviation 4 is corrected by row 266 point 3).

## Follow-up rows
266 `order-sections-review-advisories-review` (new). Row 265 (measurements after the backfill, rendered page numbers, owner checks) was already added by the scribe.

## Load status
`aslms queue-status` was started but had not answered within 2 minutes (the worker is busy with the historical load); not recorded here.

## Push
See the final return of the cycle: `main` and the tag are pushed with the two fixed forms when the remote accepts them.
