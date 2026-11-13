# Design: The gold Lion Capital on the sign-in frame

```
slug: signin-gold-emblem
status: approved
author: architect
date: 2026-11-12
approved_by: owner, 2026-11-12, as written (the owner's mock aslms-login-emblem-mock-v2.html)
```

## Context

Backlog row 249. **Owner, 12 Nov 2026:** the approach and the mock are approved; this note is the design to approve.
The row is built before row 238 `rolling-case-refresh`.

**What the owner asked for.** The Lion Capital of the Government of Assam emblem, in gold, at the top of the navy panel
of the sign-in frame. It turns slowly, with "অসম চৰকাৰ" above it, "सत्यमेव जयते" below it, and "Government of Assam"
and the portal's full name beside it. The visual reference is `docs/design/ui/aslms-login-emblem-mock-v2.html`, the
owner's approved mock. The earlier mock `aslms-login-emblem-mock.html`, mode "Keeps Turning", shows the turning. The
emblem cut-out is `docs/design/ui/assam-emblem-capital-mask.png`: 508 x 756 px RGBA, transparent, the Lion Capital
only, with no text. The owner settled five points on 12 Nov 2026:
1. a Pause / Play control, because the motion runs longer than 5 s (WCAG success criterion 2.2.2 "Pause, Stop, Hide",
   and GIGW);
2. the emblem may be used as shown;
3. the brand row above the form, shown in the owner's screenshot, is removed;
4. the two fonts are self-hosted;
5. the two texts live in `messages.ts`.

**What is in place.**
- `frontend/src/components/auth/AuthFrame.tsx` (a server component) draws the frame for:
  - the sign-in, code and reset pages, through `src/app/(public)/layout.tsx`;
  - the first-sign-in pages, through `src/app/(welcome)/layout.tsx`, with `wide`.
- The left side is the navy panel. It holds the kicker `T.owner`, the title `T.portalLong`, the lead line, three tiles
  and the maker line. It is a `section` named `T.auth.frame.label`, outside `main`.
- The right side, `main#main`, holds three things:
  - the brand row `data-testid="auth-brand"`: `BrandLockup` with `T.owner` / `T.portal`;
  - the page's form, with its own `h1`;
  - the foot line.
- Styles live in `auth.module.css`. Colours come from the navy-and-cream tokens (design portal-navy-cream, decision 8).
  Motion comes from `--fast`, `--med` and `--slow`. Under reduced motion `globals.css` sets these to 0 ms and turns
  every animation off (portal-ui-redesign decision 13).
- `src/lib/brand.ts` is the one place that configures the official files (portal-ui-redesign decision 21). It has
  `emblem` (`/brand/assam-emblem-mark.png`, header) and `lockup` (`/brand/assam-emblem-lockup.png`). `BrandLockup`
  is used only by `AuthFrame`.
- Fonts: Inter and IBM Plex Mono are self-hosted through `@fontsource` and imported in `src/app/layout.tsx`. The CSP
  in `src/proxy.ts` has `font-src 'self'` and `img-src 'self' data:`. `/brand/*` is outside the page gate.
- uicheck (`frontend/e2e/`) runs at 375, 768, 1024 and 1280 px with `reducedMotion: "reduce"`. The layout signature
  (`src/components/ui/layoutSignature.test.ts`, portal-navy-cream decision 14) records every box-sizing rule.

**The plan.** The plan does not mention the emblem, the sign-in page's look or motion. It asks only for individual
logins with OTP. Nothing here departs from it. This row amends two earlier design decisions, each marked where it
applies:
- portal-ui-redesign decision 26, the template A frame as built in round 5 (row 105): the emblem moves from the
  form side to the panel;
- portal-ui-redesign decision 21: the official cut-out is shown through a gold mask rather than as an unaltered
  image. The owner allowed this as point 2.

**Not covered.** The header's 40 px emblem (`EmblemSlot`), the error and not-found pages, the portal's other pages,
and the texts of the forms. No backend, API or database change.

## Decisions

1. **One client component, `GoldEmblem`, in `frontend/src/components/auth/GoldEmblem.tsx`.**
   - It holds the emblem, the two text lines and the Pause / Play button.
   - `AuthFrame` stays a server component and renders it at the top of the panel.
   - The panel's first block becomes `.panelTop`: on the left, `GoldEmblem`; on the right, `.panelHead` with a thin
     gold divider (`border-left: 1px solid var(--gold-line)`) holding the kicker `T.owner` and the title
     `T.portalLong`.
   - The lead line, the three tiles and the maker line follow as now.

   Alternatives: making all of `AuthFrame` a client component (rejected: only the button needs state); building the
   emblem into `Brand.tsx` (rejected: the header slot is a different thing and is untouched).

2. **The gold comes from a CSS mask over a gold gradient, never from a recoloured image file.**
   - `.gold` is a box filled with `background: var(--gold)`, the gradient token.
   - It is masked by the cut-out: `mask: var(--emblem-mask) center / contain no-repeat`, written with and without the
     `-webkit-` prefix.
   - `--emblem-mask` is set inline by `GoldEmblem` as `url(<BRAND.capital.src>)`. The path is therefore configured
     only in `brand.ts` (decision 3), and the CSS module carries no file path. The CSP allows the inline style
     (`style-src 'unsafe-inline'`) and the mask image (`img-src 'self'`).
   - A soft halo sits behind the stage (`.stage::before`, a radial gradient in `--gold-halo`, not animated). A
     `drop-shadow` glow sits on the faces.

   Alternatives: a gold PNG prepared once (rejected by the owner: "not a recoloured image"; a mask also keeps the
   official outline exact at every size); an SVG trace (forbidden by decision 21: nothing drawn or traced).

3. **The cut-out is served by the portal, configured in `brand.ts`.**
   - The owner's file `docs/design/ui/assam-emblem-capital-mask.png` is copied unaltered, byte for byte, to
     `frontend/public/brand/assam-emblem-capital-mask.png`.
   - `BrandConfig` gains `capital?: EmblemImage | null`, set to
     `{ src: "/brand/assam-emblem-capital-mask.png", width: 508, height: 756 }`.
   - The stage keeps the file's ratio: 118 x 176 px on laptops and 52 x 78 px on phones.
   - The header comment of `brand.ts` records the change: the owner supplied the cut-out with row 249 and allowed it
     to be shown in gold (point 2).
   - When `capital` is null, `GoldEmblem` renders nothing. The panel then starts at `.panelHead`, still with its
     divider.

   This amends decision 21's rule that the build team places nothing under `public/brand/`: here the build team
   copies a file the owner supplied with the row.

4. **It turns as a two-sided coin, so it is never shown mirrored.**
   - `.spinner` has `transform-style: preserve-3d` and the animation `emblem-turn var(--turn) linear infinite`, which
     runs `rotateY(0)` to `rotateY(360deg)`.
   - It holds two `.face` layers with `backface-visibility: hidden`. The back face is pre-rotated by `rotateY(180deg)`,
     so whichever face points at the viewer reads the right way round.
   - The stage has `perspective: 900px`.
   - The sheen (`emblem-sheen`, the gradient's `background-position` and a slight brightness change) runs on the same
     `--turn`. The face therefore darkens as it turns away and brightens face-on.
   - The floor shadow (`emblem-shadow`, `calc(var(--turn) / 2)`) narrows to 15 % edge-on and widens face-on.
   - `will-change: transform` is set on `.spinner` only.

   These are the mock's layers and keyframes. Alternative: a flat 2D "breathing" or shine-only effect (not what the
   owner approved).

5. **"অসম চৰকাৰ" above and "सत्यमेव जयते" below, in gold, not turning.**
   - Both are `.goldText`: the same gradient clipped to the text (`background-clip: text`), with the slow sweep
     `gold-sweep var(--sweep) ease-in-out infinite`.
   - The Assamese line is Noto Serif Bengali 600 at 22 px and carries `lang="as"`.
   - The motto is Noto Serif Devanagari 500 at 15 px and carries `lang="sa"`. The motto is Sanskrit; the backlog
     calls it the "Hindi line", and only the script matters for the font.
   - Both texts are new keys in `messages.ts`, `T.auth.frame.emblem.assamese` and `T.auth.frame.emblem.motto` (owner,
     point 5). `messages.ts` already holds non-ASCII text, and the i18n catalogue test keeps every locale on the same
     keys.

6. **Accessibility: one label for the emblem, every decorative layer hidden.**
   - `.emblemArt` (the two lines and the stage) is `role="img"` with `aria-label={T.brand.emblemAlt}` ("Emblem of the
     Government of Assam"), the same alternative text the emblem has elsewhere.
   - Its children are `aria-hidden="true"`.
   - The button sits outside the `role="img"` element, so it stays operable.
   - The texts are part of the emblem (a logotype), so the contrast rule does not apply. Gold on navy is high
     contrast anyway.

   The portal stays at WCAG 2.1 AA (portal-ui-redesign decision 20). Success criterion 2.2.2 is met by decision 7.

7. **The Pause / Play button (owner, point 1).**
   - It is a native `<button type="button">` under the emblem, styled in `auth.module.css` as the mock's small pill:
     a gold line border and `--panel-accent` text.
   - Its focus is visible: a 2 px `--panel-accent` outline, offset by 2 px.
   - It is never a primary action, so the frame's "one primary per page" test stays at 1.
   - On laptops it shows an icon and a word: "Pause" while turning, "Play" while stopped. Its accessible name is
     "Pause the Emblem's Movement" or "Play the Emblem's Movement", which contains the visible word (success
     criterion 2.5.3).
   - On phones it shows the icon only, with the same name.
   - The label changes, so the button has **no `aria-pressed`**. The mock set both, which makes screen readers
     announce a contradiction.
   - The new texts are `T.auth.frame.emblem.pause`, `play`, `pauseLabel` and `playLabel`.
   - Two icons, `PauseIcon` and `PlayIcon`, are added to `components/shell/icons.tsx`.
   - The button stops all four motions: the turn, the sheen, the floor shadow and the gold sweep of the two text
     lines.

8. **Pausing shows the still front face. Deviation from the mock (not from the plan), for the owner to approve with
   this note.**
   - The mock pauses in place (`animation-play-state: paused`), so a pause near edge-on leaves a gold sliver.
   - Here the paused state sets `data-motion="paused"` on the emblem block, and the CSS drops the four animations. The
     emblem then shows the same still, face-on gold emblem as under reduced motion.
   - Play starts the turn again from the front.
   - A paused screen is also the same in every screenshot (uicheck, decision 14).

   Alternative: pausing in place as in the mock (rejected: it can stop on an unreadable sliver).

9. **The choice is remembered on that browser.**
   - `localStorage` key `aslms.emblemMotion` holds `"paused"`, or nothing. It is read after mount and written on each
     click.
   - The choice holds from the sign-in page to the code page and to the first-sign-in pages, which have a different
     layout and so remount the frame.
   - If `localStorage` cannot be used (some private modes), the choice lasts only while the frame stays mounted, the
     same fallback as `lib/session/store.ts`.
   - The server always renders the turning state. A stored pause takes effect at hydration, which is a fraction of a
     second.

   Alternatives: `sessionStorage` (the choice would be lost at the next visit); no memory (the officer would pause
   again on every page).

10. **The brand row on the form side is removed (owner, point 3).**
    - `.brandRow`, `.lockup`, `.gov`, `.name` and the rule `.brandRow:has(+ .wide)` go.
    - `data-testid="auth-brand"` is retired.
    - The emblem now appears once, on the navy panel.
    - The form side keeps the page's form and the foot line. The sign-in form keeps "Sign In" and "Use your official
      e-mail and password." (`T.auth.signIn`, `T.auth.signInSub`), and the code, reset and first-sign-in pages keep
      their own headings.
    - `BrandLockup` has no other caller, so it is removed from `Brand.tsx`, together with `BRAND.lockup` and the
      `lockup` field of `BrandConfig`.
    - The official file `public/brand/assam-emblem-lockup.png` stays where it is. Under decision 21 only the owner adds
      or removes the official files.

    Alternative: keeping `BrandLockup` unused (rejected: dead code).

11. **Phones and tablets (< 820 px, the existing breakpoint).**
    - The panel stays a header above the form, only as tall as its content.
    - `.panelTop` keeps the emblem beside the title: stage 52 x 78 px, gap `--s4`, divider padding `--s4`, title at
      22 px.
    - The two text lines are hidden, and the halo is inset to `-8px -14px`.
    - The floor shadow is 50 px wide.
    - The Pause / Play button sits under the small emblem, icon only, 28 px high, which is above the 24 px target
      minimum.
    - The lead line stays at `--t-sm`. The tiles and maker line stay hidden, as now.

    The mock's phone view is used as it is.

12. **Laptops between 820 and 1199 px get a smaller panel title.**
    - At 1024 px the panel's content column is about 440 px. Beside a 118 px emblem and the divider, the mock's 34 px
      title would break into four lines.
    - From 820 to 1199 px: the title is `--t-3xl` (30 px), and the `.panelTop` gap and divider padding are `--s5`.
    - From 1200 px: the mock's 34 px, with `--s6` gap and padding.
    - The stage stays 118 x 176 px on all laptops.

    This range is not in the mock; the owner's check at 1024 px covers it.

    Alternative: hiding the two text lines from 820 to 1199 px (rejected: the owner's laptop look should hold).

13. **Tokens in `globals.css` (`:root`).**
    - Gold, from the mock:
      - `--gold-deep: #7a5a14`, `--gold-mid: #c99a2e`, `--gold-light: #f7e08a`, `--gold-shine: #fff6c9`;
      - `--gold-line: rgba(246, 196, 142, 0.28)` and `--gold-halo: rgba(246, 196, 142, 0.22)`;
      - the gradient `--gold`, built from these stops plus the mock's three in-between stops (`#e2b545`, `#a8791d`,
        `#f3d270`, `#8c6418`), written once.
    - Motion: `--turn: 10s` (one turn) and `--sweep: 8s` (the text sweep), next to `--fast`, `--med` and `--slow`.
      Both become `0ms` in the existing reduced-motion block.
    - The layout signature's `COLOUR_TOKEN` pattern gains `gold(-[a-z]+)?`, so a later change of gold leaves the
      signature unchanged (portal-navy-cream decision 14).

    Alternative: hard-coding the values in `auth.module.css` (rejected: owner's item 8, and the token rule of
    portal-navy-cream).

14. **Reduced motion: a still gold emblem and no button.**
    - The existing global rule turns every animation off, and the tokens become 0 ms, so the emblem stays face-on with
      the gradient at rest.
    - `GoldEmblem` reads `usePrefersReducedMotion()` (`components/ui/motion.ts`) and then does not render the button.
    - `auth.module.css` also hides `.motionBtn` under `@media (prefers-reduced-motion: reduce)`, so the button does not
      show before hydration.

    Alternative: keeping the button with nothing to pause (rejected: a control that does nothing).

15. **The two fonts are self-hosted and loaded only on the public pages (owner, point 4).**
    - Two dependencies are added: `@fontsource/noto-serif-bengali` and `@fontsource/noto-serif-devanagari` (OFL
      licence), at the same `^5` range as the existing `@fontsource` packages, recorded in `package-lock.json`.
    - Only the one subset and weight each line needs is imported: the Bengali-script subset at 600 and the Devanagari
      subset at 500 (for example `@fontsource/noto-serif-bengali/bengali-600.css` and
      `@fontsource/noto-serif-devanagari/devanagari-500.css`). The developer confirms the exact file names in the
      installed packages.
    - The imports are in `AuthFrame.tsx`. Only the `(public)` and `(welcome)` layouts use it, so Next.js puts the two
      font faces in those routes' CSS alone, and the portal's pages never download them.
    - `font-display: swap` (the fontsource default) and a fallback stack (`"Nirmala UI", serif`) keep the lines
      readable while the font loads.
    - `font-src 'self'` is unchanged, and `npm audit --omit=dev` stays at 0.

    Alternative: Google Fonts as in the mock (rejected: CSP and owner's point 4); images of the two texts (rejected:
    the owner approved texts in `messages.ts`).

16. **Comments and documents follow the change.**
    - `AuthFrame.tsx`'s header comment and `auth.module.css`'s header comment describe the new panel and point to this
      note.
    - The scribe adds an "Amended by signin-gold-emblem (row 249)" line under portal-ui-redesign decisions 21 and 26,
      and an entry in `docs/claude_ASLMS_design_decisions.md`.
    - The layout signature snapshot is regenerated on purpose, as this note states
      (`UPDATE_LAYOUT_SIGNATURE=1 npx vitest run src/components/ui/layoutSignature.test.ts`).

## Data

None. No table, column, reference code or migration.

## Services

None. No backend change.

Portal modules touched (`frontend/src`):
- `components/auth/GoldEmblem.tsx`: new, client.
- `components/auth/AuthFrame.tsx`: the panel top, the brand row removed, the font imports.
- `components/auth/auth.module.css`: the panel top, the emblem, the button, the breakpoints, reduced motion; the
  brand-row rules removed.
- `components/shell/Brand.tsx`: `BrandLockup` removed.
- `components/shell/icons.tsx`: `PauseIcon`, `PlayIcon`.
- `lib/brand.ts`: `capital` added, `lockup` removed.
- `lib/messages.ts`: `T.auth.frame.emblem.*`.
- `app/globals.css`: the gold and motion tokens.
- `components/ui/layoutSignature.test.ts` and `layout-signature.json`.
- `public/brand/assam-emblem-capital-mask.png`: copied.
- `package.json` and `package-lock.json`: the two fonts.

## API

None. No endpoint is added or changed, so no `Permission` applies. The public pages stay outside the page gate as now.

## Jobs

None.

## Tests

Vitest (`frontend/src`):
- `components/auth/frame.test.tsx`, rewritten for the new frame:
  - **the sign-in, code, reset and reset-code pages show the gold emblem in the panel:**
    - one element with role `img` and name `T.brand.emblemAlt` inside the region `T.auth.frame.label`;
    - its stage has the inline `--emblem-mask` naming `BRAND.capital.src`;
    - the panel holds `T.owner`, `T.portalLong`, the lead and the three tiles;
    - the foot line is shown;
    - the court is not named;
    - exactly one primary action.
  - **the brand row is gone:** there is no `auth-brand` test id, `main` holds no `img`, and the emblem's label appears
    once on the page.
  - **the form keeps its heading and line:** the sign-in page has the heading `T.auth.signIn` and the text
    `T.auth.signInSub`; the code page has `T.auth.codeTitle`.
  - **the two text lines come from messages.ts with their languages:**
    - `T.auth.frame.emblem.assamese` with `lang="as"`, `T.auth.frame.emblem.motto` with `lang="sa"`;
    - both are inside the `role="img"` element and `aria-hidden`.
  - **Pause stops the motion and Play restarts it:**
    - the button is named "Pause the Emblem's Movement" and shows "Pause";
    - a click sets `data-motion="paused"` and renames the button "Play the Emblem's Movement";
    - a second click clears both;
    - the button has no `aria-pressed`;
    - it is not inside the `role="img"` element.
  - **the pause is remembered:** after a pause, `localStorage["aslms.emblemMotion"]` is `"paused"`; a fresh render of
    the first-sign-in frame starts paused; with `localStorage` throwing, the button still toggles.
  - **reduced motion hides the button:** with `matchMedia` answering reduced motion, there is no Pause / Play button,
    and the emblem's `role="img"` is still present.
  - **no capital file configured, no emblem:** `GoldEmblem` with `brand={{ emblem: …, capital: null }}` renders
    nothing.
  - the existing landmark test, adjusted: one `main#main` holding the form and the foot line, with the panel outside
    it, for the public and first-sign-in frames.
  - **the first-sign-in pages:** the same panel with the emblem, and the wider form side.
- `components/auth/frame.css.test.ts` (new, node), a static read of `auth.module.css` and `globals.css`:
  - the emblem's animations use `var(--turn)` and `var(--sweep)`, not literal seconds;
  - `--turn` and `--sweep` are `0ms` in the reduced-motion block;
  - `.motionBtn` is hidden under `prefers-reduced-motion: reduce`;
  - the paused state removes the four animations;
  - the gold values are only in `globals.css` as `--gold*` tokens, with no gold hex in `auth.module.css`;
  - `.brandRow` no longer exists.
- **the Noto fonts load only on the public pages** (source scan, node):
  - `AuthFrame.tsx` imports the two `@fontsource/noto-serif-*` stylesheets;
  - no file under `src/app/(portal)` and neither `src/app/layout.tsx` nor `globals.css` imports them.
- `components/shell/shell.test.tsx`:
  - **the configured emblem files are the official ones under public/brand/:** the directory lists exactly
    `assam-emblem-capital-mask.png`, `assam-emblem-lockup.png` and `assam-emblem-mark.png`;
  - `BRAND.emblem.src` is unchanged, and `BRAND.capital` is `{ src: "/brand/assam-emblem-capital-mask.png", width:
    508, height: 756 }`;
  - the capital file's bytes equal `docs/design/ui/assam-emblem-capital-mask.png` (a SHA-256 comparison, so the copy
    is unaltered).
- `proxy.test.ts`: `/brand/assam-emblem-capital-mask.png` is outside the gate; the CSP still has `font-src 'self'` and
  `img-src 'self' data:`.
- `lib/i18n.test.ts` (existing): the new keys exist in every catalogue, and no JSX text literal is added.
- `components/ui/layoutSignature.test.ts`: the snapshot regenerated, and a case proving that a `var(--gold)` inside
  `background` masks to `<c>`.
- `lib/branding.test.ts` (existing) stays green: no agency names in the new files.

uicheck (`frontend/e2e/uicheck.spec.ts`):
- The four public routes and the first-sign-in routes pass at 375, 768, 1024 and 1280 px under reduced motion, with
  0 findings. There, the still emblem is in the panel and no Pause button is shown.
- New state **"/login (motion on)"**, at all four widths:
  - `page.emulateMedia({ reducedMotion: "no-preference" })`;
  - the Pause button is visible, inside the panel, not overlapping the emblem or the title, and icon only at 375 and
    768 px;
  - a click turns it into Play, and the spinner's computed `animation-name` is `none`;
  - the screenshot is then taken (still front face, decision 8);
  - every font request on the page is same-origin.
- On `/` (a portal page) no `noto-serif` font file is requested.
- `UICHECK_BOXES=1` box comparison: the public pages' boxes change as this note describes. No portal page's boxes
  change.

## Verification

The integrator:
1. In `frontend/`, runs `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npx vitest run` and `npm run build`; all green.
   `npm audit --omit=dev` reports 0 vulnerabilities.
2. Runs the Compose-free uicheck on temporary images as in runbook section 16. Expected: every route and state passes
   with 0 findings, including the new "/login (motion on)" state at 375, 768, 1024 and 1280 px. The contact sheet shows
   the panel with the gold emblem, the two lines (hidden at 375 and 768 px), the divider and the title, and the form
   side without the brand row.
3. After deploy, against `http://localhost:3000/login`:
   - `curl -sI http://localhost:3000/login` shows the same `Content-Security-Policy` as before (`font-src 'self'`);
   - `curl -sI http://localhost:3000/brand/assam-emblem-capital-mask.png` answers 200 `image/png`.
4. The owner's browser check (Chrome or Edge, and Firefox) at 375, 768, 1024 and 1280 px:
   - the emblem turns about once in 10 s and never shows mirrored;
   - the floor shadow narrows edge-on;
   - the two lines are gold and sweep slowly;
   - Pause stops all of it on the front face, and Play resumes;
   - after Pause, the code page (after a sign-in) and a reload stay paused;
   - with "reduce motion" switched on in Windows (Settings, Accessibility, Visual effects, Animation effects off), the
     emblem is still and there is no button;
   - the DevTools Network panel on `/login` shows the two Noto font files and the mask from `localhost:3000` only, and
     none of them on the dashboard;
   - the Performance panel shows no long tasks while the emblem turns.

**Owner check passed, 13 Nov 2026:** the owner checked the sign-in page in the browser and reported it ok. View Cause List → Original PDF (List and Download on one line) is still to be checked.

## Open questions

None. The owner settled the approach, the mock and points 1 to 5 on 12 Nov 2026. Decision 8 (pausing shows the still
front face rather than freezing in place as the mock does) is the one change from the mock, and the owner approves it
with this note.

## Deviations

Recorded by the developer while building; none changes the plan or a business rule.

1. **Three more colour tokens.** The colour-literal guard (`tokens.test.ts`, portal-navy-cream decisions 7 and 14)
   allows no `rgba()` in a CSS module, so the mock's remaining literals became `:root` tokens next to the gold ones:
   `--gold-wash` (the button's hover, `rgba(246, 196, 142, 0.1)`), `--gold-glow` (the faces' glow,
   `rgba(247, 208, 120, 0.35)`) and `--shadow-emblem` (the drop shadow and the floor shadow, `rgba(0, 0, 0, 0.45)`).
   The button's resting ground is the existing `--panel-tile`. All three names fall under the layout signature's
   colour pattern (`gold(-[a-z]+)?` and `shadow-[a-z0-9]+`).
2. **Spacing from the scale.** The spacing guard (`tokens.test.ts`, decision 14) allows only scale tokens in
   margins, paddings and gaps, so the mock's 6, 10, 14 and 28 px became `--s1`, `--s2`, `--s3` and `--s5`. The floor
   shadow is placed by `left` and `right` insets (4 px on laptops, 1 px on phones: the mock's 110 and 50 px) rather
   than a negative margin, because its `transform` belongs to the narrowing animation.
3. **The motion-rules test follows decision 13.** `motionRules.test.ts` pinned the reduced-motion block word for
   word; it now includes `--turn: 0ms` and `--sweep: 0ms`.
4. **`.lockupImage` removed from `shell.module.css`.** It styled only `BrandLockup`'s default image and had no other
   user (decision 10, dead code). No portal page's boxes change.
5. **uicheck.** The state list gained a `public` flag so "/login (motion on)" runs without session cookies, and the
   portal-page font check is a state of its own, "/ (no sign-in fonts)", at 1280 px only. In "/login (motion on)"
   the Noto font requests are required only from 820 px up, because the two lines are hidden (and so never fetched)
   on phones and tablets.
