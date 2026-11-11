# Report: portal-motion (row 235)

Date: 2026-11-12 (branch `feature/portal-motion`, design `docs/design/portal-motion.md`, approved 11 Nov 2026).

## What changed
Frontend only, no migration, no endpoint or table change (60 files, about 1,485 insertions and 242 deletions).
- Confirmation toast (6 s, pauses on hover or focus, polite status region) in place of inline success notices.
- Sliding thumb for the kit's segmented switch and switches, through one shared sliding-mark hook.
- Side-menu hover slide of 4 px by transform; reduced-motion fallback kept.
- Layout signature updated; uicheck skips motion layers in the box comparison and has two toast states.
- New tests: `toast.test.tsx`, `toastGuard.test.ts`, others in the kit.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3245 passed, 3 skipped (48 min 52 s).
- `docker compose build`: succeeded (no service recreated).
- Screen check on a private network against a `web` image built from the branch: 176 routes and states, 425 screenshots, 0 findings, 596 passed, 7 skipped. Temporary containers, network and images removed.
- CI on main: last run success (run 43075819424). Branch holds only row 235 commits. Design status approved; decisions-log entry and backlog row present.

## Push and CI
See the integrator's return values; the push of `main` and the tag `feature/portal-motion-done` follows this commit.

## Review findings
Two advisories, both left open and recorded as rows:
1. Case Claim toast with a link never closes on its own, stays over the next case modal and is unreachable by keyboard under its focus trap: row 246.
2. A repeated toast with identical text is not re-announced by screen readers: row 247.

## Deviations
None beyond the design note's build deviations section.

## Follow-up rows
246 `toast-link-persists`, 247 `toast-repeat-announce`. Row 238 `rolling-case-refresh` is next.

## Load status
`aslms queue-status` did not answer within 120 s (the worker is using the full court allowance); not recorded here.
The deploy after CI is the owner's step: build from a clean worktree of `main`, recreate app services with `--no-deps --force-recreate`.
