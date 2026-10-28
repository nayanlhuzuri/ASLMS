# Report: Case Assistant polish (row 198, `assistant-polish`)

Date: 28 Oct 2026. Branch `feature/assistant-polish`, squash-merged to `main`, tag `feature/assistant-polish-done`.

## What changed
- Enter sends a question in the assistant box; Shift+Enter makes a new line (`Assistant.tsx`).
- Quick facts (next hearing, parties, advocates, status, last order date, bench) answered from the case record without the model, cited to Case Details (`assistant_facts`, `assistant_sources.py`, `assistant_ollama.py`).
- Fewer repeated answers: the model answers only the new question, earlier turns are context only, with a repeat check; one-fact-one-sentence rule.
- Sources open from their reference in the portal. Endpoint and schema additions in `frontend/openapi.json` and `schema.d.ts`.
- No migration, no new table. Docs: decisions log, runbook, workflows 4.9, software documentation 1.3, design note.
- Tests: new `test_assistant_facts.py` (unit and db), extended Ollama tests, portal tests, screen-check additions.

## Gates
- ruff check: All checks passed.
- pytest -q: 2890 passed, 3 skipped (37 min).
- docker compose build: succeeded.
- Portal smoke (web rebuilt and restarted): passed.
- git status clean; design note status approved; decisions-log entry and backlog row present.
- CI on main before the merge: success (run 40662736646, head 45b796e).

## Review findings (all advisory) and closure
1. "Nothing found" line says sources are listed below, but they are behind the Sources button: open, row 202.
2. Quick fact source dialog shows "Text Given to the Model": open, row 202.
3. S1 of a quick fact omits some stated values: open, row 202.
4. Extra queries per Case Details citation on conversation reads: open, row 202.

## Deviations
None beyond those recorded in the design note.

## Follow-up rows
Row 202 `assistant-polish-followups`.

## Load status
`aslms queue-status` was started but had not finished when this report was written.
