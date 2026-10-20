# portal-ui-foundation (backlog row 101, round 1 of 5)

Merge commit: e8de1c9 on main; tag `feature/portal-ui-foundation-done`. Design: docs/design/portal-ui-redesign.md.

## What changed
Frontend only (55 files): design tokens, self-hosted Inter, motion with prefers-reduced-motion; restyled and
extended UI kit (Card, PageHeader, Kpi, Chip, Skeleton, Collapsible, Menu, SidePanel, Modal, Stepper, DataTable
with phone cards, Lead / DateChip); header with emblem slot (`src/lib/brand.ts`), grouped sidebar, phone drawer and
bottom bar, breadcrumbs, i18n seams (`src/lib/i18n.ts`). No migration, no table, no endpoint, no API change.

## Gates
- ruff check: All checks passed
- pytest -q: 1663 passed, 2 skipped
- docker compose build: succeeded
- portal_smoke.py: portal smoke: passed
- git status clean; design status approved; decisions-log entry and backlog row present

## Push and CI
No remote (`origin` not configured) and `gh` is not installed: nothing pushed; CI status unknown.

## Review findings (all advisory, recorded and not fixed in this round)
1. overlays.tsx: dialog still clickable during the 220 ms exit animation (double submit risk if a parent does not reset).
2. PortalShell.tsx: drawer state not cleared when the viewport grows past 820 px (scroll lock and Tab trap stay).
3. layout.tsx: tab underline not re-measured when a single tab's width changes.
4. CaseFrame.tsx: h1 uses the semibold `cno` class even for a bare ref_no (should stay monospace).
5. overlays.tsx:68: initial focus goes to the Close button rather than the first field (unchanged from main).
6. i18n.ts: `in` lookup matches inherited Object.prototype keys; use Object.hasOwn.
7. `wide` Dialog (720 px) is narrower than the default (760 px); JSDoc is wrong; no callers yet.
Follow-up: items 1-7 should be picked up in rounds 2-3 (no separate backlog row added).

## Deviations
None beyond those written back into the design note.

## Load status
Not collected for this frontend-only merge.
