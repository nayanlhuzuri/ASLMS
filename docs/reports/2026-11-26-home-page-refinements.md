# home-page-refinements (row 281)

Merged 26 Nov 2026 as a343192 (squash of `feature/home-page-refinements`), tag `feature/home-page-refinements-done`.

## What changed
Frontend only, no migration, no table, no endpoint. `frontend/src/components/home/` (HomePage, new HomeSamples,
homeChat, sampleData, SignInCard; HomePreview and jumpToSignIn removed), `home.module.css`, `auth.module.css`,
`messages.ts`, `layout-signature.json`, `frontend/e2e/uicheck.spec.ts` (first-screen and level-pictures state),
design note, decisions log, CLAUDE.md.
The hero with the sign-in card is the whole first screen; top bar and closing band removed; sample pictures are
the Case Inbox (With Me) and a cited Assistant answer drawn from the kit with sample data.

## Gates
- CI on main (4fbbfe0): success (run 45571388061).
- `ruff check .`: All checks passed.
- `pytest -q` against a throwaway container of the branch's postgres image (port 7433, `ASLMS_TEST_REQUIRE_DB=1`): 3960 passed, 3 skipped, 1:41:16 (the same 3 skips as the earlier runs of 3,960).
- `docker compose build`: all eight images built (no `up`; the shared stack untouched).
- Screen check on a private network against `web` built from the branch: run `20261126-1437`, 207 routes and states, 680 screenshots, 0 findings, 972 passed, 16 skipped (phone and tablet skip the laptop-only states, by the spec). The `/login (first screen and pictures)` state ran at the laptop and desktop widths.
- Design note status `approved`; decisions-log entry and backlog row present.
- `git status` on the branch: only the untracked `.claude/skills/design-taste-frontend/` (not part of the feature, not merged).

## Review findings and closure
1. Advisory, `messages.ts` `T.home.samples.assistantAria` says the answers cite "the court order or cause list", the picture cites the order and Case Details: open, row 282.
2. Advisory, no recorded uicheck run: closed by the run above (`20261126-1437`, 0 findings); no production build was run apart from the `web` image build.
3. Advisory, server-rendered first HTML shows a blank conversation and a Pause button under reduced motion until hydration: open, row 282.

## Deviations
None beyond those in the design note. The untracked skill folder was left alone.

## Follow-up rows
282 `home-page-refinements-followups` (findings 1 and 3).

## Push
See the final line of the integrator's return (main and the tag).

## Load status
`aslms queue-status` run after the merge: status_batch 4,715 done, 147 pending, 1 running, 10 skipped; order_pdf 437 skipped (full table in the command output).
