# Gold Lion Capital on the sign-in frame (row 249)

Date: 12 Nov 2026. Branch `feature/signin-gold-emblem`, squash-merged to `main` as `476d901`, tag `feature/signin-gold-emblem-done`. Design: `docs/design/signin-gold-emblem.md` (approved).

## What changed
Frontend only: no table, endpoint, job or migration.
- New `frontend/src/components/auth/GoldEmblem.tsx` and the cut-out `frontend/public/brand/assam-emblem-capital-mask.png`; `AuthFrame.tsx`, `auth.module.css` rewritten for the panel (turning gold Lion Capital, Assamese line and motto, Pause / Play button, brand row above the form removed, phone header).
- Gold, glow, wash and emblem-shadow tokens in `globals.css`; Noto Serif Bengali and Devanagari self-hosted (`@fontsource`, `package.json`, lock) for the public pages only; texts in `messages.ts`, icons in `shell/icons.tsx`, `brand.ts`, `Brand.tsx`, `shell.module.css`.
- Tests: `frame.test.tsx`, `frame.css.test.ts`, `layout-signature.json` and its test, `motionRules.test.ts`, `proxy.test.ts`, `shell.test.tsx`, uicheck states in `e2e/uicheck.spec.ts`.
- Docs: design note deviations, decisions log entry, CLAUDE.md current focus.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3245 passed, 3 skipped (58 min), every run green.
- `docker compose build`: succeeded (no `up`).
- Screen check on a private network (temporary `web` image of the branch and `uicheck` image, removed afterwards): 179 routes and states, 574 screenshots, 0 findings; 846 passed, 14 skipped.
- Branch `git status` clean; design status `approved`; decisions-log entry and backlog row present.
- CI on `main` before the merge: `completed success` (run 43189279557).
- Merge: `main` had moved by docs only since the branch point (CLAUDE.md, backlog, decisions log, one design note); the three docs conflicts were resolved by keeping both sides (the new rows 250 to 253 and the case research entry kept; row 249 moved from "next build" to done in CLAUDE.md).

## Review findings
All three were advisory; none blocks, and all are in row 254 (`signin-gold-emblem-followups`): the 820 to 860 px title wrap, the missing uicheck check of the reduced-motion still emblem, and the scribe's "Amended by" lines under portal-ui-redesign decisions 21 and 26.

## Deviations
Recorded in the design note (Deviations 1 to 5): pause shows the still front face, three extra colour tokens, dead `.lockupImage` removed, a uicheck `public` flag, Noto fonts required only from 820 px.

## Follow-up rows
254 `signin-gold-emblem-followups`.

## Pushed
See the commit that adds this report; push result recorded in the integrator's answer.

## Load status
`aslms queue-status` returned nothing within 60 s; not captured. The deploy is the owner's step (no `up` by the integrator).
