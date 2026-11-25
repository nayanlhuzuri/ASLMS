/**
 * The public home page with the sign-in form on it (design home-page, row 274, decisions 4 and 7 to 10), at `/login`.
 * Top to bottom: the navy top bar (the name, and a Sign In link), the navy hero (the gold emblem beside "Government of
 * Assam" and the full name, the heading, the sign-in card, the lead and the access line), the sample picture of the
 * app, the strip of what ASLMS does, the closing band with a second Sign In link, and the footer.
 *
 * From 1024 px the hero has two columns with the card on the right, in the first view on a laptop; below that the card
 * comes right after the heading. The top bar and the footer sit outside `main`; the bands inside it reach the screen's
 * edges by a painted layer only, so nothing leaves `main`'s content box (uicheck's gutter rule). The submit is the one
 * primary action: both Sign In links are secondary. ASLMS is described in general words only: no case number, count,
 * department or court name, and the page makes no request before sign-in. Only the card and the emblem are client
 * components.
 */
import { Suspense } from "react";

import { GoldEmblem } from "@/components/auth/GoldEmblem";
import { CalendarIcon, ClaimIcon, FilesIcon, InboxIcon } from "@/components/shell/icons";
import { T } from "@/lib/messages";

import s from "./home.module.css";
import { HomePreview } from "./HomePreview";
import { SignInCard, SignInLink } from "./SignInCard";

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

export function HomePage() {
  const H = T.home;
  return (
    <div className={s.page}>
      <header className={s.top}>
        <div className={s.topInner}>
          <p className={s.name}>
            <span className={s.nameShort}>{T.portal}</span>
            <span className={s.nameOwner}>{T.owner}</span>
          </p>
          <SignInLink />
        </div>
      </header>
      <main id="main" className={s.main}>
        <section className={`${s.band} ${s.hero}`} aria-labelledby="home-heading">
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
        </section>
        <section className={s.band} aria-labelledby="home-preview">
          <h2 id="home-preview">{H.preview.heading}</h2>
          <p className={s.intro}>{H.preview.intro}</p>
          <HomePreview />
        </section>
        <section className={`${s.band} ${s.strip}`} aria-labelledby="home-strip">
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
        </section>
        <section className={`${s.band} ${s.closing}`} aria-labelledby="home-closing">
          <h2 id="home-closing">{H.closing.heading}</h2>
          <p>{H.closing.line}</p>
          <SignInLink />
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
