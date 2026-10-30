# Design: the Data Collection page gutter, checked against live data

```
slug: data-collection-gutter-live-check
status: awaiting-approval
author: architect
date: 2026-10-30
approved_by:
```

## Context

Backlog row 187, a follow-up of row 172 `data-collection-redesign` (deviation 18).

**The defect.** Defect D1 of that note: on the owner's screen the Data Collection breadcrumb, title and tabs sat about
3 px from the edge. The fixture screenshots of 25 Oct showed a normal gutter, so the cause was thought to be live data
overflowing a column (a long error, an API path, the estimate's raw JSON). Row 172 fixed it by reading the code, not by
reproducing it:
- `DataFrame` renders `<div className="stack">`;
- cards have `min-width: 0`;
- long values have `overflow-wrap: anywhere`;
- no raw JSON is shown;
- the uicheck rule `gutter` (`frontend/e2e/checks.ts`, `pageChecks`) now measures every page.

The row asks for `docker compose --profile uicheck run --rm uicheck` and the signed-in check at 375, 768 and 1280 px
on `/data/overview`, `/data/collect` and `/data/automatic`, and, if a gutter remains, its cause.

**What has happened since, and what it means for this row:**

| Part of the row | State on 30 Oct 2026 | Why |
|---|---|---|
| "Run `docker compose --profile uicheck run --rm uicheck`" | **Overtaken; the method changes** | On 28 Oct that command recreated the shared `api` without the court-data switch (court searches were off from 03:21 to 07:19 IST). Runbook `docs/operations.md` section 16 now forbids it: the check runs on a private network against images under temporary tags. Row 197 also found that the uicheck image had not built since 26 Oct, so row 172's own run had used a stale image |
| The fixture check of the three pages | **Done, by rows 197 and 173** | After the image was repaired (row 197), row 173's runs on a private network covered `/data/overview`, `/data/collect`, `/data/automatic` and `/data/problems`, each at 375, 768 and 1280 px, with long values in the fixtures: run `20261029-0847` (147 routes and states, 0 findings), run `20261029-1336` (0 findings), and the post-merge run (467 passed, 0 findings). The `gutter` rule found nothing on synthetic data |
| The signed-in check on live data | **Still open; the real gap** | uicheck answers every request from fixtures, so it cannot see a value shape that only live data has. That was the original suspicion. Nobody has measured the pages signed in against the dev database |
| The pages to check | **Widened** | Row 173 added Problems and Fixes (`/data/problems`: failed rows with their problem, CNRs and references) and moved the court call log to System Health's Court Calls section (`/system#calls`). Both now hold the live values D1 suspected. Row 174, on its branch and not merged, rewrites Collect Now (`/data/collect`, a requests list with live progress), so that page must be measured in its merged form |

**Why no agent can do the live part.** Signing in needs the 6-digit code e-mailed at every sign-in (OTP, no bypass in
any `APP_ENV`). The live stack is shared and must not be driven by tooling. A signed-in browser is the owner's.

**Not covered:** pages outside Data Collection and `/system#calls`; any change to the `gutter` rule's definition; the
review advisories of row 172, which are row 191.

## Decisions

1. **The live check uses the uicheck's own measurement, run in the owner's signed-in browser as a console snippet.**
   - Every uicheck run writes `layout-probe.js` into its run folder (`/out/<stamp>/`), beside the results. Its content
     is `pageChecks`, serialised by `Function.prototype.toString` as Playwright serialises it for `page.evaluate`,
     wrapped to run once:

     ```
     (() => {
       const f = <pageChecks>;
       const r = f({ width: document.documentElement.clientWidth });
       console.table(r);
       return r.length;
     })()
     ```

   - So there is one rule and no second copy to drift.
   - It only measures and prints. It makes no request, reads no storage and changes nothing on the page.
   - It is never part of the portal: not under `frontend/src` or `public`, and never served.
   - Alternatives:
     - the owner looks at the pages by eye only. Rejected: 3 px is easy to miss, and the eye does not name the element
       that causes it;
     - a headed Playwright walk of the live stack after the owner signs in. Rejected: a browser download on the host,
       and a script driving the shared stack;
     - live answers captured as fixtures. Rejected: real case references would go into the repository, and the shapes
       change daily.
2. **Every geometry kind is printed, not only `gutter`.** D1's 3 px could equally be `page-overflow` or `off-screen`
   (a child wider than the screen moves everything sideways), and the probe reports all three. Findings of other kinds
   are recorded too.
3. **What is measured, each at 375, 768 and 1280 px (DevTools' responsive mode) and at the owner's own window width:**
   - `/data/overview` with Waiting Work opened and Month by Month scrolled to its end;
   - `/data/automatic` with the schedule and Search by Department Names in view;
   - `/data/collect` with the Requests list showing and one request's items opened (after row 174);
   - `/data/problems` with every section drawn;
   - `/system#calls`.

   The check is signed in as the Super Administrator, who sees every tab and every row.
4. **The build has three steps, and the row is done only when step 3 is recorded in this note.**
   - **Step 1, the developer:**
     - the snippet writer in `frontend/e2e/global-setup.ts`;
     - a self-test proving the snippet finds what `pageChecks` finds;
     - one screen check on a private network that produces the snippet.
   - **Step 2, the owner, about ten minutes:**
     - open each page and state of decision 3 at each width;
     - paste the snippet into the console (Chrome asks once for "allow pasting");
     - send back the printed table, or "0", per page and width.
   - **Step 3, the developer:**
     - **If a finding:** read the named element, the cause. Reproduce it with a synthetic fixture value of the same
       shape (length and characters, never the real reference) in `frontend/e2e/fixtures`, so uicheck fails before the
       fix and passes after it. Fix the component, and record the cause.
     - **If none:** record "D1 not reproduced on live data" with the date and the widths, and close D1.

   This avoids row 173's lesson, where the role-based live checks were never recorded (row 204, item 3).
5. **A finding on these pages is fixed in this row if it is a layout fix in the Data Collection or Court Calls
   components.** Anything larger, or on another page, becomes a new backlog row, named in step 3's record.
6. **This row builds after row 174 merges**, so that Collect Now is measured in the form it keeps. It does not depend
   on row 191.
7. **No migration, no API change, no backend change.** The changes are the uicheck tooling and, only if step 3 finds a
   cause, the component and fixture that fix it.

Nothing here deviates from the plan. The row's own wording (the Compose command) is superseded by the runbook, as
the Context table says.

## Data

None. No table, column or reference code; no migration; `docs/schema/schema.md` unchanged.

## Services

None. No backend module changes.

**Frontend tooling** (`frontend/e2e/`, not shipped):
- `global-setup.ts` writes `layout-probe.js` into the run folder from `pageChecks` (imported from `checks.ts`). The
  file carries a header comment: what it is, that it only measures, and the page and widths to run it at.
- `checks.ts` keeps `pageChecks` self-contained, as its comment already requires.

## API

None. The snippet makes no request. Each page it runs on makes only its normal reads, under its normal function
(`data_load.READERS` for Data Collection; `admin.service_health` plus a health reader for `/system#calls`).

## Jobs

None.

## Tests

- `frontend/e2e/uicheck-self.spec.ts`:
  - **the probe matches the rule:** on the existing self pages (the 3 px gutter with a value past the content box, and
    the kept gutter with a `data-scroll-x` region and a hidden caption), evaluating the generated snippet's source
    gives the same findings as `page.evaluate(pageChecks, …)`: two gutter findings on the first, none on the second;
  - **the probe writes nothing:** after it runs, the page's DOM serialisation is unchanged, and no request is seen
    (`page.on("request")` stays silent).
- `npx tsc --noEmit` in `frontend/e2e` clean (the image build runs it).
- Step 3, only if a finding: a fixture value reproducing it, and the uicheck state that shows it, so the run fails
  without the fix.

## Verification

1. **Step 1:** one screen check as `docs/operations.md` section 16 says (temporary `tmpX-web` and `tmpX-uicheck`
   images, a private network, the shared stack untouched).
   - Expected: 0 findings on `/data/overview`, `/data/collect`, `/data/automatic`, `/data/problems` and
     `system-court-calls` at the three widths, with the self-tests passing.
   - `layout-probe.js` is present in the run folder and is handed to the owner. Then the container, the network and
     the images are removed.
2. **Step 2, the owner's record**, a table added to this note:

   | Page and state | 375 | 768 | 1280 | Own width (px) |
   |---|---|---|---|---|
   | `/data/overview` | | | | |
   | `/data/automatic` | | | | |
   | `/data/collect` | | | | |
   | `/data/problems` | | | | |
   | `/system#calls` | | | | |

   Each cell holds the probe's count (and, if any, its rows).
3. **Step 3:** either "D1 not reproduced on live data, <date>", or the cause and fix with the uicheck run that fails
   before and passes after. Then the definition of done as usual: `npm run lint`, `npm run typecheck`, `npm test`, and
   the private-network screen check with 0 findings.

## Open questions

None. Step 2 is an owner step (ten minutes, signed in), not a question.
