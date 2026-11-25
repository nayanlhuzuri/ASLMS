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

1. **The hero is the whole first screen.** The hero is exactly one screen tall at every width where it fits
   (`min-height: 100svh`, with `100vh` as the fallback), and the hero's content is
   centred vertically in that height. When the content is taller than the screen (a phone with the card stacked under
   the heading, or a short laptop window) the hero simply grows; it never clips and never scrolls inside itself.
   Everything else (the sample screens, the strip of what ASLMS does, the footer) starts below the first screen and is
   reached by scrolling.
   With the top bar gone, the hero fills the height instead of floating in it (owner, on the mock: "the top empty
   space looks weird"): the gold emblem, the full name and the heading grow with the screen's height within fixed
   limits (`clamp()` on `vh`, the heading capped so it keeps two lines on a wide screen, about 68 px at most), the
   content block sits a little above the centre (less space above than below), and the hero's content column is
   up to about 1,520 px wide on a large screen. At the bottom of the first screen a quiet line "See What You Work
   With" with a small down arrow scrolls to the sample screens (a link to `#samples`, never a button; the arrow's
   gentle nudge stops under reduced motion). The gold emblem keeps turning exactly as on the live page, with its
   Pause / Play button.
2. **One sign-in, on the card, and no top bar.** The top bar is removed entirely (owner, 25 Nov 2026, on the mock:
   "you can remove the header. it is looking odd"); the hero's own lockup (the gold emblem, "Government of Assam"
   and the full name) is the page's identity, and the page's `h1` stays the heading. The closing band, whose only purpose was a second Sign In link, is removed. The Sign In jump of row
   274 decision 11 (`jumpToSignIn.ts`, its test and its uicheck states) goes with them, since nothing links to the
   card any more. The card's own submit stays the page's one primary action.
3. **The sample screens are the real screens with sample data.** In place of today's made-up window, the page shows
   two framed pictures that look exactly like the live portal:
   - **Case Inbox, With Me tab**: the shell's side menu and top line as the portal draws them, the page heading, the
     four tabs, the toolbar and the real `DataTable` with its real columns, `HearingDate` badges (Today or Tomorrow in
     red, within a week in amber) and status badges, five or six rows.
   - **Case Assistant answer**: a question and the answer as the Assistant page draws it, with the AI label, the
     numbered source markers and the Sources list (order, date, page and excerpt).
   - **The Assistant picture plays a short conversation** (owner, 25 Nov 2026, on the mock): four messages, two
     questions and two answers about one sample case. Each question is typed into the ask box and then rises in as
     a bubble; the Assistant shows a three-dot typing indicator for about a second, then its answer writes out word
     by word with its source markers, and its Sources card fades in. Whole conversation about 15 to 20 seconds.
     The picture keeps the size of the still Assistant picture (owner: "keep the assistant section size same as
     before"): the message area has a fixed height, new messages enter at the bottom as in a chat window, and older
     ones move up and fade out under a soft top edge; nothing scrolls inside it and the page never jumps.
     It starts when the picture is at least a third in view (IntersectionObserver) and runs in a continuous loop
     until paused (owner: "it should run in a continuous loop until it is paused"): after the last answer it waits
     about 3.5 seconds, the messages fade out, and it begins again. It holds while the picture is out of view. A
     Pause / Play button in the picture's caption bar stops and resumes it at any point (WCAG 2.2.2, as the
     emblem's button). Under `prefers-reduced-motion: reduce` the finished conversation shows at once
     and the button is hidden. Only `opacity` and `transform` are animated, in the portal's motion tokens. The
     moving text is `aria-hidden`; the `role="img"` label describes the whole conversation.
   They are built from the portal's own kit components fed with static sample data, so they stay true when the kit
   changes. They are inert (`inert`, `aria-hidden`), with one `role="img"` and a label that names what each shows, no
   link, no request, and no live data.
4. **Sample data, by the owner's leave, that cannot be mistaken for a real record.** Each picture carries a visible
   "Sample Data" label. Case numbers keep the court's format with a masked number, for example `WP(C)/XXXX/2026`; no
   CNR is shown. Parties are plain role words or invented generic names with "vs State of Assam & Ors."; no
   department, officer or judge is named; dates are words ("Tomorrow", "In 5 Days") or dates in a fixed sample month,
   so the picture does not go out of date. A cause-list item number in the conversation is a plain sample number with
   the masked case number beside it. This keeps CLAUDE.md's "never fabricate identifiers" rule: nothing on the
   page can be taken for, or confused with, a held case.
5. **Layout below the first screen.** From 1024 px the two pictures sit side by side, the Case Inbox wider (about
   1.65 to 1) and the Assistant beside it (owner, on the mock: "exactly how it was before beside the sample
   screens"). The Case Inbox sets the row's height and the Assistant fills exactly that height, so neither has an
   empty band. To fit every column beside the Assistant, the picture's side menu is narrower than the live one and
   the Sent By column is left out when the picture is narrower than about 860 px (a container query). Below 1024 px
   they stack; on a phone the table stacks as cards as the real `DataTable` does, with no horizontal scroll. The strip of what ASLMS does and the
   footer follow as built.

The mock the owner reviewed on 25 Nov 2026 (a local page, not part of the build) shows decisions 1 to 5.

## Data, Services, API, Jobs
None. Frontend only, no migration, no API change.

## Tests
- `home.test.tsx`: there is no top bar (no `header` before `main`) and no Sign In link outside the card; there is no closing band; the page has exactly one form and one
  primary button; both pictures are `role="img"` with a label and an `inert`, `aria-hidden` window; each shows
  "Sample Data"; no CNR pattern (`[A-Z]{4}\d{2}\d{6}\d{4}`) and no unmasked case number appear in the page text.
- `home.css.test.ts`: the first-screen rule (`min-height: 100svh` with the `100vh` fallback) is present on the first
  screen's wrapper.
- `jump.test.ts` and `jumpToSignIn.ts` removed; any test that clicked a Sign In link updated.
- `homeChat.test.tsx`: the conversation plays in order (question, typing, answer, sources), Pause stops it and Play
  resumes it, it starts again after the last answer, it holds while out of view, and under reduced motion all four messages are present at once with no button.
- uicheck: the `/login` states (taken under reduced motion, so the conversation is in its finished state) at 375, 768, 1024 and 1280 px with 0 findings; the Sign In jump states removed; a check
  at 1280 px that the sample pictures start below the first screen (the hero's bottom is at or after the viewport's
  height), and that the two pictures' bottoms are level from 1024 px.

## Verification
1. `npm run lint`, `npm run typecheck`, `npm test` and the production build are green; the uicheck run reports 0
   findings.
2. The owner looks at `/login` at 375, 768, 1024 and 1280 px (row 280, now covering this row too): the first view is
   the hero and the card alone; there is no other Sign In; the pictures look like the Case Inbox and the Assistant.

## Open questions
None. The owner's three instructions settle the scope; decision 4 records how "dummy data" keeps the identifier rule.
