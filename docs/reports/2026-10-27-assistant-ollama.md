# Report: assistant-ollama (backlog row 188, round 1 of 2)

Merged 2026-10-28 by the integrator. Tag `feature/assistant-ollama-done`. Design: `docs/design/assistant-ollama.md` (status approved).

## What changed
- `ASSISTANT_MODE=ollama` beside off, preview and sourcetrace. The Ollama HTTP client, its settings and the `FakeOllama` transport live in `backend/aslms/integration/ollama/`; services in `assistant_ollama.py` and `assistant_internal.py`.
- Court information is read in every scope. One case's internal records (saved notes, file movement trail, pending actions, department documents; never drafts) only after the officer switches on Include This Case's Internal Records in that case's Assistant tab: one-way, audited, per conversation, limited to what the asker may open.
- Portal: local-model state, the switch and its dialog, source panels (`frontend/src/components/assistant/Assistant.tsx`, `frontend/src/lib/assistant.ts`), `frontend/openapi.json`.
- Migration 0032: the ollama mode CHECK and `assistant_conversations.internal_included_at`.
- Compose `extra_hosts` and the optional `ollama` profile, settings example, runbook section 20, System health card, `no_cloud_model` preflight, `no_local_model` guard widened.
- CLAUDE.md rules, decisions log, software documentation (docx regenerated).

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 2619 passed, 3 skipped (42 min), every run green.
- `docker compose build`: succeeded.
- Portal smoke (`docker compose up -d --wait --no-deps web`, `portal_smoke.py`): passed.
- `git status` clean on the branch; design status approved; decisions-log entry and backlog row present.
- CI on `main` before merge: last run success (run 40548710721).

## Merge notes
The squash conflicted in `docs/backlog.md`, `docs/software-documentation/build.js` and the docx (main had gained rows 192-194 and hosting-guide changes). Resolution: backlog keeps main's rows 192-194 and the branch's follow-up becomes row 195 (references in CLAUDE.md and the decisions log renumbered); build.js takes the branch's Assistant wording at each conflict (main's other changes merged automatically); the docx was regenerated from the merged build.js (10,013 words against main's 9,653). TOC_PAGES not re-checked against a rendered copy (design deviation 15 stands).

## Review findings and closure
All eight were advisories and were not fixed in this cycle; none blocked the merge.
1. Copy to note numbering versus [S#] labels (`assistant.ts` noteText): open, to be handled in rows 189 / 195.
2. Internal records button shown when the asker can open none (not recorded as a deviation before): open; the server answers 422 `no_internal_records`. Noted for row 189.
3. Switch time `now()` versus the question's start time: open, may give a false alarm in `aslms assistant check`; row 189.
4. Department document pages may exceed the remaining internal budget: open, bounded by the `num_ctx` fit check; row 189.
5. "Text Given to the Model" for department documents rebuilt at 3000 characters: open; row 189.
6. Readiness check up to three sequential calls, not single-flighted: open; row 195 live check on the pilot machine.
7. build.js / docx conflict: closed here by the hand merge and regeneration above.
8. The rule change versus the plan: rests on the owner's approval (commit a1ea095, decisions log, design decision 1). The owner should confirm the variation; the plan document still says all AI goes through SourceTrace.

## Deviations
Design deviations 1-18 are in the design note; round 2 tests are left to row 189.

## Follow-up rows
- Row 195 `assistant-ollama-live-check` (renumbered from the branch's 192): the owner's live check of the local model on the pilot machine.
- Row 189 `assistant-ollama-work` (round 2) already exists.
- No new rows added by the integrator; advisories 1 to 6 are left for the developer to fold into rows 189 and 195.

## Push
See the final return of the cycle; recorded after the push.

## Load status (`aslms queue-status`)
status_batch: 1417 done, 6 skipped (tail of the output; the database was up).
