# Design: Next.js security release 16.4.6

```
slug: next-security-upgrade-2
status: approved
author: owner session
date: 2026-11-23
approved_by: owner on 2026-11-23
```

## Context
Backlog row 269 (scribe, 19 Nov 2026, row 259's closing note, design deviation 30). `npm audit --omit=dev` reports one
moderate advisory on `next` 16.4.3 (GHSA-mfr8-8qww-v76h and GHSA-vc7v-qv4w-wrv8, published after row 205), fixed in
16.4.6. Row 205 `nextjs-security-upgrade` set the pattern: exact pins, both suites, the build, the uicheck.

## Decisions
1. Pin `next` and `eslint-config-next` exactly at `16.4.6` in `frontend/package.json` (no caret), and update
   `frontend/package-lock.json` with `npm install` (not `npm update` of anything else).
2. No other dependency changes. If 16.4.6 needs a code change (a deprecation, a type change), make the smallest one
   and record it here as a deviation.
3. Gates: `npm audit --omit=dev` reports 0 vulnerabilities; lint, type check, vitest and the Playwright suite green;
   `next build` succeeds; uicheck at 375, 768, 1024 and 1280 px with 0 findings, run on a private network against
   temporary images, never through Compose on the shared stack (runbook section 16).
4. Frontend only, no migration, no backend change. The deploy is a `web` rebuild from `main` with the build ID checked.

## Tests
The existing suites; no new test unless a code change needs one.

## Open questions
None.

## Deviations
1. Context names two advisories; on 23 Nov 2026 `npm audit --omit=dev` on 16.4.3 listed the one moderate finding
   (`next` 16.0.0 to 16.4.4) under seven advisories: GHSA-mfr8-8qww-v76h, GHSA-vc7v-qv4w-wrv8, GHSA-7qx7-33qx-rqx2,
   GHSA-f3mh-rxg3-f5g2, GHSA-pc58-hwjq-p385, GHSA-rhh4-g77r-r9qj and GHSA-vvgp-ww4w-46vf. All are fixed by 16.4.6, so
   the decisions stand unchanged; after the pin `npm audit --omit=dev` reports 0 vulnerabilities. No source change was
   needed: the lock file changes only `next`, `eslint-config-next`, `@next/env`, `@next/eslint-plugin-next` and the
   `@next/swc-*` binaries, all at 16.4.6.

## Verification (developer, 23 Nov 2026)
- `npm ci` in a worktree's own `frontend/node_modules`: `next` and `eslint-config-next` 16.4.6 installed;
  `npm audit --omit=dev`: found 0 vulnerabilities.
- `npm run lint` clean, `npm run typecheck` clean, `npm test` 112 files and 2823 tests passed, `npm run build`
  succeeded (Next.js 16.4.6), `npm run gen:api` leaves no diff.
- uicheck on a private network against temporary images (`tmpnsu2-web` with alias `web`, `tmpnsu2-uicheck` with
  Playwright 1.64.1), never through Compose: 195 routes and states, 638 screenshots, 0 findings, `findings.json`
  empty, 563 s; 910 passed and 14 skipped (the width-only states); containers, network and images removed after.
- Backend unchanged: `ruff check` clean and `pytest -q` on a throwaway PostgreSQL 16.15 with
  `ASLMS_TEST_REQUIRE_DB=1`: 3865 passed, 3 skipped (the reviewer's run of this branch's own tree; an earlier
  recorded figure of 3871 came from a different tree and is withdrawn) (the three skips are Windows-only or sample-only:
  symbolic links, POSIX permissions, a hand-saved encrypted envelope; no database test skipped).
