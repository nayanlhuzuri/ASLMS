/**
 * The frame of the public pages (design portal-ui-redesign, decision 26 as amended by the owner on 20 Oct 2026:
 * template A, the split panel; visual reference docs/design/ui/aslms-sign-in-templates.html, tab A). On laptops the
 * left half is the deep-blue panel with "Government of Assam", the full name, one line on what the portal is for and
 * three benefit tiles; the right half is white, with the official emblem (`BrandLockup`), the page's form and the
 * foot line. On phones the panel shrinks to a header above the form and the tiles are hidden. The sign-in, code,
 * reset and first-sign-in pages share it; only the right half changes. Every text comes from `messages.ts`, and the
 * Gauhati High Court is not named here.
 */
import type { ReactNode } from "react";

import { BellIcon, CalendarIcon, FilesIcon } from "@/components/shell/icons";
import { BrandLockup } from "@/components/shell/Brand";
import { T } from "@/lib/messages";

import s from "./auth.module.css";

const TILE_ICONS = [CalendarIcon, FilesIcon, BellIcon];

export function AuthFrame({ children, wide }: { children: ReactNode; wide?: boolean }) {
  // the brand panel bleeds to the screen's edges like a banner, so it sits outside `main`; `main` is the form's half,
  // which keeps the page gutter (design data-collection-redesign, decision 12)
  return (
    <div className={s.page}>
      <section className={s.panel} aria-label={T.auth.frame.label}>
        <div>
          <p className={s.kicker}>{T.owner}</p>
          <p className={s.big}>{T.portalLong}</p>
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
        <div className={s.brandRow} data-testid="auth-brand">
          <BrandLockup height={64} className={s.lockup} />
          <span>
            <span className={s.gov}>{T.owner}</span>
            <span className={s.name}>{T.portal}</span>
          </span>
        </div>
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
