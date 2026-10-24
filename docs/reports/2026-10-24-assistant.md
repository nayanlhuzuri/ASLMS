# Report: assistant (backlog row 14)

Date: 2026-10-24. Branch `feature/assistant`, squash-merged into `main` as 99fb399, tag `feature/assistant-done`.

## What changed
- Migration 0024 (`backend/migrations/versions/0024_assistant.py`): `assistant_conversations` and `assistant_messages`, message columns, CHECKs, append-only rule, the `my_cases` scope. Applied by the owner's `migrate` step after the merge; the dev database is at 0023 and was not touched.
- SourceTrace connector query contract and the fake's ask; preview mode (word search over stored court-record text, dev and test only); eligibility rule; one unanswered question per user; conversations API; `aslms assistant` CLI.
- Portal: case Assistant tab, Assistant page, court-record view (22 frontend files).
- 53 files, 11196 insertions, 1817 deletions in the squash.

## Gates
- ruff check: all checks passed.
- pytest: 2184 passed, 3 skipped (28 min).
- docker compose build: succeeded.
- Portal smoke (web rebuilt and healthy): passed.
- git status clean; design note `approved`; decisions-log entry, schema note and backlog row present.
- CI on main before merge: success, run 40104920460 (court-data-freshness). origin/main equalled local main.
- Developer's vitest: 1312 passed (not rerun).

## Review
Round 1: may merge, 11 advisories. 1-8 and 11 fixed (0e57a09, 7ecc58e, db2f2c8, f5bf71b; Deviations 17-24). 9 folded into row 36. 10 is row 140.

## Follow-up rows
- 140 assistant-cli-user-check
- 141 assistant-owner-browser-check

## Deviations
Deviations 1-24 are in `docs/design/assistant.md`.

## Load status
`aslms queue-status` did not answer within 120 s when run; not recorded.

## Push
See the integrator's return message.
