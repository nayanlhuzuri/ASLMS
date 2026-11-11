# Design: Portal motion, the toast, the sliding switch and the menu hover slide

```
slug: portal-motion
status: approved
author: architect
date: 2026-11-11
approved_by: owner on 2026-11-11
```

## Context

Backlog row 235. **Owner, 10 Nov 2026** (decisions log, "2026-11-10 — Portal UI review approved; rows 228 and 229
approved (owner)", and the answers recorded in `docs/design/portal-navy-cream.md`, "Motion: yes"): the owner wants three
transitions from the approved navy-and-cream sample. Row 229 left them out because each one adds an element or moves
one:

- the confirmation toast after an action;
- the sliding segmented switch (My Work and Department on the dashboard);
- the side-menu hover slide.

All three stay within the motion tokens and the reduced-motion fallback. The decisions log (10 Nov 2026, "Motion") sets
the sample's character: 0.15 to 0.4 s, easing to a stop, no bounce.

**The plan.** The plan fixes what each screen holds (Annexure B, "Indicative UI Screens"). It says nothing about
motion, toasts or switches, so nothing here deviates from it. This row amends two earlier design decisions, each marked
where it applies:
- portal-navy-cream decision 12 (its table marks the toast and the sliding pill "not adopted" and the menu slide
  "rejected");
- portal-workflow decision 6 (the flash notice shown as an inline notice on the next page).

**What exists (read for this design, `main` at 78a5ff8).**
- **Motion tokens** in `frontend/src/app/globals.css` `:root`:
  - `--ease` `cubic-bezier(0.2, 0.8, 0.2, 1)`, the sample's own curve;
  - `--fast` 150 ms, `--med` 220 ms, `--slow` 320 ms.

  Under `prefers-reduced-motion: reduce` the three durations are 0 ms and every animation and transition is off
  (portal-ui-redesign decision 13). `components/ui/motion.ts` mirrors them for the JavaScript parts: `DURATION`,
  `usePrefersReducedMotion()`, `usePresence(open, ms)` and `useCountUp`. `motion.test.tsx` proves the fallback.
- **The sample's three transitions** (`docs/design/ui/navy-cream/`):
  - **Toast** (`CaseClaim.dc.html`): a navy 900 card at the bottom right with white text and a light-orange check.
    It enters by rising 24 px with a fade (`transform .38s` on the curve, `opacity .3s`) and stays 3.2 s. It is a
    `role="status"` `aria-live="polite"` element, and a new toast replaces the current one.
  - **View switch** (`Dashboard.dc.html`): a pill under the two buttons that slides with
    `transform .32s` on the curve, while the text colour changes over `.25s`.
  - **Menu hover slide** (both files): `.nav-link:hover` changes `padding-left` from 30 px to 36 px over `.22s`.
- **Confirmation today:** an inline `<Notice tone="success">` (`components/ui/feedback.tsx`, `role="status"`) is
  rendered in the page flow, so the content below it moves down when it appears. There are 29 call sites:
  - **26 confirm an action just done on a shell page:**
    - `admin/mapping/CounselCodes.tsx`, `Keywords.tsx`, `Watchlist.tsx`;
    - `admin/UserTypes.tsx`;
    - `assistant/Assistant.tsx`;
    - `case/CaseFrame.tsx`, `case/Notes.tsx`;
    - `causelist/DayBar.tsx`;
    - `claim/ClaimFrame.tsx`, which shows the text with an Open Case Page link;
    - `data/AutomaticCollection.tsx` (three), `data/CollectNow.tsx` (three), `data/CollectRequests.tsx`;
    - `nextdates/CaseNextDate.tsx`, `nextdates/ReviewList.tsx`;
    - `profile/Profile.tsx` (three);
    - `workflow/CustodyDialogs.tsx`, `CustodyTab.tsx`, `DraftsPanel.tsx`, `NoteComposer.tsx`, `Upload.tsx`.
  - **One is shown inside an open dialog:** `admin/UserDetail.tsx`, "Temporary password set" in the Reset Password
    dialog.
  - **Two are on the sign-in pages, outside the shell:** `auth/SignInForms.tsx`, password changed and code re-sent.
  - **The flash:** `lib/flash.ts` (`setFlash`, `peekFlash`, `clearFlash`, in sessionStorage) carries a notice to the
    next page. `workflow/common.tsx` `FlashNotice` shows it inline on the dashboard and on the Case Inbox
    (`InboxFrame.tsx`). It is set by `CustodyDialogs.tsx` and `CloseCaseDialog.tsx`.

  The portal has no toast.
- **The kit `SegmentedSwitch`** (`components/ui/controls.tsx`):
  - a `role="radiogroup"` with `role="radio"` buttons and arrow-key movement;
  - `.segmented` is a 2 px-padded shaded track, and `.segmentOn` paints the chosen option with `--surface`,
    `--shadow-1` and `--action` text. The ground jumps from one option to the next.
  - It is used on the dashboard (My Work, Department, State), in the Case Inbox's Show switch, on My Calendar,
    Transfers, Keywords, the Assistant, Problems and Fixes, and through `SegmentedField` in the filter bar.
  - Options are as wide as their words, so a pill of half the width (as in the sample) would not fit them.
- **The kit `Tabs`** already slides an element: the `.ink` underline is a `span` (`aria-hidden`) that is measured
  from the current tab's `offsetLeft` and `offsetWidth`. It is placed by a layout effect with a `ResizeObserver` on
  the row and on each tab, and placed again on `document.fonts.ready`. It is positioned with `style={{ left, width }}`
  (the CSP allows `style-src 'self' 'unsafe-inline'`, `src/proxy.ts`) and moves with `left` and `width` transitions
  over `--med`.
- **The side menu** (`components/shell/shell.module.css`, `NavTree.tsx`):
  - every row is an `a.row` (`.nav a`), 36 px high with `padding: 0 var(--s3)`, holding `.navIcon`, `.navLabel`
    (truncating), the optional `.navCount` and the parent's `.chevron`, pushed right by `margin-left: auto`;
  - hover changes only the background and the colour, over `--fast`;
  - child rows are `a.row.childRow`.
- **The proof tools of row 229:**
  - `components/ui/layoutSignature.test.ts` with `layout-signature.json` (regenerated only under
    `UPDATE_LAYOUT_SIGNATURE=1`; row 244 will make a missing file fail);
  - uicheck's box comparison (`UICHECK_BOXES=1`, `e2e/boxes.ts`, `e2e/boxdiff.ts`, runbook section 16);
  - the token test's contrast pairs and the colour-literal guard.
- **Fixed layers today:** dialogs (`overlays.module.css`, z-index 60), the phone drawer (61, 62) and the bottom bar
  (40, 64 px high, phones under 820 px). The user-type page's Save bar (`admin.module.css` `.saveBar`) is
  `position: sticky` at `bottom: var(--s4)`, `--savebar-h` (64 px) high.

**Not covered** (not asked for in row 235; each would be its own row if the owner wants it):
- the sample's other motion: the staggered 14–16 px entrance rise, the 4 px tile lift, the claimed "pop", the check
  draw, the row slide-out after a claim, the pulsing urgent badge, the growing link underline and the "View All" arrow
  gap. The pop also bounces (`scale(1.08)`), which the decisions log rules out;
- the sample's solid navy pill with white text: colours stay as row 229 set them (decision 9);
- any change of wording: every confirmation keeps its words.

## Decisions

### A. The confirmation toast

1. **One kit toast, raised by a hook.**
   - `components/ui/feedback.tsx` gains `ToastProvider` and `useToast()`; the CSS goes in `feedback.module.css` and
     both are exported from `components/ui/index.tsx`.
   - `useToast()` returns `toast(text: string, link?: { href: string; label: string })`.
   - `ToastProvider` renders its children, then the toast host as its **last child**.
   - `PortalShell` wraps the content of `.frame` in it, so the host is the frame's last element, after
     `SessionWatch`. Only signed-in shell pages have it.
   - `useToast()` outside a provider throws an error naming `ToastProvider`, so a confirmation is never lost
     silently.

   Alternatives:
   - a toast library (a dependency, and portal-ui-redesign decision 13 says no animation library);
   - a toast per page (a different place and timing on each page).

2. **Every confirmation of an action just done on a shell page becomes a toast.**
   - All 26 call sites listed under Context call `toast(...)` in place of rendering `<Notice tone="success">`. Each
     keeps its words exactly.
   - The page then no longer moves when a confirmation appears, which is the reason for a toast.
   - Errors (`ErrorBanner`), warnings and information notices stay inline. They describe the page and must stay
     until the person deals with them.
   - **Three stay inline, and an allow-list in the guard (Tests 2) names them:**
     - `admin/UserDetail.tsx`: the Reset Password dialog stays open to show its confirmation, and a toast behind a
       focus-trapped dialog cannot be reached by keyboard;
     - the two in `auth/SignInForms.tsx`: the sign-in pages have no shell and no toast host.
   - If the developer finds another call site that renders outside the shell or inside a dialog that stays open, it
     stays inline, joins the allow-list, and is written as a deviation.

   Alternatives:
   - a toast as well as the inline notice (the same sentence twice);
   - only Case Claim (two ways to confirm an action in one portal).

3. **The flash becomes a toast on the next page.**
   - The host reads `peekFlash()` when it mounts and on every pathname change (`usePathname`). It shows the text as
     a toast and then calls `clearFlash()`.
   - This covers both a client navigation and a full reload (`CloseCaseDialog`).
   - `FlashNotice` is removed from `workflow/common.tsx`, `Dashboard.tsx` and `InboxFrame.tsx`.
   - `setFlash` callers do not change. A caller that navigates away after an action keeps using `setFlash`; a caller
     that stays on the page calls `toast()`.

   *Amends portal-workflow decision 6 (where the flash is shown, not what it says).*

4. **Behaviour: one toast at a time, readable, never in the way.**
   - **A text-only toast closes after 6 seconds** (`TOAST_MS = 6000` in `feedback.tsx`). The sample's 3.2 s is too
     short to read a sentence that names a case number.
   - **The timer pauses** while the pointer is over the toast or focus is inside it, and starts again at 6 seconds
     when the pointer leaves or focus moves out (WCAG 2.2.1, timing adjustable).
   - **A toast with a link does not close by itself.** It closes only on Close, Escape, a new toast or navigation. A
     link that disappears on a timer cannot be reached by keyboard. Today only Case Claim's "Open Case Page" uses
     this.
   - **Close:** an icon button named **"Close Message"** (`T.kit.closeMessage`, Title Case). Escape closes the toast
     while focus is inside it. Escape is not taken from the rest of the page, because dialogs use it.
   - **A new toast replaces the current one.** The text changes in place, without a second entrance, and the timer
     starts again. There is no stack.
   - **A toast closes when the pathname changes**, except the flash toast that the change itself brought. Changes
     of the query string (filters, tabs carried in the URL) do not close it.
   - **The toast never takes focus**, because a polite confirmation must not interrupt typing.

   Alternative: the sample's 3.2 s with no pause (fails WCAG 2.2.1 for slow readers and screen-magnifier users).

5. **Accessible structure.**
   - The host holds a visually hidden `role="status"` `aria-live="polite"` `aria-atomic="true"` element. It is always
     in the document, so screen readers register it before any text arrives. The message text, and the link label
     when there is one, are written into it.
   - The visible card is a `role="group"` whose `aria-label` is the message text. Its visible text span is
     `aria-hidden`, so a screen reader moving through the page does not read the message twice. Its link and Close
     button are ordinary controls. When the card is empty it is `visibility: hidden`, so nothing in it can be
     focused.
   - Alternative: the visible card as the live region. Its visibility changes at the moment the text arrives, and
     some screen readers then miss the announcement.

6. **The look, from the sample, on the palette's tokens** (row 229's navy set; no new colour token):
   - Ground `--panel-from` (navy 900). Text `--panel-strong` (16.49:1).
   - A check icon in `--panel-accent` (light orange, the sample's stroke, 10.37:1), 18 px, `aria-hidden`. It is a new
     `CheckIcon` in the kit if none exists.
   - The link in `--panel-strong`, underlined.
   - Close in `--panel-text`, with ground `--panel-hover` on hover (9.28:1).
   - The focus ring on the card is bright `--mark` (6.72:1 on navy), as in the side menu. Deep orange on navy is only
     3.02:1.
   - `--shadow-3`, radius `--r-lg`, padding `var(--s3) var(--s4)`, gap `var(--s3)`, font `--t-sm` weight 500.

   The orange-10% rule holds: the only orange is the small light-orange check, a marker on navy (portal-navy-cream
   decision 5).

7. **Where it sits.** The host is `position: fixed` with `z-index: 70`, above dialogs (60) and the drawer (61, 62).
   The host has `pointer-events: none` and the card has `pointer-events: auto`, so the empty corner never blocks a
   click.
   - **From 820 px:** `right: var(--s5)`, `bottom: var(--s5)`, `max-width: 420px`.
   - **Under 820 px (phones):** `left` and `right` `var(--s3)`, and `bottom: calc(var(--s7) + var(--s4) + var(--s3))`
     (76 px), just above the 64 px bottom bar. This is the same calc idiom the content's bottom padding already uses.
   - **Above a Save bar:** while the page holds a Save bar, the toast rises by `var(--savebar-h) + var(--s3)`. The
     Save bar gains `data-ui="save-bar"`, and the rule is
     `:global(body:has([data-ui="save-bar"])) .toastHost`, with the phone offset added under 820 px. The Save Changes
     button stays visible beside the "Saved" toast.

8. **Motion, on the tokens.**
   - **Entrance:** from `opacity: 0; transform: translateY(var(--s5))` (24 px, the sample's distance) to rest,
     `opacity` and `transform` over `--slow` with `--ease`.
   - **Exit:** to `opacity: 0; transform: translateY(var(--s3))` over `--med`. `usePresence(open, DURATION.med)` keeps
     the text until the exit ends. `visibility` switches with a delay of `var(--med)`, the pattern of the side menu's
     children.
   - **Under reduced motion:** the durations are 0 ms and the global block turns transitions off, so the toast appears
     and disappears in place with no movement or fade. `usePresence` clears it at once. Reduced motion changes motion
     only, not reading time: the 6 seconds and the pause stay.
   - No bounce, no overshoot.

### B. The sliding segmented switch

9. **The chosen option's ground slides, in the kit, for every switch.**
   - `SegmentedSwitch` renders one extra `span` as its last child:
     - `className={s.thumb}`, `aria-hidden="true"`, `data-motion-layer=""`;
     - `position: absolute`, `top: 2px`, `bottom: 2px` (the track's padding), `left` and `width` from the chosen
       option;
     - radius `--r-sm`, ground `--surface`, `--shadow-1`. These are the colours `.segmentOn` paints today; the
       colours stay as row 229 approved them.
   - It moves with `left` and `width` transitions over `--slow` (320 ms, the sample's `.32s`) with `--ease`. The
     text colour keeps its `--fast` change.
   - `.segmented` gains `position: relative`. `.segment` gains `position: relative; z-index: 1`, so the words sit
     above the thumb.
   - Once the thumb is placed, the group carries `data-thumb`. The colour-only rule
     `.segmented[data-thumb] .segmentOn { background-color: transparent; box-shadow: none; }` then hands the ground
     to the thumb.
   - Before the first measurement, on the server render and wherever measuring fails, there is no thumb and
     `.segmentOn` paints as today. Nothing flashes and nothing breaks without JavaScript.
   - With no option matching `value`, there is no thumb.
   - Roles, `aria-checked`, the roving `tabIndex`, arrow keys and disabled options do not change.

   Alternatives:
   - only the dashboard switch (one control with two behaviours);
   - the sample's fixed half-width pill (wrong for options as wide as their words, and for three options);
   - the sample's solid navy pill with white text (a colour change; row 229 kept the shaded switch).

10. **One measuring hook for the two sliding marks.** The ink's measuring code moves from `Tabs` into
    `components/ui/motion.ts` as `useSlidingMark(containerRef, selector, deps)`. It returns `{ left, width } | null`:
    a layout effect, a `ResizeObserver` on the container and on each item, and once more on `document.fonts.ready`.
    `Tabs` (selector `[data-tab-current='true']`) and `SegmentedSwitch` (selector `[aria-checked='true']`) both use
    it. The first placement mounts the element in place, so nothing slides in from 0 on page load. The `Tabs` tests
    prove the ink unchanged. Alternative: a copy of the code in `controls.tsx` (two measuring paths to keep in step).

11. **The dashboard's switch slides between views.** My Work, Department and State change only the URL's `view`
    (`setFilters`), and the switch stays mounted, so the thumb slides. A test pins that the same thumb element is
    still there after a switch (Tests 3).

### C. The side-menu hover slide

12. **On hover, the icon and the label slide 4 px; the row does not move.** In `shell.module.css`:
    ```css
    .navIcon, .navLabel { transition: transform var(--med) var(--ease); }
    @media (hover: hover) and (pointer: fine) {
      .nav a:hover:not([aria-current="page"]) .navIcon,
      .nav a:hover:not([aria-current="page"]) .navLabel { transform: translateX(var(--s1)); }
    }
    ```
    - The sample changes `padding-left` (30 → 36 px), which resizes the row's content box and reflows it. Row 229
      rejected that for this reason. A `transform` moves only the painted icon and words: the row's box, its padding,
      the count and the chevron stay where they are. *Amends portal-navy-cream decision 12 (the "rejected" line).*
    - **4 px** (`--s1`, the smallest step of the spacing scale) in place of the sample's 6 px, because the portal's
      rows are 36 px with 12 px padding, against the sample's 40 px with 30 px. The `--med` duration (220 ms) is the
      sample's `.22s`.
    - **Room:** a truncated label keeps 8 px of its 12 px gap before the count, and stays inside the row's right
      padding when there is no count or chevron, so nothing is clipped or overlapped.
    - **The current item does not slide.** It is already marked by its ground and the orange bar. Parents and child
      rows slide like any other row.
    - **Pointer devices only.** Touch screens do not hover, and the media query keeps a tap from leaving a row
      shifted.
    - **Keyboard focus does not slide the row.** Arrow keys walk the tree one row at a time, and a slide on every
      step would be busy. Focus already has the ring.
    - **Under reduced motion:** the global block turns the transition off and the 4 px offset shows at once on hover.
      That is a still position change, not motion. Alternative: no offset at all under reduced motion (one more
      media rule; the offset alone does not animate).

### D. Proof

13. **The layout signature changes once, on purpose.** These rules change layout properties on purpose:
    - `.segmented` and `.segment` (`position`, `z-index`);
    - the new `.thumb`;
    - `.navIcon` and `.navLabel` (`transition`), and the hover rule (`transform`);
    - the toast rules;
    - `.saveBar` is unchanged (only the attribute is added in TSX);
    - `claim.module.css` `.notice`, removed when the claim notice goes.

    The developer regenerates `layout-signature.json` with `UPDATE_LAYOUT_SIGNATURE=1` in **one commit**. The
    reviewer checks that `git diff main -- frontend/src/components/ui/layout-signature.json` names only the selectors
    above. Colour-only additions (`.segmented[data-thumb] .segmentOn`) leave no trace, as in row 229.

14. **The box comparison proves that nothing else moved.**
    - `e2e/boxes.ts` `collectBoxes` skips any element carrying `data-motion-layer`, with its subtree, **only when its
      computed `position` is `absolute` or `fixed`**. It skips before counting `nth-of-type`, so no sibling's path
      changes. A marked element in the flow is recorded as usual, so a misuse shows up as "extra".
    - The thumb and the toast host carry the marker.
    - With the same uicheck image (built from the branch) for both runs, `main` against the branch must give
      **0 moved, 0 missing, 0 extra elements, 0 page-size changes**.
    - The only differences allowed are the **6 extra pages** of the two new interaction states (decision 15) at three
      widths.
    - uicheck runs under reduced motion with no hover, so the menu slide and the thumb's movement do not show in
      boxes. The owner's browser check covers them (Verification 4).

15. **Two new uicheck interaction states** show the toast at 375, 768 and 1280 px.
    - **How the toast is raised:** the fixtures answer no writing request, so each state writes a flash into
      sessionStorage with `page.addInitScript` and lets the host show it. It then hovers the toast, which pauses the
      timer, before the screenshot.
    - **`/ (confirmation toast)`:** the dashboard with the toast at the bottom right, or above the bottom bar on
      phones.
    - **`/admin/access/${SAMPLE.userType} (toast above the Save bar)`:** the two-switches-changed steps of the existing
      Save bar state, plus the flash. The toast sits above the Save bar.
    - Both must have **0 findings**. That proves that the toast does not overflow the page at 375 px, that it covers
      no menu item, and that one primary per page still holds (the toast holds no button variant).

## Data

None. No table, column, reference code or migration.

## Services

None. No backend change.

## API

None. No endpoint is added or changed, so no `Permission` applies.

## Jobs

None.

## Tests

Vitest, `frontend/src`:

1. **The toast** (`components/ui/toast.test.tsx`, rendered with the provider):
   - **the live region:** a visually hidden `role="status"` with `aria-live="polite"` exists before any toast;
     `toast("Saved.")` writes the text into it; the card is a `group` named by the text and its text span is
     `aria-hidden`;
   - **the timer:** with fake timers, a text-only toast is gone after 6000 ms and is still shown at 5999 ms;
   - **the pause:** pointer over the card or focus inside it stops the timer, and leaving starts 6000 ms again;
   - **the link:** a toast with `{ href, label }` shows the link and is still shown after 60 s;
   - **closing:** "Close Message" closes it, and Escape with focus inside closes it;
   - **replacement:** a second `toast()` replaces the text in the same card and restarts the timer; there is never
     more than one card;
   - **navigation:** a pathname change closes the toast, and a query-string change does not;
   - **the flash:** a flash in sessionStorage is shown on mount and on a pathname change, and is then cleared;
   - **focus:** the toast never takes focus (`document.activeElement` unchanged);
   - **reduced motion:** after Close the card is empty at once, with no `data-closing`;
   - **with motion:** the card keeps its text with `data-closing` for `DURATION.med`, then empties;
   - **outside a provider:** `useToast()` throws an error naming `ToastProvider`.
2. **The confirmation guard** (source scan with `src/test/sourceScan.ts`):
   - no `tone="success"` on a `Notice` in any `.tsx` source except the allow-list (`admin/UserDetail.tsx`,
     `auth/SignInForms.tsx`), each entry listed with its reason;
   - `FlashNotice` is defined and imported nowhere.
3. **The switch** (`components/ui/ui.test.tsx`, offsets mocked as in the ink tests):
   - the thumb is `aria-hidden` with `data-motion-layer`, at the checked option's `offsetLeft` and `offsetWidth`;
   - it moves to the new option when `value` changes and when an arrow key moves the choice;
   - it follows a resize through the `ResizeObserver` mock;
   - there is no thumb before measurement or when `value` matches no option, and the group has `data-thumb` only
     while a thumb is shown;
   - radio roles, `aria-checked`, the roving `tabIndex` and disabled options are unchanged (the existing tests stay
     green);
   - **the dashboard** (`dashboard` test): switching My Work → Department keeps the same thumb element, with a new
     `left`.
4. **The sliding-mark hook** (`motion.test.tsx`): `useSlidingMark` returns the selected item's box and follows a
   resize. The existing `Tabs` ink tests (`ui.test.tsx`, left 90 → width 150 etc.) pass unchanged on the shared hook.
5. **The motion rules** (`components/ui/motionRules.test.ts`, parsing the CSS sources):
   - the transitions of `.thumb`, the toast card and `.navIcon`/`.navLabel` name only `var(--fast)`, `var(--med)` or
     `var(--slow)` with `var(--ease)`;
   - the menu hover rule sits inside `@media (hover: hover) and (pointer: fine)`, excludes `[aria-current="page"]`
     and sets only `transform`, never `padding`, `margin`, `width` or `left`;
   - `.thumb` is `position: absolute` and `.toastHost` is `position: fixed`;
   - the reduced-motion block is unchanged (also pinned by `tokens.test.ts`).
6. **Colour guards:** the token test's colour-literal and orange guards cover the new rules as written, with no new
   pairs; the toast's pairs are already pinned (`--panel-strong`/`--panel-from` 16.49, `--panel-text`/`--panel-hover`
   9.28, `--panel-accent`/`--panel-from` 10.37, `--mark`/`--panel-from` 6.72).
7. **The shell** (`shell.test.tsx`): the toast host is the last element of `.frame`, and the Save bar carries
   `data-ui="save-bar"`.
8. **Screen tests:** every test that found an inline success notice now finds the same words in the toast's status
   region. `renderWithClient` (`src/test/render.tsx`) wraps in `ToastProvider`. Case Claim's test finds the "Open
   Case Page" link in the toast.
9. **The layout signature** (`layoutSignature.test.ts`): green against the snapshot of decision 13's single commit.

uicheck, `frontend/e2e`:

10. `uicheck-self.spec.ts`: on a synthetic page, `collectBoxes` skips a fixed element marked `data-motion-layer` and its
    subtree, leaves its siblings' paths unchanged, and records a marked element in the flow.
11. `uicheck.spec.ts`: the two states of decision 15, with no findings at 375, 768 and 1280 px.

## Verification

The integrator, from a clean worktree of the branch:

1. `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`: all green.
   `git log -p -- frontend/src/components/ui/layout-signature.json` shows one commit on the branch, and its diff names
   only the selectors of decision 13.
2. The backend is untouched: `git diff --stat main -- backend` is empty. Run `ruff check` and `pytest -q` as usual.
3. The box comparison on a private network (runbook section 16; never through Compose on the shared stack):
   1. Build `tmpA-web` from `main`, `tmpB-web` from the branch, and `tmp-uicheck` from the branch's `e2e/`.
   2. Run uicheck with `UICHECK_BOXES=1` twice against `tmpA-web` (`/out/a1`, `/out/a2`).
      `npm run boxdiff -- /out/a1 /out/a2` must give **0 differences**.
   3. Run it once against `tmpB-web` (`/out/b`). `npm run boxdiff -- /out/a1 /out/b` must give **0 moved, 0 missing,
      0 extra elements, 0 page-size changes**. The only extra pages are the two new states at three widths
      (**6**).
   4. The `/out/b` run has **0 findings**.
   5. Remove the containers, the network and the images.
4. **The owner's motion check** follows the deploy, in a browser at `http://localhost:3000`, because screenshots
   cannot show motion:
   - **At 1280 px:**
     - hover the side-menu items: icon and words slide 4 px, and the count and chevron stay put;
     - switch My Work / Department (and State) on the dashboard, and the Show switch on the Case Inbox: the ground
       slides;
     - claim a case on Case Claim: a navy toast rises at the bottom right with Open Case Page, and stays until
       closed;
     - save a user type: "Saved" rises above the Save bar and closes after about 6 seconds, or stays while the pointer
       is over it.
   - **At 375 px:** a toast sits above the bottom bar.
   - **With Windows "Animation effects" off** (reduced motion): nothing slides, and the toast appears and disappears
     in place.
5. Deploy: frontend only. Build `web` from a clean worktree of `main` and recreate it with `--no-deps
   --force-recreate`. Check the web build ID. No migration and no `init`.

## Open questions

None. Each decision lists the alternatives; the owner may pick one of them at approval:
- the 6-second time (decision 4);
- toasts for every confirmation or only for Case Claim (decision 2);
- the solid navy pill (decision 9);
- the slide distance (decision 12).
