# Report: case-stages-extension (backlog row 61)

Merged to `main` as a squash commit (tag `feature/case-stages-extension-done`). Design: `docs/design/case-stages-extension.md` (approved).

## What changed
- Migration 0016 (`0016_case_stages.py`): reference data only, seven inserts into `ref_case_stage` (ON CONFLICT DO NOTHING). No table or column change. Downgrade refuses while a case uses a new code.
- Codes: `review_petition_filed`, `appeal_dismissed`, `appeal_allowed`, `further_appeal_filed`, `complied_after_dismissal` (phase appeal); `vakalatnama_submitted`, `contempt_disposed` (phase contempt). Catalogue is now 24 stages.
- `aslms/domain/reference.py` (Stage enum), `aslms/services/seed.py`, `aslms/services/stages.py` (docstring), `docs/schema/schema.md`, decisions log, CLAUDE.md focus.
- Endpoints: none added or changed; `GET /workflow/codes`, `POST /cases/{ref}/stages` and Send file read the catalogue.
- Tests: `tests/unit/test_case_stages_extension.py`, `tests/db/test_migration_0016.py`, additions to `tests/db/test_api_workflow.py`.

## Gates
- ruff check: All checks passed!
- pytest -q: 1015 passed, 84 warnings (1224.75s)
- docker compose build: succeeded
- Portal smoke: not required (`frontend/` unchanged)
- git status clean; design status approved; decisions-log entry and backlog row present.

## Review findings and closure
1. Advisory, send-path test does not check the `stage_set` event payload (`phase: "appeal"`): not fixed; the direct-path test covers the payload. Follow-up row 66.
2. Advisory, decisions log lacked the convention change (new `ref_*` codes now also through a migration): closed; the scribe's decisions-log entry records it ("a change of convention").
3. Advisory, containers running old code reject the new codes after `alembic upgrade head`: no code change; after `init`, restart `api`, `worker` and `scheduler`. Noted in follow-up row 66.

## Deviations
Those listed in the design note's Deviations section (hand-written migration with one insert per row; no-op test also checks a seeded label edit survives; unit test compares migration rows with the seed).

## Follow-ups
Row 66: assert the `stage_set` event payload in the send-path test; add the restart-after-init step to the verification notes.

## Load status (`aslms queue-status`, abridged)
causelist_day pending 493, skipped 67; dossier done 32603, failed 370, pending 448, skipped 29; order_pdf done 23156, failed 3, pending 194706, skipped 113; status_batch done 253, failed 1, skipped 5; masters done 1.
