# Report: research-index-portal (row 275, round 2 of row 251)

Merged 25 Nov 2026 as squash commit 526a834 on `main`, tag `feature/research-index-portal-done`. Design
`docs/design/research-index-portal.md` (approved by the owner 24 Nov 2026).

## What changed
- Frontend: Research Index section on Data Collection (`ResearchIndexSection.tsx`), research filters on All Court
  Orders and My Cases, passage view of a cited order with the exact passage highlighted, Text Has Changed note,
  removed-sentence notes, `lib/research.ts`, uicheck with nine research states and per-state fixture answers.
- Backend (two read-only additions): the filters a question was asked with on each question message;
  `GET /assistant/filter-choices` for the act and cited-judgment pickers.
- No migration, no table change. 35 files in the squash.

## Gates
- `ruff check .`: All checks passed.
- pytest on a throwaway container of the branch's own postgres image (port 7433, `ASLMS_TEST_REQUIRE_DB=1`):
  3960 passed, 3 skipped, 1:20:03 (the skips are non-database: no POSIX sh, optional-module and non-git checks).
- `docker compose build`: succeeded (shared stack not touched).
- Screen check: run `20261125-0149` (private network, temporary images from the branch), 204 routes and states,
  0 findings. Cited because `git diff 0534aef HEAD -- frontend` was empty.
- CI on main: head 9c53afd, run 45443889316 `success`.
- git status clean (only an untracked `.claude/skills/design-taste-frontend/`, not part of the branch).

## Review
Review closed with mayMerge true and two advisories, both closed: the debounced address write in Cites a Judgment
or Act (ceae728); no Cited Passage card for another order's passage (5138e33). An earlier merge attempt stopped at
4 alignment findings on the Research filters grid; fixed in 472b3b7 and 0534aef.

## Deviations
Design deviations 14 to 16 are recorded in the design note.

## Follow-up rows
Row 279 `research-index-portal-followups` (owner's browser check; the full EXPLAIN of the act and cites choices,
not recorded in this merge; the Word guides stay with row 276). No new rows.

## Load status
Not read: the dev database was not touched in this merge.
