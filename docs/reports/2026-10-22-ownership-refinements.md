# Report: ownership-refinements (row 120), 2026-10-22

Design: docs/design/ownership-refinements.md (approved 21 Oct 2026). Squash-merged from `feature/ownership-refinements`; tag `feature/ownership-refinements-done`.

## What changed
- Backend: `services/ownership.py`, `matching.py`, `court_search.py`, `recipients.py`, `alerts.py`, CLI `aslms close-claimed-recommendations`; migration 0021 (enum value `claimed_elsewhere` on `recommendation_status`, `ref_event_type` row `recommendation_closed`; no table or column added).
- Claim or accepted transfer queues a `dossier` row (request lane) through the queue only; database-answered court searches return before the guard and are not counted; a primary claim closes other departments' open recommendations (`claimed_elsewhere`, named notice); engine never recommends a claimed case; every suggestion alerts the target's claimers.
- Frontend: Search ticks "Only cases I can open" by default, closed-recommendation display, filters, messages, OpenAPI schema.
- Docs: decisions log, schema.md, backlog.

## Gates
- ruff check: All checks passed
- pytest -q: 2013 passed, 3 skipped (27m46s)
- docker compose build: succeeded
- portal_smoke.py: passed
- git status clean; design status approved; decisions-log entry and backlog row present.
- CI on main: unknown (`gh` is not installed).

## Review findings (all advisory)
1. Backfill has no cut-off and can close post-claim suggestions on a repeat run: not fixed, row 130. The planned one-off run is made once; do not repeat `--apply`.
2. `apply_scores` reads claimed state without the case row lock (race with a claim): not fixed, row 130.
3. `_suggestion_event` calls `session.get(Recommendation, None)` (SAWarning): not fixed, row 130.

## Deviations
None beyond those recorded in the design note.

## Follow-ups
Row 130 (the three advisories).

## Push
See the integrator's return values (pushed commit and CI address).

## Load status (`aslms queue-status`)
dossier skipped 29; masters done 1; order_pdf done 116772, pending 185291, skipped 4; status_batch done 887, skipped 6.
