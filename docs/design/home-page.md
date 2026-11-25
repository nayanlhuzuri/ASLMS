# Design: One public home page with the sign-in form on it

```
slug: home-page
status: approved
author: architect
date: 2026-11-24
approved_by: owner on 2026-11-24
```

## Context

Backlog row 274. **Owner, 23 Nov 2026** (decisions log, "Home page direction"): after seeing two concept screens made
with the design-taste-frontend skill, the owner chose a home page only. It is one public page in place of today's bare
sign-in entry, with the sign-in form on the same page, built in the portal's own code and look. The owner asked for this
design on 24 Nov 2026. It is built after row 251 (done).

**What the owner asked for (the row, point by point).**
1. A short plain-words explanation of what ASLMS does.
2. A preview of the app: a static picture of a Case Inbox and a cited Case Assistant answer, with sample content and
   never live data.
3. A short what-it-does strip.
4. The existing sign-in form, with the e-mailed code, on the same page, so signing in takes no extra click.
5. Public page rules: ASLMS described in general terms only. No case numbers, no live counts, no department names. A
   figure such as cases tracked appears only if the owner decides so in this design (open question 1).
6. Transitions, each about 200 to 300 ms, under the portal's motion rules (rows 101 and 235) and none under reduced
   motion:
   - a Sign In button on the page moves smoothly to the form and focuses its first field, with no page change;
   - after the password, the form panel slides or cross-fades in place to the code step;
   - after the code, a short fade into the Dashboard.
7. No code from the taste skill in the portal: `.claude/skills/design-taste-frontend` stays a design aid.
8. Frontend only, no migration. uicheck at 375, 768, 1024 and 1280 px.

**The concept screen (layout only).** The private concept page of 23 Nov 2026, screen 1, was read for its layout and
nothing else. No code, class name, colour value or font is taken from it. What is borrowed:
- a top bar with the name on the left and a Sign In button on the right;
- a hero with a headline and a short lead;
- one framed "window" of the app under the hero, with a list on the left and an Assistant answer with its source on
  the right;
- a band explaining what the system does;
- a closing band with Sign In, and a footer.

What is **not** borrowed, because the row or an earlier owner decision forbids it:
- the live figure "84,898 cases read from the court since January 2025" (no live counts);
- case numbers in court format, party names, "Education (Elementary)" and other department names;
- the mega-menu of portal pages (every one of them is behind sign-in);
- the "See the Case Inbox" button (the preview is on the page itself);
- the dark colour scheme for the artifact viewer (the portal has no dark mode);
- the Instrument Sans and DM Mono fonts;
- the naming of the Gauhati High Court (decision 4).

**What is in place.**
- **Routes.** `src/app/(public)/login/page.tsx` (`LoginForm`) and `login/code/page.tsx` (`CodeForm`), with
  `/forgot` and `/forgot/code`, all inside `(public)/layout.tsx`, which renders `AuthFrame`. The first-sign-in pages
  `(welcome)/welcome/password` and `welcome/profile` use `AuthFrame` with `wide`.
- **The page gate.** `src/proxy.ts` lets `PUBLIC_PAGES` (`/login`, `/login/code`, `/forgot`, `/forgot/code`) through
  without the refresh cookie. Any other page without it goes to `/login?next=…`, and `/` with no query goes to `/login`.
  The CSP has `font-src 'self'`, `img-src 'self' data:` and a per-request script nonce.
- **The sign-in flow** (design portal-shell, decision 8, unchanged by this note):
  - `LoginForm` posts e-mail and password through the backend-for-frontend (`/api/session/login`, with its origin
    check), keeps the masked address and timings in `sessionStorage` (`steps.ts`, key `aslms.step`) and then
    `router.push`es to `/login/code`.
  - `CodeForm` posts the 6-digit code (`/api/session/verify`). On success it clears the step and the stored session
    limits and calls `router.replace(afterSignIn(next_step, next))`: `/welcome/password`, `/welcome/profile`, or the
    page asked for (`/` is the Dashboard). On `otp_expired` it goes to `/login?expired=1`. Resend counts down
    `resend_after`.
  - `safeNext` keeps `next` relative.
  - The session timeout (row 169) and the API client send a signed-out person to `/login?reason=…&next=…`. `LoginForm`
    shows the reason from the shared clock. `/login?reset=done` shows the password-changed notice.
- **The frame.** `AuthFrame` is the navy panel with `GoldEmblem` (row 249: the gold Lion Capital turning, "অসম চৰকাৰ"
  above it, "सत्यमेव जयते" below it, Pause / Play remembered in `localStorage`, still under reduced motion), the
  kicker `T.owner`, the title `T.portalLong`, the lead, three tiles and the maker line, beside the cream form side.
  The two Noto fonts are imported in `AuthFrame.tsx`, so only the public and first-sign-in routes load them. The
  Gauhati High Court is not named on these pages (portal-ui-redesign decision 26, owner's amendment of 20 Oct 2026).
- **Tokens and motion.** Navy and cream (row 229) and the `--gold*` tokens are in `globals.css`. `--fast` 150, `--med`
  220 and `--slow` 320 ms become 0 ms under `prefers-reduced-motion: reduce`, where every animation and transition is
  off. `components/ui/motion.ts` has `DURATION`, `usePrefersReducedMotion` and `usePresence`. `tokens.test.ts` allows
  no colour literal and no off-scale spacing in a CSS module. `layoutSignature.test.ts` records every box-sizing rule.
- **Wording guards.** Title Case for headings, buttons and labels (`titleCase.ts`, `labels.test.ts`). The "file" and
  "allot" guards (`wording.test.ts`). No agency name (`branding.test.ts`). Every text in `messages.ts` (i18n
  catalogue test).
- **uicheck** (`frontend/e2e/`) reads every `page.tsx`, runs at 375, 768, 1024 and 1280 px under reduced motion, and
  has the state "/login (motion on)". Among the kinds: `gutter` (everything inside `main#main`'s content box unless
  marked `data-bleed`), `primary` (one primary action outside a dialog), `clipped` (text cut by overflow), `overlap`,
  `text-overrun`, `doubled-heading`. `backend/tools/portal_smoke.py` wants HTTP 200, not a redirect, from every
  `page.tsx`.

**The plan.** The plan asks only for individual logins with OTP verification. It says nothing about a home page.
Nothing here departs from the plan or from any business rule.

**Not covered.**
- The reset pages (`/forgot`, `/forgot/code`) and the first-sign-in pages stay on `AuthFrame` as they are.
- The portal's own pages, header and menu. The only change inside the portal is the one-time fade on arrival
  (decision 13).
- Any public API, count or data. The home page makes no request before the person signs in.
- A second language (the i18n seams stay as they are).

## Decisions

### A. Where the page lives

1. **The home page is `/login`.** `/` without a session keeps going to `/login`, as now.
   - The page moves from `(public)` to a new route group `(home)`: `src/app/(home)/login/page.tsx` renders
     `HomePage`. The group has no layout of its own, so the root layout and nothing else applies, and the page does
     not use `AuthFrame`.
   - Every existing address keeps working with no change to the page gate, the backend-for-frontend, the API client
     or the session watch: `/login?next=…`, `?reason=…`, `?expired=1`, `?reset=done`.
   - `metadata.title` is `{ absolute: "ASLMS — Assam State Litigation Management System" }` (from `T.portal` and
     `T.portalLong`), in place of "Sign In · ASLMS". `robots: noindex, nofollow` stays from the root layout.

   Alternatives:
   - serving the page at `/` through a proxy rewrite when there is no refresh cookie (rejected). It gains only the
     address. With a stale cookie, `/` shows the portal, the API answers `signed_out` and the person is sent to
     `/login`, so the home page would still need `/login`. The client router would also hold `/` as the home page's
     payload when the code step sends the person to `/`.
   - keeping `/login` as the bare form and adding a separate home page (rejected: the row asks for the form on the
     page, so signing in takes no extra click).

2. **The code step happens in place, and `/login/code` stays only as an old address.**
   - The step is read from the address: `/login?step=code` (with `next` kept) is the code step, anything else is the
     password step.
   - The page changes step with `window.history.pushState`. Next.js 16 keeps `useSearchParams` in step with it, so the
     page does not remount, makes no server request and can animate (decision 11).
   - Browser Back from the code step returns to the password step, as Back from `/login/code` does today. A reload
     keeps the step, as a reload of `/login/code` does today. The masked address comes from `aslms.step` as before,
     and without it the general sentence is shown.
   - `(home)/login/code/page.tsx` stays so old links and bookmarks work. It is a client redirect, the existing
     pattern of `components/inbox/Redirects.tsx`, which replaces the address with `/login?step=code` and keeps
     `next`. The route therefore still answers 200 for `portal_smoke.py`, and uicheck measures the page it lands on.
   - `/login/code` stays in `PUBLIC_PAGES` and in uicheck's `PUBLIC` set.

   Alternatives:
   - a router search-param navigation (`router.push("?step=code")`) (rejected: the App Router keys the page segment
     by its search parameters, so the page would remount and could not cross-fade);
   - the step in component state only (rejected: Back would leave the site, and a reload would lose the step).

3. **Signed-in visitors still see the home page at `/login`**, as they see the sign-in form today. A refresh cookie may
   be stale, and only the API can tell. The Dashboard stays at `/`.

### B. What the page says (texts for the owner to approve)

4. **General wording only.**
   - No case number, CNR, party, department name, judge, count or date from the database appears anywhere on the
     page, the preview included.
   - The Gauhati High Court is not named: the owner's rule of 20 Oct 2026 for the public pages holds here too. The
     page says "the court". The owner may lift this at approval; the change would be one sentence in `messages.ts`.
   - No figure is shown (open question 1).
   - No help contact is shown (open question 2).
   - Every text is in `messages.ts` under a new `T.home` block. Headings, buttons and labels are in Title Case, and
     body sentences in sentence case. Nothing uses "file" in the custody sense or "allot".

   The proposed texts:

   | Place | Text |
   |---|---|
   | Top bar, name | "ASLMS" with "Government of Assam" beneath it (`T.portal`, `T.owner`) |
   | Top bar and closing band, button | "Sign In" (`T.auth.signIn`) |
   | Hero, beside the emblem | kicker "Government of Assam", title "Assam State Litigation Management System" (as on the frame) |
   | Hero, `h1` | "The State's Court Cases, Followed Day by Day" |
   | Hero, lead | "ASLMS reads the court's daily cause lists and orders, recommends the department each case concerns, and tells the officer who has the case what is coming up and what needs doing next." |
   | Hero, access line | "For officers of Government of Assam departments. Your department's administrator gives you a login, and a code comes to your e-mail each time you sign in." |
   | Card | the existing sign-in texts: "Sign In", "Use your official e-mail and password.", the two-step line, "E-mail", "Password", "Forgot password?", then "Enter the Code", "A 6-digit code was sent to …", "Verify", "Send a New Code", "Start Again" |
   | Preview, `h2` | "What You See After Signing In" |
   | Preview, line | "Your cases with their next hearing, and answers from the court's orders that show the page they come from." |
   | Preview, label on the window | "Sample Screen, Not Real Cases" |
   | Strip, `h2` | "What ASLMS Does" |
   | Strip, item 1 | "Never Miss a Hearing": "Your dates and the day's cause list, with alerts." |
   | Strip, item 2 | "Orders As They Are Passed": "Read, print or download every order of your cases." |
   | Strip, item 3 | "Each Case Finds Its Department": "ASLMS recommends the department a case concerns, and the department claims it. Nothing is assigned automatically." |
   | Strip, item 4 | "Know Who Has the Case": "Send, track and recall a case with a clear trail." |
   | Closing band | "Sign In to ASLMS" (`h2`) and "Use your official e-mail and password. A code comes to your e-mail each time." |
   | Footer | "Assam State Litigation Management System · Government of Assam" and "For official use by Government of Assam departments." (`T.auth.frame.foot`) |

   Items 1, 2 and 4 repeat the frame's three tiles word for word: the strip reuses `T.auth.frame.tiles` for them, so
   the two never drift apart. Item 3 states the recommend-and-claim rule in plain words.

5. **The preview is a static picture drawn in HTML and CSS, with plainly sample content.**
   - `HomePreview` is a server component with no data and no request. One framed window has a title bar and two panes:
     - **left, the Case Inbox:** a "With Me" heading and three rows, each with a name, a party line, a hearing badge
       and a status word;
     - **right, the Case Assistant:** one question, one answer with a source marker, and one source chip.
   - **The sample content:**
     - Case Inbox rows: "Sample Case 1", "Tomorrow", "New Order"; "Sample Case 2", "In 3 Days", "Reply Due"; "Sample
       Case 3", "Next Week", "Listed". The party line on every row is "A Petitioner v. The State".
     - Question: "What did the court direct in the last order?"
     - Answer: "The State is to file its reply within two weeks, and the case comes up again after that. [1]"
     - Source chip: "[1] Sample Order, Page 2"
     - The label "Sample Screen, Not Real Cases" sits on the window's title bar and is visible at every width.
   - The words "Sample Case n" take the place of a case number, so no identifier is made up (the rule "never fabricate
     identifiers"). Relative words take the place of dates, so the picture never goes out of date. "The State" is the
     only party named.
   - **Built from the portal's own pieces:** the tokens, Inter, and the kit's `Badge` (tones `danger` for "Tomorrow" and
     `warning` for "In 3 Days", matching the meaning of row 190's hearing colours), plus the `AssistantIcon`.
   - **No live control inside it:** no `DataTable`, no `Button`, no link and no field. The window is `inert`. It is one
     `role="img"` element with the label "A sample of the Case Inbox and a Case Assistant answer with its source. The
     cases shown are not real." Its children are `aria-hidden`.
   - **No ellipsis:** text wraps rather than truncating, so the `clipped` and `text-overrun` checks have nothing to
     find.

   Alternatives:
   - a screenshot image (rejected): it would carry whatever data the screen held, including the fixtures' department
     names, it blurs at some widths, and it has to be redrawn whenever the portal's look changes;
   - live kit components with fake data (rejected): they would be focusable, and uicheck would treat the picture as a
     real list.

6. **No figure and no live count by default** (open question 1). A live count would need an unauthenticated API
   endpoint, which the row rules out. If the owner wants a figure, it is a fixed, rounded sentence the owner supplies,
   kept in `messages.ts` and changed by hand, shown as a small line above the `h1`. No API change is needed either
   way.

### C. Layout

7. **The page, top to bottom.** `HomePage` is a server component. Only `SignInCard` and `GoldEmblem` are client
   components.
   - **Top bar** (`header`, outside `main`, navy `--panel-from`, 64 px high, not sticky):
     - left, the name block, which is text and not a link (there is nowhere public to link to);
     - right, a "Sign In" link drawn as a secondary button (`buttonClass("secondary")`, 36 px, `href="#sign-in"`).
     - The official 40 px emblem mark is not repeated here, so the emblem appears once on the page (signin-gold-emblem
       decision 10).
   - **Hero** (navy band, the frame panel's gradient `--panel-from` to `--panel-to` with its dot pattern):
     - from 1024 px, two columns: on the left the panel top as on the frame (`GoldEmblem` beside the kicker and title
       behind the thin gold divider), then the `h1`, the lead and the access line; on the right the sign-in card;
     - the card is cream (`--surface`), radius `--r-xl`, `--shadow-3`, padding `--s6`, 360 to 440 px wide, and its
       top lines up with the emblem block;
     - on a laptop the whole form is in the first view, with no scrolling.
   - **Preview** (cream `--bg` band): the `h2`, the line, and the window (decision 5), at most 1120 px wide and
     centred. The two panes sit side by side from 768 px, about 2 : 3.
   - **Strip** (cream band): the `h2` and four items, each an icon from `components/shell/icons.tsx` (`CalendarIcon`,
     `FilesIcon`, `ClaimIcon`, `InboxIcon`), a bold title and one line. Four columns from 1024 px, two from 768 px,
     one below 768 px.
   - **Closing band** (navy): the `h2` "Sign In to ASLMS", the line, and a second secondary "Sign In" link to
     `#sign-in`.
   - **Footer** (`footer`, outside `main`, navy): the two footer lines.

   Alternatives:
   - the concept's centred hero with the form only in the closing band (rejected: a returning officer would scroll
     on every visit, against "no extra click");
   - the form in a dialog opened by Sign In (rejected: an extra click, and a page change in all but name).

8. **Phones and tablets (below 1024 px): the form comes right after the headline.**
   - The order is the panel top, the `h1`, the card, then the lead and the access line, then the preview, the strip,
     the closing band and the footer.
   - At 375 × 667 the card's top is about 330 px down. Its first field and any notice above the form (a sign-out
     reason, an expired code, a changed password) are in the first view, so a returning officer does not scroll and
     a signed-out officer sees why.
   - Below 820 px `GoldEmblem` keeps its existing phone look from `auth.module.css`: a 52 × 78 px stage, the two gold
     lines hidden, Pause / Play as an icon only.
   - The card is full width up to 480 px and centred. The preview's panes stack below 768 px, list first.

9. **The gutter and the bands.**
   - `main#main` keeps a left and right padding of at least `--s4`, so uicheck's `gutter` kind holds.
   - The navy and cream bands reach the screen's edges by a painted background only: a `box-shadow` spread with
     `clip-path: inset(0 -100vmax)` on the band. No box sits outside the content box, and no width makes the page
     scroll sideways.
   - No element needs `data-bleed`. The top bar and footer are outside `main` and span the width directly.

10. **One primary action.** The form's submit ("Sign In" on the password step, "Verify" on the code step) is the only
    primary. The top-bar and closing-band links are secondary, so uicheck's `primary` kind finds one.

### D. The three transitions

All three use `--med` (220 ms) with `--ease`, inside the owner's 200 to 300 ms. Under `prefers-reduced-motion: reduce`
the tokens are 0 ms, the global rule turns animations off, and the JavaScript reads `usePrefersReducedMotion()`, so
each change is instant. No animation library is added.

11. **The Sign In links move to the form and focus its first field.**
    - Each "Sign In" link is a real `<a href="#sign-in">`. Without JavaScript the browser jumps to the card, whose id
      is `sign-in`.
    - With JavaScript, a small client helper (`components/home/jumpToSignIn.ts`, one listener on the page) prevents the
      default, adds no hash to the address, and:
      - when the card is already wholly in view (a laptop at the top of the page), moves focus only;
      - otherwise scrolls the window with `requestAnimationFrame` over `DURATION.med`, easing out, until the card's top
        sits `--s4` below the viewport's top (or as near as the page allows), then focuses the field;
      - under reduced motion calls `scrollIntoView({ block: "start" })` instantly, then focuses.
    - The field is the e-mail field on the password step and the code field on the code step. It is focused with
      `focus({ preventScroll: true })`, so the scroll is never doubled.
    - CSS `scroll-behavior: smooth` is not used, because its length cannot be set.

12. **Password to code, and back, as a cross-fade in place.**
    - `SignInCard` stacks the two steps in one grid cell (`grid-area: 1 / 1`).
    - On a step change, the incoming step fades in from `opacity: 0; transform: translateX(12px)`. The outgoing one,
      kept mounted for 220 ms by `usePresence`, fades out to `translateX(-12px)`. Going back, the directions are
      reversed.
    - The outgoing step is `inert` and `aria-hidden` while it fades, so it can be neither clicked nor read. The card's
      height follows the taller of the two only for those 220 ms.
    - **Focus:** after the change to the code step, the code field is focused. Its `aria-describedby` names the
      sentence "A 6-digit code was sent to …", so a screen reader hears where the code went. After the change back,
      the e-mail field is focused.
    - **What changes the step:**
      - a successful password step: `pushState` to `?step=code`, keeping `next`;
      - Start Again: `pushState` to the password step, keeping `next`;
      - an expired code: `replaceState` to `?expired=1`, keeping `next`, so the existing banner shows;
      - browser Back or Forward.
    - The forms keep their fields, checks, errors, resend countdown and every call exactly as they are now. Only the
      `router.push` and `router.replace` calls to `/login…` become the card's callbacks.

13. **After the code, a short fade into the Dashboard.**
    - On a successful verify, `CodeForm` keeps its busy "Checking…" button. Before calling `router.replace(target)`,
      it writes the flag `aslms.arrive` = `"1"` to `sessionStorage`, unless the target is a `/welcome/…` page, which
      has its own entry on the frame.
    - The home page stays on screen until the portal is ready, so there is never a blank moment.
    - `PortalShell` reads and removes the flag once, on mount. If it was set, the shell's frame takes `data-arrive`,
      which runs one 220 ms opacity fade from 0 to 1 (a new `@keyframes portal-arrive` in `shell.module.css`, opacity
      only, so sticky and fixed parts do not shift). It is removed on `animationend`.
    - A normal portal navigation, a reload, or a new tab without the flag shows no fade.
    - If `sessionStorage` cannot be used, there is no fade and nothing else changes.

    Alternative: fading the home page out before navigating (rejected): if the Dashboard's payload is slow, the person
    stares at an empty page.

### E. Code shape

14. **New and changed portal modules** (`frontend/src`):
    - `app/(home)/login/page.tsx` (new): `HomePage` and the metadata.
    - `app/(home)/login/code/page.tsx` (new): the client redirect of decision 2.
    - `app/(public)/login/` (removed): both pages move to `(home)`.
    - `components/home/HomePage.tsx` (new, server): the top bar, hero, preview, strip, closing band and footer.
    - `components/home/SignInCard.tsx` (new, client): the step from the address, the cross-fade, focus, and the
      callbacks.
    - `components/home/HomePreview.tsx` (new, server): decision 5.
    - `components/home/jumpToSignIn.ts` (new, client): decision 11.
    - `components/home/home.module.css` (new): layout and bands, tokens only.
    - `components/auth/SignInForms.tsx`:
      - `LoginForm` and `CodeForm` take `onSent`, `onStartAgain`, `onExpired` and a `headingLevel` (`h2` on the home
        page) in place of their own navigation;
      - `CodeForm` writes the arrive flag;
      - `ForgotForm` and `ForgotCodeForm` are unchanged.
    - `components/auth/GoldEmblem.tsx`: now imports the two Noto stylesheets itself, as the only thing that uses them.
      `AuthFrame.tsx` drops the two imports, and its header comment says so.
    - `components/shell/PortalShell.tsx` and `shell.module.css`: the arrive fade (decision 13).
    - `lib/messages.ts`: `T.home`.
    - `components/ui/layout-signature.json`: regenerated on purpose
      (`UPDATE_LAYOUT_SIGNATURE=1 npx vitest run src/components/ui/layoutSignature.test.ts`).
    - `e2e/uicheck.spec.ts`: the states of the Tests section.

    No new dependency, no new token unless the developer finds a colour the existing tokens lack (then a `:root` token,
    as in signin-gold-emblem, deviation 1). No change to `proxy.ts`, the backend-for-frontend, `steps.ts`, `safeNext`,
    the session store or the API client. `.claude/skills/design-taste-frontend` is neither imported nor copied.

15. **Documents follow the change.**
    - The scribe adds an "Amended by home-page (row 274)" line under portal-ui-redesign decision 26: the sign-in and
      code steps are on the home page, and the reset and first-sign-in pages stay on the frame.
    - The scribe adds the same line in signin-gold-emblem's Context: the emblem also appears on the home page's hero,
      and the fonts are imported by `GoldEmblem`.
    - The scribe adds an entry in `docs/claude_ASLMS_design_decisions.md`.
    - `docs/ASLMS_Process_Workflows.md` and the software guide describe signing in from the home page.

## Data

None. No table, column, reference code or migration.

## Services

None. No backend module changes.

## API

None. No endpoint is added or changed, so no `Permission` applies. Before sign-in the home page makes no request apart
from the existing `/api/session/login`, `/verify` and `/resend` calls of the sign-in itself, all unchanged. The page stays
outside the page gate as `/login` is today. Visibility rules are not touched, because the page shows no case data.

## Jobs

None.

## Tests

Vitest (`frontend/src`):
- `components/home/home.test.tsx` (new):
  - **the home page holds the sign-in form:**
    - one `h1` with the hero heading;
    - the card's `h2` "Sign In" with the e-mail and password fields and "Forgot password?" linking to `/forgot`;
    - the card has id `sign-in` and sits inside `main#main`;
    - `header` and `footer` are outside `main`.
  - **one primary action:** exactly one `data-variant="primary"` on the page (the submit). The two Sign In links are
    secondary and point to `#sign-in`.
  - **the hero has the emblem and the frame's names:** one `role="img"` named "Emblem of the Government of Assam",
    `T.owner`, `T.portalLong`.
  - **the preview is plainly sample and inert:**
    - one `role="img"` with the sample label;
    - the visible text "Sample Screen, Not Real Cases";
    - the window is `inert` and holds no link, button, field or table.
  - **no identifiers, counts, departments or court name on the page:** the rendered text matches none of these:
    - a case-number pattern (`/\b[A-Z][A-Za-z.()]*\/\d+\/\d{4}\b/`);
    - a CNR pattern (`/\b[A-Z]{4}\d{12}\b/`);
    - a figure of four or more digits;
    - "Gauhati";
    - any name in `e2e/fixtures` department and office lists.
  - **the strip:** four items, and items 1, 2 and 4 equal `T.auth.frame.tiles`.
  - **every text comes from messages.ts:** covered by the existing i18n test (no JSX text literal).
- `components/home/signInCard.test.tsx` (new), with `next/navigation` and `session` mocked:
  - **password step to code step in place:** a successful login calls `history.pushState` with `?step=code` (and
    `next` when given), shows "Enter the Code", focuses the code field, and the code field's description names the
    masked address. `router.push` is never called.
  - **the outgoing step is inert while it fades:** during the 220 ms both steps are mounted, and the old one has
    `inert` and `aria-hidden`. After that only the new one remains.
  - **reduced motion swaps at once:** with `matchMedia` answering reduce, only one step is ever mounted.
  - **Back returns to the password step:** changing the mocked search parameters to no `step` shows the password step
    and focuses the e-mail field.
  - **`?step=code` on load shows the code step,** with the general sentence when `aslms.step` is empty.
  - **an expired code returns to the password step with the banner:** `replaceState` with `expired=1`, and the
    expired banner shown.
  - **Start Again:** `pushState` to the password step, keeping `next`.
  - **after the code:** `router.replace` with `afterSignIn(...)`. `sessionStorage["aslms.arrive"]` is `"1"` for `/`
    and for a `next` page, and is not written for `/welcome/password`.
  - **the reason, expired and reset notices still show** on the password step (the existing `LoginForm` cases, moved).
- `components/home/jump.test.ts` (new):
  - a click on a Sign In link prevents the default, leaves `location.hash` empty and focuses the e-mail field, or the
    code field on the code step;
  - with the card in view, no scroll call is made;
  - under reduced motion, `scrollIntoView` is called once with no `behavior: "smooth"`;
  - with motion, the scroll finishes within `DURATION.med` plus one frame (fake timers and `requestAnimationFrame`).
- `components/home/home.css.test.ts` (new, node, a static read of `home.module.css` and `shell.module.css`):
  - the step and arrive animations use `var(--med)` and `var(--ease)`, with no literal milliseconds;
  - there is no `scroll-behavior: smooth`;
  - `portal-arrive` animates `opacity` only.
- `components/auth/frame.test.tsx`, updated: the frame is now checked on `/forgot`, `/forgot/code` and the first-sign-in
  pages; the sign-in cases move to `home.test.tsx`.
- **the Noto fonts load only on the public pages** (source scan, updated):
  - `GoldEmblem.tsx` imports the two `@fontsource/noto-serif-*` stylesheets, and `AuthFrame.tsx` no longer does;
  - no file under `src/app/(portal)`, nor `src/app/layout.tsx`, nor `globals.css`, imports them or imports
    `GoldEmblem`.
- `components/shell/shell.test.tsx`, added:
  - **the arrive fade runs once:** with the flag set, the frame has `data-arrive` and the flag is removed;
  - a second mount has no `data-arrive`;
  - without the flag there is none.
- `app/pages.test.tsx`: `/login` expects the hero heading and "Sign In". `/login/code` is listed as a redirect to
  `/login?step=code`.
- `proxy.test.ts`: unchanged and still green (`/login` and `/login/code` are public, the CSP is the same).
- `lib/branding.test.ts`, `lib/wording.test.ts`, `lib/labels.test.ts`, `tokens.test.ts` and `motionRules.test.ts`
  stay green with the new texts and CSS.
- `components/ui/layoutSignature.test.ts`: the snapshot is regenerated, and only rules from `home.module.css` and the
  arrive rule are added.

uicheck (`frontend/e2e/uicheck.spec.ts`), at 375, 768, 1024 and 1280 px unless noted:
- `/login` (from the routes) passes under reduced motion with 0 findings.
- `/login/code` lands on `/login?step=code` with 0 findings.
- New state **"/login?step=code"** (public): the card shows "Enter the Code" with the code field visible. At 1024 and
  1280 px the card's box is within the first viewport.
- New state **"/login (first view)"** (public):
  - from 1024 px, the e-mail field, the password field and the submit are within the first viewport;
  - at 375 and 768 px, the e-mail field is within the first viewport.
- New state **"/login (Sign In jump)"** (public, at 375 px with motion on, and at 375 px under reduced motion):
  - scroll to the strip and click the closing band's "Sign In";
  - the e-mail field is focused and wholly in the viewport, and the address has no hash.
- **"/login (motion on)"**, updated for the hero: the emblem is found by its `role="img"` in the hero (no longer in the
  region "About the Portal"). The Pause button's checks, the same-origin fonts and the Noto fonts from 820 px are as
  before.
- **"/ (no sign-in fonts)"** unchanged: a portal page requests no `noto-serif` file.
- The sample window: no `clipped`, `text-overrun` or `overlap` finding at any width, and no `page-overflow` at 375 px.
- `UICHECK_BOXES=1` box comparison: `/login` changes completely, as intended. `/forgot`, `/forgot/code` and the
  first-sign-in pages are unchanged. No portal page's boxes change, because the arrive fade is not in uicheck's states:
  they load without the flag.

## Verification

The integrator:
1. In `frontend/`, runs `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`; all green.
   `npm run gen:api` leaves no diff, and `npm audit --omit=dev` reports 0 vulnerabilities.
2. Runs `docker compose build web` and checks that `backend/tools/portal_smoke.py` answers 200 for every page,
   including `/login` and `/login/code`, with no error in the web log.
3. Runs the Compose-free uicheck on temporary images as in runbook section 16. Expected: every route and state passes
   with 0 findings, including the three new states, and the run's route, state and screenshot counts are recorded in the
   report. The contact sheet shows the top bar, the hero with the emblem and the card, the sample window with its label,
   the strip, the closing band and the footer at each width.
4. After deploy:
   - `curl -sI http://localhost:3000/` answers 307 to `/login`;
   - `curl -sI http://localhost:3000/login` answers 200 with the same `Content-Security-Policy` as before;
   - `curl -s http://localhost:3000/login | grep -c "Gauhati"` prints 0.
5. The owner's browser check (Chrome or Edge, and Firefox) at 375, 768, 1024 and 1280 px, at `http://localhost:3000`:
   - the page reads as one home page with the form in the first view on a laptop, and right under the headline on a
     phone;
   - the window is plainly sample;
   - the top-bar and closing-band Sign In move to the form in a quarter of a second and the cursor is in the e-mail
     field;
   - after the password, the card cross-fades to the code step without the page changing, and Back returns to the
     password step;
   - after the code, the Dashboard fades in briefly;
   - "Start Again", an expired code and the session timeout's sign-out reason all show in the card;
   - "Forgot password?" still goes to the reset page;
   - with Windows "Animation effects" off, every change is instant and the emblem is still;
   - the texts of decision 4 read as the owner wants.

## Open questions

Answered by the owner on 24 Nov 2026 ("approve both designs as recommended"):

1. **A figure on the home page:** (a) no figure. Nothing in `messages.ts` names a count, and no figure is shown.
2. **A help contact:** (a) nothing more. The page says only "Your department's administrator gives you a login".

The developer builds decision 6 and the footer as written. None remain open.

## Deviations

Recorded by the developer while building (24 to 25 Nov 2026):

1. **Closing band heading "Sign in to ASLMS"** in place of "Sign In to ASLMS". The portal's Title Case rule
   (`titleCase.ts`, guarded by `labels.test.ts`) keeps a short joining word lower case in the middle of a heading, as in
   the existing "Sign in Now"; the guard refused the capital "In". The two Sign In buttons keep "Sign In", where "In"
   is the last word.
2. **The bands' painted layer is a `::before` behind the band, exactly as wide as the page**
   (`position: absolute; inset: 0 calc(50% - 50cqw); z-index: -1` inside a band with `isolation: isolate`, the page
   wrapper being an inline-size container), in place of a `box-shadow` spread with `clip-path`. The hero and the closing
   band carry the frame panel's gradient and the hero its dot pattern, which a box-shadow cannot paint. A first try
   clipped wider layers with `overflow-x: clip` on the page wrapper, and uicheck's `clipped` kind refused it (the
   wrapper's scroll width past its client width); a layer of exactly the page's width needs no clipping. As decided, no
   box leaves `main`'s content box and nothing needs `data-bleed`.
3. **The two Sign In links are a small client component, `SignInLink`, exported from `SignInCard.tsx`.** `buttonClass`
   lives in the client kit, and a server component may take only components from a client module (the server-import
   rule of `pages.test.tsx`), so `HomePage` cannot call it. The page's one click listener is installed by the card
   (`listenForSignInLinks` in `jumpToSignIn.ts`), which is on the page exactly once.
4. **The arrival fade is set on the frame element by a ref callback** (`arriveOnAttach` in `PortalShell.tsx`), not
   through React state, so a Strict Mode re-attach or a re-render neither repeats nor clears it. Under reduced motion the
   flag is still read and removed, and nothing is marked, since nothing would fade. The helper is
   `components/shell/arrive.ts` (`markArrive`, `takeArrive`).
5. **`/login/code` uses the existing `Redirect` of `components/inbox/Redirects.tsx`**, which keeps the query string,
   so `?next=…` is kept and `step=code` added.
6. **`home.preview.party` is in `SENTENCE_EXCEPTIONS`** (`labelRules.ts`): "A Petitioner v. The State" keeps the
   court's lower-case "v.", which the Title Case guard would otherwise refuse. The answer's source marker "[1]" is its
   own text (`T.home.preview.marker`) so it can be drawn as a marker.
7. **The card's `h2` is styled in `home.module.css`** (`.card h2`), not by widening `auth.module.css`'s `.form h1`, so
   the frame's stylesheet and its layout signature are unchanged.
8. **uicheck's jump state is two states**, "/login (Sign In jump)" with the motion on and "/login (Sign In jump,
   reduced motion)", both at 375 px only, so each is reported and screenshotted on its own.
