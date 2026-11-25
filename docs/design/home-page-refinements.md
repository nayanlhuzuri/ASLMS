# Design: Home page refinements from the owner's first look

```
slug: home-page-refinements
status: approved
author: main session (from the owner's instructions)
date: 2026-11-25
approved_by: owner on 2026-11-25
```

## Context
Backlog row 281. Row 274 `home-page` (docs/design/home-page.md) went live on 25 Nov 2026 at 09:18. The owner looked at
it on a laptop that afternoon (a screenshot of the first view at about 2520 px wide) and asked for three changes, in
their words:

> "you can keep this section as the whole first screen and then the remaining part as scrollable. also since you are
> providing the sigin section in the home page, remove the other sign in sections and button at the header. and the
> sample screens please provide as per the actual screens and not the current one. you can provide dummy data for the
> sample screens."

These instructions are the approval: this note only fixes how they are built. Everything in docs/design/home-page.md
not named here stays as built (the code step in place at `/login?step=code`, `/login/code` redirecting, the gold
emblem with Pause / Play, the arrival fade into the Dashboard, reduced motion, no request before sign-in, no figure,
no help contact).

## Decisions

1. **The hero is the whole first screen.** The top bar and the hero together are exactly one screen tall at every
   width where they fit (`min-height: 100svh` on the pair, with `100vh` as the fallback), and the hero's content is
   centred vertically in that height. When the content is taller than the screen (a phone with the card stacked under
   the heading, or a short laptop window) the hero simply grows; it never clips and never scrolls inside itself.
   Everything else (the sample screens, the strip of what ASLMS does, the footer) starts below the first screen and is
   reached by scrolling. No scroll hint, arrow or animation is added.
2. **One sign-in, on the card.** The top bar keeps only the name ("ASLMS" and "Government of Assam") and loses its
   Sign In link. The closing band, whose only purpose was a second Sign In link, is removed. The Sign In jump of row
   274 decision 11 (`jumpToSignIn.ts`, its test and its uicheck states) goes with them, since nothing links to the
   card any more. The card's own submit stays the page's one primary action.
3. **The sample screens are the real screens with sample data.** In place of today's made-up window, the page shows
   two framed pictures that look exactly like the live portal:
   - **Case Inbox, With Me tab**: the shell's side menu and top line as the portal draws them, the page heading, the
     four tabs, the toolbar and the real `DataTable` with its real columns, `HearingDate` badges (Today or Tomorrow in
     red, within a week in amber) and status badges, five or six rows.
   - **Case Assistant answer**: a question and the answer as the Assistant page draws it, with the AI label, the
     numbered source markers and the Sources list (order, date, page and excerpt).
   They are built from the portal's own kit components fed with static sample data, so they stay true when the kit
   changes. They are inert (`inert`, `aria-hidden`), with one `role="img"` and a label that names what each shows, no
   link, no request, and no live data.
4. **Sample data, by the owner's leave, that cannot be mistaken for a real record.** Each picture carries a visible
   "Sample Data" label. Case numbers keep the court's format with a masked number, for example `WP(C)/XXXX/2026`; no
   CNR is shown. Parties are plain role words or invented generic names with "vs State of Assam & Ors."; no
   department, officer or judge is named; dates are words ("Tomorrow", "In 5 Days") or dates in a fixed sample month,
   so the picture does not go out of date. This keeps CLAUDE.md's "never fabricate identifiers" rule: nothing on the
   page can be taken for, or confused with, a held case.
5. **Layout below the first screen.** On a laptop the two pictures sit side by side (Case Inbox wider), and below
   1024 px they stack, each scaled to the column, with no horizontal scroll. The strip of what ASLMS does and the
   footer follow as built.

## Data, Services, API, Jobs
None. Frontend only, no migration, no API change.

## Tests
- `home.test.tsx`: the top bar holds no Sign In link; there is no closing band; the page has exactly one form and one
  primary button; both pictures are `role="img"` with a label and an `inert`, `aria-hidden` window; each shows
  "Sample Data"; no CNR pattern (`[A-Z]{4}\d{2}\d{6}\d{4}`) and no unmasked case number appear in the page text.
- `home.css.test.ts`: the first-screen rule (`min-height: 100svh` with the `100vh` fallback) is present on the first
  screen's wrapper.
- `jump.test.ts` and `jumpToSignIn.ts` removed; any test that clicked a Sign In link updated.
- uicheck: the `/login` states at 375, 768, 1024 and 1280 px with 0 findings; the Sign In jump states removed; a check
  at 1280 px that the sample pictures start below the first screen (the hero's bottom is at or after the viewport's
  height).

## Verification
1. `npm run lint`, `npm run typecheck`, `npm test` and the production build are green; the uicheck run reports 0
   findings.
2. The owner looks at `/login` at 375, 768, 1024 and 1280 px (row 280, now covering this row too): the first view is
   the hero and the card alone; there is no other Sign In; the pictures look like the Case Inbox and the Assistant.

## Open questions
None. The owner's three instructions settle the scope; decision 4 records how "dummy data" keeps the identifier rule.
