/**
 * The frame of the public pages (design portal-ui-redesign, decision 26 as amended by the owner on 20 Oct 2026:
 * template A, the split panel; amended again by design signin-gold-emblem, row 249, visual reference
 * docs/design/ui/aslms-login-emblem-mock-v2.html). On laptops the left half is the navy panel: at its top the gold
 * Lion Capital (`GoldEmblem`) beside "Government of Assam" and the full name behind a thin gold divider, then one line
 * on what the portal is for and three benefit tiles; the right half is cream, with the page's form and the foot line
 * (the brand row that stood above the form is gone, so the emblem appears once). On phones the panel shrinks to a
 * header above the form, with a small emblem beside the title, and the tiles are hidden. The sign-in, code, reset and
 * first-sign-in pages share it; only the right half changes. Every text comes from `messages.ts`, and the Gauhati High
 * Court is not named here. The two Noto fonts of the emblem's lines are imported here, so only the public and
 * first-sign-in routes load them (decision 15).
 */
import "@fontsource/noto-serif-bengali/bengali-600.css";
import "@fontsource/noto-serif-devanagari/devanagari-500.css";

import type { ReactNode } from "react";

import { BellIcon, CalendarIcon, FilesIcon } from "@/components/shell/icons";
import { T } from "@/lib/messages";

import s from "./auth.module.css";
import { GoldEmblem } from "./GoldEmblem";

const TILE_ICONS = [CalendarIcon, FilesIcon, BellIcon];

export function AuthFrame({ children, wide }: { children: ReactNode; wide?: boolean }) {
  // the brand panel bleeds to the screen's edges like a banner, so it sits outside `main`; `main` is the form's half,
  // which keeps the page gutter (design data-collection-redesign, decision 12)
  return (
    <div className={s.page}>
      <section className={s.panel} aria-label={T.auth.frame.label}>
        <div>
          <div className={s.panelTop}>
            <GoldEmblem />
            <div className={s.panelHead}>
              <p className={s.kicker}>{T.owner}</p>
              <p className={s.big}>{T.portalLong}</p>
            </div>
          </div>
          <p className={s.lead}>{T.auth.frame.lead}</p>
          <ul className={s.tiles}>
            {T.auth.frame.tiles.map((tile, i) => {
              const Icon = TILE_ICONS[i] ?? CalendarIcon;
              return (
                <li key={tile.title} className={s.tile}>
                  <span className={s.tileIcon}>
                    <Icon />
                  </span>
                  <span>
                    <strong>{tile.title}</strong>
                    <span>{tile.text}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <p className={s.maker}>{T.auth.frame.maker}</p>
      </section>
      <main className={s.side} id="main">
        <div className={wide ? `${s.body} ${s.wide}` : s.body}>{children}</div>
        <p className={s.foot}>{T.auth.frame.foot}</p>
      </main>
    </div>
  );
}

/** The two-step indicator of the sign-in ("Password, then a code sent to your e-mail"), with the current step. */
export function SignInSteps({ step }: { step: 1 | 2 }) {
  return (
    <p className={s.steps}>
      <span className="visually-hidden">{T.auth.stepOf(step, 2)}. </span>
      <span className={step === 1 ? `${s.step} ${s.stepOn}` : s.step} aria-hidden="true">
        1
      </span>
      <span className={s.stepBar} aria-hidden="true" />
      <span className={step === 2 ? `${s.step} ${s.stepOn}` : s.step} aria-hidden="true">
        2
      </span>
      <span className={s.stepText}>{T.auth.steps}</span>
    </p>
  );
}
