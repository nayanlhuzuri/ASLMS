# Report: Case Assistant polish follow-ups (row 202, `assistant-polish-followups`)

Merged 3 Nov 2026 as squash commit 1c30913 on `main`, tag `feature/assistant-polish-followups-done`. The cycle
started on 2 Nov 2026; the merge run was interrupted after the squash commit and tag by a machine shutdown, and the
report, the backlog close and the push were finished on 3 Nov 2026 from the gate results recorded by the integrator.

## What changed
- Backend: `services/assistant_ollama.py` (the nothing-found line points to the Sources button instead of "listed
  below"), `services/assistant_facts.py` (a quick fact's S1 is the facts form: it adds the date entered in ASLMS, party
  counts and the last order date and number, hidden from a reader who can no longer open the case),
  `services/assistant.py` and `services/assistant_sources.py` (Case Details read once per conversation read instead
  of about three queries per citation).
- Portal: `components/assistant/Assistant.tsx` and `lib/messages.ts`: a quick fact's source dialog shows Facts From
  the Case Record and hides "Text Given to the Model" (no model was called).
- Tests: `tests/db/test_assistant.py`, `test_assistant_facts.py`, `test_assistant_ollama.py`,
  `tests/unit/test_assistant_facts.py`; `assistant.test.tsx`, `labels.test.ts`.
- Docs: design note with its deviations, decisions log, backlog, CLAUDE.md.
- No tables, endpoints, API shape change or migration (`alembic heads` still 0035). No NAPIX call.

## Gates
- `ruff check` and `ruff format --check`: clean.
- `pytest -q`: 3179 passed, 3 skipped (35 min 54 s), every run green.
- Frontend (developer): Vitest 89 files, 1936 tests; lint, typecheck and build pass; `gen:api` shows no diff.
- `docker compose build`: succeeded (no `up`; the shared stack was not touched).
- Screen check on a private network (temporary `web` and uicheck images from the branch, then removed): 0 findings.
- CI on `main` before the merge: last run success (41495192156).

## Review findings
- Advisory, `backend/tests/db/test_assistant_facts.py:537`: the lost-sight test covers only a date entered by hand;
  decision 3 also hides a confirmed reading (through `next_hearing(public=True)` and `court_public`) from a reader
  who can no longer open the case, and no database test covers that. Not fixed in this cycle (see follow-ups).

## Deviations
- None beyond those in the design note.

## Follow-ups
- Row 219: a database test that a confirmed reading in a quick fact's S1 is hidden from a reader who lost sight of
  the case.

## Load status
At 14:19 IST on 3 Nov 2026: cause lists 671 of 671 days; 83,317 cases; 200,734 of 390,063 order PDFs stored, none
failed; the weekly case-details refresh had about 4,660 cases left before order PDFs resume.
