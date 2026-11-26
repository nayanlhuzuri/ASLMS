/**
 * The public home page with the sign-in form on it (design home-page, row 274, decisions 4 and 7 to 10; refined by
 * design home-page-refinements, row 281), at `/login`. There is no top bar: the hero's own lockup (the gold emblem,
 * "Government of Assam" and the full name) is the page's identity and its `h1` the heading.
 *
 * The hero is the whole first screen (`min-height: 100svh`): the lockup, the heading, the sign-in card, the lead and
 * the access line, centred a little above the middle and growing with the screen's height within fixed limits, and at
 * its foot the quiet "See What You Work With" link to the sample pictures. Below the first screen, reached by
 * scrolling: the two sample pictures (`HomeSamples`), the strip of what ASLMS does, and the footer. The card's submit is
 * the page's one primary action and the card is the only sign-in on the page.
 *
 * From 1024 px the hero has two columns with the card on the right; below that the card comes right after the
 * heading. The footer sits outside `main`; the bands inside it reach the screen's edges by a painted layer only, so
 * nothing leaves `main`'s content box (uicheck's gutter rule). ASLMS is described in general words only, the pictures
 * show plainly marked sample data, and the page makes no request before sign-in.
 */
import { Suspense } from "react";

import { GoldEmblem } from "@/components/auth/GoldEmblem";
import { CalendarIcon, ClaimIcon, FilesIcon, InboxIcon } from "@/components/shell/icons";
import { T } from "@/lib/messages";

import s from "./home.module.css";
import { HomeSamples } from "./HomeSamples";
import { SignInCard } from "./SignInCard";

/** The id of the sample pictures' section, the first screen's link target. */
export const SAMPLES_ID = "samples";

/** The strip: the frame's three tiles as items 1, 2 and 4, so the two never drift apart, and the claim rule as item 3. */
function stripItems() {
  const [hearing, orders, custody] = T.auth.frame.tiles;
  return [
    { ...hearing!, Icon: CalendarIcon },
    { ...orders!, Icon: FilesIcon },
    { ...T.home.strip.claim, Icon: ClaimIcon },
    { ...custody!, Icon: InboxIcon },
  ];
}

function DownIcon() {
  return (
    <svg className={s.cueIcon} aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function HomePage() {
  const H = T.home;
  return (
    <div className={s.page}>
      <main id="main" className={s.main}>
        <section className={`${s.band} ${s.hero}`} aria-labelledby="home-heading" data-first-screen="">
          <div className={s.heroGrid}>
            <div className={s.heroTop}>
              <GoldEmblem />
              <div className={s.heroHead}>
                <p className={s.kicker}>{T.owner}</p>
                <p className={s.big}>{T.portalLong}</p>
              </div>
            </div>
            <h1 id="home-heading" className={s.heading}>
              {H.heading}
            </h1>
            <div className={s.cardCell}>
              <Suspense>
                <SignInCard />
              </Suspense>
            </div>
            <div className={s.heroText}>
              <p className={s.lead}>{H.lead}</p>
              <p className={s.access}>{H.access}</p>
            </div>
          </div>
          <a className={s.cue} href={`#${SAMPLES_ID}`}>
            <span>{H.cue}</span>
            <DownIcon />
          </a>
        </section>
        <section id={SAMPLES_ID} className={`${s.band} ${s.samples}`} aria-labelledby="home-samples">
          <div className={s.inner}>
            <h2 id="home-samples">{H.samples.heading}</h2>
            <p className={s.intro}>{H.samples.intro}</p>
            <HomeSamples />
          </div>
        </section>
        <section className={`${s.band} ${s.strip}`} aria-labelledby="home-strip">
          <div className={s.inner}>
            <h2 id="home-strip">{H.strip.heading}</h2>
            <ul className={s.items}>
              {stripItems().map(({ title, text, Icon }) => (
                <li key={title} className={s.item}>
                  <span className={s.itemIcon}>
                    <Icon />
                  </span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>
      <footer className={s.foot}>
        <div className={s.footInner}>
          <p>{H.footName}</p>
          <p>{T.auth.frame.foot}</p>
        </div>
      </footer>
    </div>
  );
}
