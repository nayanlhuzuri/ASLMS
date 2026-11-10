# Design: Portal colours, navy and cream with orange

```
slug: portal-navy-cream
status: approved
author: architect
date: 2026-11-10
approved_by: owner on 2026-11-10, with the recommended answers to the open questions
```

## Context

Backlog row 229. **Owner, 10 Nov 2026** (decisions log, "2026-11-10 — Portal colours: navy and cream with orange
(owner)"): the portal's colours become navy and cream (about 90%) with orange (about 10%) for what must stand out, as
in the sample screens the owner approved (Dashboard, Case Claim, Sign In, and the palette sheet). **The owner's hard
rule: colours only.** Every position, size, spacing, font weight and layout stays exactly as it is in the portal
today. The samples are drawn with their own spacing (40 px controls, a menu with the emblem at its top, a toast, an
orange bar under the sign-in title); none of that geometry is adopted, only their colours and their rules for orange.

**The plan.** Annexure B shows "indicative UI screens"; the plan fixes what each screen holds, not its colours. Nothing
here deviates from the plan. This row amends three earlier design decisions, each marked where it applies:
portal-ui-redesign decision 11 (the token values and "blue = action or selection"), decision 20 (the focus ring's
colour) and decision 26 (the sign-in panel's deep blue).

**What exists (read for this design, `main` at a956b9d).**
- `frontend/src/app/globals.css` `:root` holds every colour token: `--bg`, `--surface`, `--surface-2`, `--border`,
  `--border-strong`, `--text`, `--text-2`, `--text-3`, `--accent` / `-hover` / `-soft` / `-ring`, `--red`,
  `--red-text`, `--red-soft`, `--on-red`, `--amber`, `--amber-soft`, `--green`, `--green-soft`, `--slate-soft`,
  `--panel-from` / `-to` / `-text` / `-strong` / `-muted` / `-accent`, and three shadows. Motion tokens `--ease`,
  `--fast 150ms`, `--med 220ms`, `--slow 320ms`, all 0 ms under `prefers-reduced-motion`, with every animation and
  transition off (decision 13); `components/ui/motion.ts` mirrors them for the JavaScript parts.
- `components/ui/tokens.test.ts` pins the values, checks 23 text pairs for 4.5:1, white on the accent, the next-hearing
  pairs, a hearing-badge module with no colour literal, spacing from the scale, and the retired alias names.
- **One accent does two jobs.** `--accent*` has **122 uses** in globals and 27 CSS modules. It colours the main button,
  links, focus rings, selected items, info badges, progress fills and avatars. The new palette splits them (decision 2).
- **Colour literals outside the tokens:** 29 in CSS modules and 7 in one component.
  - `admin.module.css`: the Save bar `#0b1220`, `#fff`, `rgba(255,255,255,.18)`, `#fec84b`, `#cbd5e1`.
  - `auth.module.css`: the panel's blue glow `rgba(37,99,235,.33)`, the dot grid, the tile border and ground, the tile
    icon ground `rgba(37,99,235,.2)`, `#fff` on the current step.
  - `calendar` and `filters`: `#fff`.
  - `reports.module.css`: the fallback `var(--accent, #1d4ed8)`.
  - `shell.module.css`: the bell pulse in red rgba, the drawer scrim.
  - `controls.module.css`: `#fff` on the primary, the danger border `#fda29b`, the switch knob `#fff` and its shadow.
  - `ui/data.module.css`: the fallback `var(--surface-2, #f8fafc)`.
  - `feedback.module.css`: the banner, notice and warning borders `#fecdca`, `#abefc6`, `#fedf89`, the skeleton
    gradient.
  - `overlays.module.css`: the scrim.
  - `components/case/LinkGraph.tsx`: seven hex values as SVG `fill` and `stroke` attributes.
  - `globals.css` outside `:root`: `#fff` on `.button-link`.
- **The side menu** (`shell.module.css` `.sidebar`) is a white column under the header. On phones (< 820 px) it is a
  drawer whose top block holds the brand (the official emblem) and the search box. The emblem files in
  `public/brand/` are near-black and deep maroon on a transparent ground, kept unaltered by decision 21.
- **Data graphics:** `components/ui/charts.tsx` draws inline SVG.
  - `SparkBars`: green, red, empty.
  - `RateRing`: tones ok, warn, down, unknown.
  - `StatusDot`: the same tones plus busy.
  - The kit's `ProgressBar`, meters, segment bars and step dots.
  - `LinkGraph` (the case links graph).
- **Motion already in the portal:**
  - the page content's fade-and-rise (`aslms-fade-in`, 6 px, `--slow`) and the sign-in rise (`auth-rise`);
  - the kit `Tabs` sliding underline (`.ink`, `--med`);
  - the 1 px button lift and the 2 px KPI-tile lift;
  - the pulsing bell dot;
  - the count-up of headline numbers.
  The portal has no toast.
- **Tooling:**
  - `uicheck` (Playwright, `frontend/e2e/`) visits every route and interaction state at 375, 768 and 1280 px against
    the fixtures. It runs the geometry checks of `checks.ts`, among them "one primary": more than one visible
    `[data-variant=primary]` or `.button-link` outside a dialog fails.
  - `pages.test.tsx` checks the same in vitest.
  - The check runs on a private network against temporary images (runbook section 16).

**Order.** Row 229 builds after **row 228** (`dashboard-my-work-polish`, which recolours the dashboard alert badges
by meaning: recommendations navy, strong solid and possible outlined) and after the **findings of row 230** (the
review of every portal screen). Decision 15 is the hook for those findings.

**Not covered:**
- a dark theme (decision 13);
- e-mails and the Excel and PDF exports, which keep their own neutral colours (backend templates);
- any change of text, layout, size, spacing or font weight;
- any new animation that would change layout (decision 12).

## Decisions

### A. The palette as tokens

1. **The token mapping, old → new** (`globals.css` `:root`; values from the decisions log and the approved samples).

   | Token | Today | New | Used for |
   |---|---|---|---|
   | `--bg` | `#f5f7fa` | `#F7F1E3` | the page (cream) |
   | `--surface` | `#ffffff` | `#FFFBF2` | cards, tables, dialogs, header, sign-in form side |
   | `--surface-2` | `#f9fafb` | `#F6EDDA` | table header, row hover, dialog and panel feet, code blocks |
   | `--field` *(new)* | — | `#FFFFFF` | text fields, selects, textareas, the switch knob (white fields on cream, as in the samples) |
   | `--border` | `#e4e7ec` | `#E2D6BE` | lines and dividers |
   | `--border-strong` | `#d0d5dd` | `#CDBFA6` | field and button borders |
   | `--text` | `#101828` | `#13213F` | body text (ink) |
   | `--text-2` | `#475467` | `#4A5570` | secondary text |
   | `--text-3` | `#667085` | `#5B6580` | muted text, labels |
   | `--heading` *(new)* | — | `#0F1E3D` | `h1`–`h3`, KPI values, selected tab text |
   | `--slate-soft` | `#f2f4f7` | `#EFE6D2` | the shade: neutral badges, tracks, ghost hover |
   | `--action` *(new)* | — | `#22386A` | navy 700: ordinary actions and selection |
   | `--action-hover` *(new)* | — | `#2E4785` | its hover |
   | `--action-soft` *(new)* | — | `#E3E8F2` | a selected item's ground, the info tone |
   | `--on-action` *(new)* | — | `#FFFFFF` | text on a navy fill |
   | `--link` *(new)* | — | `#3C5A94` | navy 500: links, icons |
   | `--link-hover` *(new)* | — | `var(--action)` | link hover |
   | `--mark` *(new)* | — | `#F28C28` | orange fill (always with navy text), markers on navy |
   | `--mark-hover` *(new)* | — | `#F59A3E` | the orange button's hover |
   | `--on-mark` *(new)* | — | `#0F1E3D` | navy text on orange |
   | `--mark-text` *(new)* | — | `#B4470C` | deep orange: orange words and thin markers on cream |
   | `--mark-soft` *(new)* | — | `#FDE9D1` | the highlighted headline tile |
   | `--mark-line` *(new)* | — | `#F3C99B` | its border |
   | `--mark-glow` *(new)* | — | `rgba(242, 140, 40, 0.45)` | the orange button's hover shadow, the bell pulse |
   | `--focus-line` *(new)* | — | `var(--mark-text)` | the focus outline and focused field border |
   | `--focus-ring` *(new)* | — | `rgba(242, 140, 40, 0.35)` | the 4 px focus halo |
   | `--accent`, `--accent-hover`, `--accent-soft`, `--accent-ring` | blue | **retired** | split by decision 2 |
   | `--red` | `#d92d20` | `#B42318` | urgent fills (the strong hearing band) and borders |
   | `--red-text` | `#b42318` | `#B42318` | urgent words |
   | `--red-soft` | `#fef3f2` | `#FBE7E4` | urgent ground |
   | `--on-red` | `#ffffff` | `#FFFFFF` | unchanged |
   | `--red-line` *(new)* | — | `#EBB1A9` | danger button and error banner border |
   | `--amber`, `--amber-soft` | `#b54708`, `#fffaeb` | **retired** | replaced by ochre (decision 6) |
   | `--ochre` *(new)* | — | `#7A5A00` | due soon, warnings, "changed" marks |
   | `--ochre-soft` *(new)* | — | `#F5ECCB` | their ground |
   | `--ochre-line` *(new)* | — | `#E3D08F` | warning notice border |
   | `--green` | `#067647` | `#0B6B3A` | done, confirmed |
   | `--green-soft` | `#ecfdf3` | `#E2F0E5` | its ground |
   | `--green-line` *(new)* | — | `#A9D3B5` | success notice border |
   | `--panel-from` / `--panel-to` | `#0b1f4d` / `#0f172a` | `#0F1E3D` / `#0B1730` | the navy ground (decision 8) |
   | `--panel-text` | `#cbd5e1` | `#C9D3E6` | text on navy |
   | `--panel-strong` | `#ffffff` | `#FFFFFF` | strong text on navy |
   | `--panel-muted` | `#94a3b8` | `#8C97B0` | muted text on navy |
   | `--panel-accent` | `#93c5fd` | `#F6C48E` | light orange words on navy (the sign-in kicker) |
   | `--panel-raised` *(new)* | — | `#22386A` | the selected menu item, tile icon ground |
   | `--panel-hover` *(new)* | — | `#1C2B4D` | menu hover on navy |
   | `--panel-line` *(new)* | — | `#2A3B5E` | lines on navy |
   | `--panel-dots`, `--panel-tile`, `--panel-tile-line` *(new)* | literals | `rgba(255,255,255,.06 / .03 / .10)` | the sign-in panel's dot grid and tiles |
   | `--scrim` *(new)* | literal | `rgba(15, 30, 61, 0.40)` | dialog and drawer scrim |
   | `--shadow-1/2/3` | `rgba(16,24,40,…)` | `rgba(15,30,61,…)`, same offsets and alphas | navy-tinted shadows |
   | `--shadow-knob` *(new)* | literal | `0 1px 2px rgba(15, 30, 61, 0.2)` | the switch knob |

   **Headings use navy 900 (`#0F1E3D`), as the approved screens render them.** The palette sheet's caption says navy
   700 for headings. Both pass AA (15.97:1 and 11.04:1 on the card), and the screens are what the owner looked at. The
   comment at the top of `globals.css` changes to give the fixed meanings: red = urgent, overdue or within 48 h;
   ochre = due soon; green = done or confirmed; navy = action or selection; orange = the one thing to do now, focus, and
   markers; neutral = everything else.
   *Amends portal-ui-redesign decision 11.* Alternatives:
   - keep the name `--accent` and point it at navy (a name that no longer says which of the two colours it is);
   - keep `--amber` with an ochre value (a misleading name).
   The retired names join a second retired list in the token test, so a leftover use fails (decision 14).

2. **The accent splits: navy for ordinary actions and selection, orange for the 10%.** Every one of the 122 uses goes
   one way, as listed below.

   **Orange, the one main action** (bright fill `--mark`, hover `--mark-hover`, text `--on-mark`; on hover the
   existing lift, with the shadow `0 4px 12px var(--mark-glow)`):
   - `controls.module.css` `.primary`, `.primary:hover`;
   - `globals.css` `.button-link`, `.button-link:hover`.

   **Orange, focus** (decision 5): the outline uses `--focus-line` and the halo uses `--focus-ring`.
   - `globals.css` `:focus-visible`.
   - `outline` rules:
     - assistant `.thread:focus-visible` and `.marker:focus-visible`;
     - causelist `.entry:focus-visible`;
     - reports `.scroll:focus-visible` (fallback dropped);
     - shell `.row:focus-visible` (it takes `--nav-focus`, decision 9);
     - ui/data `.clickable` and `.sortButton:focus-visible`;
     - layout `.scrollBox`;
     - listSearch `.clear`.
   - Halo rules:
     - claim `.tab:focus-visible` and system `.tab:focus-visible`;
     - controls `.revealButton` and `.switch:focus-visible`;
     - layout `.tabs .tab:focus-visible` (inset);
     - workflow `.person:focus-within`.
   - Focused fields (border `--focus-line`, halo `--focus-ring`): controls `.input:focus`, shell `.search input:focus`,
     listSearch `.input:focus` and `.select:focus`.
   - admin `.jumpNav a:focus-visible`: the left border uses `--focus-line` and the text uses `--heading`.

   **Orange, selection markers:**
   - the side menu's 3 px current bar (`.nav a[aria-current]::before`): `--nav-mark` (decision 9);
   - the open tab's underline (deep orange `--mark-text`, decision 5): layout `.ink` (the kit `Tabs`), remarks
     `.tabOn`, claim `.tab[aria-selected="true"]`, system `.tab[aria-selected="true"]`;
   - the selected tab's text uses `--heading` (layout `.tab[aria-current]` and `.tabMoreCurrent`, and the three above);
     it is never orange;
   - the phone bottom bar's current item (`.bottomBar a[aria-current]`) uses `--mark-text`.

   **Orange, counts that need action** (fill `--mark`, text `--on-mark`):
   - the side menu's counts (`.navCount`, current or not): Case Inbox With Me, Case Claim, Alerts unread;
   - the Save bar's unsaved count (`admin .saveBar:not([data-count="0"]) .saveCount`, today `#fec84b` on
     `#0b1220`).

   **Orange, the bell dot** (`shell .dot`): fill `--mark-text`, pulse halo `--mark-glow` fading to `transparent`
   (decision 5).

   **Orange, the one headline tile:** a new kit class `.kpiMark` on `Kpi` (decision 10).

   **Navy, everything else:**
   - **Links** (`--link`, hover `--link-hover`):
     - globals `a` and `.skip-link`;
     - controls `.link`;
     - layout `.crumbs a:hover` and `.summary`;
     - dashboard `.title:hover`;
     - officePicker `.sub`;
     - assistant `.uncited summary`;
     - collectProgress `.state-fetching`;
     - overlays `.menuList a[aria-current]`.
   - **Selected items** (ground `--action-soft`, text `--action`):
     - layout `.settingsLink[aria-current]`;
     - officePicker `.option[aria-selected]`;
     - assistant `.conv[aria-current]`;
     - controls `.chipOn` (border `--action`) and `.filterChip`;
     - calendar `.selected .day`;
     - workflow `.personOn` (border `--action`);
     - causelist `.heading th`;
     - data `.useEverything` (left border `--action`).
   - **Navy borders on hover and on applied filters** (`--action`): controls `.chip:hover`, workflow `.person:hover`,
     filters `.chip`.
   - **The info tone** (ground `--action-soft`, text `--action`):
     - feedback `.badge-info`;
     - assistant `.num` and `.marker` (border `--action`; on hover, fill `--action` with `--on-action`);
     - rail `.nowMark`;
     - calendar `.ev-confirm`.
   - **Navy fills with white text** (`--action` with `--on-action`):
     - auth `.stepOn`;
     - calendar `.dayNo.today`, `.sw-confirm` and the phone `.ev-confirm`;
     - controls `.switch[aria-checked="true"]`;
     - filters `.chipRemove:hover, :focus-visible`;
     - the avatars: shell `.avatar`, admin `.avatar` and `.avatarXl` (solid navy initials, as in the samples).
   - **Navy marks and progress** (`--action`):
     - case `.railItem::before`;
     - rail `.eyebrow` and `.now::before`;
     - hearings `.today` (inset ring);
     - system `.fill`;
     - charts `.dot-busy`;
     - feedback `.meterFill`, `.step i` and `.seg-active`, with `.seg-waiting` stripes in `--action-soft`;
     - listSearch `.spinner`;
     - controls `.segmentOn` (text);
     - controls `.check input` and mapping `.slider` (`accent-color`).
   - **The side menu's current item and the parent on its path:** the `--nav-*` set (decision 9).

   **The 10% rule holds by construction:**
   - The orange button is the kit primary, and the existing "one primary" checks (uicheck `checks.ts` and
     `pages.test.tsx`) already fail a page with more than one visible primary outside a dialog. One orange button per
     view; a dialog's own primary is the only orange button while the dialog covers the page.
   - Row buttons are `secondary`, `ghost` or `link` (137, 9 and 32 uses) and become navy (decision 3). None is
     orange.
   - Orange is never a text colour except deep orange words (`--mark-text`), never a large ground (`--mark-soft` only on
     the one tile), never a status, and never a chart colour.

   Alternative: one orange accent everywhere (the portal would be about 40% orange: every link, selected item and
   progress bar).

3. **Ordinary buttons are navy.**
   - `secondary`: ground `--surface`, border `--border-strong`, text `--action`; on hover, ground `--slate-soft` and
     border `--action`.
   - `ghost`: text `--action`, hover ground `--slate-soft`.
   - `danger`: border `--red-line`, text `--red-text`, hover ground `--red-soft`.
   - `link`: `--link`.

   Border widths, heights and padding are unchanged. The samples also show a solid navy row button (Claim, Accept).
   The portal cannot tell those from other secondary buttons without a new variant and a choice made at every call
   site, so this row does not draw them. Open question 4 asks whether the owner wants that as a later row.
   Alternative: solid navy for every secondary button (137 heavy buttons; the calm 90% would be lost).

4. **Orange fills always carry navy text.** White on `#F28C28` is 2.45:1 and is never used. A source guard
   (decision 14) checks it in two ways:
   - every rule whose `background` is `var(--mark)` or `var(--mark-hover)` sets `color: var(--on-mark)`;
   - no rule sets `color: var(--mark)`. Orange words are `--mark-text`.

5. **Where orange stands alone on cream, it is deep orange.** WCAG 2.1 AA (portal-ui-redesign decision 20) asks 3:1
   for a mark that shows a state on its own (1.4.11). Bright orange on cream is 2.18:1 on the page and 2.38:1 on a
   card. These marks therefore use `--mark-text` `#B4470C` (4.85:1 on the page, 5.29:1 on a card, 5.46:1 on a white
   field):
   - the focus outline and focused field border;
   - the open tab's underline;
   - the bell dot;
   - the phone bottom bar's current item.

   Bright orange `#F28C28` is used for:
   - fills behind navy text (6.72:1);
   - markers on navy (6.72:1 on navy 900);
   - halos.

   The focus ring stays the 2 px outline plus the 4 px halo of decision 20, now orange. *Amends portal-ui-redesign
   decision 20 (colour only).* Open question 3 lets the owner keep the sample's bright underline instead.

### B. Status colours, the navy ground, the emblem

6. **Status colours keep their meanings and stay apart from orange.**
   - Urgent red: `--red` and `--red-text` are both `#B42318` (white on it 6.57:1), with `--red-soft` `#FBE7E4`.
   - Due soon moves from amber to ochre: `--ochre` `#7A5A00` on `--ochre-soft` `#F5ECCB` (5.39:1). Ochre is darker
     than orange, so it is not taken for it.
   - Done: `--green` `#0B6B3A` on `--green-soft` `#E2F0E5` (5.61:1).
   - The neutral badge: `--text-2` on the shade (5.99:1).

   Every current `--amber` and `--amber-soft` use (25 and 13, in 13 modules) becomes `--ochre` and `--ochre-soft`.
   That covers:
   - the hearing badge's soft band, warning and "differs" styles (`hearingDate.module.css`);
   - `badge-warning` and the warning notice;
   - `kpiSub-warning`;
   - the calendar's action-due dots;
   - the charts' warn tone;
   - the "changed" marks of mapping and audit;
   - the assistant's included-records and passage marks;
   - the case banner, the next-dates panel and the office picker mark;
   - the system card and data `.warnLine`.

   The meanings do not change, so neither do the next-hearing bands (next-hearing-highlight decisions 4 and 5).

7. **Literal colours become tokens** (29 in modules, 7 in `LinkGraph.tsx`, 2 in globals outside `:root`):
   - **Save bar** (`admin.module.css`):
     - ground `--panel-from`, text `--panel-strong`;
     - idle count: ground `--panel-raised`, text `--panel-strong`;
     - unsaved count: `--mark` with `--on-mark`;
     - ghost button text `--panel-text`.

     Its Save Changes button is the page's one primary, so it is orange on navy.
   - **Sign-in panel**: decision 8.
   - **White text** (`#fff`): `--on-action` on navy, `--on-mark` where the ground turns orange.
   - **Danger and banner borders**: `--red-line`; notice `--green-line`; warning notice `--ochre-line`.
   - **Switch knob**: `--field` with `--shadow-knob`.
   - **Skeleton**: `linear-gradient(90deg, var(--slate-soft) 25%, var(--surface-2) 50%, var(--slate-soft) 75%)`.
   - **Scrims** (overlays, shell drawer): `--scrim`.
   - **Bell pulse keyframes**: `--mark-glow` to `transparent`.
   - **Fallbacks**: `var(--accent, #1d4ed8)` becomes `var(--focus-line)`, and `var(--surface-2, #f8fafc)` becomes
     `var(--surface-2)`.
   - **`LinkGraph.tsx`**: the SVG attributes become classes in `case.module.css`. CSS variables are unreliable in SVG
     presentation attributes, and the CSP forbids inline style attributes.
     - edge `--text-3`, edge label `--text-2`;
     - root node fill `--panel-from`, its text `--panel-strong`;
     - a visible node: fill `--action-soft`, stroke `--action`, text `--text`;
     - a hidden node: fill `--slate-soft`, stroke `--border-strong`, text `--text-3`.

   After this row, no CSS module, no component and no part of `globals.css` outside `:root` names a colour literal
   (decision 14). Only `transparent`, `currentColor` and `inherit` are allowed.

8. **The sign-in panel is navy.**
   - The `.panel` ground is `linear-gradient(160deg, var(--panel-from), var(--panel-to))`, navy 900 to a deeper navy.
     The blue radial glow is removed (blue is no longer in the palette).
   - The dot grid stays, in `--panel-dots`.
   - Tiles: border `--panel-tile-line`, ground `--panel-tile`; the tile icon has ground `--panel-raised` and colour
     `--panel-text`, which keeps orange off the tiles.
   - The kicker "Government of Assam" is light orange `--panel-accent` (10.37:1), as in the sample.
   - Title `--panel-strong`, lead `--panel-text`, maker line `--panel-muted` (5.63:1).
   - The form side and page are the card cream `--surface`. Fields are white (`--field`). Sign In is the orange
     primary. Forgot Password is a `--link`. The current step is navy (`--action` with `--on-action`), not orange, so the
     page keeps one orange thing.
   - The same colours serve the code, reset and first-sign-in pages, and the phone layout where the panel is a header.

   *Amends portal-ui-redesign decision 26 (colour only).* Not adopted, because each adds or moves an element: the
   emblem moved onto the panel, the orange bar under the title, the form drawn as a bordered card.

9. **The side menu is navy on laptops and tablets; the emblem never sits on navy.**
   - `.sidebar` defines a local colour set (custom properties only):
     - `--nav-bg` `--panel-from`;
     - `--nav-text` `--panel-text`;
     - `--nav-strong` `--panel-strong`;
     - `--nav-muted` `--panel-muted`;
     - `--nav-hover` `--panel-hover`;
     - `--nav-current-bg` `--panel-raised`;
     - `--nav-current-text` `--panel-strong`;
     - `--nav-line` `--panel-line`;
     - `--nav-mark` `--mark`;
     - `--nav-focus` `--mark`.
   - The menu's rules read only that set:
     - the sidebar ground and right border;
     - group labels;
     - links, hover and current;
     - the 3 px current bar;
     - the parent on the path (`.onPath`);
     - chevrons (`--nav-strong` on the current row, where `--panel-muted` would be 3.89:1);
     - the children's guide line;
     - the memberships foot (border, text, its text button in `--nav-strong`);
     - `.sidebar :focus-visible`, whose outline colour is `--nav-focus`. Deep orange on navy is only 3.02:1, so on navy
       the focus ring is bright orange.
   - Counts stay orange with navy text in both sets.
   - **Phones (< 820 px): the drawer keeps the cream set.** The media query re-points the same properties to
     `--surface`, `--text-2`, `--text`, `--text-3`, `--slate-soft`, `--action-soft`, `--action`, `--border`,
     `--mark-text` and `--focus-line`. Why:
     - the drawer's top block holds the official emblem, a near-black and maroon image;
     - on navy the emblem would vanish;
     - decision 21 keeps the files unaltered, so neither a recoloured file nor a CSS filter is acceptable;
     - a cream band behind only the brand would need padding the block does not have (a layout change).
   - The header stays the card cream with the emblem on it, at every width. The bottom bar is cream (decision 2).

   Open question 1 asks the owner to confirm the cream drawer.
   Alternatives:
   - a navy drawer with the emblem on navy (the emblem vanishes);
   - the emblem filtered to white (alters the official emblem).

### C. Data graphics, the headline tile, motion, dark mode

10. **The one headline tile.** The decisions log puts orange on "the single most important headline tile".
    - `Kpi` gains an optional `emphasis` prop. It adds the class `.kpiMark`: ground `--mark-soft`, border `--mark-line`
      (the same 1 px), label `--mark-text`. That is a colour-only rule.
    - It is used once: on the personal dashboard's **Files With Me** tile (`HeadlineKpis`, `headline.files_with_me`),
      and only while that count is above 0. This is the sample's highlighted tile, and a tile is orange only when there
      is something to do.
    - No department or State tile is emphasised.

    Open question 2 asks the owner to confirm the tile.

11. **Data graphics keep their colours' meanings and take the new values through the tokens.**
    - `SparkBars`: ok green, failed red, empty `--border-strong`.
    - `RateRing` tones: ok green, warn ochre, down red, unknown `--text-3`, track the shade.
    - `StatusDot`: the same tones; busy is navy (`--action`).
    - Progress bars, meters, segment bars and step dots: navy fills on the shade.
    - `LinkGraph`: decision 7.

    Orange is never a data colour, because a bar in orange would read as "act now". Numbers and words stay beside every
    colour, as today (decision 20). There is no other chart in the portal.

12. **Motion: the portal keeps its own transitions and recolours them. No new animation in this row.** Every
    transition in the sample that the portal can take without moving a box is already in the portal under decision 13,
    on the existing tokens and reduced-motion fallback.

    | Sample transition | In the portal | This row |
    |---|---|---|
    | Entrance rise | page content `aslms-fade-in` (6 px, `--slow`), sign-in `auth-rise` | unchanged; the sample's 14–16 px rise and staggered delays are not adopted (slower pages; motion the owner has not approved) |
    | Sliding tab underline | kit `Tabs` `.ink` (`--med`) | turns deep orange; the Case Claim, System Health and remarks tabs keep their per-tab underline, recoloured (making them slide needs the kit's ink element: a later row if wanted) |
    | Sliding view switch (pill) | segmented control, no pill | not adopted: a new moving element |
    | Hover lift | buttons 1 px, KPI tiles 2 px (`transform` only) | unchanged; the orange primary's hover shadow is `--mark-glow` |
    | Confirmation toast | none in the portal | not adopted: a new component and behaviour |
    | Pulsing unread dot | the bell dot `pulse` (2 s) | turns orange |
    | Menu hover slide (`padding-left` 30 → 36 px) | none | **rejected**: changes padding |
    | Claimed pop, check draw, row slide-out, pulsing urgent badge | none | not adopted: new behaviour; an urgent badge stays still |

    `motion.ts`, the duration tokens and the reduced-motion block do not change. Alternatives: adopt the toast and
    sliding pill now (both add elements; they break the colours-only rule).

13. **Dark mode is out of scope.** The owner did not ask for it. The structure stays ready for it: every colour is a
    token, and the guard of decision 14 keeps it so. A dark theme would be a new row with its own palette approval.

### D. Proof, the row 230 hook, the reference files

14. **Tests prove the colours, the contrast and that nothing moved** (the full list is under Tests):
    - **The token test** pins every new value, checks every text pair at 4.5:1 and every stand-alone mark at 3:1, and
      fails a retired name.
    - **A colour-literal guard** covers every CSS module, `globals.css` outside `:root`, and every `.ts`/`.tsx` source
      apart from tests. It generalises today's `hearingDate.module.css` check.
    - **The orange guards** of decision 4.
    - **The side menu's two colour sets** are checked for contrast.
    - **A layout signature test**, `components/ui/layoutSignature.test.ts`, with its snapshot `layout-signature.json`.
      For every `*.module.css` and for `globals.css` it lists each selector with its declarations normalised:
      - comments dropped;
      - custom-property declarations (`--*`) dropped;
      - declarations dropped whose property only paints and never sizes: `color`, `background-color`,
        `background-image`, `border-*-color`, `border-color`, `outline-color`, `box-shadow`, `fill`, `stroke`,
        `accent-color`, `caret-color`, `text-decoration-color`;
      - in every other declaration, each colour value replaced with `<c>`: `var(--…)` naming a colour token, a hex,
        `rgb()`/`rgba()`, a named colour, or a gradient. So `border: 1px solid var(--accent)` stays
        `border: 1px solid <c>`, and `background:` shorthands stay as `<c>`;
      - a rule left with no declarations dropped. A new colour-only rule (`.kpiMark`, `.sidebar :focus-visible`,
        the `--nav-*` sets) therefore leaves no trace.

      The developer's **first commit** on the branch adds the test and generates the snapshot from `main`'s CSS, before
      any colour changes. After that the snapshot never changes on the branch, and the reviewer checks
      `git log -p -- layout-signature.json` shows only that commit. Font weight, padding, margins, sizes, gaps, radii,
      positions, transitions and animations are all in the signature, so any of them changing fails the test.
    - **A screen box comparison** with uicheck (decision 16).

15. **The hook for row 230.** The review of every portal screen (row 230) reports findings for the owner's approval
    before this row is built. When the developer starts:
    - every approved finding that is about colour is folded into this row. Examples: "colours without a fixed meaning",
      or a badge tone that means nothing to a reader. The architect appends them to this note as an addendum under
      Decisions, "Row 230 colour findings", with the token each takes, and the owner approves the addendum with the
      row;
    - every approved finding that changes layout, wording or data is its own build row and merges **before** this one.
    - The box baseline of decision 16 is `main` **after** rows 228 and 230's fixes are merged, so this row's comparison
      sees only colour.

    Row 228's navy recommendation badges (strong solid, possible outlined) use `--action`, `--on-action` and a 1.5 px
    `--action` outline as row 228 builds them. This row only checks that they read the new tokens.

16. **The screen box comparison** (uicheck, private network, runbook section 16). uicheck gains an opt-in
    `UICHECK_BOXES=1`:
    - each route and interaction state, at each width, also writes `boxes/<slug>-<width>.json`;
    - each file holds every rendered element's stable path (tag and `nth-of-type` from `body`, which a class change does
      not alter) and its `getBoundingClientRect()` rounded to 0.5 px, plus the document's scroll width and height;
    - it is collected after `document.fonts.ready`, under the existing reduced motion;
    - the page clock is pinned with Playwright's `page.clock.setFixedTime` to one IST instant, so greetings, "Today"
      bands and relative dates render the same text in both runs.

    A new `e2e/boxdiff.ts` (script `npm run boxdiff -- <before> <after>` in the uicheck image) compares two run
    folders. It reports:
    - every element whose box moved or resized by more than 0.5 px;
    - every element present in one run only;
    - every page whose size differs;
    - and exits non-zero on any of them.

    The integrator runs it in three steps:
    1. **Calibration:** two runs of a `main` image, which must give **0 differences**. This proves the method is stable.
    2. **The real comparison:** the `main` image against the branch image, which must give **0 moved, 0 missing, 0
       extra, 0 page-size changes**.
    3. **The ordinary uicheck:** it must have no findings.

    The screenshots of both runs go to the owner for the colour check. Alternative: pixel diffs of screenshots
    (every pixel changes in a recolour, so they prove nothing about layout).

17. **The approved samples become the repository's visual reference.** The developer copies `Main.dc.html`,
    `Dashboard.dc.html`, `CaseClaim.dc.html` and `SignIn.dc.html` unchanged into `docs/design/ui/navy-cream/`, with a
    `README.md` of three lines saying three things: they are the owner-approved colour reference of 10 Nov 2026; they
    need the design tool's `support.js` to render, and their inline styles are readable as they are; their geometry is
    not the portal's. Today they exist only in a temporary folder.

## Data

None. No table, column, reference code or migration.

## Services

None. No backend change. The e-mail templates and `services/report_export.py` (Excel and PDF) keep their neutral
colours.

## API

None. No endpoint is added or changed, so no `Permission` applies.

## Jobs

None.

## Tests

Vitest, `frontend/src`:

1. `components/ui/tokens.test.ts`:
   - **carry the navy and cream values**: every colour token of decision 1 pinned. The spacing, type, motion, size and
     reduced-motion assertions stay as they are.
   - **the navy and cream retirements**: a second list, `RETIRED_NAVY_CREAM` = `--accent`, `--accent-hover`,
     `--accent-soft`, `--accent-ring`, `--amber`, `--amber-soft`. Each is undefined in `:root` and unused in every
     `.css`, `.ts` and `.tsx` source, by the same `aliasUses` matcher.
   - **text pairs at 4.5:1** (decision 1; figures computed for this note):
     - `--text` on `--bg` 14.16, `--surface` 15.44, `--surface-2` 13.70, `--field` 15.95, `--slate-soft` 12.85;
     - `--text-2` on `--bg` 6.60, `--surface` 7.20, `--surface-2` 6.39, `--slate-soft` 5.99, `--mark-soft` 6.29;
     - `--text-3` on `--bg` 5.15, `--surface` 5.62, `--surface-2` 4.99, `--slate-soft` 4.68, `--field` 5.80,
       `--ochre-soft` 4.90;
     - `--heading` on `--bg` 14.64, `--surface` 15.97, `--action-soft` 13.42;
     - `--action` on `--surface` 11.04, `--bg` 10.12, `--slate-soft` 9.19, `--action-soft` 9.28, `--field` 11.40;
     - `--link` on `--surface` 6.60, `--bg` 6.05, `--surface-2` 5.85, `--action-soft` 5.55;
     - `--on-action` on `--action` 11.40, `--action-hover` 8.91;
     - `--on-mark` on `--mark` 6.72, `--mark-hover` 7.52;
     - `--mark-text` on `--surface` 5.29, `--bg` 4.85, `--mark-soft` 4.61, `--surface-2` 4.69, `--field` 5.46;
     - `--on-red` on `--red` 6.57;
     - `--red-text` on `--red-soft` 5.53, `--surface` 6.37, `--bg` 5.84, `--surface-2` 5.65, `--slate-soft` 5.30;
     - `--ochre` on `--ochre-soft` 5.39, `--slate-soft` 5.14, `--surface` 6.18, `--surface-2` 5.48;
     - `--green` on `--green-soft` 5.61, `--surface` 6.40, `--slate-soft` 5.32;
     - the navy ground: `--panel-text` on `--panel-from` 10.95, `--panel-to` 11.82, `--panel-raised` 7.57,
       `--panel-hover` 9.28; `--panel-strong` on `--panel-from` 16.49, `--panel-raised` 11.40, `--panel-hover` 13.98;
       `--panel-muted` on `--panel-from` 5.63, `--panel-to` 6.08, `--panel-hover` 4.77; `--panel-accent` on
       `--panel-from` 10.37, `--panel-to` 11.20.
   - **stand-alone marks at 3:1** (WCAG 1.4.11, decision 5):
     - `--focus-line` on `--bg` 4.85, `--surface` 5.29, `--surface-2` 4.69, `--field` 5.46;
     - `--mark` on `--panel-from` 6.72 (the menu's current bar and focus);
     - `--mark` on `--panel-raised` 4.65 (a count on the current item).
   - **white on orange fails**: `contrast("#ffffff", --mark) < 4.5`, pinned so the rule's reason stays visible. The old
     "white text on the accent" case is replaced by the `--on-action` and `--on-mark` pairs above.
   - **the next hearing badge's colours**: the existing block with `--amber`/`--amber-soft` replaced by
     `--ochre`/`--ochre-soft`.
   - **no colour literal in any CSS module**: every `*.module.css` has no hex value and no `rgb`/`hsl`/`hwb`/`lab`/
     `lch`/`oklab`/`oklch` function. In colour properties no named colour is allowed other than `transparent`,
     `currentColor` and `inherit`. This replaces and widens the `hearingDate.module.css`-only test.
   - **no colour literal in `globals.css` outside `:root`**.
   - **no hex colour in any `.ts`/`.tsx` source** outside tests.
   - **orange fills carry navy text**: every rule in every module and in globals with `background: var(--mark)` or
     `var(--mark-hover)` also sets `color: var(--on-mark)`. No rule sets `color: var(--mark)`. A self-test shows the
     check catches a white-on-orange rule.
   - **the side menu's colour sets**: both `.sidebar` sets in `shell.module.css` (laptop and phone media query) are
     parsed. In each set, nav-text on nav-bg, nav-strong on nav-hover, nav-current-text on nav-current-bg and nav-muted
     on nav-bg are at least 4.5:1, and nav-mark and nav-focus on nav-bg are at least 3:1.
2. `components/ui/layoutSignature.test.ts` + `layout-signature.json` (decision 14):
   - **the layout signature equals main's**;
   - a self-test: the normaliser keeps `padding: 10px`, `font-weight: 600`, `border: 2px solid <c>` and
     `transform: translateY(-1px)`, drops `color` and `box-shadow`, and turns `border: 1px solid var(--accent)` and
     `border: 1px solid #fff` into the same entry. A changed width or weight fails.
3. Kit and screens:
   - `Kpi` with `emphasis` carries `.kpiMark`; without it, it does not.
   - `HeadlineKpis` emphasises Files With Me only when `files_with_me.total > 0`, and never another tile (dashboard
     test).
   - `LinkGraph` renders no `fill` or `stroke` attribute holding a colour; root, visible and hidden nodes carry their
     classes.
   - `pages.test.tsx` "at most one primary" stays green (the orange button count).

uicheck, `frontend/e2e`:

4. `uicheck-self.spec.ts`:
   - **the box collector**: on a synthetic page it records each element's path and box, and ignores a class change;
   - **boxdiff**: identical runs give 0 differences; a 1 px shift, a missing element and a changed page height are each
     reported, with a non-zero exit.
5. `uicheck.spec.ts` with `UICHECK_BOXES` unset behaves exactly as today. The clock is pinned only in boxes mode.

## Verification

The integrator, from a clean worktree, after rows 228 and 230's fixes are on `main`:

1. `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`: all green. The layout signature test is green
   with the snapshot from the branch's first commit. `git log -p -- frontend/src/components/ui/layout-signature.json`
   shows that one commit only.
2. Backend untouched: `git diff --stat main -- backend` is empty, so `ruff check` and `pytest -q` are unchanged; run
   them as usual.
3. The box comparison on a private network (runbook section 16; never through Compose on the shared stack):
   1. Build `tmpA-web` from `main` and `tmpB-web` from the branch, plus `tmp-uicheck` from the branch's `e2e/`.
   2. Run uicheck with `UICHECK_BOXES=1` twice against `tmpA-web` (`/out/a1`, `/out/a2`). Then
      `npm run boxdiff -- /out/a1 /out/a2` must give **0 differences** (calibration).
   3. Run it once against `tmpB-web` (`/out/b`). Then `npm run boxdiff -- /out/a1 /out/b` must give **0 moved, 0
      missing, 0 extra, 0 page-size changes** across every route, state and width.
   4. The `/out/b` run itself has **0 findings**, including "one primary" (at most one orange button per page).
   5. Remove the containers, network and images.
4. Hand the owner the `/out/a1` and `/out/b` screenshots side by side for the colour check: Dashboard, Case Claim,
   sign-in, code page, case page, Case Inbox, My Calendar, Alerts, Administration user type (the Save bar),
   Data Collection, System Health (charts), Reports, at 375, 768 and 1280 px. The owner's browser check of the same
   screens follows the deploy.
5. Deploy: frontend only. Build `web` from a clean worktree of `main` and recreate it with
   `--no-deps --force-recreate`. Check the web build ID. No migration and no `init`.

## Open questions

The note's decisions stand on their recommended answers; each question is for the owner to confirm or change at
approval.

1. **The phone drawer:** keep it cream with the navy current item and orange counts (recommended, decision 9)? The
   official emblem in its top block is dark and would vanish on navy, and its file may not be altered.
2. **The one orange headline tile:** Files With Me, orange only while above 0, as in the sample (recommended, decision
   10)? Or Recommended to Claim, or no tile.
3. **Thin orange marks on cream:** deep orange `#B4470C` for the tab underline, bell dot, phone current item and focus
   line, to meet WCAG's 3:1 (recommended, decision 5)? Or the sample's bright `#F28C28` underline, which is 2.2:1 on
   cream.
4. **Solid navy row buttons** (the sample's Claim and Accept): leave them out here, with every secondary button as navy
   text on the card (recommended, decision 3)? Or open a later row that adds a solid navy variant and picks its call
   sites.

## Owner's answers (10 Nov 2026)

Questions 1 to 4 answered with the recommended answers: the phone drawer stays cream; Files With Me is the one
orange headline tile, orange only while above 0; thin marks on cream use deep orange `#B4470C`; no solid navy row
button variant in this row. **Motion: yes** — the sample's toast, sliding view-switch pill and menu hover slide are
left out of this row (it moves no box) and built afterwards as row 235 `portal-motion`, with its own design.

**Addendum from the review of row 230 (approved by the owner).** This row also carries the colour-meaning findings:
K7 notice tones (`info`, `success`, `warning`: one neutral info tone in place of the success green used for most
notices), A1 alert tone by meaning in place of severity on the Alerts page and the case Alerts tab (with row 228
point 5), and C4 one recommendation tone on every screen (strong solid navy, possible outlined). Layout findings land
first in rows 231 to 234; the box baseline is `main` after them.
