# Design: Next.js security upgrade to 16.4.3

```
slug: nextjs-security-upgrade
status: approved
author: architect
date: 2026-10-29
approved_by: owner on 2026-10-29
```

## Context
Row 173's build printed Next.js's notice that the installed version has a known vulnerability. `npm audit --omit=dev`
on 29 Oct 2026 reports one critical finding: `next` 16.0.0 to 16.4.0 (installed 16.4.0, `"next": "^16.4.0"`), three
advisories, all fixed from 16.4.1 (newest 16.x: 16.4.3):
- GHSA-2464-fhr4-w9xw (critical): remote code execution in the Image Optimization API with SVG files, through the
  `sharp` library on glibc Linux; fixed by `sharp` 0.35.5 or later.
- GHSA-673q-mjm6-r5xr (critical): remote code execution in `use cache` functions returning typed arrays.
- GHSA-p3m5-59mp-jv5r (high): denial of service in the App Router with at least one Server Action.

Exposure as read on 29 Oct 2026: the lock file already resolves `sharp` 0.35.5 and the `web` image runs on Alpine
(musl), the portal shows images with plain `<img>`; there is no `use cache` and no `use server` in `frontend/src`. So
none is exploitable today, but `npm audit` stays critical while 16.4.0 is pinned and any later Server Action or cache
function would expose the portal. The owner asked for the upgrade on 29 Oct 2026, placed straight after row 174.

## Decisions
1. Upgrade `next` to exactly the newest 16.4 patch, 16.4.3, with `eslint-config-next` and any `@next/*` package at the
   same version; refresh `package-lock.json` with `npm install` (no `npm audit fix --force`, no major or minor bump of
   anything else). Alternative: `next upgrade --agent=security` — not used, it may change more than the patch.
2. `npm audit --omit=dev` must report no critical or high finding afterwards; anything left that has no fix is listed
   in the report with its exposure.
3. No source change unless 16.4.3 requires one; any such change is a deviation recorded here.
4. No backend change, no migration, no new setting.

## Data
None.

## Services
None.

## API
None.

## Jobs
None.

## Tests
The existing suites are the test: vitest, lint, typecheck, `npm run build`, the e2e harness `tsc`, `gen:api` with no diff,
and the browser screen check on a private network (`docs/operations.md` section 16) with 0 findings.

## Verification
1. `node -p "require('next/package.json').version"` in `frontend/` prints 16.4.3.
2. `npm audit --omit=dev` reports no critical or high finding.
3. The frontend suites above pass; the screen check passes with 0 findings.
4. After the deploy: `portal_smoke.py` passes.

## Open questions
None.
